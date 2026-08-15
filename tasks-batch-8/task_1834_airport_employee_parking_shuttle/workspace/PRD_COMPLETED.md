# Airport Employee Parking & Shuttle Operations API — Product Requirements Document

## 1. Introduction

Large airports run employee parking programs for tens of thousands of badge holders spread across airlines, ground handlers, concessionaires, and terminal tenants. The operational reality is unforgiving: core lots next to the terminal are chronically oversubscribed, remote lots must be activated on peak travel days and fed by shuttles that run on a published headway, and the entire program is funded through payroll deduction — which means every permit fee, violation fine, and impound charge must flow through a disciplined billing cycle that payroll can close, export, and occasionally reject. Enforcement is equally sensitive: the officer who writes a citation must never adjudicate its appeal, and a tow is only lawful after a defined hold period has elapsed.

This document specifies the API that administers such a program end to end. It covers badge-based eligibility and permit issuance, lot capacity management with shift-pattern-ranked waitlists, shuttle route and trip operations with a measured wait-time service level, payroll-deduction billing with termination sweeps, violation enforcement with escalation and towing, remote-lot activation through scheduled peak windows, service-change communication with mandatory advance notice, and program economics reporting — gross and net cost per parked employee, including subsidy spend. All resources are mounted under `/parking`, and every time-dependent rule in the system evaluates against a server-held logical clock rather than wall-clock time.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, structural contracts, and cross-cutting principles that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their operational capacity. A request with a missing header or an unrecognized role is rejected with `ERR_MISSING_OR_INVALID_AUTH_CONTEXT` (HTTP 400). The system recognizes exactly six roles: `ParkingAdmin` (airport parking program administrator — programs, lots, peak windows, notices, posture, the ops checkpoint, permit administration, renewal decisions, and employee registration and termination), `Employee` (a badge-holding airport employee acting on their own permits, renewals, and violation appeals), `PayrollAdmin` (payroll deduction operator — billing cycles, manual adjustments, settlement outcomes), `EnforcementOfficer` (parking enforcement — issues violations, authorizes and processes tows, and may never adjudicate appeals), `AppealsOfficer` (independent adjudicator for violation appeals, segregated from the issuing officer), and `ShuttleDispatcher` (shuttle operations — routes, trips, departures, completions). A request whose role is not authorized for the target endpoint — or, on event-style endpoints, for the particular event verb requested — is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Identity semantics differ by role. When `X-User-Role` is `Employee`, `X-User-ID` is the `id` of the acting Employee; ownership checks on any resource that references an Employee compare the resource's owning employee reference to `X-User-ID`, and a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). When `X-User-Role` is `ParkingAdmin`, `PayrollAdmin`, `EnforcementOfficer`, `AppealsOfficer`, or `ShuttleDispatcher`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity: the server records it where a workflow calls for attribution — for example as `decided_by` on a decided renewal, `issued_by` on a violation, or `authorized_by` on a tow event — but does not compare it to any entity's `id`. The one deliberate exception is appeal adjudication, where an `AppealsOfficer`'s `X-User-ID` is compared against the violation's recorded `issued_by` attribution to enforce segregation of duties; that is an operator-to-attribution comparison, not an entity ownership check.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items from the start of the result set and defaults to 0. A `limit` that is not an integer or falls outside 1–100, and an `offset` that is not an integer or is negative, are rejected with `ERR_INVALID_REQUEST`. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource in the system — programs, employees, lots, permits, renewals, routes, trips, notices, violations, tow events, billing cycles, charge entries, and peak windows — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that starts at 1 on creation and increments by one on every mutation, including mutations caused by a cascade rather than a direct client write.

Fields described in this document as computed or system-managed are never accepted from clients. A client that supplies values for such fields does not cause an error; the supplied values are silently ignored.

### 2.5. The Logical Clock

All time-dependent rules — offer expiry, peak-window activation, notice effectiveness, appeal windows, tow holds, billing spans — evaluate against a server-held logical clock. The logical clock never falls back to wall-clock time. At server startup, before any adjustment, the logical clock reads exactly 2026-08-01T00:00:00Z. A `ParkingAdmin`-only test-driving capability sets the clock to a supplied `to_iso8601` instant — forward or backward, with no monotonicity constraint — and its response reports the resulting `current_utc`. Here and in every datetime field of the API, an ISO 8601 value supplied without an explicit offset is interpreted as UTC.

### 2.6. Monetary Precision and Rounding Order

All monetary values are integer cents. Every charge entry amount is rounded half-up to integer cents at posting time, and a billing cycle's total is the plain integer sum of its non-reversed entries — never re-rounded after summation. This per-entry-then-sum ordering is pinned; sum-then-round is not acceptable. The one division that produces the subsidy per-capita cap uses floor division to integer cents. Shuttle service-level reporting is the single non-monetary consumer of fractional rounding: the expected wait is expressed in minutes rounded half-up to two decimal places, while gap figures are whole minutes.

### 2.7. Optimistic Concurrency Control

Two write operations guard against stale client snapshots through optimistic concurrency control, and no other endpoint takes a version field.

First, renewal creation: a request to create a renewal for a permit must carry `expected_permit_version`, holding the permit `version` the client last observed. If the permit's current `version` has advanced since that observation — for example because another writer's renewal create already bumped it, or a cascade-driven suspension did — the create is rejected with `ERR_STALE_PERMIT_VERSION` (HTTP 412), and the client must re-read before writing.

Second, billing-cycle close: a close request must carry `expected_billing_cycle_version` matching the cycle's current `version`. Entry postings — activation fees, proration reposts, manual adjustments — bump the cycle's `version`, so a closer holding a stale snapshot would otherwise finalize a total it never saw; the mismatch is rejected with `ERR_STALE_CYCLE_VERSION` (HTTP 412).

### 2.8. Request Validation Order

When several checks could reject the same request, the server evaluates them in a fixed order, and an earlier failure masks all later ones. The order is:

