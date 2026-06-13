# Public Library Management API — Product Requirements Document

## 1. Introduction

This document specifies the Public Library Management API, the backend service that runs the circulation and resource operations of a multi-branch public library system. The system carries the full weight of day-to-day library work: it tracks the bibliographic catalog and the physical holdings shelved against it, issues and limits patron cards, drives the checkout / renewal / return cycle, maintains a fair holds queue, enforces due dates and an overdue-fine policy that may be fine-bearing or fine-free depending on branch policy, brokers inter-library loans for works the branch does not own, books study rooms and public computers, bills patrons for lost items, and lends a finite pool of e-book licenses.

The hard problems this API exists to solve are consistency problems. A single physical copy moves through availability, loan, hold-shelf, lost, and withdrawn states, and each move ripples outward: a returned book may promote the next patron waiting in line, a lost book bills a replacement charge that can push a patron over their fine threshold and block all further borrowing, and a waived fine can lift that block again. Money is tracked in whole cents and never in floating point. Two patrons competing for the last available computer station in a given hour must be serialized deterministically rather than left to chance. The requirements below describe each of these flows precisely, because the value of the system is in getting the cascades, the queue ordering, the fine arithmetic, and the concurrency control exactly right — not merely approximately right.

Throughout, the system is presented from the perspective of three operators — patrons acting on their own borrowing, circulation-desk librarians running the front desk, and branch managers who own branch policy and resources. Each has a distinct slice of authority, and the rules that follow are written so that an engineer can implement the contract without guessing.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. All resources live under a single flat `/library` namespace; collections are sibling resources linked by foreign keys, and no resource is nested inside another's URL path.

### 2.1. User and Role-Based Access Control

Every request must be authenticated with two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares their operational capacity. The system recognizes exactly three roles, spelled precisely as `Patron`, `Librarian`, and `BranchManager`. A request that omits either header, or that carries an `X-User-Role` value outside this set, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is well-formed but not permitted to perform the requested operation — or a `Patron` attempting to act on a resource they do not own — is rejected with `ERR_FORBIDDEN`.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `Patron`, `X-User-ID` is the `id` of the acting `Patron` entity; every ownership check compares the relevant foreign-key field of the target resource against `X-User-ID`. Concretely, a `Patron` may renew, cancel, return, or otherwise act on a `Loan`, `Hold`, `Reservation`, or `EbookLoan` only when that resource's `patron_id` equals `X-User-ID`; an attempt against another patron's resource yields `ERR_FORBIDDEN`. When `X-User-Role` is `Librarian`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may accept and log it but never compares it to any entity's `id`. When `X-User-Role` is `BranchManager`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity, recorded for audit but never matched against an entity `id`. Librarians and branch managers act on behalf of the desk and the branch respectively, so their actions on patron-owned resources are not subject to the ownership comparison that constrains patrons.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets how many items to skip; it defaults to 0 and may not be negative. A `limit` outside the range 1 through 100, or a negative `offset`, is rejected with `ERR_VALIDATION_PARAM`, as is any unknown enum value supplied to a list filter.

Unless otherwise stated, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order. Every paginated response carries the fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Derived-Field Reconciliation

Every resource in the system carries a server-minted `id` formatted as a UUID, with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. All entities in this system are mutable and additionally carry an `updated_at` timestamp (ISO 8601 UTC, three fractional digits, refreshed on every change) and an integer `version` that begins at its initial value of `1` on creation and increments by one on every mutation. The `version` field is the basis for optimistic concurrency control where it applies (see §2.9).

A substantial number of fields are *derived* — they are not supplied by clients but computed by counting or summing related rows, and they are reconciled to their true value whenever a relevant mutation occurs and again whenever the owning resource is read. On a `Patron`, the derived fields are `active_loan_count`, `active_hold_count`, `total_owed_cents`, `borrowing_status`, and `ready_pickup_count`; a GET of a patron recomputes all five before returning. On a `Title`, `available_copy_count`, `total_copy_count`, and `waiting_hold_count` are recomputed on every copy, loan, and hold mutation and again on read. On a `LicensePool`, `loaned_licenses` and `available_licenses` are recomputed on every e-book checkout, return, and expiry and again on read. On a `Hold`, `queue_position` and `pickup_deadline` are recomputed on read. Because these reconciliations mutate the owning resource, they refresh its `updated_at` and increment its `version` exactly as any other mutation does.

### 2.5. Whole-Cent Money and Rounding

All monetary quantities — overdue fines, replacement charges, ILL lending fees, balances, and thresholds — are stored and returned as integers denominated in whole cents. There is no floating-point money anywhere in the contract. Where a calculation produces a fractional cent, the rounding method is **round half up** applied to whole cents, and the precise point at which rounding occurs is specified per calculation in §3 (it matters: the lost-item charge rounds each component before summing, not after). Day counts used in fine accrual are computed by truncating partial days toward zero, so a loan returned part-way through a day counts only the whole UTC days that have fully elapsed.

### 2.6. Catalog, Holdings, and Availability Consistency

