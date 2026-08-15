# Summer Conference Housing & Campus Turn API — Product Requirements Document

## 1. Introduction

Every summer, a university's residence halls undergo a compressed metamorphosis: the last students move out in May, and for the three months of summer the buildings operate as conference hotels — hosting external client groups with contracted bed blocks, rooming lists, chaperoned minors, linen service, and physical key credentials — before the entire inventory must be cleaned, repaired, and handed back in time for fall academic opening. This document specifies the API that runs that season. It governs the release of room inventory after the academic year, the intake and confirmation of conference client contracts, the cleaning "turn" of each room between departing and arriving groups, the safety screening required when minors are on campus, per-bed-night billing with damage and incidentals, the maintenance windows that must clear the fall-opening deadline, and the final allocation of settled summer revenue to the housing budget.

The system is built around two structural commitments. First, a strict season lifecycle on each building — from `ACADEMIC_USE` through release, the active turn season, fall preparation, and back to academic use — gates which commercial and facilities operations are legal at any moment. Second, all time-dependent behavior (check-in windows, no-show eligibility, screening expiry, dispute windows, cancellation fee tiers, maintenance start dates) is evaluated against a single server-held logical clock rather than wall-clock time, so that every temporal rule in this document is deterministic and testable. Campus conference services staff, facilities managers, housekeeping supervisors, finance officers, screening reviewers, and external client coordinators each interact with the API under a role-based access model described below.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply uniformly to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity in which they act. If either header is missing, or if `X-User-Role` does not name one of the declared roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes exactly six roles: `ConferenceServicesAdmin`, `FacilitiesManager`, `HousekeepingSupervisor`, `FinanceOfficer`, `ScreeningReviewer`, and `ClientCoordinator`. Each endpoint declares the roles authorized to call it (see §4); a caller whose role is not in the endpoint's list is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403). `ConferenceServicesAdmin` is the hierarchical override role: it holds a superset of every operational capability in the system, including exclusive rights to create buildings and conference groups, to confirm, return, and close out groups, to perform check-in, check-out, and no-show marking, to cancel turn tasks and inspect escalated ones, to issue and manage key credentials, and to drive the logical clock.

Role identity is interpreted as follows. When `X-User-Role` is `ClientCoordinator`, `X-User-ID` is the `id` of the acting `ConferenceGroup`; ownership checks on any resource that references a `ConferenceGroup` compare the resource's group foreign key — directly, or via the parent group of the addressed participant, assignment, screening, or damage assessment — to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403). The ownership-guarded operations are: submitting or cancelling a group, adding participants to a group, creating rooming-list revisions, fetching a group, listing its participants and its rooming-list revisions, submitting a background screening for a participant, appealing a flagged screening, cancelling a single reserved stay assignment, and disputing an assessed damage charge. When `X-User-Role` is `ConferenceServicesAdmin`, `FacilitiesManager`, `HousekeepingSupervisor`, `FinanceOfficer`, or `ScreeningReviewer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by creation timestamp (`created_at`) in ascending order. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created, and `updated_at` is the same kind of timestamp refreshed on every mutation. `version` is a system-managed integer that starts at its initial value on creation and increments by one on every mutation of the resource; it underpins the optimistic concurrency rules of §2.7. One entity is an exception: a `RoomingListRevision` is immutable once written and therefore carries only `id` and `created_at` — both `updated_at` and `version` are absent on revisions.

### 2.5. The Logical Clock

All temporal semantics in this document resolve against a server-held logical clock, never against wall-clock time. At server startup the logical clock reads exactly `2026-05-01T00:00:00Z`, and until it is explicitly advanced it continues to read that default. A `ConferenceServicesAdmin`-only, test-driving capability advances the logical clock to a supplied instant given in the `to_iso8601` request field; the response reports the new reading in the `current_utc` field. Actual check-in and check-out instants, key return instants, screening decision instants and cleared dates, assessment instants, invoice finalization and payment instants, revision supersession instants, no-show eligibility, maintenance start eligibility, dispute windows, cancellation fee tiers, and the screening `is_expired` flag are all read off this clock; time-dependent computed flags such as `is_expired` reflect the new clock on the next read after an advance.

### 2.6. Request Validation Order

When several checks could reject the same request, the server evaluates them in a fixed order so that the surfaced error is deterministic. First come authentication and authorization: header presence and role validity (`ERR_UNAUTHENTICATED`), then membership of the acting role in the endpoint's role list (`ERR_UNAUTHORIZED_ROLE`), then the conditional inspection-escalation rule (`ERR_TURN_REWORK_ESCALATION`), then coordinator ownership (`ERR_FORBIDDEN_OWNERSHIP`). Next, every identifier in the request path is resolved left-to-right, and the first missing resource yields `ERR_NOT_FOUND` (see §2.10). The request body is then checked for well-formedness — required fields present, enum members valid, and foreign-key identifiers in the body referencing existing entities — with failures rejected as `ERR_INVALID_REQUEST` (HTTP 400). After that, the optimistic-concurrency expected-version check runs where one is declared (`ERR_STALE_VERSION`), followed by state-machine legality checks (`ERR_INVALID_STATE` and the domain-named state errors). Only then do business rules run, in the relative order: safety rules, temporal rules, constraint rules, and finally fiscal rules. The ordered check sequences for individual operations are stated with each workflow in §3.

### 2.7. Optimistic Concurrency Control

Two write operations guard against lost updates with an expected-version check on the parent aggregate. Creating a new rooming-list revision for a group requires the request to carry `expected_conference_group_version` holding the group's `version` as the client last observed it; if the group's current `version` has advanced past that value, the creation is rejected with `ERR_STALE_VERSION` (HTTP 412), because a writer holding a stale group version would otherwise supersede a revision it never saw. Creating a maintenance window on a building likewise requires `expected_building_version` matching the building's current `version`, with a mismatch rejected as `ERR_STALE_VERSION` (HTTP 412), because lifecycle transitions such as confirm-release or begin-turn-season change the building's releasable inventory and a window planned against a stale building version must not be accepted. Endpoints other than these two do not take a version field.

### 2.8. Hierarchical Consistency, Cascades, and Building Ledger Counters

The building is the aggregate root of the season, and it maintains five system-managed ledger counters that must stay synchronized with the operational reality beneath it. `released_bed_count` is the sum of `bed_count` over all of the building's rooms, frozen at the moment of confirm-release. `reserved_bed_count` counts stay assignments in `RESERVED` or `CHECKED_IN` status across the building's rooms. `available_bed_count` is always `released_bed_count` minus `reserved_bed_count`, recomputed on every assignment creation, cancellation, no-show, and checkout. `scheduled_turn_count` counts the building's turn tasks in `SCHEDULED`, `IN_PROGRESS`, `READY_FOR_INSPECTION`, or `FAILED` status. `out_of_service_room_count` counts rooms currently `OUT_OF_SERVICE` under a maintenance window. A sixth counter, `available_key_count`, tracks the physical key pool: it equals `key_pool_size` minus keys currently outstanding (in `ISSUED` or `ACTIVATED` status) minus keys reported `LOST`, and it is initialized to `key_pool_size` at confirm-release.

