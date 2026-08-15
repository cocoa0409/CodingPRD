# Vacant Property Preservation API — Product Requirements Document

## 1. Introduction

Mortgage servicers carry a legal and financial duty to preserve vacant and real-estate-owned properties from the moment a loan enters default servicing until the asset conveys to an investor. The work is executed by field services vendors whose crews inspect, secure, winterize, mow, shovel, board up, and repair thousands of scattered properties, while investors — FHA, FNMA, FHLMC, and private note holders — reimburse only against tightly capped allowable schedules, and municipalities impose vacant-property registration ordinances and code-violation fines that accrue daily. This document specifies the Vacant Property Preservation API, mounted under `/preservation`, through which one such vendor coordinates that entire operation: servicer work order intake, inspection-driven occupancy determination, dispatch to capacity-limited crews, photo-evidenced completion, municipal registration and code-violation cure, damage bidding, and investor-allowable-constrained invoicing.

Three design commitments run through the specification. First, every financial decision is reproducible: investor allowable schedules are pinned onto work orders at creation time, invoice math runs identically at submission and approval from that snapshot, and a servicer's monthly volume position is recomputed by a deterministic scheduled process rather than by wall-clock accident. Second, occupancy is a safety boundary — locking, winterizing, or clearing personal property from a home that turns out to be occupied is the industry's cardinal sin — and the API gates those operations on a verified occupancy determination, with a full cascade that suspends recurring work when a property proves occupied. Third, time itself is a controlled input: the system runs on a logical clock that operators can set explicitly, and a single daily operational sweep advances every time-driven obligation — recurring service generation, registration expiry, violation escalation, hold release, work order expiry, inspection misses, posture recomputation, year rollover, and monthly volume rebates — in one auditable step.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and invariants that apply to every endpoint in the API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes five distinct roles: `Servicer`, `VendorAdmin`, `Dispatcher`, `FieldCrew`, and `QualityReviewer`. A request missing either header, or carrying a role value outside these five, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. Access to each operation is further restricted by role, per the endpoint catalogue in §4; an attempt to perform an action outside the caller's designated role, or in violation of an entity-backed ownership rule, is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

The identity carried by `X-User-ID` depends on the role. When `X-User-Role` is `Servicer`, `X-User-ID` is the `id` of the acting `Servicer`; ownership checks on any resource that references a servicer compare the resource's servicer foreign key to `X-User-ID`. Concretely, a servicer may create a property only under its own `servicer_id`, and may act on bids and invoices only where the underlying property belongs to that same servicer. When `X-User-Role` is `FieldCrew`, `X-User-ID` is the `id` of the acting `Crew`; ownership checks compare crew-stamped fields — a work order's `assigned_crew_id`, a bid's `submitted_by_crew_id` — to `X-User-ID`, and the server stamps that id onto resources the crew creates, such as a damage report's `reported_by_crew_id` or a photo's `captured_by_crew_id`. When `X-User-Role` is `VendorAdmin`, `Dispatcher`, or `QualityReviewer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `authorized_by_user_id` on a personal property disposition or `flagged_by_user_id` on a photo evidence row — but it does not compare it to any entity's `id`.

The roles' operating charters are as follows. A `Servicer` is the mortgage servicer client: it issues and cancels work orders, conveys properties, reviews, approves, counters, and rejects bids, and approves, denies, pays, and voids invoices. A `VendorAdmin` is the vendor's operations administrator: it maintains master data (servicers, crews, allowable schedules), manages municipal registrations, code violations, and recurring plans, triages and closes damage reports, assembles and appeals invoices, drives the logical clock, and runs the daily sweep. A `Dispatcher` assigns and reassigns crews to work orders. A `FieldCrew` member starts and submits assigned work, records and verifies inspections, reports damage, bids on repairs, and uploads photo evidence. A `QualityReviewer` approves or rejects work order submissions, completes orders, and flags deficient photo evidence — under a segregation-of-duties rule that forbids a reviewer from clearing a flag they themselves set.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100; a supplied value outside those bounds is clamped to the nearest bound rather than rejected, and a non-integer value falls back to the default. The `offset` parameter specifies the number of items to skip and defaults to 0; a negative value is clamped to 0 and a non-integer value falls back to the default.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order, with any remaining ties broken by insertion order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource in this API — servicers, crews, investor allowables, properties, work orders, inspections, personal property dispositions, recurring service plans, code violations, municipal registrations, damage reports, bids, photo evidence rows, invoices, and expense lines — carries a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 timestamp in UTC with three fractional digits (for example, `2025-05-24T10:30:00.123Z`) recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp, likewise with three fractional digits, refreshed upon any change to the resource's properties.
- `version` (integer): a system-managed integer that begins at 1 when the resource is created and increments by one on every mutation, including mutations driven by cascades originating on another resource. This field underpins optimistic concurrency control where that mechanism applies (§2.8).

### 2.5. The Logical Clock and the Daily Operational Sweep

The system runs on a **logical clock**, not on wall-clock time. Before the clock has ever been set, it defaults to `2026-08-01T00:00:00Z`, and it never falls back to wall-clock time thereafter. A `VendorAdmin`-only test-driving capability sets the logical clock to a supplied `to_iso8601` instant and returns the resulting `current_utc` (rendered as an ISO 8601 UTC timestamp; an instant falling on a whole second is rendered without fractional digits); setting the clock does not itself run the daily sweep.

A second `VendorAdmin`-only capability advances the operational epoch at the current logical clock — the **daily sweep**. One invocation of the sweep performs, in a single auditable step: recurring service generation for active plans, expiry of registrations whose window has closed, escalation of code violations past their cure deadline, release of personal property holds whose period has elapsed, expiry of overdue issued or assigned work orders, marking of overdue scheduled inspections as missed, recomputation of property condition scores and compliance postures, the year-rollover reset of each property's year-to-date counters on the first sweep of a new calendar year, and — when the clock date is the first of a month — settlement of servicer volume rebates. The sweep's response enumerates what it did, as `generated_work_order_ids`, `expired_registration_ids`, `escalated_violation_ids`, `released_disposition_ids`, `expired_work_order_ids`, and `missed_inspection_ids`.

### 2.6. Monetary Precision and Rounding

All monetary values in this system are integer cents; no floating-point money ever appears in a request or a response. Wherever a calculation would produce a non-integer cent value — a percentage discount, a multiplied estimate, a rebate — the result is rounded half up to the nearest whole cent. Date arithmetic throughout the system is performed in whole days against the logical clock's date.

### 2.7. Request Validation Order and Nested Path Resolution

Every request passes through a fixed validation pipeline, and the order matters: a failure at an earlier stage masks every later stage, so the error a caller receives is always the earliest applicable one.

1. **Identity context.** The `X-User-ID` and `X-User-Role` headers must be present and the role must be one of the five declared roles, or the request fails with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400).
2. **Authorization and ownership.** The caller's role must be listed for the endpoint, and entity-backed ownership rules must hold — a `FieldCrew` caller acts as their own crew's `id`, a `Servicer` caller acts on their own properties' invoices and bids — or the request fails with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).
3. **Existence.** Every resource identifier referenced by the path or the body must exist, or the request fails with `ERR_NOT_FOUND` (HTTP 404).
4. **Body shape.** Required fields must be present, types must be valid, enum values must lie within their declared domains, a `quantity` must be at least 1, amounts must be at least 0, photo evidence must reference exactly one subject, and `personal_property_value_estimate_cents` must be present whenever `personal_property_present` is true — violations yield `ERR_INVALID_REQUEST` (HTTP 400).
5. **State preconditions.** The target resource must be in a state that permits the requested transition; failures surface as `ERR_INVALID_STATE` or one of the more specific state errors `ERR_PROPERTY_NOT_ACTIVE`, `ERR_POSTURE_BLOCKS_ORDER`, `ERR_DAMAGE_NOT_ACCEPTING_BIDS`, `ERR_FINANCIAL_REVIEW_REQUIRED`, or `ERR_OPEN_WORK_ORDERS` (HTTP 409).
6. **Occupancy and hold safety.** Securing-type work on an occupied property, plan resumption on an occupied property, and disposal authorization during the hold period fail with `ERR_PROPERTY_OCCUPIED` or `ERR_HOLD_PERIOD_ACTIVE`.
7. **Referential business requirements.** Missing municipal registration, missing allowable schedule row, duplicate citation number, and duplicate registration number fail with `ERR_REGISTRATION_REQUIRED`, `ERR_ALLOWABLE_NOT_FOUND`, `ERR_CITATION_NOT_UNIQUE`, or `ERR_REGISTRATION_NUMBER_NOT_UNIQUE`.
8. **Temporal windows.** Overlapping registration windows, expired cure deadlines, and closed season windows fail with `ERR_REGISTRATION_OVERLAP`, `ERR_CURE_DEADLINE_PASSED`, or `ERR_SEASON_WINDOW_CLOSED`.
9. **Constraint satisfaction.** Crew day capacity, photo completeness, open photo flags, segregation of duties on flag clearing, and crew or bid ownership fail with `ERR_CREW_DAY_CAPACITY`, `ERR_PHOTO_INCOMPLETE`, `ERR_PHOTO_FLAGGED_OPEN`, `ERR_SOD_FLAG_CLEAR`, `ERR_NOT_ASSIGNED_CREW`, or `ERR_NOT_BID_OWNER`.
10. **Fiscal gates.** Over-cap submission without an approved bid, disposal authority limits, and line-less invoices fail with `ERR_BID_REQUIRED_OVER_CAP`, `ERR_DISPOSAL_AUTHORITY_LIMIT`, or `ERR_INVOICE_NO_LINES`.

