# Cosmetic Surgery API — Product Requirements Document

## 1. Introduction

This document specifies the back-office platform for a concierge, cash-pay cosmetic and plastic surgery practice. Unlike an insurance-billed clinic, every dollar in this business flows directly between the patient and the practice, so the system's central obligation is to keep a precise financial ledger for each quoted engagement: what was quoted, what the patient has put down as a deposit, what a third-party lender has agreed to finance, and what therefore remains owed. These figures must never drift out of agreement with one another, even as bookings are cancelled, financing is voided, and quotes are reverted.

The workflow the platform automates is long and clinically sensitive. A patient arrives for a consultation with a surgeon, receives a bundled quote spanning surgical, facility, and anesthesia fees, signs photo and surgical consent, is medically cleared to a risk-appropriate tier, and only then may surgery be scheduled into a contended operating room and surgeon calendar. After surgery, a revision or complication policy governs whether the practice absorbs the cost of corrective work or bills the patient for it. Four distinct staff roles — front-desk coordination, clinical surgery, billing, and practice administration — each own a slice of this pipeline, and the platform enforces both who may do what and the exact order in which safety, fiscal, and scheduling checks are applied.

Because the practice operates on a logical clock that test harnesses can advance at will, all time-relative rules — cancellation notice windows, "surgery not yet started," future-dated bookings, and revision windows — are evaluated against that clock rather than wall-clock time.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming that user's role. If either header is missing, or if `X-User-Role` is not one of the four recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the named role is not permitted to perform the requested operation (per the authorization column of the endpoint table in §4), the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The four roles are `PracticeAdmin`, `FrontDeskCoordinator`, `Surgeon`, and `BillingSpecialist`. A `PracticeAdmin` is the operational administrator who manages the procedure catalog and the logical clock. A `FrontDeskCoordinator` handles intake, quoting, consent capture, and scheduling. A `Surgeon` is the clinical role: completing consultations, issuing clearances, capturing consent, running surgery, and managing complications. A `BillingSpecialist` handles deposits, financing, refunds, and cancellation settlements.

All four roles use an **opaque** identity model: `X-User-ID` is an operator identifier that is not tied to any persisted entity's `id`. The server never compares `X-User-ID` to an entity's primary key. It does, however, record the caller's `X-User-ID` where a workflow demands it: when a `FrontDeskCoordinator` opens a consultation, the `surgeon_user_id` supplied in the request body is stored on the `Consultation`, and when a surgery is booked, the operating `surgeon_user_id` is stored on the `SurgeryBooking`. Ownership checks (see §2.4) then compare `X-User-ID` against that stored `surgeon_user_id` value, not against any surgeon record's `id`, because surgeons are not first-class persisted entities in this system.

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

List endpoints accept two query parameters, `limit` and `offset`. The `limit` defaults to 10, must be at least 1, and may not exceed 100. The `offset` defaults to 0 and has a minimum of 0. Results are returned sorted by `created_at` in ascending order (oldest first), with ties broken by ascending `id`. For list responses, the `meta` object carries the pagination fields `limit`, `offset`, `total_count` (the total number of matching records ignoring pagination), and `has_more` (true when records remain beyond the current page).

### 2.4. Identity, Ownership, and Nested Path Resolution

Certain surgeon actions are restricted to the surgeon who owns the underlying resource. Completing a consultation is permitted only to the surgeon whose `X-User-ID` equals the `surgeon_user_id` recorded on that `Consultation`; a mismatch is rejected with `ERR_NOT_OWNER` (HTTP 403). The same ownership principle governs the surgeon-driven booking and complication actions, which compare the caller's `X-User-ID` against the `surgeon_user_id` recorded on the relevant `SurgeryBooking`.

Many resources are reached through nested URL paths (for example, the line items or consents beneath a quote, or the clearances beneath a patient). Path parameters are validated left to right: the outer resource is resolved first, and if it does not exist the corresponding not-found error is returned before any inner identifier or request-body foreign key is examined. Only after every path segment resolves are body-referenced foreign keys checked, again in the order they are read. The not-found errors are `ERR_PROCEDURE_NOT_FOUND`, `ERR_PATIENT_NOT_FOUND`, `ERR_CONSULTATION_NOT_FOUND`, `ERR_QUOTE_NOT_FOUND`, `ERR_LINE_ITEM_NOT_FOUND`, `ERR_CONSENT_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_FINANCING_NOT_FOUND`, and `ERR_CASE_NOT_FOUND`, each carrying HTTP 404.

