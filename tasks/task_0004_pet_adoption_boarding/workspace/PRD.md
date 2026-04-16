# Pet Adoption and Boarding Platform API — Product Requirements Document

## 1. Introduction

Animal welfare shelters sit at the intersection of three distinct workflows that rarely fit into a single off-the-shelf system: moving animals through intake, adoption, and eventually into a forever home; temporarily boarding animals on behalf of the broader community; and keeping an auditable medical and compliance record for every creature in their care. This document specifies a REST API for a unified Pet Adoption and Boarding Platform that serves all three concerns through one coherent data model.

The platform is designed around the realities of how a shelter actually operates. A case worker registers the animals and interviews prospective adopters; a shelter manager signs off on the outcomes that affect the shelter's reputation and its finances; a veterinarian keeps the medical record clean. Because the same people play these roles every day, the system must enforce separation of duties programmatically — the person who reviews an application cannot be the person who approves it, and routine medical interventions must be distinguishable from managerial interventions in the audit trail.

The API is built as a workflow-orchestration platform with an immediate-consistency contract: every write is durable before the response returns, every computed field is recomputed synchronously when its inputs change, and every concurrent conflict is detected at commit time rather than swept under the rug. Compliance gates — vaccination checks, active holds, segregation-of-duties — are consulted at each state transition, not only at submission, so that a fact which becomes true mid-workflow (an expiring vaccine, a newly discovered behavior incident) blocks the next step even if earlier steps had already cleared.

## 2. Global Specifications & System-Wide Principles

### 2.1. Authentication and Role Model

Every request to the API must carry two request headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, one of the exact strings `ShelterManager`, `CaseWorker`, or `Veterinarian`. Requests that omit either header, or carry a role outside this enumeration, are rejected with `ERR_AUTH_REQUIRED` and HTTP 401. A caller whose role is present and valid but is not granted the requested operation by the RBAC matrix receives `ERR_FORBIDDEN` with HTTP 403.

A **ShelterManager** is a senior administrator responsible for shelter lifecycle transitions, fee schedules, settlement, adoption approval and rejection, boarding confirmation and cancellation, invoice refund and void, resolution of compliance holds, and adopter blacklisting. A **CaseWorker** handles day-to-day frontline work: animal intake, adopter registration, moving applications through the review pipeline up to but not including approval, home visit scheduling and completion, boarding check-in and check-out, and recording payments. A **Veterinarian** owns medical artifacts — vaccination records — and may create compliance holds for medical reasons. Compliance-hold creation is the only write operation shared between two roles (ShelterManager and Veterinarian). Segregation of duties is enforced further at the application level: the reviewer of an application may not also be the approver, which is checked against the `reviewer_id` pinned at `start-review` time.

### 2.2. API Response Structure

Every successful response is wrapped in a standard envelope with a `meta` block and a typed `data` payload. A successful single-resource response looks like this:

```json
{
  "meta": {
    "api_request_id": "req_petcare_8F3A1B9CE24D",
    "api_request_timestamp": "2026-04-16T09:14:27.842Z"
  },
  "response_type": "object",
  "data": {
    "id": "animal_a7c2f19b0e4d4a6c8f1d",
    "created_at": "2026-03-02T11:05:00.000Z",
    "updated_at": "2026-04-10T08:21:11.337Z",
    "version": 3,
    "name": "Biscuit"
  }
}
```

A list response adds the four pagination fields to `meta`:

```json
{
  "meta": {
    "api_request_id": "req_petcare_0C8D7A3EF165",
    "api_request_timestamp": "2026-04-16T09:15:02.118Z",
    "limit": 20,
    "offset": 0,
    "total_count": 47,
    "has_more": true
  },
  "response_type": "array",
  "data": [ /* 20 resource objects */ ]
}
```

An error response reuses the same envelope but sets `response_type` to `"error"` and delivers the fault through the `data` payload:

```json
{
  "meta": {
    "api_request_id": "req_petcare_5E2A7F44B8C1",
    "api_request_timestamp": "2026-04-16T09:15:42.003Z"
  },
  "response_type": "error",
  "data": {
    "error_id": "ERR_COMPLIANCE_HOLD_ACTIVE",
    "message": "Animal has an ACTIVE ComplianceHold of severity HIGH or CRITICAL."
  }
}
```

Each envelope field has a defined semantic. `api_request_id` is a server-generated unique identifier for the request, used for observability and log correlation; clients must treat it as opaque. `api_request_timestamp` is the server's view of when the response was produced, expressed as ISO 8601 UTC with exactly three fractional-second digits. `response_type` is the enumerated string `"object"`, `"array"`, or `"error"` and tells the client how to interpret `data`. `data` is the business payload: an object for single-resource reads and writes, an array for list reads, or an object with `error_id` and `message` for errors. The pagination keys `limit`, `offset`, `total_count`, and `has_more` appear inside `meta` only for list endpoints — `limit` and `offset` echo the applied values, `total_count` reports the total matching rows, and `has_more` is a boolean that is true when `offset + limit < total_count`.

### 2.3. Pagination and Ordering

List endpoints accept `limit` and `offset` query parameters. `limit` defaults to 20, with a minimum of 1 and a maximum of 100; values outside this range yield `ERR_INVALID_REQUEST` (HTTP 422). `offset` defaults to 0 and must be non-negative. Collections are always returned sorted by `created_at` ascending, so that pagination is stable for a client scrolling forward in time. The pagination fields `limit`, `offset`, `total_count`, and `has_more` appear on list responses only — single-resource reads do not include them.

