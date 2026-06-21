# Veterinary Clinic Practice Management API — Product Requirements Document

## 1. Introduction

This document specifies the Veterinary Clinic Practice Management API, a back-office platform for a multi-doctor companion-animal practice. The system has to hold together a surprising number of moving parts: a household may keep several pets, each pet accrues a long clinical history of appointments, vaccinations, prescriptions and lab work, and the practice simultaneously runs a surgical suite and a boarding facility whose physical resources can only be in one place at a time. Money flows through the same fabric — refundable deposits sit as credit on a household account, wellness-plan subscriptions discount eligible services, and every completed visit eventually reconciles into an immutable invoice.

The platform exists to make these concerns coherent and auditable. Receptionists schedule and check in patients, post deposits, and present estimates; veterinarians run exams, administer vaccines, prescribe and refill medications, book and run surgeries, and order diagnostics; and a practice manager configures rooms and kennels, expires stale estimates, and finalizes the bills. Throughout, the system is expected to behave like a careful clerk rather than a permissive one: it refuses to double-book an operatory, it refuses to over-fill a kennel, it enforces re-dose intervals and controlled-substance cooldowns, and it never lets a deposit refund leak or duplicate a credit. The remainder of this document defines the global contracts every endpoint shares (Section 2), the business workflows and their scattered rules (Section 3), the endpoint surface (Section 4), and the catalogue of error identifiers (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. The system recognizes exactly three roles, spelled precisely as `Receptionist`, `Veterinarian`, and `PracticeManager`. If either header is absent, or if `X-User-Role` is not one of these three known roles, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 401). When the headers are well-formed but the named role is not permitted to perform the requested operation under the access matrix in Section 4, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

All three roles are **opaque operator identifiers**. When `X-User-Role` is `Receptionist`, `Veterinarian`, or `PracticeManager`, the accompanying `X-User-ID` is an operator handle that is not tied to any persisted entity; the server may log it for audit purposes but never compares it to any resource's `id`, and ownership of households, patients, or any other resource is never derived from the acting user's identity. Authorization in this system is purely role-based: a request is permitted or refused solely on whether the role may perform the operation, never on who owns the target resource.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it is constrained to a minimum of 1 and a maximum of 100. The `offset` parameter counts how many items to skip from the front of the result set and defaults to 0. These bounds are enforced by silent clamping rather than rejection: a `limit` below 1 is raised to 1, a `limit` above 100 is lowered to 100, and a negative `offset` is raised to 0; the (clamped) `limit` and `offset` are the values echoed back in `meta`. A `limit` or `offset` that is present but not parseable as an integer is rejected with `ERR_INVALID_REQUEST`.

Unless an endpoint states otherwise, every list endpoint returns its resources sorted by creation timestamp (`created_at`) in ascending order. Each list response surfaces the pagination bookkeeping in the `meta` object via the fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource is addressed by an `id` that the server mints as a UUID with no type prefix; clients never supply it. Each resource also carries a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits, fixed at the moment of creation.

Most resources additionally carry an `updated_at` timestamp (same ISO 8601 UTC format, refreshed on every mutation) and an integer `version` that begins at 1 on creation and increments by one on each mutation. There is one deliberate exception: the **Invoice** is an immutable billing record created already in its final state, so an Invoice carries only `id` and `created_at` — it has neither an `updated_at` nor a `version` field, because it is never modified after creation. All other entities — Household, Owner, Patient, WellnessPlan, Appointment, Vaccination, Prescription, Estimate, Surgery, BoardingStay, LabOrder, Operatory, and Kennel — carry the full set of `id`, `created_at`, `updated_at`, and `version`.

Whenever a derived or computed field changes as a side effect of an operation — for example a household's running credit, an operatory's booked-time accumulator, or a prescription's used-refill count — that mutation refreshes the owning resource's `updated_at` and increments its `version`, exactly as a direct field edit would. Every lifecycle-bearing entity carries a `status` field holding its current state, enumerated per entity in Section 3.

### 2.5. Monetary Values, Precision, and Rounding

All monetary amounts in this system are integer cents; there are no fractional-cent values stored anywhere. Where a calculation introduces a fractional intermediate — most notably a percentage discount or a per-kilogram anesthesia charge — the fractional result is rounded to a whole number of cents using the **round half up** convention (a value whose fractional part is exactly one half rounds away from zero, upward). The specific point at which rounding is applied matters and is pinned per calculation in Section 3; where a total is built from several components, the document states explicitly whether each component is rounded before being summed or whether already-integer charges are simply added with no intermediate rounding.

### 2.6. Optimistic Concurrency on Household Credit Writes

The **Household** is the financial aggregate of this system, and its `version` is the concurrency anchor for credit-bearing writes. One operation is guarded by optimistic concurrency control: finalizing an invoice. A request to finalize a new invoice must include the field `expected_household_version`, carrying the `version` of the target household that the client most recently observed. The server compares this value against the household's current `version`; if they do not match — because another writer has advanced the household's version since the client read it (a competing invoice finalize, a deposit posting or refund, or a surgery deposit commit, all of which bump `version`) — the finalize is rejected with `ERR_STALE_HOUSEHOLD_VERSION` (HTTP 412) before any credit is applied. This stops a client from finalizing against a household snapshot it has not actually seen, which would otherwise double-apply credit or advance lifetime totals twice. The `expected_household_version` field is non-optional on invoice finalization; endpoints that are not the invoice-finalize write do not take a version field, even when they happen to bump the household version as a side effect (deposit posting and surgery booking increment the version but are not themselves OCC-guarded).

### 2.7. Cascades and Cross-Aggregate Consistency