State changes propagate in both directions through the hierarchy. Cascades travel downward — confirming a building's release flips every academically occupied room to `RELEASED`; superseding a rooming-list revision cancels its still-reserved assignments; starting a maintenance window takes rooms out of service. Bubbling travels upward — the first check-in on a room flips the room to `OCCUPIED`, and the first check-in of a group moves the group from `CONFIRMED` to `IN_HOUSE`; the last checkout from a room pushes the room into `NEEDS_TURN` and spawns its turn task. Conditional cascades fire only when a predicate holds: a reserved room returns to `RELEASED` only when its last active assignment leaves. Every mutation described in §3 — including each ledger-counter adjustment on the building — refreshes the mutated resource's `updated_at` and increments its `version`.

### 2.9. Monetary Precision and Rounding

All monetary values are integer cents; no fractional cents ever appear in requests, responses, or intermediate results. Where a calculation requires rounding, the method is round half up, applied at the pinned step stated for that calculation: per night for bed-night billing (before nights are summed), per unit for damage depreciation (before multiplying by quantity), and at the first two waterfall steps of revenue allocation. Threshold comparisons on money are integer-exact.

### 2.10. Nested Resource Retrieval

Requests that address nested resources validate path identifiers strictly left-to-right. The request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first path identifier that does not reference an existing resource, before any later identifier or any body content is examined; a request addressed to a room under a non-existent building therefore fails on the building identifier first.

## 3. Business Logic & Workflows

### 3.1. Releasing the Building: Season Lifecycle and Room Inventory

A `ConferenceServicesAdmin` registers each residence hall as a **Building** with a display `name`, a `fall_opening_date` (the calendar date by which the building must be handed back for the fall academic term, which every maintenance plan must clear), and a `key_pool_size` (the total physical key credentials held for the building, zero or more). New buildings begin in `ACADEMIC_USE`. While a building is in `ACADEMIC_USE` or `RELEASE_REVIEW`, a `FacilitiesManager` (or an admin) creates its **Rooms**, each with a `room_number` unique within the building and a `bed_count` of at least one; every room begins in `ACADEMIC_OCCUPIED`. Attempts to create rooms at any other point of the season are rejected as an invalid state.

The summer cycle starts when a `FacilitiesManager` initiates the release, moving the building from `ACADEMIC_USE` to `RELEASE_REVIEW`. Release review can be abandoned — aborting returns the building to `ACADEMIC_USE` — or confirmed. Confirming the release requires the building to have at least one room; it cascades downward so that every `ACADEMIC_OCCUPIED` room transitions to `RELEASED`, freezes `released_bed_count` as the sum of `bed_count` over all rooms, initializes `available_bed_count` as the released count minus whatever is already reserved, and sets `available_key_count` to the full `key_pool_size`. Once the building is `RELEASED`, beginning the turn season moves it to `TURN_ACTIVE` — the only building state in which conference groups can be confirmed and guests checked in; attempts at either while the building is in any other state are rejected with `ERR_BUILDING_NOT_RELEASED`.

Closing the season is equally deliberate. Beginning fall prep moves the building from `TURN_ACTIVE` to `FALL_PREP`, and is permitted only when no stay assignment in `RESERVED` or `CHECKED_IN` remains in any room of the building and no turn task in `SCHEDULED`, `IN_PROGRESS`, `READY_FOR_INSPECTION`, or `FAILED` remains open — the summer's guests and cleaning work must be fully drained first. Certifying fall readiness then moves the building from `FALL_PREP` to `READY_FOR_FALL`, permitted only when `out_of_service_room_count` is zero and no maintenance window in `CONFIRMED` or `IN_PROGRESS` status exists for the building. Finally, reopening for the academic year moves the building from `READY_FOR_FALL` back to `ACADEMIC_USE`: every room in `READY` or `RELEASED` returns to `ACADEMIC_OCCUPIED`, and `released_bed_count`, `reserved_bed_count`, and `available_bed_count` all reset to zero, closing the season cycle. Each of these building transitions increments the building's `version`.

### 3.2. Contract Intake: Groups, Participants, and Deposits

A `ConferenceServicesAdmin` opens the commercial relationship by creating a **ConferenceGroup** contract against a host building, supplying the `building_id`, the `client_name`, and the coordinator's `contact_email`, together with the contract `arrival_date` and `departure_date` — the departure must fall after the arrival, or the request fails with `ERR_DATE_RANGE_INVALID`. Optional fields at creation are `has_minor_participants` (defaulting to false), the `linen_tier` service level of `STANDARD` or `DELUXE` (defaulting to `STANDARD`; a `DELUXE` group lengthens the required turn window after its stay), and an initial `deposit_paid_cents` (defaulting to zero). The `contracted_bed_count` — at least one — records how many beds the contract covers and will be reconciled against the operative rooming list at confirmation. New groups begin in `DRAFT`, with `provisional_invoice_id` null until an invoice exists and `cancellation_fee_cents` null unless the group is later cancelled.

Participants join the group while it is in `DRAFT`, `RETURNED`, `SUBMITTED`, or `CONFIRMED`. A `ClientCoordinator` (for their own group) or an admin adds each **Participant** with a `full_name`, a `date_of_birth`, and a `role_in_group` of `ATTENDEE`, `CHAPERONE`, or `STAFF`. The system derives `is_minor` for each participant: true when the participant's age at the group's `arrival_date` is strictly under 18. Adding a participant mutates the parent group and increments its `version`.

When the client is ready for review, submission moves the group from `DRAFT` — or from `RETURNED` on the resubmission loop — to `SUBMITTED`, requiring at least one participant to exist. An admin who finds the submission deficient returns it for revision, moving `SUBMITTED` back to `RETURNED` so the coordinator can correct and resubmit. Separately, a `FinanceOfficer` records incoming deposit money: each deposit call carries `amount_cents`, which is added to the group's `deposit_paid_cents`, and the group's `version` increments with each record.

### 3.3. Background Screening and the Minor-Participant Policy

Groups that flag `has_minor_participants` carry additional safety obligations, enforced at confirmation. The chaperone ratio requires that the number of `CHAPERONE` participants whose `is_minor` is false be at least the total count of minor participants divided by ten and rounded up; a shortfall is rejected with `ERR_CHAPERONE_RATIO_UNMET`. In addition, every participant whose `role_in_group` is `CHAPERONE` or `STAFF` must hold a cleared, unexpired background screening.

