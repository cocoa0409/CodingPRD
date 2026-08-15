# Campus Parking & Transportation Demand Management API — Product Requirements Document

## 1. Introduction

Campus parking operations sit at the intersection of real-estate scarcity, academic-calendar cadence, and constituent equity. Every fall, thousands of students, staff, and faculty arrive with vehicles they need to park on a fixed inventory of stalls; meanwhile events, construction projects, and sustainability mandates constantly shrink or reshape that inventory. A modern campus parking office cannot run on paper permits and manual waitlists — it needs a system that treats every stall as a managed allocation, every citation as a defensible financial instrument, and every shuttle route as an operating commitment backed by permit and citation revenue.

This document specifies the API for the Campus Parking & Transportation Demand Management platform. The platform serves four constituencies: the commuter trying to buy a permit or pay a fine, the parking administrator balancing allocations across lots and coordinating event closures, the enforcement officer issuing citations from license-plate-recognition scans, and the appeals officer adjudicating those citations under segregation of duties. Running beneath all of these workflows is a transportation fund ledger that converts permit and citation revenue into the operating budget for the campus shuttle system, plus an alternative-commute incentive program that rewards patrons who leave their cars at home.

The API is mounted under `/parking` and is organized around eleven peer resources: patrons, parking lots, lot allocations (permit classes sold on a lot), waitlist entries, virtual permits, citations, lot closures, shuttle routes, incentive accounts, transportation funds, and a logical clock used to drive deterministic time-dependent behavior.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID` and `X-User-Role`. If either header is missing, or if `X-User-Role` is not one of the declared roles, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 401). If the role is recognized but is not in the endpoint's authorized role list, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The four declared roles are `Commuter`, `ParkingAdmin`, `EnforcementOfficer`, and `AppealsOfficer`.

- **`Commuter`** — a campus member (student, staff, or faculty) buying permits, joining waitlists, paying or appealing citations, and participating in the incentive program. When `X-User-Role` is `Commuter`, `X-User-ID` is the `id` of the acting `Patron`; ownership checks on any resource that references a `Patron` compare the resource's foreign-key field to `X-User-ID`. A Commuter acting on a resource whose owning `patron_id` does not match the supplied `X-User-ID` is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).
- **`ParkingAdmin`** — a parking & transportation services operator. When `X-User-Role` is `ParkingAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- **`EnforcementOfficer`** — an LPR enforcement officer issuing citations. When `X-User-Role` is `EnforcementOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it on the issued citation as `issued_by_officer_id` but does not compare it to any entity's `id` for ownership.
- **`AppealsOfficer`** — a citation appeals adjudicator. When `X-User-Role` is `AppealsOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it on the decided citation as `appeal_decided_by`. Segregation of duties requires that an `AppealsOfficer` may not decide an appeal on a citation whose `issued_by_officer_id` equals their `X-User-ID`; violations are rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

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

List endpoints accept two query parameters: `limit` (default `10`, minimum `1`, maximum `100`) and `offset` (default `0`). The `meta` block of every list response includes `limit`, `offset`, `total_count`, and `has_more`. Default sort order is `created_at` ascending (oldest first) on every list endpoint.

### 2.4. Common Resource Properties

All eleven persisted entities carry the standard four system fields unless explicitly noted:

- `id` — a server-minted UUID with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, recorded at creation and never mutated.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation.
- `version` — an integer starting at `1` on creation and incremented by exactly `1` on every mutation of that entity.

### 2.5. The Logical Clock and Time-Driven Behavior

The server maintains a logical clock, distinct from wall-clock time. Before any clock-set call, the logical clock is exactly `2026-08-01T00:00:00Z`. The server MUST NOT fall back to wall-clock time at any point. Advancing the logical clock (via the admin clock-set capability) sweeps `ACTIVE` permits whose `valid_to` is strictly before the new logical date and flips them to `EXPIRED`, freeing allocation seats and triggering waitlist offers on those freed seats. Waitlist offer expiry is evaluated lazily — at claim time and at the start of an offer-extension round — not by the clock sweep itself. All system-recorded timestamps (`issued_at`, `waiting_since`, `offered_at`, `offer_expires_at`) come from the logical clock, never from wall-clock.

### 2.6. Optimistic Concurrency Control on Lot Allocations

Three write endpoints guard against stale views of a `LotAllocation` using optimistic concurrency control. Each requires a non-optional `expected_allocation_version` field carrying the client's last-observed `version` of the target allocation:

- Permit purchase (`POST /parking/permits`)
- Waitlist offer claim (`POST /parking/waitlist-entries/{entryId}/claim`)
- Allocation quota adjustment (`PATCH /parking/allocations/{allocationId}`)

If `expected_allocation_version` does not match the allocation's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). The canonical read before any such write is `GET /parking/allocations/{allocationId}`, which returns the allocation's current `version`. Endpoints not listed above do not accept a version field.

### 2.7. Precision, Rounding, and Currency

All monetary amounts are integer cents. Every division or percentage evaluation rounds half-up to the nearest integer cent — never banker's rounding, never truncation. Dates are ISO 8601 calendar dates (`YYYY-MM-DD`); datetimes are ISO 8601 UTC. Permit and closure windows are inclusive/exclusive as specified per rule — closure windows use half-open `[starts_at, ends_at)` semantics where adjacency (one closure's `ends_at` equal to another's `starts_at`) does NOT count as overlap, while permit validity windows use inclusive `[valid_from, valid_to]` semantics where touching dates DO count as overlap.

### 2.8. Validation Ordering

Every write endpoint evaluates checks in a fixed priority order. A failure at an earlier tier masks later checks (the earlier error is the one returned):

