# In-Home Senior Care API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the In-Home Senior Care platform, a back-office system modeled on the operating practices of non-medical home-care franchises. The platform coordinates the full span of an agency's day-to-day work: it maintains a registry of caregivers and their background-screening tiers, captures each client's care plan with its list of activities of daily living, schedules in-home visits and verifies them through electronic visit verification (EVV), pairs caregivers with clients while protecting care continuity, and turns completed work into invoices with overtime, mileage reimbursement, and long-term-care insurance reconciliation.

Two recurring tensions shape almost every rule in this system. The first is the difference between what a visit looks like the moment it ends and what it is ultimately worth on a finalized invoice: a single completed visit is priced in isolation at the agency's base rate when the caregiver clocks out, but the same hours may later be repriced with overtime once they are accumulated chronologically across a billing period. The second is the need to keep money, continuity, and insurance coverage consistent as visits are cancelled, invoices are disputed and reopened, and claims are denied and appealed. The platform is therefore a ledger-reconciliation system at heart: every clock-out, every finalize, every claim adjudication must leave the relevant totals, continuity scores, and insurance balances in a defensible state.

The intended operators are agency administrators, schedulers, field caregivers, and billing clerks. Each owns a distinct slice of the workflow, and the rules below make those boundaries explicit so that the system can be trusted as the single source of truth for scheduling, verification, and billing.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares the operational capacity under which the request is made. If either header is missing or malformed, the request is rejected with `ERR_MISSING_AUTH`. When the headers are present but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes exactly four roles: `AgencyAdmin`, `Scheduler`, `Caregiver`, and `BillingClerk`. An `AgencyAdmin` is the agency operator who manages the caregiver roster, background tiers, the client lifecycle, invoice disputes, and claim adjudication. A `Scheduler` builds care plans, proposes and activates matches, schedules visits, and records cancellations and mileage. A `Caregiver` is the field worker who performs telephony clock-in and clock-out, departs for visits, and records mileage. A `BillingClerk` handles finance: opening and finalizing invoices, marking them paid, and assigning, submitting, and appealing insurance claims.

Three of these roles are opaque operator identifiers. When `X-User-Role` is `AgencyAdmin`, `Scheduler`, or `BillingClerk`, the `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. When `X-User-Role` is `Caregiver`, by contrast, `X-User-ID` is the `id` of the acting `Caregiver` entity; ownership checks on any resource that references a `Caregiver` compare the resource's caregiver foreign key to `X-User-ID`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip from the start of the result set and defaults to 0.

Unless an endpoint states otherwise, list results are sorted by their creation timestamp in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Resource Identity, Timestamps, and Versioning

Every primary, top-level resource — agencies, caregivers, clients, care plans, care tasks, matches, visits, mileage entries, invoices, and claims — carries a system-managed `id` formatted as a UUID with no type prefix, and a `created_at` timestamp recorded in ISO 8601 UTC with three fractional digits at the moment the resource is first persisted.

All of these resources additionally carry an `updated_at` timestamp and an integer `version`. The `updated_at` field is refreshed on every mutation of the resource, and the `version` begins at the value assigned on creation and increases by one with each subsequent modification. Because derived values such as a client's continuity score or an invoice's totals are themselves mutations of the owning resource, recomputing them refreshes `updated_at` and increments `version` on that resource. Every entity in this system maintains all four common fields; there are no creation-only resources that omit `updated_at` or `version`.

### 2.5. Nested Resource Retrieval and Existence Ordering

Several resources are addressed through nested paths — care plans and care tasks under a client, tasks under a care plan, mileage under a visit. For any request that names more than one resource identifier, whether in the path or in the request body's foreign keys, the system validates existence left to right: the agency first, then the caregiver, client, or plan, and only then the visit, invoice, claim, mileage, or task. The request is rejected at the first identifier that does not resolve, and the error reflects which kind of resource was missing: `ERR_AGENCY_NOT_FOUND`, `ERR_CAREGIVER_NOT_FOUND`, `ERR_CLIENT_NOT_FOUND`, `ERR_CARE_PLAN_NOT_FOUND`, `ERR_MATCH_NOT_FOUND`, `ERR_VISIT_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, or `ERR_CLAIM_NOT_FOUND`. A care task that cannot be found under an otherwise valid plan folds into `ERR_CARE_PLAN_NOT_FOUND`, and a mileage entry that cannot be found when voiding folds into `ERR_VISIT_NOT_FOUND`. All of these existence failures carry HTTP status 404.

### 2.6. Validation Precedence

When a single request could fail several checks, the system evaluates them in a fixed order so that the returned error is deterministic. Authentication comes first: a missing or malformed credential header yields `ERR_MISSING_AUTH` before anything else is considered. Authorization is second: a recognized but unpermitted role yields `ERR_FORBIDDEN_ROLE`. Existence is third, applying the left-to-right resolution of §2.5 and returning the appropriate not-found error. Fourth is request well-formedness — required fields present, enumerated values legal, and the body-level numeric and ordering constraints described in §2.7 — failing which the request is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Fifth is the state check: the target resource must be in a state from which the requested transition is legal, otherwise a state error is returned (the generic `ERR_INVALID_STATE` or one of the state-specific variants such as `ERR_VISIT_NOT_IN_PROGRESS`, `ERR_INVOICE_NOT_DRAFT`, `ERR_INVOICE_NOT_ISSUED`, `ERR_INVOICE_NOT_DISPUTED`, or `ERR_BACKGROUND_NOT_PENDING`, all at HTTP 409). Only after these five tiers pass does the system evaluate the business-referential, temporal, fiscal, and concurrency rules attached to the specific operation. Within that final tier, the per-operation orderings stated in §3 apply.