A **BackgroundScreening** is submitted for a participant — by the group's coordinator or an admin — with a signed `consent_reference`. Screenings are accepted only for `CHAPERONE` and `STAFF` participants; submitting one for an `ATTENDEE` is rejected with `ERR_SCREENING_NOT_REQUIRED`. A new screening begins `SUBMITTED`. A `ScreeningReviewer` begins review, moving it to `IN_REVIEW`, and then decides with an `outcome`: `CLEAR` moves the screening to `CLEARED` and stamps `decided_at` with the current instant and `cleared_on` with the logical clock's calendar date, while `FLAG` moves it to `FLAGGED` with `decided_at` stamped. A flagged decision can be appealed by the group's coordinator, moving `FLAGGED` to `APPEALED` with the client's `appeal_reason` recorded. The reviewer then resolves the appeal with an `outcome`: `CLEAR` closes the appeal loop into `CLEARED` (again stamping `decided_at` and `cleared_on`), and `DENY` terminates the screening as `DENIED`. `CLEARED` and `DENIED` are terminal.

Clearance decays. The computed `is_expired` flag is true when a screening is in `CLEARED` status and the logical clock's calendar date is strictly after the date `SCREENING_VALIDITY_MONTHS` months after `cleared_on`. At group confirmation, a minor-flagged group whose `CHAPERONE` or `STAFF` participant lacks any `CLEARED` screening is rejected with `ERR_SCREENING_NOT_CLEARED`, and one whose cleared screening has `is_expired` true is rejected with `ERR_SCREENING_EXPIRED`.

### 3.4. Rooming Lists, Revisions, and Stay Occupancy

The operative guest list of a group is expressed as a chain of **RoomingListRevision** resources. Creating a new revision is an OCC-guarded write (§2.7): the request carries `expected_conference_group_version` and an `assignments` payload, each entry naming a `room_id`, a `participant_id`, and the planned `checkin_at` and `checkout_at` instants. The checkout must be strictly after the check-in, or the request fails with `ERR_DATE_RANGE_INVALID`; occupancy is the half-open interval in which the night of check-in counts and the night of checkout does not. Each revision receives a per-group monotonically increasing `revision_number` starting at 1 and begins `ACTIVE`. When a newer revision for the same group is persisted, the previously `ACTIVE` revision becomes `SUPERSEDED` with `superseded_at` stamped from the logical clock, and every one of its stay assignments still in `RESERVED` is cancelled, with the room and building counter effects of a cancellation — and all of this happens before the new assignments are validated, so a superseding revision never collides with the assignments it replaces. A revision records the `id` values of the stay assignments it created, in creation order, in `assignment_ids`, and each **StayAssignment** in turn records the creating revision's id in `revision_id` alongside its `group_id`. Successful revision creation increments the group's `version`.

Every new assignment is born `RESERVED`, and each one passes a validation gauntlet, evaluated in this order after the general checks of §2.6. First, the target room must be reservable — `RELEASED`, `READY`, `RESERVED`, or `OCCUPIED`; a room in `NEEDS_TURN`, `IN_TURN`, or `OUT_OF_SERVICE` rejects the assignment with `ERR_ROOM_NOT_RESERVABLE`. Second, participant double-booking: if the same participant already holds a non-cancelled assignment on any room whose half-open interval intersects the new one, the request fails with `ERR_OCCUPANCY_OVERLAP` — two intervals that merely touch, one's checkout equal to the other's check-in, do not overlap. Third, the turn-window rule against the immediate neighbors on the same room: the gap in hours between the preceding assignment's checkout and the new check-in must be at least the required turn hours for the new group's own `linen_tier`, and the gap between the new checkout and the following assignment's check-in must be at least the required hours for that following group's `linen_tier`; equality passes, and a shortfall is rejected with `ERR_TURN_WINDOW_TOO_SHORT`. The required gap is 24 hours — one full day — for a `STANDARD` tier and 30 hours for a `DELUXE` tier. Neighbors considered are assignments in `RESERVED` or `CHECKED_IN` (binding their planned interval) and assignments `CHECKED_OUT` (binding their actual interval from `actual_checkin_at` to `actual_checkout_at`); cancelled and no-show assignments are ignored. Note that touching intervals, while not an overlap, leave a zero-hour gap that the turn rule still evaluates — so back-to-back bookings on a room always fail the turn requirement. Fourth, room capacity: the number of overlapping non-cancelled assignments on the room must be fewer than its `bed_count` to admit one more, else `ERR_ROOM_CAPACITY_EXCEEDED`.

Landing assignments move the world with them. The first active assignment on a `RELEASED` or `READY` room flips it to `RESERVED`. The building's `reserved_bed_count` increases by the number of new assignments and `available_bed_count` is recomputed, with the building's `version` incrementing. If the group is already `CONFIRMED` when a revision is created, the provisional invoice's bed-night subtotal is recomputed (§3.8).

### 3.5. Guest Stays: Check-In, Check-Out, No-Show, and Cancellation

Check-in is performed by a `ConferenceServicesAdmin` and moves an assignment from `RESERVED` to `CHECKED_IN`. Its checks fire in order: the assignment must be `RESERVED`, its group must be `CONFIRMED` or `IN_HOUSE`, and the room must be `RESERVED` or `OCCUPIED` — violations reject with `ERR_INVALID_STATE`; the host building must be `TURN_ACTIVE`, else `ERR_BUILDING_NOT_RELEASED`; and the logical clock must fall within the planned stay — on or after `checkin_at` and strictly before `checkout_at` — else `ERR_OUTSIDE_CHECKIN_WINDOW`. On success, `actual_checkin_at` is stamped from the clock; if this is the first `CHECKED_IN` assignment on the room, the room bubbles from `RESERVED` to `OCCUPIED`; if it is the first check-in of the whole group, the group bubbles from `CONFIRMED` to `IN_HOUSE`.

Check-out moves a `CHECKED_IN` assignment to `CHECKED_OUT`, stamps `actual_checkout_at` from the clock, and settles the building ledger — `reserved_bed_count` decreases by one and `available_bed_count` increases by one. When no `CHECKED_IN` assignment remains on the room afterwards, the room cascades from `OCCUPIED` to `NEEDS_TURN`, spawning its turn task as described in §3.6.

