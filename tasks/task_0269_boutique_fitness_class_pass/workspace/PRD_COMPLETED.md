# Boutique Fitness Class Pass API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Boutique Fitness Class Pass platform, a multi-studio class-booking network in the spirit of a ClassPass-style marketplace. The platform stitches together three concerns that are easy to describe in isolation but unforgiving when they interact: a published class schedule constrained by physical rooms and traveling instructors, a credit wallet funded by purchased packages and memberships, and a reservation flow that must hold seats, run a fair waitlist, and assess fees when members fail to honour their bookings.

The business problem the API solves is the reconciliation of *capacity* against *entitlement* in real time. A member holds spendable credits inside a membership wallet; a class session holds a fixed number of bookable seats inside a physically limited room. When a member reserves a seat, credits must be debited atomically against capacity, and when a seat frees up, the next eligible member on the waitlist must inherit it without anyone having to ask. Layered on top are the messy realities of a fitness business: intro offers that may be used only once, memberships that can be frozen and later renewed with credit rollover, prorated cancellation refunds, and an escalating fee structure that discourages last-minute cancellations and no-shows while still treating members fairly.

Every mutation in this system resolves its consequences immediately and atomically within the triggering request. There is no eventual consistency and no background settlement: when a session is cancelled, its reservations are released and credits refunded before the response returns; when a seat opens on a full session, the waitlist is walked and a promotion is committed inside the same call. The sections below define the global contract first, then narrate the business workflows from which an implementer must reconstruct the complete behaviour.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the operational capacity under which the request is made. The system recognizes exactly three roles, spelled precisely as `NetworkAdmin`, `StudioManager`, and `Member`. A request that omits either header, or that carries a role string outside this set, is rejected with `ERR_UNAUTHENTICATED`. When the headers are present and well-formed but the role is not permitted to perform the requested operation — or an ownership check fails — the request is rejected with `ERR_FORBIDDEN`.