Several operations in this system touch more than one entity. A patient marked deceased, an appointment cancelled, a surgery cancelled, an estimate expired — each of these radiates secondary effects across prescriptions, boarding stays, surgeries, lab orders, operatory time, kennel occupancy, and household credit. These cascades are specified in full within the relevant workflows of Section 3 rather than here, but the governing principle is uniform: every entity a cascade mutates has its own `updated_at` refreshed and its own `version` incremented, and every monetary or capacity quantity that is released by a cancellation is restored exactly — never partially, never twice — to its source. The system favors immediate consistency: all cascade effects of a single operation are applied together as part of that operation, and the response reflects the fully reconciled state.

### 2.8. Nested and Filtered Retrieval

Every entity is a peer collection mounted under the `/clinic` prefix; relationships are expressed by foreign-key fields carried in request bodies rather than by deep URL nesting. When a path names a resource by id (for example a patient id, an appointment id, or an estimate id), that id is validated for existence first, and a missing resource yields the corresponding `404` not-found error for that resource type before any other rule is evaluated. Each resource type has its own not-found identifier: `ERR_HOUSEHOLD_NOT_FOUND`, `ERR_OWNER_NOT_FOUND`, `ERR_PATIENT_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_ESTIMATE_NOT_FOUND`, `ERR_SURGERY_NOT_FOUND`, `ERR_BOARDING_NOT_FOUND`, `ERR_PRESCRIPTION_NOT_FOUND`, `ERR_VACCINATION_NOT_FOUND`, `ERR_LAB_ORDER_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_OPERATORY_NOT_FOUND`, and `ERR_KENNEL_NOT_FOUND`. The one resource without a catalogued identifier is the wellness plan: a missing `wpid` on the `/clinic/wellness-plans/{wpid}` path yields a `404` whose `error_id` is the uncatalogued `ERR_WELLNESS_PLAN_NOT_FOUND`. The same not-found identifiers also apply to foreign keys carried in a request body when they fail to resolve: a surgery booking whose `operatory_id`, `estimate_id`, or `appointment_id` does not exist, a boarding reservation whose `kennel_id` does not exist, or an invoice finalize whose `household_id`, `appointment_id`, or referenced `estimate_id` does not exist, are each rejected with that resource type's not-found error. List endpoints accept optional filter parameters that select by a foreign key — for instance owners and patients filter by `household_id`; wellness plans, appointments, vaccinations, prescriptions, estimates, and boarding stays filter by `patient_id`; surgeries filter by `appointment_id`, `operatory_id`, or `estimate_id`; lab orders filter by `appointment_id`; boarding stays additionally filter by `kennel_id`; and invoices filter by `household_id`, `appointment_id`, or `estimate_id`. A filter that names a foreign key restricts the returned collection to rows whose corresponding field matches.

### 2.9. The Clock

Several rules reference "now": vaccine administration may not be in the future, a no-show may not be declared before the appointment's scheduled end, vaccine re-dose intervals and controlled-substance cooldowns are measured against the current time, and a vaccination reminder becomes due relative to the current time. All such comparisons are made against the system's logical clock at the instant the request is processed, and all timestamps are interpreted in UTC.

## 3. Business Logic & Workflows

### 3.1. Households, Owners, Patients, and the Multi-Pet Account

The **Household** is the billing account at the center of every financial story in the practice. A receptionist or practice manager opens a household with an `account_name` such as "The Rivera Family"; on creation it starts in status `ACTIVE` (the only status a household ever holds — households are not closed in this version), with `account_credit_cents` and `lifetime_invoiced_cents` both initialized to zero and `version` at 1. The `account_credit_cents` field is refundable monetary credit held on the account in integer cents; it is never negative and is moved only by deposit posting, deposit refunds, and invoice settlement. The `lifetime_invoiced_cents` field is a running, monotonically non-decreasing sum of the finalized `actual_total_cents` of every invoice billed to the household.

An **Owner** is a human client attached to a household. Adding an owner requires the `household_id` of the household they join, their `full_name`, and an `email`; an `is_primary` flag (defaulting to false) marks whether they are the household's primary billing contact. The email must be unique across all owners in the system — an attempt to reuse an address already held by another owner is rejected with `ERR_OWNER_EMAIL_TAKEN`.

A **Patient** is a pet. Registration takes the owning `household_id`, the pet's `name`, its `species` — one of `DOG`, `CAT`, `RABBIT`, or `FERRET`, which governs the vaccine schedule — and its current body weight `weight_kg` in kilograms, which must be strictly greater than zero and which later drives anesthesia dosing. A new patient begins in status `ACTIVE`; its lifecycle status is one of `ACTIVE`, `INACTIVE`, or `DECEASED`.

A receptionist may **deactivate** a patient, moving it from `ACTIVE` to `INACTIVE`. This is permitted only when the patient is currently `ACTIVE` (otherwise `ERR_PATIENT_NOT_ACTIVE`) and only when the patient has no appointment in any open state — that is, no appointment in `SCHEDULED`, `CHECKED_IN`, or `IN_EXAM`; if such an open visit exists the deactivation is refused with `ERR_PATIENT_HAS_OPEN_VISITS`.

A veterinarian may **mark a patient deceased**, moving it from `ACTIVE` to the terminal `DECEASED` state; this too requires the patient to be `ACTIVE` first (`ERR_PATIENT_NOT_ACTIVE`). Marking a patient deceased fans out a three-hop cascade. First (hop one), every prescription for that patient currently in status `ACTIVE` is transitioned to `VOIDED`. Then (hop two), each prescription that was just voided restores its remaining refills to the full authorized count — its `refills_used` is reset to zero so that the difference between `refills_authorized` and `refills_used` returns to the full authorization — conserving the authorized-refill budget rather than burning it on a void. In parallel with the prescription cascade (also a first-hop target), every boarding stay for that patient in status `RESERVED` or `CHECKED_IN` is transitioned to `CANCELLED`, and each such cancellation releases that stay's kennel occupancy across the days it spanned, freeing aggregate kennel capacity. Each entity touched by these cascades has its own `updated_at` and `version` advanced.

