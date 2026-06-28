# Scuba Dive Certification API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for the Scuba Dive Certification API, the operational backbone of a full-service dive shop that trains, certifies, equips, and dispatches recreational divers. The shop runs the complete PADI-style learning journey — entry-level Open Water and Advanced courses delivered through a mix of e-learning, confined-water pool work, and open-water training dives — and it must do so under a layered web of safety, scheduling, and financial constraints that no manual process can hold together reliably. A single diver may sign a medical and liability waiver, enroll in a course, attend a sequence of supervised sessions taught under strict instructor-to-student ratios, become eligible for and ultimately receive a certification card, rent gear against a refundable deposit, have tanks filled with air or nitrox, book a charter dive trip on one of the shop's boats, and bring equipment in for annual or five-yearly servicing — every one of which touches a different rule set, yet all of which must agree on the same diver record.

The system exists to make those interactions consistent and auditable. Certification eligibility must reflect genuine training completion rather than wishful bookkeeping; instructor ratios and boat capacities must never be quietly exceeded; deposits debited at gear checkout must reconcile exactly when the gear comes back; and a diver's medical clearance and certification level must gate the activities they are allowed to perform. Because timing pervades nearly every rule — waiver expiry, session windows, rental billing, trip turnaround buffers, and service due-dates all depend on "now" — the server maintains a single logical clock that all deadline, expiry, and window comparisons read from, rather than relying on wall-clock time. The remainder of this document defines the global contracts that every endpoint honors (Section 2) and the domain workflows that give those contracts meaning (Section 3), followed by the endpoint and error reference tables (Sections 4 and 5).

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope formats, and cross-cutting principles that apply uniformly across the entire API. Where a rule below references a numeric threshold or a state name, the value stated here is authoritative.

### 2.1. User and Role-Based Access Control

Every request to the API — with the single exception of the logical-clock control endpoint described in Section 3 — must be authenticated through two mandatory HTTP headers. The `X-User-ID` header identifies the acting principal, and the `X-User-Role` header declares the role under which the request is made. If either header is missing, or if `X-User-Role` does not name a role the system recognizes, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes exactly three roles, spelled precisely as follows: `ShopAdmin`, `Instructor`, and `Diver`. When a request carries valid headers but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The three roles partition the system's responsibilities with little overlap. A `ShopAdmin` is the dive-shop operator: it manages the shop's catalog and inventory (courses, sessions, boats, dive trips, instructors), issues certifications, and runs the rental, fill, and gear-service desks. When `X-User-Role` is `ShopAdmin`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may accept and record it but never compares it to any entity's `id`, and a `ShopAdmin` is never subject to ownership restrictions. An `Instructor`, by contrast, is entity-backed: when `X-User-Role` is `Instructor`, `X-User-ID` is the `id` of the acting `Instructor`, and ownership checks compare a resource's instructor reference to `X-User-ID` — an `Instructor` may complete a session or record attendance only when that session's `primary_instructor_id` equals `X-User-ID`. A `Diver` is likewise entity-backed: when `X-User-Role` is `Diver`, `X-User-ID` is the `id` of the acting `Diver`, and ownership checks compare a resource's `diver_id` (directly, or through the enrollment a booking belongs to) to `X-User-ID` — a `Diver` may act only on its own enrollments, bookings, rentals, waivers, fills, and gear-service orders. When an entity-backed actor attempts to mutate a resource it does not own, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

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

All endpoints that return collections of resources are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it is constrained to a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip from the front of the result set; when omitted it defaults to 0.

Unless an endpoint states otherwise, every list is returned sorted by the resource's creation timestamp in ascending order, so the earliest-created resource appears first. The `meta` object of every list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the number of resources matching the query before pagination is applied and `has_more` is true exactly when items remain beyond the current page.

### 2.4. Common Resource Properties and the Logical Clock

Most resources in the system carry a common set of system-managed fields. Each such resource has an `id` (a server-minted UUID with no type prefix), a `created_at` timestamp recording when it was first created (ISO 8601 UTC with three fractional digits), an `updated_at` timestamp recording when it was last modified (same format), and a `version` integer that begins at its initial value on creation and increments by one on every mutation of the resource. The `version` field is the basis for the optimistic concurrency control described in Section 2.7.

Two resource types are deliberate exceptions: a `CertificationCard` and a `Waiver` are immutable once created and therefore carry only `id` and `created_at` — they have neither an `updated_at` field nor a `version` field. This reflects that a card, once issued, and a waiver, once signed, are permanent records rather than mutable working state.

Because the entire domain is time-sensitive, the server keeps a single **logical clock** that is the sole source of "now" for every deadline, expiry, window-overlap, and elapsed-time computation in this document. On startup the clock reads exactly `2026-01-01T00:00:00Z`, and until it is explicitly set it remains at that value and never falls back to the host's wall-clock time. The clock can be advanced or rewound through an administrative test-driving capability that accepts a single `to_iso8601` instant and sets the clock to it. Timestamps that the system stamps from this clock — a waiver's `signed_at`, a card's `issued_at`, a rental's `checkout_at` and `actual_return_at`, a gear order's `serviced_at` — all read the logical clock at the moment of the operation.

