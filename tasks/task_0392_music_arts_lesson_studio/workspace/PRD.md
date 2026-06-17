# Music Arts Lesson Studio API — Product Requirements Document

## 1. Introduction

The Music & Arts Lesson Studio API is the operational backbone for a multi-disciplinary teaching studio that pairs students with instructors and instruments, runs a recurring weekly lesson schedule across a finite set of rooms, and reconciles the tuition, makeup, and rental economics that flow from that schedule. A studio juggles several moving parts at once: a recurring lesson must fit an instructor's published availability, occupy a room equipped for the right instrument, and never collide with another lesson on the same instructor or in the same room. When a family freezes or cancels an enrollment, future lessons must unwind cleanly and — where the cancellation was timely — convert into reusable makeup credits rather than forfeited money.

This document specifies the behavior an implementation must reproduce exactly. The studio runs on a deterministic, server-held clock so that lead-time, expiry, and billing-period rules are reproducible; nothing in this system reads wall-clock time. Tuition is computed two different ways depending on whether an invoice is a forward-looking provisional estimate or a backward-looking finalized charge, and student progress is reported both as a raw practice total and as a decay-weighted score. The remainder of this document defines the global contract (Section 2), the business workflows where the bulk of the domain rules live (Section 3), the endpoint surface (Section 4), and the error catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. The API is mounted under `/studios/{studioId}` for all studio-scoped resources.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_USER_CONTEXT` (HTTP 401). When the headers are present but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The system recognizes exactly four roles: `StudioAdmin`, `Instructor`, `ParentGuardian`, and `BillingClerk`. A `StudioAdmin` runs studio operations — configuring the studio, instructors, and rooms, driving the enrollment lifecycle and occurrence scheduling, the recital lifecycle, and rental fulfillment. A `BillingClerk` owns money movement: issuing and finalizing invoices, taking payments, issuing refunds, and crediting wallets. An `Instructor` teaches lessons, marks them complete, and logs student practice. A `ParentGuardian` is the family account holder who enrolls students, manages auto-pay and the wallet, cancels or requests makeups, registers students for recitals, and rents instruments.

Two of the roles are entity-backed. When `X-User-Role` is `Instructor`, `X-User-ID` is the `id` of the acting `Instructor`; ownership checks on any resource that references an `Instructor` compare the resource's instructor foreign key to `X-User-ID`. When `X-User-Role` is `ParentGuardian`, `X-User-ID` is the `id` of the acting `Family`; ownership checks on any resource that references a `Family` compare the resource's family foreign key to `X-User-ID`. The other two roles are opaque. When `X-User-Role` is `StudioAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. Likewise, when `X-User-Role` is `BillingClerk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity and is never compared to an entity's `id`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource in the system carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp recorded as an ISO 8601 UTC value with three fractional digits. All entities in this system are mutable bookkeeping records, so each also carries an `updated_at` timestamp (ISO 8601 UTC, three fractional digits) refreshed on every change, and a `version` — an integer that starts at the resource's creation value and increments by one on every mutation. The `version` field is the basis for the optimistic concurrency control described in Section 2.7.

The deterministic studio clock is exposed on the `Studio` resource as `current_utc`. At studio creation this defaults to `2026-01-01T00:00:00.000Z`. It advances only through an administrative test-driving capability that sets it to a supplied instant; it never tracks real wall-clock time. Every lead-time comparison, expiry computation, and billing-period boundary in this specification reads `current_utc`, not the host system clock.

### 2.5. Studio Configuration Constants

A `Studio` is created with a `name` and exposes a single-value lifecycle: its `status` is `OPEN` at creation and is never closed in this version. Four tunable policy values may be supplied at creation and otherwise take documented defaults. The `makeup_credit_cap_per_enrollment` is the maximum number of `OUTSTANDING` makeup credits a single enrollment may hold concurrently, defaulting to 3. The `cancellation_notice_hours` is the minimum number of hours before a lesson's start that a cancellation must occur to earn a makeup credit, defaulting to 24. The `makeup_credit_valid_days` is the number of days after issuance that a makeup credit remains usable before it expires, defaulting to 30.

The `family_discount_tiers` value is an array of tier objects, each carrying a `min_active_enrollments` integer and a `discount_pct` fraction, ordered ascending by `min_active_enrollments`. When omitted, it defaults to four tiers: one active enrollment earns a discount fraction of 0, two active enrollments earn 0.05, three earn 0.10, and four or more earn 0.15. These tiers drive the family discount selection described in Section 3.4.

### 2.6. Nested Resource Retrieval and Referential Scope

Resource identifiers in a path are validated left to right. The studio identifier `studioId` is always checked first; if no such studio exists the request fails with `ERR_STUDIO_NOT_FOUND` (HTTP 404) before any sub-resource is consulted. Only then is the sub-resource identifier validated, yielding the not-found error specific to that resource type — `ERR_FAMILY_NOT_FOUND` for an unknown `familyId`, `ERR_STUDENT_NOT_FOUND` for `studentId`, `ERR_INSTRUCTOR_NOT_FOUND` for `instructorId`, `ERR_ROOM_NOT_FOUND` for `roomId`, `ERR_ENROLLMENT_NOT_FOUND` for `enrollmentId`, `ERR_OCCURRENCE_NOT_FOUND` for `occId`, `ERR_CREDIT_NOT_FOUND` for `creditId`, `ERR_INVOICE_NOT_FOUND` for `invoiceId`, `ERR_PAYMENT_NOT_FOUND` for `paymentId`, `ERR_EVENT_NOT_FOUND` for `eventId`, `ERR_REGISTRATION_NOT_FOUND` for `regId`, and `ERR_RENTAL_NOT_FOUND` for `rentalId` — each HTTP 404.

The system applies a strict ordering of checks to every write. Authentication (`ERR_MISSING_USER_CONTEXT`, HTTP 401) is evaluated first, then role authorization (`ERR_INSUFFICIENT_PERMISSIONS`, HTTP 403), then path-resource existence as described above (HTTP 404), then request-body well-formedness (`ERR_INVALID_REQUEST`, HTTP 422, raised when a required field is missing, a type or enum value is invalid, or a supplied window has its end at or before its start). After those, referential-scope checks run: on enrollment creation, recital-registration creation, and instrument-rental creation, any foreign key in the body must reference a sibling that belongs to this same studio — a `student_id` must belong to a `Family` in this studio, and an `instructor_id`, `room_id`, or `family_id` must belong to this studio. A body that references an entity outside this studio is rejected with `ERR_CROSS_STUDIO_REFERENCE` (HTTP 422). Only once all of the above pass does the system evaluate domain state and business rules. This priority chain is global: authentication outranks authorization, which outranks existence, which outranks request validity, which outranks referential scope, which outranks state and business checks.

### 2.7. Optimistic Concurrency Control on Enrollment

Two enrollment transitions claim a recurring instructor-and-room slot and therefore guard against acting on a stale view of the enrollment. Activating an enrollment requires the request body to carry `expected_enrollment_version`, which must equal the enrollment's current `version`. If another writer has advanced the enrollment's `version` since the client last read it — for example, a freeze-then-resume round trip, or an activate-then-cancel sequence — the activation is rejected with `ERR_STALE_VERSION` (HTTP 412) on the version check, before the recurring slot is committed. Resuming a frozen enrollment likewise requires `expected_enrollment_version` to match the enrollment's current `version`; if a cancel or a re-freeze has advanced the `version` since the client's last read, the resume is rejected with `ERR_STALE_VERSION` (HTTP 412) before the recurring slot is re-claimed. No other endpoint in the system takes a version field; all other mutations proceed without an OCC check.

### 2.8. Monetary Precision, Counts, and the Studio Clock

All monetary amounts in this system are stored and returned as integer cents. Tuition computations round half up at each pinned step described in Section 3, and intermediate amounts are never carried as floating-point dollars. A family's `wallet_balance_cents` is a conserved quantity: it equals the sum of all wallet credits, minus the sum of `amount_cents` over the family's `SUCCEEDED` payments, plus the sum of `amount_cents` over the family's `REFUNDED` payments. As a direct consequence, a successful payment followed by its refund leaves `wallet_balance_cents` exactly where it began, and the balance is never allowed to go negative. The decay-weighted progress score described in Section 3.7 rounds half up to two decimal places.

### 2.9. Cascading Consistency and Derived Counts

Several operations mutate more than one resource. When the specification says a transition recomputes a derived count or refreshes a related resource, that secondary mutation is part of the same operation: it refreshes the affected resource's `updated_at` and increments its `version` exactly as any other change would. A family's `active_enrollment_count` is always the number of that family's enrollments whose `lifecycle_status` is `ACTIVE`; `family_discount_pct` is recomputed from it whenever an enrollment moves into or out of `ACTIVE`. A recital event's `confirmed_count` and `waitlist_count` always reflect the live number of its `CONFIRMED` and `WAITLISTED` registrations. A student's `total_practice_minutes` and `weighted_progress_score` are recomputed on every practice log. None of these derived values is ever supplied by a client; the server owns them.

## 3. Business Logic & Workflows

### 3.1. Building the Studio: Families, Students, Instructors, and Rooms

Before any lesson can be scheduled, a `StudioAdmin` populates the studio's roster. A `Family` is created as a household account with a `household_name` and an optional `autopay_enabled` flag (defaulting to off); at creation its `status` is `ACTIVE`, its `wallet_balance_cents` is 0, its `active_enrollment_count` is 0, and its `family_discount_pct` is 0. A family's `studio_id` ties it to the studio. The autopay flag and the family's `status` can later be changed — a `StudioAdmin` or a `ParentGuardian` may toggle `autopay_enabled` or move `status` between `ACTIVE` and `SUSPENDED`. A `SUSPENDED` family is blocked from new enrollment activations and from auto-pay. Prepaid funds reach a family through a wallet credit carrying an `amount_cents` value, which is added to `wallet_balance_cents`; both a `StudioAdmin` and a `BillingClerk` may credit a wallet.

A `Student` belongs to a `Family` via `family_id` and is created with a `full_name` and an optional `skill_level`, one of `BEGINNER`, `INTERMEDIATE`, or `ADVANCED`, defaulting to `BEGINNER`. A new student begins with `total_practice_minutes` of 0 and `weighted_progress_score` of 0. Either a `StudioAdmin` or a `ParentGuardian` may create a student.

An `Instructor` is created by a `StudioAdmin` with a `full_name`, an `instruments` array drawn from `PIANO`, `VIOLIN`, `GUITAR`, `DRUMS`, `VOICE`, and `CELLO`, an `hourly_rate_cents` tuition rate expressed per sixty lesson-minutes, and a `weekly_availability` array. Each availability entry is a half-open window with a `weekday` (0 for Monday through 6 for Sunday), a `start_min`, and an `end_min`, both measured in minutes from midnight. An instructor's `studio_id` scopes it to the studio. An instructor's `status` is `ACTIVE` at creation and may be toggled to `INACTIVE` and back by a `StudioAdmin`; an `INACTIVE` instructor cannot be matched to new enrollments.

A `Room` is created by a `StudioAdmin` with a `room_name`, a `supported_instruments` array drawn from the same six instrument values, and an optional `turnover_buffer_min` — the mandatory clean-and-turnover gap in minutes required between two consecutive occupations of the room, defaulting to 10. A room's `studio_id` scopes it to the studio.

### 3.2. Enrollment: Matching, Activation, and the Recurring Slot

An enrollment is the recurring contract between a student and an instructor for a weekly lesson on a particular instrument in a particular room. A `StudioAdmin` or a `ParentGuardian` creates one by supplying `student_id`, `instructor_id`, `room_id`, `instrument` (one of the six instrument values), `weekday`, `start_min`, `duration_min`, and the recurring lesson is defined by the half-open weekly window that runs from `start_min` for `duration_min` minutes. At creation the enrollment's `lifecycle_status` is `PENDING_MATCH`, its `billing_status` is `UNBILLED`, its `studio_id` is set, its `family_id` is derived from the student's family, and its `monthly_tuition_cents` is computed (Section 3.3). These two status dimensions evolve independently: `lifecycle_status` tracks the matching and scheduling life of the enrollment, while `billing_status` tracks its invoicing state.

Activation is the moment the recurring slot is claimed, and it is performed only by a `StudioAdmin`. It carries `expected_enrollment_version` and is subject to a battery of preconditions evaluated together with the stale-version guard of Section 2.7. The family must be `ACTIVE`, or activation fails with `ERR_FAMILY_SUSPENDED` (HTTP 409). The instructor must be `ACTIVE` and must teach the enrollment's `instrument` (the value must appear in the instructor's `instruments`), or the result is `ERR_INSTRUCTOR_INSTRUMENT_MISMATCH` (HTTP 422). The room's `supported_instruments` must contain the `instrument`, or the result is `ERR_ROOM_INSTRUMENT_MISMATCH` (HTTP 422). The recurring weekly window must lie entirely inside one of the instructor's `weekly_availability` windows for that `weekday`, or activation fails with `ERR_OUTSIDE_AVAILABILITY` (HTTP 409). The slot must be free on the instructor: no other `ACTIVE` enrollment for the same `instructor_id` may collide on the same `weekday` with an overlapping half-open minute window, evaluated with no buffer, or the result is `ERR_INSTRUCTOR_DOUBLE_BOOKED` (HTTP 409). The slot must also be free in the room: no other `ACTIVE` enrollment for the same `room_id` may collide on the same `weekday`, where the room's collision test expands each window by the room's `turnover_buffer_min` before testing overlap — two enrollments on the same room conflict when the interval from one enrollment's start to its end plus the buffer intersects the corresponding interval of the other — or the result is `ERR_ROOM_DOUBLE_BOOKED` (HTTP 409). When all preconditions hold, the enrollment moves `PENDING_MATCH → ACTIVE`, the owning family's `active_enrollment_count` and `family_discount_pct` are recomputed, and the enrollment's `version` increments by one.

When the relative priority of these activation checks matters, they resolve in the global order established in Section 2.6 — authentication, authorization, path existence, request validity, then cross-studio referential scope — after which the activation-specific checks apply: family suspension, then the instructor-and-instrument capability match, then the room-and-instrument capability match, then availability, then instructor double-booking, then room double-booking, and finally the stale-version check that guards the commit of the slot.

Freezing an enrollment is a `StudioAdmin` action permitted only while `lifecycle_status` is `ACTIVE`, else `ERR_INVALID_STATE` (HTTP 409). A freeze moves the enrollment `ACTIVE → FROZEN` and triggers a three-hop cascade: first, every one of this enrollment's `SCHEDULED` lesson occurrences whose `scheduled_start_utc` is at or after the studio clock is moved to `CANCELLED_NOTICE`; second, each such cancelled occurrence mints one `OUTSTANDING` makeup credit for the enrollment, but only while the enrollment's outstanding-credit count remains below `makeup_credit_cap_per_enrollment`; third, because a `FROZEN` enrollment no longer counts as active, the family's `active_enrollment_count` and `family_discount_pct` are recomputed. The enrollment's `version` increments by one.

Resuming is the inverse `StudioAdmin` action, permitted only while `lifecycle_status` is `FROZEN`, else `ERR_INVALID_STATE`. A resume re-validates the recurring slot against current `ACTIVE` instructor and room bookings exactly as activation does — a conflict yields `ERR_INSTRUCTOR_DOUBLE_BOOKED` or `ERR_ROOM_DOUBLE_BOOKED` — and it carries `expected_enrollment_version` subject to the stale-version guard. On success the enrollment moves `FROZEN → ACTIVE`, the family's `active_enrollment_count` and `family_discount_pct` are recomputed, and `version` increments by one.

Cancelling an enrollment is a `StudioAdmin` action permitted from `PENDING_MATCH`, `ACTIVE`, or `FROZEN` — any state other than `CANCELLED`, else `ERR_INVALID_STATE`. Cancellation moves `lifecycle_status → CANCELLED` (a terminal state) and cascades: all future `SCHEDULED` lesson occurrences for the enrollment move to `CANCELLED_NOTICE` but mint no makeup credits (unlike a freeze, an enrollment cancellation forfeits the makeup opportunity), every `OUTSTANDING` makeup credit for the enrollment moves to `VOIDED`, and the family's `active_enrollment_count` and `family_discount_pct` are recomputed. The `version` increments by one.

### 3.3. Tuition: Base Rate, Provisional Estimate, and Finalized Charge

Each enrollment's base monthly tuition before any family discount, stored as `monthly_tuition_cents`, is computed at enrollment creation as the instructor's `hourly_rate_cents` multiplied by `duration_min`, divided by 60 to convert to the lesson's fraction of an hour, then multiplied by the number of sessions in a month, which is fixed at four, with the result rounded half up to whole cents.

Tuition is invoiced through a `TuitionInvoice`. A `BillingClerk` or `StudioAdmin` issues one by supplying `enrollment_id` and `billing_period`, where the period is a calendar month written as `YYYY-MM`. At issue the invoice's `status` is `ISSUED`, its `family_id` is derived from the enrollment, and the enrollment's `billing_status` moves `UNBILLED → BILLED` (this systemic billing transition requires the enrollment's `lifecycle_status` to be `ACTIVE` or `FROZEN`). Issuing computes the forward-looking `provisional_amount_cents`. The provisional figure is a prorated estimate: the system first counts the enrollment's `SCHEDULED` lesson occurrences whose `scheduled_start_utc` falls within the billing period and is at or after the current studio clock, calling that count the remaining sessions. The prorated base is `monthly_tuition_cents` multiplied by the remaining sessions, divided by four sessions per month, rounded half up to whole cents. The provisional amount is then that prorated base multiplied by one minus the family's `family_discount_pct` read at issue time, rounded half up to whole cents. The ordering of operations is pinned: prorate and round first, then apply the discount and round again. While the invoice remains `ISSUED`, its `amount_due_cents` equals `provisional_amount_cents`, and both `finalized_amount_cents` and `rental_surcharge_cents` are 0.

Finalization is a `BillingClerk` action that moves an invoice `ISSUED → FINALIZED`. It is permitted only when the billing period has fully elapsed — that is, when the studio clock is at or after the first instant of the month after `billing_period` — otherwise it fails with `ERR_PERIOD_NOT_ENDED` (HTTP 409); and only from the `ISSUED` state, else `ERR_INVALID_STATE`. Finalization recomputes the charge from what actually happened, using a different rounding discipline than the provisional path. First, the per-session rate is `monthly_tuition_cents` divided by four sessions per month, rounded half up to whole cents. Next, the billable count is the number of the enrollment's lesson occurrences in the billing period whose `status` is either `COMPLETED` or `CANCELLED_LATE` — late cancellations are still billed, while `CANCELLED_NOTICE` and `MAKEUP_PENDING` occurrences are excluded. The gross is the per-session rate multiplied by the billable count, where the per-session rounding happens before this multiplication and summation. The `finalized_amount_cents` is the gross multiplied by one minus the family's `family_discount_pct`, rounded half up to whole cents. Because the provisional path prorates the whole month and rounds once while the finalized path rounds each session before summing, the two figures can legitimately differ by a few cents for the same enrollment.

At finalization the system also computes `rental_surcharge_cents` as the sum of `period_fee_cents` over the active instrument rentals attributed to this invoice's family and period (Section 3.8), and then sets `amount_due_cents` to `finalized_amount_cents` plus `rental_surcharge_cents`. Once finalized, if the family has `autopay_enabled` and its `status` is `ACTIVE`, the system synthesizes an `AUTOPAY` payment in a cascade: on success the payment's `status` is `SUCCEEDED`, the invoice moves to `PAID`, and the family's `wallet_balance_cents` is debited; on insufficient funds the payment's `status` is `FAILED` and the enrollment's `billing_status` moves to `PAST_DUE`. An `ISSUED` invoice that should not be charged at all can instead be voided by a `BillingClerk`, moving it `ISSUED → VOID`; void is permitted only from `ISSUED`, else `ERR_INVALID_STATE`. Both `PAID` and `VOID` are terminal.

The enrollment's `billing_status` dimension tracks this money flow independently of its lifecycle. From `BILLED` it moves to `PAST_DUE` when an associated invoice is `FINALIZED` and not yet paid, and a later successful payment that clears the enrollment's outstanding finalized invoice moves it back `PAST_DUE → BILLED`.

### 3.4. The Family Discount

A family earns a tuition discount that grows with how many lessons it actively runs. The discount fraction `family_discount_pct` is selected from the studio's `family_discount_tiers` keyed on the family's `active_enrollment_count`, which counts only enrollments whose `lifecycle_status` is `ACTIVE` — enrollments that are `FROZEN`, `PENDING_MATCH`, or `CANCELLED` do not count. To select the fraction, the system considers every tier whose `min_active_enrollments` is less than or equal to the current active count and chooses the one with the greatest `min_active_enrollments` among them; if no tier qualifies, the discount fraction is 0. Under the default tiers, a family with no active enrollments or one active enrollment gets a fraction of 0, two active enrollments get 0.05, three get 0.10, and four or more get 0.15. The fraction is recomputed on any enrollment transition into or out of `ACTIVE`, which is why activation, freeze, resume, and cancellation each list a discount recomputation among their effects. A change to the discount affects only invoices issued after the change; invoices already issued keep the rate they captured at issue time.

### 3.5. Lesson Occurrences: Scheduling, Completion, Cancellation, and Makeups

A `LessonOccurrence` is a single dated instance of a recurring lesson. A `StudioAdmin` creates one for an `ACTIVE` enrollment by supplying `enrollment_id` and `scheduled_start_utc`; the system sets `scheduled_end_utc` to `scheduled_start_utc` plus the enrollment's `duration_min` (a half-open interval), copies the enrollment's `room_id` and `instructor_id` onto the occurrence, sets `is_makeup` to false and leaves `consumed_credit_id` unset, and starts the occurrence in `SCHEDULED`. Creating a dated occurrence enforces a non-overlap check on both the instructor and the room: a new occurrence collides with another non-cancelled occurrence on the same instructor or room when their half-open UTC windows overlap, evaluated with no buffer so that instantaneous adjacency (one ending exactly when the next begins) is allowed.

Completing an occurrence is performed by an `Instructor` or `StudioAdmin` and moves it `SCHEDULED → COMPLETED` (terminal). It requires the occurrence to be `SCHEDULED`, else `ERR_INVALID_STATE`; the studio clock to be at or after `scheduled_start_utc`, else `ERR_LESSON_NOT_STARTED` (HTTP 409); and the parent enrollment's `lifecycle_status` to be `ACTIVE`, else `ERR_ENROLLMENT_NOT_ACTIVE` (HTTP 409). A completed occurrence counts toward the finalized tuition of Section 3.3.

Cancelling an occurrence — a `StudioAdmin` or `ParentGuardian` action — branches on lead time relative to the studio clock and the studio's `cancellation_notice_hours`. When the gap from the studio clock to `scheduled_start_utc` is at least `cancellation_notice_hours`, the cancellation is timely: the occurrence moves `SCHEDULED → CANCELLED_NOTICE` and the system mints one `OUTSTANDING` makeup credit for the enrollment — provided the enrollment's outstanding-credit count is below `makeup_credit_cap_per_enrollment`; if the cap is already reached, the cancellation is rejected with `ERR_MAKEUP_CAP_EXCEEDED` (HTTP 409). When the gap is less than `cancellation_notice_hours`, the cancellation is late: the occurrence moves `SCHEDULED → CANCELLED_LATE` (terminal) and no makeup credit is minted — a late cancellation forfeits. Either branch requires the occurrence to start in `SCHEDULED`, else `ERR_INVALID_STATE`.

Requesting a makeup is a distinct `StudioAdmin` or `ParentGuardian` action that proactively converts an upcoming lesson into a pending makeup. It requires the occurrence to be `SCHEDULED`, else `ERR_INVALID_STATE`; the occurrence's `is_makeup` to be false, since a makeup occurrence cannot itself spawn another makeup, else `ERR_MAKEUP_NOT_ALLOWED` (HTTP 409); the gap from the studio clock to `scheduled_start_utc` to be at least `cancellation_notice_hours`, else `ERR_LATE_CANCELLATION` (HTTP 409); and the enrollment's outstanding-credit count to be below `makeup_credit_cap_per_enrollment`, else `ERR_MAKEUP_CAP_EXCEEDED`. On success the occurrence moves `SCHEDULED → MAKEUP_PENDING` and one `OUTSTANDING` makeup credit is minted for the enrollment with its `origin_occurrence_id` set to this occurrence.

### 3.6. Makeup Credits and Scheduling the Makeup Lesson

A `MakeupCredit` carries the `enrollment_id` it belongs to, the `origin_occurrence_id` of the cancelled or makeup-pending occurrence that minted it, an `issued_utc` set from the studio clock at issuance, and an `expires_utc` equal to `issued_utc` plus the studio's `makeup_credit_valid_days`. Its `status` is `OUTSTANDING` at issuance and may become `CONSUMED`, `EXPIRED`, or `VOIDED`, all terminal. A credit whose `expires_utc` is in the past relative to the studio clock is treated as `EXPIRED` on its next read or use. The enrollment's outstanding-credit count — the gate behind the makeup cap — is the number of its credits that are `OUTSTANDING` and still within their validity window; minting a credit then consuming or voiding it returns the count to its prior value.

Scheduling a makeup lesson consumes a credit. A `StudioAdmin` or `ParentGuardian` supplies `credit_id`, a `scheduled_start_utc`, and an optional `room_id`. The credit must be `OUTSTANDING` and the studio clock must be at or before its `expires_utc`, else `ERR_CREDIT_NOT_USABLE` (HTTP 409). The dated window of the new makeup occurrence must not overlap an existing occurrence on the same instructor or room — using the same half-open, no-buffer overlap test as ordinary occurrence creation — or the request fails with `ERR_MAKEUP_SLOT_CONFLICT` (HTTP 409). On success the system creates a new `LessonOccurrence` with `is_makeup` set to true and `consumed_credit_id` pointing at the credit, moves the credit `OUTSTANDING → CONSUMED`, and restores the origin occurrence from `MAKEUP_PENDING → SCHEDULED` (the original is retained for audit and is not separately completed). If a `room_id` is supplied it sets the makeup occurrence's room; otherwise the enrollment's room is used.

### 3.7. Student Practice and Progress

An `Instructor` or `ParentGuardian` appends a practice log to a student by supplying `minutes`, an optional `logged_utc` timestamp, and an optional free-text `note`. Each log recomputes the student's two progress fields. The `total_practice_minutes` is the raw, undecayed sum of `minutes` over all of the student's practice logs.

The `weighted_progress_score` applies a daily decay so that recent practice counts for more than old practice. The system replays the student's logs in chronological order by `logged_utc` ascending, then by `created_at` ascending. For each log, the age in whole days is the difference between the studio clock and the log's `logged_utc` measured in milliseconds and divided by the number of milliseconds in a day (86,400,000), taking the floor. That log contributes its `minutes` multiplied by the decay base of 0.95 raised to the power of the age in days. The weighted score is the sum of those contributions across all logs, divided by 60 to convert minutes to hours, rounded half up to two decimal places. The two figures share the same inputs but differ in meaning: `total_practice_minutes` never decays, while `weighted_progress_score` discounts older practice at five percent per day.

### 3.8. Instrument Rentals

A family may rent a physical instrument unit for a window of time. A `StudioAdmin` or `ParentGuardian` reserves a rental by supplying `family_id`, an `instrument_unit_code` identifying the physical unit, a `period_fee_cents` flat fee for the window, a `rental_start_utc`, and a `rental_end_utc`. The rental's `studio_id` scopes it to the studio. A physical unit is a finite resource that only one rental may occupy at a time, and the occupation is treated as a closed interval: a new rental is rejected with `ERR_INSTRUMENT_UNIT_UNAVAILABLE` (HTTP 409) when any `RESERVED` or `ACTIVE` rental on the same `instrument_unit_code` overlaps it, where overlap holds when the new rental's `rental_start_utc` is at or before the existing rental's `rental_end_utc` and the new rental's `rental_end_utc` is at or after the existing rental's `rental_start_utc`. Because endpoints are inclusive, a return at one instant blocks a new pickup at the very same instant. A new rental's `status` is `RESERVED`.

A `StudioAdmin` activates a reserved rental (the pickup), moving it `RESERVED → ACTIVE`; activation requires the rental to be `RESERVED`, else `ERR_INVALID_STATE`, and the studio clock to be at or after `rental_start_utc`, else `ERR_RENTAL_NOT_STARTED` (HTTP 409). Returning a rental is a `StudioAdmin` action permitted from `RESERVED` or `ACTIVE`, moving it to `RETURNED` and freeing the unit for future windows; from any other state it fails with `ERR_INVALID_STATE`. A `RESERVED` rental can be cancelled by a `StudioAdmin` or `ParentGuardian`, moving it `RESERVED → CANCELLED` with no surcharge attributed to any invoice; cancellation is permitted only from `RESERVED`, else `ERR_INVALID_STATE`. Both `RETURNED` and `CANCELLED` are terminal. As described in Section 3.3, when an invoice is finalized the `period_fee_cents` of the active rentals attributed to that family and period is summed into the invoice's `rental_surcharge_cents`.

### 3.9. Recitals: Events, Registration, and the Waitlist

A `StudioAdmin` creates a `RecitalEvent` with a `title`, a `venue_capacity` capping confirmed performer registrations, an `event_start_utc`, and a `registration_deadline_utc` that must be strictly before `event_start_utc`. The event's `studio_id` scopes it to the studio, its `status` starts at `REG_OPEN`, and both `confirmed_count` and `waitlist_count` begin at 0.

A student is registered for a recital by a `StudioAdmin` or `ParentGuardian` supplying `recital_event_id` and `student_id`. Registration is accepted only while the event is `REG_OPEN` and the studio clock is before `registration_deadline_utc`, else `ERR_REGISTRATION_CLOSED` (HTTP 409). A student may hold at most one non-`WITHDRAWN` `RecitalRegistration` per event; a second attempt is rejected with `ERR_DUPLICATE_REGISTRATION` (HTTP 409). A new `RecitalRegistration` records its `registered_utc` from the studio clock and is created `CONFIRMED` when the event's `confirmed_count` is below `venue_capacity`, otherwise `WAITLISTED`. Each registration carries a `performance_order`, a one-based slot among the `CONFIRMED` registrations for the event, ordered by `registered_utc` ascending and then `created_at` ascending; the event's `confirmed_count` and `waitlist_count` are recomputed on every registration change.

Closing registration is a `StudioAdmin` action that moves an event `REG_OPEN → REG_CLOSED`, accepts no further registrations, and recomputes `performance_order` for all `CONFIRMED` registrations in the `registered_utc`-then-`created_at` order. Completing an event moves it `REG_CLOSED → COMPLETED` and requires the studio clock to be at or after `event_start_utc`, else `ERR_EVENT_NOT_STARTED` (HTTP 409); it must start from `REG_CLOSED`, else `ERR_INVALID_STATE`. Cancelling an event is permitted from either `REG_OPEN` or `REG_CLOSED`, else `ERR_INVALID_STATE`; it moves the event to `CANCELLED` (the branch that diverges from `COMPLETED`) and cascades every `CONFIRMED` and `WAITLISTED` registration to `WITHDRAWN`. All of `COMPLETED` and `CANCELLED` are terminal event states.

Withdrawing a registration is a `StudioAdmin` or `ParentGuardian` action permitted from `CONFIRMED` or `WAITLISTED`, else `ERR_INVALID_STATE`. It moves the registration to `WITHDRAWN` (terminal) and recomputes the event's `confirmed_count` and `waitlist_count`. When the withdrawal frees a `CONFIRMED` seat and a `WAITLISTED` registration exists, the system promotes the earliest-waiting registration — the one earliest by `registered_utc` ascending, then `created_at` ascending — from `WAITLISTED → CONFIRMED`, provided the event's `confirmed_count` is below `venue_capacity` after the withdrawal. Promotion recomputes `confirmed_count`, `waitlist_count`, and the `performance_order` of the `CONFIRMED` registrations.

### 3.10. Payments, Refunds, and Auto-Pay

A payment settles a finalized invoice against a family's wallet. A `BillingClerk` or `ParentGuardian` creates one by supplying `invoice_id` and an optional `method`, which is `WALLET` or `AUTOPAY` and defaults to `WALLET`. The system copies the invoice's `family_id` onto the payment and sets the payment's `amount_cents` to the invoice's `amount_due_cents` at the moment of the attempt. A payment succeeds only when the family's `wallet_balance_cents` is at least `amount_due_cents`; otherwise the payment's `status` is `FAILED`, its `failure_reason` is set to `INSUFFICIENT_FUNDS`, the operation reports `ERR_INSUFFICIENT_FUNDS` (HTTP 402), and the enrollment's `billing_status` moves to `PAST_DUE`. On a successful payment the `status` is `SUCCEEDED`, the family's `wallet_balance_cents` is debited by `amount_cents`, the invoice moves to `PAID`, and any `PAST_DUE` enrollment for that invoice returns to `BILLED`. A new payment's `failure_reason` is `NONE` unless a failure sets it. The same auto-pay path runs automatically at invoice finalization when the family has `autopay_enabled` and is `ACTIVE`, as described in Section 3.3, and a synthesized `AUTOPAY` payment that cannot be funded leaves the enrollment `PAST_DUE`.

A `BillingClerk` may refund a `SUCCEEDED` payment, moving it `SUCCEEDED → REFUNDED` (terminal). A refund is permitted only from `SUCCEEDED`, else `ERR_INVALID_STATE`. The refund adds the payment's `amount_cents` back to the family's `wallet_balance_cents`, returning the wallet to its pre-payment value, and re-opens the associated invoice from `PAID → FINALIZED` so it is unpaid again.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return a `201 Created` status code; operations that modify an existing resource — including all state transitions and the wallet-credit and clock-set actions — return a `200 OK` status code. The complete request and response shape of each endpoint must be reconstructed from the workflow narratives in Section 3; the table below lists only the method, path, purpose, and authorized roles.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/studios` | Create a studio | StudioAdmin |
| GET | `/studios` | List studios | StudioAdmin, Instructor, ParentGuardian, BillingClerk |
| GET | `/studios/{studioId}` | Get a studio | StudioAdmin, Instructor, ParentGuardian, BillingClerk |
| POST | `/studios/{studioId}/_clock/set_current_utc` | Set the deterministic studio clock | StudioAdmin |
| POST | `/studios/{studioId}/families` | Create a family | StudioAdmin |
| GET | `/studios/{studioId}/families` | List families | StudioAdmin, BillingClerk |
| GET | `/studios/{studioId}/families/{familyId}` | Get a family | StudioAdmin, BillingClerk, ParentGuardian |
| PATCH | `/studios/{studioId}/families/{familyId}` | Update family autopay / suspend-reactivate | StudioAdmin, ParentGuardian |
| POST | `/studios/{studioId}/families/{familyId}/wallet/credits` | Credit prepaid funds to a family wallet | StudioAdmin, BillingClerk |
| POST | `/studios/{studioId}/students` | Create a student | StudioAdmin, ParentGuardian |
| GET | `/studios/{studioId}/students` | List students | StudioAdmin, Instructor, ParentGuardian |
| GET | `/studios/{studioId}/students/{studentId}` | Get a student | StudioAdmin, Instructor, ParentGuardian |
| POST | `/studios/{studioId}/students/{studentId}/practice-logs` | Append a practice log | Instructor, ParentGuardian |
| POST | `/studios/{studioId}/instructors` | Create an instructor | StudioAdmin |
| GET | `/studios/{studioId}/instructors` | List instructors | StudioAdmin, Instructor, ParentGuardian |
| GET | `/studios/{studioId}/instructors/{instructorId}` | Get an instructor | StudioAdmin, Instructor, ParentGuardian |
| PATCH | `/studios/{studioId}/instructors/{instructorId}` | Update instructor status | StudioAdmin |
| POST | `/studios/{studioId}/rooms` | Create a room | StudioAdmin |
| GET | `/studios/{studioId}/rooms` | List rooms | StudioAdmin, Instructor, ParentGuardian |
| GET | `/studios/{studioId}/rooms/{roomId}` | Get a room | StudioAdmin, Instructor, ParentGuardian |
| POST | `/studios/{studioId}/enrollments` | Create an enrollment | StudioAdmin, ParentGuardian |
| GET | `/studios/{studioId}/enrollments` | List enrollments | StudioAdmin, Instructor, ParentGuardian, BillingClerk |
| GET | `/studios/{studioId}/enrollments/{enrollmentId}` | Get an enrollment | StudioAdmin, Instructor, ParentGuardian, BillingClerk |
| POST | `/studios/{studioId}/enrollments/{enrollmentId}/activate` | Activate an enrollment | StudioAdmin |
| POST | `/studios/{studioId}/enrollments/{enrollmentId}/freeze` | Freeze an enrollment | StudioAdmin |
| POST | `/studios/{studioId}/enrollments/{enrollmentId}/resume` | Resume a frozen enrollment | StudioAdmin |
| POST | `/studios/{studioId}/enrollments/{enrollmentId}/cancel` | Cancel an enrollment | StudioAdmin |
| POST | `/studios/{studioId}/lesson-occurrences` | Create a scheduled occurrence | StudioAdmin |
| GET | `/studios/{studioId}/lesson-occurrences` | List occurrences | StudioAdmin, Instructor, ParentGuardian |
| GET | `/studios/{studioId}/lesson-occurrences/{occId}` | Get an occurrence | StudioAdmin, Instructor, ParentGuardian |
| POST | `/studios/{studioId}/lesson-occurrences/{occId}/complete` | Complete an occurrence | Instructor, StudioAdmin |
| POST | `/studios/{studioId}/lesson-occurrences/{occId}/cancel` | Cancel an occurrence | StudioAdmin, ParentGuardian |
| POST | `/studios/{studioId}/lesson-occurrences/{occId}/request-makeup` | Request a makeup for an occurrence | StudioAdmin, ParentGuardian |
| POST | `/studios/{studioId}/make-up-occurrences` | Schedule a makeup by consuming a credit | StudioAdmin, ParentGuardian |
| GET | `/studios/{studioId}/makeup-credits` | List makeup credits | StudioAdmin, ParentGuardian |
| GET | `/studios/{studioId}/makeup-credits/{creditId}` | Get a makeup credit | StudioAdmin, ParentGuardian |
| POST | `/studios/{studioId}/invoices` | Issue a provisional tuition invoice | BillingClerk, StudioAdmin |
| GET | `/studios/{studioId}/invoices` | List invoices | BillingClerk, StudioAdmin, ParentGuardian |
| GET | `/studios/{studioId}/invoices/{invoiceId}` | Get an invoice | BillingClerk, StudioAdmin, ParentGuardian |
| POST | `/studios/{studioId}/invoices/{invoiceId}/finalize` | Finalize an invoice | BillingClerk |
| POST | `/studios/{studioId}/invoices/{invoiceId}/void` | Void an issued invoice | BillingClerk |
| POST | `/studios/{studioId}/payments` | Create a payment against an invoice | BillingClerk, ParentGuardian |
| GET | `/studios/{studioId}/payments` | List payments | BillingClerk, StudioAdmin, ParentGuardian |
| GET | `/studios/{studioId}/payments/{paymentId}` | Get a payment | BillingClerk, StudioAdmin, ParentGuardian |
| POST | `/studios/{studioId}/payments/{paymentId}/refund` | Refund a succeeded payment | BillingClerk |
| POST | `/studios/{studioId}/recital-events` | Create a recital event | StudioAdmin |
| GET | `/studios/{studioId}/recital-events` | List recital events | StudioAdmin, Instructor, ParentGuardian |
| GET | `/studios/{studioId}/recital-events/{eventId}` | Get a recital event | StudioAdmin, Instructor, ParentGuardian |
| POST | `/studios/{studioId}/recital-events/{eventId}/close-registration` | Close registration | StudioAdmin |
| POST | `/studios/{studioId}/recital-events/{eventId}/complete` | Complete a recital event | StudioAdmin |
| POST | `/studios/{studioId}/recital-events/{eventId}/cancel` | Cancel a recital event | StudioAdmin |
| POST | `/studios/{studioId}/recital-registrations` | Register a student for a recital | StudioAdmin, ParentGuardian |
| GET | `/studios/{studioId}/recital-registrations` | List registrations | StudioAdmin, ParentGuardian |
| GET | `/studios/{studioId}/recital-registrations/{regId}` | Get a registration | StudioAdmin, ParentGuardian |
| POST | `/studios/{studioId}/recital-registrations/{regId}/withdraw` | Withdraw a registration | StudioAdmin, ParentGuardian |
| POST | `/studios/{studioId}/instrument-rentals` | Reserve an instrument rental | StudioAdmin, ParentGuardian |
| GET | `/studios/{studioId}/instrument-rentals` | List rentals | StudioAdmin, ParentGuardian, BillingClerk |
| GET | `/studios/{studioId}/instrument-rentals/{rentalId}` | Get a rental | StudioAdmin, ParentGuardian, BillingClerk |
| POST | `/studios/{studioId}/instrument-rentals/{rentalId}/activate` | Activate a reserved rental | StudioAdmin |
| POST | `/studios/{studioId}/instrument-rentals/{rentalId}/return` | Return a rental | StudioAdmin |
| POST | `/studios/{studioId}/instrument-rentals/{rentalId}/cancel` | Cancel a reserved rental | StudioAdmin, ParentGuardian |