1. **Auth context** — `X-User-ID` and `X-User-Role` present and role recognized.
2. **Role authorization** — role is in the endpoint's authorized list.
3. **Ownership** — a `Commuter`'s `X-User-ID` matches the target resource's `patron_id`.
4. **Existence** — path ids and body foreign keys resolve, validated left-to-right (patron, lot, allocation, entry, permit, citation, closure, route, incentive account, fund).
5. **OCC state** — `expected_allocation_version` matches the allocation's current `version` on the three OCC-guarded endpoints.
6. **Request shape** — required fields present, enums in domain, dates parseable, interval and conditional-field rules satisfied.
7. **Target resource state** — the resource is in a state that permits the operation (allocation `OPEN` for purchase, `WAITLISTING` for join, etc.).
8. **Plate resolution** — citation `plate_number` resolves to an existing permit.
9. **Temporal conflicts** — closure overlap, plate double-booking, fleet window buffer, offer expiry, `valid_from` within term.
10. **Eligibility & duties** — role/residency eligibility, commute-mode eligibility, segregation of duties.
11. **Uniqueness** — duplicate allocation code, already-waitlisted, appeal-already-exists, account-already-exists.
12. **Capacity & fiscal** — patron standing, credit balance, displacement capacity, route funding and seat coverage, redemption points. Fiscal checks always run after state and temporal checks.

Within route activation, the seat-coverage check is evaluated before the funding check. Within permit purchase or claim, the patron-standing check is evaluated before the credit check.

## 3. Business Logic & Workflows

### 3.1. Patron Registration and Standing

A `ParkingAdmin` registers a campus member by submitting `full_name`, `campus_role`, `residency`, and `primary_commute_mode`. `campus_role` must be one of `STUDENT`, `STAFF`, or `FACULTY`; `residency` must be `ON_CAMPUS` or `OFF_CAMPUS`; `primary_commute_mode` must be one of `DRIVE_ALONE`, `CARPOOL`, `TRANSIT`, `BIKE`, or `WALK`. At creation the patron's `outstanding_balance_cents` is `0` and `standing` is `GOOD_STANDING`.

A patron's `outstanding_balance_cents` is the sum of `fine_amount_cents` across all of that patron's citations whose status is exactly `ISSUED` — citations that are `UNDER_APPEAL`, `PAID`, or `VOIDED` are excluded. `standing` flips to `BLOCKED` whenever `outstanding_balance_cents` reaches or exceeds `10000` cents, and returns to `GOOD_STANDING` when the balance falls back below that threshold. The balance is recomputed on every citation issuance, payment, and appeal decision. When standing flips to `BLOCKED`, every `ACTIVE` permit the patron holds flips to `SUSPENDED`; when standing flips back to `GOOD_STANDING`, those `SUSPENDED` permits return to `ACTIVE`. A `SUSPENDED` permit still occupies its allocation seat — `allocated_count` does not change on suspension — but it is not valid for parking.

### 3.2. Lots, Allocations, and the Capacity Ledger

A `ParkingAdmin` creates a parking lot with `lot_code` (a unique human code such as `LOT_NORTH_1`), `name`, `zone` (one of `CORE`, `PERIMETER`, `REMOTE`), and `capacity_total` (at least `1`). At creation the lot's `posture` is `OPEN` and `reserved_spaces_total` is `0`. Posture may later flip to `CLOSED_EVENT` or `CLOSED_CONSTRUCTION` via closure activation and is restored to `OPEN` by lifting.

Each lot sells permits through one or more `LotAllocation` records, each defining a `permit_code` (e.g. `RESIDENT_STUDENT`), the `eligible_roles` (a non-empty subset of `STUDENT`, `STAFF`, `FACULTY`), the `residency_rule` (one of `ANY`, `ON_CAMPUS_ONLY`, `OFF_CAMPUS_ONLY`), the `base_fee_cents` (non-negative), the `proration_policy` (one of `PRORATED_WEEKLY`, `FLAT_HALF_TERM`), the term window `term_start` to `term_end` (both ISO dates, `term_end` strictly after `term_start`), and the `quota` (maximum seats, at least `0`). The pair (`lot_id`, `permit_code`) is unique — creating a second allocation with the same pair is rejected with `ERR_DUPLICATE_ALLOCATION_CODE` (HTTP 409).

An allocation tracks two counters: `allocated_count` (permits on the allocation with status `ACTIVE` or `SUSPENDED`) and `offers_outstanding` (waitlist entries on the allocation with status `OFFERED`). Both start at `0`. The allocation's `status` is `OPEN` when created with `quota > 0`, else `WAITLISTING`. Thereafter the status is system-managed: after any mutation that leaves `allocated_count + offers_outstanding` greater than or equal to `quota`, the allocation flips to `WAITLISTING`; after any mutation that leaves the sum strictly below `quota`, it flips back to `OPEN`. New permit purchases against a `WAITLISTING` allocation are rejected with `ERR_ALLOCATION_NOT_OPEN` (HTTP 409); waitlist joins against an `OPEN` allocation are rejected with `ERR_ALLOCATION_NOT_WAITLISTING` (HTTP 409).

The lot's `reserved_spaces_total` is the sum of `reserved_spaces` across closures on the lot with status `SCHEDULED` or `ACTIVE`. The lot's `available_capacity` is `capacity_total` minus `reserved_spaces_total` minus the sum of `allocated_count` over all allocations on the lot.

### 3.3. Permit Purchase and Fee Proration

A `Commuter` (or `ParkingAdmin` on behalf of a patron) purchases a permit by submitting `patron_id`, `allocation_id`, `plate_number`, an optional `valid_from`, the OCC field `expected_allocation_version`, and optionally `apply_credit_cents`. The allocation must be `OPEN`. The patron's `campus_role` must appear in the allocation's `eligible_roles` and the patron's `residency` must satisfy the allocation's `residency_rule` (`ANY` accepts both residencies; `ON_CAMPUS_ONLY` requires `ON_CAMPUS`; `OFF_CAMPUS_ONLY` requires `OFF_CAMPUS`) — violations are rejected with `ERR_PATRON_INELIGIBLE` (HTTP 403). The patron's `standing` must be `GOOD_STANDING`; a `BLOCKED` patron is rejected with `ERR_PATRON_BLOCKED` (HTTP 402).