### 2.5. Hierarchical Consistency, Cascades, and Conserved Quantities

Many operations in this domain mutate more than one resource. Whenever a write changes a resource, that resource's `updated_at` is refreshed and its `version` is incremented; this is equally true of derived counters that the system maintains on a resource's behalf and of every lifecycle `status` field that a state transition advances. Several integer fields are **conserved quantities** — counters or ledgers that the system recomputes so they always equal a defined aggregate rather than being set directly by clients.

A `Session` tracks `confirmed_seats`, defined as the count of that session's session bookings whose status is `BOOKED`; every booking creation, cancellation, no-show, or attendance change that affects this set keeps the counter in step. A `DiveTrip` tracks `confirmed_divers`, the count of its trip bookings whose status is `CONFIRMED`. An `Instructor` tracks `active_session_count`, the count of sessions where that instructor is the `primary_instructor_id` and whose status is `SCHEDULED`. A `Diver` tracks `deposit_on_hold_cents`, defined as the sum of `deposit_cents` across that diver's rental agreements whose status is `ACTIVE`; this ledger is recomputed on every rental checkout, check-in, and void so that money debited at checkout is restored exactly when the gear is returned or the rental is voided. An `Enrollment` tracks `pool_sessions_attended` and `open_water_sessions_attended` (counts of distinct attended pool and open-water sessions respectively) and a derived `completion_pct`. When a cascading operation reverses one of these aggregates — for example, a session cancellation that releases booked seats — the affected counter is recomputed rather than left stale. The precise cascade chains are described where the triggering workflows are defined in Section 3.

### 2.6. Precision and Rounding

All monetary amounts in the system are expressed and stored as integer cents; there are no fractional-cent values in any stored field or response body. Where a calculation produces a non-integer intermediate value — for example, applying a percentage discount or a fractional late multiplier — the result is rounded to a whole number of cents using the round-half-up convention (a value exactly halfway between two integers rounds up to the larger). Each calculation in Section 3 states the exact point at which rounding is applied; unless stated otherwise, rounding happens once, on the final value, and intermediate line items are summed at full integer precision before any rounding step. Counts of whole billed days are computed by rounding any partial day up to the next whole day, with a floor of one day.

### 2.7. Optimistic Concurrency Control

Two write operations require the client to prove it is acting on a current view of a shared parent resource, guarding against a client overwriting state it has not observed. Creating a session booking targets a parent `Session`, and the request must carry `expected_session_version` holding the client's last observed `version` of that session. Because each accepted booking increments the session's `version` (its `confirmed_seats` changes), a request whose `expected_session_version` does not equal the session's current `version` — meaning another writer has advanced the session since the client read it — is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the booking from over-filling a ratio cap the client cannot see. Symmetrically, creating a trip booking targets a parent `DiveTrip`, and the request must carry `expected_trip_version` holding the client's last observed `version` of that trip; each accepted trip booking increments the trip's `version` (its `confirmed_divers` changes), so a request whose `expected_trip_version` does not equal the trip's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). These two create operations are the only endpoints that take a version field; no other endpoint accepts or checks an expected-version input.

### 2.8. Medical, Waiver, and Certification Gates

The shop will not let a diver into the water — or into a seat — without current medical and liability clearance. A diver's clearance is summarized by `medical_status`, a derived value of `UNKNOWN`, `CLEAR`, or `RESTRICTED`. It is computed from the diver's latest `Waiver`: if the diver has no active waiver, the status is `UNKNOWN`; if the latest active waiver was signed with `medical_flagged` false, the status is `CLEAR`; and if that waiver was signed with `medical_flagged` true (a flagged questionnaire requiring physician sign-off), the status is `RESTRICTED`. A waiver is **active** when the current logical clock is strictly before its `expires_at` and it is the diver's most recently signed waiver.

Three activities are gated on this clearance: booking a session seat, booking a trip, and a diver becoming certification-eligible. In each of these, the diver must have an active waiver and a `medical_status` that is not `RESTRICTED` (equivalently, `CLEAR`); if not, the operation is rejected with `ERR_WAIVER_REQUIRED` (HTTP 422). Certification prerequisites form a second safety gate: booking a trip requires the diver's `cert_level` to be at least the trip's `min_cert_level`, and requesting a nitrox fill requires the diver to be nitrox-certified; a violation of either is rejected with `ERR_CERT_PREREQUISITE_NOT_MET` (HTTP 422). The diver's own certification fields — `cert_level` (one of `NONE`, `OPEN_WATER`, `ADVANCED`) and the `nitrox_certified` boolean — are never set directly by clients; they are upgraded only as a consequence of certification-card issuance, as described in Section 3.

### 2.9. Validation Ordering