### 2.7. Request Well-Formedness Constraints

Several constraints are checked as part of the fourth (well-formedness) tier and all surface as `ERR_INVALID_REQUEST`. A visit's `scheduled_end` must be strictly later than its `scheduled_start`. An invoice's `period_end` must be strictly later than its `period_start`. A claim's `covered_pct` must be at least 0 and at most 1. A mileage entry's `miles` must be strictly greater than 0. An unknown `action` value on any transition endpoint, or an unknown `target_tier` on a background-clearing action, is likewise an `ERR_INVALID_REQUEST`. Configuration values supplied when creating an agency are bounded as well: `base_hourly_rate` and `live_in_day_rate` must be greater than 0; `overtime_threshold_hours` and `mileage_rate` must be at least 0; `overtime_multiplier` must be at least 1; `evv_rounding_minutes` must be greater than 0; `travel_buffer_minutes` must be at least 0; and a caregiver's `max_weekly_hours` must be greater than 0.

### 2.8. Monetary Precision and Rounding

All monetary amounts — visit charges, invoice line amounts and totals, mileage line charges, insurance coverage figures, and client-responsible amounts — are carried to exactly 2 decimal places and rounded using the round-half-up method. Where a calculation specifies that rounding happens per component before the components are summed (as with mileage and with invoice labor lines), that ordering is authoritative: each component is rounded to 2 decimal places first, and the stored total is the plain sum of those already-rounded components, never a single rounding applied to the raw sum. Configuration and rate fields supplied as input preserve the precision in which they were provided.

### 2.9. Optimistic Concurrency on Claim Assignment

Assigning a long-term-care insurance claim to an invoice is guarded by optimistic concurrency on the invoice. A request that creates a claim must carry `expected_invoice_version`, and that value must equal the current `version` of the target invoice named by `invoice_id`. Because a claim assignment legitimately supersedes any prior claim attached to that invoice, a value that does not match indicates the client's view of the invoice — its total, its status, or a previously assigned claim — is out of date and the new claim would attach to a superseded financial snapshot. When `expected_invoice_version` does not equal the invoice's current `version`, the create is rejected with `ERR_STALE_INVOICE_VERSION` at HTTP 412. On a successful claim assignment the invoice's `version` is itself incremented by one, so a second assignment that reused the same observed version would then fail the check. This `expected_invoice_version` field is required only when assigning a claim; no other endpoint takes a version field, and endpoints not described here perform no version comparison.

### 2.10. The Two Billing Variants

A central design point worth stating up front is that this system computes labor charges twice, by two different algorithms, on two different entity domains. The first is the **provisional (forward) charge** computed on a single visit at clock-out: the visit is priced in isolation, with no awareness of any other visit, and every hour is billed at the agency's base hourly rate. The second is the **final (chronological) charge** computed when an invoice is finalized: the period's completed visits are walked in chronological order, hours are accumulated, and any hours beyond the weekly overtime threshold are billed at the overtime rate. The two variants deliberately diverge — the provisional charge never applies overtime, so an invoice's final labor figure is greater than or equal to the plain sum of the provisional visit charges it covers. §3 specifies each variant in full.

### 2.11. Background Screening, Continuity, and Cascades

Two of this domain's most consequential behaviors are cascades. When a caregiver is suspended or revoked, the system must end that caregiver's matches and, where those matches carried care continuity, mark continuity as broken and recompute the affected clients' continuity scores. When an invoice is disputed or reopened, or when a claim is denied, the system must unwind the insurance coverage that had been applied to that invoice and restore the client-responsible figure. These cascades are not optional side notes; they are the mechanism by which money and continuity stay consistent, and they are specified transition by transition in §3. Each entity touched by a cascade independently has its `updated_at` refreshed and its `version` incremented.

### 2.12. The Logical Clock

Because ISO-week overtime accumulation and billing-period windows depend on wall-clock time, the platform exposes an administrator-only test-driving capability that pins the server's notion of the current UTC instant to a supplied `to_iso8601` value. All week-boundary and period computations read from this logical clock. This capability performs no state-machine transition and returns no resource body.

## 3. Business Logic & Workflows

### 3.1. The Agency as Configuration Root

Everything in the system hangs off an **Agency**, the configuration root that holds the rates and thresholds the rest of the platform reads. An `AgencyAdmin` creates an agency with its legal `name`, a `base_hourly_rate` (the default hourly bill rate, in USD), and a `live_in_day_rate` (the flat per-day rate billed for live-in clients). Several further settings may be supplied and otherwise take documented defaults: `overtime_threshold_hours`, the weekly billable-hours threshold above which overtime applies, defaults to 40; `overtime_multiplier`, the factor applied to the base hourly rate for overtime hours, defaults to 1.5; `mileage_rate`, the reimbursement per mile in USD, defaults to 0.70; `evv_rounding_minutes`, the increment to which verified durations are rounded, defaults to 15; and `travel_buffer_minutes`, the travel cushion added on each side of a client's visit interval for overlap detection, defaults to 30. These configuration values flow into the visit, mileage, and invoice calculations described later.

