# Brow & Lash Studio API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Brow & Lash Studio platform, a back-office and booking system modeled on a membership-driven lash and brow salon. A studio sells a small catalogue of chair-time services — a full lash set, a fill, a brow lift, a tint — and runs a recurring-revenue membership program on top of them. Members pre-pay a monthly fee in exchange for a credit allotment that they spend on services, with unused credits rolling forward under a capped ceiling. The platform must reconcile that credit economy with the physical realities of a salon floor: a finite number of lash technicians, each tied to a sanitized station, each able to occupy only one chair at a time.

The hard problems this API solves sit at the intersection of money, time, and safety. Lash fills are only meaningful within a biological window after a full set, so the system enforces fill-timing rules anchored to a member's service history. Stations must be sanitized on a rolling schedule before they can host an appointment. Deposits, no-show strikes, and late-cancellation penalties protect the studio against lost chair time, and a member who accumulates too many no-shows within a rolling window has their membership automatically suspended. Because the system is driven by a logical clock rather than wall-clock time, every temporal rule — fill windows, sanitation validity, cancellation cutoffs, patch-test expiry, and strike aging — is evaluated deterministically against that clock.

The platform is consumed by studio operators (managers and front-desk staff), by the technicians who perform the work, and by members who book and manage their own visits. The remainder of this document defines the global contract every endpoint shares, the cross-cutting principles that govern consistency and money, and the detailed business workflows that an implementer must reproduce exactly.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the capacity in which they act. If either header is absent, or if `X-User-Role` is not one of the recognized role names, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 401). When the headers are well-formed but the role is not permitted to perform the requested operation — or an entity-backed role attempts to act on a resource it does not own — the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes exactly four roles: `StudioManager`, `FrontDesk`, `LashTech`, and `Member`.

`StudioManager` and `FrontDesk` are operator roles whose identity is opaque. When `X-User-Role` is `StudioManager`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. When `X-User-Role` is `FrontDesk`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the server may record it — for example, as the `performed_by_user_id` of a `SanitationLog` the operator logs — but does not compare it to any entity's `id`.

The remaining two roles are entity-backed. When `X-User-Role` is `LashTech`, `X-User-ID` is the `id` of the acting `LashTech`; ownership checks on any resource that references a `LashTech` compare the resource's lash-technician foreign key to `X-User-ID`. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`; ownership checks on any resource that references a `Member` compare the resource's `member_id` foreign key to `X-User-ID`. In particular, a `Member` may only book an appointment for themselves — the `member_id` in the booking payload must equal `X-User-ID` — and may only read or act on their own memberships, appointments, patch tests, retail orders, and recurring schedules.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of leading items to skip and defaults to 0.

Unless a specific workflow states otherwise, every list endpoint returns its resources sorted by their creation timestamp (`created_at`) in ascending order. The append-only credit ledger is read in this same ascending creation order so that its entries replay in the sequence they were written.

List responses carry the pagination bookkeeping inside the envelope's `meta` object: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

Every time-dependent rule in this system — fill-timing windows, sanitation validity, late-cancellation cutoffs, the no-show strike window, and patch-test expiry — is evaluated against a server-maintained **logical clock**, never against wall-clock time. On server startup the clock reads exactly `2026-01-01T00:00:00Z`, and before any clock-setting call is made it holds this default and never falls back to the host's real time. An administrative test-driving capability lets a `StudioManager` move the clock to an arbitrary UTC instant supplied as `to_iso8601`; the clock may be advanced or rewound, and the response reports the new `current_utc`. All "current clock" comparisons throughout this document refer to this value.

### 2.5. Common Resource Properties and Mutation Semantics

Every primary resource carries a server-minted `id` formatted as a bare UUID with no type prefix; it is identity only and is never supplied by the client. Resources also carry a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits, recorded once at creation.

Most resources additionally carry an `updated_at` timestamp (same ISO 8601 UTC format) and an integer `version`. The `updated_at` field is refreshed on every mutation, and `version` is an integer that increments by one on every mutation; it begins at its initial value on creation and supports optimistic concurrency control where the system requires it. These two fields are present on `Studio`, `ServiceType`, `MembershipPlan`, `LashTech`, `Member`, `Membership`, `ConsentPatchTest`, `Appointment`, `RetailOrder`, `RecurringFillSchedule`, and `SanitationLog`.

The single exception is the `CreditLedgerEntry`. Ledger entries are append-only and immutable once written; a `CreditLedgerEntry` therefore carries only `id` and `created_at`, and has neither an `updated_at` field nor a `version` field. Recomputation of a derived field on a parent — for example, refreshing a `Membership`'s `credit_balance` from its ledger, or refreshing a `Member`'s `noshow_strike_count` — is itself a mutation of that parent and refreshes its `updated_at` and increments its `version` whenever it is driven by a write operation.

### 2.6. Money and Credit Precision

