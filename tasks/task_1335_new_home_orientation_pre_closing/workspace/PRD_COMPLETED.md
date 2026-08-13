# New Home Orientation API — Product Requirements Document

## 1. Introduction

In the final weeks before a new home closes, the builder's customer care organization runs a structured hand-over: an orientation appointment at which the home's major systems are demonstrated to the buyer, deficiencies are identified and classified as warrantable or cosmetic, every item is decided for completion before or after closing, an escrow holdback secures the cost of work left open at closing, the buyer formally acknowledges the outcome, repaired items are re-inspected and signed off, and a post-orientation survey feeds community-level quality trends. This document specifies the API that orchestrates that pipeline for a builder operating multiple communities, each carrying its own scheduling, escrow, and survey policy.

Two design commitments shape every workflow that follows. First, closing readiness is a derived property of the home record: the server compounds the state of the home's acknowledgment signature, its open deficiency counts, and its escrow holdback, letting cascades ripple through related records inside the same request — clients react to those derivations rather than computing them. Second, every temporal gate in the system reads a logical clock instead of wall-clock time, so scheduling windows, start windows, survey windows, and visit timing are fully deterministic. Segregation of duties keeps the representative conducting an orientation from verifying that appointment's attendees, and a small set of version-sensitive writes is protected by optimistic concurrency control.

## 2. Global Specifications & System-Wide Principles

This section defines the rules, principles, and boilerplate that apply uniformly across the API. All business endpoints are mounted under the `/api` prefix; the logical-clock control capability described in §2.4 is the single exception.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their operational capacity. Three roles exist, spelled exactly as follows: `CustomerCareManager`, `CustomerCareRep`, and `Homebuyer`. A request whose role header is missing or does not name one of the declared roles — or whose `X-User-ID` header is missing — is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not permitted for the target operation is rejected with `ERR_FORBIDDEN` (HTTP 403).

Role identity binds to stored entities differently per role:

- When `X-User-Role` is `CustomerCareRep`, `X-User-ID` is the `id` of the acting `CustomerCareRep`; ownership checks on any resource that references a `CustomerCareRep` compare the resource's foreign-key field to `X-User-ID` — most visibly the segregation-of-duties check that bars a representative from deciding attendee verification on an appointment whose `rep_id` equals their own `X-User-ID`. Apart from that segregation check, no representative-scoped write binds `X-User-ID` to the target's `rep_id` — any representative may start, mark the checklist of, complete, reschedule, or cancel any appointment, record attendees, manage deficiency items, and schedule or complete visits.
- When `X-User-Role` is `Homebuyer`, `X-User-ID` is the `id` of the acting `Homebuyer`; every buyer-scoped write compares the target home's `primary_buyer_id` to `X-User-ID` and rejects a mismatch with `ERR_FORBIDDEN` (HTTP 403).
- When `X-User-Role` is `CustomerCareManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `decided_by_user_id` on an `Attendee` the manager verifies — but never compares it to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; when omitted it defaults to 10, and it accepts values from a minimum of 1 to a maximum of 100. The `offset` parameter sets how many items to skip and defaults to 0. A non-integer `limit` or `offset`, a `limit` outside the 1-to-100 range, or a negative `offset` is rejected with `ERR_VALIDATION` (HTTP 400).

Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order, with ties broken by creation order.

The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Temporal Determinism

A server-side logical clock is the single source of "now" for every temporal rule in this document — orientation scheduling windows, the appointment start window, the survey submission window, and re-inspection visit timing all read it, and the server must never fall back to wall-clock time. Before any client sets it, the clock starts at exactly 2026-08-01T00:00:00Z. A `CustomerCareManager` moves it through a test-driving capability that accepts a target instant `to_iso8601` and answers with the resulting `current_utc`. System-stamped timestamps throughout the API — `created_at`, `updated_at`, `completed_at`, `signed_at`, `signed_off_at`, `submitted_at`, `window_closes_at`, `demonstrated_at` — are all taken from this clock. Client-supplied datetime strings such as `scheduled_start` and `closing_date` are stored and echoed back verbatim as submitted; all computations parse them.

### 2.5. Common Resource Properties

All eleven resources — `Community`, `Homebuyer`, `CustomerCareRep`, `Home`, `OrientationAppointment`, `Attendee`, `DeficiencyItem`, `ReinspectionVisit`, `EscrowHoldback`, `AcknowledgmentSignature`, and `FeedbackSurvey` — carry a standard set of system-managed fields:

- `id` (string): a server-minted unique identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 timestamp in UTC taken from the logical clock, set once at creation; whole-second instants render without a fractional part (e.g. `2026-08-01T00:00:00Z`), while sub-second instants render with three fractional digits.
- `updated_at` (string): an ISO 8601 UTC timestamp in the same format, refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that starts at 1 on creation and increments by one on every mutation, including mutations caused by server-side cascades rather than a direct client call on that resource. It is the basis for optimistic concurrency control.

### 2.6. Money, Scores, and Rounding Discipline

All monetary values are integer amounts of cents, carried in `_cents`-suffixed fields such as `sales_price_cents`, `estimated_repair_cost_cents`, `holdback_min_cents`, `holdback_max_cents`, `holdback_amount_cents`, `final_holdback_cents`, `funded_amount_cents`, `released_amount_cents`, and `remaining_amount_cents`. A community's `holdback_cost_multiplier` is a unit-less factor applied to per-item repair costs. Rounding discipline is pinned and not subject to implementation preference:

- Escrow holdback contributions are rounded half up to a whole cent per deficiency item before any summation; summation and clamping happen only after per-line rounding.
- Survey composite scores and quality-trend averages are rounded half up to exactly two decimal places.
- An average computed over an empty set is null, never zero.

### 2.7. Optimistic Concurrency Control

Exactly three write operations are guarded by optimistic concurrency control, each keyed to the current `version` of a parent entity:

1. Rescheduling an orientation appointment — `POST /api/appointments/{id}/reschedule` — requires `expected_appointment_version`, carrying the client's last observed `version` of the appointment. If the appointment's current version differs, the request is rejected with `ERR_STALE_VERSION` (HTTP 412): another write has advanced the appointment since the client last read it.
2. Releasing escrow funds — `POST /api/escrow-holdbacks/{id}/release` — requires `expected_escrow_version` matching the escrow's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), because any decide-driven recompute or prior release advances the escrow version and invalidates the amount basis the client saw.
3. Moving a home's closing date — `POST /api/homes/{id}/reschedule-closing` — requires `expected_home_version` matching the home's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), since every cascade that touches the home bumps its version and a stale expectation means the closing context the client observed no longer holds.

Endpoints not listed here do not accept a version field. In the validation order of §2.8, the version check fires immediately after path existence and, where the endpoint has one, the state gate — before any temporal, structural, or fiscal gate. The expected-version field must be an integer; a numeric string is coerced to an integer.

### 2.8. Request Validation Order

When a request would violate several rules at once, the server evaluates its gates in a fixed order and reports only the earliest failure. The order is:

1. Authentication — the `X-User-Role` header is present and names a declared role and the `X-User-ID` header is present; otherwise `ERR_UNAUTHENTICATED` (HTTP 401).
2. Role authorization — the role is permitted for the endpoint per §2.1 and §4; otherwise `ERR_FORBIDDEN` (HTTP 403).
3. Entity-backed ownership — for buyer-scoped operations (deficiency withdrawal, repair sign-off, acknowledgment response, survey submission), `X-User-ID` must equal the home's `primary_buyer_id`; otherwise `ERR_FORBIDDEN` (HTTP 403).
4. Request schema — required fields are present, types and enum members are valid, and ratings lie within their 1-to-5 range; otherwise `ERR_VALIDATION` (HTTP 400).
5. Path existence — every identifier in the URL resolves to an existing resource; otherwise `ERR_NOT_FOUND` (HTTP 404).
6. Body referential integrity — body-supplied foreign keys resolve and are mutually consistent; otherwise `ERR_REFERENCED_ENTITY_NOT_FOUND` (HTTP 422).
7. State — the target entity is in a valid from-state for the requested transition; otherwise `ERR_INVALID_STATE` (HTTP 409).
8. Compliance — segregation of duties on attendee verification and the attendee identity rules; otherwise `ERR_SELF_VERIFICATION_FORBIDDEN` (HTTP 403), `ERR_POA_DOCUMENT_REQUIRED` (HTTP 422), or `ERR_ATTENDEE_IDENTITY_INVALID` (HTTP 422).
9. Temporal gates — schedule-in-past, the orientation scheduling window, the appointment start window, the survey window, and visit completion timing, in that order; otherwise `ERR_OUTSIDE_SCHEDULING_WINDOW` or `ERR_SCHEDULE_IN_PAST` (HTTP 422), or `ERR_APPOINTMENT_START_WINDOW`, `ERR_SURVEY_EXPIRED`, or `ERR_VISIT_TOO_EARLY` (HTTP 409).
10. Structural constraints — one open appointment per home, representative schedule overlap, daily visit capacity, the reschedule cap, checklist and attendee completion gates, cosmetic photo evidence, withdrawal eligibility, representative activity, and email uniqueness; otherwise `ERR_OPEN_APPOINTMENT_EXISTS`, `ERR_REP_SCHEDULE_CONFLICT`, `ERR_VISIT_OVERLAP`, `ERR_DAILY_CAPACITY_EXCEEDED`, `ERR_RESCHEDULE_LIMIT_REACHED`, `ERR_CHECKLIST_INCOMPLETE`, or `ERR_ATTENDEE_REQUIREMENT_UNMET` (HTTP 409), `ERR_PHOTO_EVIDENCE_REQUIRED` (HTTP 422), or `ERR_WITHDRAW_NOT_ALLOWED`, `ERR_REP_INACTIVE`, or `ERR_DUPLICATE_EMAIL` (HTTP 409).
11. Fiscal gates — the escrow release must have a positive releasable amount and closing funding must match the final holdback; otherwise `ERR_NO_RELEASABLE_AMOUNT` (HTTP 409) or `ERR_HOLDBACK_FUNDING_MISMATCH` (HTTP 422).

A worked example: a request with a malformed payload aimed at a non-existent home is rejected with `ERR_VALIDATION`, not `ERR_NOT_FOUND`, because schema validation sits earlier in the order; likewise an authenticated buyer acting on another buyer's home hears `ERR_FORBIDDEN` before any state or temporal rule is consulted.

### 2.9. Cascading Consistency, Derived Fields, and Identifier Resolution

A home's `status` is largely a server-maintained derivation. Beyond the explicit mark-ready and close operations, clients never set it directly: intermediate values arise from cascades — appointment confirmation and cancellation, appointment completion, deficiency identification, signature responses, and deficiency count recomputation all move the home without a home-targeted request. Whenever such a cascade mutates a resource, that resource's `updated_at` refreshes and its `version` increments, even though no client called an endpoint on it. The same rule covers the server's computed fields — `open_before_closing_count` and `open_after_closing_count` on the home, the four checklist counters on the appointment, and `remaining_amount_cents` on the escrow — which are recomputed whenever an underlying fact changes.

For any URL containing more than one identifier, the server validates identifiers left to right and rejects the request with `ERR_NOT_FOUND` at the first identifier that does not resolve. This applies to the checklist-marking path, where the appointment identifier is resolved before the `system_key` path segment is examined.

## 3. Business Logic & Workflows

### 3.1. Community Policy, Registries, and Bringing a Home Under Care

Everything begins with the **Community**, the policy envelope for a group of homes. A `CustomerCareManager` creates one with a `name` and, optionally, overrides for its policy knobs: `holdback_cost_multiplier` (default 1.5), `holdback_min_cents` (default 50000), `holdback_max_cents` (default 1000000), `orientation_min_days_before_closing` (default 5), `orientation_max_days_before_closing` (default 30), `appointment_duration_minutes` (default 120), `appointment_buffer_minutes` (default 30), `survey_window_days` (default 14), and `cosmetic_photo_required` (default true). Every home registered under the community inherits this policy.

Two registries serve the pipeline. A `CustomerCareManager` registers a **Homebuyer** with `full_name`, `email`, and an optional `phone`; the email must be unique across homebuyers — an exact, case-sensitive string comparison — and a duplicate is rejected with `ERR_DUPLICATE_EMAIL`. The same manager registers a **CustomerCareRep** with `full_name`, `email` (likewise unique, with the same `ERR_DUPLICATE_EMAIL` consequence), an `active` flag defaulting to true, and `daily_visit_capacity_minutes` defaulting to 240. An inactive representative cannot take on new work: naming one at appointment or visit creation is rejected with `ERR_REP_INACTIVE`.

A `CustomerCareManager` then brings a **Home** under care by supplying `community_id`, `primary_buyer_id`, `lot_number`, `address`, `sales_price_cents`, and `closing_date`. Both references must resolve to existing records — a dangling `community_id`, `primary_buyer_id`, or any other body foreign key is rejected with `ERR_REFERENCED_ENTITY_NOT_FOUND`. A new home starts in `UNDER_CONSTRUCTION` with `open_before_closing_count` and `open_after_closing_count` at zero. When construction is far enough along, the manager marks the home ready, moving it from `UNDER_CONSTRUCTION` to `PRE_CLOSE_READY` and incrementing the home's `version`. Plans change: the manager may also move the `closing_date`, a write guarded by optimistic concurrency — the request must carry `expected_home_version` matching the home's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` as described in §2.7. Homes may be listed and filtered by `community_id`, `primary_buyer_id`, or `status`.