### 3.2. Wellness Plans: Discounts, Bundled Vaccines, and the Two Savings Views

A **WellnessPlan** is a subscription enrolling a single pet, created by a receptionist or practice manager against a `patient_id` and a `tier` of `BASIC`, `PLUS`, or `PREMIER`. A plan is always `ACTIVE` (plans are not cancelled in this version). The chosen tier fixes two computed quantities at enrollment. The `service_discount_pct`, the discount fraction applied to eligible service line items, is 0.10 for `BASIC`, 0.20 for `PLUS`, and 0.30 for `PREMIER`. The `bundled_vaccines_remaining`, the count of fee-waived vaccinations available in the plan year, starts at 2 for `BASIC`, 4 for `PLUS`, and 8 for `PREMIER`, and is decremented by one each time a bundled vaccine is administered. The plan also carries `realized_savings_cents`, a running tally initialized to zero, described below.

When a wellness plan is read individually, the response surfaces two distinct savings figures whose divergence is the point of the feature. The **projected** savings is an optimistic forward look surfaced as the computed response field `projected_savings_cents` (present on both the individual-read and list responses, alongside the stored fields): it assumes the full vaccine bundle for the tier is used and applies a fixed reference spend. Concretely, the projected savings is the tier's full bundled-vaccine allotment multiplied by the standard vaccine fee of 4,500 cents (giving the bundle component), plus the service-discount component, which is the reference annual service spend of 60,000 cents multiplied by the plan's `service_discount_pct` and rounded half up to whole cents. These two components are added to give the projected total. This projection ignores what the household actually consumed.

The `realized_savings_cents` field, by contrast, is the chronological, ground-truth tally of savings the household has actually accrued under the plan, and it is mutated as real events settle. When an appointment for a plan-enrolled patient is completed, the system walks that appointment's rendered, discount-eligible work — each `RESULTED` lab order, each `DONE` surgery, and each administered non-bundled vaccination that is marked discount-eligible — in render order (earliest `created_at` first); for each such item it computes the eligible gross multiplied by the plan's `service_discount_pct`, rounds that product half up to whole cents, and adds it to `realized_savings_cents`. Because rendered lab orders, surgeries, and vaccinations carry no `eligible_for_plan_discount` field (that flag lives only on estimate line items), this completion-time walk finds no item flagged discount-eligible and therefore contributes zero to `realized_savings_cents` in this version; the only event that concretely moves the tally is the bundled-vaccine waived fee below. Separately, at the moment a bundled vaccine is administered, the waived standard vaccine fee of 4,500 cents is added to `realized_savings_cents`. The realized figure therefore counts only savings the household has truly earned and diverges from the projected figure by exactly the portion of the bundle and discount that went unused.

### 3.3. Scheduling: The Appointment Lifecycle and Its Reschedule Loop

An **Appointment** is a clinical visit. A receptionist schedules one against a `patient_id`, a `scheduled_start` and `scheduled_end` (ISO 8601 UTC, with the end required to be strictly after the start, else `ERR_INVALID_TIME_RANGE`), and a free-text `visit_reason`. A new appointment opens in `SCHEDULED` with its `reschedule_count` at zero. The appointment's status is one of `SCHEDULED`, `CHECKED_IN`, `IN_EXAM`, `COMPLETED`, `CANCELLED`, or `NO_SHOW`; `COMPLETED`, `CANCELLED`, and `NO_SHOW` are terminal.

Appointment transitions are driven by a single transition operation that takes an `action` selecting which move to make. A receptionist **checks in** a `SCHEDULED` appointment, advancing it to `CHECKED_IN`; this requires the appointment to be `SCHEDULED` (otherwise `ERR_APPOINTMENT_INVALID_STATE`) and, because this is a cross-entity dependency from the appointment to its pet, requires the patient to be `ACTIVE` (otherwise `ERR_PATIENT_NOT_ACTIVE`). A veterinarian **begins the exam** on a `CHECKED_IN` appointment, advancing it to `IN_EXAM` (the appointment must be `CHECKED_IN`, else `ERR_APPOINTMENT_INVALID_STATE`).

From `IN_EXAM`, two onward moves exist. A veterinarian may **reschedule**, cycling the appointment from `IN_EXAM` back to `SCHEDULED` — this is the reschedule loop. Rescheduling requires the appointment to be `IN_EXAM`, requires `reschedule_count` to be strictly fewer than 3 (a fourth attempt is refused with `ERR_APPOINTMENT_INVALID_STATE` for exceeding the reschedule limit), and requires that no surgery on this appointment sits in `BOOKED` or `IN_PROGRESS` (a pending or running surgery blocks rescheduling, again `ERR_APPOINTMENT_INVALID_STATE`). On success the status returns to `SCHEDULED`, `reschedule_count` increases by one, and the `scheduled_start` and `scheduled_end` are replaced by the new window supplied in the request body. Alternatively, a veterinarian may **complete** an `IN_EXAM` appointment, moving it to `COMPLETED`; completion requires that no lab order on the appointment is still `ORDERED` or `COLLECTED` (open diagnostics block completion) and that no surgery on the appointment is still `BOOKED` or `IN_PROGRESS` (an open surgery blocks completion) — both refusals carry `ERR_APPOINTMENT_INVALID_STATE`.

