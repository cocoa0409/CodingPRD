# Marching Band Program API — Product Requirements Document

## 1. Introduction

A high school marching band season is a logistics operation disguised as a music program. Between the first roster posting and the last bus ride home, a director juggles an instrument locker full of school-owned brass and percussion, a uniform room of jackets, bibbers, shakos, plumes and gloves, a calendar of rehearsals, sectionals, competitions and fundraisers, a library of licensed charts, chair auditions with judging rubrics, booster-club money, and one or more chartered equipment trucks. Each of these concerns carries its own money flow — rental fees, late fees, cleaning charges, trip cost shares, fundraiser credits — and each is entangled with the others: a student cannot board the bus while delinquent on fees, a plume cannot be issued without a shako, a trip roster cannot lock until a truck charter exists for the event, and a season cannot close while a single sousaphone is still checked out.

This document specifies a REST API, mounted under `/band`, that manages the full season lifecycle of a band program. It governs program configuration and lifecycle gating; student enrollment, suspension, and withdrawal; instrument checkout, renewal, return, and maintenance; uniform fitting, issuance, and the cleaning-batch cycle; music arrangement licensing under segregation of duties; event scheduling with weather contingencies; trip planning, roster management, cost-share finalization, and refunds; an append-only payment ledger with waterfall allocation; fundraiser credit distribution; audition scoring with two selectable scoring variants and a chair-challenge window; and equipment-truck chartering with buffered scheduling windows and capacity checks.

A deliberate design commitment runs through the whole API: every dollar a student owes or has paid lives in one append-only ledger, every deadline is evaluated against a controllable logical clock, and every genuinely concurrent write is guarded by optimistic concurrency control. Implementers should read §2 for the system-wide contracts, §3 for the business workflows in narrative form, §4 for the endpoint index, and §5 for the error catalogue.

## 2. Global Specifications & System-Wide Principles

This section defines the contracts that hold across every resource and endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. A request with a missing or malformed header, or a role value outside the declared set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The declared roles are `BandDirector`, `AssistantDirector`, `BoosterTreasurer`, `EquipmentManager`, `SectionLeader`, `Student`, and the collective read marker `Any`. A request whose role is authenticated but not listed among the roles permitted for the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

The identity carried in `X-User-ID` differs by role. When `X-User-Role` is `Student`, `X-User-ID` is the `id` of the acting `Student` record; ownership checks on any resource that references a student compare the resource's `student_id` field to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403). When `X-User-Role` is `SectionLeader`, `X-User-ID` is likewise the `id` of the acting `Student` record — a section leader is first of all a student — and endpoints that gate on section leadership additionally require that student's `is_section_leader` flag to be true, and that the student's `section` match the section scope of the target resource, else the request is rejected with `ERR_SECTION_LEADER_REQUIRED` (HTTP 403) or `ERR_FORBIDDEN_OWNERSHIP` as applicable. When `X-User-Role` is `BandDirector`, `AssistantDirector`, `BoosterTreasurer`, or `EquipmentManager`, `X-User-ID` is an opaque staff identifier not tied to any persisted entity; the server may record it (for example, as `creator_user_id` or `approver_user_id` on a `MusicArrangement`) but never compares it to any entity's `id`.

Role responsibilities in brief: the `BandDirector` is the program head and holds a superset of operations, subject to the segregation-of-duties rule on arrangement approval. The `AssistantDirector` is the second staff conductor and shares day-to-day scheduling, student, trip, audition, and enrollment work. The `BoosterTreasurer` owns all money movement: ledger posting, fundraisers, arrangement purchases, and trip finalization. The `EquipmentManager` owns instruments, uniforms, the cleaning cycle, and truck logistics. A `SectionLeader` may request arrangements and file chair challenges for their own section. A `Student` may enroll themselves in trips, excuse themselves, and read their own data. All roles, marked as `Any` in §4, may call every read endpoint.

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

Requests that match no declared route, or a declared path with an unsupported method, are rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.3. Pagination