Because referential checks rank above temporal ones, a cure start against a property with no active municipal registration is rejected with `ERR_REGISTRATION_REQUIRED` even when the cure deadline has also passed — the deadline failure never masks the missing registration.

When an endpoint path contains nested resource identifiers — for example, a bid created beneath a damage report, or an expense line added beneath an invoice — the identifiers are validated in strict left-to-right order. The request is rejected with `ERR_NOT_FOUND` at the first identifier that does not resolve to an existing resource, before any later identifier or body check runs.

### 2.8. Optimistic Concurrency Control

Two write operations in this API are guarded by optimistic concurrency control, and only those two.

Reassigning a work order requires the request to carry `expected_work_order_version`, holding the work order `version` the dispatcher last observed. If the work order's current `version` no longer equals that value — because the order has been mutated since the dispatcher's last read — the reassignment is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the dispatcher from overwriting a crew and date placement they have not observed. A reassignment legitimately supersedes an earlier assignment while the order remains `ASSIGNED`, so the stale-view rejection is delivered through this version check rather than through any state restriction.

Creating a bid beneath a damage report requires the request to carry `expected_damage_report_version`, holding the damage report `version` the crew last observed. If the report's current `version` has advanced since that read — noting that every successfully created bid itself increments the report's `version` by one — the creation is rejected with `ERR_STALE_VERSION` (HTTP 412), ensuring each crew prices against a report it has actually read. Competitive bidding allows several bids to coexist on one report, so the version check is the serialization point.

Within the §2.7 pipeline, each version guard evaluates after body-shape validation and before state preconditions: a missing or malformed expected-version field is an `ERR_INVALID_REQUEST`, while a well-formed but stale one is `ERR_STALE_VERSION` even when the target's state would also forbid the write.

No other endpoint accepts a version field; clients must not send one elsewhere.

### 2.9. Occupancy Safety as a Portfolio-Wide Gate

Certain preservation activities presume a vacant property, and performing them on an occupied one is a safety and legal failure the system refuses to allow. Assigning or starting a work order whose `order_type` is `SECURING`, `WINTERIZATION`, `DEWINTERIZATION`, `PERSONAL_PROPERTY`, or `DEBRIS_REMOVAL` is rejected with `ERR_PROPERTY_OCCUPIED` whenever the property's `occupancy_status` is `OCCUPIED`. The same gate guards the resumption of a suspended recurring service plan: a plan may not resume while its property's `occupancy_status` is `OCCUPIED`. Occupancy itself is never set directly — it is derived from completed inspections, as specified in §3.4, so the gate always reflects the latest verified determination.

### 2.10. Property Condition Score and Compliance Posture

Every property carries a `condition_score` between 0 and 100 — it starts at 100 when the property is created — and a derived `compliance_posture` of `CLEAR`, `AT_RISK`, or `NON_COMPLIANT`. The posture is computed from the score, never directly mutated: a score of at least 80 yields `CLEAR`, a score from 50 through 79 inclusive yields `AT_RISK`, and a score below 50 yields `NON_COMPLIANT`. The score blends open code violations, lapsed municipal registration, open damage reports, and inspection staleness; the full deduction recipe, including the interior-access variant, is specified in §3.7 where those inputs live, and its recompute triggers are enumerated there as well.

The posture has teeth. A property whose `compliance_posture` is `NON_COMPLIANT` may not receive new `GRASS_CUT` or `SNOW_REMOVAL` work orders — creation of such an order is rejected with `ERR_POSTURE_BLOCKS_ORDER` — until the score recovers.

### 2.11. Investor Allowable Schedules and Snapshot Pinning

Reimbursement policy lives in the **investor allowable** schedule: one row per (`investor_type`, `item_code`, `effective_from`) combination, where `investor_type` is one of `FHA`, `FNMA`, `FHLMC`, or `PRIVATE`, and `item_code` is one of `INSPECTION`, `LOCK_CHANGE`, `WINTERIZATION`, `DEWINTERIZATION`, `GRASS_CUT`, `SNOW_REMOVAL`, `DEBRIS_REMOVAL`, `CODE_CURE`, `BOARD_UP`, `PERSONAL_PROPERTY`, or `DAMAGE_REPAIR`. Each row carries `max_per_occurrence_cents` (the per-unit reimbursement ceiling), `max_occurrences_per_calendar_year` (the reimbursable unit count per property per calendar year), `aggregate_cap_cents_per_property_year` (the reimbursable cents per property per calendar year), `requires_bid_over_cents` (the submitted-cost level strictly above which an approved bid must back the claim), and `effective_from` (the ISO date the row takes effect). The (`investor_type`, `item_code`, `effective_from`) triple is unique. Within each (`investor_type`, `item_code`) family, the row with the latest `effective_from` as of the logical clock is marked `is_current`; that flag is recomputed whenever a new row is created in the family.

When a work order is created, the system selects the schedule row whose `investor_type` equals the property's `investor_type`, whose `item_code` equals the work order's mapped `item_code`, and whose `effective_from` is on or before the current clock date; among matching rows the one with the latest `effective_from` wins, with ties broken by the row's `created_at` in descending order and any remaining ties by creation sequence, most recently created first. When no row matches, work order creation fails with `ERR_ALLOWABLE_NOT_FOUND`. The selected row is then **pinned** onto the work order as `investor_allowable_id` and `investor_allowable_version`, and its two fiscal parameters are snapshotted as `allowable_cap_cents` and the order's own `requires_bid_over_cents`. Thereafter the schedule row may be updated — such an update increments the row's `version` — but existing work orders keep their pinned snapshot, and all downstream invoice math for those orders reads the snapshot, never the live row.

### 2.12. Cross-Resource Cascades and Consistent Reconciliation

State changes in this system rarely stay on one resource. An occupancy verification can suspend recurring plans and cancel their generated orders; a property conveyance ends every recurring plan; a bid approval spawns a repair work order, moves the damage report, and rejects competing bids; a work order completion creates an invoice; an invoice approval, void, or appeal moves the property's year-to-date totals and may raise or clear a financial review flag. Each such cascade is specified where its workflow lives in §3. Two invariants hold everywhere: whenever a cascade mutates a resource, that resource's `updated_at` refreshes and its `version` increments by one; and cascades that compensate a counter — such as a recurring plan's `generated_this_season` or a property's `ytd_investor_approved_cents` — always move the counter by exactly the amount the original operation added, so that an operation and its reversal leave the counter unchanged.

## 3. Business Logic & Workflows

### 3.1. Portfolio Onboarding: Servicers, Crews, Allowables, and Properties

A `VendorAdmin` onboards a servicer organization with a `name` and a `code`; the code must be unique across all servicers — a duplicate is rejected with `ERR_INVALID_REQUEST`. New servicers are created with `active` set to true — the flag records whether the servicer may issue new work orders — and with both rebate counters, `prior_month_gross_cents` and `volume_rebate_cents`, at zero until the first monthly settlement (§3.9).

Field capacity is onboarded the same way. A `VendorAdmin` creates a crew with a `name` and a `crew_code` unique across all crews (a duplicate is rejected with `ERR_INVALID_REQUEST`), optionally listing the `region_state_codes` the crew operates in and a `daily_capacity_jobs` ceiling that defaults to 8 when omitted and must be a non-negative integer when supplied. That ceiling is the maximum number of the crew's work orders in `ASSIGNED` or `IN_PROGRESS` status that may share one `scheduled_date`; dispatch enforces it at assignment time (§3.2).

The reimbursement policy is onboarded as investor allowable rows by a `VendorAdmin`, as specified in §2.11. A servicer-facing nuance matters here: because every work order pins its schedule row at creation, mid-month schedule updates never disturb work already issued.