### 2.4. Shared Resource Contract

Most resources carry a stable set of properties beyond their business fields. `id` is a server-assigned UUID string and immutable. `created_at` is an ISO 8601 UTC timestamp with three fractional digits, written at insertion time and never rewritten. `updated_at` is refreshed on every mutation and has the same format; `version` is an integer that starts at 1 and increments by exactly one on each successful mutation. Two resources in this system deliberately omit `updated_at` and `version`: `VaccinationRecord` (an append-only medical artifact that is never edited) and `BoardingMatch` (a derived assignment artifact that is either live or voided, never mutated in place). A `SettlementBatch` similarly lacks the pair, because once approved the batch is frozen and the only subsequent change is a single terminal `mark-paid` transition that does not invite optimistic-concurrency races.

### 2.5. Optimistic Concurrency Control

Mutations that accept a body may include the current resource `version`. When a PATCH request carries `version` and that value no longer matches the stored resource, the server responds with `ERR_VERSION_CONFLICT` and leaves the resource unchanged. Clients that legitimately wish to bypass the check may omit `version` from the request body. A separate family of stale-data errors exists for the adoption approval path: the approval step re-checks the `animal_version_pinned` and `adopter_version_pinned` captured when the application entered review, returning `ERR_STALE_ANIMAL_DATA` or `ERR_STALE_ADOPTER_DATA` respectively if either underlying resource has moved on in the interim.

### 2.6. Hierarchical Resource Addressing

URL paths are validated strictly left-to-right. A request to a nested or scoped endpoint first verifies the outer ID — `ERR_SHELTER_NOT_FOUND`, `ERR_ANIMAL_NOT_FOUND`, `ERR_ADOPTER_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_HOME_VISIT_NOT_FOUND`, `ERR_RESERVATION_NOT_FOUND`, `ERR_BOARDING_MATCH_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_HOLD_NOT_FOUND`, `ERR_FEE_SCHEDULE_NOT_FOUND`, `ERR_VACCINATION_RECORD_NOT_FOUND`, or `ERR_SETTLEMENT_BATCH_NOT_FOUND` — before body validation runs. The same 404 codes apply when a foreign-key reference in a request body fails to resolve.

### 2.7. Fiscal Precision

All monetary amounts are stored as integer cents. Every calculation that multiplies by a rate or a duration applies `floor` rounding at the multiplication step, so that fractional cents are discarded in favour of the payer. Tax is the sole exception: the tax amount is computed using banker-safe `round_half_up` to the nearest whole cent, ensuring that the government line is never understated. The `compliance_score` reported on a shelter is a non-monetary percentage computed to two decimal places with the same `round_half_up` rule.

### 2.8. Compliance Gates at Every Transition

Two categories of check recur throughout the business logic. The first is vaccination compliance — an animal's `vaccination_compliant` flag is recomputed on vaccination record creation and consulted at every step where an animal would be exposed to staff or other animals. The second is the presence of active compliance holds — an `ACTIVE` `ComplianceHold` of severity `HIGH` or `CRITICAL` blocks `make-available`, boarding confirm, boarding check-in, and adoption approval with `ERR_COMPLIANCE_HOLD_ACTIVE`. Each transition re-evaluates these gates at commit time rather than at request receipt, so that a gate which closes mid-flight is respected on first-writer-wins terms.

### 2.9. Immediate Consistency

Every derived field the API exposes — `vaccination_compliant`, `adoption_eligible`, `active_hold_count`, `current_boarding_count`, `adoption_count`, `compliance_score`, `revenue_pending_cents`, `revenue_settled_cents`, `planned_duration_days`, `actual_duration_days`, `balance_due_cents`, `is_currently_valid`, `is_currently_active`, `latest_home_visit_id`, `latest_home_visit_result`, and the like — is recomputed synchronously before the response returns. There is no eventual-consistency window. A read issued immediately after a write must reflect the write.

## 3. Business Logic & Workflows

### 3.1. Shelters, Their Lifecycle, and Fee Schedules

A new shelter is created via an authenticated `ShelterManager` POST that supplies `name`, `address`, `contact_email`, `boarding_capacity`, and `tax_rate`. The `boarding_capacity` must be at least 1 and the `tax_rate` must fall in the inclusive range 0.0 through 0.30; violations produce `ERR_INVALID_REQUEST`. On success, the new shelter is placed in `OPEN` state with all counters — `current_boarding_count`, `adoption_count`, `revenue_pending_cents`, `revenue_settled_cents` — initialized to zero and `compliance_score` initialized to 100.00. A shelter's `status` flips between `OPEN` and `SUSPENDED` through the `/suspend` and `/reopen` actions; both require the `ShelterManager` role. A suspended shelter rejects new adoption applications and new boarding reservations with `ERR_SHELTER_SUSPENDED`, and any application approval against a suspended shelter fails for the same reason, even though in-progress applications and reservations may continue to idle. Reopening is refused with `ERR_CRITICAL_HOLD_PRESENT` if any animal at the shelter still carries an `ACTIVE` `CRITICAL` `ComplianceHold`.