When a single request could fail several checks, the system evaluates them in a fixed priority order and returns the error for the first check that fails, so that an earlier, more fundamental failure is never masked by a later one. The order is: first, authentication — both headers present and `X-User-Role` a known role (`ERR_UNAUTHENTICATED`); second, role authorization — the acting role is permitted for the operation (`ERR_FORBIDDEN`); third, existence — every referenced resource, whether named in the URL path or in the request body, resolves to a real resource, with path and body references checked left to right (`ERR_NOT_FOUND`); fourth, request well-formedness — required fields are present, enum values are in range, and numeric fields satisfy their declared constraints (`ERR_INVALID_REQUEST`); fifth, ownership — an entity-backed actor is acting on a resource it owns (`ERR_FORBIDDEN`); sixth, state — the target resource is in a state from which the requested transition is legal (`ERR_INVALID_STATE`); and seventh, optimistic-concurrency — when an expected-parent-version field is supplied, it matches the parent's current `version` (`ERR_STALE_VERSION`). Domain-specific business rules — the medical/waiver gate, the certification prerequisite, instructor and boat scheduling conflicts, seat capacity, and duplicate-booking checks — are evaluated after these seven foundational layers.

### 2.10. Nested Reference Resolution

Several operations name a parent resource through a path segment and additionally reference other resources in the request body. All such references are resolved before any business rule runs, and they are checked in left-to-right order — a path identifier before a body identifier, and body identifiers in the order they appear in the workflow. The first reference that does not resolve to an existing resource causes the request to be rejected with `ERR_NOT_FOUND` (HTTP 404) for that reference, before the system attempts to validate anything that depends on it.

## 3. Business Logic & Workflows

### 3.1. Onboarding a Diver: Registration, Waivers, and Medical Clearance

A diver enters the system through registration, supplying a `full_name` and a contact `email` (unique per diver). A newly registered diver starts with `cert_level` equal to `NONE`, `nitrox_certified` false, `medical_status` `UNKNOWN`, and `deposit_on_hold_cents` zero — none of which the registrant supplies; they are all system-initialized. A `Diver` may self-register, and a `ShopAdmin` may register a diver on a walk-in's behalf.

Before a diver can train or dive, a medical and liability waiver must be on file. Signing a waiver records the `diver_id` of the signer and a `medical_flagged` boolean indicating whether the medical questionnaire surfaced a condition requiring physician sign-off. The server stamps `signed_at` from the logical clock at the moment of signing and computes `expires_at` as `signed_at` plus exactly 365 days. Signing a waiver immediately recomputes the diver's `medical_status` from this newly latest waiver: `CLEAR` when `medical_flagged` is false, `RESTRICTED` when it is true. Because medical status always derives from the *latest* waiver, a diver who re-signs supersedes the prior waiver, and because a waiver is only active while the clock is strictly before its `expires_at`, a diver whose waiver has lapsed reverts to `UNKNOWN` clearance for gate purposes. A waiver may be signed by the owning `Diver` or by a `ShopAdmin`, and waivers can be retrieved individually or listed (optionally filtered by `diver_id`).

### 3.2. Building the Catalog: Courses, Instructors, and Boats

The shop's offerings are defined by a `ShopAdmin`. A `Course` is created with a `title`, a `course_type` (`OPEN_WATER` for the entry-level program or `ADVANCED`), the number of distinct pool sessions a diver must attend stored in `required_pool_sessions` (zero or greater), the number of distinct open-water sessions stored in `required_open_water_sessions` (at least one), a `price_cents` tuition (greater than zero), and an optional `grants_specialty` that defaults to `NONE` and may instead be `ENRICHED_AIR`. The `course_type` determines both the certification level a graduate receives and, together with the required-session counts, what it takes to finish; `grants_specialty` determines whether the issued card additionally confers a nitrox specialty.

An `Instructor` is added by a `ShopAdmin` with a `full_name` and a professional `rating` of either `DIVEMASTER` or `INSTRUCTOR`. The distinction is operational: only an instructor rated `INSTRUCTOR` may lead and grade sessions, whereas a `DIVEMASTER` may serve only as an assistant attached to a session. Each instructor carries the conserved `active_session_count` described in Section 2.5, which starts at zero.

A `Boat` is the charter vessel for dive trips. A `ShopAdmin` adds a boat with a `name`, a `capacity` (the maximum number of divers per charter, greater than zero), and a `turnaround_minutes` buffer (defaulting to 60) that represents the mandatory rest-and-reset interval required between two trips on the same hull. Capacity governs trip-booking limits, and the turnaround buffer governs trip scheduling, both described below.

### 3.3. Enrollment and the Path to Eligibility

Enrolling a diver in a course creates an `Enrollment` carrying the `diver_id` and `course_id`. A new enrollment begins in `ACTIVE` status with `elearning_pct` at 0, both attendance counters (`pool_sessions_attended` and `open_water_sessions_attended`) at 0, a freshly computed `completion_pct`, and `certification_card_id` null until the enrollment completes. A diver may enroll itself; a `ShopAdmin` may enroll on a diver's behalf. Enrollments can be fetched individually or listed (optionally filtered by `diver_id` or `course_id`). The canonical link from an enrollment to its eventual card lives on the card as `enrollment_id`; the enrollment's `certification_card_id` is a back-reference, and a card for a given enrollment is discoverable by listing certification cards filtered by that enrollment.

