# Senior Errand & Companion Service API — Product Requirements Document

## 1. Introduction

The Senior Errand & Companion Service API coordinates non-medical support for elderly clients: grocery runs, prescription pickups, transportation, and in-home companionship. Operations staff onboard each senior, capture the billing terms that govern how their care is priced, and stand up recurring schedules that materialize into individual visits. Field caregivers are matched to those visits, but only after they have cleared a background check and carry active bonding coverage. Once a caregiver clocks in and later clocks out, the platform prices the visit — hourly labor with an overtime tier, mileage reimbursement, and any approved add-on services — and issues an invoice.

Beyond scheduling and billing, the platform serves two additional constituencies. Family members are given portal access scoped to a single senior so they can follow visit logs and respond to wellness escalations raised in the field. Billing staff reconcile finalized invoices against long-term-care insurance, filing reimbursement claims whose payouts flow back into the client's running balance. The domain is inherently temporal — background checks and bonds expire, schedules run between eligible dates, and visits occupy windows that must not collide — so the system runs on an explicit logical clock rather than wall-clock time, and many of its rules are boundary-sensitive by design.

This document specifies the complete contract: the global conventions every endpoint honors, the business rules that govern each entity's lifecycle, the calculations that price visits and reimbursements, and the full endpoint and error catalogues.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, envelopes, and cross-cutting principles that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header is rejected with `ERR_UNAUTHENTICATED`. When the headers are present but the declared role is not permitted to invoke the target endpoint, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly four roles: `CareCoordinator`, `Caregiver`, `FamilyContact`, and `BillingClerk`.