A receptionist may **cancel** an appointment from any of `SCHEDULED`, `CHECKED_IN`, or `IN_EXAM` (otherwise `ERR_APPOINTMENT_INVALID_STATE`), moving it to the terminal `CANCELLED`. Cancellation triggers a multi-target cascade. Every surgery on the appointment in `BOOKED` or `IN_PROGRESS` is itself cancelled (hop one); each cancelled surgery releases its operatory booking by decrementing that operatory's `booked_minutes` by the surgery's window length in minutes (hop two), conserving operatory minutes; and each cancelled surgery refunds its `deposit_consumed_cents` back to the funding estimate's household by adding it to that household's `account_credit_cents` and bumping that household's `version` by one (hop three), conserving credit — this refund follows the same path as a direct surgery cancellation (Section 3.8), so the refunded amount is also added back to the funding estimate's `deposit_posted_cents` and the surgery's `deposit_consumed_cents` is then reset to zero. In parallel (also a first-hop target), every lab order on the appointment in `ORDERED` or `COLLECTED` is cancelled.

A receptionist may also mark an appointment **no-show**, but only from `SCHEDULED` and only once the clock has reached or passed the appointment's `scheduled_end`; declaring a no-show while still `SCHEDULED` is correct, but doing so before `scheduled_end` is too early and is refused with `ERR_APPOINTMENT_INVALID_STATE`, as is attempting a no-show from any non-`SCHEDULED` state. A successful no-show moves the appointment to the terminal `NO_SHOW`.

### 3.4. Vaccinations, Re-Dose Intervals, and Reminders

A veterinarian records a **Vaccination** against a `patient_id`, a `vaccine_code` of `RABIES`, `DHPP`, `BORDETELLA`, or `FVRCP`, the `administered_at` time (ISO 8601 UTC, which must not be after the clock's current time, else `ERR_FUTURE_ADMINISTRATION`), and an optional `bundled` flag (default false) indicating the dose should draw from the patient's wellness-plan bundle.

Each vaccine code has a minimum re-dose interval measured in whole days: `RABIES` is 365 days, `DHPP` is 21 days, `BORDETELLA` is 180 days, and `FVRCP` is 21 days. Before a new dose is accepted, the system finds the patient's latest prior dose of the same `vaccine_code` (the most recent by `administered_at`, breaking ties by the later `created_at`). If the gap between the new dose's `administered_at` and that prior dose's `administered_at` is strictly fewer than the code's interval in days, the dose is rejected with `ERR_VACCINE_INTERVAL`; a gap exactly equal to the interval is allowed, and any larger gap is allowed. The gap is measured as whole calendar days — the difference between the new dose's `administered_at` calendar date and the prior dose's `administered_at` calendar date, both interpreted in UTC, with the time-of-day component discarded — so the comparison is `(new_date − prior_date).days < interval`.

For an accepted dose, two schedule fields are computed. The `next_due_at` is the `administered_at` plus the code's interval in days. The `reminder_at` is the `next_due_at` minus a fixed reminder lead of 14 days — the date on which a reminder for this dose becomes due.

The fee a dose charges, `fee_cents`, depends on the bundle. When the dose is marked `bundled` and the patient has an `ACTIVE` wellness plan whose `bundled_vaccines_remaining` is greater than zero at that moment, the fee is zero (waived) — and in that case the plan's `bundled_vaccines_remaining` is decremented by one and its `realized_savings_cents` is increased by the standard vaccine fee of 4,500 cents, as described in the wellness-plan workflow. Otherwise the dose charges the flat standard vaccine fee of 4,500 cents, which is the same for every `vaccine_code`. A vaccination list may be narrowed with a `due_only` filter, which returns only those doses whose `reminder_at` is at or before the current clock time. The filter is engaged only when the `due_only` query value is `true` or `1` (case-insensitive); any other value (including `false` or `0`, or the parameter's absence) leaves the list unfiltered by due date.

### 3.5. Prescriptions, Refills, and Controlled Substances

A veterinarian creates a **Prescription** for a `patient_id` with a `drug_name`, a count of `refills_authorized` (which must be at least zero), and an `is_controlled` flag (default false) marking the drug as a controlled substance. A new prescription opens `ACTIVE`, with `refills_used` at zero. The number of refills still available is the `refills_authorized` minus `refills_used`, a quantity that never drops below zero nor exceeds the authorization. The prescription's status is one of `ACTIVE`, `EXHAUSTED`, or `VOIDED`, the latter two terminal. The `last_refill_at` field records the clock time of the most recent dispense and is null until the first refill.

Dispensing a **refill** is a veterinarian action that keeps the prescription `ACTIVE` while refills remain. A refill requires the prescription itself to be `ACTIVE` (otherwise `ERR_PRESCRIPTION_NOT_ACTIVE`) and, as a cross-entity dependency from the prescription to its pet, requires the patient to be `ACTIVE` (otherwise `ERR_PATIENT_NOT_ACTIVE`). If the drug is controlled, a cooldown applies: the time elapsed since `last_refill_at` must be at least 30 days, and a refill attempted strictly within 30 days of the last one is refused with `ERR_CONTROLLED_COOLDOWN`. Finally, there must be refills available — the difference between `refills_authorized` and `refills_used` must be greater than zero, or the refill is refused with `ERR_NO_REFILLS_REMAINING`. On a successful dispense, `refills_used` increases by one and `last_refill_at` is set to the current clock time. When that dispense drives the remaining-refill count to zero, the prescription auto-advances to the terminal `EXHAUSTED` state.

A prescription also reaches `VOIDED` indirectly: when its patient is marked deceased, every `ACTIVE` prescription for that patient is voided as part of that cascade, and the void restores the prescription's `refills_used` to zero so that its remaining refills return to the full `refills_authorized` — the authorized count is conserved through the void rather than consumed.

### 3.6. Estimates, Line Items, Deposits, and the Revision Loop