Progress accrues along three independent tracks that combine into one **completion score**. The e-learning track is set directly: submitting e-learning progress writes the enrollment's `elearning_pct` to a value between 0 and 100 inclusive (a value outside that range is malformed). The two attendance tracks accrue through session attendance, described in Section 3.5. The `completion_pct` is a weighted blend recomputed whenever any track changes — on attendance recording, on the session-cancellation cascade, on e-learning submission, and on an explicit eligibility recompute. To compute it, the system first derives two attendance fractions: the pool fraction is 1 when the course requires no pool sessions, otherwise it is the smaller of 1 and the ratio of `pool_sessions_attended` to the course's `required_pool_sessions`; the open-water fraction is 1 when the course requires no open-water sessions, otherwise the smaller of 1 and the ratio of `open_water_sessions_attended` to the course's `required_open_water_sessions`. These two fractions are derived first and only then fed into the blend; the blend never feeds back into the fractions. The raw score is the e-learning percentage weighted at 0.2, plus the pool fraction expressed as a percentage (the fraction multiplied by 100) weighted at 0.3, plus the open-water fraction expressed as a percentage weighted at 0.5. That raw score is rounded half-up to a whole integer to produce `completion_pct`.

An enrollment becomes certification-eligible — transitioning `ACTIVE → ELIGIBLE` — when all of the following hold at once: `elearning_pct` equals exactly 100; `pool_sessions_attended` is at least the course's `required_pool_sessions`; `open_water_sessions_attended` is at least the course's `required_open_water_sessions`; the diver has an active waiver (the logical clock is before the waiver's `expires_at` and it is the diver's latest); and the diver's `medical_status` is `CLEAR`. When those conditions are all satisfied, `completion_pct` necessarily computes to 100. This evaluation runs automatically as a side effect whenever attendance is recorded or e-learning progress is set, and it can also be forced explicitly through a `ShopAdmin`-only eligibility-recompute capability. The same recompute is bidirectional: if an enrollment is `ELIGIBLE` and at least one eligibility precondition no longer holds — for instance because a previously attended session was cancelled, dropping an attendance counter, or because the diver's waiver has expired — the enrollment reverts `ELIGIBLE → ACTIVE` and its `completion_pct` recomputes to a value below 100. This revert edge exists to keep certification issuance honest after a prerequisite is invalidated. Should the medical or waiver gate fail at the moment eligibility is evaluated, that evaluation is blocked by `ERR_WAIVER_REQUIRED` (HTTP 422) rather than silently advancing the enrollment.

A diver or a `ShopAdmin` may withdraw an enrollment. Withdrawal is permitted from either the `ACTIVE` or the `ELIGIBLE` state and drives the enrollment to the terminal `WITHDRAWN` status; from any other state it is rejected with `ERR_INVALID_STATE` (HTTP 409). Withdrawing cascades to release seats: every session booking belonging to the enrollment that is still `BOOKED` is moved to `CANCELLED`, and each release decrements the owning session's `confirmed_seats`.

### 3.4. Scheduling Sessions Under Instructor Ratios

A `ShopAdmin` schedules a training session by supplying the `course_id` it belongs to, a `session_type` of `POOL` (confined water) or `OPEN_WATER` (a training dive), the `primary_instructor_id` who will lead it, an optional `assistant_count` of attached `DIVEMASTER` assistants (defaulting to 0, zero or greater), and the session window as `starts_at` and `ends_at` (the end must be strictly after the start, or the request is malformed). A new session begins `SCHEDULED` with `confirmed_seats` at 0, and creating it increments the lead instructor's `active_session_count`.

Two constraints guard session creation. First, the named `primary_instructor_id` must reference an instructor rated `INSTRUCTOR`, and that instructor must not already lead another `SCHEDULED` session whose window overlaps the new one. Overlap is evaluated on a half-open interval basis: each window covers from its `starts_at` up to but not including its `ends_at`, so two sessions that merely touch at a boundary (one ending exactly when the next begins) do not conflict, whereas any genuine overlap does. A non-`INSTRUCTOR` rating or a genuine window overlap is rejected with `ERR_INSTRUCTOR_CONFLICT` (HTTP 409).

The session's `max_students` capacity is computed once at creation from the instructor ratio and is not recomputed afterward, since `session_type` and `assistant_count` are fixed at creation. The ratio is non-linear in the session type and widens linearly with assistants. For a `POOL` session, `max_students` is 8 plus 4 for each assistant. For an `OPEN_WATER` session, `max_students` is 4 plus 2 for each assistant. Open-water work is held to the tighter base ratio because it is the higher-risk environment.

An `Instructor` who is the session's `primary_instructor_id` may complete the session once the logical clock has reached or passed the session's `starts_at` and the session is still `SCHEDULED`; an attempt by any other instructor, or before the start time, or against a session not in `SCHEDULED`, fails (a wrong-state target yields `ERR_INVALID_STATE`, HTTP 409). Completing a session drives it `SCHEDULED → COMPLETED`, decrements the lead instructor's `active_session_count`, and converts every booking on the session that is still `BOOKED` and was never recorded as attended into `NO_SHOW`, with each such conversion decrementing the session's `confirmed_seats`.

