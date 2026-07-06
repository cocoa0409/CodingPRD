# SEO & Digital-Marketing Agency API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the SEO & Digital-Marketing Agency platform, the operational backbone through which a full-service agency runs its book of business. The agency onboards client companies, audits their websites, builds keyword strategy, schedules and delivers SEO work, manages paid-media spend, optimizes local listings, and bills everything through retainers governed by signed contracts. A large share of the agency's work is also sold through white-label resellers who re-brand the service for their own customers, which means every price the platform computes must respect a reseller's resale markup while the agency continues to reason about its own wholesale economics.

The system exists to make a tangle of interdependent commercial promises behave predictably. Retainer credits are a conserved resource: they are granted on a billing cycle, reserved when work is scheduled, burned when work is approved, and partially rolled into the next cycle — and at no point may the platform manufacture credits out of nothing or let a sprint over-commit beyond its capacity. Paid-media management fees ride on a marginal tiered markup over cumulative ad spend, disputes can claw spend back, and account health is a living score that reacts to rank momentum, overdue work, and unresolved disputes. The contracts that bind all of this carry renewal and early-termination economics that must be recomputed at exactly the right moments. The remainder of this document defines the entities, their lifecycles, the precise calculations, the validation order, and the API surface that together hold these guarantees in place.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which declares the capacity in which they act. The platform recognizes exactly four roles, spelled precisely as `AgencyAdmin`, `AccountManager`, `Reseller`, and `Client`. A request that omits either header, or carries a malformed value, is rejected with `ERR_MISSING_AUTH`. A request whose role is syntactically valid but not permitted to perform the targeted operation is rejected with `ERR_FORBIDDEN_ROLE`. The two unauthenticated bootstrap operations are reseller creation and client creation, together with the logical-clock control endpoint, which do not require the auth headers; every other operation does.

Two of the roles are **opaque operators** and two are **entity-backed**. When `X-User-Role` is `AgencyAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`. When `X-User-Role` is `AccountManager`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity, recorded but never matched against an entity `id`. When `X-User-Role` is `Reseller`, `X-User-ID` is the `id` of the acting `Reseller`; ownership checks on any resource that references a reseller compare that resource's `reseller_id` (directly, or through its parent `Client.reseller_id`) to `X-User-ID`. When `X-User-Role` is `Client`, `X-User-ID` is the `id` of the acting `Client`; ownership checks on any resource that references a client compare the resource's `client_id` to `X-User-ID`. An entity-backed actor that targets a resource it does not own — a `Client` acting on another client's data, or a `Reseller` acting on a client that is not its own — is rejected with `ERR_NOT_RESOURCE_OWNER`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, may be no smaller than 1, and may be no larger than 100. The `offset` parameter is the number of leading items to skip and defaults to 0. A `limit` that is non-integer or outside the 1-to-100 range, or an `offset` that is non-integer or negative, is rejected with `ERR_INVALID_REQUEST`. Unless an endpoint states otherwise, list results are ordered by their `created_at` timestamp in ascending order, with insertion order used as a stable tie-break among records sharing a `created_at`. Every list response surfaces `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `total_count` is the count of all matching records before pagination and `has_more` is true exactly when `offset` plus the number of returned items is less than `total_count`.

### 2.4. Common Resource Properties and Versioning

Every resource carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp recorded in ISO 8601 UTC with three fractional digits. Most resources additionally carry an `updated_at` timestamp in the same format and an integer `version` that begins at its creation value and increments by one on every mutation — including mutations to computed and derived fields. Whenever a resource's state, a derived balance, or any stored field changes, the platform refreshes `updated_at` and increments `version`.

Three entities are append-only readings or immutable records and therefore carry only `id` and `created_at`; for these, both `updated_at` and `version` are absent. These are the `SiteAudit` (a recorded crawl result), the `RankSnapshot` (a single SERP reading), and the `Report` (a generated point-in-time summary). Every other entity — `Reseller`, `Client`, `KeywordTarget`, `Retainer`, `Contract`, `Sprint`, `Deliverable`, `AdCampaign`, `AdSpendDispute`, and `GbpListing` — carries the full `updated_at` and `version` pair.

### 2.5. Hierarchical Consistency and Cascading State

The platform keeps parent and child resources mutually consistent, and several operations on a parent deliberately cascade into its children. When such a cascade fires, every entity it touches is a genuine mutation: its state changes, its `updated_at` is refreshed, and its `version` increments. Cascades are described in full alongside the workflows that trigger them in §3, but the governing principle is uniform — a parent transition that suspends, closes, ends, or cancels its dependents drives each dependent through its own legitimate transition rather than silently editing fields. The server may also transition a parent automatically when a child operation satisfies the parent's criteria (for example, activating a retainer can promote its client), and each such bubble-up is an independent mutation of the affected resource.

### 2.6. Nested Resource Retrieval and Referential Existence

Several paths embed a resource identifier (for example, a client identifier preceding its audits, keywords, snapshots, or reports). The platform validates path identifiers strictly left to right and rejects the request with `ERR_NOT_FOUND` at the first identifier that does not resolve to an existing resource, before examining anything to its right. The same existence guarantee covers every foreign key supplied in a request body: a payload that references a non-existent client, retainer, sprint, campaign, or keyword is rejected with `ERR_NOT_FOUND`. This existence pass runs after authentication and authorization but before request-body well-formedness and before any business rule.

### 2.7. Validation Order