An **Estimate** is a forward-looking treatment quote. A veterinarian or receptionist drafts one against a `patient_id`, an array of `line_items`, and an optional `deposit_required_cents` (default zero, never negative) the household must post before the estimate may be approved. Each entry in `line_items` is an object with a `service_code`, a `qty` (at least 1), a `unit_price_cents` (at least 0), and an `eligible_for_plan_discount` flag. A new estimate opens in `DRAFT` with `revision` at 1; its `deposit_posted_cents` (the deposit actually posted against it) starts at zero. The estimate's status is one of `DRAFT`, `PRESENTED`, `APPROVED`, `DECLINED`, or `EXPIRED`, with `APPROVED` and `EXPIRED` terminal.

The forward-looking `estimated_total_cents` projects the total over all line items with the plan discount applied optimistically, and the order of operations is pinned: discounts are rounded per line item before summing, not after. Processing the `line_items` in array order, for each line the gross is its `unit_price_cents` multiplied by its `qty`; if that line is `eligible_for_plan_discount` and the patient has an `ACTIVE` wellness plan, the line's discount is the gross multiplied by the plan's `service_discount_pct`, rounded half up to whole cents, and the line's net is the gross minus that rounded discount; if the line is not eligible or the patient has no active plan, the line's net is simply its gross. The `estimated_total_cents` is the sum of these per-line nets. Because every eligible line is discounted regardless of whether the work is ultimately rendered, this projection is deliberately optimistic.

Estimate transitions are driven by a transition operation taking an `action`. A veterinarian **presents** a `DRAFT` estimate, moving it to `PRESENTED`; presentation requires the estimate to be `DRAFT` and to have at least one line item (an empty estimate is refused with `ERR_ESTIMATE_INVALID_STATE`), and it recomputes `estimated_total_cents`. A receptionist may **decline** a `PRESENTED` estimate, moving it to `DECLINED` (the estimate must be `PRESENTED`, else `ERR_ESTIMATE_INVALID_STATE`). From `DECLINED`, a veterinarian may **revise**, cycling the estimate back to `DRAFT` — this is the revision loop; revision requires the estimate to be `DECLINED`, increments `revision` by one, and replaces `line_items` with the new array in the request body. A receptionist **approves** a `PRESENTED` estimate, moving it to the terminal `APPROVED`; approval requires the estimate to be `PRESENTED` and requires that `deposit_posted_cents` be at least `deposit_required_cents`, otherwise the approval is refused with `ERR_DEPOSIT_NOT_MET`. Finally, a practice manager may **expire** an estimate from either `DRAFT` or `PRESENTED` (otherwise `ERR_ESTIMATE_INVALID_STATE`), moving it to the terminal `EXPIRED`; if any deposit had been posted — that is, `deposit_posted_cents` is greater than zero — that amount is refunded to the patient's household by adding it to the household's `account_credit_cents` and bumping that household's `version` by one.

### 3.7. Deposits and the Household Credit Account

A receptionist or practice manager **posts a deposit** to credit a household. The request supplies the `household_id`, an `amount_cents` to post, an optional `estimate_id` to earmark the deposit to a specific estimate, and an `expected_household_version` reflecting the household version the client last saw. Posting a deposit increases the household's `account_credit_cents` by `amount_cents`; if an `estimate_id` is supplied, that estimate's `deposit_posted_cents` is also increased by the same `amount_cents`; and the household's `version` is incremented by one. Although the deposit write advances the household version, it is the invoice-finalize write — not deposit posting — that is OCC-guarded, as described in Section 2.6; the deposit's `expected_household_version` is recorded with the request but the stale-version rejection contract applies specifically to invoice finalization.

### 3.8. Surgery: Operatory Booking, Tiered Pricing, and Deposit Commitment

A **Surgery** is a surgical procedure booked into an operatory and funded by an approved estimate. A veterinarian books one against the parent `appointment_id`, the `operatory_id` of the suite, the funding `estimate_id`, a `procedure_name`, and a `window_start` and `window_end` (ISO 8601 UTC, with the end strictly after the start, else `ERR_INVALID_TIME_RANGE`). The funding estimate must be `APPROVED` at booking time, otherwise booking is refused with `ERR_ESTIMATE_INVALID_STATE`; the parent appointment need only exist at booking time and is not required to be in any particular state then. A new surgery opens in `BOOKED`; its status is one of `BOOKED`, `IN_PROGRESS`, `DONE`, or `CANCELLED`, the latter two terminal.

An **Operatory** is a surgical suite created by a practice manager with a `name` and an optional `cleanup_buffer_minutes` (default 30, never negative) — a mandatory cleanup buffer enforced after each surgery window before the suite is free again. The operatory tracks `booked_minutes`, the running sum of window lengths over its `BOOKED`, `IN_PROGRESS`, and `DONE` surgeries, and is always in status `OPEN` (resources are not closed). Booking is geometry-checked against overlap: a new surgery's window taken together with the operatory's `cleanup_buffer_minutes` appended after its end — that is, the half-open interval from `window_start` up to `window_end` plus the buffer — must not overlap the equivalently buffered interval of any other non-cancelled surgery in the same operatory; a conflict is refused with `ERR_OPERATORY_CONFLICT`. On a successful booking the operatory's `booked_minutes` increases by the surgery's window length in minutes.

The charge for a surgery, `surgery_total_cents`, is computed and fixed at booking time from three inputs — the procedure base, the patient's weight band, and the operatory time used. The procedure base is 20,000 cents. The anesthesia component is weight-banded against the patient's `weight_kg`: for a weight of at most 5 kg the anesthesia is `weight_kg` multiplied by 800 cents per kg; for a weight greater than 5 kg but at most 25 kg it is `weight_kg` multiplied by 600 cents per kg; for a weight greater than 25 kg it is `weight_kg` multiplied by 500 cents per kg; the resulting anesthesia amount is rounded half up to whole cents. The time surcharge takes the window length in minutes, subtracts a free allowance of 60 minutes, and — if any minutes remain (that is, the excess over 60 minutes, but never less than zero) — charges 150 cents for each excess minute. The raw total is the procedure base plus the rounded anesthesia plus the time surcharge. That raw total is finally clamped into a band: it is raised to a floor of 25,000 cents if it falls below that, and capped at a ceiling of 500,000 cents if it exceeds that, and the clamped value is `surgery_total_cents`.

