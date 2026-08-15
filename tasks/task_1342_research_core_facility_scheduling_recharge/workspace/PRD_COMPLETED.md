# Research Core Facility API — Product Requirements Document

## 1. Introduction

University core facilities — shared instrument centers that recover their operating costs by charging researchers for instrument time — sit at the intersection of scientific operations, sponsored-research finance, and federal cost-accounting rules. This document specifies the Research Core Facility Scheduling & Recharge API: a system that runs the full operational loop of such a facility, from the day an instrument is placed in the catalog through the annual close of its fiscal books. A researcher with a certified training record books time on a 600 MHz NMR against an authorized grant; the booking encumbers the grant; staff check the user in, log actual usage, and validate the log; the resulting charge, net of any subsidy award, posts into a monthly recharge batch and debits the grant; and at fiscal-year close the facility computes whether its rates broke even and carries any surplus or deficit into the next year's rate development.

Three cross-cutting obligations shape every requirement below. First, **segregation of duties**: the person who authors a rate set cannot approve it, and the person who logs a usage session cannot validate it. Second, **NIH-style rate discipline**: internal rates are capped year-over-year, break-even deficits require written waivers, and an accrual true-up at fiscal-year close feeds the next cycle's rates. Third, **deterministic time**: the system runs on a logical clock, settable only through an admin test-driving capability, and every time-derived status (expired training, exhausted grant, expired contract, expired award) resolves against that clock — never against wall time.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide contracts that apply to every endpoint and every entity in the API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity in which they act. The system recognizes exactly five roles, spelled exactly as follows: `FacilityAdmin`, `CoreStaff`, `FinanceOfficer`, `Researcher`, and `ExternalClient`. A request missing either header, presenting a role outside these five, or — for the entity-backed roles — presenting an `X-User-ID` that does not reference an existing `User` record, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not authorized for the endpoint, or in which an entity-backed role attempts to reach a resource belonging to another user, is rejected with `ERR_FORBIDDEN` (HTTP 403).

Three of the five roles are opaque: for `FacilityAdmin`, `CoreStaff`, and `FinanceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `developed_by` on a `RateSet`, `approved_by` on a `RateSet`, `logged_by` or `validated_by` on a `UsageLog`, `reviewed_by` on a `SubsidyApplication`, or `verified_by` on a `Publication` — but it never compares these operator identifiers against any entity's `id` for ownership purposes. The segregation-of-duties comparisons described later (validator versus logger, approver versus developer) compare these opaque operator identifiers to each other, not to `User` rows.

The remaining two roles are entity-backed. When `X-User-Role` is `Researcher`, and likewise when it is `ExternalClient`, `X-User-ID` is the `id` of the acting `User`; ownership checks on any resource that references a `User` compare the resource's foreign-key field (for example, `user_id` on a `Booking`, `UsageLog`, `RechargeEntry`, `SubsidyApplication`, `SubsidyAward`, or `Publication`) to `X-User-ID`. Entity-backed callers may only read and mutate their own resources and may only create resources whose `user_id` equals their own `X-User-ID`; list endpoints force-filter to the caller's own records. A `Researcher` additionally sees grants for which the caller is the principal investigator or appears in `authorized_user_ids`.

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

List endpoints accept two query parameters. The `limit` parameter specifies the maximum number of items returned; when omitted it defaults to 10, and it is clamped to a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0, with negative values clamped to 0. A non-integer `limit` or `offset` is rejected as `ERR_INVALID_REQUEST`. Unless a more specific rule is stated, every list endpoint returns resources sorted by `created_at` ascending, with ties on `created_at` broken by creation (insertion) order. List responses carry `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope; `has_more` is true exactly when `offset` plus the number of items returned is still below `total_count`.

### 2.4. The Logical Clock and Time-Derived Statuses

The server runs on a **logical clock**, not wall time. On fresh startup, before any explicit adjustment, the logical clock reads exactly `2026-08-01T00:00:00Z`. A `FacilityAdmin` may set the logical clock — forward or backward — via the test-driving capability by supplying a `to_iso8601` instant; the endpoint answers 200 with an object carrying `current_utc`, the new logical time rendered in UTC without fractional digits when whole-second and with three fractional digits otherwise. Thereafter every time-dependent derivation in the system resolves against the new logical time. The logical clock never silently falls back to wall-clock time.

Four families of status are *derived* from the logical clock rather than stored:

- A `CERTIFIED` `TrainingRecord` whose `expires_at` is at or before the current logical time is reported and treated as `EXPIRED`. The boundary is inclusive: exactly at `expires_at` the record is expired; one second before, it is still certified.
- A `Grant` whose `end_date` falls before the current logical date is `EXPIRED`.
- A `SubsidyAward` whose `valid_until` is at or before the current logical time is `EXPIRED`.
- A `MaintenanceContract` whose `coverage_end` falls before the current logical date is `EXPIRED`.

A fiscal year label `N` (on `FiscalYearPeriod.fiscal_year`) covers the calendar dates from January 1 of year N through December 31 of year N inclusive. For recharge entries, the charge date used for fiscal attribution is the entry's batch period (the batch's `period_year` and `period_month`); for bookings, the booking date is the calendar date of `start_at`.

### 2.5. Money, Precision, and Rounding Discipline

All monetary amounts in the system are integer cents — `budget_total_cents`, `estimated_charge_cents`, `penalty_cents`, `amount_cents`, `subsidy_offset_cents`, `net_amount_cents`, `awarded_amount_cents`, `remaining_amount_cents`, `annual_cost_cents`, `carryforward_in_cents`, `revenue_cents`, `cash_revenue_cents`, `cost_cents`, `surplus_deficit_cents`, `carryforward_out_cents`, `gross_amount_cents`, and the various per-hour rate fields. Rates are integer cents per hour (`internal_rate_cents_per_hour`, `external_rate_cents_per_hour`, `applied_rate_cents_per_hour`). Wherever a money computation involves division or multiplication by a fractional percentage, the result is rounded **half-up to whole cents**, and that rounding is applied exactly once per money computation, at the step the relevant workflow section prescribes. Penalty fractions (`late_cancel_penalty_pct`, `no_show_penalty_pct`) are numbers between 0 and 1 inclusive. Percentage constants used by the rate-cap and deviation-flag rules are fractions (0.10 and 0.05 respectively), applied as multiplicative factors.

Two rounding orders are pinned and non-negotiable. In usage charging, the billing-increment ceiling is applied first (in whole minutes), the minimum-charge floor second, the multiplication by the hourly rate and its half-up rounding to cents third, and the consumables fee is added last and is never itself rounded. In derived rate computation, each line's suggested rate is rounded to whole cents first, and only then does the break-even re-check run against the rounded rates. Computing money from un-ceiled minutes, or rounding only the final verdict, yields different cent values and is non-conformant.

### 2.6. Common Resource Properties