Properties enter the portfolio through either a `VendorAdmin` or the owning `Servicer`; a servicer caller must pass its own `servicer_id` or the creation is rejected with `ERR_FORBIDDEN_FOR_ROLE`. Creation takes the property's `servicer_id` — required of every caller and required to reference an existing servicer (`ERR_NOT_FOUND`) — `address_line1`, `municipality_code` (the municipality identifier used for registration and violations), `state_code` (which drives personal-property hold days, §3.5), `zip`, `investor_type` (one of `FHA`, `FNMA`, `FHLMC`, `PRIVATE`, selecting the allowable schedule), `lot_size_sqft`, `heating_system` (one of `NONE`, `FORCED_AIR`, `HOT_WATER`, `STEAM`), and `fixture_count`; `has_pool` is optional and defaults to false. A new property starts with `status` `ACTIVE`, `occupancy_status` `UNKNOWN`, a `condition_score` of 100, `compliance_posture` `CLEAR`, `ytd_investor_approved_cents` at zero, `ytd_calendar_year` set to the clock's current year, and `financial_review_required` false. The property list endpoint accepts optional `servicer_id`, `status`, and `compliance_posture` filters alongside the standard `limit` and `offset` parameters.

Conveyance is the property's terminal act, performed by the owning `Servicer`: transitioning `ACTIVE → CONVEYED` requires the property to be `ACTIVE` (otherwise `ERR_INVALID_STATE`) and is refused with `ERR_OPEN_WORK_ORDERS` while any of its work orders stands in `ISSUED`, `ASSIGNED`, `IN_PROGRESS`, or `SUBMITTED`. Conveyance ends every recurring plan of the property in `ACTIVE` or `SUSPENDED` status, moving each to `ENDED`; that plan-ending is silent — the cancellation compensation that normally restores `generated_this_season` does not fire — and the property's `version` increments. Once `CONVEYED`, the property rejects further work order creation with `ERR_PROPERTY_NOT_ACTIVE`, and assignment or start of its work orders fails the same way.

### 3.2. Work Order Intake, Allowable Pinning, and Dispatch

A `Servicer` issues a work order with a `property_id` naming one of its own properties — the caller's `X-User-ID` must equal the property's `servicer_id`, or creation is rejected with `ERR_FORBIDDEN_FOR_ROLE` — an `order_type`, and a `due_date` — the ISO date the work must be submitted by — optionally linking a `code_violation_id` for `CODE_CURE` orders or a `damage_report_id` for the originating damage report. The `order_type` vocabulary is `INSPECTION`, `SECURING`, `WINTERIZATION`, `DEWINTERIZATION`, `GRASS_CUT`, `SNOW_REMOVAL`, `DEBRIS_REMOVAL`, `CODE_CURE`, `BOARD_UP`, `PERSONAL_PROPERTY`, and `DAMAGE_REPAIR`. Creation copies the property's `servicer_id` onto the order and maps the order type to the allowable `item_code`: `SECURING` maps to `LOCK_CHANGE`, `PERSONAL_PROPERTY` and `DAMAGE_REPAIR` map to their same-named items, and every other order type maps to the item of the same name. The order's `source` is `DIRECT` for these servicer-issued orders; `BID_CONVERTED` and `RECURRING_AUTO` orders arise only from the bid and recurring-plan workflows (§3.6, §3.8). New orders start in `ISSUED` status.

Creation is gated twice before the schedule is even consulted: the property must be `ACTIVE` (`ERR_PROPERTY_NOT_ACTIVE`), and a `GRASS_CUT` or `SNOW_REMOVAL` order is refused with `ERR_POSTURE_BLOCKS_ORDER` while the property's `compliance_posture` is `NON_COMPLIANT`. The allowable schedule row is then selected and pinned exactly as §2.11 specifies — `investor_allowable_id`, `investor_allowable_version`, `allowable_cap_cents`, and `requires_bid_over_cents` — with `ERR_ALLOWABLE_NOT_FOUND` when no effective row exists.

For `WINTERIZATION` and `DEWINTERIZATION` orders, creation also computes `estimated_cost_cents` through the **winterization quote**; every other order type starts with an `estimated_cost_cents` of zero. The quote begins with a base of 15,000 cents plus 1,200 cents for each plumbing fixture recorded in the property's `fixture_count`, adding a further 9,000 cents when the property's `has_pool` flag is true. The base is scaled by a heating-system multiplier: 1.00 for `NONE`, 1.00 for `FORCED_AIR`, 1.5 for `HOT_WATER`, and 1.75 for `STEAM`. A seasonal multiplier of 1.2 applies whenever the logical clock's month falls in October through March inclusive; in all other months it is 1.0. For `DEWINTERIZATION` orders the seasonal multiplier is always 1.0 and the base is halved — rounded down to a whole cent — before the multipliers are applied. The estimate is the base times the heating multiplier times the seasonal multiplier, rounded half up to whole cents, and is stored on the order as `estimated_cost_cents`. Fixture count, pool flag, heating system, and season interact non-linearly, so the quote must be computed from the property's live fields at creation, never transcribed from elsewhere.

Dispatch belongs to the `Dispatcher`. Assigning an order — moving `ISSUED → ASSIGNED` — takes a `crew_id` and a `scheduled_date`, and is refused with `ERR_PROPERTY_NOT_ACTIVE` when the property is no longer active, with `ERR_PROPERTY_OCCUPIED` under the §2.9 occupancy gate, and with `ERR_CREW_DAY_CAPACITY` when the target crew already has a count of work orders in `ASSIGNED` or `IN_PROGRESS` on that calendar date equal to or greater than its `daily_capacity_jobs`; the calendar date is the whole bucket — there is no per-slot geometry. A successful assignment stamps `assigned_crew_id` and `scheduled_date` and increments the order's `version`.

Reassignment is the dispatch correction path: `ASSIGNED → ASSIGNED` with a new `crew_id` and `scheduled_date`. It repeats the capacity check against the new date — the order being reassigned is excluded from the count — and it is the first of the two OCC-guarded writes in §2.8 — the request must carry `expected_work_order_version`, and a stale view is rejected with `ERR_STALE_VERSION` (HTTP 412).

A `Servicer` may cancel an order in `ISSUED`, `ASSIGNED`, or `IN_PROGRESS`, optionally supplying a `reason`. Cancellation is also how time kills neglected work: the daily sweep moves any `ISSUED` or `ASSIGNED` order whose `due_date` has passed to `EXPIRED`. Both endings honor a compensating invariant — when the cancelled or expired order's `source` is `RECURRING_AUTO` and it carries a `recurring_plan_id`, the plan's `generated_this_season` is decremented by one, restoring the season allowance the generation consumed.

The work order list endpoint filters by `property_id`, `assigned_crew_id`, `servicer_id`, `bid_id`, `investor_allowable_id`, `recurring_plan_id`, `code_violation_id`, `damage_report_id`, and `status`, plus pagination.

### 3.3. Field Execution, Photo Evidence, and Quality Review

Work on site begins when the assigned `FieldCrew` starts the order — `ASSIGNED → IN_PROGRESS`. The starter's `X-User-ID` must equal the order's `assigned_crew_id` (`ERR_NOT_ASSIGNED_CREW`), the property must still be `ACTIVE` (`ERR_PROPERTY_NOT_ACTIVE`), and the §2.9 occupancy gate applies to the five securing-type order types (`ERR_PROPERTY_OCCUPIED`).

Submission — `IN_PROGRESS → SUBMITTED` — is the crew's declaration of finished work and carries `submitted_cost_cents`, the crew-declared cost, which must be at least zero (`ERR_INVALID_REQUEST`). As with starting, the submitter must be the order's assigned crew: the caller's `X-User-ID` must equal `assigned_crew_id` (`ERR_NOT_ASSIGNED_CREW`). Three further gates apply, in pipeline order. Photographic completeness: the order type's minimum unflagged-photo counts must be met, or `ERR_PHOTO_INCOMPLETE`. Flag hygiene: no photo evidence linked to the order may remain flagged and uncleared, or `ERR_PHOTO_FLAGGED_OPEN`. The bid threshold: when `submitted_cost_cents` is strictly greater than the order's pinned `requires_bid_over_cents`, an `APPROVED` bid must be linked via the order's `bid_id`, or the submission is rejected with `ERR_BID_REQUIRED_OVER_CAP`; a submitted cost exactly equal to the threshold needs no bid.