A `ShopAdmin` may instead cancel a `SCHEDULED` session, driving it `SCHEDULED → CANCELLED` and decrementing the lead instructor's `active_session_count`. Cancellation triggers a three-level cascade. Every booking on the session whose status is `BOOKED` or `ATTENDED` is moved to `CANCELLED`, and the session's `confirmed_seats` is driven to 0. For each cancelled booking that had been `ATTENDED`, the owning enrollment's matching attendance counter — `pool_sessions_attended` for a pool session or `open_water_sessions_attended` for an open-water session — is decremented and its `completion_pct` is recomputed; and if that enrollment had been `ELIGIBLE` but now fails a prerequisite, it reverts `ELIGIBLE → ACTIVE`. This is the serialization point that keeps a certification from resting on attendance that was later undone.

### 3.5. Booking and Attending Sessions

A diver claims a seat in a session through a session booking, which references the target `session_id`, the `enrollment_id` claiming the seat, and the `expected_session_version` carrying the client's last observed `version` of that session. A booking may be created by the owning `Diver` (for its own enrollment) or by a `ShopAdmin`. A successful booking begins `BOOKED`, increments the session's `confirmed_seats`, and increments the session's `version` by one. Bookings can be retrieved individually or listed (optionally filtered by `session_id` or `enrollment_id`).

Creating a booking runs a sequence of guards beyond the foundational checks of Section 2.9. The enrollment must be `ACTIVE` and the session `SCHEDULED`, or the request is rejected with `ERR_INVALID_STATE` (HTTP 409). The optimistic-concurrency check of Section 2.7 applies: `expected_session_version` must equal the session's current `version`, else `ERR_STALE_VERSION` (HTTP 412). The diver must clear the medical/waiver gate — an active waiver and `medical_status` not `RESTRICTED` — or the booking is rejected with `ERR_WAIVER_REQUIRED` (HTTP 422). The seat must fit: the booking must not push the session's `confirmed_seats` above its `max_students`, or it is rejected with `ERR_CAPACITY_EXCEEDED` (HTTP 409). And the booking must not duplicate an existing one: at most one non-terminal session booking may exist for a given enrollment-and-session pair, with a second rejected by `ERR_DUPLICATE_BOOKING` (HTTP 409). A diver or `ShopAdmin` may cancel a `BOOKED` booking, moving it `BOOKED → CANCELLED` and decrementing the session's `confirmed_seats`; this same `BOOKED → CANCELLED` transition is what the enrollment-withdrawal and session-cancellation cascades trigger automatically.

Attendance is recorded by the session's lead instructor. Recording attendance is permitted only by the `Instructor` who is the owning session's `primary_instructor_id`, only while the booking is `BOOKED`, and only while the owning session is still `SCHEDULED`. It moves the booking `BOOKED → ATTENDED` and increments the owning enrollment's `pool_sessions_attended` or `open_water_sessions_attended` according to the session's `session_type`. As a cascade, the enrollment's `completion_pct` is recomputed, and if every eligibility precondition now holds the enrollment advances `ACTIVE → ELIGIBLE`. A booking that is still `BOOKED` when its session is completed (never having been attended) is moved by the completion cascade to `NO_SHOW`, releasing its seat; and a booking that was already `ATTENDED` when its session is cancelled is moved by the cancellation cascade to `CANCELLED`, with the attendance reversal described in Section 3.4.

### 3.6. Issuing Certification Cards

Certification issuance is the act that turns training into a credential, and it is reserved for a `ShopAdmin`. Issuance is permitted only against an enrollment in the `ELIGIBLE` state; against any other state it is rejected with `ERR_INVALID_STATE` (HTTP 409). Because issuance is a one-way commitment that mutates downstream diver state, it is guarded by optimistic concurrency at the enrollment level: the request must carry `expected_enrollment_version` matching the enrollment's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), ensuring the operator is issuing against the eligibility state it actually observed.

Issuance drives the enrollment `ELIGIBLE → COMPLETED` and creates a `CertificationCard`. The card records the `diver_id` of the certified diver, the `enrollment_id` that produced it, a `level` mirroring the course's `course_type` (`OPEN_WATER` or `ADVANCED`), a `specialty` taken from the course's `grants_specialty` (`NONE` or `ENRICHED_AIR`), and an `issued_at` stamped from the logical clock. The enrollment's `certification_card_id` is set to the new card's `id`, and the enrollment's `version` increments by one. Issuance then cascades onto the diver: the diver's `cert_level` is upgraded to the course's `course_type` if that level is higher than the diver currently holds (so an `ADVANCED` card raises an `OPEN_WATER` diver but a card never demotes), and that diver mutation in turn recomputes the diver's `nitrox_certified`, which becomes true once a card with `specialty` equal to `ENRICHED_AIR` has been issued to the diver. Cards are immutable; they can be fetched individually or listed, optionally filtered by `diver_id` or `enrollment_id`.

### 3.7. Charters: Scheduling Trips and Booking Divers