The catalog is organized as bibliographic `Title` records, each owning zero or more physical `Copy` holdings. A `Title` is `ACTIVE` while it circulates and `WITHDRAWN` once retired; a `Copy` moves among `AVAILABLE`, `ON_LOAN`, `ON_HOLD_SHELF`, `LOST`, and `WITHDRAWN`. Copy status is never set by a direct copy endpoint — it changes only as a side effect of loan, hold, and title transitions. The denormalized availability counters on a title must always agree with the copies beneath it: `available_copy_count` is the number of that title's copies in `AVAILABLE` status, `total_copy_count` is the number of that title's copies that are not `WITHDRAWN`, and `waiting_hold_count` is the number of that title's holds in `WAITING` status. Any operation that moves a copy into or out of `AVAILABLE`, or withdraws a copy, must reconcile these counters.

Withdrawing a `Title` is a cascading retirement. When a `BranchManager` withdraws an `ACTIVE` title, the title moves to `WITHDRAWN`; every `AVAILABLE` copy of that title moves to `WITHDRAWN` (copies that are `ON_LOAN` or `ON_HOLD_SHELF` are left in place until they are returned), and every `WAITING` or `READY` hold on the title is moved to `CANCELLED`. The title's `version` increments, and the copy and hold counters are reconciled to reflect the retirement. New copies and new holds may not be created against a `WITHDRAWN` title; such attempts are rejected with `ERR_TITLE_WITHDRAWN`.

### 2.7. Cascading Side Effects Across Aggregates

Many operations in this system touch more than one entity in a single atomic step, and every secondary effect is part of the contract. The governing examples are the check-in cascade (a returned loan can promote a waiting hold, which reserves a copy and bumps a patron's pickup counter), the lost-item cascade (a declared-lost loan creates a fine, recomputes the patron's balance, and may flip the patron into a blocked state), and the fine-settlement cascade (paying or waiving a fine recomputes the balance and may lift a block). The precise mechanics of each cascade are given in §3 alongside the workflow that triggers it. The unifying rule is that whenever an operation changes a count or a balance that another resource derives from, that other resource is reconciled in the same step, with its `updated_at` and `version` advanced accordingly.

### 2.8. Patron Standing: Card Status and Fine-Driven Blocking

A patron's ability to borrow rests on two independent gates. The first is `card_status`, one of `ACTIVE`, `SUSPENDED`, or `EXPIRED`, set administratively; only an `ACTIVE` card may check out a physical item, place a hold, book a room or computer, check out an e-book, or submit an ILL request, and a `SUSPENDED` or `EXPIRED` card is rejected with `ERR_CARD_NOT_ACTIVE`. The second is `borrowing_status`, a derived field that is either `CLEAR` or `BLOCKED`. A patron is `BLOCKED` when their `total_owed_cents` — the sum of `amount_cents` over all of their fines whose `settlement_status` is `UNPAID` — reaches or exceeds the home branch's `block_threshold_cents`; otherwise they are `CLEAR`. A `BLOCKED` patron may not check out, place a hold, check out an e-book, or reserve a room or computer, and such attempts are rejected with `ERR_PATRON_BLOCKED`. The branch that governs a patron's threshold is resolved through the patron's `branch_id`.

### 2.9. Optimistic Concurrency Control on Resource Booking

Reservation creation is the one write in the system that is guarded by optimistic concurrency control, because a computer pool with several stations can legitimately accept several overlapping bookings, and only by pinning the resource's `version` can two strictly sequential booking attempts for the last station be resolved deterministically. A request to create a reservation must therefore carry `expected_resource_version` as a non-optional field, holding the client's last observed `version` of the target `BookableResource`. If `expected_resource_version` does not match the resource's current `version` — because another writer advanced the resource's `version` since the client last read it — the create is rejected with `ERR_STALE_RESOURCE_VERSION` (HTTP 412), preventing the client from booking against a resource view that has gone stale. A successful reservation create advances the `BookableResource.version` by one, so the next sequential writer observes the change. No other endpoint takes a version field, and no other write performs an OCC check.

### 2.10. Validation Ordering

When several checks could fail a single request, they are evaluated in a fixed priority order so that the error returned is deterministic. Authentication is checked first: a missing or unknown role or missing user id yields `ERR_UNAUTHENTICATED` (priority 1). Authorization is next: a role not permitted for the operation, or a patron acting on a resource it does not own, yields `ERR_FORBIDDEN` (priority 2). Then existence of every path- and body-referenced resource is checked left-to-right, with any unresolved id yielding `ERR_NOT_FOUND` (priority 3). Then request well-formedness — required body fields present and correctly typed, enum values within their declared domain, and `end_at` strictly after `start_at` — yields `ERR_INVALID_REQUEST` on failure (priority 4). Then the target's state is checked against the requested transition, yielding `ERR_INVALID_STATE` (priority 5). After these come the business gates, in this order: cross-entity reference availability yields `ERR_RESOURCE_NOT_AVAILABLE` (priority 6); patron card status yields `ERR_CARD_NOT_ACTIVE` (priority 7); patron fine-block yields `ERR_PATRON_BLOCKED` (priority 8); reservation interval conflict yields `ERR_RESERVATION_CONFLICT` (priority 9); patron limit checks yield `ERR_LIMIT_EXCEEDED` (priority 10); license availability yields `ERR_NO_LICENSE_AVAILABLE` (priority 11); and finally the reservation OCC check yields `ERR_STALE_RESOURCE_VERSION` (priority 12). Where a more specific error code exists for a sub-case (for example `ERR_TITLE_WITHDRAWN`, `ERR_RENEWAL_LIMIT`, or `ERR_RENEWAL_BLOCKED_BY_HOLD`), the workflow narrative in §3 names it; the ordering above governs the cross-cutting gates that apply broadly.