### 3.2. The Caregiver: Two Independent Lifecycles

A **Caregiver** record is registered by an `AgencyAdmin` with the owning `agency_id`, the worker's `full_name`, and a `hire_state_code` (the two-letter US state of registration). An optional `max_weekly_hours` caps how many billable hours may be scheduled for that caregiver within any one ISO week and defaults to 50. A newly registered caregiver always begins with `background_tier` of `PENDING` and `employment_status` of `APPLICANT`.

These two dimensions evolve independently. The `background_tier` reflects screening — `PENDING`, then one of `TIER_1`, `TIER_2`, or `TIER_3` once cleared, or `REVOKED` — while `employment_status` reflects employment standing: `APPLICANT`, `ACTIVE`, `SUSPENDED`, or `TERMINATED`. An `AgencyAdmin` advances both through a single lifecycle action endpoint that takes an `action` and, for background clearance, a `target_tier`.

Clearing background screening (`action` of `CLEAR_BACKGROUND`) requires that the caregiver's `background_tier` is currently `PENDING`; if it is not, the request is rejected with `ERR_BACKGROUND_NOT_PENDING`. The supplied `target_tier` must be one of `TIER_1`, `TIER_2`, or `TIER_3`, and anything else is an `ERR_INVALID_REQUEST`. On success the `background_tier` is set to the requested tier. This action does not touch the employment dimension.

Activation (`action` of `ACTIVATE`) is the cross-dimension guard: it succeeds only when `background_tier` is one of `TIER_1`, `TIER_2`, or `TIER_3`, otherwise it is rejected with `ERR_BACKGROUND_NOT_CLEARED`. Activation applies whether the caregiver is being brought up from `APPLICANT` or restored from `SUSPENDED`; in either case the prior `employment_status` must be `APPLICANT` or `SUSPENDED` respectively, and an activation attempted from any other employment state is rejected with `ERR_INVALID_STATE`. On success `employment_status` becomes `ACTIVE`. The `SUSPENDED → ACTIVE` path is a genuine cycle: a suspended caregiver who is reactivated returns to full standing.

Suspension (`action` of `SUSPEND`) requires the caregiver's `employment_status` to be `ACTIVE`, otherwise `ERR_INVALID_STATE`. On success `employment_status` becomes `SUSPENDED`, and a cascade fires: every match for this caregiver that is currently `ACTIVE` has its `match_status` set to `ENDED`, and for any such match that was the client's primary match with a `continuity_status` of `PREFERRED`, that match's `continuity_status` is set to `BROKEN` and the affected client's `continuity_score` is recomputed.

Revocation (`action` of `REVOKE`) requires only that `background_tier` is not already `REVOKED`, otherwise `ERR_INVALID_STATE`. Revocation is terminal on both dimensions at once: `background_tier` becomes `REVOKED` and `employment_status` becomes `TERMINATED`. A wider cascade fires here — every match for this caregiver in `PROPOSED` or `ACTIVE` has its `match_status` set to `ENDED`, and again every primary match that held `PREFERRED` continuity is set to `BROKEN` with the affected client's `continuity_score` recomputed. The states `TERMINATED` and `REVOKED` are terminal; no further lifecycle action is accepted.

### 3.3. The Client and the Care Plan

A **Client** is created by an `AgencyAdmin` or a `Scheduler` with the owning `agency_id`, the person's `full_name`, and a `residence_state_code`. A `requires_live_in` flag, defaulting to false, marks clients who are typically billed at the flat live-in daily rate rather than hourly. A client opens in `INTAKE` status with a `continuity_score` of 0. The status field moves through `INTAKE`, `ACTIVE`, `ON_HOLD`, and `DISCHARGED` via a client lifecycle action endpoint: `ACTIVATE` brings an `INTAKE` client to `ACTIVE`, `HOLD` moves an `ACTIVE` client to `ON_HOLD`, `RESUME` returns an `ON_HOLD` client to `ACTIVE`, and `DISCHARGE` retires the client to `DISCHARGED`. An action requested from an incompatible status is rejected with `ERR_INVALID_STATE`. The client's status gates downstream work: a match may be activated only for a client in `INTAKE` or `ACTIVE`, and a visit may be clocked in only for an `ACTIVE` client.

Care is organized through a **CarePlan**, a sub-resource of a client created with a `title`. Each plan records the owning `client_id`, opens in `DRAFT` status, and tracks a `task_count` that begins at 0. A plan's `status` moves through `DRAFT`, `PUBLISHED`, and `RETIRED`: a `Scheduler` or `AgencyAdmin` publishes a draft plan (advancing `DRAFT → PUBLISHED`) and may later retire a published plan (`PUBLISHED → RETIRED`); an action from an incompatible status is an `ERR_INVALID_STATE`. The publish gate matters because a visit may only be clocked in against a plan whose `status` is `PUBLISHED`.

Within a plan, a **CareTask** captures one activity. It is added with a `category` of either `ADL` (an activity of daily living) or `IADL` (an instrumental activity of daily living), a `name` such as "Bathing assistance" or "Grocery errand", and an optional `requires_companion_errand` flag, defaulting to false, that marks tasks involving an errand trip which may later accrue mileage. Each task records its owning `care_plan_id` and opens with a `status` of `ACTIVE`. Adding a task increments the parent plan's `task_count`. Removing a task sets its `status` to `REMOVED` and decrements the parent's `task_count`; the `task_count` is, by definition, the number of non-`REMOVED` tasks on the plan, so removed tasks are excluded from it.

