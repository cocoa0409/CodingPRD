# Mobile Home Lease API — Product Requirements Document

## 1. Introduction

Mobile home parks occupy an unusual corner of residential real estate. A park owns the land and the lots, sometimes owns the homes themselves, and rents to long-tenured residents whose dwellings are too large to move once placed. The legal regime governing these tenancies is deeply state-specific: some jurisdictions cap annual rent increases by statute, others leave the matter to the market, and most impose strict notice windows and cure periods before an eviction can finalize. Operationally, a park manager must coordinate rent billing, master-metered utility apportionment, eviction proceedings, conversions between park-owned and resident-owned tenure, and the resale of resident-owned homes — each governed by its own timeline and each capable of unwinding the others.

The Mobile Home Lease API exists to make this coordination tractable in a single system of record. It must enforce the state-by-state ceiling on rent-increase notices, run a defensible monthly billing sweep that distributes a single master utility bill across occupied lots in cent-exact increments, and gate every consequential transition — eviction filings, conversion finalizations, sale closings — on the same set of fiscal and compliance preconditions that govern the underlying contracts. The system serves three operational actors with sharply divergent authority: park managers who run a specific park, residents who interact only with their own resources, and platform administrators who advance the test clock and run the scheduled sweeps that materialize time-gated transitions.

## 2. Global Specifications & System-Wide Principles

This section captures the cross-cutting rules that every endpoint inherits — authentication, response shape, pagination, the common audit fields, the precision conventions, and the concurrency model.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which declares the role under which the request is made. Both headers must be present and non-empty; a request that violates this rule is rejected with `ERR_AUTH_REQUIRED`. A request whose role is not authorized for the targeted endpoint per the §4 endpoint table is rejected with `ERR_FORBIDDEN`.

The system recognises three roles with exact spelling:

- `ParkManager` — the operator of a specific park. When `X-User-Role` is `ParkManager`, `X-User-ID` is the `id` of the acting `Park`; ownership checks on any resource that references a `Park` (a `Lot`, a `Home`, or any descendant of those) compare the resource's `park_id` to `X-User-ID`. A `ParkManager` may only act on lots, leases, notices, evictions, transfers, and conversions whose `park_id` matches the header.
- `Resident` — an individual tenant. When `X-User-Role` is `Resident`, `X-User-ID` is the `id` of the acting `Resident`; ownership checks on any resource that references a `Resident` compare the resource's `resident_id` (for a `Lease`) or `owner_resident_id` (for a `Home`) to `X-User-ID`. Resident-only mutations (paying a lease, curing an eviction, accepting or rejecting a conversion offer) additionally require the acting `Resident` to match the resource owner; mismatch is rejected with `ERR_FORBIDDEN_NOT_OWNER`.
- `PlatformAdmin` — a cross-park operator. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit purposes but does not compare it to any entity's `id`. A `PlatformAdmin` is the only role permitted to advance the test clock or run the billing, eviction, and rent-effective sweeps.

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

List endpoints accept two query parameters. The `limit` parameter defaults to 10, with a minimum of 1 and a maximum of 100; the `offset` parameter defaults to 0 and has no upper bound. Unless otherwise specified, list endpoints return resources sorted by their `created_at` timestamp in ascending order. The response envelope's `meta` block for list responses always carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Most resources in the system carry a uniform audit envelope of four server-managed fields:

- `id` — a server-minted UUID with no domain-specific prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, set on initial persistence.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation that changes the resource's persisted fields.
- `version` — an integer that begins at 1 and increments by exactly one with each mutation that refreshes `updated_at`.

A `Park`, a `Lot`, a `Home`, a `Resident`, a `Lease`, a `RentIncreaseNotice`, an `EvictionCase`, a `HomeSaleTransfer`, and a `ConversionRequest` all carry the full four-field envelope. The only exception is a `UtilityBill`: because a bill is materially immutable once written by the billing sweep (its only mutation is the one-shot `paid_at` stamp captured on the lease-level pay action), a `UtilityBill` carries `id` and `created_at` but no `updated_at` and no `version`.

### 2.5. Nested Resource Retrieval

URL paths in this API frequently nest one resource under another (e.g., `/parks/{park_id}/lots` or `/lots/{lot_id}/utility-bills`). When a request targets a nested path, the server validates every path identifier in strict left-to-right order. The first path identifier that does not correspond to an existing resource yields an immediate `ERR_RESOURCE_NOT_FOUND` response, before any subsequent identifier or any body-level reference is consulted. Body-level references — a `lease_id`, `home_id`, `resident_id`, or any other identifier embedded in the request payload — are checked only after every path identifier has resolved, and a missing body-level resource yields `ERR_REFERENCED_RESOURCE_NOT_FOUND`.

### 2.6. Monetary Precision and Rounding

All monetary fields in the API are stored and exchanged as integer cents. Intermediate arithmetic uses native floating-point only when computing a percentage; the final cent value is then rounded half up to the nearest integer cent. Utility apportionment differs slightly: each lot's raw fractional cent share is truncated downward (floor) to a whole cent, and the residual cents that remain after summing the floors are redistributed one-per-lot to the occupied lots in ascending `lot_number` order until the sum exactly equals the master meter total. Proration of a partial-period rent uses the same floor truncation. The net effect is that no apportionment or proration ever creates phantom cents, and the master total of any sweep is reconciled exactly.

### 2.7. Hierarchical Consistency and the Audit Envelope

