# Oversize Load Escort API — Product Requirements Document

## 1. Introduction

Moving an oversize or overweight load across state lines is one of the most regulated operations in road transport. A load that is perfectly legal in Texas can require an additional front escort in Oklahoma, a height pole in Louisiana, or a police escort in Kansas — and in every state it is subject to morning and evening curfew windows, holiday embargoes, and permit validity windows that must align with the actual movement plan. A certified pilot car company sits in the middle of this: it quotes and books escort jobs for trucking carriers, works out per-state escort and equipment requirements for every leg of the route, staffs each required position with a certified, properly equipped escort, supervises route surveys when overhead clearance is in doubt, coordinates police escorts, and then bills the carrier — including standby time, cancellation fees, damage chargebacks, and volume discounts — under a credit limit the carrier must never silently exceed.

This document specifies the Oversize Load Escort API, the system of record for that operation. It governs the full lifecycle of an escort job from booking through delivery or cancellation: requirement determination and provisional quoting, quote acceptance under carrier credit control, permit administration, police coordination, route surveys with obstruction records, escort assignment with deterministic selection, movement control with a driver communication protocol, delay and standby billing, incident reporting with liability assessment, and invoice generation, dispute, and settlement. Seven distinct operator roles interact with the system, several of them under explicit segregation-of-duties constraints, and all time-dependent behavior is driven by a controllable logical clock rather than wall-clock time. The API operates across four states — Texas, Oklahoma, Kansas, and Louisiana — whose differing escort thresholds, curfew windows, and equipment rules are first-class business data throughout this specification.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, structural contracts, and cross-cutting principles that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity in which they act. A request missing either header, or carrying a role value that is not one of the declared roles, is rejected with `ERR_MISSING_USER_CONTEXT`. A request whose declared role is not authorized for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes exactly seven roles. `CarrierRep` is a representative of a carrier (trucking company) customer, booking escort jobs and acting on its own carrier's jobs, incident disputes, and invoice disputes. `Dispatcher` is the pilot-car company's dispatcher, responsible for carrier and escort registration, quoting, permit administration, police coordination, assignment management, movement control, standby tracking, and the logical clock. `EscortOperator` is a certified pilot car operator acting on its own assignments and filing field reports. `RouteSurveyor` performs route surveys and records obstructions. `SafetyManager` is the safety authority for survey decisions, escort standing, and incident assessment. `BillingClerk` generates, finalizes, and adjusts invoices under a maker-checker rule. `FinanceManager` settles incidents, records payments, and writes off bad debt.

Two roles are entity-backed, which is what ties `X-User-ID` to resource ownership. When `X-User-Role` is `CarrierRep`, `X-User-ID` is the `id` of the acting Carrier; ownership checks on any resource that references a Carrier compare the resource's `carrier_id` field to `X-User-ID`, and a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER`. When `X-User-Role` is `EscortOperator`, `X-User-ID` is the `id` of the acting Escort; ownership checks on an assignment compare the assignment's `escort_id` field to `X-User-ID`, and a mismatch is likewise rejected with `ERR_NOT_RESOURCE_OWNER`. When `X-User-Role` is `Dispatcher`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `reporter_user_id` or `assessed_by_user_id` on an Incident where a Dispatcher reports or assesses) but does not compare it to any entity's `id`. The same opaque rule applies individually to `RouteSurveyor`, to `SafetyManager` (whose `X-User-ID` is recorded as `decided_by_user_id` on survey decisions and as `assessed_by_user_id` on incident assessments, without being compared to any entity's `id`), to `BillingClerk` (whose `X-User-ID` is recorded as `generated_by_user_id` on invoices it generates), and to `FinanceManager`.

All read endpoints (every GET operation) are open to all seven roles. Ownership rules never restrict reads; they restrict the specific mutating operations enumerated in §3.

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

List endpoints are paginated through two optional query parameters. The `limit` parameter caps the number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items from the start of the result set and defaults to 0. Integer values outside these ranges are clamped to the nearest bound rather than rejected: a `limit` below 1 is treated as 1, a `limit` above 100 is treated as 100, and a negative `offset` is treated as 0, and the effective values are the ones carried in the response's pagination fields.

Unless otherwise specified, list endpoints return rows ordered by `created_at` in ascending order, so the first element of `data` is deterministic. The single exception is the listing of a job's route legs, which is ordered by `sequence_index` ascending so that the route reads in traversal order.

Every paginated list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the response envelope.

### 2.4. Logical Time and the System Clock

All time-dependent behavior in the system — quote expiry, permit expiry, curfew evaluation, check-in staleness, delay durations — reads a single server-side logical clock, never the host's wall clock. Before any administrative set call, the logical clock starts at exactly 2026-08-01T00:00:00Z. A `Dispatcher`-only administrative capability advances the clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`; once set, the clock never falls back to wall-clock time.

Advancing the clock is not inert: it triggers a sweep of time-dependent state. Every permit in `ISSUED` status whose `valid_until` is earlier than the new current time transitions to `EXPIRED`, and each such expiry cascades — the affected leg falls from `CLEARED` to `BLOCKED`, and the owning job is demoted from `CLEARED` or `SCHEDULED` back to `BOOKED` as described in §3.4.

### 2.5. Common Resource Properties and Versioning

Every primary resource — Carrier, Escort, Job, RouteLeg, Permit, RouteSurvey, EscortAssignment, DelayEvent, Incident, and Invoice — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp, refreshed on every modification of the resource.
- `version` (integer): a system-managed integer that increments by exactly 1 on every modification of the resource, including system-driven cascade mutations.

Obstruction rows are the single exception: an Obstruction carries only `id` and `created_at`. Both `updated_at` and `version` are absent from Obstruction resources, because obstruction records are append-only and immutable once created.

Every state transition described in §3 — whether client-initiated or fired automatically by the server — constitutes a mutation of each affected resource: its `updated_at` is refreshed and its `version` is incremented by 1. Where a single operation mutates several resources (for example, a survey decision that also clears or blocks its leg), each affected resource's version is incremented independently.

### 2.6. Units, Measurements, and Monetary Precision

All monetary values in the system are integer numbers of cents; no fractional cents exist anywhere, and every monetary field is stored, computed, and returned as a whole number of cents. Wherever a computation produces a fractional cent, the value is rounded half up to the nearest whole cent at the step this document marks for rounding, and rounding is applied at that step rather than once at the end. Load dimensions (`width_inches`, `height_inches`, `length_inches`, clearances, pole heights) are whole inches. Leg distances are whole miles. Durations and time comparisons (`raw_minutes`, `billable_minutes`, check-in staleness, curfew and overlap windows) are whole minutes. Reliability scores are integers between 0 and 100 inclusive, and fault-share percentages are integers between 0 and 100 inclusive. Requirement thresholds in §3.3 are integer thresholds compared inclusively — a dimension exactly at a threshold always triggers the requirement.

### 2.7. Hierarchical Consistency and Cascade Semantics

Jobs own route legs; legs own permits, route surveys, and escort assignments; surveys own obstruction rows; jobs additionally own delay events, incidents, and invoices. Each child record carries its parent's identifier: every RouteLeg, DelayEvent, Incident, and Invoice records its owning job in its `job_id` field, every Permit, RouteSurvey, and EscortAssignment records its leg in `leg_id`, and every Obstruction records its survey in `survey_id`. The server keeps this hierarchy consistent automatically, without requiring a client request on each affected resource: when a parent undergoes a transition that invalidates its children's state, the children are transitioned in the same operation, and when a child event satisfies or breaks a parent's gate, the parent is re-evaluated immediately.