### 2.11. Nested Reference Validation and the Test Clock

Although the URL space is flat, several operations reference other resources by foreign key in their request bodies. References are validated left-to-right in the order they appear, and the first reference that does not resolve produces `ERR_NOT_FOUND` before any later reference or business rule is considered.

Because overdue accrual, hold pickup windows, e-book expiry, and reservation windows all depend on the passage of time, the system exposes an administrative test-driving capability that pins the server's logical UTC clock to an absolute instant supplied as `to_iso8601`; all subsequent reads of "now" use that instant. The set operation returns `200 OK` with a `data` object carrying a single `now` field holding the newly pinned instant as an ISO 8601 UTC timestamp. This capability is available to circulation and management operators and underlies the deterministic evaluation of every time-based rule below.

## 3. Business Logic & Workflows

### 3.1. Branches, Patron Cards, and Account Standing

A branch is the unit of policy, created by a `BranchManager` with a display `name` and a set of policy knobs that default if omitted: `fine_free` (default false) declares whether the branch assesses any overdue money at all; `daily_fine_cents` (default 25) is the per-day overdue charge per loan; `max_fine_cents` (default 1000) caps the accrued overdue fine on any one loan; `grace_days` (default 1) is the number of whole days past the due date that accrue no fine; `loan_period_days` (default 21) is the default loan length used to compute and to extend due dates; `block_threshold_cents` (default 1000) is the unpaid-balance level at which a patron is blocked from new borrowing; and `reservation_buffer_minutes` (default 15) is the cleanup gap required between two room bookings on the same resource. A fine-free branch still records overdue loans as `OVERDUE` and still blocks on other fine types, but it assesses zero money for lateness.

Patron cards are registered by a `Librarian` or `BranchManager` against a home `branch_id` with a `full_name` and an optional `patron_type` of `ADULT` (the default), `JUVENILE`, or `STAFF`. A new patron starts with `card_status` of `ACTIVE`, `borrowing_status` of `CLEAR`, and every counter at zero. The borrowing ceilings `checkout_limit` (default 20) and `hold_limit` (default 10) may be supplied at registration. A patron's `card_status` may later be moved to any of `ACTIVE`, `SUSPENDED`, or `EXPIRED` by a librarian or manager, by supplying the target value in a required `card_status` body field, which updates the card and increments the patron's `version`.

Reading a patron reconciles five derived figures before returning them: `active_loan_count` is the number of that patron's loans whose status is `ACTIVE` or `OVERDUE`; `active_hold_count` is the number of holds whose status is `WAITING` or `READY`; `ready_pickup_count` is the number of holds whose status is `READY`; `total_owed_cents` is the sum of `amount_cents` over the patron's `UNPAID` fines; and `borrowing_status` is `BLOCKED` when that owed total reaches or exceeds the branch's `block_threshold_cents`, otherwise `CLEAR`.

A patron may also request an **account summary**, a computed read that returns four integers: `raw_total_cents`, `waiver_cents`, `net_owed_cents`, and `unpaid_fine_count`. The summary follows a strictly pinned evaluation order to resolve what looks like a circular dependency. First, `raw_total_cents` is computed as the sum of `amount_cents` over the patron's fines whose `settlement_status` is `UNPAID`; fines that are `PAID` or `WAIVED` are excluded entirely, so settling a fine can change the result and even the tier below. Second, a goodwill tier is determined from that pre-waiver raw total: if `raw_total_cents` is at least 2000 cents, `waiver_cents` is set to a goodwill waiver of 200 cents; otherwise `waiver_cents` is zero. Third, `net_owed_cents` is the raw total minus the waiver, floored at zero so it is never negative. The `unpaid_fine_count` is simply the number of `UNPAID` fines folded into the raw total. The tier is keyed on the raw total before the waiver is applied, never on the net.

### 3.2. The Physical Catalog and Its Holdings

Bibliographic titles are created by a librarian or manager against an owning `branch_id`, with an `isbn` (the ISBN-13 key), a `title_text`, and an optional `default_replacement_cents` (default 3000) that fixes the list price used later in lost-item billing before depreciation. A new title is `ACTIVE` with all copy and hold counters at zero. Reading a title reconciles `available_copy_count`, `total_copy_count`, and `waiting_hold_count` as defined in §2.6. Titles may be filtered on read by `branch_id` and by `isbn`.