Price lists are expressed as `FeeSchedule` rows keyed by `shelter_id`, `fee_type`, and `species`. The enumerated `fee_type` is one of `ADOPTION_BASE`, `BOARDING_DAILY`, `SPECIAL_NEEDS_SURCHARGE`, or `LOYALTY_DISCOUNT_PCT`, and the species is one of `DOG`, `CAT`, `RABBIT`, `BIRD`, `OTHER`, or the sentinel value `ALL` used for shelter-wide rules. Each row carries `amount_cents` — interpreted as a whole-cent amount for currency-denominated rows and as an integer percentage (0–100) for `LOYALTY_DISCOUNT_PCT`. A validity interval is expressed via `effective_from` (inclusive) and optional `effective_to` (exclusive; a null value means open-ended), and the read-side field `is_currently_active` is true when the current moment lies within that interval. A `FeeSchedule` creation request whose `effective_to` is not strictly greater than `effective_from` is rejected with `ERR_INVALID_DATES`. When the adoption or boarding calculations need a species-specific value but find none, they fall back to the `ALL` row.

### 3.2. Animal Intake, Medical History, and Availability

A `CaseWorker` registers a new animal with `shelter_id`, `name`, `species` (one of `DOG`, `CAT`, `RABBIT`, `BIRD`, `OTHER`), `breed`, `age_months` (non-negative integer), `weight_kg` (strictly positive number), `temperament` (one of `CALM`, `MODERATE`, `ENERGETIC`, `AGGRESSIVE`), and an optional `special_needs` array whose tags may include `MEDICATION_REQUIRED`, `DIET_RESTRICTED`, `MOBILITY_LIMITED`, and the like. On creation the animal enters `INTAKE` status and the system derives two early signals — `vaccination_compliant` and `boarding_zone_hint` — that inform subsequent flows. A PATCH endpoint allows updating `name`, `breed`, `age_months`, `weight_kg`, `temperament`, and `special_needs`, with `version` honoured for OCC; after any edit `adoption_eligible` and `boarding_zone_hint` are recomputed.

Medical history accumulates through `VaccinationRecord` rows created exclusively by `Veterinarian`s. A record carries `animal_id`, `vaccine_name` (one of `RABIES`, `DHPP`, `FVRCP`, `BORDETELLA`, `RHDV`, or `OTHER`), `administered_date`, `expiry_date`, and `batch_number`; the `veterinarian_id` is captured from `X-User-ID` server-side, and the derived `is_currently_valid` mirrors whether `expiry_date` exceeds the present moment. A request in which `expiry_date` is not strictly greater than `administered_date`, or in which `administered_date` sits in the future, is rejected with `ERR_INVALID_DATES`. Vaccination records are append-only — they have no `updated_at` or `version` — so corrections are made by superseding a record with a new one.

The `vaccination_compliant` flag is true for an animal if and only if, for every vaccine in the species-specific required set, at least one `VaccinationRecord` exists whose `expiry_date` is strictly greater than the current moment. For dogs the adoption-time required set is `RABIES` and `DHPP`; cats require `RABIES` and `FVRCP`; rabbits require `RHDV`; birds and `OTHER` have no mandatory vaccines. A `make-available` call by a `CaseWorker` drives the animal from `INTAKE` to `AVAILABLE`, but only if the animal is currently in `INTAKE`, `vaccination_compliant` is true, the owning shelter is `OPEN`, and no `ACTIVE` `ComplianceHold` of severity `HIGH` or `CRITICAL` is in force; these failures emit `ERR_VACCINATION_NOT_COMPLIANT`, `ERR_SHELTER_SUSPENDED`, and `ERR_COMPLIANCE_HOLD_ACTIVE` respectively. An animal whose `status` is `AVAILABLE` may move to `ADOPTION_PENDING` through a system-driven transition when one of its adoption applications is approved, and back to `AVAILABLE` if that application later ends in `REJECTED` or `WITHDRAWN` before `COMPLETED`. Terminal adoption drops the animal into `ADOPTED`. Two other system-driven transitions govern the boarding side of the life cycle: `AVAILABLE` to `BOARDING` on check-in, and `BOARDING` to `AVAILABLE` on check-out. Finally, any `ACTIVE` hold of severity `HIGH` or `CRITICAL` can push an animal into `UNAVAILABLE` until the hold is resolved.

The read-side `adoption_eligible` is true exactly when the animal is in `AVAILABLE`, is vaccination compliant, and has no `ACTIVE` hold of severity `HIGH` or `CRITICAL`. The read-side `active_hold_count` tracks the number of `ACTIVE` holds for the animal.

### 3.3. Adopters and the Application Pipeline

An `Adopter` is registered by a `CaseWorker` with `shelter_id`, `full_name`, `email`, `phone`, `home_type` (`HOUSE`, `APARTMENT`, `FARM`, or `OTHER`), `has_yard`, `has_other_pets`, and an optional `other_pet_species` array. The email is unique per shelter. Editable fields may be patched later with OCC; the `adoption_history_count`, `latest_home_visit_id`, and `latest_home_visit_result` fields are all read-side derivations surfaced for operator convenience. A `ShelterManager` may move an adopter to `BLACKLISTED` via `/blacklist`, supplying a `reason`; doing so also cascades every one of that adopter's applications whose status is among `SUBMITTED`, `UNDER_REVIEW`, `HOME_VISIT_REQUIRED`, `HOME_VISIT_SCHEDULED`, or `REVIEWED` into `WITHDRAWN`, along with the usual cascade effects on linked home visits and animals.