### 3.2. Scheduling the Orientation Appointment

With a home `PRE_CLOSE_READY`, a `CustomerCareRep` schedules the orientation by providing `home_id`, `rep_id`, `scheduled_start`, and an optional `duration_minutes` that defaults to the community's `appointment_duration_minutes` when omitted. Creation is gated by a battery of checks. The referenced home must be `PRE_CLOSE_READY` for a first orientation or `ORIENTED` for a re-orientation; any other home status rejects creation with `ERR_INVALID_STATE`. The named representative must be active, and the home must not already have an appointment in `REQUESTED`, `CONFIRMED`, or `IN_PROGRESS` — a second open appointment is rejected with `ERR_OPEN_APPOINTMENT_EXISTS`.

Two scheduling calculations run at creation and again at every reschedule. The **window check** measures the gap between the appointment's `scheduled_start` and the home's `closing_date` in whole minutes, counting 1,440 minutes per day: the gap must be at least the community's `orientation_min_days_before_closing` days and at most its `orientation_max_days_before_closing` days, with both bounds inclusive — an orientation scheduled exactly the minimum number of days before closing is acceptable, while one minute less is rejected with `ERR_OUTSIDE_SCHEDULING_WINDOW`. Independently, `scheduled_start` must lie strictly after the current logical-clock instant; a start in the past or at the present instant is rejected with `ERR_SCHEDULE_IN_PAST`, and this schedule-in-past check is evaluated before the window check.

The **overlap check** protects a representative's calendar. Each of the rep's existing orientation appointments in `REQUESTED`, `CONFIRMED`, or `IN_PROGRESS` occupies a closed interval that begins `appointment_buffer_minutes` before its start and ends `appointment_buffer_minutes` after its finish. The new appointment conflicts — and is rejected with `ERR_REP_SCHEDULE_CONFLICT` — whenever its own buffer-extended interval touches or overlaps an existing one; because the intervals are closed, two appointments whose extended edges merely touch still count as a conflict. Re-inspection visits are never part of this check: orientation crews and visit crews are independent, and the two calendars do not interfere.

A created appointment lands in `REQUESTED`. Confirmation by a `CustomerCareManager` moves it `REQUESTED` → `CONFIRMED` and flips the home — whether it was `PRE_CLOSE_READY` or `ORIENTED` — to `ORIENTATION_SCHEDULED`. Rescheduling, available from either `REQUESTED` or `CONFIRMED` with identical rules, is a representative's OCC-guarded write: the request carries the new `scheduled_start`, an optional new `duration_minutes`, and `expected_appointment_version`; a stale version is rejected with `ERR_STALE_VERSION`, a `reschedule_count` that has already reached 3 is rejected with `ERR_RESCHEDULE_LIMIT_REACHED`, and the new start is re-validated against the window and overlap rules exactly as at creation. A successful reschedule updates the schedule, increments `reschedule_count` by one, and bumps the appointment's `version`.

Cancellation is shared between `CustomerCareRep` and `CustomerCareManager` and accepts an optional `reason` of `BUYER_NO_SHOW`, `BUYER_REQUEST`, or `BUILDER_DELAY`, which is recorded in `cancel_reason`. From `REQUESTED`, cancelling with any reason other than `BUYER_NO_SHOW` — or with the reason omitted — lands in `CANCELLED`, while a cancel carrying reason `BUYER_NO_SHOW` against a still-`REQUESTED` appointment is rejected with `ERR_INVALID_STATE`. From `CONFIRMED`, a cancel carrying reason `BUYER_NO_SHOW` lands in `NO_SHOW`, while any other reason or an omitted reason lands in `CANCELLED`; in both confirmed cases the home reverts from `ORIENTATION_SCHEDULED` to `PRE_CLOSE_READY`. `COMPLETED`, `CANCELLED`, and `NO_SHOW` are terminal. Appointments may be listed filtered by `home_id`, `rep_id`, or `status`.