### 3.4. Matching Caregivers to Clients and Protecting Continuity

A **CaregiverMatch** is the junction that pairs a caregiver with a client. A `Scheduler` or `AgencyAdmin` proposes a match with a `caregiver_id`, a `client_id`, and an optional `is_primary` flag, defaulting to false, that designates the client's primary continuity caregiver. A new match opens with a `match_status` of `PROPOSED` and a `continuity_status` of `STANDARD`. These two dimensions, like the caregiver's, evolve in parallel: `match_status` runs `PROPOSED`, `ACTIVE`, `ENDED`, while `continuity_status` runs `STANDARD`, `PREFERRED`, `BROKEN`.

Activating a match (`action` of `ACTIVATE`) is the most heavily guarded operation in the matching workflow, and its preconditions are evaluated in the following order. First, the referenced caregiver's `employment_status` must be `ACTIVE`, otherwise `ERR_CAREGIVER_NOT_ACTIVE`. Second, that caregiver's `background_tier` must be one of `TIER_1`, `TIER_2`, or `TIER_3`, otherwise `ERR_BACKGROUND_NOT_CLEARED`. Third, the client's `status` must be `INTAKE` or `ACTIVE`, otherwise `ERR_CLIENT_NOT_SCHEDULABLE`. Fourth, no other `ACTIVE` match may already exist for this same `caregiver_id` and `client_id` pair, otherwise `ERR_DUPLICATE_ACTIVE_MATCH`. When all four hold, `match_status` becomes `ACTIVE`. If the match was proposed as primary, its `continuity_status` is set to `PREFERRED` and any other match for the same `client_id` that currently holds `PREFERRED` is demoted to `STANDARD`, so a client has at most one preferred match at a time.

Ending a match (`action` of `END`) requires only that the match is not already `ENDED`, otherwise `ERR_INVALID_STATE`. The match's `match_status` becomes `ENDED`, and if it was a primary match whose `continuity_status` was `PREFERRED`, that status becomes `BROKEN` and the client's `continuity_score` is recomputed. The same continuity-breaking effect is what the caregiver suspension and revocation cascades of §3.2 reach into: whenever a primary, preferred match lapses — whether because a scheduler ends it or because the underlying caregiver is suspended or revoked — the match's `continuity_status` transitions `PREFERRED → BROKEN` and the client's `continuity_score` is recomputed. A match must be `ACTIVE` for the caregiver-and-client pair before any visit for that pair can depart or clock in.

### 3.5. Scheduling a Visit

A **Visit** is the unit of field work. A `Scheduler` or `AgencyAdmin` schedules one with the `caregiver_id`, the `client_id`, the `care_plan_id` it will be performed against, a `billing_mode` of either `HOURLY` or `LIVE_IN`, and a planned window given by `scheduled_start` and `scheduled_end` (both ISO 8601 UTC). A visit opens in `SCHEDULED` status, with `clock_in_at`, `clock_out_at`, and `evv_source` unset, an empty `evv_log`, `billable_minutes` of 0, and a `visit_charge` of 0.

Scheduling enforces three business constraints in addition to the well-formedness rule that `scheduled_end` must be after `scheduled_start`. First, a caregiver may not be double-booked: the new visit's half-open interval from `scheduled_start` up to `scheduled_end` must not overlap the interval of any non-terminal visit — one in `SCHEDULED`, `EN_ROUTE`, or `IN_PROGRESS` — for the **same caregiver**. Because the interval is half-open, an exact endpoint touch, where one visit's end equals the next visit's start, does not conflict; a true overlap is rejected with `ERR_CAREGIVER_DOUBLE_BOOKED`. Second, the same-client check is stricter: the new visit's interval is expanded by the agency's `travel_buffer_minutes` on each side, and that buffered interval must not overlap any non-terminal visit for the **same client**; because the buffered interval is treated as closed, a touch that falls within the buffer does conflict, and the rejection is `ERR_CLIENT_VISIT_CONFLICT`. Third, scheduling must not push the caregiver's total scheduled billable hours within the visit's ISO week above that caregiver's `max_weekly_hours`; exceeding the cap is rejected with `ERR_WEEKLY_HOURS_EXCEEDED`.

The visit's `status` runs through `SCHEDULED`, `EN_ROUTE`, `IN_PROGRESS`, `COMPLETED`, `CANCELLED`, and `MISSED`, of which the last three are terminal, and the machine is deliberately cyclic so that mis-clocked visits can be corrected.

### 3.6. Departing, Clocking In, and Clocking Out

A `Caregiver` begins a visit by departing for it (`action` of `DEPART`), which advances the visit `SCHEDULED → EN_ROUTE`. Departure requires that the visit is `SCHEDULED`, otherwise `ERR_INVALID_STATE`, and that an `ACTIVE` match exists for the visit's `caregiver_id` and `client_id`, otherwise `ERR_NO_ACTIVE_MATCH`.