A new application is opened by a `CaseWorker` with an `animal_id`, `adopter_id`, and free-form `reason`. The `shelter_id` is inherited from the animal, and the system computes the derived `requires_home_visit` flag, which is true if the animal's `species` is `DOG` or its `weight_kg` is at least 25. The application's `status` begins in `SUBMITTED`. To progress, a `CaseWorker` calls `/start-review`; this transition requires the application to be `SUBMITTED`, the animal to be `AVAILABLE`, the adopter to be `ACTIVE` (not `BLACKLISTED`), and the owning shelter to be `OPEN`, with failures mapped to `ERR_INVALID_STATE`, `ERR_ANIMAL_NOT_AVAILABLE`, `ERR_ADOPTER_BLACKLISTED`, and `ERR_SHELTER_SUSPENDED` respectively. Upon `UNDER_REVIEW` the system stamps `reviewer_id` with the caller's `X-User-ID` and pins `animal_version_pinned` and `adopter_version_pinned` to the then-current versions of the animal and adopter — these pinned values become part of the approval contract.

From `UNDER_REVIEW` there are three paths. If `requires_home_visit` is true, the reviewer calls `/require-home-visit` to move to `HOME_VISIT_REQUIRED`; if the reviewer tries to shortcut directly via `/complete-review` on such an application, the system responds with `ERR_HOME_VISIT_REQUIRED`. Otherwise the reviewer calls `/complete-review` and the application advances to `REVIEWED`. The third path is `/withdraw`, which is permitted as long as the application is not yet `APPROVED`, `COMPLETED`, or `REJECTED`; withdrawal also reverts an animal from `ADOPTION_PENDING` back to `AVAILABLE` if applicable, and cancels any scheduled home visit. Only the stamped `reviewer_id` may execute `/require-home-visit` or `/complete-review`; any other caller receives `ERR_REVIEWER_MISMATCH`.

Once an application reaches `REVIEWED`, a `ShelterManager` approves it with `/approve`. Approval enforces four independent checks in addition to role: the caller's `X-User-ID` must differ from `reviewer_id` (`ERR_SELF_APPROVAL`); the animal's current `version` must match `animal_version_pinned` (`ERR_STALE_ANIMAL_DATA`); the adopter's current `version` must match `adopter_version_pinned` (`ERR_STALE_ADOPTER_DATA`); and the animal must still be `AVAILABLE` at the moment of commit (`ERR_ANIMAL_NOT_AVAILABLE`), which is where two simultaneous approvals for the same animal resolve to exactly one winner. On success the application moves to `APPROVED`, `approver_id` is captured, the animal transitions from `AVAILABLE` to `ADOPTION_PENDING`, and a new adoption `FeeInvoice` is created and linked via `fee_invoice_id`. Rejection via `/reject` requires the same segregation-of-duties check and a mandatory `rejection_reason` string in the request body; omitting it returns `ERR_INVALID_REQUEST`. Completion via `/complete` is the final lap — it is run by a `CaseWorker` once the fee invoice has been paid; if the invoice is not yet `PAID`, `ERR_FEE_NOT_PAID` is returned. Completion moves the animal to `ADOPTED`, increments `shelter.adoption_count`, and increments `adopter.adoption_history_count`.

### 3.4. The Home Visit Subworkflow

A home visit is a small state machine attached to an application that requires one. A `CaseWorker` calls `POST /petcare/home-visits` with an `application_id` and a future `scheduled_date` — the date must be strictly greater than the current moment, or the request fails with `ERR_INVALID_DATES`. The system captures `case_worker_id` from `X-User-ID`, derives `adopter_id` from the application, places the visit in `SCHEDULED`, and pivots the application from `HOME_VISIT_REQUIRED` to `HOME_VISIT_SCHEDULED`, recording `home_visit_id` on the application.

When the visit is carried out, the same case worker completes it via `/complete`, which requires `X-User-ID` to equal the pinned `case_worker_id` (`ERR_ASSESSOR_MISMATCH`) and requires a request body containing all four assessment booleans — `yard_adequate`, `space_adequate`, `safety_hazards_found`, `existing_pets_compatible` — together with free-form `notes`. The system computes `overall_score` from the four booleans using a weighted rubric and derives `result` from the score. Under the standard rubric an adequate yard contributes 25 points, an adequate space contributes 30, the absence of safety hazards contributes 25, and pet compatibility contributes 20; the sum is capped at 100. A variant applies when the animal's `species` is `CAT`, `BIRD`, or `RABBIT`: the yard weight drops to 0 and the space weight rises to 55, because such animals live indoors and the yard is not relevant. Regardless of variant, a `result` of `PASS` requires a score of at least 70, a `CONDITIONAL_PASS` covers 50 through 69, and anything below 50 is `FAIL`. A `PASS` or `CONDITIONAL_PASS` moves the application from `HOME_VISIT_SCHEDULED` to `REVIEWED`; a `FAIL` moves it to `REJECTED` with `rejection_reason` set to `'Home visit failed'`. On completion the adopter's `latest_home_visit_id` and `latest_home_visit_result` are updated.

A scheduled visit can also be cancelled by a `CaseWorker` via `/cancel`, which reverts the application from `HOME_VISIT_SCHEDULED` back to `HOME_VISIT_REQUIRED` and clears `home_visit_id`. Visits whose `scheduled_date` has slipped into the past may be swept by the `ShelterManager` via `POST /petcare/home-visits/expire-due`, which transitions any `SCHEDULED` visit with a past `scheduled_date` into `EXPIRED` and likewise reverts the linked application. A terminal visit (`COMPLETED`, `CANCELLED`, or `EXPIRED`) does not change further.

