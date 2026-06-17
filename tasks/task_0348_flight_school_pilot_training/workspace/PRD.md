# Flight School & Pilot Training API — Product Requirements Document

## 1. Introduction

This document specifies the Flight School & Pilot Training API, the operational backbone for a Part-61/Part-141-style training organization. A flight school must coordinate several moving parts at once: students arrive with paperwork that has to clear two independent gates — an FAA medical and a TSA security screening — before a single hour can be flown; aircraft must be scheduled without double-booking and pulled from the line the instant a grounding defect is reported; instructors must be available and credentialed for the endorsements they sign; and every flight consumes real money against a pre-paid block-time deposit that must never be overdrawn.

The API treats each of these concerns as a first-class workflow rather than a side note. It governs the full arc from student enrollment and clearance, through aircraft and instructor scheduling, into the actual logging of Hobbs and Tach meter time, and onward to checkride (stage-check) milestones, maintenance squawk handling, solo rental dispatch, and endorsement issuance. Money is tracked to the cent on a ledger that distinguishes provisional holds from finalized consumption, and physical meter readings are conserved so that an aircraft's logbook can always be reconstructed from its posted flights.

Because dispatch decisions, billing, and safety grounding all interact, the system is built around immediate consistency: a grounded aircraft cancels its open reservations at once, an expired medical suspends an active enrollment, and a posted flight log settles its deposit, advances meters, and rolls up logged hours in a single atomic step. The sections below define the global contract first, then the business workflows, and finally the concrete endpoint and error catalogues.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting principal, and `X-User-Role` declares the capacity in which they are acting. If either header is missing or invalid, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 401). When the headers are present and valid but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The system recognizes exactly five roles, spelled precisely as follows: `SchoolAdmin`, `Dispatcher`, `Student`, `Instructor`, and `Mechanic`. `SchoolAdmin` runs the front office — students, deposits, instructor and aircraft onboarding, syllabi, enrollments and their clearance decisions, and the scheduling of stage checks. `Dispatcher` works the scheduling desk, confirming, dispatching, cancelling, and no-showing bookings and posting or voiding flight logs. `Student` is self-service. `Instructor` is the Certified Flight Instructor (CFI) surface. `Mechanic` owns the maintenance squawk lifecycle that drives aircraft grounding.

These roles are peer-oriented, not a strict hierarchy. Two of them are tied to a persisted entity, and three are operational identities. When `X-User-Role` is `Student`, `X-User-ID` is the `id` of the acting `Student`; any ownership check on a resource that references a student (an enrollment, booking, flight log, or deposit transaction) compares that resource's student foreign key to `X-User-ID`. When `X-User-Role` is `Instructor`, `X-User-ID` is the `id` of the acting `Instructor`; ownership checks on a resource that references an instructor compare the resource's instructor foreign key to `X-User-ID`. When `X-User-Role` is `SchoolAdmin`, `Dispatcher`, or `Mechanic`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit but does not compare it to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items a single response returns; when omitted it defaults to 10, may be no smaller than 1, and may be no larger than 100. The `offset` parameter is the count of leading items to skip and defaults to 0.