1. **Authentication context.** `X-User-ID` and `X-User-Role` are present and the role is one of the six declared roles (`ERR_MISSING_OR_INVALID_AUTH_CONTEXT`).
2. **Role authorization.** The acting role is listed for the endpoint; on event-style endpoints, event-verb restrictions apply at the same step — permit `SUSPEND`, `REINSTATE`, and `REVOKE` are `ParkingAdmin`-only events, `APPEAL` is `Employee`-only, and `DECIDE_APPEAL` is `AppealsOfficer`-only (`ERR_FORBIDDEN_ROLE`).
3. **Employee body-ownership.** On a permit application, the payload `employee_id` must equal the caller's `X-User-ID` (`ERR_NOT_RESOURCE_OWNER`).
4. **Existence.** Every identifier in the path, validated left to right, and every foreign-key identifier in the body must reference an existing resource (`ERR_NOT_FOUND`). Immediately after the path resource loads — and before any state check — Employee path-ownership is enforced on permit events, renewal creation, and violation events: the loaded resource's owning `employee_id` must equal the caller's `X-User-ID` (`ERR_NOT_RESOURCE_OWNER`).
5. **Stale-version rejections.** The two optimistic-concurrency rules of §2.7 fire here, before any state evaluation (`ERR_STALE_PERMIT_VERSION`, `ERR_STALE_CYCLE_VERSION`).
6. **Lifecycle state and posture gates.** The target resource must be in the exact from-state of the requested transition, and program posture must permit the operation (`ERR_PROGRAM_FROZEN`, `ERR_PERMIT_NOT_OFFERED`, `ERR_INVALID_STATE`, `ERR_LOT_NOT_BOOKABLE`, `ERR_ROUTE_NOT_ACTIVE`, `ERR_CYCLE_NOT_OPEN`).
7. **Compliance gates.** Employment, enforceability, reinstatement-eligibility, and segregation-of-duties requirements (`ERR_EMPLOYEE_NOT_ACTIVE`, `ERR_TOW_VIOLATION_NOT_ENFORCEABLE`, `ERR_SEGREGATION_OF_DUTIES`, `ERR_REINSTATE_BLOCKED`).
8. **Temporal gates.** Logical-clock window checks (`ERR_OFFER_EXPIRED`, `ERR_TOW_HOLD_NOT_ELAPSED`, `ERR_APPEAL_WINDOW_CLOSED` — each HTTP 409 — and `ERR_NOTICE_EFFECTIVE_TOO_SOON`, which returns HTTP 422).
9. **Structural constraints.** Uniqueness, overlap, capacity, spacing, and shape rules (`ERR_DUPLICATE_ACTIVE_PERMIT`, `ERR_BADGE_NUMBER_TAKEN`, `ERR_PEAK_WINDOW_OVERLAP`, `ERR_BILLING_CYCLE_OVERLAP`, `ERR_CAPACITY_BELOW_OCCUPANCY`, `ERR_TRIP_SPACING_CONFLICT` — each HTTP 409 — plus `ERR_REMOTE_LOT_REQUIRED` at HTTP 422 and `ERR_INVALID_REQUEST` at HTTP 400, the last of which also covers malformed JSON, missing required fields, values of the wrong primitive type, invalid enum values, bad date or datetime formats, inverted date or datetime ranges (a `period_end` earlier than its `period_start`, a peak-window `ends_at` not strictly later than its `starts_at`, a notice `effective_to` not later than its `effective_from`), out-of-set `suspension_reason` values on a permit `SUSPEND` event, sign-rule violations on manual adjustments, and lot- and route-code conflicts).
10. **Fiscal gates.** Standing and open-cycle requirements (`ERR_BILLING_HOLD`, HTTP 402, and `ERR_NO_OPEN_BILLING_CYCLE`, HTTP 409).
11. **Cross-reference coherence.** Targeted resources must agree with each other (`ERR_VIOLATION_PERMIT_MISMATCH`, HTTP 409, and `ERR_NOTICE_TARGET_MISMATCH`, HTTP 422).

Two refinements pin what the ladder leaves unordered. Payload well-formedness — malformed JSON and missing required fields — is checked as the body is consumed: on the create endpoints, on renewal creation and decision, and on permit and violation events this precedes identifier resolution and ownership (steps 3–4); on the posture, capacity-update, close, settle, and route, trip, notice, tow, and cycle event endpoints the path resource loads first, so an unknown id masks a malformed body. Verb validation is likewise early: an unrecognized `event_type`, `decision`, or `outcome` is rejected with `ERR_INVALID_REQUEST` before the target resource's state gate on every event, decision, and settlement endpoint — and on permit events, violation events, and renewal decisions even before the path resource loads. Notice and violation creation validate the `notice_type`/`violation_code` enum (and, for notices, the `effective_from`/`effective_to` formats) before resolving body foreign keys, and a manual adjustment's charge-type, amount-type, and sign rules report before the cycle-open gate of step 6.

### 2.9. Identifier Resolution and Nested Reads

Identifiers embedded in a URL path are validated in left-to-right order: the first identifier that does not correspond to an existing resource yields `ERR_NOT_FOUND` (HTTP 404) before any further processing. The API surface is flat — resources are joined by foreign-key references rather than deep URL nesting, with sub-resource reads limited to patterns such as listing the renewals of a permit — and foreign-key identifiers supplied in request bodies are likewise verified to exist.

### 2.10. Cascading Consistency Across the Program Graph

Single operations in this domain routinely mutate several resources in one transaction: a notice becoming effective can close a lot, suspend every active permit on it, and reverse-and-repost their pending fee entries; a permit revocation releases a slot and immediately promotes the next waitlisted applicant. Derived figures — a lot's `occupied_slots` and `reserved_slots`, an employee's `balance_due_cents` and `standing`, a cycle's `total_charges_cents` — are always recomputed from their defining source rows rather than stored independently, so they stay correct after every direct write and every cascade. Every mutation a cascade performs on a resource refreshes that resource's `updated_at` and increments its `version`, exactly as a direct client write would.

## 3. Business Logic & Workflows

### 3.1. Program Configuration, Employee Registry, and the Posture Gate

A `ParkingAdmin` creates a parking program by supplying a `name` and, optionally, the program's operating configuration. The `proration_mode` selects the proration variant — `CALENDAR_DAY` (the default) or `HALF_MONTH` — and is immutable after creation. The `monthly_subsidy_pool_cents` seeds the subsidy pool available per billing cycle (default 0, never negative). Three policy knobs govern enforcement timing: `waitlist_offer_ttl_hours` sets how many hours an offer remains acceptable (default 72, must be positive), `violation_suspension_threshold` sets the unpaid-violation count that suspends a permit (default 3, at least 1), and `tow_hold_hours` sets the minimum suspension age in hours before a tow may be authorized (default 48, never negative). A new program starts in `posture` `PROGRAM_NORMAL` with its batch checkpoint counter `ops_run_index` at 0.

Posture is the program's master gate. A `ParkingAdmin` may freeze a `PROGRAM_NORMAL` program into `PROGRAM_FROZEN` and thaw it back at will. While frozen, waitlist promotion is disabled, and new permit applications and renewal creations are rejected with `ERR_PROGRAM_FROZEN`. Thawing a program back to `PROGRAM_NORMAL` immediately runs a waitlist promotion pass on every bookable lot of the program, processing the lots in `created_at` ascending order. Closure is stricter: moving from `PROGRAM_NORMAL` or `PROGRAM_FROZEN` to `PROGRAM_CLOSED` is allowed only when the program has no permit in `REQUESTED`, `WAITLISTED`, `OFFERED`, `ACTIVE`, or `SUSPENDED` and no billing cycle in `OPEN`. `PROGRAM_CLOSED` is terminal.

Employee registration is also a `ParkingAdmin` duty. Registering an employee takes the `program_id` of the program they park under, a `badge_number` that must be unique within that program across all employees (a conflict is rejected with `ERR_BADGE_NUMBER_TAKEN`), a `full_name`, an `employer_code` identifying the tenant or airline, a `shift_pattern` of `DAY`, `NIGHT`, `ROTATING`, or `SPLIT`, and a `hire_date` as an ISO calendar date. The shift pattern is immutable after creation and drives three downstream behaviors: the fee multiplier, the subsidy percentage, and the waitlist priority class. A new employee starts with `employment_status` `ACTIVE`, `balance_due_cents` 0, and `standing` `GOOD_STANDING`.

