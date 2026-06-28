# Yoga & Pilates Studio API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for the Yoga & Pilates Studio API, the operational backbone of a Mindbody-style studio business. The system coordinates the scarce physical resources of a boutique studio — reformer stations and mat spots in named rooms, certified teachers, and the finite clock of a class schedule — against the commercial machinery of memberships, class packs, intro promotions, reservations, waitlists, late-cancellation and no-show penalties, and multi-day teacher-training cohorts.

The central challenge the API solves is allocation under contention. A single open seat in a popular class is a finite resource that two members may both believe is available; a reformer studio cannot host two overlapping sessions; a member who freezes a membership expects the lost days back when they thaw. The system resolves these tensions deterministically through a logical clock, optimistic concurrency control on contended parent resources, cascading state machines that keep capacity postures and credit ledgers consistent, and a periodic operations sweep that expires, renews, and promotes on demand. Because the studio runs promotions, surcharges for repeat offenders, and proration across mid-cycle price changes, monetary precision and evaluation order are treated as first-class contractual concerns throughout.

This specification is written for the engineer who will implement the service. It leads with the business meaning of each rule and follows with the precise mechanics so that the resulting API behaves identically to the studio's real-world policies.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting principal, and `X-User-Role` declares the operational capacity under which the request is made. If either header is absent or malformed, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly three roles, spelled precisely as follows: `StudioManager`, `Member`, and `Instructor`.

A `StudioManager` is an operator of the studio. The role configures rooms, teachers, the class schedule, and intro offers; activates entitlements; runs the periodic operations sweep; settles fees; and sets the logical clock. When `X-User-Role` is `StudioManager`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server may record it where a workflow calls for an operator stamp, but it never compares it to any entity's `id`; a `StudioManager` is therefore not subject to ownership checks.

