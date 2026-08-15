# Hog Contract Finishing API — Product Requirements Document

## 1. Introduction

Contract finishing arrangements put an integrator's pigs and feed into barns owned and daily-operated by independent growers, who are paid per head under a finishing contract that carries a performance bonus. Coordinating that relationship at scale is operationally unforgiving: barn space is finite and booked in half-open occupancy windows, feed arrives in phase-specific diets against a lifetime per-head budget, every truck that approaches a barn must carry a fresh, verified wash, and the final settlement blends base pay, a feed-conversion and growth-rate bonus, and negligence deductions into one auditable number. This document specifies an API that acts as the system of record for those flows — pig placement scheduling and barn space matching, feed ordering and phase-diet delivery, mortality and cull reporting, packer slot booking and load dispatch, truck and barn wash governance, close-out settlement and payment, manure management and land application, and the owner–grower split of barn maintenance costs.

The platform serves six operator roles, from the integrator's administrators and field technicians to growers, feed mills, live-haul coordinators, and environmental managers, and it enforces segregation of duties wherever money or compliance attestation changes hands. Wherever two clients could build competing decisions on the same shared resource — a barn's booking book or a packer slot's reservation book — the API serializes them through explicit optimistic-concurrency checks. All temporal rules in this document are evaluated against a server-maintained logical clock, so every workflow in this document is reproducible under test.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and boilerplate that apply to every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. A request missing either header, or carrying an empty value for either, is rejected with `ERR_UNAUTHENTICATED`. The system recognizes exactly six roles, spelled precisely as follows: `IntegratorAdmin`, `FieldTech`, `Grower`, `FeedMill`, `TransportCoordinator`, and `EnvironmentalManager`. Each endpoint declares the roles permitted to call it; a caller whose role is not on that list is rejected with `ERR_FORBIDDEN_ROLE`.

Role identity resolves to persisted entities in two different ways, and the distinction matters for ownership checks. When `X-User-Role` is `Grower`, `X-User-ID` is the `id` of the acting `Grower` entity; ownership checks on any resource that traces back to a grower compare that resource's grower chain to `X-User-ID`. The grower chain resolves as follows: a pig group resolves through its contract's `grower_id`; a maintenance ticket resolves through its own `grower_id`; a settlement resolves through its contract's `grower_id`; and a barn resolves through the `ACTIVE` contract on the barn's site to that contract's `grower_id`. When `X-User-Role` is `IntegratorAdmin`, `FieldTech`, `FeedMill`, `TransportCoordinator`, or `EnvironmentalManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example as `recorded_by` on a wash, `quoted_by` on a ticket, or `approved_by` on a settlement — but does not compare it to any entity's `id`. A grower acting on a resource whose grower chain does not resolve to their own `X-User-ID` is rejected with `ERR_NOT_RESOURCE_OWNER`.

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

A request that matches no defined route, or that uses an unsupported method on a defined route, is rejected in this same envelope with `ERR_NOT_FOUND` (404), without any further validation.

---

### 2.3. Pagination

List endpoints paginate through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, accepts a minimum of 1, and is capped at a maximum of 100. The `offset` parameter skips a number of items from the front of the result set and defaults to 0. A `limit` or `offset` that is not an integer, a `limit` outside 1 through 100, or a negative `offset` fails with `ERR_MALFORMED_FIELD` (HTTP 400).

Unless otherwise specified, every list endpoint returns its resources sorted by creation timestamp in ascending order — oldest first; ties on the creation timestamp, common under a frozen logical clock, are broken by arrival order so the sort stays deterministic. When an endpoint accepts several filter parameters, supplying several at once combines them conjunctively — a resource must match every supplied filter to appear.

Paginated list responses carry four pagination fields in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Temporal Comparisons