- When `X-User-Role` is `CareCoordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it, but it does not compare it to any entity's `id`. Care coordinators are the operations staff who onboard clients and caregivers, run background checks and bonding, build schedules, match caregivers, manage visits, resolve wellness checks directly, and drive the logical clock.
- When `X-User-Role` is `BillingClerk`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. Billing clerks finalize and void invoices and manage the full reimbursement-claim lifecycle.
- When `X-User-Role` is `Caregiver`, `X-User-ID` is the `id` of the acting `Caregiver`; ownership checks on any resource that references a `Caregiver` compare the resource's foreign-key field to `X-User-ID`. Concretely, a caregiver may clock in, clock out, escalate, and append visit-log entries only on a visit whose `caregiver_id` equals `X-User-ID`.
- When `X-User-Role` is `FamilyContact`, `X-User-ID` is the `id` of the acting `FamilyContact`; ownership checks on any resource that references a client compare the resource's `client_id` to the contact's own `client_id`. A family contact may acknowledge and resolve wellness checks, request add-ons, and read visits, invoices, wellness checks, and logs only for the one client they are registered against.

When an `entity_backed` actor (a `Caregiver` or a `FamilyContact`) targets a resource they do not own, the request is rejected with `ERR_NOT_RESOURCE_OWNER`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items are returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items skipped before the returned page begins and defaults to 0.

Unless a specific endpoint says otherwise, list endpoints return their resources sorted by `created_at` in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every primary resource carries a system-managed `id` — a UUID minted by the server, with no type prefix — and a `created_at` timestamp in ISO 8601 UTC with three fractional digits, recorded when the resource is first created. Most resources additionally carry an `updated_at` timestamp (same format, refreshed on every mutation) and an integer `version` that starts at its initial value and increments by one on every mutation of the resource.

There is one deliberate exception. A `VisitLogEntry` is append-only and immutable after creation: it carries only `id` and `created_at`, and has neither an `updated_at` field nor a `version` field. Every other entity — `Client`, `FamilyContact`, `Caregiver`, `BackgroundCheck`, `BondingRecord`, `RecurringSchedule`, `Visit`, `Assignment`, `AddOn`, `Invoice`, `LTCPolicy`, `ReimbursementClaim`, and `WellnessCheck` — carries the full set of `id`, `created_at`, `updated_at`, and `version`.

Whenever a derived or computed field on a resource changes — for example a client's `outstanding_balance_cents`, a caregiver's `committed_minutes`, or a visit's `caregiver_id` and `estimated_cost_cents` — that change is a mutation of the owning resource: it refreshes `updated_at` and increments `version`. Every lifecycle-bearing entity additionally exposes its current lifecycle state through a `status` field, whose permitted values are enumerated per entity in §3.

### 2.5. The Logical Clock and Time-Sensitive Transitions

The server keeps an explicit logical clock rather than reading wall-clock time. At startup the clock reads exactly `2026-03-01T00:00:00Z`, and before any clock-setting call is made it holds that default without ever falling back to real time. An administrative test-driving capability advances the clock to a supplied `to_iso8601` instant.

Advancing the clock lazily settles two time-based lifecycles. A `BackgroundCheck` in `CLEARED` status whose `expires_at` instant has been reached or passed by the current clock is treated as `EXPIRED`. A `BondingRecord` is `ACTIVE` while its `effective_date` is on or before the clock and the clock is strictly before its `expiry_date`; once the clock reaches or passes `expiry_date`, the bond becomes `LAPSED`. These transitions require no explicit per-resource call — reaching the deadline on the clock is sufficient.

A `RecurringSchedule` also responds to the clock: an `ACTIVE` schedule whose `end_date` has passed with no remaining occurrences becomes `ENDED`, which is terminal.

### 2.6. Monetary Precision and Rounding

All money is expressed in integer cents on the stored resources, with two exceptions that are rates rather than amounts: `mileage_rate_cents_per_mile` and `reimbursement_rate` may carry fractional precision as supplied. Wherever a computation produces a fractional cent, the result is rounded to a whole number of cents using the round-half-up convention (a value whose fractional part is exactly one half rounds away from zero to the next whole cent).

A crucial ordering rule governs invoice totals: each line item is rounded to whole cents first, and only the already-rounded line items are summed. Rounding the sum instead of the parts would produce a different total whenever two lines each carry a half-cent fraction, so the per-line-then-sum order is fixed and must not be reversed.

### 2.7. Optimistic Concurrency Control on Visit Assignment

Matching a caregiver to a visit is the one write in this system guarded by optimistic concurrency control. A request to create an assignment on a visit must carry `expected_visit_version`, and this field is mandatory for that operation — it is the client's last observed `version` of the target `Visit`. If `expected_visit_version` does not equal the visit's current `version`, the request is rejected with `ERR_STALE_VISIT_VERSION` at HTTP status 412.

This matters because a fresh assignment legitimately supersedes any prior confirmed match on the same visit and increments the visit's `version`. A later create that still carries the pre-supersede version is therefore operating on a stale view of the visit and is rejected on the version mismatch, preventing it from overwriting a match it never observed. No other endpoint in the system takes a version field; only assignment creation is version-checked.

### 2.8. Cascading State Propagation and Hierarchical Consistency

Several operations mutate more than one entity. The system applies these cascades immediately and in full; each secondary mutation refreshes the affected resource's `updated_at` and increments its `version`.

Suspending a client cascades down the client's schedule tree. The client moves to `SUSPENDED`; then, as hop one, every `RecurringSchedule` owned by that client that is currently `ACTIVE` moves to `PAUSED`. Pausing a schedule is itself hop two: every `Visit` belonging to that schedule that is still `SCHEDULED` moves to `CANCELLED`. Cancelling a visit is hop three: every `CONFIRMED` `Assignment` on it moves to `CANCELLED` (releasing that caregiver's committed minutes), and any `DRAFT` `Invoice` for the visit moves to `VOID`.

Voiding an invoice likewise cascades. A finalized invoice being voided reverses its debit from the client's balance, and then, as hop two, every `ReimbursementClaim` against that invoice in `DRAFT`, `SUBMITTED`, `NEEDS_INFO`, or `APPROVED` status moves to `WITHDRAWN`; if a withdrawn claim had been `APPROVED`, its `reimbursed_cents` is subtracted back out of both the policy's `reimbursed_to_date_cents` and the client's `outstanding_balance_cents`.

### 2.9. Nested Resource Retrieval and Path Validation

Many endpoints address resources through a hierarchical path — a caregiver's background checks, a client's schedules, a visit's add-ons. The system validates the existence of every resource named in a path from left to right, and rejects the request with `ERR_RESOURCE_NOT_FOUND` at the first path segment whose identifier does not correspond to an existing resource. A nested resource is never inspected until its ancestors in the path have been confirmed to exist.

### 2.10. Validation Ordering

When several checks could reject a single request, they are evaluated in a fixed precedence so that the returned error is deterministic. Authentication comes first: absent headers yield `ERR_UNAUTHENTICATED`. Authorization by role comes next, yielding `ERR_UNAUTHORIZED`. Existence of every path-referenced resource is checked third (`ERR_RESOURCE_NOT_FOUND`, left to right per §2.9). Ownership for entity-backed actors is checked fourth, yielding `ERR_NOT_RESOURCE_OWNER`. Structural validity of the request body — required fields present with correct types — is fifth, yielding `ERR_INVALID_REQUEST`; enum-typed fields carrying an undeclared member are sixth, yielding `ERR_INVALID_ENUM`. The optimistic-concurrency check on assignment creation is seventh, yielding `ERR_STALE_VISIT_VERSION`. State-machine eligibility of the target resource is eighth (the generic `ERR_INVALID_STATE`, refined into the specific state errors named in §3). Caregiver clearance and bonding are ninth (`ERR_CAREGIVER_NOT_CLEARED` / `ERR_CAREGIVER_NOT_BONDED`). Cross-entity referential integrity between a claim's policy and invoice is tenth (`ERR_POLICY_CLIENT_MISMATCH`). Temporal-overlap conflicts are eleventh (`ERR_CAREGIVER_DOUBLE_BOOKED` on assignment, `ERR_CLIENT_VISIT_OVERLAP` on visit creation). Value and range constraints are twelfth (`ERR_INVALID_TIME_RANGE`). Fiscal eligibility of a policy on claim submission is last (`ERR_POLICY_EXHAUSTED`). Reading the list top to bottom, an earlier failure is reported in preference to any later one.

## 3. Business Logic & Workflows

### 3.1. Onboarding a Client and Configuring Billing

A `CareCoordinator` opens the relationship by registering a senior. The creation payload supplies the client's `name`, residence `home_zip`, and the billing terms: `hourly_rate_cents` (the billing rate per hour, in cents, which must be at least 0) and `mileage_rate_cents_per_mile` (the mileage reimbursement rate in cents per mile, which may be fractional such as 67.5 and must be at least 0). The payload may also supply an IANA `timezone` label — informational only, since all timestamps are UTC, and defaulting to `UTC` when omitted — along with three optional overtime and floor parameters described in the pricing narrative of §3.5: `ot_threshold_hours`, `ot_multiplier`, and `min_visit_minutes`. A new client begins in `ACTIVE` status with `outstanding_balance_cents` initialized to 0. A client's lifecycle has only one further state: an active client may be moved to `SUSPENDED`, which is terminal and drives the suspension cascade of §2.8; suspending a client that is not `ACTIVE` is rejected with `ERR_CLIENT_NOT_ACTIVE`.

Around the client, the coordinator registers family-portal contacts. Each `FamilyContact` is created against the client with a `name`, an `email`, and a stated `relationship` to the senior (for example, daughter or son), and is bound to that client through its `client_id`. Contacts may be listed back for a client.

The coordinator also attaches long-term-care insurance. An `LTCPolicy` records the `payer_name`, a `benefit_type` of either `INDEMNITY` or `REIMBURSEMENT`, and a `lifetime_max_cents` cumulative reimbursement ceiling (at least 0). Depending on the benefit type, the coordinator supplies the relevant terms: an indemnity policy carries a flat `daily_benefit_cents` (null for a reimbursement policy), while a reimbursement policy carries a `reimbursement_rate` fraction between 0 and 1 and a per-claim `daily_cap_cents` ceiling (both null for an indemnity policy). A new policy starts `ACTIVE` with `reimbursed_to_date_cents` at 0. As approved claims accumulate, `reimbursed_to_date_cents` rises; once it reaches `lifetime_max_cents` the policy becomes `EXHAUSTED`, which is terminal.

### 3.2. Credentialing Caregivers: Background Checks and Bonding

Field staff are onboarded as caregivers by a `CareCoordinator`. A `Caregiver` is created with a `name` and base `home_zip`, and optionally an `hourly_pay_cents` figure that is informational to the caregiver's compensation and plays no part in client billing (it defaults to 0 and must be at least 0). A caregiver begins `ACTIVE` with `committed_minutes` at 0; the alternate employment state is `INACTIVE`. The `committed_minutes` figure is the sum, in minutes, of the scheduled length (`scheduled_end` minus `scheduled_start`) of every visit the caregiver holds a `CONFIRMED` assignment on; superseded and cancelled assignments never contribute.

Before a caregiver may be matched or work a visit, two credentials must be in force. The coordinator opens a `BackgroundCheck` — which references the caregiver through `caregiver_id` and starts in `PENDING` — and later records a decision. The decision call carries an `outcome`: a `CLEARED` outcome moves the check `PENDING → CLEARED` and stamps `decided_at` to the current clock while recording the supplied `expires_at` instant after which the cleared result stops being valid; a `FLAGGED` outcome moves the check `PENDING → FLAGGED` and stamps `decided_at`. Both `FLAGGED` and `EXPIRED` are terminal, and as described in §2.5 a `CLEARED` check lapses to `EXPIRED` once the clock reaches `expires_at`.

Bonding coverage is captured as a `BondingRecord` referencing the caregiver through `caregiver_id`, with a `coverage_cents` amount (at least 0) and a coverage window running from `effective_date` to `expiry_date`. The record is `ACTIVE` while the clock sits within that window and `LAPSED` once the clock reaches `expiry_date`, per §2.5.

Clearance and bonding are enforced together at two moments — when a caregiver is matched to a visit and when that caregiver clocks in. At each, the caregiver must hold a `CLEARED` background check whose `expires_at` is strictly after the current clock, or the request is rejected with `ERR_CAREGIVER_NOT_CLEARED`; and the caregiver must hold an `ACTIVE` bond whose window covers the current clock, or the request is rejected with `ERR_CAREGIVER_NOT_BONDED`.

### 3.3. Recurring Schedules and Visit Generation

A `CareCoordinator` builds a `RecurringSchedule` for an active client to encode a repeating errand. The schedule references its client through `client_id` and specifies the `task_type` (one of `GROCERY`, `RX_PICKUP`, `TRANSPORT`, or `COMPANION`), a `frequency` of either `WEEKLY` or `BIWEEKLY`, the `day_of_week` the visit lands on (one of `MON`, `TUE`, `WED`, `THU`, `FRI`, `SAT`, `SUN`), a `start_time` given as `HH:MM` and interpreted as UTC, and a `duration_minutes` length (greater than 0). The schedule is bounded by `start_date` (the first eligible date, inclusive) and `end_date` (the last eligible date, inclusive); creation is rejected with `ERR_INVALID_TIME_RANGE` if `end_date` falls before `start_date`. Attempting to create a schedule for a client that is not `ACTIVE` is rejected with `ERR_CLIENT_NOT_ACTIVE`. A schedule begins `ACTIVE`; it can be moved to `PAUSED` by the client-suspension cascade (§2.8), and it reaches the terminal `ENDED` state once the clock passes its `end_date` with no remaining occurrences.

The coordinator materializes concrete visits from a schedule by requesting generation over a window bounded by a `from_date` and a `to_date`. The system creates one `SCHEDULED` `Visit` for each date within that window that matches the schedule's `day_of_week` occurrence pattern; when the window contains no matching day, the result is an empty array. Generation is permitted only while the schedule is `ACTIVE`; on a non-active schedule it is rejected with `ERR_SCHEDULE_NOT_ACTIVE`.

### 3.4. Ad-Hoc Visits and Matching Caregivers

Not every visit comes from a schedule. A `CareCoordinator` may create an ad-hoc `Visit` directly, supplying the `client_id`, the `task_type`, the planned `scheduled_start` and `scheduled_end` instants, and optionally a `schedule_id` (which is null for a genuinely ad-hoc visit). A visit's `scheduled_end` must be strictly after its `scheduled_start`, or creation is rejected with `ERR_INVALID_TIME_RANGE`. A visit may only be created for an `ACTIVE` client, else `ERR_CLIENT_NOT_ACTIVE`. Creating a visit also guards against the same client being double-booked: if the new visit's time range overlaps an existing non-cancelled visit for that client, the request is rejected with `ERR_CLIENT_VISIT_OVERLAP`. This client-overlap comparison uses closed intervals with no buffer, so two visits whose endpoints merely touch — one beginning exactly when another ends — are treated as overlapping.

At creation the visit snapshots the client's billing configuration onto itself, freezing the terms in force at that moment: `hourly_rate_cents`, `mileage_rate_cents_per_mile`, `ot_threshold_hours`, `ot_multiplier`, and `min_visit_minutes` are all copied from the client onto the visit, so later edits to the client never retroactively reprice an existing visit. A freshly created visit is `SCHEDULED`, with `caregiver_id`, `actual_start`, `actual_end`, and `estimated_cost_cents` still unset and `mileage_miles` defaulting to 0.

Matching is performed by a `CareCoordinator` and is the optimistic-concurrency write of §2.7: the request carries the chosen `caregiver_id` and the mandatory `expected_visit_version`. The visit must be `SCHEDULED` (otherwise `ERR_VISIT_NOT_SCHEDULED`); `expected_visit_version` must match the visit's current `version` (otherwise `ERR_STALE_VISIT_VERSION`, 412); the caregiver must be cleared and bonded at the current clock per §3.2; and the match must not double-book the caregiver. The caregiver double-booking check uses a buffered, half-open comparison against the caregiver's other `CONFIRMED` assignments, so a caregiver's back-to-back visits where one ends exactly as the next begins do not conflict, whereas any genuine overlap within the travel buffer is rejected with `ERR_CAREGIVER_DOUBLE_BOOKED`.

A successful match creates an `Assignment` (referencing the visit through `visit_id` and the caregiver through `caregiver_id`) in `CONFIRMED` status. Any prior `CONFIRMED` assignment on the same visit is moved to `SUPERSEDED`, and that superseding releases the earlier caregiver's committed minutes. The visit's `caregiver_id` is set to the new caregiver, this visit's scheduled minutes are added to the new caregiver's `committed_minutes`, the visit's `estimated_cost_cents` is set to the provisional labor estimate described in §3.5, and the visit's `version` is incremented by one. A coordinator may also cancel a live match directly; cancelling a `CONFIRMED` assignment moves it `CONFIRMED → CANCELLED`, subtracts this visit's scheduled minutes from the caregiver's `committed_minutes`, and clears the visit's `caregiver_id` if it still points at that caregiver. Both the automatic supersession and the explicit cancellation may act only on a `CONFIRMED` assignment.

### 3.5. Working the Visit: Clock-In, Add-Ons, Escalation, and Clock-Out

The matched `Caregiver` starts the visit by clocking in, which advances it `SCHEDULED → IN_PROGRESS` and records the supplied `actual_start`. Clock-in requires the visit to be `SCHEDULED` (else `ERR_VISIT_NOT_SCHEDULED`), the acting caregiver to own the visit, and — because clearance is re-verified in the field — the caregiver to still be cleared and bonded at the current clock.

At any point before completion, extra services may be attached to a visit. Either a `CareCoordinator` or a `FamilyContact` may request an `AddOn` on a visit, naming its `addon_type` (one of `MEAL_PREP`, `PET_CARE`, `PAPERWORK`, or `EXTRA_STOP`) and a flat `fee_cents` charge (at least 0); the add-on references its visit through `visit_id` and begins `REQUESTED`. Only a `CareCoordinator` dispositions it, supplying an `outcome`: an `APPROVE` outcome moves it `REQUESTED → APPROVED`, and a `REJECT` outcome moves it `REQUESTED → REJECTED`. Approval additionally requires that the parent visit not already be `COMPLETED` or `CANCELLED`; rejection carries no such state requirement beyond the add-on itself being `REQUESTED`. Dispositioning an add-on that is not `REQUESTED` is rejected with `ERR_ADDON_NOT_REQUESTED`. Only `APPROVED` add-ons are billed on the visit's invoice.

A caregiver may also append `VisitLogEntry` lines to a visit they own — each with an `entry_type` of `NOTE`, `TASK_DONE`, or `INCIDENT` and free-text `note`. Log entries are append-only and never mutated once written.

If something is wrong during the visit, the owning caregiver may escalate. Escalation moves the visit `IN_PROGRESS → ESCALATED` and opens a `WellnessCheck` for the visit's client — carrying the triggering `visit_id`, the `client_id`, a `severity` of `LOW`, `MEDIUM`, or `HIGH`, and a free-text `reason` — but it deliberately does not produce an invoice. This is the fork point: from `IN_PROGRESS` a visit may go to either `COMPLETED` or `ESCALATED`, and the two branches carry different side effects. Escalation requires the visit to be `IN_PROGRESS` and the acting caregiver to own it; attempting to escalate a visit that is not `IN_PROGRESS` is rejected with `ERR_VISIT_NOT_IN_PROGRESS`.

Clocking out ends the visit and prices it. Clock-out is accepted from either `IN_PROGRESS` or `ESCALATED` — both paths move the visit to `COMPLETED` — while any other state is rejected with `ERR_VISIT_NOT_IN_PROGRESS`. The caregiver submits the `actual_end` instant and the `mileage_miles` driven; `actual_end` must be strictly after `actual_start` and `mileage_miles` must be at least 0, or the request is rejected with `ERR_INVALID_TIME_RANGE`. On success the visit records `actual_end` and `mileage_miles`, and a `DRAFT` `Invoice` is produced for the visit regardless of whether completion arrived from the `IN_PROGRESS` or the `ESCALATED` branch.

**Pricing.** Labor is priced from a single visit's own snapshot fields and its duration. First, the billable minutes are the larger of the actual worked minutes and the visit's `min_visit_minutes` floor (which defaults to 60 when the client did not override it) — so a visit shorter than the floor is still billed at the floor. Billable hours are those billable minutes divided by 60. Regular hours are the smaller of the billable hours and the `ot_threshold_hours` overtime threshold (which defaults to 8 and must be greater than 0). Overtime hours are the billable hours minus that threshold when positive, and zero otherwise; the overtime multiplier therefore applies strictly above the threshold, so at exactly the threshold there are no overtime hours. The raw labor amount is the regular hours multiplied by `hourly_rate_cents`, plus the overtime hours multiplied by `hourly_rate_cents` and then by the `ot_multiplier` overtime multiplier (which defaults to 1.5 and must be at least 1). This raw labor figure is carried unrounded and is rounded only during invoice assembly.

When a caregiver is matched to a visit, the system sets `estimated_cost_cents` as a provisional labor estimate: it runs the same labor computation but using the scheduled duration (`scheduled_end` minus `scheduled_start`) in place of actual minutes, assumes zero mileage and no add-ons, and rounds the raw labor to whole cents half-up. When the visit is clocked out, the final invoice is assembled from the visit's actual figures. The invoice's `labor_cents` is the raw labor (computed from the actual worked minutes) rounded to whole cents half-up. Its `mileage_cents` is the submitted `mileage_miles` multiplied by the visit's snapshot `mileage_rate_cents_per_mile`, rounded to whole cents half-up. Its `addon_cents` is the sum of `fee_cents` across the visit's `APPROVED` add-ons only (each already an integer). The invoice's `total_cents` is the sum of those three already-rounded line items — `labor_cents` plus `mileage_cents` plus `addon_cents` — honoring the round-per-line-then-sum order fixed in §2.6.

A `CareCoordinator` may cancel a `SCHEDULED` visit outright; this moves it `SCHEDULED → CANCELLED` and triggers hop three of §2.8 (every `CONFIRMED` assignment on it cancels, releasing committed minutes, and any `DRAFT` invoice for it voids). Cancelling a visit that is not `SCHEDULED` is rejected with `ERR_VISIT_NOT_SCHEDULED`.

### 3.6. Invoicing and the Client Balance

Every completed visit yields exactly one `Invoice`, referencing its client through `client_id` and its visit through `visit_id`, that begins in `DRAFT`. A `BillingClerk` finalizes a draft invoice, moving it `DRAFT → FINALIZED` and adding its `total_cents` to the client's `outstanding_balance_cents`. Finalizing an invoice that is not `DRAFT` is rejected with `ERR_INVOICE_NOT_DRAFT`.

A clerk may also void an invoice. A `DRAFT` invoice voids without any balance effect, while a `FINALIZED` invoice being voided subtracts its `total_cents` back out of the client's `outstanding_balance_cents` and triggers the claim-withdrawal cascade of §2.8. Voiding an invoice that is already `VOID` is rejected with `ERR_INVOICE_ALREADY_VOID`. `VOID` is terminal.

The client's `outstanding_balance_cents` is always reconcilable as a derived figure: it is the sum of `total_cents` over that client's `FINALIZED` invoices, minus the sum of `reimbursed_cents` over that client's `APPROVED` reimbursement claims. Draft and void invoices and non-approved claims never contribute. This quantity is recomputed on every invoice finalize or void and on every claim approval or withdrawal.

### 3.7. Long-Term-Care Reimbursement Claims

A `BillingClerk` opens a `ReimbursementClaim` against an invoice, naming the `ltc_policy_id` of the policy to bill; the claim references its invoice through `invoice_id`. The policy must belong to the same client as the invoice, or the request is rejected with `ERR_POLICY_CLIENT_MISMATCH`. At creation the claim snapshots the policy's `benefit_type` and computes its monetary fields, then begins in `DRAFT`.

The eligible base excludes mileage: `eligible_cents` is the invoice's `labor_cents` plus its `addon_cents`. The `reimbursed_cents` the payer covers depends on the snapshot benefit type. Under an `INDEMNITY` policy, the reimbursement is the smaller of the policy's `daily_benefit_cents` and the eligible base — a flat daily benefit capped at what is actually eligible, ignoring the reimbursement rate and daily cap. Under a `REIMBURSEMENT` policy, the reimbursement is the smaller of two quantities: the policy's `reimbursement_rate` multiplied by the eligible base and then rounded to whole cents half-up, and the policy's `daily_cap_cents` per-claim ceiling — ignoring the daily benefit. The claim's `client_responsibility_cents` is the invoice's `total_cents` minus `reimbursed_cents` (note this uses the full invoice total, mileage included, even though mileage was not eligible for reimbursement).

The claim then follows a review lifecycle with a revision cycle. A clerk submits a claim from `DRAFT` or from `NEEDS_INFO`, moving it to `SUBMITTED`; submission requires the referenced invoice to be `FINALIZED` (else `ERR_INVOICE_NOT_FINALIZED`) and the referenced policy to be `ACTIVE` (a policy that has become `EXHAUSTED` is rejected with `ERR_POLICY_EXHAUSTED` at HTTP 402; other non-active policy states surface as `ERR_POLICY_NOT_ACTIVE`). Submitting a claim that is not in `DRAFT` or `NEEDS_INFO` is rejected with `ERR_CLAIM_NOT_SUBMITTABLE`. On a submitted claim the payer may request more information, supplying an optional `note`, which moves it `SUBMITTED → NEEDS_INFO`; the clerk may then resubmit, and this `SUBMITTED → NEEDS_INFO → SUBMITTED` revision cycle may repeat any number of times.

A payer decision on a submitted claim carries an `outcome`. An `APPROVE` outcome moves the claim `SUBMITTED → APPROVED`: it adds the claim's `reimbursed_cents` to the policy's `reimbursed_to_date_cents` — and if that running total reaches the policy's `lifetime_max_cents`, the policy transitions `ACTIVE → EXHAUSTED` — and it subtracts the claim's `reimbursed_cents` from the client's `outstanding_balance_cents`. A `DENY` outcome moves the claim `SUBMITTED → DENIED`. A request-for-information or a decision attempted on a claim that is not `SUBMITTED` is rejected with `ERR_CLAIM_NOT_ACTIONABLE`.

A clerk may withdraw a claim while it is in `DRAFT`, `SUBMITTED`, `NEEDS_INFO`, or `APPROVED`, moving it to `WITHDRAWN`; if the withdrawn claim had been `APPROVED`, its `reimbursed_cents` is reversed back out of both the policy's `reimbursed_to_date_cents` and the client's `outstanding_balance_cents`. Withdrawal is also the target of the invoice-void cascade in §2.8. Attempting to withdraw a claim already in a terminal state is rejected with `ERR_CLAIM_NOT_ACTIONABLE`. The claim's terminal states are `APPROVED`, `DENIED`, and `WITHDRAWN`.

### 3.8. Wellness Checks and the Family Portal

An escalation in the field opens a `WellnessCheck` in `OPEN` status, and this is where the family portal earns its keep. A `FamilyContact` who owns the client may acknowledge an open check, which moves it `OPEN → ACKNOWLEDGED` and records `acknowledged_by` as the acting `X-User-ID`. After acknowledging, that family contact may resolve it, moving it `ACKNOWLEDGED → RESOLVED`. A `CareCoordinator` has a shortcut: a coordinator may resolve a check directly from `OPEN`, moving it `OPEN → RESOLVED` without an intervening acknowledgement. Acknowledging a check that is not `OPEN`, or resolving one from an ineligible state, is rejected with `ERR_WELLNESS_NOT_ACTIONABLE`. Family contacts and coordinators may both read wellness checks, and family contacts may follow their client's visits, invoices, and visit logs through the portal.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource or add a new resource to a collection return `201 Created`. Operations that modify an existing resource — including state transitions such as finalizing, approving, clocking in, or resolving — return `200 OK`. Reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/care/clients` | Create a client with billing configuration | CareCoordinator |
| GET | `/care/clients/{id}` | Fetch a client | CareCoordinator, BillingClerk |
| POST | `/care/clients/{id}/suspend` | Suspend a client; cascades to schedules, visits, assignments | CareCoordinator |
| POST | `/care/clients/{id}/family-contacts` | Register a family-portal contact for a client | CareCoordinator |
| GET | `/care/clients/{id}/family-contacts` | List a client's family contacts | CareCoordinator |
| POST | `/care/clients/{id}/schedules` | Create a recurring schedule for a client | CareCoordinator |
| GET | `/care/clients/{id}/schedules` | List a client's schedules | CareCoordinator |
| POST | `/care/clients/{id}/ltc-policies` | Attach a long-term-care policy to a client | CareCoordinator |
| GET | `/care/clients/{id}/ltc-policies` | List a client's LTC policies | CareCoordinator, BillingClerk |
| POST | `/care/caregivers` | Create a caregiver | CareCoordinator |
| GET | `/care/caregivers/{id}` | Fetch a caregiver | CareCoordinator, BillingClerk |
| POST | `/care/caregivers/{id}/background-checks` | Open a background check for a caregiver | CareCoordinator |
| GET | `/care/caregivers/{id}/background-checks` | List a caregiver's background checks | CareCoordinator |
| POST | `/care/background-checks/{id}/decision` | Record a background-check decision | CareCoordinator |
| POST | `/care/caregivers/{id}/bonds` | Record a bonding coverage window for a caregiver | CareCoordinator |
| GET | `/care/caregivers/{id}/bonds` | List a caregiver's bonds | CareCoordinator |
| GET | `/care/schedules/{id}` | Fetch a schedule | CareCoordinator |
| POST | `/care/schedules/{id}/generate-visits` | Materialize SCHEDULED visits for matching days in a window | CareCoordinator |
| POST | `/care/visits` | Create an ad-hoc visit; snapshots the client's billing rates | CareCoordinator |
| GET | `/care/visits/{id}` | Fetch a visit | CareCoordinator, BillingClerk, Caregiver, FamilyContact |
| GET | `/care/visits` | List/filter visits | CareCoordinator, BillingClerk |
| POST | `/care/visits/{id}/assignments` | Match a caregiver to a visit (OCC-guarded, supersedes prior match) | CareCoordinator |
| POST | `/care/assignments/{id}/cancel` | Cancel a caregiver assignment | CareCoordinator |
| GET | `/care/assignments/{id}` | Fetch an assignment | CareCoordinator |
| GET | `/care/assignments` | List/filter assignments | CareCoordinator |
| POST | `/care/visits/{id}/add-ons` | Request an add-on service on a visit | CareCoordinator, FamilyContact |
| GET | `/care/visits/{id}/add-ons` | List a visit's add-ons | CareCoordinator, FamilyContact |
| POST | `/care/add-ons/{id}/approve` | Approve or reject a requested add-on | CareCoordinator |
| POST | `/care/visits/{id}/clock-in` | Caregiver starts the visit | Caregiver |
| POST | `/care/visits/{id}/clock-out` | Caregiver ends the visit; produces a DRAFT invoice | Caregiver |
| POST | `/care/visits/{id}/escalate` | Caregiver escalates a wellness concern during a visit | Caregiver |
| POST | `/care/visits/{id}/cancel` | Cancel a scheduled visit; cascades to assignments and draft invoice | CareCoordinator |
| POST | `/care/visits/{id}/log` | Append a visit-log entry (append-only) | Caregiver |
| GET | `/care/visits/{id}/log` | List a visit's log entries | CareCoordinator, FamilyContact, Caregiver |
| GET | `/care/wellness-checks/{id}` | Fetch a wellness check | CareCoordinator, FamilyContact |
| GET | `/care/wellness-checks` | List/filter wellness checks | CareCoordinator, FamilyContact |
| POST | `/care/wellness-checks/{id}/acknowledge` | Family contact acknowledges a wellness check | FamilyContact |
| POST | `/care/wellness-checks/{id}/resolve` | Resolve a wellness check | FamilyContact, CareCoordinator |
| GET | `/care/invoices/{id}` | Fetch an invoice | CareCoordinator, BillingClerk, FamilyContact |
| GET | `/care/invoices` | List/filter invoices | CareCoordinator, BillingClerk |
| POST | `/care/invoices/{id}/finalize` | Finalize a draft invoice; debits client balance | BillingClerk |
| POST | `/care/invoices/{id}/void` | Void an invoice; reverses balance and withdraws claims | BillingClerk |
| POST | `/care/invoices/{id}/claims` | Open an LTC reimbursement claim against an invoice | BillingClerk |
| GET | `/care/claims/{id}` | Fetch a reimbursement claim | CareCoordinator, BillingClerk |
| GET | `/care/claims` | List/filter claims | CareCoordinator, BillingClerk |
| POST | `/care/claims/{id}/submit` | Submit a claim (from DRAFT or NEEDS_INFO) | BillingClerk |
| POST | `/care/claims/{id}/request-info` | Payer requests more information on a submitted claim | BillingClerk |
| POST | `/care/claims/{id}/decision` | Record a payer decision on a submitted claim | BillingClerk |
| POST | `/care/claims/{id}/withdraw` | Withdraw a claim | BillingClerk |
| POST | `/_clock/set_current_utc` | Set the server's logical clock (test-driving) | CareCoordinator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_RESOURCE_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_ENUM` | 422 |
| `ERR_STALE_VISIT_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_VISIT_NOT_SCHEDULED` | 409 |
| `ERR_VISIT_NOT_IN_PROGRESS` | 409 |
| `ERR_INVOICE_NOT_DRAFT` | 409 |
| `ERR_INVOICE_NOT_FINALIZED` | 409 |
| `ERR_INVOICE_ALREADY_VOID` | 409 |
| `ERR_CLAIM_NOT_SUBMITTABLE` | 409 |
| `ERR_CLAIM_NOT_ACTIONABLE` | 409 |
| `ERR_ADDON_NOT_REQUESTED` | 409 |
| `ERR_WELLNESS_NOT_ACTIONABLE` | 409 |
| `ERR_SCHEDULE_NOT_ACTIVE` | 409 |
| `ERR_CLIENT_NOT_ACTIVE` | 409 |
| `ERR_CAREGIVER_NOT_CLEARED` | 409 |
| `ERR_CAREGIVER_NOT_BONDED` | 409 |
| `ERR_POLICY_CLIENT_MISMATCH` | 409 |
| `ERR_CAREGIVER_DOUBLE_BOOKED` | 409 |
| `ERR_CLIENT_VISIT_OVERLAP` | 409 |
| `ERR_INVALID_TIME_RANGE` | 422 |
| `ERR_POLICY_EXHAUSTED` | 402 |
| `ERR_POLICY_NOT_ACTIVE` | 409 |