### 3.3. Conducting the Walkthrough: Checklist, Attendees, and Completion

Starting the appointment is the conducting representative's act, allowed only while the logical clock sits within a closed window that opens 30 minutes before `scheduled_start` and closes `duration_minutes` after it; an attempt outside that window is rejected with `ERR_APPOINTMENT_START_WINDOW`. Starting moves the appointment `CONFIRMED` → `IN_PROGRESS` and seeds `checklist_items` from a fixed six-entry catalog: `HVAC`, `PLUMBING`, `ELECTRICAL`, `APPLIANCES`, `EXTERIOR`, and `SAFETY`. Every entry carries a `system_key`, a human-readable `label`, an `is_required` flag — true for all except `APPLIANCES` — a `demonstration_status` beginning at `PENDING`, and a `demonstrated_at` timestamp that stays unset until demonstration. From this point the appointment reports `checklist_total_count` as 6 (it is 0 before the start), with `checklist_demonstrated_count`, `checklist_pending_count`, and `checklist_skipped_count` derived from the entries; reading an appointment returns the embedded checklist alongside the rest of the record.

During the walkthrough the representative marks each entry's `outcome` as `DEMONSTRATED`, `SKIPPED`, or `PENDING` — the last acting as a compensating reset when a demonstration must be unwound. Marking an entry `DEMONSTRATED` stamps its `demonstrated_at`; marking `SKIPPED` or `PENDING` clears it. Every mark recomputes the checklist counters and increments the appointment's `version`.

Attendance is recorded by the representative with `appointment_id`, an `attendee_type` of `BUYER`, `CO_BUYER`, or `POA_PROXY`, and the identity fields that type demands; the appointment's status is not gated at recording time. A `BUYER` or `CO_BUYER` attendee requires a resolvable `buyer_id` and forbids the proxy fields; a `POA_PROXY` attendee requires `proxy_name` and `poa_document_ref` and forbids `buyer_id`. A proxy missing its name or document reference is rejected with `ERR_POA_DOCUMENT_REQUIRED`; a `buyer_id` present on a proxy, absent on a buyer-type attendee, or proxy fields present on a buyer-type attendee are all rejected with `ERR_ATTENDEE_IDENTITY_INVALID`. New attendees start with `verification_status` `PENDING`.

Verification is decided by a `CustomerCareRep` or `CustomerCareManager` submitting a `decision` of `VERIFIED` or `REJECTED`, with a `rejection_reason` recorded when rejecting. The appointment must be `CONFIRMED` or `IN_PROGRESS` — deciding against an appointment in any other status, or re-deciding an attendee who has already reached the terminal `VERIFIED` or `REJECTED` states, is rejected with `ERR_INVALID_STATE`. Segregation of duties applies at this gate: when the actor is a `CustomerCareRep`, their `X-User-ID` must differ from the appointment's `rep_id`, and a violation is rejected with `ERR_SELF_VERIFICATION_FORBIDDEN`; a `CustomerCareManager` is exempt from the segregation rule. Whichever way the decision goes, `decided_by_user_id` is recorded and the attendee's `version` increments. Attendees may be listed filtered by `appointment_id`, `buyer_id`, or `verification_status`.

Completion gates the whole pipeline. The conducting representative may complete the appointment — moving it `IN_PROGRESS` → `COMPLETED` — only when two conditions hold. First, every checklist entry with `is_required` true must be `DEMONSTRATED` and no entry may remain `PENDING`; the optional `APPLIANCES` entry may be `SKIPPED` but never left pending, and a shortfall is rejected with `ERR_CHECKLIST_INCOMPLETE`. Second, at least one `VERIFIED` attendee must cover the primary buyer: either an attendee of type `BUYER` or `CO_BUYER` whose `buyer_id` equals the home's `primary_buyer_id`, or a `POA_PROXY` acting on the buyer's behalf; otherwise the completion is rejected with `ERR_ATTENDEE_REQUIREMENT_UNMET`. A successful completion stamps `completed_at` from the logical clock and fires a cascade within the same request: a `FeedbackSurvey` is created in `ISSUED` with its `window_closes_at` set to `completed_at` plus the community's `survey_window_days`; an `AcknowledgmentSignature` is created in `PENDING` only if none exists for the home, an existing record being left untouched; and the home moves from `ORIENTATION_SCHEDULED` to `ORIENTED`, which itself provisions the escrow holdback described in §3.7. The appointment's `version` increments.

### 3.4. Deficiency Identification, Classification, and the Before/After Decision

Deficiencies surface during or after the walkthrough. A `CustomerCareRep` identifies one with `home_id`, `appointment_id`, an optional `system_key` drawn from `HVAC`, `PLUMBING`, `ELECTRICAL`, `APPLIANCES`, `EXTERIOR`, `SAFETY`, or `OTHER`, a short `title`, and an optional `description`. The referenced appointment must belong to the same home — a mismatch is rejected with `ERR_REFERENCED_ENTITY_NOT_FOUND` — and must be `IN_PROGRESS` or `COMPLETED`; identifying against an appointment in any other status is rejected with `ERR_INVALID_STATE`. The new item lands in `IDENTIFIED`, and identification carries a deliberate shock wave: if the home's acknowledgment signature is currently `SIGNED` it immediately becomes `STALE`, and a home sitting in `ACKNOWLEDGED` or `READY_TO_CLOSE` reverts to `ORIENTED`, forcing the buyer to re-acknowledge the changed picture.