The cascades in this system, each detailed where it occurs in §3, are: quoting a job determines every leg's requirements; amending a job's dimensions resets determined legs; issuing a permit, accepting a survey, or confirming police coordination re-evaluates the leg's clearance gate and then the job's clearance gate; a failing survey or an expiring permit blocks its leg and demotes its job; cancelling a job releases its assignments and cancels its legs; delivering a job completes its assignments and legs; suspending an escort releases that escort's accepted assignments and demotes any scheduled job that loses a required position; settling an incident can suspend an escort and thereby trigger that same cascade; accepting a new survey supersedes the previously accepted one; and paying or writing off an invoice closes a delivered job. Each of these reconciliations mutates every resource it touches, refreshing `updated_at` and incrementing `version` per §2.5.

### 2.8. Nested Resource Retrieval

Endpoints that address nested resources validate path identifiers strictly left to right, and the request is rejected with the not-found error belonging to the first path identifier that does not resolve to an existing resource: a missing job yields `ERR_JOB_NOT_FOUND`, a missing leg `ERR_LEG_NOT_FOUND`, a missing permit `ERR_PERMIT_NOT_FOUND`, a missing survey `ERR_SURVEY_NOT_FOUND`, a missing assignment `ERR_ASSIGNMENT_NOT_FOUND`, a missing delay event `ERR_DELAY_EVENT_NOT_FOUND`, a missing incident `ERR_INCIDENT_NOT_FOUND`, a missing invoice `ERR_INVOICE_NOT_FOUND`, a missing carrier `ERR_CARRIER_NOT_FOUND`, and a missing escort `ERR_ESCORT_NOT_FOUND`. On a path such as a job's leg collection, a non-existent job id is reported before the system even considers the leg segment. All nested parents in this API use `{id}` as the placeholder segment name.

Identifiers referenced inside a request body are checked after the path identifiers: a booking that names an unknown `carrier_id` is rejected with `ERR_CARRIER_NOT_FOUND`, an assignment offer that names an unknown `escort_id` is rejected with `ERR_ESCORT_NOT_FOUND`, and an incident report that names an unknown `assignment_id` is rejected with `ERR_ASSIGNMENT_NOT_FOUND`. An `assignment_id` that exists but belongs to a leg of a different job is not a not-found case; it is rejected with `ERR_INVALID_REQUEST`.

### 2.9. Optimistic Concurrency Control

Two write operations in this API are guarded by optimistic concurrency control on a parent resource, and these are the only two operations that accept a version field at all.

Amending a job requires the request to carry `expected_job_version`, holding the job `version` the client last observed. If that value does not match the job's current `version` — for example because a quote was generated, or another amendment was applied, since the client read the job — the amendment is rejected with `ERR_STALE_JOB_VERSION` (HTTP 412). The client's view of the job is stale and must be refreshed before the amendment can be attempted again.

Deciding a route survey (accept or reject) requires the request to carry `expected_leg_version`, holding the leg `version` the client last observed. If that value does not match the leg's current `version` — for example because a prior decision on this leg superseded the previously accepted survey and recomputed the leg's clearance verdict — the decision is rejected with `ERR_STALE_LEG_VERSION` (HTTP 412), since it would be based on a stale survey set.

No other endpoint takes a version field; all other state preconditions in the system are enforced through the state checks of §2.11 rather than through client-supplied versions.

### 2.10. Carrier Credit Availability

Every carrier has a credit limit and a live availability figure. A carrier's `credit_available_cents` equals its `credit_limit_cents`, minus the sum of `quoted_cents` over that carrier's jobs currently in `BOOKED`, `CLEARED`, `SCHEDULED`, `EN_ROUTE`, or `ON_HOLD` status (the outstanding quoted holds), minus the sum of `total_cents` over that carrier's invoices currently in `FINALIZED` or `DISPUTED` status (the outstanding billed set). Jobs in `DRAFT`, `QUOTED`, `DELIVERED`, `CLOSED`, or `CANCELLED` contribute no hold, and invoices in `DRAFT`, `PAID`, or `WRITTEN_OFF` sit outside the outstanding set.