At booking, the surgery also commits deposit from its funding estimate. The `deposit_consumed_cents` is set to the smaller of the funding estimate's `deposit_posted_cents` and the surgery's `surgery_total_cents`. That committed amount is debited from the funding estimate's household — its `account_credit_cents` is reduced by `deposit_consumed_cents` — the funding estimate's `deposit_posted_cents` is reduced by the same amount, and that household's `version` is bumped by one. The deposit is thereby committed to this surgery, to be refunded if the surgery is cancelled and settled permanently if it completes.

Surgery transitions are driven by a transition operation taking an `action`. A veterinarian **starts** a `BOOKED` surgery, moving it to `IN_PROGRESS`; starting requires the surgery to be `BOOKED` (else `ERR_SURGERY_INVALID_STATE`) and, as a cross-entity dependency from the surgery to its appointment, requires the parent appointment to be `IN_EXAM` (else `ERR_APPOINTMENT_NOT_IN_EXAM`). A veterinarian **completes** an `IN_PROGRESS` surgery, moving it to the terminal `DONE` (the surgery must be `IN_PROGRESS`, else `ERR_SURGERY_INVALID_STATE`); on completion the previously committed `deposit_consumed_cents` is permanently settled toward this surgery, and `account_credit_cents` is left unchanged because it was already debited at booking. A veterinarian may **cancel** a surgery from either `BOOKED` or `IN_PROGRESS` (else `ERR_SURGERY_INVALID_STATE`), moving it to the terminal `CANCELLED`; cancellation decrements the operatory's `booked_minutes` by this surgery's window length in minutes, and — if `deposit_consumed_cents` is greater than zero — refunds it to the funding estimate's household by adding it back to that household's `account_credit_cents` and back to the funding estimate's `deposit_posted_cents`, bumps that household's `version` by one, and then resets `deposit_consumed_cents` to zero.

### 3.9. Boarding: Kennels and Aggregate Capacity

A **BoardingStay** reserves a kennel for a pet across a date span. A receptionist or practice manager creates one against a `patient_id`, the `kennel_id` of the block, a `check_in_date` (the inclusive day of arrival), a `check_out_date` (the inclusive day of departure, which must be on or after `check_in_date`, else `ERR_INVALID_TIME_RANGE`), and a `nightly_rate_cents` (never negative). A new stay opens in `RESERVED`; its status is one of `RESERVED`, `CHECKED_IN`, `CHECKED_OUT`, or `CANCELLED`, the latter two terminal. The `board_total_cents` is the `nightly_rate_cents` multiplied by the number of nights, where nights is the inclusive-day span: the number of days from `check_in_date` to `check_out_date` plus one, so that a same-day stay (check-in equal to check-out) counts as one night.

A **Kennel** is a boarding block created by a practice manager with a `name` and a `capacity` (the maximum number of overlapping stays the kennel may hold on any single shared day, at least 1); it is always in status `OPEN`. Capacity is enforced per day: for every inclusive day a new boarding stay would span, the count of non-cancelled stays already covering that day in that kennel must remain at or below the kennel's `capacity`; if admitting the new stay would exceed capacity on even one overlapping day, the reservation is refused with `ERR_KENNEL_AT_CAPACITY`. On a successful reservation the kennel's occupancy is incremented for each of the stay's days.

Boarding transitions are driven by a transition operation taking an `action`. A receptionist **checks in** a `RESERVED` stay, moving it to `CHECKED_IN`; check-in requires the stay to be `RESERVED` (else `ERR_BOARDING_INVALID_STATE`) and requires the patient to be `ACTIVE` (else `ERR_PATIENT_NOT_ACTIVE`). A receptionist **checks out** a `CHECKED_IN` stay, moving it to the terminal `CHECKED_OUT` (the stay must be `CHECKED_IN`, else `ERR_BOARDING_INVALID_STATE`); checkout finalizes `board_total_cents`, and the kennel occupancy for those days is retained — a checked-out stay still counts as having occupied the days it used. A receptionist may **cancel** a stay from either `RESERVED` or `CHECKED_IN` (else `ERR_BOARDING_INVALID_STATE`), moving it to the terminal `CANCELLED`; cancellation decrements the kennel's occupancy for this stay's days, freeing that aggregate capacity for other stays.

### 3.10. Lab and Dental Orders

A **LabOrder** is a diagnostic order placed on an appointment. A veterinarian places one against the parent `appointment_id`, an `order_type` of `BLOODWORK`, `URINALYSIS`, `DENTAL_XRAY`, `CYTOLOGY`, or `BIOPSY`, and a `fee_cents` (never negative). A new order opens in `ORDERED`; its `result_text` is null until the order is resulted, and its status is one of `ORDERED`, `COLLECTED`, `RESULTED`, or `CANCELLED`, the latter two terminal.

Lab transitions are driven by a transition operation taking an `action`. A veterinarian **collects** an `ORDERED` order, moving it to `COLLECTED` (the order must be `ORDERED`, else `ERR_LAB_ORDER_INVALID_STATE`). A veterinarian **results** a `COLLECTED` order, moving it to the terminal `RESULTED`; resulting requires the order to be `COLLECTED` (else `ERR_LAB_ORDER_INVALID_STATE`) and requires a `result_text` in the request body (a missing result text is refused with `ERR_INVALID_REQUEST`), and on success the provided `result_text` is stored. A veterinarian may **cancel** an order from either `ORDERED` or `COLLECTED` (else `ERR_LAB_ORDER_INVALID_STATE`), moving it to the terminal `CANCELLED`; a lab order is also cancelled automatically when its parent appointment is cancelled, as part of that appointment's cascade.

