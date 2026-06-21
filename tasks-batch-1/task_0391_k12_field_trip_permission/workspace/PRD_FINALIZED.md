# K-12 Field Trip & Permission Management API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the K-12 Field Trip & Permission Management API, a backend platform that coordinates the full life of a school field trip — from the moment a teacher drafts a proposal, through a multi-tier approval chain, the collection of signed permission slips and fees, the assembly of chaperones and transportation, the final lock of the roster, and finally the headcount events that bracket the trip itself.

The platform exists to resolve a tension that schools navigate every season: a single outing simultaneously involves money (fees, deposits, scholarships, refunds), safety (chaperone-to-student ratios, background checks, emergency contacts), capacity (seats on a bus, seats on a trip), and authority (who may approve, who may sign, who may cancel). Each of these concerns has its own rules, and they interact — withdrawing a student moves money, cancelling a trip releases bus seats and reverses payments, signing a slip can change how many chaperones the trip needs. The system treats every such interaction as a first-class, immediately-consistent operation so that no party ever sees a roster, a balance, or a bus that disagrees with reality.

Because the approval chain crosses three administrative tiers and the financial picture must reconcile to the cent at all times, the API enforces strict role separation, optimistic concurrency on the roster-lock step, and a conserved-quantity discipline over cash and seats. The sections that follow define the global contract first, then the domain workflows where the bulk of the business logic lives.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. Every entity is exposed as a flat, top-level collection: each resource has its own single-item read and a list read whose every foreign-key field doubles as an optional filter, so a child is always reachable by filtering its parent's identifier.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is absent, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 401). When the headers are valid but the role is not permitted to invoke the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes exactly four roles: `Teacher`, `Principal`, `DistrictAdmin`, and `Guardian`.

Two of these roles are tied to a persisted entity, and two are opaque operators. When `X-User-Role` is `Teacher`, `X-User-ID` is the `id` of the acting `Guardian` record — a teacher organizes trips through a Guardian-backed identity, and that same identity is what a trip records in its `organizer_teacher_id` field; ownership checks on any resource that references that Guardian compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `Guardian`, `X-User-ID` is likewise the `id` of the acting `Guardian`; ownership checks on a permission slip or chaperone compare the resource's `guardian_id` to `X-User-ID`. When `X-User-Role` is `Principal`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity — the server may record it (for example, as the `actor_user_id` on a `TripApproval` that a principal's decision writes) but does not compare it to any entity's `id`. When `X-User-Role` is `DistrictAdmin`, `X-User-ID` is similarly an opaque operator identifier; the server may record it on the approval audit record it writes but never matches it against an entity `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and its accepted range is a minimum of 1 and a maximum of 100. The `offset` parameter is the number of leading items to skip and defaults to 0.

Unless a specific workflow states otherwise, every list endpoint returns its resources sorted by their creation timestamp, `created_at`, in ascending order.

List responses carry the pagination bookkeeping in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Record Classes

Most resources in the system are mutable, versioned records carrying a uniform set of system-managed fields:

- `id` — a unique, server-minted identifier formatted as a UUID, with no type prefix of any kind.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, fixed at creation.
- `updated_at` — an ISO 8601 UTC timestamp, refreshed on every mutation of the resource.
- `version` — an integer that begins at 1 on creation and increments by exactly 1 on every mutation. It is the basis for optimistic concurrency control (§2.7).

The mutable, versioned resources are `Student`, `Guardian`, `Vehicle`, `ScholarshipPool`, `FieldTrip`, `PermissionSlip`, `ScholarshipGrant`, `Chaperone`, and `TransportBooking`.

A second class of records is append-only or immutable and therefore carries only `id` and `created_at` — neither `updated_at` nor `version` is present on these. This class comprises `TripApproval` (an append-only approval-chain audit record), `EmergencyContact` (an immutable child of a slip), `FeeTransaction` (an append-only money ledger entry), and `AttendanceRecord` (an append-only headcount event). These records are never updated in place; the workflow that needs to "change" one instead appends a new record.

### 2.5. Hierarchical Consistency and Derived Counts

Several `FieldTrip` fields are derived rather than supplied. `signed_count` is the number of this trip's permission slips whose `signature_status` is `SIGNED`. `required_chaperones` is the output of the chaperone-ratio rule (§3) over the currently `SIGNED` slips. `collected_fees_cents` is the conserved net cash of the trip. `confirmed_count` and `per_student_final_fee_cents` are null-valued until the roster is locked, at which point both are snapshotted and fixed. On a `PermissionSlip`, `fee_due_cents`, `scholarship_award_cents`, and `net_paid_cents` are likewise derived. On a `Vehicle`, `seats_reserved` is derived; on a `ScholarshipPool`, `granted_cents` and `remaining_cents` are derived.

Whenever a child operation changes a quantity that feeds a parent's derived field — a slip being signed changing the trip's `signed_count`, a booking being confirmed changing a vehicle's `seats_reserved` — the server recomputes the parent's derived fields immediately and, where the parent is a versioned resource, refreshes its `updated_at` and increments its `version`. These automatic reconciliations are server-driven; a client never has to issue a separate request against the parent to keep it consistent. The roster-lock step is the one operation that explicitly increments `FieldTrip.version` as a declared side effect of its own transition.

### 2.6. Nested Resource Retrieval and Existence Ordering