A guest who never arrives is marked as a no-show, moving `RESERVED` to `NO_SHOW` — but only once the logical clock is more than 24 hours past the planned `checkin_at`; earlier attempts fail with `ERR_OUTSIDE_CHECKIN_WINDOW`. A single reserved assignment can also be cancelled by the group's coordinator or an admin, moving `RESERVED` to `CANCELLED`; operating on an assignment that belongs to a `SUPERSEDED` revision — for instance cancelling one of its already-cancelled assignments — is rejected with `ERR_REVISION_SUPERSEDED`. Both no-show and cancellation decrement `reserved_bed_count` and increment `available_bed_count`, and both trigger the conditional room cascade: when no `RESERVED` or `CHECKED_IN` assignment remains on the room, the room returns from `RESERVED` to `RELEASED`. `CHECKED_OUT`, `NO_SHOW`, and `CANCELLED` are the terminal states of a stay.

### 3.6. The Turn Between Groups

The moment a room empties, the cleaning machinery engages. The cascade that moves the room to `NEEDS_TURN` creates a **TurnTask** in `SCHEDULED` status and points the room's `active_turn_task_id` at it, while the building's `scheduled_turn_count` increments in ledger sync. The task's cleaning window starts at the triggering checkout instant — `window_start` equals the `actual_checkout_at` that emptied the room — and `window_end` is the earliest future `RESERVED` check-in on that room, or seven days after `window_start` when no next reservation exists. The task's governing `linen_tier` is the incoming group's tier when a next `RESERVED` assignment exists on the room, otherwise the departing group's tier — this is where the 30-hour `DELUXE` turn requirement of §3.5's booking checks gets its operational teeth.

A `HousekeepingSupervisor` starts the work, moving the task from `SCHEDULED` — or from `FAILED` on the rework loop — to `IN_PROGRESS`, permitted only while the room is `NEEDS_TURN` or `IN_TURN`; a start from `NEEDS_TURN` flips the room to `IN_TURN`. When the crew finishes, submitting for inspection moves `IN_PROGRESS` to `READY_FOR_INSPECTION`. Inspection then records an `outcome` and an optional free-text `note`, which is stored as the task's `inspector_note`. A `PASS` outcome moves the task to its terminal `PASSED` state and cascades the room from `IN_TURN` to `READY`, clearing the room's `active_turn_task_id` and decrementing `scheduled_turn_count`. A `FAIL` outcome moves the task to `FAILED` and increments its `rework_count`, sending the crew back through the start step. Rework escalates: once a task's `rework_count` has reached two, only a `ConferenceServicesAdmin` may inspect it, and a `HousekeepingSupervisor`'s inspection attempt is rejected with `ERR_TURN_REWORK_ESCALATION` (HTTP 403). An admin may also cancel a `SCHEDULED` task outright — an override that skips cleaning entirely: the task terminates as `CANCELLED`, the room moves directly from `NEEDS_TURN` to `READY` with its `active_turn_task_id` cleared, and `scheduled_turn_count` decrements.

### 3.7. Linen Packs and Key Credentials

While a group is `CONFIRMED` or `IN_HOUSE`, housekeeping issues linen against it: a **LinenIssue** records a `packs_issued` count of at least one and begins `ISSUED` with `packs_returned` and `packs_damaged` at zero. Returns are recorded incrementally, each call accumulating into `packs_returned` and `packs_damaged`; the cumulative sum of returned plus damaged packs after each call must not exceed `packs_issued`, or the call is rejected with `ERR_LINEN_OVERRETURN`. The issue sits in `PARTIALLY_RETURNED` while packs remain unaccounted — repeat partial returns keep it there — and reaches its terminal `RECONCILED` state the moment the cumulative returned-plus-damaged count equals `packs_issued` exactly, whether in one full-accounting call from `ISSUED` or as a final partial return. Every return recomputes `loss_charge_cents`: packs still unaccounted (issued minus returned minus damaged) are charged at 3,200 cents each, and damaged packs at 1,600 cents each.

Physical access works the same ledger discipline. Issuing a **KeyCredential** to a participant of the group records the holder's `participant_id` and a `credential_code` unique within the building; issuance requires the building's `available_key_count` to be at least one — an exhausted pool rejects with `ERR_KEY_INVENTORY_EXHAUSTED` — and decrements it. A new credential begins `ISSUED` and can be activated once the group is `CONFIRMED` or `IN_HOUSE` (otherwise the activation is rejected as an invalid state), moving to `ACTIVATED`. Return is accepted from either `ISSUED` or `ACTIVATED` and moves the credential to its terminal `RETURNED` state: `returned_at` is stamped from the logical clock, the `late_fee_cents` are computed, and the key flows back into the pool, incrementing `available_key_count`. Reporting the credential lost — likewise from `ISSUED` or `ACTIVATED` — terminates it as `LOST`, charging a `lost_fee_cents` of 5,000 cents; a lost key is never returned to the pool.

The late-return fee respects a grace boundary. The return's calendar date is compared to the group's `departure_date`: a return on the departure date or within the two grace days after it incurs no fee — late days are the calendar days between `departure_date` and the return date, minus two, floored at zero. Each late day costs 1,500 cents, and the fee is capped at 7,500 cents no matter how late the return. So a return exactly two days after departure is free, and one day later bills a single late day.

### 3.8. Damage Assessment and Dispute Resolution

When facilities staff find damage in a room, a `FacilitiesManager` (or admin) reports a **DamageAssessment** against the room, naming the responsible `group_id` and a `line_items` array whose entries each carry a `description`, a `quantity`, a `unit_replacement_cost_cents`, and the fixture's `fixture_age_months`. At report time the system computes `estimate_total_cents` — a straight sum of quantity times unit replacement cost over the lines, with no depreciation and no fee — and the assessment begins `REPORTED`, with `assessed_total_cents` null until a formal assessment.

The formal assessment moves `REPORTED` to `ASSESSED` and computes `assessed_total_cents` with a pinned rounding order. For each line, the depreciation factor is the larger of 0.40 and one minus two percent times the fixture's age in months; the depreciated unit value is the unit replacement cost times that factor, rounded half-up to whole cents per unit; and the line total is the depreciated unit value multiplied by the quantity. The assessed charge is the sum of the line totals plus one flat administrative fee of 2,500 cents, added once whenever at least one line exists; `assessed_at` is stamped from the logical clock. Because only the assessed variant depreciates and the estimate never does, the estimate is never lower than the assessed total for the same lines whenever any fixture has a positive age.

From `ASSESSED`, a `FinanceOfficer` bills the charge — moving it to `BILLED`, permitted only while the responsible group is `IN_HOUSE` or `DEPARTED` — or the group's coordinator disputes it with a `dispute_reason`, moving it to `DISPUTED`. The dispute must arrive within seven calendar days of `assessed_at`, inclusive of the seventh day; later attempts fail with `ERR_DISPUTE_WINDOW_CLOSED`. A `FinanceOfficer` resolves a dispute with an `outcome`: `ACCEPT` moves the assessment to `BILLED`, and if the resolution carries optional `adjusted_line_items`, those replace the assessment's lines and `assessed_total_cents` is recomputed by the same assessed-variant rule; `WAIVE` moves it to its terminal `WAIVED` state with `assessed_total_cents` zeroed. `BILLED` and `WAIVED` are terminal. Any of these four operations — assess, bill, dispute, resolve — attempted from a state that does not permit it is rejected with `ERR_DAMAGE_NOT_ASSESSED`.

