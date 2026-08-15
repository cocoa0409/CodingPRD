# Trade Order Allocation API — Product Requirements Document

## 1. Introduction

An asset manager's trading desk lives or dies on the integrity of a single pipeline: portfolio accounts originate orders, compliance vets them before they may trade, the desk aggregates approved orders into blocks, brokers execute those blocks, and the resulting fills are allocated back across the participating accounts at a defensible average price. Around that pipeline sit the controls that make it trustworthy — pre-trade restriction rules, per-period commission budgets, segregation of duties between the people who build allocations and the people who approve them, a formal trade-error correction path with a dedicated error account, settlement instruction monitoring with escalation, and an audit trail that never forgets a mutation. This document specifies the Trade Order Allocation API, the system of record for that entire lifecycle.

The API is mounted under `/trading` and serves six operator roles, from the `Trader` who originates and aggregates orders to the read-only `Auditor`. Two fairness invariants have real teeth: every allocation plan carries a measurable deviation metric that compliance must approve against a fixed tolerance, and every account's commission spend is gated against a period budget that can exhaust but never overflow. Because trading rules must not wobble with wall-clock accidents, every date- and time-sensitive rule in the system — restriction effectiveness windows, routing timestamps, settlement dates, fail monitoring — reads a single logical clock that administrators advance explicitly. Section 2 states the system-wide contracts, Section 3 walks the business workflows, Section 4 tabulates the endpoints, and Section 5 catalogues the error codes.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the acting role. A request missing either header, or presenting a role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A recognized role that is not on the endpoint's authorized list is rejected with `ERR_FORBIDDEN` (HTTP 403).

Six roles exist, spelled exactly as follows:

- `Trader` — the trading desk user; creates orders and blocks, attaches and detaches orders, cancels orders and blocks, routes blocks to brokers, and builds, proposes, and posts allocation plans.
- `ExecutionDesk` — books broker fills against routed blocks; deliberately separate from `Trader`, so the person who wants the execution is never the person who records it.
- `ComplianceOfficer` — owns restriction rules, runs pre-trade compliance checks, approves or returns allocation plans (never a plan that same user created — see the segregation-of-duties gate in §3.7), and co-flags trade errors.
- `SettlementOps` — drives the settlement instruction lifecycle (instruct, settle, fail, repair), runs the fail monitor, and co-flags trade errors.
- `DeskAdmin` — the desk administrator; owns reference data (accounts, securities, brokers), commission budgets, trade-error correction and dismissal, and the logical clock.
- `Auditor` — read-only; queries every resource plus the audit trail.

For all six roles — `Trader`, `ExecutionDesk`, `ComplianceOfficer`, `SettlementOps`, `DeskAdmin`, and `Auditor` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it, for example as `created_by_user_id` on an allocation plan, as `approved_by_user_id` on an approved plan, or as `flagged_by_user_id` on a trade error, but it never compares it to any entity's `id` for ownership. The single place `X-User-ID` is compared against anything is the segregation-of-duties check at plan approval, where it must differ from the plan's `created_by_user_id`.

Every role may call every read endpoint — all single-resource retrievals and all listings. The audit event listing is narrower: only `ComplianceOfficer`, `DeskAdmin`, and `Auditor` may read it.

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
- The same envelope frames failures below the routing layer: a request matching no endpoint returns 404 with `error_id` `ERR_NOT_FOUND`, a known path called with an unsupported method returns 405 with `ERR_METHOD_NOT_ALLOWED`, and an unexpected server fault returns 500 with `ERR_INTERNAL`. These three identifiers sit outside the Section 5 catalogue because no business workflow raises them.

### 2.3. Pagination

List endpoints accept two query parameters: `limit` and `offset`. The `limit` defaults to 10, with a minimum of 1 and a maximum of 100; the `offset` defaults to 0. Out-of-range values are clamped into range rather than rejected — a `limit` below 1 or above 100 becomes 1 or 100, and a negative `offset` becomes 0 — while a non-integer `limit` or `offset` is rejected `ERR_INVALID_REQUEST`. The `meta` object of a list response carries exactly the pagination fields `limit`, `offset`, `total_count`, and `has_more`, so a caller can always tell how many rows exist and whether another page follows. List results are sorted by `created_at` ascending unless a specific endpoint states otherwise — the one exception in this system is a block's fill listing, which sorts by `fill_seq` ascending (§3.6).

### 2.4. Resource Identity, Timestamps and Versioning

Every persisted resource carries a server-minted `id`, a UUID with no type prefix, and a `created_at` timestamp rendered as ISO 8601 UTC with three fractional digits. Most resources additionally carry `updated_at`, refreshed in the same format on every mutation, and `version`, an integer that increments by exactly one on every state-changing mutation of that resource. Two resource kinds are deliberately lighter: a Fill and an AuditEvent carry only `id` and `created_at`. Both `updated_at` and `version` are absent on them, because fills and audit events are immutable once written.

Version increments attach to the resource being mutated, and certain operations deliberately bump a related resource's version as well: attaching or detaching an order increments the block's `version`; creating an allocation plan increments the block's `version`; posting a plan increments both the plan's and the block's `version`. These cross-resource bumps are what make the optimistic-concurrency check of §2.7 meaningful — a client holding a stale block version has demonstrably missed a material change.

### 2.5. The Desk Logical Clock

All date and time rules in the system read a single server-side logical clock: restriction effectiveness windows, the `routed_at` timestamp stamped at block routing, the fill timing check, trade and settle dates, and fail monitoring. The clock never falls back to wall-clock time. Its startup default, before any administrator sets it, is exactly 2026-08-01T00:00:00Z.

A `DeskAdmin` advances the clock through a dedicated test-driving capability, supplying the target instant as `to_iso8601`; a successful set responds with the new value under `current_utc`. The clock is monotone: the supplied instant must be strictly later than the current value, otherwise the request is rejected with `ERR_INVALID_REQUEST`.

### 2.6. Money, Precision and Rounding

All monetary amounts are integer cents — prices, gross amounts, commissions, budgets. All quantities are integer units. Basis points appear in two places: broker commission rates, where a `commission_rate_bp` of 50 means 0.50% of notional, and the allocation fairness metric `max_deviation_bp`. Every division in the system is performed in exact decimal arithmetic; rounding happens once, at the end of each calculation, half-up to the nearest integer — cents for money, basis points for deviation, units never fractional. Two rounding orders are pinned explicitly: average prices are rounded half-up to whole cents after an exact-decimal division, and commissions are rounded half-up to whole cents on each allocation line before any per-account summation. Summing unrounded notionals and rounding once at the account level is forbidden, because the two orders can differ by cents.

Dates — budget period boundaries, trade dates, settle dates — are ISO calendar dates at day granularity. The system keeps no holiday calendar; "calendar days" means exactly what it says.

### 2.7. Concurrency Control on Plan Creation