A `ShopAdmin` schedules a dive trip on a boat, supplying the `boat_id`, the trip window as `starts_at` and `ends_at` (end strictly after start), the `min_cert_level` a diver must hold to book (`OPEN_WATER` or `ADVANCED`), a per-diver `base_fare_cents` (greater than zero), and a `fill_addon_cents` per-tank surcharge applied when a booking requests tank fills (zero or greater). A new trip begins `OPEN` with `confirmed_divers` at 0. Trip scheduling enforces a boat-level non-overlap that is stricter than the session rule: the boat must have no other non-`CANCELLED` trip whose window, expanded by the boat's `turnaround_minutes` on each side, overlaps the requested window. This is a closed-with-buffer comparison — the turnaround minutes are subtracted from each existing trip's start and added to each existing trip's end before testing for overlap, and the endpoints are inclusive — so a new trip must clear every existing trip by at least the full turnaround buffer on both sides. A conflict is rejected with `ERR_BOAT_CONFLICT` (HTTP 409).

A diver is placed on a trip through a trip booking that references the `trip_id`, the `diver_id`, an optional `tanks` count of fill add-ons requested (defaulting to 0, zero or greater), an optional `party_size` (defaulting to 1, at least 1, which drives the group discount), and the `expected_trip_version` carrying the client's last observed `version` of the trip. A trip booking may be created by the owning `Diver` or by a `ShopAdmin`. A successful booking begins `CONFIRMED`, increments the trip's `confirmed_divers`, and increments the trip's `version` by one. Beyond the foundational checks, booking runs these guards: the optimistic-concurrency check of Section 2.7 (`expected_trip_version` against the trip's current `version`, else `ERR_STALE_VERSION`, HTTP 412); the certification prerequisite — the diver's `cert_level` must be at least the trip's `min_cert_level`, else `ERR_CERT_PREREQUISITE_NOT_MET` (HTTP 422); the medical/waiver gate — an active waiver and `medical_status` not `RESTRICTED`, else `ERR_WAIVER_REQUIRED` (HTTP 422); the capacity check — the booking must not push `confirmed_divers` above the boat's `capacity`, else `ERR_CAPACITY_EXCEEDED` (HTTP 409); and the duplicate check — at most one non-`CANCELLED` trip booking may exist for a given diver-and-trip pair, else `ERR_DUPLICATE_BOOKING` (HTTP 409). Trip bookings can be fetched individually or listed (optionally filtered by `trip_id` or `diver_id`).

The booking's charges are computed at creation and stored as `total_cents`, `deposit_cents`, and `balance_due_cents`. The system first sums the integer line items: the trip's `base_fare_cents` plus the number of `tanks` multiplied by the trip's `fill_addon_cents`. A group discount of 15 percent applies to that subtotal when the `party_size` is at least 4; for a smaller party no discount applies (a discount of zero). The discount is applied to the summed subtotal as a single step, and the discounted amount is then rounded half-up once to whole cents to yield `total_cents` — the line items are never rounded individually before summing. The `deposit_cents` is `total_cents` multiplied by 30 percent, rounded half-up to whole cents. The `balance_due_cents` is `total_cents` minus `deposit_cents`. (For a solo or small party the discount is zero, so the total equals the subtotal; for a qualifying party the 15 percent comes off the sum before the single rounding step.)

A diver or `ShopAdmin` may cancel a `CONFIRMED` trip booking, moving it `CONFIRMED → CANCELLED` and decrementing the trip's `confirmed_divers`. A `ShopAdmin` may depart an `OPEN` trip once the logical clock has reached or passed the trip's `starts_at`; departure drives the trip `OPEN → DEPARTED` and, for every `CONFIRMED` booking on it, sets that booking's `balance_due_cents` to 0 (the balance is treated as settled at departure) and moves the booking `CONFIRMED → DEPARTED`. A `ShopAdmin` may instead cancel an `OPEN` trip, driving it `OPEN → CANCELLED` and moving every `CONFIRMED` booking on it to `CANCELLED` with the trip's `confirmed_divers` driven to 0. A departure or cancel attempted against a trip not in `OPEN`, or a depart attempted before the trip's start time, is rejected with `ERR_INVALID_STATE` (HTTP 409).

### 3.8. Gear Rental, Deposits, and Settlement

Gear rental is a `ShopAdmin` desk operation. Checking out gear creates a `RentalAgreement` recording the `diver_id` renter, an `item_description`, a `daily_rate_cents` (greater than zero), a refundable `deposit_cents` security deposit (zero or greater), and a `scheduled_return_at` the diver plans to return by. The agreement begins `ACTIVE`; the server stamps `checkout_at` from the logical clock and leaves `actual_return_at`, `actual_cost_cents`, and `deposit_refund_cents` null while the rental is active. At checkout the system projects an `estimated_cost_cents` and, as a cascade, recomputes the renter's `deposit_on_hold_cents` so that the deposit just placed is reflected in the diver's held-deposit ledger. Agreements can be fetched individually or listed (optionally filtered by `diver_id`).

Billing turns on billed days, where a billed-day count is the elapsed span between two instants converted to whole days with any partial day rounded up and a floor of one day. The `estimated_cost_cents`, projected forward at checkout against the planned return, is the billed days from `checkout_at` to `scheduled_return_at` multiplied by the `daily_rate_cents`; it deliberately excludes any late surcharge and damage fee, neither of which is known yet.