A single user-initiated action frequently mutates more than one resource — a sweep creates many `UtilityBill` rows and refreshes the `outstanding_balance_cents` on every affected `Lease`, the close of a home sale terminates one lease and creates its successor, and a conversion finalization rewrites a `Lot`'s ownership and adjusts a `Park`'s counter. Whenever a resource's persisted fields change as a side effect of any operation, the server refreshes its `updated_at` and increments its `version` by one. The cascades themselves are spelled out in §3 alongside the workflow that drives them; the universal rule here is that no side-effect mutation is silent — the `updated_at` and `version` envelope follows the data.

A specific consistency invariant is worth pulling out at this level: `Park.ownership_pool_count` is the count of `Lot` rows under that park whose `ownership_mode` equals `PARK_OWNED`. The counter is initialised to zero on park creation, incremented by one when a new lot is created (every lot starts in `PARK_OWNED` mode), and decremented by one whenever a conversion finalize switches a lot from `PARK_OWNED` to `RESIDENT_OWNED`. There is no opposite direction — the park-to-resident conversion is one-way only.

### 2.8. Optimistic Concurrency Control

Mutation endpoints that target a specific resource by its identifier may carry an optional `version` field in their request body. When `version` is supplied, the server compares it to the resource's current `version` before applying the mutation: a mismatch causes the request to be rejected with `ERR_VERSION_MISMATCH`, the resource is unchanged, and no side effects fire. When `version` is omitted from the body, the server skips the comparison and processes the mutation without any concurrency check. The only PATCH endpoint in this API, the lot sub-meter reading update at `/lots/{lot_id}`, follows this rule, as does any future mutation that accepts a `version` in its payload.

Several mutation pairs that are not OCC-mediated have explicit serialization guarantees instead. Two simultaneous approvals of the same `HomeSaleTransfer` serialize on the transfer's `status` field; exactly one wins the `PENDING_PARK_APPROVAL → APPROVED` transition and the loser receives `ERR_INVALID_STATE`. When a `ParkManager` issues a dismissal on an `EvictionCase` at the same moment the eviction sweep is finalizing it for cause, exactly one of `DISMISSED` or `FINALIZED_FOR_CAUSE` wins on the case's `status` and the loser receives `ERR_INVALID_STATE`. Two concurrent issue requests on the same draft `RentIncreaseNotice` serialize on its `status`; one issues and the other is rejected with `ERR_INVALID_STATE`. A conversion finalize and a home-sale close that race on the same `Lot` serialize on `Lot.version`; at most one mutates the lot's `ownership_mode` or `current_lease_id`, and the loser receives `ERR_LOT_OCCUPIED_BY_PENDING_OP`. Two simultaneous pay actions on the same delinquent lease serialize on the drop of `Lease.outstanding_balance_cents` to zero; one succeeds in marking the bills paid and the duplicate is rejected with `ERR_INVALID_STATE`.

### 2.9. State-Specific Rent-Increase Caps

Each `Park` declares the state in which it operates via the `state_code` field, which must be one of `CA`, `FL`, `OR`, `AZ`, or `TX`. The state code selects which annual rent-increase cap law applies when a `RentIncreaseNotice` is issued, and the park-level `master_cpi_pct` provides the consumer price index input for states whose statutes add CPI to a base percentage:

- A park in `CA` caps the annual increase at five percent plus the park's `master_cpi_pct`, with a hard absolute ceiling of ten percent. That is, the effective cap is the smaller of `5.0 + master_cpi_pct` and `10.0`.
- A park in `OR` caps the annual increase at seven percent plus the park's `master_cpi_pct`, with the same hard absolute ceiling of ten percent — the effective cap is the smaller of `7.0 + master_cpi_pct` and `10.0`.
- A park in `AZ` caps the annual increase at a flat ten percent; the `master_cpi_pct` value is not consulted for `AZ`.
- A park in `FL` or `TX` has no statutory cap; any proposed increase is accepted at the proposed value regardless of its magnitude.

The cap application itself is described in §3 alongside the issuance workflow it governs. The `master_cpi_pct` field on a park is an input value between zero and twenty inclusive, expressed with two decimal places of precision; it represents a percent, not a fraction (a CPI of two percent is stored as the number `2.00`).

### 2.10. Validation Priority and the Compliance Cascade

Every endpoint that the system exposes runs its inbound request through the same ordered chain of validation gates, and the order matters whenever a single request would fail multiple checks. The gates are evaluated in the order below, and the first one to fail returns its error:

1. Authentication — both `X-User-Role` and `X-User-ID` headers must be present and non-empty, otherwise `ERR_AUTH_REQUIRED`.
2. Authorization — the role must be authorized for the target endpoint per §4, otherwise `ERR_FORBIDDEN`.
3. Path-resource existence — every identifier in the URL path must resolve, evaluated strictly left-to-right per §2.5; the first missing identifier yields `ERR_RESOURCE_NOT_FOUND`.
4. Body-resource existence — every identifier embedded in the request body (a `resident_id`, `home_id`, `lease_id`, `lot_id`, `seller_resident_id`, `buyer_resident_id`, or `prospective_buyer_resident_id`) must resolve, otherwise `ERR_REFERENCED_RESOURCE_NOT_FOUND`.
5. Owner identity — Resident-only mutations (paying a lease, curing an eviction, accepting or rejecting a conversion offer) require the acting `Resident` to match the resource's `resident_id` or `owner_resident_id`, otherwise `ERR_FORBIDDEN_NOT_OWNER`.
6. Source-state legality — the target resource must be in a state from which the requested transition is permitted, otherwise `ERR_INVALID_STATE`.
7. OCC version match — when the body carries a `version`, it must equal the resource's current `version`, otherwise `ERR_VERSION_MISMATCH`.