Two computed fields track an employee's fiscal position. `balance_due_cents` is the sum of `amount_cents` over the employee's charge entries currently in `DEDUCTION_FAILED` status — reversed and settled rows are excluded — and is never negative. `standing` is `BILLING_HOLD` whenever that balance is strictly greater than zero and `GOOD_STANDING` when it is exactly zero.

Termination is deliberately decoupled from permit revocation. When a `ParkingAdmin` terminates an employee, `employment_status` becomes `TERMINATED` and `terminated_at` is stamped with the current logical time; the employee's permits are not revoked at that moment. Revocation happens later, inside the ops-checkpoint termination sweep described in §3.9. `TERMINATED` is terminal.

### 3.2. Lots, Tiers, and the Occupancy Ledger

A `ParkingAdmin` creates a parking lot with its `program_id`, a `code` unique within the program (a code conflict is rejected with `ERR_INVALID_REQUEST`), an immutable `tier` of `CORE` or `REMOTE`, a `capacity` of total bookable slots (never negative), and an optional `monthly_maintenance_cents` fixed cost (default 0, never negative) that feeds the program cost report. Initial status depends on tier: a `CORE` lot starts `ACTIVE`, while a `REMOTE` lot starts `STANDBY`. A lot is bookable exactly when its `status` is `ACTIVE` or `ACTIVATED`.

Two derived counters keep the occupancy ledger. `occupied_slots` counts the lot's permits in `ACTIVE` status; `reserved_slots` counts the lot's permits in `OFFERED` status whose `offer_expires_at` has not yet passed relative to the logical clock — expired offers are excluded from the reservation. The available-slot figure is `capacity` minus `occupied_slots` minus `reserved_slots`, and it routes new applications: at least one available slot yields an offer, while zero yields the waitlist. The boundary is inclusive — a lot with exactly one available slot still makes an offer.

Capacity can be revised by a `ParkingAdmin`, but never below the sum of `occupied_slots` and `reserved_slots` (`ERR_CAPACITY_BELOW_OCCUPANCY`). A capacity increase triggers an immediate waitlist promotion pass on that lot.

The lot lifecycle itself is mostly system-driven and detailed in §3.9: peak windows swing a remote lot between `STANDBY` and `ACTIVATED`, a lot-closure notice drives `ACTIVE` or `ACTIVATED` to `CLOSED` with a permit-suspension cascade, a lot in `STANDBY` closes quietly, and a reopen notice returns a `CLOSED` lot to `ACTIVE` (for `CORE`) or `STANDBY` (for `REMOTE`) with an auto-reinstatement cascade.

### 3.3. Permit Applications, Offers, and the Waitlist

An employee — or a `ParkingAdmin` acting on their behalf — applies for a permit by submitting the `employee_id`, the requested `lot_id`, and the `vehicle_plate` used for enforcement. When the caller's role is `Employee`, the payload `employee_id` must equal their `X-User-ID` (`ERR_NOT_RESOURCE_OWNER`). Three structural gates guard the application: the program must not be `PROGRAM_FROZEN` or `PROGRAM_CLOSED` (`ERR_PROGRAM_FROZEN`); the target lot must be bookable (`ERR_LOT_NOT_BOOKABLE`); and the employee may hold at most one non-terminal permit — a second application while any permit of theirs sits in `REQUESTED`, `WAITLISTED`, `OFFERED`, `ACTIVE`, or `SUSPENDED` is rejected with `ERR_DUPLICATE_ACTIVE_PERMIT`.

At request time the server snapshots the employee's `shift_pattern` into the permit's `queue_shift_pattern`, which becomes the waitlist ranking key and the fee driver for everything that follows. The application is then evaluated synchronously within the same request: the transient `REQUESTED` state resolves to `OFFERED` when the lot shows at least one available slot, and to `WAITLISTED` when it shows none. An offer stamps `offered_at` with the current logical time, sets `offer_expires_at` to `offered_at` plus the program's `waitlist_offer_ttl_hours`, and raises the lot's derived reservation count by one.

Waitlist promotion follows a strict ranking whenever a pass runs. The candidate set is the lot's permits in `WAITLISTED`. Ranking is by shift-class priority descending — `NIGHT` ranks highest (priority 3), then `ROTATING` (2), then `SPLIT` (1), then `DAY` (0) — with ties broken first by `created_at` ascending and finally by `badge_number` ascending; resource ids are never used as tie-breakers. A pass promotes the top candidate to `OFFERED` — stamping `offered_at` and `offer_expires_at` as at application time — and continues while at least one slot remains available and candidates remain. Promotion requires the lot to be bookable and the program posture to be `PROGRAM_NORMAL`. Passes run after any slot release (a decline, a revocation, an offer expiring at the ops checkpoint), after a capacity increase, on lot activation or reopen, on program unfreeze, and inside every ops checkpoint; multi-lot passes process lots in `created_at` ascending order.

An offer that is not accepted can end three ways. Declining — via a permit event whose `event_type` is `DECLINE`, available to the owning employee or a `ParkingAdmin` — moves `OFFERED` to `DECLINED`, releases the reservation, and runs an immediate promotion pass on the lot. Expiry is the system's path: at the ops checkpoint, any offer whose `offer_expires_at` is strictly earlier than the current logical time moves `OFFERED` to `EXPIRED`, releases the reservation, and the promotion pass continues within the same checkpoint. Cancellation — `event_type` `CANCEL` — is permitted from `REQUESTED`, `WAITLISTED`, or `OFFERED`; only the `OFFERED` cancellation releases a reservation and runs a promotion pass, the other two have no lot effects. `REVOKED`, `DECLINED`, `EXPIRED`, and `CANCELLED` are the terminal states of a permit.

### 3.4. Activation and the Monthly Fee Pipeline

Accepting an offer — a permit event whose `event_type` is `ACCEPT`, performed by the owning employee or a `ParkingAdmin` — moves the permit from `OFFERED` to `ACTIVE`. Following the global validation order of §2.8, acceptance checks, in sequence: the permit must currently be `OFFERED` (`ERR_PERMIT_NOT_OFFERED`); the employee's `employment_status` must be `ACTIVE` (`ERR_EMPLOYEE_NOT_ACTIVE`); the current logical time must not be past `offer_expires_at` — the expiry instant itself remains acceptable (`ERR_OFFER_EXPIRED`); the employee's `standing` must be `GOOD_STANDING` (`ERR_BILLING_HOLD`, HTTP 402); and an `OPEN` billing cycle must exist for the program (`ERR_NO_OPEN_BILLING_CYCLE`).

Activation stamps `activated_at`, sets `term_end` to the activation date plus 12 months (a February 29 activation yields a February 28 `term_end`), releases the reservation and increases the lot's derived occupancy by one, and freezes the permit's gross monthly fee. The gross fee — stored as `monthly_fee_cents` — is the tier base rate multiplied by the shift multiplier of the permit's `queue_shift_pattern`, rounded half-up to integer cents. Base rates are 12000 cents per month for a `CORE` lot and 6000 cents for a `REMOTE` lot; multipliers are 1.0 for `DAY`, 0.75 for `NIGHT`, 0.85 for `ROTATING`, and 1.1 for `SPLIT`. The subsidy, by contrast, is never frozen onto the permit: it is re-derived at every fee posting from the billed cycle's own cap.