Many operations address a resource through a nested path — for example, a slip identified within its trip, or a grant identified within its slip. The server validates the path identifiers strictly left to right and rejects on the first one that does not resolve, before evaluating any business rule. A trip identifier is checked first, yielding `ERR_TRIP_NOT_FOUND` if absent; only then is the slip checked, yielding `ERR_SLIP_NOT_FOUND`; and so on for `ERR_CHAPERONE_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, and `ERR_GRANT_NOT_FOUND`. Foreign-key identifiers supplied in a request body are validated the same way: a missing `student_id` yields `ERR_STUDENT_NOT_FOUND`, a missing `guardian_id` or `organizer_teacher_id` yields `ERR_GUARDIAN_NOT_FOUND`, a missing `vehicle_id` yields `ERR_VEHICLE_NOT_FOUND`, and a missing `pool_id` yields `ERR_POOL_NOT_FOUND`. Existence checks (404) always precede state, ownership, and business checks; the only checks that precede existence are header validity (401) and role permission (403).

### 2.7. Optimistic Concurrency Control on Roster Lock

The roster-lock operation is guarded by optimistic concurrency control. The request to lock a trip's roster must carry `expected_trip_version`, a non-optional field holding the `version` of the `FieldTrip` the client last observed. The server compares it against the trip's current `version`; if another writer has advanced that version since the client read it — for instance by signing or revoking a slip, which bumps the trip — the lock is rejected with `ERR_STALE_TRIP_VERSION` (HTTP 412). The rationale is that a roster lock takes a snapshot of which `SIGNED` slips become confirmed and fixes the final per-student fee; if the client's view of `signed_count` and `required_chaperones` is stale, its lock would freeze the wrong roster. The lock supersedes that stale view and is refused. No other endpoint accepts or requires a version field; the version check applies to the roster-lock step alone.

### 2.8. Monetary Precision and Conserved Cash

All money in the system is expressed and stored in integer cents — there are no fractional cents and no floating-point amounts. Fields named with a `_cents` suffix are always whole integers. Where a division is required to split a cost across students, the calculation floors each per-line share to a whole cent first and then sweeps the leftover cents one at a time, as detailed in §3; this floor-then-distribute order is mandatory and must not be replaced by summing first and rounding once.

The trip's `collected_fees_cents` is a conserved quantity. Every movement of money is recorded as a `FeeTransaction` ledger entry whose `amount_cents` is signed: positive for a `PAYMENT`, negative for a `REFUND`. The trip's `collected_fees_cents` always equals the sum of `amount_cents` over all of that trip's fee transactions, and a slip's `net_paid_cents` always equals the sum of `amount_cents` over that slip's own transactions. The invariant the system preserves is that a trip's `collected_fees_cents` equals the sum of `net_paid_cents` across its slips. Because the ledger is append-only — refunds are appended, never deleted — a payment followed by its refund leaves the conserved cash exactly where it started.

### 2.9. Conserved Seats and Scholarship Funds

Two further quantities are conserved the same way. A `Vehicle`'s `seats_reserved` always equals the sum of `seat_count` over that vehicle's `CONFIRMED` transport bookings and may never exceed the vehicle's `seat_capacity`; confirming a booking adds its seats and cancelling a confirmed booking returns them, so a confirm followed by a cancel restores `seats_reserved` to its prior value. A `ScholarshipPool`'s `granted_cents` always equals the sum of `award_cents` over that pool's `ACTIVE` grants, and its `remaining_cents` is the pool's `total_cents` minus `granted_cents`; granting an award draws the pool down and revoking that award returns the funds, leaving the pool whole.

### 2.10. Enumerations

The fixed enumerations used across the system are as follows. A `FieldTrip`'s `status` is one of `DRAFT`, `PENDING_PRINCIPAL`, `PENDING_DISTRICT`, `APPROVED`, `ROSTER_LOCKED`, `IN_PROGRESS`, `COMPLETED`, or `CANCELLED`, and its `grade_band` is one of `ELEMENTARY`, `MIDDLE`, or `HIGH`. A `PermissionSlip` carries three independent dimensions: `signature_status` is `UNSIGNED`, `SIGNED`, or `REVOKED`; `payment_status` is `UNPAID`, `PAID`, or `REFUNDED`; and `participation_status` is `PENDING`, `CONFIRMED`, or `WITHDRAWN`. A `Chaperone`'s `status` is `INVITED`, `CONFIRMED`, `CLEARED`, or `WITHDRAWN`. A `TransportBooking`'s `status` is `REQUESTED`, `CONFIRMED`, or `CANCELLED`. A `Vehicle`'s `status` is `ACTIVE` or `RETIRED`. A `ScholarshipGrant`'s `status` is `ACTIVE` or `REVOKED`. A `TripApproval` records a `step` of `PRINCIPAL` or `DISTRICT`, a `decision` of `APPROVE` or `REJECT`, and an `actor_role` of `PRINCIPAL` or `DISTRICT_ADMIN`. A `FeeTransaction` records a `kind` of `PAYMENT` or `REFUND` and a `reason` of `GUARDIAN_PAYMENT`, `TRIP_CANCELLATION`, or `VOLUNTARY_WITHDRAWAL`. An `AttendanceRecord` records a `checkpoint` of `DEPARTURE` or `RETURN`.

### 2.11. Validation Ordering

When several checks could fail on one request, the server evaluates them in a fixed priority so that the same situation always yields the same error. Header validity is checked first (`ERR_MISSING_OR_INVALID_USER_CONTEXT`, 401), then role permission (`ERR_FORBIDDEN_ROLE`, 403), then existence of every path and body identifier (the family of `*_NOT_FOUND` errors, 404), then — for guardian-owned operations — that the acting guardian owns the slip or chaperone being mutated (`ERR_NOT_SLIP_GUARDIAN` or `ERR_NOT_CHAPERONE_GUARDIAN`, 403). For an approval decision, the body's `step` is checked against the trip's current pending step (`ERR_INVALID_APPROVAL_STEP`, 422) before the state precondition. The resource's own state precondition is checked next, then any cross-entity parent-state gate, then temporal-overlap checks, then the safety, capacity, fiscal, and concurrency checks particular to each workflow. The detailed conditions and the exact error each raises live with the workflows in §3. Independently of all of these, any request whose body is missing a required field, carries an ill-typed value, or supplies an invalid enum value is rejected with `ERR_VALIDATION` (HTTP 422).

## 3. Business Logic & Workflows

### 3.1. Reference Data: People, Vehicles, and Funding Pools

Before any trip can take shape, the system holds the people and resources a trip draws on. A `Student` is registered with a `full_name`, a `grade_level` (an integer from 0, representing kindergarten, up to and including 12), a `home_school_code` naming the school of enrollment, and an optional `special_needs` flag that defaults to false; a student so flagged requires a dedicated one-to-one chaperone on any trip they join. A `Guardian` is registered with a `full_name`, an `email` that must be unique across all guardians, and a `phone`; an attempt to register a second guardian with an `email` already on file is rejected with `ERR_GUARDIAN_EMAIL_TAKEN`. A teacher, a principal, or a district administrator may register students and guardians.

A `Vehicle` is registered by a district administrator with a `label` and a `seat_capacity` of at least 1; it starts with `status` `ACTIVE` and `seats_reserved` at 0. A district administrator may retire a vehicle, moving its `status` to `RETIRED` so that no further bookings on it can be confirmed. A `ScholarshipPool` is created by a district administrator with a `name` and `total_cents` of at least 0; it starts with `granted_cents` at 0 and `remaining_cents` equal to `total_cents`. Each of these resources is readable individually and through a filtered list — vehicles may be listed by `status`, students by `home_school_code`, guardians by `email`.

### 3.2. Drafting and the Approval Chain

A `Teacher` opens the lifecycle by creating a field trip, which begins in `DRAFT`. The creation payload carries the `title`, the `organizer_teacher_id` (the Guardian-backed identity of the requesting teacher), the `school_code`, the `grade_band`, the departure and return timestamps `depart_at` and `return_at`, the `capacity` of student participants, the `base_fee_cents` admission portion, and the `transport_cost_cents` to be split across confirmed students. The payload may also set `deposit_cents` — the non-refundable deposit portion of each per-student fee, defaulting to 0 — and `has_water_activity`, a flag defaulting to false that signals swimming or water and raises the chaperone requirement. On creation the trip's `signed_count` and `collected_fees_cents` are 0 and its `version` is 1.

When the trip is ready, the teacher submits it, advancing `DRAFT → PENDING_PRINCIPAL`. Submission is allowed only from `DRAFT`; a submit from any other state is rejected with `ERR_TRIP_NOT_DRAFT`. Submission also revalidates the trip's bones: `return_at` must be strictly after `depart_at`, or the request fails with `ERR_INVALID_TIME_WINDOW`, and `capacity` must be at least 1, or it fails with `ERR_INVALID_CAPACITY`.

A submitted trip flows through a two-tier approval chain recorded as `TripApproval` audit entries. Each decision names a `step` and a `decision` and may carry an optional `comment`; the server stamps the record's `trip_id`, the `actor_role` of the deciding role, and the `actor_user_id` from the approver's `X-User-ID`. The body's `step` must match the trip's current pending step — `PRINCIPAL` while the trip is `PENDING_PRINCIPAL`, `DISTRICT` while it is `PENDING_DISTRICT`. A well-formed but wrong-for-now step is rejected with `ERR_INVALID_APPROVAL_STEP` before the state precondition is examined. A `Principal` records the principal step: a `PRINCIPAL`/`APPROVE` decision advances `PENDING_PRINCIPAL → PENDING_DISTRICT` and appends an approval record, while a `PRINCIPAL`/`REJECT` decision sends the trip back to `DRAFT` for the teacher to revise and resubmit, also appending a record. Either principal decision requires the trip to be in `PENDING_PRINCIPAL`; otherwise it is rejected with `ERR_TRIP_NOT_AWAITING_PRINCIPAL`. Symmetrically, a `DistrictAdmin` records the district step: a `DISTRICT`/`APPROVE` decision advances `PENDING_DISTRICT → APPROVED` and appends a record, while a `DISTRICT`/`REJECT` decision returns the trip all the way to `DRAFT` and appends a record. Either district decision requires the trip to be in `PENDING_DISTRICT`; otherwise it is rejected with `ERR_TRIP_NOT_AWAITING_DISTRICT`. The reject branches form revision loops: a rejected trip lands back in `DRAFT`, may be edited, and may re-enter the chain.

### 3.3. Building the Roster: Slips, Emergency Contacts, and Signing

Once a trip is `APPROVED`, guardians may begin signing their students onto it. A teacher first creates a `PermissionSlip` for the trip, supplying the `student_id` and the signing `guardian_id`, with optional `medical_notes` and an `allergies` list that defaults to empty. The slip begins with `signature_status` `UNSIGNED`, `payment_status` `UNPAID`, and `participation_status` `PENDING`. A slip records the `trip_id` it belongs to and exposes the derived `fee_due_cents`, `scholarship_award_cents`, `net_paid_cents`, and the `signed_at` timestamp described below.

Before a slip can be signed it must list at least one emergency contact. An `EmergencyContact` — added either by the teacher or by the guardian — captures a `name`, a `phone`, and the `relationship` to the student (for example "aunt"), and references its `slip_id`. A sign attempt against a slip with no emergency contact on file is rejected with `ERR_EMERGENCY_CONTACT_REQUIRED`.

The signing guardian e-signs the slip, driving `signature_status` `UNSIGNED → SIGNED` (and the identical re-sign path `REVOKED → SIGNED` after a prior revocation). Signing is permitted only to the guardian named on the slip — when `X-User-ID` does not equal the slip's `guardian_id`, the request fails with `ERR_NOT_SLIP_GUARDIAN`. The parent trip must be in `APPROVED` for signing to be open; signing against a trip in any other state is rejected with `ERR_TRIP_NOT_OPEN_FOR_SIGNING`. The slip's `signature_status` must currently be `UNSIGNED` or `REVOKED`; signing an already-signed slip yields `ERR_SLIP_ALREADY_SIGNED`. The trip must have room: if the trip's `signed_count` has already reached `capacity`, a further sign is rejected with `ERR_TRIP_AT_CAPACITY`. On a successful sign the server moves the slip to `SIGNED`, stamps `signed_at` with the current time, increments the trip's `signed_count` by 1, and recomputes the trip's `required_chaperones`. Because the live `signed_count` has changed, the server then recomputes the `fee_due_cents` of every currently `SIGNED` slip on the trip under the provisional variant described in §3.7 — including the slip just signed — so that each signed slip's provisional transport share follows the new count rather than only the slip that triggered the change.

A guardian may revoke their own signature before the roster locks, driving `signature_status` `SIGNED → REVOKED`. Revocation, too, is limited to the slip's own guardian (`ERR_NOT_SLIP_GUARDIAN`) and requires the parent trip to still be in `APPROVED`; a revoke once the trip has moved on — in particular once it is `ROSTER_LOCKED` — is rejected with `ERR_ROSTER_LOCKED`, and the guardian must instead use the withdraw path. The slip's `signature_status` must be `SIGNED`, or the revoke fails with `ERR_SLIP_NOT_SIGNED`. Revoking cascades: the slip becomes `REVOKED`, the trip's `signed_count` decreases by 1, and `required_chaperones` is recomputed; because the live `signed_count` has changed, the server also recomputes the `fee_due_cents` of every still-`SIGNED` slip on the trip under the provisional variant described in §3.7, so that the remaining signed slips' provisional transport share follows the new count; moreover, if any chaperone on the trip was assigned as the dedicated one-to-one for this slip's student, that student's one-to-one requirement drops out of the ratio computation.

### 3.4. Chaperones, Background Checks, and the Ratio

A `Teacher` invites a `Chaperone` onto a trip by naming the chaperoning `guardian_id`; the invitation may also carry an `assigned_student_id`, set when this chaperone is to be the dedicated one-to-one for a particular special-needs student, and a `background_check_ref`, the reference that a later clearance will require. The chaperone begins `INVITED`.

A chaperone progresses through three steps before it counts. The invited guardian confirms the invitation, moving `INVITED → CONFIRMED`; confirmation is limited to the chaperone's own guardian (`ERR_NOT_CHAPERONE_GUARDIAN`) and requires the chaperone to be in `INVITED`, otherwise it is rejected with `ERR_CHAPERONE_NOT_INVITED`. A `Principal` then clears the confirmed chaperone, moving `CONFIRMED → CLEARED`; only a cleared chaperone counts toward the ratio. Clearing requires the chaperone to be in `CONFIRMED` (`ERR_CHAPERONE_NOT_CONFIRMED`), requires the parent trip to be in either `APPROVED` or `ROSTER_LOCKED` (`ERR_TRIP_NOT_APPROVED`), and requires the chaperone to carry a `background_check_ref` (`ERR_BACKGROUND_CHECK_MISSING`). Clearing also runs a scheduling-conflict check described in §3.5.

A guardian may withdraw their chaperone role at any non-terminal point — from `INVITED`, `CONFIRMED`, or `CLEARED` — moving the chaperone to `WITHDRAWN`. Withdrawal requires the chaperone not to be already `WITHDRAWN` (`ERR_CHAPERONE_NOT_WITHDRAWABLE`) and requires the parent trip not to be `ROSTER_LOCKED`, since cleared chaperones are frozen once the roster locks; a withdraw against a locked trip is rejected with `ERR_ROSTER_LOCKED`.

The number of chaperones a trip needs is recomputed every time a slip is signed, revoked, or withdrawn, and is read as a precondition at roster lock. The requirement is built from three parts. Take S, the count of slips currently `SIGNED`, and N, the count of those `SIGNED` slips whose student is flagged `special_needs`. A base ratio is selected by the trip's `grade_band`: one chaperone per 8 students for `ELEMENTARY`, one per 12 for `MIDDLE`, and one per 15 for `HIGH`. The general requirement is S divided by that base ratio, rounded up to the next whole chaperone — so a `MIDDLE` trip with 10 signed students needs 1 general chaperone, while 13 signed students needs 2. General chaperones cover all signed students, special-needs included; on top of them, each special-needs signed student needs its own dedicated one-to-one, adding N more. Finally, if the trip has `has_water_activity` set, one additional chaperone is added as a water surcharge; otherwise nothing is added. The required total is the general count plus N plus the water surcharge.

### 3.5. Scheduling Conflicts: Vehicles and Chaperones

Two distinct overlap rules guard against double-booking, and they deliberately use different interval semantics.

When a transport booking is confirmed, the server checks the vehicle's other commitments for a time clash. Take the parent trip's window from `depart_at` to `return_at` for the booking being confirmed. For every other `CONFIRMED` booking on the same vehicle, take that booking's parent trip window, and test for overlap on a closed interval with no buffer: the two clash when the new trip's departure is at or before the other's return and the other's departure is at or before the new trip's return. Touching endpoints collide — if one trip returns at exactly the instant another departs, that is a conflict. Any clash rejects the confirm with `ERR_VEHICLE_TIME_CONFLICT`.

When a principal clears a chaperone, the server checks whether that same guardian is already cleared as a chaperone on another trip whose time overlaps. Take the parent trip's window from `depart_at` to `return_at` for the chaperone being cleared, and expand it by a travel buffer of one hour — that is, 3600 seconds — on each side. For every other `CLEARED` chaperone sharing the same `guardian_id`, take that chaperone's trip window unbuffered, and test for overlap on a half-open interval: they clash when the buffered start of the new window is strictly before the other window's end and the other window's start is strictly before the buffered end of the new window. Because the comparison is strict, windows that merely touch after the buffer is applied do not collide. Any clash rejects the clearance with `ERR_CHAPERONE_TIME_CONFLICT`. A person cannot chaperone two trips at once.

### 3.6. Booking Transportation

A `Teacher` requests a transport booking on a trip by naming the `vehicle_id` and the `seat_count` of at least 1; the booking begins `REQUESTED`. Confirming the booking moves it `REQUESTED → CONFIRMED` and is the moment seats are actually committed. Confirmation requires the booking to be in `REQUESTED`, otherwise `ERR_BOOKING_NOT_REQUESTED`; requires the vehicle's `status` to be `ACTIVE`, otherwise `ERR_VEHICLE_RETIRED`; requires that adding this booking's `seat_count` to the vehicle's current `seats_reserved` not exceed the vehicle's `seat_capacity`, otherwise `ERR_VEHICLE_OVERBOOKED`; and requires the vehicle-window check of §3.5 to pass. On a successful confirm the booking becomes `CONFIRMED` and the vehicle's `seats_reserved` increases by the booking's `seat_count`.

A booking may be cancelled from `REQUESTED` or from `CONFIRMED`, moving it to `CANCELLED`. Cancellation requires the booking not to be already `CANCELLED` (`ERR_BOOKING_NOT_CANCELLABLE`). Cancelling a `CONFIRMED` booking additionally requires the parent trip not to be `ROSTER_LOCKED`, since confirmed transport is frozen at lock (`ERR_ROSTER_LOCKED`); when a confirmed booking is cancelled the vehicle's `seats_reserved` decreases by that booking's `seat_count`, returning the seats to the pool. Cancelling a booking that was still only `REQUESTED` releases no seats, since none had been committed.

### 3.7. Fees, Scholarships, and Payment

Each slip owes a per-student fee. A scholarship may reduce that fee but never the deposit. A `Teacher` or `Principal` may grant a `ScholarshipGrant` against a slip by naming the `pool_id` and an `award_cents` of at least 1; the grant begins `ACTIVE`. The award is bounded twice: it must not exceed the pool's `remaining_cents`, or it is rejected with `ERR_SCHOLARSHIP_POOL_EXHAUSTED`, and it must not exceed the slip's waivable amount — the gross fee minus the trip's `deposit_cents` — or it is rejected with `ERR_AWARD_EXCEEDS_WAIVABLE`. Granting draws the pool down: the pool's `granted_cents` rises by `award_cents`, its `remaining_cents` falls by the same, and the slip's `fee_due_cents` and `scholarship_award_cents` are recomputed. A `Teacher` or `Principal` may revoke an active grant, moving its `status` `ACTIVE → REVOKED`; revocation requires the grant to be `ACTIVE`, otherwise `ERR_GRANT_NOT_ACTIVE`. Revoking returns the money: `granted_cents` falls by `award_cents`, `remaining_cents` rises by the same, and the slip's fee is recomputed.

The slip's fee is computed in two variants that differ only in how the transport cost is shared. In both, the gross is the trip's `base_fee_cents` plus this slip's transport share. The scholarship applied is the sum of `award_cents` over the slip's `ACTIVE` grants. Because the deposit is never waivable, the effective scholarship is the smaller of that scholarship sum and the waivable amount, where the waivable amount is the gross minus the trip's `deposit_cents` but never less than zero. The fee owed, `fee_due_cents`, is the gross minus the effective scholarship.

The provisional variant is computed at sign time, before the roster locks. Its transport share is the trip's `transport_cost_cents` divided by the trip's current live `signed_count` (or by 1 if `signed_count` is zero), rounded up to the next whole cent — an estimate that shifts as other guardians sign and revoke. The final variant is computed at roster lock and fixed thereafter; its transport share is this slip's exact allocated share from the lock-time split described in §3.8, which includes the leftover-cent distribution and so can differ from the provisional figure whenever the count of confirmed slips differs from the live signed count.

A guardian pays their own slip by submitting `amount_cents`. Payment is limited to the slip's guardian (`ERR_NOT_SLIP_GUARDIAN`), requires the slip to be `SIGNED` (`ERR_SLIP_NOT_SIGNED`), requires `payment_status` to be `UNPAID` (`ERR_SLIP_ALREADY_PAID`), and requires the submitted `amount_cents` to equal the slip's current `fee_due_cents` exactly (`ERR_PAYMENT_AMOUNT_MISMATCH`). On success the slip's `payment_status` becomes `PAID`, a `FeeTransaction` of `kind` `PAYMENT` and `reason` `GUARDIAN_PAYMENT` is appended with `amount_cents` equal to the positive fee, the slip's `net_paid_cents` is recomputed, and the trip's `collected_fees_cents` rises by the fee.

### 3.8. Locking the Roster

When the roster is ready, the `Teacher` locks it, advancing the trip `APPROVED → ROSTER_LOCKED`. This is the system's most consequential single operation, and it runs a gauntlet of preconditions in order. The trip must be in `APPROVED`, otherwise `ERR_TRIP_NOT_APPROVED`. The supplied `expected_trip_version` must match the trip's current `version`, otherwise the lock is superseded with `ERR_STALE_TRIP_VERSION` as described in §2.7. The roster must not be empty — `signed_count` must be at least 1, otherwise `ERR_EMPTY_ROSTER`. The chaperone ratio must be met — the count of `CLEARED` chaperones must be at least the trip's `required_chaperones`, otherwise `ERR_CHAPERONE_RATIO_UNMET`. And transport must be booked — the trip must have at least one `CONFIRMED` transport booking whose summed `seat_count` is at least `signed_count`, otherwise `ERR_TRANSPORT_NOT_BOOKED`.

When all preconditions pass, the lock takes a snapshot. Every slip currently `SIGNED` has its `participation_status` set to `CONFIRMED`; every slip that is `UNSIGNED` or `REVOKED` has its `participation_status` set to `WITHDRAWN`. The count of confirmed slips becomes the trip's `confirmed_count`. The transport cost is then allocated across the confirmed slips and each confirmed slip's `fee_due_cents` is recomputed under the final variant. Finally, the trip's `version` is incremented by 1 as the declared side effect of the lock.

The allocation works as a waterfall. Let C be the trip's `confirmed_count`. If C is zero the lock aborts with `ERR_EMPTY_ROSTER`. The base share is the trip's `transport_cost_cents` divided by C using integer floor division — each per-line share is rounded down to a whole cent first. The remainder is the `transport_cost_cents` minus the base share times C, a leftover of fewer cents than there are confirmed slips. Those leftover cents are assigned one apiece to confirmed slips taken in order of `signed_at` ascending, with `PermissionSlip.created_at` ascending as the tie-break — never by `id`. The first as-many-as-the-remainder slips in that order each get a transport share of the base share plus one cent; the rest get exactly the base share. The trip's `per_student_final_fee_cents` is set to the trip's `base_fee_cents` plus the base share as a representative pre-remainder figure. This floor-then-sweep order is pinned: flooring each share before sweeping the remainder gives a different per-slip result than summing and rounding once, and the former is the required behavior.

### 3.9. Running the Trip and Headcount

After the roster locks, the `Teacher` starts the trip, advancing `ROSTER_LOCKED → IN_PROGRESS`; starting requires the trip to be in `ROSTER_LOCKED`, otherwise `ERR_TRIP_NOT_LOCKED`. During and around the trip, the teacher records headcount events. Each `AttendanceRecord` names the `slip_id`, the `checkpoint` (`DEPARTURE` or `RETURN`), and whether the student was `present`, and references its `trip_id`; these are append-only events, so a correction is a new record rather than an edit.

The teacher completes the trip, advancing `IN_PROGRESS → COMPLETED`. Completion requires the trip to be in `IN_PROGRESS`, otherwise `ERR_TRIP_NOT_IN_PROGRESS`, and requires that every slip that was snapshotted `CONFIRMED` at lock has at least one `RETURN` attendance record; if any confirmed slip lacks a return headcount, completion is refused with `ERR_RETURN_HEADCOUNT_INCOMPLETE`. `COMPLETED` is terminal.

### 3.10. Withdrawal Refunds and Trip Cancellation

A guardian may voluntarily withdraw their student, and the whole trip may be cancelled; the two paths refund the same paid slip by different amounts.

A guardian withdraws their own paid student through the withdraw operation, which moves the slip's `payment_status` `PAID → REFUNDED`. Withdrawal is limited to the slip's guardian (`ERR_NOT_SLIP_GUARDIAN`), requires the parent trip not to be in `IN_PROGRESS`, `COMPLETED`, or `CANCELLED` (`ERR_TRIP_NOT_OPEN_FOR_WITHDRAWAL`), and requires the slip's `payment_status` to be `PAID` (`ERR_SLIP_NOT_PAID`). A withdraw sets the slip's `participation_status` to `WITHDRAWN`, sets `signature_status` to `REVOKED` if it was `SIGNED`, and sets `payment_status` to `REFUNDED`. The refund for a voluntary withdrawal is calculated as what the guardian actually paid — the slip's `net_paid_cents` — minus the forfeited portion, where the forfeit is the trip's `deposit_cents` plus this slip's committed transport share, and the refund is that difference but never less than zero. In other words the deposit and the committed transport share are both forfeited. A `FeeTransaction` of `kind` `REFUND` and `reason` `VOLUNTARY_WITHDRAWAL` is appended with a negative `amount_cents` equal to the refund, the slip's `net_paid_cents` is recomputed, the trip's `collected_fees_cents` falls by the refund, and if the slip had been counted as signed the trip's `signed_count` is adjusted accordingly.

Cancelling the whole trip refunds differently. A trip may be cancelled from any state that is not already `COMPLETED` or `CANCELLED`, moving it to `CANCELLED`; a cancel against a completed or cancelled trip is rejected with `ERR_TRIP_NOT_CANCELLABLE`. A `Teacher` may cancel a trip that is still early — in `DRAFT`, `PENDING_PRINCIPAL`, or `PENDING_DISTRICT` — and these early cancellations carry no money or roster cascade because nothing has been committed yet. Once the trip has reached `APPROVED` or `ROSTER_LOCKED`, cancellation is a `Principal` action and triggers a three-level cascade. First, every slip that is `PAID` has its `payment_status` set to `REFUNDED` and its `signature_status` set to `REVOKED`, and for each such slip a `FeeTransaction` of `kind` `REFUND` and `reason` `TRIP_CANCELLATION` is appended whose `amount_cents` is the negative of that slip's `net_paid_cents`; this is a full refund — for a trip cancellation the refund equals exactly what was paid, with nothing forfeited, so the deposit and transport share are returned. Appending those refunds drives each affected slip's `net_paid_cents` to zero and lowers the trip's `collected_fees_cents` correspondingly. Second, every transport booking that is `CONFIRMED` or `REQUESTED` is moved to `CANCELLED`, and the seats from the confirmed ones are released back to their vehicles' `seats_reserved`. Third, every chaperone that is not already `WITHDRAWN` is moved to `WITHDRAWN`.

### 3.11. Reading Back the Ledger and Roster

Every entity is reachable for reading. A `FieldTrip` read returns its computed counts and fees alongside its stored fields. A `Vehicle` read returns its live `seats_reserved`; a `ScholarshipPool` read returns its `remaining_cents`. The append-only records — `TripApproval` with its `step` and `decision`, `FeeTransaction` with its `kind` and `amount_cents`, `AttendanceRecord` with its `checkpoint` and `present` — are exposed through filtered list reads so that the full money and decision history of a trip can be reconstructed by filtering on the relevant `trip_id`, `slip_id`, or `pool_id`. Guardians may read the trips, slips, chaperones, students, and guardians within their view, while teachers, principals, and district administrators may read across the system.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — including every state-transition action and every list or single read — return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/students` | Register a student | Teacher, Principal, DistrictAdmin |
| GET | `/students` | List students (filter by school) | Teacher, Principal, DistrictAdmin |
| GET | `/students/{id}` | Get a student | Teacher, Principal, DistrictAdmin, Guardian |
| POST | `/guardians` | Register a guardian | Teacher, Principal, DistrictAdmin |
| GET | `/guardians` | List guardians (filter by email) | Teacher, Principal, DistrictAdmin |
| GET | `/guardians/{id}` | Get a guardian | Teacher, Principal, DistrictAdmin, Guardian |
| POST | `/vehicles` | Register a transport vehicle | DistrictAdmin |
| GET | `/vehicles` | List vehicles | Teacher, Principal, DistrictAdmin |
| GET | `/vehicles/{id}` | Get a vehicle | Teacher, Principal, DistrictAdmin |
| POST | `/vehicles/{id}/retire` | Retire a vehicle | DistrictAdmin |
| POST | `/scholarship-pools` | Create a scholarship funding pool | DistrictAdmin |
| GET | `/scholarship-pools` | List scholarship pools | Teacher, Principal, DistrictAdmin |
| GET | `/scholarship-pools/{id}` | Get a pool | Teacher, Principal, DistrictAdmin |
| GET | `/scholarship-grants` | List scholarship grants (filter by slip, pool, status) | Teacher, Principal, DistrictAdmin |
| GET | `/scholarship-grants/{id}` | Get a scholarship grant | Teacher, Principal, DistrictAdmin |
| POST | `/field-trips` | Create a field trip in DRAFT | Teacher |
| GET | `/field-trips` | List field trips (filter by organizer, school, status) | Teacher, Principal, DistrictAdmin |
| GET | `/field-trips/{id}` | Get a field trip | Teacher, Principal, DistrictAdmin, Guardian |
| POST | `/field-trips/{id}/submit` | Submit a DRAFT trip into the approval chain | Teacher |
| POST | `/field-trips/{id}/approvals` | Record an approval-chain decision | Principal, DistrictAdmin |
| POST | `/field-trips/{id}/lock-roster` | Lock the roster (OCC-guarded) | Teacher |
| POST | `/field-trips/{id}/start` | Start the trip | Teacher |
| POST | `/field-trips/{id}/complete` | Complete the trip | Teacher |
| POST | `/field-trips/{id}/cancel` | Cancel the trip (cascades) | Teacher, Principal |
| GET | `/trip-approvals` | List approval records (filter by trip, step) | Teacher, Principal, DistrictAdmin |
| GET | `/trip-approvals/{id}` | Get an approval record | Teacher, Principal, DistrictAdmin |
| POST | `/field-trips/{id}/permission-slips` | Create a permission slip | Teacher |
| GET | `/permission-slips` | List permission slips (filter by trip, student, guardian, signature) | Teacher, Principal, DistrictAdmin, Guardian |
| GET | `/permission-slips/{id}` | Get a permission slip | Teacher, Principal, DistrictAdmin, Guardian |
| POST | `/field-trips/{tripId}/permission-slips/{id}/sign` | Guardian e-signs (or re-signs) the slip | Guardian |
| POST | `/field-trips/{tripId}/permission-slips/{id}/revoke` | Guardian revokes signature before lock | Guardian |
| POST | `/field-trips/{tripId}/permission-slips/{id}/pay` | Guardian pays the slip fee | Guardian |
| POST | `/field-trips/{tripId}/permission-slips/{id}/withdraw` | Guardian withdraws their student | Guardian |
| POST | `/field-trips/{tripId}/permission-slips/{id}/emergency-contacts` | Add an emergency contact to a slip | Teacher, Guardian |
| GET | `/emergency-contacts` | List emergency contacts (filter by slip) | Teacher, Principal, DistrictAdmin, Guardian |
| GET | `/emergency-contacts/{id}` | Get an emergency contact | Teacher, Principal, DistrictAdmin, Guardian |
| POST | `/field-trips/{tripId}/permission-slips/{id}/scholarship-grants` | Grant a scholarship against a slip | Teacher, Principal |
| POST | `/field-trips/{tripId}/permission-slips/{slipId}/scholarship-grants/{id}/revoke` | Revoke a scholarship award | Teacher, Principal |
| POST | `/field-trips/{id}/chaperones` | Invite a chaperone | Teacher |
| GET | `/chaperones` | List chaperones (filter by trip, guardian, assigned student, status) | Teacher, Principal, DistrictAdmin, Guardian |
| GET | `/chaperones/{id}` | Get a chaperone | Teacher, Principal, DistrictAdmin, Guardian |
| POST | `/field-trips/{tripId}/chaperones/{id}/confirm` | Guardian confirms a chaperone invitation | Guardian |
| POST | `/field-trips/{tripId}/chaperones/{id}/clear` | Principal clears a confirmed chaperone | Principal |
| POST | `/field-trips/{tripId}/chaperones/{id}/withdraw` | Chaperone withdraws | Guardian |
| POST | `/field-trips/{id}/transport-bookings` | Request a transport booking | Teacher |
| GET | `/transport-bookings` | List transport bookings (filter by trip, vehicle, status) | Teacher, Principal, DistrictAdmin |
| GET | `/transport-bookings/{id}` | Get a transport booking | Teacher, Principal, DistrictAdmin |
| POST | `/field-trips/{tripId}/transport-bookings/{id}/confirm` | Confirm a transport booking | Teacher |
| POST | `/field-trips/{tripId}/transport-bookings/{id}/cancel` | Cancel a transport booking | Teacher |
| GET | `/fee-transactions` | List fee transactions (filter by slip, trip, kind) | Teacher, Principal, DistrictAdmin, Guardian |
| GET | `/fee-transactions/{id}` | Get a fee transaction | Teacher, Principal, DistrictAdmin, Guardian |
| POST | `/field-trips/{id}/attendance` | Record a headcount/attendance event | Teacher |
| GET | `/attendance-records` | List attendance records (filter by trip, slip, checkpoint) | Teacher, Principal, DistrictAdmin |
| GET | `/attendance-records/{id}` | Get an attendance record | Teacher, Principal, DistrictAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_TRIP_NOT_FOUND` | 404 Not Found |
| `ERR_SLIP_NOT_FOUND` | 404 Not Found |
| `ERR_CHAPERONE_NOT_FOUND` | 404 Not Found |
| `ERR_BOOKING_NOT_FOUND` | 404 Not Found |
| `ERR_GRANT_NOT_FOUND` | 404 Not Found |
| `ERR_STUDENT_NOT_FOUND` | 404 Not Found |
| `ERR_GUARDIAN_NOT_FOUND` | 404 Not Found |
| `ERR_VEHICLE_NOT_FOUND` | 404 Not Found |
| `ERR_POOL_NOT_FOUND` | 404 Not Found |
| `ERR_NOT_SLIP_GUARDIAN` | 403 Forbidden |
| `ERR_NOT_CHAPERONE_GUARDIAN` | 403 Forbidden |
| `ERR_GUARDIAN_EMAIL_TAKEN` | 409 Conflict |
| `ERR_TRIP_NOT_DRAFT` | 409 Conflict |
| `ERR_TRIP_NOT_AWAITING_PRINCIPAL` | 409 Conflict |
| `ERR_TRIP_NOT_AWAITING_DISTRICT` | 409 Conflict |
| `ERR_TRIP_NOT_APPROVED` | 409 Conflict |
| `ERR_TRIP_NOT_LOCKED` | 409 Conflict |
| `ERR_TRIP_NOT_IN_PROGRESS` | 409 Conflict |
| `ERR_TRIP_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_ROSTER_LOCKED` | 409 Conflict |
| `ERR_INVALID_TIME_WINDOW` | 422 Unprocessable Entity |
| `ERR_INVALID_CAPACITY` | 422 Unprocessable Entity |
| `ERR_INVALID_APPROVAL_STEP` | 422 Unprocessable Entity |
| `ERR_TRIP_NOT_OPEN_FOR_SIGNING` | 409 Conflict |
| `ERR_TRIP_NOT_OPEN_FOR_WITHDRAWAL` | 409 Conflict |
| `ERR_SLIP_ALREADY_SIGNED` | 409 Conflict |
| `ERR_SLIP_NOT_SIGNED` | 409 Conflict |
| `ERR_SLIP_ALREADY_PAID` | 409 Conflict |
| `ERR_SLIP_NOT_PAID` | 409 Conflict |
| `ERR_EMERGENCY_CONTACT_REQUIRED` | 409 Conflict |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 409 Conflict |
| `ERR_CHAPERONE_NOT_INVITED` | 409 Conflict |
| `ERR_CHAPERONE_NOT_CONFIRMED` | 409 Conflict |
| `ERR_CHAPERONE_NOT_WITHDRAWABLE` | 409 Conflict |
| `ERR_BACKGROUND_CHECK_MISSING` | 409 Conflict |
| `ERR_BOOKING_NOT_REQUESTED` | 409 Conflict |
| `ERR_BOOKING_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_VEHICLE_RETIRED` | 409 Conflict |
| `ERR_TRIP_AT_CAPACITY` | 409 Conflict |
| `ERR_VEHICLE_OVERBOOKED` | 409 Conflict |
| `ERR_VEHICLE_TIME_CONFLICT` | 409 Conflict |
| `ERR_CHAPERONE_TIME_CONFLICT` | 409 Conflict |
| `ERR_TRANSPORT_NOT_BOOKED` | 409 Conflict |
| `ERR_CHAPERONE_RATIO_UNMET` | 409 Conflict |
| `ERR_EMPTY_ROSTER` | 409 Conflict |
| `ERR_RETURN_HEADCOUNT_INCOMPLETE` | 409 Conflict |
| `ERR_SCHOLARSHIP_POOL_EXHAUSTED` | 409 Conflict |
| `ERR_AWARD_EXCEEDS_WAIVABLE` | 409 Conflict |
| `ERR_GRANT_NOT_ACTIVE` | 409 Conflict |
| `ERR_STALE_TRIP_VERSION` | 412 Precondition Failed |
| `ERR_VALIDATION` | 422 Unprocessable Entity |