Classification, also by the representative, moves the item `IDENTIFIED` → `CLASSIFIED` and records a `classification` of `WARRANTABLE` or `COSMETIC` — any other value is rejected with `ERR_VALIDATION` — together with `estimated_repair_cost_cents`, which must be zero or greater, and an optional `photo_evidence_ref`. When the classification is `COSMETIC` and the community's `cosmetic_photo_required` flag is true, `photo_evidence_ref` is mandatory and its absence is rejected with `ERR_PHOTO_EVIDENCE_REQUIRED`.

The before/after decision belongs to the `CustomerCareManager`, who sets `resolution` to `COMPLETE_BEFORE_CLOSING` or `COMPLETE_AFTER_CLOSING`, moving the item `CLASSIFIED` → `DECIDED`. The same operation serves an item already `DECIDED`, overwriting the resolution — a `DECIDED` → `DECIDED` reversal. Both forms recompute the home's open-item counts and re-evaluate its readiness, and both drive the escrow recompute of §3.7 whenever a non-`VOIDED` holdback exists: the escrow flips `DRAFT` → `ACTIVE` when the recomputed amount rises above zero and `ACTIVE` → `VOIDED` when it returns to zero pre-close. The reversal is compensating with exact symmetry — changing an item from after-closing to before-closing removes precisely the contribution that the opposite change added.

Two counters summarize the home's exposure. `open_before_closing_count` tallies the home's items whose `resolution` is `COMPLETE_BEFORE_CLOSING` and whose status is one of `DECIDED`, `IN_REPAIR`, `READY_FOR_REINSPECTION`, or `VERIFIED`; `open_after_closing_count` tallies the same four statuses for `COMPLETE_AFTER_CLOSING` items, excluding anything already `SIGNED_OFF`. Readiness re-evaluation follows every recomputation: while the home is `ACKNOWLEDGED` with its signature still `SIGNED`, a before-closing count that reaches zero — after a sign-off, a withdrawal, or a resolution change — advances the home to `READY_TO_CLOSE`; while the home is `READY_TO_CLOSE`, a resolution change that pushes the before-closing count above zero drops it back to `ACKNOWLEDGED`.

Withdrawal is the buyer's prerogative and is checked against the home's `primary_buyer_id`, with a mismatch rejected as `ERR_FORBIDDEN`. From `IDENTIFIED`, withdrawal to `WITHDRAWN` is always permitted. From `CLASSIFIED`, only a `COSMETIC` item may be withdrawn — a `WARRANTABLE`-classified item, or any item already past `CLASSIFIED`, is rejected with `ERR_WITHDRAW_NOT_ALLOWED`. Deficiency items may be listed filtered by `home_id`, `appointment_id`, `status`, or `classification`.

### 3.5. Repair, Re-Inspection, and Buyer Sign-Off

Once a resolution exists, the repair loop begins. A `CustomerCareRep` starts repair, moving the item `DECIDED` → `IN_REPAIR`, and later marks repair complete, moving it `IN_REPAIR` → `READY_FOR_REINSPECTION`; each step recomputes the home's open-item counts.

Re-inspection is scheduled as a **ReinspectionVisit** with `home_id`, `rep_id`, a `scheduled_start` that must lie strictly after the logical clock — anything else is rejected with `ERR_SCHEDULE_IN_PAST` — and a `duration_minutes` that defaults to 60. The named representative must be active. Two capacity rules, deliberately different from the orientation rules, guard the visit calendar. Pairwise, each existing `SCHEDULED` visit of the same representative occupies a half-open interval from its start to its start plus duration: a new visit conflicts — and is rejected with `ERR_VISIT_OVERLAP` — only when it begins strictly before an existing visit ends while the existing visit begins strictly before the new one ends, so a visit starting at the exact moment another finishes is allowed. In aggregate, the durations of that representative's visits in `SCHEDULED` or `COMPLETED` falling on the same UTC calendar date, plus the new visit's duration, must not exceed `daily_visit_capacity_minutes`; a total exactly equal to the cap is allowed, while one minute beyond it is rejected with `ERR_DAILY_CAPACITY_EXCEEDED`. A created visit lands in `SCHEDULED`, and visits may be listed filtered by `home_id`, `rep_id`, or `status`.

Completing a visit applies its findings. The representative submits a `results` array in which each entry pairs a `deficiency_item_id` with an `outcome` of `PASS` or `FAIL` — malformed entries are rejected with `ERR_VALIDATION`, and an empty array is accepted and completes the visit applying no item outcomes — allowed only once the logical clock has reached the visit's `scheduled_start`; an earlier attempt is rejected with `ERR_VISIT_TOO_EARLY`. Every entry in `results` must reference a `DeficiencyItem` of the same home currently in `READY_FOR_REINSPECTION`; any other reference is rejected with `ERR_INVALID_STATE`. Each passing item moves `READY_FOR_REINSPECTION` → `VERIFIED`, while each failing item drops back `READY_FOR_REINSPECTION` → `IN_REPAIR` — the repair loop is unbounded, and an item may cycle until it passes. The visit lands in its terminal `COMPLETED` state, the home's counts recompute, and readiness is re-evaluated.

Sign-off belongs to the buyer alone, checked against the home's `primary_buyer_id` with mismatches rejected as `ERR_FORBIDDEN`. Signing off moves a `VERIFIED` item to the terminal `SIGNED_OFF`, stamps `signed_off_at` from the logical clock, recomputes the home's counts with readiness re-evaluation, and makes the item eligible for escrow release under §3.7. `SIGNED_OFF` and `WITHDRAWN` end the item's lifecycle.

### 3.6. The Acknowledgment Signature Cycle