Every `PERMIT_FEE` posting — the activation entry, the cycle-open entries for already-active permits, truncation reposts, and reinstatement spans — derives its money in a pinned evaluation order: gross first, then subsidy, then net, then per-entry proration. The full-month subsidy is the smallest of three values: the shift subsidy percentage applied to the gross fee and rounded half-up, the billed cycle's `subsidy_per_capita_cap_cents` snapshot, and the gross fee itself. Subsidy percentages are 10% for `DAY`, 40% for `NIGHT`, 25% for `ROTATING`, and 15% for `SPLIT`. The full-month net fee is the gross minus the subsidy — never negative, because the subsidy is clamped at the gross. The entry's `amount_cents` is then the net fee prorated over the entry's billed span, and its `subsidy_cents` is the full subsidy scaled by exactly the same proration ratio and rounded half-up; `subsidy_cents` is 0 on every non-fee charge type.

Proration has two variants, selected by the program's `proration_mode`. Both share two span definitions: the period length is the number of calendar days from `period_start` through `period_end` inclusive — a closed interval — and the active days of an entry are the calendar days of its billed span (from `span_start` through `span_end`, both inclusive) that fall inside the period.

Under `CALENDAR_DAY`, the amount is the full-month net fee multiplied by the active-day count and divided by the period length, rounded half-up to integer cents. Consider a net fee of 10800 cents activated on 2026-08-11 inside a 31-day period: the span covers 21 active days, and the entry posts 7316 cents.

Under `HALF_MONTH`, the period splits on its fifteenth day. For spans that begin a billing — activation and reinstatement spans — the entry posts the full net fee when the span's start falls on or before the fifteenth day of the period (counting `period_start` as day 1), and half the net fee rounded half-up when it starts later. For truncation reposts — spans that end on a suspension or revocation date — the entry posts the full net fee when the span's end day, counted the same way, is later than the fifteenth (that is, the sixteenth or beyond), and half the net fee rounded half-up otherwise. The same 10800-cent activation on 2026-08-11 starts on day 11 of the period, so `HALF_MONTH` posts the full 10800 cents — a deliberate divergence from the 7316 cents the calendar-day variant produces. The `subsidy_cents` of the same entry follows the identical shape: under `CALENDAR_DAY` it is the full subsidy scaled by the active-day ratio and rounded half-up; under `HALF_MONTH` it is the full subsidy when the entry qualifies for the full fee and half the subsidy rounded half-up otherwise.

The activation entry itself posts as a `PENDING` `PERMIT_FEE` into the program's `OPEN` cycle, with `span_start` set to the activation date and `span_end` set to the cycle's `period_end`.

### 3.5. Suspension, Reinstatement, Revocation, and Renewal

A permit in `ACTIVE` can be suspended through three paths. The system suspends it when the unpaid-violation threshold is reached (§3.7) with `suspension_reason` `VIOLATION_THRESHOLD`, or when a lot-closure notice takes effect (§3.9) with reason `LOT_CLOSURE`. A `ParkingAdmin` may also suspend directly through a permit event whose `event_type` is `SUSPEND`, optionally supplying a `suspension_reason` of `ADMIN` or `BILLING_HOLD` — the default when omitted is `ADMIN`. Every suspension stamps `suspended_at` with the current logical time and records the reason. Note that a failed payroll deduction never suspends a permit by itself; billing-hold suspension is always an explicit administrative action.

Suspension truncates billing. The permit's `PENDING` `PERMIT_FEE` entry in the program's `OPEN` cycle whose span contains the suspension date is reversed, and a truncated `PENDING` repost is created covering the span start through the suspension date, priced per §3.4. Spans that already ended before the suspension date are untouched, and when no `OPEN` cycle exists the adjustment is skipped entirely. Because `occupied_slots` counts only `ACTIVE` permits, a suspension also reduces the lot's derived occupancy.

Reinstatement — a permit event whose `event_type` is `REINSTATE`, performed by a `ParkingAdmin` or triggered by the lot-reopen cascade — returns a `SUSPENDED` permit to `ACTIVE`. Its preconditions depend on the recorded reason. After a `VIOLATION_THRESHOLD` suspension, the permit's unpaid violation count must have fallen strictly below the program's `violation_suspension_threshold`. After a `LOT_CLOSURE` suspension, the lot must be bookable. After a `BILLING_HOLD` or `ADMIN` suspension, the employee's `standing` must be `GOOD_STANDING`. An unmet gate is rejected with `ERR_REINSTATE_BLOCKED`, and in every case an `OPEN` billing cycle must exist for the program (`ERR_NO_OPEN_BILLING_CYCLE`). Reinstatement clears the `suspension_reason`, increases the lot's derived occupancy by one, and posts a fresh `PENDING` `PERMIT_FEE` spanning the reinstate date through the cycle's `period_end`.

Revocation ends a permit, whether by a `ParkingAdmin` event (`event_type` `REVOKE`) or by the ops-checkpoint termination sweep. From `ACTIVE`, revocation applies the same span truncation as suspension — the pending fee entry whose span contains the revocation date is reversed and reposted through the revocation date, earlier ended spans untouched, skipped without an `OPEN` cycle — then releases the occupied slot and runs an immediate waitlist promotion pass on the lot. From `SUSPENDED`, revocation makes no further billing adjustment because the fee was already prorated at suspension; the permit had already left the lot's derived occupancy when it suspended, and the release is followed by a promotion pass. From `OFFERED`, revocation releases the reservation and promotes. From `WAITLISTED`, revocation has no lot effects at all.

Renewals extend an active permit's life in twelve-month increments. The owning employee or a `ParkingAdmin` creates a renewal against a permit, and the request must carry `expected_permit_version` per §2.7 — a permit whose `version` has advanced past the client's last observation rejects the create with `ERR_STALE_PERMIT_VERSION` (HTTP 412). Creation is refused outright when the program is `PROGRAM_FROZEN` or `PROGRAM_CLOSED` (`ERR_PROGRAM_FROZEN`) and when the employee is `TERMINATED` (`ERR_EMPLOYEE_NOT_ACTIVE`). Creation does not otherwise gate on the permit's own status — a `SUSPENDED`, `OFFERED`, or even terminal permit may hold a `PENDING` renewal; only the decision does. A successful creation starts the renewal at `PENDING`, stamps `requested_at`, supersedes any existing `PENDING` renewal of the same permit by moving it to `SUPERSEDED`, and increments the permit's `version` by one. A `ParkingAdmin` then decides: a `decision` of `APPROVE` requires the permit to be `ACTIVE` (`ERR_INVALID_STATE` otherwise) and extends the permit's `term_end` by 12 months (the same leap-day convention as activation applies: February 29 becomes February 28); a `decision` of `REJECT` closes the renewal as `REJECTED`. Either decision records the decider's `X-User-ID` in `decided_by`. Finally, renewals left undecided too long are swept: at the ops checkpoint, any renewal still `PENDING` whose permit's `term_end` date is strictly earlier than the current logical date — the comparison is by calendar day, so a renewal survives the checkpoint on its `term_end` day itself — moves to `EXPIRED`. `APPROVED`, `REJECTED`, `SUPERSEDED`, and `EXPIRED` are terminal.