Checking in gear is also a `ShopAdmin` action and is permitted only while the agreement is `ACTIVE` (otherwise `ERR_INVALID_STATE`, HTTP 409). The operator may supply a `damage_fee_cents` damage assessment (defaulting to 0, zero or greater). Check-in drives the agreement `ACTIVE → RETURNED`, stamps `actual_return_at` from the logical clock, and finalizes the charge as `actual_cost_cents`. The actual charge is computed chronologically: let the estimate's billed days be the billed days from `checkout_at` to `scheduled_return_at`, and the actual billed days be the billed days from `checkout_at` to `actual_return_at`. On-time days are the smaller of the actual and estimate day counts; late days are the actual day count minus the estimate day count, floored at zero. The late-day rate is the `daily_rate_cents` multiplied by 1.5 and rounded half-up to whole cents. The `actual_cost_cents` is the on-time days at the standard daily rate, plus the late days at the late-day rate, plus the `damage_fee_cents`.

Settlement at check-in returns part or all of the deposit. The deposit absorbs any overage of the actual charge above the prepaid estimate: the overage is the `actual_cost_cents` minus the `estimated_cost_cents`, floored at zero, and the `deposit_refund_cents` is the `deposit_cents` minus that overage, floored at zero. Check-in then cascades to recompute the renter's `deposit_on_hold_cents` (now that this rental has left `ACTIVE`, its deposit is no longer held), restoring the money-conservation invariant.

A `ShopAdmin` may instead void an `ACTIVE` rental, but only as a compensating action taken before any time has elapsed — the void is permitted only when the current logical clock equals the agreement's `checkout_at` exactly; otherwise it is rejected with `ERR_INVALID_STATE` (HTTP 409). Voiding drives the agreement `ACTIVE → VOIDED`, sets `actual_cost_cents` to 0 and `deposit_refund_cents` to the full `deposit_cents`, and cascades to recompute the renter's `deposit_on_hold_cents`, fully reversing the checkout debit.

### 3.9. Tank Fills and Equipment Servicing

Filling a tank is a `ShopAdmin` operation that creates a `FillService` for a `diver_id`, recording the `gas` (`AIR` or `NITROX`), the `o2_pct` oxygen percentage, and the `tank_capacity_liters` water capacity (greater than zero). Oxygen percentage is constrained by gas: for `AIR` it must be exactly 21, and for `NITROX` it must be between 22 and 40 inclusive; a value outside the gas-appropriate range is malformed (`ERR_INVALID_REQUEST`, HTTP 400). A `NITROX` fill additionally requires the diver to be nitrox-certified, else `ERR_CERT_PREREQUISITE_NOT_MET` (HTTP 422). Fill services can be fetched individually or listed (optionally filtered by `diver_id`).

The `price_cents` is computed at creation. The base is 1200 cents. An `AIR` fill is priced at the base alone. A `NITROX` fill adds a surcharge banded by oxygen percentage: 800 cents when `o2_pct` is at most 32, 1400 cents when `o2_pct` is at most 36 (that is, 33 through 36), and 2200 cents when `o2_pct` is higher (37 through 40). A large-tank factor then applies: if `tank_capacity_liters` is greater than 12 the subtotal is multiplied by 1.25, otherwise by 1.0. The final `price_cents` is that product rounded half-up to whole cents.