Clocking in is the electronic visit verification entry point and advances the visit from `SCHEDULED` or `EN_ROUTE` to `IN_PROGRESS`. The caregiver supplies the verification `event_at` timestamp and may supply an `evv_source` — the channel of the event, one of `TELEPHONY`, `MOBILE`, or `MANUAL` — and a `caller_id`. Four preconditions guard clock-in: the visit must be in `SCHEDULED` or `EN_ROUTE` (otherwise `ERR_INVALID_STATE`); the client's `status` must be `ACTIVE` (otherwise `ERR_CLIENT_NOT_SCHEDULABLE`); the referenced care plan's `status` must be `PUBLISHED` (otherwise `ERR_CARE_PLAN_NOT_PUBLISHED`); and an `ACTIVE` match must exist for the visit's caregiver-and-client pair (otherwise `ERR_NO_ACTIVE_MATCH`). On success the system sets `clock_in_at` to the supplied `event_at`, records the `evv_source`, and appends a clock-in entry to the `evv_log`. Each `evv_log` entry captures an `event_type` of either `CLOCK_IN` or `CLOCK_OUT`, the `event_at`, the `evv_source`, and the `caller_id`.

Clocking out advances the visit `IN_PROGRESS → COMPLETED` and is where the provisional charge is struck. The caregiver again supplies an `event_at` and may supply `evv_source` and `caller_id`. Clock-out requires that the visit is `IN_PROGRESS`, otherwise `ERR_VISIT_NOT_IN_PROGRESS`, and that the supplied `event_at` is strictly later than `clock_in_at`, otherwise `ERR_INVALID_CLOCK_WINDOW`. On success the system sets `clock_out_at` to the `event_at`, appends a clock-out entry to the `evv_log`, computes `billable_minutes`, computes the provisional `visit_charge`, and recomputes the client's `continuity_score`.

To compute `billable_minutes`, the system first takes the raw number of whole minutes between `clock_in_at` and `clock_out_at`, discarding any fractional minute. It then rounds that raw figure to the nearest multiple of the agency's `evv_rounding_minutes` using round-half-up — that is, it divides the raw minutes by the rounding increment, rounds that quotient to the nearest whole number with halves going up, and multiplies back by the increment. The provisional `visit_charge` then depends on `billing_mode`. For an `HOURLY` visit, the charge is the `billable_minutes` divided by 60 and multiplied by the agency's `base_hourly_rate`, rounded half-up to 2 decimal places, with no awareness of overtime — every hour is billed at the base rate. For a `LIVE_IN` visit, the system counts the number of started 24-hour blocks by dividing `billable_minutes` by 1440 and rounding up to the next whole block, then multiplies that count of started days by the agency's `live_in_day_rate` and rounds half-up to 2 decimal places, ignoring any per-hour rate. Each visit is priced in isolation at the moment it completes.

Two corrective transitions let a scheduler unwind clocking. Cancelling a visit (`action` of `CANCEL`) is permitted from `SCHEDULED` or `EN_ROUTE`, otherwise `ERR_INVALID_STATE`; it moves the visit to `CANCELLED`, sets `billable_minutes` to 0 and `visit_charge` to 0, and recomputes the client's `continuity_score`. Resetting a visit (`action` of `RESET`) is permitted from `EN_ROUTE` or `IN_PROGRESS`, otherwise `ERR_INVALID_STATE`; it returns the visit to `SCHEDULED`, clears `clock_in_at`, `clock_out_at`, and `evv_source`, and sets `billable_minutes` and `visit_charge` back to 0, providing the cyclic revert loop for mis-clocked visits. Marking a visit missed (`action` of `MARK_MISSED`) is permitted only from `SCHEDULED`, otherwise `ERR_INVALID_STATE`; it moves the visit to `MISSED` and recomputes the client's `continuity_score`, with the reliability term penalized as described in §3.7.

### 3.7. The Continuity Score

A client's `continuity_score` is a weighted measure on the closed interval from 0 to 1 that the system recomputes whenever a visit reaches a terminal state — completion, cancellation, or marking missed — and whenever a match ends or a primary match's continuity breaks. The score is built over all of the client's terminal-state visits, meaning those in `COMPLETED`, `CANCELLED`, or `MISSED`. If the client has no terminal visits at all, the score is 0.

Otherwise the score combines two terms. The first is a **continuity ratio**: among the client's completed visits, the fraction that were served by the client's primary caregiver. The primary caregiver is the caregiver of the client's `ACTIVE` primary match; if there is no active primary match, it is the caregiver of the earliest-created `ACTIVE` match ordered by `created_at` ascending; and if the client has no active match at all, there is no primary caregiver. The tie-break for selecting the primary caregiver always uses `created_at` ascending, never the `id`. If the client has zero completed visits, the continuity ratio is 0; otherwise it is the count of completed visits whose caregiver is the primary caregiver divided by the total count of completed visits. The second term is **reliability**: the count of completed visits divided by the count of terminal visits — a figure that drops whenever a visit is cancelled or missed rather than completed, which is the penalty referred to in §3.6. The final `continuity_score` weights the continuity ratio at 0.6 and reliability at 0.4 — that is, six-tenths of the continuity ratio plus four-tenths of reliability — and rounds the result half-up to 2 decimal places.

### 3.8. Mileage and Companion Errands

When a companion errand is performed during a visit, a `Caregiver` or `Scheduler` records a **MileageEntry** against that visit with the `miles` driven (which must be greater than 0) and a `purpose` such as "Grocery run". The entry records its owning `visit_id`, opens with a `status` of `RECORDED`, and immediately receives a `line_charge` computed as the `miles` multiplied by the agency's `mileage_rate`, rounded half-up to 2 decimal places at the moment of creation. Rounding happens per entry, here and now; this is significant because the invoice's mileage total is later assembled as the plain sum of these already-rounded line charges, not as a single rounding of the summed raw miles. A `Scheduler` or `AgencyAdmin` may void a mileage entry, advancing its `status` from `RECORDED` to `VOIDED`, and `VOIDED` entries are excluded from all invoice mileage totals.