### 3.6. Billing Cycles, Adjustments, and Payroll Settlement

A `PayrollAdmin` opens a billing cycle with its `program_id`, a `period_start`, and a `period_end` that must not be earlier than the start; the period is a closed interval covering both boundary dates. Cycles of one program may never share a calendar day — even sharing a single boundary day counts as an overlap and is rejected with `ERR_BILLING_CYCLE_OVERLAP`. A new cycle starts in `status` `OPEN`. Because only period overlap is forbidden, two cycles of one program can stand `OPEN` at the same time; wherever a workflow then posts an entry into the program's `OPEN` cycle without the operation itself naming the cycle — activation fees, reinstatement spans, truncation reposts, violation fines, tow fees, and appeal-dismissal credits — the earliest-created cycle of the program still in `OPEN` status receives the posting. A cycle's own creation-time entries always post into the newly created cycle itself.

Creation snapshots the subsidy cap that every fee posted against the cycle will use. The server first reads every employee's current `standing` — a position settled by prior cycles only — then counts the program's permits in `ACTIVE` status whose employee is in `GOOD_STANDING`, evaluated across all lots of the program at the creation instant. The cap stored as `subsidy_per_capita_cap_cents` is the program's `monthly_subsidy_pool_cents` floor-divided by that eligible count, with the denominator raised to a minimum of one so an empty program still yields a defined cap. Eligibility deliberately ignores the subsidy being computed — the standing snapshot breaks the circularity — and the stored cap is never recomputed for the life of the cycle. Creation also posts a full-period `PENDING` `PERMIT_FEE` entry for every permit `ACTIVE` at that instant, each spanning `period_start` through `period_end` and priced per §3.4 using this cycle's cap for the subsidy derivation.

Closing is the payroll gateway. A `PayrollAdmin` closes an `OPEN` cycle by submitting `expected_billing_cycle_version`; per §2.7 a mismatch with the cycle's current `version` is rejected with `ERR_STALE_CYCLE_VERSION` (HTTP 412), and that stale-version rejection is evaluated before the state gate. Closing a cycle that is not `OPEN` is rejected with `ERR_CYCLE_NOT_OPEN`. A successful close moves every `PENDING` entry of the cycle to `APPLIED`, recomputes `total_charges_cents` as the integer sum of `amount_cents` over the cycle's entries not in `REVERSED` status, and increments the cycle's `version` by one.

Export hands the cycle to payroll. A cycle event whose `event_type` is `EXPORT` moves a `CLOSED` cycle to `EXPORTED` and flips its `APPLIED` entries to `EXPORTED`. If payroll rejects the file, an event of `REJECT_EXPORT` returns the cycle from `EXPORTED` to `CLOSED` and compensates by moving its `EXPORTED` entries back to `APPLIED` — but only while no entry of the cycle has reached `SETTLED` or `DEDUCTION_FAILED`; once any entry has, the rejection is refused with `ERR_INVALID_STATE`.

Between those milestones, a `PayrollAdmin` may post manual adjustments into an `OPEN` cycle (`ERR_CYCLE_NOT_OPEN` otherwise). The payload carries `cycle_id`, `employee_id`, a `charge_type` restricted to `ADJUSTMENT_CREDIT` or `ADJUSTMENT_DEBIT`, an `amount_cents`, and an optional free-text `description`. The sign of a manual amount is enforced by its type — credits must be strictly negative, debits strictly positive, and zero is rejected for both — and a violation is rejected with `ERR_INVALID_REQUEST`. System-posted entries pin their own `charge_type`: `PERMIT_FEE` for fee postings, `VIOLATION_FINE` at violation issuance, and `TOW_FEE` at tow release. On system entries the `cycle_id` is assigned by the server at posting, `permit_id` carries the permit context for fee, fine, and tow rows and is null on plain adjustments, and `span_start` with `span_end` appear only on `PERMIT_FEE` rows, inclusive at both ends.

A charge entry's `status` begins at `PENDING` and flows to `APPLIED` at cycle close, then to `EXPORTED` at cycle export, and finally to `SETTLED` or `DEDUCTION_FAILED` through settlement. `REVERSED` is reachable from `PENDING` — through the suspension and revocation truncations of §3.5 or the appeal dismissal of a still-pending fine in §3.7 — and the transition out of `APPLIED` is defined, though the two workflows that touch applied rows deliberately avoid it: an export rejection returns entries to `APPLIED`, and an appeal dismissal on an already-applied or already-exported fine posts a compensating credit instead of reversing the row. `SETTLED` and `REVERSED` are terminal, and `REVERSED` entries are excluded from `total_charges_cents`.

Settlement records payroll's deduction outcome. A `PayrollAdmin` settles an `EXPORTED` entry — or retries a `DEDUCTION_FAILED` one — by supplying an `outcome` of `SETTLED` or `DEDUCTION_FAILED`. The only retry defined for a `DEDUCTION_FAILED` entry is `SETTLED`; re-declaring `DEDUCTION_FAILED` on an already-failed entry, or settling an entry in any status other than `EXPORTED` or `DEDUCTION_FAILED`, is rejected with `ERR_INVALID_STATE`. Marking `DEDUCTION_FAILED` raises the employee's `balance_due_cents` by the entry's `amount_cents` and recomputes `standing`, which flips to `BILLING_HOLD` once the balance exceeds zero; permits are not auto-suspended as a consequence. A later `SETTLED` outcome on that entry reduces the balance by the same amount and recomputes standing again. Settling an entry whose `charge_type` is `VIOLATION_FINE` to `SETTLED` — whether directly from `EXPORTED` or by retry from `DEDUCTION_FAILED` — flips the linked violation's `payment_status` from `UNPAID` to `PAID`.

Program economics close the loop. A computed cost report, readable by `ParkingAdmin` and `PayrollAdmin`, returns five figures in one response. `total_cost_cents` aggregates, over every route of the program, the all-time count of `COMPLETED` trips each multiplied by its route's `operating_cost_per_trip_cents`, and adds the `monthly_maintenance_cents` of every lot of the program. `subsidy_spent_cents` sums `subsidy_cents` over the program's `PERMIT_FEE` entries not in `REVERSED` status. `active_permit_count` counts the program's permits in `ACTIVE` at read time. `gross_cost_per_employee_cents` divides the total cost by the active-permit count — with the denominator raised to a minimum of one — rounded half-up to integer cents, and `net_cost_per_employee_cents` performs the same division after subtracting the subsidy spend from the total cost, so the net figure is lower whenever any subsidy has been spent.

### 3.7. Violations, Appeals, and Tow Enforcement

An `EnforcementOfficer` issues a violation against a permit by submitting its `permit_id` and a `violation_code` drawn from `EXPIRED_PERMIT`, `WRONG_LOT`, `NO_PERMIT_DISPLAY`, `BLOCKED_LANE`, or `PARKED_AFTER_REVOCATION`. The server records the officer's `X-User-ID` in `issued_by`, stamps `issued_at` with the current logical time, and requires an `OPEN` billing cycle for the program (`ERR_NO_OPEN_BILLING_CYCLE`).