The **AcknowledgmentSignature** is the buyer's formal assent to the orientation outcome, created in `PENDING` when an orientation appointment completes — once per home, since an existing record is left unchanged by later completions. The buyer responds by submitting a `decision` of `SIGN` or `DECLINE`, optionally accompanied by a `signature_payload`; the actor must be the home's `primary_buyer_id`, with mismatches rejected as `ERR_FORBIDDEN`, and responding on a record that is not `PENDING` or `STALE` is rejected with `ERR_INVALID_STATE`.

Signing — from `PENDING` or, in the cycle's second act, from `STALE` — moves the record to `SIGNED`: `signer_buyer_id` and `signed_at` are recorded from the acting buyer and the logical clock, any `decline_reason` is cleared, and `open_item_snapshot_count` pins the number of the home's deficiency items in non-terminal states — everything except `SIGNED_OFF` and `WITHDRAWN` — at the moment of signing. A signing while the home is `ORIENTED` flips it to `ACKNOWLEDGED`, and when the `open_before_closing_count` is already zero the home continues immediately to `READY_TO_CLOSE` in the same breath.

Declining is valid from `PENDING` only — a `DECLINE` submitted against a `STALE` record is rejected with `ERR_INVALID_STATE` — and lands the record in `DECLINED` with the buyer's `decline_reason` recorded. A `CustomerCareRep` may then re-request the acknowledgment, returning the record `DECLINED` → `PENDING`, clearing `decline_reason`, and incrementing the signature's `version`. The record's later life is reactive: identifying a new deficiency against the home turns a `SIGNED` record `STALE` and reverts the home as described in §3.4, after which the buyer may sign again with a freshly pinned snapshot — the `PENDING` → `SIGNED` → `STALE` → `SIGNED` cycle. Signature records may be listed filtered by `home_id`, `appointment_id`, `signer_buyer_id`, or `status`.

### 3.7. Escrow Holdback: Provisioning, Closing, and Release

The **EscrowHoldback** materializes without a client call: when an orientation appointment completes and flips the home to `ORIENTED`, a holdback is auto-provisioned for that home in `DRAFT` with an amount of zero — but only when no non-`VOIDED` escrow already exists for the home. Provisioning immediately runs the amount recompute, and if the computed amount exceeds zero the fresh escrow flips `DRAFT` → `ACTIVE` inside the same request.

The amount formula pins its rounding order. For each included deficiency item, `estimated_repair_cost_cents` is multiplied by the community's `holdback_cost_multiplier` and the product is rounded half up to a whole cent; only then are the per-item contributions summed. When the raw sum is zero, the holdback amount is zero. Otherwise the amount is clamped: a sum below `holdback_min_cents` is raised to that floor, and a sum above `holdback_max_cents` is capped at that ceiling. Rounding per item before summation — never once at the end — and clamping after summation is the contract; the alternate order yields different cents and is not.

Two variants of the same formula serve different moments. The **provisional** amount, stored in `holdback_amount_cents` and refreshed on every recompute, includes the home's after-closing items in `DECIDED`, `IN_REPAIR`, `READY_FOR_REINSPECTION`, `VERIFIED`, and `SIGNED_OFF` — signed-off items still count. The **final** amount, computed at closing and frozen into `final_holdback_cents`, uses the identical formula but excludes `SIGNED_OFF` items, so whenever any after-closing item was signed off before closing the two amounts diverge.

Pre-close, the escrow breathes with the decisions: a recompute that returns the amount to zero — every after-closing decision reversed — voids an `ACTIVE` holdback while the home is not yet `CLOSED`, and a later after-closing decision provisions a fresh `DRAFT` record in its place. At most one non-`VOIDED` escrow exists per home at any time, while `VOIDED` records are retained for history; escrows may be listed filtered by `home_id` or `status`.

Closing is the fiscal point of no return, performed by a `CustomerCareManager` on a home in `READY_TO_CLOSE` — any other status is rejected with `ERR_INVALID_STATE`. When a non-`VOIDED` escrow exists whose final amount exceeds zero, the request must carry `funded_holdback_cents` equal to that computed final amount — omitting it is rejected with `ERR_VALIDATION`, while a present but unequal value is rejected as `ERR_HOLDBACK_FUNDING_MISMATCH`; when no holdback is due, `funded_holdback_cents` must be omitted entirely, and supplying it is rejected with `ERR_VALIDATION`. An explicit null counts as omitted in both cases. Closing freezes `final_holdback_cents`, records `funded_amount_cents`, sets `remaining_amount_cents` to the funded amount, voids an escrow still in `DRAFT` whose final amount is zero, moves the home `READY_TO_CLOSE` → `CLOSED`, and increments the home's `version`.

Releases come after closing and are manager-only, OCC-guarded writes: the request carries `expected_escrow_version`, and a stale expectation is rejected with `ERR_STALE_VERSION` per §2.7. Releasing against a home that has not reached `CLOSED` is rejected with `ERR_INVALID_STATE`, as is any attempt on an escrow in any other status — `DRAFT`, `FULLY_RELEASED`, or `VOIDED`. The releasable amount is computed from the home's after-closing items that are `SIGNED_OFF` and not yet released, each contributing its holdback contribution, consumed oldest sign-off first — `signed_off_at` ascending, ties broken by `created_at` ascending — with the credited total capped at the remaining balance, every eligible item flipping `holdback_released` to true, and the credited total added to `released_amount_cents`. A flush rule overrides the arithmetic: if after the release no after-closing item remains in `DECIDED`, `IN_REPAIR`, `READY_FOR_REINSPECTION`, or `VERIFIED`, the entire remaining balance is released instead. When nothing is releasable — no unreleased signed-off items and no flush — or the computed release amount is zero, the request is rejected with `ERR_NO_RELEASABLE_AMOUNT`. While the remaining balance stays above zero the escrow sits in `PARTIALLY_RELEASED`; a release that drains it to zero, including a flush, moves it to the terminal `FULLY_RELEASED`. Throughout, `remaining_amount_cents` is simply `funded_amount_cents` minus `released_amount_cents`.