The same `plate_number` may not be covered by more than one permit with status `ACTIVE` or `SUSPENDED` over any overlapping inclusive `[valid_from, valid_to]` window — a touching date counts as overlap. Violations are rejected with `ERR_DUPLICATE_ACTIVE_PERMIT` (HTTP 409).

If supplied, `valid_from` must lie within `[term_start, term_end]`; otherwise it is rejected with `ERR_INVALID_REQUEST` (HTTP 400). When `valid_from` is omitted it defaults to the later of the current logical date and the allocation's `term_start`. `valid_to` is always the allocation's `term_end` (inclusive) and is set by the system.

#### 3.3.1. Fee Calculation (PRORATED_WEEKLY variant)

When the allocation's `proration_policy` is `PRORATED_WEEKLY`, the prorated base fee scales with the number of whole weeks remaining in the term, and the weekly rate is rounded before multiplication. Concretely:

1. Compute `total_days` as the number of calendar days from `term_start` through `term_end` inclusive (that is, the difference in days plus one).
2. Compute `term_weeks` as `total_days` divided by seven, rounded up to the nearest whole number.
3. Compute `remaining_days` as the number of calendar days from `valid_from` through `term_end` inclusive (the `valid_from` day itself is counted).
4. Compute `weeks_remaining` as `remaining_days` divided by seven, rounded up to the nearest whole number.
5. Compute `weekly_rate` as `base_fee_cents` divided by `term_weeks`, rounded half-up to the nearest integer cent. **This rounding happens before multiplication.**
6. `fee_base_cents` is `weekly_rate` multiplied by `weeks_remaining` — an exact integer multiply.

#### 3.3.2. Fee Calculation (FLAT_HALF_TERM variant)

When the allocation's `proration_policy` is `FLAT_HALF_TERM`, the fee is the full list price up to the midterm date and half price after it:

1. Compute `total_days` as above.
2. Compute `midterm_date` as `term_start` plus the floor of `total_days / 2` days.
3. If `valid_from` is on or before `midterm_date`, `fee_base_cents` is `base_fee_cents` in full. Otherwise `fee_base_cents` is `base_fee_cents` multiplied by `0.5`, rounded half-up to the nearest integer cent.

Identical inputs under the two policies yield different fees — the variants are not interchangeable.

#### 3.3.3. Surcharge, Credit, and Final Paid Amount

Both variants share a common tail, evaluated in pinned order after the proration:

1. `surcharge_cents` is `fee_base_cents` multiplied by `0.05`, rounded half-up to the nearest integer cent. The surcharge is computed from the already-rounded `fee_base_cents`.
2. `fee_total_cents` is `fee_base_cents` plus `surcharge_cents`.
3. If `apply_credit_cents` is supplied, `credit_applied_cents` is the smaller of `apply_credit_cents` and `fee_total_cents`; otherwise `credit_applied_cents` is `0`. The supplied `apply_credit_cents` must not exceed the patron's incentive `credit_balance_cents` — violations are rejected with `ERR_INSUFFICIENT_CREDIT` (HTTP 422), and the same error applies if the patron has no incentive account at all.
4. `fee_paid_cents` is `fee_total_cents` minus `credit_applied_cents`. This is the cash amount recognized as permit revenue.

On successful purchase the permit is created `ACTIVE`, the allocation's `allocated_count` increments by `1`, the allocation's `status` is re-evaluated, the allocation's `version` increments, the transportation fund's `permit_revenue_cents` increases by `fee_paid_cents`, and any applied incentive credit is debited from the patron's incentive account.

### 3.4. Waitlist Joining, Offers, Claims, and Withdrawal

When an allocation is `WAITLISTING`, a `Commuter` (or `ParkingAdmin` on behalf of a patron) joins the queue by submitting `patron_id` and `allocation_id`. A patron may hold at most one entry with status `WAITING` or `OFFERED` per allocation — duplicates are rejected with `ERR_ALREADY_WAITLISTED` (HTTP 409). The eligibility rules (role and residency) apply at join time as at purchase. The new entry is created with status `WAITING`, `waiting_since` set to the current logical time, `decline_count` of `0`, and `requeue_count` of `0`.

#### 3.4.1. Offer Selection and the Priority Score

Offers are extended in two situations: explicitly when a `ParkingAdmin` runs an offer round on an allocation, and automatically when a permit cancellation or expiry frees seats. In both cases the same selector runs.

First, any `OFFERED` entries whose `offer_expires_at` is strictly before the current logical time are swept: each transitions `OFFERED → EXPIRED`, decrements `offers_outstanding` by `1`, and immediately requeues per the requeue policy below. Then, if the free-seat count (computed as `quota` minus `allocated_count` minus `offers_outstanding`) is greater than zero, the system ranks all `WAITING` entries on the allocation by `waitlist_priority_score` descending, tie-broken by `waiting_since` ascending (earliest waiter first), and promotes at most that many entries to `OFFERED`.

The priority score is computed as follows. `wait_days` is the whole number of days between the entry's `waiting_since` and the current logical time (fractional days are discarded). The score is the role weight (`FACULTY` contributes `100`, `STAFF` contributes `80`, `STUDENT` contributes `60`), plus two points per `wait_day` capped at thirty days of credit (so the wait-day term contributes at most `60` points), plus a residency bonus of `10` if the patron's `residency` is `ON_CAMPUS`, minus a decline penalty of `15` multiplied by the entry's `decline_count`.

Each promoted entry transitions `WAITING → OFFERED`, records `offered_at` as the current logical time, sets `offer_expires_at` to `offered_at` plus seventy-two hours, and increments the allocation's `offers_outstanding` by `1`. The allocation's status is re-evaluated and its `version` increments when any entry changes.

#### 3.4.2. Claiming an Offer