All monetary amounts in this system are integer cent values; fields such as `base_price_cents`, `monthly_fee_cents`, `deposit_cents`, `deposit_forfeited_cents`, `subtotal_cents`, `peak_surcharge_cents`, `total_cents`, and the per-line `unit_price_cents` are whole numbers of cents. Whenever a monetary computation produces a fractional cent — deposit derivation, late-cancel forfeiture, loyalty-discounted line totals, and the peak surcharge — the result is rounded to the nearest cent using the **round half up** convention (a value exactly halfway between two cents rounds upward).

Membership credits are integer quantities and are never rounded; the credit balance, the monthly allotment, per-service credit costs, and every ledger `delta` are whole credits. A membership's `credit_balance` is never permitted to go negative.

### 2.7. Hierarchical Consistency and Cascades

The system maintains consistency across related resources rather than leaving dependent state stale. When a membership is cancelled, any recurring fill schedule belonging to that member that is currently `ACTIVE` is automatically transitioned to `ENDED` as a cascade. When a member's no-show strike count reaches the studio's configured suspension threshold, the suspension is not limited to the membership record: every one of that member's appointments that is still `BOOKED` with a start instant in the future is auto-cancelled to `CANCELLED`, and for each such appointment that was credit-paid the credits are returned while each cash-deposit appointment forfeits nothing, because it is the suspension and not the member that cancels them. Each of these propagated changes independently mutates its target resource, refreshing `updated_at` and incrementing `version`.

Several fields are derived rather than stored directly and are reconciled by the system: a `LashTech`'s `station_sanitized_through_utc`, a `Member`'s `noshow_strike_count` and `last_premium_completed_utc`, a `Membership`'s `credit_balance` and `cycles_closed`, an `Appointment`'s `end_utc`, `deposit_cents`, `credits_charged`, and `deposit_forfeited_cents`, a `RecurringFillSchedule`'s `next_due_utc` and `spawned_count`, a `ConsentPatchTest`'s `valid_through_utc`, and a `SanitationLog`'s `valid_through_utc`. These are computed and refreshed by the workflows described in §3, not set by clients.

### 2.8. Resource Existence and Reference Resolution

The platform follows a flat URL topology: every entity is reached through its own top-level collection, and parent-child links travel in request bodies as foreign-key fields rather than as nested URL segments. For any endpoint that names a resource by its identifier in the path, that identifier is validated first; a path that names a non-existent resource is rejected with the matching not-found error — `ERR_STUDIO_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_MEMBERSHIP_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_TECH_NOT_FOUND`, `ERR_SCHEDULE_NOT_FOUND`, `ERR_PATCH_TEST_NOT_FOUND`, or `ERR_SERVICE_TYPE_NOT_FOUND` — before any other check runs. When a request names multiple path identifiers, they are validated left to right and the first missing one determines the error.

Foreign keys carried in a request body are validated next: every referenced row must exist and must belong to the same studio as the operation. A missing `member_id`, `service_type_id`, `membership_id`, or `appointment_id` in a create payload yields the corresponding not-found error (`ERR_MEMBER_NOT_FOUND`, `ERR_SERVICE_TYPE_NOT_FOUND`, `ERR_MEMBERSHIP_NOT_FOUND`, or `ERR_APPOINTMENT_NOT_FOUND`). This body-reference resolution applies to booking an appointment, creating a retail order, and enrolling a membership.

### 2.9. Optimistic Concurrency on Membership Credits

A membership's `version` is the concurrency token that guards its credit balance, because that balance moves whenever credits are consumed, refunded, granted, or reconciled. Two write operations must therefore carry an `expected_membership_version` field as a non-optional input: booking a credit-paid appointment, and closing a billing cycle.

When booking a credit-paid appointment, the request must supply `expected_membership_version` equal to the current `version` of the target `Membership`. A credit booking debits the membership — appending a consumption ledger entry and incrementing `Membership.version` — and a cycle close, a refund, or an earlier booking may also have advanced that version since the client last read it. If `expected_membership_version` does not match the membership's current `version`, the booking is rejected with `ERR_STALE_MEMBERSHIP_VERSION` (HTTP 412), preventing the client from acting on a balance it has not observed. The same guard applies to closing a billing cycle: the close request must carry `expected_membership_version` matching the membership's current `version`, and a mismatch is rejected with `ERR_STALE_MEMBERSHIP_VERSION` (HTTP 412), so the rollover math is never applied on top of unseen balance movements. Operations that are not credit bookings or cycle closes do not take a version field. When a recurring schedule spawns its next fill it likewise consumes credits and carries an `expected_membership_version`, and the same stale-version rejection applies.

### 2.10. Validation Ordering