Unless a specific workflow states otherwise, every list endpoint returns its resources sorted by creation timestamp (`created_at`) in ascending order. List and array responses carry the pagination bookkeeping in the `meta` object of the envelope, namely `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Identifiers

Most resources in the system are mutable, versioned records. `Student`, `Instructor`, `Aircraft`, `Enrollment`, `Squawk`, `Booking`, `FlightLog`, `StageCheck`, and `Endorsement` each carry four system-managed fields: an `id` that is a server-minted UUID with no type prefix; a `created_at` ISO 8601 UTC timestamp with three fractional digits set at creation; an `updated_at` ISO 8601 UTC timestamp refreshed on every mutation; and a `version`, an integer that begins at 1 and increments by one with each mutation.

Two entities are deliberately leaner. A `Syllabus` is a configuration record that is immutable after creation, and a `DepositTransaction` is an append-only ledger event. Both carry only `id` and `created_at`; neither has an `updated_at` nor a `version`, and that absence is intentional — they are never modified in place.

Whenever a derived field changes on a mutable resource — for example when `current_hobbs` advances on an `Aircraft`, when `deposit_balance_cents` shifts on a `Student`, or when `current_stage_index` increments on an `Enrollment` — that change is itself a mutation: `updated_at` is refreshed and `version` is incremented.

### 2.5. Resource Hierarchy and Path Resolution

The domain is a flat collection of peer entities. Every business entity is its own top-level collection beneath the `/flight-school` mount, and relationships are expressed through foreign-key body fields resolved by filtered list queries rather than by nested URLs. Path resolution is nonetheless ordered: when a request names a resource by an identifier in its path, that resource's existence is verified before any body or business validation runs, and a missing target yields `ERR_NOT_FOUND` (HTTP 404). The same rule applies to foreign keys carried in a request body — every referenced resource (the aircraft, instructor, enrollment, booking, syllabus, or student a payload points to) is validated left-to-right, and the first one that does not exist produces `ERR_NOT_FOUND` before deeper rules are considered.

### 2.6. Hierarchical Consistency and Cascades

Several operations mutate more than one entity at once, and the system applies those cascades immediately and atomically. When an aircraft is grounded, every booking on that aircraft that is still `REQUESTED` or `CONFIRMED` is cancelled, and a cancelled booking that had been `CONFIRMED` releases its provisional deposit hold as part of the same step. When an enrollment leaves `ACTIVE` for `SUSPENDED` or `WITHDRAWN`, its `REQUESTED` and `CONFIRMED` bookings are likewise cancelled (with hold release for the confirmed ones). When a flight log is posted, the deposit ledger is settled, the aircraft meters advance, the enrollment's logged hours roll up, and the underlying booking is driven to `COMPLETED` — all together. Each entity touched by a cascade independently records the change: its `updated_at` is refreshed and, where the entity is versioned, its `version` is incremented. A reconciliation may transition a parent or child without an explicit client request against that specific resource; this is the intended behavior, not an anomaly.

### 2.7. Optimistic Concurrency Control on Aircraft Scheduling

Creating a booking claims a slice of an aircraft's schedule, and to keep two writers from claiming the same slice from stale views, booking creation is guarded by optimistic concurrency on the aircraft's `version`. A booking-create request must carry `expected_aircraft_version`, a non-optional field holding the `version` the client last observed when it read the target aircraft. If that value does not equal the aircraft's current `version`, the create is rejected with `ERR_STALE_AIRCRAFT_VERSION` (HTTP 412). Because any successful booking create advances the aircraft's `version` by one — as does an automatic grounding — a client whose view predates another writer's create or a grounding is, by definition, stale, and its create is refused so that two strictly sequential creates carrying the same observed version cannot both succeed. No other endpoint takes a version field; this OCC field exists only on booking creation.

### 2.8. Money, Meters, and Rounding Precision

All monetary amounts in the system are integer cents — deposits, holds, charges, and balances alike — and ledger arithmetic introduces no rounding because every amount is already a whole number of cents. Where money is derived from a rate multiplied by hours, however, rounding does occur and its order is pinned. For the booking cost estimate, each rate-times-hours product (the aircraft portion, and the instructor portion when applicable) is rounded half up to whole cents *before* the portions are summed — round-then-sum, never sum-then-round. For the flight charge, the meter delta is first rounded half up to one decimal place (tenths of an hour), then multiplied by the rate, then that product is rounded half up to whole cents; the raw product is never rounded directly at the cent level. Meter readings themselves are carried to one decimal place, and meter deltas are summed exactly.

### 2.9. Aircraft Grounding and Maintenance Safety

An aircraft's airworthiness is governed entirely by its open grounding squawks. The field `open_squawk_count` tracks how many grounding squawks are currently `OPEN` on the aircraft. Whenever that count is at least one, the aircraft is `GROUNDED`; when it returns to zero, the aircraft is `AVAILABLE` again. A `GROUNDED` (or `RETIRED`) aircraft cannot be confirmed or dispatched for a flight — both operations reject with `ERR_AIRCRAFT_GROUNDED` (HTTP 409). The grounding and un-grounding transitions are automatic system effects driven by the squawk lifecycle described in §3, never direct client calls against the aircraft.

### 2.10. Deposit Ledger Principles

Each student's block-time funds are tracked across three computed running totals and an append-only ledger of `DepositTransaction` events. `deposit_balance_cents` is the spendable balance, `deposit_held_cents` is the sum currently provisionally held against in-flight confirmed and dispatched bookings, and `deposit_consumed_cents` is the funds finalized against posted flight logs. Every ledger event has a `txn_type` of `DEPOSIT`, `HOLD`, `RELEASE`, or `CONSUME`, an `amount_cents` that is always a positive magnitude (the type fixes the sign), and — where the event arises from a booking or flight — a `booking_id` and, for consumption that finalizes a posted flight, a `flight_log_id`. The three totals are not free-floating: at all times after any settlement, `deposit_balance_cents` equals the sum of all `DEPOSIT` amounts, minus the sum of all `HOLD` amounts, plus the sum of all `RELEASE` amounts, minus the sum of all `CONSUME` amounts; `deposit_held_cents` equals the sum of all `HOLD` amounts minus the sum of all `RELEASE` amounts; and `deposit_consumed_cents` equals the sum of all `CONSUME` amounts. These invariants hold to the cent on every mutation.

### 2.11. Request Validation Ordering

Mutating requests are validated in a fixed priority order so that the same failure always surfaces the same error. First, authentication: missing or invalid `X-User-ID`/`X-User-Role` headers yield `ERR_MISSING_OR_INVALID_USER_CONTEXT` (401). Second, authorization: a role not permitted for the operation yields `ERR_INSUFFICIENT_PERMISSIONS` (403). Third, existence: any path or foreign-key-referenced resource that does not exist yields `ERR_NOT_FOUND` (404), checked left-to-right. Fourth, request shape: a malformed body — a missing required field, an invalid enum value, or an out-of-range number (`landings` below 1, any hours value not strictly greater than 0, or an `amount_cents` not strictly greater than 0) — yields `ERR_INVALID_REQUEST` (400). Fifth, for booking creation only, the optimistic-concurrency check on `expected_aircraft_version` runs (after existence and request-shape but before the remaining business rules), yielding `ERR_STALE_AIRCRAFT_VERSION` (412) on a mismatch and otherwise advancing the aircraft's `version`. Sixth, state: a target not in the correct state for the requested transition yields the transition's specific state error (HTTP 409), such as `ERR_BOOKING_NOT_REQUESTED`, `ERR_FLIGHT_LOG_NOT_DRAFT`, or `ERR_STAGE_CHECK_NOT_SCHEDULED`. Beyond these, the workflow-specific safety, temporal, referential, and fiscal checks described in §3 apply in the order narrated there.

## 3. Business Logic & Workflows

### 3.1. Onboarding the Roster: Students, Instructors, Aircraft, and Syllabi

A `SchoolAdmin` populates the operational roster. Creating a student requires only a `full_name` and a unique `email`; the new record starts with `status` of `ACTIVE`, a `no_show_strikes` count of zero, and all three deposit totals — `deposit_balance_cents`, `deposit_held_cents`, and `deposit_consumed_cents` — set to zero. Funds are added later by recording a block-time deposit on the student: the payload carries the `amount_cents` to add and an optional `memo`, which appends a `DEPOSIT` ledger event and increases `deposit_balance_cents` by that amount.

Creating an instructor records the CFI's `full_name`, unique `email`, a billing rate `cfi_rate_cents_per_hour` charged per logged Hobbs hour, and the list of `authorized_endorsement_codes` the CFI is permitted to sign (drawn from `SOLO`, `XC`, `COMPLEX`, and `TAILWHEEL`). A new instructor's `status` is `ACTIVE` and may later be `INACTIVE`.

Onboarding an aircraft records its unique `tail_number`, its `model`, the wet rental rate `rental_rate_cents_per_hour`, the `billing_basis` of either `HOBBS` or `TACH` that selects which meter bills flight time, the onboarding meter readings `initial_hobbs` and `initial_tach`, and an optional `is_complex` flag that defaults to false and drives the complexity surcharge tier on bookings. At creation the aircraft is `AVAILABLE`, its `open_squawk_count` is zero, its `version` is 1, and its live meters `current_hobbs` and `current_tach` are initialized from `initial_hobbs` and `initial_tach` respectively. Those live meters advance only when a flight log is posted; they never move on any other operation. An aircraft's `status` may be `AVAILABLE`, `GROUNDED`, or `RETIRED`. Retiring an aircraft is restricted to a `SchoolAdmin` and is permitted only from `AVAILABLE`: a `GROUNDED` or already-`RETIRED` aircraft cannot be retired and yields `ERR_AIRCRAFT_NOT_AVAILABLE`, and an aircraft with any booking still in `REQUESTED`, `CONFIRMED`, or `DISPATCHED` cannot be retired and yields `ERR_AIRCRAFT_HAS_ACTIVE_BOOKINGS`. A successful retire moves the aircraft to `RETIRED` and increments its `version` by one.

A syllabus defines a training program and, once created, is immutable. It carries a `name`, the total `required_dual_hours` of dual instruction and `required_solo_hours` of solo time needed to finish, a `stage_count` giving how many ordered stage checks the program contains, and a `min_deposit_cents` — the minimum block-time balance a student must hold before an enrollment against this syllabus may go active.

### 3.2. Enrollment and the Two Parallel Clearance Gates

Enrolling a student into a syllabus is a `SchoolAdmin` action that carries the `student_id` and `syllabus_id`. A fresh enrollment opens in `PENDING_CLEARANCE` with both clearance axes pending: `medical_status` is `PENDING` and `tsa_status` is `PENDING`. Its `current_stage_index` starts at 1, and `logged_dual_hours` and `logged_solo_hours` both start at zero. These two clearance dimensions are independent of each other and of the lifecycle `status`. The medical axis (`medical_status`) may be `PENDING`, `CLEARED`, or `EXPIRED`; the security axis (`tsa_status`) may be `PENDING`, `CLEARED`, or `DENIED`.

A `SchoolAdmin` records a clearance decision on exactly one axis at a time. The request names the `clearance_type` and the `decision`, and for a medical clearance may carry a `medical_expiry_date`. When the `clearance_type` is `MEDICAL`, the `decision` sets `medical_status` to either `CLEARED` or `EXPIRED`, and `medical_expiry_date` is recorded — the ISO date the FAA medical lapses — when the decision is `CLEARED`. When the `clearance_type` is `TSA`, the `decision` sets `tsa_status` to either `CLEARED` or `DENIED`. A decision that does not fit its axis — for example a medical decision of `DENIED`, or a TSA decision of `EXPIRED` — is rejected with `ERR_INVALID_CLEARANCE_DECISION` (HTTP 400). Recording a medical decision of `EXPIRED` on an enrollment that is currently `ACTIVE` cascades the enrollment from `ACTIVE` to `SUSPENDED`.

Activation is the lifecycle gate that opens flying. A `SchoolAdmin` activates an enrollment that is in `PENDING_CLEARANCE` or `SUSPENDED`; an enrollment in any other state is rejected with `ERR_ENROLLMENT_NOT_PENDING_OR_SUSPENDED`. Activation requires both clearance axes to be satisfied: `medical_status` must be `CLEARED` or the request fails with `ERR_MEDICAL_NOT_CLEARED`, and `tsa_status` must be `CLEARED` or it fails with `ERR_TSA_NOT_CLEARED`. The student's spendable balance, `deposit_balance_cents`, must be at least the syllabus's `min_deposit_cents`, failing with `ERR_DEPOSIT_BELOW_MINIMUM` (HTTP 402) otherwise. When the enrollment being activated is coming back from `SUSPENDED`, one additional gate applies: the student's `no_show_strikes` must be below the no-show suspension threshold (`NO_SHOW_SUSPEND_THRESHOLD`), or re-activation is refused with `ERR_STUDENT_SUSPENDED`. A successful activation moves the enrollment to `ACTIVE`.

An `ACTIVE` enrollment may be suspended explicitly by a `SchoolAdmin`; the explicit suspend requires the enrollment to be `ACTIVE`, otherwise it is rejected with `ERR_ENROLLMENT_NOT_ACTIVE_FOR_SUSPEND`. Suspension moves the enrollment from `ACTIVE` to `SUSPENDED` and cascades a cancellation of every `REQUESTED` or `CONFIRMED` booking on that enrollment, releasing the deposit holds of the confirmed ones. Withdrawal is also a `SchoolAdmin` action and is permitted from `PENDING_CLEARANCE`, `ACTIVE`, or `SUSPENDED`, moving the enrollment to `WITHDRAWN`; withdrawing from `PENDING_CLEARANCE` or `ACTIVE` cascades the same cancellation of `REQUESTED`/`CONFIRMED` bookings, whereas a withdrawal from `SUSPENDED` carries no booking cascade (its open bookings were already cancelled at suspension). `COMPLETED` and `WITHDRAWN` are terminal.

Completing an enrollment is the graduation step, restricted to a `SchoolAdmin` and permitted only from `ACTIVE`. Four conditions must all hold. The accumulated `logged_dual_hours` must be at least the syllabus's `required_dual_hours`, and `logged_solo_hours` at least `required_solo_hours`; a shortfall on either yields `ERR_HOURS_NOT_MET`. Every stage check must have passed, which is the case exactly when `current_stage_index` has advanced beyond the syllabus's `stage_count` — otherwise the completion is rejected with `ERR_STAGES_NOT_PASSED`. Finally, no booking on the enrollment may still be `REQUESTED`, `CONFIRMED`, or `DISPATCHED`, or completion fails with `ERR_ENROLLMENT_HAS_ACTIVE_BOOKINGS`. When all four hold, the enrollment moves to `COMPLETED`.

### 3.3. Scheduling a Booking and the Aircraft Schedule Claim

A booking reserves an aircraft (and, for dual instruction, an instructor) for a time window. Either a `Student` or a `Dispatcher` requests one, supplying the `enrollment_id`, the `aircraft_id`, the `lesson_type`, the reservation window's `start_at` and `end_at`, the planned `estimated_hours` used to size the provisional hold, and — as described in §2.7 — the `expected_aircraft_version`. For a dual lesson the payload also names the `instructor_id`; for a solo rental dispatch the instructor is omitted. The `lesson_type` is either `DUAL`, which requires an instructor, or `SOLO`, which requires a valid solo endorsement at dispatch time. The reservation window is half-open: it covers `start_at` up to but not including `end_at`.

Creating the booking first passes the optimistic-concurrency check on `expected_aircraft_version`, then opens the booking in `REQUESTED`, computes its `estimated_cost_cents` via the booking cost estimate (see §3.7), and increments the aircraft's `version` by one to record that this create has claimed a slice of the aircraft's schedule. The new booking's `estimated_cost_cents` is computed once at creation and never recomputed afterward.

Confirmation is a `Dispatcher` action that takes a booking from `REQUESTED` to `CONFIRMED`. The booking must be in `REQUESTED`, otherwise `ERR_BOOKING_NOT_REQUESTED`. The aircraft must be `AVAILABLE`, otherwise `ERR_AIRCRAFT_GROUNDED`. The requested window must not overlap, on a half-open `[start_at, end_at)` basis, any other booking on the same aircraft that is `REQUESTED`, `CONFIRMED`, or `DISPATCHED`; an overlap yields `ERR_AIRCRAFT_TIME_CONFLICT`. For a dual booking, the assigned instructor must have no other booking falling within the instructor buffer (`INSTRUCTOR_BUFFER_MINUTES`) of the requested window — the requested window treated as a closed interval extended by that buffer on each side — or the confirm is rejected with `ERR_INSTRUCTOR_TIME_CONFLICT`. Finally, the student's `deposit_balance_cents` must be at least the booking's `estimated_cost_cents`, or the confirm fails with `ERR_INSUFFICIENT_DEPOSIT` (HTTP 402). On success the booking becomes `CONFIRMED` and a provisional hold of `estimated_cost_cents` is placed on the deposit ledger (see §3.7).

Dispatching is a `Dispatcher` action moving a booking from `CONFIRMED` to `DISPATCHED`, releasing the aircraft for the flight; the hold was already placed at confirm, so dispatch places no new hold. The booking must be `CONFIRMED`, otherwise `ERR_BOOKING_NOT_CONFIRMED`. The aircraft must be `AVAILABLE`, otherwise `ERR_AIRCRAFT_GROUNDED`. The enrollment must be `ACTIVE`, otherwise `ERR_ENROLLMENT_NOT_ACTIVE`, and its `medical_status` must be `CLEARED`, otherwise `ERR_MEDICAL_NOT_CLEARED`. If the `lesson_type` is `SOLO`, a `VALID` solo endorsement must exist for the enrollment, or dispatch fails with `ERR_SOLO_ENDORSEMENT_MISSING`.

A booking may be cancelled by the `Student` or a `Dispatcher`. The explicit cancel requires the booking to be `REQUESTED` or `CONFIRMED`; a terminal booking — `COMPLETED`, `CANCELLED`, or `NO_SHOW` — cannot be cancelled and yields `ERR_BOOKING_NOT_CANCELLABLE`. Cancelling a booking that was merely `REQUESTED` simply moves it to `CANCELLED` with no ledger effect, since no hold had been placed. Cancelling a booking that was `CONFIRMED` moves it to `CANCELLED` and releases the held `estimated_cost_cents` back to the balance. The same `CANCELLED` outcome and the same hold-release-for-confirmed behavior occur when the system cancels bookings as a cascade — when an aircraft is grounded or an enrollment is suspended or withdrawn.

A `Dispatcher` may mark a `CONFIRMED` booking as a no-show; the booking must be `CONFIRMED`, otherwise `ERR_BOOKING_NOT_CONFIRMED`. A no-show moves the booking to `NO_SHOW`, releases the held `estimated_cost_cents` back to the student's balance, and increments the student's `no_show_strikes` by one. If that increment brings `no_show_strikes` to at least the no-show suspension threshold (`NO_SHOW_SUSPEND_THRESHOLD`) and the related enrollment is currently `ACTIVE`, the enrollment cascades from `ACTIVE` to `SUSPENDED` — which in turn cancels that enrollment's other open bookings as described in §3.2. A student whose `no_show_strikes` has reached the threshold carries `status` `SUSPENDED` rather than `ACTIVE`.

### 3.4. Flying the Flight: Logging and Posting Hobbs/Tach Time

After a booking is dispatched, the flight is recorded as a flight log. Either an `Instructor` or a `Dispatcher` creates a draft log against the dispatched booking, supplying the `booking_id`, the engine-start and shutdown meter readings `hobbs_start`, `hobbs_end`, `tach_start`, and `tach_end`, and the number of `landings`, which must be at least 1. On creation the log opens in `DRAFT`, and the `enrollment_id`, `aircraft_id`, and `instructor_id` are copied from the booking (the instructor being null for a solo flight). The log's billing fields — `billed_hours`, `aircraft_charge_cents`, `instructor_charge_cents`, and `total_charge_cents` — are not computed at draft time; they are filled in at post.

Posting a flight log is the finalizing step, performed by an `Instructor` or a `Dispatcher`, that takes the log from `DRAFT` to `POSTED`. The log must be `DRAFT`, otherwise `ERR_FLIGHT_LOG_NOT_DRAFT`, and its booking must be `DISPATCHED`, otherwise `ERR_BOOKING_NOT_DISPATCHED`. The meter readings must be sane: `hobbs_end` must be strictly greater than `hobbs_start` and `tach_end` strictly greater than `tach_start`, or the post is rejected with `ERR_INVALID_METER_READING` (HTTP 400). The readings must also be continuous with the aircraft's live meters: `hobbs_start` must equal the aircraft's `current_hobbs` and `tach_start` must equal its `current_tach`, or the post is rejected with `ERR_METER_DISCONTINUITY`. Fiscally, the student must be able to cover the actual charge given that the estimate was already held — that is, `deposit_balance_cents` plus the booking's held `estimated_cost_cents` must be at least the computed `total_charge_cents`, or the post fails with `ERR_INSUFFICIENT_DEPOSIT` (HTTP 402).

A successful post does five things atomically. It computes `billed_hours`, `aircraft_charge_cents`, `instructor_charge_cents`, and `total_charge_cents` via the flight-charge calculation (see §3.7). It settles the deposit: the held `estimated_cost_cents` is released and the actual `total_charge_cents` is consumed (see §3.7). It advances the aircraft's live meters, setting `current_hobbs` to `hobbs_end` and `current_tach` to `tach_end`, which increments the aircraft's `version` by one. It rolls the flight's `billed_hours` into the enrollment — into `logged_dual_hours` when the booking's `lesson_type` is `DUAL`, or into `logged_solo_hours` when it is `SOLO`. And it cascades the underlying booking from `DISPATCHED` to `COMPLETED`. A draft that is no longer wanted can instead be voided by a `Dispatcher`, moving it from `DRAFT` to `VOID`; the log must be `DRAFT`, otherwise `ERR_FLIGHT_LOG_NOT_DRAFT`. A `VOID` or `DRAFT` log contributes nothing to meters or hours.

The aircraft hour ledger is conserved. At any time the aircraft's `current_hobbs` equals its `initial_hobbs` plus the sum, over all of that aircraft's `POSTED` flight logs taken in chronological order of `created_at` ascending (ties broken by `created_at` ascending), of each log's `hobbs_end` minus `hobbs_start`. Because the discontinuity check forbids a start reading that does not match the live meter, the meter never moves backward. Likewise, an enrollment's `logged_dual_hours` is the exact sum of `billed_hours` across that enrollment's `POSTED` flight logs whose booking `lesson_type` is `DUAL`, and `logged_solo_hours` the exact sum where the `lesson_type` is `SOLO`.

### 3.5. Maintenance Squawks and Automatic Grounding

Maintenance defects are tracked as squawks. A `Mechanic` or an `Instructor` reports one against an aircraft, supplying the `aircraft_id`, a `description` of the defect, and the `is_grounding` flag indicating whether the defect grounds the aircraft until resolved; when the report comes from an instructor, the optional `reported_by_instructor_id` records who filed it (omitted when a mechanic files it). A new squawk opens in `OPEN`. If it is a grounding squawk, reporting it increments the aircraft's `open_squawk_count` by one, and if the aircraft was `AVAILABLE` this cascades it from `AVAILABLE` to `GROUNDED` — which itself cancels the aircraft's `REQUESTED` and `CONFIRMED` bookings (releasing holds on the confirmed ones) and increments the aircraft's `version` by one. A squawk's `status` may be `OPEN`, `DEFERRED`, or `RESOLVED`.

Only a `Mechanic` works the squawk lifecycle from there. Resolving a squawk requires it to be `OPEN` or `DEFERRED`, otherwise `ERR_SQUAWK_NOT_RESOLVABLE`; resolution moves it to `RESOLVED`, and if it was a grounding squawk that had been `OPEN`, decrements the aircraft's `open_squawk_count`, and if it was the last open grounding squawk, cascades the aircraft from `GROUNDED` back to `AVAILABLE` (incrementing the aircraft's `version`). Deferring a squawk requires it to be `OPEN`, otherwise `ERR_SQUAWK_NOT_OPEN`, and additionally requires that it is not a grounding squawk — a grounding squawk cannot be deferred and yields `ERR_GROUNDING_SQUAWK_NOT_DEFERRABLE`; a successful defer moves it to `DEFERRED` with no aircraft effect. Reopening a squawk requires it to be `RESOLVED` or `DEFERRED`, otherwise `ERR_SQUAWK_NOT_REOPENABLE`; reopening moves it back to `OPEN`. Reopening a grounding squawk increments the aircraft's `open_squawk_count`, and if that grounding squawk's reopen finds the aircraft `AVAILABLE`, it cascades the aircraft from `AVAILABLE` to `GROUNDED` (which itself cancels open bookings). Reopening a non-grounding deferred squawk simply returns it to `OPEN` with no aircraft effect.

### 3.6. Stage Checks and Endorsements

Stage checks are the ordered checkride milestones within a syllabus. A `SchoolAdmin` or an `Instructor` schedules one, supplying the `enrollment_id`, the `examiner_instructor_id` conducting it, the 1-based `stage_index` within the syllabus, and — when this is a retry of a previously failed check — the `retry_of_stage_check_id` pointing at that failed stage check. A new stage check opens in `SCHEDULED`, and an `Instructor` drives it from there.

Beginning a stage check moves it from `SCHEDULED` to `IN_PROGRESS`. The check must be `SCHEDULED`, otherwise `ERR_STAGE_CHECK_NOT_SCHEDULED`; the enrollment must be `ACTIVE`, otherwise `ERR_ENROLLMENT_NOT_ACTIVE`; and the check's `stage_index` must equal the enrollment's `current_stage_index`, ensuring stages are attempted in order, or it is rejected with `ERR_STAGE_OUT_OF_ORDER`. From `IN_PROGRESS`, the examining `Instructor` records the outcome, optionally attaching a `result_note`. Passing requires the check to be `IN_PROGRESS`, otherwise `ERR_STAGE_CHECK_NOT_IN_PROGRESS`; a pass moves it to `PASSED` and increments the enrollment's `current_stage_index` by one, opening the next stage. Failing likewise requires `IN_PROGRESS`, otherwise `ERR_STAGE_CHECK_NOT_IN_PROGRESS`; a fail moves the check to `FAILED` and leaves `current_stage_index` unchanged. `FAILED` is not a dead end: a fresh stage check may later be scheduled with its `retry_of_stage_check_id` referencing this failed one, which restarts the loop at `SCHEDULED`. `PASSED` is terminal.

Endorsements are the privileges a CFI signs off. An `Instructor` issues one to an enrollment, supplying the `enrollment_id`, the issuing `instructor_id`, and the `endorsement_code` — one of `SOLO`, `XC`, `COMPLEX`, or `TAILWHEEL`. An instructor may only issue an endorsement whose `endorsement_code` is among that instructor's `authorized_endorsement_codes`; an attempt to sign a code outside the instructor's authorization is refused with `ERR_ENDORSEMENT_NOT_AUTHORIZED` (HTTP 403). A new endorsement is `VALID`. An `Instructor` may later revoke a valid endorsement, moving its `status` to `REVOKED`; the endorsement must be `VALID` to revoke, otherwise `ERR_ENDORSEMENT_NOT_VALID`. A solo dispatch, as noted in §3.3, depends on a `VALID` `SOLO` endorsement existing for the enrollment.

### 3.7. Pricing, Holds, and Settlement

Three calculations turn flight activity into money, and their order of operations matters.

The **booking cost estimate** is computed once when a booking is created and sizes the provisional hold. Let the planned hours be the booking's `estimated_hours`, carried to two decimal places. The aircraft portion is the aircraft's `rental_rate_cents_per_hour` multiplied by those hours, rounded half up to whole cents. The instructor portion, for a `DUAL` lesson, is the instructor's `cfi_rate_cents_per_hour` multiplied by the same hours, rounded half up to whole cents; for a `SOLO` lesson the instructor portion is zero. A complexity surcharge then applies to the aircraft portion only: if the aircraft's `is_complex` is false the surcharge percentage is zero; if it is true and the planned hours are at most the complex tier-one threshold of 2.0 hours the surcharge percentage is 10 percent; if it is true and the planned hours exceed 2.0 hours the surcharge percentage is 15 percent. The surcharge in cents is the aircraft portion multiplied by that percentage, rounded half up to whole cents. The booking's `estimated_cost_cents` is then the aircraft portion plus the surcharge plus the instructor portion — each product rounded to cents before this final sum.

The **flight charge** is computed at post and produces the log's billing fields, and which meter drives it depends on the aircraft's `billing_basis`. When the basis is `HOBBS`, the raw meter delta is `hobbs_end` minus `hobbs_start` (the engine-running clock, which yields the larger delta); when the basis is `TACH`, the raw delta is `tach_end` minus `tach_start` (the rpm-scaled clock, which yields a smaller delta and so a different charge for the identical flight). The `billed_hours` is that raw delta rounded half up to one decimal place — the tenths rounding happens first, before any multiplication. The `aircraft_charge_cents` is the aircraft's `rental_rate_cents_per_hour` multiplied by `billed_hours`, with that product rounded half up to whole cents. For a `DUAL` booking the `instructor_charge_cents` is the instructor's `cfi_rate_cents_per_hour` multiplied by `billed_hours`, rounded half up to whole cents; for a `SOLO` booking it is zero. The `total_charge_cents` is `aircraft_charge_cents` plus `instructor_charge_cents`.

The **deposit settlement** moves money on the student ledger in two variants. The provisional variant fires when a booking is confirmed: it records a `HOLD` for the booking's `estimated_cost_cents`, increasing `deposit_held_cents` by that amount and decreasing `deposit_balance_cents` by the same amount. The final variant fires when a flight log is posted: it records a `RELEASE` for the booking's `estimated_cost_cents` and a `CONSUME` for the flight log's `total_charge_cents`. The release reduces `deposit_held_cents` by the estimate, the consume increases `deposit_consumed_cents` by the actual charge, and `deposit_balance_cents` is adjusted by the estimate minus the actual — a net change that may be positive when the flight came in under estimate or negative when it ran over. Booking cancellation of a confirmed booking and a no-show each record a `RELEASE` for the booking's `estimated_cost_cents`, returning the held funds to the balance. All these amounts are whole cents and no rounding is introduced at settlement. The ledger invariants of §2.10 hold after every one of these events.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code; operations that modify or transition an existing resource return a `200 OK` status code. List and read operations return `200 OK`. The request body, response body, and side effects of each operation are not repeated here — they are defined in the §3 workflow narratives above; this table is a routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/flight-school/students` | Create a student account | SchoolAdmin |
| GET | `/flight-school/students` | List students | SchoolAdmin, Dispatcher |
| GET | `/flight-school/students/{studentId}` | Get a student | SchoolAdmin, Dispatcher, Student |
| POST | `/flight-school/students/{studentId}/deposits` | Add a block-time deposit to a student | SchoolAdmin |
| GET | `/flight-school/deposit-transactions` | List deposit ledger entries (filter by student, booking, or flight log) | SchoolAdmin, Dispatcher, Student |
| GET | `/flight-school/deposit-transactions/{depositTransactionId}` | Get a single deposit ledger entry | SchoolAdmin, Dispatcher, Student |
| POST | `/flight-school/instructors` | Create an instructor (CFI) | SchoolAdmin |
| GET | `/flight-school/instructors` | List instructors | SchoolAdmin, Dispatcher, Student |
| GET | `/flight-school/instructors/{instructorId}` | Get an instructor | SchoolAdmin, Dispatcher, Student, Instructor |
| POST | `/flight-school/aircraft` | Onboard an aircraft | SchoolAdmin |
| GET | `/flight-school/aircraft` | List aircraft (filter by status) | SchoolAdmin, Dispatcher, Student, Instructor, Mechanic |
| GET | `/flight-school/aircraft/{aircraftId}` | Get an aircraft (carries version for OCC) | SchoolAdmin, Dispatcher, Student, Instructor, Mechanic |
| POST | `/flight-school/aircraft/{aircraftId}/retire` | Retire an aircraft | SchoolAdmin |
| POST | `/flight-school/squawks` | Report a maintenance squawk | Mechanic, Instructor |
| GET | `/flight-school/squawks` | List squawks (filter by aircraft, reporting instructor, or status) | SchoolAdmin, Dispatcher, Mechanic, Instructor |
| GET | `/flight-school/squawks/{squawkId}` | Get a squawk | SchoolAdmin, Dispatcher, Mechanic, Instructor |
| POST | `/flight-school/squawks/{squawkId}/resolve` | Resolve a squawk | Mechanic |
| POST | `/flight-school/squawks/{squawkId}/defer` | Defer a non-grounding squawk | Mechanic |
| POST | `/flight-school/squawks/{squawkId}/reopen` | Reopen a resolved or deferred squawk | Mechanic |
| POST | `/flight-school/syllabi` | Create a syllabus / program (immutable) | SchoolAdmin |
| GET | `/flight-school/syllabi` | List syllabi | SchoolAdmin, Dispatcher, Student, Instructor |
| GET | `/flight-school/syllabi/{syllabusId}` | Get a syllabus | SchoolAdmin, Dispatcher, Student, Instructor |
| POST | `/flight-school/enrollments` | Enroll a student into a syllabus | SchoolAdmin |
| GET | `/flight-school/enrollments` | List enrollments (filter by student or syllabus) | SchoolAdmin, Dispatcher, Student, Instructor |
| GET | `/flight-school/enrollments/{enrollmentId}` | Get an enrollment | SchoolAdmin, Dispatcher, Student, Instructor |
| POST | `/flight-school/enrollments/{enrollmentId}/clearance` | Record a clearance decision (medical or TSA) | SchoolAdmin |
| POST | `/flight-school/enrollments/{enrollmentId}/activate` | Activate an enrollment | SchoolAdmin |
| POST | `/flight-school/enrollments/{enrollmentId}/suspend` | Suspend an active enrollment | SchoolAdmin |
| POST | `/flight-school/enrollments/{enrollmentId}/complete` | Complete an enrollment | SchoolAdmin |
| POST | `/flight-school/enrollments/{enrollmentId}/withdraw` | Withdraw an enrollment | SchoolAdmin |
| POST | `/flight-school/bookings` | Request a booking (OCC-guarded on aircraft version) | Student, Dispatcher |
| GET | `/flight-school/bookings` | List bookings (filter by enrollment, aircraft, instructor, or status) | SchoolAdmin, Dispatcher, Student, Instructor |
| GET | `/flight-school/bookings/{bookingId}` | Get a booking | SchoolAdmin, Dispatcher, Student, Instructor |
| POST | `/flight-school/bookings/{bookingId}/confirm` | Confirm a requested booking | Dispatcher |
| POST | `/flight-school/bookings/{bookingId}/dispatch` | Dispatch a confirmed booking | Dispatcher |
| POST | `/flight-school/bookings/{bookingId}/cancel` | Cancel a requested or confirmed booking | Student, Dispatcher |
| POST | `/flight-school/bookings/{bookingId}/no-show` | Mark a confirmed booking as a no-show | Dispatcher |
| POST | `/flight-school/flight-logs` | Create a draft flight log against a dispatched booking | Instructor, Dispatcher |
| GET | `/flight-school/flight-logs` | List flight logs (filter by booking, enrollment, aircraft, instructor, or status) | SchoolAdmin, Dispatcher, Student, Instructor |
| GET | `/flight-school/flight-logs/{flightLogId}` | Get a flight log | SchoolAdmin, Dispatcher, Student, Instructor |
| POST | `/flight-school/flight-logs/{flightLogId}/post` | Post a flight log (charge, settle, advance meters, roll up hours) | Instructor, Dispatcher |
| POST | `/flight-school/flight-logs/{flightLogId}/void` | Void a draft flight log | Dispatcher |
| POST | `/flight-school/stage-checks` | Schedule a stage check (or a retry) | SchoolAdmin, Instructor |
| GET | `/flight-school/stage-checks` | List stage checks (filter by enrollment, examiner, retried check, or status) | SchoolAdmin, Dispatcher, Student, Instructor |
| GET | `/flight-school/stage-checks/{stageCheckId}` | Get a stage check | SchoolAdmin, Dispatcher, Student, Instructor |
| POST | `/flight-school/stage-checks/{stageCheckId}/begin` | Begin a scheduled stage check | Instructor |
| POST | `/flight-school/stage-checks/{stageCheckId}/pass` | Pass a stage check | Instructor |
| POST | `/flight-school/stage-checks/{stageCheckId}/fail` | Fail a stage check | Instructor |
| POST | `/flight-school/endorsements` | Issue an endorsement to an enrollment | Instructor |
| GET | `/flight-school/endorsements` | List endorsements (filter by enrollment or instructor) | SchoolAdmin, Dispatcher, Student, Instructor |
| GET | `/flight-school/endorsements/{endorsementId}` | Get an endorsement | SchoolAdmin, Dispatcher, Student, Instructor |
| POST | `/flight-school/endorsements/{endorsementId}/revoke` | Revoke a valid endorsement | Instructor |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT` | 401 Unauthorized |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_AIRCRAFT_VERSION` | 412 Precondition Failed |
| `ERR_BOOKING_NOT_REQUESTED` | 409 Conflict |
| `ERR_BOOKING_NOT_CONFIRMED` | 409 Conflict |
| `ERR_BOOKING_NOT_DISPATCHED` | 409 Conflict |
| `ERR_BOOKING_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_AIRCRAFT_GROUNDED` | 409 Conflict |
| `ERR_AIRCRAFT_TIME_CONFLICT` | 409 Conflict |
| `ERR_INSTRUCTOR_TIME_CONFLICT` | 409 Conflict |
| `ERR_INSUFFICIENT_DEPOSIT` | 402 Payment Required |
| `ERR_ENROLLMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_MEDICAL_NOT_CLEARED` | 409 Conflict |
| `ERR_TSA_NOT_CLEARED` | 409 Conflict |
| `ERR_SOLO_ENDORSEMENT_MISSING` | 409 Conflict |
| `ERR_AIRCRAFT_HAS_ACTIVE_BOOKINGS` | 409 Conflict |
| `ERR_AIRCRAFT_NOT_AVAILABLE` | 409 Conflict |
| `ERR_SQUAWK_NOT_OPEN` | 409 Conflict |
| `ERR_SQUAWK_NOT_RESOLVABLE` | 409 Conflict |
| `ERR_SQUAWK_NOT_REOPENABLE` | 409 Conflict |
| `ERR_GROUNDING_SQUAWK_NOT_DEFERRABLE` | 409 Conflict |
| `ERR_FLIGHT_LOG_NOT_DRAFT` | 409 Conflict |
| `ERR_INVALID_METER_READING` | 400 Bad Request |
| `ERR_METER_DISCONTINUITY` | 409 Conflict |
| `ERR_ENROLLMENT_NOT_PENDING_OR_SUSPENDED` | 409 Conflict |
| `ERR_ENROLLMENT_NOT_ACTIVE_FOR_SUSPEND` | 409 Conflict |
| `ERR_DEPOSIT_BELOW_MINIMUM` | 402 Payment Required |
| `ERR_STUDENT_SUSPENDED` | 409 Conflict |
| `ERR_HOURS_NOT_MET` | 409 Conflict |
| `ERR_STAGES_NOT_PASSED` | 409 Conflict |
| `ERR_ENROLLMENT_HAS_ACTIVE_BOOKINGS` | 409 Conflict |
| `ERR_INVALID_CLEARANCE_DECISION` | 400 Bad Request |
| `ERR_STAGE_CHECK_NOT_SCHEDULED` | 409 Conflict |
| `ERR_STAGE_CHECK_NOT_IN_PROGRESS` | 409 Conflict |
| `ERR_STAGE_OUT_OF_ORDER` | 409 Conflict |
| `ERR_ENDORSEMENT_NOT_AUTHORIZED` | 403 Forbidden |
| `ERR_ENDORSEMENT_NOT_VALID` | 409 Conflict |
