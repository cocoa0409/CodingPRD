# MSP Managed IT API — Product Requirements Document

## 1. Introduction

This document specifies the behavior of the MSP Managed IT platform, a back-office system for a managed-service provider that runs computer and phone repair alongside recurring managed-IT services for small and mid-sized businesses. The platform ties together five operational disciplines that a typical MSP juggles daily: client and site records with a device inventory, remote-monitoring-and-management (RMM) health and patching, a ticketing desk with service-level commitments and remote or onsite dispatch, per-seat recurring managed-services contracts with backup and security add-ons, and the sales-adjacent flow of project quotes and hardware procurement.

The API is organized as a set of flat, peer collections rather than one deeply nested tree. Clients, sites, technicians, contracts, assets, patch jobs, tickets, dispatches, quotes, procurement orders, invoices, and seat adjustments each live at the root of the API and reference one another by identifier. The recurring theme throughout is *baseline integrity*: seat counts drive billing, ticket labor accrues against contract periods, procurement debits a client's credit ceiling, and terminating a contract must unwind everything monitored beneath it. Every workflow below is written so that these interlocking baselines stay consistent as resources move through their lifecycles.

Because service-level deadlines, quote expiry, and billing periods all depend on wall-clock reasoning, the platform runs on a **logical clock** that test harnesses and operators can set explicitly. All server-stamped timestamps are read from this clock, never from real time.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. If either header is missing or `X-User-Role` does not name a role the system recognizes, the request is rejected with `ERR_MISSING_AUTH_CONTEXT` (HTTP 401). When the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes exactly five roles: `ServiceManager`, `Dispatcher`, `Technician`, `AccountManager`, and `ClientContact`.

Two of these roles are **entity-backed**, meaning their `X-User-ID` is not an arbitrary label but the identifier of a persisted record, and ownership of a resource is decided by comparing that identifier to a foreign key on the resource:

- When `X-User-Role` is `Technician`, `X-User-ID` is the `id` of the acting `Technician`. Ownership checks on a `Dispatch` compare the dispatch's `technician_id` to `X-User-ID`; a technician acting on patch or dispatch work they are not assigned to is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).
- When `X-User-Role` is `ClientContact`, `X-User-ID` is the `id` of the acting `Client`. Ownership checks on any resource that references a client compare the resource's `client_id` to `X-User-ID`; a client contact reading or mutating another client's records is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). This is why a client contact may open, reopen, accept, or revise only within their own client.

The remaining three roles — `ServiceManager`, `Dispatcher`, and `AccountManager` — are **opaque**: their `X-User-ID` is an operator identifier not tied to any persisted entity. The server does not compare it to any entity's `id`; it functions purely to satisfy the authentication requirement and to scope role permissions.

Role authority is partitioned by discipline. A `ServiceManager` owns clients, contracts, billing, offboarding, the technician roster, and the logical clock. A `Dispatcher` runs the service desk: triaging and assigning tickets, reopening them, creating and cancelling dispatches, and scheduling patch jobs. A `Technician` executes field and remote work: starting and reporting patch jobs, marking arrival, and completing dispatches. An `AccountManager` owns quotes, procurement, and client onboarding. A `ClientContact` is the SMB customer, opening tickets and accepting or revising quotes for their own client. Exact per-endpoint authority appears in the §4 table.

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