When several checks apply to a single operation, they are evaluated in a fixed precedence so that the failure surfaced is deterministic. Authentication of the user context comes first; a request with missing or unknown headers fails with `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 401) before anything else. Role authorization is evaluated second, yielding `ERR_FORBIDDEN_ROLE` (HTTP 403). Existence of path resources is checked third (the not-found family), then existence of body foreign keys fourth (also not-found). State checks come fifth, confirming the target resource is in a state that permits the operation — `ERR_APPOINTMENT_NOT_BOOKED`, `ERR_INVALID_MEMBERSHIP_STATE`, `ERR_PATCH_TEST_NOT_VALID`, or `ERR_INVALID_SCHEDULE_STATE` (all HTTP 409).

Business checks then follow in this order: referential business rules sixth (a retired service type, a non-fill recurring service, or a mismatched retail appointment, yielding `ERR_SERVICE_TYPE_RETIRED`, `ERR_SCHEDULE_NOT_FILL_SERVICE`, or `ERR_ORDER_APPOINTMENT_MISMATCH`, all HTTP 409); the patch-test safety check seventh (`ERR_NO_VALID_PATCH_TEST`, HTTP 422); the fill-timing window eighth (`ERR_FILL_REQUIRES_PRIOR_FULL_SET`, `ERR_FILL_TOO_SOON`, or `ERR_FILL_WINDOW_EXPIRED`, all HTTP 422); sanitation coverage ninth (`ERR_STATION_NOT_SANITIZED`, HTTP 422); chair availability tenth (`ERR_NO_TECH_AVAILABLE`, HTTP 409); the membership-bookable state eleventh (`ERR_MEMBERSHIP_NOT_BOOKABLE`, HTTP 409); the optimistic-concurrency version check twelfth (`ERR_STALE_MEMBERSHIP_VERSION`, HTTP 412); the sufficient-credits check thirteenth (`ERR_INSUFFICIENT_CREDITS`, HTTP 402); and field-level request-shape validation, surfacing `ERR_INVALID_REQUEST` (HTTP 400), last among the listed business checks. A reader implementing the booking pipeline should treat this list as the authoritative ordering for which error wins when more than one condition is violated.

## 3. Business Logic & Workflows

### 3.1. Studios, Service Catalogue, and Membership Plans

A `StudioManager` establishes the configuration root by creating a `Studio` with a `name`. Several policy knobs are set here and default if omitted: `deposit_rate_pct` is the fraction of a service's base price taken as a booking deposit and defaults to 0.20 (it must lie between 0 and 1 inclusive); `late_cancel_cutoff_hours` is the number of hours before an appointment's start under which a cancellation counts as late, defaulting to 24 (it must be at least 0); `noshow_strike_window_days` is the length in days of the rolling window over which no-show strikes accumulate, defaulting to 90; and `noshow_strike_threshold` is the strike count that triggers automatic suspension, defaulting to 3. A studio opens in `status` `OPEN` and may later be `CLOSED`.

Within a studio, the `StudioManager` defines the service catalogue. Each `ServiceType` belongs to a studio (`studio_id`) and is described by a `code` — one of `FULL_SET`, `FILL`, `LIFT`, or `TINT` — a display `name`, a `duration_minutes` (which must be greater than zero and fixes the chair time consumed), a `base_price_cents` (a non-negative cash price from which the deposit is derived), a `credit_cost` (the non-negative number of membership credits a booking consumes when paid with credits), and a `category` that is either `PREMIUM` (the `FULL_SET` and `LIFT` services) or `STANDARD` (the `FILL` and `TINT` services). The `category` drives both the technician-skill requirement and peak-surcharge eligibility. A boolean `requires_patch_test` declares whether a valid consent and patch test is a precondition for booking and defaults to true. A service type is created `active` (true); retiring it sets `active` to false so it can no longer be booked.

Membership pricing is captured by a `MembershipPlan`, also scoped to a studio via `studio_id`. A plan names a `tier` — `ESSENTIAL`, `PREMIER`, or `LUXE` — a positive `monthly_credit_allotment` granted at each billing-cycle close, a non-negative `monthly_fee_cents`, a `rollover_cap_multiplier` that defaults to 1.0 and bounds how many unused credits may carry forward (it must be at least 0), and a `loyalty_discount_pct` that defaults to 0.10 and is the per-line discount fraction applied to a member's retail and add-on purchases (it must lie between 0 and 1 inclusive).

### 3.2. Technicians, Stations, and the Sanitation Log

A `StudioManager` adds a `LashTech` to a studio with a `full_name`, a `skill_level` between 1 and 3 inclusive (1 is junior, 3 is master), and a `station_number` of at least 1 identifying the physical chair the technician occupies, unique within the studio. A new technician starts `AVAILABLE`; the manager may toggle a technician between `AVAILABLE` and `OFF_DUTY`, and an `OFF_DUTY` technician is excluded from appointment assignment. The technician's `station_sanitized_through_utc` begins null.

Sanitation is recorded through the **SanitationLog**, an append-only safety record. A `StudioManager`, `FrontDesk`, or `LashTech` logs a sanitation event for a technician by supplying the `lash_tech_id` and the `sanitized_at_utc` instant at which the station was sanitized; the server stamps the logging operator's identifier into `performed_by_user_id`. Each log is created with `status` `COMPLETED` and computes a `valid_through_utc` equal to `sanitized_at_utc` plus twelve hours. A sanitation log covers the **closed** interval running from `sanitized_at_utc` through `valid_through_utc` inclusive — an appointment that begins exactly at `valid_through_utc` is still considered covered. A `StudioManager` may void a sanitation log, setting its `status` to `VOIDED`.

A technician's `station_sanitized_through_utc` is the latest `valid_through_utc` among that technician's `COMPLETED` sanitation logs (voided logs are excluded), and is recomputed both when a new log is recorded and when a log is voided. This computed instant is the gate that the booking pipeline consults: an appointment may be hosted on a technician only when that technician's `station_sanitized_through_utc` is not null and the appointment's start instant falls at or before it.

### 3.3. Members, Consent, and Patch Tests

A `StudioManager` or `FrontDesk` registers a `Member` against a studio with a `full_name` and an `email` that must be unique within the studio. A new member's `noshow_strike_count` starts at zero and their `last_premium_completed_utc` starts null. Both are computed values that the system keeps current: the strike count is the number of the member's no-show appointments whose start instant lies within the studio's strike window measured backward from the current clock, recomputed on every no-show and on every read of the member; the premium anchor is the start instant of the member's most recent `COMPLETED` appointment whose service `category` is `PREMIUM`, and it anchors the fill-timing window.

Before a member can be booked into a service that requires it, the studio must hold a valid patch test. A `StudioManager` or `FrontDesk` records a `ConsentPatchTest` for a member by supplying the `administered_utc` instant at which the patch test was performed and a `consent_signed` boolean; if `consent_signed` is not true the creation is rejected as an invalid request. The record is created `VALID` and computes a `valid_through_utc` of `administered_utc` plus 365 days. A patch test is treated as `EXPIRED` once the current clock is strictly past its `valid_through_utc` (evaluated whenever the record is read or used to gate a booking), and a member or a `StudioManager` may manually move a `VALID` patch test to `REVOKED`; revoking a record that is not `VALID` is rejected with `ERR_PATCH_TEST_NOT_VALID`.

A service whose `requires_patch_test` is true may only be booked when the member has a patch test that is in `VALID` status, whose `valid_through_utc` is at or after the current clock, and which was signed (`consent_signed` true). When no such patch test exists, the booking is rejected with `ERR_NO_VALID_PATCH_TEST` (HTTP 422). This same patch-test gate applies both to booking an appointment directly and to spawning the next fill from a recurring schedule.

### 3.4. Memberships, the Credit Ledger, and Cycle Reconciliation

A `StudioManager` or `FrontDesk` enrolls a member into a plan by creating a `Membership`, supplying the `member_id`, the `plan_id`, a `cycle_anchor_utc` (the day-of-month anchor for billing-cycle close), and an optional `initial_credits`. The membership opens `ACTIVE` with `cycles_closed` at zero, and a grant ledger entry is appended for the initial credits — defaulting to the plan's `monthly_credit_allotment` when `initial_credits` is omitted — so that the starting `credit_balance` reflects that grant.

Credit movements are recorded exclusively through the **CreditLedgerEntry**, an append-only sub-resource of the membership read back in creation order. Each entry carries a signed `delta`, a `reason` that is one of `GRANT`, `ROLLOVER`, `ROLLOVER_FORFEIT`, `CONSUME`, or `REFUND`, and a polymorphic `source_ref_id` that points at the appointment for consumption and refund entries and at the membership itself for grant, rollover, and rollover-forfeit entries. A membership's `credit_balance` is always the sum of all `delta` values in its ledger and is never negative.

A membership moves through a cyclic lifecycle, all transitions driven by a `StudioManager`. Flagging an `ACTIVE` membership moves it to `PAST_DUE`; settling dues returns a `PAST_DUE` membership to `ACTIVE`. A `SUSPENDED` membership may be reactivated to `ACTIVE`, but only when the member's `noshow_strike_count` has fallen below the studio's threshold because the offending strikes have aged out of the rolling window; reactivating while the count is still at or above the threshold is rejected with `ERR_STRIKES_STILL_ACTIVE` (HTTP 409). From `ACTIVE`, `PAST_DUE`, or `SUSPENDED` a membership may be cancelled to the terminal `CANCELLED` state, which also ends any of that member's `ACTIVE` recurring fill schedules as described in §2.7. A transition requested from a state that does not permit it is rejected with `ERR_INVALID_MEMBERSHIP_STATE` (HTTP 409). Every one of these transitions increments the membership's `version` by one.

Closing a billing cycle is the reconciliation centerpiece, permitted only while the membership is `ACTIVE` and guarded by the optimistic-concurrency check of §2.9. The close proceeds as follows. First, the pre-close balance is read as the current `credit_balance` (the sum of all prior ledger deltas). The rollover ceiling is the plan's `monthly_credit_allotment` multiplied by its `rollover_cap_multiplier`, rounded down to a whole number of credits. The amount carried forward is the smaller of the pre-close balance and that ceiling, and the amount forfeited is the pre-close balance minus the carried amount (never negative). When the pre-close balance exceeds the ceiling, the overage is given up: a `ROLLOVER_FORFEIT` ledger entry with a `delta` equal to the negative of the forfeited amount is appended; the alternative reading in which all credits are carried regardless of the cap is incorrect and must not be implemented. When the pre-close balance is at or below the ceiling, nothing is forfeited and the carried amount equals the pre-close balance. After any forfeiture, a `GRANT` ledger entry with a `delta` of the plan's `monthly_credit_allotment` is appended, so the resulting `credit_balance` equals the carried amount plus the monthly allotment. Closing the cycle also increments `cycles_closed` by one, advances `cycle_anchor_utc` by one month, and increments the membership's `version` by one.

### 3.5. Booking an Appointment: The Full Pipeline

Booking an `Appointment` is the heart of the system and runs a fixed sequence of gates before a chair is committed. A `StudioManager`, `FrontDesk`, or `Member` initiates a booking with the `member_id`, the `service_type_id`, the `start_utc` start instant, an optional `pay_with_credits` flag (defaulting to false), an optional `membership_id`, and, when paying with credits, the `expected_membership_version`. The owning `studio_id` is taken from the referenced member, the appointment is created `BOOKED`, and `end_utc` is computed as `start_utc` plus the service's `duration_minutes`. A `Member` may only book for themselves.

Before the booking commits, the service must be bookable: a retired service type (`active` false) is rejected with `ERR_SERVICE_TYPE_RETIRED`. The patch-test gate of §3.3 then applies when the service requires it. If the service `code` is `FILL`, the fill-timing window of §3.6 is enforced. The system then selects a technician from the candidate pool described in §3.7, applying the sanitation gate of §3.2 (a candidate whose `station_sanitized_through_utc` is null or earlier than `start_utc` is ineligible, and if the gate is the reason no technician can host the appointment the rejection is `ERR_STATION_NOT_SANITIZED`) and the chair-overlap rule of §3.7; if no eligible, non-overlapping technician exists the booking is rejected with `ERR_NO_TECH_AVAILABLE`. The chosen technician's identifier is recorded as the appointment's `lash_tech_id`.

The payment branch then runs. When `pay_with_credits` is false, the appointment is a cash booking: its `deposit_cents` is the service's `base_price_cents` multiplied by the studio's `deposit_rate_pct`, rounded half up to the nearest cent, and `credits_charged` is zero. When `pay_with_credits` is true, the appointment is credit-paid: `deposit_cents` is zero, and the credit pipeline runs. The membership named by `membership_id` must be `ACTIVE` — a `PAST_DUE`, `SUSPENDED`, or `CANCELLED` membership blocks a credit booking and is rejected with `ERR_MEMBERSHIP_NOT_BOOKABLE`. The optimistic-concurrency check of §2.9 then compares `expected_membership_version` to the membership's current `version`. Finally the credit gate runs in a pinned order: the available balance is read as the sum of the membership's existing ledger deltas before this booking; the required amount is the service's `credit_cost`; if the available balance is less than the required amount the booking is rejected with `ERR_INSUFFICIENT_CREDITS` (HTTP 402) and nothing is appended; only when the gate passes does the system append a `CONSUME` ledger entry with a `delta` of the negative of the required amount, set `credits_charged` to the required amount, and increment the membership's `version` by one. Because the gate is checked before the append, the post-booking balance is never negative. The appointment's `recurring_schedule_id` is null for a directly booked appointment and `deposit_forfeited_cents` is zero until a cancellation or no-show resolves it.

Field-shape problems anywhere in a create payload — an unparseable `start_utc`, a non-positive duration, a `deposit_rate_pct` outside the 0-to-1 range, an empty retail line list, or any missing or malformed required field — are rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 3.6. Fill-Timing Windows

A `FILL` service is meaningful only within a biological window after a prior full set or lift, so booking a `FILL` (whether directly or via a recurring schedule) enforces a timing rule anchored to the member's `last_premium_completed_utc`. If that anchor is null — the member has no prior `COMPLETED` `PREMIUM` appointment — the fill is rejected with `ERR_FILL_REQUIRES_PRIOR_FULL_SET`. Otherwise the system measures the gap from the anchor to the proposed `start_utc` in days (the difference in seconds divided by 86,400). A gap of fewer than 5 days is too soon and is rejected with `ERR_FILL_TOO_SOON`; a gap that is exactly 5 days or more satisfies the lower bound. A gap of more than 21 days has let the window expire and is rejected with `ERR_FILL_WINDOW_EXPIRED`; a gap of exactly 21 days or fewer satisfies the upper bound. All three of these rejections carry HTTP 422.

A `RecurringFillSchedule` lets a member or operator automate this cadence. A `StudioManager`, `FrontDesk`, or `Member` creates a schedule with the `member_id`, a `service_type_id` that must reference a `FILL` service (a non-fill service is rejected with `ERR_SCHEDULE_NOT_FILL_SERVICE`), a `cadence_days` between 5 and 21 inclusive (the same fill-window bounds), and a `first_start_utc`. The schedule opens `ACTIVE` with `next_due_utc` set to `first_start_utc` and `spawned_count` at zero.

### 3.7. Technician Assignment and Chair Overlap

The technician is chosen by the server, never named by the client. The candidate pool for a booking is every `LashTech` in the appointment's studio that is `AVAILABLE`, that is qualified for the service (a `PREMIUM` service requires a `skill_level` of at least 2, while a `STANDARD` service has no skill floor), whose `station_sanitized_through_utc` is not null and is at or after the appointment's `start_utc`, and who has no `BOOKED` appointment whose chair time overlaps the new appointment's interval. Only `BOOKED` appointments occupy a chair. Two appointments on the same technician conflict when their half-open intervals — from `start_utc` up to but not including `end_utc` — overlap, that is, when the existing appointment's start is before the new appointment's end and the new appointment's start is before the existing appointment's end. Back-to-back appointments where one's `end_utc` equals the next's `start_utc` are allowed with no buffer between them. Note that this chair-overlap interval is half-open, in deliberate contrast to the sanitation coverage interval of §3.2, which is closed and includes its end instant.

When more than one candidate qualifies, the server ranks them and picks the smallest under this ordering, applied in sequence: first the fewest `BOOKED` appointments the technician already has on the same UTC calendar date as the new appointment's `start_utc`; then the lowest qualifying `skill_level`, so that masters are reserved for premium work; then the lowest `station_number`; and finally, as the deterministic tie-break, the earliest `created_at`. The technician's `id` is never used as a tie-break. If the candidate pool is empty the booking is rejected with `ERR_NO_TECH_AVAILABLE`.

A schedule that is `ACTIVE` can spawn its next fill, an action a `FrontDesk` or `StudioManager` performs and which carries an `expected_membership_version`. Spawning is permitted only when the schedule is `ACTIVE`, when the member's membership is `ACTIVE` (otherwise `ERR_MEMBERSHIP_NOT_BOOKABLE`), and when the prospective fill at `next_due_utc` satisfies the fill-timing window against the member's premium anchor (otherwise the fill-window rejections of §3.6 apply, surfaced here as `ERR_FILL_WINDOW_VIOLATION` in the schedule context). A successful spawn creates a new `BOOKED` `FILL` appointment whose `recurring_schedule_id` is set, whose `start_utc` equals the schedule's `next_due_utc`, and whose `pay_with_credits` is true — running the same selector, sanitation, patch-test, membership, concurrency, and credit-consumption pipeline as a direct booking. After a successful spawn, the schedule's `next_due_utc` advances by `cadence_days` and its `spawned_count` increases by one. A member or operator may also pause an `ACTIVE` schedule to `PAUSED`, resume a `PAUSED` schedule to `ACTIVE`, or end a schedule (from `ACTIVE` or `PAUSED`) to the terminal `ENDED` state; a transition from a state that does not permit it is rejected with `ERR_INVALID_SCHEDULE_STATE`.

### 3.8. Completing, Cancelling, and No-Showing Appointments

A `BOOKED` appointment terminates down one of four branches, each with its own side-effects. Completion is performed by the assigned `LashTech` (or a `StudioManager`) and moves the appointment to `COMPLETED`; it is permitted only when the appointment is still `BOOKED` and the current clock has reached or passed `start_utc` (otherwise `ERR_APPOINTMENT_NOT_STARTED`, HTTP 409). On completion, if the service `category` is `PREMIUM`, the member's `last_premium_completed_utc` is recomputed to reflect this newly completed premium visit, re-anchoring future fill windows. For an appointment that was spawned by a recurring schedule, no further schedule change occurs at completion because `next_due_utc` and `spawned_count` were already advanced at spawn time.

Marking a **no-show** is performed by `FrontDesk` (or a `StudioManager`), is permitted only on a `BOOKED` appointment once the current clock has reached or passed `start_utc` (otherwise `ERR_APPOINTMENT_NOT_STARTED`), and moves the appointment to `NO_SHOW`. The full deposit is kept: `deposit_forfeited_cents` is set equal to `deposit_cents`, and the cash deposit is retained by the studio. If the appointment was credit-paid there is no refund — the consumed credits stay consumed. The member's `noshow_strike_count` is then recomputed against the rolling window, and if it reaches the studio's `noshow_strike_threshold` the member's membership cascades from `ACTIVE` or `PAST_DUE` to `SUSPENDED`, which in turn auto-cancels the member's future `BOOKED` appointments as described in §2.7.

Cancelling a `BOOKED` appointment is performed by the booking `Member` or by `FrontDesk` (a `StudioManager` may also cancel), and the timing relative to the studio's `late_cancel_cutoff_hours` decides the outcome. A cancellation is **timely** when the gap from the current clock to `start_utc` is at or beyond the cutoff (that is, the time remaining until start is greater than or equal to the cutoff hours); the appointment moves to `CANCELLED`, `deposit_forfeited_cents` is set to zero so the cash deposit is fully refundable, and if it was credit-paid a `REFUND` ledger entry with a `delta` of the positive of `credits_charged` is appended, returning the credits. A cancellation is **late** when the current clock is within the cutoff window before start — the time remaining is less than the cutoff hours and the clock is still before `start_utc`; the appointment moves to `LATE_CANCELLED`, and `deposit_forfeited_cents` is set to the deposit multiplied by one half, rounded half up to the nearest cent, so the studio keeps half the deposit. The competing reading in which the studio refunds half (forfeiting the other half) is incorrect: the studio keeps half. A late cancellation of a credit-paid appointment likewise appends a `REFUND` ledger entry of the positive of `credits_charged`. Cancelling or no-showing an appointment that is not `BOOKED` is rejected with `ERR_APPOINTMENT_NOT_BOOKED` (HTTP 409). When a timely cancellation resolves an appointment that was spawned by a recurring schedule, the slot is reclaimed: the schedule's `next_due_utc` is rewound by `cadence_days` and its `spawned_count` is decreased by one.

### 3.9. Retail and Add-On Orders

A `StudioManager`, `FrontDesk`, or `Member` attaches a retail or add-on purchase to a visit by creating a `RetailOrder` with the `member_id`, the `appointment_id` it attaches to, and a non-empty `lines` array. Each line is an object with a `sku`, a positive `unit_price_cents`, and a positive `quantity`; an empty line list or a non-positive unit price or quantity is an invalid request. The referenced appointment must be a `BOOKED` appointment belonging to the same member, otherwise the order is rejected with `ERR_ORDER_APPOINTMENT_MISMATCH`. An order is created with `status` `PAID`, and a `StudioManager` or `FrontDesk` may later void it to `VOIDED`.

The order total is computed with a pinned rounding order. The loyalty discount fraction is the member's plan `loyalty_discount_pct` if the member holds an `ACTIVE` or `PAST_DUE` membership, and zero otherwise. For each line, the line amount is `unit_price_cents` multiplied by `quantity` multiplied by one minus the loyalty fraction, rounded half up to the nearest cent — the discount and rounding are applied **per line first**, and only then are the line amounts summed into `subtotal_cents`. Summing the raw amounts and rounding once at the end is the wrong reading and must not be used.

A peak surcharge may then apply, determined by three inputs together. The assigned technician's load is the count of that technician's `BOOKED` appointments whose `start_utc` falls on the same UTC calendar date as the linked appointment's `start_utc`. The order is premium when the linked appointment's service `category` is `PREMIUM`. When the technician's same-day load is at least 3 and the linked service is premium, `peak_surcharge_cents` is `subtotal_cents` multiplied by 0.15, rounded half up to the nearest cent; in every other case `peak_surcharge_cents` is zero. The order's `total_cents` is `subtotal_cents` plus `peak_surcharge_cents`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that read a resource or collection, or that modify an existing resource (including state transitions and voids), return `200 OK`. The logical-clock control returns `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/studios` | Create a studio | StudioManager |
| GET | `/studios` | List studios | StudioManager, FrontDesk, LashTech, Member |
| GET | `/studios/{id}` | Get a studio | StudioManager, FrontDesk, LashTech, Member |
| POST | `/service-types` | Create a service type | StudioManager |
| GET | `/service-types` | List service types (filter by `studio_id`) | StudioManager, FrontDesk, LashTech, Member |
| GET | `/service-types/{id}` | Get a service type | StudioManager, FrontDesk, LashTech, Member |
| POST | `/service-types/{id}/retire` | Retire a service type | StudioManager |
| POST | `/membership-plans` | Create a membership plan | StudioManager |
| GET | `/membership-plans` | List membership plans (filter by `studio_id`) | StudioManager, FrontDesk, LashTech, Member |
| GET | `/membership-plans/{id}` | Get a membership plan | StudioManager, FrontDesk, LashTech, Member |
| POST | `/lash-techs` | Create a lash technician | StudioManager |
| GET | `/lash-techs` | List lash technicians (filter by `studio_id`) | StudioManager, FrontDesk, LashTech, Member |
| GET | `/lash-techs/{id}` | Get a lash technician | StudioManager, FrontDesk, LashTech, Member |
| POST | `/lash-techs/{id}/set-status` | Set a technician AVAILABLE or OFF_DUTY | StudioManager |
| GET | `/lash-techs/{id}/sanitation-logs` | List a technician's sanitation logs | StudioManager, FrontDesk, LashTech, Member |
| POST | `/sanitation-logs` | Record a station sanitation event | StudioManager, FrontDesk, LashTech |
| GET | `/sanitation-logs` | List sanitation logs (filter by `lash_tech_id`) | StudioManager, FrontDesk, LashTech, Member |
| GET | `/sanitation-logs/{id}` | Get a sanitation log | StudioManager, FrontDesk, LashTech, Member |
| POST | `/sanitation-logs/{id}/void` | Void a sanitation log | StudioManager |
| POST | `/members` | Create a member | StudioManager, FrontDesk |
| GET | `/members` | List members (filter by `studio_id`) | StudioManager, FrontDesk |
| GET | `/members/{id}` | Get a member | StudioManager, FrontDesk, Member |
| GET | `/members/{id}/patch-tests` | List a member's patch tests | StudioManager, FrontDesk, Member |
| POST | `/memberships` | Enroll a member in a plan | StudioManager, FrontDesk |
| GET | `/memberships` | List memberships (filter by `member_id` or `plan_id`) | StudioManager, FrontDesk, Member |
| GET | `/memberships/{id}` | Get a membership | StudioManager, FrontDesk, Member |
| GET | `/memberships/{id}/credit-ledger` | List a membership's credit ledger | StudioManager, FrontDesk, Member |
| POST | `/memberships/{id}/close-cycle` | Close a billing cycle (rollover + grant) | StudioManager |
| POST | `/memberships/{id}/flag-past-due` | Flag a membership past due | StudioManager |
| POST | `/memberships/{id}/settle-dues` | Settle dues and return to active | StudioManager |
| POST | `/memberships/{id}/reactivate` | Reactivate a suspended membership | StudioManager |
| POST | `/memberships/{id}/cancel-membership` | Cancel a membership | StudioManager |
| POST | `/patch-tests` | Record a patch test and consent | StudioManager, FrontDesk |
| GET | `/patch-tests` | List patch tests (filter by `member_id`) | StudioManager, FrontDesk, Member |
| GET | `/patch-tests/{id}` | Get a patch test | StudioManager, FrontDesk, Member |
| POST | `/patch-tests/{id}/revoke` | Revoke consent | StudioManager, Member |
| POST | `/appointments` | Book an appointment | StudioManager, FrontDesk, Member |
| GET | `/appointments` | List appointments (filter by `studio_id`, `member_id`, `lash_tech_id`, `service_type_id`, `membership_id`, `recurring_schedule_id`) | StudioManager, FrontDesk, LashTech, Member |
| GET | `/appointments/{id}` | Get an appointment | StudioManager, FrontDesk, LashTech, Member |
| POST | `/appointments/{id}/complete` | Mark an appointment completed | LashTech, StudioManager |
| POST | `/appointments/{id}/cancel` | Cancel an appointment | Member, FrontDesk, StudioManager |
| POST | `/appointments/{id}/mark-no-show` | Mark an appointment no-show | FrontDesk, StudioManager |
| GET | `/appointments/{id}/retail-orders` | List retail orders for an appointment | StudioManager, FrontDesk, Member |
| POST | `/retail-orders` | Create a retail/add-on order | StudioManager, FrontDesk, Member |
| GET | `/retail-orders` | List retail orders (filter by `member_id` or `appointment_id`) | StudioManager, FrontDesk, Member |
| GET | `/retail-orders/{id}` | Get a retail order | StudioManager, FrontDesk, Member |
| POST | `/retail-orders/{id}/void` | Void a retail order | StudioManager, FrontDesk |
| POST | `/recurring-schedules` | Create a recurring fill schedule | StudioManager, FrontDesk, Member |
| GET | `/recurring-schedules` | List recurring schedules (filter by `member_id` or `service_type_id`) | StudioManager, FrontDesk, Member |
| GET | `/recurring-schedules/{id}` | Get a recurring schedule | StudioManager, FrontDesk, Member |
| POST | `/recurring-schedules/{id}/spawn-next` | Spawn the next fill appointment | FrontDesk, StudioManager |
| POST | `/recurring-schedules/{id}/pause` | Pause a recurring schedule | Member, FrontDesk, StudioManager |
| POST | `/recurring-schedules/{id}/resume` | Resume a paused schedule | Member, FrontDesk, StudioManager |
| POST | `/recurring-schedules/{id}/end` | End a recurring schedule | Member, FrontDesk, StudioManager |
| POST | `/_clock/set_current_utc` | Set the server logical clock | StudioManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_STUDIO_NOT_FOUND` | 404 Not Found |
| `ERR_SERVICE_TYPE_NOT_FOUND` | 404 Not Found |
| `ERR_MEMBER_NOT_FOUND` | 404 Not Found |
| `ERR_MEMBERSHIP_NOT_FOUND` | 404 Not Found |
| `ERR_APPOINTMENT_NOT_FOUND` | 404 Not Found |
| `ERR_TECH_NOT_FOUND` | 404 Not Found |
| `ERR_SCHEDULE_NOT_FOUND` | 404 Not Found |
| `ERR_PATCH_TEST_NOT_FOUND` | 404 Not Found |
| `ERR_APPOINTMENT_NOT_BOOKED` | 409 Conflict |
| `ERR_APPOINTMENT_NOT_STARTED` | 409 Conflict |
| `ERR_INVALID_MEMBERSHIP_STATE` | 409 Conflict |
| `ERR_PATCH_TEST_NOT_VALID` | 409 Conflict |
| `ERR_INVALID_SCHEDULE_STATE` | 409 Conflict |
| `ERR_STRIKES_STILL_ACTIVE` | 409 Conflict |
| `ERR_SERVICE_TYPE_RETIRED` | 409 Conflict |
| `ERR_SCHEDULE_NOT_FILL_SERVICE` | 409 Conflict |
| `ERR_ORDER_APPOINTMENT_MISMATCH` | 409 Conflict |
| `ERR_NO_TECH_AVAILABLE` | 409 Conflict |
| `ERR_MEMBERSHIP_NOT_BOOKABLE` | 409 Conflict |
| `ERR_NO_VALID_PATCH_TEST` | 422 Unprocessable Entity |
| `ERR_FILL_REQUIRES_PRIOR_FULL_SET` | 422 Unprocessable Entity |
| `ERR_FILL_TOO_SOON` | 422 Unprocessable Entity |
| `ERR_FILL_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_FILL_WINDOW_VIOLATION` | 422 Unprocessable Entity |
| `ERR_STATION_NOT_SANITIZED` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_CREDITS` | 402 Payment Required |
| `ERR_STALE_MEMBERSHIP_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