Exactly one endpoint is guarded by optimistic concurrency control: the plan-creation endpoint (`POST /trading/blocks/{blockId}/allocation-plans`). The request must carry `expected_block_version` — required only to be an integer, with no positivity constraint — the client's last observed `version` of the block. If that value does not match the block's current `version` — because another writer has created a plan for the same block (which legitimately supersedes the prior non-terminal plan), recorded a fill (changing the fill set the plan would cover), or attached or detached an order — the create is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint takes a version field; every other write is accepted or rejected purely on state and business rules.

### 2.8. Validation Priority and Error Ordering

When a single request violates several rules, the system does not choose arbitrarily: checks are evaluated in a fixed priority order and the first failure wins. The ladder, highest priority first:

1. Authentication — both headers present and the role recognized (`ERR_UNAUTHENTICATED`, HTTP 401).
2. Authorization — the acting role appears in the endpoint's authorized list (`ERR_FORBIDDEN`, HTTP 403).
3. Request shape — required fields present, enum values valid, integers positive where required, and conditional field requirements honored: a LIMIT order carries `limit_price_cents` while a MARKET order must not; a MAX_POSITION_UNITS restriction carries `threshold_units` while a PROHIBITED one must not; a WRONG_ACCOUNT correction carries `target_account_id`, a WRONG_QTY correction carries `corrected_qty`, and a WRONG_PRICE correction carries `corrected_price_cents`. Window sanity also lives here: `period_end` strictly after `period_start`, and `effective_to` no earlier than `effective_from`. Uniqueness of the self-claimed codes — `account_code`, `ticker`, and `broker_code` — is enforced at this rung as well. Unknown or undeclared request fields are ignored, not rejected. All of this surfaces as `ERR_INVALID_REQUEST` (HTTP 400).
4. Existence — every referenced resource id resolves, path ids first (validated left to right), then ids referenced in the request body. Each missing resource yields its own specific 404 (§2.9).
5. Segregation of duties at plan approval (`ERR_SEGREGATION_OF_DUTIES`, HTTP 403).
6. State-machine legality — the target resource is in a valid from-state for the action. Generic mismatches surface as `ERR_INVALID_STATE` (HTTP 409) — examples include approving a DRAFT plan, settling a PENDING instruction, cancelling an ALLOCATED order, or setting an account to the status it already has. Named mismatches carry their own 409 codes: `ERR_ORDER_NOT_APPROVED` at attach, `ERR_BLOCK_NOT_OPEN` at attach, detach, block cancel, or route, `ERR_PLAN_NOT_POSTABLE` at post, `ERR_ERROR_ALREADY_OPEN` at flag, `ERR_ALLOCATION_ALREADY_SETTLED` at correction, and `ERR_ORDER_NOT_IN_BLOCK` at detach. Within attach and detach, the block's state is evaluated before the order's membership or ownership, which is evaluated before the order's own state.
7. Optimistic concurrency at plan creation (`ERR_STALE_VERSION`, HTTP 412).
8. Business safety gates on related entities, evaluated in this order: the account must be ACTIVE where the action requires it (`ERR_ACCOUNT_SUSPENDED`, HTTP 409), and an order may not originate on an ERROR-type account (`ERR_ACCOUNT_TYPE_FORBIDDEN`, HTTP 422); then the security must be ACTIVE where the action executes or approves (`ERR_SECURITY_HALTED`, HTTP 409); then the broker must be ACTIVE at routing (`ERR_BROKER_SUSPENDED`, HTTP 409) and must support the instrument's asset class (`ERR_BROKER_ASSET_CLASS_UNSUPPORTED`, HTTP 422); then restriction rules, with an applicable PROHIBITED rule (`ERR_TRADE_PROHIBITED`) surfacing before any MAX_POSITION_UNITS breach (`ERR_POSITION_LIMIT_BREACH`).
9. Constraint satisfaction (HTTP 422): lot-size multiples, block security and side matching, order not already in a block, a non-empty block at routing or plan proposal, no overfill, disjoint budget periods, disjoint restriction windows, corrected quantity strictly below the original.
10. Temporal rules (HTTP 422): a fill's execution timestamp must not precede the block's routing timestamp (`ERR_FILL_BEFORE_ROUTE`).
11. Referential configuration (HTTP 422): a desk ERROR account exists for quantity corrections (`ERR_NO_ERROR_ACCOUNT`); every affected account has an OPEN budget covering the trade date (`ERR_NO_ACTIVE_BUDGET`); uncovered fills exist at propose (`ERR_NOTHING_TO_ALLOCATE`); no new fills arrived beyond the proposed batch at post (`ERR_PLAN_STALE_BATCH`).
12. Fiscal gates (HTTP 422): projected commission accrual fits the budget (`ERR_COMMISSION_BUDGET_EXCEEDED`), and the plan's fairness metric is within tolerance at approval (`ERR_UNFAIR_ALLOCATION`).

Two codes in the ladder are unusual: `ERR_TRADE_PROHIBITED` and `ERR_POSITION_LIMIT_BREACH` are never returned as API error responses. They surface as the order's `compliance_note` when a compliance check rejects the order — the check call itself returns 200 (§3.4).

### 2.9. Resource Resolution and Path Semantics

Resource ids in a URL resolve from left to right: the leftmost path parameter is looked up first, and only if it exists is the next one examined; ids referenced in the request body are resolved after all path ids. A missing resource yields the 404 specific to its kind — `ERR_ACCOUNT_NOT_FOUND`, `ERR_SECURITY_NOT_FOUND`, `ERR_BROKER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_BLOCK_NOT_FOUND`, `ERR_BUDGET_NOT_FOUND`, `ERR_RESTRICTION_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND`, `ERR_TRADE_ERROR_NOT_FOUND`, `ERR_INSTRUCTION_NOT_FOUND`, or `ERR_POSITION_NOT_FOUND`. The resource hierarchy is flat: budgets are created under an account, and fills and plans under a block, but everything is retrieved by its own top-level id, and every child collection is also reachable through a filterable top-level listing — allocations, for example, by `plan_id`, `account_id`, `order_id`, or `corrects_allocation_id`.

### 2.10. Audit Trail and Retention

Every mutation in the system appends an AuditEvent. An audit event records `entity_type`, a polymorphic entity-type tag such as Order, AllocationPlan, or SettlementInstruction that is an identity label rather than a foreign key; `entity_id`, the mutated resource's id, likewise an identity only and not a join key; `action`, a machine tag such as ORDER_CREATED, BLOCK_ROUTED, or PLAN_POSTED; `actor_role` and `actor_user_id`, taken from the mutating request's headers, or the literal string "system" for automatic transitions such as escalations, budget exhaustion, and settlement bubble-ups; and `detail`, a structured summary of the mutation including from/to states and key fields. The trail is append-only and retained indefinitely; it can be paged and filtered by `entity_type` and `entity_id`. As stated in §2.1, only `ComplianceOfficer`, `DeskAdmin`, and `Auditor` may read it.