A `Member` is a studio customer who acts on their own entitlements, reservations, and enrollments. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`; any ownership check on a resource that references a `Member` compares that resource's owning member foreign key (for example `member_id` on a `Reservation`, `Entitlement`, `FeeCharge`, or `Enrollment`) to `X-User-ID`. A member acting on a resource they do not own is rejected with `ERR_NOT_RESOURCE_OWNER`. On the unscoped collection list endpoints `GET /reservations`, `GET /enrollments`, and `GET /fee-charges`, a `Member` is not rejected for breadth but is instead silently scoped to only their own records (those whose `member_id` equals `X-User-ID`), whereas a `StudioManager` sees all records; the member-nested list endpoints (for example `GET /members/{id}/reservations`) instead apply the ownership check and reject a member reading another member's id with `ERR_NOT_RESOURCE_OWNER`.

An `Instructor` is a teacher with read-only visibility into their own taught sessions and workshops plus the studio catalog. When `X-User-Role` is `Instructor`, `X-User-ID` is the `id` of the acting `Teacher`. The `Instructor` role is granted only on read (catalog and resource-fetch) endpoints and is never the authorized role for any write, so in practice no implemented endpoint applies a teacher-foreign-key ownership comparison: an `Instructor` permitted to read an endpoint may read any resource it exposes (the full catalog and every session, workshop, room, and teacher), and `ERR_NOT_RESOURCE_OWNER` is raised in this system only for the member ownership checks described above, never against an `Instructor`'s `teacher_id` or `lead_teacher_id`.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits. It is request metadata drawn from real wall-clock time at the moment the response is built, independent of the logical clock of §2.4 (which governs only the persisted resource timestamps and every temporal comparison, not this envelope field).
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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Logical Clock

Every primary resource — `Member`, `Room`, `Teacher`, `IntroOffer`, `ClassSession`, `Entitlement`, `Reservation`, `Workshop`, and `Enrollment` — carries a system-managed `id`, formatted as a UUID with no type prefix, generated by the server at creation. Each also carries a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits, fixed at creation. With one exception noted below, every such resource also carries an `updated_at` timestamp (ISO 8601 UTC, three fractional digits, refreshed on every mutation) and an integer `version` that begins at the resource's first persisted value and increments by one on every mutation of that resource. The `version` field is the basis for optimistic concurrency control described in §2.7.

The `FeeCharge` resource is the single exception: it is effectively immutable in shape once raised and carries only `id` and `created_at`. A `FeeCharge` has no `updated_at` and no `version` field; its lifecycle (settling or waiving) is expressed through its `status` rather than a version counter.

The system operates on a **logical clock** rather than wall-clock time. On server startup the clock reads exactly `2026-01-01T00:00:00Z`, and before any clock-set call it remains at this default and never falls back to wall-clock time. A `StudioManager` may move the clock to any ISO 8601 UTC instant. Every temporal comparison in this specification — late-cancel windows, session start gating, freeze durations, cycle expiry — is evaluated against this logical clock. Moving the clock does not by itself run any scheduled work; the operations sweep described in §2.6 must be invoked explicitly.

### 2.5. Hierarchical Consistency and Cascading Reconciliation

Many operations in this system mutate more than one resource. A booking changes a reservation and may flip a session's capacity posture; completing a session settles every reservation on it and may suspend members and raise fees; cancelling a workshop refunds deposits across every confirmed enrollment. Whenever a workflow specifies such a cascade, each affected resource is mutated independently: its `updated_at` is refreshed and its `version` is incremented (except `FeeCharge`, which has neither). A `ClassSession`'s `booked_count` and `waitlisted_count`, and a `Workshop`'s `confirmed_seat_count`, are derived counts that the system keeps consistent with the reservations and enrollments attached to them; the corresponding capacity-posture state (for example `OPEN` versus `FULL`) is a function of those counts and is recomputed by the system whenever a child changes, without an explicit client request on the parent.

For requests whose path names a resource by id, the system validates existence left-to-right: each id in the path is resolved in order, and the first id that does not correspond to an existing resource produces `ERR_NOT_FOUND` before any later id or body rule is evaluated.

### 2.6. The Periodic Operations Sweep

A `StudioManager` triggers the periodic operations sweep, which performs all time-driven reconciliation at the current logical clock in a single pass. The sweep expires entitlements whose cycle has ended and that are not eligible to auto-renew; renews eligible auto-renewing memberships with rollover; resets no-show strike counts whose window has elapsed; promotes eligible waitlists; and resets the frozen-day accounting on any renewed cycle. Each entitlement the sweep actually transitions — that is, each one it expires or renews — has its `version` incremented by one; an entitlement the sweep merely examines but leaves unchanged (for example one whose cycle has not yet ended, or one that is not `ACTIVE`/`UNFROZEN`) is not touched and keeps its `version`. The precise conditions for each of these effects are given in §3 alongside the workflows they belong to. Setting the clock and running the sweep are deliberately separate actions: advancing the clock alone never triggers these effects.

### 2.7. Optimistic Concurrency Control on Contended Seats

Two operations in this system compete for a finite, last-of-its-kind resource and therefore carry an optimistic-concurrency guard keyed on the parent resource's `version`.

Booking a reservation competes for the last open seat on a `ClassSession`. A booking request must carry `expected_class_session_version`, the `version` of the target session that the client last observed. If another writer has advanced the session's `version` since then — for example by booking the final seat and moving the session from `OPEN` to `FULL` — the client's view of remaining capacity is stale, and the booking is rejected with `ERR_STALE_VERSION` (HTTP 412). This field is mandatory for booking; if it is absent the request is rejected with `ERR_VERSION_REQUIRED` (HTTP 422).

Confirming an enrollment competes for the last confirmable seat on a `Workshop`. A confirm request must carry `expected_workshop_version`, the `version` of the target workshop the client last read. If the workshop's `version` has advanced since then — for example because another applicant confirmed the final seat and moved the workshop from `OPEN` to `FULL` — the confirm is rejected with `ERR_STALE_VERSION` (HTTP 412). The field is mandatory; its absence yields `ERR_VERSION_REQUIRED` (HTTP 422). No other endpoint takes a version field except the room update described in §3, which carries `expected_room_version`; endpoints not described as OCC-guarded never require a version input.

### 2.8. Monetary Precision and Rounding

All monetary values in the system are integer cents. Wherever a calculation produces a fractional cent — a per-credit refund value, a surcharge percentage, a daily rate applied across days — the result is rounded half up to a whole cent. Where a calculation is composed of segments that must each be rounded (the renewal proration of §3), the rounding is applied per segment before the segments are summed, never to the running total; this rounding order is contractual and can differ from a sum-then-round approach by up to one cent. Seat counts, credit counts, and strike counts are always integers.

### 2.9. Account Standing and Strike Accounting

A `Member` carries an `account_status` of either `ACTIVE` or `SUSPENDED`, defaulting to `ACTIVE` at registration. A suspended account blocks new reservations and new enrollments. Standing is driven by the member's `no_show_strike_count`, a rolling count of no-shows within the current strike window that begins at 0. When that count reaches at least 3, the account moves to `SUSPENDED`. The member also tracks `outstanding_fee_cents`, the sum of the `amount_cents` of every `FeeCharge` for that member whose `status` is `UNPAID`, beginning at 0; this figure rises as fees are raised and falls as they are settled or waived. A member additionally tracks `lifetime_attended_count` (the number of their reservations that reached `ATTENDED`, starting at 0) and the boolean `is_new_student`, which begins `true` and gates intro-offer eligibility and fee grace as described in §3.

## 3. Business Logic & Workflows

### 3.1. Studio Configuration: Rooms, Teachers, and Intro Offers

Before any class can run, a `StudioManager` configures the studio's physical and staffing inventory. A **Room** is created with a `name`, a `room_type` of either `REFORMER` (equipment stations) or `MAT` (open floor), and a `station_capacity` — the hard physical ceiling of reformer stations or mat spots, which must be at least 1. A new room opens in `status` `OPEN`; a room may also be `CLOSED`, and a `CLOSED` room cannot host newly scheduled sessions or workshops. A manager may update a room's `name`, `station_capacity`, or `status`; because a room is a contended resource whose capacity governs published sessions, the update is OCC-guarded and must carry `expected_room_version` matching the room's current `version`, failing with `ERR_STALE_VERSION` (HTTP 412) on mismatch and `ERR_VERSION_REQUIRED` (HTTP 422) when omitted. Each successful update increments the room's `version`. Critically, if the update lowers `station_capacity` below the `booked_count` of one of the room's published sessions, the system cascades a demotion: the most-recently-booked over-capacity holders are moved from `BOOKED` to `WAITLISTED` until the session's booked count fits within the new effective capacity (see §3.5 for the demotion rule).

A **Teacher** is created with a `full_name` and an array of `certifications` — the disciplines the teacher is qualified to lead, such as `VINYASA` or `REFORMER`. A teacher opens in `status` `ACTIVE`; an `INACTIVE` teacher cannot be assigned to newly published sessions or workshops.

An **IntroOffer** is a published promotion template configured with a `name` (its label, e.g. "Two Weeks Unlimited"), a `price_cents` (at least 0) that a redeemed intro entitlement costs, a `credits_total` granted by the offer (where -1 denotes unlimited within the window, and the value must be at least -1), and a `window_days` validity length (at least 1) that sets how long a redeemed intro entitlement remains valid. These offer fields are descriptive metadata on the template: redemption (purchasing an `INTRO` entitlement, §3.3) only validates that the referenced offer exists and is `ACTIVE` — it does not copy the offer's `price_cents`, `credits_total`, or `window_days` onto the new entitlement; the entitlement's own `price_cents` and `credits_total` are taken from the purchase request body, and its validity window is the flat 30-day cycle of §3.3 rather than `window_days`. An offer opens in `status` `ACTIVE`; only an `ACTIVE` offer may be redeemed into a new `INTRO` entitlement, and a retired offer carries `status` `RETIRED`.

A `StudioManager` also registers each **Member** with an `email` (unique across members; registering with an `email` already held by another member is rejected with `ERR_INVALID_REQUEST` at HTTP 422), a `full_name`, and a `home_studio_state` (a two-letter state code such as CA; it is validated only as a present, non-empty string and its two-letter form is not otherwise enforced). A newly registered member starts with `is_new_student` true, `lifetime_attended_count` and `no_show_strike_count` and `outstanding_fee_cents` at 0, and `account_status` `ACTIVE`.

### 3.2. Scheduling and Publishing Class Sessions

A `StudioManager` drafts a **ClassSession** by supplying the hosting `room_id`, the assigned `teacher_id`, the `discipline` (one of `VINYASA`, `YIN`, `REFORMER`, or `MAT_PILATES`), a `start_utc` and `end_utc` (both ISO 8601 UTC, with `end_utc` required to be strictly after `start_utc`, else `ERR_END_BEFORE_START` at HTTP 422), a `published_capacity` of bookable spots (at least 1), and optionally a `waitlist_capacity` (the maximum number of reservations permitted in `WAITLISTED` state on the session, at least 0, defaulting to 5). A session may optionally carry a `recurrence_parent_id` pointing at another session it was cloned from; this is null for standalone sessions, and when supplied non-null it is resolved against existing sessions and a value naming no existing session is rejected with `ERR_NOT_FOUND`. At creation the session enters `status` `SCHEDULED`, and its derived `booked_count` and `waitlisted_count` both begin at 0. At creation and at publish, `published_capacity` must not exceed the room's `station_capacity`, otherwise the request is rejected with `ERR_CAPACITY_EXCEEDS_ROOM` (HTTP 422).

Publishing a scheduled session — advancing it from `SCHEDULED` to `OPEN` so that bookings are permitted — is the gate where the studio's scheduling invariants are enforced. Publication requires that the session is currently `SCHEDULED`, that the hosting room is `OPEN` (publishing into a closed room is rejected with `ERR_ROOM_CLOSED`), and that the assigned teacher is `ACTIVE`. The session's `discipline` must appear among the teacher's `certifications`, and the teacher must be active at publish time; a discipline the teacher is not certified for, or an inactive teacher, is rejected with `ERR_TEACHER_NOT_CERTIFIED` (HTTP 409). Publication also enforces two non-overlap rules. No other non-cancelled session may occupy the same room over an interval that overlaps the new session's interval, treated as half-open from `start_utc` up to but not including `end_utc`; a room conflict is rejected with `ERR_ROOM_DOUBLE_BOOKED` (HTTP 409). Likewise, the assigned teacher may not already be committed to another non-cancelled session or workshop whose interval overlaps; a teacher conflict is rejected with `ERR_TEACHER_DOUBLE_BOOKED` (HTTP 409). When all of these hold, the session becomes `OPEN` and accepts bookings.

A session's capacity posture then tracks demand automatically. When `booked_count` reaches `published_capacity` the system moves the session from `OPEN` to `FULL`, after which further booking attempts route to the waitlist. Conversely, when a booked seat frees on a full session and no waitlisted reservation is promoted to fill it — that is, when `booked_count` falls below `published_capacity` and `waitlisted_count` is 0 — the system returns the session from `FULL` to `OPEN`.

A manager starts a session, advancing it from `OPEN` or `FULL` to `IN_PROGRESS`, only once the logical clock has reached `start_utc`; a start attempted from any other status, or while the clock is still earlier than `start_utc`, is rejected with `ERR_INVALID_STATE` (HTTP 409). Starting opens the check-in window and causes new bookings to be rejected. A manager completes an `IN_PROGRESS` session, moving it to `COMPLETED`, which settles every reservation on it as described in §3.6. A manager may cancel a session that is `SCHEDULED`, `OPEN`, or `FULL`, moving it to `CANCELLED`; the cancellation cascade and its refund semantics are detailed in §3.6. `COMPLETED` and `CANCELLED` are terminal session states.

### 3.3. Entitlements: Purchase, Activation, and the Membership Lifecycle

An **Entitlement** is what a member spends to book a class. Every entitlement names its owning `member_id`, a `kind` of `MEMBERSHIP` (recurring, capped or unlimited per cycle), `CLASS_PACK` (a fixed credit bundle), or `INTRO` (a single-window new-student offer), a `price_cents` (at least 0), a `credits_total` (the bookable credits granted at purchase, where -1 is the sentinel for an unlimited membership and the value is at least -1), a `cycle_start_utc`, an `auto_renew` flag (default false), and a `rollover_cap` (the maximum credits that may carry into the next cycle on renewal, at least 0, default 0). An `INTRO` entitlement additionally references the redeemed offer template through `intro_offer_id`, which is required when the kind is `INTRO` and null otherwise.

At purchase the entitlement is created in `lifecycle_status` `PENDING` with `freeze_status` `UNFROZEN`, and its `cycle_end_utc` is computed as `cycle_start_utc` plus 30 days. The derived `credits_used` starts at 0; `credits_remaining` is `credits_total` minus `credits_used` for finite entitlements, or the unlimited sentinel -1 for an unlimited membership. The freeze-tracking fields `frozen_at_utc` (null when unfrozen) and `frozen_days_consumed` (0) round out the new record.

Purchasing an `INTRO` entitlement is gated by new-student eligibility, evaluated as a single business rule: the buying member must currently have `is_new_student` true, the referenced `intro_offer_id` must name an `ACTIVE` `IntroOffer`, and the member must not already hold an `INTRO` entitlement (at most one per member). Any violation is rejected with `ERR_INTRO_NOT_ELIGIBLE` (HTTP 409).

A `StudioManager` activates a `PENDING` entitlement, moving its `lifecycle_status` to `ACTIVE` so that it becomes chargeable; activation requires the entitlement to be `PENDING` and the logical clock to have reached `cycle_start_utc`, and an activation from a non-`PENDING` status or while the clock is still before `cycle_start_utc` is rejected with `ERR_INVALID_STATE` (HTTP 409). A member may cancel an `ACTIVE` entitlement, moving it to `CANCELLED` and forcing `auto_renew` to false; future reservations against a cancelled entitlement are rejected, but reservations already in `BOOKED` are unaffected. `EXPIRED` and `CANCELLED` are the terminal lifecycle states.

The membership lifecycle's time-driven transitions are realized only by the operations sweep. When the sweep finds the logical clock at or past an entitlement's `cycle_end_utc` while the entitlement is `ACTIVE` and `UNFROZEN`, and the entitlement is either not a membership or not set to auto-renew, the entitlement moves from `ACTIVE` to `EXPIRED` and its unused finite credits are forfeited. When instead the entitlement is an `ACTIVE`, `UNFROZEN` `MEMBERSHIP` with `auto_renew` true and the clock has reached `cycle_end_utc`, the sweep renews it in place (the lifecycle stays `ACTIVE`): the new `cycle_start_utc` becomes the old `cycle_end_utc`, the new `cycle_end_utc` becomes that new start plus 30 days, the rollover described below is applied, and `frozen_days_consumed` resets to 0 for the fresh cycle.

Rollover on renewal carries the lesser of the entitlement's `credits_remaining` and its `rollover_cap` into the new cycle. After carrying, `credits_used` is reset so that `credits_remaining` equals `credits_total` plus the carried amount; any credits beyond the cap are forfeited. The cash side of a renewal that straddles a price change is computed by the proration rule of §3.8.

### 3.4. Freezing and Thawing a Membership

A member may freeze an `ACTIVE`, `UNFROZEN` entitlement, which keeps `lifecycle_status` at `ACTIVE` but flips `freeze_status` to `FROZEN`. A freeze is permitted only while `frozen_days_consumed` is strictly below the per-cycle freeze ceiling of 21 days; a freeze attempted at or above that ceiling is rejected with `ERR_FREEZE_LIMIT_REACHED` (HTTP 409). On a successful freeze the system records `frozen_at_utc` as the current logical clock, and new reservations against the entitlement are rejected while it is `FROZEN`. Attempting to freeze an entitlement that is already `FROZEN` (or to thaw one that is already `UNFROZEN`) is rejected with `ERR_ENTITLEMENT_FROZEN` (HTTP 409).

Thawing reverses the freeze and compensates the member for lost days. On thaw of an `ACTIVE`, `FROZEN` entitlement, the system computes the frozen duration as the number of days elapsed between `frozen_at_utc` and the current clock, rounded up to a whole number of days, and then capped so that the new `frozen_days_consumed` does not exceed the 21-day per-cycle ceiling. That number of days is added to `cycle_end_utc`, the same number is added to `frozen_days_consumed`, `freeze_status` returns to `UNFROZEN`, and `frozen_at_utc` is cleared to null.

### 3.5. Booking, Waitlisting, and the Capacity Resolution

A member books a class by creating a **Reservation** that names the `member_id`, the `class_session_id`, the `entitlement_id` to charge, and the OCC guard `expected_class_session_version`. Every reservation carries a `status`, a `waitlist_position` (a 1-based queue position while `WAITLISTED`, null otherwise), a boolean `credit_charged`, and a system-stamped `booked_at_utc` recording the logical-clock instant the reservation entered `BOOKED` or `WAITLISTED`. The `booked_at_utc` stamp drives both waitlist ordering and the late-cancel window.

A booking runs an ordered gauntlet of checks before it is accepted. The acting member's `account_status` must be `ACTIVE`; a suspended member is rejected with `ERR_MEMBER_SUSPENDED` (HTTP 409). The charged entitlement must belong to the booking member, be lifecycle `ACTIVE`, and be `UNFROZEN`; otherwise the booking is rejected with `ERR_ENTITLEMENT_NOT_USABLE` (HTTP 409). For a finite entitlement, `credits_remaining` must be at least 1; an unlimited membership (whose `credits_total` is -1) is exempt from this check, but a finite entitlement with no credits left is rejected with `ERR_NO_CREDITS_REMAINING` (HTTP 409). Booking is only permitted before the session begins — the logical clock must be earlier than the session's `start_utc`, and the session must not be `IN_PROGRESS` or in a terminal state — otherwise the booking is rejected with `ERR_SESSION_NOT_BOOKABLE` (HTTP 409).

The seat outcome is decided by the **capacity resolution**, which reads three inputs: the session's `published_capacity`, the room's `station_capacity`, and the session's current `booked_count`. The effective capacity is the smaller of `published_capacity` and `station_capacity` — so that a room downgrade can clamp the bookable seats below what was advertised, while a session whose published capacity is within the room's ceiling simply uses its published capacity. Open seats are the effective capacity minus the current `booked_count`, floored at 0. If the session is `IN_PROGRESS` or terminal the booking is rejected with `ERR_SESSION_NOT_BOOKABLE`. Otherwise, if there is at least one open seat the reservation lands `BOOKED`; if there are no open seats but the session's `waitlisted_count` is below its `waitlist_capacity` the reservation lands `WAITLISTED`; and if the waitlist is also full the booking is rejected with `ERR_WAITLIST_FULL` (HTTP 409).

A reservation that lands `BOOKED` charges one credit: `credits_used` on the entitlement increases by one and `credit_charged` becomes true. A reservation that lands `WAITLISTED` is assigned `waitlist_position` equal to the session's prior `waitlisted_count` plus one, and it **holds** a credit in the same way — `credits_used` increases by one and `credit_charged` becomes true — so that a promotion later requires no further charge. A booking that fills the final open seat moves the session from `OPEN` to `FULL`. Each successful booking increments the session's `version` by one — whether the reservation lands `BOOKED` or `WAITLISTED`, since both are writes against the session — which is what makes a competing booking's `expected_class_session_version` go stale. (An `OPEN`-to-`FULL` flip on the booking that fills the last seat is folded into that same single increment, not an additional one.)

A separate, system-driven demotion path applies when a room downgrade (see §3.1) reduces a published session's effective capacity below its `booked_count`. The system demotes over-capacity holders from `BOOKED` to `WAITLISTED`, choosing the most-recently-booked holder first (latest `booked_at_utc`, breaking ties by earliest `created_at`), and places each demoted reservation at the head of the queue — `waitlist_position` 1 — with the existing waitlist shifted down behind it.

### 3.6. Cancellation, Check-In, Completion, and Waitlist Promotion

Cancelling a reservation is classified by the **late-cancel window**. The cutoff is the session's `start_utc` minus 12 hours. If the logical clock is strictly before that cutoff the cancel is EARLY; if the clock is at or after the cutoff it is LATE — the boundary instant itself counts as LATE, so a cancel exactly 12 hours before start is a late cancel and is charged a fee.

A `BOOKED` reservation cancelled in the early window moves to `CANCELLED_EARLY`: its credit is refunded (the entitlement's `credits_used` decreases by one and `credit_charged` becomes false), and the system auto-promotes the head of the session's waitlist into the freed seat. A `BOOKED` reservation cancelled inside the late window — permitted while the session is `OPEN` or `FULL`, and otherwise (for example when the session has already advanced to `IN_PROGRESS` or a terminal state) rejected with `ERR_INVALID_STATE` (HTTP 409) — moves to `CANCELLED_LATE`: a `FeeCharge` of type `LATE_CANCEL` is raised (see §3.7), the member's `outstanding_fee_cents` rises by the charged amount, the credit is forfeited rather than refunded, and the head of the waitlist is auto-promoted into the freed seat. A `WAITLISTED` reservation may be cancelled at any time, moving to `CANCELLED_EARLY`: its held credit is refunded (`credits_used` down by one, `credit_charged` false), and every waitlisted reservation behind it has its `waitlist_position` decremented by one to re-pack the queue.

Waitlist promotion is strictly by ascending `waitlist_position`. When a booked seat frees on a session and at least one seat is open (`booked_count` below `published_capacity`), the waitlisted reservation with the lowest `waitlist_position` is promoted from `WAITLISTED` to `BOOKED`: its `waitlist_position` is cleared to null, its already-held credit simply remains charged, and every remaining waitlisted reservation decrements its `waitlist_position` by one to close the gap. If a promotion fills the last open seat, the session returns to `FULL`.

A member checks in to an `IN_PROGRESS` session, moving their `BOOKED` reservation to `CHECKED_IN`; check-in requires the reservation to be `BOOKED` and the session to be `IN_PROGRESS`.

When a manager completes a session, the settlement cascade resolves every outstanding reservation on it, processing the session's reservations in ascending order of their creation (so that when a single member has multiple no-shows on the same session, the earlier-created no-show's fee is assessed against the lower prior strike count). Each reservation still `CHECKED_IN` becomes `ATTENDED` (its credit charge stands); the owning member's `lifetime_attended_count` increases by one, and once that count is at least 1 the member's `is_new_student` flips to false. Each reservation still `BOOKED` becomes `NO_SHOW`: a `FeeCharge` of type `NO_SHOW` is raised and the member's `outstanding_fee_cents` rises by its amount, the member's `no_show_strike_count` increases by one (and if that count reaches at least 3 the member's `account_status` becomes `SUSPENDED`), and the held credit is forfeited rather than refunded. Each reservation still `WAITLISTED` becomes `CANCELLED_EARLY`; no credit needs refunding because none of those reservations had escaped the hold-then-forfeit boundary — to be precise, their held credit is returned exactly as in a waitlisted early cancel.

Studio cancellation of a session follows a different, member-friendly cascade. When a manager cancels a `SCHEDULED`, `OPEN`, or `FULL` session, every reservation that is `BOOKED`, `WAITLISTED`, or `CHECKED_IN` moves to `CANCELLED_EARLY`, no late-cancel or no-show fee is assessed, and every such reservation that had `credit_charged` true has its credit returned to the owning entitlement (the entitlement's `credits_used` decreases by one) and its `credit_charged` flag set back to false. The cash valuation of that studio refund follows the final-refund variant in §3.7; that valuation is a conceptual accounting figure only — the sole persisted effect of the studio refund is the one-credit restoration to the entitlement, and no cash amount is written to any member, entitlement, or reservation field.

### 3.7. Fees, Surcharges, and Credit Refund Valuation

A **FeeCharge** records a penalty against a member. It names the charged `member_id`, the triggering `reservation_id`, a `fee_type` of `LATE_CANCEL` or `NO_SHOW`, an `amount_cents`, and a `status` that begins `UNPAID` and may become `PAID` or `WAIVED`. A `StudioManager` settles a fee by supplying a `resolution`, moving the charge from `UNPAID` to `PAID` or `WAIVED` and reducing the member's `outstanding_fee_cents` by the charge amount; settling a charge that is already `PAID` or `WAIVED` is rejected with `ERR_FEE_ALREADY_RESOLVED` (HTTP 409).

The **fee amount** is computed at the moment the fee is raised. The base is 2500 cents for a no-show and 1500 cents for a late cancel. A repeat-offender surcharge is keyed on the member's `no_show_strike_count` read at the instant *before* this event would increment it: if that prior count is at least 4 the surcharge is 50 percent of the base; otherwise if it is at least 2 the surcharge is 25 percent of the base; otherwise there is no surcharge. The fee amount is the base plus the surcharge, rounded half up to whole cents. Two grace and accounting subtleties govern the result. First, a member still flagged `is_new_student` pays nothing — the assessed `amount_cents` is 0 regardless of base or surcharge. Second, the strike tier always reads `no_show_strike_count`, even for a late cancel, even though a late cancel does not itself increment that count; only the no-show path increments `no_show_strike_count`, and it does so *after* the amount has been read.

The **credit refund valuation** has two deliberately different forms for the same cancelled reservation, depending on who initiated the cancellation. When a member early-cancels their own reservation (a `BOOKED` or `WAITLISTED` reservation moving to `CANCELLED_EARLY`), the refund is provisional: exactly one whole credit is returned to the entitlement (its `credits_used` drops by one) and no cash moves. When the studio cancels the session and the cascade refunds affected reservations, the refund is final and is valued in cash so that the member's pack value is conserved: for a finite pack the per-credit cash value is the entitlement's `price_cents` divided by its `credits_total`, rounded half up to whole cents, and that amount is returned per affected reservation; for an unlimited membership (whose `credits_total` is -1) credits are not cash-valued, so the cash refund is 0.

### 3.8. Membership Renewal Proration

When the operations sweep renews an auto-renewing membership and the renewing cycle straddles a mid-cycle price change, the cash charge for the new cycle is computed per price segment and then summed. The renewing cycle is divided into ordered segments, each with its own `segment_days` and `monthly_rate_cents`. For each segment the daily rate is that segment's `monthly_rate_cents` divided by 30, the segment charge is the segment's day count multiplied by that daily rate, rounded half up to whole cents, and the renewal total is the integer sum of the per-segment charges. This round-per-segment-then-sum order is pinned: a single-segment renewal (no price change in the cycle) is simply one segment spanning the full 30-day cycle, whereas a split renewal (a price change falling strictly inside the cycle) yields two independently rounded segment charges whose sum can differ from a sum-then-round computation by up to one cent. Any rollover credit value is applied as a credit only after the cash total has been computed; the net charge for the cycle is the renewal total.

### 3.9. Workshops, Teacher-Training, and Enrollment

A **Workshop** — a single-event `WORKSHOP` or a multi-day `TEACHER_TRAINING` cohort, set by its `kind` — is created by a `StudioManager` with the hosting `room_id`, the `lead_teacher_id`, a `title`, a `start_utc` and `end_utc` (UTC; `end_utc` must be strictly after `start_utc`, else `ERR_END_BEFORE_START` at HTTP 422), a `seat_capacity` of total enrollable seats (at least 1, and at publish not exceeding the room's `station_capacity`, else `ERR_CAPACITY_EXCEEDS_ROOM`), a non-refundable `deposit_cents` captured at confirmation (at least 0), and a full `price_cents` (at least 0). A workshop opens in `status` `DRAFT` with a derived `confirmed_seat_count` of 0.

Publishing a workshop moves it from `DRAFT` to `OPEN` and accepts enrollments. Publication requires the workshop to be `DRAFT`, the room to be `OPEN` (else `ERR_ROOM_CLOSED`), and the lead teacher to be `ACTIVE`. Workshop publication enforces a stricter room non-overlap than sessions do: the workshop's interval must clear every other non-cancelled workshop **and** every non-cancelled class session in the same room by a buffer of 30 minutes on each side; a violation is rejected with `ERR_ROOM_DOUBLE_BOOKED` (HTTP 409). The lead teacher must likewise not be committed to another non-cancelled session or workshop overlapping the workshop's interval, else `ERR_TEACHER_DOUBLE_BOOKED` (HTTP 409).

A workshop's posture tracks confirmations: when `confirmed_seat_count` reaches `seat_capacity` the workshop moves from `OPEN` to `FULL`, after which a newly confirmed applicant is routed to the waitlist; when a confirmed seat frees and no waitlisted enrollment can fill it the workshop returns from `FULL` to `OPEN`. A manager closes an `OPEN` or `FULL` workshop once the logical clock has reached `end_utc`, moving it to `CLOSED` and withdrawing any lingering `APPLIED` or `WAITLISTED` enrollments (each such enrollment moves to status `WITHDRAWN`); a close attempted from any other status, or while the clock is still before `end_utc`, is rejected with `ERR_INVALID_STATE` (HTTP 409). A manager may cancel a `DRAFT`, `OPEN`, or `FULL` workshop, moving it to `CANCELLED`. `CLOSED` and `CANCELLED` are terminal.

An **Enrollment** names the enrolling `member_id` and the `workshop_id`. It carries a `status` beginning `APPLIED`, a `deposit_paid_cents` (0 until captured), and a `balance_due_cents` (0 until confirmed). A member applies to a workshop, creating the enrollment in `APPLIED`; a suspended member is blocked from applying with `ERR_MEMBER_SUSPENDED`.

Confirming an `APPLIED` enrollment is OCC-guarded on the workshop and must carry `expected_workshop_version` (see §2.7). Confirmation requires the enrollment to be `APPLIED`. When the workshop is `OPEN` with a confirmable seat (`confirmed_seat_count` below `seat_capacity`), confirmation captures the deposit — `deposit_paid_cents` is set to the workshop's `deposit_cents` and `balance_due_cents` becomes the workshop's `price_cents` minus that deposit — the workshop's `confirmed_seat_count` rises by one, and the enrollment moves to `CONFIRMED`; if that confirmation fills the last seat the workshop moves to `FULL`. When instead the workshop is already `FULL` — or is `OPEN` yet has no confirmable seat remaining (`confirmed_seat_count` already at `seat_capacity`) — the confirm routes the enrollment to `WAITLISTED` with no deposit captured (`deposit_paid_cents` and `balance_due_cents` stay at 0). Each confirm increments the workshop's `version`, including a confirm that lands on the waitlist.

A member withdraws an enrollment. Withdrawing an `APPLIED` or a `WAITLISTED` enrollment simply moves it to `WITHDRAWN` with no deposit involved. Withdrawing a `CONFIRMED` enrollment moves it to `WITHDRAWN`, does **not** refund the captured deposit (a member-initiated withdrawal forfeits it) and sets `balance_due_cents` to 0; the workshop's `confirmed_seat_count` drops by one, and the system auto-promotes the earliest-created `WAITLISTED` enrollment to `CONFIRMED`, capturing that enrollment's deposit and recomputing its `balance_due_cents`. If no waitlisted enrollment is available to promote and the workshop was `FULL`, it returns to `OPEN`. A waitlisted enrollment is also promoted to `CONFIRMED` by the system whenever a confirmed seat frees and a seat is confirmable, choosing the earliest-created waitlisted enrollment, capturing its deposit, recomputing `balance_due_cents`, and raising `confirmed_seat_count` by one.

Cancelling a workshop drives a refund cascade distinct from a member withdrawal. Every `CONFIRMED` enrollment moves to `CANCELLED_BY_STUDIO` and its `deposit_paid_cents` is refunded to the member (the member's `outstanding_fee_cents` is unaffected by this refund); the studio refund is recorded on the enrollment by zeroing both `deposit_paid_cents` and `balance_due_cents` to 0, in contrast to a member-initiated `CONFIRMED` withdrawal, which forfeits the deposit and therefore leaves `deposit_paid_cents` at its captured value. Every `APPLIED` or `WAITLISTED` enrollment moves to `CANCELLED_BY_STUDIO` with no deposit to return. `WITHDRAWN` and `CANCELLED_BY_STUDIO` are terminal enrollment states.

### 3.10. Validation Ordering and Operational Reads

Across every write, the validations are evaluated in a fixed priority order so that the most fundamental failure is reported first. Authentication of the headers comes first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_UNAUTHORIZED`), then existence of every referenced id resolved left-to-right (`ERR_NOT_FOUND`), then resource ownership for member-scoped writes such as reservation cancel and check-in, entitlement freeze, thaw, and cancel, and enrollment confirm and withdraw (`ERR_NOT_RESOURCE_OWNER`); there are no instructor-scoped writes, so this ownership step is only ever a member check. After those come the state-validity check for the requested transition (`ERR_INVALID_STATE`), then the optimistic-concurrency check on `expected_class_session_version` for booking and `expected_workshop_version` for enrollment confirmation (`ERR_STALE_VERSION`), then member standing (`ERR_MEMBER_SUSPENDED` on booking and enrollment), then entitlement usability (`ERR_ENTITLEMENT_NOT_USABLE` on booking). The business-constraint checks follow in order: intro eligibility (`ERR_INTRO_NOT_ELIGIBLE`), teacher certification at publish (`ERR_TEACHER_NOT_CERTIFIED`), room overlap at publish (`ERR_ROOM_DOUBLE_BOOKED`), teacher overlap at publish (`ERR_TEACHER_DOUBLE_BOOKED`), capacity versus room (`ERR_CAPACITY_EXCEEDS_ROOM`), finite-credit availability (`ERR_NO_CREDITS_REMAINING`), waitlist room (`ERR_WAITLIST_FULL`), the freeze ceiling (`ERR_FREEZE_LIMIT_REACHED`), and bookability of the session by clock and state (`ERR_SESSION_NOT_BOOKABLE`). Finally, generic request-body validation — required fields present and field types and enum values well-formed — is the last check, reported as `ERR_INVALID_REQUEST` (HTTP 422). The clock-set operation is the sole endpoint exempt from the general authentication ordering note in the sense that it still requires a `StudioManager`, but it is otherwise subject to the same authorization rule as every other write.