When several checks could fail a single request, they are evaluated in a fixed priority so that the returned error is deterministic. The order is: (1) presence and well-formedness of the auth headers, failing with `ERR_MISSING_AUTH`, where both `X-User-Role` (which must be one of the four recognized roles) and `X-User-ID` (which must be present and non-empty) are mandatory for every role — including the opaque-operator roles `AgencyAdmin` and `AccountManager` — and a missing or unrecognized `X-User-Role` is reported before a missing `X-User-ID`; (2) whether the acting role is permitted for the endpoint, failing with `ERR_FORBIDDEN_ROLE`; (3) for entity-backed actors, ownership of the targeted resource, failing with `ERR_NOT_RESOURCE_OWNER`; (4) existence of every path and foreign-key-referenced resource, validated left to right, failing with `ERR_NOT_FOUND`; (5) request-body well-formedness — required fields present, enum values legal, numbers within their declared ranges — failing with `ERR_INVALID_REQUEST`; (6) that the target resource is in a state that permits the requested transition, failing with `ERR_INVALID_STATE`; (7) the optimistic-concurrency version check, failing with `ERR_STALE_RETAINER_VERSION`. Only after all seven of these pass does the platform evaluate the endpoint's specific business rules (cross-entity preconditions, capacity, credits, dispute, budget, temporal, and uniqueness checks), which are described in §3 next to the workflows they guard. The earlier a check sits in this list, the higher its precedence; a higher-priority failure masks every lower-priority one.

### 2.8. Optimistic Concurrency on the Retainer Credit Pool

Two operations mutate a retainer's conserved credit pool in a way that would be unsafe to perform against a stale view, and both therefore require an optimistic-concurrency token. Advancing a retainer's billing cycle requires the request to carry `expected_retainer_version` equal to the retainer's current `version`; if another writer has advanced that version since the client last read the retainer, the rollover is rejected with `ERR_STALE_RETAINER_VERSION` at HTTP 412, which prevents a second rollover from doubling a carry-forward against a cycle that no longer exists. Likewise, assigning a deliverable — which reserves credits against the retainer — requires `expected_retainer_version` to match the retainer's current `version`; if a concurrent assignment or rollover has already moved the credit balance and bumped the version, the reservation is refused with `ERR_STALE_RETAINER_VERSION` at HTTP 412 rather than over-committing the pool against a balance the writer never saw. On both operations `expected_retainer_version` is a required integer field, so a body that omits it or supplies a non-integer fails request-body well-formedness with `ERR_INVALID_REQUEST` (priority 5); the concurrency comparison itself sits at priority 7 and is therefore evaluated only after the priority-6 state check passes (an invalid target state surfaces `ERR_INVALID_STATE` before any stale-version check). No other endpoint accepts or requires a version field; operations not named here perform no concurrency check.

### 2.9. The Credit Ledger Principle

Retainer credits are conserved, never created from nothing. Each retainer exposes four credit figures that always reconcile: `credits_granted` is the total made available in the current cycle, `credits_committed` is the amount reserved by deliverables that are in progress, `credits_consumed` is the amount permanently burned by approved deliverables in the current cycle, and `credits_available` is exactly `credits_granted` minus `credits_committed` minus `credits_consumed`. Committing a deliverable moves credits into `credits_committed`; approving it moves the same amount out of `credits_committed` and into `credits_consumed`, leaving `credits_available` unchanged at the moment of approval; rejecting or cancelling a reserved deliverable releases its amount back out of `credits_committed`. All credit quantities are whole integers. The precise rebalancing for each transition lives with that transition's narrative in §3.

### 2.10. Monetary Precision and Rounding

All monetary amounts are stored and returned as integer cents. Calculations that introduce fractional cents are reduced to whole cents by the rounding rule the specific calculation names: ad-management fees, reseller-marked billing prices, and early-termination fees each round **down** (floor) at the point their narrative specifies, while score-style computations round **half up** to the stated precision. Where a calculation produces a non-integer score, the result is rounded half up to the stated number of decimal places — to a whole integer for the audit composite, the GBP optimization score, and the account health score, and to two decimal places for the keyword priority score, the report average rank, and the report rank momentum. No monetary or score field is ever stored with more precision than its rule allows.

### 2.11. The Logical Clock

The platform reads time from a logical clock rather than the wall clock, so that temporal rules — sprint windows, overdue-deliverable penalties, and reporting periods — are deterministic under test. On startup the clock reads exactly `2026-03-01T00:00:00Z` and never falls back to wall-clock time; before any clock-setting call it returns precisely this default. An administrator may advance the clock to a supplied instant via the required `to_iso8601` field (a missing, empty, or unparseable value fails with `ERR_INVALID_REQUEST`); doing so immediately affects which deliverables count as overdue and which sprint windows contain "now". The clock-setting call returns `200 OK` with the standard success envelope whose `data` is an empty object rather than echoing the clock state.

## 3. Business Logic & Workflows

### 3.1. Resellers, Clients, and the Onboarding Arc

The agency's commercial graph begins with two roots. A `Reseller` is a white-label partner created by an agency administrator, identified to its own customers by a `brand_name` and characterized by two economic rates: `markup_pct`, the resale markup it applies on top of the agency's wholesale retainer price (a fraction at least 0.0 and at most 1.0, so 0.30 means a thirty-percent uplift), and `ppc_management_pct`, the reseller's standing paid-media management rate applied to ad spend (a fraction at least 0.0 and at most 0.5, defaulting to 0.15 when not supplied). A reseller is always created in `ACTIVE` `status`; resellers have no suspend or close lifecycle in this scope.

A `Client` represents a customer company under management, described by a `company_name` and a `primary_domain` (the root domain the agency works on, such as example.com). A client may belong to a reseller, in which case its `reseller_id` points at that `Reseller`; a direct agency client leaves `reseller_id` null and carries no white-label markup. Every client begins life in `PROSPECT` `status` with a `health_score` of 100 and an `open_dispute_count` of 0. The client lifecycle proceeds `PROSPECT → AUDITED → ACTIVE`, may move `ACTIVE → PAUSED` and back `PAUSED → ACTIVE`, and finally reaches the terminal `CHURNED`. The `health_score` is a derived account-health figure in the range 0 to 100, and `open_dispute_count` is a derived count of the client's disputes currently `OPEN` or `UNDER_REVIEW`; both are recomputed by the platform rather than supplied.

The first substantive step is the site audit. An account manager records a `SiteAudit` against a `PROSPECT` client by supplying three sub-scores, each an integer from 0 to 100: a `technical_score` for crawl health, a `content_score` for on-page content, and a `backlink_score` for off-page authority. Recording the audit computes its `composite_score` and advances the client from `PROSPECT` to `AUDITED`, incrementing the client's `version`. The audit may only be recorded while the client is in `PROSPECT`. The `composite_score` is a weighted blend: weight the `technical_score` at four-tenths, the `content_score` at thirty-five hundredths, and the `backlink_score` at twenty-five hundredths, sum the three weighted parts, and round that sum half up to the nearest whole integer between 0 and 100. The three weights sum to one.