Physical copies are added by a librarian or manager with a `title_id`, a shelving `branch_id`, a `barcode`, an `acquired_on` acquisition date (the basis for depreciation age), and an optional `condition_factor` (default 1.0, a multiplier between 0.0 and 1.0 applied to a copy's depreciated value in the lost-item calculation). A new copy is `AVAILABLE`, and adding it reconciles the parent title's `available_copy_count` and `total_copy_count`. A copy may not be added to a `WITHDRAWN` title; the attempt is rejected with `ERR_TITLE_WITHDRAWN`. Copies are read individually and can be listed filtered by `title_id` and/or `branch_id`.

When a manager retires a title, the cascade of §2.6 fires: the title goes `WITHDRAWN`, its `AVAILABLE` copies follow it to `WITHDRAWN` while loaned and hold-shelf copies remain until returned, and its `WAITING` and `READY` holds are `CANCELLED`. Throughout, a copy whose status is driven from `AVAILABLE` to `ON_LOAN`, from `ON_LOAN` back to `AVAILABLE`, from `AVAILABLE` to `ON_HOLD_SHELF`, from `ON_HOLD_SHELF` to `ON_LOAN`, from `ON_HOLD_SHELF` back to `AVAILABLE`, from `ON_LOAN` to `LOST`, or from `AVAILABLE` to `WITHDRAWN` is moved only as the downstream effect of a loan, hold, or title operation; each such move that changes the available pool reconciles the title's counters.

### 3.3. Checkout, Renewal, and the Overdue Clock

Checkout is a desk action: a `Librarian` checks out a copy to a patron by supplying `copy_id` and `patron_id`. The copy must be `AVAILABLE` (otherwise `ERR_RESOURCE_NOT_AVAILABLE`), the patron's card must be `ACTIVE` (otherwise `ERR_CARD_NOT_ACTIVE`), and the patron must be `CLEAR` rather than blocked (otherwise `ERR_PATRON_BLOCKED`). The patron's open physical-loan count — loans in `ACTIVE` or `OVERDUE` status — must be below their `checkout_limit`; a checkout that would exceed it is rejected with `ERR_LIMIT_EXCEEDED`. On success a `Loan` is created in `ACTIVE` status with `checked_out_at` set to the server clock and `renewal_count` zero; its `due_date` is `checked_out_at` advanced by the branch's `loan_period_days`. The copy moves `AVAILABLE → ON_LOAN`, the title's `available_copy_count` is reconciled, and the patron's `active_loan_count` is reconciled. The loan also carries `returned_at` (null until return) and `accrued_fine_cents` (zero until the loan terminates). Loans may be listed filtered by `copy_id`, `patron_id`, and `status`.

Renewal is a self-loop that keeps a loan `ACTIVE`. The acting patron must own the loan (its `patron_id` must equal `X-User-ID`), or a librarian may renew on the desk's behalf. A renewal is permitted only when the loan is still `ACTIVE` — never once it has gone `OVERDUE`. Three further conditions gate it: the loan's `renewal_count` must be below the maximum of two renewals, or the request is rejected with `ERR_RENEWAL_LIMIT`; and no `WAITING` or `READY` hold may exist on the title of the loan's copy, because outstanding hold demand takes precedence over an incumbent borrower — if such a hold exists the renewal is refused with `ERR_RENEWAL_BLOCKED_BY_HOLD`. (Both of these conditions also surface under the general limit code `ERR_LIMIT_EXCEEDED` as priority-10 checks; the specific renewal codes name the exact cause.) A successful renewal increments `renewal_count` by one, advances `due_date` by another `loan_period_days`, and increments the loan's `version`.

The overdue transition is driven explicitly against the test clock. After the clock has advanced past a loan's `due_date`, a `Librarian` may refresh the loan's overdue flag; if the loan is `ACTIVE` and the current clock is strictly later than its `due_date`, it moves `ACTIVE → OVERDUE` and its `version` increments. Invoking the refresh before the clock has actually passed the `due_date` is rejected with `ERR_NOT_YET_DUE`.

A patron, librarian, or manager may request a forward-looking **fine estimate** for a loan, supplying an optional `projected_return` date. The estimate answers "what would the overdue fine be if the book came back on this date" and returns `estimate_cents`, `overdue_days`, and `chargeable_days`. It uses the client-supplied `projected_return` in place of an actual return instant — or, when `projected_return` is omitted, the current server clock — but is otherwise identical to the final fine arithmetic: `overdue_days` is the whole UTC days by which `projected_return` exceeds the `due_date`, never below zero; `chargeable_days` is `overdue_days` minus the branch's `grace_days`, never below zero; and `estimate_cents` is `chargeable_days` multiplied by the branch's `daily_fine_cents`, capped at `max_fine_cents`, and forced to zero entirely when the branch is fine-free. Because it projects rather than measures, the estimate and the eventual final fine diverge for the same loan whenever the projected date differs from the actual return.

### 3.4. Return, Final Fine Assessment, and Hold Promotion

Returning a loaned copy — a librarian action — is the system's busiest cascade. A loan in `ACTIVE` or `OVERDUE` status may be checked in. On check-in the loan moves to `RETURNED`, `returned_at` is set to the clock, and the final overdue fine is computed and written to `accrued_fine_cents`. That final fine is computed chronologically and capped per loan: if the branch is fine-free it is zero; otherwise `overdue_days` is the whole UTC days by which `returned_at` exceeds the `due_date` (never below zero), `chargeable_days` is `overdue_days` minus the branch's `grace_days` (never below zero, so any day index up to and including `grace_days` is free and only day indices beyond it are charged), the raw fine is `chargeable_days` multiplied by `daily_fine_cents`, and the assessed fine is the smaller of that raw amount and `max_fine_cents`.

If that assessed amount is greater than zero, the system creates a `Fine` with `fine_type` `OVERDUE`, `amount_cents` equal to the assessed fine, `settlement_status` `UNPAID`, and `loan_id` pointing at the returning loan; the patron's `total_owed_cents` is then recomputed and, in turn, their `borrowing_status` is recomputed — this is the Loan → Fine → `total_owed_cents` → `borrowing_status` cascade. In the same step the copy moves `ON_LOAN → AVAILABLE` and the title's `available_copy_count` is reconciled.

Then hold promotion runs. If any `WAITING` hold exists on the returned copy's title, the head hold — the one with the lowest `queue_position`, which is to say the earliest by `created_at` — is promoted `WAITING → READY`: the just-freed copy is reserved on the hold shelf (its status goes `AVAILABLE → ON_HOLD_SHELF`), the hold's `ready_copy_id` is set to that copy, `ready_at` is set to the clock, the hold's `pickup_deadline` is set, and the promoted patron's `ready_pickup_count` is reconciled. The loan's `version` increments. When promotion consumes the freed copy, the copy does not return to the available pool; when there is no waiting hold, the copy simply stays `AVAILABLE`.

### 3.5. Lost Items and Replacement Billing

A librarian may declare a loaned copy lost from either `ACTIVE` or `OVERDUE`. Declaring lost triggers a deep cascade: the loan moves to `LOST`, the copy moves to `LOST`, a replacement `Fine` is created, the patron's balance is recomputed, and if that balance now reaches or exceeds the branch's `block_threshold_cents` the patron's `borrowing_status` flips to `BLOCKED`. The title's `available_copy_count` and `total_copy_count` are both reconciled to their §2.6 definitions, and the loan's `version` increments. Reconciliation follows those definitions exactly: a `LOST` copy leaves the available pool, so `available_copy_count` drops by one; but `LOST` is a copy status distinct from `WITHDRAWN`, so a lost copy is still non-withdrawn and therefore remains counted in `total_copy_count` — declaring a single loaned copy lost does not change that title's `total_copy_count`. The created fine has `fine_type` `LOST`, `loan_id` set to the lost loan, `amount_cents` equal to the replacement charge below, and `settlement_status` `UNPAID`.

The replacement charge is built from two independently rounded components that are summed only after each is rounded — the order is pinned, and summing before rounding is wrong. The first component is the depreciated item value. The copy's age in fractional years is the whole UTC days between its `acquired_on` date and the moment of declaring it lost, divided by 365. Depreciation is that age in years multiplied by the annual depreciation rate of ten percent, but never more than the cap of eighty percent. The depreciated item value in cents is the title's `default_replacement_cents` multiplied by one minus that depreciation fraction, multiplied by the copy's `condition_factor`, with that product rounded half up to whole cents. The second component is a flat processing fee: the title's `default_replacement_cents` multiplied by ten percent, rounded half up to whole cents on its own. The replacement charge is the sum of these two already-rounded components.

A branch policy override is available on the declare-lost call via the optional `flat_replacement` flag. When `flat_replacement` is true, the default variant is used: depreciation and `condition_factor` are ignored entirely, the item-value component is simply the title's `default_replacement_cents`, the processing fee is computed exactly as above and rounded on its own, and the two are then summed. The depreciated and the default variants diverge for any copy older than zero days or with a `condition_factor` below 1.0.

### 3.6. The Holds Queue and Its Promotion Loop

A hold expresses demand for a title. A patron places a hold, or a librarian places one on a patron's behalf, supplying `title_id` and `patron_id`; the card must be `ACTIVE` and the patron `CLEAR`, the title must not be `WITHDRAWN`, and the patron's open-hold count — holds in `WAITING` or `READY` status — must be below their `hold_limit`, or the placement is rejected with `ERR_LIMIT_EXCEEDED`. A new hold enters in `WAITING` status and is assigned a `queue_position`. The `queue_position` is a 1-based rank among the `WAITING` holds on the title, ordered by `created_at` ascending with the tie-break always on `created_at` and never on `id`; holds that are `READY` or in any terminal status carry `queue_position` zero. Placing a hold reconciles the patron's `active_hold_count` and the title's `waiting_hold_count`. Holds may be listed filtered by `title_id`, `patron_id`, `ready_copy_id`, and `status`.

When a copy of the title becomes free and this hold is the head of the `WAITING` queue, the hold is promoted `WAITING → READY`: a free copy is reserved (`AVAILABLE → ON_HOLD_SHELF`), `ready_copy_id` records it, `ready_at` is stamped, the `pickup_deadline` is set to `ready_at` advanced by the pickup window of three whole days, the patron's `ready_pickup_count` is reconciled, and the hold's `version` increments. A `READY` hold is fulfilled when a librarian checks out the reserved copy on behalf of the hold's patron; this is permitted only while the hold is `READY` and the current clock is at or before its `pickup_deadline` (otherwise `ERR_HOLD_NOT_READY`, or `ERR_PICKUP_EXPIRED` once the deadline has passed). Fulfilment moves the hold `READY → FULFILLED`, creates a `Loan` on the `ready_copy_id` for the hold's patron with the copy moving `ON_HOLD_SHELF → ON_LOAN`, recomputes the remaining `WAITING` holds' `queue_position`, reconciles the patron's `ready_pickup_count`, and increments the hold's `version`.

A `READY` hold that is not collected in time is expired by a librarian once the clock is strictly past its `pickup_deadline`; attempting to expire before that point is refused with `ERR_NOT_YET_DUE`, and attempting it on a hold that is not `READY` is `ERR_INVALID_STATE`. Expiry moves the hold `READY → EXPIRED` and releases the reserved copy `ON_HOLD_SHELF → AVAILABLE`; the promotion loop then re-fires — if another `WAITING` hold exists it is immediately promoted to `READY` and re-reserves that copy, otherwise the copy stays `AVAILABLE` and the title's `available_copy_count` is reconciled. The expiring patron's `ready_pickup_count` is reconciled and the hold's `version` increments. A patron may cancel their own `WAITING` or `READY` hold, or a librarian may cancel on their behalf; cancellation moves the hold to `CANCELLED`, and if it was `READY` the reserved copy is released and the same promotion loop runs to hand the copy to the next `WAITING` hold if any. Cancellation recomputes the remaining `WAITING` holds' `queue_position`, reconciles `ready_pickup_count`, and increments the hold's `version`.

### 3.7. Rooms, Computers, and Reservations

Bookable resources are created by a `BranchManager` against a `branch_id`, with a `resource_kind` of `ROOM` or `COMPUTER`, a human `label`, and an optional `capacity` (default 1). A `ROOM` is treated as exclusive and ignores `capacity`; a `COMPUTER` interprets `capacity` as the number of stations that may overlap in any window. A resource starts `IN_SERVICE` and may be moved `IN_SERVICE`/`OUT_OF_SERVICE` by a manager, by supplying the target value in a required `status` body field, which increments its `version`. An `OUT_OF_SERVICE` resource blocks new reservations and check-ins. Resources may be listed filtered by `branch_id` and `resource_kind`, and a single-resource read exposes the current `version` clients need for booking.

Booking a reservation is the OCC-guarded write of §2.9. A patron books for themselves, or a librarian books on their behalf, supplying `resource_id`, `patron_id`, `start_at`, `end_at`, and the mandatory `expected_resource_version`. The window is half-open: it covers `start_at` up to but not including `end_at`, and `end_at` must be strictly after `start_at` or the request is `ERR_INVALID_REQUEST`. The resource must be `IN_SERVICE` (else `ERR_RESOURCE_NOT_AVAILABLE`), the card `ACTIVE` (else `ERR_CARD_NOT_ACTIVE`), and the patron `CLEAR` (else `ERR_PATRON_BLOCKED`). The interval must not conflict with existing active reservations on the same resource (else `ERR_RESERVATION_CONFLICT`), where "active" means reservations in `REQUESTED`, `CONFIRMED`, or `CHECKED_IN` status. Finally `expected_resource_version` must match the resource's current `version` (else `ERR_STALE_RESOURCE_VERSION`). On success the reservation is created in `REQUESTED` status and the resource's `version` advances by one. Reservations may be listed filtered by `resource_id`, `patron_id`, and `status`.

The conflict test depends on the kind. For a `ROOM`, two bookings conflict if their windows, each expanded on the end side by the booking patron's home branch's `reservation_buffer_minutes` (resolved through the patron's `branch_id`), intersect — concretely, a new booking conflicts with an active room reservation when the new start is before that reservation's end plus the buffer and that reservation's start is before the new end plus the buffer. Adjacency within the buffer counts as a conflict, because rooms need cleanup time. For a `COMPUTER`, there is no buffer and capacity is aggregate: gather the active reservations whose half-open windows strictly overlap the new window (the new start before an existing end and that existing start before the new end), and reject only if, at the busiest instant across the combined set including the new booking, the number of simultaneously overlapping reservations would exceed the resource's `capacity`. A second overlapping computer booking is therefore fine as long as it stays within capacity.

A requested reservation is confirmed by a librarian, permitted only from `REQUESTED` and only while the resource is `IN_SERVICE`, moving it `REQUESTED → CONFIRMED` and incrementing its `version`. A confirmed reservation is checked in by a librarian, permitted only from `CONFIRMED`, only while the resource is `IN_SERVICE`, and only once the clock has reached `start_at` (a check-in attempted before `start_at` is rejected with `ERR_NOT_YET_DUE`); check-in stamps `checked_in_at`, moves the reservation `CONFIRMED → CHECKED_IN`, and increments its `version`. A checked-in reservation is completed by a librarian from `CHECKED_IN`, moving it to `COMPLETED`, which frees the window so a `COMPLETED` reservation no longer counts as occupying the resource. A confirmed reservation whose window has fully elapsed without a check-in is marked a no-show by a librarian — permitted only from `CONFIRMED` and only once the clock has reached `end_at`, otherwise `ERR_NOT_YET_DUE` — moving it `CONFIRMED → NO_SHOW`, which frees the window without ever recording a check-in. Finally, a patron may cancel their own `REQUESTED` or `CONFIRMED` reservation, or a librarian may cancel on their behalf, moving it to `CANCELLED` and freeing the window with no check-in recorded. Every reservation transition increments the reservation's `version`.

### 3.8. Inter-Library Loans

When a branch does not own a requested work, a patron may submit an inter-library loan request, or a librarian may submit on their behalf, providing the requesting `patron_id`, the handling `branch_id`, the `isbn` of the external work, and an optional `lending_fee_cents` (default 500) that will be billed to the patron when the item arrives. The request starts `REQUESTED`. ILL requests may be listed filtered by `patron_id`, `branch_id`, and `status`.

A librarian drives the ILL pipeline forward by submitting an `action` that names the transition. The `approve` action moves a request `REQUESTED → APPROVED`, but only if the requesting patron's `borrowing_status` is `CLEAR` (a `BLOCKED` patron is rejected with `ERR_PATRON_BLOCKED`). The `deny` action moves a request `REQUESTED → DENIED`. The `ship` action moves an `APPROVED` request to `SHIPPED`. The `receive` action moves a `SHIPPED` request to `RECEIVED` and, as a side effect, creates a `Fine` with `fine_type` `ILL_FEE`, `amount_cents` equal to the request's `lending_fee_cents`, and `loan_id` null (an ILL fee has no originating loan); the patron's `total_owed_cents` and then `borrowing_status` are recomputed. The `return` action moves a `RECEIVED` request to `RETURNED`. Each transition is rejected with `ERR_INVALID_STATE` when the request is not in the required source state, and every transition increments the request's `version`. An `action` value that is not one of these verbs is rejected with `ERR_INVALID_ACTION`.

### 3.9. E-Book Lending Against a License Pool

Each electronically lendable work is backed by a `LicensePool` created by a librarian or manager with a `title_id`, a `total_licenses` count (the maximum simultaneous e-book loans), and an optional `loan_term_days` (default 14) fixing the e-book loan length. The pool tracks two derived figures: `loaned_licenses`, the number of its e-book loans currently `ACTIVE`, and `available_licenses`, which is `total_licenses` minus `loaned_licenses` and is never allowed below zero. Both are reconciled on every checkout, return, and expiry and again on read. Pools may be listed filtered by `title_id`.

Checking out an e-book consumes a license. A patron checks out for themselves, or a librarian on their behalf, supplying `pool_id` and `patron_id`; the card must be `ACTIVE` and the patron `CLEAR`, and the pool must have at least one available license — `available_licenses` of at least one — or the checkout is rejected with `ERR_NO_LICENSE_AVAILABLE`. On success an `EbookLoan` is created in `ACTIVE` status with `checked_out_at` at the clock and `expires_at` set to `checked_out_at` advanced by the pool's `loan_term_days`; the pool's `loaned_licenses` and `available_licenses` are reconciled. E-book loans may be listed filtered by `pool_id`, `patron_id`, and `status`.

A patron returns their own e-book early, or a librarian on their behalf, moving the loan `ACTIVE → RETURNED` and releasing the license back to the pool (both pool counters reconciled, the conserved token returned), incrementing the loan's `version`. Expiry is handled in bulk: a librarian runs the pool's expiry sweep, and every `ACTIVE` e-book loan on that pool whose `expires_at` is at or before the current clock is moved `ACTIVE → EXPIRED`, releasing its license; the pool's `loaned_licenses` and `available_licenses` are reconciled afterward. Each expired loan's `version` increments.

### 3.10. Fines, Payment, and Waiver

Every chargeable event lands as a `Fine` row tied to a `patron_id`: overdue returns and lost declarations attach via their `loan_id`, while ILL fees carry a null `loan_id`. A fine records its `fine_type` (`OVERDUE`, `LOST`, or `ILL_FEE`), its `amount_cents`, a `settlement_status` of `UNPAID`, `PAID`, or `WAIVED`, and a `settled_at` timestamp that stays null until the fine is settled. Fines may be read individually and listed filtered by `patron_id`, `loan_id`, and `settlement_status`.

A librarian or manager settles an `UNPAID` fine as paid: `settlement_status` moves to `PAID`, `settled_at` is stamped with the clock, and the patron's `total_owed_cents` is recomputed; if that recomputed total falls below the branch's `block_threshold_cents`, the patron's `borrowing_status` is set back to `CLEAR`, lifting any block. A waiver is the manager-only counterpart: only a `BranchManager` may waive an `UNPAID` fine, moving its `settlement_status` to `WAIVED`, stamping `settled_at`, recomputing `total_owed_cents`, and likewise restoring `CLEAR` when the total drops below the threshold. Both settlement paths increment the fine's `version`, and both remove the fine's amount from the patron's owed total because only `UNPAID` fines count toward it.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`. Operations that modify an existing resource — including all state transitions, settlements, and administrative status changes — return `200 OK`. All reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/library/branches` | Create a branch with its fine/loan policy | BranchManager |
| GET | `/library/branches/{id}` | Get a branch | Patron, Librarian, BranchManager |
| GET | `/library/branches` | List branches | Patron, Librarian, BranchManager |
| POST | `/library/patrons` | Register a patron card | Librarian, BranchManager |
| GET | `/library/patrons/{id}` | Get a patron (counters reconciled on read) | Patron, Librarian, BranchManager |
| GET | `/library/patrons` | List/filter patrons by branch | Librarian, BranchManager |
| POST | `/library/patrons/{id}/set-card-status` | Suspend/reactivate/expire a patron card | Librarian, BranchManager |
| GET | `/library/patrons/{id}/account-summary` | Computed read: raw/waiver/net owed totals | Patron, Librarian, BranchManager |
| POST | `/library/titles` | Create a bibliographic title | Librarian, BranchManager |
| GET | `/library/titles/{id}` | Get a title (copy/hold counters reconciled) | Patron, Librarian, BranchManager |
| GET | `/library/titles` | List/filter titles by branch | Patron, Librarian, BranchManager |
| POST | `/library/titles/{id}/withdraw` | Withdraw a title from circulation | BranchManager |
| POST | `/library/copies` | Add a physical holding copy to a title | Librarian, BranchManager |
| GET | `/library/copies/{id}` | Get a copy | Patron, Librarian, BranchManager |
| GET | `/library/copies` | List/filter copies by title and/or branch | Patron, Librarian, BranchManager |
| POST | `/library/loans` | Check out a copy to a patron | Librarian |
| GET | `/library/loans/{id}` | Get a loan | Patron, Librarian, BranchManager |
| GET | `/library/loans` | List/filter loans by copy and/or patron | Patron, Librarian, BranchManager |
| GET | `/library/loans/{id}/fine-estimate` | Computed read: forward-looking overdue estimate | Patron, Librarian, BranchManager |
| POST | `/library/loans/{id}/renew` | Renew a loan (self-loop on ACTIVE) | Patron, Librarian |
| POST | `/library/loans/{id}/refresh-overdue` | Recompute overdue flag against current clock | Librarian |
| POST | `/library/loans/{id}/checkin` | Return a loaned copy; assess fine; promote head hold | Librarian |
| POST | `/library/loans/{id}/declare-lost` | Declare a loaned copy lost; bill replacement | Librarian |
| POST | `/library/holds` | Place a hold on a title | Patron, Librarian |
| GET | `/library/holds/{id}` | Get a hold (queue_position reconciled) | Patron, Librarian, BranchManager |
| GET | `/library/holds` | List/filter holds by title, patron, or reserved copy | Patron, Librarian, BranchManager |
| POST | `/library/holds/{id}/checkout` | Fulfil a READY hold by checking out the reserved copy | Librarian |
| POST | `/library/holds/{id}/expire-ready` | Expire an unclaimed READY hold; promote next | Librarian |
| POST | `/library/holds/{id}/cancel` | Cancel a WAITING or READY hold | Patron, Librarian |
| POST | `/library/resources` | Create a bookable room or computer station pool | BranchManager |
| GET | `/library/resources/{id}` | Get a bookable resource (read version for OCC) | Patron, Librarian, BranchManager |
| GET | `/library/resources` | List/filter resources by branch | Patron, Librarian, BranchManager |
| POST | `/library/resources/{id}/set-service-status` | Take a resource out of / back into service | BranchManager |
| POST | `/library/reservations` | Request a room/computer reservation | Patron, Librarian |
| GET | `/library/reservations/{id}` | Get a reservation | Patron, Librarian, BranchManager |
| GET | `/library/reservations` | List/filter reservations by resource and/or patron | Patron, Librarian, BranchManager |
| POST | `/library/reservations/{id}/confirm` | Confirm a requested reservation | Librarian |
| POST | `/library/reservations/{id}/checkin` | Check a patron into a confirmed reservation | Librarian |
| POST | `/library/reservations/{id}/complete` | Complete a checked-in reservation | Librarian |
| POST | `/library/reservations/{id}/no-show` | Mark a confirmed reservation a no-show | Librarian |
| POST | `/library/reservations/{id}/cancel` | Cancel a requested/confirmed reservation | Patron, Librarian |
| POST | `/library/ill-requests` | Submit an inter-library loan request | Patron, Librarian |
| GET | `/library/ill-requests/{id}` | Get an ILL request | Patron, Librarian, BranchManager |
| GET | `/library/ill-requests` | List/filter ILL requests by patron and/or branch | Patron, Librarian, BranchManager |
| POST | `/library/ill-requests/{id}/transition` | Advance ILL lifecycle (action in body) | Librarian |
| POST | `/library/license-pools` | Create an e-book license pool for a title | Librarian, BranchManager |
| GET | `/library/license-pools/{id}` | Get a license pool (availability reconciled) | Patron, Librarian, BranchManager |
| GET | `/library/license-pools` | List/filter license pools by title | Patron, Librarian, BranchManager |
| POST | `/library/license-pools/{id}/run-expiry` | Expire due ebook-loans; release licenses | Librarian |
| POST | `/library/ebook-loans` | Check out an e-book against a license pool | Patron, Librarian |
| GET | `/library/ebook-loans/{id}` | Get an e-book loan | Patron, Librarian, BranchManager |
| GET | `/library/ebook-loans` | List/filter e-book loans by pool and/or patron | Patron, Librarian, BranchManager |
| POST | `/library/ebook-loans/{id}/return` | Return an e-book early; release the license | Patron, Librarian |
| GET | `/library/fines/{id}` | Get a fine | Patron, Librarian, BranchManager |
| GET | `/library/fines` | List/filter fines by patron and/or loan | Patron, Librarian, BranchManager |
| POST | `/library/fines/{id}/pay` | Settle a fine as PAID; recompute balance | Librarian, BranchManager |
| POST | `/library/fines/{id}/waive` | Waive a fine; recompute balance | BranchManager |
| POST | `/library/_clock/set` | Set the server's current UTC clock to an instant | Librarian, BranchManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_RESOURCE_NOT_AVAILABLE` | 409 Conflict |
| `ERR_CARD_NOT_ACTIVE` | 409 Conflict |
| `ERR_PATRON_BLOCKED` | 409 Conflict |
| `ERR_RESERVATION_CONFLICT` | 409 Conflict |
| `ERR_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_NO_LICENSE_AVAILABLE` | 409 Conflict |
| `ERR_STALE_RESOURCE_VERSION` | 412 Precondition Failed |
| `ERR_TITLE_WITHDRAWN` | 409 Conflict |
| `ERR_HOLD_NOT_READY` | 409 Conflict |
| `ERR_PICKUP_EXPIRED` | 409 Conflict |
| `ERR_NOT_YET_DUE` | 409 Conflict |
| `ERR_RENEWAL_LIMIT` | 409 Conflict |
| `ERR_RENEWAL_BLOCKED_BY_HOLD` | 409 Conflict |
| `ERR_VALIDATION_PARAM` | 400 Bad Request |
| `ERR_INVALID_ACTION` | 400 Bad Request |