A `StudioManager` sets the logical clock by supplying a target instant `to_iso8601`; this advances the clock and runs no operations sweep. Beyond the workflow reads named above, the API exposes read endpoints to fetch and list each resource and to traverse the natural relationships — a member's reservations, entitlements, fee charges, and enrollments; a room's sessions and workshops; a teacher's sessions and workshops; an offer's redeemed intro entitlements; a session's reservations; and a workshop's enrollments — each filterable and paginated as described in §2.3. The operations sweep additionally resets a member's `no_show_strike_count` to 0 when that member's oldest no-show is older than the 90-day strike window. The oldest no-show is identified by the earliest `booked_at_utc` among that member's reservations currently in `NO_SHOW` status, and the window is exceeded only when the elapsed time from that instant to the current logical clock is strictly greater than 90 days; a member with no `NO_SHOW` reservations or a non-positive strike count is skipped.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including state transitions and settlements — return a `200 OK` status code. List and fetch reads return `200 OK`. The clock-set and operations-sweep endpoints return `200 OK` with an empty data object.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/members` | Register a member | StudioManager |
| GET | `/members/{id}` | Fetch a member | StudioManager, Member |
| GET | `/members` | List members | StudioManager |
| GET | `/members/{id}/reservations` | List a member's reservations | StudioManager, Member |
| GET | `/members/{id}/entitlements` | List a member's entitlements | StudioManager, Member |
| GET | `/members/{id}/fee-charges` | List a member's fee charges | StudioManager, Member |
| GET | `/members/{id}/enrollments` | List a member's enrollments | StudioManager, Member |
| POST | `/rooms` | Create a room | StudioManager |
| GET | `/rooms/{id}` | Fetch a room | StudioManager, Member, Instructor |
| PATCH | `/rooms/{id}` | Update a room (may demote over-capacity bookings) | StudioManager |
| GET | `/rooms/{id}/class-sessions` | List a room's sessions | StudioManager, Member, Instructor |
| GET | `/rooms/{id}/workshops` | List a room's workshops | StudioManager, Member, Instructor |
| POST | `/teachers` | Create a teacher | StudioManager |
| GET | `/teachers/{id}` | Fetch a teacher | StudioManager, Member, Instructor |
| GET | `/teachers/{id}/class-sessions` | List a teacher's sessions | StudioManager, Member, Instructor |
| GET | `/teachers/{id}/workshops` | List a teacher's workshops | StudioManager, Member, Instructor |
| POST | `/intro-offers` | Create an intro offer | StudioManager |
| GET | `/intro-offers/{id}` | Fetch an intro offer | StudioManager, Member |
| GET | `/intro-offers` | List intro offers | StudioManager, Member |
| GET | `/intro-offers/{id}/entitlements` | List entitlements redeemed from an offer | StudioManager, Member |
| POST | `/class-sessions` | Create a class session | StudioManager |
| GET | `/class-sessions/{id}` | Fetch a session | StudioManager, Member, Instructor |
| GET | `/class-sessions` | List sessions | StudioManager, Member, Instructor |
| POST | `/class-sessions/{id}/publish` | Publish a session to OPEN | StudioManager |
| POST | `/class-sessions/{id}/start` | Start a session (IN_PROGRESS) | StudioManager |
| POST | `/class-sessions/{id}/complete` | Complete a session; settle reservations | StudioManager |
| POST | `/class-sessions/{id}/cancel` | Cancel a session; refund cascade | StudioManager |
| GET | `/class-sessions/{id}/reservations` | List a session's reservations | StudioManager, Member, Instructor |
| POST | `/entitlements` | Purchase an entitlement | StudioManager, Member |
| GET | `/entitlements/{id}` | Fetch an entitlement | StudioManager, Member |
| POST | `/entitlements/{id}/activate` | Activate a PENDING entitlement | StudioManager |
| POST | `/entitlements/{id}/freeze` | Freeze an ACTIVE entitlement | Member, StudioManager |
| POST | `/entitlements/{id}/thaw` | Thaw a FROZEN entitlement | Member, StudioManager |
| POST | `/entitlements/{id}/cancel` | Cancel an ACTIVE entitlement | Member, StudioManager |
| POST | `/reservations` | Book a session (OCC on session) | Member, StudioManager |
| GET | `/reservations/{id}` | Fetch a reservation | StudioManager, Member |
| GET | `/reservations` | List reservations | StudioManager, Member |
| POST | `/reservations/{id}/check-in` | Check in to an IN_PROGRESS session | Member, StudioManager |
| POST | `/reservations/{id}/cancel` | Cancel a reservation (EARLY/LATE) | Member, StudioManager |
| POST | `/workshops` | Create a workshop | StudioManager |
| GET | `/workshops/{id}` | Fetch a workshop | StudioManager, Member, Instructor |
| GET | `/workshops` | List workshops | StudioManager, Member, Instructor |
| POST | `/workshops/{id}/publish` | Publish a workshop to OPEN | StudioManager |
| POST | `/workshops/{id}/close` | Close a workshop after end | StudioManager |
| POST | `/workshops/{id}/cancel` | Cancel a workshop; refund deposits | StudioManager |
| GET | `/workshops/{id}/enrollments` | List a workshop's enrollments | StudioManager, Member, Instructor |
| POST | `/enrollments` | Apply to a workshop | Member, StudioManager |
| GET | `/enrollments/{id}` | Fetch an enrollment | StudioManager, Member |
| POST | `/enrollments/{id}/confirm` | Confirm an enrollment (OCC on workshop) | Member, StudioManager |
| POST | `/enrollments/{id}/withdraw` | Withdraw an enrollment | Member, StudioManager |
| GET | `/fee-charges/{id}` | Fetch a fee charge | StudioManager, Member |
| GET | `/fee-charges` | List fee charges | StudioManager, Member |
| POST | `/fee-charges/{id}/settle` | Settle or waive a fee charge | StudioManager |
| POST | `/_clock/set_current_utc` | Set the logical clock | StudioManager |
| POST | `/_ops/run` | Run the periodic operations sweep | StudioManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_MEMBER_SUSPENDED` | 409 |
| `ERR_ENTITLEMENT_NOT_USABLE` | 409 |
| `ERR_NO_CREDITS_REMAINING` | 409 |
| `ERR_INTRO_NOT_ELIGIBLE` | 409 |
| `ERR_TEACHER_NOT_CERTIFIED` | 409 |
| `ERR_ROOM_DOUBLE_BOOKED` | 409 |
| `ERR_TEACHER_DOUBLE_BOOKED` | 409 |
| `ERR_CAPACITY_EXCEEDS_ROOM` | 422 |
| `ERR_WAITLIST_FULL` | 409 |
| `ERR_SESSION_NOT_BOOKABLE` | 409 |
| `ERR_FREEZE_LIMIT_REACHED` | 409 |
| `ERR_ROOM_CLOSED` | 409 |
| `ERR_ENTITLEMENT_FROZEN` | 409 |
| `ERR_END_BEFORE_START` | 422 |
| `ERR_FEE_ALREADY_RESOLVED` | 409 |
| `ERR_VERSION_REQUIRED` | 422 |
