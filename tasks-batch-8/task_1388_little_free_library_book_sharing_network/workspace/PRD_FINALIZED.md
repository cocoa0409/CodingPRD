# Little Free Library Network API — Product Requirements Document

## 1. Introduction

Neighborhood book-sharing boxes thrive on trust: a steward builds and stocks a small wooden box on a front lawn, passers-by take a book and leave a book, and the whole arrangement works because someone is quietly keeping an eye on it. A regional network of these boxes multiplies both the charm and the operational burden. Stewards must be onboarded and trained, boxes must be chartered and kept honest on the public map, donated books must be graded and routed to the boxes that need them most, storm damage and vandalism must be repaired on season-aware timelines, and community complaints about content must be handled fairly — with a hard separation between the person who triages a complaint and the person who rules on it.

This document specifies the Little Free Library Network API, the coordination backbone for that regional network. It governs steward registration, training, and recognition; the full lifecycle of a library box from draft proposal through charter, activation, suspension, and decommissioning; a listing-posture system that keeps the public map trustworthy by flagging or delisting neglected or troubled boxes; a maintenance pipeline with seasonal repair deadlines and parts reimbursement; a complaint pipeline with a steward response window and segregated adjudication; book drives run with partner schools under dual approval; and the donation intake, grading, and distribution machinery that moves books from collection bins onto box shelves. All network endpoints are mounted under `/library-network`. Because the product is heavily time-driven — response windows, repair deadlines, staleness thresholds, and rolling recognition windows all depend on "now" — the server maintains a logical clock rather than trusting wall-clock time, and every timestamp, deadline, and window in this document reads that clock.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request carries two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. The declared roles are `Anonymous`, `Steward`, `SchoolLiaison`, `HubCoordinator`, `Moderator`, and `NetworkAdmin`. Endpoints whose authorized-role list includes `Anonymous` may be called without either header and are then treated as anonymous public calls; every other endpoint rejects a missing or malformed header pair, or a role string that is not one of the declared roles, with `ERR_UNAUTHENTICATED`. A `SchoolLiaison` caller carries an additional authentication burden: its `X-User-ID` must equal the `id` of an existing School, or the call fails with `ERR_UNAUTHENTICATED` before any other check.

When `X-User-Role` is `Steward`, `X-User-ID` is the `id` of the acting Steward; ownership checks on any resource that references a Steward compare the resource's steward foreign-key field to `X-User-ID`. When `X-User-Role` is `SchoolLiaison`, `X-User-ID` is the `id` of the acting School, and ownership checks compare it to the school foreign key of the resource in play. When `X-User-Role` is `HubCoordinator`, `Moderator`, or `NetworkAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example as `inspector_user_id` on an InspectionRecord, or as `triaged_by_user_id` and `resolved_by_user_id` on a Complaint — but never compares it to any entity's `id`. The `Anonymous` role is likewise opaque and simply marks unauthenticated public traffic.

Role membership alone does not authorize a call: the presented role must appear in the endpoint's authorized-role list, and a disallowed role is rejected with `ERR_UNAUTHORIZED_ROLE`. Where a shared transition endpoint restricts particular transitions to a subset of its listed roles, a disallowed role-and-transition combination is likewise rejected with `ERR_UNAUTHORIZED_ROLE`; concretely, on the box charter-status transition endpoint only a `NetworkAdmin` may request the `CHARTERED`, `SUSPENDED`, or `DECOMMISSIONED` targets, while a `Steward` caller may request only the `ACTIVE` target and only on their own suspended box. Entity-backed roles must also own the resource they act on: a `Steward` may act only on their own profile, their own boxes, drives they coordinate, and the complaints, allocations, and maintenance requests attached to their own boxes; a `SchoolLiaison` may decide only drives belonging to their own school. Ownership violations are rejected with `ERR_FORBIDDEN_OWNERSHIP`.

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

List endpoints paginate through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, accepts a minimum of 1, and is clamped at a maximum of 100. The `offset` parameter says how many items to skip and defaults to 0. Unless a more specific ordering is stated for a particular endpoint, every list endpoint returns resources sorted by `created_at` in ascending order.