### 3.5. Boarding Reservations, Matching, and Care

A `CaseWorker` opens a boarding request with `shelter_id`, `animal_id`, `owner_name`, `owner_contact`, `check_in_date`, `check_out_date`, and optional `special_instructions`. The system computes `planned_duration_days` as the day-ceiling of `(check_out_date - check_in_date)` and places the reservation in `REQUESTED`. The dates must satisfy `check_out_date > check_in_date` and `check_in_date >= current day`; violations yield `ERR_INVALID_DATES`.

Confirmation is a `ShelterManager` responsibility. On `/confirm`, the system enforces five gates at commit time: the shelter must be `OPEN` (`ERR_SHELTER_SUSPENDED`); the animal must pass the boarding variant of the vaccination check (`ERR_VACCINATION_NOT_COMPLIANT`), which for dogs adds `BORDETELLA` to the adoption-time set so that a dog passing adoption-compliance may still fail boarding-compliance if its `BORDETELLA` has lapsed; the animal must have no `ACTIVE` `HIGH`/`CRITICAL` hold (`ERR_COMPLIANCE_HOLD_ACTIVE`); the count of `CONFIRMED` plus `CHECKED_IN` reservations at the shelter must stay strictly below `boarding_capacity` (`ERR_BOARDING_CAPACITY_FULL`) — this is the only place where capacity is checked, and it is checked on commit, so two races at the capacity boundary serialize to exactly one winner; and no existing `CONFIRMED` or `CHECKED_IN` reservation for the same animal may overlap the requested `[check_in_date, check_out_date)` interval (`ERR_BOARDING_DATE_OVERLAP`). Successful confirmation creates a `BoardingMatch` and assigns `boarding_match_id`, and also creates a boarding `FeeInvoice` and assigns `fee_invoice_id`.

The `BoardingMatch` captures the compatibility story of placing this animal next to the shelter's current boarders. The `compatibility_score` starts from a base of 100 and is penalized for every animal already `CHECKED_IN` at the same shelter: each species mismatch costs 10 points, any involvement of an `AGGRESSIVE` temperament (either incoming or present) costs 25 points, a direct clash between `ENERGETIC` and `CALM` temperaments costs 15 points, and each special-needs tag on the incoming animal costs an additional 5 points. The score floor is 0. Independent of the score, `boarding_zone` is assigned deterministically: an `AGGRESSIVE` animal goes to `ISOLATION`, an `ENERGETIC` animal goes to `ACTIVE`, a cat, bird, or rabbit goes to `SMALL_ANIMAL`, and everything else goes to `GENERAL`. The match also carries `reservation_id`, `animal_id`, `shelter_id`, `voided_at`, and an informational `conflict_flags` array — tags like `SPECIES_MISMATCH`, `AGGRESSIVE_NEAR_CALM`, or `OVER_CAPACITY_RISK` that surface the reasons for the score.

Check-in is performed by a `CaseWorker` via `/check-in`. The reservation must be `CONFIRMED`, the animal must still be vaccination-compliant under the boarding rule, there must be no `ACTIVE` `HIGH`/`CRITICAL` hold, and the current time must be at least the `check_in_date` — failure returns `ERR_TOO_EARLY_TO_CHECK_IN`. On success the system stamps `actual_check_in`, increments `shelter.current_boarding_count`, and transitions the animal from `AVAILABLE` to `BOARDING`. Check-out via `/check-out` stamps `actual_check_out`, recomputes `actual_duration_days`, rewrites the invoice line items using the final boarding-fee variant (see §3.6), decrements `shelter.current_boarding_count`, and moves the animal back to `AVAILABLE`. A reservation in `REQUESTED` or `CONFIRMED` may be cancelled by a `ShelterManager` via `/cancel`, which marks any existing `BoardingMatch` with `voided_at`, voids the invoice if it is still `ISSUED`, and makes an explicit refund necessary if the invoice is already `PAID` or `PARTIALLY_PAID` — the platform never silently refunds money.

### 3.6. Fees, Invoices, and Payment

A `FeeInvoice` is created in one of two places: when an adoption application is approved (`reference_type` = `ADOPTION`, `reference_id` = the application's id), or when a boarding reservation is confirmed (`reference_type` = `BOARDING`, `reference_id` = the reservation's id). The invoice starts in `DRAFT` conceptually but is written directly into `ISSUED` with the computed `line_items`, `subtotal_cents`, `discount_cents`, `tax_cents`, and `total_amount_cents` materialized at creation. `paid_amount_cents` and `refund_amount_cents` begin at zero, and `balance_due_cents` is continuously derived as the greater of zero and `total_amount_cents - paid_amount_cents`. The `settlement_batch_id` starts null.