Every top-level resource carries a standard set of system-managed fields. `id` is a server-minted UUID with no type prefix, rendered in the canonical RFC 4122 string form — five hyphen-separated hexadecimal groups (for example, `3f6b0a2e-7c41-4e9a-9c2d-1a2b3c4d5e6f`). `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits; `updated_at` refreshes on every mutation of the resource. The same three-fractional-digit UTC rendering applies to every other datetime-valued field carried on a resource: client-supplied datetimes — a booking's or downtime event's `start_at`/`end_at`, a usage log's `actual_start_at`/`actual_end_at`, an award's `valid_from`/`valid_until`, and a rate set's `effective_from` — are parsed, converted to UTC, and re-rendered in this canonical form rather than echoed verbatim, and server-stamped datetimes (`certified_at`, `expires_at`, `finalized_at`, `closed_at`) are rendered the same way. Date-only fields (`start_date`, `end_date`, `coverage_start`, `coverage_end`, `published_at`) remain strict `YYYY-MM-DD` strings. `version` is a system-managed integer that increments by 1 on every mutation, including mutations driven by system cascades (for example, when a suspension flips a user's bookings, the `User.version` itself advances by 1 for the suspension, and each cascade-affected resource's own version advances as it is mutated). All fifteen entities in this domain — `User`, `Instrument`, `TrainingRecord`, `Grant`, `RateSet`, `Booking`, `UsageLog`, `RechargeBatch`, `RechargeEntry`, `SubsidyApplication`, `SubsidyAward`, `MaintenanceContract`, `DowntimeEvent`, `Publication`, and `FiscalYearPeriod` — carry the full set of common fields.

### 2.7. Nested Resource Retrieval and Reference Resolution

The system validates every request's references in a strict left-to-right order. Path identifiers are resolved first, in path order; the first identifier that does not resolve to an existing resource is rejected with `ERR_NOT_FOUND` (HTTP 404). Body foreign-key references — `instrument_id`, `grant_id`, `user_id`, `booking_id`, `application_id`, `maintenance_contract_id`, and every element of an `instrument_ids` array — must each reference an existing resource; any failure is likewise `ERR_NOT_FOUND`. Existence checking precedes all business-rule evaluation.

### 2.8. Optimistic Concurrency Control

Three write endpoints — and only these three — require an explicit expected-version field in the request body:

- Rescheduling an `APPROVED` booking requires `expected_booking_version` matching the booking's current `version`. If another writer has advanced the booking's version since the client last read it (for example, an earlier legitimate reschedule already moved the window), the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting a booking state it never observed.
- Amending a grant via its `PUT` requires `expected_grant_version` matching the grant's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). Sequential amendments are individually legitimate, so only the stale-version check rejects the second writer.
- Editing a `DRAFT` rate set via its `PUT` requires `expected_rate_set_version` matching the set's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).

Endpoints not listed here do not accept a version field. The stale-version comparison applies only to a well-formed integer expected-version value; a missing or non-integer expected-version field is not a stale-version failure and instead surfaces at field-format validation as `ERR_INVALID_REQUEST`. On these three endpoints the stale-version check is evaluated after authentication, authorization, segregation-of-duties, and path-identifier resolution, and before everything else — body foreign-key existence, state-machine legality, field formats, and business rules (on grant amendment specifically, existence of any newly supplied `authorized_user_ids` is verified only after field formats; on rate-set editing, existence of newly supplied line instruments is verified only after the `DRAFT`-only state check).

### 2.9. Validation Order

When multiple validation rules could reject the same request, the server evaluates them in a fixed priority order, and the earliest failing rule produces the response. The order is:

1. Authentication (`ERR_UNAUTHENTICATED`): headers present, role recognized, entity-backed id resolves.
2. Authorization (`ERR_FORBIDDEN`): role listed for the endpoint; entity-backed ownership.
3. Segregation of duties (`ERR_SEGREGATION_OF_DUTIES`): usage-log validation/rejection and rate-set approval actor-versus-recorder comparisons.
4. Existence (`ERR_NOT_FOUND`): path ids and body foreign keys, left-to-right.
5. Optimistic concurrency (`ERR_STALE_VERSION`) on the three OCC endpoints — integer-valued expected versions only, evaluated ahead of the body's own checks per §2.8.
6. State-machine legality (`ERR_INVALID_STATE`): the target resource's current state must permit the requested transition; booking approval additionally requires that an `EFFECTIVE` rate set exists for the fiscal year containing the booking's `start_at` and contains a rate line for the booking's instrument. This rule also covers time-window misuse on booking cancel and no-show: cancelling an `APPROVED` booking is permitted only strictly before `start_at`, and marking a no-show is permitted only after `start_at` has passed; violations surface as `ERR_INVALID_STATE`.
7. Open-batch gating (`ERR_BATCH_NOT_OPEN`): every entry-posting action — cancelling a booking with a penalty, marking a no-show with a penalty, validating a usage log, and resolving a dispute by write-off — requires an `OPEN` `RechargeBatch`.
8. Fiscal-year gating (`ERR_FY_CLOSED`): rate-set approve, rate-set activate, and batch creation are rejected when the target fiscal year period is `CLOSED`.
9. Grant-close gating (`ERR_GRANT_HAS_OPEN_ENTRIES`).
10. Instrument availability (`ERR_INSTRUMENT_UNAVAILABLE`) for booking creation and approval.
11. User-active gating (`ERR_USER_SUSPENDED`) for booking creation, booking approval, and training certification.
12. Training requirement (`ERR_TRAINING_REQUIRED`).
13. Training currency (`ERR_TRAINING_EXPIRED`).
14. Future-dated booking (`ERR_BOOKING_IN_PAST`).
15. Duration bounds (`ERR_DURATION_OUT_OF_RANGE`).
16. Booking overlap (`ERR_BOOKING_OVERLAP`).
17. Downtime conflict (`ERR_DOWNTIME_CONFLICT`).
18. Contract-window overlap (`ERR_CONTRACT_OVERLAP`).
19. Usage-log window shape (`ERR_USAGE_WINDOW_INVALID`).
20. Preventive-maintenance contract requirement (`ERR_CONTRACT_REQUIRED`).
21. Field formats (`ERR_INVALID_REQUEST`): required fields present, enums valid, `end_at` after `start_at`, positive amounts where required, email format; unknown or system/computed-sourced fields in request bodies are rejected here as malformed. On state-transition action endpoints this unknown-field rejection generally fires as the body is read, ahead of state-machine legality (rule 6); the exceptions — booking reschedule, usage-log edit, entry dispute and dispute resolution, and subsidy-application approval — evaluate state legality (and, where applicable, open-batch gating) first, and rate-set approval ignores the request body entirely.
22. Uniqueness (`ERR_UNIQUE_CONSTRAINT`): user `email`, `grant_code`, `fiscal_year`, the batch (`period_year`, `period_month`) pair, one `EFFECTIVE` rate set per fiscal year, one non-`REVOKED` `TrainingRecord` per (user, instrument), and rate-set lines unique per instrument.
23. Single open batch (`ERR_DUPLICATE_OPEN_BATCH`).
24. Duplicate booking (`ERR_DUPLICATE_BOOKING`).
25. One usage log per booking (`ERR_USAGE_LOG_EXISTS`).
26. Rate ordering (`ERR_RATE_ORDER_INVALID`).
27. Priority entitlement (`ERR_PRIORITY_NOT_AVAILABLE`).
28. Preemption feasibility (`ERR_PREEMPTION_BLOCKED`) — at approval of a `PRIORITY` booking this check replaces the overlap rule and runs at the overlap rule's position, ahead of the downtime-conflict check (rule 17).
29. Publication evidence (`ERR_PUBLICATION_EVIDENCE_MISSING`).
30. Acknowledgment reason (`ERR_ACK_REASON_REQUIRED`).
31. Grant affiliation shape (`ERR_GRANT_AFFILIATION_MISMATCH`).
32. Grant active (`ERR_GRANT_INACTIVE`).
33. Grant chargeable window (`ERR_GRANT_WINDOW_VIOLATION`).
34. Grant authorization (`ERR_GRANT_NOT_AUTHORIZED`).
35. Fiscal capacity (`ERR_GRANT_BUDGET_EXCEEDED`): at approval, the grant's `budget_available_cents` must be at least the provisional `estimated_charge_cents`; at usage validation, at least the entry's `net_amount_cents`. The same error rejects a budget amendment that would lower `budget_total_cents` below the sum of encumbered plus used.
36. Rate cap (`ERR_RATE_CAP_EXCEEDED`).
37. Break-even waiver (`ERR_BREAK_EVEN_WAIVER_REQUIRED`).
38. Subsidy eligibility (`ERR_SUBSIDY_INELIGIBLE`).
39. Usage-log creation requires a `COMPLETED` booking (`ERR_BOOKING_NOT_COMPLETED`).
40. Fiscal-year close gating (`ERR_UNFINALIZED_BATCHES`).
41. The cancel/no-show time-window rule described under item 6 (also `ERR_INVALID_STATE`).

### 2.10. Computed Statuses and the Ledger Bubble-Up

Several statuses are **computed**, not stored as independent facts, and they recover automatically when the underlying numbers reverse. A `Grant` reports `CLOSED` only when explicitly closed (stored), otherwise `EXPIRED` when its `end_date` has passed, otherwise `EXHAUSTED` when `budget_available_cents` is less than or equal to zero — exactly zero is exhausted — and otherwise `ACTIVE`. The precedence is `CLOSED` above `EXPIRED` above `EXHAUSTED` above `ACTIVE`. A `SubsidyAward` follows the same shape: `REVOKED` (stored) above `EXPIRED` (`valid_until` reached) above `EXHAUSTED` (`remaining_amount_cents` at or below zero) above `ACTIVE`. A `MaintenanceContract` reports `TERMINATED` (stored) above `EXPIRED` (`coverage_end` passed) above `ACTIVE`.

The grant ledger recomputes on every mutation touching encumbrance or usage. `budget_encumbered_cents` is the sum of `encumbered_cents` over the grant's bookings in `APPROVED` or `IN_PROGRESS` status. `budget_used_cents` is the sum of `net_amount_cents` over the grant's recharge entries of kind `USAGE` or `PENALTY` whose status is `PENDING`, `BILLED`, `PAID`, or `DISPUTED` — entries in `WRITTEN_OFF` are excluded because they have been reversed, and `ADJUSTMENT` entries never count. `budget_available_cents` is `budget_total_cents` minus the encumbered and used sums; it may go negative only through a budget amendment. When a reversal (a cancellation releasing encumbrance, a write-off crediting a charge, or an amendment raising the budget) pushes availability back above zero, an `EXHAUSTED` grant flips back to `ACTIVE` without any explicit client action.

## 3. Business Logic & Workflows

### 3.1. Users and the Facility Registry

A `FacilityAdmin` registers each facility user with `full_name`, `email`, `affiliation`, and optionally `department` and `is_pi`. The `email` must be unique across users and non-empty. `affiliation` is either `INTERNAL` (a university member who is grant-billed) or `EXTERNAL` (an outside client who is invoiced); this single flag drives grant requirements, rate selection, subsidy eligibility, and priority access throughout the system. `is_pi` marks a principal investigator who may own grants and defaults to false. New users start `ACTIVE`.

Suspension is a blunt operational tool. When a `FacilityAdmin` suspends a user, every `REQUESTED` booking of that user whose `start_at` lies in the future is `REJECTED`, and every `APPROVED` booking with a future `start_at` is `CANCELLED` with `cancellation_reason` set to `USER_SUSPENDED`, `penalty_waived` set to true, and `penalty_cents` set to zero. Each such cancellation releases the booking's grant encumbrance: the grant's `budget_encumbered_cents` decreases by the booking's `encumbered_cents`, the booking's `encumbered_cents` becomes zero, and the grant's status is recomputed, so an `EXHAUSTED` grant may recover to `ACTIVE`. Reactivation returns the user to `ACTIVE` with no cascade. Suspension is legal only from `ACTIVE` and reactivation only from `SUSPENDED`; either violation is `ERR_INVALID_STATE`.

### 3.2. The Instrument Catalog and Its Booking Policies

A `FacilityAdmin` registers each instrument with `name`, `model`, `location`, and a policy bundle: `requires_training` (default true), `booking_buffer_minutes` (default 0, never negative), `min_booking_minutes` (strictly positive), `max_booking_minutes` (at least the minimum), `cancellation_free_notice_hours` (never negative), `late_cancel_penalty_pct`, and `no_show_penalty_pct` (each a fraction between 0 and 1 inclusive). New instruments start `AVAILABLE`.

The buffer deserves emphasis because it defines what "overlap" means across the whole domain: for booking-versus-booking conflict purposes, every booking occupies the **half-open interval** from its `start_at` up to but not including its `end_at` plus the instrument's `booking_buffer_minutes`. Two buffered intervals conflict if and only if they intersect; exact adjacency — one booking's `start_at` equaling the other's buffered end — is allowed. `REQUESTED` bookings never block other bookings; only `APPROVED` and `IN_PROGRESS` bookings participate in overlap. Downtime windows behave differently: a `CONFIRMED` downtime event conflicts with bookings under **closed-interval** semantics, where touching endpoints collide; the booking side of this comparison uses its raw `start_at`–`end_at` window, the booking buffer applying only to booking-versus-booking conflicts.

Instruments cycle through `AVAILABLE`, `DOWN`, `MAINTENANCE`, and the terminal `RETIRED`. The flips to `DOWN` and `MAINTENANCE` are system-driven: confirming a downtime event of kind `UNSCHEDULED_FAILURE` on an instrument flips it to `DOWN`, and confirming one of kind `PREVENTIVE_MAINTENANCE` or `CALIBRATION` flips it to `MAINTENANCE` — but only when the event window contains the current logical time. Confirming a future-window event leaves the instrument `AVAILABLE`, though the confirmed window still blocks overlapping bookings via `ERR_DOWNTIME_CONFLICT`. Returning to service — whether triggered directly by a `FacilityAdmin` or driven by the system when a downtime event is resolved — is allowed only when no other `CONFIRMED` downtime event on that instrument has a window containing the current logical time; the instrument then becomes `AVAILABLE`. The direct return-to-service endpoint applies only to an instrument currently `DOWN` or `MAINTENANCE`; any other status — like a still-covering `CONFIRMED` window — fails `ERR_INVALID_STATE`, and re-retiring an already `RETIRED` instrument likewise fails `ERR_INVALID_STATE`.

Retirement is terminal and cascades broadly: every `REQUESTED` booking on the instrument is `REJECTED`; every `APPROVED` booking with a future `start_at` is `CANCELLED` with `cancellation_reason` `INSTRUMENT_RETIRED`, penalty waived, and zero penalty; each cancellation releases its grant encumbrance exactly as in the suspension cascade; every `CONFIRMED` downtime event on the instrument becomes `RESOLVED`; any non-terminated maintenance contract on the instrument is terminated by the system; and the instrument's line inside any rate set in `DRAFT` or `UNDER_REVIEW` status gets `flagged_for_review` set to true in its verdict entry.

### 3.3. Training and Certification

Before a user may book an instrument whose `requires_training` is true, a `CoreStaff` member (or a `FacilityAdmin`) enrolls them, creating a `TrainingRecord` for the `user_id` and `instrument_id` pair in `ENROLLED` status. At most one record with status `ENROLLED`, `CERTIFIED`, or `EXPIRED` may exist per (user, instrument) pair; `REVOKED` records do not block a fresh enrollment.

Certification is performed by `CoreStaff` and requires the user to be `ACTIVE` (`ERR_USER_SUSPENDED` otherwise) and the instrument not to be `RETIRED` (a `RETIRED` instrument fails certification with `ERR_INVALID_STATE`). On certification, `certified_at` is set to the current logical time and `expires_at` to exactly twelve months later. Certification is a step-decay credential: the record remains `CERTIFIED` until the logical clock reaches `expires_at`, at which instant it is expired (the boundary is inclusive — exactly at `expires_at` the record is treated as `EXPIRED`; one second earlier it is still valid). An `EXPIRED` record can be re-enrolled by `CoreStaff`, which returns it to `ENROLLED` and clears both `certified_at` and `expires_at` to null, starting the cycle over. Revocation from `ENROLLED`, `CERTIFIED`, or `EXPIRED` is terminal (`REVOKED`) and blocks all future booking creation and approval for that (user, instrument) pair until a brand-new record is created and certified.

At booking creation and again at booking approval, when the instrument requires training the user must hold a record whose effective status is `CERTIFIED`; absence of one is rejected with `ERR_TRAINING_REQUIRED`. When a certified record exists, its `expires_at` must be strictly after the booking's `end_at` — the certification must cover the entire session — otherwise the request fails with `ERR_TRAINING_EXPIRED`.

### 3.4. Grants and the Authorization Model

A `FinanceOfficer` creates each grant with `grant_code` (unique, non-empty), `pi_user_id`, `title`, `budget_total_cents` (strictly positive), `start_date`, `end_date` (on or after `start_date`, both inclusive chargeable dates in `YYYY-MM-DD` form), and optionally `authorized_user_ids`. The PI is always implicitly authorized to charge the grant; `authorized_user_ids` extends that to additional users.

Grants live under the computed-status regime of §2.10: a grant is `ACTIVE` unless exhausted, expired, or closed. Budget amendments by a `FinanceOfficer` — via the grant's `PUT` — may change `budget_total_cents`, `start_date`, `end_date`, or `authorized_user_ids`, and must carry `expected_grant_version` per §2.8. An amendment that would lower `budget_total_cents` below the sum of encumbered plus used is rejected with `ERR_GRANT_BUDGET_EXCEEDED`. Every amendment recomputes the grant's status.

Closing a grant is a `FinanceOfficer` action permitted from `ACTIVE`, `EXHAUSTED`, or `EXPIRED`, but only while no recharge entries on the grant sit in `PENDING`, `BILLED`, or `DISPUTED` status; otherwise the close is rejected with `ERR_GRANT_HAS_OPEN_ENTRIES`. Closing cancels nothing and releases no encumbrance: the grant's `APPROVED` bookings stand, and their encumbrance keeps counting against the grant until they complete or are cancelled — but neither creation nor approval of a booking may charge a `CLOSED` grant (`ERR_GRANT_INACTIVE`). `CLOSED` is terminal.

### 3.5. Rate Development, Break-Even Review, and the Rate Cap

Each fiscal year's prices are authored as a `RateSet`. A `FacilityAdmin` creates a set in `DRAFT` status by supplying `fiscal_year`, `effective_from`, and an array of `lines`. Each line carries an `instrument_id` (unique within the set), `internal_rate_cents_per_hour` (strictly positive), `external_rate_cents_per_hour` (at least the internal rate), `billing_increment_minutes` (strictly positive), `min_charge_minutes` (zero or more), `projected_billable_hours` (strictly positive), and `break_even_waiver_reason` (string or null). The creating operator's `X-User-ID` is recorded as `developed_by`. At most one `EFFECTIVE` set may exist per fiscal year.

While `DRAFT`, the set may be edited — `effective_from`, `lines`, or both — via its `PUT`, which must carry `expected_rate_set_version` per §2.8; replacing `lines` resets the per-line review verdicts and `flagged_for_review` flags. Every rate line, at both creation and edit time, must satisfy `external_rate_cents_per_hour` at least equal to `internal_rate_cents_per_hour`; a violation is `ERR_RATE_ORDER_INVALID`.

Submitting the set moves `DRAFT → UNDER_REVIEW` and triggers the projected break-even review. For each line, projected revenue is the line's `internal_rate_cents_per_hour` multiplied by its `projected_billable_hours`. Projected cost is the sum of `annual_cost_cents` over every `MaintenanceContract` on that instrument whose coverage window (from `coverage_start` through `coverage_end`) intersects the set's fiscal year — full annual cost each time, never prorated — plus a flat operating overhead of 120,000 cents ($1,200) per instrument. The verdict per line, recorded in `line_verdicts` as `break_even_verdict`, is `PASS` when projected revenue is at least projected cost, and `DEFICIT` otherwise; the projected review's results mirror the `lines` array element-for-element and each element additionally carries `flagged_for_review`.

The submit also enforces the year-over-year rate cap. For each line whose instrument had a line in the currently `EFFECTIVE` set of the *preceding* fiscal year, the new internal rate may not exceed the prior internal rate grown by ten percent — that is, the new rate must be less than or equal to the prior rate multiplied by 1.10 — unless the submitter supplies a non-empty `override_justification` string. A line exactly at the cap is allowed; a line beyond it without justification is rejected with `ERR_RATE_CAP_EXCEEDED`. Submitting also requires `lines` to be non-empty and every referenced instrument to be non-`RETIRED` (each violation is `ERR_INVALID_REQUEST`), and every `instrument_id` to exist (`ERR_NOT_FOUND`).

Approval moves `UNDER_REVIEW → APPROVED` and is a `FinanceOfficer` action with three preconditions: the `FiscalYearPeriod` for the set's `fiscal_year` must exist and be `OPEN` (`ERR_FY_CLOSED` otherwise); every line whose verdict is `DEFICIT` must carry a non-null `break_even_waiver_reason` (`ERR_BREAK_EVEN_WAIVER_REQUIRED` otherwise), and each waived line is then recorded as `WAIVED`; and segregation of duties forbids the approver's `X-User-ID` from equaling the set's `developed_by` (`ERR_SEGREGATION_OF_DUTIES`). Approval stamps `approved_by` with the approver's operator id. Rejection instead returns the set from `UNDER_REVIEW` to `DRAFT`, optionally carrying a `reason`.

Activation moves `APPROVED → EFFECTIVE`, gated on the current logical time being at or after `effective_from` (a too-early activation fails `ERR_INVALID_STATE`) and the fiscal year period existing and still being `OPEN` (a missing or `CLOSED` period is `ERR_FY_CLOSED`). Activation supersedes the incumbent: the previously `EFFECTIVE` set of the same fiscal year, if any, flips to `SUPERSEDED`, and its id is recorded on the new set as `supersedes_rate_set_id` (null until activation). `SUPERSEDED` is terminal. The per-line break-even computation is also exposed as a read-only diagnostic returning the `fiscal_year`, an `overall_verdict`, and the per-line verdict array; each verdict element additionally carries `projected_revenue_cents`, `projected_cost_cents`, and `suggested_internal_rate_cents_per_hour` (the suggestion computed with the fiscal year period's `carryforward_in_cents`, zero when the period does not exist). The diagnostic reports the stored review verdicts once the set has been submitted (`WAIVED` where waived) and a live computation while the set is `DRAFT`; `overall_verdict` is `DEFICIT` exactly when some line's reported verdict is `DEFICIT`, and `PASS` otherwise.

A derived-rate aid supports authoring: the suggested internal rate for a line is computed by taking projected cost for the instrument (the same contract-cost-plus-overhead formula), subtracting the fiscal year period's `carryforward_in_cents` — a positive surplus *reduces* the next year's rate base, a negative deficit *increases* it — and dividing the result by `projected_billable_hours`, rounding half-up to whole cents per line. The rounding order is pinned: each line's suggested rate is rounded to cents first, and only then does the break-even re-check run against the rounded rates.

### 3.6. Booking: Request, Approval, and the Preemption Auction

A booking is created by a `Researcher` or `ExternalClient` with `user_id`, `instrument_id`, `start_at`, `end_at`, optionally `grant_id`, and optionally `priority` (defaulting to `STANDARD`). Creation validates, in the order given in §2.9: the instrument must be `AVAILABLE` (`ERR_INSTRUMENT_UNAVAILABLE`); the user must be `ACTIVE` (`ERR_USER_SUSPENDED`); training must be satisfied when required (`ERR_TRAINING_REQUIRED`, then `ERR_TRAINING_EXPIRED`); `start_at` must be strictly in the future (`ERR_BOOKING_IN_PAST`); the duration from `start_at` to `end_at` must lie within the instrument's minimum-to-maximum booking window (`ERR_DURATION_OUT_OF_RANGE`); the buffered half-open overlap check must pass (`ERR_BOOKING_OVERLAP`); no confirmed-downtime closed-interval conflict may exist (`ERR_DOWNTIME_CONFLICT`); no duplicate — same user, same instrument, same `start_at` among bookings in `REQUESTED`, `APPROVED`, or `IN_PROGRESS` — may exist (`ERR_DUPLICATE_BOOKING`); grant affiliation must match: an `INTERNAL` user must supply a `grant_id`, an `EXTERNAL` user must not (`ERR_GRANT_AFFILIATION_MISMATCH`); the grant must resolve `ACTIVE` (`ERR_GRANT_INACTIVE`); the booking date must fall within the grant's chargeable window from `start_date` through `end_date` inclusive (`ERR_GRANT_WINDOW_VIOLATION`); and the booker must be the grant's PI or appear in `authorized_user_ids` (`ERR_GRANT_NOT_AUTHORIZED`). A successful creation lands in `REQUESTED`.

Approval by `CoreStaff` is the moment money becomes real, and it re-runs the same availability, user-active, training, overlap, downtime, grant-active, and grant-window checks against the world as it now stands. Two further gates apply at approval. First, an `EFFECTIVE` rate set must exist for the fiscal year containing the booking's `start_at` and must contain a rate line for the booking's instrument (either absence is `ERR_INVALID_STATE`). Second, fiscal capacity: for an internal booking, the grant's `budget_available_cents` must be at least the provisional estimate (`ERR_GRANT_BUDGET_EXCEEDED`).

On approval the booking pins its rate snapshot from that effective set: `rate_set_id`, `applied_rate_cents_per_hour` (the internal rate for `INTERNAL` bookers, the external rate otherwise), `applied_increment_minutes`, and `applied_min_charge_minutes`. The provisional estimate — `estimated_charge_cents` — is the scheduled minutes (the whole-minute difference between `end_at` and `start_at`) multiplied by the pinned hourly rate divided by sixty, rounded half-up to whole cents; this provisional variant applies no billing-increment ceiling, no minimum-charge floor, and no consumables. For an internal booking, `encumbered_cents` is set equal to `estimated_charge_cents` and the grant's `budget_encumbered_cents` increases by that amount; for an external booking, `encumbered_cents` stays zero. The grant's status is recomputed.

**Priority bookings and preemption.** A booking may carry `priority` `PRIORITY` only when the booker holds an `ACTIVE` `SubsidyAward` with `conveys_priority` true; `EXTERNAL` users are never eligible, and any other shortfall is `ERR_PRIORITY_NOT_AVAILABLE`. When a `PRIORITY` booking reaches approval and its window is occupied, the system selects victims — this feasibility evaluation runs at the overlap check's position in the approval-time validation order, ahead of the downtime-conflict re-check: bookings on the same instrument in `APPROVED` status with `priority` `STANDARD` whose buffered half-open intervals overlap the incoming window. Victims are ranked most-recently-created first, with earlier `start_at` breaking ties. The selection is all-or-nothing: after bumping every eligible victim, if any overlapping booking remains — one already `IN_PROGRESS`, or an `APPROVED` booking that is itself `PRIORITY` — approval fails with `ERR_PREEMPTION_BLOCKED` and *no* victim is bumped. When the victim set fully clears the window, each victim transitions to `PREEMPTED` with `cancellation_reason` `PREEMPTION`, `penalty_waived` true, and `penalty_cents` zero, and each victim's grant encumbrance is released exactly as on a cancellation, with the victim grant's status recomputed. Only then does the incoming approval complete.

Rejection of a `REQUESTED` booking by `CoreStaff` (optionally with a `reason`), or by the system during user suspension or instrument retirement, lands in the terminal `REJECTED`.

### 3.7. Cancellation, Rescheduling, and the Session Itself

Cancellation rules depend on where the booking stands. Cancelling a `REQUESTED` booking is always free: `penalty_cents` becomes zero. Cancelling an `APPROVED` booking is permitted to the owner (a `Researcher` or `ExternalClient`) or to `CoreStaff`, but only strictly before `start_at` — once the start has passed, only the no-show path applies, and attempting a cancel then fails with `ERR_INVALID_STATE`. System-driven cancellations (downtime, suspension, retirement, preemption) are exempt from this time gate. On an actor-driven cancel, `cancellation_reason` is set to `USER` for entity-backed callers and `STAFF` for `CoreStaff`, and every actor-driven cancellation records `penalty_waived` false — the waived flag is reserved for involuntary cancellations.

The penalty for cancelling an `APPROVED` booking is computed from notice. When the cancellation is involuntary — `PREEMPTION`, `DOWNTIME`, `USER_SUSPENDED`, or `INSTRUMENT_RETIRED` — `penalty_waived` is true and the penalty is zero. Otherwise, notice is the whole-minute difference between `start_at` and the current logical time; when that notice is at least the instrument's `cancellation_free_notice_hours` converted to minutes, the cancellation is free (notice exactly equal to the free window is free — the comparison is inclusive). Inside the window, `penalty_cents` is the booking's `estimated_charge_cents` multiplied by the instrument's `late_cancel_penalty_pct`, rounded half-up to cents. Whenever `penalty_cents` exceeds zero, a `PENALTY` `RechargeEntry` — with `amount_cents` equal to the penalty, `subsidy_offset_cents` zero, and `net_amount_cents` equal to the penalty — posts into the currently `OPEN` `RechargeBatch` (none open means `ERR_BATCH_NOT_OPEN`), debiting the grant or, for external users, accruing to their invoice. The booking's grant encumbrance is released on any cancellation from `APPROVED`: the grant's `budget_encumbered_cents` drops by the booking's `encumbered_cents`, the booking's `encumbered_cents` zeroes, and the grant's status is recomputed.

Rescheduling moves an `APPROVED` booking to a new `start_at`/`end_at`. The request must carry `expected_booking_version` per §2.8, and the new window re-validates the future-dated rule, the duration bounds, the buffered overlap rule, the downtime-conflict rule, and the training-currency rule (the overlap check treats a `PRIORITY` booking's window exactly as at creation — `STANDARD` `APPROVED` occupants do not block it, and no victims are preempted; preemption happens only at approval). On success the estimate is recomputed against the *pinned* rate snapshot (rates never re-pin on reschedule), the grant encumbrance adjusts by the delta, and the grant's status is recomputed.

Check-in advances an `APPROVED` booking to `IN_PROGRESS` and is allowed from fifteen minutes before `start_at` through `end_at`, inclusive at both ends; outside that window the attempt fails `ERR_INVALID_STATE`. Completing an `IN_PROGRESS` booking moves it to `COMPLETED` and releases the grant encumbrance — the actual charge will post later through the usage log's recharge entry — with the grant's status recomputed. Marking a no-show is permitted only once the current logical time has passed `start_at`; it sets the booking to `NO_SHOW`, computes `penalty_cents` as the instrument's `no_show_penalty_pct` multiplied by `estimated_charge_cents` rounded half-up to cents with `penalty_waived` false, releases the encumbrance, and posts a `PENALTY` entry to the open batch exactly as on cancellation when the penalty exceeds zero. `COMPLETED`, `CANCELLED`, `NO_SHOW`, `PREEMPTED`, and `REJECTED` are all terminal.

### 3.8. Usage Logging and Validation

After a session completes, `CoreStaff` records what actually happened in a `UsageLog` carrying `booking_id`, `actual_start_at`, `actual_end_at`, and optionally `consumable_fee_cents` (default zero, never negative). The log's `instrument_id` and `user_id` are denormalized from the booking, and the creator's operator id is recorded as `logged_by`. Exactly one usage log may exist per booking (`ERR_USAGE_LOG_EXISTS`), the booking must be `COMPLETED` (`ERR_BOOKING_NOT_COMPLETED`), and the observed window must be well-formed: `actual_end_at` strictly after `actual_start_at`, and `actual_end_at` no later than twenty-four hours after the booking's `end_at` (`ERR_USAGE_WINDOW_INVALID`). New logs start `DRAFT`.

A `DRAFT` log may be edited (its times and `consumable_fee_cents`) and then submitted, moving to `SUBMITTED`. Validation is the fiscal point of no return and is guarded by segregation of duties: the validator's `X-User-ID` must differ from the log's `logged_by` (`ERR_SEGREGATION_OF_DUTIES`). Validation re-checks that the booking is `COMPLETED` and that an `OPEN` `RechargeBatch` exists (`ERR_BATCH_NOT_OPEN`).

Validation computes the **final** charge, which differs from the provisional estimate whenever actual usage diverges from the schedule. Actual minutes are the whole-minute difference between `actual_end_at` and `actual_start_at`. `billable_minutes` is the actual minutes rounded *up* to the next whole multiple of the booking's `applied_increment_minutes`, then floored at `applied_min_charge_minutes` — the increment ceiling is applied first, the minimum-charge floor second. `usage_charge_cents` is `billable_minutes` multiplied by the pinned `applied_rate_cents_per_hour` and divided by sixty, rounded half-up to whole cents, with `consumable_fee_cents` added last and never itself rounded.

For `INTERNAL` users, validation then runs the **subsidy waterfall**. Candidate awards are the user's `SubsidyAward`s whose status resolves `ACTIVE` and whose validity window contains the entry-creation instant under half-open semantics — `valid_from` inclusive, `valid_until` exclusive. Candidates are consumed in ascending `valid_until` order, ties broken by ascending `created_at`. Starting with the full `amount_cents` as the remaining-to-cover, each award in turn contributes the smaller of its own `remaining_amount_cents` and the remaining-to-cover; the award's balance decrements and the remainder shrinks. When an award's take exactly empties it, the award becomes `EXHAUSTED` and the next award continues the same entry. The entry's `subsidy_offset_cents` is the total drawn; its `net_amount_cents` is what remains. Penalty and adjustment entries, and all entries for `EXTERNAL` users, are never subsidized — their offset is zero. For an internal user, validation also requires the grant's `budget_available_cents` to be at least the entry's `net_amount_cents` (`ERR_GRANT_BUDGET_EXCEEDED`).

Validation's side effects land together: `validated_by` records the validator's operator id; a `USAGE` `RechargeEntry` is created in the open batch with `amount_cents` equal to `usage_charge_cents`, the waterfall offset, and `net_amount_cents` their difference, starting in `PENDING` status with the entry's `grant_id`, `user_id`, `instrument_id`, `booking_id`, and `usage_log_id` populated from context (external entries carry a null `grant_id`); the grant's `budget_used_cents` increases by the net; each award drawn upon loses that much `remaining_amount_cents`; and the grant's status is recomputed. `VALIDATED` is terminal.

Rejection by `CoreStaff` — also under segregation of duties versus `logged_by`, and optionally with a `reason` — moves `SUBMITTED → REJECTED`. A `REJECTED` log is corrected by editing it and resubmitting, which returns it to `SUBMITTED`; the correction cycle may repeat.

### 3.9. Recharge Batches, Entries, and the Dispute Loop

Billing runs through monthly batches. A `FinanceOfficer` opens a `RechargeBatch` by supplying `period_year` and `period_month` (1 through 12); the pair is unique, only one `OPEN` batch may exist at any time (`ERR_DUPLICATE_OPEN_BATCH`), and the fiscal year period containing the period must exist and be `OPEN` (a missing or `CLOSED` period is `ERR_FY_CLOSED`). While `OPEN`, the batch's totals — `entry_count`, `gross_amount_cents`, `subsidy_offset_cents`, `net_amount_cents` — track their entries incrementally: the count of entries posted to the batch and the sums of `amount_cents`, `subsidy_offset_cents`, and `net_amount_cents` over them.

Finalization by a `FinanceOfficer` flips every `PENDING` entry in the batch to `BILLED`, freezes the four totals by recomputing them once — they are immutable thereafter — stamps `finalized_at`, and recomputes each affected grant's status. Finalization deliberately does *not* open the next period's batch; the `FinanceOfficer` opens each period explicitly, which keeps fiscal-year close deterministic. Corrections after finalization never touch the frozen batch — they post as `ADJUSTMENT` entries into the *next* open batch.

Entries themselves carry `batch_id`, `usage_log_id` (null for `PENALTY` and `ADJUSTMENT`), `booking_id` (null for `ADJUSTMENT`), `grant_id` (null for external invoiced entries), `user_id`, `instrument_id`, `kind` (`USAGE`, `PENALTY`, or `ADJUSTMENT`), `is_external` (true when the charged user's affiliation is `EXTERNAL`), `amount_cents` (which may be negative only for adjustments), `subsidy_offset_cents` (default zero; always zero for penalties, adjustments, and external entries), `net_amount_cents` (the amount minus the offset — this is what debits the grant or is invoiced externally), and `status`. `USAGE` and `PENALTY` entries start `PENDING`; `ADJUSTMENT` entries are created directly in `PAID` as self-settling correction records. `PAID` and `WRITTEN_OFF` are terminal.

Once `BILLED`, an entry may be marked `PAID` by a `FinanceOfficer`, or disputed by its owner or a `FinanceOfficer` with a non-empty `dispute_reason`, moving to `DISPUTED`. Dispute resolution by a `FinanceOfficer` takes a `resolution` (with an optional `note`): `UPHOLD` returns the entry to `BILLED` and clears `dispute_reason` — the dispute loop may repeat; `WRITE_OFF` moves the entry to `WRITTEN_OFF` and triggers the compensating cascade: an `ADJUSTMENT` entry is created in the currently open batch (`ERR_BATCH_NOT_OPEN` if none) with kind `ADJUSTMENT`, status `PAID`, the original's `grant_id`, `user_id`, and `instrument_id` copied across, `amount_cents` the negative of the original's amount, `subsidy_offset_cents` zero, and `net_amount_cents` likewise the negative of the original. The written-off original leaves the grant's counted set while the adjustment never counts, so the grant's `budget_used_cents` recomputes to fully credit the original charge and the grant's status is recomputed (an `EXHAUSTED` grant may recover). The subsidy is reversed too: the award that funded the original offset regains `original.subsidy_offset_cents` on its `remaining_amount_cents`, and an award may thereby recover from `EXHAUSTED` to `ACTIVE` unless it is `EXPIRED` or `REVOKED`.

### 3.10. Subsidy Applications and Awards

An internal researcher applies for support by creating a `SubsidyApplication` with `user_id`, `kind` (`STARTUP` for new-lab startup funds, which may convey priority, or `SUBSIDY` for ordinary usage subsidy), `requested_amount_cents` (strictly positive), and free-text `justification`; the application starts `DRAFT`. Creation already enforces the applicant's affiliation — a non-`INTERNAL` applicant is rejected with `ERR_SUBSIDY_INELIGIBLE` — and submitting — by the owning `Researcher`, from `DRAFT` or `REVISION_REQUESTED` — re-checks it, an `EXTERNAL` applicant again rejected with `ERR_SUBSIDY_INELIGIBLE`. A `FinanceOfficer` then moves `SUBMITTED → UNDER_REVIEW`, stamping `reviewed_by` (each subsequent FinanceOfficer review action — revision request, approval, rejection — refreshes it), and from `UNDER_REVIEW` may request revisions (optionally with a `note`), cycling back through `REVISION_REQUESTED` and re-submission as many times as needed.

Approval is the award-minting act. The `FinanceOfficer` supplies `awarded_amount_cents`, `valid_from`, `valid_until`, and `conveys_priority`; `valid_until` must be strictly after `valid_from` (`ERR_INVALID_REQUEST`). The award may not exceed the request — `awarded_amount_cents` must be strictly positive and at most `requested_amount_cents` — and `conveys_priority` true is permitted only for `STARTUP` applications; either violation is `ERR_SUBSIDY_INELIGIBLE`. Approval creates the `SubsidyAward` in `ACTIVE` status with `application_id`, `user_id`, and `kind` copied from the application, the four input fields recorded, and `remaining_amount_cents` initialized to the full award; the approval response carries the newly minted `SubsidyAward` object. One award exists per approved application. Rejection moves `UNDER_REVIEW → REJECTED`, terminal as is `APPROVED`.

Awards decay on their own schedule. When the waterfall drains an award to zero it becomes `EXHAUSTED`; when the logical clock reaches `valid_until` it becomes `EXPIRED`; either way the priority entitlement ends. A write-off reversal that restores balance while the award is still within its validity window flips `EXHAUSTED` back to `ACTIVE`. Revocation by a `FinanceOfficer` (optionally with a `reason`) is terminal from `ACTIVE`, `EXHAUSTED`, or `EXPIRED`: the remaining balance is clawed back to zero — already-applied offsets are *not* reversed — and the priority entitlement ends. While an award is `ACTIVE` with `conveys_priority` true, its holder may create `PRIORITY` bookings.

### 3.11. Maintenance Contracts and Downtime

A `FacilityAdmin` registers a `MaintenanceContract` with `instrument_id`, `vendor`, `sla_response_hours` (strictly positive), `coverage_start`, `coverage_end` (on or after `coverage_start`, both inclusive `YYYY-MM-DD` dates), and `annual_cost_cents` (strictly positive). The overlap rule is half-open on dates: an instrument may not hold two contracts whose status is anything other than `TERMINATED` and whose coverage windows overlap, but touching boundaries — one contract's `coverage_end` equaling another's `coverage_start` — are allowed; a violation is `ERR_CONTRACT_OVERLAP`. The annual cost counts once, in full and never prorated, toward the break-even and true-up costs of every fiscal year the coverage window intersects. Contracts report `EXPIRED` once the logical date passes `coverage_end`, and termination by a `FacilityAdmin` (optionally with a `reason`) or by the system on instrument retirement is terminal; a terminated contract no longer satisfies the contract requirement for new preventive-maintenance events.

Downtime is reported by `CoreStaff` or a `FacilityAdmin` with `instrument_id`, `kind` (`UNSCHEDULED_FAILURE`, `PREVENTIVE_MAINTENANCE`, or `CALIBRATION`), `start_at`, `end_at` (strictly after `start_at`, and *inclusive* for conflict purposes — touching endpoints collide), optionally `maintenance_contract_id`, and free-text `notes`. For `PREVENTIVE_MAINTENANCE` the `maintenance_contract_id` is required and must reference an `ACTIVE` contract whose coverage window contains the event window — judged on the event's start and end calendar dates against the contract's `coverage_start`/`coverage_end` — (`ERR_CONTRACT_REQUIRED`); for the other kinds it is optional. New events start `REPORTED`.

Confirmation — by `CoreStaff` or `FacilityAdmin`, and only while the instrument is not `RETIRED` — is the cascade point. If the event's window contains the current logical time, the instrument flips to `DOWN` for `UNSCHEDULED_FAILURE` or to `MAINTENANCE` for the other kinds; a future-window confirm leaves the instrument `AVAILABLE` but the confirmed window still blocks bookings. Every booking on the instrument whose interval intersects the downtime window under closed-interval semantics is resolved: `APPROVED` bookings are `CANCELLED` with `cancellation_reason` `DOWNTIME`, penalty waived and zeroed; `REQUESTED` bookings are `REJECTED`; and each cancelled booking's grant encumbrance is released exactly as in the suspension cascade, with the grant's status recomputed. Resolving a `CONFIRMED` event returns the instrument to `AVAILABLE` provided no other confirmed event's window contains the current logical time; resolution also happens automatically on instrument retirement. Cancelling a `REPORTED` event (an erroneous report) moves it to `CANCELLED`, terminal like `RESOLVED`.

### 3.12. Publications and Acknowledgment Tracking

The facility tracks its scientific impact through reported publications. A `Researcher` or `ExternalClient` reports one with `user_id`, `title`, `journal`, `published_at` (`YYYY-MM-DD`), `acknowledges_core`, a non-empty `instrument_ids` array whose every element must reference an existing instrument, and conditionally `non_ack_reason`. When `acknowledges_core` is false, `non_ack_reason` is required and non-empty (`ERR_ACK_REASON_REQUIRED`). Reports start `REPORTED`.

Verification by `CoreStaff` requires evidence: the reporting user must have at least one `VALIDATED` usage log whose `instrument_id` appears in the publication's `instrument_ids`; without one the verification fails with `ERR_PUBLICATION_EVIDENCE_MISSING`. On success the publication becomes `VERIFIED` and `verified_by` records the verifier's operator id. Rejection moves it to `REJECTED` (optionally with a `reason`); both outcomes are terminal.

### 3.13. Fiscal-Year Close, True-Up, and Carryforward

A `FinanceOfficer` opens each fiscal year by creating a `FiscalYearPeriod` with `fiscal_year` (unique) and optionally `carryforward_in_cents` (default zero; a signed value where positive means surplus carried in and negative means deficit). The period starts `OPEN`.

Closing the year is permitted only when no `RechargeBatch` whose period falls inside the closing year remains `OPEN` (`ERR_UNFINALIZED_BATCHES`). The close computes the accrual true-up. The counted set is the year's recharge entries of kind `USAGE` or `PENALTY` whose batch period falls inside the fiscal year. The official accrual revenue — `revenue_cents` — is the sum of `net_amount_cents` over counted entries whose status at close time is `BILLED` or `PAID`; written-off entries are excluded as reversed. An informational cash variant, `cash_revenue_cents`, sums the same set but counts only entries `PAID` at close time; the two figures diverge whenever any counted entry is billed-but-unpaid at close, and the accrual figure is the official one carried forward. `cost_cents` is the sum of `annual_cost_cents` over every maintenance contract whose coverage window intersects the fiscal year — full cost, no proration — plus 120,000 cents of operating overhead for each instrument that has at least one counted revenue entry in the year. `surplus_deficit_cents` is revenue minus cost, signed; `carryforward_out_cents` equals it; and `closed_at` stamps the close. `CLOSED` is terminal.

The close then cascades forward. If the next fiscal year's period does not exist, it is auto-created in `OPEN` status with `carryforward_in_cents` set to this year's `carryforward_out_cents`. That new carryforward propagates into every rate set in `DRAFT` or `UNDER_REVIEW` for the next fiscal year: the derived-rate computation re-runs against the next-year period's `carryforward_in_cents` — the newly auto-created value, or the pre-existing period's own carryforward when that period already exists — (projected cost minus the signed carryforward, divided by projected hours, each line's suggestion rounded half-up to cents first), and any re-derived line whose stored internal rate deviates from the new suggestion by more than five percent of the suggestion's absolute value — a zero suggestion flags any non-zero stored rate — gets `flagged_for_review` set to true in its verdict entry; a flag once set by these cascades is never cleared by them.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource, including all state-transition actions, return `200 OK`. The table below is a summary only — request bodies, response payloads, and side effects are defined by the narratives in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/users` | Register a facility user | FacilityAdmin |
| GET | `/users` | List users with filters | FacilityAdmin, CoreStaff, FinanceOfficer |
| GET | `/users/{id}` | Get one user; entity-backed roles read only themselves | FacilityAdmin, CoreStaff, FinanceOfficer, Researcher, ExternalClient |
| POST | `/users/{id}/suspend` | Suspend a user; future bookings rejected or cancelled with encumbrance release | FacilityAdmin |
| POST | `/users/{id}/reactivate` | Reactivate a suspended user | FacilityAdmin |
| POST | `/instruments` | Register an instrument with its booking and cancellation policy | FacilityAdmin |
| GET | `/instruments` | List instruments | FacilityAdmin, CoreStaff, FinanceOfficer, Researcher, ExternalClient |
| GET | `/instruments/{id}` | Get one instrument | FacilityAdmin, CoreStaff, FinanceOfficer, Researcher, ExternalClient |
| POST | `/instruments/{id}/retire` | Retire an instrument; cascades bookings, downtime, contracts, draft rate lines | FacilityAdmin |
| POST | `/instruments/{id}/return-to-service` | Return a DOWN/MAINTENANCE instrument to AVAILABLE | FacilityAdmin |
| POST | `/training-records` | Enroll a user for training on an instrument | CoreStaff, FacilityAdmin |
| GET | `/training-records` | List training records; entity-backed roles force-filtered to themselves | CoreStaff, FacilityAdmin, Researcher, ExternalClient |
| GET | `/training-records/{id}` | Get one training record | CoreStaff, FacilityAdmin, Researcher, ExternalClient |
| POST | `/training-records/{id}/certify` | Certify an ENROLLED record (12-month validity) | CoreStaff |
| POST | `/training-records/{id}/re-enroll` | Re-enroll an EXPIRED record back to ENROLLED | CoreStaff |
| POST | `/training-records/{id}/revoke` | Revoke a training record (terminal) | CoreStaff |
| POST | `/grants` | Create a grant funding source | FinanceOfficer |
| GET | `/grants` | List grants; Researcher filtered to own PI/authorized grants | FacilityAdmin, CoreStaff, FinanceOfficer, Researcher |
| GET | `/grants/{id}` | Get one grant (Researcher only if PI or authorized) | FacilityAdmin, CoreStaff, FinanceOfficer, Researcher |
| PUT | `/grants/{id}` | Amend budget/window/authorized users; OCC on grant version | FinanceOfficer |
| POST | `/grants/{id}/close` | Close a grant with no open entries | FinanceOfficer |
| POST | `/rate-sets` | Author a DRAFT rate set with embedded rate lines | FacilityAdmin |
| GET | `/rate-sets` | List rate sets | FacilityAdmin, FinanceOfficer |
| GET | `/rate-sets/{id}` | Get one rate set including line verdicts | FacilityAdmin, FinanceOfficer |
| PUT | `/rate-sets/{id}` | Edit a DRAFT rate set; OCC on rate-set version | FacilityAdmin |
| POST | `/rate-sets/{id}/submit` | Submit for review; runs projected break-even and rate-cap checks | FacilityAdmin |
| POST | `/rate-sets/{id}/approve` | Approve an UNDER_REVIEW set (SoD, waivers, FY open) | FinanceOfficer |
| POST | `/rate-sets/{id}/reject` | Send an UNDER_REVIEW set back to DRAFT | FinanceOfficer |
| POST | `/rate-sets/{id}/activate` | Activate an APPROVED set; supersedes the incumbent EFFECTIVE set | FinanceOfficer |
| GET | `/rate-sets/{id}/break-even` | Computed per-line projected break-even review | FacilityAdmin, FinanceOfficer |
| POST | `/bookings` | Create a booking request (REQUESTED) | Researcher, ExternalClient |
| GET | `/bookings` | List bookings; entity-backed roles force-filtered to their own | FacilityAdmin, CoreStaff, FinanceOfficer, Researcher, ExternalClient |
| GET | `/bookings/{id}` | Get one booking (entity-backed roles: own only) | FacilityAdmin, CoreStaff, FinanceOfficer, Researcher, ExternalClient |
| POST | `/bookings/{id}/approve` | Approve a REQUESTED booking: pin rate snapshot, encumber, preempt | CoreStaff |
| POST | `/bookings/{id}/reject` | Reject a REQUESTED booking | CoreStaff |
| POST | `/bookings/{id}/cancel` | Cancel a REQUESTED (free) or APPROVED (penalty rules) booking | Researcher, ExternalClient, CoreStaff |
| POST | `/bookings/{id}/reschedule` | Move an APPROVED booking; OCC on booking version; re-validates window | Researcher, ExternalClient, CoreStaff |
| POST | `/bookings/{id}/check-in` | Check in an APPROVED booking (15 minutes early until end) | CoreStaff |
| POST | `/bookings/{id}/complete` | Complete an IN_PROGRESS booking; release encumbrance | CoreStaff |
| POST | `/bookings/{id}/no-show` | Mark an APPROVED booking NO_SHOW after start; penalty entry posts | CoreStaff |
| POST | `/usage-logs` | Create a DRAFT usage log for a COMPLETED booking | CoreStaff |
| GET | `/usage-logs` | List usage logs; entity-backed roles force-filtered | CoreStaff, FacilityAdmin, FinanceOfficer, Researcher, ExternalClient |
| GET | `/usage-logs/{id}` | Get one usage log | CoreStaff, FacilityAdmin, FinanceOfficer, Researcher, ExternalClient |
| PUT | `/usage-logs/{id}` | Edit a DRAFT or REJECTED usage log | CoreStaff |
| POST | `/usage-logs/{id}/submit` | Submit a DRAFT or REJECTED log for validation | CoreStaff |
| POST | `/usage-logs/{id}/validate` | Validate a SUBMITTED log: final charge, subsidy waterfall, USAGE entry | CoreStaff |
| POST | `/usage-logs/{id}/reject` | Reject a SUBMITTED log back for correction (SoD) | CoreStaff |
| POST | `/recharge-batches` | Open a billing batch for a period (one OPEN at a time) | FinanceOfficer |
| GET | `/recharge-batches` | List batches | FinanceOfficer |
| GET | `/recharge-batches/{id}` | Get one batch | FinanceOfficer |
| POST | `/recharge-batches/{id}/finalize` | Finalize: PENDING entries to BILLED, totals frozen | FinanceOfficer |
| GET | `/recharge-entries` | List entries; entity-backed roles force-filtered | FinanceOfficer, Researcher, ExternalClient |
| GET | `/recharge-entries/{id}` | Get one entry | FinanceOfficer, Researcher, ExternalClient |
| POST | `/recharge-entries/{id}/dispute` | Dispute a BILLED entry (owner or finance) | Researcher, ExternalClient, FinanceOfficer |
| POST | `/recharge-entries/{id}/resolve-dispute` | Resolve: UPHOLD returns to BILLED; WRITE_OFF credits with ADJUSTMENT | FinanceOfficer |
| POST | `/recharge-entries/{id}/mark-paid` | Mark a BILLED entry PAID | FinanceOfficer |
| POST | `/subsidy-applications` | Create a subsidy/startup application (INTERNAL only) | Researcher |
| GET | `/subsidy-applications` | List applications; Researcher filtered to own | FinanceOfficer, FacilityAdmin, Researcher |
| GET | `/subsidy-applications/{id}` | Get one application | FinanceOfficer, FacilityAdmin, Researcher |
| POST | `/subsidy-applications/{id}/submit` | Submit a DRAFT or REVISION_REQUESTED application (owner) | Researcher |
| POST | `/subsidy-applications/{id}/review` | Move SUBMITTED to UNDER_REVIEW | FinanceOfficer |
| POST | `/subsidy-applications/{id}/request-revision` | Send UNDER_REVIEW to REVISION_REQUESTED | FinanceOfficer |
| POST | `/subsidy-applications/{id}/approve` | Approve and mint the SubsidyAward | FinanceOfficer |
| POST | `/subsidy-applications/{id}/reject` | Reject an UNDER_REVIEW application | FinanceOfficer |
| GET | `/subsidy-awards` | List awards; Researcher filtered to own | FinanceOfficer, Researcher |
| GET | `/subsidy-awards/{id}` | Get one award | FinanceOfficer, Researcher |
| POST | `/subsidy-awards/{id}/revoke` | Revoke an award (terminal); remaining clawed back | FinanceOfficer |
| POST | `/maintenance-contracts` | Create a contract; non-terminated windows on an instrument must not overlap | FacilityAdmin |
| GET | `/maintenance-contracts` | List contracts | FacilityAdmin, CoreStaff, FinanceOfficer |
| GET | `/maintenance-contracts/{id}` | Get one contract | FacilityAdmin, CoreStaff, FinanceOfficer |
| POST | `/maintenance-contracts/{id}/terminate` | Terminate a contract (terminal) | FacilityAdmin |
| POST | `/downtime-events` | Report a downtime event (PREVENTIVE_MAINTENANCE needs covering contract) | CoreStaff, FacilityAdmin |
| GET | `/downtime-events` | List downtime events | FacilityAdmin, CoreStaff, FinanceOfficer, Researcher, ExternalClient |
| GET | `/downtime-events/{id}` | Get one downtime event | FacilityAdmin, CoreStaff, FinanceOfficer, Researcher, ExternalClient |
| POST | `/downtime-events/{id}/confirm` | Confirm: instrument DOWN/MAINTENANCE; bookings cancelled or rejected | CoreStaff, FacilityAdmin |
| POST | `/downtime-events/{id}/resolve` | Resolve; instrument returns to AVAILABLE when clear | CoreStaff, FacilityAdmin |
| POST | `/downtime-events/{id}/cancel` | Cancel a REPORTED event | CoreStaff, FacilityAdmin |
| POST | `/publications` | Report a publication; acknowledgment-reason rule applies | Researcher, ExternalClient |
| GET | `/publications` | List publications | FacilityAdmin, CoreStaff, FinanceOfficer, Researcher, ExternalClient |
| GET | `/publications/{id}` | Get one publication | FacilityAdmin, CoreStaff, FinanceOfficer, Researcher, ExternalClient |
| POST | `/publications/{id}/verify` | Verify with usage evidence on a listed instrument | CoreStaff |
| POST | `/publications/{id}/reject` | Reject a REPORTED publication | CoreStaff |
| POST | `/fiscal-years` | Open a fiscal year period | FinanceOfficer |
| GET | `/fiscal-years` | List fiscal year periods | FinanceOfficer, FacilityAdmin |
| GET | `/fiscal-years/{id}` | Get one fiscal year period | FinanceOfficer, FacilityAdmin |
| POST | `/fiscal-years/{id}/close` | Close: accrual true-up, carryforward, next-year rate re-derivation | FinanceOfficer |
| POST | `/_clock/set_current_utc` | Set the server's logical clock (test-driving) | FacilityAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error live in the narratives of §2 and §3; this table is the canonical id-to-status mapping only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_BATCH_NOT_OPEN` | 409 |
| `ERR_FY_CLOSED` | 409 |
| `ERR_GRANT_HAS_OPEN_ENTRIES` | 409 |
| `ERR_INSTRUMENT_UNAVAILABLE` | 409 |
| `ERR_USER_SUSPENDED` | 403 |
| `ERR_TRAINING_REQUIRED` | 422 |
| `ERR_TRAINING_EXPIRED` | 422 |
| `ERR_BOOKING_IN_PAST` | 422 |
| `ERR_DURATION_OUT_OF_RANGE` | 422 |
| `ERR_BOOKING_OVERLAP` | 409 |
| `ERR_DOWNTIME_CONFLICT` | 409 |
| `ERR_CONTRACT_OVERLAP` | 409 |
| `ERR_USAGE_WINDOW_INVALID` | 422 |
| `ERR_CONTRACT_REQUIRED` | 422 |
| `ERR_UNIQUE_CONSTRAINT` | 409 |
| `ERR_DUPLICATE_OPEN_BATCH` | 409 |
| `ERR_DUPLICATE_BOOKING` | 409 |
| `ERR_USAGE_LOG_EXISTS` | 409 |
| `ERR_RATE_ORDER_INVALID` | 422 |
| `ERR_PRIORITY_NOT_AVAILABLE` | 422 |
| `ERR_PREEMPTION_BLOCKED` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_PUBLICATION_EVIDENCE_MISSING` | 422 |
| `ERR_ACK_REASON_REQUIRED` | 422 |
| `ERR_GRANT_AFFILIATION_MISMATCH` | 422 |
| `ERR_GRANT_INACTIVE` | 422 |
| `ERR_GRANT_WINDOW_VIOLATION` | 422 |
| `ERR_GRANT_NOT_AUTHORIZED` | 403 |
| `ERR_GRANT_BUDGET_EXCEEDED` | 422 |
| `ERR_RATE_CAP_EXCEEDED` | 422 |
| `ERR_BREAK_EVEN_WAIVER_REQUIRED` | 422 |
| `ERR_SUBSIDY_INELIGIBLE` | 422 |
| `ERR_BOOKING_NOT_COMPLETED` | 400 |
| `ERR_UNFINALIZED_BATCHES` | 409 |