## 3. Business Logic & Workflows

### 3.1. Desk Reference Data: Accounts, Securities and Brokers

Three registries underpin everything else, all administered by `DeskAdmin`.

An account is created with a unique `account_code` that becomes immutable after creation, a human-readable `display_name`, an `account_type`, and a `custodian_name`. The type is one of DISCRETIONARY, PROPRIETARY, or ERROR. The ERROR type is special: such accounts exist to absorb residual quantities from trade-error corrections (§3.8), and they may not originate orders — attempting to create an order on one is rejected with `ERR_ACCOUNT_TYPE_FORBIDDEN`. The custodian name is copied onto every settlement instruction later created for this account's allocations. New accounts start ACTIVE, and creation writes an `ACCOUNT_CREATED` audit event.

An administrator flips an account between ACTIVE and SUSPENDED by submitting `to_status`. Suspension is destructive by design: every order of the account sitting in `PENDING_COMPLIANCE`, `COMPLIANCE_REJECTED`, or `APPROVED` transitions to `CANCELLED` outright, while orders already `BLOCKED` in a block are deliberately left untouched — the desk must unwind blocks explicitly. The transition writes an `ACCOUNT_SUSPENDED` event; resumption back to ACTIVE writes `ACCOUNT_RESUMED`. Asking for the status the account already has is a generic from-state mismatch, rejected `ERR_INVALID_STATE`. Suspension also happens automatically, with no administrator involved, when the settlement-fail escalation of §3.9 fires; the automatic path records the actor as "system" on the same `ACCOUNT_SUSPENDED` event. Either path increments the account's `version` by one.

A security is created with a unique `ticker` (immutable after creation), an `asset_class` of EQUITY or FIXED_INCOME, a `currency` that defaults to USD when omitted — a provided value must be a non-empty string — and names the ISO 4217 settlement currency, a `lot_size` of at least one, and a strictly positive `reference_price_cents`. The reference price is informational only — no calculation consumes it. The asset class, by contrast, drives the settlement lag used in §3.9 (one calendar day for EQUITY, two for FIXED_INCOME), and the lot size constrains order quantities in §3.4. Halting a security by submitting `to_status` HALTED blocks compliance approval of its orders, routing of its blocks, and recording of its fills, surfacing `ERR_SECURITY_HALTED` at each; submitting ACTIVE resumes it. The transitions write `SECURITY_HALTED` and `SECURITY_RESUMED` respectively and increment the security's `version`; creation writes `SECURITY_CREATED`.

A broker is created with a unique `broker_code` (immutable after creation), a `display_name`, a strictly positive `commission_rate_bp` — any positive number, integer or fractional — expressed in basis points of notional, and a non-empty `supported_asset_classes` array whose members are asset-class values (EQUITY, FIXED_INCOME, or both). Suspending a broker blocks new block routing with `ERR_BROKER_SUSPENDED` — but, pinned deliberately, blocks already `WORKING` under that broker may continue to receive fills. The flips write `BROKER_SUSPENDED` and `BROKER_RESUMED` and increment the broker's `version`; creation writes `BROKER_CREATED`. New brokers start ACTIVE, as do new securities.

### 3.2. Commission Budgets and Period Accounting

Each account's commission spend is capped per period by a CommissionBudget, created by `DeskAdmin` under the account. The create supplies `period_start`, `period_end`, and a strictly positive `budget_amount_cents` in cents; the owning `account_id` comes from the path. The budget covers the half-open window from `period_start` inclusive to `period_end` exclusive, and `period_end` must be strictly after `period_start`. Windows of the same account must be disjoint across its OPEN and EXHAUSTED budgets: a new budget whose half-open window intersects an existing one is rejected with `ERR_BUDGET_PERIOD_OVERLAP`. Adjacency is not intersection — one budget's `period_end` may equal another's `period_start`, and the two coexist.

A fresh budget starts OPEN with `accrued_commission_cents` at zero and writes `BUDGET_CREATED`. The accrual is the sum of `commission_cents` over the account's allocation lines in `POSTED`, `SETTLED`, or `ERROR_FLAGGED` status whose block's trade date falls inside the budget's half-open window; reversals decrement it (§3.8). When a posting brings the accrual to exactly the budgeted amount, the budget flips from OPEN to the terminal EXHAUSTED automatically and writes `BUDGET_EXHAUSTED`. A posting that would push the accrual past the budgeted amount is rejected outright with `ERR_COMMISSION_BUDGET_EXCEEDED` — only exact equality exhausts, and overshoot never lands. Budgets can be listed with optional `account_id` and `status` filters, and fetched individually by id.

### 3.3. Restriction Rules and Effectiveness Windows

Restrictions are the desk's pre-trade rulebook, authored by `ComplianceOfficer`. A restriction is created in `DRAFT` with a nullable `account_id` (null means the rule applies firm-wide), a nullable `security_id` (null means all securities), a `rule_type` of PROHIBITED or MAX_POSITION_UNITS, a `side` of BUY, SELL, or BOTH naming which order sides the rule inspects, and a closed effectiveness window bracketed by `effective_from` and `effective_to` — both ends inclusive, with `effective_to` no earlier than `effective_from`. The `threshold_units` field, a strictly positive integer, is required exactly when the rule type is MAX_POSITION_UNITS and forbidden otherwise. Window overlap is not checked at creation: `RESTRICTION_CREATED` simply lands the draft.

Activation — whether from `DRAFT` or later from `SUSPENDED` — is where the overlap guard lives: no other ACTIVE restriction with the same key (the combination of `account_id`, `security_id`, `rule_type`, and `side`) may hold a closed window intersecting this one's, and shared endpoints do intersect — two windows that merely touch at a boundary instant collide. A violating activation is rejected with `ERR_RESTRICTION_WINDOW_OVERLAP`. An ACTIVE rule can be suspended to `SUSPENDED` and re-activated (the same overlap guard reruns), and a rule in any of `DRAFT`, `ACTIVE`, or `SUSPENDED` can be retired to the terminal `RETIRED`. These transitions write `RESTRICTION_ACTIVATED`, `RESTRICTION_SUSPENDED`, and `RESTRICTION_RETIRED` and increment the restriction's `version`.

Only ACTIVE rows gate compliance. A rule applies to an order when its account scope is null or matches the order's account, its security scope is null or matches the order's security, its `side` is BOTH or matches the order's side, and the current logical instant lies inside the closed effectiveness window. What a matching rule does is §3.4's story. Restrictions are listed with optional `account_id`, `security_id`, and `status` filters, and fetched individually by id.

### 3.4. Order Capture and Pre-Trade Compliance

