# Charitable Gaming API — Product Requirements Document

## 1. Introduction

State charitable-gaming commissions license nonprofit organizations to run regulated games of chance — bingo nights and raffles — and then hold those organizations to a demanding chain of obligations: prove eligibility, schedule occasions within statutory prize caps, report actual receipts and payouts, distribute net proceeds to charitable purposes, register the equipment they use through licensed suppliers, and answer for violations that accrue toward suspension. This API is the system of record for that entire regulatory relationship. It exists to make the paper-heavy, audit-driven world of charitable gaming enforceable in software, so that a regulator, an organization's officer, and an equipment supplier can each act only within their lawful authority and every financial figure reconciles against a single source of truth.

The domain is unusually tightly coupled. A single occasion report can move money between two prize-consumption ledgers, breach a per-occasion or annual prize cap, and — if filed late — automatically raise a violation that tips a license over its suspension threshold and cascades cancellations across every future occasion and its reserved equipment. Because so many figures are *derived* rather than stored by the client, the specifications below pin down exactly how each computed value is produced, in what order, and to what precision. Time itself is modeled through an explicit logical clock rather than wall-clock time, so that eligibility windows, reporting grace periods, and license expiry can be tested deterministically.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that govern every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If `X-User-Role` is missing or is not exactly one of the three recognized role names, the request is rejected with `ERR_UNAUTHENTICATED`. When the header is present and valid but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly three roles, spelled precisely as follows:

- `Regulator` — the state charitable-gaming commission operator. Regulators register organizations and suppliers, approve/suspend/reinstate licenses, register suppliers, accept or reject audited financial reports, record and waive violations, decide renewals, and control the logical clock. When `X-User-Role` is `Regulator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. Any authenticated `Regulator` may act on any resource of the types under regulatory control.
- `OrgOfficer` — an officer acting on behalf of a single nonprofit `Organization`. When `X-User-Role` is `OrgOfficer`, `X-User-ID` is the `id` of the acting `Organization`. Ownership checks on any resource that references an `Organization` compare `X-User-ID` to that organization: for a `License`, `X-User-ID` must equal the license's `organization_id`; for an `Occasion`, `FinancialReport`, `Violation`, or `Renewal`, ownership is resolved indirectly through the resource's `license_id` to the owning license's `organization_id`. An `OrgOfficer` acting on a resource its organization does not own is rejected with `ERR_FORBIDDEN`.
- `Supplier` — a registered equipment supplier acting as a single `Supplier` entity. When `X-User-Role` is `Supplier`, `X-User-ID` is the `id` of the acting `Supplier`. Ownership checks on any `Equipment` compare the equipment's `supplier_id` to `X-User-ID`; a mismatch is rejected with `ERR_FORBIDDEN`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

List-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource in this system — `Organization`, `License`, `Occasion`, `Supplier`, `Equipment`, `EquipmentAllocation`, `FinancialReport`, `Violation`, and `Renewal` — carries the same set of system-managed fields:

- `id` — a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, recorded when the resource is first created.
- `updated_at` — an ISO 8601 UTC timestamp, refreshed on every modification to the resource.
- `version` — an integer that begins at its initial value and increments by one on every mutation of the resource. It is the basis for optimistic concurrency control (§2.7).

Beyond these, each resource that moves through a lifecycle exposes a `status` field holding its current state, using the exact uppercase enumeration values named in §3.

Whenever the server recomputes a derived figure on a resource and persists the change — for example, adjusting a license's prize ledgers or its active violation points — that counts as a mutation of the affected resource: its `updated_at` is refreshed and its `version` is incremented.

### 2.5. The Logical Clock and Deferred Time-Based Actions

The system never reads wall-clock time. Instead it maintains a single logical clock that a `Regulator` may set to any instant. On server startup the clock reads exactly `2026-05-01T00:00:00Z`; before any clock-setting call is made, the clock holds this default and never falls back to real time. The clock-setting capability accepts a target instant in the `to_iso8601` field and moves the clock to it.

The clock drives two families of deferred computation. First, an organization's `months_active` and `eligibility_status` are always evaluated against the current clock, so the same organization can be ineligible at one clock value and eligible at a later one. Second, advancing the clock past a license's `expiration_date` lazily transitions any `ACTIVE` license whose expiry has passed into the `EXPIRED` state, applying the standard suspension/expiry cancellation cascade described in §2.6 and §3.

### 2.6. Hierarchical Consistency and Cascades

Several operations mutate more than one resource. The system applies these cascades atomically and consistently, and each affected resource independently has its `updated_at` refreshed and its `version` incremented.

When a license leaves the `ACTIVE` state — whether suspended by a regulator, auto-suspended when its active violation points reach the suspension threshold, or expired by the advancing clock — every `Occasion` on that license still in `SCHEDULED` status is driven to `CANCELLED`. Each such cancellation is itself a full transition: it releases that occasion's reserved prize commitment back to the license, and it drives every `EquipmentAllocation` for that occasion that is still `ACTIVE` to `RELEASED`. This is a transitive cascade — a single suspend or expire can therefore ripple through many occasions and many allocations in one operation.

Filing an occasion report late produces a second kind of cascade: the system auto-creates a `Violation`, which recomputes the owning license's active violation total, which may in turn auto-suspend the license and trigger the cancellation cascade above.

### 2.7. Optimistic Concurrency Control

Two write operations against a `License` require the client to prove it is acting on a current view of that license by supplying `expected_license_version`, which must equal the license's current `version`. This field is non-optional on those two operations.

The first is updating a license's mutable contact fields. The second is requesting a renewal for a license. In both cases, if `expected_license_version` does not match the license's current `version` — because another update, a renewal, or a cascade advanced the version since the client last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and no change is made. This protects against the lost-update case in which a client would otherwise overwrite state it never observed. A successful update or renewal request advances the license's `version` by one. No other endpoint accepts or requires a version field.

### 2.8. Reverse-Reachability Retrieval and Left-to-Right Path Validation

Although every resource is addressable as a top-level collection member, the API also exposes reverse-reachability list endpoints — for example, the licenses belonging to an organization, the occasions or financial reports or violations or renewals belonging to a license, the equipment belonging to a supplier, and the allocations belonging to an occasion or to an equipment item. For any request whose path contains a resource identifier, the system validates that identifier's existence first; if it does not correspond to an existing resource, the request is rejected with `ERR_NOT_FOUND` before any further processing. When a path contains more than one identifier, they are validated left-to-right, and the first missing identifier determines the `ERR_NOT_FOUND` rejection.

### 2.9. Monetary Precision and Rounding

All monetary amounts are stored and returned as integer cents. Where a calculation multiplies a cents amount by a percentage — the administrative allowance and regulatory fee on a financial report — the product is rounded to a whole number of cents using the round-half-up method (a fractional value of exactly one-half rounds up). The `charitable_use_ratio` is the sole non-integer figure: it is a decimal rounded to four decimal places. No monetary figure is ever represented with fractional cents.

### 2.10. Validation Ordering

When several checks could reject the same request, they are evaluated in a fixed priority order so that the returned `error_id` is deterministic. The order is:

1. **Authentication** — `X-User-Role` is present and is one of `Regulator`, `OrgOfficer`, or `Supplier`; otherwise `ERR_UNAUTHENTICATED` (401).
2. **Role authorization** — the role is permitted to perform the operation; otherwise `ERR_FORBIDDEN` (403).
3. **Path existence** — every resource identifier in the path exists, validated left-to-right; otherwise `ERR_NOT_FOUND` (404).
4. **Ownership** — an entity-backed actor (`OrgOfficer` or `Supplier`) owns the targeted resource as defined in §2.1; otherwise `ERR_FORBIDDEN` (403).
5. **Body well-formedness** — required fields present, enum values valid, and ordered time ranges correct; a malformed body yields `ERR_VALIDATION` (422), except for the three ordered-range checks which carry their own codes (see §3).
6. **Optimistic concurrency** — where `expected_license_version` is carried, it matches the license's current `version`; otherwise `ERR_STALE_VERSION` (412).
7. **State legality** — the target resource is in a state from which the requested transition is defined; otherwise `ERR_INVALID_STATE` (409).
8. **Cross-entity safety gates** — the eligibility and license-active gates described in §3; e.g. `ERR_ORG_NOT_ELIGIBLE` or `ERR_LICENSE_NOT_ACTIVE` (409).
9. **Referential registration gates** — supplier/equipment registration status, e.g. `ERR_SUPPLIER_NOT_REGISTERED` or `ERR_EQUIPMENT_NOT_REGISTERED` (409).
10. **Temporal overlap** — occasion and equipment-allocation overlap checks, e.g. `ERR_OCCASION_OVERLAP` or `ERR_EQUIPMENT_ALLOCATION_CONFLICT` (409).
11. **Fiscal caps** — prize allowance and charitable-minimum gates, e.g. `ERR_PRIZE_LIMIT_EXCEEDED` or `ERR_CHARITABLE_MINIMUM_NOT_MET` (409).
12. **Remaining business constraints** — reinstatement violation gate `ERR_OUTSTANDING_VIOLATIONS` and duplicate-serial gate `ERR_DUPLICATE_SERIAL` (409).

A lower-numbered check that fails masks every higher-numbered one, so a request that both lacks permission and targets a missing resource is rejected as `ERR_FORBIDDEN`, not `ERR_NOT_FOUND`.

## 3. Business Logic & Workflows

### 3.1. Organization Eligibility

A `Regulator` registers a nonprofit by supplying its `legal_name`, its `ein` (Employer Identification Number), its `nonprofit_type`, its `incorporation_date`, its `state_code` (a two-letter state code), and optionally whether it is in `good_standing` with the state registry — a boolean that defaults to `true` when omitted. The `nonprofit_type` is one of `501C3`, `501C4`, `501C8`, `501C10`, `501C19`, or `OTHER`.

Two figures on an organization are always computed against the logical clock rather than stored from input. The first, `months_active`, is the number of whole calendar months elapsed from `incorporation_date` to the current clock: compute twelve times the difference between the clock's year and the incorporation year, add the difference between the clock's month and the incorporation month, and then subtract one further month if the clock's day-of-month is earlier than the incorporation day-of-month. The result is clamped so it is never negative — a future incorporation date yields zero, not a negative count. The second, `eligibility_status`, is `ELIGIBLE` only when all three of the following hold, and is `INELIGIBLE` otherwise: the `nonprofit_type` is one of the qualifying types `501C3`, `501C4`, `501C8`, `501C10`, or `501C19` (i.e. any type other than `OTHER`); `months_active` is at least 36 (three full calendar years); and `good_standing` is `true`. Both figures are recomputed whenever an organization is fetched and whenever eligibility is evaluated as a gate on license approval.

### 3.2. The License Lifecycle

An `OrgOfficer` applies for a license on behalf of its organization by supplying the `organization_id`, the `license_type` (`BINGO`, `RAFFLE`, or `COMBINED`), a `contact_email`, and a `venue_name`. A newly created license begins in `DRAFT` status. At creation its `annual_prize_limit_cents` is fixed from the license type — 1,000,000 cents for `BINGO`, 2,000,000 cents for `RAFFLE`, and 3,000,000 cents for `COMBINED` — and its prize ledgers `prize_committed_cents` and `prize_settled_cents` both start at zero.

The license moves through its lifecycle by transition. Submitting a license for review advances it from `DRAFT` to `SUBMITTED`; this is permitted only while the license is in `DRAFT`, otherwise the request is rejected with `ERR_INVALID_STATE`. A `Regulator` then approves a submitted license, advancing it from `SUBMITTED` to `ACTIVE`. Approval requires the license to be in `SUBMITTED` (else `ERR_INVALID_STATE`) and requires the owning organization's `eligibility_status` to be `ELIGIBLE` at the moment of approval (else `ERR_ORG_NOT_ELIGIBLE`). On approval the system sets `effective_date` to the current clock date and sets `expiration_date` to exactly twelve months after `effective_date`; the prize buckets are initialized to reflect any existing occasions, which is zero for a fresh license.

A `Regulator` may suspend an `ACTIVE` license, advancing it from `ACTIVE` to `SUSPENDED` (permitted only from `ACTIVE`, else `ERR_INVALID_STATE`). Suspension triggers the cancellation cascade of §2.6: every `SCHEDULED` occasion on the license is cancelled, releasing its prize commitment and releasing its active equipment allocations. A `Regulator` may reinstate a suspended license, advancing it from `SUSPENDED` back to `ACTIVE`; this requires the license to be `SUSPENDED` (else `ERR_INVALID_STATE`) and requires `total_violation_points_active` to be below the suspension threshold of 10 points (else `ERR_OUTSTANDING_VIOLATIONS`). Separately, the license may auto-transition from `ACTIVE` to `SUSPENDED` when violation points reach the threshold (§3.8), and from `ACTIVE` to `EXPIRED` when the clock advances past `expiration_date` (§2.5); both automatic transitions apply the same cancellation cascade. A license may return from `EXPIRED` to `ACTIVE` only through renewal approval (§3.9). `EXPIRED` is the terminal state of the license lifecycle.

The `contact_email` and `venue_name` are the only mutable license fields. An `OrgOfficer` may update them, but the update must carry `expected_license_version` matching the license's current `version`, or it is rejected with `ERR_STALE_VERSION` (§2.7); a successful update increments the license `version`.

### 3.3. Scheduling Occasions and Reserving Prizes

Within an active license an `OrgOfficer` schedules a gaming occasion by supplying the `license_id`, the `occasion_type` (`BINGO` or `RAFFLE`), a `scheduled_start` and `scheduled_end`, a `venue_name`, and three projections: `planned_gross_cents`, `planned_prize_pool_cents`, and `planned_expenses_cents`. The `scheduled_end` must be strictly after `scheduled_start`; otherwise the request is rejected with `ERR_OCCASION_TIME_INVALID`. A newly scheduled occasion begins in `SCHEDULED` status.

Scheduling an occasion reserves prize allowance: at creation, `planned_prize_pool_cents` is added to the license's `prize_committed_cents`. An occasion's scheduled window is treated as a half-open interval that includes its start and excludes its end, so two occasions on the same license that merely touch end-to-start do not collide. A new occasion whose window overlaps that of any non-`CANCELLED` occasion on the same license is rejected with `ERR_OCCASION_OVERLAP`.

An `OrgOfficer` may cancel a `SCHEDULED` occasion, advancing it from `SCHEDULED` to `CANCELLED` (permitted only from `SCHEDULED`, else `ERR_INVALID_STATE`). Cancellation releases the reservation by subtracting `planned_prize_pool_cents` from the license's `prize_committed_cents`, and it cascades to every `EquipmentAllocation` for that occasion still in `ACTIVE` status, driving each to `RELEASED`. This is the same cancellation used by the license suspend/expire cascade. Both `REPORTED` and `CANCELLED` are terminal states for an occasion.

### 3.4. Holding and Reporting an Occasion

An `OrgOfficer` marks a scheduled occasion as held once it has taken place, advancing it from `SCHEDULED` to `HELD`. This is permitted only when the occasion is `SCHEDULED` (else `ERR_INVALID_STATE`) and only while the owning license is `ACTIVE` (else `ERR_LICENSE_NOT_ACTIVE`). Holding computes a **provisional** `net_proceeds_cents` from the planned projections: `planned_gross_cents` minus `planned_prize_pool_cents` minus `planned_expenses_cents`.

Reporting closes the occasion out. The `OrgOfficer` supplies the actuals `gross_receipts_cents`, `prizes_paid_cents`, and `expenses_cents`, advancing the occasion from `HELD` to `REPORTED`. Reporting is permitted only when the occasion is `HELD` (else `ERR_INVALID_STATE`), only while the license is `ACTIVE` (else `ERR_LICENSE_NOT_ACTIVE`), and only when the reported `prizes_paid_cents` does not exceed the occasion's prize allowance (else `ERR_PRIZE_LIMIT_EXCEEDED`, described below). On success the actuals are stored, and `net_proceeds_cents` is recomputed as the **final** variant: `gross_receipts_cents` minus `prizes_paid_cents` minus `expenses_cents`. The same `net_proceeds_cents` field is thus written by two different arithmetic variants over the life of one occasion — the planned projection at hold time and the actual figures at report time — and the two typically diverge.

Reporting also transfers prize consumption on the license: `planned_prize_pool_cents` is subtracted from `prize_committed_cents` (retiring the forward reservation) and `prizes_paid_cents` is added to `prize_settled_cents` (recording the actual payout). Finally, if the current clock is later than `scheduled_end` plus a grace period of 7 days, the report is late: the system auto-creates a `Violation` of type `LATE_REPORT` with `source` `AUTO`, which recomputes the license's active violation points and may in turn auto-suspend the license (§3.8).

The occasion's prize allowance at report time is the smaller of two limits. First, a per-occasion cap selected by `occasion_type` — 800,000 cents for a `BINGO` occasion, 1,500,000 cents for a `RAFFLE` occasion. Second, the annual allowance still available to this specific occasion, computed as the license's `annual_prize_limit_cents`, minus its `prize_settled_cents`, minus the committed prizes of all *other* occasions (that is, the license's current `prize_committed_cents` minus this occasion's own `planned_prize_pool_cents`). The allowance is the minimum of those two figures. The boundary is inclusive: `prizes_paid_cents` equal to the allowance is accepted, and one cent above it is rejected with `ERR_PRIZE_LIMIT_EXCEEDED`.

### 3.5. The License Prize Ledgers

Each license carries two complementary views of how much of its annual prize allowance it has consumed, plus a remaining figure derived from both. The forward-looking `prize_committed_cents` is the sum of `planned_prize_pool_cents` over all occasions of the license whose status is `SCHEDULED` or `HELD`. The realized `prize_settled_cents` is the sum of `prizes_paid_cents` over all occasions whose status is `REPORTED`. The `prize_allowance_remaining_cents` is `annual_prize_limit_cents` minus `prize_committed_cents` minus `prize_settled_cents`.

These buckets move only through the three occasion transitions already described: scheduling an occasion adds its `planned_prize_pool_cents` to the committed bucket; cancelling an occasion subtracts the same amount from the committed bucket; and reporting an occasion subtracts `planned_prize_pool_cents` from the committed bucket while adding `prizes_paid_cents` to the settled bucket. Every such adjustment is a mutation of the license and refreshes its `updated_at` and `version`.

### 3.6. Suppliers, Equipment, and Allocations

A `Regulator` creates a supplier registration by supplying its `business_name` and `state_code`; the supplier begins in `PENDING` status. A `Regulator` registers a pending supplier, advancing it from `PENDING` to `REGISTERED` (permitted only from `PENDING`, else `ERR_INVALID_STATE`).

A `Supplier` registers an equipment item by supplying its `supplier_id`, an `equipment_type` (`BINGO_BLOWER`, `FLASHBOARD`, `RAFFLE_DRUM`, or `CARD_MINDER`), and a `serial_number`. Equipment may be registered only under a supplier whose status is `REGISTERED`; otherwise the request is rejected with `ERR_SUPPLIER_NOT_REGISTERED`. A `serial_number` must be unique among that supplier's equipment; a duplicate is rejected with `ERR_DUPLICATE_SERIAL`. A newly registered item begins in `REGISTERED` status. A `Supplier` may retire one of its items, advancing it from `REGISTERED` to `RETIRED` (permitted only from `REGISTERED`, else `ERR_INVALID_STATE`); `RETIRED` is terminal.

An `OrgOfficer` allocates a registered equipment item to one of its own occasions by supplying the `equipment_id`, the `occasion_id`, a `start_date`, and an `end_date`. The `end_date` must not be before `start_date`; otherwise `ERR_ALLOCATION_DATE_INVALID`. Allocation requires the owning license to be `ACTIVE` (else `ERR_LICENSE_NOT_ACTIVE`) and requires the target equipment to be `REGISTERED` (else `ERR_EQUIPMENT_NOT_REGISTERED`). A newly created allocation begins in `ACTIVE` status. Allocation windows are treated as closed intervals that include both `start_date` and `end_date`, and a mandatory buffer of one day must separate two allocations of the same equipment: the gap between them must be strictly greater than one day, so a gap of exactly one day still conflicts. A new allocation that violates this buffer against any `ACTIVE` allocation on the same equipment is rejected with `ERR_EQUIPMENT_ALLOCATION_CONFLICT`. An `OrgOfficer` may release an active allocation, advancing it from `ACTIVE` to `RELEASED` (permitted only from `ACTIVE`, else `ERR_INVALID_STATE`); this same release is what the occasion-cancellation cascade performs automatically. `RELEASED` is terminal.

### 3.7. Financial Reporting and Proceeds Distribution

An `OrgOfficer` opens a periodic financial report by supplying the `license_id`, a `period_start` and `period_end`, and the `charitable_use_cents` the organization claims it applied to charitable purpose during the period. The `period_end` must be strictly after `period_start`; otherwise `ERR_REPORT_PERIOD_INVALID`. A new report begins in `DRAFT` status.

At creation the report aggregates over every `REPORTED` occasion of the license whose `scheduled_start` falls within `[period_start, period_end]` inclusive. From that occasion set it computes `total_gross_cents` (the sum of `gross_receipts_cents`), `total_prizes_cents` (the sum of `prizes_paid_cents`), and `total_expenses_cents` (the sum of `expenses_cents`). The report's `net_proceeds_cents` is `total_gross_cents` minus `total_prizes_cents` minus `total_expenses_cents`.

Two allowances are then carved out of net proceeds, and the rounding order is pinned. First round each component to whole cents *before* subtracting: `admin_allowance_cents` is 15 percent of `net_proceeds_cents` rounded half up, and `regulatory_fee_cents` is 5 percent of `net_proceeds_cents` rounded half up. The `charitable_minimum_cents` is then `net_proceeds_cents` minus `admin_allowance_cents` minus `regulatory_fee_cents`. Because the two components are rounded first and only then subtracted, this figure can differ by a cent from naively taking 80 percent of net proceeds. The `charitable_use_ratio` is `charitable_use_cents` divided by `net_proceeds_cents`, rounded to four decimal places, but is exactly 0 whenever `net_proceeds_cents` is zero or negative.

The report then moves through an audit cycle. Submitting a draft advances it from `DRAFT` to `SUBMITTED`, permitted only when the report is `DRAFT` (else `ERR_INVALID_STATE`) and only when the reported `charitable_use_cents` is at least the computed `charitable_minimum_cents` (else `ERR_CHARITABLE_MINIMUM_NOT_MET`). A `Regulator` reviewing a submitted report may accept it, advancing it from `SUBMITTED` to `ACCEPTED` (permitted only from `SUBMITTED`, else `ERR_INVALID_STATE`); `ACCEPTED` is terminal. Alternatively a `Regulator` may reject a submitted report, advancing it from `SUBMITTED` to `REJECTED` (permitted only from `SUBMITTED`, else `ERR_INVALID_STATE`). An `OrgOfficer` may then revise a rejected report, returning it from `REJECTED` to `DRAFT` (permitted only from `REJECTED`, else `ERR_INVALID_STATE`) so it can be amended and re-submitted, forming a cyclic revision loop.

### 3.8. Violations and Suspension

A `Regulator` records a violation against a license by supplying the `license_id` and a `violation_type`, one of `LATE_REPORT`, `PRIZE_LIMIT_EXCEEDED`, `UNREGISTERED_EQUIPMENT`, or `PROCEEDS_MISUSE`. A manually recorded violation has `source` `MANUAL`; late-report violations raised automatically at report time have `source` `AUTO`. Every violation begins in `OPEN` status, and its `points` are assigned by type: `LATE_REPORT` carries 3 points, `PRIZE_LIMIT_EXCEEDED` 6 points, `UNREGISTERED_EQUIPMENT` 5 points, and `PROCEEDS_MISUSE` 10 points.

Whenever a violation is created or waived, the license's `total_violation_points_active` is recomputed as the sum of `points` over all of that license's violations still in `OPEN` status. When that total reaches or exceeds the suspension threshold of 10 points while the license is `ACTIVE`, the license automatically transitions from `ACTIVE` to `SUSPENDED`, applying the standard cancellation cascade over its `SCHEDULED` occasions and their active allocations. This auto-suspension is triggered both by a manually recorded violation and by an auto-raised `LATE_REPORT` violation.

A `Regulator` may waive an open violation, advancing it from `OPEN` to `WAIVED` (permitted only from `OPEN`, else `ERR_INVALID_STATE`). Waiving subtracts the violation's `points` from the license's active total, so that a violation created and later waived nets to zero effect on the total. `WAIVED` is terminal. Note that clearing points below the threshold does not itself reinstate a suspended license; reinstatement is a separate regulator action gated on the active total being below 10 (§3.2).

### 3.9. Renewals

An `OrgOfficer` requests a renewal for a license by supplying the `license_id`, optionally a `requested_term_months` (which defaults to 12 when omitted), and `expected_license_version`. The renewal-create operation is under optimistic concurrency: `expected_license_version` must equal the license's current `version` at the moment of the request, or the create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from acting on a stale view of a license whose version has since advanced. A successful create advances the license's `version` by one. A new renewal begins in `REQUESTED` status, and it legitimately supersedes any prior renewal for the same license that is still `REQUESTED`, driving that earlier renewal to `SUPERSEDED`.

A `Regulator` approves a requested renewal, advancing it from `REQUESTED` to `APPROVED` (permitted only from `REQUESTED`, else `ERR_INVALID_STATE`). Approval extends the license's `expiration_date` to the later of its current `expiration_date` and the current clock date, plus `requested_term_months`; and if the license is currently `EXPIRED`, approval reactivates it, transitioning it from `EXPIRED` back to `ACTIVE`. A `Regulator` may instead deny a requested renewal, advancing it from `REQUESTED` to `DENIED` (permitted only from `REQUESTED`, else `ERR_INVALID_STATE`). The states `APPROVED`, `DENIED`, and `SUPERSEDED` are all terminal for a renewal.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify or transition an existing resource, and all retrieval operations, return `200 OK`. The clock-setting capability returns `200 OK` with an empty data object.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/organizations` | Register a nonprofit organization | Regulator |
| GET | `/organizations/{id}` | Fetch an organization (recomputes months active and eligibility) | Regulator, OrgOfficer |
| GET | `/organizations/{id}/licenses` | List licenses belonging to an organization | Regulator, OrgOfficer |
| POST | `/licenses` | Create a DRAFT license application | OrgOfficer |
| GET | `/licenses/{id}` | Fetch a license with computed prize buckets and violation points | Regulator, OrgOfficer |
| GET | `/licenses/{id}/occasions` | List occasions for a license | Regulator, OrgOfficer |
| GET | `/licenses/{id}/financial-reports` | List financial reports for a license | Regulator, OrgOfficer |
| GET | `/licenses/{id}/violations` | List violations for a license | Regulator, OrgOfficer |
| GET | `/licenses/{id}/renewals` | List renewals for a license | Regulator, OrgOfficer |
| PATCH | `/licenses/{id}` | Update mutable license fields under optimistic concurrency | OrgOfficer |
| POST | `/licenses/{id}/submit` | Submit a DRAFT license for review | OrgOfficer |
| POST | `/licenses/{id}/approve` | Approve a SUBMITTED license | Regulator |
| POST | `/licenses/{id}/suspend` | Suspend an ACTIVE license | Regulator |
| POST | `/licenses/{id}/reinstate` | Reinstate a SUSPENDED license | Regulator |
| POST | `/occasions` | Schedule a gaming occasion under a license | OrgOfficer |
| GET | `/occasions/{id}` | Fetch an occasion | Regulator, OrgOfficer |
| GET | `/occasions/{id}/allocations` | List equipment allocations for an occasion | Regulator, OrgOfficer, Supplier |
| POST | `/occasions/{id}/hold` | Mark a SCHEDULED occasion as HELD | OrgOfficer |
| POST | `/occasions/{id}/report` | File the report for a HELD occasion | OrgOfficer |
| POST | `/occasions/{id}/cancel` | Cancel a SCHEDULED occasion | OrgOfficer |
| POST | `/suppliers` | Create a supplier registration | Regulator |
| GET | `/suppliers/{id}` | Fetch a supplier | Regulator, Supplier |
| GET | `/suppliers/{id}/equipment` | List equipment for a supplier | Regulator, Supplier |
| POST | `/suppliers/{id}/register` | Register a PENDING supplier | Regulator |
| POST | `/equipment` | Register an equipment item | Supplier |
| GET | `/equipment/{id}` | Fetch an equipment item | Regulator, Supplier, OrgOfficer |
| GET | `/equipment/{id}/allocations` | List allocations for an equipment item | Regulator, Supplier, OrgOfficer |
| POST | `/equipment/{id}/retire` | Retire a REGISTERED equipment item | Supplier |
| POST | `/equipment-allocations` | Allocate equipment to an occasion | OrgOfficer |
| GET | `/equipment-allocations/{id}` | Fetch an equipment allocation | Regulator, OrgOfficer, Supplier |
| POST | `/equipment-allocations/{id}/release` | Release an ACTIVE allocation | OrgOfficer |
| POST | `/financial-reports` | Create a DRAFT financial report | OrgOfficer |
| GET | `/financial-reports/{id}` | Fetch a financial report with computed aggregates | Regulator, OrgOfficer |
| POST | `/financial-reports/{id}/submit` | Submit a DRAFT financial report | OrgOfficer |
| POST | `/financial-reports/{id}/accept` | Accept a SUBMITTED report | Regulator |
| POST | `/financial-reports/{id}/reject` | Reject a SUBMITTED report | Regulator |
| POST | `/financial-reports/{id}/revise` | Return a REJECTED report to DRAFT | OrgOfficer |
| POST | `/violations` | Record a violation against a license | Regulator |
| GET | `/violations/{id}` | Fetch a violation | Regulator, OrgOfficer |
| POST | `/violations/{id}/waive` | Waive an OPEN violation | Regulator |
| POST | `/renewals` | Request a renewal under optimistic concurrency | OrgOfficer |
| GET | `/renewals/{id}` | Fetch a renewal | Regulator, OrgOfficer |
| POST | `/renewals/{id}/approve` | Approve a REQUESTED renewal | Regulator |
| POST | `/renewals/{id}/deny` | Deny a REQUESTED renewal | Regulator |
| POST | `/_clock/set_current_utc` | Set the logical clock | Regulator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 422 |
| `ERR_OCCASION_TIME_INVALID` | 422 |
| `ERR_REPORT_PERIOD_INVALID` | 422 |
| `ERR_ALLOCATION_DATE_INVALID` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ORG_NOT_ELIGIBLE` | 409 |
| `ERR_LICENSE_NOT_ACTIVE` | 409 |
| `ERR_SUPPLIER_NOT_REGISTERED` | 409 |
| `ERR_EQUIPMENT_NOT_REGISTERED` | 409 |
| `ERR_OCCASION_OVERLAP` | 409 |
| `ERR_EQUIPMENT_ALLOCATION_CONFLICT` | 409 |
| `ERR_PRIZE_LIMIT_EXCEEDED` | 409 |
| `ERR_CHARITABLE_MINIMUM_NOT_MET` | 409 |
| `ERR_OUTSTANDING_VIOLATIONS` | 409 |
| `ERR_DUPLICATE_SERIAL` | 409 |