The `meta` object of a list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`, so a client can always tell how many records exist in total and whether further pages remain.

### 2.4. The Logical Clock

All time in the system flows from a single server-side logical clock. At startup the logical clock reads exactly `2026-08-01T00:00:00Z`, and it must never fall back to wall-clock time. Every `created_at` stamp, every deadline, every staleness computation, and every rolling window reads this logical clock. A `NetworkAdmin`-only test-driving capability, `POST /_clock/set_current_utc`, advances the logical clock to a caller-supplied `to_iso8601` instant and answers with the resulting `current_utc`; nothing else moves time forward.

### 2.5. Resource Identity, Timestamps, and Versioning

Every primary resource exposes a standard set of system-managed properties. The `id` is a server-minted UUID with no type prefix. `created_at` records when the resource was created as an ISO 8601 UTC timestamp with three fractional digits, and `updated_at` refreshes on every mutation. The `version` is an integer that starts low and increments by one on every mutation of the resource, including cascaded mutations driven by events elsewhere in the network; clients use it for optimistic concurrency where this document names such a field.

Three record types are deliberately leaner. A TrainingCompletion, an InspectionRecord, and a RecognitionEvent carry only `id` and `created_at`: they are immutable once written, so `updated_at` and `version` are absent from them entirely.

### 2.6. Addressing Resources and Referential Integrity

When an endpoint path contains resource identifiers, the server validates their existence left to right and answers with the not-found error belonging to the first missing segment — for example `ERR_STEWARD_NOT_FOUND` when the steward segment of a nested path does not resolve, before any deeper segment is even examined. Each entity has its own not-found error: `ERR_STEWARD_NOT_FOUND`, `ERR_BOX_NOT_FOUND`, `ERR_SCHOOL_NOT_FOUND`, `ERR_DRIVE_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`, `ERR_RUN_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND`, `ERR_MAINTENANCE_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`, and `ERR_MODULE_NOT_FOUND`. A missing path identifier yields HTTP 404.

Identifiers supplied inside a request body are checked with the same entity-specific error identifiers but at a different severity: a body reference that does not resolve — say a `school_id` on drive creation, a `module_id` on a completion, a `box_id` on a complaint, or a `prerequisite_module_id` on a module — is rejected with HTTP 422 carrying the matching not-found error id. Batch creation adds two link-shape errors of its own, `ERR_DRIVE_LINK_REQUIRED` and `ERR_DRIVE_LINK_FORBIDDEN`, described with the intake workflow.

### 2.7. Optimistic Concurrency Control

Exactly two write operations participate in optimistic concurrency control, and each names its own expected-version field as a non-optional input. Creating a distribution run for a batch requires `expected_batch_version`, carrying the client's last observed `version` of that DonationBatch; if the batch's current `version` has moved past what the client observed — for instance because another writer has already created a run for the same batch — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), so the client cannot build a plan on top of a batch state it never saw. Updating a steward profile requires `expected_steward_version`, carrying the client's last observed `version` of that Steward; a mismatch with the steward's current `version` — advanced by any profile patch, status transition, or cascaded recognition recompute — is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint accepts a version field.

### 2.8. The Validation Pipeline

A request that fails several rules at once must fail predictably, so validation runs as an ordered pipeline and the first failing stage wins. The stages, in order:

1. **Authentication.** Header presence, a declared role, and the `SchoolLiaison` school-existence rule — failures are `ERR_UNAUTHENTICATED` (401).
2. **Role and ownership.** The role must be listed for the endpoint, role-restricted transition targets are enforced, and entity-backed callers must own the target — failures are `ERR_UNAUTHORIZED_ROLE` or `ERR_FORBIDDEN_OWNERSHIP` (403).
3. **Path existence.** Path identifiers resolve left to right with entity-specific 404s.
4. **Body referential integrity.** Body-referenced entities exist and are linkable — failures include `ERR_DRIVE_LINK_REQUIRED`, `ERR_DRIVE_LINK_FORBIDDEN`, and the entity-specific not-found ids at HTTP 422.
5. **State preconditions.** The target entity sits in the exact from-state the transition requires — failures are `ERR_INVALID_STATE` or `ERR_DRIVE_NOT_OPEN` (409).
6. **Cross-entity state gates.** Related entities must be in the states an operation assumes: the steward is `ACTIVE` where required (`ERR_STEWARD_NOT_ACTIVE`), a qualifying `CONFIRMED` inspection exists (`ERR_INSPECTION_REQUIRED`), an `ORIENTATION` pass exists (`ERR_ORIENTATION_REQUIRED`), the linked drive is `APPROVED` or `OPEN` (`ERR_DRIVE_NOT_APPROVED`) — all 409.
7. **Safety and segregation.** Content-policy checks on drive-linked intake (`ERR_CONTENT_POLICY_VIOLATION`, 422) and segregation-of-duties checks on complaint handling (`ERR_SEGREGATION_OF_DUTIES`, 403). This stage outranks the temporal and constraint stages below regardless of the status code involved.
8. **Temporal rules.** Drive windows, scheduling dates, reopen windows, and inspection cadence — failures are `ERR_DRIVE_WINDOW_CLOSED`, `ERR_DRIVE_WINDOW_INVALID`, `ERR_DRIVE_WINDOW_OVERLAP`, `ERR_SCHEDULE_DATE_PAST`, `ERR_REOPEN_WINDOW_EXPIRED`, and `ERR_INSPECTION_TOO_SOON` (422).
9. **Business constraints.** Capacity limits, selector outcomes, grading completeness, training rules, uniqueness, and public-visibility gates — failures include `ERR_BOX_LIMIT_REACHED`, `ERR_NO_ELIGIBLE_BOXES`, `ERR_UNGRADED_ITEMS`, `ERR_MODULE_ALREADY_PASSED`, `ERR_MODULE_INACTIVE`, `ERR_PREREQUISITE_NOT_MET`, `ERR_MODULE_CYCLE`, `ERR_EMAIL_TAKEN`, `ERR_BOX_NOT_PUBLIC` (all 422), and `ERR_PLAN_STALE` (409).
10. **Optimistic concurrency.** The expected-version fields of §2.7 — failure is `ERR_STALE_VERSION` (412).
11. **Schema and field validity.** Required fields are present, enum members are valid, and numeric ranges hold — failure is `ERR_INVALID_REQUEST` (400). This stage runs last, so a structurally malformed payload aimed at an unauthorized or stale target still reports the earlier, more meaningful failure.

### 2.9. Points, Percentages, and Pennies: Numeric Precision

Money is counted in whole cents. Reimbursement rounding is pinned to a specific order: every parts line is rounded half-up to whole cents first, and only then are the rounded line amounts summed; summing raw line products and rounding once at the end is forbidden because it yields different cents. The labor component is rounded half-up to whole cents once, as a single figure. Percentages used by the book-drive metrics are integers produced by floor division — the fractional remainder is always discarded, never rounded up. Day counts, such as staleness, are the floor of an elapsed-second difference divided by 86,400 seconds. Recognition points and tier comparisons are plain integer arithmetic. Timestamp arithmetic for deadlines is exact to the second.

### 2.10. The Recognition Ledger

Every award or penalty of recognition points is an append-only RecognitionEvent: once written it is never edited or deleted, and no status filter ever excludes an event from a sum. Each event records the `steward_id` it belongs to, an `event_type` drawn from `MAINTENANCE_RESOLVED`, `ALLOCATION_PLACED`, `DRIVE_COMPLETED`, `COMPLAINT_UPHELD`, and `TRAINING_PASSED`, a signed `points_delta`, and a polymorphic pointer — a `source_type` naming the kind of entity that caused the event (`MAINTENANCE_REQUEST`, `ALLOCATION`, `BOOK_DRIVE`, `COMPLAINT`, or `TRAINING_COMPLETION`) paired with the `source_id` of that entity. The signed values are fixed: resolving a maintenance request pays +40, each placed allocation pays +5, completing a drive pays +150 when the drive qualifies for its bonus and +50 when it does not, an upheld complaint levies −60, and passing a training module pays +25. A compensating event with the opposite sign is the only way a previous event is ever offset, which is how an adjudicated dismissal repays a steward. Section 3.2 defines how the log aggregates into the figures shown on a steward's profile.

## 3. Business Logic & Workflows

### 3.1. Becoming a Steward: Registration, Training, and Standing

Anyone may apply to join the network. Registration — open to the public and to administrators — captures the applicant's `full_name`, `email`, and the two-letter `region_code` (for example OR or WA) in which they will operate, and creates a Steward in `APPLIED` status with every computed counter at zero. Email addresses are unique across all stewards regardless of status: a registration or update that reuses an existing steward's address is rejected with `ERR_EMAIL_TAKEN`.

An applicant becomes operational only after training. A `NetworkAdmin` curates the training catalog: each module carries a unique `code` (the network's catalog includes `ORIENTATION`, `SAFETY`, `CURATION`, `OUTREACH`, and `FUNDRAISING`), a human-readable `title`, an integer difficulty `level` where 1 is introductory, an optional `prerequisite_module_id` pointing at the module that must be passed first, and an `active` flag that defaults to true. The prerequisite chain must remain acyclic — creating or editing a module whose `prerequisite_module_id` would close a loop is rejected with `ERR_MODULE_CYCLE`, and the referenced module must exist. Modules can be browsed with filters on `prerequisite_module_id` and `active`.

Recording a completion is a self-service act for a steward (or an administrative act on their behalf) and takes the `module_id` and an integer `score` from 0 to 100. A score of at least 80 yields a `result` of `PASSED`; 79 or below yields `FAILED`. Three guards protect the record: the module must be active (`ERR_MODULE_INACTIVE` otherwise), its prerequisite chain must already be fully passed by this steward (`ERR_PREREQUISITE_NOT_MET`), and a module already passed by this steward cannot be passed again (`ERR_MODULE_ALREADY_PASSED`). Every `PASSED` completion raises the steward's `training_level` — the count of distinct modules passed — and appends a `TRAINING_PASSED` recognition event worth +25 points, which in turn refreshes the recognition figures of §3.2. Completion records can be listed with `steward_id`, `module_id`, and `result` filters.

Activation is the gateway from applicant to steward: a `NetworkAdmin` activates an `APPLIED` steward only when that steward holds a `PASSED` completion in the `ORIENTATION` module, failing with `ERR_ORIENTATION_REQUIRED` when the pass is missing and `ERR_INVALID_STATE` when the steward is not `APPLIED`. From `ACTIVE`, a steward may be suspended by a `Moderator` or `NetworkAdmin` — the transition to `SUSPENDED` stamps `suspended_at` with the current logical time — and later reinstated by a `NetworkAdmin`, which returns them to `ACTIVE` and clears `suspended_at` to null. Retirement is terminal: a steward may retire themselves, or be retired by a `NetworkAdmin`, from either `ACTIVE` or `SUSPENDED` into `RETIRED`; a steward attempting to retire someone else's record is rejected with `ERR_FORBIDDEN_OWNERSHIP`, and any retire attempt from a state other than `ACTIVE` or `SUSPENDED` fails with `ERR_INVALID_STATE`. Each of these transitions increments the steward's `version` by one.

Profile upkeep runs through a patch operation that accepts an optional `full_name` and an optional `region_code` alongside the mandatory `expected_steward_version` described in §2.7; a steward may patch only their own record. Reading a steward returns the computed recognition fields alongside the stored ones, and the steward list supports `status`, `tier`, and `region_code` filters for administrative overview.

### 3.2. Recognition: Points, Tiers, and the Privilege of More Boxes

Two running totals summarize a steward's standing, both derived deterministically from the recognition ledger and both floored independently at zero. The `lifetime_points` total sums the `points_delta` of every RecognitionEvent the steward has ever received. The `rolling_points` total sums only those events whose `created_at` falls inside the closed window from 365 days before the current logical instant up to and including that instant. The figures refresh on every steward read, whenever a new event lands, and whenever a map sweep advances the epoch — the last case matters because events ageing past the 365-day boundary quietly shrink `rolling_points` while `lifetime_points` stands unchanged.

The `recognition_tier` reads only the rolling figure, never the lifetime one. The thresholds are inclusive: at least 1,000 rolling points earns `PLATINUM`, at least 600 earns `GOLD`, at least 300 earns `SILVER`, at least 100 earns `BRONZE`, and anything below 100 is `NONE` — exactly 100 is `BRONZE`, exactly 99 is `NONE`.

Standing has a material privilege attached: how many boxes a steward may hold. Box creation enforces a capacity keyed to the steward's current `recognition_tier` — a steward at `NONE` or `BRONZE` may hold one box, `SILVER` two, `GOLD` three, and `PLATINUM` five. The count against that limit includes every box the steward owns in `DRAFT`, `CHARTERED`, `ACTIVE`, or `SUSPENDED` charter states; decommissioned boxes no longer count. The boundary is inclusive of the limit, so a steward already holding exactly their allotment is rejected with `ERR_BOX_LIMIT_REACHED` on the next attempt.

The darker mirror of recognition is the strike record. A steward's `strike_count` is the number of complaints currently standing in an upheld terminal status — `RESOLVED_UPHELD` or `ADJUDICATED_UPHELD` — against boxes owned by that steward. It rises when a complaint is ruled or adjudicated against the steward and falls when an adjudicated dismissal reverses such a ruling, since the count is recomputed from the live complaint set rather than stored as a mutable tally. Stewards, moderators, and administrators can review the underlying event log through a steward-scoped listing, with stewards restricted to their own history.

### 3.3. Chartering a Box and Keeping the Map Honest

A box begins as a proposal. Creation takes the owning `steward_id` — a steward caller may propose only for themselves, while a `NetworkAdmin` may act on any steward's behalf — plus a public display `name`, WGS84 coordinates (`latitude` between −90 and 90, `longitude` between −180 and 180), the integer `capacity_books` (at least 1), and the `region_code` where the box will stand. The proposing steward must be `ACTIVE` (`ERR_STEWARD_NOT_ACTIVE` otherwise) and below the recognition-tier capacity of §3.2. A new box starts in `DRAFT` charter status with an `UNLISTED` posture: it exists, but the public map does not show it.

Chartering is an administrative act. All box lifecycle moves flow through a single charter-status operation whose caller supplies a `target_status` of `CHARTERED`, `ACTIVE`, `SUSPENDED`, or `DECOMMISSIONED`, with role restrictions per §2.1. When a `NetworkAdmin` moves a `DRAFT` box to `CHARTERED` — again requiring the owning steward to be `ACTIVE`, failing with `ERR_STEWARD_NOT_ACTIVE` otherwise — the network mints the box's `charter_number`: the prefix `CH-` followed by a six-digit zero-padded sequence equal to one more than the count of previously chartered boxes, so the first charter ever issued is `CH-000001`. The field stays null while a box remains in `DRAFT`.

Activation requires proof the box physically exists. Moving a `CHARTERED` box to `ACTIVE` demands at least one inspection record with `result` `CONFIRMED` for the box (`ERR_INSPECTION_REQUIRED` without one) and an owning steward in `ACTIVE` standing (`ERR_STEWARD_NOT_ACTIVE` otherwise); the transition stamps both `installed_at` — which stays null for as long as the box has never been activated — and `last_activity_at` with the current logical time, sets the posture to `LISTED`, and puts the box on the public map. Inspections are filed by a `Moderator` or `NetworkAdmin` with a `result` of `CONFIRMED`, `NOT_FOUND`, or `FAILED_CONDITION` and optional free-text `notes`; the acting operator's header identity is stored as `inspector_user_id`. Inspections can be recorded only for boxes in `CHARTERED`, `ACTIVE`, or `SUSPENDED` states — anything else is `ERR_INVALID_STATE`. A `CONFIRMED` result refreshes the box's `last_activity_at` and triggers a posture recompute, but two confirmations may not crowd each other: a `CONFIRMED` inspection filed less than 30 days after the box's previous `CONFIRMED` inspection is rejected with `ERR_INSPECTION_TOO_SOON`. A `NOT_FOUND` result on an `ACTIVE` box suspends it on the spot — `charter_status` drops to `SUSPENDED`, `suspended_at` is set, and the posture becomes `DELISTED` — while the same result on a `CHARTERED` or `SUSPENDED` box is simply stored without a charter change. A `FAILED_CONDITION` result spawns a maintenance request for the box in category `WEAR`, status `REPORTED`, severity still null, feeding §3.5.

Suspension and decommissioning close the lifecycle. A `NetworkAdmin` may suspend an `ACTIVE` box, which stamps `suspended_at`, forces the posture to `DELISTED`, and recalls everything in flight: every allocation for the box in `RESERVED` or `DISPATCHED` status becomes `CANCELLED`, and each affected book returns to `AVAILABLE` with its `box_id` cleared. Reactivation from `SUSPENDED` is available to the box's owner steward or a `NetworkAdmin`, but only on fresh evidence: a `CONFIRMED` inspection created strictly after `suspended_at` must exist (`ERR_INSPECTION_REQUIRED` otherwise), and a steward actor must own the box (`ERR_FORBIDDEN_OWNERSHIP`). Reactivation clears `suspended_at`, refreshes `last_activity_at`, recomputes the posture from live conditions rather than restoring it blindly, and increments the box's `version`. Decommissioning is terminal. From `CHARTERED` it simply delists the box. From `ACTIVE` or `SUSPENDED` it additionally unwinds the box's book load: allocations in `RESERVED` or `DISPATCHED` become `CANCELLED` and their books return to `AVAILABLE` with `box_id` cleared to null, while allocations already `PLACED` become `REMOVED` and their books are written off as `RECYCLED`; the box's `current_stock` is forced to 0 and its posture to `DELISTED`.

Three derived counters travel with every box read. The `current_stock` counts the box's allocations currently in `PLACED` status and is maintained invariantly as placements and removals happen. The `last_activity_at` is the latest of the box's `installed_at`, the `created_at` of its most recent `CONFIRMED` inspection, the `resolved_at` of its most recently resolved maintenance request, and the most recent moment an allocation transitioned to `PLACED` for it. From that, `days_since_activity` is the whole number of days between `last_activity_at` and the current logical instant — the elapsed-second difference divided by 86,400 and rounded down — and stays null until the box has any activity at all. The box resource also exposes `open_critical_maintenance_count`, `open_high_maintenance_count`, and `upheld_complaints_90d`, defined in §3.4. Box reads are public, and the listing endpoint — the public map — filters by `steward_id`, `charter_status`, `listing_posture`, and `region_code`; individual inspection histories filter by `result`.

### 3.4. Listing Posture: How the Map Protects Itself

Posture is the network's second, parallel state dimension on every box, and no client ever sets it directly — it is recomputed by the system whenever the underlying facts change: a complaint upheld or adjudicated, a maintenance triage, resolution, reopen, or won't-fix decision, a new inspection, a placement, a box activation or reactivation, and every map sweep. Four live counters feed the decision, and each recompute writes them back onto the box. The `open_critical_maintenance_count` counts the box's maintenance requests with `severity` `CRITICAL` whose status is `SCHEDULED` or `REOPENED`; the `open_high_maintenance_count` counts the same two statuses at `severity` `HIGH`. Requests still in `REPORTED` carry a null severity and never count, and requests in `RESOLVED` or `WONT_FIX` never count. The `upheld_complaints_90d` counts the box's complaints standing in `RESOLVED_UPHELD` or `ADJUDICATED_UPHELD` whose `upheld_at` falls inside the closed window from 90 days before the current logical instant through that instant; a complaint sitting in `ESCALATED` limbo does not count. Staleness is the `days_since_activity` of §3.3, treated as 0 for pre-activation boxes, which are unlisted anyway.

The decision is evaluated in a fixed precedence order, and the order is part of the contract. First, a box in `DRAFT` or `CHARTERED` is `UNLISTED`. Second, a box in `SUSPENDED` or `DECOMMISSIONED` is `DELISTED`. Third, an `ACTIVE` box is `DELISTED` when any delisting condition holds: at least one open critical maintenance request, at least three upheld complaints in the 90-day window, or staleness of at least 180 days. Fourth, failing that, the box is `FLAGGED` when any flagging condition holds: at least one upheld complaint in the window, at least one open high-severity request, or staleness of at least 120 days. Only when none of the above applies is the box `LISTED`.

Posture moves in every direction as facts change: `UNLISTED` to `LISTED` at activation and to `DELISTED` when a chartered box is decommissioned; `LISTED` to `FLAGGED` or `DELISTED` as conditions arrive; `FLAGGED` back to `LISTED` when neither flagging nor delisting condition survives, or down to `DELISTED` when a delisting condition appears; `DELISTED` back to `FLAGGED` when only flagging conditions remain, or fully back to `LISTED` when the slate is clean. Falling into `DELISTED` from `LISTED` or `FLAGGED` fires the same recall cascade as a suspension: in-flight allocations (`RESERVED` or `DISPATCHED`) for the box become `CANCELLED`, their books return to `AVAILABLE` with `box_id` cleared to null, and run-completion bubble-up checks fire for the runs those allocations belonged to. A delisting does not rewrite any existing draft plan, but it poisons one: a distribution run still in `DRAFT` whose snapshot contains the delisted box can no longer be confirmed and fails at confirm time with `ERR_PLAN_STALE`.

### 3.5. Repairs, Seasons, and the Maintenance Loop

Damage reporting is public. Anyone — a passer-by, a steward, a moderator — reports an issue by naming the `box_id`, a `category` of `WEATHER_DAMAGE`, `VANDALISM`, `WEAR`, or `INSTALLATION_DEFECT`, and a free-text `description`. The target box must be a real public fixture: requests against a `DRAFT` or `DECOMMISSIONED` box are rejected with `ERR_BOX_NOT_PUBLIC`, leaving `CHARTERED`, `ACTIVE`, and `SUSPENDED` boxes reportable, which is how construction and installation defects on not-yet-active boxes enter the system. A fresh request sits in `REPORTED` with its `severity` still null. Two seasonal facts are pinned at report time from the UTC month of the request's `created_at`: the `season_at_report` — `WINTER` for December through February, `SPRING` for March through May, `SUMMER` for June through August, `FALL` for September through November — and the `season_multiplier`, which is 2.0 for winter reports and 1.0 in every other season.

Triage belongs to a `Moderator` or `NetworkAdmin` and applies equally to fresh `REPORTED` requests and to `REOPENED` ones cycling back through the loop. The operator supplies a `severity` of `LOW`, `MEDIUM`, `HIGH`, or `CRITICAL` (anything else is `ERR_INVALID_REQUEST`) and a `scheduled_date` that must not lie before the current logical date (`ERR_SCHEDULE_DATE_PAST`). Triaging moves the request to `SCHEDULED`, stamps `triaged_at`, and computes the `sla_deadline_at`: the triage instant plus the severity's base allowance — 336 hours (fourteen days) for `LOW`, 168 hours (seven days) for `MEDIUM`, 72 hours (three days) for `HIGH`, 24 hours (one day) for `CRITICAL` — multiplied by the request's season multiplier, so a winter report doubles every allowance. Because triage changes the open-maintenance counters, the box's posture is recomputed at this moment.

Resolution pays the steward who did the work. Resolving a `SCHEDULED` request takes an `outcome`, an optional `parts` array in which each line carries a `qty` of at least 1 and a `unit_cost_cents` of at least 0, an optional `labor_hours` of at least 0, and optional `resolution_notes`. The `reimbursement_cents` field stays null until the first resolution. With `outcome` `RESOLVED`, the server computes it: each parts line is reimbursed at eighty percent of its extended cost — quantity times unit cost times 0.8 — with every line rounded half-up to whole cents before the rounded lines are summed (the pinning rule of §2.9); labor adds 500 cents per hour, itself rounded half-up to whole cents; the total is the parts subtotal plus labor, capped at 15,000 cents (one hundred fifty dollars), with `parts` defaulting to empty and `labor_hours` to 0 when omitted. The same resolution stamps `resolved_at`, sets `sla_breached` by strict comparison — resolving strictly later than `sla_deadline_at` is a breach, while resolving exactly at the deadline is not — and bumps `resolution_count`, which accumulates across every resolution including ones after a reopen. Resolution is also a recognition moment: the box's steward receives a `MAINTENANCE_RESOLVED` event worth +40, the box's `last_activity_at` refreshes to the current instant, and the posture recomputes as open-maintenance counters drop. Alternatively, an `outcome` of `WONT_FIX` closes a `REPORTED` or `SCHEDULED` request with no payout; from `SCHEDULED` the box's counters and posture are recomputed, while from `REPORTED` nothing downstream changes since the request never carried a severity.

A resolved request is not necessarily finished. Within a strict fourteen-day window after `resolved_at`, the box's owner steward (anyone else drawing `ERR_FORBIDDEN_OWNERSHIP`) or a `NetworkAdmin` may reopen it, moving the request to `REOPENED`; at exactly fourteen days the window is already expired and the attempt fails with `ERR_REOPEN_WINDOW_EXPIRED`, as does any later attempt. Reopening resets `reimbursement_cents` to null pending recomputation at the next resolution and recomputes the box's posture, after which the request flows through triage and resolution again. The maintenance list filters by `box_id`, `status`, and `severity`.

### 3.6. Handling Community Complaints

Complaint intake is public. A filer names the `box_id`, a `category` of `INAPPROPRIATE_CONTENT`, `HATE_SPEECH`, `COMMERCIAL_SPAM`, or `OTHER`, and a free-text `description`, with an optional `target_category` — one of the book categories `FICTION`, `NONFICTION`, `CHILDREN`, `YOUNG_ADULT`, or `REFERENCE` — and an optional `evidence_url`. Only boxes visible to the public may be complained about: the target must be `ACTIVE` or `SUSPENDED`, and any other charter state is rejected with `ERR_BOX_NOT_PUBLIC`. A new complaint stands in `FILED`, with its `outcome` null until a resolving or adjudicating decision lands and its `upheld_at` null unless the complaint is upheld.

Triage starts the clock. A `Moderator` or `NetworkAdmin` triages a `FILED` complaint into `STEWARD_RESPONSE_PENDING`, which records the operator's identity as `triaged_by_user_id` and sets `response_due_at` exactly 72 hours after the triage instant. The box's owner steward then has that window to submit a `response_text` — a steward responding on someone else's box is rejected with `ERR_FORBIDDEN_OWNERSHIP` — responding moves the complaint to `UNDER_REVIEW` and stores the text. Silence is not a deadlock: a map sweep that finds the response deadline reached advances the complaint to `UNDER_REVIEW` itself, leaving `response_text` null.

Resolution is deliberately a different pair of hands. A `Moderator` or `NetworkAdmin` resolves an `UNDER_REVIEW` complaint with an `outcome` of `UPHELD` or `DISMISSED` and optional `resolution_notes`, but the resolver must not be the operator who triaged it — a match between the caller's identity and `triaged_by_user_id` is rejected with `ERR_SEGREGATION_OF_DUTIES`. The resolver's identity lands in `resolved_by_user_id`. A dismissal simply records the outcome as `DISMISSED` and closes at `RESOLVED_DISMISSED`. An upheld ruling lands at `RESOLVED_UPHELD` and fires a heavier cascade: the outcome is set to `UPHELD`, `upheld_at` is stamped, the box's steward receives a `COMPLAINT_UPHELD` event worth −60 and their `strike_count` rises by one on recount, and — when the complaint named a `target_category` — every book physically placed in that box in the named category is quarantined, its status moving from `PLACED` to `QUARANTINED` while `box_id` stays set and the underlying allocation remains `PLACED`, so `current_stock` does not move. The box's `upheld_complaints_90d` and posture then recompute.

Either side may appeal once. A `NetworkAdmin` may escalate a complaint standing in `RESOLVED_DISMISSED` or `RESOLVED_UPHELD` — a reporter-backed appeal of a dismissal, or a steward's appeal of an upheld ruling — moving it to `ESCALATED`; these resolved states are not terminal, and only the two adjudicated states are. Escalation out of an upheld ruling immediately relieves the box: the complaint stops counting toward `upheld_complaints_90d` on entry to `ESCALATED`, and the posture recomputes.

Adjudication is final and again segregated: the adjudicating `NetworkAdmin` must differ from both the triager and the resolver, with any collision rejected as `ERR_SEGREGATION_OF_DUTIES`. The network remembers which resolved state the complaint was escalated from, because the same `outcome` behaves differently along the two branches. Adjudicating `UPHELD` stamps `outcome` and `upheld_at`; when the complaint had been escalated from `RESOLVED_DISMISSED`, the full upheld cascade fires — the −60 event, the strike recount, the category quarantine, the posture recompute — but when it was escalated from `RESOLVED_UPHELD`, that cascade must not fire twice, so no second recognition event and no second quarantine occur. Adjudicating `DISMISSED` sets the outcome and, when the complaint had been escalated from an upheld ruling, pays compensation: a `COMPLAINT_UPHELD` event worth +60 offsets the earlier penalty, the strike count recomputes downward as the complaint leaves the upheld set, every book quarantined by this complaint returns from `QUARANTINED` to `PLACED` keeping its `box_id` and leaving stock untouched, and the box's posture recalculates. Both adjudicated states — `ADJUDICATED_UPHELD` and `ADJUDICATED_DISMISSED` — are terminal. Complaint listings filter by `box_id`, `status`, and `category`.

### 3.7. Book Drives with Partner Schools

Schools join the network by administrative registration. A `NetworkAdmin` records the school's `name`, `district_code`, a `contact_email` unique across schools, its `region_code`, and any `restricted_categories` — a subset of the five book categories the school forbids in its drives. A school starts `REGISTERED` and cycles to `ACTIVE` (from `REGISTERED` or `INACTIVE`) or back to `INACTIVE` (from `ACTIVE`) under administrative control via a status operation taking a `target_status` of `ACTIVE` or `INACTIVE`, each change incrementing its `version`; its `drives_completed_count` tracks how many of its drives have reached `COMPLETED`.

An `ACTIVE` steward proposes a drive for an `ACTIVE` school — proposing as a suspended steward fails with `ERR_STEWARD_NOT_ACTIVE`, and a school in any other status fails with `ERR_SCHOOL_NOT_ACTIVE`. The proposal names the `school_id`, an integer `goal_books` of at least 1, and a collection window `starts_at` to `ends_at`. The window is half-open: it includes its start instant and excludes its end, and an end that does not fall strictly after the start is `ERR_DRIVE_WINDOW_INVALID`. One school cannot run overlapping drives: a new window that intersects any non-terminal drive of the same school under half-open semantics is rejected with `ERR_DRIVE_WINDOW_OVERLAP`, though back-to-back adjacency — one drive's `ends_at` equal to another's `starts_at` — is allowed. A fresh drive stands in `PROPOSED` with both approval dimensions `PENDING`, and the proposing caller's identity is recorded as `coordinator_steward_id`.

Approval is a fork-join across two independent dimensions. The school's liaison decides the `school_approval_status` — the caller's `X-User-ID` must equal the drive's `school_id` or the attempt fails with `ERR_FORBIDDEN_OWNERSHIP` — while a `NetworkAdmin` decides the `network_approval_status`; each decision is a `decision` of `APPROVE` or `REJECT`. A `REJECT` from either side moves the drive straight to terminal `REJECTED` and marks the deciding dimension `REJECTED`. Only when both dimensions stand `APPROVED` does the drive join into `APPROVED`, and the join mints the drive's linked donation batch: a batch with `source_type` `BOOK_DRIVE`, its `drive_id` pointing back to the drive, the school's `region_code`, and `RECEIVED` status. From there the calendar drives the lifecycle: a map sweep opens an `APPROVED` drive once the current instant reaches `starts_at`, moving it to `OPEN`, and collection closes either manually — the coordinator steward or a `NetworkAdmin` moves an `OPEN` drive to `COLLECTION_CLOSED` — or automatically when a sweep finds `ends_at` reached.

Completion is the payoff. Drive lifecycle moves after approval — closing collection, completing, cancelling — are requested through a status operation carrying a `target_status` of `COLLECTION_CLOSED`, `COMPLETED`, or `CANCELLED`. From `COLLECTION_CLOSED`, the coordinator or an administrator completes the drive, but only when the linked batch is fully graded — every item carrying a `condition_grade` — or the attempt fails with `ERR_UNGRADED_ITEMS`. Completion recomputes the drive's two fulfillment lenses. The gross lens, `fulfillment_pct_gross`, counts every book ever collected into the linked batch regardless of fate: `collected_count` is all items in the batch in any status, multiplied by 100 and floor-divided by `goal_books`. The net lens, `fulfillment_pct_net`, counts only books still in play: `accepted_count` covers items in `AVAILABLE`, `ALLOCATED`, `DISPATCHED`, or `PLACED`, excluding anything `QUARANTINED` or `RECYCLED`, again multiplied by 100 and floor-divided by `goal_books`. Because a recycled or quarantined item still feeds the gross figure but not the net one, the net percentage is always the smaller-or-equal reading. The bonus line, `qualifies_for_bonus`, holds when the net percentage reaches at least 80 — the boundary is inclusive. Completion pays the coordinator a `DRIVE_COMPLETED` event worth +150 points when the drive qualifies and +50 when it does not, and increments the school's `drives_completed_count`.

Cancellation unwinds cleanly. The coordinator or an administrator may cancel from `PROPOSED`, `APPROVED`, or `OPEN`; anything later is past the point of cancellation. Cancelling a merely `PROPOSED` drive changes nothing downstream, but cancelling from `APPROVED` or `OPEN` closes the linked batch — its status drops to `CLOSED` — and writes off every still-`AVAILABLE` book in it as `RECYCLED`. Drive listings filter by `school_id`, `coordinator_steward_id`, and `status`.

### 3.8. From Donation Bin to Bookshelf: Intake, Sorting, and Distribution

Physical books enter the network through donation batches, operated by a `HubCoordinator` or `NetworkAdmin`. A batch declares a `source_type` of `PUBLIC_DROP`, `STEWARD_TRANSFER`, or `BOOK_DRIVE`, and the `region_code` where the books were collected. The drive linkage is strict: a `BOOK_DRIVE` batch without a `drive_id` is rejected with `ERR_DRIVE_LINK_REQUIRED`, and a `drive_id` attached to any other source type is rejected with `ERR_DRIVE_LINK_FORBIDDEN`; the referenced drive must stand in `APPROVED` or `OPEN`, failing with `ERR_DRIVE_NOT_APPROVED` otherwise. A batch opens in `RECEIVED` status. Its `item_count` only ever grows — items are never hard-deleted — while `graded_count` tracks how many carry a `condition_grade`.

Intake is bulk and best-effort. A single call presents an `items` array, each element describing one donated book with at least its `title` and its `category` — `FICTION`, `NONFICTION`, `CHILDREN`, `YOUNG_ADULT`, or `REFERENCE` — and optionally a `condition_grade` of `A`, `B`, or `C`, since ungraded books are graded during sorting. The batch must still be `RECEIVED` (`ERR_INVALID_STATE` past that point), and intake into a drive-linked batch faces two more gates: the drive must be `OPEN` (`ERR_DRIVE_NOT_OPEN`) and the current instant must fall before the drive's `ends_at` (`ERR_DRIVE_WINDOW_CLOSED`). Within the array, every element is judged on its own: an item whose category appears in the partner school's `restricted_categories` is rejected individually with `ERR_CONTENT_POLICY_VIOLATION`, and malformed entries fail individually too, while their valid siblings are still created. The response reports a `created_count`, the `created_item_ids`, and a `rejected` array pairing each failure's `index` with its `error_id`. Created items start `AVAILABLE`, and items created in one call receive monotonically increasing `created_at` values in array order so that later distribution draws are deterministic. Books can be browsed with `batch_id`, `box_id`, `status`, and `category` filters.

Sorting closes when every book is graded. Grading a single book — setting its `condition_grade` to `A`, `B`, or `C` — is permitted only while the book is `AVAILABLE` and its batch is still `RECEIVED`, with anything else rejected as `ERR_INVALID_STATE`; each grading refreshes the batch's `graded_count`. The sort-complete step moves the batch from `RECEIVED` to `SORTED` only when `graded_count` equals `item_count`, failing with `ERR_UNGRADED_ITEMS` while any book is ungraded. From then on a batch empties monotonically: once every book it holds has reached a terminal status — `PLACED` or `RECYCLED` — the batch bubbles itself up to `CLOSED`.

Distribution planning is a server-side computation, never a client-supplied list. Creating a distribution run for a `SORTED` batch requires the `expected_batch_version` of §2.7, and creating the run itself advances the batch's `version`, so a second writer holding a stale observation is turned away with `ERR_STALE_VERSION`. Creating a newer run for the same batch supersedes any run still in `DRAFT` for that batch, moving it to `SUPERSEDED`. The planner first filters for eligible boxes: charter status `ACTIVE`, posture `LISTED`, and at least one free slot — `capacity_books` exceeding `current_stock`. Each eligible box earns a `need_score`: take its remaining capacity capped at ten books and double it, add its `days_since_activity` capped at sixty days, and add a twenty-point bonus when the box's `region_code` matches the batch's `region_code`. Boxes rank by score from highest to lowest, ties broken in favor of the box created earliest; box ids never participate in ranking. Walking the ranking, each box is planned a quantity equal to the smallest of three figures — its remaining capacity, ten books, and the count of still-unassigned available graded items — and a box whose quantity works out to zero drops out of the plan. When no eligible box exists or the batch holds no available graded items, the empty plan is rejected with `ERR_NO_ELIGIBLE_BOXES`. The surviving plan is frozen into the run's `plan_snapshot`, an ordered array of entries each naming a `box_id`, a `quantity`, and the box's `need_score`, ordered exactly as ranked; `planned_item_count` is the sum of those quantities.

Confirmation turns the plan into commitments. Confirming a `DRAFT` run re-validates the frozen snapshot against the present: every planned box must still be `ACTIVE`, still `LISTED`, and still hold enough free capacity for its planned quantity, and the batch must still hold enough available graded items to cover `planned_item_count` — any drift fails with `ERR_PLAN_STALE`. A clean confirmation creates one allocation per planned book in `RESERVED` status, consuming boxes in snapshot order and drawing items from the batch's available graded pool oldest-first by `created_at`; each drawn book moves to `ALLOCATED` with its `box_id` set to the planned box, and the allocations themselves receive monotonically increasing `created_at` values in plan order. Dispatch then moves a `CONFIRMED` run to `DISPATCHED`, flipping every `RESERVED` allocation to `DISPATCHED` and every `ALLOCATED` book to `DISPATCHED`.

Receipt is the steward's handshake. The owner steward of the destination box — or a `NetworkAdmin` acting on their behalf — confirms a `DISPATCHED` allocation as received; a steward acting on someone else's box is rejected with `ERR_FORBIDDEN_OWNERSHIP`, and a non-`ACTIVE` steward with `ERR_STEWARD_NOT_ACTIVE`: the allocation becomes `PLACED` with `placed_at` stamped, the book becomes `PLACED`, the box's `current_stock` rises by one and its `last_activity_at` refreshes, the box's steward collects an `ALLOCATION_PLACED` event worth +5 points, and the box's posture recomputes as its staleness resets. Each placement also runs a bubble-up check: when every allocation of a run stands in `PLACED` or `CANCELLED`, the run closes itself as `COMPLETED`, whether from `DISPATCHED` or — when everything was cancelled before dispatch — directly from `CONFIRMED`. Cancellation is the compensating lever, available to a `HubCoordinator` or `NetworkAdmin` while an allocation is `RESERVED` or `DISPATCHED`: the allocation becomes `CANCELLED`, its book returns to `AVAILABLE` with `box_id` cleared to null, and the same bubble-up check runs. Allocations leave the active flow in one more way — a `PLACED` allocation becomes `REMOVED` when its box is decommissioned or when its book, sitting `QUARANTINED`, is recycled by a sweep — and removal writes the book off as `RECYCLED` and decrements the box's `current_stock` by one. Run listings filter by `batch_id` and `status`; a run's allocation listing filters by `status` and follows creation order, which is plan order; the network-wide allocation listing filters by `run_id`, `box_id`, `book_item_id`, and `status`.

### 3.9. The Map Sweep: Epoch Maintenance

Time-dependent transitions do not fire themselves; they ride a single administrative checkpoint. A `NetworkAdmin` triggers the map sweep, and each run walks the whole network in one pass: complaints sitting in `STEWARD_RESPONSE_PENDING` whose `response_due_at` has been reached move to `UNDER_REVIEW`; `APPROVED` drives whose `starts_at` has arrived open; `OPEN` drives whose `ends_at` has arrived move to `COLLECTION_CLOSED`; every box's posture recomputes against the counters of §3.4; `ACTIVE` boxes whose `days_since_activity` has reached 180 days are suspended with `suspended_at` stamped; boxes that have sat `SUSPENDED` for at least 30 days are decommissioned with the full cascade of §3.3; and books still `QUARANTINED` thirty days after the `upheld_at` of the decision that quarantined them are recycled, clearing their `box_id`, turning the still-`PLACED` allocation `REMOVED`, and decrementing the box's `current_stock` by one. The sweep is idempotent — a second pass without any clock movement changes nothing.

The sweep answers with a tally of its work: `expired_response_count`, `opened_drive_count`, `closed_drive_count`, `suspended_box_count`, `decommissioned_box_count`, `recycled_item_count`, and `posture_change_count`. Every entity the sweep mutates increments its `version` and refreshes its `updated_at`, which is precisely what makes stale client views detectable through §2.7 on the next write.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource or advance a workflow return `200 OK`. The bulk item-intake operation, the sweep, and the clock utility also return `200 OK` with their summary payloads. Request and response shapes for each operation are defined by the workflows of §3 rather than restated here.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/library-network/stewards` | Register a new steward (status `APPLIED`) | Anonymous, NetworkAdmin |
| GET | `/library-network/stewards` | List stewards with pagination and filters | Steward, HubCoordinator, Moderator, NetworkAdmin |
| GET | `/library-network/stewards/{id}` | Get a steward including computed recognition fields and version | Steward, HubCoordinator, Moderator, NetworkAdmin |
| PATCH | `/library-network/stewards/{id}` | Update steward profile with optimistic concurrency | Steward, NetworkAdmin |
| POST | `/library-network/stewards/{id}/activate` | Activate an `APPLIED` steward (requires passed `ORIENTATION`) | NetworkAdmin |
| POST | `/library-network/stewards/{id}/suspend` | Suspend an `ACTIVE` steward | Moderator, NetworkAdmin |
| POST | `/library-network/stewards/{id}/reinstate` | Reinstate a `SUSPENDED` steward | NetworkAdmin |
| POST | `/library-network/stewards/{id}/retire` | Retire a steward (terminal) | Steward, NetworkAdmin |
| POST | `/library-network/training-modules` | Create a training module; prerequisite graph must stay acyclic | NetworkAdmin |
| GET | `/library-network/training-modules` | List training modules | Steward, HubCoordinator, Moderator, NetworkAdmin |
| GET | `/library-network/training-modules/{id}` | Get a single training module | Steward, HubCoordinator, Moderator, NetworkAdmin |
| PATCH | `/library-network/training-modules/{id}` | Update a module's prerequisite or active flag | NetworkAdmin |
| POST | `/library-network/stewards/{id}/training-completions` | Record a module completion for a steward | Steward, NetworkAdmin |
| GET | `/library-network/training-completions` | List training completions | Steward, HubCoordinator, Moderator, NetworkAdmin |
| GET | `/library-network/training-completions/{id}` | Get a single training completion | Steward, HubCoordinator, Moderator, NetworkAdmin |
| POST | `/library-network/boxes` | Propose a new library box (`DRAFT` / `UNLISTED`) | Steward, NetworkAdmin |
| GET | `/library-network/boxes` | List boxes (public map listing) with filters | Anonymous, Steward, HubCoordinator, Moderator, NetworkAdmin |
| GET | `/library-network/boxes/{id}` | Get a box (public map read with posture counters) | Anonymous, Steward, HubCoordinator, Moderator, NetworkAdmin |
| POST | `/library-network/boxes/{id}/status` | Charter-status transition (`CHARTERED`, `ACTIVE`, `SUSPENDED`, `DECOMMISSIONED`) | Steward, NetworkAdmin |
| POST | `/library-network/boxes/{id}/inspections` | Record a box inspection | Moderator, NetworkAdmin |
| GET | `/library-network/boxes/{id}/inspections` | List inspection records for a box | Steward, HubCoordinator, Moderator, NetworkAdmin |
| GET | `/library-network/book-items` | List book items with filters, sorted by creation ascending | Steward, HubCoordinator, Moderator, NetworkAdmin |
| GET | `/library-network/book-items/{id}` | Get a single book item | Steward, HubCoordinator, Moderator, NetworkAdmin |
| PATCH | `/library-network/book-items/{id}` | Grade an ungraded book item during sorting | HubCoordinator, NetworkAdmin |
| POST | `/library-network/maintenance-requests` | Report box damage or wear (public) | Anonymous, Steward, Moderator, NetworkAdmin |
| GET | `/library-network/maintenance-requests` | List maintenance requests with filters | Steward, HubCoordinator, Moderator, NetworkAdmin |
| GET | `/library-network/maintenance-requests/{id}` | Get a maintenance request including SLA and reimbursement fields | Steward, HubCoordinator, Moderator, NetworkAdmin |
| POST | `/library-network/maintenance-requests/{id}/triage` | Triage a reported or reopened request; computes the seasonal SLA | Moderator, NetworkAdmin |
| POST | `/library-network/maintenance-requests/{id}/resolve` | Resolve (reimbursement, recognition, breach flag) or mark won't-fix | Moderator, NetworkAdmin |
| POST | `/library-network/maintenance-requests/{id}/reopen` | Reopen a resolved request within the fourteen-day window | Steward, NetworkAdmin |
| POST | `/library-network/complaints` | File a community complaint about a box (public) | Anonymous, Steward, Moderator, NetworkAdmin |
| GET | `/library-network/complaints` | List complaints with filters | Steward, HubCoordinator, Moderator, NetworkAdmin |
| GET | `/library-network/complaints/{id}` | Get a complaint | Steward, HubCoordinator, Moderator, NetworkAdmin |
| POST | `/library-network/complaints/{id}/triage` | Triage a filed complaint; starts the 72-hour steward response window | Moderator, NetworkAdmin |
| POST | `/library-network/complaints/{id}/respond` | Steward responds to a triaged complaint | Steward |
| POST | `/library-network/complaints/{id}/resolve` | Resolve an under-review complaint; resolver must differ from triager | Moderator, NetworkAdmin |
| POST | `/library-network/complaints/{id}/escalate` | Escalate a resolved complaint to network adjudication | NetworkAdmin |
| POST | `/library-network/complaints/{id}/adjudicate` | Final adjudication; adjudicator must differ from triager and resolver | NetworkAdmin |
| POST | `/library-network/schools` | Register a partner school | NetworkAdmin |
| GET | `/library-network/schools` | List schools | Steward, SchoolLiaison, HubCoordinator, Moderator, NetworkAdmin |
| GET | `/library-network/schools/{id}` | Get a single school including `drives_completed_count` | Steward, SchoolLiaison, HubCoordinator, Moderator, NetworkAdmin |
| POST | `/library-network/schools/{id}/status` | School status transition (`ACTIVE`, `INACTIVE`) | NetworkAdmin |
| POST | `/library-network/drives` | Propose a book drive with a partner school | Steward |
| GET | `/library-network/drives` | List book drives with filters | Steward, SchoolLiaison, HubCoordinator, Moderator, NetworkAdmin |
| GET | `/library-network/drives/{id}` | Get a book drive including approval dimensions and fulfillment metrics | Steward, SchoolLiaison, HubCoordinator, Moderator, NetworkAdmin |
| POST | `/library-network/drives/{id}/school-decision` | School liaison approves or rejects the drive | SchoolLiaison |
| POST | `/library-network/drives/{id}/network-decision` | Network admin approves or rejects the drive | NetworkAdmin |
| POST | `/library-network/drives/{id}/status` | Drive status transitions (`COLLECTION_CLOSED`, `COMPLETED`, `CANCELLED`) | Steward, NetworkAdmin |
| POST | `/library-network/batches` | Create a donation intake batch | HubCoordinator, NetworkAdmin |
| GET | `/library-network/batches` | List donation batches with filters | Steward, HubCoordinator, Moderator, NetworkAdmin |
| GET | `/library-network/batches/{id}` | Get a donation batch including version and item counters | Steward, HubCoordinator, Moderator, NetworkAdmin |
| POST | `/library-network/batches/{id}/items` | Bulk best-effort intake of book items into a `RECEIVED` batch | HubCoordinator, NetworkAdmin |
| POST | `/library-network/batches/{id}/sort-complete` | Close sorting when every item is graded | HubCoordinator, NetworkAdmin |
| POST | `/library-network/batches/{id}/distribution-runs` | Create a distribution run for a `SORTED` batch; server computes the plan | HubCoordinator, NetworkAdmin |
| GET | `/library-network/distribution-runs` | List distribution runs with filters | Steward, HubCoordinator, Moderator, NetworkAdmin |
| GET | `/library-network/distribution-runs/{id}` | Get a distribution run including its plan snapshot | Steward, HubCoordinator, Moderator, NetworkAdmin |
| GET | `/library-network/distribution-runs/{id}/allocations` | List a run's allocations in creation order | Steward, HubCoordinator, Moderator, NetworkAdmin |
| POST | `/library-network/distribution-runs/{id}/confirm` | Confirm a draft run; re-validates the plan and materializes allocations | HubCoordinator, NetworkAdmin |
| POST | `/library-network/distribution-runs/{id}/dispatch` | Dispatch a confirmed run | HubCoordinator, NetworkAdmin |
| GET | `/library-network/allocations` | List allocations with filters | Steward, HubCoordinator, Moderator, NetworkAdmin |
| GET | `/library-network/allocations/{id}` | Get a single allocation | Steward, HubCoordinator, Moderator, NetworkAdmin |
| POST | `/library-network/allocations/{id}/receive` | Box steward confirms placement of a dispatched book | Steward, NetworkAdmin |
| POST | `/library-network/allocations/{id}/cancel` | Cancel a reserved or dispatched allocation (compensating action) | HubCoordinator, NetworkAdmin |
| GET | `/library-network/stewards/{id}/recognition-events` | List a steward's append-only recognition event log | Steward, Moderator, NetworkAdmin |
| POST | `/library-network/map/sweeps` | Run the ops checkpoint advancing the network epoch | NetworkAdmin |
| POST | `/_clock/set_current_utc` | Test-driving capability: set the logical clock | NetworkAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflows in §2 and §3; this catalogue fixes only the identifier and its HTTP status.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED_ROLE` | 403 |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STEWARD_NOT_FOUND` | 404 |
| `ERR_BOX_NOT_FOUND` | 404 |
| `ERR_SCHOOL_NOT_FOUND` | 404 |
| `ERR_DRIVE_NOT_FOUND` | 404 |
| `ERR_BATCH_NOT_FOUND` | 404 |
| `ERR_RUN_NOT_FOUND` | 404 |
| `ERR_ALLOCATION_NOT_FOUND` | 404 |
| `ERR_MAINTENANCE_NOT_FOUND` | 404 |
| `ERR_COMPLAINT_NOT_FOUND` | 404 |
| `ERR_MODULE_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_DRIVE_NOT_OPEN` | 409 |
| `ERR_STEWARD_NOT_ACTIVE` | 409 |
| `ERR_INSPECTION_REQUIRED` | 409 |
| `ERR_ORIENTATION_REQUIRED` | 409 |
| `ERR_DRIVE_NOT_APPROVED` | 409 |
| `ERR_CONTENT_POLICY_VIOLATION` | 422 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_DRIVE_WINDOW_CLOSED` | 422 |
| `ERR_DRIVE_WINDOW_INVALID` | 422 |
| `ERR_DRIVE_WINDOW_OVERLAP` | 422 |
| `ERR_SCHEDULE_DATE_PAST` | 422 |
| `ERR_REOPEN_WINDOW_EXPIRED` | 422 |
| `ERR_INSPECTION_TOO_SOON` | 422 |
| `ERR_BOX_LIMIT_REACHED` | 422 |
| `ERR_NO_ELIGIBLE_BOXES` | 422 |
| `ERR_PLAN_STALE` | 409 |
| `ERR_UNGRADED_ITEMS` | 422 |
| `ERR_MODULE_ALREADY_PASSED` | 422 |
| `ERR_MODULE_INACTIVE` | 422 |
| `ERR_PREREQUISITE_NOT_MET` | 422 |
| `ERR_MODULE_CYCLE` | 422 |
| `ERR_EMAIL_TAKEN` | 422 |
| `ERR_BOX_NOT_PUBLIC` | 422 |
| `ERR_DRIVE_LINK_REQUIRED` | 422 |
| `ERR_DRIVE_LINK_FORBIDDEN` | 422 |
| `ERR_SCHOOL_NOT_ACTIVE` | 422 |
| `ERR_STALE_VERSION` | 412 |