The fine escalates with repeat offenses. The escalation count is the number of violations of the same permit still `UNPAID` and issued within the trailing 365 days, measured to the instant — a prior violation counts when its `issued_at` is no earlier than the current logical time minus 365 days — while `PAID` and `REVERSED` violations are excluded. Each such prior unpaid violation adds 50% of the base fine: the fine is the base for the code multiplied by one plus one-half times the escalation count, rounded half-up to integer cents, and stored as `fine_cents`. Base fines are 5000 cents for `EXPIRED_PERMIT`, 3500 for `WRONG_LOT`, 2500 for `NO_PERMIT_DISPLAY`, 7500 for `BLOCKED_LANE`, and 10000 for `PARKED_AFTER_REVOCATION`. Issuance immediately posts a `PENDING` `VIOLATION_FINE` charge entry for that amount into the `OPEN` cycle and links it back through the violation's `charge_entry_id`.

One more consequence fires after the entry posts. When the escalation count plus the new violation reaches or exceeds the program's `violation_suspension_threshold` — the violation that reaches the threshold is the one that triggers — and the permit is `ACTIVE`, the permit moves to `SUSPENDED` with `suspension_reason` `VIOLATION_THRESHOLD`, carrying the full suspension bookkeeping of §3.5 including the fee truncation repost.

A violation then lives along two parallel dimensions. The payment dimension `payment_status` starts at `UNPAID` and moves to `PAID` when the linked fine entry settles to `SETTLED`, or to `REVERSED` through the dismissal cascade below. The appeal dimension `appeal_status` starts at `NONE` and moves to `APPEALED`, then to `UPHELD` or `DISMISSED`.

Appeals belong to the cited employee alone. The owning employee — and only the `Employee` role — may file an appeal event while `payment_status` is still `UNPAID` (`ERR_INVALID_STATE` otherwise) and no later than the instant exactly 14 days after `issued_at` — that instant itself remains acceptable, and any later moment is rejected with `ERR_APPEAL_WINDOW_CLOSED`. An `AppealsOfficer` then decides with a `decision` of `UPHELD` or `DISMISSED`; segregation of duties forbids the decider's `X-User-ID` from matching the violation's `issued_by`, and a match is rejected with `ERR_SEGREGATION_OF_DUTIES`. An `UPHELD` decision changes nothing further. A `DISMISSED` decision flips `payment_status` to `REVERSED` and compensates the ledger: the linked `VIOLATION_FINE` entry is reversed when it is still `PENDING`, while an entry that has already advanced to `APPLIED` or `EXPORTED` is left in place and an `ADJUSTMENT_CREDIT` for the fine amount is posted instead into the program's current `OPEN` cycle, if one exists. If the linked entry has already reached `SETTLED` or `DEDUCTION_FAILED`, the dismissal still flips `payment_status` to `REVERSED` but leaves the entry untouched and posts no compensation.

Towing is the enforcement endpoint of last resort. An `EnforcementOfficer` authorizes a tow by naming the `permit_id` and the triggering `violation_id`. Authorization requires the permit to be `SUSPENDED` with `suspension_reason` `VIOLATION_THRESHOLD` (`ERR_INVALID_STATE` otherwise); the triggering violation must remain enforceable — `payment_status` `UNPAID` and `appeal_status` anything other than `DISMISSED` (`ERR_TOW_VIOLATION_NOT_ENFORCEABLE`); the tow hold must have elapsed, meaning the current logical time has reached or passed `suspended_at` plus the program's `tow_hold_hours` (`ERR_TOW_HOLD_NOT_ELAPSED`); and the cited violation must belong to the same permit (`ERR_VIOLATION_PERMIT_MISMATCH`). Authorization records the officer's `X-User-ID` in `authorized_by` and starts the tow event at `AUTHORIZED`.

From there the tow event tracks physical reality. A tow event whose `event_type` is `MARK_TOWED` stamps `towed_at` and moves `AUTHORIZED` to `TOWED`. An event of `RELEASE` moves `TOWED` to `RELEASED`, requires an `OPEN` billing cycle (`ERR_NO_OPEN_BILLING_CYCLE`), stamps `released_at`, and computes `impound_fee_cents` as a 15000-cent tow base plus 2500 cents of storage per day held — the held time being `released_at` minus `towed_at`, rounded up to whole days, with a one-day minimum. Release then posts a `PENDING` `TOW_FEE` entry for that amount into the `OPEN` cycle and records it in the tow event's `charge_entry_id`. A tow still in `AUTHORIZED` may instead be cancelled. `RELEASED` and `CANCELLED` are terminal.

### 3.8. Shuttle Operations and Service-Level Measurement

A `ShuttleDispatcher` creates a shuttle route by naming the `lot_id` it serves, a `code` unique within that lot's program, a positive `headway_target_minutes` scheduling goal, and a non-negative `operating_cost_per_trip_cents` that feeds the cost report. A new route starts `ACTIVE`. Suspension — either a dispatcher route event whose `event_type` is `SUSPEND`, or a route-suspension notice becoming effective — moves the route to `SUSPENDED`; crucially, its trips are not cancelled: `SCHEDULED` trips remain on the books, but any departure attempt is rejected with `ERR_ROUTE_NOT_ACTIVE` while the route is suspended. A dispatcher event of `RESUME` returns the route to `ACTIVE`.

Trips are the route's timetable. A dispatcher schedules a trip with its `route_id` and a `scheduled_departure_at` in the logical-clock domain, starting at `SCHEDULED`. Departures on one route must breathe: the scheduled departures of all non-`CANCELLED` trips on a route must sit at least 5 minutes apart, so a new trip landing within five minutes of an existing one is rejected with `ERR_TRIP_SPACING_CONFLICT` — exactly five minutes is acceptable. A departure event (`event_type` `DEPART`) requires the route to be `ACTIVE`, stamps `actual_departure_at` with the current logical time, and moves the trip to `DEPARTED`. Completion (`COMPLETE`) carries the `boarded_count` of passengers — non-negative, defaulting to 0 — and moves the trip to `COMPLETED`. Cancellation is available from `SCHEDULED` or `DEPARTED`. `COMPLETED` and `CANCELLED` are terminal.

Service level is a computed read over a time window, answering whether the route honored its headway promise. The caller supplies `window_start`, `window_end`, and a `mode` of `SCHEDULED` or `OBSERVED`, and receives `max_gap_minutes`, `expected_wait_minutes`, `sla_compliant`, and `trip_count`. The window selects trips whose `scheduled_departure_at` falls within it, both endpoints inclusive. Under `SCHEDULED` mode every selected trip participates by its scheduled departure — the published timetable, whatever the trip's status. Under `OBSERVED` mode only trips with an `actual_departure_at` — those `DEPARTED` or `COMPLETED` — participate, and they participate by their actual departure; cancelled and never-departed trips drop out, which stretches the adjacent observed gaps. In both modes the participating trips are ordered by departure ascending with `created_at` ascending as the tie-break, gaps are the consecutive departure deltas in whole minutes, `max_gap_minutes` is the largest gap, and `expected_wait_minutes` is half the mean of the gaps, rounded half-up to two decimal places. A route is `sla_compliant` exactly when its largest gap is at most twice its `headway_target_minutes`. When fewer than two trips participate, the gap list is empty and `max_gap_minutes`, `expected_wait_minutes`, and `sla_compliant` all come back null, while `trip_count` — which always reports the number of participating trips — comes back 0 or 1. The two modes can disagree sharply: a route whose timetable shows four trips ten minutes apart reports a compliant 10-minute maximum gap under `SCHEDULED`, yet if the middle two trips were cancelled, `OBSERVED` mode sees a 30-minute hole between the surviving departures and reports non-compliance for the same window.