The **adoption fee** is computed as follows: the system looks up a `FeeSchedule` row of type `ADOPTION_BASE` for the shelter that is currently active and matches the animal's species, falling back to an `ALL` row if no species-specific row exists. If the animal is a senior — that is, its `age_months` is at least seven years' worth of months — the base is cut in half via `floor` multiplication. A `SPECIAL_NEEDS_SURCHARGE` row, if present, is multiplied by the number of entries in `special_needs` to produce a surcharge, and the subtotal is `base + surcharge`. A loyalty discount is applied to adopters with `adoption_history_count` at or above a two-adoption loyalty threshold: the platform looks up a `LOYALTY_DISCOUNT_PCT` row (species `ALL`), treats its `amount_cents` as an integer percentage between 0 and 100, and sets `discount_cents` to the `floor` of `subtotal_cents * percentage / 100`. Tax is then `round_half_up((subtotal_cents - discount_cents) * shelter.tax_rate)`, and `total_amount_cents` is `subtotal_cents - discount_cents + tax_cents`. A provisional variant of this calculation runs when an application is fetched in any pre-approval status and uses whatever `FeeSchedule` rows are active at read time — that preview may shift if schedules change before approval, but the final invoice pins its line items immutably at the moment of approval.

The **boarding fee** is built daily. A `BOARDING_DAILY` row (species-specific with `ALL` fallback) defines the daily rate; a `SPECIAL_NEEDS_SURCHARGE` row contributes once per tag per day to produce an `effective_daily` amount. Long stays are rewarded: if the duration exceeds two full weeks, the effective daily rate is multiplied by a 0.9 long-stay rate with `floor`. The subtotal is the effective daily multiplied by the duration, `discount_cents` is zero, tax is `round_half_up(subtotal_cents * shelter.tax_rate)`, and the total is `subtotal_cents + tax_cents`. The boarding calculation runs twice: once at `/confirm` (provisional variant, using `planned_duration_days`), and once again at `/check-out` (final variant, using `actual_duration_days`) where the invoice line items are overwritten. If the recomputed total is less than what the owner has already paid, the invoice still moves to `PAID` but `paid_amount_cents` is reduced to the new total, and the difference is recorded as a credit line item with a negative amount.

Payments are recorded by a `CaseWorker` via `/pay`, which accepts `amount_cents` in the request body. The amount must be strictly positive and no greater than `balance_due_cents`, or the system returns `ERR_PAYMENT_AMOUNT_INVALID`. If the cumulative `paid_amount_cents` after the payment equals `total_amount_cents`, the invoice moves to `PAID` and `shelter.revenue_pending_cents` rises by `total_amount_cents` until the invoice is settled; otherwise the invoice is `PARTIALLY_PAID`. A `ShelterManager` may refund a `PAID` or `PARTIALLY_PAID` invoice via `/refund`, but only if the invoice has not yet been attached to an `APPROVED` or `PAID` settlement batch — otherwise the request is denied with `ERR_INVOICE_ALREADY_SETTLED`. A refund sets `refund_amount_cents` equal to `paid_amount_cents` and reduces `shelter.revenue_pending_cents` accordingly. A `DRAFT` or `ISSUED` invoice with zero payments may be voided via `/void`; an invoice that has received any money cannot be voided until the money is refunded (`ERR_INVOICE_HAS_PAYMENTS`).

### 3.7. Compliance Holds

A `ComplianceHold` is a flag on an animal that restricts downstream operations. It is created by either a `Veterinarian` or a `ShelterManager` with `animal_id`, `hold_type` (one of `VACCINATION_OVERDUE`, `HEALTH_CONCERN`, `BEHAVIOR_INCIDENT`, or `QUARANTINE`), `severity` (`LOW`, `MEDIUM`, `HIGH`, or `CRITICAL`), and a free-form `reason`. The system captures `imposed_by` from `X-User-ID` and records `imposed_role` as `VETERINARIAN` or `SHELTER_MANAGER` so that medical and administrative interventions remain distinguishable in the audit trail. A new hold begins in `ACTIVE` and increments the animal's `active_hold_count`; a hold of severity `HIGH` or `CRITICAL` may also drive the animal into `UNAVAILABLE` if it was previously `AVAILABLE` or `BOARDING`. While the animal is `UNAVAILABLE`, `adoption_eligible` is false and any in-flight boarding reservation remains as it is — the animal continues to receive care.

Only a `ShelterManager` may resolve a hold, via `/resolve`, supplying `resolution_notes` in the request body (omission yields `ERR_INVALID_REQUEST`). Resolution records `resolved_by`, decrements `active_hold_count`, recomputes `adoption_eligible`, and — if the resolved hold was the last `HIGH`/`CRITICAL` hold keeping the animal `UNAVAILABLE` — transitions the animal back to `AVAILABLE`. The shelter's `compliance_score` is also recomputed; its formula anchors at 100 minus a five-point penalty for each `ACTIVE` hold across all of the shelter's non-adopted animals, scaled down by the fraction of those animals that are currently vaccination-compliant. In concrete terms, if 8 of 10 non-adopted animals are vaccination-compliant and 3 active holds remain, the base is 80 and the penalty is 15, producing a `compliance_score` of 65.00 — stored to two decimal places with `round_half_up`. If the shelter has no non-adopted animals at all, the score is 100.00 by definition.

### 3.8. Settlement

Periodic settlement aggregates paid and refunded invoices into a `SettlementBatch`. A `ShelterManager` creates a batch by specifying `shelter_id`, `period_start`, and `period_end`; the period must satisfy `period_end > period_start` (`ERR_INVALID_REQUEST`). The system then walks eligible invoices in chronological order of their state change — invoices belonging to this shelter, whose `settlement_batch_id` is null, whose state is `PAID` (with a pay timestamp in the period) or `REFUNDED` (with a refund timestamp in the period). Their ids are collected in `invoice_ids`. The `gross_amount_cents` is the sum of `total_amount_cents` for the `PAID` invoices in the batch; the `refund_amount_cents` is the sum of `refund_amount_cents` for the `REFUNDED` invoices; and `net_amount_cents` is `max(0, gross - refund)`. A pure gross-only batch occurs when no refunds fall in the period; a clawback scenario, in which refunds exceed paid totals because a refund spans a prior period, still yields a batch with `net_amount_cents` of zero and pushes the residual into the shelter's `revenue_pending_cents` as a debit.