### 3.9. Billing: Provisional Invoices, Cancellation, Finalization, and Payment

Confirmation is the pivot of the commercial lifecycle. An admin confirms a `SUBMITTED` group, and the checks run in a fixed sequence: the host building must be `TURN_ACTIVE` (else `ERR_BUILDING_NOT_RELEASED`); then, for minor-flagged groups, the safety gates of §3.3 in their stated order — chaperone ratio (`ERR_CHAPERONE_RATIO_UNMET`), screening clearance (`ERR_SCREENING_NOT_CLEARED`), screening freshness (`ERR_SCREENING_EXPIRED`); then the rooming-list gates — an `ACTIVE` revision with at least one assignment must exist (else `ERR_ROOMING_LIST_REQUIRED`) and its assignment count must equal the group's `contracted_bed_count` (else `ERR_CONTRACTED_BED_MISMATCH`); and finally the fiscal gate — the deposit must cover at least one quarter of the provisional bed-night estimate, evaluated integer-exact as `deposit_paid_cents` multiplied by four being at least the estimate in cents (else `ERR_DEPOSIT_INSUFFICIENT`). Success moves the group to `CONFIRMED`, creates its **Invoice** in `PROVISIONAL` status with the bed-night subtotal as its only component so far — stored in `provisional_bed_night_subtotal_cents` and mirrored in `provisional_total_cents` — and points the group's `provisional_invoice_id` at it.

Bed-night billing comes in two deliberate variants over the same stay data. The provisional variant, computed at confirmation and recomputed whenever a revision supersedes while the group is `CONFIRMED`, includes the assignments of the `ACTIVE` revision in `RESERVED` or `CHECKED_IN` status and counts each assignment's planned nights: every calendar date from the check-in date up to but not including the checkout date. All included nights across the whole group are then ordered by check-in date ascending, ties broken by the participant's `created_at` ascending, and priced marginally by cumulative position: nights up to and including the one-hundredth bed-night bill at the base rate of 4,500 cents, and every night beyond the hundredth bills at the tier-two rate of 3,900 cents — only the nights past the threshold receive the lower rate. If the group's `has_minor_participants` is true, each night's tier rate is increased by a fifteen percent surcharge, rounded half-up to the cent per night, before any weekend adjustment. Finally, each night falling on a Friday or a Saturday adds a weekend premium of 400 cents, applied after the surcharge rounding. The subtotal is the plain integer sum of these per-night amounts.

The final variant, computed at invoice finalization, prices reality instead of plans. Assignments that reached `CHECKED_OUT` bill their actual nights — the calendar dates from the `actual_checkin_at` date up to but not including the `actual_checkout_at` date — under the same tier, surcharge, and weekend rules. A `NO_SHOW` assignment bills exactly one flat night at the 4,500-cent base rate with no surcharge, no weekend premium, and no tier adjustment. `CANCELLED` assignments are excluded entirely. Identical data can therefore yield different numbers: early checkouts shrink the night list, and no-shows collapse to the flat rate.

Cancellation follows its own tariff. A coordinator (or admin) cancels a group from `DRAFT`, `SUBMITTED`, `RETURNED`, or `CONFIRMED`; from `IN_HOUSE`, `DEPARTED`, `CLOSED`, or `CANCELLED` the attempt is rejected with `ERR_GROUP_NOT_CANCELLABLE`. From the three pre-confirmation states the fee is zero. From `CONFIRMED`, the fee tiers on the calendar days between the logical clock's date and the group's `arrival_date`: at least 31 days out, the fee is zero; at least 15 days out — so a cancellation exactly 30 days before arrival lands in this tier — the fee is twenty percent of the invoice's `provisional_total_cents`, rounded half-up; fewer than 15 days out — a cancellation exactly 14 days before arrival lands here — the fee is fifty percent, rounded half-up. The assessed fee is stored in `cancellation_fee_cents`. Cancelling from `CONFIRMED` also voids the `PROVISIONAL` invoice, moving it to `VOID`. In every cancellation the reserved-stay cascade runs: each `RESERVED` assignment of the group moves to `CANCELLED`; each room left without any active assignment returns from `RESERVED` to `RELEASED`; and each freed bed decrements `reserved_bed_count` and increments `available_bed_count` on the building ledger.

When the group's stay is over, an admin closes it out: from `IN_HOUSE` to `DEPARTED`, permitted only when every stay assignment of the group sits in a terminal state — `CHECKED_OUT`, `NO_SHOW`, or `CANCELLED`. Finalization then settles the account. A `FinanceOfficer` finalizes the invoice, moving `PROVISIONAL` to `FINALIZED`, permitted only while the group is `DEPARTED` — otherwise `ERR_INVOICE_NOT_FINALIZABLE`. Finalization writes `final_bed_night_subtotal_cents` per the final variant above; `linen_charge_cents` as the sum of `loss_charge_cents` over all of the group's linen issues regardless of their status; `key_charge_cents` as the sum of `late_fee_cents` plus `lost_fee_cents` over the group's key credentials; and `damage_charge_cents` as the sum of `assessed_total_cents` over the group's `BILLED` damage assessments. The `total_cents` is the sum of those four components, `balance_due_cents` is the total minus the group's `deposit_paid_cents`, and `finalized_at` is stamped.

Payment closes the loop. Recording a payment is legal only on a `FINALIZED` invoice — an attempt against an invoice already `PAID` (or one `VOID`) is rejected with `ERR_INVOICE_ALREADY_PAID` — and the tendered `amount_cents` must equal `balance_due_cents` exactly, else `ERR_PAYMENT_AMOUNT_MISMATCH`. On success the invoice moves to `PAID`, `paid_at` is stamped from the clock, and the group bubbles from `DEPARTED` to its terminal `CLOSED` state.

### 3.10. Maintenance Windows, Fall Readiness, and Revenue Allocation

Facilities work between groups is planned as **MaintenanceWindow** resources on a building. Creation — by a `FacilitiesManager` or admin — is the second OCC-guarded write (§2.7): the request carries `start_date`, `end_date`, an optional `buffer_days` defaulting to one (zero or more), and `expected_building_version`. The end date must fall on or after the start date, else `ERR_DATE_RANGE_INVALID`. The system derives the inclusive blocked interval: `blocked_start_date` is `buffer_days` before `start_date`, and `blocked_end_date` is `buffer_days` after `end_date`. A new window begins `PLANNED`, and its creation increments the building's `version`.