A `Trader` creates an order with an `account_id`, a `security_id`, a `side` of BUY or SELL, a strictly positive `order_qty` that must be a whole multiple of the security's `lot_size` (otherwise `ERR_LOT_SIZE_VIOLATION`), and an `order_type` of MARKET or LIMIT. The `limit_price_cents` field is required exactly for LIMIT orders — strictly positive when present, and forbidden on MARKET orders. The owning account must be ACTIVE (`ERR_ACCOUNT_SUSPENDED`) and must not be an ERROR-type account (`ERR_ACCOUNT_TYPE_FORBIDDEN`). Creation runs no compliance evaluation at all: the order lands in `PENDING_COMPLIANCE` with `allocated_qty` zero, writes `ORDER_CREATED`, and waits.

Compliance is a deliberate act: a `ComplianceOfficer` runs the compliance check, and the gates fire in a fixed order. The check is legal only from `PENDING_COMPLIANCE` or `COMPLIANCE_REJECTED`; running it against an order in any other state — `APPROVED`, `BLOCKED`, and beyond — is rejected `ERR_INVALID_STATE`. First the account must be ACTIVE (`ERR_ACCOUNT_SUSPENDED`) and the security must be ACTIVE (`ERR_SECURITY_HALTED`); failures here abort the check as real error responses. Then the restriction rules run. If an applicable ACTIVE PROHIBITED rule matches the order, or the order would breach an applicable ACTIVE MAX_POSITION_UNITS rule, the order transitions to `COMPLIANCE_REJECTED`, the failing rule's error id — `ERR_TRADE_PROHIBITED` or `ERR_POSITION_LIMIT_BREACH`, in that precedence — is recorded as the order's `compliance_note`, and an `ORDER_COMPLIANCE_REJECTED` event is written. The check call itself still returns 200: rejection is a state, not an error response. A position-limit breach is measured by projection — the account's current `net_qty` for the security (an absent position row counts as zero) plus the signed order quantity, positive for BUY and negative for SELL, must not exceed the rule's `threshold_units`; exceeding it is the breach. A clean order transitions `PENDING_COMPLIANCE → APPROVED` and writes `ORDER_COMPLIANCE_APPROVED`.

Re-checks are first-class. An order already `COMPLIANCE_REJECTED` can be checked again after the world changes — a restriction retired, an account resumed. If the gates now pass, the order moves `COMPLIANCE_REJECTED → APPROVED` under the same preconditions as a fresh check, its `compliance_note` is cleared, and `ORDER_COMPLIANCE_APPROVED` is written. If a restriction still fails, the order stays in `COMPLIANCE_REJECTED`, the note is refreshed to the currently failing rule, and another `ORDER_COMPLIANCE_REJECTED` event lands.

Cancellation is available to a `Trader` from `PENDING_COMPLIANCE`, `COMPLIANCE_REJECTED`, or `APPROVED` — exactly the three states the account-suspension cascade cancels — and lands the order in the terminal `CANCELLED` with `ORDER_CANCELLED`. Cancelling an order in any later state, such as `BLOCKED` or `ALLOCATED`, is rejected `ERR_INVALID_STATE`. Orders are listed with optional `account_id`, `security_id`, `block_id`, and `status` filters, and fetched individually by id; each order also exposes its computed `allocated_qty` and `avg_executed_price_cents` once allocation begins (§3.7).

### 3.5. Block Assembly: Aggregating Approved Orders

Aggregation starts when a `Trader` creates a block for a `security_id` and a `side`: the block lands `OPEN` with `total_qty`, `filled_qty`, and `allocated_through_seq` all zero, its allocation dimension `allocation_status` starting at `UNALLOCATED`, and a `BLOCK_CREATED` event. Every member order of the block shares its security and its side.

Attaching is guarded, and the guards fire in order: the block must be `OPEN` (`ERR_BLOCK_NOT_OPEN`); the order named by `order_id` must not already sit in a block (`ERR_ORDER_ALREADY_BLOCKED`); the order must be `APPROVED` (`ERR_ORDER_NOT_APPROVED`); its security must match the block's (`ERR_BLOCK_SECURITY_MISMATCH`); and its side must match (`ERR_BLOCK_SIDE_MISMATCH`). A successful attach sets the order's `block_id` to the block, moves the order `APPROVED → BLOCKED`, adds its `order_qty` into the block's `total_qty`, increments the block's `version`, writes `ORDER_ATTACHED`, and responds with the updated order. Detaching mirrors it: again the block must be `OPEN` (`ERR_BLOCK_NOT_OPEN`), evaluated before the membership check, and the order's `block_id` must actually point at this block (`ERR_ORDER_NOT_IN_BLOCK`). The order returns `BLOCKED → APPROVED` with `block_id` cleared, the block's `total_qty` loses the order's quantity, the block's `version` increments, `ORDER_DETACHED` lands, and the detachment responds with 204 and no body.

A block with no fills can be abandoned entirely. Cancelling a block requires it to be `OPEN` (`ERR_BLOCK_NOT_OPEN` from any other state) with `filled_qty` still zero: every member order returns `BLOCKED → APPROVED` with its `block_id` cleared, the block moves to the terminal `CANCELLED`, its `version` increments, and `BLOCK_CANCELLED` is written. Blocks are listed with optional `security_id`, `broker_id`, and `status` filters, and fetched individually by id.

### 3.6. Routing, Fills and Average Execution Price

Routing sends an assembled block to market: a `Trader` names the `broker_id`. The block must be `OPEN` (`ERR_BLOCK_NOT_OPEN`) and hold at least one member order — routing an empty block whose `total_qty` is zero is rejected `ERR_EMPTY_BLOCK`. The broker must exist (`ERR_BROKER_NOT_FOUND`), be ACTIVE (`ERR_BROKER_SUSPENDED`), and count the block security's asset class among its `supported_asset_classes` (`ERR_BROKER_ASSET_CLASS_UNSUPPORTED`); the security itself must be ACTIVE (`ERR_SECURITY_HALTED`). Routing stamps the block's `broker_id` and `routed_at` — the latter read from the logical clock — moves the block `OPEN → WORKING`, increments its `version`, and writes `BLOCK_ROUTED`. If the broker is suspended afterwards, in-flight `WORKING` blocks under it still receive fills, per §3.1.

Fills are booked by `ExecutionDesk`, never by the trader who routed the block. Each fill carries a strictly positive `fill_qty`, a strictly positive `fill_price_cents`, and the broker's `executed_at` timestamp; its `block_id` comes from the path. The block must be `WORKING` or `PARTIALLY_FILLED` — fills against a block in any other state are rejected `ERR_INVALID_STATE`. The timestamp must not precede the block's `routed_at` (`ERR_FILL_BEFORE_ROUTE`), the security must still be ACTIVE at recording (`ERR_SECURITY_HALTED`), and the fill must not push the block's cumulative `filled_qty` above its `total_qty` (`ERR_OVERFILL` — a fill that lands exactly on `total_qty` is accepted and completes the block). Each accepted fill receives a per-block monotone `fill_seq` starting at 1, the authoritative chronological ordering key since broker timestamps may tie or wander, and its computed `gross_amount_cents` is the fill quantity multiplied by the fill price. A fill is immutable: it carries `id` and `created_at` only, with no `updated_at` and no `version` (§2.4).