The list endpoints accept the standard `limit` and `offset` query parameters from Section 2.3 and the following filters: families and instructors and rooms and recital-events and instrument-rentals by `studio_id`; students by `family_id`; enrollments by `family_id`, `student_id`, `instructor_id`, and `room_id`; lesson-occurrences by `enrollment_id`, `room_id`, `instructor_id`, and `consumed_credit_id`; makeup-credits by `enrollment_id` and `origin_occurrence_id`; invoices by `family_id` and `enrollment_id`; payments by `invoice_id` and `family_id`; recital-registrations by `recital_event_id` and `student_id`; and instrument-rentals additionally by `family_id` and `instrument_unit_code`. The clock-set capability takes a single `to_iso8601` body field carrying the instant the studio clock is moved to.

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_USER_CONTEXT` | 401 |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 |
| `ERR_STUDIO_NOT_FOUND` | 404 |
| `ERR_FAMILY_NOT_FOUND` | 404 |
| `ERR_STUDENT_NOT_FOUND` | 404 |
| `ERR_INSTRUCTOR_NOT_FOUND` | 404 |
| `ERR_ROOM_NOT_FOUND` | 404 |
| `ERR_ENROLLMENT_NOT_FOUND` | 404 |
| `ERR_OCCURRENCE_NOT_FOUND` | 404 |
| `ERR_CREDIT_NOT_FOUND` | 404 |
| `ERR_INVOICE_NOT_FOUND` | 404 |
| `ERR_PAYMENT_NOT_FOUND` | 404 |
| `ERR_EVENT_NOT_FOUND` | 404 |
| `ERR_REGISTRATION_NOT_FOUND` | 404 |
| `ERR_RENTAL_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_CROSS_STUDIO_REFERENCE` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ENROLLMENT_NOT_ACTIVE` | 409 |
| `ERR_FAMILY_SUSPENDED` | 409 |
| `ERR_PERIOD_NOT_ENDED` | 409 |
| `ERR_INSTRUCTOR_INSTRUMENT_MISMATCH` | 422 |
| `ERR_ROOM_INSTRUMENT_MISMATCH` | 422 |
| `ERR_OUTSIDE_AVAILABILITY` | 409 |
| `ERR_INSTRUCTOR_DOUBLE_BOOKED` | 409 |
| `ERR_ROOM_DOUBLE_BOOKED` | 409 |
| `ERR_INSTRUMENT_UNIT_UNAVAILABLE` | 409 |
| `ERR_MAKEUP_SLOT_CONFLICT` | 409 |
| `ERR_LATE_CANCELLATION` | 409 |
| `ERR_MAKEUP_CAP_EXCEEDED` | 409 |
| `ERR_MAKEUP_NOT_ALLOWED` | 409 |
| `ERR_CREDIT_NOT_USABLE` | 409 |
| `ERR_LESSON_NOT_STARTED` | 409 |
| `ERR_REGISTRATION_CLOSED` | 409 |
| `ERR_DUPLICATE_REGISTRATION` | 409 |
| `ERR_EVENT_NOT_STARTED` | 409 |
| `ERR_RENTAL_NOT_STARTED` | 409 |
| `ERR_INSUFFICIENT_FUNDS` | 402 |
| `ERR_STALE_VERSION` | 412 |