The photographic minimums per order type, each count referring to unflagged photos in the named `category`, are: `SECURING` requires two `BEFORE`, one `DURING`, two `AFTER`, and one `SERIAL_NUMBER`; `WINTERIZATION` requires one `BEFORE`, two `DURING`, and one `AFTER`; `DEWINTERIZATION`, `GRASS_CUT`, and `SNOW_REMOVAL` each require one `BEFORE` and one `AFTER`; `DEBRIS_REMOVAL` requires two `BEFORE` and two `AFTER`; `PERSONAL_PROPERTY` requires one `BEFORE` and two `DOCUMENT`; `CODE_CURE` requires one `BEFORE`, one `DURING`, and two `AFTER`; `BOARD_UP` requires one `BEFORE` and two `AFTER`; `DAMAGE_REPAIR` requires one `BEFORE`, one `DURING`, and one `AFTER`; and `INSPECTION` requires one `STREET_SCENE`. Meeting a minimum exactly passes. While those counts are all met by unflagged photos, the order's computed `evidence_complete` reads true; it is recomputed on every photo upload, flag, and flag clearing. Such recomputation refreshes the field in place: it does not increment the order's `version` or refresh its `updated_at`.

Photo evidence is uploaded by a `FieldCrew` member with a `category` — one of `BEFORE`, `DURING`, `AFTER`, `SERIAL_NUMBER`, `DAMAGE_CLOSEUP`, `STREET_SCENE`, or `DOCUMENT` — a `taken_at` timestamp, and a `content_hash` (the SHA-256 of the photo bytes, recorded as supplied; no duplicate detection is performed on it). Each photo belongs to exactly one subject: precisely one of `work_order_id`, `inspection_id`, `bid_id`, or `damage_report_id` must be supplied; zero or several subjects is an `ERR_INVALID_REQUEST`. The uploader's crew identity is stamped as `captured_by_crew_id`. A `QualityReviewer` may flag a photo as deficient, supplying a `reason`; flagging sets `flagged` true, records the reviewer's identity in `flagged_by_user_id` and the deficiency in `flag_reason`, and recomputes the subject order's `evidence_complete`; flagging an already-flagged photo fails with `ERR_INVALID_STATE`. Clearing a flag is likewise a `QualityReviewer` action, but segregation of duties forbids self-clearance: the clearing reviewer's `X-User-ID` must differ from the `flagged_by_user_id` on the photo, or the clear is rejected with `ERR_SOD_FLAG_CLEAR`. Clearing sets `flagged` false while leaving `flagged_by_user_id` and `flag_reason` as recorded; clearing a photo that is not flagged fails with `ERR_INVALID_STATE`. The photo list endpoint filters by `work_order_id`, `inspection_id`, `bid_id`, `damage_report_id`, and `captured_by_crew_id`.

Quality review of a submission belongs to the `QualityReviewer`. Approval — `SUBMITTED → APPROVED` — is blocked while any linked photo remains flagged and uncleared (`ERR_PHOTO_FLAGGED_OPEN`), and on success sets `approved_cost_cents`: the declared `submitted_cost_cents`, unless the order's `bid_id` links an `APPROVED` bid whose `amount_cents` is lower, in which case the approved cost is the bid amount — the lesser of the two figures. Rejection returns the order to the crew — `SUBMITTED → IN_PROGRESS` — with a mandatory `reason`; the order's `rework_count` increments by one and its `submitted_cost_cents` resets to null, so the rework loop from `IN_PROGRESS` through `SUBMITTED` and back is cyclic and may repeat.

Completion — `APPROVED → COMPLETED`, also by a `QualityReviewer` — closes the field lifecycle and opens the financial one: the system auto-creates an invoice in `DRAFT` status carrying the order's `work_order_id`, its `property_id`, and its `investor_type` (§3.9). Two order kinds carry follow-on notes. Completing a `CODE_CURE` order leaves the linked code violation in `CURE_IN_PROGRESS`; the cure is submitted to the municipality separately (§3.7). Completing a `BID_CONVERTED` order does not close the originating damage report; that report is closed through its own endpoint once the repair is verified (§3.8).

### 3.4. The Inspection Cycle and Occupancy Determination

Inspections drive occupancy, and occupancy drives everything else. A `VendorAdmin` or `Servicer` schedules an inspection with a `property_id` and a `due_date`, optionally linking the originating `work_order_id` of an `INSPECTION` order. The system assigns `cycle_index` — a per-property counter starting at 1, set to the count of the property's prior inspections plus one — and the inspection starts `SCHEDULED`. The inspection list filters by `property_id`, `work_order_id`, and `status`.

Recording findings is a `FieldCrew` action and supplies `occupancy_determination` (`VACANT`, `OCCUPIED`, or `INDETERMINATE`), `interior_access` (whether the inspector gained interior access), `personal_property_present`, and optional `condition_notes`. When `personal_property_present` is true, `personal_property_value_estimate_cents` is required (`ERR_INVALID_REQUEST`). The determination decides the transition. Recording `VACANT` completes the inspection — `SCHEDULED → COMPLETED`: the property's `occupancy_status` becomes `VACANT`, its `condition_score` is recomputed (under the interior-inclusive variant when `interior_access` is true, otherwise exterior-only) with `compliance_posture` re-derived, and the inspection's `recorded_at` is stamped from the logical clock. Recording `OCCUPIED` or `INDETERMINATE` instead moves the inspection to `VERIFICATION_PENDING` with `recorded_at` likewise stamped — every recording stamps `recorded_at` from the logical clock, whatever the determination; when the determination was `OCCUPIED`, the property's `occupancy_status` becomes `OCCUPIED_PENDING_VERIFICATION`.

Verification — again by a `FieldCrew` member — supplies `verified_occupancy` (`VACANT` or `OCCUPIED`) and completes the inspection. A verified `OCCUPIED` result fires the system's deepest cascade: first the property's `occupancy_status` becomes `OCCUPIED`; then every recurring plan of the property in `ACTIVE` status moves to `SUSPENDED`; then every work order generated by those plans — `source` `RECURRING_AUTO`, still in `ISSUED` or `ASSIGNED` — is `CANCELLED`, each cancellation decrementing its plan's `generated_this_season` by one as compensation; and the property's `version` increments. A verified `VACANT` result instead sets `occupancy_status` to `VACANT` and recomputes the condition score. Either way the property's `version` increments.

Inspections nobody performs do not linger: the daily sweep moves a `SCHEDULED` inspection whose `due_date` has passed to `MISSED`, a terminal state alongside `COMPLETED`.

### 3.5. Personal Property Documentation, Hold, and Disposal

When a crew or administrator documents personal property found on site, a `FieldCrew` or `VendorAdmin` creates a disposition record with the `property_id`, a `description` of the items, and a `valuation_cents`, optionally tying it to the `work_order_id` or `inspection_id` during which the items were found. Creation stamps `documented_date` from the logical clock's date and computes `hold_until_date` by adding the statutory hold to that date: 30 days when the property's `state_code` is OH, 28 days for MI, and 30 days for every other state. The record starts `IN_HOLD`.

The daily sweep releases what time has matured: a disposition in `IN_HOLD` whose `hold_until_date` is on or before the clock date moves to `RELEASE_ELIGIBLE` — the boundary is inclusive, so the hold day itself releases. Authorizing disposal — `RELEASE_ELIGIBLE → DISPOSAL_AUTHORIZED` — may be performed by a `VendorAdmin` or a `Servicer`. An attempt while the record is still `IN_HOLD` is rejected with `ERR_HOLD_PERIOD_ACTIVE`, and valuation carries an authority limit: when `valuation_cents` is at least 50,000 cents, the authorizer must be a `Servicer` — a `VendorAdmin` attempt is rejected with `ERR_DISPOSAL_AUTHORITY_LIMIT`. Authorization records the acting identity in `authorized_by_user_id`.

Final disposition is a `VendorAdmin` act taking an `outcome` of `DISPOSED`, `DONATED`, or `RETURNED`, each terminal; all three close the record from `DISPOSAL_AUTHORIZED`. The disposition list filters by `property_id`, `work_order_id`, `inspection_id`, and `status`.

### 3.6. Recurring Exterior Service Plans

Grass cuts and snow removal run on recurrence, not on individual orders. A `VendorAdmin` creates a plan with the `property_id`, a `service_type` of `GRASS_CUT` or `SNOW_REMOVAL`, a `season_start_md` and `season_end_md` as zero-padded `MM-DD` month-day strings (the end must be after the start), an `interval_days` minimum spacing between generated orders, and a `max_per_season` cap — `interval_days` and `max_per_season` must each be an integer of at least 1. The plan starts `ACTIVE` with `generated_this_season` at zero and `last_generated_date` null until the first generation.

Generation is the daily sweep's job, evaluated per `ACTIVE` plan. The season window runs from the current clock year's `season_start_md` through its `season_end_md`, inclusive of both ends; seasons do not span the year boundary. The sweep generates a work order — `source` `RECURRING_AUTO`, with `due_date` set to the clock date plus `interval_days`, and with the allowable schedule row selected and pinned per §2.11 whenever an effective row exists (when none exists the order is still generated, its `investor_allowable_id`, `investor_allowable_version`, `allowable_cap_cents`, and `requires_bid_over_cents` left null) — only when all four conditions hold: the clock date lies within the season window; `last_generated_date` is null or at least `interval_days` have elapsed since it (exactly `interval_days` elapsed is enough); `generated_this_season` is below `max_per_season` (reaching the cap exactly stops generation); and the property is `ACTIVE` with an `occupancy_status` other than `OCCUPIED`. Each generation increments `generated_this_season` and stamps `last_generated_date` with the clock date. Generated orders flow through the normal dispatch and field lifecycle; when one is cancelled or expires while still open, the plan's `generated_this_season` is decremented as compensation (§3.2).

