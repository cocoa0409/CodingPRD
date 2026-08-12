# Prescribed Burn Program API — Product Requirements Document

## 1. Introduction

Prescribed fire is one of the cheapest and most effective tools a land-management cooperative has for reducing wildfire fuel loads, but it is also one of the most legally and operationally exposed. A burn that escapes its perimeter becomes a wildfire, an uninsured liability event, and a regulatory incident all at once. A prescribed burn association exists to pool that risk: it coordinates planning among member landowners, enforces a common safety discipline, runs a shared liability and cost-share fund, and answers to air-quality regulators who ration how many acres may burn in an airshed on any given day.

This document specifies the API through which such an association runs its program. The system governs the full arc of a prescribed burn: a certified burn boss drafts a plan against a parcel, an agency reviewer approves it, a permit is issued only after neighbors are notified and a contingency plan is accepted, contractors are ordered and confirmed against a computed holding force, and on burn day a chain of gates — briefing, fresh in-prescription weather, a go/no-go checklist — must pass before a test fire is lit. When a fire escapes, the same system converts the event into an incident, tracks suppression costs, adjudicates liability between landowner and association fund, and manages cost-share reimbursement to landowners once post-burn monitoring proves the treatment worked. The design intent is that no fire is lit against stale paperwork, no dollar leaves the fund without an audit trail, and every approval is segregated from the person who authored the work.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contract formats, and cross-cutting principles that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. A request in which either header is missing or empty is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. A request whose role is not authorized for the target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

The system recognizes seven acting roles: `AssociationAdmin`, `Landowner`, `BurnBoss`, `AgencyReviewer`, `AirQualityOfficer`, `IncidentCommander`, and `Contractor`. Read endpoints are open to any authenticated role; the endpoint table marks these as `Any`, which is a readability designation rather than a credential a client ever sends.

Identity resolution differs by role. When `X-User-Role` is `Landowner`, `X-User-ID` is the `id` of the acting `Landowner`; ownership checks on any resource that references a landowner compare the resource's `landowner_id` field to `X-User-ID`. When `X-User-Role` is `BurnBoss`, `X-User-ID` is the `id` of the acting `BurnBoss`; author-scoped actions compare the plan's `author_boss_id` to `X-User-ID`. When `X-User-Role` is `AgencyReviewer`, `X-User-ID` is likewise the `id` of a `BurnBoss` — reviewers are certified burn bosses acting in a review capacity — and segregation-of-duties checks compare it against the plan's `author_boss_id`. When `X-User-Role` is `Contractor`, `X-User-ID` is the `id` of the acting `Contractor`, compared against an assignment's `contractor_id`. When `X-User-Role` is `AssociationAdmin`, `AirQualityOfficer`, or `IncidentCommander`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`.

Broadly, `AssociationAdmin` runs the registry (landowners, burn bosses, contractors), the fund, and all cost-share and liability adjudication. A `Landowner` registers parcels and applies for cost-share on their own holdings. A `BurnBoss` authors plans and leads every burn-day action on their own plans. An `AgencyReviewer` approves plans, issues permits, and accepts safety documents and monitoring reports — never on their own authored work. An `AirQualityOfficer` decides smoke-management approvals. An `IncidentCommander` reports and runs incident response and cost assessment. A `Contractor` confirms or declines their own crew assignments.

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

List endpoints accept two query parameters. `limit` caps the number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` skips a number of items from the front of the result set and defaults to 0. The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

Unless an endpoint states otherwise, list results are sorted by `created_at` in ascending order.

### 2.4. Common Resource Properties

Every primary resource carries a standard set of system-managed fields:

- `id` — a server-minted UUID, with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, fixed at creation.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation.
- `version` — an integer that starts at its initial value on creation and increments by exactly one on every mutation, including system-driven state transitions.

As a rule, every state transition described in §3 increments the acting entity's `version` by one and refreshes its `updated_at`. A small set of system bookkeeping moves are explicitly silent on versioning and therefore leave both fields unchanged: the supersession of a smoke approval or an ignition plan when a newer one is filed, a resource order's fill-level adjustments between `SUBMITTED`, `PARTIALLY_FILLED`, and `FILLED` (including cascade cancellation of an order), and the clock sweep that flips a monitoring report from `DUE` to `OVERDUE`.

Two audit-record resources are deliberately lighter: a `WeatherObservation` and a `GoNoGoChecklist` carry only `id` and `created_at` — both `updated_at` and `version` are absent from them.

### 2.5. The Logical Clock and Scheduled Sweeps