### 3.9. Peak Windows, Service Notices, and the Ops Checkpoint

Remote lots exist for peak days, and peak windows schedule their activation. A `ParkingAdmin` creates a peak window with the target `lot_id`, a `starts_at`, and an `ends_at`. The target lot must be tier `REMOTE` (`ERR_REMOTE_LOT_REQUIRED`, HTTP 422), and `ends_at` must be strictly later than `starts_at`. Windows are half-open — they include `starts_at` and exclude `ends_at` — and a new window may not overlap any non-`CANCELLED` window of the same lot (`ERR_PEAK_WINDOW_OVERLAP`), although back-to-back adjacency, where one window's `starts_at` equals another's `ends_at`, is allowed. A new window starts `SCHEDULED` and may be cancelled while still in that state.

Peak windows are driven by the ops checkpoint. When the logical clock has reached a window's `starts_at` but not yet its `ends_at`, the checkpoint moves the window from `SCHEDULED` to `ACTIVE` and flips its lot from `STANDBY` to `ACTIVATED`, making it bookable and running a waitlist promotion pass on it. Once the clock reaches `ends_at`, the checkpoint moves the window from `ACTIVE` to `ENDED` and returns the lot to `STANDBY` — unbookable for new applications, while existing `ACTIVE` permits on the lot are unaffected. `ENDED` and `CANCELLED` are terminal.

Service change notices are how the program communicates — and executes — structural changes. A `ParkingAdmin` drafts a notice with a `notice_type` of `LOT_CLOSURE`, `LOT_REOPEN`, `ROUTE_SUSPENSION`, `HEADWAY_CHANGE`, or `GENERAL`, a public `headline`, and an `effective_from` instant. Target coherence is enforced by type: `LOT_CLOSURE` and `LOT_REOPEN` require a `lot_id` and forbid a `route_id`; `ROUTE_SUSPENSION` and `HEADWAY_CHANGE` require a `route_id` and forbid a `lot_id`; and `HEADWAY_CHANGE` additionally requires a positive `new_headway_minutes`. Any incoherence is rejected with `ERR_NOTICE_TARGET_MISMATCH` (HTTP 422). An optional `effective_to` may be recorded to bound the communicated effect window and, when present, must be later than `effective_from`; it is informational only — no checkpoint or cascade consults it, and an `EFFECTIVE` notice's effects are never undone when it passes. A new notice starts in `DRAFT`.

Publication commits the communication. A notice event of `PUBLISH` stamps `published_at` and moves the notice from `DRAFT` to `PUBLISHED`, but only when `effective_from` lies at least 72 hours in the future relative to the logical clock (`ERR_NOTICE_EFFECTIVE_TOO_SOON`, HTTP 422) — the program owes its parkers three days of warning. Cancellation is permitted from `DRAFT` or `PUBLISHED`.

Effectiveness is where notices bite. At the ops checkpoint, every `PUBLISHED` notice whose `effective_from` has been reached and whose target belongs to the checkpoint's program — the named lot, or the lot of the named route — moves to `EFFECTIVE` and fires its cascade; notices due in the same run fire in `created_at` ascending order. A `GENERAL` notice names no target, so no program's checkpoint ever claims it: it remains `PUBLISHED` until cancelled. A notice whose target is already in the destination state — a closure on a `CLOSED` lot, a reopen on a lot that is not `CLOSED`, a suspension of an already-`SUSPENDED` route — fires no cascade but still becomes `EFFECTIVE`. A `LOT_CLOSURE` closes its target lot: from `ACTIVE` or `ACTIVATED`, every permit of the lot currently `ACTIVE` is suspended with `suspension_reason` `LOT_CLOSURE` and `suspended_at` stamped, and each such suspension applies the §3.5 span truncation — the pending fee entry whose span contains the suspension date is reversed and reposted through that date — in the program's `OPEN` cycle when one exists; a lot sitting in `STANDBY` simply closes, with no permit cascade. A `LOT_REOPEN` returns a `CLOSED` lot to `ACTIVE` when its tier is `CORE` or to `STANDBY` when `REMOTE`, auto-reinstates every permit still `SUSPENDED` with reason `LOT_CLOSURE` back to `ACTIVE`, posts a prorated `PENDING` `PERMIT_FEE` spanning the reinstate date through the cycle's `period_end` in the `OPEN` cycle when one exists, and runs a waitlist promotion pass on the lot. A `ROUTE_SUSPENSION` suspends its route — trips are not cancelled, but departures are blocked while suspended. A `HEADWAY_CHANGE` rewrites the route's `headway_target_minutes` to `new_headway_minutes`. A `GENERAL` notice carries no structural effect. `EFFECTIVE` and `CANCELLED` are terminal.