### 3.9. Opening and Finalizing an Invoice

A **BillingClerk** or `AgencyAdmin` opens an **Invoice** for a billing period against a specific caregiver-and-client pairing, supplying the `agency_id`, `caregiver_id`, `client_id`, an inclusive `period_start`, and an exclusive `period_end` (which must be after `period_start`). A new invoice opens in `DRAFT` with `labor_total`, `mileage_total`, `invoice_total`, and `client_responsible_amount` all 0, and an empty `lines` array. The invoice `status` machine runs `DRAFT`, `ISSUED`, `DISPUTED`, `PAID`, and `VOID`, with `PAID` and `VOID` terminal, and is cyclic in that a disputed invoice can be reopened to `DRAFT`.

Finalizing an invoice (the `DRAFT → ISSUED` transition, performed by a `BillingClerk` or `AgencyAdmin`) is the system's most involved calculation. It requires that the invoice is `DRAFT`, otherwise `ERR_INVOICE_NOT_DRAFT`, and that at least one `COMPLETED` visit falls inside the half-open window from `period_start` up to `period_end` for the invoice's `caregiver_id` and `client_id`, otherwise `ERR_NO_BILLABLE_VISITS`. On success the system rebuilds the invoice's `lines`, computes the final `labor_total` and the `mileage_total`, sets `invoice_total` to their sum, sets `client_responsible_amount` equal to `invoice_total`, and increments the invoice's `version` by one.

The labor calculation is the **final, chronological** variant and differs from the per-visit provisional charges. The system gathers only the `COMPLETED` visits in the window for the matching `caregiver_id` and `client_id` — `CANCELLED` and `MISSED` visits are excluded — and orders them by `clock_in_at` ascending, breaking ties by `created_at` ascending. It then walks that ordered list keeping a running total of hours billed so far. A `LIVE_IN` visit in the list is priced on its own terms: the count of started 24-hour blocks (its `billable_minutes` divided by 1440, rounded up) multiplied by the `live_in_day_rate`, rounded half-up to 2 decimal places, emitted as a `LIVE_IN` line with its `source_visit_id`, and it does not contribute to the running hours. For an `HOURLY` visit, the system converts its `billable_minutes` to hours by dividing by 60, then splits those hours against the overtime threshold: the regular portion is the smaller of the visit's hours and the remaining headroom below the threshold, where the headroom is the agency's `overtime_threshold_hours` minus the running hours so far, never less than 0; the overtime portion is whatever hours remain beyond that. If the regular portion is greater than 0, a `REGULAR` line is emitted at the `base_hourly_rate` with an `amount` of those regular hours times the base rate, rounded half-up to 2 decimal places. If the overtime portion is greater than 0, an `OVERTIME` line is emitted at the `base_hourly_rate` multiplied by the `overtime_multiplier`, with an `amount` of those overtime hours times that overtime rate, rounded half-up to 2 decimal places. After each visit the running hours are increased by that visit's full hours. The `labor_total` is the plain sum of all the already-rounded `REGULAR`, `OVERTIME`, and `LIVE_IN` line amounts. Each line in `lines` records its `line_type` (`REGULAR`, `OVERTIME`, `LIVE_IN`, or `MILEAGE`), its `source_visit_id`, the `hours`, the `rate`, and the `amount`. Because overtime is allocated across the whole period this way, the final labor figure is greater than or equal to the simple sum of the provisional visit charges, which never carry overtime.

The mileage total is computed alongside the labor lines: the system sums the `line_charge` of every `MileageEntry` whose `status` is `RECORDED` and whose `visit_id` belongs to a `COMPLETED` visit inside the window, again as a plain sum of the already-rounded per-entry charges. Each such mileage entry contributes a `MILEAGE` line. The `mileage_total` is that sum, and `invoice_total` is `labor_total` plus `mileage_total`.

### 3.10. Disputing, Reopening, Paying, and Voiding an Invoice

After an invoice is issued, an `AgencyAdmin` may dispute it (`action` of `DISPUTE`, `ISSUED → DISPUTED`), which requires the invoice to be `ISSUED`, otherwise `ERR_INVOICE_NOT_ISSUED`. Disputing carries a cascade: any claim attached to this invoice that is `SUBMITTED` or `APPROVED` is moved to `DENIED`, that denial resets the claim's `covered_amount` to 0, and the invoice's `client_responsible_amount` is restored to its full `invoice_total`. The dispute increments the invoice's `version` by one.

A disputed invoice can be reopened (`action` of `REOPEN`, `DISPUTED → DRAFT`) by an `AgencyAdmin`, which requires the invoice to be `DISPUTED`, otherwise `ERR_INVOICE_NOT_DISPUTED`. Reopening clears the invoice's `lines` and resets `labor_total`, `mileage_total`, `invoice_total`, and `client_responsible_amount` all back to 0, returning the invoice to `DRAFT` so it can be finalized afresh; it increments `version` by one.