List endpoints are paginated through two query parameters. `limit` sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets the number of items to skip and defaults to 0. Unless a specific endpoint states otherwise, list results are sorted by `created_at` in ascending order, with `id` ascending as the tie-breaker. Every list response echoes `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. The Logical Clock and Time Semantics

The platform reasons about time exclusively through a logical clock. At server startup the clock reads exactly `2026-05-01T00:00:00Z`; before any explicit set call it holds this default and never falls back to real wall-clock time. A `ServiceManager` may advance or rewind the clock by supplying a target instant in the `to_iso8601` field; the response reports the new value in a `now` field. Every server-stamped timestamp — `created_at`, `updated_at`, a ticket's `first_response_at` and `resolved_at`, and a contract's `period_start` and `period_end` — is read from this logical clock. In particular, a resource's `created_at` equals the clock value at the moment it was created. All SLA breach evaluation, quote expiry, and billing-period math read "now" from this same clock.

### 2.5. Common Resource Properties and Immutable Records

Most resources — `Client`, `Site`, `Technician`, `Contract`, `Asset`, `PatchJob`, `Ticket`, `Dispatch`, `Quote`, and `ProcurementOrder` — carry a common set of system-managed fields:

- `id`: a server-minted UUID with no type prefix.
- `created_at`: an ISO 8601 UTC timestamp with three fractional digits, stamped from the logical clock at creation.
- `updated_at`: an ISO 8601 UTC timestamp refreshed on every mutation.
- `version`: an integer that starts at 1 on creation and increments by one on every mutation. It underpins the optimistic-concurrency mechanism in §2.8.

Two record types are **immutable audit rows** and therefore carry only `id` and `created_at` — they have neither `updated_at` nor `version`: the `Invoice` (a computed billing snapshot) and the `SeatAdjustment` (a seat-change event). Once written they are never modified.

### 2.6. Cascading Termination and State Propagation

Several operations mutate more than one resource, and the platform commits every cascade as part of the same operation. Whenever a resource transitions, its `updated_at` is refreshed; entities that carry a `version` also have it incremented by one on each such mutation.

The deepest cascade begins when a client is offboarded. Offboarding moves the client's `status` from `ACTIVE` to `OFFBOARDED` and increments the client's `version`. Every one of that client's contracts currently in `ACTIVE` is then terminated exactly as if terminated directly — moving `ACTIVE` → `TERMINATED`. Terminating a contract in turn retires every `Asset` it covers whose `monitoring_status` is `ACTIVE`, moving that asset `ACTIVE` → `RETIRED`. Retiring an asset cascades once more: each of that asset's patch jobs still in `SCHEDULED` moves `SCHEDULED` → `CANCELLED`, and each of the asset's tickets in `NEW` or `IN_PROGRESS` moves to `CANCELLED`. When a ticket is cancelled from `IN_PROGRESS`, any of its dispatches still in `SCHEDULED` are cancelled as well. This four-level chain (client → contract → asset → patch jobs and tickets → dispatches) always runs to completion.

### 2.7. Nested Resource Retrieval and Request Processing Order

Requests are validated in a fixed priority order, and the first failing check determines the error returned. The order is: (1) authentication headers must be present and name a known role, else `ERR_MISSING_AUTH_CONTEXT`; (2) the acting role must be permitted for the operation, else `ERR_FORBIDDEN_ROLE`; (3) every resource identifier named in the path or body must exist, validated left-to-right, so the first missing identifier yields the not-found error for its own type (`ERR_CLIENT_NOT_FOUND`, `ERR_SITE_NOT_FOUND`, `ERR_TECHNICIAN_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_ASSET_NOT_FOUND`, `ERR_PATCH_JOB_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`, `ERR_DISPATCH_NOT_FOUND`, `ERR_QUOTE_NOT_FOUND`, or `ERR_PROCUREMENT_ORDER_NOT_FOUND`), each HTTP 404; (4) for entity-backed roles, ownership must hold, else `ERR_NOT_RESOURCE_OWNER`; (5) the target resource must be in a state that admits the requested transition, else a state error (`ERR_INVALID_STATE`, or the specific `ERR_TICKET_NOT_DISPATCHABLE` or `ERR_QUOTE_EXPIRED`); (6) any cross-entity reference must be in its required state, else `ERR_CONTRACT_NOT_ACTIVE`, `ERR_ASSET_NOT_MONITORED`, or `ERR_QUOTE_NOT_ACCEPTED`; (7) temporal-overlap checks, else `ERR_TECHNICIAN_DOUBLE_BOOKED` or `ERR_PATCH_WINDOW_CONFLICT`; (8) constraint checks, else `ERR_EMPTY_LINE_ITEMS`, `ERR_NO_SEATS_AVAILABLE`, `ERR_SEAT_FLOOR_VIOLATION`, `ERR_INVALID_SEAT_DELTA`, or `ERR_INVALID_TIME_WINDOW`; (9) the fiscal ceiling check, else `ERR_CREDIT_LIMIT_EXCEEDED`; and finally (10) the optimistic-concurrency check on seat adjustments, else `ERR_STALE_CONTRACT_VERSION`. Malformed bodies or missing required fields surface as `ERR_VALIDATION` (HTTP 400), and an enum field carrying a value outside its declared set surfaces as `ERR_INVALID_ENUM` (HTTP 400).

### 2.8. Optimistic Concurrency on Seat Adjustments

Recording a seat change against a contract is guarded by optimistic concurrency, because a seat adjustment resets the contract's billing baseline — both the current `seat_count` and the seat-day accrual that the FINAL invoice depends on. The seat-adjustment create endpoint therefore requires a non-optional `expected_contract_version` field carrying the client's last observed `version` of the target `Contract`. If the contract's `version` has advanced since the client read it — because another writer has already adjusted seats or activated or terminated the contract — the submitted `expected_contract_version` will not equal the contract's current `version`, and the request is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412). This prevents a writer holding a stale view from double-counting seats. No other endpoint accepts or requires a version field.

### 2.9. Monetary Precision and Rounding

All monetary amounts are integer cents. Wherever a calculation below calls for rounding, the method is **round half up** to whole cents unless a finer precision is explicitly stated (patch compliance, for example, rounds half up to two decimal places). Tax is applied per line item and rounded per line item before the lines are summed; the alternative of summing pre-tax then rounding once is not used and may differ by a cent. Volume-discount tier selection is made on the seat snapshot using inclusive lower bounds.

## 3. Business Logic & Workflows

### 3.1. Clients, Sites, and the Technician Roster

A `ServiceManager` registers an SMB customer by supplying a `company_name` and a `primary_contact_email`, and optionally a `credit_limit_cents` — the ceiling against which hardware procurement is drawn, defaulting to 0 if omitted. A new client opens in `status` `ACTIVE`, and its read-only `credit_available_cents` is initialized to equal `credit_limit_cents`. That available-credit figure is always derived, never set directly: it equals `credit_limit_cents` minus the sum of `total_cents` over the client's procurement orders currently in `PLACED`, and it is recomputed whenever an order is placed or cancelled.

Sites and the technician roster are simple supporting records. A site is created under a client by providing its owning `client_id`, a `label`, and an `address`; a `ServiceManager` or `AccountManager` may create one. Sites can be listed and optionally filtered by `client_id`. A `ServiceManager` registers a technician with a `full_name`, an `hourly_rate_cents` labor rate, and an optional `skill_level` that is either `JUNIOR` or `SENIOR`, defaulting to `JUNIOR`.

Offboarding a client is a `ServiceManager` action available only while the client is `ACTIVE`; attempting it on a client that is already `OFFBOARDED` is rejected with `ERR_INVALID_STATE`. The full downstream cascade of offboarding is described in §2.6.

### 3.2. The Managed-Services Contract Lifecycle

A managed-services contract is the recurring, per-seat agreement that governs a client's monitored devices, its ticket SLAs, and its billing. A `ServiceManager` or `AccountManager` drafts one by supplying the covered `client_id`, a `service_tier` of `BRONZE`, `SILVER`, or `GOLD`, a `seat_count`, a `per_seat_rate_cents`, and optionally `backup_addon` and `security_addon` booleans that each default to `false`. A fresh contract opens in `DRAFT`, with its read-only `seats_available` initialized to `seat_count` and its `period_ticket_minutes` at 0.

Activation is a `ServiceManager` action that opens the first billing period. A contract can only be activated from `DRAFT`; activating one that is not `DRAFT` is rejected with `ERR_INVALID_STATE`. Activation additionally requires that the owning client not be offboarded — a contract whose client is no longer `ACTIVE` cannot be activated and is rejected with `ERR_CONTRACT_NOT_ACTIVE` — and requires the `seat_count` to be greater than zero (a `seat_count` of zero or less is rejected with `ERR_VALIDATION`). On success the contract moves `DRAFT` → `ACTIVE`, `period_start` is stamped with the current logical clock, `period_end` is set to exactly 30 days after `period_start` (the period is treated as the half-open interval from `period_start` up to but not including `period_end`), `period_ticket_minutes` is reset to 0, and the contract's `version` increments by one.

Termination is a `ServiceManager` action permitted only from `ACTIVE`; terminating a contract in any other state is rejected with `ERR_INVALID_STATE`. Moving `ACTIVE` → `TERMINATED` triggers the asset-retirement cascade of §2.6 for every covered asset still monitored, and increments the contract's `version` by one. Termination also occurs automatically as the second link of the client-offboarding cascade.

The contract's `period_ticket_minutes` accrues billable labor as covered tickets resolve and reverses when they reopen — the mechanics of that accrual are covered in §3.5. A contract carries two derived read-only fields worth naming here: `seats_available`, computed as `seat_count` minus the count of assets assigned to the contract whose `monitoring_status` is `ACTIVE`; and `period_start`/`period_end`, the current billing window. Contracts can be listed and filtered by `client_id` and `status`.

**Seat adjustments.** A `ServiceManager` or `AccountManager` records a change to a contract's seat level by creating a `SeatAdjustment`, supplying a signed `delta`, an `effective_at` instant from which the new level applies, the optimistic-concurrency `expected_contract_version` described in §2.8, and an optional `reason`. The `delta` must be non-zero; a zero delta is rejected with `ERR_INVALID_SEAT_DELTA`. The adjustment must also not drop the contract below its committed capacity: if applying the `delta` would push `seat_count` below the number of assets currently assigned to the contract with `monitoring_status` `ACTIVE`, it is rejected with `ERR_SEAT_FLOOR_VIOLATION`. On success the contract's `seat_count` is increased by the `delta`, the resulting level is recorded on the event's read-only `seat_count_after`, `seats_available` is recomputed, and the contract's `version` increments by one. The `effective_at` instant matters later: it is the boundary that drives seat-day proration on a FINAL invoice. Seat adjustments for a contract can be listed.

### 3.3. Asset Inventory, RMM Monitoring, and Seat Consumption

An asset is a managed device. A `ServiceManager` or `AccountManager` adds one to inventory by supplying its owning `client_id`, its physical `site_id`, an `asset_type` of `LAPTOP`, `DESKTOP`, `PHONE`, or `SERVER`, and an RMM `hostname`. A new asset opens with `monitoring_status` `UNMONITORED`, a null `contract_id`, and a `patch_compliance_pct` of 100.0. Assets can be listed and filtered by `client_id`, `site_id`, `contract_id`, and `monitoring_status`.

Bringing an asset under management consumes a seat. A `ServiceManager` or `AccountManager` assigns an `UNMONITORED` asset to a contract by naming the target `contract_id`. The asset must be `UNMONITORED` (otherwise `ERR_INVALID_STATE`), the target contract must be `ACTIVE` (otherwise `ERR_CONTRACT_NOT_ACTIVE`), and the contract must have at least one free seat — its `seats_available` must be greater than zero, otherwise `ERR_NO_SEATS_AVAILABLE`. On success the asset moves `UNMONITORED` → `ACTIVE`, its `contract_id` is set to the target, the contract's `seats_available` is recomputed (falling by one as the newly active asset is now counted), and the asset's `version` increments by one.

Unassigning reverses this. A `ServiceManager` or `AccountManager` unassigns an asset that is currently `ACTIVE`; unassigning one that is not `ACTIVE` is rejected with `ERR_INVALID_STATE`. The asset moves `ACTIVE` → `UNMONITORED`, its `contract_id` is cleared to null, the contract's `seats_available` is recomputed (rising by one, compensating the earlier assignment), and the asset's `version` increments by one.

An asset may also be driven to its terminal `RETIRED` state automatically, never by direct client call, as part of the contract-termination cascade of §2.6: an `ACTIVE` asset whose covering contract terminates moves `ACTIVE` → `RETIRED`, its still-`SCHEDULED` patch jobs are cancelled, its open tickets are cancelled, and the contract's `seats_available` is recomputed.

### 3.4. RMM Patch Jobs and Compliance

Patch jobs represent scheduled RMM maintenance runs against an asset. A `Dispatcher` or `Technician` schedules one on an asset by supplying a maintenance window: a `window_start` (inclusive) and a `window_end` (exclusive), plus an optional `patch_count` that defaults to 0. The window must be well-formed — `window_end` must be strictly after `window_start`, otherwise `ERR_INVALID_TIME_WINDOW`. The asset must be actively monitored: scheduling a patch job on an asset whose `monitoring_status` is not `ACTIVE` is rejected with `ERR_ASSET_NOT_MONITORED`. The new window must also not collide with existing work: if its half-open `[window_start, window_end)` interval overlaps that of another patch job on the same asset that is still `SCHEDULED` or `RUNNING`, it is rejected with `ERR_PATCH_WINDOW_CONFLICT`. Because the intervals are half-open, two windows that merely touch at an endpoint (one ending exactly when the next begins) do not conflict. A newly scheduled patch job opens in `SCHEDULED`. Patch jobs for an asset can be listed and filtered by `status`.

Only a `Technician` executes a patch job. Starting one requires it to be `SCHEDULED` (otherwise `ERR_INVALID_STATE`) and again requires the asset's `monitoring_status` to be `ACTIVE` (otherwise `ERR_ASSET_NOT_MONITORED`); on success it moves `SCHEDULED` → `RUNNING`. Reporting a running job requires it to be `RUNNING` (otherwise `ERR_INVALID_STATE`) and carries an `outcome`, plus an optional `patch_count`. An `outcome` of `SUCCEEDED` moves the job `RUNNING` → `SUCCEEDED`; an `outcome` of `FAILED` moves it `RUNNING` → `FAILED`. Either terminal report recomputes the asset's `patch_compliance_pct`. A `SCHEDULED` job may also be cancelled automatically (`SCHEDULED` → `CANCELLED`) as part of the asset-retirement cascade.

An asset's `patch_compliance_pct` is a derived figure over that asset's terminal patch jobs only. Let the succeeded count be the number of the asset's patch jobs in `SUCCEEDED` and the failed count the number in `FAILED`; jobs in `SCHEDULED`, `RUNNING`, or `CANCELLED` are excluded entirely. When the succeeded and failed counts together total zero — no completed patch jobs yet — compliance is 100.00 by default. Otherwise it is 100 multiplied by the succeeded count, divided by the sum of the succeeded and failed counts, rounded half up to two decimal places.

### 3.5. Tickets, Service-Level Deadlines, and Billable Labor

A support ticket is opened by a `ServiceManager`, `Dispatcher`, or `ClientContact` against an `ACTIVE` governing contract. The opener supplies the requesting `client_id`, the governing `contract_id`, a `priority` of `P1`, `P2`, `P3`, or `P4`, a `subject`, and optionally an `asset_id` for the device concerned. The governing contract must be `ACTIVE`; opening a ticket against a contract that is not `ACTIVE` is rejected with `ERR_CONTRACT_NOT_ACTIVE`. A new ticket opens in `NEW`, with its `owner_technician_id`, `first_response_at`, and `resolved_at` all null. Tickets can be listed and filtered by `client_id`, `asset_id`, `contract_id`, and `status`.

**SLA deadlines and breach flags.** At creation the ticket's two service-level deadlines are fixed from the governing contract's `service_tier` and the ticket's `priority`. The response-time target, in minutes, is drawn from the tier/priority grid — for `GOLD` it is 15, 30, 60, and 120 minutes for `P1` through `P4`; for `SILVER`, 30, 60, 120, and 240; for `BRONZE`, 60, 120, 240, and 480 — and `sla_response_due_at` is the ticket's `created_at` plus that many minutes. The resolution-time target is likewise drawn from its own grid — for `GOLD`, 240, 480, 1440, and 2880 minutes for `P1` through `P4`; for `SILVER`, 480, 960, 2880, and 5760; for `BRONZE`, 960, 1920, 5760, and 11520 — and `sla_resolve_due_at` is `created_at` plus that many minutes. Both `sla_response_breached` and `sla_resolve_breached` are read-only booleans recomputed against the current clock on every read. The response deadline is breached when either the ticket has no `first_response_at` and the clock now is at or past `sla_response_due_at`, or a `first_response_at` exists but falls strictly after `sla_response_due_at`. The resolve deadline is breached, symmetrically, when either `resolved_at` is still null and now is at or past `sla_resolve_due_at`, or `resolved_at` exists but falls strictly after `sla_resolve_due_at`. Note the boundary is inclusive on the "no response yet" branch: at exactly the due instant with nothing recorded, the deadline counts as breached.

**Assignment and first response.** A `Dispatcher` assigns a `NEW` ticket to a technician by naming the `technician_id`; assigning a ticket that is not `NEW` is rejected with `ERR_INVALID_STATE`. The ticket moves `NEW` → `IN_PROGRESS`, its `owner_technician_id` is set to the named technician, and `first_response_at` is stamped with the current clock — but only if it was still null, so a later reopen-and-reassign does not overwrite the original first-response instant.

**Resolution and the billing accrual.** Resolving a ticket requires it to be `IN_PROGRESS` (otherwise `ERR_INVALID_STATE`) and may be done by a `Technician` or a `Dispatcher`. On resolve the ticket moves `IN_PROGRESS` → `RESOLVED`, `resolved_at` is stamped from the clock, and the ticket's `billable_minutes` is finalized. That finalized labor is then added to the governing contract's `period_ticket_minutes`. Resolution also happens indirectly when a dispatch that is flagged to resolve its ticket completes (see §3.6).

**Reopening.** A `Dispatcher` or `ClientContact` may reopen a `RESOLVED` ticket; reopening one that is not `RESOLVED` is rejected with `ERR_INVALID_STATE`. The ticket moves `RESOLVED` → `IN_PROGRESS`, its `resolved_at` returns to null, and — crucially for billing integrity — the contract's `period_ticket_minutes` has the ticket's previously accrued `billable_minutes` subtracted back out, exactly reversing the accrual that the earlier resolve applied.

**Billable minutes.** The read-only `billable_minutes` is an *estimated* figure until real labor lands, then an *actual* one. If no dispatch on the ticket has reached `COMPLETED`, the value is the priority standard — 240 minutes for `P1`, 120 for `P2`, 60 for `P3`, and 30 for `P4`. Once at least one dispatch on the ticket has completed, the value instead becomes the sum of `logged_minutes` across all of that ticket's completed dispatches.

A ticket may also be cancelled automatically (from `NEW` or `IN_PROGRESS` to `CANCELLED`) as part of the asset-retirement cascade of §2.6; when cancelled from `IN_PROGRESS`, its still-`SCHEDULED` dispatches are cancelled with it.

### 3.6. Dispatch: Remote and Onsite Field Work

A dispatch is a scheduled unit of remote or onsite labor against a ticket. A `Dispatcher` creates one on a ticket by supplying the `technician_id`, a `mode` of `REMOTE` or `ONSITE`, a `scheduled_start` (inclusive) and `scheduled_end` (exclusive), and an optional `resolves_ticket` flag that defaults to `true`. The window must be well-formed — `scheduled_end` strictly after `scheduled_start`, otherwise `ERR_INVALID_TIME_WINDOW` — and the parent ticket must be dispatchable, meaning `IN_PROGRESS`; creating a dispatch on a ticket that is not `IN_PROGRESS` is rejected with `ERR_TICKET_NOT_DISPATCHABLE`. A new dispatch opens in `SCHEDULED`.

**Technician double-booking.** To keep a field technician's calendar realistic, the system stamps each dispatch with a read-only `travel_buffer_minutes` — 30 minutes for an `ONSITE` dispatch and 0 for a `REMOTE` one — that is applied *after* the scheduled window for conflict math. The technician's effective occupancy for a dispatch is therefore the interval from `scheduled_start` up to `scheduled_end` plus `travel_buffer_minutes`. When creating a dispatch, if that buffered interval overlaps the buffered interval of another non-cancelled dispatch already held by the same technician, the create is rejected with `ERR_TECHNICIAN_DOUBLE_BOOKED`.

**Execution.** Only a `Technician` executes a dispatch, and the path branches by `mode`. An `ONSITE` dispatch is marked arrived first — that transition requires the dispatch to be `SCHEDULED` and its `mode` to be `ONSITE` (a `REMOTE` dispatch never enters the arrived state, and either violation is rejected with `ERR_INVALID_STATE`), moving `SCHEDULED` → `ON_SITE`. Completing an onsite dispatch then requires it to be in `ON_SITE`. A `REMOTE` dispatch skips arrival entirely and completes straight from `SCHEDULED`; that completion requires the dispatch to be `SCHEDULED` and its `mode` to be `REMOTE` (an `ONSITE` dispatch must arrive before it can complete, and either violation is rejected with `ERR_INVALID_STATE`). Either way, completion carries the `logged_minutes` of actual labor, records them on the dispatch, moves the dispatch to `COMPLETED`, and switches the parent ticket's `billable_minutes` onto its actual basis. If the dispatch's `resolves_ticket` flag is set, completing it also resolves the parent ticket, moving it `IN_PROGRESS` → `RESOLVED` and running the same resolve side effects — stamping `resolved_at` and accruing the ticket's `billable_minutes` into the contract's `period_ticket_minutes`.

**Cancellation.** A `Dispatcher` may cancel a `SCHEDULED` dispatch, moving `SCHEDULED` → `CANCELLED`; cancelling one that is not `SCHEDULED` is rejected with `ERR_INVALID_STATE`. Dispatches can be listed and filtered by `ticket_id`, `technician_id`, and `status`.

### 3.7. Quotes, Projects, and Hardware Procurement

An `AccountManager` prepares a quote for a client by supplying the `client_id`, a `quote_type` of either `PROJECT` (project work) or `PROCUREMENT` (hardware), a `title`, a non-empty `line_items` array, a `valid_until` expiry instant, and an optional `tax_rate` that defaults to 0.08. Each entry in `line_items` carries a `description`, a `unit_price_cents`, and a `qty`. A new quote opens in `DRAFT`. Two read-only money figures are computed at write time: `subtotal_cents` is the sum over the line items of `unit_price_cents` multiplied by `qty` (pre-tax); `total_cents` is computed line by line — for each line, take `unit_price_cents` multiplied by `qty`, multiply by one plus the `tax_rate`, and round that line half up to whole cents — and only then sum the rounded lines. Quotes can be listed and filtered by `client_id` and `status`.

The quote lifecycle is a small loop. An `AccountManager` sends a `DRAFT` quote — this requires the quote to be `DRAFT` (otherwise `ERR_INVALID_STATE`) and its `line_items` to be non-empty (otherwise `ERR_EMPTY_LINE_ITEMS`) — moving it `DRAFT` → `SENT`. The `ClientContact` for that client then either accepts or asks for changes. Accepting requires the quote to be `SENT` (otherwise `ERR_INVALID_STATE`) and the clock now to be strictly before `valid_until`; if now has reached or passed `valid_until` the quote is treated as expired and the accept is rejected with `ERR_QUOTE_EXPIRED`, moving it `SENT` → `ACCEPTED` only on success. Requesting a revision requires the quote to be `SENT` (otherwise `ERR_INVALID_STATE`) and reverts it `SENT` → `DRAFT` so the account manager can revise its `line_items`. Separately, a `SENT` quote is treated as `EXPIRED` — a terminal state — once the clock reaches or passes `valid_until`; this expiry is evaluated whenever the quote is read or an accept is attempted.

Hardware is actually billed through a procurement order. An `AccountManager` creates one by supplying the billed `client_id`, a non-empty `line_items` array (same `description`, `unit_price_cents`, `qty` shape), an optional `tax_rate` defaulting to 0.08, and an optional `quote_id` linking an accepted `PROCUREMENT` quote it draws from. The order's read-only `total_cents` is computed by the same per-line, round-then-sum rule as a quote. A new order opens in `DRAFT`. Orders can be listed and filtered by `client_id`, `quote_id`, and `status`.

Placing an order commits the client's credit and is available to an `AccountManager` or `ServiceManager`. The order must be `DRAFT` (otherwise `ERR_INVALID_STATE`). If a `quote_id` is linked, that quote must be `ACCEPTED`, otherwise the place is rejected with `ERR_QUOTE_NOT_ACCEPTED`. The order's `total_cents` must not exceed the client's `credit_available_cents` at place time; an order that would breach the ceiling is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`. On success the order moves `DRAFT` → `PLACED` and the client's `credit_available_cents` is recomputed, debited by `total_cents`. Cancelling an order is available to an `AccountManager` or `ServiceManager` from either `DRAFT` or `PLACED`; cancelling from any other state is rejected with `ERR_INVALID_STATE`. Cancelling moves the order to `CANCELLED`, and if it had been `PLACED`, the client's `credit_available_cents` is recomputed, refunding `total_cents` and compensating the earlier debit.