The batch begins in `DRAFT`. Approval via `/approve` is a `ShelterManager` operation that rechecks every invoice: if any invoice included in `invoice_ids` is no longer in `PAID` status — typically because it was refunded in between — the approval fails with `ERR_INVOICE_STATUS_CHANGED` and the batch remains `DRAFT`. On success `approved_by` is stamped, each included invoice has its `settlement_batch_id` set, `shelter.revenue_settled_cents` rises by `net_amount_cents`, and `revenue_pending_cents` falls by the same amount. `/mark-paid` moves an `APPROVED` batch to the terminal `PAID` state. Because `SettlementBatch` does not carry `updated_at` or `version`, its lifecycle is modelled as a strict forward progression.

## 4. Endpoint Definitions

Mutation endpoints that create a new resource return HTTP 201 (`POST /petcare/shelters`, `POST /petcare/animals`, `POST /petcare/vaccination-records`, `POST /petcare/adopters`, `POST /petcare/adoption-applications`, `POST /petcare/home-visits`, `POST /petcare/boarding-reservations`, `POST /petcare/compliance-holds`, `POST /petcare/fee-schedules`, `POST /petcare/settlement-batches`). All other successful writes and every read return HTTP 200. Path parameters (`shelter_id`, `animal_id`, `vaccination_record_id`, `adopter_id`, `application_id`, `home_visit_id`, `reservation_id`, `boarding_match_id`, `invoice_id`, `hold_id`, `fee_schedule_id`, `batch_id`) are validated left-to-right, and list endpoints accept the common `limit` and `offset` query parameters in addition to any filters noted for that resource.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /petcare/shelters | Create a new shelter | ShelterManager |
| GET | /petcare/shelters | List all shelters | ShelterManager, CaseWorker, Veterinarian |
| GET | /petcare/shelters/:shelter_id | Get a specific shelter | ShelterManager, CaseWorker, Veterinarian |
| POST | /petcare/shelters/:shelter_id/suspend | Suspend a shelter | ShelterManager |
| POST | /petcare/shelters/:shelter_id/reopen | Reopen a suspended shelter | ShelterManager |
| POST | /petcare/animals | Register a new animal | CaseWorker |
| GET | /petcare/animals | List animals with filtering | ShelterManager, CaseWorker, Veterinarian |
| GET | /petcare/animals/:animal_id | Get a specific animal | ShelterManager, CaseWorker, Veterinarian |
| PATCH | /petcare/animals/:animal_id | Update editable fields on an animal | CaseWorker |
| POST | /petcare/animals/:animal_id/make-available | Transition an animal from INTAKE to AVAILABLE | CaseWorker |
| POST | /petcare/vaccination-records | Record a vaccination for an animal | Veterinarian |
| GET | /petcare/vaccination-records | List vaccination records | ShelterManager, CaseWorker, Veterinarian |
| GET | /petcare/vaccination-records/:vaccination_record_id | Get a specific vaccination record | ShelterManager, CaseWorker, Veterinarian |
| POST | /petcare/adopters | Register a new adopter | CaseWorker |
| GET | /petcare/adopters | List adopters with filtering | ShelterManager, CaseWorker |
| GET | /petcare/adopters/:adopter_id | Get a specific adopter | ShelterManager, CaseWorker |
| PATCH | /petcare/adopters/:adopter_id | Update editable fields on an adopter | CaseWorker |
| POST | /petcare/adopters/:adopter_id/blacklist | Mark an adopter as BLACKLISTED | ShelterManager |
| POST | /petcare/adoption-applications | Submit a new adoption application | CaseWorker |
| GET | /petcare/adoption-applications | List adoption applications with filtering | ShelterManager, CaseWorker |
| GET | /petcare/adoption-applications/:application_id | Get a specific adoption application | ShelterManager, CaseWorker |
| POST | /petcare/adoption-applications/:application_id/start-review | Begin reviewing an application | CaseWorker |
| POST | /petcare/adoption-applications/:application_id/require-home-visit | Mark the application as requiring a home visit | CaseWorker |
| POST | /petcare/adoption-applications/:application_id/complete-review | Advance application to REVIEWED | CaseWorker |
| POST | /petcare/adoption-applications/:application_id/approve | Approve a reviewed application | ShelterManager |
| POST | /petcare/adoption-applications/:application_id/reject | Reject a reviewed application | ShelterManager |
| POST | /petcare/adoption-applications/:application_id/complete | Complete an approved adoption | CaseWorker |
| POST | /petcare/adoption-applications/:application_id/withdraw | Withdraw an application | CaseWorker |
| POST | /petcare/home-visits | Schedule a home visit | CaseWorker |
| GET | /petcare/home-visits | List home visits with filtering | ShelterManager, CaseWorker |
| GET | /petcare/home-visits/:home_visit_id | Get a specific home visit | ShelterManager, CaseWorker |
| POST | /petcare/home-visits/:home_visit_id/complete | Complete a home visit with assessment results | CaseWorker |
| POST | /petcare/home-visits/:home_visit_id/cancel | Cancel a scheduled home visit | CaseWorker |
| POST | /petcare/home-visits/expire-due | Sweep expired scheduled home visits | ShelterManager |
| POST | /petcare/boarding-reservations | Request a boarding reservation | CaseWorker |
| GET | /petcare/boarding-reservations | List boarding reservations with filtering | ShelterManager, CaseWorker |
| GET | /petcare/boarding-reservations/:reservation_id | Get a specific reservation | ShelterManager, CaseWorker |
| POST | /petcare/boarding-reservations/:reservation_id/confirm | Confirm a reservation | ShelterManager |
| POST | /petcare/boarding-reservations/:reservation_id/check-in | Check an animal into boarding | CaseWorker |
| POST | /petcare/boarding-reservations/:reservation_id/check-out | Check an animal out of boarding | CaseWorker |
| POST | /petcare/boarding-reservations/:reservation_id/cancel | Cancel a requested or confirmed reservation | ShelterManager |
| GET | /petcare/boarding-matches/:boarding_match_id | Get a specific boarding match | ShelterManager, CaseWorker |
| GET | /petcare/fee-invoices | List fee invoices with filtering | ShelterManager, CaseWorker |
| GET | /petcare/fee-invoices/:invoice_id | Get a specific fee invoice | ShelterManager, CaseWorker |
| POST | /petcare/fee-invoices/:invoice_id/pay | Record a payment against an invoice | CaseWorker |
| POST | /petcare/fee-invoices/:invoice_id/refund | Refund a paid invoice | ShelterManager |
| POST | /petcare/fee-invoices/:invoice_id/void | Void an unpaid invoice | ShelterManager |
| POST | /petcare/compliance-holds | Create a compliance hold | Veterinarian, ShelterManager |
| GET | /petcare/compliance-holds | List compliance holds with filtering | ShelterManager, CaseWorker, Veterinarian |
| GET | /petcare/compliance-holds/:hold_id | Get a specific compliance hold | ShelterManager, CaseWorker, Veterinarian |
| POST | /petcare/compliance-holds/:hold_id/resolve | Resolve an active compliance hold | ShelterManager |
| POST | /petcare/fee-schedules | Create a fee schedule entry | ShelterManager |
| GET | /petcare/fee-schedules | List fee schedule entries | ShelterManager, CaseWorker |
| GET | /petcare/fee-schedules/:fee_schedule_id | Get a specific fee schedule entry | ShelterManager, CaseWorker |
| POST | /petcare/settlement-batches | Compose a draft settlement batch | ShelterManager |
| GET | /petcare/settlement-batches | List settlement batches with filtering | ShelterManager |
| GET | /petcare/settlement-batches/:batch_id | Get a specific settlement batch | ShelterManager |
| POST | /petcare/settlement-batches/:batch_id/approve | Approve a draft settlement batch | ShelterManager |
| POST | /petcare/settlement-batches/:batch_id/mark-paid | Mark an approved settlement batch as paid | ShelterManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_AUTH_REQUIRED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_INVALID_REQUEST | 422 |
| ERR_INVALID_DATES | 422 |
| ERR_SHELTER_NOT_FOUND | 404 |
| ERR_ANIMAL_NOT_FOUND | 404 |
| ERR_ADOPTER_NOT_FOUND | 404 |
| ERR_APPLICATION_NOT_FOUND | 404 |
| ERR_HOME_VISIT_NOT_FOUND | 404 |
| ERR_RESERVATION_NOT_FOUND | 404 |
| ERR_BOARDING_MATCH_NOT_FOUND | 404 |
| ERR_INVOICE_NOT_FOUND | 404 |
| ERR_HOLD_NOT_FOUND | 404 |
| ERR_FEE_SCHEDULE_NOT_FOUND | 404 |
| ERR_VACCINATION_RECORD_NOT_FOUND | 404 |
| ERR_SETTLEMENT_BATCH_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_SHELTER_SUSPENDED | 409 |
| ERR_ANIMAL_NOT_AVAILABLE | 409 |
| ERR_ADOPTER_BLACKLISTED | 409 |
| ERR_TOO_EARLY_TO_CHECK_IN | 409 |
| ERR_VACCINATION_NOT_COMPLIANT | 409 |
| ERR_COMPLIANCE_HOLD_ACTIVE | 409 |
| ERR_CRITICAL_HOLD_PRESENT | 409 |
| ERR_SELF_APPROVAL | 409 |
| ERR_REVIEWER_MISMATCH | 409 |
| ERR_ASSESSOR_MISMATCH | 409 |
| ERR_HOME_VISIT_REQUIRED | 409 |
| ERR_STALE_ANIMAL_DATA | 409 |
| ERR_STALE_ADOPTER_DATA | 409 |
| ERR_BOARDING_DATE_OVERLAP | 409 |
| ERR_BOARDING_CAPACITY_FULL | 409 |
| ERR_FEE_NOT_PAID | 409 |
| ERR_PAYMENT_AMOUNT_INVALID | 422 |
| ERR_INVOICE_HAS_PAYMENTS | 409 |
| ERR_INVOICE_ALREADY_SETTLED | 409 |
| ERR_INVOICE_STATUS_CHANGED | 409 |
| ERR_VERSION_CONFLICT | 409 |