Equipment servicing is tracked by a `GearServiceOrder`, opened by a `ShopAdmin` for a `diver_id` with a `service_type` of `VIP` (an annual visual inspection) or `HYDRO` (a five-yearly hydrostatic test). A new order is `OPEN` with `serviced_at` and `next_due_at` null. Completing the order is a `ShopAdmin` action permitted only while it is `OPEN` (otherwise `ERR_INVALID_STATE`, HTTP 409); completion drives it `OPEN → COMPLETED`, stamps `serviced_at` from the logical clock, and computes the `next_due_at` as `serviced_at` plus the service interval — 365 days for a `VIP` order, or 1825 days for a `HYDRO` order. A `ShopAdmin` may instead cancel an `OPEN` order, driving it `OPEN → CANCELLED` with no further side effects; a cancel against an order not in `OPEN` is rejected with `ERR_INVALID_STATE` (HTTP 409). Orders can be fetched individually or listed (optionally filtered by `diver_id`).

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including state-transition actions and progress updates — return a `200 OK` status code; the clock control endpoint also returns `200 OK`. Read operations return `200 OK`. The request body, response body, and side effects of each endpoint are defined by the workflow narratives in Section 3 and the global rules in Section 2; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | ShopAdmin |
| POST | `/divers` | Register a diver | ShopAdmin, Diver |
| GET | `/divers/{id}` | Get a diver | ShopAdmin, Diver, Instructor |
| GET | `/divers` | List divers | ShopAdmin, Instructor |
| POST | `/waivers` | Sign a medical & liability waiver | ShopAdmin, Diver |
| GET | `/waivers/{id}` | Get a single waiver | ShopAdmin, Diver, Instructor |
| GET | `/waivers` | List waivers (optionally by diver) | ShopAdmin, Diver, Instructor |
| GET | `/certification-cards/{id}` | Get a single certification card | ShopAdmin, Diver, Instructor |
| GET | `/certification-cards` | List certification cards (optionally by diver or enrollment) | ShopAdmin, Diver, Instructor |
| POST | `/instructors` | Add an instructor | ShopAdmin |
| GET | `/instructors/{id}` | Get an instructor | ShopAdmin, Instructor |
| POST | `/courses` | Create a course | ShopAdmin |
| GET | `/courses/{id}` | Get a course | ShopAdmin, Diver, Instructor |
| POST | `/enrollments` | Enroll a diver in a course | ShopAdmin, Diver |
| GET | `/enrollments/{id}` | Get an enrollment | ShopAdmin, Diver, Instructor |
| GET | `/enrollments` | List enrollments (optionally by diver or course) | ShopAdmin, Diver, Instructor |
| POST | `/enrollments/{id}/elearning-progress` | Set e-learning completion percentage | ShopAdmin, Diver |
| POST | `/enrollments/{id}/recompute-eligibility` | Force re-evaluation of cert eligibility | ShopAdmin |
| POST | `/enrollments/{id}/issue-certification` | Issue the certification card for an ELIGIBLE enrollment | ShopAdmin |
| POST | `/enrollments/{id}/withdraw` | Withdraw from a course | ShopAdmin, Diver |
| POST | `/sessions` | Schedule a pool or open-water session | ShopAdmin |
| GET | `/sessions/{id}` | Get a session | ShopAdmin, Diver, Instructor |
| GET | `/sessions` | List sessions (optionally by course or instructor) | ShopAdmin, Diver, Instructor |
| POST | `/sessions/{id}/complete` | Mark a session completed | Instructor |
| POST | `/sessions/{id}/cancel` | Cancel a session | ShopAdmin |
| POST | `/session-bookings` | Book a seat in a session for an enrollment | ShopAdmin, Diver |
| GET | `/session-bookings/{id}` | Get a session booking | ShopAdmin, Diver, Instructor |
| GET | `/session-bookings` | List session bookings (optionally by session or enrollment) | ShopAdmin, Diver, Instructor |
| POST | `/session-bookings/{id}/attend` | Record attendance for a booking | Instructor |
| POST | `/session-bookings/{id}/cancel` | Cancel a session booking | ShopAdmin, Diver |
| POST | `/boats` | Add a charter boat | ShopAdmin |
| GET | `/boats/{id}` | Get a boat | ShopAdmin, Diver, Instructor |
| POST | `/dive-trips` | Schedule a dive trip / charter on a boat | ShopAdmin |
| GET | `/dive-trips/{id}` | Get a dive trip | ShopAdmin, Diver, Instructor |
| GET | `/dive-trips` | List dive trips (optionally by boat) | ShopAdmin, Diver, Instructor |
| POST | `/dive-trips/{id}/depart` | Depart a trip | ShopAdmin |
| POST | `/dive-trips/{id}/cancel` | Cancel a trip | ShopAdmin |
| POST | `/trip-bookings` | Book a diver onto a trip | ShopAdmin, Diver |
| GET | `/trip-bookings/{id}` | Get a trip booking | ShopAdmin, Diver |
| GET | `/trip-bookings` | List trip bookings (optionally by trip or diver) | ShopAdmin, Diver |
| POST | `/trip-bookings/{id}/cancel` | Cancel a trip booking | ShopAdmin, Diver |
| POST | `/rental-agreements` | Check out rental gear | ShopAdmin |
| GET | `/rental-agreements/{id}` | Get a rental agreement | ShopAdmin, Diver |
| GET | `/rental-agreements` | List rental agreements (optionally by diver) | ShopAdmin, Diver |
| POST | `/rental-agreements/{id}/checkin` | Check in rental gear and settle | ShopAdmin |
| POST | `/rental-agreements/{id}/void` | Void a rental at checkout (full deposit refund) | ShopAdmin |
| POST | `/fill-services` | Fill a tank (air or nitrox) | ShopAdmin |
| GET | `/fill-services/{id}` | Get a fill service | ShopAdmin, Diver |
| GET | `/fill-services` | List fill services (optionally by diver) | ShopAdmin, Diver |
| POST | `/gear-service-orders` | Open a VIP or hydro gear service order | ShopAdmin |
| GET | `/gear-service-orders/{id}` | Get a gear service order | ShopAdmin, Diver |
| GET | `/gear-service-orders` | List gear service orders (optionally by diver) | ShopAdmin, Diver |
| POST | `/gear-service-orders/{id}/complete` | Complete a gear service order | ShopAdmin |
| POST | `/gear-service-orders/{id}/cancel` | Cancel a gear service order | ShopAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_WAIVER_REQUIRED` | 422 Unprocessable Entity |
| `ERR_CERT_PREREQUISITE_NOT_MET` | 422 Unprocessable Entity |
| `ERR_INSTRUCTOR_CONFLICT` | 409 Conflict |
| `ERR_BOAT_CONFLICT` | 409 Conflict |
| `ERR_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_DUPLICATE_BOOKING` | 409 Conflict |