Domain-specific gates run after the universal seven and are described inline with their workflows in §3. Their priority within a single endpoint is fixed by the same numerical order in which they are introduced in this document — most notably, on the issue path for a rent-increase notice, the eviction-pending block (priority 15, surfacing as `ERR_RENT_INCREASE_BLOCKED_DURING_EVICTION`) is evaluated before the strict-greater-than check on the proposed rent (priority 16, surfacing as `ERR_RENT_INCREASE_NONPOSITIVE`); on the cure path, the no-cure-permitted check for `ILLEGAL_USE` (priority 8, surfacing as `ERR_NO_CURE_PERMITTED`) is evaluated before the cure-window-expired check (priority 14, surfacing as `ERR_CURE_WINDOW_EXPIRED`), and both run before the nonpayment balance check (priority 17, surfacing as `ERR_BALANCE_NOT_ZERO`).

### 2.11. The Logical Clock and Scheduled Sweeps

The system maintains a logical wall clock that drives every time-gated transition: cure-deadline finalizations, rent-increase notices crossing their `effective_on`, and the monthly billing run. A `PlatformAdmin` test-driving capability advances the clock by a supplied number of `seconds`. Three scheduled-sweep capabilities, each `PlatformAdmin`-only, materialize the time-gated transitions in a deterministic order: a billing sweep that takes a `park_id`, `billing_period_start`, `billing_period_end`, and `master_total_cents` and produces one `UtilityBill` per occupied lot; an eviction sweep that finalizes any `IN_CURE` case whose `cure_deadline` has passed; and a rent-effective sweep that promotes any `ISSUED` `RentIncreaseNotice` whose `effective_on` has been reached. Their concrete side-effect chains are described in §3.

## 3. Business Logic & Workflows

### 3.1. Parks, Lots, and Homes — the Physical Substrate

A `Park` is the top-level operational tenant in the system. A `ParkManager` or a `PlatformAdmin` registers a new park by supplying its display `name` (between 1 and 120 characters, unique per park), the two-letter `state_code` selecting the applicable rent-increase law, the `master_cpi_pct` value driving the CPI add-on, the park-level `utility_apportionment_method` choosing between `SUB_METER` and `EQUAL_SPLIT` apportionment, and the `billing_period_anchor_day` (an integer day-of-month between 1 and 28 inclusive, used as the anchor for the monthly billing sweep). A freshly created park reports an `ownership_pool_count` of zero — the counter is system-maintained and grows or shrinks only as lots are added or as conversion finalizations flip a lot from park-owned to resident-owned.