Suspension — `ACTIVE → SUSPENDED` — is available to a `VendorAdmin`, and also fires automatically from the occupancy cascade of §3.4. Suspending a plan cancels each of its open generated orders — those in `ISSUED` or `ASSIGNED` — with the same per-order `generated_this_season` compensation. Resumption — `SUSPENDED → ACTIVE`, a `VendorAdmin` action — is gated on reality: the property's `occupancy_status` must not be `OCCUPIED` (`ERR_PROPERTY_OCCUPIED`), and the clock date must lie within the plan's current-year season window, or the resume is rejected with `ERR_SEASON_WINDOW_CLOSED`. Ending a plan — from `ACTIVE` or `SUSPENDED` to the terminal `ENDED` — is a `VendorAdmin` action and also the conveyance cascade of §3.1; plan ending is silent, with no cancellation compensation. The plan list filters by `property_id` and `status`.

### 3.7. Municipal Registration and Code Violation Cure

Most municipalities require vacant properties to be registered, and many fine owners daily when code violations go uncured. A `VendorAdmin` creates a municipal registration with the `property_id`, the `municipality_code` it covers, a `registration_number` (unique within its municipality — duplicates are rejected with `ERR_REGISTRATION_NUMBER_NOT_UNIQUE`), a `fee_cents`, and a validity window from `valid_from` to `valid_to`. The window is half-open: the registration covers its municipality from `valid_from` inclusive up to but not including `valid_to`. New registrations start `PENDING`.

Activation — `PENDING → ACTIVE`, by a `VendorAdmin` — runs the overlap check against the property's other registrations in the same municipality that are already `ACTIVE`: the windows overlap when this registration's `valid_from` falls before the other's `valid_to` while this registration's `valid_to` falls after the other's `valid_from`, and an overlap is rejected with `ERR_REGISTRATION_OVERLAP`. Pure adjacency — one window's start equalling the other's end — is not an overlap and activates cleanly. Renewal takes a `new_valid_to` and behaves differently by state. Renewing an `ACTIVE` registration requires `new_valid_to` to be after the current `valid_to` (`ERR_INVALID_REQUEST`); it extends `valid_to` and increments `renewal_count`. Renewing an `EXPIRED` registration requires `new_valid_to` to be after the clock date; it rebases `valid_from` to the clock date, sets `valid_to` to the new end, increments `renewal_count`, returns the registration to `ACTIVE`, and recomputes the property's condition score and posture. The daily sweep expires a registration — `ACTIVE → EXPIRED` — once the clock date reaches `valid_to`, recomputing the score with the registration-lapsed deduction. Release — to the terminal `RELEASED`, by a `VendorAdmin` — is available from `ACTIVE` (recomputing the score) or from `EXPIRED` (without further effects). The registration list filters by `property_id`, `municipality_code`, and `status`.