List endpoints accept two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0. A non-integer or out-of-range `limit` or `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). All list endpoints sort by `created_at` ascending, with ties falling to storage insertion order. The `meta` object of every list response carries `limit`, `offset`, `total_count`, and `has_more`; `total_count` counts every matching item before paging, and `has_more` is true exactly when `offset` plus `limit` is strictly less than `total_count`. List endpoints additionally accept optional equality filters on their resource's foreign-key and enum fields (for example `program_id`, `status`, `section`, `student_id`); each supplied filter narrows the list to exact matches.

### 2.4. Common Resource Properties

Every primary resource carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation.
- `version` (integer): starts at 1 at creation and increments by exactly 1 on every mutation of the resource, including mutations driven by cascading side effects — with one exception: the ledger-driven recomputation of a student's `account_balance_cents` and `is_delinquent` and of an enrollment's `net_paid_cents`, `refunded_cents`, and `payment_status` upon the posting of a `Payment` row does not increment `version` or refresh `updated_at` on those records.

Two resources are deliberately exempt from the full set. `Payment` rows and `TruckLoad` rows are append-only ledger and manifest records: they carry only `id` and `created_at`, and both `updated_at` and `version` are absent from them entirely. Every other resource carries all four fields.

### 2.5. Monetary Precision and Rounding

All money in the system is integer cents; no fractional cents ever appear in stored fields or responses. Wherever a calculation must produce a non-integer intermediate, the rule attached to that calculation governs: rental late fees and trip refund tiers round half up to the nearest cent; cleaning batch lines round half up per garment line before summing; trip cost shares round half up to the nearest cent; fundraiser credits floor each participant's raw share before the remainder distribution; audition composite scores under the raw-weighted variant round half up to two decimal places and, together with the cleaning batch's `discount_pct` (0, 0.15, or 0.25), are the only non-integer numbers in the system. The phrases "round half up" and "floor" in this document are exact contracts, not approximations: half-up means a fraction of exactly one half rounds away from zero.

### 2.6. The Logical Clock and Time-Driven Transitions

The system never reads wall-clock time. All temporal evaluation is driven by a logical clock exposed through an admin-only test-driving capability that advances the clock to a supplied `to_iso8601` instant; the supplied instant is accepted unconditionally — any valid ISO 8601 instant may be set, even one earlier than the current logical time — and the endpoint returns the current logical time as `current_utc`. Before any such call, the logical clock starts at exactly 2026-08-01T00:00:00Z and never falls back to the wall clock. Advancing the clock evaluates all time-based transitions lazily, both at the moment the clock is set and on any subsequent read of an affected resource. Two transitions are driven this way: an `InstrumentAssignment` whose `due_date` has passed while still `ACTIVE` flips to `OVERDUE`, and a `MusicArrangement` whose `rights_end` has passed while still `LICENSED_ACTIVE` flips to `EXPIRED`. All timestamps recorded by the system — `checkout_at`, `returned_at`, `issued_at`, `published_at`, and the `api_request_timestamp` of every response envelope — are read from this logical clock.

### 2.7. The Append-Only Payment Ledger

Every dollar owed or paid by a student flows through the `Payment` ledger. Ledger rows are immutable once posted: there are no updates and no deletions, only compensating rows. The `kind` of a row is one of `PAYMENT`, `REFUND`, `WAIVER`, `MANUAL_DEBIT`, `RENTAL_FEE_DEBIT`, `LATE_FEE_DEBIT`, `CLEANING_FEE_DEBIT`, `TRIP_SHARE_DEBIT`, or `FUNDRAISING_CREDIT`. Clients posting a ledger row may use only `PAYMENT`, `REFUND`, `WAIVER`, or `MANUAL_DEBIT`; the five remaining kinds are system-only, and a client request naming one of them is rejected with `ERR_INVALID_REQUEST` (HTTP 400). The `amount_cents` of any client-posted row must be a positive integer, again else `ERR_INVALID_REQUEST`. A client-posted `REFUND` or `WAIVER` row must name the row it compensates via `reference_payment_id` — omitting it is `ERR_INVALID_REQUEST` (HTTP 400) — and the referenced row is validated for existence only (`ERR_PAYMENT_NOT_FOUND`), as is a `reference_payment_id` supplied on any other client-postable kind. A refund may not exceed the student's net cash paid — the sum of all `PAYMENT` rows minus the sum of all `REFUND` rows across the student's ledger — else `ERR_REFUND_EXCEEDS_PAID` (HTTP 422). System-posted rows are exempt from the reference and positivity rules: the refund rows posted by the excuse, cancellation, and withdrawal cascades carry no `reference_payment_id`, and a zero-share participant in a fundraiser close receives a zero-amount `FUNDRAISING_CREDIT` row. A row may optionally carry a free-text `note` and, for trip-related money, a `trip_enrollment_id` linking it to a specific enrollment; rows posted by the fundraiser close carry a `fundraiser_id`.

A student's `account_balance_cents` is derived from the ledger alone: the sum of the amounts of all debit-kind rows (`MANUAL_DEBIT`, `RENTAL_FEE_DEBIT`, `LATE_FEE_DEBIT`, `CLEANING_FEE_DEBIT`, `TRIP_SHARE_DEBIT`), minus the sum of the amounts of all credit-kind rows (`PAYMENT`, `WAIVER`, `FUNDRAISING_CREDIT`), plus the sum of the amounts of all `REFUND` rows. A positive balance means the student owes the program; a negative balance is a credit in the student's favor. The ledger is the single source of truth — the derived balance must always equal what a fresh aggregation of the ledger produces.

### 2.8. Delinquency and Fiscal Gates

A program declares a tolerance for unpaid balances in `delinquency_grace_cents` (default 2500 cents, i.e. $25.00). A student whose `account_balance_cents` is strictly greater than this threshold is delinquent, surfaced as the derived boolean `is_delinquent`; a balance exactly equal to the threshold is not delinquent. Delinquency has teeth in three places: creating a new financial obligation for the student (checking out an instrument, or enrolling in a trip) is rejected with `ERR_STUDENT_DELINQUENT_FEES` (HTTP 402), and reinstating a suspended student is likewise rejected with `ERR_STUDENT_DELINQUENT_FEES` while the balance remains strictly above the grace amount. Fiscal checks are always evaluated last in the validation order — after authentication, existence, state, and constraint checks — so a request that fails both a state rule and a fiscal rule surfaces the state error, never the fiscal one.

### 2.9. Program Posture: Which Phases Permit Child Creation

A `BandProgram` moves its `status` field through `SETUP`, `ENROLLMENT_OPEN`, `SEASON_ACTIVE`, and `CLOSED` in that order. Creation of a program-scoped child resource is permitted only while the program is in `ENROLLMENT_OPEN` or `SEASON_ACTIVE`. The gated creations are exactly: students, instruments, instrument assignments, uniforms, uniform assignments, cleaning batches, arrangements, events, fundraisers, auditions, and truck charters — for instrument and uniform assignments the gate reads the referenced student's program. Trips, trip enrollments, audition entries, ledger postings, and truck loads are created without any posture check. Attempting a gated creation while the program is in `SETUP` or `CLOSED` is rejected with `ERR_PROGRAM_NOT_IN_REQUIRED_STATE` (HTTP 409). This posture gate is evaluated before any child-specific business rule, so a create against a closed program surfaces the posture error even if the payload is otherwise invalid in some later-checked way.

### 2.10. Optimistic Concurrency Control

Three write operations are protected by optimistic concurrency control, each keyed to a parent entity's `version`.

Updating a program's configuration requires the request to carry `expected_program_version` holding the `version` of the `BandProgram` the client last observed. If the program's current `version` differs — because another writer has since patched budgets, thresholds, or modes — the update is rejected with `ERR_STALE_VERSION` (HTTP 412). The version check runs after payload validation.

Creating a trip requires the request to carry `expected_event_version` holding the `version` of the parent `Event` the client last observed. Because creating a trip legitimately supersedes the event's existing `PLANNING` trip, a writer acting on a stale view of the event is refused: a mismatch with the event's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). The version check runs immediately after the event's existence check, before the one-live-trip conflict rule of §3.6.

Publishing chair placements for an audition requires the request to carry `expected_audition_version` holding the `version` of the `Audition` the client last observed. Because a publish legitimately supersedes the audition's prior published placement set, a stale writer is refused: a mismatch with the audition's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). Here the audition's state check runs first: a publish against an audition not in `SCORES_FINALIZED` surfaces `ERR_AUDITION_SCORES_NOT_FINAL` even when the version is also stale.

These three fields are non-optional on their respective endpoints. No other endpoint takes a version field.

### 2.11. Validation Order

Every request is validated against the following checks in strict priority order; the first failure encountered produces the response and no later check runs. Two refinements pin that order at the edges. Payload shape — a JSON object body carrying no undeclared fields, all required fields present, every scalar coercible to its declared type, and, for ledger posting, the client-postable-`kind` and positive-`amount_cents` rules of §2.7 — is validated before the numbered checks and surfaces `ERR_INVALID_REQUEST` (HTTP 400); on endpoints addressed by a path identifier, the path resource is loaded before the body is examined, so its not-found error precedes shape validation. And where ownership is judged from a stored resource rather than a request-body `student_id` (excusing an enrollment, challenging an audition), the resource's existence check necessarily precedes the ownership gate.

1. Authentication headers are present and the role is a declared role — else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. The acting role is permitted for this endpoint — else `ERR_UNAUTHORIZED_ROLE`.
3. Ownership: a `Student` actor may act only on resources whose `student_id` equals their `X-User-ID`, and a `SectionLeader` must additionally hold `is_section_leader` with a matching `section` where the endpoint is section-scoped — else `ERR_FORBIDDEN_OWNERSHIP` or `ERR_SECTION_LEADER_REQUIRED`. Read endpoints perform no ownership check — every declared role may read every resource.
4. Path identifiers exist, validated left to right — else the corresponding `ERR_<RESOURCE>_NOT_FOUND`.
5. Foreign keys in the request body (`student_id`, `instrument_id`, `uniform_id`, `trip_id`, `audition_id`, `charter_id`, `event_id`, `reference_payment_id`, and participant student ids) exist — else the corresponding `ERR_<RESOURCE>_NOT_FOUND`. Foreign keys are validated for existence only: no cross-program consistency check is performed between a referenced student and a referenced instrument, uniform, trip, or audition.
6. Program posture: child creation requires the program in `ENROLLMENT_OPEN` or `SEASON_ACTIVE` — else `ERR_PROGRAM_NOT_IN_REQUIRED_STATE`.
7. The target entity is in the state its transition requires — else the domain-specific state error (`ERR_INSTRUMENT_NOT_AVAILABLE`, `ERR_BATCH_NOT_OPEN`, and so on), falling back to `ERR_INVALID_STATE` where no specific code applies.
8. Business safety: an `UNPLAYABLE` instrument may not be assigned, and a truck load may not exceed capacity — else `ERR_INSTRUMENT_UNPLAYABLE`, `ERR_TRUCK_OVERWEIGHT`, or `ERR_TRUCK_OVERVOLUME`.
9. Temporal windows are sane: an event's `ends_at` strictly after `starts_at`, a charter's `window_end` strictly after `window_start`, an assignment's `due_date` strictly after checkout, an arrangement's `rights_end` in the future, a challenge inside its seven-day window — else `ERR_EVENT_WINDOW_INVALID`, `ERR_DUE_DATE_INVALID`, `ERR_LICENSE_WINDOW_INVALID`, or `ERR_CHALLENGE_WINDOW_EXPIRED`.
10. Uniqueness and conflict rules: facility overlap, vehicle overlap, duplicate serial numbers, duplicate judge scores, score range, one active trip per event, duplicate enrollments, garment-type and instrument-type uniqueness, weather-watch only outdoors — else the matching conflict error.
11. Cross-entity references are in their required states: the shako held before the plume, the charter present before roster lock, scores finalized before publish, the loaded instrument not retired or in maintenance — else the matching referential error. A referenced student's `ENROLLED` requirement is evaluated earlier than this item on the creations that require it (instrument checkout, uniform issue, trip enrollment, audition entry) — immediately after program posture, before item 7's state checks — and on fundraiser close it is evaluated per participant after the `ERR_FUNDRAISER_NOT_OPEN` check.
12. Money last: the student is not delinquent, budgets are not exceeded, and the refund does not exceed net cash paid — else the matching fiscal error.

This ordering is observable: when two rules fail simultaneously, the response always carries the earlier-priority error.

### 2.12. Hierarchical Consistency and Cascading Reconciliation

State changes propagate. Cancelling an event cancels its trip, which excuses its enrollments, which posts refunds, which recompute student balances; withdrawing a student forces the return of instruments and uniforms and excuses trip seats; receiving a cleaning batch posts per-student cleaning charges and returns garments to storage. Each of these cascades is atomic in effect: every dependent resource lands in its reconciled state, and every mutated resource has its `updated_at` refreshed and its `version` incremented. Derived aggregates — `music_spent_cents`, `repair_spent_cents`, `garment_count`, `registered_count`, `confirmed_count`, `loaded_weight_lb`, `loaded_volume_cuft`, `allocated_credit_cents`, and the student's `account_balance_cents` and `is_delinquent` — are recomputed from their source rows on every mutation that touches them, never patched incrementally in a way that could drift. Two exceptions are pinned: posting a ledger row recomputes the student's and any linked enrollment's derived money fields without bumping those records' versions (§2.4), and the trip-cancellation cascades — event-driven or direct — excuse enrollments without recomputing the trip's `registered_count` and `confirmed_count`.

### 2.13. Nested Resource Retrieval

All collections are mounted flat under `/band`, so no endpoint path nests one resource under another. Where a path does carry multiple identifiers in the future, identifiers are validated for existence left to right, and the first missing identifier produces its own `ERR_<RESOURCE>_NOT_FOUND` (HTTP 404) before any later identifier is examined. Body foreign keys follow the same rule after path identifiers: each referenced resource must exist, surfaced as the corresponding not-found error.

## 3. Business Logic & Workflows

### 3.1. The Season: Program Setup, Lifecycle, and Configuration

A `BandDirector` opens a season by creating a `BandProgram` with a human-readable `season_name` (for example, "Fall 2026"), a `music_budget_cents` for arrangement purchases, and a `repair_budget_cents` for instrument repairs. Three optional knobs shape downstream behavior: `rental_fee_mode` selects the rental-fee variant and defaults to `FLAT`; `scoring_mode` selects the audition scoring variant and defaults to `RAW_WEIGHTED`; `subsidy_pool_cents` seeds the booster-funded pool used to subsidize trip cost shares and defaults to 0. The grace threshold `delinquency_grace_cents` may also be overridden at creation, defaulting to 2500. A new program starts in `SETUP` with both spending aggregates — `music_spent_cents` and `repair_spent_cents` — at zero.

The program lifecycle is a one-way ratchet driven by a `BandDirector` supplying a `to_state`. From `SETUP` the program advances to `ENROLLMENT_OPEN`; from `ENROLLMENT_OPEN` to `SEASON_ACTIVE`; from `SEASON_ACTIVE` to `CLOSED`. Advancing from any other starting state is rejected with `ERR_PROGRAM_NOT_IN_REQUIRED_STATE`. Closing is gated on the program having no open obligations: any instrument assignment still `ACTIVE` or `OVERDUE`, any uniform assignment still `ISSUED`, or any trip still `PLANNING`, `ROSTER_OPEN`, `ROSTER_LOCKED`, or `FINALIZED` blocks the close with `ERR_PROGRAM_HAS_OPEN_OBLIGATIONS` (HTTP 409). Every successful advance increments the program's `version`.

While the season runs, a `BandDirector` may reconfigure the program — adjusting `music_budget_cents`, `repair_budget_cents`, `subsidy_pool_cents`, `delinquency_grace_cents`, `rental_fee_mode`, or `scoring_mode` — subject to the optimistic-concurrency contract of §2.10: the request must carry `expected_program_version` matching the program's current `version`, else the update is refused with `ERR_STALE_VERSION` and nothing changes. Reconfiguration is permitted in any program status, including `SETUP` and `CLOSED`. Mode changes are not retroactive: `rental_fee_mode` is snapshotted onto each new instrument assignment at creation as its `fee_variant`, and `scoring_mode` is snapshotted onto each new audition at creation, so existing assignments and auditions keep the variant they were born with. The spending aggregates are pure derived values: `music_spent_cents` is the sum of `cost_cents` over the program's arrangements in `LICENSED_ACTIVE` or `EXPIRED` status, and `repair_spent_cents` is the sum of `repair_cost_cents` over all completed maintenance calls for the program's instruments.

### 3.2. Roster Building: Students, Enrollment, and Withdrawal

A `BandDirector` or `AssistantDirector` registers a student by providing the owning `program_id`, a `full_name`, a `grade` (an integer, conventionally 9 to 12 — no range check is enforced), and a `section` — one of `WOODWIND`, `BRASS`, `PERCUSSION`, or `GUARD`. The student begins with `enrollment_status` set to `APPLIED` and `is_section_leader` false. Enrollment — the transition from `APPLIED` to `ENROLLED` — is performed by a `BandDirector` or `AssistantDirector`; enrolling a student not currently `APPLIED` is rejected with `ERR_INVALID_STATE`. Suspension moves a student from `ENROLLED` to `SUSPENDED` and is restricted to the `BandDirector`, as is reinstatement. Reinstatement additionally requires the student's `account_balance_cents` to be no greater than the program's `delinquency_grace_cents` — a balance strictly above the grace blocks reinstatement with `ERR_STUDENT_DELINQUENT_FEES`. Each of these transitions increments the student's `version`. A `BandDirector` may also designate an enrolled student as a section leader, setting `is_section_leader` to true; that flag is the sole gate for `SectionLeader`-role operations and is never set through any other path. Designation itself performs no enrollment-status check: any student record, whatever its `enrollment_status`, may be flagged.

Withdrawal is the heaviest cascade in the system. A `BandDirector` may withdraw a student from `ENROLLED` or `SUSPENDED`. The withdrawal then reconciles every open commitment the student holds. Each instrument assignment in `ACTIVE` or `OVERDUE` is forced to `RETURNED`, with any late fee computed against the assignment's `due_date` as of the logical clock posted as a `LATE_FEE_DEBIT`, and the instrument itself moved to `RETURN_PENDING_INSPECTION`. Each uniform assignment still `ISSUED` is forced to `RETURNED` with `soiling_level` recorded as `NORMAL`, moving the garment to `RETURNED_DIRTY`. Each trip enrollment whose attendance is `REGISTERED` or `CONFIRMED` is moved to `EXCUSED`, with a refund computed under the tiered withdrawal policy of §3.6 posted as a `REFUND` payment, and each freed seat triggers the waitlist promotion of §3.6. Finally the student's `version` increments and `account_balance_cents` is recomputed from the ledger. Withdrawal is terminal: a `WITHDRAWN` student takes no further transitions.

### 3.3. The Instrument Locker: Checkout, Fees, Returns, and the Repair Bench

The `EquipmentManager` stocks the locker by creating instruments with a `program_id`, a `serial_number` unique within the program (duplicates rejected with `ERR_SERIAL_NUMBER_TAKEN`), an `instrument_type` such as `TRUMPET`, `SNARE`, or `SOUSAPHONE`, a declared `replacement_value_cents`, and an optional `condition_grade` — one of `EXCELLENT`, `GOOD`, `FAIR`, `POOR`, or `UNPLAYABLE` — defaulting to `GOOD`. New instruments start `AVAILABLE`.

Checking an instrument out is a single operation with several gates. The `EquipmentManager` supplies `student_id`, `instrument_id`, and a `due_date`. The student must be `ENROLLED` — an `APPLIED`, `SUSPENDED`, or `WITHDRAWN` student is rejected with `ERR_STUDENT_NOT_ENROLLED` — and must not be delinquent, else `ERR_STUDENT_DELINQUENT_FEES`. The instrument must be `AVAILABLE`, else `ERR_INSTRUMENT_NOT_AVAILABLE`, and must not be `UNPLAYABLE`, else `ERR_INSTRUMENT_UNPLAYABLE` (HTTP 422). The `due_date` must be strictly after the checkout instant recorded as `checkout_at`, else `ERR_DUE_DATE_INVALID` (HTTP 422). One student may hold at most one active assignment per instrument type: a second checkout of the same `instrument_type` while an `ACTIVE` or `OVERDUE` assignment exists for that student is rejected with `ERR_INSTRUMENT_TYPE_ALREADY_ASSIGNED`. These gates fire in a fixed order: the student's enrollment status first, then instrument availability, then playability, then the due-date window, then type uniqueness, and delinquency last. On success the assignment starts `ACTIVE`, the instrument moves to `CHECKED_OUT`, and the rental fee accrues.

The rental fee is forward-looking and variant-driven. When the assignment's snapshotted `fee_variant` is `FLAT`, the accrued fee is a whole-semester 15000 cents regardless of the checkout window. When the variant is `PRORATED`, the fee is weekly: the number of days from `checkout_at` to `due_date` is rounded up to whole days, then rounded up to whole weeks with a minimum of one week, and each week costs 2000 cents. Either way, the resulting `accrued_fee_cents` is posted to the student's ledger as a `RENTAL_FEE_DEBIT` at creation. The two variants share inputs but diverge sharply: an identical fourteen-day window accrues 4000 cents under `PRORATED` against 15000 under `FLAT`.

When the logical clock passes an assignment's `due_date` while it is still `ACTIVE`, the assignment flips to `OVERDUE` — evaluated lazily when the clock is set and whenever the assignment is read. An `EquipmentManager` may renew an assignment in `ACTIVE` or `OVERDUE` (any other state yields `ERR_ASSIGNMENT_NOT_ACTIVE`) by supplying a `new_due_date` strictly later than the current `due_date`, else `ERR_DUE_DATE_INVALID`. Renewal sets `due_date` to the new value, returns an `OVERDUE` assignment to `ACTIVE`, and — for the `PRORATED` variant only — recomputes `accrued_fee_cents` over the extended window from `checkout_at` to `new_due_date` and posts the delta over the previously accrued amount as a further `RENTAL_FEE_DEBIT` when the delta is positive. The `FLAT` variant never re-accrues.

Return is an inspection. The `EquipmentManager` returns an assignment in `ACTIVE` or `OVERDUE` (else `ERR_ASSIGNMENT_NOT_ACTIVE`), supplying an `inspection_result`. The assignment records `returned_at` from the logical clock and moves to `RETURNED`. If the assignment was `OVERDUE` — that is, `returned_at` is strictly after `due_date` — a late fee accrues: the number of days from `due_date` to `returned_at`, rounded up to whole days and then to whole weeks, at 500 cents per week, recorded as `late_fee_cents` and posted as a `LATE_FEE_DEBIT`; a return on or before `due_date` leaves `late_fee_cents` at zero. The instrument then moves to `RETURN_PENDING_INSPECTION` and resolves by the inspection: a `PASS` restores it to `AVAILABLE` with `condition_grade` unchanged, while a `FAIL` moves it to `IN_MAINTENANCE` and degrades its `condition_grade` one step down the ladder `GOOD` → `FAIR` → `POOR` → `UNPLAYABLE`, with `UNPLAYABLE` as the floor (an `EXCELLENT` instrument degrades to `GOOD`).

An instrument in `IN_MAINTENANCE` is returned to service by the `EquipmentManager` completing maintenance with a `repair_cost_cents`, which must be a positive integer — validated before the `IN_MAINTENANCE` state check — else `ERR_INVALID_REQUEST` (HTTP 400). The completion is gated fiscally: the program's `repair_spent_cents` plus the new `repair_cost_cents` must not exceed `repair_budget_cents`, with equality permitted, else `ERR_REPAIR_BUDGET_EXCEEDED` (HTTP 402). On success the instrument returns to `AVAILABLE`, its `condition_grade` is restored to `GOOD` if it had degraded below `GOOD`, the program's `repair_spent_cents` increases by `repair_cost_cents`, and the instrument's `version` increments. Retirement is terminal and irreversible: the `EquipmentManager` may retire an instrument from `AVAILABLE` or `IN_MAINTENANCE`; retiring one that is `CHECKED_OUT` is rejected with `ERR_INSTRUMENT_CHECKED_OUT`, and a `RETIRED` instrument is excluded from all further operations — a second retire attempt yields `ERR_INSTRUMENT_RETIRED`.

### 3.4. The Uniform Room and the Cleaning Cycle

The `EquipmentManager` stocks the uniform room with garments, each carrying a `program_id`, a `garment_type` — `JACKET`, `BIBBERS`, `SHAKO`, `PLUME`, or `GLOVES` — and a `size_label` such as `M` or `42R`. Garments start `IN_STORAGE` with a `cleaning_count` of zero and no `cleaning_batch_id`.

Issuing a garment pairs a fitting with a record. The `EquipmentManager` supplies `student_id` and `uniform_id`; the student must be `ENROLLED` else `ERR_STUDENT_NOT_ENROLLED`, and the garment must be `IN_STORAGE` else `ERR_UNIFORM_NOT_ISSUABLE`. A student may hold at most one `ISSUED` garment of each `garment_type` — a second issue of the same type is rejected with `ERR_GARMENT_TYPE_ALREADY_ISSUED`. The plumage rule is cross-garment: issuing a `PLUME` requires the same student to currently hold an `ISSUED` `SHAKO`, else `ERR_MATCHING_GARMENT_REQUIRED`. These checks fire in the order stated: enrollment status, then garment state, then garment-type uniqueness, then the plumage rule. On success the assignment starts `ISSUED` with `issued_at` from the logical clock, and the garment moves to `ISSUED`.

Return records condition. The `EquipmentManager` returns an `ISSUED` uniform assignment (else `ERR_UNIFORM_ASSIGNMENT_NOT_ISSUED`) with a `soiling_level` of `NORMAL` or `HEAVY`. The assignment records `returned_at` and moves to `RETURNED`; its `cleaning_fee_cents` stays at zero for now — it is only priced when the garment's cleaning batch is received. The garment moves to `RETURNED_DIRTY`, awaiting the next batch. A garment may be retired only from `IN_STORAGE`; retiring from any other state is rejected with `ERR_UNIFORM_NOT_ISSUABLE`.

The cleaning cycle is batch-driven. The `EquipmentManager` opens a `CleaningBatch` for a program; the batch starts `OPEN` with a `garment_count` of zero. While the batch is `OPEN`, garments in `RETURNED_DIRTY` are attached to it one at a time — each attach sets the garment's `cleaning_batch_id` and increases `garment_count` by one; attaching to a batch no longer `OPEN` is rejected with `ERR_BATCH_NOT_OPEN`, a check that precedes the garment-state check, and attaching a garment not in `RETURNED_DIRTY` is rejected with `ERR_UNIFORM_NOT_ISSUABLE`. A successful attach returns the updated batch with `201 Created`. Sending the batch requires it `OPEN` (else `ERR_BATCH_NOT_OPEN`) with at least one garment attached (else `ERR_BATCH_EMPTY`); sending moves every attached garment to `AT_CLEANER`, moves the batch to `SENT`, and increments its `version`.

Receiving reconciles money and garments in one act. Receiving requires the batch `SENT`, else `ERR_BATCH_NOT_SENT`. The cleaner's bill is computed per garment line and summed; the volume discount tier is chosen from `garment_count`: 0 percent for 1 to 10 garments, 15 percent for 11 to 30, and 25 percent for 31 or more. Each line is priced by garment type at base rates of 900 cents for a `JACKET`, 700 for `BIBBERS`, 450 for a `SHAKO`, 300 for a `PLUME`, and 150 for `GLOVES`. The pinned rounding order is per-line first, then sum: each garment's line cost is its base price multiplied by one minus the discount fraction, rounded half up to integer cents, plus a 200-cent heavy-soiling surcharge when the garment's most recent `RETURNED` assignment recorded a `soiling_level` of `HEAVY`; the batch's `total_cost_cents` is the sum of those line costs. The alternative order — summing base prices, applying the discount once, and rounding a single total — is forbidden, because the two orders genuinely disagree: six shakos and six plumes at the 15 percent tier price at 3828 cents under per-line rounding (six lines of 383 plus six lines of 255) against 3825 under sum-then-round. At receive, each garment's `UniformAssignment` has its `cleaning_fee_cents` set to that garment's line cost, a `CLEANING_FEE_DEBIT` for the same amount is posted to the wearing student's ledger, the garment returns to `IN_STORAGE` with its `cleaning_count` increased by one and its `cleaning_batch_id` cleared, and the batch's `discount_pct` and `total_cost_cents` are recorded as the batch moves to `RECONCILED`.

### 3.5. The Music Library: Quotes, Segregation of Duties, and Licensing

A chart enters the library as a quote. A `BandDirector`, `AssistantDirector`, or `SectionLeader` may request an arrangement by providing `program_id`, `title`, `arranger`, a `license_type` of `STANDARD`, `CUSTOM_ARRANGEMENT`, or `COMPETITION_EXCERPT`, a `cost_cents`, and a `rights_end` that must lie in the future at creation, else `ERR_LICENSE_WINDOW_INVALID` (HTTP 422). The arrangement starts `QUOTED`, and the acting user's identifier is recorded as `creator_user_id`. The `SectionLeader` role alone suffices to request: arrangements are not section-scoped, and no `is_section_leader` flag or section match is checked.

Approval is segregated. A `BandDirector` may approve a `QUOTED` arrangement (else `ERR_ARRANGEMENT_NOT_QUOTED`), but the approver's `X-User-ID` must differ from `creator_user_id` — self-approval is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). On approval the acting identifier is recorded as `approver_user_id` and the arrangement moves to `APPROVED`. Rejection follows the same dual rule: a `BandDirector` may reject a `QUOTED` arrangement only when the rejecter differs from the creator, else `ERR_SEGREGATION_OF_DUTIES`; a rejected arrangement is terminally `REJECTED`.

Purchase is the treasurer's act and the budget's gate. A `BoosterTreasurer` may purchase an `APPROVED` arrangement (else `ERR_ARRANGEMENT_NOT_APPROVED`), but only while the program's `music_spent_cents` plus this arrangement's `cost_cents` does not exceed `music_budget_cents` — equality is permitted, overshoot rejected with `ERR_MUSIC_BUDGET_EXCEEDED` (HTTP 402). On purchase the arrangement moves to `LICENSED_ACTIVE` and `music_spent_cents` increases by `cost_cents`. Licenses expire with the clock: when the logical clock passes `rights_end`, the arrangement moves from `LICENSED_ACTIVE` to `EXPIRED`, evaluated lazily on clock set and on read; expiry does not refund anything, and the spent aggregate is unchanged because the money is already gone.

### 3.6. The Calendar and the Road: Events, Trips, and Enrollments

#### Events and Weather

A `BandDirector` or `AssistantDirector` schedules an event with `program_id`, an `event_type` of `REHEARSAL`, `SECTIONAL`, `COMPETITION`, `PERFORMANCE`, or `FUNDRAISER`, a `facility` label such as `STADIUM`, `GYM`, or `BAND_ROOM`, a `starts_at` and `ends_at` window that must be strictly increasing else `ERR_EVENT_WINDOW_INVALID` (HTTP 422), and an `is_outdoor` flag. New events start `SCHEDULED`. Two events in the same program may not share a facility across overlapping windows: the check is half-open, so back-to-back events where one's `starts_at` equals the other's `ends_at` are legal, and a conflict exists exactly when the other event is in `SCHEDULED`, `WEATHER_WATCH`, or `INDOOR_RELOCATED` status, the facility and program match, and the new window begins strictly before the other's end while the other's window begins strictly before the new window's end. A conflicting schedule is rejected with `ERR_FACILITY_CONFLICT` (HTTP 409).

Weather governs outdoor events. Weather-watch moves a `SCHEDULED` event to `WEATHER_WATCH` and is permitted only on outdoor events — an indoor event is rejected with `ERR_EVENT_NOT_OUTDOOR` (HTTP 422) and an event not in `SCHEDULED` with `ERR_EVENT_NOT_SCHEDULED`. From `WEATHER_WATCH`, the staff may relocate indoors: the event moves to `INDOOR_RELOCATED`, its `facility` is replaced with the supplied indoor venue, `is_outdoor` flips to false, and the facility conflict check is re-run against the new facility, surfacing `ERR_FACILITY_CONFLICT` if the new venue is already committed in that window. Relocating an event not in `WEATHER_WATCH` is rejected with `ERR_EVENT_NOT_SCHEDULED`. Postponement moves an event from `SCHEDULED`, `WEATHER_WATCH`, or `POSTPONED` to `POSTPONED` — operating on an event in any other state, `INDOOR_RELOCATED` or terminally `COMPLETED` or `CANCELLED`, yields `ERR_EVENT_TERMINAL`, a check that precedes the paired-field validation — and leaves the times unchanged: any `new_starts_at` and `new_ends_at` supplied while the event is not yet `POSTPONED` are disregarded, and the two fields must be supplied together or not at all, so a request carrying exactly one of them is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Only postponing an already-`POSTPONED` event, supplying fresh `new_starts_at` and `new_ends_at` together, reschedules it back to `SCHEDULED` with the new window, provided the window is strictly increasing (else `ERR_EVENT_WINDOW_INVALID`) and conflict-free (else `ERR_FACILITY_CONFLICT`). Completion moves an event from `SCHEDULED`, `WEATHER_WATCH`, or `INDOOR_RELOCATED` to `COMPLETED`; from any other state the completion is rejected with `ERR_EVENT_TERMINAL`.

Cancellation is the director's alone and cascades through the road plan. Cancelling an event in `SCHEDULED`, `WEATHER_WATCH`, `INDOOR_RELOCATED`, or `POSTPONED` (else `ERR_EVENT_TERMINAL`) moves it to `CANCELLED` and forces any linked trip in `PLANNING`, `ROSTER_OPEN`, `ROSTER_LOCKED`, or `FINALIZED` to `CANCELLED` as well. That trip cancellation then cascades in full: every enrollment of the trip with attendance `REGISTERED`, `CONFIRMED`, or `WAITLISTED` moves to `EXCUSED`; every enrollment so excused that holds a positive `net_paid_cents` receives a `REFUND` payment of its full `net_paid_cents` and its `payment_status` moves to `REFUNDED`; enrollments already `ATTENDED` or `NO_SHOW` are neither excused nor refunded; and each affected student's `account_balance_cents` is recomputed.

#### Trips: Planning, Roster, Finalization

A trip is planned against an event. A `BandDirector` or `AssistantDirector` creates one with `event_id`, `capacity`, `estimated_cost_cents`, and `departure_at`; the trip inherits its `program_id` from the linked event. Creation is OCC-guarded per §2.10: the request must carry `expected_event_version` matching the event's current `version`, else `ERR_STALE_VERSION`, and a successful creation increments the event's `version` by 1. Creation does not gate on the event's own status — a trip may be planned against an event in any status. One event has at most one live trip: if the event's existing trip is still in `PLANNING`, creating the new trip legitimately supersedes it, moving the old trip to `SUPERSEDED`; any other existing trip not already `SUPERSEDED` — including a `CANCELLED` or `COMPLETED` one — blocks creation with `ERR_EVENT_HAS_ACTIVE_TRIP`. The trip starts in `PLANNING` with `subsidy_applied_cents` at zero and its roster counters — `registered_count` and `confirmed_count` — derived from its enrollments.

Roster management is a two-step gate. Opening the roster moves the trip from `PLANNING` to `ROSTER_OPEN` (from any other state, `ERR_TRIP_ROSTER_NOT_OPEN`). Locking the roster moves it from `ROSTER_OPEN` to `ROSTER_LOCKED` (again else `ERR_TRIP_ROSTER_NOT_OPEN`), but only once transportation exists: at least one truck charter linked to the trip's event must be in `RESERVED`, `LOADED`, `DEPARTED`, or `RETURNED` status, else `ERR_CHARTER_REQUIRED`. Locking freezes the roster.

Finalization is the treasurer's accounting act. A `BoosterTreasurer` finalizes a `ROSTER_LOCKED` trip (else `ERR_TRIP_NOT_LOCKED`) by supplying the `actual_cost_cents`, which must be a non-negative integer — validated before the `ROSTER_LOCKED` check — else `ERR_INVALID_REQUEST` (HTTP 400). The final cost share is then computed in a pinned evaluation order that resolves an otherwise circular dependency: first the confirmed set is frozen — exactly the enrollments whose attendance is `CONFIRMED` at this moment; second, the gross is set to `actual_cost_cents`; third, `subsidy_applied_cents` is set to the lesser of the program's `subsidy_pool_cents` and 25 percent of the gross rounded half up to integer cents; fourth, the net is the gross minus the subsidy; fifth, each confirmed enrollment's `final_share_cents` is the net divided by the confirmed count, rounded half up to integer cents — which requires at least one confirmed enrollment. Sizing the subsidy off the net rather than the gross, or dividing before subtracting the subsidy, is forbidden. Each `CONFIRMED` enrollment then has `amount_due_cents` replaced by its `final_share_cents`, a `TRIP_SHARE_DEBIT` for that amount posted to its student's ledger, and its `payment_status` recomputed. For contrast, the provisional share assigned at enrollment time is the trip's `estimated_cost_cents` divided by the roster count, so an estimated 90000 cents over seven registered students yields a provisional 12857 cents, while a finalized actual of 100000 cents with a 20000-cent pool (the cap of 25000 does not bind) over seven confirmed students yields a final 11429 cents. Finalization increments the trip's `version`.

Completion closes the loop. A `FINALIZED` trip may be completed by a `BandDirector` or `AssistantDirector` (else `ERR_TRIP_NOT_LOCKED`), but only when every enrollment's attendance is resolved to `ATTENDED`, `NO_SHOW`, or `EXCUSED` — any unresolved seat yields `ERR_UNRESOLVED_ENROLLMENTS_EXIST`. Cancellation of a trip is available to a `BandDirector` from `PLANNING`, `ROSTER_OPEN`, `ROSTER_LOCKED`, or `FINALIZED` (else `ERR_INVALID_STATE`), and triggers the same cascade as the event-driven cancellation above: enrollments in `REGISTERED`, `CONFIRMED`, or `WAITLISTED` move to `EXCUSED`, every such excused enrollment with positive `net_paid_cents` is refunded in full via a `REFUND` payment and moves to `REFUNDED` — enrollments already `ATTENDED` or `NO_SHOW` are untouched — and affected student balances recompute.

#### Enrollments: Seats, Shares, and Refunds

Enrollment is open to staff and to students themselves. A `BandDirector` or `AssistantDirector` may enroll any student; a `Student` actor may enroll only themselves — a payload whose `student_id` differs from the caller's identity is rejected with `ERR_FORBIDDEN_OWNERSHIP`. The student must be `ENROLLED` else `ERR_STUDENT_NOT_ENROLLED`, must not be delinquent else `ERR_STUDENT_DELINQUENT_FEES`, and must not already hold a non-terminal enrollment for the same trip, else `ERR_ENROLLMENT_DUPLICATE`. Enrollment does not gate on the trip's status — seats may be added while the trip is in any status, including `PLANNING` or `CANCELLED`. The checks fire in the order stated: ownership, identifier existence, enrollment status, duplication, delinquency, then capacity. Capacity is inclusive: enrollments whose `attendance_status` is `REGISTERED` or `CONFIRMED` may number up to exactly the trip's `capacity`, and an enrollment created when the count already equals capacity lands with `attendance_status` `WAITLISTED` and both `provisional_share_cents` and `amount_due_cents` set to zero. An enrollment that lands a seat starts `REGISTERED` with `payment_status` `UNPAID`; its provisional share is the trip's `estimated_cost_cents` divided by the roster count including this new enrollment, rounded half up to integer cents, and `amount_due_cents` mirrors the provisional share until finalization replaces it.

Payment tracking is derived, never set directly. An enrollment's `net_paid_cents` is the sum of `PAYMENT` rows minus the sum of `REFUND` rows linked to it via `trip_enrollment_id`, and `refunded_cents` is the sum of those `REFUND` rows alone. `payment_status` reads `UNPAID` when `net_paid_cents` is zero, `PAID` when `net_paid_cents` is at least `amount_due_cents` and `amount_due_cents` is positive, and `PARTIAL` otherwise; `REFUNDED` is set only by the full-refund paths of excuse (including the excuses driven by student withdrawal under §3.2) and trip cancellation. Confirmation moves a `REGISTERED` enrollment to `CONFIRMED` and is performed by a `BandDirector` or `AssistantDirector`; it requires the trip in `ROSTER_OPEN` or `ROSTER_LOCKED` (else `ERR_TRIP_ROSTER_NOT_OPEN`), the enrollment in `REGISTERED` (else `ERR_ENROLLMENT_NOT_CONFIRMABLE`), and `payment_status` exactly `PAID` (else `ERR_ENROLLMENT_NOT_PAID`).

Excusing a seat triggers the refund tiers. A `BandDirector`, `AssistantDirector`, or the enrolled `Student` themselves may excuse an enrollment in `REGISTERED` or `CONFIRMED` — an enrollment in any other attendance state, terminal or `WAITLISTED`, yields `ERR_ENROLLMENT_TERMINAL`. The refund percentage keys off the whole days between now and the trip's `departure_at` (any partial day discarded): at least 14 days out, the full net paid amount is refunded; from 7 up to but not including 14 days, half; under 7 days, nothing. The refund amount is the enrollment's `net_paid_cents` multiplied by that percentage, rounded half up to integer cents, and is posted as a `REFUND` payment when positive; when the refund equals the full net paid and the net paid is positive, `payment_status` moves to `REFUNDED`. Both the refund computation and this full-refund comparison measure `net_paid_cents` as it stands immediately before the refund row is posted, since posting the refund itself reduces `net_paid_cents`. Excusing frees the seat, which fires the waitlist: among the trip's `WAITLISTED` enrollments, the one with the earliest `created_at` — never any identifier ordering — is promoted to `REGISTERED` exactly when the roster count after the freeing is below capacity, and the promoted enrollment's `provisional_share_cents` is recomputed as the trip's `estimated_cost_cents` divided by the new roster count, rounded half up, with `amount_due_cents` following it. An empty waitlist makes promotion a no-op. Boundary cases are exact: exactly 14 days to departure refunds 100 percent, and exactly 7 days refunds 50 percent.

Attendance marking happens after finalization. A `BandDirector` or `AssistantDirector` may mark a `CONFIRMED` enrollment (else `ERR_ENROLLMENT_NOT_CONFIRMABLE`) on a `FINALIZED` trip (else `ERR_TRIP_NOT_LOCKED`) with an `outcome` of `ATTENDED` or `NO_SHOW`. A `NO_SHOW` outcome carries a hard negative-space rule: a no-show forfeits all refund rights, and a `REFUND` payment posted against a `NO_SHOW` enrollment is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 3.7. Money In: Ledger Posting, the Allocation Waterfall, and Fundraisers

Only a `BoosterTreasurer` may post to the ledger. Each posted row names a `student_id`, a client-postable `kind`, a positive `amount_cents`, and optionally a `trip_enrollment_id` and a free-text `note`; `REFUND` and `WAIVER` rows must also name the compensated row via `reference_payment_id`. Posting recomputes the student's `account_balance_cents` per §2.7, and when the row is linked to a trip enrollment, that enrollment's `net_paid_cents`, `refunded_cents`, and `payment_status` recompute as well.

A `PAYMENT` row runs the allocation waterfall. The student's outstanding debits — debit-kind rows whose posted `amount_cents` exceeds the sum of allocations already applied to them — are walked in order of `created_at` ascending with ties broken by `amount_cents` ascending, never by identifier. The payment applies to each debit in turn the lesser of the payment's remaining amount and that debit's outstanding remainder, recording each application as an entry in the payment's `allocations` list, where each entry pairs the settled debit's identifier `debit_payment_id` with the applied amount `applied_cents`. Any payment remainder beyond all outstanding debits stays on the account as unallocated credit, and a payment posted against a student with no outstanding debits carries an empty `allocations` list.

Fundraisers close the loop from booster labor to student credit. A `BoosterTreasurer` creates a fundraiser with `program_id`, `name`, and a `goal_cents` target; it starts `OPEN`. Closing requires `OPEN` (else `ERR_FUNDRAISER_NOT_OPEN`) and supplies the final `raised_cents` plus the `participant_hours` of each participating student. `raised_cents` must be a non-negative integer, each participant's hours a non-negative integer, and the total hours strictly positive, else `ERR_INVALID_REQUEST` (HTTP 400); the `OPEN` check fires before any participant is validated. The `participant_hours` payload accepts either of two wire shapes: an object mapping each participating student's `id` to that student's hours, or a list of entries each carrying `student_id` and `hours`; a payload in any other shape, a list entry missing either field, or an empty participant set is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Every participant must be `ENROLLED`, else `ERR_STUDENT_NOT_ENROLLED`. The close allocates `raised_cents` across participants by largest remainder: each participant's raw share is `raised_cents` multiplied by their hours divided by the total hours across all participants; each base share is that raw share floored to whole cents; the leftover cents — `raised_cents` minus the sum of base shares — are distributed one cent at a time to participants in descending order of fractional remainder, ties broken by the participant student's `created_at` ascending, never by identifier. One `FUNDRAISING_CREDIT` payment row, carrying the `fundraiser_id`, is posted per participant for their final amount. The allocation is lossless: the fundraiser's `allocated_credit_cents` always equals `raised_cents` exactly, and the fundraiser moves to `CREDITED`.

### 3.8. Auditions, Scores, and the Chair Challenge

An audition is a per-section seating event. A `BandDirector` or `AssistantDirector` creates one with `program_id`, a `section`, and a `chair_capacity` giving the number of seated chairs — a non-negative integer, else `ERR_INVALID_REQUEST` (HTTP 400); the audition snapshots the program's current `scoring_mode` and starts `SCORING_OPEN`. Staff then enter students into the audition — each entry pairs an `audition_id` with a `student_id`, and the student must be `ENROLLED` else `ERR_STUDENT_NOT_ENROLLED`. Entry creation does not gate on the audition's status, and no duplicate-entry rule applies: the same student may be entered more than once.

Judging accumulates one rubric row per judge. A `BandDirector` or `AssistantDirector` submits a judge's scores for an entry by supplying `judge_id`, `musicianship`, `marching`, and `leadership`; each of the three rubric fields must lie between 0 and 100 inclusive, else `ERR_SCORE_OUT_OF_RANGE` (HTTP 422), and one judge may score an entry only once — a repeat `judge_id` on the same entry is rejected with `ERR_DUPLICATE_SCORE`. Each score row is appended to the entry's `judge_scores` list. Score submission requires the audition to be `SCORING_OPEN`, else `ERR_AUDITION_NOT_SCORING`.

Finalizing scores turns rubrics into ranks. A `BandDirector` finalizes an audition in `SCORING_OPEN` or `UNDER_CHALLENGE` (else `ERR_AUDITION_NOT_SCORING`), but only when every entry has at least one judge score, else `ERR_SCORES_INCOMPLETE` — an audition with no entries at all is rejected the same way. Each judge's weighted score for an entry is half the `musicianship` score plus three-tenths of the `marching` score plus one-fifth of the `leadership` score. What happens next depends on the snapshotted variant. Under `RAW_WEIGHTED`: with exactly one judge, the composite is that judge's weighted score multiplied by 0.95, rounded half up to two decimals; with exactly two judges, the composite is the mean of the two weighted scores, rounded half up to two decimals; with three or more judges, the single lowest weighted score is dropped and the composite is the mean of the remainder, rounded half up to two decimals. Under `RANK_NORMALIZED`: each judge independently ranks the entries carrying a score from that judge by weighted score descending — an entry a judge did not score receives no points from that judge — ties broken by the entry's `created_at` ascending, and awards Borda points equal to the audition's total entry count minus the entry's rank; the composite is the sum of those Borda points across judges, with score magnitudes discarded entirely. The two variants share inputs but routinely disagree: with two judges, an entry whose weighted scores are 100 and 60 composites to 80.0 under the raw variant, while a rival at 80 and 90 composites to 85.0, yet under rank normalization the two entries tie at one Borda point apiece and the tie falls to creation time. Either way, each entry's `composite_score` is recorded and ranks are assigned one-based by composite descending, ties broken by the entry's `created_at` ascending; finalization moves the audition to `SCORES_FINALIZED` and increments its `version`.

Publishing placements is the OCC-guarded act of §2.10. A `BandDirector` publishes an audition in `SCORES_FINALIZED` (else `ERR_AUDITION_SCORES_NOT_FINAL`) with `expected_audition_version` matching the audition's current `version`, else `ERR_STALE_VERSION`. Publishing walks the entries in rank order: any entry whose `rank` is at most `chair_capacity` receives a `ChairPlacement` with `chair_number` equal to its rank and `is_alternate` false; any entry beyond capacity receives a placement with `is_alternate` true and `chair_number` null. Any previously published placements for the same audition move from `PUBLISHED` to `SUPERSEDED`, so a re-publish after a challenge cleanly replaces the old set. Publishing stamps `published_at` from the logical clock and increments the audition's `version` as it moves to `PLACEMENTS_PUBLISHED`.

The chair challenge gives student leadership a seven-day voice. A `SectionLeader` may challenge a published audition (else `ERR_AUDITION_NOT_PUBLISHED`) by supplying the contested `entry_id` — which must exist but need not belong to the challenged audition — and an optional `reason`. The acting student must hold `is_section_leader` and belong to the same `section` as the audition, else `ERR_SECTION_LEADER_REQUIRED`, and the challenge must arrive no later than seven days after `published_at` — later challenges are rejected with `ERR_CHALLENGE_WINDOW_EXPIRED` (HTTP 422). A successful challenge moves the audition to `UNDER_CHALLENGE` and increments its `version`. Re-finalization from `UNDER_CHALLENGE` — after additional judge scores have been submitted — recomputes composites and ranks exactly as the original finalization did and returns the audition to `SCORES_FINALIZED`, ready for a fresh publish.

### 3.9. Truck Logistics: Charters, Manifests, and the Two-Hour Buffer

The `EquipmentManager` reserves vehicles by creating a charter with `program_id`, a `vehicle_label` such as `TRUCK-1`, inclusive capacity ceilings `capacity_weight_lb` and `capacity_volume_cuft`, a reservation `window_start` and `window_end` that must be strictly increasing, and an optional `event_id` linking the charter to the event it serves. Reservation windows for the same vehicle may not even touch: the overlap check is buffered, applying a two-hour loading buffer to both ends of every existing reservation, so a new window conflicts whenever the other charter belongs to the same program, carries the same `vehicle_label`, sits in `RESERVED`, `LOADED`, or `DEPARTED` status, and the new `window_start` falls strictly before the other's `window_end` plus two hours while the other's `window_start` minus two hours falls strictly before the new `window_end`. A conflicting reservation is rejected with `ERR_VEHICLE_WINDOW_CONFLICT` (HTTP 409). Validation runs in this order: program posture, then the optional `event_id`'s existence, then window sanity, then the buffered overlap. Back-to-back scheduling without the buffer is deliberately impossible for vehicles, in contrast to the half-open adjacency permitted for facilities. A new charter starts `RESERVED` with `loaded_weight_lb` and `loaded_volume_cuft` at zero.

Loading builds the manifest. The `EquipmentManager` adds loads to a charter by supplying a `description` such as "12 equipment trunks", a positive `weight_lb`, and a positive `volume_cuft`; a load may optionally name an `instrument_id`, in which case that instrument must not be `RETIRED` or `IN_MAINTENANCE`, else `ERR_LOAD_INSTRUMENT_INVALID`. A non-positive `weight_lb` or `volume_cuft` is rejected with `ERR_INVALID_REQUEST` (HTTP 400) before any other check. Loads may only be added while the charter is in a loadable state — once `DEPARTED`, `RETURNED`, or `CANCELLED`, the request fails with `ERR_CHARTER_NOT_LOADABLE` — and the loadable-state check precedes the instrument existence and state checks, which precede the capacity check. Capacity is checked on every add, weight before volume: the prospective `loaded_weight_lb` — the existing sum plus the new load's `weight_lb` — must not exceed `capacity_weight_lb`, with exact equality allowed, else `ERR_TRUCK_OVERWEIGHT` (HTTP 422); only if weight passes is volume checked, with the prospective `loaded_volume_cuft` likewise bounded by `capacity_volume_cuft` with equality allowed, else `ERR_TRUCK_OVERVOLUME` (HTTP 422). The first successful load moves the charter from `RESERVED` to `LOADED`, and every load updates the charter's running `loaded_weight_lb` and `loaded_volume_cuft` aggregates. Manifest rows are append-only records and are retained on record even if the charter is later cancelled.

Departure and return close the loop. Departure requires a `LOADED` charter (else `ERR_CHARTER_NOT_LOADABLE`) carrying at least one pound of loaded weight (else `ERR_CHARTER_EMPTY`), and moves the charter to `DEPARTED`. Return requires `DEPARTED` (else `ERR_INVALID_STATE`) and moves it to `RETURNED`. Cancellation is available from `RESERVED` or `LOADED` — any other state yields `ERR_INVALID_STATE` — and moves the charter to `CANCELLED` with its load rows retained.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; the cleaning-batch item attach and the judge-score submission endpoints also answer `201 Created`, returning the updated batch and entry respectively. All other operations that modify an existing resource, including all state-transition actions, return `200 OK`. Read endpoints return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/band/programs` | Create a band program (season) | BandDirector |
| GET | `/band/programs` | List programs | Any |
| GET | `/band/programs/{id}` | Get a program | Any |
| PATCH | `/band/programs/{id}` | Update program configuration (OCC) | BandDirector |
| POST | `/band/programs/{id}/advance` | Advance the program lifecycle | BandDirector |
| POST | `/band/students` | Register a student (starts APPLIED) | BandDirector, AssistantDirector |
| GET | `/band/students` | List students | Any |
| GET | `/band/students/{id}` | Get a student | Any |
| POST | `/band/students/{id}/enroll` | Enroll an applicant | BandDirector, AssistantDirector |
| POST | `/band/students/{id}/suspend` | Suspend an enrolled student | BandDirector |
| POST | `/band/students/{id}/reinstate` | Reinstate a suspended student (balance gate) | BandDirector |
| POST | `/band/students/{id}/withdraw` | Withdraw a student; cascades returns, excuses, refunds | BandDirector |
| POST | `/band/students/{id}/designate-leader` | Mark a student as section leader | BandDirector |
| GET | `/band/students/{id}/ledger` | List a student's payment ledger | Any |
| POST | `/band/instruments` | Add an instrument to inventory | EquipmentManager |
| GET | `/band/instruments` | List instruments | Any |
| GET | `/band/instruments/{id}` | Get an instrument | Any |
| POST | `/band/instruments/{id}/retire` | Retire an instrument (terminal) | EquipmentManager |
| POST | `/band/instruments/{id}/complete-maintenance` | Finish repair; debits the repair budget | EquipmentManager |
| POST | `/band/instrument-assignments` | Check out an instrument; posts the rental fee | EquipmentManager |
| GET | `/band/instrument-assignments` | List instrument assignments | Any |
| GET | `/band/instrument-assignments/{id}` | Get an instrument assignment | Any |
| POST | `/band/instrument-assignments/{id}/return` | Return with an inspection result | EquipmentManager |
| POST | `/band/instrument-assignments/{id}/renew` | Extend the due date; PRORATED re-accrual | EquipmentManager |
| POST | `/band/uniforms` | Add a garment | EquipmentManager |
| GET | `/band/uniforms` | List garments | Any |
| GET | `/band/uniforms/{id}` | Get a garment | Any |
| POST | `/band/uniforms/{id}/retire` | Retire a garment | EquipmentManager |
| POST | `/band/uniform-assignments` | Issue a garment | EquipmentManager |
| GET | `/band/uniform-assignments` | List uniform assignments | Any |
| GET | `/band/uniform-assignments/{id}` | Get a uniform assignment | Any |
| POST | `/band/uniform-assignments/{id}/return` | Return a garment with a soiling level | EquipmentManager |
| POST | `/band/cleaning-batches` | Open a cleaning batch | EquipmentManager |
| GET | `/band/cleaning-batches` | List batches | Any |
| GET | `/band/cleaning-batches/{id}` | Get a batch | Any |
| POST | `/band/cleaning-batches/{id}/items` | Attach a RETURNED_DIRTY garment while OPEN | EquipmentManager |
| POST | `/band/cleaning-batches/{id}/send` | Send the batch to the cleaner | EquipmentManager |
| POST | `/band/cleaning-batches/{id}/receive` | Receive and reconcile: tiered cost, per-student debits | EquipmentManager |
| POST | `/band/arrangements` | Request an arrangement/license quote | BandDirector, AssistantDirector, SectionLeader |
| GET | `/band/arrangements` | List arrangements | Any |
| GET | `/band/arrangements/{id}` | Get an arrangement | Any |
| POST | `/band/arrangements/{id}/approve` | Approve a quote (approver differs from creator) | BandDirector |
| POST | `/band/arrangements/{id}/reject` | Reject a quote (rejecter differs from creator) | BandDirector |
| POST | `/band/arrangements/{id}/purchase` | Purchase an approved arrangement against the music budget | BoosterTreasurer |
| POST | `/band/events` | Schedule an event | BandDirector, AssistantDirector |
| GET | `/band/events` | List events | Any |
| GET | `/band/events/{id}` | Get an event | Any |
| POST | `/band/events/{id}/weather-watch` | Flag an outdoor event for weather | BandDirector, AssistantDirector |
| POST | `/band/events/{id}/relocate-indoor` | Relocate a watched event indoors | BandDirector, AssistantDirector |
| POST | `/band/events/{id}/postpone` | Postpone, or reschedule with a new window | BandDirector, AssistantDirector |
| POST | `/band/events/{id}/cancel` | Cancel an event; cascades trip cancellation and refunds | BandDirector |
| POST | `/band/events/{id}/complete` | Mark an event completed | BandDirector, AssistantDirector |
| POST | `/band/trips` | Plan a trip for an event (OCC; supersedes PLANNING trip) | BandDirector, AssistantDirector |
| GET | `/band/trips` | List trips | Any |
| GET | `/band/trips/{id}` | Get a trip | Any |
| POST | `/band/trips/{id}/open-roster` | Open the trip roster | BandDirector, AssistantDirector |
| POST | `/band/trips/{id}/lock-roster` | Lock the roster (requires a truck charter) | BandDirector, AssistantDirector |
| POST | `/band/trips/{id}/finalize` | Compute final shares; post TRIP_SHARE_DEBITs | BoosterTreasurer |
| POST | `/band/trips/{id}/cancel` | Cancel a trip; refunds all net-paid enrollments | BandDirector |
| POST | `/band/trips/{id}/complete` | Complete a finalized trip (all attendance resolved) | BandDirector, AssistantDirector |
| POST | `/band/trip-enrollments` | Enroll a student in a trip (Student: self only) | BandDirector, AssistantDirector, Student |
| GET | `/band/trip-enrollments` | List enrollments | Any |
| GET | `/band/trip-enrollments/{id}` | Get an enrollment | Any |
| POST | `/band/trip-enrollments/{id}/confirm` | Confirm a registered, fully paid enrollment | BandDirector, AssistantDirector |
| POST | `/band/trip-enrollments/{id}/excuse` | Excuse with a tiered refund; triggers waitlist promotion | BandDirector, AssistantDirector, Student |
| POST | `/band/trip-enrollments/{id}/mark-attendance` | Mark ATTENDED or NO_SHOW after finalize | BandDirector, AssistantDirector |
| POST | `/band/payments` | Post a ledger entry (PAYMENT runs the waterfall) | BoosterTreasurer |
| GET | `/band/payments` | List ledger rows | Any |
| GET | `/band/payments/{id}` | Get a ledger row | Any |
| POST | `/band/fundraisers` | Create a fundraiser | BoosterTreasurer |
| GET | `/band/fundraisers` | List fundraisers | Any |
| GET | `/band/fundraisers/{id}` | Get a fundraiser | Any |
| POST | `/band/fundraisers/{id}/close` | Close and allocate credits by largest remainder | BoosterTreasurer |
| POST | `/band/auditions` | Create an audition for a section | BandDirector, AssistantDirector |
| GET | `/band/auditions` | List auditions | Any |
| GET | `/band/auditions/{id}` | Get an audition | Any |
| POST | `/band/auditions/{id}/finalize-scores` | Compute composites and ranks | BandDirector |
| POST | `/band/auditions/{id}/placements` | Publish chair placements (OCC; supersedes prior publish) | BandDirector |
| POST | `/band/auditions/{id}/challenge` | Section leader challenges placements within 7 days | SectionLeader |
| POST | `/band/audition-entries` | Enter a student into an audition | BandDirector, AssistantDirector |
| GET | `/band/audition-entries` | List audition entries | Any |
| GET | `/band/audition-entries/{id}` | Get an entry | Any |
| POST | `/band/audition-entries/{id}/scores` | Submit one judge's rubric scores | BandDirector, AssistantDirector |
| GET | `/band/chair-placements` | List chair placements | Any |
| GET | `/band/chair-placements/{id}` | Get a placement | Any |
| POST | `/band/truck-charters` | Reserve a vehicle (buffered overlap check) | EquipmentManager |
| GET | `/band/truck-charters` | List charters | Any |
| GET | `/band/truck-charters/{id}` | Get a charter | Any |
| POST | `/band/truck-charters/{id}/loads` | Add a manifest load (capacity checked, weight before volume) | EquipmentManager |
| GET | `/band/truck-loads` | List manifest loads | Any |
| GET | `/band/truck-loads/{id}` | Get a load | Any |
| POST | `/band/truck-charters/{id}/depart` | Depart a loaded charter | EquipmentManager |
| POST | `/band/truck-charters/{id}/return` | Return a departed charter | EquipmentManager |
| POST | `/band/truck-charters/{id}/cancel` | Cancel a charter before departure | EquipmentManager |
| POST | `/band/_clock/set_current_utc` | Set the logical clock; evaluates time-based transitions | BandDirector |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 Forbidden |
| `ERR_SECTION_LEADER_REQUIRED` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_PROGRAM_NOT_FOUND` | 404 Not Found |
| `ERR_STUDENT_NOT_FOUND` | 404 Not Found |
| `ERR_INSTRUMENT_NOT_FOUND` | 404 Not Found |
| `ERR_INSTRUMENT_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_UNIFORM_NOT_FOUND` | 404 Not Found |
| `ERR_UNIFORM_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_CLEANING_BATCH_NOT_FOUND` | 404 Not Found |
| `ERR_ARRANGEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_TRIP_NOT_FOUND` | 404 Not Found |
| `ERR_TRIP_ENROLLMENT_NOT_FOUND` | 404 Not Found |
| `ERR_PAYMENT_NOT_FOUND` | 404 Not Found |
| `ERR_FUNDRAISER_NOT_FOUND` | 404 Not Found |
| `ERR_AUDITION_NOT_FOUND` | 404 Not Found |
| `ERR_AUDITION_ENTRY_NOT_FOUND` | 404 Not Found |
| `ERR_CHAIR_PLACEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_TRUCK_CHARTER_NOT_FOUND` | 404 Not Found |
| `ERR_TRUCK_LOAD_NOT_FOUND` | 404 Not Found |
| `ERR_PROGRAM_NOT_IN_REQUIRED_STATE` | 409 Conflict |
| `ERR_PROGRAM_HAS_OPEN_OBLIGATIONS` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STUDENT_NOT_ENROLLED` | 409 Conflict |
| `ERR_INSTRUMENT_NOT_AVAILABLE` | 409 Conflict |
| `ERR_INSTRUMENT_CHECKED_OUT` | 409 Conflict |
| `ERR_INSTRUMENT_RETIRED` | 409 Conflict |
| `ERR_ASSIGNMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_UNIFORM_NOT_ISSUABLE` | 409 Conflict |
| `ERR_UNIFORM_ASSIGNMENT_NOT_ISSUED` | 409 Conflict |
| `ERR_BATCH_NOT_OPEN` | 409 Conflict |
| `ERR_BATCH_NOT_SENT` | 409 Conflict |
| `ERR_BATCH_EMPTY` | 409 Conflict |
| `ERR_ARRANGEMENT_NOT_QUOTED` | 409 Conflict |
| `ERR_ARRANGEMENT_NOT_APPROVED` | 409 Conflict |
| `ERR_EVENT_NOT_SCHEDULED` | 409 Conflict |
| `ERR_EVENT_TERMINAL` | 409 Conflict |
| `ERR_EVENT_HAS_ACTIVE_TRIP` | 409 Conflict |
| `ERR_TRIP_ROSTER_NOT_OPEN` | 409 Conflict |
| `ERR_TRIP_NOT_LOCKED` | 409 Conflict |
| `ERR_ENROLLMENT_NOT_CONFIRMABLE` | 409 Conflict |
| `ERR_ENROLLMENT_NOT_PAID` | 409 Conflict |
| `ERR_ENROLLMENT_TERMINAL` | 409 Conflict |
| `ERR_UNRESOLVED_ENROLLMENTS_EXIST` | 409 Conflict |
| `ERR_AUDITION_NOT_SCORING` | 409 Conflict |
| `ERR_AUDITION_SCORES_NOT_FINAL` | 409 Conflict |
| `ERR_AUDITION_NOT_PUBLISHED` | 409 Conflict |
| `ERR_SCORES_INCOMPLETE` | 409 Conflict |
| `ERR_CHARTER_NOT_LOADABLE` | 409 Conflict |
| `ERR_CHARTER_EMPTY` | 409 Conflict |
| `ERR_FUNDRAISER_NOT_OPEN` | 409 Conflict |
| `ERR_INSTRUMENT_UNPLAYABLE` | 422 Unprocessable Entity |
| `ERR_EVENT_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_DUE_DATE_INVALID` | 422 Unprocessable Entity |
| `ERR_LICENSE_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_CHALLENGE_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_FACILITY_CONFLICT` | 409 Conflict |
| `ERR_VEHICLE_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_SERIAL_NUMBER_TAKEN` | 409 Conflict |
| `ERR_DUPLICATE_SCORE` | 409 Conflict |
| `ERR_SCORE_OUT_OF_RANGE` | 422 Unprocessable Entity |
| `ERR_ENROLLMENT_DUPLICATE` | 409 Conflict |
| `ERR_GARMENT_TYPE_ALREADY_ISSUED` | 409 Conflict |
| `ERR_INSTRUMENT_TYPE_ALREADY_ASSIGNED` | 409 Conflict |
| `ERR_EVENT_NOT_OUTDOOR` | 422 Unprocessable Entity |
| `ERR_MATCHING_GARMENT_REQUIRED` | 409 Conflict |
| `ERR_CHARTER_REQUIRED` | 409 Conflict |
| `ERR_LOAD_INSTRUMENT_INVALID` | 409 Conflict |
| `ERR_TRUCK_OVERWEIGHT` | 422 Unprocessable Entity |
| `ERR_TRUCK_OVERVOLUME` | 422 Unprocessable Entity |
| `ERR_STUDENT_DELINQUENT_FEES` | 402 Payment Required |
| `ERR_MUSIC_BUDGET_EXCEEDED` | 402 Payment Required |
| `ERR_REPAIR_BUDGET_EXCEEDED` | 402 Payment Required |
| `ERR_REFUND_EXCEEDS_PAID` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