The server runs on a logical clock, not wall-clock time. At startup the clock reads exactly `2026-05-01T00:00:00Z`, and until it is explicitly set it never drifts from that value. An `AssociationAdmin`-only test-driving capability sets the logical clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`. All temporal rules in this document — windows, lead times, freshness limits, deadlines, expirations — are evaluated against this clock.

Setting the clock performs four time sweeps. An `APPROVED` burn plan whose `planned_window_end` has passed and for which no execution ever reached `CLOSED` or `WILDFIRE_RESPONSE` moves to `EXPIRED`, and its `ISSUED` permit moves to `EXPIRED` with it (a permit also expires when the plan's window has passed with no non-terminal execution outstanding). A `SCHEDULED` execution whose `scheduled_date` has passed moves to `LAPSED`. A monitoring report still `DUE` whose `due_at` has passed moves to `OVERDUE`; this particular sweep is bookkeeping and does not bump the report's `version`.

### 2.6. Nested Resource Retrieval

For any endpoint whose path nests one resource beneath another, identifiers are validated strictly left to right: the first path identifier that does not resolve to an existing resource rejects the request immediately with a `404 Not Found`, and later identifiers are not examined. Existence failures carry resource-specific error codes — `ERR_ASSOCIATION_NOT_FOUND`, `ERR_LANDOWNER_NOT_FOUND`, `ERR_PARCEL_NOT_FOUND`, `ERR_BOSS_NOT_FOUND`, `ERR_CONTRACTOR_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_NOTIFICATION_NOT_FOUND`, `ERR_SMOKE_APPROVAL_NOT_FOUND`, `ERR_CONTINGENCY_NOT_FOUND`, `ERR_IGNITION_PLAN_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_EXECUTION_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND` — with `ERR_NOT_FOUND` as the generic fallback. A request for a permit under a non-existent plan therefore fails with `ERR_PLAN_NOT_FOUND` before the permit id is ever looked up.

### 2.7. Validation Order of Precedence

When several checks could reject the same request, the server evaluates them in a fixed order so that the surfaced error is deterministic: first the presence of the two authentication headers; second role authorization for the endpoint; third left-to-right existence of path resources; fourth ownership; fifth segregation of duties; sixth the optimistic-concurrency expected-version check, which runs before any business rule; seventh the lifecycle-state precondition of the attempted transition; eighth burn-day safety conditions (weather within prescription, holding-force coverage, accepted safety documents); ninth certification, waiver, and standing gates; tenth referential alignment such as the execution's pinned plan version and parcel-ownership matching; eleventh uniqueness and capacity constraints; twelfth temporal windows and deadlines; thirteenth fiscal sufficiency; and fourteenth, last, field-level input shape. A body that cannot be parsed at all is reported as malformed before authentication is even attempted; for well-formed bodies, however, field-level checks run last so that authentication, state, and business errors surface first.

### 2.8. Optimistic Concurrency Control

Two write operations carry an optimistic-concurrency contract, and no other endpoint takes a version field.

Creating a burn plan requires the client to send `expected_parcel_version` holding the parcel `version` the client last observed. If the parcel's current `version` differs — for example because another writer has just created a plan on the same parcel, which itself advances the parcel's version — the create is rejected with `ERR_STALE_VERSION` and HTTP status 412, preventing the client from building on a parcel view it has not re-read.

Uploading an ignition plan requires the client to send `expected_burn_plan_version` holding the burn plan `version` the client last observed. Because filing an ignition plan legitimately supersedes the prior ignition plan and advances the burn plan's own `version`, a second filing carrying an older value is stale; it is rejected with `ERR_STALE_VERSION` and HTTP status 412.

### 2.9. Monetary Precision and Rounding

All monetary amounts are carried as integer cents; no fractional cent ever appears in the API. Where a money computation produces a fractional cent, the intermediate line amount is rounded half-up to a whole cent before any summation. In particular, cost-share estimates and final reimbursements follow a pinned rounding order: each treatment line is rounded to whole cents first, and only then are the rounded line amounts summed. Summing unrounded line values and rounding once at the end is a different computation — it diverges by cents — and is not permitted. Percentage scores are integers rounded half-up, and fund arithmetic is exact integer cents throughout.

### 2.10. The Association Fund Ledger

Each association operates a single liability and cost-share fund, exposed as `fund_balance_cents`. The fund opens at the `initial_fund_cents` supplied when the association is created, and its balance is a pure ledger: the initial amount, plus every deposit, minus the `fund_payout_cents` of every liability payout that has not been reversed, minus every cost-share installment disbursed. Deposits and debits each mutate the association resource, refreshing `updated_at` and incrementing its `version`.

The ledger is compensating: reversing a liability payment credits the fund by exactly the reversed claim's recorded `fund_payout_cents`, restoring the balance to precisely its pre-payment value; the reversed payout remains recorded on the claim but is excluded from the payout sum thereafter. A negative final cost-share installment (a clawback) credits the fund by the same magnitude it removes from the agreement.

The fund also carries a computed `fund_posture`. When `fund_balance_cents` falls below 200,000 cents — two thousand dollars — the posture is `FUND_RESTRICTED`; otherwise it is `FUND_NORMAL`.

## 3. Business Logic & Workflows

### 3.1. Founding the Association and Its Registry

Before any fire is planned, the association itself is constituted. An `AssociationAdmin` creates it with a display `name` and three policy numbers that shadow every later calculation: `airshed_daily_acres_cap`, the maximum aggregate approved burn acres per airshed per day; `single_claim_cap_cents`, the per-claim payout ceiling of the liability fund; and `landowner_liability_cap_cents`, the per-incident cap on a landowner's liability under the standard allocation. The creation payload also supplies `initial_fund_cents`, which becomes the opening `fund_balance_cents`. The administrator may later top the fund up with a deposit carrying an `amount_cents`, which is added to `fund_balance_cents` and bumps the association's `version`.

Landowners join through the administrator as well. A landowner record holds a `name`, a `contact_email`, and the `liability_waiver_signed` flag attesting that the association's liability waiver is on file. Two computed fields track the member's standing with the program: `outstanding_liability_cents`, which starts at 0 and accumulates unpaid landowner-liable shares from adjudicated claims, and `standing`, which is `GOOD_STANDING` normally and flips to `SUSPENDED` while any claim adjudicated `LANDOWNER_LIABLE` against them still has an outstanding balance more than thirty days after its `adjudicated_at`. The landowner list endpoint can be filtered by `standing`.

A landowner registers each parcel of ground themselves, acting as the owning `Landowner` — the payload's `landowner_id` must equal the caller's `X-User-ID`, otherwise the request is rejected with `ERR_NOT_RESOURCE_OWNER`, and the waiver must be on file: a caller whose `liability_waiver_signed` is not true is rejected with `ERR_LANDOWNER_WAIVER_UNSIGNED`. The parcel captures a `name`, its total `acreage` (a positive integer), a `fuel_model` of `GRASS`, `BRUSH`, or `TIMBER`, a `slope_class` of `FLAT`, `MODERATE`, or `STEEP`, the `wui_adjacent` flag marking adjacency to the wildland-urban interface, an `airshed_id` for smoke-capacity accounting, and a `drought_index` between 0 and 30. From these immutable attributes the system computes `hazard_score` once, at registration: the fuel weight (20 for `GRASS`, 35 for `BRUSH`, 50 for `TIMBER`), plus the slope weight (0 for `FLAT`, 10 for `MODERATE`, 20 for `STEEP`), plus 20 when the parcel is `wui_adjacent`, plus the `drought_index`. The score ranges from 0 to 120 and, because its inputs never change, is never recomputed. Parcel lists can be filtered by `landowner_id`.

Two professional registries complete the setup, both administered by the `AssociationAdmin`. A burn boss is registered with a `name` and a `certification_tier` of `RXB1`, `RXB2`, or `RXB3`, which later gates the size and hazard of plans they may author. A contractor is registered with a company `name`, a `resource_type` of `ENGINE`, `HAND_CREW`, `DOZER`, or `WATER_TENDER`, the `capacity_units` the company can field, the `personnel_per_unit` each unit carries, and a `day_rate_cents_per_unit`. Two counters track reliability: `no_show_count`, starting at 0 and incremented on every `NO_SHOW` assignment, and a computed `standing` that becomes `SUSPENDED` once `no_show_count` reaches 2 or more. A contractor's `available_units` is computed as `capacity_units` minus the units committed on that contractor's assignments currently in `ASSIGNED` or `CONFIRMED` status; the contractor directory can be filtered by `resource_type`, and a contractor's full assignment book is listable.

### 3.2. Authoring, Reviewing, and Superseding a Burn Plan

The burn plan is the program's central artifact. A `BurnBoss` drafts one against a parcel, supplying the `parcel_id`, the OCC token `expected_parcel_version` (§2.8), the `planned_acres` to be treated — positive, and no more than the parcel's `acreage` — and an inclusive prescription window from `planned_window_start` to `planned_window_end`. The prescription itself is six numbers: `max_wind_mph`, `min_fuel_moisture_pct` and `max_fuel_moisture_pct`, `min_rh_pct`, `min_temp_f` and `max_temp_f`, and `min_mixing_height_ft`; every minimum must not exceed its paired maximum. The work is itemized as `treatment_lines`, a non-empty array of lines each carrying a `category` of `BROADCAST`, `UNDERSTORY`, or `PILE_BURN`, a `rate_class` of `GRASS`, `BRUSH`, or `TIMBER`, and an integer `acres`; the acreage across all lines must sum exactly to `planned_acres`. A plan may optionally name a `supersedes_plan_id`, declaring itself the revision of a prior plan on the same parcel. On creation the server stamps `author_boss_id` from the caller's `X-User-ID`, sets `status` to `DRAFT`, and — this is the side effect that makes the OCC token meaningful — increments the parcel's `version` by one.

Certification gates authorship. An `RXB1` boss may author a plan only when `planned_acres` is at most 40 and the parcel's `hazard_score` is at most 40; an `RXB2` boss only when `planned_acres` is at most 200 and the `hazard_score` is at most 70; an `RXB3` boss is unrestricted. All bounds are inclusive, and a violation is rejected with `ERR_BOSS_CERTIFICATION_INSUFFICIENT`. A parcel may host at most one plan in an active status — `DRAFT`, `SUBMITTED`, `REVISION_REQUESTED`, or `APPROVED`; a second is rejected with `ERR_ACTIVE_PLAN_EXISTS_FOR_PARCEL`, except that a draft whose `supersedes_plan_id` names the parcel's currently `APPROVED` plan is allowed, and the incumbent leaves the active set only when the successor is itself approved. Malformed bodies, missing or unknown fields, type mismatches, empty `treatment_lines`, or line acreage not summing to `planned_acres` are rejected with `ERR_INVALID_REQUEST`; a value outside an enum's declared member set with `ERR_INVALID_ENUM`; inverted prescription ranges or windows and non-positive acreage with `ERR_INVALID_PRESCRIPTION_PARAMS`.

The review loop is cyclic and may repeat without bound. The author submits a `DRAFT` plan, moving it to `SUBMITTED` — attempting this on anything but a `DRAFT` fails with `ERR_PLAN_NOT_DRAFT`, and only the author may submit, else `ERR_NOT_RESOURCE_OWNER`. An `AgencyReviewer` may send a `SUBMITTED` plan back to `REVISION_REQUESTED` (any other state: `ERR_PLAN_NOT_SUBMITTED`), from which the author alone pulls it back to `DRAFT` via revision (`ERR_PLAN_NOT_IN_REVISION` otherwise, `ERR_NOT_RESOURCE_OWNER` for non-authors). Approval is the consequential move: an `AgencyReviewer` approves a `SUBMITTED` plan to `APPROVED`, but the reviewer's `X-User-ID` must differ from the plan's `author_boss_id` — a reviewer approving their own authored work is rejected with `ERR_SEGREGATION_OF_DUTIES_VIOLATION`. Approval records the reviewer in `approved_by_boss_id`, and it fires the supersession cascade: if `supersedes_plan_id` is set and that prior plan is currently `APPROVED`, the prior plan moves to `SUPERSEDED`, the prior plan's `ISSUED` permit (if any) moves to `SUSPENDED`, and any cost-share agreement on the superseded plan sitting in `APPROVED` or `PARTIALLY_DISBURSED` moves to `SUSPENDED`.

The author may cancel a plan while it is in `DRAFT`, `SUBMITTED`, `REVISION_REQUESTED`, or `APPROVED`; cancelling a terminal plan is rejected with `ERR_PLAN_NOT_CANCELLABLE`, and a non-author with `ERR_NOT_RESOURCE_OWNER`. Cancellation cascades downward: the plan's resource orders in `DRAFT`, `SUBMITTED`, or `PARTIALLY_FILLED` move to `CANCELLED`, their crew assignments in `ASSIGNED` or `CONFIRMED` move to `RELEASED` (restoring contractor availability), and a non-terminal execution of the plan — one in `SCHEDULED` or `BRIEFED` only — moves to `CANCELLED`. Finally, plans age out: the clock sweep (§2.5) expires an `APPROVED` plan whose window has closed without any execution reaching `CLOSED` or `WILDFIRE_RESPONSE`, moving it to `EXPIRED` and its `ISSUED` permit to `EXPIRED`. Plan listings support filters on `parcel_id`, `author_boss_id`, `approved_by_boss_id`, `supersedes_plan_id`, and `status`.

### 3.3. Permits, Neighbor Notification, and Smoke Management

With a plan `SUBMITTED` or `APPROVED`, the author requests a burn permit, supplying `notifications_required` — the count of neighbor notifications the agency demands, zero or more. Requesting a permit against a plan in any other state is rejected with `ERR_PLAN_NOT_SUBMITTED`, and a plan may have at most one permit open — in `UNDER_REVIEW`, `ISSUED`, or `SUSPENDED` — with duplicates rejected as `ERR_PERMIT_ALREADY_OPEN`. The new permit is born `UNDER_REVIEW`, bound to its plan through `burn_plan_id`, with `issued_by_boss_id` null until issuance. Permit listings can be filtered by `burn_plan_id`, `issued_by_boss_id`, or `status`.

Neighbor notification is tracked as child records of the permit, each bound to its parent through `burn_permit_id`. The author records each notification with a `recipient_name` and a `channel` of `MAIL`, `PHONE`, or `IN_PERSON`; it starts `REQUESTED`. When the neighbor has actually been reached, the author confirms the notification — possible only while `REQUESTED`, else `ERR_NOTIFICATION_NOT_REQUESTED` — which stamps `confirmed_at` with the current clock, moves it to `CONFIRMED`, and recomputes two rollups on the permit: `notifications_completed`, the count of its `CONFIRMED` notifications, and `notified_completed_at`, the latest `confirmed_at` among them (null when none exist).

Issuance is a six-gate decision by an `AgencyReviewer`. The permit must be `UNDER_REVIEW` (`ERR_PERMIT_NOT_UNDER_REVIEW`); the reviewer's identity must differ from the plan's `author_boss_id` (`ERR_SEGREGATION_OF_DUTIES_VIOLATION`); the plan must be `APPROVED` (`ERR_PLAN_NOT_APPROVED`); an `ACCEPTED` contingency plan must exist for the plan (`ERR_CONTINGENCY_NOT_ACCEPTED`); `notifications_completed` must have reached `notifications_required` (`ERR_NOTIFICATIONS_INCOMPLETE`); and the plan's `planned_window_end` must not have passed the current clock date (`ERR_PLAN_WINDOW_LAPSED`). Issuance stamps `issued_by_boss_id` and moves the permit to `ISSUED`. Denial is simpler: any `UNDER_REVIEW` permit may be denied to `DENIED`.

An issued permit can be suspended, reinstated, or revoked. Suspension — by a reviewer, or by the system when the plan is superseded or an execution enters `WILDFIRE_RESPONSE` — requires `ISSUED` (`ERR_PERMIT_NOT_ISSUED`), moves the permit to `SUSPENDED`, and drags the plan's cost-share agreements in `APPROVED` or `PARTIALLY_DISBURSED` down to `SUSPENDED` with it. Reinstatement requires the permit to be `SUSPENDED` (`ERR_PERMIT_NOT_SUSPENDED`) and the plan to be `APPROVED` (`ERR_PLAN_NOT_APPROVED`), and returns it to `ISSUED`. Revocation from either `ISSUED` or `SUSPENDED` (`ERR_PERMIT_NOT_REVOKABLE` otherwise) is final: `REVOKED`.

Smoke management runs on a parallel track owned by the air-quality regulator. The burn boss files a smoke-management request for a plan — which must be `APPROVED`, else `ERR_PLAN_NOT_APPROVED` — naming a `requested_burn_date` and a positive `requested_acres` no larger than the plan's `planned_acres`. The request copies its `airshed_id` from the plan's parcel, starts `SUBMITTED`, and supersedes any prior smoke approval on the same plan that is still `SUBMITTED`, `APPROVED`, or `CONDITIONALLY_APPROVED`, pushing those to `SUPERSEDED` without touching their `version`. The `AirQualityOfficer` then decides, sending a `decision` of `APPROVED`, `CONDITIONALLY_APPROVED`, or `DENIED` with an optional `decision_note`; deciding anything not `SUBMITTED` fails with `ERR_SMOKE_NOT_SUBMITTED`. The two approving decisions enforce airshed capacity: the sum of `requested_acres` across the *other* approvals in `APPROVED` or `CONDITIONALLY_APPROVED` for the same `airshed_id` and the same `requested_burn_date`, plus this request's `requested_acres`, must not exceed the association's `airshed_daily_acres_cap` — a total exactly equal to the cap passes, and an excess is rejected with `ERR_AIRSHED_CAPACITY_EXCEEDED`. Denial runs no capacity check. A conditional approval can later be cleaned to unconditional: clearing conditions requires `CONDITIONALLY_APPROVED` (`ERR_SMOKE_NOT_CONDITIONAL`) and moves it to `APPROVED`. Either approved flavor can be withdrawn — `ERR_SMOKE_NOT_WITHDRAWABLE` guards anything not `APPROVED` or `CONDITIONALLY_APPROVED` — ending at `WITHDRAWN`.

### 3.4. Contingency and Ignition Planning

Two safety documents must be accepted before fire is ever lit, and both follow the same segregation-of-duties discipline: the reviewer who accepts may not be the plan's author.

The contingency plan describes what happens when things go wrong. The author drafts one against an `APPROVED` plan, providing free-text `escape_trigger_points` describing the conditions that trigger escape response, a `min_holding_personnel` floor (zero or more), a `water_supply_description`, and an `evacuation_route_description`; it starts `DRAFT`. An `AgencyReviewer` accepts a `DRAFT` contingency plan — anything else earns `ERR_CONTINGENCY_NOT_DRAFT`, an author accepting their own document earns `ERR_SEGREGATION_OF_DUTIES_VIOLATION`, and at most one contingency plan per burn plan may be `ACCEPTED`, a second acceptance rejected with `ERR_CONTINGENCY_ALREADY_ACCEPTED`. The reviewer may instead reject it with a `reason`, moving it to `REJECTED`, and the author alone may return a `REJECTED` document to `DRAFT` for rework (`ERR_CONTINGENCY_NOT_REJECTED` from any other state, `ERR_NOT_RESOURCE_OWNER` for non-authors). The reject-revise loop may repeat as often as needed.

The ignition plan sequences the burn itself. Filing one is an OCC-guarded write: the payload carries `expected_burn_plan_version` matching the plan's current `version` (§2.8), along with an `ignition_method` of `DRIP_TORCH`, `AERIAL`, or `HAND_LINE`, a `test_fire_required` flag, and `steps` — an ordered array of one or more entries, each with a `step_index` (unique, ascending from 1), a `zone_label`, and a `technique`. The plan must be `APPROVED` (`ERR_PLAN_NOT_APPROVED`). Filing supersedes every prior ignition plan on the same plan in `DRAFT`, `ACCEPTED`, or `REJECTED`, moving those to `SUPERSEDED` without a version bump, and — the reason the OCC token exists — increments the burn plan's own `version` by one. The new document starts `DRAFT`. An `AgencyReviewer` accepts (`ERR_IGNITION_PLAN_NOT_DRAFT` unless `DRAFT`; `ERR_SEGREGATION_OF_DUTIES_VIOLATION` for self-acceptance) to `ACCEPTED`, or rejects with a `reason` to `REJECTED`; the author revises a `REJECTED` document back to `DRAFT` (`ERR_IGNITION_PLAN_NOT_REJECTED`, `ERR_NOT_RESOURCE_OWNER`).

### 3.5. Ordering Resources and Mustering Crews

Holding force is computed, not negotiated. When the author creates a resource order against an `APPROVED` plan (`ERR_PLAN_NOT_APPROVED` otherwise), the order is born `DRAFT` and four requirements are pinned at that moment from the plan and parcel. `required_engines` is the planned acreage divided by 40 and scaled by a fuel factor — 1.0 for `GRASS`, 1.5 for `BRUSH`, 2.0 for `TIMBER` — the product rounded up to the next whole engine, plus two additional engines when the parcel is `wui_adjacent`. `required_hand_crews` is the planned acreage divided by 80 and rounded up, never less than one crew, and then doubled when the parcel's `slope_class` is `STEEP`. `required_dozers` is exactly one when the parcel's `fuel_model` is `TIMBER` and the planned acreage is strictly greater than 100, and zero otherwise. `required_water_tenders` is the planned acreage divided by 60 rounded down to a whole number, but never less than one. Submitting the order — only from `DRAFT`, else `ERR_ORDER_NOT_DRAFT` — moves it to `SUBMITTED` and opens it for crewing.

The author assigns contractor units against an open order — one in `SUBMITTED` or `PARTIALLY_FILLED`, else `ERR_ORDER_NOT_OPEN` — supplying a `contractor_id`, the `units` committed (a positive integer), and a duty window from `window_start` (inclusive) to `window_end` (exclusive, and necessarily after the start). The contractor must be in `GOOD_STANDING` (`ERR_CONTRACTOR_SUSPENDED` for a suspended company), the committed units must fit within the contractor's `available_units` (`ERR_CONTRACTOR_CAPACITY_EXCEEDED`), and the window must respect a one-day rest buffer against every other `ASSIGNED` or `CONFIRMED` window of the same contractor: separation exists when the new `window_start` falls at least one full day after the other window's `window_end`, or the new `window_end` falls at least one full day before the other window's `window_start`; when neither separation holds, the assignment is rejected with `ERR_CONTRACTOR_WINDOW_CONFLICT`. The new assignment starts `ASSIGNED`, bound to its order via `resource_order_id`.

The contractor then answers. Confirming requires the assignment to be `ASSIGNED` (`ERR_ASSIGNMENT_NOT_ASSIGNED`), the caller's `X-User-ID` to equal the assignment's `contractor_id` (`ERR_NOT_RESOURCE_OWNER`), and it re-evaluates standing (`ERR_CONTRACTOR_SUSPENDED`), capacity (`ERR_CONTRACTOR_CAPACITY_EXCEEDED`), and the window-conflict rule (`ERR_CONTRACTOR_WINDOW_CONFLICT`) at confirmation time. Declining is open to the same owner from `ASSIGNED` and ends at `DECLINED`. Confirmation moves the assignment to `CONFIRMED` and recomputes the order's fill: `confirmed_engines`, `confirmed_hand_crews`, `confirmed_dozers`, and `confirmed_water_tenders` are the summed units of `CONFIRMED` assignments whose contractors field the matching `resource_type`. The order is `FILLED` exactly when every one of the four confirmed counts meets or exceeds its required twin — equality counts as filled — otherwise `PARTIALLY_FILLED` when any confirmed count is positive, and `SUBMITTED` again while coverage is zero. These system fill-level moves are bookkeeping and do not bump the order's `version`.

The author holds two levers over confirmed crews. Releasing a `CONFIRMED` assignment (`ERR_ASSIGNMENT_NOT_CONFIRMED` from other states; manual release is restricted to the plan's author, `ERR_NOT_RESOURCE_OWNER`) moves it to `RELEASED`, frees the units back into the contractor's availability, and recomputes the order — which may drop from `FILLED` back to `PARTIALLY_FILLED`. Marking a no-show, likewise restricted to the author against a `CONFIRMED` assignment, moves it to `NO_SHOW`, increments the contractor's `no_show_count` by one — recomputing `standing`, which suspends the contractor at two or more — and recomputes the order fill the same way. When an execution eventually closes, every `CONFIRMED` assignment on the plan's orders completes to `COMPLETED`, freeing its units. The availability invariant is compensating throughout: an assignment followed by a release, decline, no-show, or completion restores `available_units` to exactly its prior value.

### 3.6. Burn Day: Scheduling, Briefing, Weather, and the Go/No-Go Call

Against an `APPROVED` plan (`ERR_PLAN_NOT_APPROVED`), the author schedules the burn by naming a `scheduled_date`, which must fall inside the plan's prescription window — on or after `planned_window_start` and on or after no later than `planned_window_end`, both ends inclusive, else `ERR_SCHEDULED_DATE_OUTSIDE_WINDOW`. A plan may have at most one non-terminal execution (`ERR_EXECUTION_ALREADY_OPEN`), and the parcel imposes its own discipline: no other non-terminal execution may exist on the parcel, and when a prior execution on the parcel has closed, the new `scheduled_date` must fall strictly more than thirty days after that execution's `closed_at` — either violation is `ERR_PARCEL_EXECUTION_WINDOW_CONFLICT`. Scheduling pins `plan_version_at_schedule` to the plan's current `version` and opens the execution with its `phase` at `SCHEDULED`.

The morning of the burn, briefing is the great gate. The author briefs a `SCHEDULED` execution (`ERR_EXECUTION_NOT_SCHEDULED`; non-authors get `ERR_NOT_RESOURCE_OWNER`), and eight further conditions must all hold. The pinned `plan_version_at_schedule` must still equal the plan's current `version` — a plan edited since scheduling is rejected with `ERR_STALE_PLAN_VERSION`, forcing re-scheduling against the plan as it now stands. The plan's resource order must be `FILLED` (`ERR_HOLDING_FORCE_INADEQUATE`). An ignition plan in `ACCEPTED` must exist (`ERR_IGNITION_PLAN_NOT_ACCEPTED`), as must an `ACCEPTED` contingency plan (`ERR_CONTINGENCY_NOT_ACCEPTED`). The plan's permit must be `ISSUED` (`ERR_PERMIT_NOT_ISSUED`). A smoke approval in `APPROVED` or `CONDITIONALLY_APPROVED` must exist for the plan whose `requested_burn_date` equals the `scheduled_date` (`ERR_SMOKE_APPROVAL_NOT_VALID`). The current clock date must be exactly the `scheduled_date` (`ERR_WRONG_BURN_DAY`). And the forty-eight-hour neighbor lead time must have elapsed: `notified_completed_at` must be set, and the current clock must be at least 48 hours past it — exactly 48 hours and zero seconds passes — else `ERR_NOTIFICATION_LEAD_TIME_UNMET`. A successful briefing moves the execution to `BRIEFED`.

Weather is observed continuously from the field. The author records an observation while the execution is in any non-terminal phase, supplying `observed_at` and the five readings — `wind_mph`, `fuel_moisture_pct`, `rh_pct`, `temp_f`, and `mixing_height_ft`. The system computes `in_prescription` against the plan's prescription: sustained wind no greater than `max_wind_mph`; fuel moisture between `min_fuel_moisture_pct` and `max_fuel_moisture_pct`, both ends inclusive; relative humidity at least `min_rh_pct`; temperature between `min_temp_f` and `max_temp_f`, both ends inclusive; and mixing height at least `min_mixing_height_ft`. Every bound is inclusive — a reading exactly equal to its bound passes. Observations remain retrievable as the execution's weather history.

The go/no-go call then decides whether fire meets the ground. The author submits `checklist_answers` covering exactly the six required items — `permit_verified`, `crew_briefed`, `communications_check`, `escape_routes_reviewed`, `weather_within_prescription`, `holding_resources_ready` — each answered `PASS` or `FAIL`; missing items or invalid result values are rejected with `ERR_INCOMPLETE_CHECKLIST`. The execution must be `BRIEFED` (`ERR_EXECUTION_NOT_BRIEFED`). Weather must be fresh: the latest observation — chosen by greatest `observed_at`, ties broken by `created_at` ascending so the later-created row wins — must exist and be no more than 60 minutes old against the current clock, an observation exactly 60 minutes old passing (`ERR_WEATHER_OBSERVATION_STALE`). That latest observation must be in prescription (`ERR_WEATHER_OUT_OF_PRESCRIPTION`). And confirmed units per resource type must still meet the required counts (`ERR_HOLDING_FORCE_INADEQUATE`). When every precondition holds and all six answers are `PASS`, the system records a `GoNoGoChecklist` — capturing the `burn_execution_id`, a `weather_observation_id` snapshot of the observation the verdict rested on (an execution-scoped audit reference; the observation itself is discovered through the execution's weather-observation list), an echo of the submitted `answers`, the computed `verdict` of `GO`, and the `evaluated_at` clock time — and the execution advances to `TEST_FIRE`. If any answer is `FAIL`, the checklist is recorded with verdict `NO_GO` and the execution moves to `STOOD_DOWN`. A rejected evaluation records no checklist. The author may also stand a `BRIEFED` execution down voluntarily at any time, moving it to `STOOD_DOWN` without a checklist, and may cancel a `SCHEDULED` execution outright, moving it to `CANCELLED` (`ERR_EXECUTION_NOT_SCHEDULED`; authors only, `ERR_NOT_RESOURCE_OWNER`); the plan-cancellation cascade moves a `SCHEDULED` or `BRIEFED` execution to `CANCELLED` the same way. Should the `scheduled_date` pass with the execution still `SCHEDULED`, the clock sweep moves it to `LAPSED`.

### 3.7. On the Fireline: Ignition, Escape, and Wildfire Conversion

A passed go/no-go opens the test fire. When the test fire's behavior is acceptable, starting primary ignition requires the execution to be in `TEST_FIRE` (`ERR_EXECUTION_NOT_IN_TEST_FIRE`) with weather still fresh — the latest observation no more than 60 minutes old (`ERR_WEATHER_OBSERVATION_STALE`) — and still in prescription (`ERR_WEATHER_OUT_OF_PRESCRIPTION`); the execution moves to `IGNITION`. Completing ignition (`ERR_EXECUTION_NOT_IGNITING` unless `IGNITION`) records the `acres_blackened` from the author's report and moves to `HOLDING`.

The walk down from active fire is gated on a clean incident board. Beginning patrol requires `HOLDING` (`ERR_EXECUTION_NOT_HOLDING`) and that no incident of the execution sits in `REPORTED` or `CONFIRMED` (`ERR_OPEN_INCIDENTS_EXIST`), moving to `PATROL`. Beginning mop-up requires `PATROL` (`ERR_EXECUTION_NOT_PATROLLING`) and the same incident check, moving to `MOP_UP`. Closing requires `MOP_UP` (`ERR_EXECUTION_NOT_MOPPING_UP`) and the same check again, moving the execution to `CLOSED`; closure stamps `closed_at` with the current clock, records the observed `actual_treatment_lines` (per-`category`, per-`rate_class` acres) from the author's submission, spawns the three monitoring reports described in §3.8, and completes every `CONFIRMED` crew assignment on the plan's orders to `COMPLETED`, freeing their units.

Escape is the fork in the road. From `TEST_FIRE`, `IGNITION`, `HOLDING`, or `PATROL` — and only those, else `ERR_EXECUTION_NOT_ESCAPABLE` — the author may declare an escape, which moves the execution to `ESCAPED` and simultaneously creates an `Incident` of `incident_type` `ESCAPE` with `response_status` `REPORTED` and `billing_status` `UNASSESSED`. Lesser events are reported manually by the `IncidentCommander` against an execution in `TEST_FIRE`, `IGNITION`, `HOLDING`, `PATROL`, or `ESCAPED`, with an `incident_type` of `SPOT` or `SMOKE_INTRUSION` — the `ESCAPE` type is reserved to the escape declaration and is rejected on manual reports; manual incidents likewise start `REPORTED` and `UNASSESSED`.

Incident response runs on two independent axes. On the response axis, the `IncidentCommander` confirms a `REPORTED` incident (`ERR_INCIDENT_NOT_REPORTED`) to `CONFIRMED`, or dismisses it from `REPORTED` to `DISMISSED` as a false alarm. A `CONFIRMED` incident can be marked contained (`ERR_INCIDENT_NOT_CONFIRMED`) to `CONTAINED`, and a `CONTAINED` incident closed (`ERR_INCIDENT_NOT_CONTAINED`) to `CLOSED`. The gravest move converts a `CONFIRMED` incident to `DECLARED_WILDFIRE` — and that conversion cascades: the parent execution, waiting in `ESCAPED`, moves to `WILDFIRE_RESPONSE`; that move suspends the plan's `ISSUED` permit; and the permit's suspension suspends the plan's cost-share agreements in `APPROVED` or `PARTIALLY_DISBURSED`. On the billing axis, once an incident is `CONTAINED`, `CLOSED`, or `DECLARED_WILDFIRE` (`ERR_INCIDENT_NOT_COSTABLE` otherwise) and its billing is still `UNASSESSED` (`ERR_BILLING_NOT_UNASSESSED`), the commander assesses costs, recording `suppression_cost_cents` and `escaped_acres` and moving billing to `ASSESSED`. Filing a liability claim then moves billing `ASSESSED` to `BILLED`; a paid claim settles it to `SETTLED`; a payment reversal disputes it to `DISPUTED`; and paying again after reversal returns it to `SETTLED`.

### 3.8. Post-Burn Monitoring and Cost-Share Reimbursement

Closure is not the end of the work — it starts the accountability clock. Closing an execution creates three monitoring reports, one of each `report_type`: `FIRST_24H` due 24 hours after `closed_at`, `SEVEN_DAY` due 7 days after, and `THIRTY_DAY` due 30 days after, each born `DUE` with its `due_at` set accordingly. The clock sweep flips a `DUE` report whose `due_at` has passed to `OVERDUE` without a version bump. An execution's reports list in `due_at` ascending order, the one exception to the default `created_at` sort.

The author submits a report while it is `DUE`, `OVERDUE`, or `DEFICIENT` (`ERR_REPORT_NOT_SUBMITTABLE` otherwise; non-authors get `ERR_NOT_RESOURCE_OWNER`), providing the observed `actual_treatment_lines`. Submission computes the `effectiveness_score`: each treatment category carries a weight — 1.0 for `BROADCAST`, 0.8 for `UNDERSTORY`, 0.6 for `PILE_BURN` — the planned weighted acreage is the sum over the cost-share agreement's `treatment_lines` of each line's `acres` times its category weight, the actual weighted acreage is the same sum over the submitted `actual_treatment_lines` with categories absent from the actuals contributing zero, and the score is one hundred times the actual weighted acreage divided by the planned weighted acreage, rounded half-up to an integer percent with no upper clamp. The report moves to `SUBMITTED`. An `AgencyReviewer` — never the plan's author, `ERR_SEGREGATION_OF_DUTIES_VIOLATION` — accepts a `SUBMITTED` report (`ERR_REPORT_NOT_SUBMITTED`) to `ACCEPTED`, and acceptance of the `THIRTY_DAY` report recomputes the linked agreement's `final_reimbursement_cents`. The reviewer may instead mark a `SUBMITTED` report deficient, recording the supplied `reason` into `deficiency_reason` and moving it to `DEFICIENT`, from which the author may resubmit; `deficiency_reason` stays null on reports never marked deficient.

Cost-share is how the association pays landowners for completed fuel work. A `Landowner` applies with their own `landowner_id` (which must equal `X-User-ID`, else `ERR_NOT_RESOURCE_OWNER`), the `burn_plan_id` being cost-shared, a `funding_tier` of `STANDARD`, `PRIORITY`, or `LEGACY`, and their own non-empty `treatment_lines`. The plan must be `APPROVED` (`ERR_PLAN_NOT_APPROVED`), the applicant must actually own the parcel the plan targets (`ERR_PARCEL_OWNERSHIP_MISMATCH`), the applicant must be in `GOOD_STANDING` (`ERR_LANDOWNER_NOT_IN_GOOD_STANDING`), and at most one agreement per plan may be live in `SUBMITTED`, `UNDER_REVIEW`, `APPROVED`, `PARTIALLY_DISBURSED`, or `SUSPENDED` (`ERR_ACTIVE_AGREEMENT_EXISTS_FOR_PLAN`). Creation computes `provisional_estimate_cents`: for each treatment line, the line's `acres` multiplied by the per-acre rate for its `rate_class` — 15,327 cents for `GRASS`, 28,750 for `BRUSH`, 46,000 for `TIMBER` — and by the tier's share percentage — 0.50 for `STANDARD`, 0.75 for `PRIORITY`, 0.65 for `LEGACY` — with each line rounded half-up to a whole cent first and the rounded lines then summed (§2.9). The agreement is born `SUBMITTED`, and agreement lists can be filtered by `landowner_id`, `burn_plan_id`, or `status`.

An `AssociationAdmin` moves a `SUBMITTED` application to `UNDER_REVIEW` (`ERR_AGREEMENT_NOT_SUBMITTED`), and from there either denies it with a `reason` to `DENIED`, or approves it — never when the approver is the applying landowner, `ERR_SEGREGATION_OF_DUTIES_VIOLATION`; any state other than `UNDER_REVIEW` earns `ERR_AGREEMENT_NOT_UNDER_REVIEW`. Approval stamps `approved_at` with the clock and sets `expires_at` to exactly 365 days after `approved_at`; disbursements attempted after that moment are rejected with `ERR_AGREEMENT_EXPIRED`.

Money moves in two installments. The provisional installment requires an `APPROVED` agreement (`ERR_AGREEMENT_NOT_APPROVED`), an execution of the plan in `CLOSED` phase (`ERR_NO_CLOSED_EXECUTION`), an unexpired agreement, and a fund balance that covers it (`ERR_INSUFFICIENT_ASSOCIATION_FUNDS`); it pays out half of `provisional_estimate_cents`, rounded half-up to a whole cent, adds the installment to `disbursed_cents`, debits the fund by the same amount, and moves the agreement to `PARTIALLY_DISBURSED`. The final installment requires `PARTIALLY_DISBURSED` (`ERR_AGREEMENT_NOT_PARTIALLY_DISBURSED`), an `ACCEPTED` `THIRTY_DAY` monitoring report (`ERR_MONITORING_NOT_ACCEPTED`), and an unexpired agreement. Its size is `final_reimbursement_cents` minus the already-paid `disbursed_cents`. The recomputed `final_reimbursement_cents` applies an effectiveness factor — 1.00 when the accepted report's `effectiveness_score` is at least 80, 0.75 when it is at least 50 but below 80, and 0.00 when below 50, the bounds at 80 and 50 inclusive — multiplying, per line, the actual acres recorded for the line's category in the report by the same rate and share and by the factor, rounding each line half-up to a whole cent, then summing. A final installment of exactly zero is rejected with `ERR_NO_DISBURSEMENT_DUE`, as is any attempt to disburse when nothing is due. A negative final installment is a lawful clawback: `disbursed_cents` decreases and the fund is credited by the same magnitude, and the fund-sufficiency check is skipped for non-positive installments; after the final disbursement `disbursed_cents` equals `final_reimbursement_cents` exactly. A positive final installment still requires the fund to cover it (`ERR_INSUFFICIENT_ASSOCIATION_FUNDS`), and paying it moves the agreement to `FULLY_DISBURSED`.

Suspension and recovery mirror the permit's fortunes. When the plan's permit is suspended or the plan is superseded, the plan's agreements in `APPROVED` or `PARTIALLY_DISBURSED` move to `SUSPENDED`. Reinstatement by an `AssociationAdmin` requires a `SUSPENDED` agreement (`ERR_AGREEMENT_NOT_SUSPENDED`), every liability claim on incidents of the plan's executions resolved into `CLOSED`, `DISMISSED`, or `PAYMENT_REVERSED` (`ERR_CLAIMS_NOT_RESOLVED`), and the plan's permit back in `ISSUED` (`ERR_PERMIT_NOT_ISSUED`); the target state is `APPROVED` when nothing has been disbursed, and `PARTIALLY_DISBURSED` when `disbursed_cents` is positive. The administrator may also cancel an agreement while it is `SUBMITTED`, `UNDER_REVIEW`, or `APPROVED` (`ERR_AGREEMENT_NOT_CANCELLABLE` from any other state), ending it at `CANCELLED`.

### 3.9. Liability Claims and the Association Fund

When suppression has been costed, the bill is split. The `IncidentCommander` files a liability claim against an incident whose billing is `ASSESSED` (`ERR_BILLING_NOT_ASSESSED` otherwise); the claim is born `FILED` with `outcome` `PENDING`, copies `total_suppression_cost_cents` from the incident, binds to it via `incident_id`, and the filing itself moves the incident's billing to `BILLED`. The `AssociationAdmin` then opens the investigation, moving a `FILED` claim (`ERR_CLAIM_NOT_FILED`) to `UNDER_INVESTIGATION`.

Adjudication requires `UNDER_INVESTIGATION` (`ERR_CLAIM_NOT_UNDER_INVESTIGATION`) and takes two inputs: the `outcome` — `LANDOWNER_LIABLE`, `ASSOCIATION_LIABLE`, or `NOT_LIABLE` — and the `negligence_found` flag. A `NOT_LIABLE` outcome dismisses the claim to `DISMISSED`. Either liable outcome adjudicates it to `ADJUDICATED`, stamps `adjudicated_at` with the clock, and computes the split. Under the standard allocation — `negligence_found` false — `landowner_share_cents` is the smaller of the escaped acreage times 25,000 cents per acre and the association's `landowner_liability_cap_cents`. Under the negligence allocation — `negligence_found` true — the landowner share is the escaped acreage times 25,000 cents times 1.5, rounded half-up to a whole cent, with no cap. In both variants `association_share_cents` is the `total_suppression_cost_cents` minus the landowner share. A `LANDOWNER_LIABLE` outcome additionally adds the landowner share to the landowner's `outstanding_liability_cents` — the debt that, thirty days after `adjudicated_at`, suspends the landowner's `standing` (§3.1).

Payment draws on the fund under a pinned evaluation order. Paying requires the claim to be `ADJUDICATED` or `PAYMENT_REVERSED` (`ERR_CLAIM_NOT_ADJUDICATED`). The payout is computed against the fund balance **before** any debit: take that pre-debit balance, halve it and round down to a whole cent, take the smaller of that figure and the association's `single_claim_cap_cents` as the per-claim ceiling, and set `fund_payout_cents` to the smaller of the claim's `association_share_cents` and that ceiling. Using the post-debit balance anywhere in this computation is forbidden. If the computed payout is zero while `association_share_cents` is positive, the payment is rejected with `ERR_INSUFFICIENT_ASSOCIATION_FUNDS`; a zero association share pays out zero legitimately. A successful payment debits the fund by `fund_payout_cents`, moves the claim to `PAID`, and settles the incident's billing to `SETTLED`.

Reversal is the compensating entry. Reversing requires `PAID` (`ERR_CLAIM_NOT_PAID`), credits the fund by exactly the claim's recorded `fund_payout_cents` — restoring the balance to precisely its pre-payment value, per the ledger invariant of §2.10 — moves the claim to `PAYMENT_REVERSED`, and disputes the incident's billing to `DISPUTED`. A reversed claim may be paid again under the same payment rules, returning the incident to `SETTLED`. Either `PAID` or `PAYMENT_REVERSED` may be closed (`ERR_CLAIM_NOT_CLOSABLE` otherwise), ending the claim at `CLOSED`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that act on an existing resource — state transitions, confirmations, and deposits alike — return `200 OK`. Request and response payloads are not repeated here; the workflow narratives of §3 define them.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock; runs the time sweeps | AssociationAdmin |
| POST | `/associations` | Create a burn association | AssociationAdmin |
| GET | `/associations/{id}` | Get an association | Any |
| POST | `/associations/{id}/fund-deposits` | Deposit into the liability/cost-share fund | AssociationAdmin |
| POST | `/landowners` | Register a landowner | AssociationAdmin |
| GET | `/landowners/{id}` | Get a landowner | Any |
| GET | `/landowners` | List landowners | Any |
| POST | `/parcels` | Register a parcel | Landowner |
| GET | `/parcels/{id}` | Get a parcel | Any |
| GET | `/parcels` | List parcels | Any |
| POST | `/burn-bosses` | Register a certified burn boss | AssociationAdmin |
| GET | `/burn-bosses/{id}` | Get a burn boss | Any |
| POST | `/contractors` | Register a contractor | AssociationAdmin |
| GET | `/contractors/{id}` | Get a contractor | Any |
| GET | `/contractors` | List contractors | Any |
| GET | `/contractors/{id}/assignments` | List assignments of a contractor | Any |
| POST | `/burn-plans` | Draft a burn plan | BurnBoss |
| GET | `/burn-plans/{id}` | Get a burn plan | Any |
| GET | `/burn-plans` | List burn plans | Any |
| POST | `/burn-plans/{id}/submit` | Submit a draft plan for review | BurnBoss |
| POST | `/burn-plans/{id}/request-revision` | Send a plan back for revision | AgencyReviewer |
| POST | `/burn-plans/{id}/revise` | Pull a revision-requested plan back to draft | BurnBoss |
| POST | `/burn-plans/{id}/approve` | Approve a submitted plan | AgencyReviewer |
| POST | `/burn-plans/{id}/cancel` | Cancel a non-terminal plan | BurnBoss |
| POST | `/burn-plans/{id}/permits` | Request a burn permit for a plan | BurnBoss |
| GET | `/permits/{id}` | Get a permit | Any |
| GET | `/permits` | List permits | Any |
| GET | `/burn-plans/{id}/permits` | List permits of a plan | Any |
| POST | `/permits/{id}/notifications` | Record a neighbor notification | BurnBoss |
| GET | `/permits/{id}/notifications` | List notifications of a permit | Any |
| POST | `/notifications/{id}/confirm` | Confirm a notification was delivered | BurnBoss |
| POST | `/permits/{id}/issue` | Issue a permit | AgencyReviewer |
| POST | `/permits/{id}/deny` | Deny a permit | AgencyReviewer |
| POST | `/permits/{id}/suspend` | Suspend an issued permit | AgencyReviewer |
| POST | `/permits/{id}/reinstate` | Reinstate a suspended permit | AgencyReviewer |
| POST | `/permits/{id}/revoke` | Revoke an issued or suspended permit | AgencyReviewer |
| POST | `/burn-plans/{id}/smoke-approvals` | Submit a smoke management approval request | BurnBoss |
| GET | `/smoke-approvals/{id}` | Get a smoke approval | Any |
| GET | `/burn-plans/{id}/smoke-approvals` | List smoke approvals of a plan | Any |
| POST | `/smoke-approvals/{id}/decide` | Decide a smoke approval request | AirQualityOfficer |
| POST | `/smoke-approvals/{id}/withdraw` | Withdraw an approved smoke approval | AirQualityOfficer |
| POST | `/smoke-approvals/{id}/clear-conditions` | Clear conditions on a conditional approval | AirQualityOfficer |
| POST | `/burn-plans/{id}/contingency-plans` | Draft a contingency plan | BurnBoss |
| GET | `/contingency-plans/{id}` | Get a contingency plan | Any |
| GET | `/burn-plans/{id}/contingency-plans` | List contingency plans of a plan | Any |
| POST | `/contingency-plans/{id}/accept` | Accept a contingency plan | AgencyReviewer |
| POST | `/contingency-plans/{id}/reject` | Reject a contingency plan | AgencyReviewer |
| POST | `/contingency-plans/{id}/revise` | Return a rejected contingency plan to draft | BurnBoss |
| POST | `/burn-plans/{id}/ignition-plans` | Upload an ignition sequencing plan | BurnBoss |
| GET | `/ignition-plans/{id}` | Get an ignition plan | Any |
| GET | `/burn-plans/{id}/ignition-plans` | List ignition plans of a plan | Any |
| POST | `/ignition-plans/{id}/accept` | Accept an ignition plan | AgencyReviewer |
| POST | `/ignition-plans/{id}/reject` | Reject an ignition plan | AgencyReviewer |
| POST | `/ignition-plans/{id}/revise` | Return a rejected ignition plan to draft | BurnBoss |
| POST | `/burn-plans/{id}/resource-orders` | Create a resource order | BurnBoss |
| GET | `/resource-orders/{id}` | Get a resource order | Any |
| GET | `/burn-plans/{id}/resource-orders` | List resource orders of a plan | Any |
| POST | `/resource-orders/{id}/submit` | Submit a draft resource order | BurnBoss |
| POST | `/resource-orders/{id}/assignments` | Assign contractor units to an order | BurnBoss |
| GET | `/resource-orders/{id}/assignments` | List assignments of an order | Any |
| POST | `/assignments/{id}/confirm` | Contractor confirms an assignment | Contractor |
| POST | `/assignments/{id}/decline` | Contractor declines an assignment | Contractor |
| POST | `/assignments/{id}/release` | Author releases a confirmed assignment | BurnBoss |
| POST | `/assignments/{id}/mark-no-show` | Author marks a confirmed assignment as no-show | BurnBoss |
| POST | `/burn-plans/{id}/executions` | Schedule a burn execution | BurnBoss |
| GET | `/executions/{id}` | Get an execution | Any |
| GET | `/burn-plans/{id}/executions` | List executions of a plan | Any |
| POST | `/executions/{id}/cancel` | Cancel a scheduled execution | BurnBoss |
| POST | `/executions/{id}/brief` | Run the pre-burn briefing gate | BurnBoss |
| POST | `/executions/{id}/weather-observations` | Record a weather observation | BurnBoss |
| GET | `/executions/{id}/weather-observations` | List observations of an execution | Any |
| POST | `/executions/{id}/go-no-go` | Evaluate the go/no-go checklist | BurnBoss |
| GET | `/executions/{id}/checklists` | List go/no-go checklists of an execution | Any |
| POST | `/executions/{id}/start-ignition` | Begin primary ignition | BurnBoss |
| POST | `/executions/{id}/complete-ignition` | Complete ignition, recording acres blackened | BurnBoss |
| POST | `/executions/{id}/begin-patrol` | Move from holding to patrol | BurnBoss |
| POST | `/executions/{id}/begin-mop-up` | Move from patrol to mop-up | BurnBoss |
| POST | `/executions/{id}/close` | Close the burn | BurnBoss |
| POST | `/executions/{id}/stand-down` | Voluntarily stand down a briefed execution | BurnBoss |
| POST | `/executions/{id}/declare-escape` | Declare an escape | BurnBoss |
| POST | `/executions/{id}/incidents` | Manually report an incident | IncidentCommander |
| GET | `/incidents/{id}` | Get an incident | Any |
| GET | `/executions/{id}/incidents` | List incidents of an execution | Any |
| POST | `/incidents/{id}/confirm` | Confirm a reported incident | IncidentCommander |
| POST | `/incidents/{id}/dismiss` | Dismiss a reported incident | IncidentCommander |
| POST | `/incidents/{id}/declare-wildfire` | Convert a confirmed incident to wildfire response | IncidentCommander |
| POST | `/incidents/{id}/mark-contained` | Mark a confirmed incident contained | IncidentCommander |
| POST | `/incidents/{id}/close` | Close a contained incident | IncidentCommander |
| POST | `/incidents/{id}/assess-costs` | Record suppression cost and escaped acres | IncidentCommander |
| GET | `/monitoring-reports/{id}` | Get a monitoring report | Any |
| GET | `/executions/{id}/monitoring-reports` | List monitoring reports of an execution | Any |
| POST | `/monitoring-reports/{id}/submit` | Submit observed treatment results | BurnBoss |
| POST | `/monitoring-reports/{id}/accept` | Accept a submitted report | AgencyReviewer |
| POST | `/monitoring-reports/{id}/mark-deficient` | Mark a submitted report deficient | AgencyReviewer |
| POST | `/cost-share-agreements` | Apply for cost-share | Landowner |
| GET | `/cost-share-agreements/{id}` | Get a cost-share agreement | Any |
| GET | `/cost-share-agreements` | List cost-share agreements | Any |
| POST | `/cost-share-agreements/{id}/begin-review` | Move an application to review | AssociationAdmin |
| POST | `/cost-share-agreements/{id}/approve` | Approve an application | AssociationAdmin |
| POST | `/cost-share-agreements/{id}/deny` | Deny an application | AssociationAdmin |
| POST | `/cost-share-agreements/{id}/disburse` | Disburse the currently-due installment | AssociationAdmin |
| POST | `/cost-share-agreements/{id}/reinstate` | Reinstate a suspended agreement | AssociationAdmin |
| POST | `/cost-share-agreements/{id}/cancel` | Cancel an agreement before final disbursement | AssociationAdmin |
| POST | `/incidents/{id}/liability-claims` | File a liability claim on an assessed incident | IncidentCommander |
| GET | `/liability-claims/{id}` | Get a liability claim | Any |
| GET | `/incidents/{id}/liability-claims` | List liability claims of an incident | Any |
| POST | `/liability-claims/{id}/begin-investigation` | Begin investigation | AssociationAdmin |
| POST | `/liability-claims/{id}/adjudicate` | Adjudicate with outcome and negligence finding | AssociationAdmin |
| POST | `/liability-claims/{id}/pay` | Pay a claim from the fund | AssociationAdmin |
| POST | `/liability-claims/{id}/reverse-payment` | Reverse a paid claim | AssociationAdmin |
| POST | `/liability-claims/{id}/close` | Close a paid or reversed claim | AssociationAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this catalogue enumerates only the identifier and its HTTP status.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES_VIOLATION` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_ASSOCIATION_NOT_FOUND` | 404 Not Found |
| `ERR_LANDOWNER_NOT_FOUND` | 404 Not Found |
| `ERR_PARCEL_NOT_FOUND` | 404 Not Found |
| `ERR_BOSS_NOT_FOUND` | 404 Not Found |
| `ERR_CONTRACTOR_NOT_FOUND` | 404 Not Found |
| `ERR_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_PERMIT_NOT_FOUND` | 404 Not Found |
| `ERR_NOTIFICATION_NOT_FOUND` | 404 Not Found |
| `ERR_SMOKE_APPROVAL_NOT_FOUND` | 404 Not Found |
| `ERR_CONTINGENCY_NOT_FOUND` | 404 Not Found |
| `ERR_IGNITION_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_EXECUTION_NOT_FOUND` | 404 Not Found |
| `ERR_INCIDENT_NOT_FOUND` | 404 Not Found |
| `ERR_REPORT_NOT_FOUND` | 404 Not Found |
| `ERR_AGREEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_ENUM` | 400 Bad Request |
| `ERR_INVALID_PRESCRIPTION_PARAMS` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_PLAN_NOT_DRAFT` | 409 Conflict |
| `ERR_PLAN_NOT_SUBMITTED` | 409 Conflict |
| `ERR_PLAN_NOT_IN_REVISION` | 409 Conflict |
| `ERR_PLAN_NOT_APPROVED` | 409 Conflict |
| `ERR_PLAN_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_PERMIT_NOT_UNDER_REVIEW` | 409 Conflict |
| `ERR_PERMIT_NOT_ISSUED` | 409 Conflict |
| `ERR_PERMIT_NOT_SUSPENDED` | 409 Conflict |
| `ERR_PERMIT_NOT_REVOKABLE` | 409 Conflict |
| `ERR_NOTIFICATION_NOT_REQUESTED` | 409 Conflict |
| `ERR_SMOKE_NOT_SUBMITTED` | 409 Conflict |
| `ERR_SMOKE_NOT_CONDITIONAL` | 409 Conflict |
| `ERR_SMOKE_NOT_WITHDRAWABLE` | 409 Conflict |
| `ERR_SMOKE_APPROVAL_NOT_VALID` | 409 Conflict |
| `ERR_CONTINGENCY_NOT_DRAFT` | 409 Conflict |
| `ERR_CONTINGENCY_NOT_REJECTED` | 409 Conflict |
| `ERR_CONTINGENCY_NOT_ACCEPTED` | 409 Conflict |
| `ERR_IGNITION_PLAN_NOT_DRAFT` | 409 Conflict |
| `ERR_IGNITION_PLAN_NOT_REJECTED` | 409 Conflict |
| `ERR_IGNITION_PLAN_NOT_ACCEPTED` | 409 Conflict |
| `ERR_ORDER_NOT_DRAFT` | 409 Conflict |
| `ERR_ORDER_NOT_OPEN` | 409 Conflict |
| `ERR_ASSIGNMENT_NOT_ASSIGNED` | 409 Conflict |
| `ERR_ASSIGNMENT_NOT_CONFIRMED` | 409 Conflict |
| `ERR_EXECUTION_NOT_SCHEDULED` | 409 Conflict |
| `ERR_EXECUTION_NOT_BRIEFED` | 409 Conflict |
| `ERR_EXECUTION_NOT_IN_TEST_FIRE` | 409 Conflict |
| `ERR_EXECUTION_NOT_IGNITING` | 409 Conflict |
| `ERR_EXECUTION_NOT_HOLDING` | 409 Conflict |
| `ERR_EXECUTION_NOT_PATROLLING` | 409 Conflict |
| `ERR_EXECUTION_NOT_MOPPING_UP` | 409 Conflict |
| `ERR_EXECUTION_NOT_ESCAPABLE` | 409 Conflict |
| `ERR_EXECUTION_ALREADY_OPEN` | 409 Conflict |
| `ERR_OPEN_INCIDENTS_EXIST` | 409 Conflict |
| `ERR_INCIDENT_NOT_REPORTED` | 409 Conflict |
| `ERR_INCIDENT_NOT_CONFIRMED` | 409 Conflict |
| `ERR_INCIDENT_NOT_CONTAINED` | 409 Conflict |
| `ERR_INCIDENT_NOT_COSTABLE` | 409 Conflict |
| `ERR_BILLING_NOT_UNASSESSED` | 409 Conflict |
| `ERR_BILLING_NOT_ASSESSED` | 409 Conflict |
| `ERR_REPORT_NOT_SUBMITTABLE` | 409 Conflict |
| `ERR_REPORT_NOT_SUBMITTED` | 409 Conflict |
| `ERR_AGREEMENT_NOT_SUBMITTED` | 409 Conflict |
| `ERR_AGREEMENT_NOT_UNDER_REVIEW` | 409 Conflict |
| `ERR_AGREEMENT_NOT_APPROVED` | 409 Conflict |
| `ERR_AGREEMENT_NOT_PARTIALLY_DISBURSED` | 409 Conflict |
| `ERR_AGREEMENT_NOT_SUSPENDED` | 409 Conflict |
| `ERR_AGREEMENT_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_CLAIM_NOT_FILED` | 409 Conflict |
| `ERR_CLAIM_NOT_UNDER_INVESTIGATION` | 409 Conflict |
| `ERR_CLAIM_NOT_ADJUDICATED` | 409 Conflict |
| `ERR_CLAIM_NOT_PAID` | 409 Conflict |
| `ERR_CLAIM_NOT_CLOSABLE` | 409 Conflict |
| `ERR_ACTIVE_PLAN_EXISTS_FOR_PARCEL` | 409 Conflict |
| `ERR_PERMIT_ALREADY_OPEN` | 409 Conflict |
| `ERR_CONTINGENCY_ALREADY_ACCEPTED` | 409 Conflict |
| `ERR_ACTIVE_AGREEMENT_EXISTS_FOR_PLAN` | 409 Conflict |
| `ERR_CONTRACTOR_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_CONTRACTOR_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_CONTRACTOR_SUSPENDED` | 403 Forbidden |
| `ERR_LANDOWNER_NOT_IN_GOOD_STANDING` | 403 Forbidden |
| `ERR_LANDOWNER_WAIVER_UNSIGNED` | 403 Forbidden |
| `ERR_BOSS_CERTIFICATION_INSUFFICIENT` | 403 Forbidden |
| `ERR_PARCEL_OWNERSHIP_MISMATCH` | 409 Conflict |
| `ERR_STALE_PLAN_VERSION` | 409 Conflict |
| `ERR_WRONG_BURN_DAY` | 422 Unprocessable Entity |
| `ERR_NOTIFICATION_LEAD_TIME_UNMET` | 422 Unprocessable Entity |
| `ERR_NOTIFICATIONS_INCOMPLETE` | 409 Conflict |
| `ERR_WEATHER_OBSERVATION_STALE` | 422 Unprocessable Entity |
| `ERR_WEATHER_OUT_OF_PRESCRIPTION` | 422 Unprocessable Entity |
| `ERR_INCOMPLETE_CHECKLIST` | 422 Unprocessable Entity |
| `ERR_HOLDING_FORCE_INADEQUATE` | 422 Unprocessable Entity |
| `ERR_AIRSHED_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_PLAN_WINDOW_LAPSED` | 422 Unprocessable Entity |
| `ERR_SCHEDULED_DATE_OUTSIDE_WINDOW` | 422 Unprocessable Entity |
| `ERR_PARCEL_EXECUTION_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_AGREEMENT_EXPIRED` | 422 Unprocessable Entity |
| `ERR_NO_CLOSED_EXECUTION` | 409 Conflict |
| `ERR_MONITORING_NOT_ACCEPTED` | 409 Conflict |
| `ERR_NO_DISBURSEMENT_DUE` | 402 Payment Required |
| `ERR_INSUFFICIENT_ASSOCIATION_FUNDS` | 402 Payment Required |
| `ERR_CLAIMS_NOT_RESOLVED` | 409 Conflict |