Availability is a computed field, re-evaluated whenever its inputs move: accepting a quote consumes availability, cancelling a booked job releases the hold (so a book-then-cancel pair conserves the carrier's available credit exactly), finalizing an invoice moves its total into the outstanding set, disputing keeps it there, and recording payment or writing the invoice off removes it — payment additionally credits the carrier's year-to-date billed total, while write-off does not. The accept-quote gate of §3.3 reads this figure to decide whether a carrier may book.

### 2.11. Validation Order Across the Request Pipeline

Every mutating request passes through a single ordered validation pipeline, and the first failing check produces the response — later checks are not evaluated once an earlier one has failed. The order is:

1. Authentication context: the `X-User-ID` and `X-User-Role` headers must be present and the role must be a declared role, else `ERR_MISSING_USER_CONTEXT` (HTTP 400).
2. Role authorization: the caller's role must appear in the endpoint's authorized roles, else `ERR_FORBIDDEN_ROLE` (HTTP 403).
3. Request body shape: required fields must be present, types must match, enum values must be members of their declared sets, and numeric ranges must hold — dimensions greater than zero, `valid_until` later than `valid_from`, `window_end_at` later than `window_start_at`, `planned_exit_at` later than `planned_entry_at`, `escort_fault_share_pct` between 0 and 100 inclusive. Violations yield `ERR_INVALID_REQUEST` (HTTP 400); for an out-of-membership enum value the server may instead return `ERR_INVALID_ENUM_VALUE` (HTTP 400), and both live at this priority.
4. Path resource existence, validated left to right per §2.8, yielding the appropriate not-found error (HTTP 404).
5. Body-referenced foreign key existence per §2.8 (HTTP 404).
6. Ownership for entity-backed callers per §2.1, else `ERR_NOT_RESOURCE_OWNER` (HTTP 403).
7. State preconditions: the target resource must be in a state that permits the operation, per the transition rules of §3, else the matching invalid-state error (HTTP 409): `ERR_JOB_INVALID_STATE`, `ERR_LEG_INVALID_STATE`, `ERR_PERMIT_INVALID_STATE`, `ERR_SURVEY_INVALID_STATE`, `ERR_ASSIGNMENT_INVALID_STATE`, `ERR_DELAY_EVENT_INVALID_STATE`, `ERR_INCIDENT_INVALID_STATE`, `ERR_INVOICE_INVALID_STATE`, or `ERR_ESCORT_INVALID_STATE`. The two optimistic-concurrency rejections of §2.9 are also evaluated at this stage.
8. Escort safety checks on explicit assignment offers: state certification (`ERR_ESCORT_NOT_CERTIFIED_FOR_STATE`, HTTP 422) and height-pole equipment (`ERR_HEIGHT_POLE_EQUIPMENT_MISSING`, HTTP 422).
9. The permit-issuance guard: a permit may only be issued while its leg's job is booked or beyond (`ERR_JOB_INVALID_STATE`, HTTP 409); this regulatory guard sits just after the general state checks.
10. Temporal business rules in endpoint order: permit window coverage (`ERR_PERMIT_WINDOW_INSUFFICIENT`, HTTP 409), curfew compliance (`ERR_CURFEW_WINDOW_VIOLATION`, HTTP 409), escort window conflict (`ERR_ESCORT_WINDOW_CONFLICT`, HTTP 409), quote expiry (`ERR_QUOTE_EXPIRED`, HTTP 409), and communication check-in currency (`ERR_COMMS_CHECKIN_OVERDUE`, HTTP 409).
11. Referential uniqueness and quota rules (HTTP 409): `ERR_ACTIVE_INVOICE_EXISTS`, `ERR_OPEN_DELAY_EVENT_EXISTS`, `ERR_OPEN_SURVEY_EXISTS`, `ERR_POSITION_QUOTA_FILLED`, and `ERR_ASSIGNMENTS_INCOMPLETE`.
12. Segregation of duties: `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).
13. Carrier credit: `ERR_CREDIT_LIMIT_WOULD_BE_EXCEEDED` (HTTP 402).
14. Payment integrity: `ERR_PAYMENT_AMOUNT_MISMATCH` and `ERR_ADJUSTMENT_EXCEEDS_TOTAL` (both HTTP 422).

Within a single endpoint, the same ordering decides which error surfaces when several rules are violated at once; §3 calls out the concrete per-endpoint sequences wherever an endpoint is guarded by more than one of these checks.

## 3. Business Logic & Workflows

### 3.1. Registering Carriers and Escorts

Before any job can move, the pilot-car company registers its counterparties, and only a `Dispatcher` may perform either registration. Registering a carrier records the customer's `carrier_name` and its `credit_limit_cents`, which must be greater than zero. A freshly registered carrier starts with `ytd_billed_cents` at 0 and `credit_available_cents` equal to its full credit limit; thereafter `ytd_billed_cents` accumulates the `total_cents` of the carrier's invoices that transitioned to `PAID` during the current calendar year (UTC), and availability follows the rule of §2.10. The carrier roster can be listed with ordinary `limit` and `offset` pagination, and a single carrier read returns the computed `credit_available_cents` alongside the stored fields.

Registering an escort captures the operator's `operator_name`, the `certified_state_codes` array — a non-empty list in which every element is one of `TX`, `OK`, `KS`, or `LA` — and the vehicle's height-pole equipment: `has_height_pole`, which defaults to false when omitted, and `height_pole_max_inches`, which defaults to 0 but must be greater than zero whenever `has_height_pole` is true. A new escort begins with a `reliability_score` of 100, an `escort_status` of `ACTIVE`, and an `active_assignment_count` of 0. The escort roster listing supports filtering by `state_code` (only escorts certified for that state are returned) and by `escort_status`, in addition to `limit` and `offset`.

An escort's standing is managed by a `SafetyManager`. Suspending an escort — an action carrying an optional `reason` — is permitted only while the escort is `ACTIVE`, else the request is rejected with `ERR_ESCORT_INVALID_STATE`. Suspension moves the escort to `SUSPENDED` and immediately releases every one of that escort's assignments currently in `ACCEPTED`: each becomes `RELEASED` with `release_cause` `ESCORT_SUSPENDED`, and the escort's `active_assignment_count` is decremented for each release. If any of those releases leaves a `SCHEDULED` job with a required position uncovered, that job is demoted to `CLEARED` in the same cascade. Reinstatement by a `SafetyManager` is permitted only while the escort is `SUSPENDED` (again `ERR_ESCORT_INVALID_STATE` otherwise) and returns the escort to `ACTIVE`; reinstatement deliberately does not reset `reliability_score` — the score survives suspension unchanged.

### 3.2. Booking the Job: Dimensions, Windows, and Route Legs

A `CarrierRep` books an escort job for its own carrier: the payload's `carrier_id` must match the caller's `X-User-ID`, or the request is rejected with `ERR_NOT_RESOURCE_OWNER`, and it must reference an existing carrier, else `ERR_CARRIER_NOT_FOUND`. The booking describes the load in free text via `load_description` and in hard numbers via `width_inches`, `height_inches`, and `length_inches` — each greater than zero — plus `gross_weight_lbs`, also greater than zero. The planned movement is bounded by `window_start_at` and `window_end_at`, with the end strictly later than the start; escorts are blocked for the whole of that window once assigned, per the overlap rule of §3.5.

The route travels with the booking as a `legs` array, supplied only at creation — legs cannot be added or edited later. The array must contain at least one element, and each element specifies `state_code` (one of `TX`, `OK`, `KS`, `LA`; any other value is rejected with `ERR_INVALID_REQUEST`), `sequence_index` (zero or greater, fixing the leg's order within the route), `distance_miles` (greater than zero), `planned_entry_at` and `planned_exit_at` (the planned state-line entry and exit, with the exit strictly later than the entry), and `map_min_clearance_inches` (zero or greater), the map database's minimum overhead clearance along the leg, which feeds the advisory clearance estimate of §3.4. Booking creates the job with its `job_status` field at `DRAFT` and, in the same operation, creates one route leg per element of `legs`, each with its `leg_status` at `PENDING`; the job's leg listing returns them ordered by `sequence_index` ascending. Until the job reaches the states that set them, `quoted_cents`, `quoted_at`, `quote_expires_at`, `booked_at`, `departed_at`, `delivered_at`, and `cancelled_at` are null, while `cancel_fee_cents` starts at 0, `cancel_fee_tier` starts null, and `total_escort_positions` starts at 0.

Either the owning `CarrierRep` or a `Dispatcher` may amend a job, but only while it is in `DRAFT` or `QUOTED` — any other status is rejected with `ERR_JOB_INVALID_STATE` — and the amendment is guarded by the optimistic concurrency rule of §2.9: the request must carry `expected_job_version`, and a mismatch with the job's current `version` is rejected with `ERR_STALE_JOB_VERSION`. All amendment fields are optional: `load_description`, `width_inches`, `height_inches`, `length_inches`, `gross_weight_lbs`, `window_start_at`, and `window_end_at` may each be supplied or omitted, and supplied values replace the stored ones. Amending a `QUOTED` job reverts it to `DRAFT` and discards the quote entirely — `quoted_cents`, `quoted_at`, and `quote_expires_at` are cleared to null and `total_escort_positions` to 0 — while amending a `DRAFT` job updates the fields in place. Whenever at least one of the four dimensional fields changes, every leg currently in `DETERMINED` is reset to `PENDING` with its requirement fields returned to their defaults; the leg's `clearance_verdict` is left untouched. An amendment confined to the description or the movement window does not disturb existing leg determinations.

### 3.3. Requirement Determination, Quoting, and Quote Acceptance

A `Dispatcher` requests a quote for a job in `DRAFT`; a job in any other status is rejected with `ERR_JOB_INVALID_STATE`. Quoting first runs requirement determination on every leg, moving each from `PENDING` to `DETERMINED`. Determination reads the leg's `state_code` and the job's `width_inches`, `height_inches`, and `gross_weight_lbs`, and sets five requirement fields on the leg: `required_rear_escorts` (0 or 1), `required_front_escorts` (0, 1, or 2), `requires_height_pole`, `requires_police_escort`, and `requires_route_survey`. Every threshold below is in whole inches or whole pounds and every boundary is inclusive: a width exactly at a threshold always triggers the requirement.

For a leg traversing Texas (`TX`): one rear escort is required when the load width is at least 168 inches; front coverage is two front escorts when the width is at least 192 inches, otherwise one front escort when it is at least 180 inches, otherwise none. A height pole is required when the load height is at least 174 inches. A police escort is required when the width is at least 192 inches or the gross weight is at least 200,000 pounds. A route survey is required whenever the leg requires a height pole, and also when the load height comes within six inches of the pole threshold — that is, at least 168 inches.

For a leg traversing Oklahoma (`OK`): one rear escort is required when the load width is at least 168 inches; front coverage is two front escorts when the width is at least 186 inches, otherwise one front escort when it is at least 174 inches, otherwise none. A height pole is required when the load height is at least 168 inches. A police escort is required when the width is at least 180 inches or the gross weight is at least 180,000 pounds. A route survey is required whenever the leg requires a height pole, and also when the load height is at least 162 inches — within six inches of the Oklahoma pole threshold.

For a leg traversing Kansas (`KS`): one rear escort is required when the load width is at least 156 inches; front coverage is two front escorts when the width is at least 192 inches, otherwise one front escort when it is at least 180 inches, otherwise none. A height pole is required when the load height is at least 174 inches. A police escort is required when the width is at least 192 inches or the gross weight is at least 250,000 pounds. A route survey is required whenever the leg requires a height pole, and also when the load height is at least 168 inches.

For a leg traversing Louisiana (`LA`): one rear escort is required when the load width is at least 144 inches; front coverage is two front escorts when the width is at least 180 inches, otherwise one front escort when it is at least 168 inches, otherwise none. A height pole is required when the load height is at least 162 inches. A police escort is required when the width is at least 180 inches or the gross weight is at least 150,000 pounds. A route survey is required whenever the leg requires a height pole, and also when the load height is at least 156 inches.

With every leg determined, quoting computes the provisional price. For each leg, the estimated escort hours are the leg's `distance_miles` divided by an assumed average speed of 50 miles per hour, with the quotient rounded up to a multiple of half an hour — a value already on a half-hour boundary is unchanged. That estimate is multiplied by the leg's total escort positions (its `required_front_escorts` plus its `required_rear_escorts`) and by the hourly rate of 9,000 cents per hour per escort position, producing the leg's base estimate. The equipment estimate adds 15,000 cents for a leg that requires a height pole, 40,000 cents for a leg that requires a police escort, and 25,000 cents for a leg that requires a route survey. The job's `quoted_cents` is the sum of the base and equipment estimates across all legs, an integer number of cents with no further rounding. Quoting also stamps `quoted_at` with the current time, sets `quote_expires_at` exactly 72 hours later, records the job's `total_escort_positions` as the sum of front and rear requirements across all legs, and moves the job from `DRAFT` to `QUOTED`.

Acceptance is the owning `CarrierRep`'s decision, and its checks are evaluated in a fixed order. The job must be in `QUOTED`, else `ERR_JOB_INVALID_STATE`. The acceptance must arrive before `quote_expires_at`; an attempt at or after that instant is rejected with `ERR_QUOTE_EXPIRED`. Finally, the carrier's `credit_available_cents` per §2.10 must be at least the job's `quoted_cents`; if accepting would push the carrier's outstanding quoted holds plus outstanding billed invoices above its `credit_limit_cents`, the acceptance is rejected with `ERR_CREDIT_LIMIT_WOULD_BE_EXCEEDED` (HTTP 402). A successful acceptance moves the job to `BOOKED`, stamps `booked_at`, and places the quoted hold: the job's `quoted_cents` now counts against the carrier's availability for as long as the job remains in `BOOKED`, `CLEARED`, `SCHEDULED`, `EN_ROUTE`, or `ON_HOLD`.

### 3.4. Clearing the Route: Permits, Police Coordination, and Route Surveys

A booked job cannot move until every leg is `CLEARED`, and three independent gates feed that clearance: a valid state permit, a passing route survey where one is required, and confirmed police coordination where a police escort is required.

A `Dispatcher` records a permit application on a leg with the state-issued `permit_number`, the validity window `valid_from` and `valid_until` (the end strictly later than the start; once the current time passes `valid_until` the permit is considered expired), and an optional `holiday_closure_dates` array of YYYY-MM-DD dates — defaulting to empty — on which oversize movement is embargoed despite the permit. A recorded permit starts with its `permit_status` at `APPLIED`. Marking the permit issued, also a `Dispatcher` action, requires the permit to be in `APPLIED` (else `ERR_PERMIT_INVALID_STATE`) and the leg's job to be in `BOOKED`, `CLEARED`, or `SCHEDULED` — permits cannot be issued for an unbooked job, and the attempt is rejected with `ERR_JOB_INVALID_STATE`. Issuance stamps `issued_at` — null until this point — moves the permit to `ISSUED`, and re-evaluates the leg's clearance gate and then the job's, as described below. Permits expire without any client action: the clock sweep of §2.4 moves every `ISSUED` permit whose `valid_until` has passed to the terminal `EXPIRED` status, and each expiry blocks a cleared leg and demotes the owning job.

Where a leg's `requires_police_escort` flag is set, a `Dispatcher` confirms police escort coordination for the leg, setting `police_confirmed` — which starts false on every leg — to true and re-evaluating the clearance gates. Confirming police on a leg whose `requires_police_escort` is false is rejected with `ERR_INVALID_REQUEST`.

Where `requires_route_survey` is set, clearance rides on field measurement. A `RouteSurveyor` requests a route survey for a leg in `DETERMINED` or `BLOCKED` status — any other leg status is rejected with `ERR_LEG_INVALID_STATE` — and a leg may have at most one non-terminal survey (one in `REQUESTED` or `SUBMITTED`) at a time; a second request while one is open is rejected with `ERR_OPEN_SURVEY_EXISTS`. The new survey starts with its `survey_status` at `REQUESTED`. Requesting a survey on a `BLOCKED` leg re-opens it for clearance: the leg returns to `DETERMINED`, its `clearance_verdict` is reset to `UNKNOWN`, and its `survey_min_clearance_inches` is reset to null.

The surveyor then submits field findings on a `REQUESTED` survey — a survey in any other status is rejected with `ERR_SURVEY_INVALID_STATE` — carrying `surveyed_min_clearance_inches` (zero or greater) and an optional `obstructions` array. Submission moves the survey to `SUBMITTED`, stamps `submitted_at`, and creates one append-only Obstruction row per element of `obstructions`, each recording the `survey_id` of its survey, a `milepost` along the leg (zero or greater), an `obstruction_type` of `BRIDGE`, `WIRE`, `SIGN`, or `OTHER`, a `measured_clearance_inches` (zero or greater), and a `disposition` of `PASSABLE`, `PASSABLE_WITH_POLE`, or `REQUIRES_REROUTE`. The leg immediately mirrors the submitted figure: its `survey_min_clearance_inches` is set to the surveyed value on a provisional basis while the decision is pending, and the verdict stays `UNKNOWN`. A survey's `submitted_at` remains null until submission, and its `decided_at`, `decided_by_user_id`, and `rejection_reason` remain null until a decision is made — with `rejection_reason` staying null whenever the outcome is an acceptance.

Deciding a survey belongs to a `SafetyManager`, acting on a `SUBMITTED` survey (else `ERR_SURVEY_INVALID_STATE`) under the optimistic concurrency rule of §2.9 — the request must carry `expected_leg_version` matching the leg's current `version`, else it is rejected with `ERR_STALE_LEG_VERSION` — and carrying an `outcome` of `ACCEPTED` or `REJECTED`. A rejection additionally requires a `rejection_reason`, and its absence is rejected with `ERR_INVALID_REQUEST`; the decision records `decided_at`, `decided_by_user_id`, and the reason, and the survey moves to the terminal `REJECTED` status. An acceptance records `decided_at` and `decided_by_user_id`, moves the survey to `ACCEPTED`, and immediately moves any previously `ACCEPTED` survey on the same leg to the terminal `SUPERSEDED` status — the supersede chain guarantees at most one accepted survey per leg. Either decision increments both the survey's `version` and the leg's `version`.

Acceptance computes the leg's `clearance_verdict` from the field measurement. The required clearance is the job's `height_inches` plus a six-inch buffer; the verdict is `PASS` when the accepted survey's `surveyed_min_clearance_inches` is at least the required clearance — equality passes — and `FAIL` otherwise, and the leg's `survey_min_clearance_inches` is set to the accepted value. Before any survey is accepted, the verdict remains `UNKNOWN`; the map-database `map_min_clearance_inches` supports only an advisory estimate against the same required clearance and never blocks the leg, so a surveyed `FAIL` can legitimately contradict the map estimate for identical job dimensions. A `FAIL` verdict moves the leg from `DETERMINED` or `CLEARED` to `BLOCKED`, and if the leg had been cleared, the owning job is demoted: a `CLEARED` job falls back to `BOOKED`, and a `SCHEDULED` job unwinds through `CLEARED` to `BOOKED`, with its assignments retained. A `PASS` verdict moves the leg from `DETERMINED` or `BLOCKED` to `CLEARED` — provided the leg's remaining gates hold: an `ISSUED` permit exists for the leg, and `police_confirmed` is true whenever the leg requires a police escort.

The gates chain upward. A leg moves from `DETERMINED` to `CLEARED` exactly when an `ISSUED` permit exists for it, its `clearance_verdict` is `PASS` whenever it requires a route survey, and `police_confirmed` is true whenever it requires a police escort; the same triple is re-evaluated on every permit issuance, every survey acceptance, and every police confirmation. A job in `BOOKED` moves automatically to `CLEARED` the moment every one of its legs satisfies all three gates — every leg has an `ISSUED` permit, every leg that requires a route survey holds a `PASS` verdict from an accepted, non-superseded survey, and every leg that requires a police escort has police coordination confirmed. Conversely, any of those events in reverse — an expiring permit or a newly accepted `FAIL` verdict — blocks the affected leg and demotes the job from `CLEARED` or `SCHEDULED` back to `BOOKED` as described above.

### 3.5. Staffing the Convoy: Assignments, Selection, and Scheduling Gates

With the route clearing, a `Dispatcher` staffs every required escort position on every leg. Offering a position targets a leg in `DETERMINED` or `CLEARED` status — any other leg status is rejected with `ERR_LEG_INVALID_STATE` — and names a `position` of `FRONT` or `REAR`. The offer may name an `escort_id` explicitly or omit it to invoke the deterministic selector. Either way the new assignment starts in `OFFERED`, with `offered_at` mirroring its creation timestamp and with `accepted_at`, `activated_at`, `completed_at`, `released_at`, and `release_cause` all null; `billable_hours` and `assignment_fee_cents` remain null until the assignment completes, and `last_checkin_at` is first set at activation. Each leg tracks its assignments through the leg's assignment listing, while a global assignment listing can be filtered by `escort_id`, `leg_id`, or `assignment_status`.

The explicit path validates the named escort, in pipeline order: the escort must exist (`ERR_ESCORT_NOT_FOUND`); the leg's `state_code` must appear in the escort's `certified_state_codes`, else `ERR_ESCORT_NOT_CERTIFIED_FOR_STATE` (HTTP 422); for a `FRONT` position on a leg that requires a height pole, the escort must carry a pole — `has_height_pole` true — whose `height_pole_max_inches` is at least the job's `height_inches`, else `ERR_HEIGHT_POLE_EQUIPMENT_MISSING` (HTTP 422); and the escort's buffered availability must be free, else `ERR_ESCORT_WINDOW_CONFLICT`. Separately, each position is quota-limited: if the number of non-terminal assignments — those in `OFFERED`, `ACCEPTED`, or `ACTIVE` — already covering that position on the leg has reached the required count (`required_front_escorts` for `FRONT`, `required_rear_escorts` for `REAR`), the offer is rejected with `ERR_POSITION_QUOTA_FILLED`.

The availability rule applies a 60-minute deadhead buffer to both ends of every job window. The candidate escort's window for this job runs from 60 minutes before `window_start_at` to 60 minutes after `window_end_at`, and it conflicts with any of the escort's other assignments in `ACCEPTED` or `ACTIVE` whose own job windows, expanded by the same 60 minutes on both ends, strictly intersect it. Intervals that merely touch after expansion do not conflict: two jobs whose unbuffered windows are exactly 120 minutes apart do not conflict, while windows 119 minutes apart do. The identical check runs at three moments: when an explicit offer is created, when an escort accepts an offer, and as an eligibility filter inside the selector.

When `escort_id` is omitted, the selector builds its candidate pool from all escorts satisfying every eligibility condition — `escort_status` `ACTIVE`, the leg's `state_code` present in `certified_state_codes`, and, for a `FRONT` position on a pole-requiring leg, a carried height pole whose `height_pole_max_inches` reaches the job's `height_inches` — and free of buffered-window conflicts against the escort's `ACCEPTED` and `ACTIVE` assignments. Eligible escorts are ranked by `reliability_score` descending, with ties broken by earlier `created_at`; the escort `id` is never consulted as a tiebreaker. The top-ranked escort receives the offer; an empty pool is rejected with `ERR_NO_ELIGIBLE_ESCORT` (HTTP 422).

An offer is answered by the assigned escort acting as an `EscortOperator` whose `X-User-ID` matches the assignment's `escort_id` — anyone else is rejected with `ERR_NOT_RESOURCE_OWNER`. Acceptance requires the assignment to be `OFFERED` (else `ERR_ASSIGNMENT_INVALID_STATE`), the escort to be `ACTIVE` (else `ERR_ESCORT_INVALID_STATE`), the leg's job to be in `BOOKED`, `CLEARED`, or `SCHEDULED` (else `ERR_JOB_INVALID_STATE`), and the buffered-window check to pass against the escort's other `ACCEPTED` and `ACTIVE` assignments (else `ERR_ESCORT_WINDOW_CONFLICT`). A successful acceptance moves the assignment to `ACCEPTED`, stamps `accepted_at`, and increments the escort's `active_assignment_count`. Declining requires only the `OFFERED` state and moves the assignment to the terminal `DECLINED`; an offer-then-decline pair leaves the escort's `active_assignment_count` unchanged — the count is conserved.

A `Dispatcher` may release an assignment in `OFFERED` or `ACCEPTED` — any other status is rejected with `ERR_ASSIGNMENT_INVALID_STATE` — moving it to the terminal `RELEASED` with `released_at` stamped and a `release_cause` of `DISPATCHER`. Releases also fire from cascades: a cancelled job releases its assignments with cause `JOB_CANCELLED`, and a suspension releases them with cause `ESCORT_SUSPENDED`. Releasing an assignment that was `ACCEPTED` decrements the escort's `active_assignment_count`, so an accept-then-release pair conserves the count just as offer-then-decline does. If a release leaves a `SCHEDULED` job with a required position uncovered, the job is demoted to `CLEARED` in the same operation.

Scheduling is the last gate before movement. A `Dispatcher` schedules a job in `CLEARED` status — anything else is rejected with `ERR_JOB_INVALID_STATE` — and three checks then run in order. First, permit coverage: for every leg, some `ISSUED` permit must fully cover the planned traversal — `valid_from` no later than the leg's `planned_entry_at` and `valid_until` no earlier than its `planned_exit_at` — and no entry of that permit's `holiday_closure_dates` may fall on any UTC calendar date the traversal touches; any leg failing coverage rejects the schedule with `ERR_PERMIT_WINDOW_INSUFFICIENT`. Second, curfew compliance: each leg's traversal interval, treated as half-open from `planned_entry_at` up to but not including `planned_exit_at`, must not intersect any of its state's daily curfew windows on any traversed UTC date; an intersection rejects the schedule with `ERR_CURFEW_WINDOW_VIOLATION`. The curfew windows, in UTC, are: Texas 07:00 to 09:00 and 16:00 to 18:30; Oklahoma 07:00 to 09:00 and 16:30 to 18:30; Kansas 06:30 to 08:30 and 16:00 to 18:00; Louisiana 06:30 to 09:00 and 15:30 to 18:00. Because both intervals are half-open, a `planned_entry_at` exactly at a curfew's end, or a `planned_exit_at` exactly at a curfew's start, is permitted. Third, completeness: every required escort position on every leg must be covered by an `ACCEPTED` assignment, else the schedule is rejected with `ERR_ASSIGNMENTS_INCOMPLETE`. A clean run moves the job to `SCHEDULED`.

### 3.6. Running the Movement: Departure, Communication, Holds, Delivery, and Cancellation

A `Dispatcher` departs a `SCHEDULED` job — any other status is rejected with `ERR_JOB_INVALID_STATE`. Departure may occur no earlier than 30 minutes before the job's `window_start_at`; an earlier attempt exceeds the grace allowance and is rejected with `ERR_INVALID_REQUEST`, while a departure exactly 30 minutes early is permitted. Departure moves the job to `EN_ROUTE`, stamps `departed_at`, and activates the convoy: every `ACCEPTED` assignment on the job's legs moves to `ACTIVE`, with `activated_at` and `last_checkin_at` both set to the departure time — the initial staging check-in is recorded automatically.

While a job is underway, the communication protocol keeps every escort position audible. The assigned `EscortOperator` records a position check-in on its own assignment — ownership is enforced per §2.1 — and a check-in is allowed while the assignment is `ACCEPTED` or `ACTIVE`; at any other status it is rejected with `ERR_ASSIGNMENT_INVALID_STATE`. Each check-in sets the assignment's `last_checkin_at` to the current time.

Weather, curfews, and carrier problems interrupt movement without ending it. A `Dispatcher` places an `EN_ROUTE` job on hold, moving it to `ON_HOLD`, and later resumes an `ON_HOLD` job, returning it to `EN_ROUTE`; each action rejects any other source status with `ERR_JOB_INVALID_STATE`. The hold–resume loop may repeat as often as operations require.

Delivery closes the movement. A `Dispatcher` delivers an `EN_ROUTE` job — any other status is rejected with `ERR_JOB_INVALID_STATE` — but only while the communication protocol is current: if any `ACTIVE` assignment's `last_checkin_at` is more than 90 minutes before the current time, the delivery is rejected with `ERR_COMMS_CHECKIN_OVERDUE`. A clean delivery moves the job to `DELIVERED`, stamps `delivered_at`, and settles the field resources. Every `ACTIVE` assignment moves to `COMPLETED` with `completed_at` stamped and final billing applied: the elapsed time between `activated_at` and `completed_at` is measured in whole minutes and rounded up to the next whole 30-minute increment; the result, expressed in hours with thirty minutes counting as half an hour, becomes the assignment's `billable_hours`, subject to a floor of four billable hours per assignment; and the `assignment_fee_cents` is the billable hours multiplied by the hourly rate of 9,000 cents. The rounding to 30-minute increments happens before the four-hour floor is applied. Each completing assignment decrements its escort's `active_assignment_count`. Every leg still in `CLEARED` moves to `COMPLETED` in the same operation.

Cancellation is the other way a job ends, and either the owning `CarrierRep` or a `Dispatcher` may invoke it, with an optional `reason`. A job in `DELIVERED`, `CLOSED`, or `CANCELLED` cannot be cancelled, and neither can a job that already has an invoice in `FINALIZED`, `DISPUTED`, or `PAID`; both violations are rejected with `ERR_JOB_INVALID_STATE`. Cancellation stamps `cancelled_at`, moves the job to `CANCELLED`, and computes the cancellation fee from the job's status immediately before cancellation: a job cancelled from `DRAFT` or `QUOTED` takes tier `NONE` at 0 percent; from `BOOKED` or `CLEARED`, tier `TIER_10` at 10 percent; from `SCHEDULED`, tier `TIER_25` at 25 percent; from `EN_ROUTE` or `ON_HOLD`, tier `TIER_50` at 50 percent. The tier is recorded in `cancel_fee_tier`, and `cancel_fee_cents` is the job's `quoted_cents` multiplied by the tier percentage, rounded half up to a whole cent — or 0 when the job was never quoted and `quoted_cents` is null. Cancellation then releases the field: every assignment in `OFFERED`, `ACCEPTED`, or `ACTIVE` moves to `RELEASED` with `release_cause` `JOB_CANCELLED`, with the escort's `active_assignment_count` decremented for each released `ACCEPTED` or `ACTIVE` assignment, and every leg in `PENDING`, `DETERMINED`, `CLEARED`, or `BLOCKED` moves to `CANCELLED`. Finally, the quoted hold is released: the job leaves the outstanding set of §2.10, so a book-then-cancel pair conserves the carrier's `credit_available_cents` exactly.

### 3.7. Standby Events, Incidents, and Escort Reliability

Standby time is money, but only some of it. A `Dispatcher` or an `EscortOperator` opens a delay event on a job in `EN_ROUTE` or `ON_HOLD` — any other job status is rejected with `ERR_JOB_INVALID_STATE` — and a job may have at most one `OPEN` delay event at a time; a second open attempt is rejected with `ERR_OPEN_DELAY_EVENT_EXISTS`. The event records a `cause` and a `started_at` that must not be later than the current time at creation. Seven causes are recognized, split into two families: the billable causes `CARRIER_DELAY`, `MECHANICAL_BREAKDOWN`, and `DOCUMENTATION_ISSUE`, and the non-billable causes `WEATHER`, `CURFEW_HOLD`, `POLICE_DIRECTED`, and `ROAD_CLOSURE`. The event starts with its `delay_status` at `OPEN`, and while it remains open its `ended_at`, `raw_minutes`, `billable_minutes`, and `standby_amount_cents` are all null.

Either role closes an `OPEN` event — a closed one rejects further closure with `ERR_DELAY_EVENT_INVALID_STATE`. Closing stamps `ended_at` with the current time, computes `raw_minutes` as the whole minutes between `started_at` and `ended_at`, and bills standby per event. For a non-billable cause, `billable_minutes` is 0. For a billable cause, the first 30 minutes are free: the chargeable time is `raw_minutes` minus 30, never less than zero — a 30-minute delay is exactly free — and that chargeable remainder is rounded up to the next whole 15-minute increment to produce `billable_minutes`. The event's `standby_amount_cents` is the billable minutes divided by 60, multiplied by the standby rate of 7,500 cents per hour, multiplied by the job's `total_escort_positions` at close time; because billable minutes are always a multiple of 15, the amount is always a whole number of cents. Rounding is pinned per event: each closed event rounds its own minutes, and invoice composition later sums the per-event amounts, never the raw minutes.

Incidents follow their own adversarial workflow. A `CarrierRep`, a `Dispatcher`, or an `EscortOperator` reports an incident on a job in `EN_ROUTE`, `ON_HOLD`, or `DELIVERED` — any other status is rejected with `ERR_JOB_INVALID_STATE` — supplying an `incident_type` of `CARGO_DAMAGE`, `PROPERTY_DAMAGE`, `TRAFFIC_VIOLATION`, `INJURY`, or `EQUIPMENT_DAMAGE`, a free-text `description`, a `claimed_amount_cents` of zero or greater, and an optional `assignment_id` tying the incident to a specific escort assignment. When present, `assignment_id` must reference an existing assignment (`ERR_ASSIGNMENT_NOT_FOUND`) on a leg of this job, else the report is rejected with `ERR_INVALID_REQUEST`; its presence is what drives reliability penalties at settlement. The report is stamped with the caller's `reporter_role` and `reporter_user_id` and starts with its `incident_status` at `REPORTED`; until the first assessment, `assessed_amount_cents`, `escort_share_cents`, and `assessed_by_user_id` are null, and `settled_at` is null until settlement.

Assessment belongs to a `SafetyManager` or a `Dispatcher`, but never to the reporter: segregation of duties requires the assessor's `X-User-ID` to differ from the incident's `reporter_user_id`, and a violation is rejected with `ERR_SEGREGATION_OF_DUTIES`. Assessment is permitted from `REPORTED` or `DISPUTED` — any other status is rejected with `ERR_INCIDENT_INVALID_STATE` — and takes an `escort_fault_share_pct` between 0 and 100 inclusive. The assessment computes two amounts: `assessed_amount_cents` is the lesser of the claimed amount and a liability cap of 25,000,000 cents; and `escort_share_cents` is the assessed amount multiplied by the fault-share percentage and divided by 100, rounded half up to a whole cent, then reduced by the 50,000-cent escort deductible, with the result floored at zero. The assessor is stamped as `assessed_by_user_id`, and the incident moves to `ASSESSED`. Re-assessment after a dispute recomputes both amounts from the newly supplied fault share and replaces the prior figures entirely — the latest assessment wins.

The owning `CarrierRep` disputes an `ASSESSED` incident, optionally with a `reason`, moving it to `DISPUTED`; any other status is rejected with `ERR_INCIDENT_INVALID_STATE`. A `DISPUTED` incident cannot be settled directly — settlement is permitted only from `ASSESSED`, and the attempt is rejected with `ERR_INCIDENT_INVALID_STATE` — so a disputed incident must first be re-assessed, looping back through `ASSESSED` before it can close.

Settlement belongs to a `FinanceManager`. Settling stamps `settled_at`, moves the incident to the terminal `SETTLED` status, and makes the incident's `escort_share_cents` a chargeback line consumable by invoice composition in §3.8. When the settled incident carries an `assignment_id`, settlement additionally penalizes the referenced escort: a fault share of at least 50 percent subtracts 35 points from the escort's `reliability_score`; a fault share between 1 and 49 percent inclusive subtracts 10 points; a fault share of 0 subtracts nothing. The score is clamped between 0 and 100. If the penalized score falls below 40, the escort is automatically moved to `SUSPENDED`, and the full suspension cascade of §3.1 follows in the same operation: the escort's `ACCEPTED` assignments are released with `release_cause` `ESCORT_SUSPENDED` and the count decremented per release, and any `SCHEDULED` job losing a required position is demoted to `CLEARED`.

### 3.8. Invoicing, Disputes, and Settlement

Billing begins once a job has ended. A `BillingClerk` generates an invoice for a job in `DELIVERED` or `CANCELLED` status — any other status is rejected with `ERR_JOB_INVALID_STATE` — subject to two further guards: the job must not already have a non-terminal invoice, meaning one in `DRAFT`, `FINALIZED`, or `DISPUTED`, else the generation is rejected with `ERR_ACTIVE_INVOICE_EXISTS`; and a `CANCELLED` job whose `cancel_fee_cents` is 0 and which has no `COMPLETED` assignments has nothing to bill, so generation is rejected with `ERR_INVALID_REQUEST`. The generator's identity is stamped as `generated_by_user_id`, and the invoice starts with its `invoice_status` at `DRAFT` and `adjustment_delta_cents` at 0; `finalized_at`, `dispute_reason`, `adjustment_note`, and `paid_at` remain null until the invoice is finalized, disputed, adjusted, and paid respectively.

Invoice composition follows a pinned evaluation order, and the same composition runs at generation and again at finalization. First, `base_charges_cents` is the sum of `assignment_fee_cents` over the job's `COMPLETED` assignments. Second, `equipment_charges_cents` sums, over all legs of the job, 15,000 cents per leg requiring a height pole, 40,000 cents per leg requiring a police escort, and 25,000 cents per leg requiring a route survey. Third, `standby_total_cents` is the sum of `standby_amount_cents` over the job's `CLOSED` delay events. Fourth, `subtotal_cents` is the sum of base, equipment, and standby. Fifth, the volume discount: the tier basis is the carrier's `ytd_billed_cents` plus this invoice's subtotal; when the basis is at least 500,000 cents the discount rate is 5 percent, otherwise when it is at least 100,000 cents the rate is 2 percent, otherwise 0 percent, and `volume_discount_cents` is the subtotal multiplied by that rate, rounded half up to a whole cent. Sixth, `fuel_surcharge_cents` is 7 percent of the sum of base and equipment charges — the pre-discount basis, and never including standby — rounded half up to a whole cent, even though the surcharge is added to the total after the discount is subtracted. Seventh, `cancellation_fee_cents` carries the job's `cancel_fee_cents`, which is 0 for delivered jobs. Eighth, `incident_chargebacks_cents` is the sum of `escort_share_cents` over the job's `SETTLED` incidents — evaluated as of finalization for the finalize re-run. Ninth, `total_cents` is the subtotal minus the volume discount, plus the fuel surcharge, plus the cancellation fee, minus the incident chargebacks, plus the accumulated `adjustment_delta_cents`; the total must never fall below zero.

Finalization is the checker to the generator's maker: a `BillingClerk` finalizes an invoice in `DRAFT` — any other status is rejected with `ERR_INVOICE_INVALID_STATE` — but the finalizer's `X-User-ID` must differ from the invoice's `generated_by_user_id`, else the request is rejected with `ERR_SEGREGATION_OF_DUTIES`. Finalization re-runs the full composition so that `incident_chargebacks_cents` reflects any incidents settled since generation, recomputes every monetary field and the total, stamps `finalized_at`, and moves the invoice to `FINALIZED`.

The owning `CarrierRep` disputes a `FINALIZED` invoice — any other status is rejected with `ERR_INVOICE_INVALID_STATE` — supplying a `dispute_reason`, which is recorded as the invoice moves to `DISPUTED`. Resolution comes through adjustment: a `BillingClerk` adjusts a `DISPUTED` invoice, again under segregation of duties against `generated_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`), supplying a signed `adjustment_delta_cents` and a required `adjustment_note`. The delta accumulates onto the running `adjustment_delta_cents` — the only way that field ever changes — the composition recomputes `total_cents`, and the resulting total must remain at least zero; an adjustment that would drive it below zero is rejected with `ERR_ADJUSTMENT_EXCEEDS_TOTAL`. A successful adjustment returns the invoice to `FINALIZED` and refreshes `finalized_at`, and the finalize–dispute–adjust loop may repeat: `FINALIZED` to `DISPUTED` and back to `FINALIZED` as many times as the parties require.

Collection closes both the invoice and the job. A `FinanceManager` records payment of a `FINALIZED` invoice — any other status is rejected with `ERR_INVOICE_INVALID_STATE` — and the paid `amount_cents` must equal the invoice's `total_cents` exactly; any other amount is rejected with `ERR_PAYMENT_AMOUNT_MISMATCH`. Payment stamps `paid_at`, moves the invoice to the terminal `PAID` status, adds the invoice's `total_cents` to the carrier's `ytd_billed_cents` (feeding future volume-discount tiers), removes the invoice from the outstanding set of §2.10 so the carrier's `credit_available_cents` is recomputed, and, when the underlying job is `DELIVERED`, closes the job by moving it to `CLOSED`. Alternatively, a `FinanceManager` writes off a `FINALIZED` invoice as bad debt, optionally with a `reason`: the invoice moves to the terminal `WRITTEN_OFF` status, leaves the outstanding set so availability is recomputed — but credits nothing to `ytd_billed_cents` — and likewise closes a `DELIVERED` job. Both `PAID` and `WRITTEN_OFF` are terminal, and a job's path from `DELIVERED` to `CLOSED` always passes through one of them.

## 4. Endpoint Definitions

Operations that create a new resource — registering a carrier or escort, booking a job, recording a permit application, requesting a route survey, offering an assignment, recording a check-in, opening a delay event, reporting an incident, or generating an invoice — return `201 Created`. Operations that modify or transition an existing resource return `200 OK`. The table below summarizes the HTTP contract; request payloads, response shapes, and side effects are defined by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the server's logical clock; sweeps time-dependent state | Dispatcher |
| POST | `/carriers` | Register a carrier customer | Dispatcher |
| GET | `/carriers` | List carriers (paginated) | All roles |
| GET | `/carriers/{id}` | Get one carrier including computed credit availability | All roles |
| POST | `/escorts` | Register a certified pilot car escort | Dispatcher |
| GET | `/escorts` | List escorts with filters (paginated) | All roles |
| POST | `/escorts/{id}/suspend` | Suspend an escort; cascades release of accepted assignments | SafetyManager |
| POST | `/escorts/{id}/reinstate` | Reinstate a suspended escort (reliability score unchanged) | SafetyManager |
| POST | `/jobs` | Book an oversize-load escort job with dimensions and route legs | CarrierRep |
| GET | `/jobs` | List jobs with filters (paginated) | All roles |
| GET | `/jobs/{id}` | Get one job | All roles |
| POST | `/jobs/{id}/amendments` | Amend job fields; OCC-guarded; reverts quoted jobs to draft | CarrierRep, Dispatcher |
| POST | `/jobs/{id}/quote` | Determine per-leg escort requirements and compute the provisional quote | Dispatcher |
| POST | `/jobs/{id}/accept-quote` | Carrier accepts the quote; places the credit hold | CarrierRep |
| POST | `/jobs/{id}/schedule` | Schedule a cleared job after permit-window, curfew, and completeness validation | Dispatcher |
| POST | `/jobs/{id}/depart` | Depart a scheduled job; activates all accepted assignments | Dispatcher |
| POST | `/jobs/{id}/hold` | Place an en-route job on hold | Dispatcher |
| POST | `/jobs/{id}/resume` | Resume an on-hold job | Dispatcher |
| POST | `/jobs/{id}/deliver` | Deliver an en-route job; enforces the communication protocol; completes assignments and legs | Dispatcher |
| POST | `/jobs/{id}/cancel` | Cancel a non-delivered job; tiered cancellation fee; releases assignments and the credit hold | CarrierRep, Dispatcher |
| GET | `/jobs/{id}/legs` | List legs of a job in route order | All roles |
| GET | `/legs/{id}` | Get one leg (requirements, gates, clearance verdict) | All roles |
| POST | `/legs/{id}/confirm-police` | Confirm police escort coordination for a leg that requires it | Dispatcher |
| POST | `/legs/{id}/permits` | Record a state oversize permit application for a leg | Dispatcher |
| GET | `/legs/{id}/permits` | List permits of a leg | All roles |
| POST | `/permits/{id}/issue` | Mark a permit issued by the state | Dispatcher |
| POST | `/legs/{id}/route-surveys` | Request a route survey for a leg (re-opens a blocked leg) | RouteSurveyor |
| GET | `/legs/{id}/route-surveys` | List surveys of a leg | All roles |
| GET | `/route-surveys/{id}` | Get one survey | All roles |
| POST | `/route-surveys/{id}/submit` | Submit field findings and obstructions for a requested survey | RouteSurveyor |
| POST | `/route-surveys/{id}/accept` | SafetyManager decision on a submitted survey; OCC-guarded on the leg; supersedes the previously accepted survey | SafetyManager |
| GET | `/route-surveys/{id}/obstructions` | List obstructions recorded by a survey | All roles |
| POST | `/legs/{id}/assignments` | Offer an escort position on a leg; omitted escort id invokes the deterministic selector | Dispatcher |
| GET | `/legs/{id}/assignments` | List assignments of a leg | All roles |
| GET | `/assignments/{id}` | Get one assignment | All roles |
| GET | `/assignments` | List assignments with filters (paginated) | All roles |
| POST | `/assignments/{id}/accept` | Escort accepts an offered assignment | EscortOperator |
| POST | `/assignments/{id}/decline` | Escort declines an offered assignment | EscortOperator |
| POST | `/assignments/{id}/release` | Dispatcher releases an offered or accepted assignment | Dispatcher |
| POST | `/assignments/{id}/check-ins` | Record a driver/escort position check-in (communication protocol) | EscortOperator |
| POST | `/jobs/{id}/delay-events` | Open a delay/standby event on an in-progress job | Dispatcher, EscortOperator |
| GET | `/jobs/{id}/delay-events` | List delay events of a job | All roles |
| POST | `/delay-events/{id}/close` | Close an open delay event; computes standby billing with per-event rounding | Dispatcher, EscortOperator |
| POST | `/jobs/{id}/incidents` | Report an incident on a job (optionally tied to an escort assignment) | CarrierRep, Dispatcher, EscortOperator |
| GET | `/jobs/{id}/incidents` | List incidents of a job | All roles |
| GET | `/incidents/{id}` | Get one incident | All roles |
| GET | `/incidents` | List incidents with filters (paginated) | All roles |
| POST | `/incidents/{id}/assess` | Assess liability share (initial or re-assessment after dispute); segregation of duties versus reporter | SafetyManager, Dispatcher |
| POST | `/incidents/{id}/dispute` | Carrier disputes an assessed incident | CarrierRep |
| POST | `/incidents/{id}/settle` | Settle an assessed incident; applies chargeback and reliability penalty cascade | FinanceManager |
| POST | `/jobs/{id}/invoices` | Generate a draft invoice for a delivered or cancelled job | BillingClerk |
| GET | `/jobs/{id}/invoices` | List invoices of a job | All roles |
| GET | `/invoices/{id}` | Get one invoice | All roles |
| POST | `/invoices/{id}/finalize` | Finalize a draft invoice (maker-checker); recomputes chargebacks and totals | BillingClerk |
| POST | `/invoices/{id}/dispute` | Carrier disputes a finalized invoice | CarrierRep |
| POST | `/invoices/{id}/adjust` | Adjust a disputed invoice back to finalized with a signed delta | BillingClerk |
| POST | `/invoices/{id}/record-payment` | Record exact full payment of a finalized invoice | FinanceManager |
| POST | `/invoices/{id}/write-off` | Write off a finalized invoice as bad debt | FinanceManager |

## 5. Error Code Catalogue

Trigger conditions for every error below are defined in the narratives of §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_USER_CONTEXT` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_ENUM_VALUE` | 400 Bad Request |
| `ERR_CARRIER_NOT_FOUND` | 404 Not Found |
| `ERR_ESCORT_NOT_FOUND` | 404 Not Found |
| `ERR_JOB_NOT_FOUND` | 404 Not Found |
| `ERR_LEG_NOT_FOUND` | 404 Not Found |
| `ERR_PERMIT_NOT_FOUND` | 404 Not Found |
| `ERR_SURVEY_NOT_FOUND` | 404 Not Found |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_DELAY_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_INCIDENT_NOT_FOUND` | 404 Not Found |
| `ERR_INVOICE_NOT_FOUND` | 404 Not Found |
| `ERR_JOB_INVALID_STATE` | 409 Conflict |
| `ERR_LEG_INVALID_STATE` | 409 Conflict |
| `ERR_PERMIT_INVALID_STATE` | 409 Conflict |
| `ERR_SURVEY_INVALID_STATE` | 409 Conflict |
| `ERR_ASSIGNMENT_INVALID_STATE` | 409 Conflict |
| `ERR_DELAY_EVENT_INVALID_STATE` | 409 Conflict |
| `ERR_INCIDENT_INVALID_STATE` | 409 Conflict |
| `ERR_INVOICE_INVALID_STATE` | 409 Conflict |
| `ERR_ESCORT_INVALID_STATE` | 409 Conflict |
| `ERR_ESCORT_NOT_CERTIFIED_FOR_STATE` | 422 Unprocessable Entity |
| `ERR_HEIGHT_POLE_EQUIPMENT_MISSING` | 422 Unprocessable Entity |
| `ERR_QUOTE_EXPIRED` | 409 Conflict |
| `ERR_PERMIT_WINDOW_INSUFFICIENT` | 409 Conflict |
| `ERR_CURFEW_WINDOW_VIOLATION` | 409 Conflict |
| `ERR_ESCORT_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_COMMS_CHECKIN_OVERDUE` | 409 Conflict |
| `ERR_ACTIVE_INVOICE_EXISTS` | 409 Conflict |
| `ERR_OPEN_DELAY_EVENT_EXISTS` | 409 Conflict |
| `ERR_OPEN_SURVEY_EXISTS` | 409 Conflict |
| `ERR_POSITION_QUOTA_FILLED` | 409 Conflict |
| `ERR_ASSIGNMENTS_INCOMPLETE` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_CREDIT_LIMIT_WOULD_BE_EXCEEDED` | 402 Payment Required |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_ADJUSTMENT_EXCEEDS_TOTAL` | 422 Unprocessable Entity |
| `ERR_NO_ELIGIBLE_ESCORT` | 422 Unprocessable Entity |
| `ERR_STALE_JOB_VERSION` | 412 Precondition Failed |
| `ERR_STALE_LEG_VERSION` | 412 Precondition Failed |