A `Commuter` claims an offer by submitting `expected_allocation_version` and optionally `apply_credit_cents`. The entry must be `OFFERED` — otherwise `ERR_OFFER_NOT_PENDING` (HTTP 409). The current logical time must be at or before `offer_expires_at`; if it is strictly later, the request is rejected with `ERR_OFFER_EXPIRED` (HTTP 422) and the entry first transitions `OFFERED → EXPIRED` and immediately requeues per the requeue policy. The patron must satisfy the allocation's role and residency rules and be in `GOOD_STANDING`. The `expected_allocation_version` must match the allocation's current `version` — otherwise `ERR_STALE_VERSION` (HTTP 412).

On a successful claim, a permit is created on the entry's allocation with the fee computed per the proration rules of §3.3, `valid_from` defaulting to the later of the current logical date and `term_start`, and `valid_to` set to `term_end`. The entry transitions to `CLAIMED` (terminal). The allocation's `offers_outstanding` decrements by `1` and `allocated_count` increments by `1`; the allocation's status is re-evaluated and its `version` increments. The fund's `permit_revenue_cents` increases by `fee_paid_cents`, and any applied incentive credit is debited.

#### 3.4.3. Expiry Requeue and Withdrawal

When an `OFFERED` entry expires (detected lazily at claim time or at the start of an offer round), it transitions `OFFERED → EXPIRED` and immediately branches on `requeue_count`:

- If `requeue_count` is strictly less than `2`, the entry requeues: `requeue_count` increments by `1`, `decline_count` increments by `1`, `waiting_since` resets to the current logical time (the wait clock restarts), `offered_at` and `offer_expires_at` are cleared, and the entry returns to `WAITING`.
- If `requeue_count` equals `2`, the entry transitions to `WITHDRAWN` (terminal) and `decline_count` increments by `1`.

A `Commuter` may also withdraw voluntarily at any time while the entry is `WAITING` or `OFFERED`. Withdrawing from `WAITING` simply transitions to `WITHDRAWN`. Withdrawing from `OFFERED` (declining the offer) additionally increments `decline_count` by `1`, decrements the allocation's `offers_outstanding` by `1`, re-evaluates allocation status, and increments the allocation's `version`. An attempt to withdraw from any other status is rejected with `ERR_OFFER_NOT_PENDING` (HTTP 409).

### 3.5. Permit Cancellation and Refund

A permit may be cancelled by its owning `Commuter` or by a `ParkingAdmin` while its status is `ACTIVE` or `SUSPENDED`; any other status is rejected with `ERR_PERMIT_NOT_ACTIVE` (HTTP 409). Cancellation transitions the permit to `CANCELLED` (terminal), computes `refund_cents` per the refund schedule, and runs several cascades.

#### 3.5.1. Refund Schedule

Let `today` be the current logical date. If `today` is strictly before the permit's `valid_from`, `refund_cents` is the full `fee_paid_cents` with no administrative fee. Otherwise:

1. Compute `total_days` as the number of calendar days from `valid_from` through `valid_to` inclusive.
2. Compute `remaining_days` as the number of calendar days from the day after `today` through `valid_to` (the cancellation day itself is consumed and does not count as remaining).
3. The prorated share is `fee_paid_cents` multiplied by `remaining_days` and divided by `total_days`, rounded half-up to the nearest integer cent.
4. `refund_cents` is the prorated share minus `500` cents of administrative fee, floored at zero.

In both branches, any `credit_applied_cents` from the original purchase is separately restored in full to the patron's incentive account `credit_balance_cents` — the credit is never prorated and never charged the administrative fee.

#### 3.5.2. Cancellation Cascades

On cancellation, the fund's `permit_revenue_cents` decreases by `refund_cents`. The allocation's `allocated_count` decrements by `1`, its status is re-evaluated, and its `version` increments. The system immediately runs the waitlist offer selector on the freed allocation — the same selection logic as an explicit offer round — so a freed seat cascades into fresh offers without admin action. `refund_cents` is recorded on the permit; before cancellation it is null.

Permits also expire via the logical clock: when the clock advances past a permit's `valid_to` (strictly — a permit is still valid on its `valid_to` day), the permit flips `ACTIVE → EXPIRED` with no refund. The allocation's `allocated_count` decrements, status is re-evaluated, and waitlist offers are extended on the freed seats, exactly as on cancellation.

### 3.6. Citation Issuance, Payment, and the Appeals Cycle

An `EnforcementOfficer` issues a citation by submitting `lot_id`, `plate_number`, and `violation_type` (one of `NO_VALID_PERMIT`, `EXPIRED_PERMIT`, `WRONG_ZONE`, `CLOSED_LOT`). The plate must resolve to at least one existing permit — the citation binds to the permit with that `plate_number` having the latest `created_at`, regardless of that permit's status, and a plate that matches no permit at all is rejected with `ERR_PLATE_NOT_REGISTERED` (HTTP 422). The resolved permit's `patron_id` is denormalized onto the citation at issuance.

#### 3.6.1. Fine Schedule

The fine is computed at issuance and pinned to this order: escalate the base first (rounded), then add the flat event surcharge.

1. The base is the violation's schedule amount: `NO_VALID_PERMIT` is `7500` cents, `EXPIRED_PERMIT` is `5000` cents, `WRONG_ZONE` is `4000` cents, `CLOSED_LOT` is `6000` cents.
2. `repeat_count` is the number of the patron's citations with status `PAID` whose `issued_at` is at or after the current logical time minus `365` days — a citation exactly `365` days old still counts.
3. If `repeat_count` is at least `2`, the escalated base is the schedule amount multiplied by `1.5`, rounded half-up to the nearest integer cent. Otherwise the escalated base is the schedule amount unchanged.
4. If the cited lot has a closure with reason `EVENT` and status `ACTIVE` whose `[starts_at, ends_at)` window contains the current logical time, add a flat `1500`-cent event surcharge; otherwise the surcharge is zero.
5. `fine_amount_cents` is the escalated base plus the event surcharge.