All date and time rules in this document — placement windows, wash staleness, slot dates, application seasons, contract effectiveness — are evaluated against a server-maintained **logical clock**, never against wall-clock time. Before any operator sets it, the logical clock starts at exactly `2026-08-01T00:00:00Z`, and it never silently falls back to wall-clock time thereafter. An `IntegratorAdmin`-only test-driving capability advances or sets the clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`. Every server-generated timestamp — the envelope's `api_request_timestamp`, each resource's `created_at` and `updated_at`, and every event stamp this document describes — is read from the logical clock as well, never from wall-clock time.

Fields typed as dates (for example `placement_date`, `slot_date`, `report_date`) compare at calendar-day granularity; fields typed as instants (for example `washed_at`, `completed_at`, `applied_at`, `downtime_until`) compare at exact timestamp granularity. Where a rule says "on or after" or "at most", the boundary is inclusive; where a rule says "strictly greater", the boundary itself survives the gate.

### 2.5. Common Resource Properties and Mutation Semantics

Every primary resource carries a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording the last modification; it refreshes on every change to the resource.
- `version` (integer): a system-managed integer that starts at 1 on creation and increments by one on every mutation of the resource, including mutations caused by cascades originating on other resources.

One entity is deliberately lighter: a mortality report is an immutable, append-only event and carries only `id` and `created_at`. Both `updated_at` and `version` are absent from mortality reports, because a report is never modified after creation.

### 2.6. Request Validation Order

Every mutating request is validated against a fixed cascade of checks, and the first failing check determines the error returned — later checks are not evaluated for that request. The cascade runs in exactly this order:

1. **Authentication.** `X-User-ID` and `X-User-Role` must both be present and non-empty; otherwise the request fails with `ERR_UNAUTHENTICATED` (HTTP 401).
2. **Role authorization.** The presented role must appear in the endpoint's role list; otherwise `ERR_FORBIDDEN_ROLE` (HTTP 403). One role check is value-dependent: on ticket approval, a `FieldTech` may approve only when the quoted `cost_cents` is below 50,000 cents, and a `FieldTech` attempt at or above that amount fails here rather than later.
3. **Grower ownership.** On endpoints exercised in the `Grower` role, the acting grower's `X-User-ID` must match the resource's grower chain (§2.1); otherwise `ERR_NOT_RESOURCE_OWNER` (HTTP 403). Because ownership is evaluated against the loaded resource, the target's own existence is confirmed first: an identifier that does not resolve reports `ERR_NOT_FOUND` from step 4 before any ownership comparison is possible, and for a target that does resolve, ownership precedes the field-shape, state, temporal, quota, and fiscal checks below.
4. **Existence.** Path identifiers are validated first, in left-to-right order as they appear in the URL, and only then are foreign-key identifiers in the request body checked; the first missing reference fails with `ERR_NOT_FOUND` (HTTP 404). For the API's one nested collection — the mortality reports filed under a pig group — this means the group's existence is confirmed before anything about the report is examined.
5. **Optimistic concurrency.** Where an endpoint participates in optimistic concurrency control (§2.7), the supplied expected version must match the parent's current `version`; mismatches fail with `ERR_STALE_BARN_VERSION` or `ERR_STALE_SLOT_VERSION` (HTTP 412).
6. **Field shape.** Required fields must be present, enum values must be members of their declared sets, integers must honor their minimums (for example `quantity_lbs`, `capacity_head`, `head_count`, and `gallons` each at least 1, and `n_lbs` and `p_lbs` at least 0), and a slot's `max_weight_lbs` must be at least its `min_weight_lbs`; violations fail with `ERR_MALFORMED_FIELD` (HTTP 400). Field shape also covers lexical form: a date-typed field must be supplied as a strict `YYYY-MM-DD` string and an instant-typed field as an ISO 8601 datetime carrying a time component, and a request body that is not a JSON object fails here too — an absent or unparseable JSON body is treated as an empty object, so its required fields are simply reported missing.
7. **State validity.** The target resource must sit in a legal from-state for the requested transition; failures surface as `ERR_INVALID_STATE_TRANSITION` or one of its domain variants — `ERR_GROUP_NOT_ACTIVE`, `ERR_CONTRACT_NOT_ACTIVE`, `ERR_SITE_NOT_ACTIVE`, `ERR_GROWER_NOT_ACTIVE`, `ERR_BARN_NOT_PLACEABLE`, `ERR_PLAN_NOT_APPROVED`, `ERR_SLOT_NOT_OPEN`, or `ERR_TICKET_UNAPPROVED` (HTTP 409).
8. **Biosecurity.** Wash verification (`ERR_WASH_NOT_VERIFIED`), wash type (`ERR_WASH_TYPE_INSUFFICIENT`), and barn downtime (`ERR_BARN_DOWNTIME_ACTIVE`) are enforced (HTTP 409).
9. **Temporal rules.** Clock and calendar-window checks (HTTP 409): `ERR_PLACEMENT_DATE_PAST`, `ERR_TARGET_BEFORE_PLACEMENT`, `ERR_CONFIRM_TOO_EARLY`, `ERR_SLOT_DATE_PAST`, `ERR_DELIVERY_BEFORE_SLOT_DATE`, `ERR_REPORT_DATE_OUT_OF_RANGE`, `ERR_FEED_DATE_PAST`, `ERR_APPLICATION_OUTSIDE_WINDOW`, `ERR_WASH_STALE`, `ERR_CONTRACT_NOT_YET_EFFECTIVE`, `ERR_CONTRACT_EXPIRED`, and `ERR_CONTRACT_NOT_EXPIRED`.
10. **Cross-aggregate references.** A pig group's barn and contract must belong to the same site; otherwise `ERR_CROSS_SITE_REFERENCE` (HTTP 409).
11. **Uniqueness, overlap, and quota.** Duplicate identifiers (`ERR_DUPLICATE_GROWER_CODE`, `ERR_DUPLICATE_BARN_CODE`, `ERR_DUPLICATE_SLOT`), occupancy collisions (`ERR_OCCUPANCY_OVERLAP`), space limits (`ERR_SPACE_HEAD_EXCEEDED`, `ERR_FLOOR_SPACE_EXCEEDED`), phase matching (`ERR_PHASE_MISMATCH`), head reconciliation (`ERR_HEAD_COUNT_EXCEEDED`), zero-loss reports (`ERR_EMPTY_REPORT`), wash reuse (`ERR_WASH_ALREADY_USED`), plan-year and contract-site overlaps (`ERR_PLAN_YEAR_OVERLAP`, `ERR_CONTRACT_SITE_OVERLAP`), lifecycle blockers (`ERR_CONTRACT_HAS_ACTIVE_GROUPS`, `ERR_SETTLEMENTS_PENDING`, `ERR_SLOT_HAS_ACTIVE_LOADS`, `ERR_TICKETS_OPEN`, `ERR_BARN_OCCUPIED`), and the projected weight window (`ERR_WEIGHT_WINDOW_PROJECTED`) — all HTTP 409.
12. **Fiscal budgets, always last.** Feed budget (`ERR_FEED_BUDGET_EXCEEDED`), slot head capacity (`ERR_SLOT_CAPACITY_EXCEEDED`), nutrient budgets (`ERR_NUTRIENT_BUDGET_EXCEEDED`), lagoon drawdown (`ERR_LAGOON_INSUFFICIENT`), and lagoon start-versus-capacity (`ERR_LAGOON_OVER_CAPACITY`) — all HTTP 409.

Because the cascade is ordered, a request that would fail several checks always reports the earliest one, and readers can rely on that masking behavior. A dispatch request whose truck wash is both unverified and older than forty-eight hours is rejected with `ERR_WASH_NOT_VERIFIED`, never `ERR_WASH_STALE`, because biosecurity outranks temporal checks. A group-scheduling request carrying a stale barn version is rejected with `ERR_STALE_BARN_VERSION` even when its dates are also invalid, because concurrency is checked before field shape, state, and temporal rules. A feed order that both mismatches the group's current phase and exceeds the lifetime feed budget is rejected with `ERR_PHASE_MISMATCH`, because quota checks precede fiscal checks.

### 2.7. Optimistic Concurrency Control

Two write operations serialize their clients through the `version` counter of a parent resource, and both are non-optional checks.

Creating a pig group requires the request to carry `expected_barn_version`, holding the barn `version` the client last observed. If the barn's current `version` has advanced since that observation — because another writer scheduled a group against the same barn, or the barn changed state in between — the client's space and overlap decision was computed from a superseded view of the barn's booking book, and the create is rejected with `ERR_STALE_BARN_VERSION` (HTTP 412).

Creating a market load requires the request to carry `expected_slot_version`, holding the packer slot `version` the client last observed. If the slot's current `version` has advanced since that observation, the client's head-capacity decision was computed from a superseded view of the slot's reservation book, and the create is rejected with `ERR_STALE_SLOT_VERSION` (HTTP 412).

No other endpoint accepts an expected-version field; these two booking operations are the entire OCC surface. The expected-version field is required on both operations, but the staleness comparison itself applies only to an integer value: a create carrying no expected version, or a non-integer one, fails field shape with `ERR_MALFORMED_FIELD` (HTTP 400), while an integer that no longer matches the parent's current `version` fails with the 412 staleness error.

### 2.8. Cross-Entity Cascades and Atomic Consistency

Every mutation, together with all of its cascading side effects, commits atomically within its request — a client never observes a half-applied cascade. When an event on one resource mutates a parent or a peer — a delivered load advancing its group's aggregates, a group closing and flipping its barn, a booking recomputing its slot's `reserved_head`, a barn status change reshaping its site's `total_capacity_head` — each reconciled resource refreshes its own `updated_at` and increments its own `version` independently. For a pig group in particular, the `version` advances when a mortality report is filed against it, when one of its feed orders is delivered, and when one of its loads is delivered or rejected at the plant; creating, scheduling, or cancelling a feed order and booking or cancelling a market load touch only the order or load itself — and, for the booking flows, the slot — without advancing the group's `version`.

The server may also transition a resource automatically when the criteria for that transition are satisfied, without an explicit client request targeting that resource: a slot flips from `OPEN` to `FULL` the moment its reserved head reaches capacity and back from `FULL` to `OPEN` when a cancellation pulls the reserved head below capacity; a group closes itself when its last pig is accounted for; a barn moves itself from `OCCUPIED` to `WASH_REQUIRED` when its occupying group closes. These automatic transitions obey the same state machines as operator-driven ones.

### 2.9. Precision, Rounding, and Monetary Representation

Numbers in this system fall into three precision classes, and the class is part of the contract. Server-computed performance ratios and weights — `fcr`, `adg_lbs`, `mortality_pct`, `avg_weight_lbs`, and the projected weights used in booking validation — are rounded half-up to exactly two decimal places at computation time. Client-supplied performance numbers — `fcr_target`, `adg_target_lbs`, `mortality_threshold_pct`, `avg_start_weight_lbs`, and the placement-confirmation actuals — are stored and used exactly as supplied, without any pre-rounding. Money is represented as integer cents throughout (`base_pay_cents`, `bonus_cents`, `deductions_cents`, `adjustment_cents`, `total_pay_cents`, `cost_cents`, `owner_share_cents`, `grower_share_cents`, `balance_due_cents`, `lifetime_paid_cents`, `pending_deductions_cents`); where a computation produces fractional cents, the result is rounded half-up to a whole cent, and where a formula chains several factors, rounding happens once at the end of the chain, never on intermediate products. Counts and volumes — head counts, pounds of feed, gallons, square feet — are integers with no rounding.

One rounding order is pinned where two parties split a bill: on a maintenance ticket the owner's share is computed and rounded first, and the grower's share is the remainder (§3.7). The reverse order yields different cents on odd amounts and is not permitted.

### 2.10. Biosecurity and Wash Governance

Two wash disciplines govern every movement of pigs. Trucks that haul loads to the plant must be washed and disinfected before dispatch, and barns must be washed and disinfected between groups. Both disciplines share one governance shape: a wash is first **recorded** by the operator who performed it, then independently **verified** or **rejected** by an `IntegratorAdmin`. The operator who recorded a wash may never be the one who verifies or rejects it; the verifier's `X-User-ID` must differ from the recorder's, and a same-operator attempt is rejected with `ERR_SEGREGATION_OF_DUTIES`.

Only a verified wash of type `FULL_DISINFECT` is biosecure enough to back a pig movement — a `WASH_ONLY` wash never suffices, and attempts to rely on one are rejected with `ERR_WASH_TYPE_INSUFFICIENT`. A truck wash additionally expires: dispatch is permitted within forty-eight hours of the wash, with the exact forty-eight-hour mark still valid. A barn that has passed verification enters a seventy-two-hour downtime before it can house pigs again. The detailed workflows live in §3.5 and §3.6.

### 2.11. Segregation of Duties and Resource Ownership

Beyond the wash discipline, segregation of duties applies wherever one operator's attestation would rubber-stamp their own work. Three pairings are enforced with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403): the operator who **quotes** a maintenance ticket may not **approve** it; the administrator who **approves** a settlement may not **pay** it; and the operator who **records** a truck or barn wash may not **verify** or **reject** it. In each case the check compares `X-User-ID` values — the second actor must be a different identity than the first. Within the §2.6 cascade, each segregation check is evaluated immediately after state validity: a same-identity attempt on a resource sitting in an illegal from-state reports the state error, never the segregation error.

Resource ownership binds the `Grower` role to its own assets. A grower files mortality reports against their own groups, records washes on their own barns, opens and cancels maintenance tickets on their own barns, and disputes their own settlements; the ownership chain for each of these is defined in §2.1, and violations are rejected with `ERR_NOT_RESOURCE_OWNER`. The same check also guards the single-resource read of a pig group, a barn, a settlement, or a maintenance ticket, the mortality-report listing under a group, the settlement preview, and the opening of a maintenance ticket. List endpoints and all other reads are not ownership-scoped: any `Grower` caller may read them, including records belonging to other growers.

## 3. Business Logic & Workflows

### 3.1. Standing Up the Finishing Relationship: Sites, Growers, and Contracts

An `IntegratorAdmin` begins by registering each finishing **site** with a display `name`, a `state_code` string (by convention a two-letter code), and a `county`. A new site starts life `ACTIVE`, and its `site_status` can later move `ACTIVE` → `SUSPENDED` when the integrator suspends it and `SUSPENDED` → `ACTIVE` when it is reinstated. Suspending a site has teeth: while a site is `SUSPENDED`, no contract may be activated against it and no new pig group may be scheduled onto its barns. A site may also be decommissioned, moving `ACTIVE` → `DECOMMISSIONED`, which is terminal; decommissioning is refused while any contract covering the site is still `ACTIVE` or any pig group on the site's barns remains `SCHEDULED`, `PLACED`, or `MARKETING`, and either refusal fails with `ERR_INVALID_STATE_TRANSITION`. The site list can be filtered by `site_status`.

Growers are onboarded with their `legal_name`, a unique `grower_code`, and a contact `email`. Registering a code already in use on another grower is rejected with `ERR_DUPLICATE_GROWER_CODE`. A grower starts `ACTIVE`; suspension moves `grower_status` to `SUSPENDED` and blocks activation of that grower's contracts until reinstatement returns them to `ACTIVE`. Termination moves a grower from either `ACTIVE` or `SUSPENDED` to the terminal `TERMINATED` state and is refused — with `ERR_INVALID_STATE_TRANSITION` — while the grower still holds an `ACTIVE` contract. Two money fields track the financial relationship over time and both start at zero: `balance_due_cents`, the amount the grower currently owes the integrator, and `lifetime_paid_cents`, the running sum of `total_pay_cents` across all of the grower's settlements that have reached `PAID`. The grower list can be filtered by `grower_status`.

The finishing **contract** binds one grower to one site and prices the relationship. An `IntegratorAdmin` drafts it with the `grower_id` and `site_id` it covers, the `base_pay_cents_per_head` paid per head placed, the `bonus_cap_cents_per_head` capping the performance bonus per head placed, the performance targets `fcr_target` (a feed-conversion target such as 2.60) and `adg_target_lbs` (an average-daily-gain target such as 1.90 pounds per day), the `mortality_threshold_pct` that gates the bonus, the `feed_budget_lbs_per_head` that sizes each group's lifetime feed budget, and the effectiveness window `effective_date` through `expiry_date`. The money and budget fields are non-negative integers — `base_pay_cents_per_head`, `bonus_cap_cents_per_head`, and `feed_budget_lbs_per_head` each at least 0 — while `fcr_target` and `adg_target_lbs` must be strictly greater than zero and `mortality_threshold_pct` at least zero, with violations failing `ERR_MALFORMED_FIELD`; no ordering between `effective_date` and `expiry_date` is enforced at drafting. Three optional percentages declare how maintenance costs split between owner and grower, each an integer from 0 to 100: `structural_owner_pct` defaulting to 100, `equipment_owner_pct` defaulting to 50, and `routine_owner_pct` defaulting to 0. A new contract sits in `DRAFT`. The contract list can be filtered by `grower_id`, `site_id`, or `contract_status`.

Activation moves a contract `DRAFT` → `ACTIVE` and enforces four checks: the grower must be `ACTIVE` (`ERR_GROWER_NOT_ACTIVE` when suspended), the site must be `ACTIVE` (`ERR_SITE_NOT_ACTIVE` when suspended), the clock date must fall on or after `effective_date` and on or before `expiry_date` (failing early with `ERR_CONTRACT_NOT_YET_EFFECTIVE` and late with `ERR_CONTRACT_EXPIRED`), and no other contract covering the same site may already be `ACTIVE` (`ERR_CONTRACT_SITE_OVERLAP`). Two terminal exits exist from `ACTIVE`. Termination moves the contract to `TERMINATED`; expiry moves it to `EXPIRED` and additionally requires the clock date to have passed `expiry_date` — expiring too early fails with `ERR_CONTRACT_NOT_EXPIRED`. Both exits share the same blockers: any pig group under the contract still `SCHEDULED`, `PLACED`, or `MARKETING` rejects the request with `ERR_CONTRACT_HAS_ACTIVE_GROUPS`, and any settlement under the contract still `FINALIZED`, `DISPUTED`, or `APPROVED` rejects it with `ERR_SETTLEMENTS_PENDING`.

### 3.2. Barn Inventory and Placement Scheduling

Each barn is registered under its site with a `barn_code` unique within that site — a code collision fails with `ERR_DUPLICATE_BARN_CODE` — plus its `capacity_head` ceiling and its usable `floor_space_sqft`, an integer at least 0. A new barn starts `AVAILABLE`, and every barn's capacity contributes to its site's `total_capacity_head`, the sum of `capacity_head` across the site's barns that are not `OUT_OF_SERVICE`; that total is recomputed whenever a barn is created, marked out of service, or returned to service. The barn list can be filtered by `site_id` or `barn_status`.

Scheduling a pig group is the act of booking a barn's space for a finishing turn. A `FieldTech` (or an `IntegratorAdmin`) supplies the target `barn_id`, the governing `contract_id`, the planned `placement_date`, the `target_market_date` that ends the stay, the scheduled `head_placed`, and the `avg_start_weight_lbs` of the incoming pigs, together with the `expected_barn_version` required by §2.7. `head_placed` must be an integer of at least 1 and `avg_start_weight_lbs` a number strictly greater than zero, with violations failing `ERR_MALFORMED_FIELD`. A successfully scheduled group starts `SCHEDULED`, and the act of scheduling itself advances the barn's `version` by one — the booking book has changed even though no pig has arrived. A new group's counters all read zero at scheduling — `mortality_total`, `cull_total`, `head_marketed`, `cumulative_feed_lbs`, and `pending_deductions_cents` — and its event stamps `placed_at` and `closed_at` stay null until confirmation and close respectively set them. Until close, `head_current` is the placed head minus mortality, culls, and marketed head; it reads zero once the group is closed. The group list can be filtered by `barn_id`, `contract_id`, or `group_status`.

Scheduling enforces a battery of space and calendar gates. The barn must not be `OUT_OF_SERVICE` (`ERR_BARN_NOT_PLACEABLE`), the barn's site must be `ACTIVE` (`ERR_SITE_NOT_ACTIVE`), and the barn's site and the contract's site must be the same site (`ERR_CROSS_SITE_REFERENCE`). The `placement_date` must not lie before the clock date (`ERR_PLACEMENT_DATE_PAST`), and the `target_market_date` must fall strictly after the `placement_date` (`ERR_TARGET_BEFORE_PLACEMENT`). Capacity is then checked two ways against the scheduled head: the head count must not exceed the barn's `capacity_head` (`ERR_SPACE_HEAD_EXCEEDED`), and the head count multiplied by eight square feet per pig must not exceed the barn's `floor_space_sqft` (`ERR_FLOOR_SPACE_EXCEEDED`).

A barn's occupancy book treats each group's stay as a half-open interval that begins on its `placement_date` and ends on its `target_market_date`, with the end date itself excluded. Two stays that merely touch — one group's `placement_date` landing exactly on another's `target_market_date` — do not collide. Scheduling is rejected with `ERR_OCCUPANCY_OVERLAP` when any other group on the same barn in `SCHEDULED`, `PLACED`, or `MARKETING` status strictly interleaves with the new stay: the new `placement_date` falls before that group's `target_market_date` while that group's `placement_date` falls before the new `target_market_date`. Where several existing groups must be examined, they are examined in creation order, oldest first; since any single collision rejects the request, the outcome does not depend on that order.

When the pigs physically arrive, a `FieldTech` confirms placement, moving the group `SCHEDULED` → `PLACED`. Confirmation requires the barn to be `AVAILABLE` (`ERR_BARN_NOT_PLACEABLE` otherwise), the clock date to have reached the `placement_date` (confirming early fails with `ERR_CONFIRM_TOO_EARLY`), and the governing contract to be `ACTIVE` (`ERR_CONTRACT_NOT_ACTIVE`). The confirmation may carry the observed `actual_head_count` and `actual_avg_weight_lbs`; when supplied, the actuals overwrite the schedule — `head_placed` becomes `actual_head_count` and `avg_start_weight_lbs` becomes `actual_avg_weight_lbs` — a supplied `actual_head_count` must be an integer of at least 1 and a supplied `actual_avg_weight_lbs` a number strictly greater than zero (`ERR_MALFORMED_FIELD` otherwise), and a supplied `actual_head_count` must pass the same two space checks as scheduling, head ceiling first and floor space second. Confirmation stamps `placed_at` with the clock instant and flips the barn `AVAILABLE` → `OCCUPIED` with `current_group_id` pointing at the group, incrementing the barn's `version`. A scheduled group that never arrives can instead be cancelled, moving `SCHEDULED` → `CANCELLED`; cancellation leaves the barn untouched, since the group never occupied it.

### 3.3. Phase Feeding and the Lifetime Feed Budget

A pig group carries two independent state dimensions that evolve in parallel: its lifecycle `group_status` and its feed phase `current_phase`. Every group starts its feed dimension in `STARTER` and may advance one step at a time — `STARTER` → `GROWER`, `GROWER` → `FINISHER_1`, `FINISHER_1` → `FINISHER_2` — through a `FieldTech`, and only while the group's lifecycle is `PLACED` or `MARKETING` (advancing otherwise fails with `ERR_GROUP_NOT_ACTIVE`). `FINISHER_2` is the terminal phase: advancing a group already in `FINISHER_2` fails with `ERR_INVALID_STATE_TRANSITION`. Advancing the phase has a deliberate casualty: every feed order of the group still `REQUESTED` or `SCHEDULED` for the phase being left behind is automatically cancelled, releasing its committed budget.

Feed orders are placed by a `FieldTech` against a group that is `PLACED` or `MARKETING` (`ERR_GROUP_NOT_ACTIVE` otherwise), naming the `group_id`, the `phase` being fed, the mill's `diet_code`, the `quantity_lbs` ordered (at least one pound), and the `requested_delivery_date`, which must not lie before the clock date (`ERR_FEED_DATE_PAST`). The `phase` on the order must equal the group's `current_phase` — a mismatch is rejected with `ERR_PHASE_MISMATCH`. A new order starts `REQUESTED`; its `scheduled_delivery_date` stays null until the mill schedules it, and its `delivered_lbs` stays null until a delivery is recorded. The order list can be filtered by `group_id`, `order_status`, or `phase`.

Each group's lifetime feed budget is its `head_placed` multiplied by the contract's `feed_budget_lbs_per_head`. Two drawdowns stand against that budget: committed pounds, the sum of `quantity_lbs` across the group's orders still `REQUESTED` or `SCHEDULED`, and delivered pounds, the sum of `delivered_lbs` across orders in `DELIVERED` or `SHORTED`. The hard remainder is the budget minus both drawdowns, and a new order whose `quantity_lbs` exceeds the hard remainder is rejected with `ERR_FEED_BUDGET_EXCEEDED` — a whole-budget gate on chronological, actual grounds.

Alongside the hard gate runs a softer, forward-looking allocation that never rejects. Each phase is allotted a fixed share of the whole lifetime budget — fifteen percent for `STARTER`, thirty percent for `GROWER`, thirty percent for `FINISHER_1`, and twenty-five percent for `FINISHER_2` — with each allotment rounded half-up to a whole pound. A phase remainder is that allotment minus the phase's own committed and delivered pounds, and when a new order's `quantity_lbs` exceeds its phase remainder, the created order is flagged with `over_phase_plan` set to true. The flag is advisory: it warns that the phase plan is being overdrawn even though the hard budget still permits the order.

The mill takes over from there. A `FeedMill` schedules a `REQUESTED` order by setting its `scheduled_delivery_date`, which must not lie before the clock date (`ERR_FEED_DATE_PAST`), moving the order `REQUESTED` → `SCHEDULED`. When the truck arrives, the mill confirms delivery with the actual `delivered_lbs` — an integer at least 0 — against an order still `SCHEDULED`; delivering an order in any other status, including a still-`REQUESTED` one, fails with `ERR_INVALID_STATE_TRANSITION`. Delivering at least eighty percent of the ordered `quantity_lbs` closes the order as `DELIVERED`; delivering less than eighty percent closes it as `SHORTED`. Either way, the delivered pounds accumulate into the group's `cumulative_feed_lbs`. A `FieldTech` may cancel an order while it is still `REQUESTED` or `SCHEDULED`, moving it to `CANCELLED`; cancellation releases the order's committed pounds back into the budget, because the order leaves the committed set.

### 3.4. Mortality Reporting and Head Reconciliation

Losses on the farm are reported by the `Grower` who owns the group, filing a mortality report under the group with the `report_date` of the losses, the `mortality_count` of dead pigs, the `cull_count` of culled pigs, and a `reason_code` of `DISEASE`, `INJURY`, `STRESS`, or `OTHER`. The group must be `PLACED` or `MARKETING` (`ERR_GROUP_NOT_ACTIVE` otherwise), and the `report_date` must fall within the group's life so far — on or after its `placement_date` and on or before the clock date (`ERR_REPORT_DATE_OUT_OF_RANGE`). Each count must be zero or greater, and a report carrying zero deaths and zero culls is rejected with `ERR_EMPTY_REPORT`. Reports are immutable once filed and are listed, paginated, under their group.

Head accounting on a group is held to a strict invariant. Before close, the `head_placed` must always equal the sum of `head_current`, `mortality_total`, `cull_total`, and `head_marketed`; after close, the `head_placed` must equal the sum of `mortality_total`, `cull_total`, `head_marketed`, and `head_unaccounted`. The components are aggregations: `mortality_total` and `cull_total` sum the corresponding counts across all of the group's reports, and `head_marketed` sums the `head_count` of the group's loads that reached `DELIVERED`. Any report whose new deaths and culls would push the accounted total — existing mortality, culls, and marketed head plus the report's `mortality_count` and `cull_count` — beyond `head_placed` is rejected with `ERR_HEAD_COUNT_EXCEEDED`. The group's `mortality_pct` is one hundred times `mortality_total` divided by `head_placed`, rounded half-up to two decimal places.

Head accounting can close a group by itself. When applying a mortality report drives `head_current` to zero, the group closes automatically — see §3.8 for the full close-out cascade.

### 3.5. Marketing: Packer Slots, Truck Washes, and Market Loads

Selling finished pigs starts with capacity at the plant. An `IntegratorAdmin` opens **packer slots**, each identified by its `plant_code`, `slot_date`, and `shift` — `AM` or `PM` — and the combination of those three must be unique, with duplicates rejected as `ERR_DUPLICATE_SLOT`. A slot declares the `capacity_head` the plant will take (at least one) and the acceptable average live-weight window `min_weight_lbs` through `max_weight_lbs` — both integers at least 0 — where the maximum must be at least the minimum. A new slot starts `OPEN`, and the slot list can be filtered by `plant_code`, `slot_date`, or `slot_status`.

A slot's `reserved_head` is the sum of `head_count` across its loads in `SCHEDULED`, `DISPATCHED`, `DELIVERED`, or `REJECTED_AT_PLANT` status — cancelled loads drop out of the reserved set. When the reserved head reaches `capacity_head` exactly, the slot flips itself from `OPEN` to `FULL`; when a cancellation later pulls the reserved head back below capacity, it flips back to `OPEN`. An `IntegratorAdmin` may close a slot from either `OPEN` or `FULL`, moving it to the terminal `CLOSED`, but only while no load against it remains `SCHEDULED` or `DISPATCHED` (`ERR_SLOT_HAS_ACTIVE_LOADS`).

Booking a **market load** reserves part of a slot for a group. A `FieldTech` supplies the `group_id`, the `slot_id`, the `head_count` being shipped (at least one), and the `expected_slot_version` required by §2.7. The group must be `PLACED` or `MARKETING` (`ERR_GROUP_NOT_ACTIVE`), the slot must not be `CLOSED` (`ERR_SLOT_NOT_OPEN`), and the `slot_date` must not lie before the clock date (`ERR_SLOT_DATE_PAST`). Because slots book out, capacity is gated: the slot's `reserved_head` plus the new `head_count` must stay at or below `capacity_head` — landing exactly on capacity is allowed — and an overage is rejected with `ERR_SLOT_CAPACITY_EXCEEDED`. The same head-accounting invariant that guards mortality reports also guards booking: a load whose `head_count` would push the group's accounted head beyond its `head_placed` is rejected with `ERR_HEAD_COUNT_EXCEEDED`. A booked load starts `SCHEDULED`; booking recomputes the slot's `reserved_head`, advances the slot's `version` by one, and may flip the slot `OPEN` → `FULL`. The load list can be filtered by `group_id`, `slot_id`, `truck_wash_id`, or `load_status`.

Booking also looks forward at what the pigs will weigh on the slot date. The projection takes the number of days from the group's `placement_date` to the slot's `slot_date` — never negative — multiplies it by 1.85 pounds of projected gain per day, and adds the group's `avg_start_weight_lbs`. The projected average weight, rounded half-up to two decimal places, must land inside the slot's weight window — at least `min_weight_lbs` and at most `max_weight_lbs` — or the booking is rejected with `ERR_WEIGHT_WINDOW_PROJECTED`.

No load moves without a biosecure truck. A `TransportCoordinator` records a **truck wash** with the `truck_code`, the `washed_at` instant the wash completed, and the `wash_type` — `FULL_DISINFECT` or `WASH_ONLY`. Unlike a barn wash's `completed_at`, `washed_at` carries no not-in-the-future gate and is accepted as supplied. The wash starts `RECORDED` with the recorder's identity captured in `recorded_by`. An `IntegratorAdmin` then verifies it — `RECORDED` → `VERIFIED`, stamping `verified_by` — or rejects it — `RECORDED` → `REJECTED` — and per §2.11 the verifier or rejecter must be a different identity than the recorder (`ERR_SEGREGATION_OF_DUTIES`). The wash list can be filtered by `truck_code` or `wash_status`.

Dispatching a load, done by a `TransportCoordinator` supplying the `truck_wash_id`, moves it `SCHEDULED` → `DISPATCHED` and enforces the full biosecurity battery. The referenced wash must be `VERIFIED` (`ERR_WASH_NOT_VERIFIED`) and of type `FULL_DISINFECT` (`ERR_WASH_TYPE_INSUFFICIENT`); the dispatch instant must fall within forty-eight hours of `washed_at`, with a dispatch exactly forty-eight hours after the wash still valid and anything later rejected as `ERR_WASH_STALE`; the wash must not already back another load in `DISPATCHED`, `DELIVERED`, or `REJECTED_AT_PLANT` (`ERR_WASH_ALREADY_USED`); and the clock date must still be on or before the slot's `slot_date` (`ERR_SLOT_DATE_PAST`). A successful dispatch records the wash on the load.

At the plant, the `TransportCoordinator` records the scale outcome with `live_weight_lbs_total` — an integer at least 0, and a value that stays null, along with `avg_weight_lbs`, until this moment — and the load's `avg_weight_lbs` is computed as that total divided by `head_count`, rounded half-up to two decimal places. Delivery is not accepted before the slot's date — the clock date must be on or after `slot_date` (`ERR_DELIVERY_BEFORE_SLOT_DATE`). From there the outcome branches on the weight window. An average weight inside the window — at least `min_weight_lbs` and at most `max_weight_lbs` — moves the load `DISPATCHED` → `DELIVERED` and settles it into the group's aggregates: `head_marketed` gains the `head_count`, `total_live_weight_lbs` gains the `live_weight_lbs_total`, and `head_current` drops by the `head_count`. A group's first delivered load also moves its lifecycle from `PLACED` to `MARKETING`, and a delivery that drains `head_current` to zero closes the group outright (§3.8). An average weight outside the window instead moves the load `DISPATCHED` → `REJECTED_AT_PLANT`: the head are not marketed, the load still counts toward the slot's `reserved_head`, and a reject penalty of 1,500 cents per head shipped is added to the group's `pending_deductions_cents`. When the group's settlement already exists and still sits in `FINALIZED` or `DISPUTED`, its `deductions_cents` and `total_pay_cents` are recomputed to absorb the new penalty.

A `FieldTech` may cancel a load while it is `SCHEDULED` or `DISPATCHED`, moving it to `CANCELLED`. Cancellation pulls the load out of the slot's reserved set — `reserved_head` is recomputed, the slot's `version` advances, and a `FULL` slot that drops below capacity flips back to `OPEN`. When the cancelled load had been dispatched, its truck wash is freed for reuse by another load.

### 3.6. Barn Washing, Downtime, and Service Status

When a group closes, its barn does not simply become empty — it becomes dirty. The close flips the barn `OCCUPIED` → `WASH_REQUIRED`, clears `current_group_id` back to null, sets the barn's `wash_required` flag, and advances the barn's `version`. A freshly registered barn carries `wash_required` false, a null `downtime_until`, and a null `current_group_id`; the downtime stamp is only ever set by wash verification. From `WASH_REQUIRED`, the only way forward is a wash.

The `Grower` who owns the barn records a **barn wash** with the `barn_id`, the `wash_type` — again `FULL_DISINFECT` or `WASH_ONLY` — and the `completed_at` instant, which must not lie in the future: a future `completed_at` fails with `ERR_MALFORMED_FIELD` (HTTP 400) at field-shape time, before the barn's status is examined. Recording is accepted only while the barn is in `WASH_REQUIRED`; the attempt against a barn in any other status fails with `ERR_INVALID_STATE_TRANSITION`. A recorded wash starts `RECORDED` with the recorder in `recorded_by`, and its arrival moves the barn `WASH_REQUIRED` → `WASHING`, incrementing the barn's `version`. The barn-wash list can be filtered by `barn_id` or `wash_status`.

Verification follows the shared wash governance of §2.10. An `IntegratorAdmin` other than the recorder verifies the wash — `RECORDED` → `VERIFIED`, stamping `verified_by` — which requires the wash to be a `FULL_DISINFECT` (verifying a `WASH_ONLY` fails with `ERR_WASH_TYPE_INSUFFICIENT`) and moves the barn `WASHING` → `DOWNTIME`, setting `downtime_until` to the wash's `completed_at` plus seventy-two hours and incrementing the barn's `version`. Rejection instead moves the wash `RECORDED` → `REJECTED` and sends the barn `WASHING` → `WASH_REQUIRED`, again incrementing its `version`, so the barn simply awaits a proper wash. If the barn has left `WASHING` in the meantime — for example it was marked `OUT_OF_SERVICE` mid-wash — verification or rejection still updates the wash but leaves the barn untouched.

A barn in `DOWNTIME` rests until its downtime elapses: an `IntegratorAdmin` releases it, moving `DOWNTIME` → `AVAILABLE`, only once the clock has reached `downtime_until` — releasing early fails with `ERR_BARN_DOWNTIME_ACTIVE`. Release clears `wash_required` to false and nulls `downtime_until`, incrementing the barn's `version`.

Two administrative controls sit alongside the wash loop. An `IntegratorAdmin` may mark a barn out of service from `AVAILABLE`, `WASH_REQUIRED`, `WASHING`, or `DOWNTIME`, moving it to `OUT_OF_SERVICE`; a barn that is `OCCUPIED` cannot be taken out of service (`ERR_BARN_OCCUPIED`). Returning a barn to service is permitted only while no maintenance ticket for that barn remains `OPEN`, `QUOTED`, `APPROVED`, or `IN_PROGRESS` (`ERR_TICKETS_OPEN`), and the return targets one of two states depending on cleanliness: a barn whose `wash_required` is false comes back `AVAILABLE`, while a barn whose `wash_required` is true comes back `WASH_REQUIRED`. Both the out-of-service and return transitions recompute the site's `total_capacity_head`, and every barn state change increments the barn's `version` and refreshes `updated_at`.

### 3.7. Barn Maintenance and the Owner–Grower Cost Split

Repairs on grower-owned barns are tracked as **maintenance tickets**. The `Grower` opens a ticket for one of their own barns with the `barn_id`, a `category` of `STRUCTURAL`, `EQUIPMENT`, `ROUTINE`, or `EMERGENCY`, and a free-text `description`. At creation the ticket adopts the `ACTIVE` contract on the barn's site — its `contract_id` and `grower_id` are copied from that contract — and starts `OPEN`. A barn whose site has no `ACTIVE` contract cannot be ticketed: the ownership chain of §2.1 does not resolve, and the attempt fails with `ERR_NOT_RESOURCE_OWNER`. The ticket list can be filtered by `barn_id`, `contract_id`, `grower_id`, or `ticket_status`.

A `FieldTech` then quotes the work, supplying the `cost_cents` (at least one cent) and the assessed `cause` — `WEAR`, `NEGLIGENCE`, or `ACT_OF_NATURE` — which moves the ticket `OPEN` → `QUOTED` and records the quoter's identity in `quoted_by`. Approval of a quote is both thresholded and segregated: a `FieldTech` may approve only when `cost_cents` is below 50,000 cents, while an `IntegratorAdmin` may approve any amount (a `FieldTech` attempt at or above the threshold fails with `ERR_FORBIDDEN_ROLE`), and the approver's identity must differ from `quoted_by` (`ERR_SEGREGATION_OF_DUTIES`). Approval moves `QUOTED` → `APPROVED`, stamps `approved_by`, sets `approved_flag` to true, and computes the cost split. Work then begins — `APPROVED` → `IN_PROGRESS` — and completion moves `IN_PROGRESS` → `COMPLETED`, stamping `completed_at` with the clock instant. Completion requires `approved_flag` to be true; completing an unapproved ticket fails with `ERR_TICKET_UNAPPROVED`. A quoted ticket can be rejected by a `FieldTech` — `QUOTED` → `REJECTED` — and the grower can cancel their own ticket while it is `OPEN` or `QUOTED`, moving it to `CANCELLED`; cancelling a ticket that belongs to another grower fails with `ERR_NOT_RESOURCE_OWNER`.

Emergencies get a deliberately compressed path. For a ticket whose `category` is `EMERGENCY`, a `FieldTech` may start work directly from `QUOTED` — `QUOTED` → `IN_PROGRESS` without waiting for approval — and may later retro-quote (`IN_PROGRESS` → `IN_PROGRESS`, refreshing `cost_cents`, `cause`, and `quoted_by`) and retro-approve (also `IN_PROGRESS` → `IN_PROGRESS`, computing shares and setting `approved_by` and `approved_flag` while the ticket stays in progress). Both emergency relaxations are gated on the category: quoting or starting work from a non-standard state on a non-`EMERGENCY` ticket fails with `ERR_INVALID_STATE_TRANSITION`, and the retro-approval carries the same cost threshold and segregation checks as a normal approval.

The cost split is computed at approval and follows a pinned rounding order. When the cause is `NEGLIGENCE`, the owner bears nothing and `grower_share_cents` equals the entire `cost_cents`. Otherwise the owner's percentage is selected from the contract by `category` — `structural_owner_pct` for `STRUCTURAL`, `equipment_owner_pct` for `EQUIPMENT`, and `routine_owner_pct` for both `ROUTINE` and `EMERGENCY` — and the `owner_share_cents` is computed first as `cost_cents` multiplied by that percentage and divided by one hundred, rounded half-up to a whole cent; the `grower_share_cents` is then whatever remains of the `cost_cents`. Rounding the grower's share first would produce different cents on odd amounts and is not permitted.

Negligence has a second life at completion. When a completed ticket's cause is `NEGLIGENCE`, the grower's share is charged against the pig group on that barn whose stay — from its `placement_date` through its `closed_at` — contains the completion instant (only a group that physically occupied the barn — `PLACED`, `MARKETING`, or `CLOSED` — qualifies, and if several stays contain the instant, a still-open group wins over a closed one): the charge accrues into that group's `pending_deductions_cents`, and when the group's settlement still sits in `FINALIZED` or `DISPUTED`, its `deductions_cents` and `total_pay_cents` are recomputed to absorb the charge. When no such group exists, or the group's settlement has already moved on to `APPROVED` or `PAID`, the charge instead lands on the grower's `balance_due_cents`.

### 3.8. Close-Out, Settlement, and Grower Payment

A group closes in one of two ways, and both end at `CLOSED`. The natural path fires automatically the moment `head_current` reaches zero after a mortality report or a load delivery — every placed pig has been accounted for — and the triggering report or delivery and the automatic close are two mutations of the group, so its `version` advances by two within that request. The force path is a deliberate close-out by a `FieldTech` while the group is `PLACED` or `MARKETING`, used when remaining pigs cannot be marketed; force closing copies the remaining `head_current` into `head_unaccounted` and zeroes `head_current`, whereas a natural close leaves `head_unaccounted` at its default of zero. Either close stamps `closed_at` with the clock instant, flips the occupying barn to `WASH_REQUIRED` as described in §3.6, and mints the group's **settlement**.

The settlement is created one-to-one with the group, already in `FINALIZED` status, carrying the group's `contract_id` and snapshotting the close-out aggregates: `head_marketed`, `total_live_weight_lbs`, the group's `mortality_pct`, and `days_on_feed` measured as the number of days from `placement_date` to the closing date. Its performance metrics are computed from actuals only. Weight gain is the group's `total_live_weight_lbs` minus the start weight of the marketed head — that is, minus `head_marketed` times `avg_start_weight_lbs`. The `adg_lbs` divides that weight gain across pig-days — by the product of `head_marketed` and `days_on_feed` — rounded half-up to two decimals. The `fcr` divides `cumulative_feed_lbs` by the weight gain, also rounded half-up to two decimals. These metric formulas presuppose that the group marketed at least one load and that the total weight gain is positive; when a presupposition fails — no marketed load, a non-positive weight gain, or a `days_on_feed` of zero — the settlement's `fcr` and `adg_lbs` are null and the performance bonus is zero.

The performance bonus is gated twice before any tiering. If `head_unaccounted` is greater than zero — a force close-out left pigs unaccounted — the `bonus_cents` is zero. Otherwise, if the group's `mortality_pct` is strictly greater than the contract's `mortality_threshold_pct`, the bonus is likewise zero; a mortality percentage exactly equal to the threshold survives the gate. A surviving bonus is then tiered on feed conversion against the contract's `fcr_target`: an `fcr` at or below one-tenth under the target earns the full tier factor of 1.00; an `fcr` at or below the target itself earns 0.60; an `fcr` at or below one-tenth above the target earns 0.30; and anything worse earns 0.00. The tier is then scaled by growth: when `adg_lbs` meets or exceeds `adg_target_lbs` the growth factor is 1.0, otherwise 0.5. The final `bonus_cents` is the contract's `bonus_cap_cents_per_head` multiplied by `head_placed`, by the tier factor, and by the growth factor, with the whole chain rounded half-up to a whole cent in a single final rounding — no intermediate products are rounded.

Pay is then assembled. The `base_pay_cents` is `head_placed` times the contract's `base_pay_cents_per_head`. The `deductions_cents` is the group's `pending_deductions_cents` at close — and it stays live afterward: penalties and negligence charges posted while the settlement sits in `FINALIZED` or `DISPUTED` recompute both `deductions_cents` and `total_pay_cents`. The `adjustment_cents` starts at zero at close. The `total_pay_cents` is always `base_pay_cents` plus `bonus_cents` plus `adjustment_cents` minus `deductions_cents`. The settlement list can be filtered by `group_id`, `contract_id`, or `settlement_status`.

While a group is still `PLACED` or `MARKETING`, a provisional settlement preview projects where the close-out is heading; a preview requested for a group in any other status fails with `ERR_GROUP_NOT_ACTIVE`. The preview blends actuals with projection for the `head_current` pigs not yet marketed: the remaining days run from the clock date to `target_market_date`, floored at zero; each remaining pig is projected to gain 1.85 pounds per remaining day and to consume 2.70 pounds of feed per pound of that projected gain. Adding the projected gain of the remaining head to the weight gain actually recorded so far yields the provisional weight gain; the provisional `fcr` divides the feed already delivered plus the projected feed for the remaining head by that provisional weight gain, rounded half-up to two decimals; and the provisional `adg_lbs` divides the provisional weight gain by the product of the total projected marketed head — `head_marketed` plus `head_current` — and the full planned days from `placement_date` to `target_market_date`, again rounded half-up to two decimals. The provisional `mortality_pct` is simply the group's current `mortality_pct`, and the provisional bonus applies the same gates and tiers to those provisional metrics, with `deductions_cents` taken as the `pending_deductions_cents` accrued to date and `adjustment_cents` fixed at zero. The preview requires at least one pig still on feed and a positive provisional weight gain — failing either requirement rejects the request with `ERR_INVALID_STATE_TRANSITION` — and its response carries `variant` with the literal value `PROVISIONAL`, together with `base_pay_cents`, `bonus_cents`, `deductions_cents`, `adjustment_cents`, `total_pay_cents`, `fcr`, `adg_lbs`, `mortality_pct`, and `head_projected_marketed` — the marketed head plus the remaining head the projection assumes will be marketed.

After close, the settlement walks a dispute-and-payment path. The owning `Grower` may dispute a `FINALIZED` settlement, supplying a `reason`, moving it `FINALIZED` → `DISPUTED`; a dispute filed by anyone whose identity does not resolve to the settlement's grower fails with `ERR_NOT_RESOURCE_OWNER`. A `FieldTech` refinalizes a disputed settlement with a signed `adjustment_cents`, moving it back `DISPUTED` → `FINALIZED` and recomputing `total_pay_cents`; each refinalization replaces `adjustment_cents` outright with the supplied value — it never accumulates onto a previous adjustment — and the dispute cycle between `FINALIZED` and `DISPUTED` may repeat any number of rounds. An `IntegratorAdmin` then approves a `FINALIZED` settlement — `FINALIZED` → `APPROVED`, stamping `approved_by` — and an `IntegratorAdmin` pays an `APPROVED` settlement, moving it `APPROVED` → `PAID`. Payment is segregated from approval per §2.11: the payer's identity must differ from `approved_by` (`ERR_SEGREGATION_OF_DUTIES`), and a successful payment stamps `paid_by` and adds the settlement's `total_pay_cents` into the grower's `lifetime_paid_cents`.

### 3.9. Manure Planning and Land Application

Each site's manure obligations are governed by an annual **manure plan**, drafted by an `EnvironmentalManager` with the `site_id`, the `plan_year` it governs, the lagoon's `lagoon_capacity_gal`, the `lagoon_start_gal` actually in storage at plan start, and the year's nutrient budgets `n_budget_lbs` and `p_budget_lbs` — all four volume and budget fields are integers at least 0, with violations failing `ERR_MALFORMED_FIELD`. The starting volume must not exceed the lagoon's capacity — a plan whose `lagoon_start_gal` tops its `lagoon_capacity_gal` is rejected with `ERR_LAGOON_OVER_CAPACITY`. A new plan sits in `DRAFT`, and the plan list can be filtered by `site_id`, `plan_year`, or `plan_status`.

Submission moves a plan `DRAFT` → `SUBMITTED`, stamping `submitted_by`, and is permitted only while no other plan for the same site and `plan_year` sits in `SUBMITTED` or `APPROVED` (`ERR_PLAN_YEAR_OVERLAP`). An `IntegratorAdmin` then approves — `SUBMITTED` → `APPROVED`, which requires the site to be `ACTIVE` (`ERR_SITE_NOT_ACTIVE`) and automatically supersedes every other `APPROVED` plan of the same site, moving each to the terminal `SUPERSEDED` — or rejects the plan, moving it `SUBMITTED` → `REJECTED`. Rejection is not the end: the `EnvironmentalManager` may revise, moving the plan `REJECTED` → `DRAFT`, and the loop from `SUBMITTED` through `REJECTED` back to `DRAFT` and on to `SUBMITTED` may repeat as often as needed.

Land applications draw the plan down. An `EnvironmentalManager` records an application against an `APPROVED` plan — applying against a plan in any other status fails with `ERR_PLAN_NOT_APPROVED` — supplying the `plan_id`, the `field_code` receiving the manure, the `applied_at` instant, the `gallons` applied (at least one), and the lab-manifest nutrient loads `n_lbs` and `p_lbs` (each zero or greater). The application season is regulated: `applied_at` must fall within the plan year's window from March 1 through November 30, inclusive, and must not lie in the future (`ERR_APPLICATION_OUTSIDE_WINDOW`). A recorded application starts `RECORDED`, and the application list can be filtered by `plan_id` or `application_status`.

Three budget gates guard creation, evaluated in a fixed order. First nitrogen: if the plan's `n_applied_lbs` plus the new `n_lbs` would exceed `n_budget_lbs`, the application is rejected with `ERR_NUTRIENT_BUDGET_EXCEEDED`. Then phosphorus, symmetrically: `p_applied_lbs` plus `p_lbs` against `p_budget_lbs`, same error. Then lagoon volume: if the new `gallons` exceeds the plan's `lagoon_available_gal`, the application is rejected with `ERR_LAGOON_INSUFFICIENT`. The tracked totals aggregate applications in `RECORDED` or `CONFIRMED` status only: `n_applied_lbs` and `p_applied_lbs` sum the corresponding nutrient loads, and `lagoon_available_gal` is the `lagoon_start_gal` minus the summed gallons of that same set. An application is later confirmed — `RECORDED` → `CONFIRMED` — or voided; voiding from either `RECORDED` or `CONFIRMED` moves it to the terminal `VOIDED`, removes it from every aggregate, and credits the plan back, subtracting its nutrients from `n_applied_lbs` and `p_applied_lbs` and returning its gallons to `lagoon_available_gal`.

## 4. Endpoint Definitions

Operations that create new resources return a `201 Created` status code. Operations that modify an existing resource — state transitions, confirmations, verifications, and the clock-setting capability — return `200 OK`, as do all reads. Failures return the 4xx status mapped to the error identifier in §5.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock | IntegratorAdmin |
| POST | `/sites` | Create site | IntegratorAdmin |
| GET | `/sites` | List sites (paginated) | IntegratorAdmin, FieldTech, Grower, FeedMill, TransportCoordinator, EnvironmentalManager |
| GET | `/sites/{id}` | Get site | IntegratorAdmin, FieldTech, Grower, FeedMill, TransportCoordinator, EnvironmentalManager |
| POST | `/sites/{id}/suspend` | Suspend site | IntegratorAdmin |
| POST | `/sites/{id}/reinstate` | Reinstate site | IntegratorAdmin |
| POST | `/sites/{id}/decommission` | Decommission site (terminal) | IntegratorAdmin |
| POST | `/growers` | Create grower | IntegratorAdmin |
| GET | `/growers` | List growers (paginated) | IntegratorAdmin, FieldTech |
| GET | `/growers/{id}` | Get grower | IntegratorAdmin, FieldTech, Grower |
| POST | `/growers/{id}/suspend` | Suspend grower | IntegratorAdmin |
| POST | `/growers/{id}/reinstate` | Reinstate grower | IntegratorAdmin |
| POST | `/growers/{id}/terminate` | Terminate grower (terminal) | IntegratorAdmin |
| POST | `/contracts` | Create finishing contract | IntegratorAdmin |
| GET | `/contracts` | List contracts (paginated, filters) | IntegratorAdmin, FieldTech, Grower |
| GET | `/contracts/{id}` | Get contract | IntegratorAdmin, FieldTech, Grower |
| POST | `/contracts/{id}/activate` | Activate contract | IntegratorAdmin |
| POST | `/contracts/{id}/terminate` | Terminate contract (terminal) | IntegratorAdmin |
| POST | `/contracts/{id}/expire` | Expire contract past expiry date (terminal) | IntegratorAdmin |
| POST | `/barns` | Create barn | IntegratorAdmin |
| GET | `/barns` | List barns (paginated, filters) | IntegratorAdmin, FieldTech, Grower |
| GET | `/barns/{id}` | Get barn | IntegratorAdmin, FieldTech, Grower |
| POST | `/barns/{id}/release` | Release barn from downtime | IntegratorAdmin |
| POST | `/barns/{id}/mark-out-of-service` | Take barn out of service | IntegratorAdmin |
| POST | `/barns/{id}/return-to-service` | Return barn to service | IntegratorAdmin |
| POST | `/pig-groups` | Schedule pig placement | FieldTech, IntegratorAdmin |
| GET | `/pig-groups` | List pig groups (paginated, filters) | IntegratorAdmin, FieldTech, Grower, TransportCoordinator |
| GET | `/pig-groups/{id}` | Get pig group | IntegratorAdmin, FieldTech, Grower, TransportCoordinator |
| POST | `/pig-groups/{id}/confirm-placement` | Confirm pigs on the ground | FieldTech |
| POST | `/pig-groups/{id}/advance-phase` | Advance feed phase one step | FieldTech |
| POST | `/pig-groups/{id}/cancel` | Cancel scheduled group | FieldTech |
| POST | `/pig-groups/{id}/close-out` | Force close-out with unaccounted head | FieldTech |
| GET | `/pig-groups/{id}/settlement-preview` | Provisional settlement projection | IntegratorAdmin, FieldTech, Grower |
| POST | `/pig-groups/{id}/mortality-reports` | Report mortality and culls (append-only) | Grower |
| GET | `/pig-groups/{id}/mortality-reports` | List reports of a group (paginated) | IntegratorAdmin, FieldTech, Grower |
| POST | `/feed-orders` | Create feed order (phase-diet gated) | FieldTech |
| GET | `/feed-orders` | List feed orders (paginated, filters) | IntegratorAdmin, FieldTech, FeedMill, Grower |
| GET | `/feed-orders/{id}` | Get feed order | IntegratorAdmin, FieldTech, FeedMill, Grower |
| POST | `/feed-orders/{id}/schedule` | Mill schedules delivery | FeedMill |
| POST | `/feed-orders/{id}/deliver` | Mill confirms delivery (variance branch) | FeedMill |
| POST | `/feed-orders/{id}/cancel` | Cancel feed order | FieldTech |
| POST | `/packer-slots` | Create packer delivery slot | IntegratorAdmin |
| GET | `/packer-slots` | List slots (paginated, filters) | IntegratorAdmin, FieldTech, TransportCoordinator |
| GET | `/packer-slots/{id}` | Get slot | IntegratorAdmin, FieldTech, TransportCoordinator |
| POST | `/packer-slots/{id}/close` | Close slot (terminal) | IntegratorAdmin |
| POST | `/market-loads` | Book load into slot | FieldTech |
| GET | `/market-loads` | List loads (paginated, filters) | IntegratorAdmin, FieldTech, TransportCoordinator, Grower |
| GET | `/market-loads/{id}` | Get load | IntegratorAdmin, FieldTech, TransportCoordinator, Grower |
| POST | `/market-loads/{id}/dispatch` | Dispatch with verified truck wash | TransportCoordinator |
| POST | `/market-loads/{id}/deliver` | Record scale weights (weight-window branch) | TransportCoordinator |
| POST | `/market-loads/{id}/cancel` | Cancel load; frees slot head and truck wash | FieldTech |
| POST | `/truck-washes` | Record truck wash | TransportCoordinator |
| GET | `/truck-washes` | List truck washes (paginated) | IntegratorAdmin, TransportCoordinator, FieldTech |
| GET | `/truck-washes/{id}` | Get truck wash | IntegratorAdmin, TransportCoordinator, FieldTech |
| POST | `/truck-washes/{id}/verify` | Verify wash (segregated from recorder) | IntegratorAdmin |
| POST | `/truck-washes/{id}/reject` | Reject wash (segregated from recorder) | IntegratorAdmin |
| POST | `/barn-washes` | Record barn wash | Grower |
| GET | `/barn-washes` | List barn washes (paginated) | IntegratorAdmin, Grower, FieldTech |
| GET | `/barn-washes/{id}` | Get barn wash | IntegratorAdmin, Grower, FieldTech |
| POST | `/barn-washes/{id}/verify` | Verify barn wash; starts 72h downtime | IntegratorAdmin |
| POST | `/barn-washes/{id}/reject` | Reject barn wash; back to wash-required | IntegratorAdmin |
| POST | `/manure-plans` | Create annual manure plan | EnvironmentalManager |
| GET | `/manure-plans` | List manure plans (paginated) | IntegratorAdmin, EnvironmentalManager |
| GET | `/manure-plans/{id}` | Get manure plan | IntegratorAdmin, EnvironmentalManager |
| POST | `/manure-plans/{id}/submit` | Submit plan | EnvironmentalManager |
| POST | `/manure-plans/{id}/approve` | Approve plan; supersedes other approved plans of site | IntegratorAdmin |
| POST | `/manure-plans/{id}/reject` | Reject plan | IntegratorAdmin |
| POST | `/manure-plans/{id}/revise` | Return rejected plan to draft | EnvironmentalManager |
| POST | `/manure-applications` | Record land application (budget-debiting) | EnvironmentalManager |
| GET | `/manure-applications` | List applications (paginated) | IntegratorAdmin, EnvironmentalManager |
| GET | `/manure-applications/{id}` | Get application | IntegratorAdmin, EnvironmentalManager |
| POST | `/manure-applications/{id}/confirm` | Confirm application (terminal) | EnvironmentalManager |
| POST | `/manure-applications/{id}/void` | Void application; budgets credited back | EnvironmentalManager |
| POST | `/maintenance-tickets` | Open maintenance ticket | Grower |
| GET | `/maintenance-tickets` | List tickets (paginated) | IntegratorAdmin, FieldTech, Grower |
| GET | `/maintenance-tickets/{id}` | Get ticket | IntegratorAdmin, FieldTech, Grower |
| POST | `/maintenance-tickets/{id}/quote` | Quote cost and cause | FieldTech |
| POST | `/maintenance-tickets/{id}/approve` | Approve quote (threshold role, segregated) | FieldTech, IntegratorAdmin |
| POST | `/maintenance-tickets/{id}/start-work` | Start work | FieldTech |
| POST | `/maintenance-tickets/{id}/complete` | Complete work; negligence charges grower | FieldTech |
| POST | `/maintenance-tickets/{id}/reject` | Reject quoted ticket | FieldTech |
| POST | `/maintenance-tickets/{id}/cancel` | Grower cancels own open ticket | Grower |
| GET | `/settlements` | List settlements (paginated) | IntegratorAdmin, FieldTech, Grower |
| GET | `/settlements/{id}` | Get settlement | IntegratorAdmin, FieldTech, Grower |
| POST | `/settlements/{id}/dispute` | Grower disputes settlement | Grower |
| POST | `/settlements/{id}/refinalize` | Re-finalize with signed adjustment | FieldTech |
| POST | `/settlements/{id}/approve` | Approve settlement | IntegratorAdmin |
| POST | `/settlements/{id}/pay` | Pay settlement (segregated from approver) | IntegratorAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error live in the workflow narratives of §2 and §3; this catalogue is the identifier-to-status mapping only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_MALFORMED_FIELD` | 400 |
| `ERR_STALE_BARN_VERSION` | 412 |
| `ERR_STALE_SLOT_VERSION` | 412 |
| `ERR_INVALID_STATE_TRANSITION` | 409 |
| `ERR_GROUP_NOT_ACTIVE` | 409 |
| `ERR_CONTRACT_NOT_ACTIVE` | 409 |
| `ERR_SITE_NOT_ACTIVE` | 409 |
| `ERR_GROWER_NOT_ACTIVE` | 409 |
| `ERR_BARN_NOT_PLACEABLE` | 409 |
| `ERR_BARN_OCCUPIED` | 409 |
| `ERR_PLAN_NOT_APPROVED` | 409 |
| `ERR_SLOT_NOT_OPEN` | 409 |
| `ERR_TICKET_UNAPPROVED` | 409 |
| `ERR_CONTRACT_HAS_ACTIVE_GROUPS` | 409 |
| `ERR_SETTLEMENTS_PENDING` | 409 |
| `ERR_SLOT_HAS_ACTIVE_LOADS` | 409 |
| `ERR_TICKETS_OPEN` | 409 |
| `ERR_WASH_NOT_VERIFIED` | 409 |
| `ERR_WASH_TYPE_INSUFFICIENT` | 409 |
| `ERR_BARN_DOWNTIME_ACTIVE` | 409 |
| `ERR_WASH_STALE` | 409 |
| `ERR_PLACEMENT_DATE_PAST` | 409 |
| `ERR_TARGET_BEFORE_PLACEMENT` | 409 |
| `ERR_CONFIRM_TOO_EARLY` | 409 |
| `ERR_SLOT_DATE_PAST` | 409 |
| `ERR_DELIVERY_BEFORE_SLOT_DATE` | 409 |
| `ERR_REPORT_DATE_OUT_OF_RANGE` | 409 |
| `ERR_FEED_DATE_PAST` | 409 |
| `ERR_APPLICATION_OUTSIDE_WINDOW` | 409 |
| `ERR_CONTRACT_NOT_YET_EFFECTIVE` | 409 |
| `ERR_CONTRACT_EXPIRED` | 409 |
| `ERR_CONTRACT_NOT_EXPIRED` | 409 |
| `ERR_CROSS_SITE_REFERENCE` | 409 |
| `ERR_DUPLICATE_GROWER_CODE` | 409 |
| `ERR_DUPLICATE_BARN_CODE` | 409 |
| `ERR_DUPLICATE_SLOT` | 409 |
| `ERR_OCCUPANCY_OVERLAP` | 409 |
| `ERR_SPACE_HEAD_EXCEEDED` | 409 |
| `ERR_FLOOR_SPACE_EXCEEDED` | 409 |
| `ERR_PHASE_MISMATCH` | 409 |
| `ERR_HEAD_COUNT_EXCEEDED` | 409 |
| `ERR_EMPTY_REPORT` | 409 |
| `ERR_WASH_ALREADY_USED` | 409 |
| `ERR_PLAN_YEAR_OVERLAP` | 409 |
| `ERR_CONTRACT_SITE_OVERLAP` | 409 |
| `ERR_WEIGHT_WINDOW_PROJECTED` | 409 |
| `ERR_FEED_BUDGET_EXCEEDED` | 409 |
| `ERR_SLOT_CAPACITY_EXCEEDED` | 409 |
| `ERR_NUTRIENT_BUDGET_EXCEEDED` | 409 |
| `ERR_LAGOON_INSUFFICIENT` | 409 |
| `ERR_LAGOON_OVER_CAPACITY` | 409 |