Marking an invoice paid (`action` of `MARK_PAID`, `ISSUED → PAID`) is performed by a `BillingClerk` and requires the invoice to be `ISSUED`, otherwise `ERR_INVOICE_NOT_ISSUED`. If any claim is assigned to this invoice, that claim must already be `APPROVED` or `PAID`, otherwise the payment is blocked with `ERR_CLAIM_NOT_RESOLVED`. On success any `APPROVED` claim on the invoice is cascaded to `PAID`, and the invoice's `version` is incremented by one.

A draft invoice may also be voided (`action` of `VOID`, `DRAFT → VOID`) by an `AgencyAdmin`, which requires the invoice to be `DRAFT`, otherwise `ERR_INVOICE_NOT_DRAFT`; voiding carries no further side effects.

### 3.11. Assigning and Adjudicating Long-Term-Care Claims

A **LtcClaim** represents an insurer's coverage of part of an invoice. A `BillingClerk` or `AgencyAdmin` assigns a claim to an invoice with the `client_id`, the `invoice_id`, the `insurer_name`, the `policy_number`, the `covered_pct` (the fraction of the invoice total the policy covers, between 0 and 1), the `daily_benefit_max` (the maximum covered USD per benefit day, greater than 0), the `covered_days` (the number of benefit days the claim spans, greater than 0), and the `expected_invoice_version` required by the optimistic-concurrency rule of §2.9. A claim opens with a `status` of `DRAFT` and a `covered_amount` of 0. As described in §2.9, the assignment checks `expected_invoice_version` against the invoice's current `version`, rejects a mismatch with `ERR_STALE_INVOICE_VERSION`, and on success increments the invoice's `version` by one so that any later assignment reusing the stale version fails. The claim `status` machine runs `DRAFT`, `SUBMITTED`, `APPROVED`, `DENIED`, `APPEALED`, and `PAID`, where `PAID` is terminal, and it both branches and cycles.

Submitting a claim (the `DRAFT → SUBMITTED` transition, performed by a `BillingClerk`) requires the claim to be `DRAFT`, otherwise `ERR_INVALID_STATE`, and the referenced invoice to be `ISSUED`, otherwise `ERR_INVOICE_NOT_ISSUED`. Submission computes the `covered_amount` and adjusts the invoice. The coverage figure is the smaller of two quantities: the percentage coverage, which is the invoice's `invoice_total` multiplied by `covered_pct` and rounded half-up to 2 decimal places; and the benefit cap, which is `daily_benefit_max` multiplied by `covered_days`. The `covered_amount` is whichever of those two is smaller, so the cap binds whenever the cap is below the rounded percentage figure. Submission then sets the invoice's `client_responsible_amount` to the `invoice_total` minus the `covered_amount`, rounded half-up to 2 decimal places, and increments the invoice's `version` by one.

Adjudication is handled by an `AgencyAdmin` (with `DENY` also available to a `BillingClerk`). Approving a submitted claim (`action` of `APPROVE`, `SUBMITTED → APPROVED`) requires the claim to be `SUBMITTED`, otherwise `ERR_INVALID_STATE`, and carries no financial side effect. Denying a submitted claim (`action` of `DENY`, `SUBMITTED → DENIED`) likewise requires `SUBMITTED`, otherwise `ERR_INVALID_STATE`; denial is compensating — it sets the claim's `covered_amount` back to 0, restores the invoice's `client_responsible_amount` to the full `invoice_total`, and increments the invoice's `version` by one.