### 3.8. Recurring Billing: Provisional and Final Invoices

A `ServiceManager` generates an invoice for a contract's current period by naming the `variant`: `PROVISIONAL` for a mid-period estimate or `FINAL` for the end-of-period settlement. Every invoice is an immutable snapshot; it records the billed `contract_id`, copies `period_start` and `period_end` from the contract, and computes a family of money fields. Invoice generation requires the contract to already have an open billing period — a contract with a null `period_start` or `period_end` (i.e. still `DRAFT`) is rejected with `ERR_INVALID_STATE`.

The two variants differ only in how the base seat charge is derived. For a `PROVISIONAL` invoice, `seat_count_snapshot` is the contract's current `seat_count`, `total_seat_days` is 0, and `base_seat_charge_cents` is `seat_count_snapshot` multiplied by `per_seat_rate_cents` — the full-period rate on the current seat level, ignoring any intra-period seat changes. For a `FINAL` invoice, the seat level is prorated across the period by seat-days. Walk the seat timeline over the period: begin at the seat level in force at `period_start`, then apply, in order of `effective_at` ascending with `created_at` ascending as the tie-break, every `SeatAdjustment` whose `effective_at` falls within the half-open period `[period_start, period_end)`. For each resulting sub-interval, accrue that sub-interval's seat level multiplied by its whole number of days; `total_seat_days` is the sum of those seat-days. For the FINAL variant, `seat_count_snapshot` is the seat level in force at `period_end`, and `base_seat_charge_cents` is `per_seat_rate_cents` multiplied by `total_seat_days`, divided by 30 (the period length in days), rounded half up to whole cents. The two variants coincide when no seat adjustment occurred mid-period and diverge whenever one did.