Code violations are recorded by a `VendorAdmin` with the `property_id`, a `citation_number` (unique within the property's municipality — duplicates are rejected with `ERR_CITATION_NOT_UNIQUE`), a `violation_class` of `MINOR`, `MAJOR`, or `HAZARDOUS`, a `daily_fine_cents`, a `fine_cap_cents`, and a `cure_deadline`. The violation starts `OPEN`, and its creation recomputes the property's condition score.

Fines accrue only after the cure deadline. The number of overdue days is the count of days from `cure_deadline` to the clock date, floored at zero — the deadline date itself accrues nothing, and the first day after it accrues exactly one day's `daily_fine_cents`. The accrued figure, exposed as `accrued_fine_cents`, is the overdue days times the daily fine, capped at `fine_cap_cents`; it is recomputed by the daily sweep and whenever the violation is read, for violations in `OPEN`, `CURE_IN_PROGRESS`, `CURE_SUBMITTED`, or `ESCALATED`.

Curing a violation is a three-step choreography. A `VendorAdmin` starts the cure by supplying a `work_order_id` that references a `CODE_CURE` work order in `ISSUED`, `ASSIGNED`, or `IN_PROGRESS` (anything else is an `ERR_INVALID_REQUEST`); the violation moves `OPEN → CURE_IN_PROGRESS` and records the link in `cure_work_order_id`. Two gates guard the start, in pipeline order: the referential gate requires an `ACTIVE` municipal registration covering the property's `municipality_code` (`ERR_REGISTRATION_REQUIRED`), and the temporal gate requires the clock date to be on or before `cure_deadline` (`ERR_CURE_DEADLINE_PASSED`) — the registration check ranks first, so a missing registration surfaces even when the deadline has also passed. Once the linked order stands `COMPLETED`, a `FieldCrew` member submits the cure to the municipality — `CURE_IN_PROGRESS → CURE_SUBMITTED` — with `ERR_CURE_WORK_INCOMPLETE` while the order is anything short of `COMPLETED`. Municipal verification, performed by a `VendorAdmin`, closes the violation — `CURE_SUBMITTED → VERIFIED_CLOSED`, with `VERIFIED_CLOSED` as the violation's only terminal state — freezing `accrued_fine_cents` at its current value and recomputing the property's condition score and posture. A rejected cure — `CURE_SUBMITTED → CURE_IN_PROGRESS`, by a `VendorAdmin` with a mandatory `reason` — forms a cyclic rework loop with no limit.

Violations that outlive their deadline escalate: the daily sweep moves an `OPEN` violation whose `cure_deadline` has passed to `ESCALATED`, recomputing its accrued fine and the property's condition score and posture; a `CURE_IN_PROGRESS` violation past deadline likewise moves to `ESCALATED`, with its accrued fine recomputed. The violation list filters by `property_id`, `cure_work_order_id`, and `status`.

The **property condition score** blends all of the above, and is recomputed on an inspection recording that completes the inspection with a `VACANT` determination and on a verification with a `VACANT` result, on violation creation, municipal verification, and escalation from `OPEN` (an escalation from `CURE_IN_PROGRESS` recomputes only the accrued fine), on registration activation, expiry, renewal from `EXPIRED`, and release from `ACTIVE`, on damage report creation and closure with outcome `CLOSED`, and on each daily sweep. The score starts at 100. From it are deducted: for each of the property's code violations in `OPEN`, `CURE_IN_PROGRESS`, `CURE_SUBMITTED`, or `ESCALATED`, 15 points for a `MINOR` violation, 25 for a `MAJOR`, and 40 for a `HAZARDOUS`, with the total violation deduction capped at 45 points; 20 points when no `ACTIVE` municipal registration covers the property's `municipality_code` at the clock date; 10 points for each of the property's damage reports in `REPORTED`, `TRIAGED`, `BID_REQUESTED`, or `REPAIR_IN_PROGRESS` whose `is_interior` is false, capped at 20 points; and 10 points when more than 30 whole days separate the clock date from the `recorded_at` date of the property's most recently recorded `COMPLETED` inspection — or, when no completed inspection exists, from the property's own creation date. The variant is chosen by interior access: when the latest `COMPLETED` inspection has `interior_access` true (the interior-inclusive variant), a further 15 points are deducted per open interior damage report — one with `is_interior` true in those same open statuses — capped at 30 points; under the exterior-only variant — the latest completed inspection lacked interior access, or no completed inspection exists — interior damage is ignored entirely, so the same property data scores higher. The score never falls below 0, and §2.10's bands derive the `compliance_posture`.

### 3.8. Damage Reporting, Competitive Bidding, and Repair Conversion

Damage and vandalism enter the system from the field: a `FieldCrew` member reports damage with the `property_id`, a `damage_type` of `VANDALISM`, `THEFT`, `WATER`, `FIRE`, `STORM`, `SQUATTER`, or `OTHER`, a `severity` of `MINOR`, `MODERATE`, or `SEVERE`, an `is_interior` flag that feeds the interior-inclusive scoring variant, a free-text `description`, and optionally the `work_order_id` during which the damage was found. The reporter's crew identity is stamped as `reported_by_crew_id`, the report starts `REPORTED`, and its creation recomputes the property's condition score. The report list filters by `property_id`, `reported_by_crew_id`, `work_order_id`, and `status`.

A `VendorAdmin` triages a fresh report — `REPORTED → TRIAGED` — and then opens it for bids — `TRIAGED → BID_REQUESTED`. Only a report in `BID_REQUESTED` accepts bids at any point in the bidding workflow; attempts to create, submit, or approve a bid against a report in any other status are rejected with `ERR_DAMAGE_NOT_ACCEPTING_BIDS`.

Bidding is competitive and crew-owned. A `FieldCrew` member creates a bid draft beneath a `BID_REQUESTED` report with an `amount_cents`; this is the second OCC-guarded write of §2.8, so the request must also carry `expected_damage_report_version`, and a stale view of the report is rejected with `ERR_STALE_VERSION` (HTTP 412). Creation stamps `submitted_by_crew_id` from the caller's identity, copies the report's `property_id` onto the bid, increments the report's `version` by one, and starts the bid in `DRAFT` with `round_number` 1 and `counter_amount_cents` unset. Submitting a draft — `DRAFT → SUBMITTED` — is restricted to the owning crew: the caller's `X-User-ID` must equal the bid's `submitted_by_crew_id` (`ERR_NOT_BID_OWNER`), and the report must still be `BID_REQUESTED`. The servicer side negotiates: countering — `SUBMITTED → COUNTERED`, by a `Servicer` — records a `counter_amount_cents` with an optional `note`; rejecting — by a `Servicer` with a mandatory `reason` — moves the bid to the terminal `REJECTED` state and is available from `SUBMITTED` or `COUNTERED`. The crew answers a counter by revising — `COUNTERED → SUBMITTED` — with a fresh `amount_cents`; ownership is checked again (`ERR_NOT_BID_OWNER`), and the `round_number` increments with each revision, so the negotiation loop from `SUBMITTED` to `COUNTERED` and back is cyclic. The owning crew may instead withdraw — from `DRAFT` or `SUBMITTED` to the terminal `WITHDRAWN` — with the same ownership check.

Bid approval is the servicer's decision and the system's busiest cascade. The approving `Servicer`'s `X-User-ID` must equal the `servicer_id` of the property that owns the report (`ERR_FORBIDDEN_FOR_ROLE`), and the report must be `BID_REQUESTED`. On approval — `SUBMITTED → APPROVED`, terminal — the system spawns a repair work order: `order_type` `DAMAGE_REPAIR`, `source` `BID_CONVERTED`, its `bid_id` set to this bid, `due_date` fourteen days out from the clock date, its allowable schedule pinned from the current `DAMAGE_REPAIR` row per §2.11 but with `allowable_cap_cents` equal to the bid's `amount_cents` — the negotiated cap; when no current `DAMAGE_REPAIR` row exists the approval still succeeds, leaving the spawned order's `investor_allowable_id`, `investor_allowable_version`, and `requires_bid_over_cents` null while `allowable_cap_cents` remains the bid amount. The bid's `approved_work_order_id` points at the spawned order, the damage report moves to `REPAIR_IN_PROGRESS`, and every other bid on the same report in `SUBMITTED` or `COUNTERED` is rejected. The bid list filters by `damage_report_id`, `submitted_by_crew_id`, `property_id`, `approved_work_order_id`, and `status`.

Closure belongs to the `VendorAdmin` and takes an `outcome`. From `REPAIR_IN_PROGRESS`, closing with outcome `CLOSED` requires that no bid on the report stands in `DRAFT`, `SUBMITTED`, or `COUNTERED` (`ERR_OPEN_BIDS`) and that the work order referenced by the approved bid stands `COMPLETED` (`ERR_REPAIR_NOT_COMPLETED`); closure recomputes the property's condition score and posture. Closing with outcome `MONITORING` — the report's other terminal state — requires only the open-bids check. A report may also be closed directly from `TRIAGED` with outcome `CLOSED`, recomputing the score. Triage, bid-request, and closure each increment the report's `version`.

### 3.9. Invoicing, Allowable Reimbursement, and Servicer Settlement

Invoices are born, not made: completing a work order auto-creates an invoice in `DRAFT` carrying the order's `work_order_id`, `property_id`, and `investor_type` (§3.3). A `VendorAdmin` builds the claim by adding expense lines to a `DRAFT` invoice, each with an `item_code` from the same eleven-item vocabulary as the allowable schedule, a `quantity` of at least 1, a `unit_price_cents` of at least 0, and an optional `description`. The line's `claimed_cents` is its quantity times its unit price, and the invoice's `claimed_total_cents` is the sum of its lines' claimed amounts, recomputed as lines are added. Lines may be listed under their invoice, or across invoices through the expense-line list, which filters by `invoice_id` and `item_code`; the invoice list filters by `property_id`, `work_order_id`, and `status`.

Submitting the invoice — `DRAFT → SUBMITTED`, by a `VendorAdmin` — requires at least one expense line (`ERR_INVOICE_NO_LINES`) and requires the property's `financial_review_required` flag to be false (`ERR_FINANCIAL_REVIEW_REQUIRED`). Submission runs the **allowable reimbursement** calculation in its provisional variant, storing the result on the invoice as `provisional_allowed_cents` and on each line as `allowed_cents`, and stamps `submitted_at` from the logical clock.

The allowable reimbursement calculation runs twice in an invoice's life — provisionally at submission and finally at approval — and both runs work from the schedule snapshot pinned on the invoice's work order at creation (§2.11); later edits to the schedule row never affect the invoice. For each expense line with item code I, the calculation first measures how much of item I's annual entitlements the property has already consumed: the consumed units are the total `quantity` over lines with item code I on this property's invoices whose status falls in the variant's inclusion set and whose `submitted_at` falls in the same calendar year as this invoice's `submitted_at`, and the consumed cents are the same aggregation over those lines' `allowed_cents` as currently recorded (a not-yet-approved invoice contributes its provisionally computed values). The line's eligible units are the smaller of its `quantity` and the remaining occurrence allowance — the snapshot's `max_occurrences_per_calendar_year` minus the consumed units, floored at zero. The remaining item budget is the snapshot's `aggregate_cap_cents_per_property_year` minus the consumed cents, floored at zero. The line's `allowed_cents` is the smaller of two figures: its eligible units times the lesser of its `unit_price_cents` and the snapshot's `max_per_occurrence_cents`, and the remaining item budget. Evaluation order is fixed: per-line caps are computed first, in integer cents, and the aggregate item-year budget is then applied line by line in `created_at` ascending order — ties broken by `unit_price_cents` descending, then by insertion order — so a line earlier in that order consumes budget before a later line. A curtailed line records the first applicable `denial_reason`: `PER_OCCURRENCE_CAP` when the per-occurrence unit-price cap bound, `OCCURRENCE_COUNT_EXCEEDED` when the eligible units fell below the claimed quantity, `AGGREGATE_CAP_EXCEEDED` when the remaining item budget bound; a fully allowed line carries no denial reason. The invoice's total allowed amount is the sum of its lines' allowed amounts, always in integer cents with half-up rounding wherever a non-integer arises. The two variants differ only in the inclusion set: the provisional variant counts invoices in `SUBMITTED`, `APPROVED`, `PARTIALLY_APPROVED`, and `PAID` — a conservative posture that holds not-yet-approved submissions against the caps — while the final variant counts only settled invoices in `APPROVED`, `PARTIALLY_APPROVED`, and `PAID`, so the final figure can diverge from the provisional one when another of the property's invoices is still awaiting review.

Approval belongs to the owning `Servicer`: the caller's `X-User-ID` must equal the `servicer_id` of the invoice's property (`ERR_FORBIDDEN_FOR_ROLE`). Approval reruns the calculation in its final variant, storing the result as `approved_amount_cents` and refreshing each line's `allowed_cents`; the invoice lands `APPROVED` when the approved amount equals the `claimed_total_cents` and `PARTIALLY_APPROVED` otherwise. Approval also settles the **prompt-pay discount** with a pinned rounding order: the discount is computed per line and then summed. Each line's `line_discount_cents` is two percent of its `allowed_cents`, rounded half up to whole cents; the invoice's `prompt_pay_discount_cents` is the sum of those per-line discounts, and its `payable_amount_cents` is the approved amount minus the discount. Computing two percent on the invoice total instead yields a different cent value and is non-conformant. Finally, approval cascades to the property: `approved_amount_cents` is added to `ytd_investor_approved_cents`, and when the resulting total reaches or exceeds 200,000 cents the property's `financial_review_required` is set true, blocking further invoice submission until a `VendorAdmin` clears the flag through the property's clear-financial-review capability; `approved_at` is stamped from the logical clock.

A `Servicer` may instead deny a submitted invoice with a mandatory `reason` — `SUBMITTED → DENIED`. Either disappointment may be appealed once by a `VendorAdmin`: from `DENIED` or `PARTIALLY_APPROVED` back to `SUBMITTED`, provided the invoice's `appeal_round` is still below 1 — a second appeal is rejected with `ERR_APPEAL_EXHAUSTED`. Appealing sets `appeal_round` to 1, and appealing a `PARTIALLY_APPROVED` invoice additionally subtracts its `approved_amount_cents` from the property's `ytd_investor_approved_cents`, to be recomputed on re-approval; a denied invoice contributed nothing, so its appeal has no year-to-date effect.

Settlement closes the loop. A `Servicer` marks an `APPROVED` or `PARTIALLY_APPROVED` invoice paid — to the terminal `PAID`. Before payment, the servicer may instead void an `APPROVED` or `PARTIALLY_APPROVED` invoice — optionally with a `reason` — moving it to the terminal `VOIDED`; voiding subtracts `approved_amount_cents` from the property's year-to-date total and re-evaluates the review flag, clearing it when the total falls back below the threshold. The year-to-date counter obeys a conserved-quantity invariant: approval adds exactly `approved_amount_cents`, voiding or appealing removes exactly the same amount, and an approve-then-void pair leaves `ytd_investor_approved_cents` unchanged. The counter aggregates the `approved_amount_cents` of the property's invoices in `APPROVED`, `PARTIALLY_APPROVED`, or `PAID` whose `approved_at` falls in the calendar year recorded as `ytd_calendar_year`; the first daily sweep of a new calendar year resets `ytd_investor_approved_cents` to zero, advances `ytd_calendar_year` to the clock's year, and clears `financial_review_required`.

Servicer-level volume is settled monthly. When the daily sweep runs on the first of a month, each servicer's **volume rebate** is computed for the prior calendar month: the gross is the sum of `approved_amount_cents` across the servicer's invoices whose `approved_at` fell within that month, first day through last — rebate credits are never invoices, so a rebate never feeds a later gross. A gross of at least 1,000,000 cents earns a rate of 1.5 percent; a gross of at least 500,000 cents but below 1,000,000 earns 1.0 percent; anything smaller earns nothing, and the boundaries are inclusive — a gross of exactly 1,000,000 cents earns the 1.5 percent rate. The sweep records the gross as the servicer's `prior_month_gross_cents` and the rebate — gross times rate, rounded half up to whole cents — as its `volume_rebate_cents`.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code — servicers, crews, allowable rows, properties, work orders, inspections, dispositions, plans, violations, registrations, damage reports, bids, photo evidence, and expense lines. Operations that modify an existing resource — including every state transition, the clock set, and the daily sweep — return a `200 OK` status code. All list endpoints return `200 OK` with the pagination envelope of §2.3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/preservation/_clock/set_current_utc` | Set the logical clock (default 2026-08-01T00:00:00Z; never falls back to wall-clock) | VendorAdmin |
| POST | `/preservation/ops/run-daily-sweep` | Advance the operational epoch: recurring generation, registration expiry, violation escalation, hold release, work-order expiry, inspection miss, posture recompute, year reset, monthly rebate | VendorAdmin |
| POST | `/preservation/servicers` | Create a servicer organization | VendorAdmin |
| GET | `/preservation/servicers/{servicerId}` | Get a servicer, including computed rebate fields | Servicer, VendorAdmin, Dispatcher, FieldCrew, QualityReviewer |
| POST | `/preservation/crews` | Create a field crew | VendorAdmin |
| GET | `/preservation/crews/{crewId}` | Get a crew | Servicer, VendorAdmin, Dispatcher, FieldCrew, QualityReviewer |
| POST | `/preservation/investor-allowables` | Create an investor allowable schedule row | VendorAdmin |
| GET | `/preservation/investor-allowables/{allowableId}` | Get an allowable row | Servicer, VendorAdmin, Dispatcher, FieldCrew, QualityReviewer |
| PATCH | `/preservation/investor-allowables/{allowableId}` | Update allowable caps; bumps version; existing work orders keep their pinned snapshot | VendorAdmin |
| POST | `/preservation/properties` | Create a property; Servicer callers must pass their own servicer_id | VendorAdmin, Servicer |
| GET | `/preservation/properties/{propertyId}` | Get a property | Servicer, VendorAdmin, Dispatcher, FieldCrew, QualityReviewer |
| GET | `/preservation/properties` | List properties with filters and pagination | Servicer, VendorAdmin, Dispatcher, FieldCrew, QualityReviewer |
| POST | `/preservation/properties/{propertyId}/convey` | Convey property to investor (terminal) | Servicer |
| POST | `/preservation/properties/{propertyId}/clear-financial-review` | Clear the financial review flag | VendorAdmin |
| POST | `/preservation/work-orders` | Issue a work order (DIRECT source); allowable schedule is selected and pinned | Servicer |
| GET | `/preservation/work-orders/{workOrderId}` | Get a work order | Servicer, VendorAdmin, Dispatcher, FieldCrew, QualityReviewer |
| GET | `/preservation/work-orders` | List work orders with filters and pagination | Servicer, VendorAdmin, Dispatcher, FieldCrew, QualityReviewer |
| POST | `/preservation/work-orders/{workOrderId}/assign` | Assign a crew and schedule date (ISSUED to ASSIGNED) | Dispatcher |
| POST | `/preservation/work-orders/{workOrderId}/reassign` | Reassign crew and date (ASSIGNED to ASSIGNED); OCC-guarded | Dispatcher |
| POST | `/preservation/work-orders/{workOrderId}/start` | Crew starts work (ASSIGNED to IN_PROGRESS) | FieldCrew |
| POST | `/preservation/work-orders/{workOrderId}/submit` | Crew submits completion with declared cost (IN_PROGRESS to SUBMITTED) | FieldCrew |
| POST | `/preservation/work-orders/{workOrderId}/approve` | QA approves submission (SUBMITTED to APPROVED) | QualityReviewer |
| POST | `/preservation/work-orders/{workOrderId}/reject` | QA rejects submission for rework (SUBMITTED to IN_PROGRESS) | QualityReviewer |
| POST | `/preservation/work-orders/{workOrderId}/cancel` | Servicer cancels an open work order | Servicer |
| POST | `/preservation/work-orders/{workOrderId}/complete` | Mark completed (APPROVED to COMPLETED); auto-creates DRAFT invoice | QualityReviewer |
| POST | `/preservation/inspections` | Schedule an inspection (cycle_index auto-assigned per property) | VendorAdmin, Servicer |
| GET | `/preservation/inspections/{inspectionId}` | Get an inspection | Servicer, VendorAdmin, Dispatcher, FieldCrew, QualityReviewer |
| GET | `/preservation/inspections` | List inspections with filters and pagination | Servicer, VendorAdmin, Dispatcher, FieldCrew, QualityReviewer |
| POST | `/preservation/inspections/{inspectionId}/record` | Record findings; VACANT completes, OCCUPIED and INDETERMINATE go to VERIFICATION_PENDING | FieldCrew |
| POST | `/preservation/inspections/{inspectionId}/verify` | Verify occupancy after VERIFICATION_PENDING; OCCUPIED cascades to plans and generated orders | FieldCrew |
| POST | `/preservation/personal-property-dispositions` | Document personal property found on site; enters hold period | FieldCrew, VendorAdmin |
| GET | `/preservation/personal-property-dispositions/{dispositionId}` | Get a disposition | Servicer, VendorAdmin, Dispatcher, FieldCrew, QualityReviewer |
| GET | `/preservation/personal-property-dispositions` | List dispositions with filters and pagination | Servicer, VendorAdmin, Dispatcher, FieldCrew, QualityReviewer |
| POST | `/preservation/personal-property-dispositions/{dispositionId}/authorize-disposal` | Authorize disposal after hold release; valuation at or above 50000 cents requires Servicer | VendorAdmin, Servicer |
| POST | `/preservation/personal-property-dispositions/{dispositionId}/dispose` | Record final disposition outcome (terminal) | VendorAdmin |
| POST | `/preservation/recurring-plans` | Create a recurring grass-cut or snow-removal plan (starts ACTIVE) | VendorAdmin |
| GET | `/preservation/recurring-plans/{planId}` | Get a plan | Servicer, VendorAdmin, Dispatcher, FieldCrew, QualityReviewer |
| GET | `/preservation/recurring-plans` | List plans with filters and pagination | Servicer, VendorAdmin, Dispatcher, FieldCrew, QualityReviewer |
| POST | `/preservation/recurring-plans/{planId}/suspend` | Suspend an ACTIVE plan; cancels its open generated orders | VendorAdmin |
| POST | `/preservation/recurring-plans/{planId}/resume` | Resume a SUSPENDED plan; requires in-season and non-OCCUPIED property | VendorAdmin |
| POST | `/preservation/recurring-plans/{planId}/end` | End a plan (terminal) | VendorAdmin |
| POST | `/preservation/code-violations` | Record a municipal code violation | VendorAdmin |
| GET | `/preservation/code-violations/{violationId}` | Get a violation (accrued_fine_cents current as of clock) | Servicer, VendorAdmin, Dispatcher, FieldCrew, QualityReviewer |
| GET | `/preservation/code-violations` | List violations with filters and pagination | Servicer, VendorAdmin, Dispatcher, FieldCrew, QualityReviewer |
| POST | `/preservation/code-violations/{violationId}/start-cure` | Link a CODE_CURE work order and begin cure | VendorAdmin |
| POST | `/preservation/code-violations/{violationId}/submit-cure` | Submit cure evidence to municipality; requires linked work order COMPLETED | FieldCrew |
| POST | `/preservation/code-violations/{violationId}/verify` | Municipal verification closes the violation (terminal) | VendorAdmin |
| POST | `/preservation/code-violations/{violationId}/reject-cure` | Municipality rejected the cure; back to CURE_IN_PROGRESS | VendorAdmin |
| POST | `/preservation/registrations` | Create a municipal vacant-property registration (PENDING) | VendorAdmin |
| GET | `/preservation/registrations/{registrationId}` | Get a registration | Servicer, VendorAdmin, Dispatcher, FieldCrew, QualityReviewer |
| GET | `/preservation/registrations` | List registrations with filters and pagination | Servicer, VendorAdmin, Dispatcher, FieldCrew, QualityReviewer |
| POST | `/preservation/registrations/{registrationId}/activate` | Activate a registration; half-open overlap check against ACTIVE siblings | VendorAdmin |
| POST | `/preservation/registrations/{registrationId}/renew` | Renew an ACTIVE or EXPIRED registration to a new exclusive end date | VendorAdmin |
| POST | `/preservation/registrations/{registrationId}/release` | Release a registration (terminal) | VendorAdmin |
| POST | `/preservation/damage-reports` | Field crew reports damage or vandalism | FieldCrew |
| GET | `/preservation/damage-reports/{reportId}` | Get a damage report | Servicer, VendorAdmin, Dispatcher, FieldCrew, QualityReviewer |
| GET | `/preservation/damage-reports` | List damage reports with filters and pagination | Servicer, VendorAdmin, Dispatcher, FieldCrew, QualityReviewer |
| POST | `/preservation/damage-reports/{reportId}/triage` | Triage a report (REPORTED to TRIAGED) | VendorAdmin |
| POST | `/preservation/damage-reports/{reportId}/request-bids` | Open the report for bids (TRIAGED to BID_REQUESTED) | VendorAdmin |
| POST | `/preservation/damage-reports/{reportId}/close` | Close or monitor a report (terminal) | VendorAdmin |
| POST | `/preservation/damage-reports/{damageReportId}/bids` | Submit a bid draft against a BID_REQUESTED damage report; OCC-guarded on the report version | FieldCrew |
| GET | `/preservation/bids/{bidId}` | Get a bid | Servicer, VendorAdmin, Dispatcher, FieldCrew, QualityReviewer |
| GET | `/preservation/bids` | List bids with filters and pagination | Servicer, VendorAdmin, Dispatcher, FieldCrew, QualityReviewer |
| POST | `/preservation/bids/{bidId}/submit` | Submit a draft bid (DRAFT to SUBMITTED) | FieldCrew |
| POST | `/preservation/bids/{bidId}/approve` | Servicer approves a bid; spawns DAMAGE_REPAIR work order and rejects competing open bids | Servicer |
| POST | `/preservation/bids/{bidId}/counter` | Servicer counter-offers (SUBMITTED to COUNTERED) | Servicer |
| POST | `/preservation/bids/{bidId}/revise` | Crew revises after counter (COUNTERED to SUBMITTED; round_number increments) | FieldCrew |
| POST | `/preservation/bids/{bidId}/reject` | Servicer rejects a bid (terminal) | Servicer |
| POST | `/preservation/bids/{bidId}/withdraw` | Owning crew withdraws a DRAFT or SUBMITTED bid (terminal) | FieldCrew |
| POST | `/preservation/photo-evidence` | Upload photo evidence; exactly one subject reference required | FieldCrew |
| GET | `/preservation/photo-evidence/{photoId}` | Get a photo evidence row | Servicer, VendorAdmin, Dispatcher, FieldCrew, QualityReviewer |
| GET | `/preservation/photo-evidence` | List photo evidence with filters and pagination | Servicer, VendorAdmin, Dispatcher, FieldCrew, QualityReviewer |
| POST | `/preservation/photo-evidence/{photoId}/flag` | QA flags a photo deficient | QualityReviewer |
| POST | `/preservation/photo-evidence/{photoId}/clear-flag` | Clear a flag; clearer must differ from flagger (segregation of duties) | QualityReviewer |
| GET | `/preservation/invoices/{invoiceId}` | Get an invoice | Servicer, VendorAdmin, Dispatcher, FieldCrew, QualityReviewer |
| GET | `/preservation/invoices` | List invoices with filters and pagination | Servicer, VendorAdmin, Dispatcher, FieldCrew, QualityReviewer |
| POST | `/preservation/invoices/{invoiceId}/lines` | Add an expense line to a DRAFT invoice | VendorAdmin |
| GET | `/preservation/invoices/{invoiceId}/lines` | List expense lines of an invoice | Servicer, VendorAdmin, Dispatcher, FieldCrew, QualityReviewer |
| GET | `/preservation/expense-lines` | List expense lines with filters and pagination | Servicer, VendorAdmin, Dispatcher, FieldCrew, QualityReviewer |
| GET | `/preservation/expense-lines/{expenseLineId}` | Get an expense line | Servicer, VendorAdmin, Dispatcher, FieldCrew, QualityReviewer |
| POST | `/preservation/invoices/{invoiceId}/submit` | Submit a DRAFT invoice; computes provisional allowable | VendorAdmin |
| POST | `/preservation/invoices/{invoiceId}/approve` | Servicer approves; computes final allowable, prompt-pay discount, year-to-date cascade | Servicer |
| POST | `/preservation/invoices/{invoiceId}/deny` | Servicer denies a submitted invoice | Servicer |
| POST | `/preservation/invoices/{invoiceId}/appeal` | Appeal a DENIED or PARTIALLY_APPROVED invoice once; returns to SUBMITTED | VendorAdmin |
| POST | `/preservation/invoices/{invoiceId}/mark-paid` | Mark an APPROVED or PARTIALLY_APPROVED invoice paid (terminal) | Servicer |
| POST | `/preservation/invoices/{invoiceId}/void` | Void an approval before payment; reverses year-to-date contribution | Servicer |

## 5. Error Code Catalogue

Trigger conditions for each error live in §2 and §3 alongside the workflows they guard; this catalogue fixes only the identifier and HTTP status.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_PROPERTY_NOT_ACTIVE` | 409 Conflict |
| `ERR_POSTURE_BLOCKS_ORDER` | 409 Conflict |
| `ERR_OPEN_WORK_ORDERS` | 409 Conflict |
| `ERR_PROPERTY_OCCUPIED` | 409 Conflict |
| `ERR_NOT_ASSIGNED_CREW` | 409 Conflict |
| `ERR_NOT_BID_OWNER` | 409 Conflict |
| `ERR_PHOTO_INCOMPLETE` | 409 Conflict |
| `ERR_PHOTO_FLAGGED_OPEN` | 409 Conflict |
| `ERR_SOD_FLAG_CLEAR` | 409 Conflict |
| `ERR_CREW_DAY_CAPACITY` | 409 Conflict |
| `ERR_BID_REQUIRED_OVER_CAP` | 409 Conflict |
| `ERR_ALLOWABLE_NOT_FOUND` | 409 Conflict |
| `ERR_REGISTRATION_REQUIRED` | 409 Conflict |
| `ERR_REGISTRATION_OVERLAP` | 409 Conflict |
| `ERR_REGISTRATION_NUMBER_NOT_UNIQUE` | 409 Conflict |
| `ERR_CITATION_NOT_UNIQUE` | 409 Conflict |
| `ERR_CURE_DEADLINE_PASSED` | 409 Conflict |
| `ERR_CURE_WORK_INCOMPLETE` | 409 Conflict |
| `ERR_SEASON_WINDOW_CLOSED` | 409 Conflict |
| `ERR_HOLD_PERIOD_ACTIVE` | 409 Conflict |
| `ERR_DISPOSAL_AUTHORITY_LIMIT` | 409 Conflict |
| `ERR_INVOICE_NO_LINES` | 409 Conflict |
| `ERR_FINANCIAL_REVIEW_REQUIRED` | 409 Conflict |
| `ERR_APPEAL_EXHAUSTED` | 409 Conflict |
| `ERR_DAMAGE_NOT_ACCEPTING_BIDS` | 409 Conflict |
| `ERR_OPEN_BIDS` | 409 Conflict |
| `ERR_REPAIR_NOT_COMPLETED` | 409 Conflict |