Confirming a window moves `PLANNED` to `CONFIRMED` and runs its checks in order: the building must be `RELEASED`, `TURN_ACTIVE`, or `FALL_PREP` (else `ERR_INVALID_STATE`); then the conflict check — the inclusive blocked interval must not intersect the occupied nights of any `RESERVED` or `CHECKED_IN` assignment in the building (a stay occupies each night from its check-in date through the day before its checkout date), nor the blocked interval of any other `CONFIRMED` or `IN_PROGRESS` window on the same building, else `ERR_MAINTENANCE_CONFLICT`; then the fall-deadline check — `blocked_end_date` must be strictly before the building's `fall_opening_date`, with equality failing as `ERR_FALL_DEADLINE_IMMINENT`. Starting the window moves `CONFIRMED` to `IN_PROGRESS`, legal only on or after `start_date` by the logical clock (earlier starts fail with `ERR_OUTSIDE_CHECKIN_WINDOW`); the start cascades every room of the building in `RELEASED` or `READY` to `OUT_OF_SERVICE`, stamping each room's `out_of_service_window_id` with the window's id and raising `out_of_service_room_count` by the number of rooms taken. Completing the window moves `IN_PROGRESS` to its terminal `COMPLETED` state and restores every room holding that window's id from `OUT_OF_SERVICE` to `READY`, clearing `out_of_service_window_id` and lowering the count by the rooms restored; cancelling a window from `PLANNED` or `CONFIRMED` terminates it as `CANCELLED`, restoring any rooms it holds in the same way. These floor states feed the season close of §3.1: certifying fall readiness is impossible while `out_of_service_room_count` is non-zero or any window remains `CONFIRMED` or `IN_PROGRESS`.

The fiscal season closes with an **AllocationRun**, a waterfall over settled revenue. A `FinanceOfficer` creates an allocation run on a building with a `period_start` and `period_end` — the period end is exclusive, and must not precede the start, else `ERR_DATE_RANGE_INVALID`. The run's `gross_cents` is the sum of `total_cents` over `PAID` invoices of groups hosted by the building whose `paid_at` falls on or after `period_start` and strictly before `period_end`; an empty set yields zero. The waterfall then evaluates in a pinned order: first `overhead_cents` is twelve percent of gross, rounded half-up; second `reserve_cents` is eight percent of gross-minus-overhead, rounded half-up — the reserve keys off the net-of-overhead remainder, never the gross; third `ops_cents` is whatever remains, the remainder bucket absorbing any rounding drift. The three buckets always sum to gross exactly. A run begins `OPEN`; locking it moves it to its terminal `LOCKED` state and freezes the bucket values.

## 4. Endpoint Definitions