A `Lot` lives under a single park and is created by a `ParkManager` via a payload carrying `lot_number` (a 1-to-16-character string that must be unique within its parent park — duplicates are rejected with `ERR_DUPLICATE_LOT_NUMBER`), the `base_rent_cents` (the lot's current monthly rent in cents, strictly greater than zero, mutated subsequently only when a rent-increase notice becomes effective), and an optional `sub_meter_reading_kwh` (a non-negative number with up to three decimal places of precision, consumed by the sub-meter apportionment path). A new lot begins life with its `ownership_mode` set to `PARK_OWNED`, a null `home_id`, and a null `current_lease_id`; the lot creation step also bumps the parent park's `ownership_pool_count` by one. The only mutation a park manager can perform on an existing lot is updating `sub_meter_reading_kwh` (the supplied request body carries `sub_meter_reading_kwh` and an optional `version` to guard against stale updates per §2.8); every other lot field is immutable except through the explicit conversion or home-sale cascades that govern it.

A `Home` is registered onto a lot by a `ParkManager` via a payload carrying `vin` (exactly 17 characters, uppercase letters A–Z and digits 0–9, globally unique — duplicates are rejected with `ERR_DUPLICATE_VIN`), the `lot_id` it will occupy, an `assessed_value_cents` greater than zero (consumed later by the conversion buyout eligibility check), and an `owner_resident_id` that is required only when the parent lot is in `RESIDENT_OWNED` mode and ignored otherwise. A home registered on a `PARK_OWNED` lot has its `owner_resident_id` set to null — the park itself is the implied owner — while a home registered on a `RESIDENT_OWNED` lot binds its `owner_resident_id` to the supplied value. The home also carries its parent `park_id`, and its `lot_id` is non-null except during a sale handover window where the system transiently nulls it as part of the close cascade.

A `Resident` is registered via `full_name` (between 1 and 120 characters) and `email` (RFC 5322 conformant and globally unique). The resident response surface always carries the computed `violation_count_12mo` — the system recomputes this counter on every read, on every lease-sign precondition check, and at the start of a home-sale approval. The counter equals the number of `EvictionCase` rows against any lease whose `resident_id` is this resident's `id` that are in `FINALIZED_FOR_CAUSE` status and whose `updated_at` is within the last 365 days from the current logical clock. The window boundary is inclusive: a case whose `updated_at` is exactly 365 days ago is counted, while a case whose `updated_at` is 366 days ago is excluded. The counter is therefore a rolling, time-sensitive measure of recent violations, used both as a precondition on lease sign and as a disqualifier on home-sale buyer approval.

### 3.2. Leasing the Lot — From Draft to Current

A `ParkManager` opens a new lease for a lot by submitting `resident_id` and `start_date` (a UTC midnight-aligned datetime indicating commencement). The resulting `Lease` carries its `lot_id`, the supplied `resident_id`, the supplied `start_date`, a `monthly_rent_cents` that remains uninitialised until signing, a `status` of `DRAFT`, an `outstanding_balance_cents` of zero, and a null `predecessor_lease_id` (the predecessor pointer is populated only on a successor lease minted by a home-sale close).

The activation step — signing the draft, transitioning `DRAFT → CURRENT` — is performed by a `ParkManager` and is gated by two preconditions. First, the parent lot's `current_lease_id` must be null (otherwise the sign is rejected with `ERR_LOT_OCCUPIED`); a lot can carry exactly one non-terminal lease at a time. Second, the resident named by `resident_id` must have a `violation_count_12mo` of zero — a resident with a finalized-for-cause eviction within the prior 365 days is barred from signing a fresh lease. On a successful sign, the system writes the lease's `id` into the lot's `current_lease_id`, copies the lot's `base_rent_cents` into the lease's `monthly_rent_cents`, and transitions the lease to `CURRENT`. The two side-effected resources (the lot and the lease) both refresh their `updated_at` and increment their `version` per §2.7.

A `CURRENT` lease remains so until the monthly billing run reveals an outstanding balance, an eviction filing forces it into `GRACE`, or the assumption of the lease through a home sale terminates it.

### 3.3. The Monthly Billing Sweep — Rent and Utilities Together

The monthly billing run is the system's heartbeat. A `PlatformAdmin` invokes the billing sweep with a `park_id` selecting the park, a `billing_period_start` and `billing_period_end` defining the half-open billing interval (start inclusive, end exclusive), and the period's `master_total_cents` (a non-negative integer giving the master meter charge to be apportioned across occupied lots). The sweep emits one `UtilityBill` per occupied lot, where an occupied lot is a lot whose `current_lease_id` is non-null and whose lease is in `CURRENT`, `DELINQUENT`, or `GRACE` status — leases in `DRAFT`, `TERMINATED`, or `ASSUMED` are excluded from the apportionment.

Each `UtilityBill` carries the originating `lot_id`, the `lease_id` in effect at the billing period's end (or null if the lot is vacant), the `billing_period_start`, the `billing_period_end`, the `master_total_cents` supplied by the sweep, the apportioned `lot_share_cents`, the period's `rent_due_cents`, the summed `total_due_cents`, and a `paid_at` timestamp that begins null and is stamped only when the resident pays the lease in full.

The utility apportionment rule is governed by the park's `utility_apportionment_method`. Under `SUB_METER`, the system sums the latest `sub_meter_reading_kwh` value (as observed one microsecond before `billing_period_end`) across the occupied lots; if the sum is strictly greater than zero, each lot's raw share is the lot's reading divided by the total reading, multiplied by `master_total_cents`. Each raw share is truncated downward to a whole cent, the residual cents remaining after the floors are summed are redistributed one-per-lot in ascending `lot_number` order until the sum of the lot shares exactly equals `master_total_cents`. If the total reading is exactly zero (every occupied lot reports a zero reading), the system falls back to equal-split: each lot receives the integer-divided share, and the residual is again distributed one cent per lot in ascending `lot_number` order. Under `EQUAL_SPLIT`, the integer division of `master_total_cents` by the number of occupied lots yields each lot's base share, and the residual is distributed one cent per lot in ascending `lot_number` order. When the park has no occupied lots, no bills are emitted and the master total is simply not apportioned.

The rent component on each bill is computed per lot from the lease that occupies it. If the lot has no `current_lease_id` at the billing period's end, `rent_due_cents` is zero. Otherwise, the system compares the lease's `start_date` to the `billing_period_start`. When `start_date` is on or before `billing_period_start`, the lease was active for the entire period and `rent_due_cents` equals the lease's `monthly_rent_cents`. When `start_date` falls strictly after `billing_period_start` (which happens for newly activated leases or for successor leases minted mid-period by a home-sale close), the rent is prorated: the system computes the count of whole calendar days in the period (the difference, in days, between `billing_period_end` and `billing_period_start`), the count of active days remaining in the period (the difference, in days, between `billing_period_end` and the later of `start_date` and `billing_period_start`), and sets `rent_due_cents` to the floor of the product of `monthly_rent_cents` and active days divided by the period day count. A successor lease whose `start_date` exactly equals `billing_period_start` is treated as full-period — the boundary is inclusive on the start side. Each bill's `total_due_cents` is then the sum of its `rent_due_cents` and its `lot_share_cents`.

When every bill for the period has been written, the system recomputes each affected lease's `outstanding_balance_cents` as the sum of `total_due_cents` across all `UtilityBill` rows whose `lease_id` matches the lease, whose `paid_at` is null, and whose `billing_period_end` has elapsed at the moment of recomputation. The sum is exact, in integer cents. Any lease that was `CURRENT` and whose recomputed balance is strictly greater than zero transitions to `DELINQUENT`; a lease that was already `DELINQUENT` remains so. The state transition is automatic and carries no further side effects beyond the `updated_at` and `version` refresh — there is no automatic eviction at this stage. A `ParkManager` may subsequently file an eviction case if the delinquency warrants it.

### 3.4. Payment and the Return to Current

A `Resident` clears their delinquency by invoking the pay action on their lease. The endpoint takes no body parameters: the system marks every previously unpaid `UtilityBill` for the lease with the current logical-clock timestamp in `paid_at`, recomputes the lease's `outstanding_balance_cents` (which drops to zero given that all bills are now paid), and cascades the lease's state. A lease that was `DELINQUENT` transitions to `CURRENT`. A lease that was `GRACE` (because an eviction case is in flight) transitions to `CURRENT` if its `outstanding_balance_cents` is zero, or remains at the appropriate state if the eviction itself has not yet resolved — the resident's payment alone does not dismiss an in-flight eviction.

The recomputation that drives the `DELINQUENT → CURRENT` transition consults exactly the set of `UtilityBill` rows whose `lease_id` matches and whose `paid_at` is null and whose `billing_period_end` has elapsed at evaluation time; after a successful pay, that set is empty and the sum is zero.

### 3.5. Rent-Increase Notices — Drafting, Issuance, and Effectiveness

A rent-increase notice is the formal instrument by which a `ParkManager` raises the rent on a specific lease. The manager drafts a notice by submitting `proposed_new_rent_cents` (an integer strictly greater than the lease's current `monthly_rent_cents`) and `effective_on` (the datetime at which the new rent becomes binding). The resulting `RentIncreaseNotice` carries its `lease_id`, the proposed value, the supplied `effective_on`, a `capped_new_rent_cents` that remains uninitialised until issuance, and a `status` of `DRAFT`.

Issuing the notice — the `DRAFT → ISSUED` transition, performed by a `ParkManager` — is the moment at which the system runs the state-specific cap and locks the notice's terms. Issuance enforces three preconditions, evaluated against the validation cascade in §2.10: the lease's `status` must be either `CURRENT` or `DELINQUENT`. If the lease is in `GRACE` (because an eviction is pending against it), the issue is rejected with `ERR_RENT_INCREASE_BLOCKED_DURING_EVICTION` — the system refuses to escalate the financial terms of a tenancy that is already under eviction. The `effective_on` must be at least 90 calendar days after the moment of issuance (a notice whose `effective_on` is less than 90 days out is rejected with `ERR_NOTICE_WINDOW_TOO_SHORT`). And the proposed value must be strictly greater than the current `monthly_rent_cents` — an equal-or-lower proposed value is rejected with `ERR_RENT_INCREASE_NONPOSITIVE`.

On a successful issue, the system computes `capped_new_rent_cents` from the lease's current `monthly_rent_cents`, the proposed new rent, the park's `state_code`, and the park's `master_cpi_pct`. The proposed percent increase is the proposed new rent minus the current rent, divided by the current rent, multiplied by one hundred. The maximum permitted percent is selected by the park's `state_code` per §2.9: for `CA`, the smaller of five plus `master_cpi_pct` and ten; for `OR`, the smaller of seven plus `master_cpi_pct` and ten; for `AZ`, exactly ten regardless of `master_cpi_pct`; for `FL` and `TX`, there is no maximum. If the maximum is undefined (the `FL` and `TX` case) or the proposed percent is less than or equal to the maximum, the `capped_new_rent_cents` is set equal to the proposed value. Otherwise — the cap activates — the system multiplies the current `monthly_rent_cents` by one plus the maximum percent divided by one hundred, and rounds the resulting cent value half up to the nearest integer cent. The order of operations matters: the percent comparison is performed first, and only if capping is required is the percent applied to the current rent and the result rounded to cents; the percent itself is never rounded prior to multiplication. The three computational variants that emerge directly from this rule are: a CA or OR park where the base plus CPI lands below the ten percent ceiling (the cap equals base plus CPI, for example a CA park with a `master_cpi_pct` of 2.0 caps at seven percent and a proposed eight-percent jump is rounded down to a seven-percent jump); a CA or OR park where the base plus CPI meets or exceeds the ceiling (the cap clamps to ten percent flat); and an FL or TX park where there is no cap and the proposed value passes through untouched. Once issued, the notice's `proposed_new_rent_cents`, `effective_on`, and `capped_new_rent_cents` become immutable.

The transition from `ISSUED` to `EFFECTIVE` is materialized by the rent-effective sweep, run by a `PlatformAdmin`. The sweep walks every `ISSUED` notice whose `effective_on` has been reached by the logical clock; for each, provided the lease is still in `CURRENT` or `DELINQUENT`, the sweep writes the notice's `capped_new_rent_cents` into both the lease's `monthly_rent_cents` and the parent lot's `base_rent_cents`. Subsequent billing periods will therefore charge the new rent, and any future lease activation on the same lot (after a termination, for example) will start from the new base.

A notice that has not yet become effective is voided automatically if the lease it targets terminates or is assumed. Specifically: when the lease transitions to `TERMINATED` (as the tail of a finalized eviction) or to `ASSUMED` (as part of a home-sale close), any `DRAFT` or `ISSUED` `RentIncreaseNotice` on that lease transitions to `VOIDED`. The void is a side effect of the lease transition itself; it carries no further cascading effects beyond the `updated_at` and `version` refresh on each affected notice.

### 3.6. Eviction Cases — Filing, Cure, Dismissal, and Finalization

A `ParkManager` files an eviction case against a lease by submitting `violation_type`, one of `NONPAYMENT`, `RULE_VIOLATION`, or `ILLEGAL_USE`. The system records the `lease_id`, stamps `filed_at` with the current logical clock, computes the `cure_deadline` from `filed_at` plus the violation-type-specific cure window, and sets `status` to `FILED`. The cure window is exactly 30 days for `NONPAYMENT`, exactly 14 days for `RULE_VIOLATION`, and zero days for `ILLEGAL_USE`. In the `ILLEGAL_USE` case the cure deadline is null — no cure window exists at all.

Immediately on creation, the case auto-advances. When the violation type is `NONPAYMENT` or `RULE_VIOLATION` (the cure deadline is non-null), the case transitions `FILED → IN_CURE` and the affected lease transitions to `GRACE`: a `CURRENT` lease becomes `GRACE`, a `DELINQUENT` lease becomes `GRACE`. The `GRACE` state suspends the lease's exposure to a fresh rent-increase notice — issuance is blocked while the lease is in `GRACE`, as described in §3.5. When the violation type is `ILLEGAL_USE` (the cure deadline is null), the case transitions directly `FILED → FINALIZED_FOR_CAUSE`, which immediately drives the lease through the `GRACE → TERMINATED` cascade described below.

A resident may cure an in-cure case by invoking the cure action, which transitions the case `IN_CURE → CURED`. The cure is gated by the cure window — the current logical clock must be strictly before `cure_deadline`, otherwise the request is rejected with `ERR_CURE_WINDOW_EXPIRED`. A cure attempt on a case whose violation type is `ILLEGAL_USE` is impossible by construction (the case never enters `IN_CURE`); the system rejects such an attempt with `ERR_NO_CURE_PERMITTED`. For a `NONPAYMENT` case specifically, the cure additionally requires that the lease's `outstanding_balance_cents` equal zero at the moment of cure — a resident must have paid the bills in question before invoking the cure, otherwise the request is rejected with `ERR_BALANCE_NOT_ZERO`. On a successful cure, the case becomes `CURED` and the lease cascades out of `GRACE`: if `outstanding_balance_cents` is zero the lease returns to `CURRENT`, otherwise it falls back to `DELINQUENT`. The cure carries no further side effects beyond the lease cascade and the `updated_at`/`version` refresh on the two affected resources.

A `ParkManager` may dismiss the case at any non-terminal point. A dismissal from `FILED` (which only happens for `ILLEGAL_USE` cases caught between filing and the automatic finalization, an edge case) transitions to `DISMISSED` with no further side effects. A dismissal from `IN_CURE` transitions to `DISMISSED` and cascades the lease out of `GRACE` (back to `CURRENT` if `outstanding_balance_cents` is zero, otherwise to `DELINQUENT`). A dismissal from `CURED` (cleaning up after the resident has already cured) transitions to `DISMISSED` with no further lease cascade — the cure already returned the lease to its post-grace state.

The eviction sweep, run by a `PlatformAdmin`, finalizes any `IN_CURE` case whose `cure_deadline` has been reached without a cure (the logical clock is at or past `cure_deadline`). For each such case, the sweep transitions `IN_CURE → FINALIZED_FOR_CAUSE` and cascades the lease through `GRACE → TERMINATED`. The `GRACE → TERMINATED` cascade has four side effects: the lot's `current_lease_id` is nulled, every `DRAFT` or `ISSUED` `RentIncreaseNotice` on the affected lease transitions to `VOIDED`, the affected resident's `violation_count_12mo` is incremented by one, and the lease itself records its terminal state. The sweep also recomputes the affected resident's `violation_count_12mo` so that subsequent reads return the updated counter. The dismissal-versus-finalize race is serialized on the case's `status` per §2.8.

### 3.7. Home Sales — From Pending Approval to Assumption

A home sale moves a `RESIDENT_OWNED` home from its current owner to a new resident, who in turn assumes the lot's lease. Either a `ParkManager` or a `Resident` opens a transfer by submitting `home_id`, `seller_resident_id` (which must equal the home's current `owner_resident_id`), `buyer_resident_id`, and `sale_price_cents` (an integer greater than zero). The resulting `HomeSaleTransfer` carries its `status` of `PENDING_PARK_APPROVAL` and a null `new_lease_id` — the successor lease pointer is populated only when the close cascade runs.

Approval — the `PENDING_PARK_APPROVAL → APPROVED` transition — is exclusive to a `ParkManager` and gates the transfer against three checks. The lot under the home must be in `RESIDENT_OWNED` mode (a park-owned home cannot be sold through this workflow; an attempt is rejected with `ERR_HOME_NOT_RESIDENT_OWNED`). The home's current `owner_resident_id` must equal the supplied `seller_resident_id`. And the buyer's eviction history must be clean: the buyer must have zero `EvictionCase` rows in any of the `FILED`, `IN_CURE`, or `FINALIZED_FOR_CAUSE` statuses where the case is within the last 365 days. The buyer's `violation_count_12mo` is recomputed at the moment of the approval check, and a non-zero count rejects the approval with `ERR_BUYER_INELIGIBLE`. The recomputation uses the same rolling-window rule described in §3.1 (boundary inclusive at exactly 365 days, exclusive past that). A `ParkManager` may instead reject the transfer outright, transitioning it `PENDING_PARK_APPROVAL → REJECTED` (a terminal state) with no side effects beyond the `updated_at`/`version` refresh.

Closing an approved transfer — the `APPROVED → CLOSED` transition, also exclusive to a `ParkManager` — drives the lease assumption cascade. The close is gated by a single state precondition: the predecessor lease (on the lot under the home being sold) must be in `CURRENT` or `DELINQUENT`; a lease in `GRACE`, `TERMINATED`, or `ASSUMED` blocks the close with `ERR_INVALID_STATE`. On a successful close, the predecessor lease transitions `CURRENT → ASSUMED`, which carries four side effects: the system mints a successor `Lease` in `CURRENT` whose `predecessor_lease_id` points to the predecessor lease's `id`, whose `resident_id` is the buyer, and whose `monthly_rent_cents` is copied from the predecessor lease's `monthly_rent_cents` (the new tenant inherits the seller's rent, not the lot's base rent — these may differ if a rent-increase notice has previously become effective); the parent lot's `current_lease_id` is rewritten to the successor lease's `id`; the home's `owner_resident_id` is set to the buyer; and the transfer's `new_lease_id` is set to the successor lease's `id`. Any `DRAFT` or `ISSUED` rent-increase notice on the predecessor lease is voided as a side effect of the predecessor's transition to `ASSUMED`.

### 3.8. Conversions — From Park-Owned to Resident-Owned

A conversion request offers a `PARK_OWNED` lot to a specific resident for buyout. A `ParkManager` initiates the offer by submitting `prospective_buyer_resident_id` and `offer_price_cents`. The resulting `ConversionRequest` carries the originating `lot_id`, the buyer, the offered price, a `status` of `OFFERED`, and lives under the lot.

The resident accepts the offer — the `OFFERED → ACCEPTED` transition, performed by the prospective buyer themselves — provided the offer meets the home's assessed value. Eligibility is a single threshold comparison: the `offer_price_cents` must be greater than or equal to the home's `assessed_value_cents`. The boundary is inclusive — an offer that exactly matches the assessed value is acceptable. Additionally, the lot's `ownership_mode` must still be `PARK_OWNED` at the moment of acceptance; if a different conversion has already finalized first, the precondition fails. If the offer is below the assessed value, the system transitions the request `OFFERED → REJECTED` (a terminal state) with `ERR_BUYOUT_UNDERVALUED`. A resident may also explicitly reject an offer they do not wish to accept, transitioning `OFFERED → REJECTED` directly; this terminal rejection carries no side effects.

Finalizing an accepted conversion — the `ACCEPTED → CLOSED` transition — is performed by a `ParkManager`. Finalization is gated by one precondition: the lot's `ownership_mode` must still be `PARK_OWNED` at the moment of finalization, otherwise the request is rejected with `ERR_LOT_ALREADY_RESIDENT_OWNED`. On a successful finalize, the lot's `ownership_mode` flips to `RESIDENT_OWNED`, the home's `owner_resident_id` is set to the `prospective_buyer_resident_id`, and the park's `ownership_pool_count` is decremented by one. Additionally, if the lot has no `current_lease_id` at the moment of finalization (the lot was vacant of any standing lease), the system creates a fresh `Lease` in `CURRENT` whose `resident_id` is the buyer and whose `monthly_rent_cents` is copied from the lot's `base_rent_cents`. If a standing lease already exists on the lot, no new lease is created — the existing lease continues, now under the new ownership regime. The conversion is one-directional: a `RESIDENT_OWNED` lot cannot be reverted to `PARK_OWNED` through this API.

## 4. Endpoint Definitions

The endpoints below define the complete surface of the API. Endpoints that create a fresh resource (a park, a lot, a home, a resident, a draft lease, a draft rent-increase notice, an eviction case, a transfer, a conversion request) return `201 Created`; endpoints that modify an existing resource, including state transitions and the test-driving sweeps, return `200 OK`. Request and response bodies are not documented here — each endpoint's expected payload and side-effect chain is described inline with its workflow in §3, and every endpoint inherits the validation cascade described in §2.10.

| Method | Path                                                  | Description                                                                                                                              | Authorized Role(s)                       |
| ------ | ----------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------- |
| POST   | `/parks`                                              | Create a park.                                                                                                                            | ParkManager, PlatformAdmin               |
| GET    | `/parks/{park_id}`                                    | Fetch a park including its `ownership_pool_count`.                                                                                       | ParkManager, PlatformAdmin, Resident     |
| POST   | `/parks/{park_id}/lots`                               | Create a lot under the park; the lot starts in `PARK_OWNED` mode.                                                                         | ParkManager                              |
| GET    | `/parks/{park_id}/lots`                               | List lots in the park, paginated; supports an `ownership_mode` query filter.                                                              | ParkManager, PlatformAdmin               |
| PATCH  | `/lots/{lot_id}`                                      | Update the lot's `sub_meter_reading_kwh` under optimistic concurrency control.                                                            | ParkManager                              |
| POST   | `/parks/{park_id}/homes`                              | Register a home on a lot.                                                                                                                | ParkManager                              |
| GET    | `/homes/{home_id}`                                    | Fetch a home.                                                                                                                            | ParkManager, PlatformAdmin, Resident     |
| POST   | `/residents`                                          | Register a resident.                                                                                                                     | ParkManager, PlatformAdmin               |
| GET    | `/residents/{resident_id}`                            | Fetch a resident; the response recomputes `violation_count_12mo`.                                                                        | ParkManager, PlatformAdmin, Resident     |
| POST   | `/lots/{lot_id}/leases`                               | Draft a lease for a lot.                                                                                                                 | ParkManager                              |
| POST   | `/leases/{lease_id}/sign`                             | Activate a draft lease (transition `DRAFT → CURRENT`).                                                                                   | ParkManager                              |
| POST   | `/leases/{lease_id}/pay`                              | Resident pays every outstanding utility bill on the lease.                                                                              | Resident                                 |
| GET    | `/leases/{lease_id}`                                  | Fetch a lease including its `outstanding_balance_cents`.                                                                                | ParkManager, PlatformAdmin, Resident     |
| POST   | `/leases/{lease_id}/rent-increase-notices`            | Draft a rent-increase notice for a lease.                                                                                                | ParkManager                              |
| POST   | `/rent-increase-notices/{notice_id}/issue`            | Issue the notice (validates the 90-day window and computes the capped value).                                                            | ParkManager                              |
| GET    | `/rent-increase-notices/{notice_id}`                  | Fetch a rent-increase notice.                                                                                                            | ParkManager, PlatformAdmin, Resident     |
| POST   | `/leases/{lease_id}/eviction-cases`                   | File an eviction case against a lease.                                                                                                   | ParkManager                              |
| POST   | `/eviction-cases/{case_id}/cure`                      | Resident cures the violation (transition `IN_CURE → CURED`).                                                                             | Resident                                 |
| POST   | `/eviction-cases/{case_id}/dismiss`                   | Park manager dismisses the case.                                                                                                          | ParkManager                              |
| GET    | `/eviction-cases/{case_id}`                           | Fetch an eviction case.                                                                                                                  | ParkManager, PlatformAdmin, Resident     |
| GET    | `/lots/{lot_id}/utility-bills`                        | List utility bills for a lot, paginated.                                                                                                 | ParkManager, PlatformAdmin, Resident     |
| POST   | `/home-sale-transfers`                                | Open a home-sale transfer.                                                                                                                | ParkManager, Resident                    |
| POST   | `/home-sale-transfers/{transfer_id}/approve`          | Park approves a pending transfer (recomputes the buyer's `violation_count_12mo`).                                                        | ParkManager                              |
| POST   | `/home-sale-transfers/{transfer_id}/reject`           | Park rejects a pending transfer.                                                                                                          | ParkManager                              |
| POST   | `/home-sale-transfers/{transfer_id}/close`            | Close an approved transfer; mints the successor lease and assumes the predecessor.                                                       | ParkManager                              |
| GET    | `/home-sale-transfers/{transfer_id}`                  | Fetch a home-sale transfer.                                                                                                              | ParkManager, PlatformAdmin, Resident     |
| POST   | `/lots/{lot_id}/conversion-requests`                  | Park offers a `PARK_OWNED` lot for conversion to `RESIDENT_OWNED`.                                                                      | ParkManager                              |
| POST   | `/conversion-requests/{conv_id}/accept`               | Resident accepts (or auto-rejects if undervalued).                                                                                       | Resident                                 |
| POST   | `/conversion-requests/{conv_id}/reject`               | Resident rejects the offer.                                                                                                              | Resident                                 |
| POST   | `/conversion-requests/{conv_id}/finalize`             | Park manager finalizes an accepted conversion.                                                                                            | ParkManager                              |
| GET    | `/conversion-requests/{conv_id}`                      | Fetch a conversion request.                                                                                                              | ParkManager, PlatformAdmin, Resident     |
| POST   | `/_clock/advance`                                     | Advance the server's logical clock by a supplied number of `seconds`.                                                                    | PlatformAdmin                            |
| POST   | `/_sweep/billing`                                     | Run the monthly billing sweep for a park; emits one utility bill per occupied lot.                                                       | PlatformAdmin                            |
| POST   | `/_sweep/evictions`                                   | Run the eviction sweep; finalizes `IN_CURE` cases whose cure deadline has elapsed.                                                       | PlatformAdmin                            |
| POST   | `/_sweep/rent-effective`                              | Run the rent-effective sweep; promotes `ISSUED` notices whose `effective_on` has been reached.                                          | PlatformAdmin                            |

## 5. Error Code Catalogue

| Error ID                                       | HTTP Status Code |
| ---------------------------------------------- | ---------------- |
| `ERR_AUTH_REQUIRED`                            | 401 Unauthorized |
| `ERR_FORBIDDEN`                                | 403 Forbidden    |
| `ERR_FORBIDDEN_NOT_OWNER`                      | 403 Forbidden    |
| `ERR_RESOURCE_NOT_FOUND`                       | 404 Not Found    |
| `ERR_REFERENCED_RESOURCE_NOT_FOUND`            | 404 Not Found    |
| `ERR_INVALID_STATE`                            | 409 Conflict     |
| `ERR_VERSION_MISMATCH`                         | 409 Conflict     |
| `ERR_VALIDATION`                               | 422 Unprocessable Entity |
| `ERR_NO_CURE_PERMITTED`                        | 409 Conflict     |
| `ERR_BUYER_INELIGIBLE`                         | 422 Unprocessable Entity |
| `ERR_LOT_OCCUPIED`                             | 409 Conflict     |
| `ERR_LOT_ALREADY_RESIDENT_OWNED`               | 409 Conflict     |
| `ERR_HOME_NOT_RESIDENT_OWNED`                  | 409 Conflict     |
| `ERR_NOTICE_WINDOW_TOO_SHORT`                  | 422 Unprocessable Entity |
| `ERR_CURE_WINDOW_EXPIRED`                      | 409 Conflict     |
| `ERR_RENT_INCREASE_BLOCKED_DURING_EVICTION`    | 409 Conflict     |
| `ERR_RENT_INCREASE_NONPOSITIVE`                | 422 Unprocessable Entity |
| `ERR_BALANCE_NOT_ZERO`                         | 409 Conflict     |
| `ERR_BUYOUT_UNDERVALUED`                       | 422 Unprocessable Entity |
| `ERR_LOT_OCCUPIED_BY_PENDING_OP`               | 409 Conflict     |
| `ERR_DUPLICATE_VIN`                            | 409 Conflict     |
| `ERR_DUPLICATE_LOT_NUMBER`                     | 409 Conflict     |