A patron with two prior paid citations within the trailing year therefore pays a larger fine than a first-time offender for an identical violation on an identical lot at an identical time.

#### 3.6.2. Issuance Cascade

On issuance the citation is created with status `ISSUED`, `appeal_outcome` of `NONE`, `issued_by_officer_id` set to the caller's `X-User-ID`, and `issued_at` set to the current logical time. The patron's `outstanding_balance_cents` increases by `fine_amount_cents`, `standing` is recomputed, and if `standing` flips to `BLOCKED` the patron's `ACTIVE` permits flip to `SUSPENDED`.

#### 3.6.3. Payment

A `Commuter` pays an `ISSUED` citation they own. The citation transitions to `PAID` (terminal), the patron's `outstanding_balance_cents` decreases by `fine_amount_cents`, `standing` is recomputed, and if `standing` flips back to `GOOD_STANDING` any `SUSPENDED` permits return to `ACTIVE`. The fund's `citation_revenue_cents` increases by `fine_amount_cents` — citation revenue is recognized on a cash basis, only at payment. A citation not in `ISSUED` status is rejected with `ERR_CITATION_NOT_ISSUED` (HTTP 409).

#### 3.6.4. Appeal and Adjudication

A `Commuter` files an appeal against an `ISSUED` citation they own by supplying a `reason`. The citation must be `ISSUED` and its `appeal_outcome` must be `NONE` — a citation may be appealed at most once, and a repeat attempt is rejected with `ERR_APPEAL_ALREADY_EXISTS` (HTTP 409). On filing, the citation transitions to `UNDER_APPEAL`, `appeal_outcome` becomes `PENDING`, `appeal_reason` is recorded, and the fine is excluded from the patron's `outstanding_balance_cents` while under appeal — so `outstanding_balance_cents` decreases by `fine_amount_cents`, `standing` is recomputed, and `SUSPENDED` permits may return to `ACTIVE`.

An `AppealsOfficer` decides an `UNDER_APPEAL` appeal by submitting an `outcome` and, when the outcome is `REDUCED`, a `reduction_pct`. The decider's `X-User-ID` must differ from the citation's `issued_by_officer_id`; a match is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Three outcomes are possible:

- **UPHELD** — the citation returns to `ISSUED` with `fine_amount_cents` unchanged. `appeal_outcome` becomes `UPHELD`, `appeal_decided_by` records the decider, and the patron's `outstanding_balance_cents` increases by the (unchanged) `fine_amount_cents`.
- **REDUCED** — `reduction_pct` must be present and in the range `1` through `99`; otherwise the request is rejected with `ERR_INVALID_REQUEST` (HTTP 400). The new `fine_amount_cents` is the current `fine_amount_cents` multiplied by `(100 - reduction_pct)` and divided by `100`, rounded half-up to the nearest integer cent. The citation returns to `ISSUED`, `appeal_outcome` becomes `REDUCED`, and the patron's `outstanding_balance_cents` increases by the new (reduced) `fine_amount_cents`. `reduction_pct` must be absent or null for any other outcome.
- **VOIDED** — the citation transitions to `VOIDED` (terminal), `appeal_outcome` becomes `VOIDED`, and there is no balance effect (the fine was already excluded while under appeal).

On `UPHELD` and `REDUCED` decisions, `standing` is recomputed after the balance increase, and if `standing` flips to `BLOCKED` the patron's `ACTIVE` permits flip to `SUSPENDED`. On all three outcomes the decider's `X-User-ID` is recorded as `appeal_decided_by`.

### 3.7. Lot Closures, Event Parking, and Construction Displacement

A `ParkingAdmin` schedules a lot closure by submitting `lot_id`, `reason` (one of `EVENT`, `CONSTRUCTION`), `starts_at`, and `ends_at`, plus conditional fields. `ends_at` must be strictly after `starts_at`; otherwise `ERR_INVALID_INTERVAL` (HTTP 400). For `EVENT` closures, `event_name` is required and `reserved_spaces` must be at least `1`; `expected_attendance` is optional. For `CONSTRUCTION` closures, `event_name` and `expected_attendance` must be null, `reserved_spaces` must be `0`, and `fallback_lot_id` is required and must differ from `lot_id` — violations are rejected with `ERR_FALLBACK_LOT_REQUIRED` (HTTP 400) when the fallback is missing or equal to the closed lot, and `ERR_INVALID_REQUEST` (HTTP 400) for other conditional-field violations.

Closures on a single lot must not overlap: a new closure is rejected with `ERR_CLOSURE_OVERLAP` (HTTP 409) if any other closure on the same lot with status `SCHEDULED` or `ACTIVE` has a `[starts_at, ends_at)` window that intersects the new one. Because windows are half-open, two closures where one's `ends_at` equals the other's `starts_at` do not overlap and both may coexist.

At creation the closure is `SCHEDULED`. For `EVENT` closures, the lot's `reserved_spaces_total` immediately increases by `reserved_spaces` (the reservation is taken at schedule time, not activation time), `available_capacity` is recomputed, and allocations on the lot may flip toward `WAITLISTING` if their free-seat picture tightens.

#### 3.7.1. Activation

Activating a `SCHEDULED` closure re-checks the overlap rule (another closure may have been scheduled in the interim) and, for `CONSTRUCTION` closures, verifies displacement capacity: for every allocation on the closed lot holding `ACTIVE` permits, the fallback lot's allocation with the same `permit_code` must have `allocated_count` plus the incoming displaced count less than or equal to its `quota`. If any fallback allocation cannot absorb its displaced permits within quota, the activation is rejected with `ERR_DISPLACEMENT_OVER_CAPACITY` (HTTP 409). Activating a closure not in `SCHEDULED` status is rejected with `ERR_CLOSURE_INVALID_STATE` (HTTP 409).