Operations that create a new resource — a building, room, conference group, participant, rooming-list revision, damage report, screening, linen issue, key credential, maintenance window, or allocation run — return `201 Created`. Reads, lifecycle actions, and other modifications of existing resources return `200 OK`. Successful responses carry the affected resource in the envelope's `data` field (§2.2).

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/buildings` | Create a building (initial status `ACADEMIC_USE`) | ConferenceServicesAdmin |
| GET | `/buildings` | List buildings with pagination | ConferenceServicesAdmin, FacilitiesManager, HousekeepingSupervisor, FinanceOfficer, ScreeningReviewer, ClientCoordinator |
| GET | `/buildings/{id}` | Fetch one building (includes version and counters) | ConferenceServicesAdmin, FacilitiesManager, HousekeepingSupervisor, FinanceOfficer, ScreeningReviewer, ClientCoordinator |
| POST | `/buildings/{id}/initiate-release` | `ACADEMIC_USE` → `RELEASE_REVIEW` | FacilitiesManager, ConferenceServicesAdmin |
| POST | `/buildings/{id}/confirm-release` | `RELEASE_REVIEW` → `RELEASED`; cascades rooms to `RELEASED`; freezes released bed count and key pool | FacilitiesManager, ConferenceServicesAdmin |
| POST | `/buildings/{id}/abort-release` | `RELEASE_REVIEW` → `ACADEMIC_USE` | FacilitiesManager, ConferenceServicesAdmin |
| POST | `/buildings/{id}/begin-turn-season` | `RELEASED` → `TURN_ACTIVE` | FacilitiesManager, ConferenceServicesAdmin |
| POST | `/buildings/{id}/begin-fall-prep` | `TURN_ACTIVE` → `FALL_PREP`; requires no active stays and no open turn tasks | FacilitiesManager, ConferenceServicesAdmin |
| POST | `/buildings/{id}/certify-fall-ready` | `FALL_PREP` → `READY_FOR_FALL`; requires zero out-of-service rooms and no open windows | FacilitiesManager, ConferenceServicesAdmin |
| POST | `/buildings/{id}/reopen-academic` | `READY_FOR_FALL` → `ACADEMIC_USE`; closes the season cycle, resets counters, returns rooms to `ACADEMIC_OCCUPIED` | FacilitiesManager, ConferenceServicesAdmin |
| POST | `/buildings/{id}/rooms` | Create a room (initial status `ACADEMIC_OCCUPIED`) | FacilitiesManager, ConferenceServicesAdmin |
| GET | `/buildings/{id}/rooms` | List rooms of a building | ConferenceServicesAdmin, FacilitiesManager, HousekeepingSupervisor, FinanceOfficer, ScreeningReviewer, ClientCoordinator |
| GET | `/rooms/{id}` | Fetch one room (includes `active_turn_task_id`) | ConferenceServicesAdmin, FacilitiesManager, HousekeepingSupervisor, FinanceOfficer, ScreeningReviewer, ClientCoordinator |
| GET | `/rooms/{id}/turn-tasks` | List turn tasks of a room | ConferenceServicesAdmin, FacilitiesManager, HousekeepingSupervisor, FinanceOfficer, ScreeningReviewer, ClientCoordinator |
| GET | `/turn-tasks/{id}` | Fetch one turn task | ConferenceServicesAdmin, FacilitiesManager, HousekeepingSupervisor, FinanceOfficer |
| POST | `/rooms/{id}/damage-assessments` | Report damage found in a room, attributed to a group; computes `estimate_total_cents` | FacilitiesManager, ConferenceServicesAdmin |
| POST | `/conference-groups` | Create a conference group contract (initial status `DRAFT`) | ConferenceServicesAdmin |
| GET | `/conference-groups` | List conference groups; optional `building_id` filter | ConferenceServicesAdmin, FacilitiesManager, HousekeepingSupervisor, FinanceOfficer |
| GET | `/conference-groups/{id}` | Fetch one group (ClientCoordinator may fetch only own group) | ConferenceServicesAdmin, FacilitiesManager, HousekeepingSupervisor, FinanceOfficer, ClientCoordinator |
| POST | `/conference-groups/{id}/record-deposit` | Increment `deposit_paid_cents` | FinanceOfficer, ConferenceServicesAdmin |
| POST | `/conference-groups/{id}/participants` | Add a participant | ClientCoordinator, ConferenceServicesAdmin |
| GET | `/conference-groups/{id}/participants` | List participants of a group; optional `role_in_group` filter | ConferenceServicesAdmin, FacilitiesManager, HousekeepingSupervisor, FinanceOfficer, ScreeningReviewer, ClientCoordinator |
| GET | `/participants/{id}` | Fetch one participant | ConferenceServicesAdmin, FacilitiesManager, HousekeepingSupervisor, FinanceOfficer, ScreeningReviewer, ClientCoordinator |
| POST | `/conference-groups/{id}/rooming-list-revisions` | Create a new rooming-list revision (OCC-guarded); supersedes the prior `ACTIVE` revision and creates `RESERVED` stay assignments | ClientCoordinator, ConferenceServicesAdmin |
| GET | `/conference-groups/{id}/rooming-list-revisions` | List revisions of a group | ConferenceServicesAdmin, FacilitiesManager, FinanceOfficer, ClientCoordinator |
| GET | `/rooming-list-revisions/{id}` | Fetch one rooming-list revision | ConferenceServicesAdmin, FacilitiesManager, FinanceOfficer, ClientCoordinator |
| POST | `/conference-groups/{id}/submit` | `DRAFT`/`RETURNED` → `SUBMITTED`; requires at least one participant | ClientCoordinator, ConferenceServicesAdmin |
| POST | `/conference-groups/{id}/return-for-revision` | `SUBMITTED` → `RETURNED` (revision loop) | ConferenceServicesAdmin |
| POST | `/conference-groups/{id}/confirm` | `SUBMITTED` → `CONFIRMED`; runs safety then fiscal checks; creates the `PROVISIONAL` invoice | ConferenceServicesAdmin |
| POST | `/conference-groups/{id}/cancel` | Cancel from `DRAFT`/`SUBMITTED`/`RETURNED`/`CONFIRMED`; tiered fee from `CONFIRMED`; cascades assignments, rooms, building counters; voids the provisional invoice | ClientCoordinator, ConferenceServicesAdmin |
| POST | `/conference-groups/{id}/close-out` | `IN_HOUSE` → `DEPARTED`; requires all assignments terminal | ConferenceServicesAdmin |
| GET | `/stay-assignments` | List stay assignments; optional `revision_id`, `group_id`, `room_id`, `participant_id`, `status` filters | ConferenceServicesAdmin, FacilitiesManager, HousekeepingSupervisor, FinanceOfficer, ClientCoordinator |
| GET | `/stay-assignments/{id}` | Fetch one stay assignment | ConferenceServicesAdmin, FacilitiesManager, HousekeepingSupervisor, FinanceOfficer, ClientCoordinator |
| POST | `/stay-assignments/{id}/check-in` | `RESERVED` → `CHECKED_IN` | ConferenceServicesAdmin |
| POST | `/stay-assignments/{id}/check-out` | `RESERVED` check-out: `CHECKED_IN` → `CHECKED_OUT`; last checkout flips the room to `NEEDS_TURN` and spawns a turn task | ConferenceServicesAdmin |
| POST | `/stay-assignments/{id}/mark-no-show` | `RESERVED` → `NO_SHOW`; only after the check-in instant plus 24 hours | ConferenceServicesAdmin |
| POST | `/stay-assignments/{id}/cancel` | `RESERVED` → `CANCELLED` (single assignment) | ClientCoordinator, ConferenceServicesAdmin |
| POST | `/turn-tasks/{id}/start` | `SCHEDULED`/`FAILED` → `IN_PROGRESS`; flips room `NEEDS_TURN` → `IN_TURN` | HousekeepingSupervisor, ConferenceServicesAdmin |
| POST | `/turn-tasks/{id}/submit-for-inspection` | `IN_PROGRESS` → `READY_FOR_INSPECTION` | HousekeepingSupervisor, ConferenceServicesAdmin |
| POST | `/turn-tasks/{id}/inspect` | `READY_FOR_INSPECTION` → `PASSED` or `FAILED`; `rework_count` of two or more restricts inspection to admins | HousekeepingSupervisor, ConferenceServicesAdmin |
| POST | `/turn-tasks/{id}/cancel` | `SCHEDULED` → `CANCELLED`; admin override leaves the room `READY` without cleaning | ConferenceServicesAdmin |
| POST | `/participants/{id}/background-screenings` | Submit a background screening (`CHAPERONE`/`STAFF` participants only) | ClientCoordinator, ConferenceServicesAdmin |
| GET | `/participants/{id}/background-screenings` | List screenings of a participant | ConferenceServicesAdmin, ScreeningReviewer, ClientCoordinator |
| GET | `/background-screenings/{id}` | Fetch one background screening | ConferenceServicesAdmin, ScreeningReviewer, ClientCoordinator |
| POST | `/background-screenings/{id}/begin-review` | `SUBMITTED` → `IN_REVIEW` | ScreeningReviewer, ConferenceServicesAdmin |
| POST | `/background-screenings/{id}/decide` | `IN_REVIEW` → `CLEARED` (outcome `CLEAR`) or `FLAGGED` (outcome `FLAG`) | ScreeningReviewer, ConferenceServicesAdmin |
| POST | `/background-screenings/{id}/appeal` | `FLAGGED` → `APPEALED` | ClientCoordinator, ConferenceServicesAdmin |
| POST | `/background-screenings/{id}/resolve-appeal` | `APPEALED` → `CLEARED` (outcome `CLEAR`) or `DENIED` (outcome `DENY`) | ScreeningReviewer, ConferenceServicesAdmin |
| POST | `/conference-groups/{id}/linen-issues` | Issue linen packs to a group | HousekeepingSupervisor, ConferenceServicesAdmin |
| GET | `/linen-issues` | List linen issues; optional `group_id`, `status` filters | ConferenceServicesAdmin, HousekeepingSupervisor, FinanceOfficer |
| GET | `/linen-issues/{id}` | Fetch one linen issue | ConferenceServicesAdmin, HousekeepingSupervisor, FinanceOfficer |
| POST | `/linen-issues/{id}/record-return` | Record returned/damaged packs; reconciles when fully accounted | HousekeepingSupervisor, ConferenceServicesAdmin |
| POST | `/conference-groups/{id}/key-credentials` | Issue a key credential; decrements the building's available key count | ConferenceServicesAdmin |
| GET | `/key-credentials` | List key credentials; optional `group_id`, `participant_id`, `status` filters | ConferenceServicesAdmin, HousekeepingSupervisor, FinanceOfficer |
| GET | `/key-credentials/{id}` | Fetch one key credential | ConferenceServicesAdmin, HousekeepingSupervisor, FinanceOfficer |
| POST | `/key-credentials/{id}/activate` | `ISSUED` → `ACTIVATED`; requires group `CONFIRMED` or `IN_HOUSE` | ConferenceServicesAdmin |
| POST | `/key-credentials/{id}/return` | `ISSUED`/`ACTIVATED` → `RETURNED`; computes the late fee; restores the key to the pool | ConferenceServicesAdmin |
| POST | `/key-credentials/{id}/report-lost` | `ISSUED`/`ACTIVATED` → `LOST`; charges the lost fee; key not restored | ConferenceServicesAdmin |
| GET | `/damage-assessments` | List damage assessments; optional `room_id`, `group_id`, `status` filters | ConferenceServicesAdmin, FacilitiesManager, FinanceOfficer, ClientCoordinator |
| GET | `/damage-assessments/{id}` | Fetch one damage assessment | ConferenceServicesAdmin, FacilitiesManager, FinanceOfficer, ClientCoordinator |
| POST | `/damage-assessments/{id}/assess` | `REPORTED` → `ASSESSED`; computes `assessed_total_cents` with pinned rounding order | FacilitiesManager, ConferenceServicesAdmin |
| POST | `/damage-assessments/{id}/bill` | `ASSESSED` → `BILLED`; requires group `IN_HOUSE` or `DEPARTED` | FinanceOfficer, ConferenceServicesAdmin |
| POST | `/damage-assessments/{id}/dispute` | `ASSESSED` → `DISPUTED` within seven calendar days of assessment | ClientCoordinator, ConferenceServicesAdmin |
| POST | `/damage-assessments/{id}/resolve` | `DISPUTED` → `BILLED` (outcome `ACCEPT`, optional adjusted lines) or `WAIVED` (outcome `WAIVE`) | FinanceOfficer, ConferenceServicesAdmin |
| GET | `/invoices` | List invoices; optional `group_id`, `status` filters | ConferenceServicesAdmin, FinanceOfficer |
| GET | `/invoices/{id}` | Fetch one invoice | ConferenceServicesAdmin, FinanceOfficer |
| POST | `/invoices/{id}/finalize` | `PROVISIONAL` → `FINALIZED`; recomputes final bed-nights plus linen/key/damage charges; requires group `DEPARTED` | FinanceOfficer, ConferenceServicesAdmin |
| POST | `/invoices/{id}/record-payment` | `FINALIZED` → `PAID`; amount must equal the balance due exactly; closes the group | FinanceOfficer, ConferenceServicesAdmin |
| POST | `/buildings/{id}/maintenance-windows` | Create a maintenance window (OCC-guarded on building version) | FacilitiesManager, ConferenceServicesAdmin |
| GET | `/buildings/{id}/maintenance-windows` | List maintenance windows of a building | ConferenceServicesAdmin, FacilitiesManager, HousekeepingSupervisor, FinanceOfficer, ClientCoordinator |
| GET | `/maintenance-windows/{id}` | Fetch one maintenance window | ConferenceServicesAdmin, FacilitiesManager, HousekeepingSupervisor, FinanceOfficer, ClientCoordinator |
| POST | `/maintenance-windows/{id}/confirm` | `PLANNED` → `CONFIRMED`; runs occupancy-conflict and fall-deadline checks | FacilitiesManager, ConferenceServicesAdmin |
| POST | `/maintenance-windows/{id}/start` | `CONFIRMED` → `IN_PROGRESS` on/after the start date; rooms go `OUT_OF_SERVICE` | FacilitiesManager, ConferenceServicesAdmin |
| POST | `/maintenance-windows/{id}/complete` | `IN_PROGRESS` → `COMPLETED`; rooms return to `READY` | FacilitiesManager, ConferenceServicesAdmin |
| POST | `/maintenance-windows/{id}/cancel` | `PLANNED`/`CONFIRMED` → `CANCELLED` | FacilitiesManager, ConferenceServicesAdmin |
| POST | `/buildings/{id}/allocation-runs` | Run the revenue waterfall for a fiscal period over the building's `PAID` invoices | FinanceOfficer, ConferenceServicesAdmin |
| GET | `/buildings/{id}/allocation-runs` | List allocation runs of a building | ConferenceServicesAdmin, FinanceOfficer |
| GET | `/allocation-runs/{id}` | Fetch one allocation run | ConferenceServicesAdmin, FinanceOfficer |
| POST | `/allocation-runs/{id}/lock` | `OPEN` → `LOCKED`; freezes bucket values | FinanceOfficer, ConferenceServicesAdmin |
| POST | `/_clock/set_current_utc` | Set the logical clock (test-driving endpoint); startup default is exactly `2026-05-01T00:00:00Z` | ConferenceServicesAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_TURN_REWORK_ESCALATION` | 403 Forbidden |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_DATE_RANGE_INVALID` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_BUILDING_NOT_RELEASED` | 409 Conflict |
| `ERR_ROOM_NOT_RESERVABLE` | 409 Conflict |
| `ERR_GROUP_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_INVOICE_NOT_FINALIZABLE` | 409 Conflict |
| `ERR_INVOICE_ALREADY_PAID` | 409 Conflict |
| `ERR_DAMAGE_NOT_ASSESSED` | 409 Conflict |
| `ERR_REVISION_SUPERSEDED` | 409 Conflict |
| `ERR_CHAPERONE_RATIO_UNMET` | 422 Unprocessable Entity |
| `ERR_SCREENING_NOT_CLEARED` | 422 Unprocessable Entity |
| `ERR_SCREENING_EXPIRED` | 422 Unprocessable Entity |
| `ERR_SCREENING_NOT_REQUIRED` | 422 Unprocessable Entity |
| `ERR_OCCUPANCY_OVERLAP` | 409 Conflict |
| `ERR_TURN_WINDOW_TOO_SHORT` | 422 Unprocessable Entity |
| `ERR_MAINTENANCE_CONFLICT` | 409 Conflict |
| `ERR_FALL_DEADLINE_IMMINENT` | 422 Unprocessable Entity |
| `ERR_OUTSIDE_CHECKIN_WINDOW` | 422 Unprocessable Entity |
| `ERR_DISPUTE_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_ROOMING_LIST_REQUIRED` | 422 Unprocessable Entity |
| `ERR_CONTRACTED_BED_MISMATCH` | 422 Unprocessable Entity |
| `ERR_ROOM_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_KEY_INVENTORY_EXHAUSTED` | 422 Unprocessable Entity |
| `ERR_LINEN_OVERRETURN` | 422 Unprocessable Entity |
| `ERR_DEPOSIT_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 422 Unprocessable Entity |