### 3.8. Feedback Survey and the Community Quality Trend

Completion of an orientation issues the **FeedbackSurvey** in `ISSUED`, its `window_closes_at` fixed at the appointment's `completed_at` plus the community's `survey_window_days`. The buyer — and only the buyer, with ownership checked against `primary_buyer_id` and mismatches rejected as `ERR_FORBIDDEN` — submits `overall_rating`, `systems_demo_rating`, and `timeliness_rating`, each an integer from 1 to 5 with anything outside rejected as `ERR_VALIDATION`, together with `would_recommend` and optional `comments`. Submission is honored only while the logical clock has not passed `window_closes_at`; a late submission on a still-`ISSUED` survey is rejected with `ERR_SURVEY_EXPIRED`, and submitting a survey that is no longer `ISSUED` is rejected with `ERR_INVALID_STATE`. A successful submission stamps `submitted_at`, computes `composite_score`, increments the survey's `version`, and lands the survey in its terminal `SUBMITTED` state.

The composite score blends the three ratings with fixed weights: the base is `overall_rating` multiplied by 0.5, plus `systems_demo_rating` multiplied by 0.3, plus `timeliness_rating` multiplied by 0.2. When `would_recommend` is false, a penalty of 0.5 is subtracted from the base. A detractor cap then applies: when the lowest of the three ratings is exactly 1, the composite becomes the lesser of the penalized base and 2.0; otherwise the composite is the base itself. The result is clamped into the band from 1.00 to 5.00 and finally rounded half up to two decimal places.

Surveys that outlive their window are reaped by an ops sweep a `CustomerCareManager` can invoke: every survey still `ISSUED` whose `window_closes_at` lies before the current logical-clock instant moves to the terminal `EXPIRED`, each incrementing its own `version`, and the sweep answers with `expired_count` and the list `expired_survey_ids`, ordered by `created_at` ascending. Surveys may be listed filtered by `home_id`, `appointment_id`, or `status`.

Quality rolls up per community and calendar month. Requested with a `period_month` in year-month form — a missing or malformed value is rejected with `ERR_VALIDATION` (HTTP 400) — the trend examines the half-open window from the first instant of that month up to — but not including — the first instant of the following month, and considers the community's `SUBMITTED` surveys whose `submitted_at` falls inside it. The response echoes `period_month` and reports `submitted_survey_count`, the number of those surveys, and `homes_surveyed_count`, the number of distinct homes behind them. Two weightings answer different questions, and they diverge whenever homes contribute unequal numbers of surveys. `response_weighted_avg_score` lets every survey weigh equally: the sum of their `composite_score` values divided by their count, rounded half up to two decimal places, null when the count is zero. `home_weighted_avg_score` lets every home weigh equally: each home's composite scores are first averaged into a per-home mean rounded half up to two decimal places, then those per-home means are averaged across the distinct homes with at least one survey, again rounded half up to two decimal places, and null when no home has a survey in the window. Finally, `avg_warrantable_items_per_home` divides the number of `WARRANTABLE`-classified deficiency items created on the community's homes within the window by the number of distinct homes whose orientation appointment reached `COMPLETED` with `completed_at` inside the window, rounded half up to two decimal places — null when that denominator is zero.

## 4. Endpoint Definitions