On successful activation the closure becomes `ACTIVE` and the lot's `posture` flips to `CLOSED_EVENT` or `CLOSED_CONSTRUCTION` according to reason, with the lot's `version` incrementing. For `CONSTRUCTION` closures, a displacement cascade runs: every `ACTIVE` permit on every allocation of the closed lot is repointed — the permit's `allocation_id` becomes the fallback lot's allocation with the same `permit_code`, and the permit's `displaced_from_allocation_id` records the original allocation. Each repoint decrements the source allocation's `allocated_count` and increments the target's; both allocations re-evaluate `OPEN`/`WAITLISTING` status and increment their `version`. The closure's `displaced_permit_count` records the number of permits repointed.

#### 3.7.2. Lift and Cancel

Lifting an `ACTIVE` closure transitions it to `LIFTED` (terminal) and restores the lot's `posture` to `OPEN`. For `EVENT` closures the lot's `reserved_spaces_total` decreases by `reserved_spaces`. For `CONSTRUCTION` closures every permit whose `displaced_from_allocation_id` points to an allocation of the closed lot (and which currently sits on the fallback allocation) is repointed back: `allocation_id` returns to the original, `displaced_from_allocation_id` is cleared, and allocation counts and statuses re-evaluate on both sides.

Cancelling a `SCHEDULED` closure transitions it to `CANCELLED` (terminal) and, for `EVENT` closures, releases the reservation by decreasing `reserved_spaces_total` by `reserved_spaces`. A closure may only be cancelled from `SCHEDULED`; a closure may only be lifted from `ACTIVE`. Either call against the wrong state is rejected with `ERR_CLOSURE_INVALID_STATE` (HTTP 409).

### 3.8. Shuttle Route Planning and the Fleet Window Buffer

A `ParkingAdmin` plans a shuttle route by submitting `fund_id`, `route_code` (a unique code such as `BLUE_LOOP`), `fleet_group`, `service_window_start_minutes` and `service_window_end_minutes` (minutes after midnight — start in `0..1439`, end strictly greater than start and at most `1440`), `headway_minutes` (at least `1`), `vehicle_capacity` (at least `1`), `projected_daily_ridership` (at least `0`), and `annual_operating_cost_cents` (at least `0`). A service window whose end is not strictly after its start is rejected with `ERR_INVALID_INTERVAL` (HTTP 400).

Routes sharing a `fleet_group` must respect a thirty-minute buffer between daily service windows: the gap between any two routes' windows in the same fleet group must be at least `30` minutes. This rule is checked against non-terminal routes (those in `PLANNED`, `ACTIVE`, or `SUSPENDED` status) at creation and re-checked against `ACTIVE` routes at activation; violations are rejected with `ERR_FLEET_WINDOW_CONFLICT` (HTTP 409).

At creation the route is `PLANNED`. Two derived fields are computed: `planned_daily_runs` is the service window length in minutes (end minus start) divided by `headway_minutes`, with the quotient rounded down to the nearest whole number; `daily_capacity` is `planned_daily_runs` multiplied by `vehicle_capacity`. `ridership_total` starts at `0`.

#### 3.8.1. Activation, Suspension, and Funding Commitment

Activating a route requires three checks, evaluated in this order:

1. **State** — the route must be `PLANNED` or `SUSPENDED`; otherwise `ERR_ROUTE_INVALID_STATE` (HTTP 409).
2. **Seat coverage** — `daily_capacity` must be greater than or equal to `projected_daily_ridership`; equality is sufficient. Failure is rejected with `ERR_INSUFFICIENT_SHUTTLE_CAPACITY` (HTTP 422).
3. **Funding** — the fund's `available_balance_cents` must be greater than or equal to `annual_operating_cost_cents`. Failure is rejected with `ERR_INSUFFICIENT_FUNDING` (HTTP 402).

On a first activation (`PLANNED → ACTIVE`) the fund's `committed_shuttle_funding_cents` increases by `annual_operating_cost_cents`. On a resume (`SUSPENDED → ACTIVE`) the commitment is unchanged — the route's cost was already committed at first activation and is not double-committed.

Suspending an `ACTIVE` route transitions it to `SUSPENDED`. The funding commitment is retained while the route is `SUSPENDED` — committed funding is the sum of `annual_operating_cost_cents` over routes with status `ACTIVE` or `SUSPENDED`, so suspension does not free the budget.

A `ParkingAdmin` logs one day of boardings against a route by submitting `log_date` and `boardings`; the route's `ridership_total` increases by `boardings`.

### 3.9. Alternative-Commute Incentive Program

A `Commuter` enrolls in the incentive program by submitting their own `patron_id`. Patrons whose `primary_commute_mode` is `DRIVE_ALONE` are ineligible — enrollment is rejected with `ERR_INELIGIBLE_COMMUTE_MODE` (HTTP 403). Each patron may hold exactly one account; a duplicate enrollment is rejected with `ERR_ACCOUNT_EXISTS` (HTTP 409). The account is created with `points_balance`, `lifetime_points`, and `credit_balance_cents` all at `0`.

A `ParkingAdmin` posts verified alternative-commute days by submitting `days_commuted`, which must be in the range `1` through `31`. The account accrues `10` points per day: `points_balance` increases by `days_commuted * 10` and `lifetime_points` increases by the same amount.

A `Commuter` redeems points in blocks by submitting `blocks` (at least `1`). Each block costs `500` points and yields `2500` cents of parking credit. Redemption requires `points_balance` to be at least `blocks * 500` — equality is sufficient; otherwise the request is rejected with `ERR_INSUFFICIENT_POINTS` (HTTP 422). On redemption `points_balance` decreases by `blocks * 500` and `credit_balance_cents` increases by `blocks * 2500`.

Credit is consumed at permit purchase or offer claim via the `apply_credit_cents` request field — the applied amount is the smaller of the requested amount and `fee_total_cents`, and may not exceed `credit_balance_cents`. When a purchase or claim that applied credit is later cancelled, the applied credit is restored to `credit_balance_cents` in full, independent of the cash refund schedule.