### 3.11. Invoice Finalization: Estimate vs. Actual Reconciliation

The **Invoice** is the immutable, finalized household bill, and only a practice manager may finalize one. Finalization takes the billed `household_id`, the `appointment_id` of the completed appointment whose rendered services are billed, an optional `estimate_id` reconciled against, and the `expected_household_version` for the optimistic-concurrency check described in Section 2.6. An invoice is created already in status `FINALIZED` and is never modified afterward; it has no `updated_at` and no `version`.

Finalization requires that the appointment actually have something to bill: there must be at least one rendered, billable item — an administered vaccination, a `RESULTED` lab order, or a `DONE` surgery — and an empty actual set is refused with `ERR_NO_BILLABLE_ITEMS`. The invoice computes two parallel totals whose difference is the reconciliation. The forward-looking `estimate_total_cents` is a copy of the linked estimate's `estimated_total_cents` captured at finalize time, or zero if no estimate is linked.

The `actual_total_cents` is the chronological sum of charges actually rendered on the appointment, net of credit applied. The system assembles the charge list in render order: first every vaccination of the appointment's patient whose `administered_at` falls between the appointment's `scheduled_start` and the finalize time — inclusive of both endpoints, i.e. `scheduled_start <= administered_at <= finalize_time` — ordered by `administered_at` ascending and then by `created_at` ascending, contributing each vaccination's `fee_cents` (a bundled dose contributes zero); then every `RESULTED` lab order on the appointment, ordered by `created_at` ascending, contributing each order's `fee_cents`; then every `DONE` surgery on the appointment, ordered by `created_at` ascending, contributing each surgery's `surgery_total_cents` minus its already-settled `deposit_consumed_cents`. The raw actual is the sum of that charge list. The credit applied is the smaller of the raw actual and the household's current `account_credit_cents`, and the `actual_total_cents` is the raw actual minus that applied credit. Because these are already-integer cent charges, the sum involves no intermediate rounding. Only rendered work counts — `ORDERED` or `CANCELLED` lab orders and non-`DONE` surgeries are excluded — so the actual diverges from the estimate whenever some estimated line items were never rendered or were not discount-eligible at render time.

The `variance_cents` records the difference, `actual_total_cents` minus `estimate_total_cents`, and may be negative. On a successful finalize the household's `account_credit_cents` is reduced by the credit applied, its `lifetime_invoiced_cents` is increased by the finalized `actual_total_cents`, and its `version` is incremented by one. Because the household version advances here, a concurrent client whose `expected_household_version` no longer matches is rejected with `ERR_STALE_HOUSEHOLD_VERSION` before any of these effects are applied.

## 4. Endpoint Definitions