Every recorded fill recomputes the block's running statistics. The block's `filled_qty` becomes the sum of all fill quantities, and its `avg_fill_price_cents` becomes the volume-weighted average price over all fills recorded so far: each fill's quantity multiplied by its price, the products summed, the sum divided by the total filled quantity in exact decimal arithmetic, and the result rounded half-up to whole cents. This running figure is the provisional average — it moves with every fill and is null until the first one. The block's execution state then advances automatically: `WORKING → PARTIALLY_FILLED` while quantity remains outstanding, and `WORKING → FILLED` or `PARTIALLY_FILLED → FILLED` the moment the cumulative filled quantity equals `total_qty`. Each fill writes `FILL_RECORDED`, and the completing fill additionally writes `BLOCK_FILLED`; the block's `version` increments. One subtler consequence matters for allocation: if the block's `allocation_status` had reached `FULL` and a new fill arrives, the dimension drops back `FULL → PARTIAL`, because the new fill is uncovered by any posted plan (§3.7), and the block's `version` increments again. A block's fills are listed ordered by `fill_seq` ascending — the single exception to the default list ordering of §2.3.

### 3.7. Allocation Plans: Propose, Approve, Post

Once a block has fills, a `Trader` creates an allocation plan against it, choosing a `method` — PRO_RATA or EQUAL_SPLIT — and presenting `expected_block_version` per the concurrency rule of §2.7 (a mismatch is rejected `ERR_STALE_VERSION`, HTTP 412). The block must be `PARTIALLY_FILLED` or `FILLED`; creating against a block in any other execution state is rejected `ERR_INVALID_STATE`. Creation snapshots `covered_from_seq` from the block's current `allocated_through_seq` watermark — the batch's exclusive lower bound — and records the creator's header as `created_by_user_id`, the segregation-of-duties anchor for later approval. Crucially, creation supersedes any existing plan of the same block still in `DRAFT`, `PROPOSED`, or `APPROVED`: the older plan becomes `SUPERSEDED`, any PROPOSED allocation lines it held are deleted, and `PLAN_SUPERSEDED` is written. The new plan starts `DRAFT` with its batch fields — `covered_to_seq`, `batch_qty`, `batch_avg_price_cents`, and `max_deviation_bp` — all null until the first successful propose, and the block's `version` increments.

Proposing computes the batch. The block must still hold at least one member order (`ERR_EMPTY_BLOCK`), and there must be something to allocate — at least one fill whose `fill_seq` lies beyond `covered_from_seq`, otherwise `ERR_NOTHING_TO_ALLOCATE`; the empty-block check is evaluated first. The proposal sets `covered_to_seq` to the greatest `fill_seq` present, computes `batch_qty` as the total quantity of the fills strictly inside the window from `covered_from_seq` exclusive to `covered_to_seq` inclusive, and freezes `batch_avg_price_cents` as the volume-weighted average over exactly those fills — the same weighted-average shape as §3.6, exact-decimal division rounded half-up to whole cents, but over the covered batch only. For a block with fills outside the batch, this final-batch average deliberately differs from the block's running average. Allocation lines are then created in `PROPOSED` status, one per member order, and `max_deviation_bp` measures their fairness; `PLAN_PROPOSED` is written and the plan's `version` increments.

The split is deterministic. Member orders are the block's attached orders at propose time — every order whose `block_id` still points at the block and whose status is `BLOCKED`, `ALLOCATED`, or `UNDER_CORRECTION` — ranked by `created_at` ascending. Under PRO_RATA, each member's ideal share is the batch quantity multiplied by the member's `order_qty` and divided by the total of all members' quantities, kept as an exact decimal. Under EQUAL_SPLIT, each member's ideal is the batch quantity divided by the member count, also exact — so unequal member quantities yield different per-account results under the two methods over identical fills. Every member's base allocation is its ideal rounded down to a whole unit; the leftover units — the batch quantity minus the sum of the bases — are dealt out one unit at a time to members ranked by fractional part descending, ties broken first by larger `order_qty` and then by earlier `created_at`. A member's final `alloc_qty` is its base plus one if it received a leftover unit, and each line's `alloc_price_cents` is the plan's frozen `batch_avg_price_cents`.

Fairness is measured against the PRO_RATA ideal always — even when the plan's method is EQUAL_SPLIT. Per member: if the pro-rata ideal is zero, the deviation is zero when the member received nothing and 99999 basis points — the deviation cap — when it received something; otherwise the deviation is the absolute gap between the member's `alloc_qty` and its pro-rata ideal, divided by that ideal, scaled by ten thousand, and rounded half-up to integer basis points. The plan's `max_deviation_bp` is the largest per-member deviation.