Once a client is `AUDITED` or `ACTIVE`, the agency builds keyword strategy and stands up retainers (§3.2 and §3.4). A client moves to `ACTIVE` as a bubble-up: when the client is `AUDITED` and its first retainer becomes `ACTIVE`, the platform promotes the client from `AUDITED` to `ACTIVE`, recomputes its `health_score`, and increments the client's `version`.

Pausing an `ACTIVE` client is an account-manager action that drives several cascades at once: it moves the client `ACTIVE → PAUSED`, conditionally cascades each of the client's retainers that is currently `ACTIVE` to `SUSPENDED` (retainers in any other status are left alone), moves each of the client's ad campaigns whose `lifecycle_status` is `LIVE` to `PAUSED`, and increments the client's `version`. Resuming a `PAUSED` client reverses the retainer suspension only: it moves the client `PAUSED → ACTIVE`, cascades each retainer currently `SUSPENDED` back to `ACTIVE`, and increments the client's `version`; campaigns paused by the earlier cascade are not automatically relaunched.

Churning a client is terminal and is permitted from either `ACTIVE` or `PAUSED`. It is blocked while the client still has any `Contract` in `ACTIVE` or `RENEWED` status — such a contract must be terminated first, and a premature churn is rejected with `ERR_CONTRACT_STILL_BINDING`. When churn proceeds from `ACTIVE`, it cascades every one of the client's retainers to `CLOSED`; each newly `CLOSED` retainer in turn cancels its own non-terminal deliverables, releasing their committed credits (a depth-three chain from client to retainer to deliverable); every ad campaign whose `lifecycle_status` is `DRAFT`, `LIVE`, or `PAUSED` is moved to `ENDED`; and the client's `version` increments. When churn proceeds from `PAUSED`, it likewise cascades all of the client's retainers to `CLOSED` and increments the client's `version`. Reading a single client recomputes and returns its `health_score`.

### 3.2. Keyword Strategy and Rank Tracking

Keyword strategy is captured as `KeywordTarget` records, each created against a client by supplying the `client_id`, the target `phrase`, an estimated monthly `search_volume` (zero or greater), and a keyword `difficulty` from 0 to 100. Creation computes a `priority_score`, initializes `current_rank` to 0 and `best_rank` to 0, and starts the target in `PLANNED` `status`. The `phrase` must be unique among the client's keyword targets that are not `DROPPED`; a colliding phrase is rejected with `ERR_DUPLICATE_RESOURCE`. The `priority_score` is the opportunity score `search_volume` multiplied by the quantity one minus `difficulty` divided by one hundred, rounded half up to two decimal places — so a high-volume, low-difficulty phrase ranks highest in the strategy backlog. Reading a single keyword target recomputes its `priority_score`.

A keyword target moves `PLANNED → TRACKING` when an account manager activates tracking, which is permitted only while the parent client is `AUDITED` or `ACTIVE` — otherwise the request is rejected with `ERR_CLIENT_NOT_AUDITED` — and increments the target's `version`. A target may be dropped to the terminal `DROPPED` from either `PLANNED` or `TRACKING`, also incrementing its `version`. The `current_rank` field holds the latest tracked SERP position, where 0 means not yet ranked or unranked and 1 means the top position; `best_rank` holds the best (lowest positive) rank ever recorded, with 0 meaning never ranked.

Rank readings arrive as `RankSnapshot` records appended to a keyword target. Each snapshot records the `keyword_target_id` it belongs to, a `position` (an integer from 0 to 100, where 0 means the page fell outside the tracked range beyond position 100), the estimated `organic_traffic` (sessions attributed in this reading, zero or greater), and the instant the reading was taken in `observed_at`; if `observed_at` is omitted it defaults to the logical clock's current value. Appending a snapshot sets the keyword target's `current_rank` to the snapshot's `position`, and when that `position` is greater than 0 it lowers `best_rank` to the smaller of the existing best rank and the new position (treating a never-ranked best rank as effectively unbounded so the first positive reading becomes the best). Snapshots are immutable readings.

### 3.3. Reporting, Rank Momentum, and Account Health