The ops checkpoint is the program's batch heartbeat, advanced by a `ParkingAdmin`. Each run executes seven ordered steps, and within a step the affected windows, notices, permits, and renewals are processed in `created_at` ascending order. First, peak-window activation and ending, swinging remote lots between `STANDBY` and `ACTIVATED` with their promotion passes. Second, every `PUBLISHED` notice of the program whose `effective_from` has arrived becomes `EFFECTIVE` and fires the cascades above. Third, offers whose `offer_expires_at` is strictly in the past move from `OFFERED` to `EXPIRED`, releasing their reservations. Fourth, the termination sweep revokes every non-terminal permit of a `TERMINATED` employee — `ACTIVE` permits receive the revocation span-truncation repost, `OFFERED` permits release their reservations, and the promotion passes those revocations would trigger are deferred to step five. Fifth, a waitlist promotion pass runs on each lot, lots processed in `created_at` ascending order. Sixth, `PENDING` renewals whose permit's `term_end` date is strictly before the current logical date move to `EXPIRED`. Seventh, the program's `ops_run_index` increments by one. The run also increments the program's `version` by one and returns the updated program.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — including state-transition event posts, capacity changes, posture transitions, closes, settlements, and the ops checkpoint — return `200 OK`. Request payloads, preconditions, and side effects for every endpoint are defined by the workflows of §3; the table below is a navigational summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock (startup default 2026-08-01T00:00:00Z) | ParkingAdmin |
| POST | `/parking/programs` | Create a parking program | ParkingAdmin |
| GET | `/parking/programs/{id}` | Get a program | All roles |
| POST | `/parking/programs/{id}/posture` | Transition program posture (freeze, unfreeze, close) | ParkingAdmin |
| POST | `/parking/programs/{id}/run-ops` | Advance the program's ops checkpoint | ParkingAdmin |
| GET | `/parking/programs/{id}/cost-report` | Computed program economics, gross and net cost per employee | ParkingAdmin, PayrollAdmin |
| POST | `/parking/employees` | Register an employee | ParkingAdmin |
| GET | `/parking/employees/{id}` | Get an employee | All roles |
| GET | `/parking/employees` | List employees; filterable by `program_id`, `shift_pattern`, `standing`, `employment_status` | All roles |
| POST | `/parking/employees/{id}/terminate` | Terminate employment | ParkingAdmin |
| POST | `/parking/lots` | Create a parking lot | ParkingAdmin |
| GET | `/parking/lots/{id}` | Get a lot, including derived occupancy | All roles |
| GET | `/parking/lots` | List lots; filterable by `program_id`, `tier`, `status` | All roles |
| PATCH | `/parking/lots/{id}` | Change lot capacity | ParkingAdmin |
| POST | `/parking/permits` | Apply for a permit; synchronously offers or waitlists | Employee, ParkingAdmin |
| GET | `/parking/permits/{id}` | Get a permit | All roles |
| GET | `/parking/permits` | List permits; filterable by `employee_id`, `lot_id`, `status` | All roles |
| POST | `/parking/permits/{id}/events` | Permit lifecycle events: ACCEPT, DECLINE, CANCEL, SUSPEND, REINSTATE, REVOKE | Employee, ParkingAdmin |
| POST | `/parking/permits/{id}/renewals` | Request a permit renewal (supersedes any pending one) | Employee, ParkingAdmin |
| GET | `/parking/permits/{id}/renewals` | List renewals of a permit | All roles |
| POST | `/parking/renewals/{id}/decide` | Approve or reject a pending renewal | ParkingAdmin |
| POST | `/parking/routes` | Create a shuttle route serving a lot | ShuttleDispatcher |
| GET | `/parking/routes/{id}` | Get a route | All roles |
| GET | `/parking/routes` | List routes; filterable by `lot_id`, `status` | All roles |
| POST | `/parking/routes/{id}/events` | Route events: SUSPEND, RESUME | ShuttleDispatcher |
| GET | `/parking/routes/{id}/service-level` | Headway and wait-time service level for a window and mode | All roles |
| POST | `/parking/trips` | Schedule a trip on a route | ShuttleDispatcher |
| GET | `/parking/trips/{id}` | Get a trip | All roles |
| GET | `/parking/trips` | List trips; filterable by `route_id`, `status` | All roles |
| POST | `/parking/trips/{id}/events` | Trip events: DEPART, COMPLETE, CANCEL | ShuttleDispatcher |
| POST | `/parking/notices` | Draft a service change notice | ParkingAdmin |
| GET | `/parking/notices/{id}` | Get a notice | All roles |
| GET | `/parking/notices` | List notices; filterable by `lot_id`, `route_id`, `notice_type`, `status` | All roles |
| POST | `/parking/notices/{id}/events` | Notice events: PUBLISH, CANCEL | ParkingAdmin |
| POST | `/parking/violations` | Issue a violation against a permit | EnforcementOfficer |
| GET | `/parking/violations/{id}` | Get a violation | All roles |
| GET | `/parking/violations` | List violations; filterable by `permit_id`, `charge_entry_id`, `payment_status`, `appeal_status` | All roles |
| POST | `/parking/violations/{id}/events` | Violation events: APPEAL, DECIDE_APPEAL | Employee, AppealsOfficer |
| POST | `/parking/tow-events` | Authorize a tow for a threshold-suspended permit | EnforcementOfficer |
| GET | `/parking/tow-events/{id}` | Get a tow event | All roles |
| GET | `/parking/tow-events` | List tow events; filterable by `permit_id`, `violation_id`, `charge_entry_id`, `status` | All roles |
| POST | `/parking/tow-events/{id}/events` | Tow events: MARK_TOWED, RELEASE, CANCEL | EnforcementOfficer |
| POST | `/parking/billing-cycles` | Open a billing cycle (snapshots subsidy cap, posts full-period fees) | PayrollAdmin |
| GET | `/parking/billing-cycles/{id}` | Get a billing cycle | All roles |
| GET | `/parking/billing-cycles` | List billing cycles; filterable by `program_id`, `status` | All roles |
| POST | `/parking/billing-cycles/{id}/close` | Close an open cycle | PayrollAdmin |
| POST | `/parking/billing-cycles/{id}/events` | Cycle events: EXPORT, REJECT_EXPORT | PayrollAdmin |
| POST | `/parking/charge-entries` | Post a manual adjustment (credit or debit) to an open cycle | PayrollAdmin |
| GET | `/parking/charge-entries/{id}` | Get a charge entry | All roles |
| GET | `/parking/charge-entries` | List charge entries; filterable by `cycle_id`, `employee_id`, `permit_id`, `charge_type`, `status` | All roles |
| POST | `/parking/charge-entries/{id}/settle` | Record a settlement outcome for an exported or failed entry | PayrollAdmin |
| POST | `/parking/peak-windows` | Schedule a remote-lot activation window | ParkingAdmin |
| GET | `/parking/peak-windows/{id}` | Get a peak window | All roles |
| GET | `/parking/peak-windows` | List peak windows; filterable by `lot_id`, `status` | All roles |
| POST | `/parking/peak-windows/{id}/cancel` | Cancel a scheduled peak window | ParkingAdmin |

## 5. Error Code Catalogue

The catalogue below lists every error identifier and its HTTP status. Trigger conditions are defined in the workflows of §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_AUTH_CONTEXT` | 400 Bad Request |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_PERMIT_VERSION` | 412 Precondition Failed |
| `ERR_STALE_CYCLE_VERSION` | 412 Precondition Failed |
| `ERR_PROGRAM_FROZEN` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_PERMIT_NOT_OFFERED` | 409 Conflict |
| `ERR_OFFER_EXPIRED` | 409 Conflict |
| `ERR_LOT_NOT_BOOKABLE` | 409 Conflict |
| `ERR_ROUTE_NOT_ACTIVE` | 409 Conflict |
| `ERR_CYCLE_NOT_OPEN` | 409 Conflict |
| `ERR_EMPLOYEE_NOT_ACTIVE` | 409 Conflict |
| `ERR_TOW_VIOLATION_NOT_ENFORCEABLE` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 409 Conflict |
| `ERR_TOW_HOLD_NOT_ELAPSED` | 409 Conflict |
| `ERR_APPEAL_WINDOW_CLOSED` | 409 Conflict |
| `ERR_NOTICE_EFFECTIVE_TOO_SOON` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_ACTIVE_PERMIT` | 409 Conflict |
| `ERR_BADGE_NUMBER_TAKEN` | 409 Conflict |
| `ERR_PEAK_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_BILLING_CYCLE_OVERLAP` | 409 Conflict |
| `ERR_CAPACITY_BELOW_OCCUPANCY` | 409 Conflict |
| `ERR_TRIP_SPACING_CONFLICT` | 409 Conflict |
| `ERR_REMOTE_LOT_REQUIRED` | 422 Unprocessable Entity |
| `ERR_BILLING_HOLD` | 402 Payment Required |
| `ERR_NO_OPEN_BILLING_CYCLE` | 409 Conflict |
| `ERR_REINSTATE_BLOCKED` | 409 Conflict |
| `ERR_VIOLATION_PERMIT_MISMATCH` | 409 Conflict |
| `ERR_NOTICE_TARGET_MISMATCH` | 422 Unprocessable Entity |