Operations that create a brand-new resource return `201 Created`. Operations that modify or transition an existing resource — including all lifecycle transition operations and refill dispensing — return `200 OK`. Deposit posting and invoice finalization create new resources (a credit posting against the household and a new invoice respectively) and return `201 Created`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/clinic/operatories` | Create an operatory (surgical suite) | PracticeManager |
| GET | `/clinic/operatories` | List operatories | PracticeManager, Veterinarian, Receptionist |
| GET | `/clinic/operatories/{oid}` | Get an operatory | PracticeManager, Veterinarian, Receptionist |
| POST | `/clinic/kennels` | Create a kennel block | PracticeManager |
| GET | `/clinic/kennels` | List kennels | PracticeManager, Veterinarian, Receptionist |
| GET | `/clinic/kennels/{kid}` | Get a kennel | PracticeManager, Veterinarian, Receptionist |
| POST | `/clinic/households` | Create a household billing account | Receptionist, PracticeManager |
| GET | `/clinic/households` | List households | Receptionist, Veterinarian, PracticeManager |
| GET | `/clinic/households/{hid}` | Get a household | Receptionist, Veterinarian, PracticeManager |
| POST | `/clinic/deposits` | Post a refundable deposit to a household | Receptionist, PracticeManager |
| POST | `/clinic/owners` | Add an owner to a household | Receptionist, PracticeManager |
| GET | `/clinic/owners` | List owners (filter by household_id) | Receptionist, Veterinarian, PracticeManager |
| GET | `/clinic/owners/{ownerid}` | Get an owner | Receptionist, Veterinarian, PracticeManager |
| POST | `/clinic/patients` | Register a patient under a household | Receptionist, PracticeManager |
| GET | `/clinic/patients` | List patients (filter by household_id) | Receptionist, Veterinarian, PracticeManager |
| GET | `/clinic/patients/{pid}` | Get a patient | Receptionist, Veterinarian, PracticeManager |
| POST | `/clinic/patients/{pid}/deactivate` | Deactivate a patient | Receptionist |
| POST | `/clinic/patients/{pid}/mark-deceased` | Mark a patient deceased (cascades) | Veterinarian |
| POST | `/clinic/wellness-plans` | Enroll a patient in a wellness plan | Receptionist, PracticeManager |
| GET | `/clinic/wellness-plans` | List wellness plans (filter by patient_id) | Receptionist, Veterinarian, PracticeManager |
| GET | `/clinic/wellness-plans/{wpid}` | Get a wellness plan (projected vs realized savings) | Receptionist, Veterinarian, PracticeManager |
| POST | `/clinic/appointments` | Schedule an appointment | Receptionist |
| GET | `/clinic/appointments` | List appointments (filter by patient_id) | Receptionist, Veterinarian, PracticeManager |
| GET | `/clinic/appointments/{aid}` | Get an appointment | Receptionist, Veterinarian, PracticeManager |
| POST | `/clinic/appointments/{aid}/transition` | Drive an appointment through its lifecycle | Receptionist, Veterinarian |
| POST | `/clinic/vaccinations` | Record a vaccine dose | Veterinarian |
| GET | `/clinic/vaccinations` | List vaccinations (filter by patient_id, due_only) | Receptionist, Veterinarian, PracticeManager |
| GET | `/clinic/vaccinations/{vid}` | Get a vaccination | Receptionist, Veterinarian, PracticeManager |
| POST | `/clinic/prescriptions` | Create a prescription | Veterinarian |
| GET | `/clinic/prescriptions` | List prescriptions (filter by patient_id) | Receptionist, Veterinarian, PracticeManager |
| GET | `/clinic/prescriptions/{rxid}` | Get a prescription | Receptionist, Veterinarian, PracticeManager |
| POST | `/clinic/prescriptions/{rxid}/refill` | Dispense one refill | Veterinarian |
| POST | `/clinic/estimates` | Create a draft estimate | Veterinarian, Receptionist |
| GET | `/clinic/estimates` | List estimates (filter by patient_id) | Receptionist, Veterinarian, PracticeManager |
| GET | `/clinic/estimates/{eid}` | Get an estimate | Receptionist, Veterinarian, PracticeManager |
| POST | `/clinic/estimates/{eid}/transition` | Drive an estimate through its lifecycle | Veterinarian, Receptionist, PracticeManager |
| POST | `/clinic/surgeries` | Book a surgery into an operatory | Veterinarian |
| GET | `/clinic/surgeries` | List surgeries (filter by appointment_id, operatory_id, estimate_id) | Receptionist, Veterinarian, PracticeManager |
| GET | `/clinic/surgeries/{sid}` | Get a surgery | Receptionist, Veterinarian, PracticeManager |
| POST | `/clinic/surgeries/{sid}/transition` | Drive a surgery through its lifecycle | Veterinarian |
| POST | `/clinic/boarding-stays` | Reserve a boarding stay in a kennel | Receptionist, PracticeManager |
| GET | `/clinic/boarding-stays` | List boarding stays (filter by patient_id, kennel_id) | Receptionist, Veterinarian, PracticeManager |
| GET | `/clinic/boarding-stays/{bid}` | Get a boarding stay | Receptionist, Veterinarian, PracticeManager |
| POST | `/clinic/boarding-stays/{bid}/transition` | Drive a boarding stay through its lifecycle | Receptionist |
| POST | `/clinic/lab-orders` | Place a lab or dental order on an appointment | Veterinarian |
| GET | `/clinic/lab-orders` | List lab orders (filter by appointment_id) | Receptionist, Veterinarian, PracticeManager |
| GET | `/clinic/lab-orders/{loid}` | Get a lab order | Receptionist, Veterinarian, PracticeManager |
| POST | `/clinic/lab-orders/{loid}/transition` | Drive a lab order through its lifecycle | Veterinarian |
| POST | `/clinic/invoices` | Finalize an invoice for a completed appointment | PracticeManager |
| GET | `/clinic/invoices` | List invoices (filter by household_id, appointment_id, estimate_id) | Receptionist, Veterinarian, PracticeManager |
| GET | `/clinic/invoices/{invid}` | Get an invoice | Receptionist, Veterinarian, PracticeManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_HOUSEHOLD_NOT_FOUND` | 404 Not Found |
| `ERR_OWNER_NOT_FOUND` | 404 Not Found |
| `ERR_PATIENT_NOT_FOUND` | 404 Not Found |
| `ERR_APPOINTMENT_NOT_FOUND` | 404 Not Found |
| `ERR_ESTIMATE_NOT_FOUND` | 404 Not Found |
| `ERR_SURGERY_NOT_FOUND` | 404 Not Found |
| `ERR_BOARDING_NOT_FOUND` | 404 Not Found |
| `ERR_PRESCRIPTION_NOT_FOUND` | 404 Not Found |
| `ERR_VACCINATION_NOT_FOUND` | 404 Not Found |
| `ERR_LAB_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_INVOICE_NOT_FOUND` | 404 Not Found |
| `ERR_OPERATORY_NOT_FOUND` | 404 Not Found |
| `ERR_KENNEL_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_TIME_RANGE` | 400 Bad Request |
| `ERR_OWNER_EMAIL_TAKEN` | 409 Conflict |
| `ERR_FUTURE_ADMINISTRATION` | 422 Unprocessable Entity |
| `ERR_PATIENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_PATIENT_HAS_OPEN_VISITS` | 409 Conflict |
| `ERR_APPOINTMENT_INVALID_STATE` | 409 Conflict |
| `ERR_ESTIMATE_INVALID_STATE` | 409 Conflict |
| `ERR_SURGERY_INVALID_STATE` | 409 Conflict |
| `ERR_APPOINTMENT_NOT_IN_EXAM` | 409 Conflict |
| `ERR_BOARDING_INVALID_STATE` | 409 Conflict |
| `ERR_LAB_ORDER_INVALID_STATE` | 409 Conflict |
| `ERR_PRESCRIPTION_NOT_ACTIVE` | 409 Conflict |
| `ERR_NO_REFILLS_REMAINING` | 409 Conflict |
| `ERR_VACCINE_INTERVAL` | 422 Unprocessable Entity |
| `ERR_CONTROLLED_COOLDOWN` | 422 Unprocessable Entity |
| `ERR_OPERATORY_CONFLICT` | 409 Conflict |
| `ERR_KENNEL_AT_CAPACITY` | 409 Conflict |
| `ERR_DEPOSIT_NOT_MET` | 402 Payment Required |
| `ERR_NO_BILLABLE_ITEMS` | 422 Unprocessable Entity |
| `ERR_STALE_HOUSEHOLD_VERSION` | 412 Precondition Failed |