### 3.10. Transportation Fund Ledger

A `ParkingAdmin` creates a transportation operations fund by submitting a unique `fund_code` (e.g. `PTS_OPERATING`). All four computed balances start at `0`.

The fund ledger combines running revenue counters, updated by cash events, with commitments derived from shuttle routes. Permits and citations carry no `fund_id`, so each cash event below is applied to every transportation fund that exists at the moment the event occurs — wherever this document says the fund's `permit_revenue_cents` or `citation_revenue_cents` increases or decreases by an amount, that amount is added to or subtracted from every then-existing fund. Each fund's revenue counters therefore reflect only the cash events that occur while that fund exists; cash events that occurred before a fund was created are never backfilled into it:

- `permit_revenue_cents` increases by `fee_paid_cents` at every permit purchase and waitlist claim, and decreases by `refund_cents` at every permit cancellation.
- `citation_revenue_cents` increases by `fine_amount_cents` at citation payment only — cash basis. Fines under appeal and fines voided on appeal never appear in citation revenue.
- `committed_shuttle_funding_cents` is the sum of `annual_operating_cost_cents` over shuttle routes with status `ACTIVE` or `SUSPENDED` on this fund.
- `available_balance_cents` is `permit_revenue_cents` plus `citation_revenue_cents` minus `committed_shuttle_funding_cents`.

This ledger is the single source of truth for the funding check at shuttle activation.

### 3.11. The Logical Clock Endpoint

An admin-only test-driving capability advances the server's logical clock by submitting `to_iso8601`. The endpoint returns the new `current_utc`. Advancing the clock sweeps `ACTIVE` permits whose `valid_to` is strictly before the new logical date and flips them to `EXPIRED` (freeing seats and extending waitlist offers per the standard selector). Waitlist offer expiry is NOT evaluated here — it is evaluated lazily at claim time and at the start of offer rounds. The startup default of `2026-08-01T00:00:00Z` holds until the first call, and the server never falls back to wall-clock time.

## 4. Endpoint Definitions