A `Report` is a generated point-in-time summary an account manager produces over a window for a client, supplying a `period_start` (inclusive) and a `period_end` (exclusive) that must lie after the start. Generation computes three figures over the client's data and recomputes the client's `health_score`. The `avg_rank` is the mean `current_rank` across the client's `TRACKING` keyword targets whose `current_rank` is greater than 0 (ranked targets only), rounded half up to two decimal places, and is 0.0 when no such target exists. The `total_traffic` is the sum of `organic_traffic` across the rank snapshots that belong to any of this client's keyword targets (regardless of each target's `status`) and whose `observed_at` reading falls within the half-open window, that is at or after `period_start` and strictly before `period_end`. The `rank_momentum` is a signed figure that feeds account health.

To compute `rank_momentum`, take the client's `TRACKING` keyword targets and, for each, replay its rank snapshots whose `observed_at` falls within the half-open window from `period_start` up to but not including `period_end`, ordered by `observed_at` ascending and, where two readings share an instant, by the snapshot's `created_at` ascending as the tie-break (never by identifier). For each keyword with at least one in-window snapshot, its improvement is the position of the first in-window reading minus the position of the last in-window reading — a positive number means the rank moved toward position 1, an improvement — and any `position` of 0, meaning unranked, is treated as 101 for this arithmetic. The `rank_momentum` is the mean of these per-keyword improvements across the keywords that had at least one in-window snapshot, rounded half up to two decimal places. If no `TRACKING` keyword has any in-window snapshot, the mean is taken over the empty set and `rank_momentum` is defined as 0.0 rather than an error.

Reporting periods for one client may not overlap, and a mandatory one-day buffer separates them. Treat each prior period as the closed interval from its `period_start` to its `period_end` inclusive, then require a one-day gap on each side: a new `period_start` must be strictly greater than the prior period's `period_end` plus one day, and a new `period_end` must be strictly less than the next period's `period_start` minus one day. Periods that touch or fall within the one-day buffer are rejected with `ERR_REPORT_PERIOD_OVERLAP`, compared against all of the client's prior reports.

The `health_score` is recomputed when a client activates, when one of its disputes resolves or is withdrawn, and when a report is generated. Begin from a base of 100. Add a momentum term equal to the client's latest report `rank_momentum` multiplied by two, clamped to lie between negative thirty and positive thirty (use 0 if the client has no report yet). Subtract an overdue penalty of five for each of the client's deliverables that is currently `ASSIGNED`, `IN_PROGRESS`, or `IN_REVIEW` and whose sprint's `ends_at` is earlier than the current logical-clock time. Subtract a dispute penalty of ten for each unit of the client's `open_dispute_count`. Round the result half up to a whole number and clamp it to the range 0 through 100.

### 3.4. Retainers and the Billing Cycle

A `Retainer` is the billing vehicle for a client's recurring SEO work, created against a client by supplying the `client_id`, a `tier` of `STARTER`, `GROWTH`, or `DOMINATE`, a `monthly_credits` allotment granted each cycle (zero or greater), a `wholesale_price_cents` agency price before any reseller markup (zero or greater), and optionally a `rollover_cap_pct` (a fraction at least 0.0 and at most 1.0, defaulting to 0.25) capping how much of the monthly allotment may roll forward. A new retainer starts in `DRAFT` `status` with `cycle_index` 0 and every credit figure — `credits_granted`, `credits_committed`, `credits_consumed`, `credits_available` — and `billing_price_cents` at 0.

Activating a retainer moves it `DRAFT → ACTIVE`, and is permitted only while the parent client is `AUDITED` or `ACTIVE`, otherwise rejected with `ERR_CLIENT_NOT_AUDITED`. Activation grants the cycle-zero allotment — `credits_granted` is set to `monthly_credits`, since cycle zero has no rollover — recomputes `credits_available`, computes `billing_price_cents`, promotes the client from `AUDITED` to `ACTIVE` if it was `AUDITED`, and increments the retainer's `version`. A retainer may also be reactivated from `SUSPENDED` back to `ACTIVE` (whether by an account manager or as the resume cascade from its client), incrementing its `version`. The `billing_price_cents` is the client-facing price: for a direct client whose `reseller_id` is null it equals `wholesale_price_cents` with no markup; for a reseller's client it is `wholesale_price_cents` multiplied by the quantity one plus the reseller's `markup_pct`, with the product floored to whole cents.

Suspending an `ACTIVE` retainer moves it to `SUSPENDED` (by account-manager action or as the client-pause cascade) and increments its `version`; while a retainer is `SUSPENDED`, creation of new deliverables against it is blocked, with the attempt rejected as `ERR_INVALID_STATE`. Closing a retainer is terminal: it is permitted from `ACTIVE`, `SUSPENDED`, or `DRAFT` (by account-manager action or as the client-churn cascade), cancels every non-terminal deliverable on the retainer and releases their committed credits, and increments the retainer's `version`. Reading a single retainer recomputes and returns its `credits_available` from the live ledger.

The credit ledger reconciles from the underlying deliverables of the current cycle. The `credits_committed` figure is the sum of `credit_cost` over the retainer's deliverables in status `ASSIGNED`, `IN_PROGRESS`, or `IN_REVIEW`. The `credits_consumed` figure is the sum of `credit_cost` over the retainer's deliverables that are `APPROVED` during the current `cycle_index`. The `credits_available` figure is `credits_granted` minus `credits_committed` minus `credits_consumed`. All three reconcile on every deliverable assign, approve, reject, or cancel, and on retainer activation and rollover.

Advancing the billing cycle is a self-transition on an `ACTIVE` retainer that requires the optimistic-concurrency check of §2.8: `expected_retainer_version` must equal the retainer's current `version`, else `ERR_STALE_RETAINER_VERSION`. The rollover is computed in a pinned order: first take the leftover, which is the `credits_available` at the end of the prior cycle; then compute the cap as `monthly_credits` multiplied by `rollover_cap_pct`, taking the floor to whole credits; then the rolled amount is the smaller of the leftover and that cap, which guarantees no cycle ever carries more than was actually unused. With the rolled amount in hand, set `credits_granted` to `monthly_credits` plus the rolled amount, reset both `credits_committed` and `credits_consumed` to 0 for the new cycle, recompute `credits_available`, advance `cycle_index` by one, and increment the retainer's `version`. If the retainer's contract is `ACTIVE`, the rollover also advances that contract's `cycles_elapsed` by one, which may in turn trigger the contract's automatic expiry or renewal (§3.5).

### 3.5. Contracts, Renewal, and Early-Termination Economics

A `Contract` binds a client to a retainer for a committed number of billing cycles. It is created by supplying the `client_id`, the governing `retainer_id`, a `term_cycles` count of at least 1, and optionally `auto_renew` (a boolean defaulting to true). A new contract starts in `PENDING` `status` with `early_termination_fee_cents` 0 and `cycles_elapsed` 0. The lifecycle runs `PENDING → SIGNED → ACTIVE`, where an `ACTIVE` contract may renew (cycling `ACTIVE → RENEWED → ACTIVE`), expire, or terminate.

A client signs a `PENDING` contract, moving it to `SIGNED`, which is permitted only when the linked retainer is in `DRAFT` or `ACTIVE` — otherwise `ERR_RETAINER_NOT_SIGNABLE` — and increments the contract's `version`. An account manager then activates a `SIGNED` contract to `ACTIVE`, permitted only when the linked retainer is `ACTIVE`, otherwise `ERR_RETAINER_NOT_ACTIVE`; activation recomputes `early_termination_fee_cents` and increments the contract's `version`. A contract may also be activated from `RENEWED` back to `ACTIVE` to begin the new term, incrementing its `version`.

The fork in a contract's life occurs when `cycles_elapsed` reaches `term_cycles`. If `auto_renew` is true, the contract follows the renewal branch from `ACTIVE` to `RENEWED`: `cycles_elapsed` is reset to 0, `early_termination_fee_cents` is recomputed, and the contract's `version` increments. Renewal may also be triggered manually by an account manager on an `ACTIVE` contract with the same effects. If instead `auto_renew` is false, the contract follows the expiry branch from `ACTIVE` to the terminal `EXPIRED`: because the full term completed, `early_termination_fee_cents` is set to 0, and the contract's `version` increments. These two branches are the symmetric outcomes of the same term-completion fork and differ only in `auto_renew`.

Terminating a contract is the other terminal path and is initiated by an account manager. Termination is permitted from `SIGNED`, `ACTIVE`, or `RENEWED`, moves the contract to `TERMINATED`, recomputes `early_termination_fee_cents` at the termination instant, and increments the contract's `version`. The `early_termination_fee_cents` is computed from the remaining commitment: the remaining cycles are `term_cycles` minus `cycles_elapsed`, floored at zero. If no cycles remain the fee is 0. Otherwise compute a raw fee as the retainer's `billing_price_cents` multiplied by the remaining cycles multiplied by one-half, floored to whole cents, and then take the larger of that raw fee and a single cycle's `billing_price_cents` — so once any cycles remain, the fee is never less than one cycle's billing price. A client churn is blocked while any of its contracts is `ACTIVE` or `RENEWED`, surfacing as `ERR_CONTRACT_STILL_BINDING`.

### 3.6. Sprints and the Deliverable Lifecycle

Work is scheduled into a `Sprint`, a capacity-bounded window of time funded by a retainer. A sprint is created by supplying the `client_id`, the funding `retainer_id`, a `name` label, a window of `starts_at` (inclusive) and `ends_at` (exclusive), and a `capacity_credits` ceiling (zero or greater) on the total deliverable credits it may hold. The window must satisfy `ends_at` strictly after `starts_at`, else `ERR_INVALID_SPRINT_WINDOW`. Sprint windows for the same retainer may not overlap: treat each window as the half-open interval from `starts_at` up to but not including `ends_at`, so two sprints that touch exactly — where one ends at the instant the other begins — are adjacent and allowed, but any genuine overlap against another `PLANNING` or `ACTIVE` sprint of the same retainer is rejected with `ERR_SPRINT_WINDOW_OVERLAP`. A new sprint starts in `PLANNING` `status` with `committed_credits` 0. Its `committed_credits` is the sum of `credit_cost` over the sprint's deliverables that are neither `CANCELLED` nor `REJECTED`.

A sprint moves `PLANNING → ACTIVE` when an account manager starts it, permitted only when the linked retainer is `ACTIVE`, otherwise `ERR_RETAINER_NOT_ACTIVE`, incrementing the sprint's `version`. A sprint closes `ACTIVE → CLOSED` only when it holds no deliverable in `ASSIGNED`, `IN_PROGRESS`, or `IN_REVIEW`; an attempt to close with open work is rejected with `ERR_SPRINT_HAS_OPEN_WORK`. Closing increments the sprint's `version`.

A `Deliverable` is a unit of SEO work, created by supplying the `client_id`, the funding `retainer_id`, the scheduling `sprint_id`, a `kind` of `CONTENT`, `BACKLINK`, or `TECHNICAL`, and optionally a `complexity` of `STANDARD` or `COMPLEX` (defaulting to `STANDARD`). Creation computes the `credit_cost` and starts the deliverable in `DRAFT` `status` with `revision_count` 0. The `credit_cost` derives from a base cost by kind — three for `CONTENT`, two for `BACKLINK`, four for `TECHNICAL` — multiplied by a complexity multiplier of one for `STANDARD` or one and one-half for `COMPLEX`, with the product rounded up to the next whole credit. Thus a `TECHNICAL` `COMPLEX` deliverable costs six credits and a `CONTENT` `COMPLEX` deliverable costs five credits.

The deliverable runs `DRAFT → ASSIGNED → IN_PROGRESS → IN_REVIEW`, then either back to `IN_PROGRESS` for revision or forward to the terminal `APPROVED`; it may also reach the terminal `REJECTED` or `CANCELLED`. Assigning a `DRAFT` deliverable is the credit-reservation step and the second site of the optimistic-concurrency check (§2.8): it requires the retainer to be `ACTIVE` (else `ERR_RETAINER_NOT_ACTIVE`), the sprint to be `PLANNING` or `ACTIVE`, the retainer's `credits_available` to be at least the deliverable's `credit_cost` (else `ERR_INSUFFICIENT_CREDITS`), the sprint's `committed_credits` plus the new `credit_cost` to be at most the sprint's `capacity_credits` (else `ERR_SPRINT_CAPACITY_EXCEEDED`), and `expected_retainer_version` to match the retainer's current `version` (else `ERR_STALE_RETAINER_VERSION`). For an `ACTIVE` sprint, the sprint window must contain the current logical-clock time, else `ERR_INVALID_SPRINT_WINDOW`. The `expected_retainer_version` field is a required integer (a missing or non-integer value fails request-body well-formedness with `ERR_INVALID_REQUEST` at priority 5), and its concurrency comparison runs at priority 7, ahead of every business rule above; among the remaining business-rule checks the platform evaluates them in this fixed order so the surfaced error is deterministic: retainer-`ACTIVE`, then sprint-state (`PLANNING` or `ACTIVE`, else `ERR_INVALID_STATE`), then the `ACTIVE`-sprint window check, then sprint capacity, then retainer credit availability. On success, assignment moves the deliverable to `ASSIGNED`, adds the `credit_cost` to the retainer's `credits_committed` and recomputes `credits_available`, adds the same amount to the sprint's `committed_credits`, and increments the deliverable's `version` (and the retainer's `version`, per the reservation against it).

Starting an `ASSIGNED` deliverable moves it to `IN_PROGRESS`, and submitting an `IN_PROGRESS` deliverable moves it to `IN_REVIEW`, each incrementing the deliverable's `version`. From `IN_REVIEW`, the client either requests a revision or approves. Requesting a revision moves the deliverable back to `IN_PROGRESS`, increments `revision_count` by one, and increments the `version`, forming the cyclic review loop. Approving an `IN_REVIEW` deliverable moves it to the terminal `APPROVED` and converts its reservation into consumption: the `credit_cost` is subtracted from the retainer's `credits_committed` and added to `credits_consumed`, which leaves `credits_available` unchanged at approval, and the deliverable's `version` increments.

Rejection and cancellation both release reserved credits. An account manager may reject a deliverable from `ASSIGNED`, `IN_PROGRESS`, or `IN_REVIEW`, moving it to the terminal `REJECTED`: this subtracts the `credit_cost` from the retainer's `credits_committed` and recomputes `credits_available`, subtracts it from the sprint's `committed_credits`, and increments the deliverable's `version`. Cancellation moves a non-terminal deliverable — one in `DRAFT`, `ASSIGNED`, `IN_PROGRESS`, or `IN_REVIEW` — to the terminal `CANCELLED`, by account-manager action or as a cascade from retainer close or client churn. Cancellation releases credits only when they had been reserved: if the deliverable was `ASSIGNED`, `IN_PROGRESS`, or `IN_REVIEW`, the `credit_cost` is subtracted from the retainer's `credits_committed` (with `credits_available` recomputed) and from the sprint's `committed_credits`; a `DRAFT` deliverable reserved nothing and so releases nothing. Cancellation increments the deliverable's `version`.

### 3.7. Paid-Media Campaigns and the Management Fee

An `AdCampaign` manages a client's paid-media spend on one channel and carries two independent state dimensions. It is created by supplying the `client_id`, the booking `retainer_id`, a `channel` of `GOOGLE_ADS`, `META`, or `BING`, and a `budget_cents` ceiling (zero or greater) on authorized monthly spend. A new campaign starts with `lifecycle_status` `DRAFT` and `billing_status` `UNBILLED`, and with `spent_cents` 0 and `management_fee_cents` 0. The spend-lifecycle dimension runs across `DRAFT`, `LIVE`, `PAUSED`, and the terminal `ENDED`; the billing dimension runs independently across `UNBILLED`, `INVOICED`, and the terminal `SETTLED`. A transition on one dimension never moves the other.

On the lifecycle dimension, launching moves a campaign from `DRAFT` or `PAUSED` to `LIVE`; launching from `DRAFT` requires the linked retainer to be `ACTIVE`, otherwise `ERR_RETAINER_NOT_ACTIVE`. Pausing moves a `LIVE` campaign to `PAUSED` (by account-manager action or as the client-pause cascade). Ending moves a campaign in `DRAFT`, `LIVE`, or `PAUSED` to the terminal `ENDED` (by account-manager action or as the client-churn cascade). Every such transition increments the campaign's `version`.

Spend is recorded against a campaign by supplying an `amount_cents` to add, a required non-negative integer (0 is accepted; a negative or non-integer value fails with `ERR_INVALID_REQUEST`); the new spend may not push `spent_cents` above `budget_cents`, else `ERR_BUDGET_EXCEEDED`. Recording spend is permitted regardless of the campaign's `lifecycle_status` or `billing_status`. Recording spend adds `amount_cents` to `spent_cents` and recomputes the live `management_fee_cents`. The `management_fee_cents` is a marginal tiered markup on cumulative `spent_cents`, not a flat rate. The base rate is the reseller's `ppc_management_pct` when the client belongs to a reseller, and otherwise the agency default rate of twenty hundredths (0.20). Spend is split across three tiers by cumulative amount: the portion of spend below five thousand dollars (500000 cents) is charged at the base rate; the portion from five thousand dollars up to twenty thousand dollars (between 500000 and 2000000 cents) is charged at the base rate reduced by three hundredths; and the portion of spend at or above twenty thousand dollars (2000000 cents) is charged at the base rate reduced by six hundredths. Apply each tier's rate to the portion of spend that falls in that tier, sum the per-tier fees, and only then floor the summed total down to whole cents — the floor is applied once, on the total, never per tier.

The same fee formula has two variants distinguished by billing state. While the campaign's `billing_status` is `UNBILLED`, the fee is a live provisional estimate over the current `spent_cents`, recomputed on every spend recording and on read, and it excludes any spend later removed by an upheld dispute. When the campaign transitions from `UNBILLED` to `INVOICED`, the fee is recomputed once over the then-current post-dispute `spent_cents` and frozen: an upheld dispute settled after invoicing does not retroactively lower an already-`INVOICED` fee. Invoicing is permitted only when the campaign has no dispute in `OPEN` or `UNDER_REVIEW`, otherwise `ERR_CAMPAIGN_HAS_OPEN_DISPUTE`; it recomputes and freezes `management_fee_cents`, moves `billing_status` from `UNBILLED` to `INVOICED`, and increments the campaign's `version`. Settling moves `billing_status` from `INVOICED` to the terminal `SETTLED` and increments the `version`. Reading a single campaign recomputes the live `management_fee_cents` estimate while it is `UNBILLED`.

### 3.8. Ad-Spend Disputes

An `AdSpendDispute` lets a client contest part of a campaign's spend. It is opened by supplying the `ad_campaign_id` of the disputed campaign, the `client_id` raising it, and a `disputed_cents` amount (at least 1). A new dispute starts in `OPEN` `status` with `credited_cents` 0, and opening it recomputes the client's `open_dispute_count`. The dispute lifecycle is `OPEN → UNDER_REVIEW` and then to the terminal `UPHELD` or `DENIED`, or directly to the terminal `WITHDRAWN`. An account manager reviews an `OPEN` dispute, moving it to `UNDER_REVIEW` and incrementing its `version`.

Resolving an `UNDER_REVIEW` dispute carries an `outcome` of either `UPHELD` or `DENIED`. An `UPHELD` resolution credits the client and claws spend back: it requires `disputed_cents` to be at most the linked campaign's current `spent_cents`, otherwise `ERR_DISPUTE_EXCEEDS_SPEND`; on success it sets `credited_cents` equal to `disputed_cents`, subtracts `disputed_cents` from the campaign's `spent_cents` and recomputes the campaign's `management_fee_cents` only while that campaign is still `UNBILLED` (an already-`INVOICED` or `SETTLED` fee stays frozen at its invoiced value per §3.7, even though `spent_cents` is still clawed back), recomputes the parent client's `open_dispute_count` and `health_score` (a depth-three cascade from dispute to campaign and to client), and increments the dispute's `version`. A `DENIED` resolution leaves `credited_cents` at 0, recomputes the client's `open_dispute_count` and `health_score`, and increments the dispute's `version`. Withdrawing a dispute is a client action permitted from `OPEN` or `UNDER_REVIEW`, moving it to the terminal `WITHDRAWN`, recomputing the client's `open_dispute_count` and `health_score`, and incrementing the dispute's `version`. The `open_dispute_count` always reflects the count of the client's disputes currently `OPEN` or `UNDER_REVIEW`.

### 3.9. Local Listing Optimization

A `GbpListing` represents a client's Google Business Profile, created by supplying the `client_id`, a required non-empty `location_name` label, and a required non-empty `service_area` string describing the geographic area served. A new listing starts in `UNVERIFIED` `status`, and its `optimization_score` is computed at creation from the completeness signals below rather than fixed at 0; because `location_name` and `service_area` are non-empty while the listing is not yet `VERIFIED`, a newly created listing scores 50, plus a further 25 if its parent client is already `ACTIVE`. The `service_area` must be unique among the client's listings that are `VERIFIED` or `OPTIMIZED`. The lifecycle runs `UNVERIFIED → VERIFIED → OPTIMIZED`, and any of these may move to the terminal `SUSPENDED`.

Verifying an `UNVERIFIED` listing moves it to `VERIFIED` but only when no other listing for the same client with the same `service_area` is already `VERIFIED` or `OPTIMIZED`, otherwise `ERR_DUPLICATE_RESOURCE`; verification recomputes the `optimization_score` and increments the listing's `version`. Optimizing a `VERIFIED` listing first recomputes its `optimization_score` and then moves it to `OPTIMIZED`, but only when that freshly recomputed `optimization_score` is at least 80 — a listing below that threshold is rejected with `ERR_OPTIMIZATION_THRESHOLD_NOT_MET` — and increments the listing's `version`. Suspending moves a listing in `UNVERIFIED`, `VERIFIED`, or `OPTIMIZED` to the terminal `SUSPENDED` and increments its `version`.

The `optimization_score` is a completeness score out of 100, awarding twenty-five points for each of four signals: twenty-five if `location_name` is non-empty, twenty-five if `service_area` is non-empty, twenty-five if the listing's `status` is `VERIFIED` or `OPTIMIZED`, and twenty-five if the parent client's `status` is `ACTIVE`. Reading a single listing recomputes its `optimization_score`.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`; operations that modify an existing resource, including every state transition, return `200 OK`. List and read operations return `200 OK`. The complete request and response payloads for each operation are defined by the workflow narratives in §3; this table fixes only the method, path, purpose, and authorized roles.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/resellers` | Create a white-label reseller | AgencyAdmin |
| GET | `/resellers/{id}` | Get a reseller | AgencyAdmin, Reseller |
| GET | `/resellers` | List resellers | AgencyAdmin |
| POST | `/clients` | Create a client | AgencyAdmin, Reseller |
| GET | `/clients/{id}` | Get a client (recomputes health score) | AgencyAdmin, AccountManager, Reseller, Client |
| GET | `/clients` | List clients; filter by reseller or status | AgencyAdmin, AccountManager, Reseller |
| POST | `/clients/{id}/pause` | Pause an active client | AgencyAdmin, AccountManager |
| POST | `/clients/{id}/resume` | Resume a paused client | AgencyAdmin, AccountManager |
| POST | `/clients/{id}/churn` | Churn a client | AgencyAdmin, AccountManager |
| POST | `/clients/{id}/audits` | Record a site audit | AgencyAdmin, AccountManager |
| GET | `/audits/{id}` | Get a site audit | AgencyAdmin, AccountManager, Client |
| GET | `/clients/{id}/audits` | List a client's site audits | AgencyAdmin, AccountManager, Client |
| POST | `/keyword-targets` | Create a keyword target | AgencyAdmin, AccountManager |
| GET | `/keyword-targets/{id}` | Get a keyword target | AgencyAdmin, AccountManager, Client |
| GET | `/keyword-targets` | List keyword targets; filter by client or status | AgencyAdmin, AccountManager, Client |
| POST | `/keyword-targets/{id}/activate-tracking` | Start tracking a keyword target | AgencyAdmin, AccountManager |
| POST | `/keyword-targets/{id}/drop` | Drop a keyword target | AgencyAdmin, AccountManager |
| POST | `/keyword-targets/{id}/snapshots` | Append a rank/traffic snapshot | AgencyAdmin, AccountManager |
| GET | `/snapshots/{id}` | Get a rank snapshot | AgencyAdmin, AccountManager, Client |
| GET | `/keyword-targets/{id}/snapshots` | List a keyword's rank snapshots | AgencyAdmin, AccountManager, Client |
| POST | `/retainers` | Create a retainer | AgencyAdmin, AccountManager |
| GET | `/retainers/{id}` | Get a retainer (recomputes credit balance) | AgencyAdmin, AccountManager, Reseller, Client |
| GET | `/retainers` | List retainers; filter by client or status | AgencyAdmin, AccountManager, Reseller, Client |
| POST | `/retainers/{id}/activate` | Activate a retainer | AgencyAdmin, AccountManager |
| POST | `/retainers/{id}/suspend` | Suspend a retainer | AgencyAdmin, AccountManager |
| POST | `/retainers/{id}/close` | Close a retainer | AgencyAdmin, AccountManager |
| POST | `/retainers/{id}/rollover` | Advance the billing cycle | AgencyAdmin, AccountManager |
| POST | `/contracts` | Create a contract | AgencyAdmin, AccountManager |
| GET | `/contracts/{id}` | Get a contract | AgencyAdmin, AccountManager, Reseller, Client |
| GET | `/contracts` | List contracts; filter by client, retainer, or status | AgencyAdmin, AccountManager, Reseller, Client |
| POST | `/contracts/{id}/sign` | Sign a contract | Client |
| POST | `/contracts/{id}/activate` | Activate a contract | AgencyAdmin, AccountManager |
| POST | `/contracts/{id}/renew` | Renew a contract | AgencyAdmin, AccountManager |
| POST | `/contracts/{id}/terminate` | Terminate a contract | AgencyAdmin, AccountManager |
| POST | `/sprints` | Create a sprint | AgencyAdmin, AccountManager |
| GET | `/sprints/{id}` | Get a sprint | AgencyAdmin, AccountManager, Client |
| GET | `/sprints` | List sprints; filter by client, retainer, or status | AgencyAdmin, AccountManager, Client |
| POST | `/sprints/{id}/start` | Start a sprint | AgencyAdmin, AccountManager |
| POST | `/sprints/{id}/close` | Close a sprint | AgencyAdmin, AccountManager |
| POST | `/deliverables` | Create a deliverable | AgencyAdmin, AccountManager |
| GET | `/deliverables/{id}` | Get a deliverable | AgencyAdmin, AccountManager, Client |
| GET | `/deliverables` | List deliverables; filter by client, retainer, sprint, or status | AgencyAdmin, AccountManager, Client |
| POST | `/deliverables/{id}/assign` | Assign a deliverable (reserves credits) | AgencyAdmin, AccountManager |
| POST | `/deliverables/{id}/start` | Start a deliverable | AgencyAdmin, AccountManager |
| POST | `/deliverables/{id}/submit` | Submit a deliverable for review | AgencyAdmin, AccountManager |
| POST | `/deliverables/{id}/request_revision` | Request a revision | Client |
| POST | `/deliverables/{id}/approve` | Approve a deliverable | Client |
| POST | `/deliverables/{id}/reject` | Reject a deliverable | AgencyAdmin, AccountManager |
| POST | `/deliverables/{id}/cancel` | Cancel a deliverable | AgencyAdmin, AccountManager |
| POST | `/ad-campaigns` | Create a PPC campaign | AgencyAdmin, AccountManager |
| GET | `/ad-campaigns/{id}` | Get a campaign (recomputes live fee) | AgencyAdmin, AccountManager, Reseller, Client |
| GET | `/ad-campaigns` | List campaigns; filter by client, retainer, lifecycle, or billing status | AgencyAdmin, AccountManager, Reseller, Client |
| POST | `/ad-campaigns/{id}/launch` | Launch a campaign | AgencyAdmin, AccountManager |
| POST | `/ad-campaigns/{id}/pause` | Pause a campaign | AgencyAdmin, AccountManager |
| POST | `/ad-campaigns/{id}/end` | End a campaign | AgencyAdmin, AccountManager |
| POST | `/ad-campaigns/{id}/record-spend` | Record ad spend | AgencyAdmin, AccountManager |
| POST | `/ad-campaigns/{id}/invoice` | Invoice a campaign (freezes fee) | AgencyAdmin, AccountManager |
| POST | `/ad-campaigns/{id}/settle` | Settle an invoiced campaign | AgencyAdmin, AccountManager |
| POST | `/ad-spend-disputes` | Open an ad-spend dispute | AgencyAdmin, AccountManager, Client |
| GET | `/ad-spend-disputes/{id}` | Get an ad-spend dispute | AgencyAdmin, AccountManager, Client |
| GET | `/ad-spend-disputes` | List disputes; filter by campaign, client, or status | AgencyAdmin, AccountManager, Client |
| POST | `/ad-spend-disputes/{id}/review` | Move a dispute under review | AgencyAdmin, AccountManager |
| POST | `/ad-spend-disputes/{id}/resolve` | Resolve a dispute (upheld or denied) | AgencyAdmin, AccountManager |
| POST | `/ad-spend-disputes/{id}/withdraw` | Withdraw a dispute | Client |
| POST | `/gbp-listings` | Create a GBP listing | AgencyAdmin, AccountManager |
| GET | `/gbp-listings/{id}` | Get a GBP listing (recomputes score) | AgencyAdmin, AccountManager, Client |
| GET | `/gbp-listings` | List GBP listings; filter by client or status | AgencyAdmin, AccountManager, Client |
| POST | `/gbp-listings/{id}/verify` | Verify a GBP listing | AgencyAdmin, AccountManager |
| POST | `/gbp-listings/{id}/optimize` | Optimize a verified listing | AgencyAdmin, AccountManager |
| POST | `/gbp-listings/{id}/suspend` | Suspend a GBP listing | AgencyAdmin, AccountManager |
| POST | `/clients/{id}/reports` | Generate a rank/traffic report | AgencyAdmin, AccountManager |
| GET | `/reports/{id}` | Get a report | AgencyAdmin, AccountManager, Reseller, Client |
| GET | `/clients/{id}/reports` | List a client's reports | AgencyAdmin, AccountManager, Reseller, Client |
| POST | `/_clock/set_current_utc` | Set the logical clock | AgencyAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_RETAINER_VERSION` | 412 |
| `ERR_RETAINER_NOT_ACTIVE` | 409 |
| `ERR_RETAINER_NOT_SIGNABLE` | 409 |
| `ERR_CLIENT_NOT_AUDITED` | 409 |
| `ERR_CONTRACT_STILL_BINDING` | 409 |
| `ERR_CAMPAIGN_HAS_OPEN_DISPUTE` | 409 |
| `ERR_DISPUTE_EXCEEDS_SPEND` | 409 |
| `ERR_BUDGET_EXCEEDED` | 409 |
| `ERR_OPTIMIZATION_THRESHOLD_NOT_MET` | 409 |
| `ERR_SPRINT_HAS_OPEN_WORK` | 409 |
| `ERR_INVALID_SPRINT_WINDOW` | 422 |
| `ERR_DUPLICATE_RESOURCE` | 409 |
| `ERR_SPRINT_CAPACITY_EXCEEDED` | 409 |
| `ERR_INSUFFICIENT_CREDITS` | 409 |
| `ERR_SPRINT_WINDOW_OVERLAP` | 409 |
| `ERR_REPORT_PERIOD_OVERLAP` | 409 |