A denied claim can be appealed and resubmitted. Appealing (`action` of `APPEAL`, `DENIED → APPEALED`) requires the claim to be `DENIED`, otherwise `ERR_INVALID_STATE`, and has no further effect. Resubmitting an appealed claim follows the same submit pathway (`APPEALED → SUBMITTED`) and requires the claim to be `APPEALED` and the invoice to be `ISSUED`, otherwise `ERR_INVALID_STATE` or `ERR_INVOICE_NOT_ISSUED` respectively; it recomputes the `covered_amount` by the same smaller-of-percentage-or-cap rule, sets the invoice's `client_responsible_amount` to `invoice_total` minus the recomputed `covered_amount` rounded half-up to 2 decimal places, and increments the invoice's `version` by one. This `DENIED → APPEALED → SUBMITTED` loop is the resubmission cycle. Finally, when the parent invoice is marked paid, any `APPROVED` claim on it is moved to `PAID` by the system as part of the invoice's payment cascade; this is the claim's only path into `PAID`.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource or add a new resource to a collection return `201 Created`. Operations that modify an existing resource — including lifecycle transitions, clock events, finalization, and claim adjudication — return `200 OK`. List and retrieval endpoints return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/agencies` | Create an agency configuration root | AgencyAdmin |
| POST | `/caregivers` | Register a caregiver | AgencyAdmin |
| GET | `/caregivers` | List/filter caregivers by agency | AgencyAdmin, Scheduler, BillingClerk |
| GET | `/caregivers/{id}` | Get a caregiver | AgencyAdmin, Scheduler, BillingClerk, Caregiver |
| POST | `/caregivers/{id}/transition` | Employment/background lifecycle action | AgencyAdmin |
| POST | `/clients` | Create a client | AgencyAdmin, Scheduler |
| GET | `/clients` | List/filter clients by agency | AgencyAdmin, Scheduler, BillingClerk |
| GET | `/clients/{id}` | Get a client | AgencyAdmin, Scheduler, BillingClerk, Caregiver |
| POST | `/clients/{id}/transition` | Change client status | AgencyAdmin, Scheduler |
| POST | `/clients/{id}/care-plans` | Create a care plan for a client | AgencyAdmin, Scheduler |
| GET | `/clients/{id}/care-plans` | List care plans for a client | AgencyAdmin, Scheduler, BillingClerk, Caregiver |
| GET | `/care-plans/{id}` | Get a care plan | AgencyAdmin, Scheduler, BillingClerk, Caregiver |
| POST | `/care-plans/{id}/transition` | Publish/retire a care plan | AgencyAdmin, Scheduler |
| POST | `/care-plans/{id}/tasks` | Add an ADL/IADL task to a plan | AgencyAdmin, Scheduler |
| GET | `/care-plans/{id}/tasks` | List care tasks for a plan | AgencyAdmin, Scheduler, BillingClerk, Caregiver |
| DELETE | `/care-plans/{id}/tasks/{id}` | Remove a care task | AgencyAdmin, Scheduler |
| POST | `/matches` | Propose a caregiver-client match | Scheduler, AgencyAdmin |
| GET | `/matches` | List/filter matches by caregiver or client | AgencyAdmin, Scheduler, BillingClerk |
| GET | `/matches/{id}` | Get a match | AgencyAdmin, Scheduler, BillingClerk, Caregiver |
| POST | `/matches/{id}/transition` | Activate/end a match | Scheduler, AgencyAdmin |
| POST | `/visits` | Schedule a visit | Scheduler, AgencyAdmin |
| GET | `/visits` | List/filter visits | AgencyAdmin, Scheduler, BillingClerk, Caregiver |
| GET | `/visits/{id}` | Get a visit | AgencyAdmin, Scheduler, BillingClerk, Caregiver |
| POST | `/visits/{id}/clock-in` | EVV telephony clock-in | Caregiver |
| POST | `/visits/{id}/clock-out` | EVV telephony clock-out | Caregiver |
| POST | `/visits/{id}/transition` | Depart/cancel/reset/mark-missed a visit | Scheduler, AgencyAdmin, Caregiver |
| POST | `/visits/{id}/mileage` | Record a mileage/companion-errand entry | Caregiver, Scheduler |
| GET | `/visits/{id}/mileage` | List mileage entries for a visit | AgencyAdmin, Scheduler, BillingClerk, Caregiver |
| POST | `/mileage/{id}/void` | Void a mileage entry | Scheduler, AgencyAdmin |
| POST | `/invoices` | Open a draft invoice for a billing period | BillingClerk, AgencyAdmin |
| GET | `/invoices` | List/filter invoices | AgencyAdmin, Scheduler, BillingClerk |
| GET | `/invoices/{id}` | Get an invoice | AgencyAdmin, Scheduler, BillingClerk, Caregiver |
| POST | `/invoices/{id}/finalize` | Finalize an invoice | BillingClerk, AgencyAdmin |
| POST | `/invoices/{id}/transition` | Dispute/reopen/mark-paid/void an invoice | BillingClerk, AgencyAdmin |
| POST | `/ltc-claims` | Assign an LTC claim to an issued invoice | BillingClerk, AgencyAdmin |
| GET | `/ltc-claims` | List/filter claims by client or invoice | AgencyAdmin, BillingClerk |
| GET | `/ltc-claims/{id}` | Get an LTC claim | AgencyAdmin, BillingClerk |
| POST | `/ltc-claims/{id}/submit` | Submit/resubmit a claim | BillingClerk |
| POST | `/ltc-claims/{id}/transition` | Approve/deny/appeal a claim | AgencyAdmin, BillingClerk |
| POST | `/_clock/set_current_utc` | Test-only: pin the server clock | AgencyAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_AGENCY_NOT_FOUND` | 404 |
| `ERR_CAREGIVER_NOT_FOUND` | 404 |
| `ERR_CLIENT_NOT_FOUND` | 404 |
| `ERR_CARE_PLAN_NOT_FOUND` | 404 |
| `ERR_MATCH_NOT_FOUND` | 404 |
| `ERR_VISIT_NOT_FOUND` | 404 |
| `ERR_INVOICE_NOT_FOUND` | 404 |
| `ERR_CLAIM_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_BACKGROUND_NOT_PENDING` | 409 |
| `ERR_BACKGROUND_NOT_CLEARED` | 409 |
| `ERR_CAREGIVER_NOT_ACTIVE` | 409 |
| `ERR_CLIENT_NOT_SCHEDULABLE` | 409 |
| `ERR_CARE_PLAN_NOT_PUBLISHED` | 409 |
| `ERR_NO_ACTIVE_MATCH` | 409 |
| `ERR_DUPLICATE_ACTIVE_MATCH` | 409 |
| `ERR_VISIT_NOT_IN_PROGRESS` | 409 |
| `ERR_INVALID_CLOCK_WINDOW` | 409 |
| `ERR_CAREGIVER_DOUBLE_BOOKED` | 409 |
| `ERR_CLIENT_VISIT_CONFLICT` | 409 |
| `ERR_WEEKLY_HOURS_EXCEEDED` | 409 |
| `ERR_INVOICE_NOT_DRAFT` | 409 |
| `ERR_INVOICE_NOT_ISSUED` | 409 |
| `ERR_INVOICE_NOT_DISPUTED` | 409 |
| `ERR_NO_BILLABLE_VISITS` | 409 |
| `ERR_CLAIM_NOT_RESOLVED` | 409 |
| `ERR_STALE_INVOICE_VERSION` | 412 |