The three roles map to identity differently. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`; ownership checks on any resource that references a `Member` compare the resource's member foreign key to `X-User-ID`. Concretely, a `Member` may act only on memberships, reservations, and fees that trace back to their own `Member.id` — for example a reservation whose `member_id` equals the caller's `X-User-ID`, or a membership whose `member_id` does — and likewise on a `Member` resource only when its own `id` equals the caller's `X-User-ID`; a `Member` acting on another member's `Member` record, or on memberships/reservations/fees keyed to another member, fails the ownership check with `ERR_FORBIDDEN`. When `X-User-Role` is `NetworkAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. Likewise, when `X-User-Role` is `StudioManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. The `NetworkAdmin` is the network operator who owns global configuration — studios, instructors, class templates, and package plans — and who drives the clock, payment, and operational sweep endpoints. The `StudioManager` runs a studio's schedule and on-site operations: publishing and cancelling sessions, editing sessions, retiring rooms, checking members in, and waiving fees. The `Member` is the end customer who purchases packages, reserves and cancels seats, and freezes their own membership.

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

List endpoints accept two query parameters, `limit` and `offset`. The `limit` parameter caps how many items are returned; it defaults to 10 when omitted, may be no smaller than 1, and may be no larger than 100. The `offset` parameter is the number of items to skip from the front of the result set; it defaults to 0. A `limit` outside [1, 100], a negative `offset`, or a non-integer value for either is rejected with `ERR_INVALID_REQUEST` rather than being clamped.

Unless a specific endpoint says otherwise, every list is sorted by the resource's creation timestamp in ascending order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Most resources in the system carry a common set of server-managed fields. The `id` is a server-minted UUID, with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created. The `updated_at` field is an ISO 8601 UTC timestamp recording the last mutation of the resource. The `version` is an integer that begins at its initial value of 1 when the resource is created and increments by one on every mutation; it is the basis for optimistic concurrency control described in §2.6.

One entity is deliberately leaner. A `WalletEntry` is an immutable ledger record: it carries only `id` and `created_at`. It has no `updated_at` and no `version`, because a ledger line, once written, is never edited — corrections are expressed by appending new entries, not by rewriting old ones. Every other entity — `Studio`, `Room`, `Instructor`, `ClassTemplate`, `PackagePlan`, `Member`, `Membership`, `ClassSession`, `Reservation`, and `FeeCharge` — carries the full quartet of `id`, `created_at`, `updated_at`, and `version`.

### 2.5. Atomic Cascades and Derived Counters

Several operations touch more than one entity. When that happens, every consequence resolves synchronously inside the triggering request, and each mutated entity independently refreshes its own `updated_at` and increments its own `version`. There is no partial application: either the whole cascade commits or the request is rejected before anything changes.

Counters and balances that are described as computed are always kept in agreement with the rows they summarize. A session's `booked_count` is the number of reservations on it whose `booking_status` is `BOOKED`, and its `waitlisted_count` is the number whose `booking_status` is `WAITLISTED`. A membership's `credit_balance` is the running sum of the `delta` values of all `WalletEntry` rows attached to it. A studio's `active_room_count` is the number of rooms under it whose `status` is `ACTIVE`. A member's `no_show_strikes` is recomputed from the fee ledger as described in §3.7. Whenever an action changes the underlying rows, these derived values are recomputed before the response is returned.

Time in this system is driven by a logical clock rather than wall-clock time, so that late-cancel windows, freeze spans, expiry, and session completion are deterministic. An admin-only test-driving capability sets the server's current UTC clock to a supplied `to_iso8601` instant; every rule in §3 that speaks of "the current clock" reads this value.

### 2.6. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, each keyed to a parent entity's `version`.

A request to reserve a seat must carry `expected_session_version`, the client's last observed `version` of the target `ClassSession`. The check is applied after the session has been confirmed bookable: if `expected_session_version` does not equal the session's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). This guards against booking against a stale view of capacity — a free seat the client saw may already have been taken by an earlier booking that bumped the session's `version` and possibly flipped the session from `OPEN` to `FULL`, so the client is required to re-read before retrying.

A request to freeze a membership must carry `expected_membership_version`, the client's last observed `version` of the target `Membership`. The check is applied after the membership has been confirmed freezable — specifically, after the generic state gate has confirmed the membership is `ACTIVE` (§2.9) but before the specific `ERR_FREEZE_NOT_ALLOWED` business-rule checks of §3.3: if `expected_membership_version` does not equal the membership's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). A debit, refund, or renewal may have moved `credit_balance` or `freeze_days_used` since the client read the membership — any of which can legitimately change whether a freeze is permitted — so a mismatched version means the snapshot is stale and the freeze is refused until re-read.

No other endpoint takes a version field; operations not named in this subsection are not OCC-guarded.

### 2.7. Nested Resource Retrieval and Existence Ordering

Many paths reference one or more resource identifiers, some nested (for example, the rooms under a studio, the reservations under a session, or the wallet entries under a membership). The system validates every referenced identifier — whether it appears in the path or the body — left to right, and rejects the request with `ERR_NOT_FOUND` the moment it reaches an identifier that resolves to nothing. A reservation listing under a non-existent session, for instance, fails on the missing session before the listing is attempted. This existence pass runs after authentication and authorization but before any business-rule evaluation.

### 2.8. Monetary and Credit Precision

Two distinct units of account circulate in this system, and neither is ever expressed as a floating-point fraction in storage. Credits are whole integers: a membership wallet holds an integer `credit_balance`, a template costs an integer number of credits to book, and every `WalletEntry.delta` is a signed integer. No rounding ever applies to credit arithmetic. Money is held in integer cents: `price_cents`, `amount_cents`, `refund_cents`, and `late_fee_cents` are all integer cent values. Where a monetary figure is derived by multiplication — notably the prorated cancellation refund of §3.4 — the multiplication is carried at full precision and the result is rounded half up to a whole cent exactly once, at the very end.

### 2.9. Validation Ordering

When several checks could fail a single request, they are evaluated in a fixed priority order so that the most fundamental failure is the one reported. Authentication (`ERR_UNAUTHENTICATED`) is checked first, then authorization and ownership (`ERR_FORBIDDEN`), then the existence of every referenced identifier (`ERR_NOT_FOUND`), then request well-formedness — required fields present, correct types, enum values within their declared sets, and numeric fields within their declared ranges (`ERR_INVALID_REQUEST`). Only after these four universal gates pass does the system evaluate state and business rules specific to each operation, in the order spelled out in the relevant §3 workflow.

For any operation that drives a state machine, the generic state gate comes next: if the targeted resource is not in a state from which the requested transition is defined, the request is rejected with `ERR_INVALID_STATE`. This is the default state error for transitions such as freezing a membership that is not `ACTIVE`, unfreezing one that is not `FROZEN`, renewing one that is not eligible, publishing a session that is not `SCHEDULED`, or waiving a fee that is not `ASSESSED`. A handful of transitions carry more specific state errors that take precedence over this generic one where they apply — reserving against a non-bookable session yields `ERR_SESSION_NOT_BOOKABLE`, and a check-in outside its lead window yields `ERR_INVALID_CANCEL_WINDOW` — as described in the §3 workflows.

## 3. Business Logic & Workflows

### 3.1. Network Configuration: Studios, Rooms, Instructors, and Templates

The network is assembled by the `NetworkAdmin`. Creating a studio supplies its display `name` and a US `state_code` such as `CA`, and optionally an IANA `timezone` such as `America/Los_Angeles`; when the `timezone` is omitted (or supplied as null) it defaults to `UTC`. The `name`, `state_code`, and (when present) `timezone` are accepted as any non-empty string — the `state_code` is not checked against a list of US states and the `timezone` is not validated against the IANA tz database. A new studio opens in `OPEN` `status` with an `active_room_count` of zero. A studio may later be moved to `CLOSED`; a `CLOSED` studio rejects new session creation and publication. Both the `NetworkAdmin` and a `StudioManager` may add rooms to a studio: a room is created under a `studio_id`, with a `name` and a `physical_capacity` that must be an integer of at least 1, and it begins `ACTIVE`. Retiring a room sets its `status` to `RETIRED`; a `RETIRED` room cannot host new sessions. Each time a room is added or retired, the owning studio's `active_room_count` is recomputed.

Instructors are network-level resources created by the `NetworkAdmin` with a `full_name` and a `home_studio_id` naming the studio they are primarily based at. An instructor begins `ACTIVE` and may be deactivated to `INACTIVE`; an `INACTIVE` instructor cannot be assigned to new sessions. Class templates, also created by the `NetworkAdmin`, describe a class type: a `name` such as `Vinyasa Flow`, a `duration_min` that must be an integer between 15 and 240 inclusive, a `credit_cost` that is an integer of at least 1 representing the credits charged to reserve one seat in a session of this template, and a `late_cancel_window_hours` integer of at least 0 that defaults to 12 and defines how many hours before a session's start a cancellation counts as a late cancel. A template begins `ACTIVE`; an `ARCHIVED` template cannot back new sessions.

### 3.2. Packages, Purchase, and Wallet Funding

A package plan is the catalogue entry a member buys. The `NetworkAdmin` creates a plan with a `name`, a `kind` that is one of `INTRO`, `CREDIT_PACK`, or `MEMBERSHIP`, a `price_cents` that is an integer of at least 0, a `grant_credits` integer of at least 1, and a `validity_days` integer of at least 1. For an `INTRO` or `CREDIT_PACK` plan, `grant_credits` is the one-time credit grant and `validity_days` is the number of days from activation until those credits expire; for a `MEMBERSHIP` plan, `grant_credits` is the credit grant per cycle and `validity_days` is the length of one billing cycle. Three further fields apply only to certain kinds. The `rollover_cap` (default 0) applies only to `MEMBERSHIP` and is the maximum number of unused credits that may be carried into the next cycle, where 0 means no rollover; it is ignored for `INTRO` and `CREDIT_PACK`. The `freeze_max_days` (default 0) applies only to `MEMBERSHIP` and is the cumulative number of days a membership may be frozen within one cycle; it is ignored otherwise. The `intro_once_per_member` boolean (default true) applies only to `INTRO`: when true, a member may purchase at most one `INTRO` plan ever. A plan begins `ACTIVE`; a `RETIRED` plan cannot be purchased.

Members are registered with an `email`, a `full_name`, and a `home_studio_id` (the `home_studio_id` must reference an existing studio); the `email` is intended to be a unique case-insensitive identifier but the system does not reject a registration whose email duplicates an existing member's. A new member starts with `has_used_intro` false, `no_show_strikes` zero, and `standing` of `GOOD`. Purchasing a plan — performed by the member themselves or by the `NetworkAdmin` — supplies the `plan_id` and creates a `Membership` referencing the buyer through `member_id` and the catalogue entry through `plan_id`. The new membership opens in `PENDING_PAYMENT` `status` with a `credit_balance` of 0. If the chosen plan is an `INTRO` plan whose `intro_once_per_member` is true and the member's `has_used_intro` is already true, the purchase is refused with `ERR_INTRO_ALREADY_USED`.

A membership only becomes spendable once payment is captured. The admin-only payment-capture capability takes the `membership_id` and an `outcome` (a non-empty string); on a `CAPTURED` outcome and a membership currently in `PENDING_PAYMENT`, the membership advances `PENDING_PAYMENT → ACTIVE`. Capture is permitted only from `PENDING_PAYMENT`: invoking it on a membership in any other state is rejected with `ERR_INVALID_STATE`. Any `outcome` other than `CAPTURED` (on a `PENDING_PAYMENT` membership) leaves the membership in `PENDING_PAYMENT` unchanged and is rejected with `ERR_INVALID_REQUEST`. Activation stamps `activated_at` and `cycle_start` to the current clock and sets `expires_at` to `cycle_start` plus the plan's `validity_days` days — the instant at which the cycle's credits expire. A grant ledger line is appended (a `WalletEntry` of `kind` `GRANT` carrying a positive `delta` equal to the plan's `grant_credits` and bearing the `membership_id`), and `credit_balance` is recomputed. Each wallet line also records a human-readable `note` and, when the line is a reservation debit or its refund, the `reservation_id` it pertains to; grant, expiry, and rollover lines leave `reservation_id` null. If the activated plan is an `INTRO` plan, the member's `has_used_intro` is set to true at activation.

### 3.3. Freeze, Unfreeze, and Renewal

A `Member` (or the `NetworkAdmin` acting on their behalf) may freeze an `ACTIVE` membership. A freeze is permitted only when the membership is `ACTIVE`, the underlying plan's `kind` is `MEMBERSHIP`, the plan's `freeze_max_days` is greater than 0, and the membership's `freeze_days_used` is still strictly below `freeze_max_days`; a request that violates any of these is refused with `ERR_FREEZE_NOT_ALLOWED`. The freeze request is OCC-guarded as described in §2.6 and must carry `expected_membership_version`. On a successful freeze the membership moves `ACTIVE → FROZEN`, `frozen_at` is set to the current clock, and — importantly — `expires_at` is *not* advanced at freeze time. The cycle is paused, not extended, until the membership is unfrozen.

Unfreezing moves the membership `FROZEN → ACTIVE`. The frozen span is computed as the number of whole days between `frozen_at` and the current clock, rounded up to the next whole day, and then capped so that `freeze_days_used` plus this span never exceeds the plan's `freeze_max_days`. That capped span is added to `freeze_days_used`, and `expires_at` is advanced by the same capped number of days — this is where the paused cycle is finally extended to compensate for the freeze. The `frozen_at` marker is then cleared to null. Because the cap is re-evaluated each time, a membership may freeze and unfreeze repeatedly within one cycle until `freeze_days_used` reaches `freeze_max_days`.

Renewal is an admin-only operation available on an `ACTIVE` `MEMBERSHIP`-kind membership once the current clock has reached or passed `expires_at`. It is a self-loop that keeps the membership `ACTIVE` while resetting the cycle and applying credit rollover. The number of credits carried forward, recorded in `rolled_over_credits`, is the smaller of the membership's `credit_balance` at the moment of renewal and the plan's `rollover_cap`. Any surplus — the `credit_balance` minus `rolled_over_credits` — is forfeited; when that forfeited amount is greater than zero, a ledger line of `kind` `ROLLOVER_FORFEIT` is appended carrying a negative `delta` equal to the forfeited amount. A fresh grant line of `kind` `GRANT` is then appended for the plan's `grant_credits` (its `note` recording how many credits rolled in), `cycle_start` is set to the old `expires_at`, `expires_at` is advanced to the new `cycle_start` plus `validity_days`, and `freeze_days_used` is reset to zero. After renewal the `credit_balance` equals `rolled_over_credits` plus the plan's `grant_credits`. At the boundary, a balance exactly equal to the rollover cap rolls entirely with nothing forfeited, whereas a balance one credit above the cap rolls the cap and forfeits that single surplus credit.

### 3.4. Membership Cancellation and Expiry

A `Member` (or the `NetworkAdmin`) may cancel a membership that is `ACTIVE` or `FROZEN`, moving it to the terminal `CANCELLED` state. Cancellation computes a prorated monetary `refund_cents` and forfeits any remaining credits. The proration first measures `elapsed_days`: the number of whole days from `cycle_start` to the current clock, taking the floor, and then subtracting `freeze_days_used` so that days spent frozen do not count as elapsed (the cycle was paused for them). The remaining portion of the cycle is `validity_days` minus `elapsed_days`, floored at zero so it never goes negative. The refund is then the plan's `price_cents` multiplied by the ratio of those remaining days to the full `validity_days` — the ratio kept at full precision, multiplied into the price, and rounded half up to a whole cent exactly once at the end (never round the ratio first). This proration applies in full only to `MEMBERSHIP`-kind plans; for `INTRO` and `CREDIT_PACK` plans the refund is always 0, because packs are non-refundable. In every case the remaining credits are forfeited: the entire `credit_balance` is written off with an `EXPIRY_FORFEIT` ledger line carrying a negative `delta` when that balance is greater than zero, and `credit_balance` is recomputed to 0.

Expiry is the unattended counterpart, driven by an admin-only operational sweep that advances every membership whose cycle has ended. A membership in `ACTIVE` whose plan `kind` is not `MEMBERSHIP` — that is, an `INTRO` or `CREDIT_PACK` membership that does not auto-renew — and whose current clock has reached or passed `expires_at` transitions `ACTIVE → EXPIRED`. A membership in `FROZEN` whose (frozen-extended) `expires_at` has been reached or passed likewise transitions `FROZEN → EXPIRED`; a membership frozen past its expiry still expires. In both expiry paths the entire remaining `credit_balance` is forfeited through an `EXPIRY_FORFEIT` ledger line carrying a negative `delta` when the balance is greater than zero, and `credit_balance` is recomputed to 0. `EXPIRED` and `CANCELLED` are terminal.

### 3.5. Scheduling Sessions: Rooms, Instructors, and Conflict Windows

A `StudioManager` or the `NetworkAdmin` schedules a class by supplying a `studio_id`, a `room_id`, an `instructor_id`, a `template_id`, a `starts_at` instant in ISO 8601 UTC, a `seat_capacity` integer of at least 1, and optionally a `waitlist_capacity` (default 5, an integer of at least 0) that bounds how many `WAITLISTED` reservations the session may hold at once. The supplied `room_id` must name a room belonging to the supplied `studio_id`; a room whose `studio_id` does not match is treated as a missing reference and rejected with `ERR_NOT_FOUND`. The `instructor_id` is not required to be based at the hosting studio — an instructor may teach at any studio, subject only to the cross-studio travel buffer below. The session is created in `SCHEDULED` `status` with `booked_count` and `waitlisted_count` at zero, and its `ends_at` computed as `starts_at` plus the template's `duration_min` minutes.

Before a session may be created, published, or edited, the operational state of its dependencies is checked first, ahead of any temporal-overlap or capacity check: the hosting studio must be `OPEN`, the room must be `ACTIVE`, and the instructor must be `ACTIVE`. A violation of any of these is rejected with `ERR_STUDIO_CLOSED`. The seat capacity is then constrained so that a session's `seat_capacity` may never exceed the hosting room's `physical_capacity`; a violation is rejected with `ERR_CAPACITY_EXCEEDS_ROOM`.

Two temporal-conflict rules then guard the schedule, evaluated over all of an instructor's or a room's non-`CANCELLED` sessions. The **instructor conflict** rule looks at the half-open interval from each session's `starts_at` to its `ends_at`. Two sessions of the same instructor at the *same* studio conflict when their intervals strictly overlap — sessions that merely touch at a single instant do not conflict. Two sessions of the same instructor at *different* studios additionally require a travel buffer of 30 minutes: they conflict when the gap between them is less than 30 minutes, where the gap is the later session's `starts_at` minus the earlier session's `ends_at` in minutes, floored at zero. Any such same-studio overlap or cross-studio under-buffer is rejected with `ERR_INSTRUCTOR_CONFLICT`. The **room conflict** rule appends a 15-minute cleaning buffer to each session: a session's effective interval runs from its `starts_at` to its `ends_at` plus 15 minutes. Two non-`CANCELLED` sessions in the same room conflict when each one's `starts_at` falls before the other's cleaning-padded end — the windows being half-open, so a session may start exactly when the prior padded interval ends without conflicting. An overlap here is rejected with `ERR_ROOM_CONFLICT`.

Editing a session before it completes lets a manager change its `seat_capacity`, `starts_at`, `room_id`, or `waitlist_capacity`. Every edit re-runs the same dependency, capacity, and conflict checks. Publishing a `SCHEDULED` session advances it `SCHEDULED → OPEN`, making it bookable; publication re-validates that the room and instructor are still `ACTIVE`, the studio still `OPEN`, and the conflict rules still hold. A session that cannot satisfy these is not publishable.

### 3.6. Reserving a Seat and the Waitlist

A `Member` reserves a seat on a bookable session (or the `NetworkAdmin` does so on their behalf), supplying the `membership_id` that funds the booking and the `expected_session_version` for the OCC guard of §2.6. The created `Reservation` records the `session_id`, the `member_id`, and the `membership_id`; it carries two independent status dimensions. The first dimension, `booking_status`, tracks seat holding through `WAITLISTED`, `BOOKED`, and the terminal `RELEASED`. The second dimension, `attendance_status`, tracks the outcome through `PENDING`, `CHECKED_IN`, `NO_SHOW`, `CANCELLED`, and `LATE_CANCELLED`, and evolves independently of the first. A reservation also carries `credits_charged` (the credits debited when it took a seat, 0 while waitlisted), `waitlist_position` (its 1-based place among `WAITLISTED` reservations on the session ordered by `created_at` ascending, 0 when not waitlisted), `late_fee_cents` (cents charged for a late cancel or no-show, 0 otherwise), and `promoted_at` (the instant a waitlisted reservation was auto-promoted, null if never promoted).

The reservation request is gated by a sequence of checks. The session must be bookable — in `OPEN` or `FULL`; a `SCHEDULED`, `CANCELLED`, or `COMPLETED` session is not bookable and the attempt is rejected with `ERR_SESSION_NOT_BOOKABLE`. After the session is confirmed bookable, the OCC check on `expected_session_version` runs, yielding `ERR_STALE_VERSION` on a mismatch. The member's `standing` must be `GOOD`; a `RESTRICTED` member is refused with `ERR_MEMBER_RESTRICTED`. The funding membership must be `ACTIVE`, checked before the duplicate, waitlist, and credit checks; an inactive membership yields `ERR_MEMBERSHIP_INACTIVE`. The member may not already hold a non-`RELEASED` reservation on the same session; a second one is rejected with `ERR_DUPLICATE_RESERVATION`.

What happens next depends on capacity. If the session is `OPEN` and `booked_count` is below `seat_capacity`, the reservation takes a free seat immediately: it is created already `BOOKED` (skipping `WAITLISTED`), the template's `credit_cost` is debited from the membership through a `RESERVE_DEBIT` wallet line carrying a negative `delta`, `credits_charged` is set to that cost, and `booked_count` is incremented; if that increment makes `booked_count` equal `seat_capacity`, the session transitions `OPEN → FULL`. This immediate-booking path requires that the membership's `credit_balance` is at least the template's `credit_cost`; if it is not, the booking is refused with `ERR_INSUFFICIENT_CREDITS`. Waitlist entries are never charged at creation time — only on promotion. If instead no free seat exists, the reservation joins the waitlist as `WAITLISTED`, but only while `waitlisted_count` is below the session's `waitlist_capacity`; once the waitlist is full the attempt is rejected with `ERR_WAITLIST_FULL`. A waitlisted reservation is assigned the next `waitlist_position` and increments `waitlisted_count`.

### 3.7. Cancellation, Auto-Promotion, Check-In, and Strikes

Cancelling a reservation behaves differently along three branches, distinguished by the reservation's current `booking_status` and, for booked seats, by timing relative to the late-cancel window. The window opens at the session's `starts_at` minus the template's `late_cancel_window_hours` hours.

Cancelling a `WAITLISTED` reservation moves its `booking_status` to `RELEASED` and its `attendance_status` to `CANCELLED`, decrements `waitlisted_count`, and recomputes the `waitlist_position` of everyone behind it. No credits ever moved for a waitlisted reservation, so none are refunded, and no fee is charged. Cancelling a `BOOKED` reservation **outside** the late-cancel window — when the current clock is strictly before `starts_at` minus `late_cancel_window_hours` hours — is an early cancel: `booking_status` becomes `RELEASED`, `attendance_status` becomes `CANCELLED`, the `credits_charged` are refunded through a `CANCEL_REFUND` wallet line carrying a positive `delta`, `booked_count` is decremented, and the freed seat triggers the auto-promotion path below. No fee is charged. Cancelling a `BOOKED` reservation **inside** the late-cancel window — when the current clock is at or after `starts_at` minus `late_cancel_window_hours` hours and still strictly before `starts_at` — is a late cancel: `booking_status` becomes `RELEASED`, `attendance_status` becomes `LATE_CANCELLED`, the seat credit *is* still refunded through a `CANCEL_REFUND` wallet line, but a `LATE_CANCEL` `FeeCharge` is assessed (see the fee schedule below), `booked_count` is decremented, the auto-promotion path is triggered, and the member's strike count is incremented and their `standing` recomputed.

**Auto-promotion.** Whenever a `BOOKED` seat is released on a `FULL` session, the waitlist is walked to fill the freed seat(s) before capacity is re-evaluated, transitioning the session `FULL → OPEN` only if a seat remains free after promotion. The candidate set is the session's `WAITLISTED` reservations ordered by `created_at` ascending — never by `id`. The number of free seats is `seat_capacity` minus the post-release `booked_count`. For each free seat, the system takes the head of the waitlist (lowest `created_at`): if that member's funding membership is `ACTIVE` and its `credit_balance` is at least the template's `credit_cost`, the reservation is promoted — its `credit_cost` is debited through a `RESERVE_DEBIT` line, `credits_charged` is set, `booking_status` becomes `BOOKED`, `promoted_at` is stamped to the current clock, and `booked_count` is incremented. If instead the head cannot pay — an inactive membership or insufficient credit — that reservation is released (`booking_status` `RELEASED`, `attendance_status` `CANCELLED`), `waitlisted_count` is decremented, and promotion proceeds to the next in line. After the seats are filled or the waitlist drains, the `waitlist_position` of all remaining `WAITLISTED` reservations is recomputed in `created_at` order, and the session settles to `FULL` if `booked_count` again equals `seat_capacity`, otherwise `OPEN`. The promotion machinery updates the session's derived `booked_count`, `waitlisted_count`, and `status` in place but does not itself increment the session's `version` (the count and status changes folded into a reservation-cancellation request do not bump the session `version`); each promoted or released reservation does refresh its own `updated_at` and `version`. The same promotion machinery runs in bulk when a manager raises `seat_capacity` on a `FULL` session: the number of free seats becomes the new capacity minus `booked_count`, and multiple heads are promoted in order until the seats fill or the waitlist drains.

**Check-in.** A `StudioManager` (or the `NetworkAdmin`) checks a member in. Check-in is permitted only when the reservation's `booking_status` is `BOOKED` and its `attendance_status` is `PENDING`, the session is `OPEN` or `FULL`, and the current clock is at or after the session's `starts_at` minus 2 hours; a check-in attempted before that lead time is rejected with `ERR_INVALID_CANCEL_WINDOW`. A successful check-in sets `attendance_status` to `CHECKED_IN` while leaving `booking_status` at `BOOKED` — the seat stays held; only the attendance dimension advances.

**Session cancellation.** A `StudioManager` or `NetworkAdmin` may cancel a session that is `SCHEDULED`, `OPEN`, or `FULL`, moving it to the terminal `CANCELLED`. When the session was `SCHEDULED` no reservations exist yet and it is simply marked `CANCELLED`. From `OPEN` or `FULL` the cancellation cascades: every reservation whose `booking_status` is `BOOKED` or `WAITLISTED` is released — `booking_status` to `RELEASED`, `attendance_status` to `CANCELLED` — and for each released `BOOKED` reservation the `credits_charged` are refunded through a `CANCEL_REFUND` line. Because the studio initiated the cancellation, no late fee is charged regardless of timing. The session's `booked_count` and `waitlisted_count` are recomputed to zero.

**Session completion and no-shows.** An admin-only operational sweep advances every `OPEN` or `FULL` session whose `ends_at` has been reached or passed to the terminal `COMPLETED`. The cascade marks every reservation still `BOOKED` with `attendance_status` `PENDING` as `NO_SHOW`. For each new no-show a `NO_SHOW` `FeeCharge` is assessed (see below), the seat credit is *not* refunded, the member's strike count is incremented, and their `standing` is recomputed. Any reservations still `WAITLISTED` at completion are released (`booking_status` `RELEASED`, `attendance_status` `CANCELLED`) with no fee.

**Strikes and standing.** A member's `no_show_strikes` is the count of that member's `FeeCharge` rows whose `status` is `ASSESSED` and whose assessment instant falls within the trailing 30 days — each late cancel and each no-show assesses exactly one fee, so each contributes one strike while assessed. The trailing-30-day window is measured against the logical clock (§2.5): each fee records the value of the current clock at the moment it was assessed, and a fee counts toward the strike total when that recorded instant is at or after the current clock minus 30 days. (This logical-clock assessment instant, rather than the wall-clock `created_at`, is what the window compares; the two coincide when the clock has not been driven.) The member's `standing` is `RESTRICTED` when `no_show_strikes` is at least 3, and `GOOD` otherwise; thus 2 strikes still leaves a member `GOOD` while 3 makes them `RESTRICTED`, and a `RESTRICTED` member cannot create reservations.

### 3.8. Fees: Assessment and Waiver

Every late cancel and every no-show produces a `FeeCharge` linked to the offending `member_id` and `reservation_id`, with a `kind` of either `LATE_CANCEL` or `NO_SHOW`, an `amount_cents`, a `status` that begins `ASSESSED`, and a `credit_refunded` flag. The `credit_refunded` flag is true exactly when the seat credit was refunded as part of the event that produced the fee — true for a late cancel (the credit is returned), false for a no-show (the credit is kept).

The fee amount depends on the event kind and on the member's rolling strike count *before* this event is counted. The base is 1500 cents for a `LATE_CANCEL` and 2500 cents for a `NO_SHOW`. A surcharge is then added according to the strike count observed before incrementing for this event: when the prior strike count is at most 1, the surcharge is 0 cents; when the prior strike count is 2 or 3, the surcharge is 1000 cents; when the prior strike count is 4 or more, the surcharge is 2500 cents. The `amount_cents` is the base plus the surcharge. At the boundaries, a prior count of exactly 1 lands in the zero-surcharge tier, and a prior count of exactly 2 lands in the 1000-cent tier.

A `StudioManager` (or the `NetworkAdmin`) may waive an `ASSESSED` fee, moving it `ASSESSED → WAIVED`. Waiving zeroes the member's effective liability for that fee and reverses the strike the originating event added: the member's `no_show_strikes` is decremented by one, floored at zero, and their `standing` is recomputed. Because `no_show_strikes` is defined as the count of `ASSESSED` fees in the trailing window, flipping a fee to `WAIVED` naturally removes its strike contribution. `WAIVED` is terminal for a fee.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource — a studio, room, instructor, template, plan, member, membership, session, or reservation — return `201 Created`. Operations that modify an existing resource, including lifecycle transitions and the operational sweeps, return `200 OK`. Read operations return `200 OK`. A single-resource lifecycle transition returns the updated resource object in `data` (the payment-capture endpoint returns the activated `Membership`); the clock-setting endpoint (`/_clock/set_current_utc`) and the two batch operational sweeps (`/_ops/run_completion` and `/_ops/run_expiry`) carry no per-resource payload and return an empty object `{}` in `data`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/studios` | Create a studio in the network | NetworkAdmin |
| GET | `/studios/{id}` | Fetch a studio | NetworkAdmin, StudioManager, Member |
| POST | `/studios/{id}/close` | Close a studio | NetworkAdmin |
| POST | `/studios/{id}/rooms` | Add a room to a studio | NetworkAdmin, StudioManager |
| GET | `/studios/{id}/rooms` | List rooms under a studio | NetworkAdmin, StudioManager, Member |
| POST | `/rooms/{id}/retire` | Retire a room | NetworkAdmin, StudioManager |
| POST | `/instructors` | Create an instructor | NetworkAdmin |
| GET | `/instructors/{id}` | Fetch an instructor | NetworkAdmin, StudioManager, Member |
| GET | `/instructors` | List instructors; filter by `home_studio_id` | NetworkAdmin, StudioManager, Member |
| POST | `/instructors/{id}/deactivate` | Deactivate an instructor | NetworkAdmin |
| POST | `/class-templates` | Create a class template | NetworkAdmin |
| GET | `/class-templates/{id}` | Fetch a class template | NetworkAdmin, StudioManager, Member |
| POST | `/package-plans` | Create a package/membership plan | NetworkAdmin |
| GET | `/package-plans/{id}` | Fetch a package plan | NetworkAdmin, StudioManager, Member |
| POST | `/members` | Register a member | NetworkAdmin, Member |
| GET | `/members/{id}` | Fetch a member | NetworkAdmin, StudioManager, Member |
| GET | `/members` | List members; filter by `home_studio_id` | NetworkAdmin, StudioManager |
| POST | `/members/{id}/memberships` | Purchase a plan, creating a membership | NetworkAdmin, Member |
| GET | `/members/{id}/memberships` | List a member's memberships | NetworkAdmin, StudioManager, Member |
| GET | `/memberships/{id}` | Fetch a membership | NetworkAdmin, StudioManager, Member |
| GET | `/memberships` | List memberships; filter by `member_id` or `plan_id` | NetworkAdmin, StudioManager |
| GET | `/memberships/{id}/wallet-entries` | List wallet ledger entries for a membership | NetworkAdmin, StudioManager, Member |
| POST | `/memberships/{id}/freeze` | Freeze an active membership (OCC-guarded) | Member, NetworkAdmin |
| POST | `/memberships/{id}/unfreeze` | Unfreeze a frozen membership | Member, NetworkAdmin |
| POST | `/memberships/{id}/renew` | Renew a membership at/after cycle end | NetworkAdmin |
| POST | `/memberships/{id}/cancel` | Cancel a membership | Member, NetworkAdmin |
| GET | `/members/{id}/fees` | List fee charges for a member | NetworkAdmin, StudioManager, Member |
| POST | `/fees/{id}/waive` | Waive a fee charge | StudioManager, NetworkAdmin |
| POST | `/sessions` | Create a class session | StudioManager, NetworkAdmin |
| GET | `/sessions/{id}` | Fetch a session | NetworkAdmin, StudioManager, Member |
| GET | `/sessions` | List sessions; filter by `studio_id`, `room_id`, `instructor_id`, `template_id` | NetworkAdmin, StudioManager, Member |
| PATCH | `/sessions/{id}` | Update a session before completion | StudioManager, NetworkAdmin |
| POST | `/sessions/{id}/publish` | Publish a scheduled session | StudioManager, NetworkAdmin |
| POST | `/sessions/{id}/cancel` | Cancel a session | StudioManager, NetworkAdmin |
| POST | `/sessions/{id}/reservations` | Reserve a seat or join the waitlist (OCC-guarded) | Member, NetworkAdmin |
| GET | `/sessions/{id}/reservations` | List reservations on a session | NetworkAdmin, StudioManager, Member |
| GET | `/reservations/{id}` | Fetch a reservation | NetworkAdmin, StudioManager, Member |
| GET | `/reservations/{id}/wallet-entries` | List wallet entries tied to a reservation | NetworkAdmin, StudioManager, Member |
| GET | `/reservations` | List reservations; filter by `member_id` or `membership_id` | NetworkAdmin, StudioManager, Member |
| POST | `/reservations/{id}/cancel` | Cancel a reservation | Member, NetworkAdmin |
| POST | `/reservations/{id}/check_in` | Check a member in | StudioManager, NetworkAdmin |
| GET | `/fees/{id}` | Fetch a fee charge | NetworkAdmin, StudioManager, Member |
| GET | `/fees` | List fee charges; filter by `reservation_id` or `member_id` | NetworkAdmin, StudioManager, Member |
| POST | `/_clock/set_current_utc` | Set the server's current UTC clock | NetworkAdmin |
| POST | `/_payments/capture` | Simulate a payment capture for a membership | NetworkAdmin |
| POST | `/_ops/run_completion` | Complete sessions past their end and assess no-shows | NetworkAdmin |
| POST | `/_ops/run_expiry` | Expire memberships past their cycle end | NetworkAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_MEMBER_RESTRICTED` | 403 |
| `ERR_INTRO_ALREADY_USED` | 409 |
| `ERR_INSTRUCTOR_CONFLICT` | 409 |
| `ERR_ROOM_CONFLICT` | 409 |
| `ERR_CAPACITY_EXCEEDS_ROOM` | 409 |
| `ERR_MEMBERSHIP_INACTIVE` | 409 |
| `ERR_DUPLICATE_RESERVATION` | 409 |
| `ERR_WAITLIST_FULL` | 409 |
| `ERR_INSUFFICIENT_CREDITS` | 402 |
| `ERR_FREEZE_NOT_ALLOWED` | 409 |
| `ERR_STUDIO_CLOSED` | 409 |
| `ERR_SESSION_NOT_BOOKABLE` | 409 |
| `ERR_INVALID_CANCEL_WINDOW` | 409 |