All endpoints are mounted under `/parking`. New resources are returned with HTTP `201`; modifications and retrievals return HTTP `200`. The `expected_allocation_version` field on the three OCC-guarded writes is non-optional; no other endpoint accepts a version field.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/parking/patrons` | Register a campus member | ParkingAdmin |
| GET | `/parking/patrons` | List patrons (filters: `campus_role`, `residency`, `standing`) | Commuter, ParkingAdmin, EnforcementOfficer, AppealsOfficer |
| GET | `/parking/patrons/{patronId}` | Get a patron | Commuter, ParkingAdmin, EnforcementOfficer, AppealsOfficer |
| POST | `/parking/lots` | Create a parking lot | ParkingAdmin |
| GET | `/parking/lots` | List lots (filters: `posture`, `zone`) | Commuter, ParkingAdmin, EnforcementOfficer, AppealsOfficer |
| GET | `/parking/lots/{lotId}` | Get a lot | Commuter, ParkingAdmin, EnforcementOfficer, AppealsOfficer |
| POST | `/parking/allocations` | Create a permit-class allocation on a lot | ParkingAdmin |
| GET | `/parking/allocations` | List allocations (filters: `lot_id`, `permit_code`, `status`) | Commuter, ParkingAdmin, EnforcementOfficer, AppealsOfficer |
| GET | `/parking/allocations/{allocationId}` | Get an allocation (canonical read before any OCC write) | Commuter, ParkingAdmin, EnforcementOfficer, AppealsOfficer |
| PATCH | `/parking/allocations/{allocationId}` | Adjust an allocation's quota (OCC-guarded) | ParkingAdmin |
| POST | `/parking/allocations/{allocationId}/extend-offers` | Run one offer round: expire overdue OFFERED entries, then promote top-scored WAITING entries | ParkingAdmin |
| POST | `/parking/waitlist-entries` | Join an allocation's waitlist | Commuter, ParkingAdmin |
| GET | `/parking/waitlist-entries` | List waitlist entries (filters: `allocation_id`, `patron_id`, `status`) | Commuter, ParkingAdmin, EnforcementOfficer, AppealsOfficer |
| GET | `/parking/waitlist-entries/{entryId}` | Get a waitlist entry | Commuter, ParkingAdmin, EnforcementOfficer, AppealsOfficer |
| POST | `/parking/waitlist-entries/{entryId}/claim` | Claim an outstanding offer; creates and returns the Permit (OCC-guarded) | Commuter |
| POST | `/parking/waitlist-entries/{entryId}/withdraw` | Withdraw (WAITING) or decline (OFFERED) a waitlist entry | Commuter |
| POST | `/parking/permits` | Purchase a permit on an OPEN allocation (OCC-guarded) | Commuter, ParkingAdmin |
| GET | `/parking/permits` | List permits (filters: `patron_id`, `allocation_id`, `displaced_from_allocation_id`, `plate_number`, `status`) | Commuter, ParkingAdmin, EnforcementOfficer, AppealsOfficer |
| GET | `/parking/permits/{permitId}` | Get a permit | Commuter, ParkingAdmin, EnforcementOfficer, AppealsOfficer |
| POST | `/parking/permits/{permitId}/cancel` | Cancel a permit; refund per schedule and restore applied credit | Commuter, ParkingAdmin |
| POST | `/parking/citations` | Issue a citation from an LPR observation | EnforcementOfficer |
| GET | `/parking/citations` | List citations (filters: `lot_id`, `permit_id`, `patron_id`, `plate_number`, `status`) | Commuter, ParkingAdmin, EnforcementOfficer, AppealsOfficer |
| GET | `/parking/citations/{citationId}` | Get a citation | Commuter, ParkingAdmin, EnforcementOfficer, AppealsOfficer |
| POST | `/parking/citations/{citationId}/pay` | Pay an issued citation (cash-basis revenue recognition) | Commuter |
| POST | `/parking/citations/{citationId}/appeal` | File an appeal against an issued citation | Commuter |
| POST | `/parking/citations/{citationId}/decide-appeal` | Adjudicate an appeal (UPHELD / REDUCED / VOIDED); decider must not be the issuing officer | AppealsOfficer |
| POST | `/parking/closures` | Schedule a lot closure (EVENT reserves stalls immediately; CONSTRUCTION requires a fallback lot) | ParkingAdmin |
| GET | `/parking/closures` | List closures (filters: `lot_id`, `fallback_lot_id`, `reason`, `status`) | Commuter, ParkingAdmin, EnforcementOfficer, AppealsOfficer |
| GET | `/parking/closures/{closureId}` | Get a closure | Commuter, ParkingAdmin, EnforcementOfficer, AppealsOfficer |
| POST | `/parking/closures/{closureId}/activate` | Activate a scheduled closure; CONSTRUCTION activation runs the displacement cascade | ParkingAdmin |
| POST | `/parking/closures/{closureId}/lift` | Lift an active closure; reverses displacement and releases event reservations | ParkingAdmin |
| POST | `/parking/closures/{closureId}/cancel` | Cancel a scheduled closure | ParkingAdmin |
| POST | `/parking/shuttle-routes` | Plan a shuttle route | ParkingAdmin |
| GET | `/parking/shuttle-routes` | List routes (filters: `fund_id`, `fleet_group`, `status`) | Commuter, ParkingAdmin, EnforcementOfficer, AppealsOfficer |
| GET | `/parking/shuttle-routes/{routeId}` | Get a route | Commuter, ParkingAdmin, EnforcementOfficer, AppealsOfficer |
| POST | `/parking/shuttle-routes/{routeId}/activate` | Activate (or resume) a route; commits annual operating cost on first activation | ParkingAdmin |
| POST | `/parking/shuttle-routes/{routeId}/suspend` | Suspend an active route (funding commitment retained) | ParkingAdmin |
| POST | `/parking/shuttle-routes/{routeId}/ridership-logs` | Log one day of boardings | ParkingAdmin |
| POST | `/parking/incentive-accounts` | Enroll a patron in the alternative-commute incentive program | Commuter |
| GET | `/parking/incentive-accounts` | List incentive accounts (filter: `patron_id`) | Commuter, ParkingAdmin, EnforcementOfficer, AppealsOfficer |
| GET | `/parking/incentive-accounts/{accountId}` | Get an incentive account | Commuter, ParkingAdmin, EnforcementOfficer, AppealsOfficer |
| POST | `/parking/incentive-accounts/{accountId}/accruals` | Post verified alternative-commute days (at most 31 per posting) | ParkingAdmin |
| POST | `/parking/incentive-accounts/{accountId}/redeem` | Redeem points in 500-point blocks for parking credit | Commuter |
| POST | `/parking/transportation-funds` | Create a transportation operations fund | ParkingAdmin |
| GET | `/parking/transportation-funds` | List funds with computed balances | Commuter, ParkingAdmin, EnforcementOfficer, AppealsOfficer |
| GET | `/parking/transportation-funds/{fundId}` | Get a fund with computed balances | Commuter, ParkingAdmin, EnforcementOfficer, AppealsOfficer |
| POST | `/parking/_clock/set_current_utc` | Set the server's logical clock | ParkingAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_PATRON_NOT_FOUND` | 404 |
| `ERR_LOT_NOT_FOUND` | 404 |
| `ERR_ALLOCATION_NOT_FOUND` | 404 |
| `ERR_ENTRY_NOT_FOUND` | 404 |
| `ERR_PERMIT_NOT_FOUND` | 404 |
| `ERR_CITATION_NOT_FOUND` | 404 |
| `ERR_CLOSURE_NOT_FOUND` | 404 |
| `ERR_ROUTE_NOT_FOUND` | 404 |
| `ERR_INCENTIVE_ACCOUNT_NOT_FOUND` | 404 |
| `ERR_FUND_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_INTERVAL` | 400 |
| `ERR_FALLBACK_LOT_REQUIRED` | 400 |
| `ERR_ALLOCATION_NOT_OPEN` | 409 |
| `ERR_ALLOCATION_NOT_WAITLISTING` | 409 |
| `ERR_OFFER_NOT_PENDING` | 409 |
| `ERR_PERMIT_NOT_ACTIVE` | 409 |
| `ERR_CITATION_NOT_ISSUED` | 409 |
| `ERR_CLOSURE_INVALID_STATE` | 409 |
| `ERR_ROUTE_INVALID_STATE` | 409 |
| `ERR_PLATE_NOT_REGISTERED` | 422 |
| `ERR_CLOSURE_OVERLAP` | 409 |
| `ERR_DUPLICATE_ACTIVE_PERMIT` | 409 |
| `ERR_FLEET_WINDOW_CONFLICT` | 409 |
| `ERR_OFFER_EXPIRED` | 422 |
| `ERR_PATRON_INELIGIBLE` | 403 |
| `ERR_INELIGIBLE_COMMUTE_MODE` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_DUPLICATE_ALLOCATION_CODE` | 409 |
| `ERR_ALREADY_WAITLISTED` | 409 |
| `ERR_APPEAL_ALREADY_EXISTS` | 409 |
| `ERR_ACCOUNT_EXISTS` | 409 |
| `ERR_PATRON_BLOCKED` | 402 |
| `ERR_INSUFFICIENT_CREDIT` | 422 |
| `ERR_DISPLACEMENT_OVER_CAPACITY` | 409 |
| `ERR_INSUFFICIENT_FUNDING` | 402 |
| `ERR_INSUFFICIENT_SHUTTLE_CAPACITY` | 422 |
| `ERR_INSUFFICIENT_POINTS` | 422 |