### 2.5. Common Resource Properties and Versioning

Every persisted resource carries a server-minted `id`, which is a UUID used purely as an identity handle and never encodes a type prefix. Most resources also carry three additional system-managed fields: `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and `version`, an integer that begins at 1 and increments by one on every mutation of that resource. The `updated_at` value is refreshed to the current server time whenever the resource is mutated. These common fields — `created_at`, `updated_at`, and `version` — apply to `Procedure`, `Patient`, `Consultation`, `QuotePackage`, `ConsentRecord`, `ClearanceRecord`, `SurgeryBooking`, `FinancingApplication`, and `ComplicationCase`.

The sole exception is the `QuoteLineItem`, which is an append-only record. A line item carries only `id` and `created_at`; it has no `updated_at` and no `version`, because it is never mutated after creation.

### 2.6. Ledger Reconciliation and Derived Balances

The financial heart of a quote is a small ledger kept permanently reconciled. Each `QuotePackage` tracks `deposit_paid_cents` (the cumulative deposit recorded against it, starting at 0) and `financed_cents` (the amount currently covered by an approved financing application, starting at 0). Its `balance_due_cents` is always the quote's `total_cents` minus its `deposit_paid_cents` minus its `financed_cents`, and this derived field must be recomputed and kept consistent every time any of its three inputs changes. Whenever a deposit is recorded, financing is approved or voided, or a cancellation settlement returns part of a deposit to the ledger, `balance_due_cents` is recomputed from the current values so that it never drifts.

A request whose body is malformed — a required field absent, or a field of the wrong type — is rejected with `ERR_VALIDATION` (HTTP 400) before any business rule is considered.

All monetary amounts are stored as integer cents. Where a rule requires multiplying a cent amount by a fractional rate or percentage, the result is rounded half up to a whole number of cents — the standard "round half up" rule, applied exactly once at the point the specification names, never accumulated across intermediate steps.

### 2.7. Optimistic Concurrency on Booking Creation

Scheduling a surgery pins the quote's financial figures at the moment the booking is created, so the request that creates a `SurgeryBooking` must prove it is acting on a current view of the quote. The create-booking request therefore requires a non-optional `expected_quote_package_version` field carrying the client's last observed `version` of the referenced `QuotePackage`. If that value does not equal the quote's current `version` — for instance because another writer has since recorded a deposit or bound a financing application, each of which increments the quote's `version` — the booking is rejected with `ERR_STALE_VERSION` (HTTP 412). This prevents a booking from encoding outdated deposit or balance figures. No other endpoint accepts or requires a version field.

### 2.8. Cascading State Effects and Hierarchical Consistency

Several operations mutate more than one entity. When such a cascade fires, every affected resource is mutated in full: its state field is updated, its `updated_at` is refreshed, and its `version` is incremented, exactly as if it had been mutated directly. The cascades themselves — quote rejection or expiry voiding submitted financing, a booking cancellation forfeiting deposit and unwinding financing, a quote acceptance converting its parent consultation — are described in the workflow narratives of §3, where each is tied to the business event that triggers it. The governing principle here is that a derived or dependent value is never left stale: when a parent figure moves, every figure computed from it is recomputed in the same operation.

## 3. Business Logic & Workflows

### 3.1. The Procedure Catalog and Patient Intake

The catalog is the practice's menu of offerings. A `PracticeAdmin` creates a `Procedure` by supplying its `code` (a unique catalog code such as `RHINO01`), its human-readable `name`, and its three fee components in cents: `surgical_fee_cents`, `facility_fee_cents`, and `anesthesia_fee_cents`. The surgical fee must be strictly greater than zero, while the facility and anesthesia fees must each be zero or greater. The admin may optionally supply `revision_window_days`, the number of days after surgery within which a surgical-origin revision is free; it defaults to 90 and must be zero or greater. A freshly created procedure has `active` set to true and `status` of `ACTIVE`. A `PracticeAdmin` may later retire a procedure, which sets its `active` to false and its `status` to `RETIRED` so that it can no longer be added to new quotes.

Patients enter the system through intake, performed by either a `FrontDeskCoordinator` or a `Surgeon`. Creating a `Patient` requires `full_name`, `date_of_birth` (an ISO date used to derive age at clearance time), `age_years`, and `bmi`. The `age_years` value must be at least 18, and `bmi` must be strictly greater than zero. Three clinical fields are optional at intake and carry defaults: `asa_class` (the ASA physical status, an integer from 1 through 4) defaults to 1, `smoker` defaults to false, and `prior_complication_count` (the count of prior surgical complications, which must be zero or greater) defaults to 0.

At the moment a patient is created, and again whenever a `Surgeon` updates the clinical fields `asa_class`, `bmi`, `smoker`, `age_years`, or `prior_complication_count`, the system computes two derived attributes: `surgical_risk_score` and `clearance_tier`. The risk score starts at zero and accumulates penalty points. First, the ASA class contributes 25 points for each step above the minimum — that is, the ASA class minus one, multiplied by 25. Body mass adds 20 points when `bmi` is at least 35, or 10 points when `bmi` is at least 30 but below 35, and nothing below 30. A patient who smokes adds 20 points. Age adds 15 points when `age_years` is at least 65, or 8 points when `age_years` is at least 50 but below 65, and nothing below 50. Each prior complication adds 15 points, so the contribution is `prior_complication_count` multiplied by 15. The accumulated total is then clamped to the range 0 through 100 to yield `surgical_risk_score`. From that score the `clearance_tier` is derived: a score of at least 70 yields `MEDICAL`, a score of at least 40 but below 70 yields `STANDARD`, and a score below 40 yields `NONE`.

### 3.2. Consultations and the Path to a Quote

A `FrontDeskCoordinator` opens a `Consultation` by supplying the `patient_id`, the `surgeon_user_id` of the surgeon who will own the consultation, and a `chief_complaint` describing the reason for the visit. The consultation begins in `SCHEDULED`. Its owning surgeon later completes it, moving it from `SCHEDULED` to `COMPLETED`; this transition is permitted only when the consultation is currently `SCHEDULED` (otherwise `ERR_INVALID_STATE`) and only to the surgeon who owns it (otherwise `ERR_NOT_OWNER`, as described in §2.4).

A consultation is closed by a `FrontDeskCoordinator` and may move to `CLOSED` from any of `SCHEDULED`, `COMPLETED`, or `CONVERTED`. Closing is blocked, however, if any `QuotePackage` on that consultation is still in `PRESENTED` status; such an attempt is rejected with `ERR_OPEN_QUOTE_EXISTS`. There is also a system-driven transition from `COMPLETED` to `CONVERTED`, which is not called directly: it fires automatically as a side effect when a quote package belonging to the consultation is accepted (see §3.3).

### 3.3. Building, Presenting, and Accepting a Quote

Once a consultation is completed, a `FrontDeskCoordinator` creates a `QuotePackage` against it by supplying the `consultation_id`. The new quote starts in `DRAFT`, copies the `patient_id` from the consultation, and initializes its totals and ledger figures to zero. The coordinator then adds procedure lines to the draft. Each line-item add supplies a `procedure_id`; the quote must currently be `DRAFT` (adding a line to a quote in any other state is rejected with `ERR_INVALID_STATE`, checked after the procedure's existence but before the retired check), and the referenced procedure must be `ACTIVE`, with adding a retired procedure rejected with `ERR_PROCEDURE_RETIRED`.

Adding a line creates a `QuoteLineItem` carrying its own `id`, a `quote_package_id` linking it to its quote, and the `procedure_id` it references. At add time the system snapshots the procedure's three fees onto the line as `surgical_fee_cents`, `facility_fee_cents`, and `anesthesia_fee_cents`, so that later catalog edits never disturb an existing quote. The line's `bundle_total_cents` is the sum of those three snapshotted fees. Because these are integer cents, no rounding is involved in the bundle total.

Every line add or removal while the quote is still `DRAFT` recomputes the quote's pricing. The `subtotal_cents` is the sum of the `bundle_total_cents` across all line items on the quote. A multi-procedure discount is then keyed on the count of line items: three or more lines yield a `discount_pct` of 0.10, exactly two lines yield 0.05, and a single line yields no discount (0.00); a draft with no lines has a subtotal of zero. The rounding order is fixed: the system first sums the bundle totals as integer cents, then applies the discount to that subtotal by multiplying it by one minus the discount fraction, and only then rounds the result half up to whole cents to obtain `total_cents`. Discounts are never applied per line item. The `required_deposit_cents` is then computed as 20 percent of `total_cents`, rounded half up to whole cents.

Presenting the quote is a `FrontDeskCoordinator` action that moves it from `DRAFT` to `PRESENTED`. It requires the quote to currently be `DRAFT` (otherwise `ERR_INVALID_STATE`) and to have at least one line item (otherwise `ERR_EMPTY_QUOTE`). Presentation freezes the pricing: `subtotal_cents`, `discount_pct`, `total_cents`, and `required_deposit_cents` are locked at their presentation-time values and no longer recompute.

Accepting a presented quote is likewise a `FrontDeskCoordinator` action, moving it from `PRESENTED` to `ACCEPTED`. Acceptance requires three things, and the quote must currently be `PRESENTED` (otherwise `ERR_INVALID_STATE`). First, a `ConsentRecord` for this quote must be `SIGNED` with `surgical_consent_signed` equal to true; absent that, the request is rejected with `ERR_CONSENT_MISSING`. Second, the recorded deposit must cover the required deposit: `deposit_paid_cents` must be at least `required_deposit_cents`, otherwise `ERR_DEPOSIT_UNPAID`. When acceptance succeeds, two side effects fire: the parent `Consultation` transitions from `COMPLETED` to `CONVERTED`, and the quote's `balance_due_cents` is recomputed.

Deposits are recorded by a `BillingSpecialist` against a quote. Each deposit posting supplies an `amount_cents` (which must be strictly greater than zero, otherwise `ERR_VALIDATION`), which is added to the quote's cumulative `deposit_paid_cents`; the quote's `balance_due_cents` is then recomputed. A deposit posting responds with HTTP 201 and returns the updated `QuotePackage` resource in `data`. Because recording a deposit mutates the quote, it also increments the quote's `version`, which is what makes an in-flight booking request's pinned version stale (see §2.7).

A presented quote may instead be rejected by a `FrontDeskCoordinator`, moving it from `PRESENTED` to `REJECTED`; this requires the quote to be `PRESENTED` (otherwise `ERR_INVALID_STATE`). A quote may also be expired by a `FrontDeskCoordinator` from either `DRAFT` or `PRESENTED`, moving it to `EXPIRED` (again `ERR_INVALID_STATE` if it is in neither of those states). Both rejection and expiry carry the same cascade: any `FinancingApplication` on the quote that is still `SUBMITTED` is transitioned to `VOIDED`. `REJECTED` and `EXPIRED` are terminal states for a quote.

### 3.4. Consent Capture and Photo Authorization

Consent is captured against a quote by either a `FrontDeskCoordinator` or a `Surgeon`. Creating a `ConsentRecord` supplies the `before_photo_ref` (a storage reference for the before photo), `photo_consent_signed` (whether the patient authorized clinical and marketing photo use), and `surgical_consent_signed` (whether the patient signed informed surgical consent). If `surgical_consent_signed` is true the record is created directly in `SIGNED`; otherwise it is created in `PENDING`. A `Surgeon` may revoke a consent record, moving its `status` to `REVOKED`; this action carries no state precondition and is permitted regardless of the record's current status. Only a consent that is `SIGNED` with `surgical_consent_signed` true satisfies the acceptance precondition of §3.3, so a revoked or pending consent will not unblock quote acceptance.

### 3.5. Pre-Operative Clearance

Before surgery can be booked, the patient must be medically cleared to the tier their risk demands. A `Surgeon` issues a `ClearanceRecord` for a patient by supplying `tier_provided`, the clearance level being attached, which is either `STANDARD` or `MEDICAL`. At issue time the system snapshots the patient's current `clearance_tier` into the record's `tier_required` (one of `NONE`, `STANDARD`, or `MEDICAL`), and computes `cleared`: the clearance is considered satisfied when the provided tier meets or exceeds the required tier. Concretely, a required tier of `NONE` is satisfied by any provided tier; a required tier of `STANDARD` is satisfied by a provided `STANDARD` or `MEDICAL`; and a required tier of `MEDICAL` is satisfied only by a provided `MEDICAL`. A newly issued record has `status` of `ISSUED`; while `REVOKED` is a defined clearance status, no endpoint exposes a revocation transition, so a clearance created through the API remains `ISSUED`. Booking a surgery requires an `ISSUED` clearance for the patient whose `cleared` is true (see §3.6).

### 3.6. Scheduling Surgery: Safety, Calendar, and Concurrency Gates

Scheduling is the most heavily guarded operation in the system. A `FrontDeskCoordinator` books surgery for an accepted quote by supplying the `quote_package_id`, the operating `surgeon_user_id`, the `or_room` (an operating-room label such as `OR1`), the `scheduled_start` and `scheduled_end` (both ISO 8601 UTC instants), and the `expected_quote_package_version` for the concurrency check of §2.7. The booking is created in `SCHEDULED`, and the `patient_id` is copied from the quote. Creating the booking mutates the referenced quote as a side effect — refreshing its `updated_at` and incrementing its `version` — even though the quote's ledger figures are unchanged. The booking is created with its `deposit_forfeited_cents` and `deposit_refunded_cents` both initialized to 0.

A cluster of gates guards this operation, and they are evaluated in the platform-wide priority order (authentication, then authorization, then existence of referenced resources, then state validity) before the booking-specific business checks. Among the booking-specific checks: the patient must have an `ISSUED` clearance whose `cleared` is true, otherwise `ERR_CLEARANCE_MISSING`. The requested operating-room interval must not overlap an existing `SCHEDULED` booking in the same `or_room`; the interval is treated as half-open, meaning two intervals conflict when one starts strictly before the other ends and the second starts strictly before the first ends — so two bookings that merely touch at an endpoint (one ending exactly when the next begins) do not conflict. A conflict here is `ERR_OR_DOUBLE_BOOKED`. The surgeon calendar is guarded more strictly: a new booking must leave a 60-minute turnaround buffer around any existing `SCHEDULED` booking with the same `surgeon_user_id`. Two bookings conflict on this rule when one starts strictly before the other's end extended forward by 60 minutes and the other starts strictly before the first's end extended forward by 60 minutes — so unlike the operating-room rule, exactly touching endpoints do conflict here, because the buffer is greater than zero. A surgeon conflict is `ERR_SURGEON_BUFFER_CONFLICT`. The `scheduled_start` must be strictly in the future relative to the current logical clock, otherwise `ERR_SURGERY_IN_PAST`. The `scheduled_end` must be strictly after `scheduled_start`, otherwise `ERR_INVALID_TIME_RANGE`. And the concurrency guard of §2.7 applies: a stale `expected_quote_package_version` yields `ERR_STALE_VERSION`.

When several of these conditions could fail at once, they are applied in a fixed priority. Authentication precedes authorization, which precedes existence checks on the referenced resources, which precede the state check that the quote is in an acceptable state. The surgeon-ownership check (used by surgeon actions elsewhere) sits just below those. The business gates then follow in this order: procedure-retired and empty-quote checks for their respective operations, then for booking the clearance-present safety check, then the operating-room overlap check, then the surgeon turnaround-buffer check, then the future-start check, then the deposit and financing fiscal checks where applicable, then the optimistic-concurrency version check, and finally the time-range check that the end follows the start. A single request that trips more than one of these surfaces the earliest one in this ordering.

### 3.7. Completing and Cancelling Surgery

The owning `Surgeon` completes a booking, moving it from `SCHEDULED` to `COMPLETED`. Completion requires the booking to be `SCHEDULED` (otherwise `ERR_INVALID_STATE`) and requires the current logical clock to have reached or passed `scheduled_start` — that is, the clock must be at or after the scheduled start — otherwise `ERR_SURGERY_NOT_STARTED`. On completion the quote's deposit and financing are consumed and `balance_due_cents` is recomputed; in practice this recomputation leaves `deposit_paid_cents` and `financed_cents` (and hence `balance_due_cents`) unchanged, and the quote is nonetheless mutated — its `updated_at` refreshed and its `version` incremented. `COMPLETED` is terminal.

A `BillingSpecialist` cancels a scheduled booking, moving it from `SCHEDULED` to `CANCELLED` (again `ERR_INVALID_STATE` if not `SCHEDULED`). Cancellation triggers a settlement and a three-hop cascade. The settlement first determines the notice window: the number of whole days of notice is the difference between `scheduled_start` and the current logical clock, expressed in seconds and divided by the number of seconds in a day (86,400), taking the floor. If that notice is at least 30 days, the refund fraction is the full 1.00; if it is at least 14 days but fewer than 30, the refund fraction is 0.50; and if it is fewer than 14 days, the refund fraction is 0.00. The `deposit_refunded_cents` is the quote's current `deposit_paid_cents` multiplied by the refund fraction, rounded half up to whole cents, and the `deposit_forfeited_cents` is the remainder — the recorded deposit minus the refunded portion — so that the forfeited and refunded amounts always sum exactly to the deposit that was paid, with no drift.

The cancellation then cascades in three ordered hops. In the first hop, the refunded portion leaves the quote ledger: the quote's `deposit_paid_cents` is reduced by `deposit_refunded_cents`. In the second hop, each `FinancingApplication` on the quote that is `APPROVED` or `SUBMITTED` is transitioned to `VOIDED`; and every application that had been `APPROVED` runs its own reversal, reducing the quote's `financed_cents` by that application's `approved_amount_cents`. In the third hop, driven by the change to `financed_cents`, the quote's `balance_due_cents` is recomputed as `total_cents` minus `deposit_paid_cents` minus `financed_cents`. `CANCELLED` is terminal.

### 3.8. Financing the Balance

A `BillingSpecialist` submits a `FinancingApplication` against a quote by supplying the `quote_package_id`, the `lender` (either `CARECREDIT` or `CHERRY`), and the `requested_amount_cents` the patient wishes financed, which must be strictly greater than zero. The application is created in `SUBMITTED` with `approved_amount_cents`, `merchant_fee_cents`, and `practice_net_cents` all initialized to 0.

Approval is a `BillingSpecialist` action moving the application from `SUBMITTED` to `APPROVED`. It requires the application to currently be `SUBMITTED` (otherwise `ERR_INVALID_STATE`), the parent quote to be `ACCEPTED` (otherwise `ERR_QUOTE_NOT_ACCEPTED`), and the amount to fit within the quote's current balance — the `approved_amount_cents` must not exceed the quote's `balance_due_cents` at approval time, otherwise `ERR_FINANCING_EXCEEDS_BALANCE`. On approval the lender approves the requested amount in full, so `approved_amount_cents` is set equal to `requested_amount_cents`. The system then computes the lender's merchant discount fee: for a `CHERRY` application the `merchant_fee_cents` is 5 percent of `approved_amount_cents`, and for a `CARECREDIT` application it is 3 percent of `approved_amount_cents`, in each case rounded half up to whole cents. The `practice_net_cents` — what the practice actually collects after the lender's cut — is `approved_amount_cents` minus `merchant_fee_cents`. Approval then cascades onto the quote: `financed_cents` is increased by `approved_amount_cents`, and `balance_due_cents` is recomputed accordingly.

An application may instead be declined by a `BillingSpecialist`, moving it from `SUBMITTED` to `DECLINED` (with `ERR_INVALID_STATE` if it is not `SUBMITTED`); a decline has no ledger side effect. `DECLINED` and `VOIDED` are terminal. Voiding is never called directly: it is the system-driven consequence of a quote being rejected or expired, or a booking being cancelled, as described in §3.3 and §3.7. When a voided application had previously been `APPROVED`, its void reverses the quote ledger by reducing `financed_cents` by its `approved_amount_cents` and recomputing `balance_due_cents`; a void of a merely `SUBMITTED` application has no ledger effect.

### 3.9. Complications and the Revision Policy

After a surgery is completed, a `Surgeon` opens a `ComplicationCase` by supplying the `surgery_booking_id`, the `line_item_id` (the affected `QuoteLineItem` whose surgical fee drives any revision charge), and the `attribution` describing the cause, which is one of `SURGICAL_ORIGIN`, `PATIENT_FACTOR`, or `UNRELATED`. The case opens in `OPEN`, and its `reported_at` is stamped with the current logical clock. Opening a case itself carries no check on the parent booking's status — the requirement that the booking be `COMPLETED` is enforced only at the review step below, not at open time — and its `within_revision_window` and `revision_charge_cents` fields are initialized to null, remaining null until a revision is approved.

The case moves through a small cyclic workflow, all steps performed by a `Surgeon`. Moving a case from `OPEN` to `UNDER_REVIEW` requires the case to be `OPEN` (otherwise `ERR_INVALID_STATE`) and the parent `SurgeryBooking` to be `COMPLETED` (otherwise `ERR_BOOKING_NOT_COMPLETED`). A case may be sent back from `UNDER_REVIEW` to `OPEN`, which clears any provisional attribution decision — resetting both `within_revision_window` and `revision_charge_cents` back to null — and returns the case to intake — this is the cyclic revision loop, and it requires the case to be `UNDER_REVIEW` (otherwise `ERR_INVALID_STATE`). Approving a revision moves the case from `UNDER_REVIEW` to `REVISION_APPROVED` and requires the case to be `UNDER_REVIEW` (otherwise `ERR_INVALID_STATE`); this step computes `within_revision_window` and `revision_charge_cents`. Finally, a case may be resolved to `RESOLVED` from `OPEN`, `UNDER_REVIEW`, or `REVISION_APPROVED` (otherwise `ERR_INVALID_STATE`); `RESOLVED` is terminal.

The revision charge turns on whether the case falls inside the procedure's revision window and on its attribution. The relevant window is the `revision_window_days` of the procedure behind the affected line item. The case is `within_revision_window` when its `reported_at` is at or before the booking's `scheduled_end` advanced by that many days — that is, `scheduled_end` plus the window expressed in seconds, where each day is 86,400 seconds. When the attribution is `SURGICAL_ORIGIN` and the case is within the revision window, the revision is free and `revision_charge_cents` is 0. In every other case — a non-surgical attribution, or a surgical-origin case reported after the window closes — the charge is 50 percent of the affected line item's `surgical_fee_cents`, rounded half up to whole cents.

### 3.10. The Logical Clock

Because so many rules — cancellation notice tiers, "surgery not started," future-dated starts, complication reporting time, and revision windows — depend on time, the platform runs on a logical clock that a `PracticeAdmin` can set to any UTC instant. This administrative test-driving capability accepts a `to_iso8601` target and moves the clock to it, responding with HTTP 200 and a `data` object of the shape `{"current_utc": <target>}` (this endpoint returns neither a persisted resource nor the common `id`/`created_at`/`version` fields). On server startup the clock reads exactly `2026-05-01T00:00:00Z` and, until a set call is made, holds that default rather than ever falling back to real wall-clock time. Every time-relative rule in this document is evaluated against this clock.

## 4. Endpoint Definitions

All endpoints share the response envelope of §2.2. Newly created resources return HTTP 201; state transitions, updates, retrievals, and other modifications return HTTP 200. The one exception among mutations is recording a deposit (`POST /quote-packages/{id}/deposits`), which returns HTTP 201 even though it mutates the existing `QuotePackage` rather than creating a new resource; the clock-set endpoint (`POST /_clock/set_current_utc`) returns HTTP 200. Every request must carry the `X-User-ID` and `X-User-Role` headers.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/_clock/set_current_utc` | Set the logical clock to a UTC instant | PracticeAdmin |
| POST | `/procedures` | Create a catalog procedure | PracticeAdmin |
| GET | `/procedures` | List procedures | PracticeAdmin, FrontDeskCoordinator, Surgeon, BillingSpecialist |
| GET | `/procedures/{id}` | Get a procedure | PracticeAdmin, FrontDeskCoordinator, Surgeon, BillingSpecialist |
| POST | `/procedures/{id}/retire` | Retire a procedure | PracticeAdmin |
| GET | `/procedures/{id}/line-items` | List line items that snapshotted this procedure | PracticeAdmin, FrontDeskCoordinator, Surgeon, BillingSpecialist |
| POST | `/patients` | Create a patient (computes risk score and clearance tier) | FrontDeskCoordinator, Surgeon |
| GET | `/patients/{id}` | Get a patient | FrontDeskCoordinator, Surgeon, BillingSpecialist |
| PATCH | `/patients/{id}` | Update clinical fields; recompute risk and tier | Surgeon |
| POST | `/patients/{id}/clearances` | Issue a clearance record | Surgeon |
| GET | `/patients/{id}/clearances` | List clearances for a patient | FrontDeskCoordinator, Surgeon, BillingSpecialist |
| GET | `/patients/{id}/consultations` | List consultations for a patient | FrontDeskCoordinator, Surgeon, BillingSpecialist |
| GET | `/patients/{id}/quote-packages` | List quote packages for a patient | FrontDeskCoordinator, Surgeon, BillingSpecialist |
| GET | `/patients/{id}/surgery-bookings` | List surgery bookings for a patient | FrontDeskCoordinator, Surgeon, BillingSpecialist |
| POST | `/consultations` | Open a consultation | FrontDeskCoordinator |
| GET | `/consultations/{id}` | Get a consultation | FrontDeskCoordinator, Surgeon, BillingSpecialist |
| POST | `/consultations/{id}/complete` | Complete a consultation (owner surgeon) | Surgeon |
| POST | `/consultations/{id}/close` | Close a consultation | FrontDeskCoordinator |
| GET | `/consultations/{id}/quote-packages` | List quote packages under a consultation | FrontDeskCoordinator, Surgeon, BillingSpecialist |
| POST | `/quote-packages` | Create a draft quote package | FrontDeskCoordinator |
| GET | `/quote-packages/{id}` | Get a quote package | FrontDeskCoordinator, Surgeon, BillingSpecialist |
| POST | `/quote-packages/{id}/line-items` | Add a procedure line to a draft quote | FrontDeskCoordinator |
| GET | `/quote-packages/{id}/line-items` | List line items of a quote | FrontDeskCoordinator, Surgeon, BillingSpecialist |
| POST | `/quote-packages/{id}/deposits` | Record a deposit payment | BillingSpecialist |
| POST | `/quote-packages/{id}/present` | Present the quote (freeze pricing) | FrontDeskCoordinator |
| POST | `/quote-packages/{id}/accept` | Accept a presented quote | FrontDeskCoordinator |
| POST | `/quote-packages/{id}/reject` | Reject a presented quote | FrontDeskCoordinator |
| POST | `/quote-packages/{id}/expire` | Expire a draft or presented quote | FrontDeskCoordinator |
| POST | `/quote-packages/{id}/consents` | Create a consent record for a quote | FrontDeskCoordinator, Surgeon |
| GET | `/quote-packages/{id}/consents` | List consent records for a quote | FrontDeskCoordinator, Surgeon, BillingSpecialist |
| POST | `/consents/{id}/revoke` | Revoke a consent record | Surgeon |
| POST | `/surgery-bookings` | Schedule surgery for an accepted quote | FrontDeskCoordinator |
| GET | `/surgery-bookings/{id}` | Get a surgery booking | FrontDeskCoordinator, Surgeon, BillingSpecialist |
| GET | `/surgery-bookings` | List surgery bookings (optional query filters `quote_package_id` and/or `patient_id`) | FrontDeskCoordinator, Surgeon, BillingSpecialist |
| POST | `/surgery-bookings/{id}/complete` | Complete surgery (owner surgeon) | Surgeon |
| POST | `/surgery-bookings/{id}/cancel` | Cancel surgery and settle deposit | BillingSpecialist |
| POST | `/financing-applications` | Submit a financing application | BillingSpecialist |
| GET | `/financing-applications/{id}` | Get a financing application | FrontDeskCoordinator, Surgeon, BillingSpecialist |
| GET | `/financing-applications` | List financing applications (optional query filter `quote_package_id`) | FrontDeskCoordinator, Surgeon, BillingSpecialist |
| POST | `/financing-applications/{id}/approve` | Approve financing | BillingSpecialist |
| POST | `/financing-applications/{id}/decline` | Decline financing | BillingSpecialist |
| POST | `/complication-cases` | Open a complication case | Surgeon |
| GET | `/complication-cases/{id}` | Get a complication case | FrontDeskCoordinator, Surgeon, BillingSpecialist |
| GET | `/complication-cases` | List complication cases (optional query filters `surgery_booking_id` and/or `line_item_id`) | FrontDeskCoordinator, Surgeon, BillingSpecialist |
| POST | `/complication-cases/{id}/review` | Move a case to under review | Surgeon |
| POST | `/complication-cases/{id}/reopen` | Send a case back to open | Surgeon |
| POST | `/complication-cases/{id}/approve-revision` | Approve a revision and compute the charge | Surgeon |
| POST | `/complication-cases/{id}/resolve` | Resolve a complication case | Surgeon |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_OWNER | 403 |
| ERR_VALIDATION | 400 |
| ERR_INVALID_TIME_RANGE | 400 |
| ERR_PROCEDURE_NOT_FOUND | 404 |
| ERR_PATIENT_NOT_FOUND | 404 |
| ERR_CONSULTATION_NOT_FOUND | 404 |
| ERR_QUOTE_NOT_FOUND | 404 |
| ERR_LINE_ITEM_NOT_FOUND | 404 |
| ERR_CONSENT_NOT_FOUND | 404 |
| ERR_BOOKING_NOT_FOUND | 404 |
| ERR_FINANCING_NOT_FOUND | 404 |
| ERR_CASE_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_OPEN_QUOTE_EXISTS | 409 |
| ERR_EMPTY_QUOTE | 409 |
| ERR_PROCEDURE_RETIRED | 409 |
| ERR_CONSENT_MISSING | 409 |
| ERR_CLEARANCE_MISSING | 409 |
| ERR_QUOTE_NOT_ACCEPTED | 409 |
| ERR_BOOKING_NOT_COMPLETED | 409 |
| ERR_SURGERY_NOT_STARTED | 409 |
| ERR_SURGERY_IN_PAST | 409 |
| ERR_OR_DOUBLE_BOOKED | 409 |
| ERR_SURGEON_BUFFER_CONFLICT | 409 |
| ERR_DEPOSIT_UNPAID | 402 |
| ERR_FINANCING_EXCEEDS_BALANCE | 402 |
| ERR_STALE_VERSION | 412 |