Approval belongs to `ComplianceOfficer`, with two gates evaluated segregation of duties first: the approver's `X-User-ID` must differ from the plan's `created_by_user_id` — the trader who built the plan cannot approve it — or `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) fires; and `max_deviation_bp` must be at most 200 basis points, two percent of the pro-rata ideal, or `ERR_UNFAIR_ALLOCATION` (HTTP 422) fires. Approval stamps `approved_by_user_id` with the approver's header, moves the plan `PROPOSED → APPROVED`, and writes `PLAN_APPROVED`. Alternatively the officer returns the plan: `PROPOSED → DRAFT`, the proposed allocation lines are deleted, the computed batch fields (`covered_to_seq`, `batch_qty`, `batch_avg_price_cents`, `max_deviation_bp`) are cleared for a fresh proposal, and `PLAN_RETURNED` is written. Approving or returning a plan that is not `PROPOSED` is a generic from-state mismatch, `ERR_INVALID_STATE`.

Posting is the point of no return, performed by a `Trader` on an `APPROVED` plan — any other plan state is rejected `ERR_PLAN_NOT_POSTABLE`. Every line's account must first be ACTIVE (`ERR_ACCOUNT_SUSPENDED`). The batch must then still be current: if fills with `fill_seq` beyond `covered_to_seq` now exist and the block is not yet `FILLED`, the plan is stale, the post is rejected `ERR_PLAN_STALE_BATCH`, and the plan must be returned and re-proposed. Only then does the fiscal gate run, per distinct account in the plan: the account must have an OPEN budget whose half-open window covers the trade date — the calendar date of the latest `executed_at` among the covered fills — otherwise `ERR_NO_ACTIVE_BUDGET`; and the projected accrual, the budget's current `accrued_commission_cents` plus the sum of that account's line commissions, must not exceed `budget_amount_cents`, or the entire post is rejected `ERR_COMMISSION_BUDGET_EXCEEDED`. Exact equality is allowed and, per §3.2, flips the budget to EXHAUSTED.

Commissions are computed per line at the moment of posting: the line's notional — its `alloc_qty` multiplied by its `alloc_price_cents` — is multiplied by the routed broker's `commission_rate_bp` and divided by ten thousand, then rounded half-up to whole cents and stored as the line's `commission_cents`. Each line is rounded individually and only afterwards summed per account for the accrual; rounding a summed notional once is forbidden, since per-line-rounded sums can differ by cents. On a successful post, every line moves `PROPOSED → POSTED`; each account's budget accrues its lines' commissions; a Position row is upserted per account-and-security pair with `net_qty` increased by the signed allocated quantity, positive for a BUY block and negative for a SELL block; every covered member order moves `BLOCKED → ALLOCATED` with its `allocated_qty` recomputed as the sum of `alloc_qty` over its lines in `POSTED`, `SETTLED`, or `ERROR_FLAGGED` and its `avg_executed_price_cents` recomputed as the quantity-weighted average of `alloc_price_cents` over the same line set, rounded half-up to whole cents and null until the order's first POSTED line, writing `ORDER_ALLOCATED` (an order already `ALLOCATED` from an earlier batch keeps its status — its statistics are still recomputed and its `version` still increments, but no second `ORDER_ALLOCATED` event is written); the block's `allocated_through_seq` watermark advances to `covered_to_seq`, its `allocation_status` becomes `PARTIAL` — or `FULL` when the watermark now reaches the greatest `fill_seq` — and the block's `version` increments; exactly one settlement instruction per line is created in `PENDING` (§3.9); the plan's own `version` increments; and `PLAN_POSTED` lands. Later posts on later batches move the block's allocation dimension from `PARTIAL` to `FULL` by the same watermark comparison. A block's plans are listed under the block, individual plans are fetched by id, and allocation lines are listed system-wide with optional `plan_id`, `account_id`, `order_id`, `corrects_allocation_id`, and `status` filters or fetched individually.

### 3.8. Trade Errors and Correction Accounting

When a posted allocation turns out wrong, nobody edits it in place. A `SettlementOps` or `ComplianceOfficer` operator flags the line, supplying an `error_type` of WRONG_ACCOUNT, WRONG_QTY, or WRONG_PRICE and an optional free-text `note`. The line must be `POSTED` — flagging in any other state is `ERR_INVALID_STATE` — and must not already have an OPEN trade error (`ERR_ERROR_ALREADY_OPEN`). The from-state guard is evaluated first: a line carrying an OPEN trade error is itself always `ERROR_FLAGGED`, so a repeated flag against such a line surfaces `ERR_INVALID_STATE`. Flagging creates a TradeError in `OPEN`, recording the flagged `allocation_id` and the operator's header as `flagged_by_user_id`, moves the allocation `POSTED → ERROR_FLAGGED`, bumps the line's `version`, tips the owning order `ALLOCATED → UNDER_CORRECTION` with an `ORDER_UNDER_CORRECTION` event, and writes `ERROR_FLAGGED`. A flagged line still counts toward positions, budget accruals, and order fill statistics — nothing is unwound until a correction actually lands.

Correction belongs to `DeskAdmin`, and its shape depends on the error type. For WRONG_ACCOUNT, `target_account_id` is required; the target account must be different from the original account (`ERR_INVALID_REQUEST`, evaluated with the request-shape rules) and must be ACTIVE (`ERR_ACCOUNT_SUSPENDED`). For WRONG_QTY, `corrected_qty` is required and must be strictly greater than zero and strictly less than the original line's `alloc_qty` — anything else is `ERR_CORRECTION_QTY_EXCEEDS`; the residual quantity is absorbed by the desk's ERROR account, selected among ACTIVE accounts whose `account_type` is ERROR with ties broken by earliest `created_at`, and if no such account exists the correction is rejected `ERR_NO_ERROR_ACCOUNT`. For WRONG_PRICE, `corrected_price_cents` is required and strictly positive (`ERR_INVALID_REQUEST` otherwise). In all cases the original line's settlement instruction must not already be `SETTLED` (`ERR_ALLOCATION_ALREADY_SETTLED`), and every account receiving a correction line must have an OPEN budget covering the trade date with room for the recomputed commissions (`ERR_NO_ACTIVE_BUDGET`, then `ERR_COMMISSION_BUDGET_EXCEEDED`) — where a receiving account is the original line's own account, the projection nets the original line's `commission_cents` out of the current accrual before adding the recomputed commissions, because the reversal unwinds it.

A successful correction resolves the error, moving it `OPEN → RESOLVED`, and rewrites the books in a fixed sequence. The original line moves `ERROR_FLAGGED → REVERSED`: its signed quantity comes out of the position, its `commission_cents` comes out of the budget accrual, and its settlement instruction — if still `PENDING`, `INSTRUCTED`, or `FAILED` — is `CANCELLED` with an `INSTRUCTION_CANCELLED` event. Correction lines are then created directly in `POSTED`, each carrying `corrects_allocation_id` pointing at the reversed original and inheriting the original's `plan_id` and `order_id`; the primary corrected line is created first and, for WRONG_QTY, the ERROR-account residual line second. A WRONG_PRICE correction line carries the corrected price as its `alloc_price_cents`. Commissions are recomputed line by line under the same pinned per-line rounding as §3.7 and accrued to the receiving accounts' budgets, positions are updated by the signed correction quantities, and one `PENDING` settlement instruction is created per correction line. If no sibling line of the order remains `ERROR_FLAGGED`, the order returns `UNDER_CORRECTION → ALLOCATED` with its `allocated_qty` and `avg_executed_price_cents` recomputed and an `ORDER_CORRECTION_CLEARED` event. `ERROR_CORRECTED` is written, and the trade error's `version` increments.

Dismissal is the false-alarm path, also `DeskAdmin`: the error moves `OPEN → DISMISSED`, the flagged line returns `ERROR_FLAGGED → POSTED` exactly as it was — compensation restores the line rather than rewriting it — the order's correction context clears if no flagged siblings remain, `ERROR_DISMISSED` is written, and the error's `version` increments. Trade errors are listed with optional `allocation_id` and `status` filters, and fetched individually by id.

### 3.9. Settlement Instructions, Fail Escalation and Positions

Posting a plan — and, later, landing a correction — creates exactly one settlement instruction per POSTED line, starting in `PENDING` with `fail_count` at zero. The instruction captures `custodian_name` copied from the account at creation, computes `trade_date` as the calendar date of the latest `executed_at` across the covered fills, and derives `settle_date` by adding the security's settlement lag in calendar days — one day for EQUITY, two days for FIXED_INCOME. `SettlementOps` then works the lifecycle. Instructing moves `PENDING → INSTRUCTED` and writes `INSTRUCTION_INSTRUCTED`. Settling moves `INSTRUCTED → SETTLED` and writes `INSTRUCTION_SETTLED`.

Settlement is an economic fact and is allowed regardless of the owning allocation's state — but it only propagates when the allocation is currently `POSTED`, moving it `POSTED → SETTLED` with an `ALLOCATION_SETTLED` event. Settling the instruction of an `ERROR_FLAGGED` line leaves the line untouched, and any later correction attempt on that line is rejected `ERR_ALLOCATION_ALREADY_SETTLED`. When every line of an order has reached `SETTLED`, the order bubbles up to the terminal `SETTLED` with an `ORDER_SETTLED` event — from `ALLOCATED` directly, or from `UNDER_CORRECTION` once no flagged lines remain. Each lifecycle action increments the instruction's `version`.

Failure is a first-class outcome. An operator fails an `INSTRUCTED` instruction with a `fail_reason` of BROKER_NON_DELIVERY, CUSTODIAN_MISMATCH, INSUFFICIENT_POSITION, or OTHER and an optional `note`; the instruction — identified by `instruction_status` — moves `INSTRUCTED → FAILED`, its `fail_count` increments by one, and `INSTRUCTION_FAILED` is written. Repair moves `FAILED → INSTRUCTED` and writes `INSTRUCTION_REPAIRED`, and deliberately does not reset `fail_count` — the last `fail_reason` is likewise retained. When `fail_count` reaches two, escalation fires automatically: the allocation's account is suspended by the system, which itself cascades the order cancellations of §3.1. The fail monitor automates the same transition: a `SettlementOps`-driven sweep marks every `INSTRUCTED` instruction whose current logical date is strictly later than its `settle_date` plus one calendar day as FAILED with reason OTHER — an instruction exactly one day past its settle date is not yet failed — applies the escalation cascade per instruction, and reports `checked_count`, `failed_count`, and the `failed_instruction_ids`. Finally, whenever error correction reverses a line, its instruction in `PENDING`, `INSTRUCTED`, or `FAILED` is cancelled by the system with `INSTRUCTION_CANCELLED`; `SETTLED` instructions are never cancelled — the correction is refused instead, as §3.8 describes. Instructions are listed with optional `allocation_id` and `status` filters, and fetched individually by id.

Positions close the loop. A Position row per `account_id`-and-`security_id` pair accumulates `net_qty` as the sum of signed allocated quantities — positive for BUY, negative for SELL — over exactly the lines in `POSTED`, `SETTLED`, or `ERROR_FLAGGED`; `PROPOSED` and `REVERSED` lines contribute nothing. Rows are upserted when a plan posts, decremented when a line reverses, and incremented again when correction lines post. Positions are listed with optional `account_id` and `security_id` filters, and fetched individually by id (`ERR_POSITION_NOT_FOUND` for an unknown id).

## 4. Endpoint Definitions

Status codes follow one convention throughout: creating a new resource returns 201 — this covers accounts, securities, brokers, commission budgets, restrictions, orders, blocks, fills, allocation plans, and flagging a trade error, which creates the error record — while state-changing actions on an existing resource, single-resource retrievals, and listings return 200. The single exception is order detachment from a block, which returns 204 with an empty body. The table below is a map only: request payloads, response bodies, and side effects are specified by the narratives of Section 3, keyed back by the state transitions and role-plus-action framing used there.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/trading/accounts` | Create an account (starts ACTIVE) | DeskAdmin |
| GET | `/trading/accounts/{accountId}` | Get one account | All six roles |
| POST | `/trading/accounts/{accountId}/status` | Set account status (ACTIVE / SUSPENDED); suspension cascades order cancellations | DeskAdmin |
| POST | `/trading/securities` | Create a security (starts ACTIVE) | DeskAdmin |
| GET | `/trading/securities/{securityId}` | Get one security | All six roles |
| POST | `/trading/securities/{securityId}/status` | Set security status (ACTIVE / HALTED) | DeskAdmin |
| POST | `/trading/brokers` | Create a broker (starts ACTIVE) | DeskAdmin |
| GET | `/trading/brokers/{brokerId}` | Get one broker | All six roles |
| POST | `/trading/brokers/{brokerId}/status` | Set broker status (ACTIVE / SUSPENDED); in-flight blocks may still receive fills | DeskAdmin |
| POST | `/trading/accounts/{accountId}/commission-budgets` | Create a commission budget for the account; overlapping half-open periods rejected | DeskAdmin |
| GET | `/trading/commission-budgets/{budgetId}` | Get one commission budget | All six roles |
| GET | `/trading/commission-budgets` | List commission budgets, filterable by account and status, paginated | All six roles |
| POST | `/trading/restrictions` | Create a restriction in DRAFT (overlap checked only at activation) | ComplianceOfficer |
| GET | `/trading/restrictions/{restrictionId}` | Get one restriction | All six roles |
| GET | `/trading/restrictions` | List restrictions, filterable by account, security, and status, paginated | All six roles |
| POST | `/trading/restrictions/{restrictionId}/activate` | Activate a DRAFT or SUSPENDED restriction; same-key closed-window overlap rejected | ComplianceOfficer |
| POST | `/trading/restrictions/{restrictionId}/suspend` | Suspend an ACTIVE restriction | ComplianceOfficer |
| POST | `/trading/restrictions/{restrictionId}/retire` | Retire a DRAFT, ACTIVE, or SUSPENDED restriction (terminal) | ComplianceOfficer |
| POST | `/trading/orders` | Create an order in PENDING_COMPLIANCE (compliance evaluated only by the check) | Trader |
| GET | `/trading/orders/{orderId}` | Get one order | All six roles |
| GET | `/trading/orders` | List orders, filterable by account, security, block, and status, paginated | All six roles |
| POST | `/trading/orders/{orderId}/compliance-check` | Run pre-trade compliance: account/security gates, then restriction rules | ComplianceOfficer |
| POST | `/trading/orders/{orderId}/cancel` | Cancel an order in PENDING_COMPLIANCE, COMPLIANCE_REJECTED, or APPROVED | Trader |
| POST | `/trading/blocks` | Create an empty block (OPEN, UNALLOCATED) | Trader |
| GET | `/trading/blocks/{blockId}` | Get one block | All six roles |
| GET | `/trading/blocks` | List blocks, filterable by security, broker, and status, paginated | All six roles |
| POST | `/trading/blocks/{blockId}/orders` | Attach an APPROVED order to an OPEN block (same security and side) | Trader |
| DELETE | `/trading/blocks/{blockId}/orders/{orderId}` | Detach an order from an OPEN block | Trader |
| POST | `/trading/blocks/{blockId}/cancel` | Cancel an OPEN block with no fills; member orders return to APPROVED | Trader |
| POST | `/trading/blocks/{blockId}/route` | Route an OPEN block to a broker for execution (WORKING) | Trader |
| POST | `/trading/blocks/{blockId}/fills` | Record an execution fill against a WORKING or PARTIALLY_FILLED block | ExecutionDesk |
| GET | `/trading/blocks/{id}/fills` | List fills of a block, ordered by fill_seq ascending | All six roles |
| POST | `/trading/blocks/{blockId}/allocation-plans` | Create an allocation plan (DRAFT) for a PARTIALLY_FILLED or FILLED block; supersedes non-terminal plans; OCC-guarded | Trader |
| GET | `/trading/allocation-plans/{planId}` | Get one allocation plan | All six roles |
| GET | `/trading/blocks/{id}/allocation-plans` | List allocation plans of a block | All six roles |
| POST | `/trading/allocation-plans/{planId}/propose` | Compute the batch, per-order lines, and fairness deviation (DRAFT to PROPOSED) | Trader |
| POST | `/trading/allocation-plans/{planId}/approve` | Approve a PROPOSED plan (segregation of duties plus fairness gate) | ComplianceOfficer |
| POST | `/trading/allocation-plans/{planId}/return` | Return a PROPOSED plan to DRAFT; proposed lines discarded | ComplianceOfficer |
| POST | `/trading/allocation-plans/{planId}/post` | Post an APPROVED plan: lines POSTED, budgets accrued, positions updated, orders ALLOCATED, instructions created | Trader |
| GET | `/trading/allocations/{allocationId}` | Get one allocation line | All six roles |
| GET | `/trading/allocations` | List allocation lines, filterable by plan, account, order, corrected-original, and status, paginated | All six roles |
| POST | `/trading/allocations/{allocationId}/flag-error` | Flag a POSTED allocation as erroneous; creates a TradeError (OPEN), line moves to ERROR_FLAGGED | SettlementOps, ComplianceOfficer |
| GET | `/trading/trade-errors/{errorId}` | Get one trade error | All six roles |
| GET | `/trading/trade-errors` | List trade errors, filterable by allocation and status, paginated | All six roles |
| POST | `/trading/trade-errors/{errorId}/correct` | Correct an OPEN trade error; original line REVERSED, correction line(s) POSTED | DeskAdmin |
| POST | `/trading/trade-errors/{errorId}/dismiss` | Dismiss an OPEN trade error; flagged line returns to POSTED unchanged | DeskAdmin |
| GET | `/trading/settlement-instructions/{instructionId}` | Get one settlement instruction | All six roles |
| GET | `/trading/settlement-instructions` | List settlement instructions, filterable by allocation and status, paginated | All six roles |
| POST | `/trading/settlement-instructions/{instructionId}/instruct` | Send a PENDING (or repaired) instruction to the custodian (INSTRUCTED) | SettlementOps |
| POST | `/trading/settlement-instructions/{instructionId}/settle` | Mark an INSTRUCTED instruction settled; allocation and order bubble-up follows | SettlementOps |
| POST | `/trading/settlement-instructions/{instructionId}/fail` | Mark an INSTRUCTED instruction failed; fail_count increments; second failure escalates | SettlementOps |
| POST | `/trading/settlement-instructions/{instructionId}/repair` | Repair a FAILED instruction back to INSTRUCTED (fail_count not reset) | SettlementOps |
| POST | `/trading/settlement-instructions/run-fail-monitor` | Batch sweep: overdue INSTRUCTED instructions become FAILED, escalation cascades apply | SettlementOps |
| GET | `/trading/positions/{positionId}` | Get one position | All six roles |
| GET | `/trading/positions` | List positions, filterable by account and security, paginated | All six roles |
| GET | `/trading/audit-events` | List audit events (append-only retention), filterable by entity type and id, paginated | ComplianceOfficer, DeskAdmin, Auditor |
| POST | `/trading/_clock/set_current_utc` | Set the server's logical clock (monotone; startup default 2026-08-01T00:00:00Z) | DeskAdmin |