Operations that create a new resource — a community, homebuyer, representative, home, appointment, attendee, deficiency item, or re-inspection visit — return `201 Created`. All other operations, including state transitions, reads, computed reports, and the ops sweep, return `200 OK`. Request payloads, response shapes, and side effects are specified by the narratives of §2 and §3; the table below is the routing summary. "All three roles" means `CustomerCareManager`, `CustomerCareRep`, and `Homebuyer`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/communities` | Create a community with policy configuration | CustomerCareManager |
| GET | `/api/communities/{id}/quality-trend` | Computed quality trend for one calendar month, both weighting variants | All three roles |
| POST | `/api/homebuyers` | Register a homebuyer | CustomerCareManager |
| POST | `/api/reps` | Register a customer care representative | CustomerCareManager |
| POST | `/api/homes` | Create a home, starting `UNDER_CONSTRUCTION` | CustomerCareManager |
| GET | `/api/homes/{id}` | Get a home | All three roles |
| GET | `/api/homes` | List and filter homes | All three roles |
| POST | `/api/homes/{id}/mark-ready` | Move a home from `UNDER_CONSTRUCTION` to `PRE_CLOSE_READY` | CustomerCareManager |
| POST | `/api/homes/{id}/reschedule-closing` | Move the closing date (OCC on the home version) | CustomerCareManager |
| POST | `/api/homes/{id}/close` | Close a `READY_TO_CLOSE` home; freeze the final holdback and record funding | CustomerCareManager |
| POST | `/api/appointments` | Schedule an orientation appointment | CustomerCareRep |
| GET | `/api/appointments/{id}` | Get an appointment, including the embedded checklist | All three roles |
| GET | `/api/appointments` | List and filter appointments | All three roles |
| POST | `/api/appointments/{id}/confirm` | Confirm a `REQUESTED` appointment; home moves to `ORIENTATION_SCHEDULED` | CustomerCareManager |
| POST | `/api/appointments/{id}/reschedule` | Move an appointment within `REQUESTED`/`CONFIRMED` (OCC on the appointment version) | CustomerCareRep |
| POST | `/api/appointments/{id}/cancel` | Cancel; from `CONFIRMED` with reason `BUYER_NO_SHOW` lands in `NO_SHOW`, else `CANCELLED` | CustomerCareRep, CustomerCareManager |
| POST | `/api/appointments/{id}/start` | Start a `CONFIRMED` appointment; seeds the six-item demonstration checklist | CustomerCareRep |
| POST | `/api/appointments/{id}/complete` | Complete an `IN_PROGRESS` appointment; cascades survey, signature, home, and escrow | CustomerCareRep |
| POST | `/api/appointments/{id}/checklist-items/{system_key}/mark` | Set a checklist entry outcome: `DEMONSTRATED`, `SKIPPED`, or `PENDING` | CustomerCareRep |
| POST | `/api/attendees` | Record an attendee for an appointment | CustomerCareRep |
| GET | `/api/attendees/{id}` | Get an attendee | All three roles |
| GET | `/api/attendees` | List and filter attendees | All three roles |
| POST | `/api/attendees/{id}/decide-verification` | Verify or reject a `PENDING` attendee; the conducting rep is barred | CustomerCareRep, CustomerCareManager |
| POST | `/api/deficiency-items` | Identify a deficiency during or after the walkthrough | CustomerCareRep |
| GET | `/api/deficiency-items/{id}` | Get a deficiency item | All three roles |
| GET | `/api/deficiency-items` | List and filter deficiency items | All three roles |
| POST | `/api/deficiency-items/{id}/classify` | Classify an `IDENTIFIED` item as warrantable or cosmetic | CustomerCareRep |
| POST | `/api/deficiency-items/{id}/decide` | Decide or reverse the before/after-closing resolution | CustomerCareManager |
| POST | `/api/deficiency-items/{id}/start-repair` | Move a `DECIDED` item to `IN_REPAIR` | CustomerCareRep |
| POST | `/api/deficiency-items/{id}/complete-repair` | Move an `IN_REPAIR` item to `READY_FOR_REINSPECTION` | CustomerCareRep |
| POST | `/api/deficiency-items/{id}/withdraw` | Withdraw an `IDENTIFIED` item, or a `CLASSIFIED` cosmetic one | Homebuyer |
| POST | `/api/deficiency-items/{id}/sign-off` | Sign off a `VERIFIED` item, making it escrow-release eligible | Homebuyer |
| POST | `/api/reinspection-visits` | Schedule a re-inspection visit | CustomerCareRep |
| GET | `/api/reinspection-visits/{id}` | Get a re-inspection visit | All three roles |
| GET | `/api/reinspection-visits` | List and filter re-inspection visits | All three roles |
| POST | `/api/reinspection-visits/{id}/complete` | Complete a visit, applying per-item pass/fail outcomes | CustomerCareRep |
| GET | `/api/escrow-holdbacks/{id}` | Get an escrow holdback | All three roles |
| GET | `/api/escrow-holdbacks` | List and filter escrow holdbacks | All three roles |
| POST | `/api/escrow-holdbacks/{id}/release` | Release funds for signed-off items, oldest sign-off first, with flush (OCC on the escrow version) | CustomerCareManager |
| GET | `/api/acknowledgment-signatures/{id}` | Get an acknowledgment signature record | All three roles |
| GET | `/api/acknowledgment-signatures` | List and filter signature records | All three roles |
| POST | `/api/acknowledgment-signatures/{id}/respond` | Buyer responds `SIGN` or `DECLINE`; signing pins the open-item snapshot | Homebuyer |
| POST | `/api/acknowledgment-signatures/{id}/re-request` | Re-request a `DECLINED` acknowledgment, returning it to `PENDING` | CustomerCareRep |
| GET | `/api/feedback-surveys/{id}` | Get a feedback survey | All three roles |
| GET | `/api/feedback-surveys` | List and filter feedback surveys | All three roles |
| POST | `/api/feedback-surveys/{id}/submit` | Submit the survey within its window; computes the composite score | Homebuyer |
| POST | `/api/feedback-surveys/expire-due` | Ops sweep: expire every `ISSUED` survey past its window | CustomerCareManager |
| POST | `/_clock/set_current_utc` | Set the logical clock; all temporal gates read it | CustomerCareManager |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this table is the identifier-to-status summary.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCED_ENTITY_NOT_FOUND` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_SELF_VERIFICATION_FORBIDDEN` | 403 Forbidden |
| `ERR_POA_DOCUMENT_REQUIRED` | 422 Unprocessable Entity |
| `ERR_ATTENDEE_IDENTITY_INVALID` | 422 Unprocessable Entity |
| `ERR_OUTSIDE_SCHEDULING_WINDOW` | 422 Unprocessable Entity |
| `ERR_SCHEDULE_IN_PAST` | 422 Unprocessable Entity |
| `ERR_APPOINTMENT_START_WINDOW` | 409 Conflict |
| `ERR_SURVEY_EXPIRED` | 409 Conflict |
| `ERR_VISIT_TOO_EARLY` | 409 Conflict |
| `ERR_OPEN_APPOINTMENT_EXISTS` | 409 Conflict |
| `ERR_REP_SCHEDULE_CONFLICT` | 409 Conflict |
| `ERR_VISIT_OVERLAP` | 409 Conflict |
| `ERR_DAILY_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_RESCHEDULE_LIMIT_REACHED` | 409 Conflict |
| `ERR_CHECKLIST_INCOMPLETE` | 409 Conflict |
| `ERR_ATTENDEE_REQUIREMENT_UNMET` | 409 Conflict |
| `ERR_PHOTO_EVIDENCE_REQUIRED` | 422 Unprocessable Entity |
| `ERR_WITHDRAW_NOT_ALLOWED` | 409 Conflict |
| `ERR_REP_INACTIVE` | 409 Conflict |
| `ERR_DUPLICATE_EMAIL` | 409 Conflict |
| `ERR_NO_RELEASABLE_AMOUNT` | 409 Conflict |
| `ERR_HOLDBACK_FUNDING_MISMATCH` | 422 Unprocessable Entity |