The remaining charges are computed identically for both variants, all on `seat_count_snapshot`. The `volume_discount_cents` is `base_seat_charge_cents` multiplied by a discount rate selected from the seat snapshot by inclusive lower bound — 0.00 for a snapshot of 1 through 9 seats, 0.05 for 10 through 24, 0.10 for 25 through 49, and 0.15 for 50 or more — with the product rounded half up to whole cents. The `addon_charge_cents` adds a per-seat surcharge for each enabled add-on: 800 cents per seat when `backup_addon` is enabled plus 1500 cents per seat when `security_addon` is enabled, each multiplied by `seat_count_snapshot`. The `overage_charge_cents` bills ticket labor beyond what the tier includes: the included allowance is 600 minutes for `BRONZE`, 1200 for `SILVER`, and 3000 for `GOLD`, the overage is the greater of zero and the contract's `period_ticket_minutes` minus that allowance, and the charge is that overage multiplied by 250 cents per minute. Finally, the invoice's `total_cents` is `base_seat_charge_cents`, minus `volume_discount_cents`, plus `addon_charge_cents`, plus `overage_charge_cents`. Invoices for a contract can be listed.

## 4. Endpoint Definitions

Operations that create a new, standalone resource return `201 Created`. Operations that modify an existing resource — including state transitions and the various lifecycle actions — return `200 OK`. In the table below, "All roles" denotes every one of the five roles; reads by a `ClientContact` are further scoped to that contact's own client, and reads by an entity-backed role obey the ownership rules of §2.1.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock | ServiceManager |
| POST | `/clients` | Create a client | ServiceManager |
| GET | `/clients/{id}` | Get a client | All roles |
| POST | `/clients/{id}/offboard` | Offboard a client (cascades) | ServiceManager |
| POST | `/sites` | Create a site under a client | ServiceManager, AccountManager |
| GET | `/sites/{id}` | Get a site | All roles |
| GET | `/sites` | List sites (filter by client_id) | All roles |
| POST | `/technicians` | Register a technician | ServiceManager |
| POST | `/contracts` | Create a managed-services contract | ServiceManager, AccountManager |
| GET | `/contracts/{id}` | Get a contract | All roles |
| GET | `/contracts` | List contracts (filter by client_id, status) | All roles |
| POST | `/contracts/{id}/activate` | Activate a draft contract | ServiceManager |
| POST | `/contracts/{id}/terminate` | Terminate an active contract (cascades) | ServiceManager |
| POST | `/contracts/{id}/seat-adjustments` | Record a seat change (OCC-guarded) | ServiceManager, AccountManager |
| GET | `/contracts/{id}/seat-adjustments` | List seat adjustments | All roles |
| POST | `/contracts/{id}/invoices` | Generate a provisional or final invoice | ServiceManager |
| GET | `/contracts/{id}/invoices` | List invoices | All roles |
| POST | `/assets` | Add an asset to inventory | ServiceManager, AccountManager |
| GET | `/assets/{id}` | Get an asset | All roles |
| GET | `/assets` | List assets (filter by client_id, site_id, contract_id, monitoring_status) | All roles |
| POST | `/assets/{id}/assign-contract` | Assign an asset to a contract (consumes a seat) | ServiceManager, AccountManager |
| POST | `/assets/{id}/unassign-contract` | Unassign an asset (releases a seat) | ServiceManager, AccountManager |
| POST | `/assets/{id}/patch-jobs` | Schedule a patch job | Dispatcher, Technician |
| GET | `/assets/{id}/patch-jobs` | List patch jobs for an asset (filter by status) | All roles |
| POST | `/patch-jobs/{id}/start` | Start a scheduled patch job | Technician |
| POST | `/patch-jobs/{id}/report` | Report a running patch job outcome | Technician |
| POST | `/tickets` | Open a support ticket | ServiceManager, Dispatcher, ClientContact |
| GET | `/tickets/{id}` | Get a ticket | All roles |
| GET | `/tickets` | List tickets (filter by client_id, asset_id, contract_id, status) | All roles |
| POST | `/tickets/{id}/assign` | Assign a ticket to a technician | Dispatcher |
| POST | `/tickets/{id}/resolve` | Resolve an in-progress ticket | Technician, Dispatcher |
| POST | `/tickets/{id}/reopen` | Reopen a resolved ticket | Dispatcher, ClientContact |
| POST | `/tickets/{id}/dispatches` | Create a dispatch for a ticket | Dispatcher |
| GET | `/dispatches/{id}` | Get a dispatch | All roles |
| GET | `/dispatches` | List dispatches (filter by ticket_id, technician_id, status) | All roles |
| POST | `/dispatches/{id}/arrive` | Mark an onsite dispatch arrived | Technician |
| POST | `/dispatches/{id}/complete` | Complete a dispatch, logging labor | Technician |
| POST | `/dispatches/{id}/cancel` | Cancel a scheduled dispatch | Dispatcher |
| POST | `/quotes` | Create a project or procurement quote | AccountManager |
| GET | `/quotes/{id}` | Get a quote (auto-expires sent quotes) | All roles |
| GET | `/quotes` | List quotes (filter by client_id, status) | All roles |
| POST | `/quotes/{id}/send` | Send a draft quote | AccountManager |
| POST | `/quotes/{id}/accept` | Accept a sent quote | ClientContact |
| POST | `/quotes/{id}/request-revision` | Request a revision, reverting to draft | ClientContact |
| POST | `/procurement-orders` | Create a procurement order | AccountManager |
| GET | `/procurement-orders/{id}` | Get a procurement order | All roles |
| GET | `/procurement-orders` | List procurement orders (filter by client_id, quote_id, status) | All roles |
| POST | `/procurement-orders/{id}/place` | Place an order, debiting client credit | AccountManager, ServiceManager |
| POST | `/procurement-orders/{id}/cancel` | Cancel an order, refunding if placed | AccountManager, ServiceManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH_CONTEXT` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_ENUM` | 400 |
| `ERR_INVALID_TIME_WINDOW` | 400 |
| `ERR_EMPTY_LINE_ITEMS` | 422 |
| `ERR_INVALID_SEAT_DELTA` | 422 |
| `ERR_SEAT_FLOOR_VIOLATION` | 422 |
| `ERR_NO_SEATS_AVAILABLE` | 422 |
| `ERR_CLIENT_NOT_FOUND` | 404 |
| `ERR_SITE_NOT_FOUND` | 404 |
| `ERR_TECHNICIAN_NOT_FOUND` | 404 |
| `ERR_CONTRACT_NOT_FOUND` | 404 |
| `ERR_ASSET_NOT_FOUND` | 404 |
| `ERR_PATCH_JOB_NOT_FOUND` | 404 |
| `ERR_TICKET_NOT_FOUND` | 404 |
| `ERR_DISPATCH_NOT_FOUND` | 404 |
| `ERR_QUOTE_NOT_FOUND` | 404 |
| `ERR_PROCUREMENT_ORDER_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_TICKET_NOT_DISPATCHABLE` | 409 |
| `ERR_QUOTE_EXPIRED` | 409 |
| `ERR_CONTRACT_NOT_ACTIVE` | 409 |
| `ERR_ASSET_NOT_MONITORED` | 409 |
| `ERR_QUOTE_NOT_ACCEPTED` | 409 |
| `ERR_TECHNICIAN_DOUBLE_BOOKED` | 409 |
| `ERR_PATCH_WINDOW_CONFLICT` | 409 |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 |
| `ERR_STALE_CONTRACT_VERSION` | 412 |