## 5. Error Code Catalogue

The catalogue below fixes every error identifier and its HTTP status. Trigger conditions are deliberately not repeated here — they are specified in the narratives of Sections 2 and 3 next to the workflows they guard.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_INVALID_REQUEST | 400 |
| ERR_ACCOUNT_NOT_FOUND | 404 |
| ERR_SECURITY_NOT_FOUND | 404 |
| ERR_BROKER_NOT_FOUND | 404 |
| ERR_ORDER_NOT_FOUND | 404 |
| ERR_BLOCK_NOT_FOUND | 404 |
| ERR_BUDGET_NOT_FOUND | 404 |
| ERR_RESTRICTION_NOT_FOUND | 404 |
| ERR_PLAN_NOT_FOUND | 404 |
| ERR_ALLOCATION_NOT_FOUND | 404 |
| ERR_TRADE_ERROR_NOT_FOUND | 404 |
| ERR_INSTRUCTION_NOT_FOUND | 404 |
| ERR_POSITION_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_ACCOUNT_TYPE_FORBIDDEN | 422 |
| ERR_ACCOUNT_SUSPENDED | 409 |
| ERR_SECURITY_HALTED | 409 |
| ERR_BROKER_SUSPENDED | 409 |
| ERR_BROKER_ASSET_CLASS_UNSUPPORTED | 422 |
| ERR_TRADE_PROHIBITED | 422 |
| ERR_POSITION_LIMIT_BREACH | 422 |
| ERR_LOT_SIZE_VIOLATION | 422 |
| ERR_BLOCK_SECURITY_MISMATCH | 422 |
| ERR_BLOCK_SIDE_MISMATCH | 422 |
| ERR_ORDER_ALREADY_BLOCKED | 409 |
| ERR_ORDER_NOT_APPROVED | 409 |
| ERR_ORDER_NOT_IN_BLOCK | 409 |
| ERR_BLOCK_NOT_OPEN | 409 |
| ERR_EMPTY_BLOCK | 422 |
| ERR_OVERFILL | 422 |
| ERR_FILL_BEFORE_ROUTE | 422 |
| ERR_BUDGET_PERIOD_OVERLAP | 409 |
| ERR_RESTRICTION_WINDOW_OVERLAP | 409 |
| ERR_NOTHING_TO_ALLOCATE | 422 |
| ERR_PLAN_NOT_POSTABLE | 409 |
| ERR_PLAN_STALE_BATCH | 409 |
| ERR_UNFAIR_ALLOCATION | 422 |
| ERR_ERROR_ALREADY_OPEN | 409 |
| ERR_ALLOCATION_ALREADY_SETTLED | 409 |
| ERR_CORRECTION_QTY_EXCEEDS | 422 |
| ERR_NO_ERROR_ACCOUNT | 422 |
| ERR_NO_ACTIVE_BUDGET | 422 |
| ERR_COMMISSION_BUDGET_EXCEEDED | 422 |
