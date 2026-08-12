# Home Medical Supply & DME Mail-Order API — Product Requirements Document

## 1. Introduction

Home medical supply and durable medical equipment (DME) mail-order businesses live or die by timing and paperwork. A patient managing an ostomy, incontinence, or a chronic wound cannot simply reorder supplies when the closet runs empty: payers impose resupply cycles measured in months, Medicare DMEPOS rules demand prescriptions with diagnosis codes, certain products require prior authorization before a box may leave the warehouse, and cash-paying patients draw down finite HSA balances. Mistakes are expensive in both directions — ship too early and the claim is denied; ship too late and adherence collapses and the patient churns to a competitor.

This document specifies the Home Medical Supply & DME Mail-Order API, the backend that coordinates the full cycle: payer plan and formulary configuration, patient intake and eligibility verification, clinical documentation (prescriptions, fit measurements, prior authorizations), recurring resupply programs with adherence scoring, order capture and submission gates, warehouse fulfillment with stock reservation and backorder allocation, claim submission and adjudication, an append-only HSA ledger, and free fitting samples. All operations are mounted under `/api` and are evaluated against a logical clock that administrators control for testing and audit replay.

Two design commitments pervade the specification. First, the system is temporal: prescriptions, prior authorizations, resupply eligibility windows, and sample limits are all evaluated against the current logical date, and several entities expire lazily when read. Second, the system is fiscally conservative: money is tracked in integer cents with pinned rounding order, the HSA ledger never allows an overdraft, and a denial that pushes a patient's balance below the reorder floor automatically suspends their resupply programs so the business stops shipping goods it will not be paid for.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes six distinct roles: `Patient`, `IntakeCoordinator`, `PriorAuthSpecialist`, `FulfillmentAgent`, `BillingSpecialist`, and `PlatformAdmin`. A request missing either header, or carrying a role other than these six, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Once authenticated, the caller's role must appear in the endpoint's authorized role set, or the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The `Patient` role is entity-backed: when `X-User-Role` is `Patient`, `X-User-ID` is the `id` of the acting `Patient`, and ownership checks on any resource that references a `Patient` compare the resource's patient foreign-key field to `X-User-ID`. A `Patient` acting on another patient's resource is rejected with `ERR_FORBIDDEN`. When `X-User-Role` is `IntakeCoordinator`, `PriorAuthSpecialist`, `FulfillmentAgent`, `BillingSpecialist`, or `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.

Role responsibilities in brief: a `Patient` confirms their own resupply cycles, creates, submits, and cancels their own orders, adds lines to their own draft orders, and reads their own resources. An `IntakeCoordinator` owns enrollment and clinical intake — creating and verifying patients, creating and cancelling prescriptions, recording fit profiles, creating, suspending, and resuming resupply programs, requesting fitting samples, and recording sample outcomes — and may also confirm cycles and manage orders on a patient's behalf. A `PriorAuthSpecialist` owns the prior authorization lifecycle: creating authorizations, recording payer decisions, and filing appeals. A `FulfillmentAgent` runs the warehouse: creating, releasing, shipping, delivering, and returning shipments, and shipping samples. A `BillingSpecialist` owns claims and the HSA ledger: creating, submitting, adjudicating, and appealing claims, and posting HSA debits and credits. A `PlatformAdmin` manages configuration — payer plans, formulary items, stock levels and restock — and is the only role permitted to set the logical clock.

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

Requests that fail before any resource logic is reached are rejected uniformly: an absent request body is treated as an empty object, but a malformed or non-object JSON body, a missing required field, or a wrongly-typed field value yields `ERR_INVALID_REQUEST` (HTTP 400); an unknown route yields `ERR_NOT_FOUND` (HTTP 404); a known route called with an unsupported method yields `ERR_INVALID_REQUEST` with HTTP 405; and an unexpected server failure yields `ERR_INTERNAL` with HTTP 500.

### 2.3. Pagination

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. A non-integer `limit` or `offset`, a `limit` below 1 or above 100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order, ties broken by `id` ascending.

Paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

Five bounded sub-resource listings return their full result set unpaginated, still sorted as above, with `meta` carrying only `api_request_id` and `api_request_timestamp`: the stock rows of an item, the HSA accounts of a patient, the shipments of an order, the claims of an order, and the backorder reservations of an order line.

### 2.4. Common Resource Properties

Every primary resource in the system carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 timestamp in UTC with three fractional digits, set when the resource is first created.
- `updated_at` (string): an ISO 8601 UTC timestamp updated upon any change to the resource.
- `version` (integer): a system-managed integer that starts at 1 when the resource is created and increments by one with every modification to the resource, including modifications driven by system cascades.

The one exception is the HSA ledger entry. A ledger entry is immutable and append-only; it carries `id` and `created_at` but neither `updated_at` nor `version`. Every other resource — payer plans, formulary items, patients, prescriptions, fit profiles, resupply programs, orders, order lines, prior authorizations, shipments, stock levels, backorder reservations, claims, HSA accounts, and fitting samples — carries all four common fields, and any mutation described in this document (including side-effect cascades onto a related entity) refreshes that entity's `updated_at` and increments its `version` by one.

### 2.5. Money, Units, and the Pinned Rounding Order

All monetary values are expressed as numbers in cents with exactly 2 decimal places, rounded half up. Dates are ISO calendar dates (YYYY-MM-DD) and datetimes are ISO 8601 UTC.

One rounding order is pinned across the entire pricing pipeline and may not be reordered: the per-unit proration of a payer's pack fee is rounded half up to 2 decimal places **first**, and only then multiplied by the line quantity and rounded half up again. The alternative — multiplying the pack fee by the quantity first and dividing by the pack size with a single final rounding — is forbidden, because the two orderings yield different cent amounts. For example, a pack fee of 999 cents over a pack size of 8 produces a unit allowance of 124.88 cents; a line of 3 units must price at 374.64 cents under the pinned per-unit-first order, whereas the forbidden single-round order would produce 374.63 cents. Implementations must reproduce the pinned order exactly.

### 2.6. Resolving Nested References

The API enforces a strict, left-to-right resolution protocol for every request. Identifiers in the URL path are resolved first, in the order they appear; if any path identifier does not correspond to an existing resource, the request is rejected immediately with `ERR_NOT_FOUND` (HTTP 404) for the first unresolvable identifier, before later identifiers or body content are examined. Foreign-key identifiers carried in the request body — such as `patient_id`, `formulary_item_id`, `payer_plan_id`, `resupply_program_id`, or `order_id` — are resolved next, and an unresolvable reference is likewise rejected with `ERR_NOT_FOUND`.

### 2.7. The Logical Clock and Lazy Expiry

The system evaluates every date-sensitive rule — prescription validity windows, prior authorization windows, resupply eligibility, adherence periods, and the sample lookback — against a **logical clock**, never against wall-clock time. On server startup, before any administrative intervention, the logical clock reads exactly 2026-05-01T00:00:00Z. A `PlatformAdmin` may advance the logical clock to a supplied instant via the test-driving capability, passing the target as `to_iso8601`; after the clock moves, the next read of any time-sensitive resource observes the new date. The logical clock also supplies every server-generated timestamp in the system — the response `meta` timestamp and every entity's `created_at` and `updated_at` — and stamps are issued strictly monotonically, each at least one millisecond after the previous stamp, even if the clock is moved backwards. A timezone-less `to_iso8601` is read as UTC; an unparseable value is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Two resources expire **lazily**. A `Prescription` in `ACTIVE` status flips to `EXPIRED` whenever it is read directly, or referenced by a validation, at a moment when the current logical date is on or after its `expiration_date`; the flip increments the prescription's `version` by one. A `PriorAuthorization` in `APPROVED` status flips to `EXPIRED` whenever it is read directly and the current logical date is strictly after its `valid_to`, again incrementing its `version` by one. Both `EXPIRED` states are terminal. A "read directly" covers both the single-resource GET and the per-patient list endpoint of the resource, so the flip fires on those listings as well. Crucially, the prior authorization gate evaluated at shipment release works from the stored authorization rows as they are: the lazy flip to `EXPIRED` applies only on direct reads of the authorization itself, and does not fire during release evaluation (see §3.6).

### 2.8. Optimistic Concurrency Control

Two write operations guard a parent entity against writers holding a stale view, and both require a version field as a non-optional input.

When creating a fit profile, the request must carry `expected_patient_version` holding the `version` of the patient as the client last observed it. If the patient's current `version` does not match — because another write has advanced it since the client's last read — the create is rejected with `ERR_STALE_VERSION` (HTTP 412). This guard exists because profile creation legitimately supersedes the patient's prior measurement, and a writer holding a stale view of the patient must be refused rather than allowed to supersede blindly.

When adding an order line, the request must carry `expected_order_version` holding the `version` of the parent order as the client last observed it. A mismatch with the order's current `version` is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412), since a stale writer would otherwise price and validate its line against an out-of-date line set.

The version check is evaluated after reference resolution (§2.6) and before every state-machine and business check of the endpoint. No other endpoint accepts a version field.

### 2.9. Cascading Consistency Across Entities

State changes rarely stay on one row. The system upholds the following propagation rules automatically, without requiring a client request against the affected resource: cancelling an order cancels its open shipments and releases their reserved stock; adjudicating a claim moves the order's billing dimension; a returned shipment recomputes program adherence and can auto-suspend the program; a final claim denial debits the patient's HSA account and can suspend every one of the patient's active programs; a restock allocates units down the backorder queue and revives fully-covered backordered shipments. Each cascade is described at its point of origin in §3, and every cascade that mutates an entity refreshes that entity's `updated_at` and increments its `version` by one, per §2.4.

### 2.10. Validation Priority Order

When several checks could reject the same request, they are evaluated in a fixed priority order so that the caller always receives the most fundamental failure first. Authentication and authorization come first (missing or unknown credentials yield `ERR_UNAUTHENTICATED`; a disallowed role or a `Patient` touching another patient's resource yields `ERR_FORBIDDEN`). Next, reference resolution runs per §2.6 (`ERR_NOT_FOUND`). Next come state-machine checks: an unavailable transition or a locked terminal state yields `ERR_INVALID_STATE`, and the endpoint-specific state gates (`ERR_ORDER_NOT_DRAFT`, `ERR_PROGRAM_SUSPENDED`, `ERR_PROGRAM_NOT_SUSPENDED`, `ERR_PATIENT_NOT_ACTIVE`, `ERR_SHIPMENT_BACKORDERED`, `ERR_CLAIM_NOT_SUBMITTABLE`, `ERR_HSA_ENTRY_NOT_REVERSIBLE`) are evaluated at this band. Business-safety checks follow (`ERR_DIAGNOSIS_REQUIRED`, `ERR_NO_VALID_PRESCRIPTION`, `ERR_PRIOR_AUTH_REQUIRED`, `ERR_SAMPLE_LIMIT_EXCEEDED`), then business-constraint checks (`ERR_ITEM_NOT_ON_FORMULARY`, `ERR_SIZE_MISMATCH`, `ERR_DUPLICATE_PROGRAM`, `ERR_DUPLICATE_STOCK_LEVEL`, `ERR_PRESCRIPTION_WINDOW_OVERLAP`, `ERR_AUTH_WINDOW_OVERLAP`, `ERR_QUANTITY_EXCEEDS_ALLOWANCE`), then business-temporal checks (`ERR_RESUPPLY_WINDOW_NOT_OPEN`, `ERR_PRIOR_AUTH_EXPIRED`), and finally fiscal checks (`ERR_INSUFFICIENT_HSA`). A request failing at an earlier band never reports an error from a later band.

## 3. Business Logic & Workflows

### 3.1. Configuring Coverage: Payer Plans and the Formulary

Everything downstream depends on two configuration objects that a `PlatformAdmin` maintains. A **payer plan** is created with a display `name`, a `plan_type` of `MEDICARE_DMEPOS`, `COMMERCIAL`, or `CASH_HSA`, a `coinsurance_pct` expressing the patient's share of the allowed amount for insured plans (0.20 means twenty percent), and a `cycle_months` count describing how many months of supply one resupply cycle covers — Medicare DMEPOS plans run three-month cycles, while other plans typically run one. For a `CASH_HSA` plan the `coinsurance_pct` must be exactly 1.00, since the patient pays everything. A `coinsurance_pct` outside [0, 1], a `CASH_HSA` `coinsurance_pct` other than 1.00, or a `cycle_months` that is not an integer of at least 1 is rejected with `ERR_INVALID_REQUEST` (HTTP 400). A plan is created with `is_active` defaulting to true; only an active plan accepts new patients, which matters at eligibility verification time. The set of patients currently covered by a plan can be listed from the plan.

A **formulary item** represents a billable product. It is created with an `hcpcs_code` (the HCPCS billing code, e.g. A4419), a display `name`, a `category` of `OSTOMY`, `INCONTINENCE`, or `WOUND`, a `covered_plan_ids` array naming the payer plans whose formulary includes the item, a `pack_fee_cents` fee-schedule amount per pack in cents, a `pack_size` count of billable units per pack (at least 1), a `retail_price_cents` cash unit price used by the `CASH_HSA` pricing variant, a `max_units_per_cycle` formulary cap, an optional `requires_pa` flag defaulting to false that marks items whose shipment release demands an approved prior authorization, and a `size_codes` array of offered sizes (e.g. 45MM, 57MM). `pack_fee_cents` and `retail_price_cents` must be at least 0 and `max_units_per_cycle` at least 1, else `ERR_INVALID_REQUEST` (HTTP 400); the entries of `covered_plan_ids` are stored as supplied and are not resolved at creation. On creation the server computes `unit_allowance_cents` as the pack fee divided by the pack size, rounded half up to 2 decimal places under the pinned order of §2.5; the result may carry fractional cents and is the insured per-unit basis used everywhere downstream. An item's `status` is `ACTIVE` by default (creation also accepts an explicit `DISCONTINUED`) and becomes `DISCONTINUED` when the item leaves the formulary. The formulary can be listed with an optional `category` filter and the standard `limit`/`offset` pagination; the order lines referencing an item can be listed from the item as well.

Warehouse stock is tracked per item: a `PlatformAdmin` creates one **stock level** row per formulary item, carrying `formulary_item_id` and the physical `on_hand_qty`. At most one stock row may exist per item — a second creation for the same item is rejected with `ERR_DUPLICATE_STOCK_LEVEL`. The row also carries `reserved_qty`, computed from open shipment and backorder allocations and starting at 0, and `available_qty`, which is always the on-hand quantity minus the reserved quantity. The stock row for an item can be read from the item.

### 3.2. Patient Intake, Eligibility, and the HSA Account

An `IntakeCoordinator` enrolls a patient by supplying `full_name`, `date_of_birth`, the `payer_plan_id` of the coverage plan, and `hsa_initial_credit_cents`, the opening credit on the patient's health savings account, which must be at least 0 (else `ERR_INVALID_REQUEST`, HTTP 400). Enrollment creates the patient in `PENDING_VERIFICATION` status and, in the same act, creates exactly one **HSA account** for the patient: the account's `initial_credit_cents` equals `hsa_initial_credit_cents`, and its opening `balance_cents` equals that same amount. There is never more than one account per patient, and the account can be read from the patient.

Eligibility verification is a deliberate act by an `IntakeCoordinator`, passing an `eligible` boolean and an optional `reason`. When `eligible` is true, the patient moves from `PENDING_VERIFICATION` to `ACTIVE` — but only if the patient's plan currently accepts new patients (its `is_active` is true); a verification attempted against an inactive plan fails its precondition and is rejected as an invalid state transition with `ERR_INVALID_STATE`. When `eligible` is false, the patient moves to `INELIGIBLE`, which is terminal. Either decision increments the patient's `version` by one. Verification attempted on a patient no longer in `PENDING_VERIFICATION` is rejected with `ERR_INVALID_STATE` (HTTP 409); the optional `reason` is accepted but not persisted.

A patient who is not `ACTIVE` blocks four downstream operations: creating a resupply program, creating an order, confirming a resupply cycle, and requesting a fitting sample each reject with `ERR_PATIENT_NOT_ACTIVE` (HTTP 409) unless the patient is `ACTIVE`. Patients can be listed with optional `payer_plan_id` and `status` filters plus pagination.

### 3.3. Clinical Documentation: Prescriptions, Fit Profiles, and Prior Authorizations

Three intake artifacts gate everything a patient can receive, and an `IntakeCoordinator` (or, for authorizations, a `PriorAuthSpecialist`) maintains them.

A **prescription** authorizes a specific product code for a patient. Creation takes `patient_id`, the `hcpcs_code` being authorized, the `prescriber_npi`, an optional `diagnosis_codes` array of ICD-10 codes, a `monthly_quantity` of authorized units per month, and a validity window given by `effective_date` (inclusive) and `expiration_date` (exclusive) — a half-open window in which the expiration date itself is no longer covered. A window whose `effective_date` is on or after its `expiration_date` is rejected with `ERR_INVALID_REQUEST` (HTTP 400), `monthly_quantity` must be an integer of at least 1, and the prescription's `hcpcs_code` is a free code that is not resolved against the formulary. A new prescription is born `ACTIVE`. Two creation-time rules apply. First, when the patient's plan is `MEDICARE_DMEPOS`, at least one diagnosis code is required; creating the prescription without any is rejected with `ERR_DIAGNOSIS_REQUIRED` (HTTP 422). Second, no two `ACTIVE` prescriptions for the same patient and the same `hcpcs_code` may have overlapping half-open windows; an overlap is rejected with `ERR_PRESCRIPTION_WINDOW_OVERLAP` (HTTP 409). Adjacency is allowed: a new prescription whose `effective_date` equals the existing prescription's `expiration_date` does not overlap. An `ACTIVE` prescription may be cancelled by an `IntakeCoordinator`, moving it to the terminal `CANCELLED` state and incrementing its `version`; it may also flip to the terminal `EXPIRED` state lazily per §2.7. A patient's prescriptions can be listed with optional `status` filtering.

A **fit profile** records a measured size for a patient in a category. Creation takes `patient_id`, a `category` of `OSTOMY`, `INCONTINENCE`, or `WOUND`, the measured `size_code` (e.g. a 45MM stoma or a 4X4 dressing), the `measured_on` date, and — per §2.8 — the mandatory `expected_patient_version`. A new profile is born `CURRENT`. If a `CURRENT` profile already exists for the same patient and category, creating the new profile supersedes it: the prior profile flips to the terminal `SUPERSEDED` state, the new profile is `CURRENT`, and the patient's `version` increments by one as the optimistic-concurrency parent. A patient's fit profiles can be listed with optional `category` and `status` filters.

A **prior authorization** records a payer's permission for a product code. A `PriorAuthSpecialist` creates one with `patient_id`, `hcpcs_code`, the `approved_units` the payer approves per cycle, and a **closed** validity window from `valid_from` through `valid_to`, inclusive on both ends. A `valid_from` after `valid_to` is rejected with `ERR_INVALID_REQUEST` (HTTP 400), `approved_units` must be an integer of at least 1, and the authorization's `hcpcs_code` is likewise a free, unresolved code. A new authorization is born `SUBMITTED`. Creation rejects any overlap with another authorization for the same patient and code that is still in `SUBMITTED`, `APPEALED`, or `APPROVED` status, with `ERR_AUTH_WINDOW_OVERLAP` (HTTP 409); because the window is closed, adjacency counts as overlap — a new `valid_from` equal to an existing `valid_to` collides. The payer's decision, recorded by a `PriorAuthSpecialist` with an `outcome` of `APPROVED` or `DENIED` plus an optional `note` (accepted but not persisted), moves an authorization from `SUBMITTED` or `APPEALED` to `APPROVED` or `DENIED` respectively; a decision attempted from any other state is rejected with `ERR_INVALID_STATE`. A `DENIED` authorization may be appealed, moving it to `APPEALED` and incrementing its `appeal_count` by one (the count starts at 0). `APPROVED` and `EXPIRED` are terminal; the lazy `EXPIRED` flip is described in §2.7. A patient's authorizations can be listed with optional `hcpcs_code` and `status` filters.

### 3.4. Resupply Programs and Cycle Confirmation

A **resupply program** enrolls a patient in automatic recurring supply for one category. An `IntakeCoordinator` creates it with `patient_id`, `category`, a `frequency_days` interval between eligible shipments, and a `start_date` on which the first cycle becomes eligible. The patient must be `ACTIVE` (else `ERR_PATIENT_NOT_ACTIVE`), and at most one `ACTIVE` program may exist per patient and category — a duplicate is rejected with `ERR_DUPLICATE_PROGRAM` (HTTP 409). A program is born `ACTIVE`, with `next_eligible_date` initialized to `start_date`, `last_delivered_date` null until the first delivery, and `suspend_reason` null while the program is `ACTIVE`.

Cycle confirmation is the heartbeat of the business: a `Patient` or an `IntakeCoordinator` confirms the due cycle, and the system builds and submits a program order in one act. The checks run in a documented order. If the program is not `ACTIVE`, the confirm is rejected with `ERR_PROGRAM_SUSPENDED`. If the patient is not `ACTIVE`, it is rejected with `ERR_PATIENT_NOT_ACTIVE`. If the current logical date is before the program's `next_eligible_date`, it is rejected with `ERR_RESUPPLY_WINDOW_NOT_OPEN` (HTTP 422); the eligible date itself is open — equality qualifies. Otherwise the system runs the **item selector**: the candidate pool is every formulary item whose `status` is `ACTIVE`, whose `category` equals the program's category, whose `covered_plan_ids` include the patient's plan, whose `size_codes` include the patient's `CURRENT` fit profile size for the category, and which either does not require prior authorization or is covered by an `APPROVED` authorization for the patient and code whose closed window contains today. An empty pool rejects the confirm with `ERR_NO_ELIGIBLE_ITEM` (HTTP 422). The selected item is the pool member with the lowest `unit_allowance_cents`, ties broken by earliest item `created_at`.

The confirmed order is created with `origin` set to `PROGRAM_CYCLE`, linked to the program, and moved straight through draft into the submitted fulfillment state. It carries exactly one line: the selected item, the patient's `CURRENT` fit profile `size_code` for the category, and a quantity equal to the **resupply quantity allowance**. That allowance is the smallest of three caps: the prescription cap (the `monthly_quantity` of the `ACTIVE`, currently valid prescription covering the item's `hcpcs_code` — the earliest-created one when several cover — multiplied by the plan's `cycle_months`), the formulary cap (the item's `max_units_per_cycle`), and the prior authorization cap (the `approved_units` of the covering `APPROVED` authorization when the item requires one, or unlimited when it does not; if the item requires one but no covering `APPROVED` authorization exists, the authorization cap imposes no limit). If the allowance computes to less than one unit, the confirm fails with `ERR_QUANTITY_EXCEEDS_ALLOWANCE` (HTTP 422). Because confirmation creates a priced line, the prescription-coverage rule also applies here: with no `ACTIVE`, currently valid prescription covering the item's code, the operation is rejected with `ERR_NO_VALID_PRESCRIPTION`. Confirmation increments the program's `version` by one.

A program can leave `ACTIVE` in one direction only. An `IntakeCoordinator` may suspend it manually, supplying a `reason` that is stored in `suspend_reason`; suspension attempted on a program that is not `ACTIVE` is rejected with `ERR_INVALID_STATE`. The system may also suspend a program automatically, per §3.7. Resuming is the mirror: an `IntakeCoordinator` resumes a `SUSPENDED` program, clearing `suspend_reason` back to null; resuming a program that is not `SUSPENDED` is rejected with `ERR_PROGRAM_NOT_SUSPENDED`. Suspend and resume each increment the program's `version` by one. The orders generated by a program can be listed from the program.

### 3.5. Building and Submitting Orders

Outside the program cycle, a `Patient` or an `IntakeCoordinator` may open a **manual reorder** by supplying `patient_id` and optionally a `resupply_program_id`. The patient must be `ACTIVE` (else `ERR_PATIENT_NOT_ACTIVE`). The new order is born with `fulfillment_status` `DRAFT` and `billing_status` `UNBILLED`, its `origin` recorded as `MANUAL_REORDER` (when created directly) and its `resupply_program_id` null for a pure manual reorder. Both computed totals, `total_allowed_cents` and `total_patient_resp_cents`, start at 0.

Every order carries **two parallel state dimensions** that evolve independently on one row. The fulfillment dimension walks `DRAFT` → `SUBMITTED` → `IN_FULFILLMENT` → `FULFILLED`, with `CANCELLED` reachable as terminal from the earlier states. The billing dimension walks `UNBILLED` → `CLAIM_DRAFT` → `CLAIM_SUBMITTED`, then to `PAID_SETTLED` or `CLAIM_DENIED`, and from denial through `APPEAL_PENDING` to `PAID_SETTLED` or `PATIENT_BILLED`. The billing transitions are driven by the claim workflow in §3.8.

An order line is added to a `DRAFT` order by a `Patient` or `IntakeCoordinator` supplying `formulary_item_id`, `size_code`, `quantity` (at least 1), and the mandatory `expected_order_version` of §2.8. Line addition enforces, in the priority bands of §2.10: the order must be in `DRAFT` fulfillment, otherwise `ERR_ORDER_NOT_DRAFT` (HTTP 409); an `ACTIVE` prescription covering the line's code must exist, otherwise `ERR_NO_VALID_PRESCRIPTION` (at line-add time the rule is existence of a covering prescription; at submission the validity window must contain the current date); the item must be covered by the patient's plan, meaning the patient's `payer_plan_id` appears in the item's `covered_plan_ids`, otherwise `ERR_ITEM_NOT_ON_FORMULARY` (HTTP 422); the line's `size_code` must be one of the item's offered `size_codes` **and** must equal the patient's `CURRENT` fit profile size for the item's category — a missing profile fails this check too — otherwise `ERR_SIZE_MISMATCH` (HTTP 422); and the requested `quantity` must not exceed the resupply quantity allowance computed exactly as in §3.4 for the patient's plan, prescription, item, and any required authorization — except that at line-add time the prescription cap comes from the earliest-created `ACTIVE` covering prescription whose window contains today when one exists, and otherwise from the earliest-created `ACTIVE` covering prescription regardless of its window — otherwise `ERR_QUANTITY_EXCEEDS_ALLOWANCE`. A created line copies the item's `hcpcs_code` and `unit_allowance_cents` at creation time and computes its `line_allowed_cents` as the unit allowance multiplied by `quantity`, rounded half up to 2 decimal places under the pinned per-unit-first order of §2.5. Adding a line recomputes the order's totals and increments the order's `version` by one. The recomputation mirrors the claim pricing of §3.8: `total_allowed_cents` is the sum of the lines' `line_allowed_cents`, and `total_patient_resp_cents` is the sum of the per-line rounded patient responsibility — each line's `line_allowed_cents` multiplied by the plan's `coinsurance_pct`, rounded half up per line, for insured plans, or each item's `retail_price_cents` multiplied by the line quantity, rounded half up per line, for `CASH_HSA` plans. An order's lines can be listed from the order, and an individual line can be read directly.

Submission is the gate where a draft becomes real. A `Patient` or `IntakeCoordinator` submits a `DRAFT` order; a non-draft order is rejected with `ERR_ORDER_NOT_DRAFT`. Submission requires at least one line (an empty order is rejected with `ERR_INVALID_REQUEST`, HTTP 400) and requires every line's `hcpcs_code` to be covered by an `ACTIVE` prescription whose half-open window contains the current logical date — the effective date on or before today and the expiration date strictly after today — otherwise `ERR_NO_VALID_PRESCRIPTION` (HTTP 422). For a patient on a `CASH_HSA` plan there is an additional fiscal gate: the estimated patient responsibility — the sum over lines of each item's `retail_price_cents` multiplied by the line quantity, rounded half up to 2 decimal places per line — must not exceed the patient's HSA `balance_cents`, otherwise the submission is rejected with `ERR_INSUFFICIENT_HSA` (HTTP 422). A successful submission moves fulfillment from `DRAFT` to `SUBMITTED`, recomputes `total_allowed_cents` and `total_patient_resp_cents` (the estimate is finalized only at claim adjudication), and increments the order's `version` by one.

Cancellation depends on how far the order has travelled. From `DRAFT` or `SUBMITTED` — states in which no shipments exist yet — a `Patient` or `IntakeCoordinator` cancels outright, moving fulfillment to `CANCELLED` and incrementing `version`. An order in `IN_FULFILLMENT` can be cancelled only while every one of its shipments is still in `CREATED` or `BACKORDERED` status — none `READY` or beyond. That cancellation cascades: each such shipment moves to `CANCELLED`, each cancelled shipment releases its reservations (the stock row's `reserved_qty` is decremented by the units reserved plus the units already allocated for that line, and any `PENDING` or `PARTIALLY_ALLOCATED` backorder reservations move to `CANCELLED`), and the order's `version` increments. Cancellation from any later fulfillment state, or from the terminal `CANCELLED` state itself, is rejected with `ERR_INVALID_STATE`. A patient's orders can be listed with an optional `fulfillment_status` filter.

### 3.6. Warehouse Fulfillment: Shipments, Stock, and Backorders

Fulfillment begins when a `FulfillmentAgent` creates a shipment for a `SUBMITTED` order, passing the `order_id`; creating a shipment for an order not in `SUBMITTED` is rejected with `ERR_INVALID_STATE` (HTTP 409). This single act advances the order from `SUBMITTED` to `IN_FULFILLMENT` and performs stock reservation line by line: for each line, the stock row's `reserved_qty` increases by the smaller of the line quantity and the units currently available (a line whose item has no stock row has zero units available and is fully backordered). Any shortage opens a **backorder reservation** for that line — linked by its `order_line_id` — in `PENDING` status with `quantity_pending` equal to the shortfall and `quantity_allocated` at 0. When every line is fully reserved the shipment is born `CREATED`; otherwise it is born `BACKORDERED`. The order's `version` increments. An order's shipments can be listed from the order, and a line's backorder reservations can be listed from the line.

Release is the compliance gate. A `FulfillmentAgent` releases a shipment that is in `CREATED` status, moving it to `READY` and incrementing its `version`. Attempting to release a `BACKORDERED` shipment is rejected with `ERR_SHIPMENT_BACKORDERED` (HTTP 409), and release attempted from any other non-`CREATED` state is rejected with `ERR_INVALID_STATE` (HTTP 409). For every order line whose item has `requires_pa` true, release evaluates the stored authorization rows for the patient and the line's code — without applying the lazy expiry flip of §2.7 — and three outcomes are possible: an `APPROVED` authorization whose closed window contains the release date passes; an `APPROVED` authorization exists but the current date is strictly after its `valid_to` rejects the release with `ERR_PRIOR_AUTH_EXPIRED` (HTTP 422); and no covering `APPROVED` authorization at all — including the case where an `APPROVED` authorization exists but its window has not yet opened, the release date falling before its `valid_from` — rejects the release with `ERR_PRIOR_AUTH_REQUIRED` (HTTP 422).

A `READY` shipment is dispatched by a `FulfillmentAgent`, moving it to `SHIPPED`, stamping `shipped_date` with the current logical date, and settling the physical stock: for each shipped line the stock row's `on_hand_qty` decreases by the reserved units and `reserved_qty` decreases by the same amount, so `available_qty` is unchanged by the dispatch itself. Because an in-transit cycle counts toward the provisional adherence score, dispatch also recomputes the program's adherence scores (§3.7). The shipment's `version` increments.

Delivery closes the loop. A `FulfillmentAgent` marks a `SHIPPED` shipment `DELIVERED`, stamping `delivered_date` with the current logical date and incrementing the shipment's `version`. When the shipment's order belongs to a resupply program, delivery advances the program: `last_delivered_date` is set to the delivery date, `next_eligible_date` becomes the delivery date plus the program's `frequency_days`, the adherence scores are recomputed, and the program's `version` increments by one. Delivery also triggers the order's fulfillment bubble-up: an order in `IN_FULFILLMENT` moves to `FULFILLED` (incrementing its `version`) the moment at least one of its shipments is `DELIVERED` and no shipment of the order remains in `CREATED`, `BACKORDERED`, `READY`, or `SHIPPED`.

A shipment in `SHIPPED` or `DELIVERED` status may be returned by a `FulfillmentAgent`, moving it to the terminal `RETURNED` state and incrementing its `version`. The returned cycle counts as **non-adherent**, and the program's adherence scores are recomputed; for a return from `SHIPPED` the order's fulfillment bubble-up runs as well, since a returned shipment counts as closed, whereas a return after delivery does not roll back `last_delivered_date` or `next_eligible_date`. Return attempted from any other shipment state is rejected with `ERR_INVALID_STATE`.

Restock is how backorders heal. A `PlatformAdmin` adds `qty_added` units to a stock row (`qty_added` must be an integer of at least 1, else `ERR_INVALID_REQUEST`, HTTP 400), which first increases `on_hand_qty` by that amount, then runs the allocation waterfall over the backorder reservations of that item's order lines whose status is `PENDING` or `PARTIALLY_ALLOCATED`. Reservations are processed oldest first by reservation `created_at`, ties broken by the parent order's `created_at`. For each reservation, while units remain, the allocation is the smaller of the reservation's `quantity_pending` and the units remaining: `quantity_pending` decreases and `quantity_allocated` increases by the allocation, and the stock row's `reserved_qty` increases by the allocation. A reservation whose pending count reaches zero moves to `ALLOCATED`; one that received some but not enough units moves to `PARTIALLY_ALLOCATED`. When every reservation of a `BACKORDERED` shipment has been fully allocated, the shipment flips back to `CREATED`, incrementing its `version`, and becomes releasable. When a parent order is cancelled, each `PENDING` or `PARTIALLY_ALLOCATED` reservation moves to the terminal `CANCELLED` state, and the stock row's `reserved_qty` is decremented per line by every unit still held for it — the units reserved at shipment creation plus the units already allocated to its reservations — releasing everything held for the line (§3.5).

### 3.7. Adherence Measurement and Program Suspension

Every resupply program carries two adherence scores, recomputed on shipment dispatch, delivery, and return, and whenever the program is read. Recomputation by itself never increments the program's `version` or refreshes its `updated_at`. The scoring considers the program's orders — those linked by `resupply_program_id` with `origin` `PROGRAM_CYCLE` whose fulfillment is not `CANCELLED` — and their shipments. The denominator, `cycles_due`, is the number of whole `frequency_days` periods elapsed from `start_date` through the current logical date, plus one; it is evaluated only once the current date has reached `start_date`; before that date both scores are null, and a program is likewise born with both scores null. A cycle counts as delivered when one of those orders has a shipment in `DELIVERED` status, and as in-transit when it has a shipment in `SHIPPED` status; a returned cycle counts toward neither.

The two scores answer different questions. The **final** score, `adherence_score_final`, is delivered cycles divided by cycles due, rounded half up to 2 decimal places, and it gates suspension. The **provisional** score, `adherence_score_provisional`, is delivered plus in-transit cycles divided by cycles due, also rounded half up to 2 decimal places — a forward-looking monitoring view that treats in-transit cycles as adherent, so the same data yields a provisional score at least as high as the final one whenever any cycle is in transit.

Suspension is the teeth behind the metric. Whenever a shipment return recomputes the scores and the final score falls strictly below 0.50, the program moves from `ACTIVE` to `SUSPENDED` with `suspend_reason` set to `LOW_ADHERENCE` and its `version` incremented; a final score of exactly 0.50 does not suspend. The second automatic suspension path is fiscal, described in §3.8: when a final claim denial debits the patient's HSA account below the reorder floor of 500 cents, every `ACTIVE` program of that patient is suspended with `suspend_reason` `HSA_FLOOR_BREACH`. Manual suspension by an `IntakeCoordinator` stores the free-text reason supplied (§3.4). In all three paths the program's `version` increments, and a suspended program refuses cycle confirmation with `ERR_PROGRAM_SUSPENDED` until it is resumed.

### 3.8. Claims, Adjudication, and the HSA Ledger

Once an order is fulfilled, a `BillingSpecialist` creates a claim for it by passing the `order_id`. Claim creation requires the order's fulfillment to be `FULFILLED`, its billing to be `UNBILLED`, and no existing claim for the order; any violation rejects creation with `ERR_CLAIM_NOT_SUBMITTABLE` (HTTP 409). A claim is born `DRAFT`, and its creation moves the order's billing dimension from `UNBILLED` to `CLAIM_DRAFT`, computes the claim's pricing, and increments the order's `version` by one.

Pricing follows the patient's plan variant. The claim's `total_allowed_cents` is the sum over the order's lines of the line basis: for an insured plan (`MEDICARE_DMEPOS` or `COMMERCIAL`) each line contributes its `line_allowed_cents`, while for a `CASH_HSA` plan each line contributes the item's `retail_price_cents` multiplied by the line `quantity`, rounded half up to 2 decimal places. The `patient_resp_cents` differs by variant. Under the insured variant, each line's coinsurance is computed as the line's allowed amount multiplied by the plan's `coinsurance_pct`, rounded half up to 2 decimal places **per line**, and those rounded per-line amounts are then summed — the rounding happens before the summation, never after. Under the `CASH_HSA` variant the patient pays one hundred percent: `patient_resp_cents` equals `total_allowed_cents` on the retail basis, and `insurer_paid_cents` is 0. When a claim is ultimately denied after appeal, the `DENIED_FINAL` variant re-prices regardless of plan: `patient_resp_cents` becomes the full `total_allowed_cents` and the insurer pays 0. The claim's `insurer_paid_cents` is set to `total_allowed_cents` minus `patient_resp_cents` only when the claim is paid; otherwise it is 0.

A `BillingSpecialist` submits a `DRAFT` claim, moving it to `SUBMITTED`, advancing the order's billing from `CLAIM_DRAFT` to `CLAIM_SUBMITTED`, and incrementing both the claim's and the order's `version` by one. Adjudication takes an `outcome` of `PAID` or `DENIED`. A `PAID` outcome on a claim in `SUBMITTED` or `APPEALED` status moves the claim to the terminal `PAID` state: `insurer_paid_cents` is set to `total_allowed_cents` minus `patient_resp_cents`, `adjudicated_at` is stamped, the order's billing moves to `PAID_SETTLED`, and both versions increment. A `DENIED` outcome on a `SUBMITTED` claim moves it to `DENIED`, stamps `adjudicated_at`, and moves the order's billing to `CLAIM_DENIED`, again incrementing both versions. A `DENIED` claim may be appealed by a `BillingSpecialist`, moving it to `APPEALED` and the order's billing to `APPEAL_PENDING`, with both versions incrementing; appealing a claim that is not `DENIED` — including a `PAID` one — is rejected with `ERR_INVALID_STATE`. Adjudication attempted from a state where that outcome is unavailable (for example `DENIED` on an already-`DENIED` claim) is likewise rejected with `ERR_INVALID_STATE`.

The heaviest cascade in the system fires when a `DENIED` outcome lands on an `APPEALED` claim. The claim moves to the terminal `DENIED_FINAL` state and is re-priced under the denial variant above, so the full allowed amount shifts to the patient. The order's billing moves to `PATIENT_BILLED`. The system then posts a `DEBIT` entry to the patient's HSA ledger for the full `patient_resp_cents`, carrying `reason` `CLAIM_DENIED_FINAL` and `related_order_id` set to the order's id; if the account's balance cannot cover the debit, the adjudication is rejected with `ERR_INSUFFICIENT_HSA` (HTTP 422). After the debit posts, if the account's `balance_cents` has fallen below the reorder floor of 500 cents, every `ACTIVE` resupply program of the patient is suspended with `suspend_reason` `HSA_FLOOR_BREACH` per §3.7. The cascade finishes by stamping `adjudicated_at` and incrementing the claim's and the order's `version` by one. An order's claims can be listed from the order.

The **HSA ledger** is an append-only record on the patient's account; every entry is tied to its owning account through `hsa_account_id`, taken from the path under which the entry is posted. A `BillingSpecialist` posts a debit by supplying `amount_cents` (strictly greater than 0, else `ERR_INVALID_REQUEST`), a free-text `reason`, and an optional `related_order_id` reference string, which is not a foreign key. A debit is accepted only when the amount does not exceed the account's `balance_cents` — equality is allowed and leaves the balance at exactly zero — otherwise the posting is rejected with `ERR_INSUFFICIENT_HSA`. A credit posting takes `amount_cents`, a `reason`, and optionally `reverses_entry_id`; without a reversal reference the entry is a `CREDIT`, and with one it is a `REVERSAL`. A reversal is accepted only when `reverses_entry_id` references a `POSTED` `DEBIT` entry of the same account, otherwise the posting is rejected with `ERR_HSA_ENTRY_NOT_REVERSIBLE` (HTTP 409). The reversal's `amount_cents` is independent of the reversed entry's amount; any positive amount is accepted. Every entry is born `POSTED` — the ledger has no other status — and its `entry_type` is one of `DEBIT`, `CREDIT`, or `REVERSAL`. The account's `balance_cents` is always derived: the `initial_credit_cents`, plus the sum of `amount_cents` over all `POSTED` entries of type `CREDIT` or `REVERSAL`, minus the sum over all `POSTED` `DEBIT` entries; each posting recomputes it. An account's ledger entries can be listed from the account, and the account itself can be read with its recomputed balance.

### 3.9. Fitting Samples

Before committing a patient to a product, an `IntakeCoordinator` may request a free **fitting sample** by supplying `patient_id`, `category`, `size_code`, and a free-text `item_name`. Samples are never billed: the sample's `unit_price_cents` is always 0. The patient must be `ACTIVE` (else `ERR_PATIENT_NOT_ACTIVE`), and a rolling-window limit applies per patient and category: within the closed lookback of the 90 days ending today — a sample created exactly 90 days ago still counts — at most two samples may exist for the patient and category across all statuses. The second sample within the window succeeds; a request that would create a third is rejected with `ERR_SAMPLE_LIMIT_EXCEEDED` (HTTP 422). A patient's samples can be listed with an optional `category` filter.

A new sample is born `REQUESTED`. A `FulfillmentAgent` ships it, moving it to `SHIPPED`. An `IntakeCoordinator` then records the fitting outcome, passing an `outcome` of `CONVERTED` or `NOT_CONVERTED`, which moves the sample to the terminal `OUTCOME_RECORDED` state and stores the outcome. Each transition increments the sample's `version` by one; a transition attempted from the wrong state is rejected with `ERR_INVALID_STATE`.

## 4. Endpoint Definitions

Operations that create a new resource — a plan, item, patient, prescription, fit profile, program, order, order line, shipment, stock level, prior authorization, claim, ledger entry, or fitting sample — return a `201 Created` status code. Operations that modify an existing resource in place — verification, suspension, resumption, submission, cancellation, release, dispatch, delivery, return, restock, decisions, appeals, adjudication, outcome recording, and the clock set — return a `200 OK` status code.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/payer-plans` | Create a payer plan | PlatformAdmin |
| GET | `/api/payer-plans/{id}` | Read one plan | PlatformAdmin, IntakeCoordinator, PriorAuthSpecialist, FulfillmentAgent, BillingSpecialist, Patient |
| GET | `/api/payer-plans/{id}/patients` | Patients on a plan | PlatformAdmin, IntakeCoordinator |
| POST | `/api/formulary-items` | Create a formulary item; computes the unit allowance | PlatformAdmin |
| GET | `/api/formulary-items/{id}` | Read one item | PlatformAdmin, IntakeCoordinator, PriorAuthSpecialist, FulfillmentAgent, BillingSpecialist, Patient |
| GET | `/api/formulary-items` | List items with optional category filter | PlatformAdmin, IntakeCoordinator, PriorAuthSpecialist, FulfillmentAgent, BillingSpecialist, Patient |
| GET | `/api/formulary-items/{id}/order-lines` | Lines referencing an item | PlatformAdmin, FulfillmentAgent, BillingSpecialist |
| GET | `/api/formulary-items/{id}/stock-levels` | Stock row for an item (array of 0–1) | PlatformAdmin, FulfillmentAgent |
| POST | `/api/patients` | Enroll a patient; auto-creates the HSA account with the opening credit | IntakeCoordinator |
| GET | `/api/patients/{id}` | Read one patient | PlatformAdmin, IntakeCoordinator, PriorAuthSpecialist, FulfillmentAgent, BillingSpecialist, Patient |
| GET | `/api/patients` | List patients with filters and pagination | PlatformAdmin, IntakeCoordinator, BillingSpecialist |
| POST | `/api/patients/{id}/verify-eligibility` | Verify coverage: `PENDING_VERIFICATION` → `ACTIVE` or `INELIGIBLE` | IntakeCoordinator |
| GET | `/api/patients/{id}/prescriptions` | Patient's prescriptions | PlatformAdmin, IntakeCoordinator, Patient |
| GET | `/api/patients/{id}/fit-profiles` | Patient's fit profiles | PlatformAdmin, IntakeCoordinator, Patient |
| GET | `/api/patients/{id}/resupply-programs` | Patient's resupply programs | PlatformAdmin, IntakeCoordinator, Patient |
| GET | `/api/patients/{id}/orders` | Patient's orders | PlatformAdmin, IntakeCoordinator, BillingSpecialist, Patient |
| GET | `/api/patients/{id}/prior-authorizations` | Patient's prior authorizations | PlatformAdmin, IntakeCoordinator, PriorAuthSpecialist, Patient |
| GET | `/api/patients/{id}/hsa-accounts` | Patient's HSA account (array of 0–1) | PlatformAdmin, IntakeCoordinator, BillingSpecialist, Patient |
| GET | `/api/patients/{id}/fitting-samples` | Patient's fitting samples | PlatformAdmin, IntakeCoordinator, Patient |
| POST | `/api/prescriptions` | Create an `ACTIVE` prescription; half-open window overlap rejected | IntakeCoordinator |
| GET | `/api/prescriptions/{id}` | Read one prescription (lazy expiry applies) | PlatformAdmin, IntakeCoordinator, Patient |
| POST | `/api/prescriptions/{id}/cancel` | Cancel an `ACTIVE` prescription | IntakeCoordinator |
| POST | `/api/fit-profiles` | Create a fit profile; supersedes the prior `CURRENT` profile; OCC on the patient | IntakeCoordinator |
| GET | `/api/fit-profiles/{id}` | Read one fit profile | PlatformAdmin, IntakeCoordinator, Patient |
| POST | `/api/resupply-programs` | Enroll a patient in a recurring resupply program | IntakeCoordinator |
| GET | `/api/resupply-programs/{id}` | Read one program (recomputes adherence scores) | PlatformAdmin, IntakeCoordinator, Patient |
| POST | `/api/resupply-programs/{id}/confirm-cycle` | Confirm the due cycle; creates a submitted program order with one allowance-quantity line | Patient, IntakeCoordinator |
| POST | `/api/resupply-programs/{id}/suspend` | Manually suspend an `ACTIVE` program | IntakeCoordinator |
| POST | `/api/resupply-programs/{id}/resume` | Resume a `SUSPENDED` program | IntakeCoordinator |
| GET | `/api/resupply-programs/{id}/orders` | Program's orders | PlatformAdmin, IntakeCoordinator, Patient |
| POST | `/api/orders` | Create a `DRAFT` manual reorder | Patient, IntakeCoordinator |
| GET | `/api/orders/{id}` | Read one order (both status dimensions and totals) | PlatformAdmin, IntakeCoordinator, PriorAuthSpecialist, FulfillmentAgent, BillingSpecialist, Patient |
| POST | `/api/orders/{id}/lines` | Add a line to a `DRAFT` order; OCC on the order | Patient, IntakeCoordinator |
| GET | `/api/orders/{id}/lines` | Order's lines | PlatformAdmin, IntakeCoordinator, FulfillmentAgent, BillingSpecialist, Patient |
| GET | `/api/order-lines/{id}` | Read one line | PlatformAdmin, IntakeCoordinator, FulfillmentAgent, BillingSpecialist, Patient |
| POST | `/api/orders/{id}/submit` | Submit a `DRAFT` order after prescription, formulary, size, and HSA validation | Patient, IntakeCoordinator |
| POST | `/api/orders/{id}/cancel` | Cancel an order; cascades to open shipments and releases reserved stock | Patient, IntakeCoordinator |
| POST | `/api/shipments` | Create a shipment for a `SUBMITTED` order; reserves stock, opens backorders on shortage | FulfillmentAgent |
| GET | `/api/shipments/{id}` | Read one shipment | PlatformAdmin, IntakeCoordinator, FulfillmentAgent, Patient |
| GET | `/api/orders/{id}/shipments` | Order's shipments | PlatformAdmin, IntakeCoordinator, FulfillmentAgent, Patient |
| POST | `/api/shipments/{id}/release` | Release a `CREATED` shipment; enforces the prior-auth gate | FulfillmentAgent |
| POST | `/api/shipments/{id}/ship` | Mark a `READY` shipment `SHIPPED`; stamps the ship date | FulfillmentAgent |
| POST | `/api/shipments/{id}/deliver` | Mark a `SHIPPED` shipment `DELIVERED`; advances the program window | FulfillmentAgent |
| POST | `/api/shipments/{id}/return` | Mark a `SHIPPED` or `DELIVERED` shipment `RETURNED`; adherence penalty applies | FulfillmentAgent |
| POST | `/api/stock-levels` | Create the stock row for an item (one per item) | PlatformAdmin |
| GET | `/api/stock-levels/{id}` | Read one stock row | PlatformAdmin, FulfillmentAgent |
| POST | `/api/stock-levels/{id}/restock` | Add on-hand units and run FIFO backorder allocation | PlatformAdmin |
| GET | `/api/order-lines/{id}/backorder-reservations` | Line's backorder reservations | PlatformAdmin, FulfillmentAgent |
| POST | `/api/prior-authorizations` | Create a `SUBMITTED` authorization; closed-window overlap rejected | PriorAuthSpecialist |
| GET | `/api/prior-authorizations/{id}` | Read one authorization (lazy expiry applies) | PlatformAdmin, IntakeCoordinator, PriorAuthSpecialist, Patient |
| POST | `/api/prior-authorizations/{id}/decision` | Record the payer decision: `APPROVED` or `DENIED` | PriorAuthSpecialist |
| POST | `/api/prior-authorizations/{id}/appeal` | Appeal a `DENIED` authorization | PriorAuthSpecialist |
| POST | `/api/claims` | Create a `DRAFT` claim for a fulfilled, unbilled order | BillingSpecialist |
| GET | `/api/claims/{id}` | Read one claim | PlatformAdmin, BillingSpecialist |
| GET | `/api/orders/{id}/claims` | Order's claims | PlatformAdmin, BillingSpecialist |
| POST | `/api/claims/{id}/submit` | Submit a `DRAFT` claim | BillingSpecialist |
| POST | `/api/claims/{id}/adjudicate` | Adjudicate `PAID` or `DENIED`; denial after appeal triggers the HSA debit cascade | BillingSpecialist |
| POST | `/api/claims/{id}/appeal` | Appeal a `DENIED` claim | BillingSpecialist |
| GET | `/api/hsa-accounts/{id}` | Read one HSA account with recomputed balance | PlatformAdmin, IntakeCoordinator, BillingSpecialist, Patient |
| POST | `/api/hsa-accounts/{id}/debits` | Post a `DEBIT` entry; amount must not exceed the balance | BillingSpecialist |
| POST | `/api/hsa-accounts/{id}/credits` | Post a `CREDIT` or `REVERSAL` entry | BillingSpecialist |
| GET | `/api/hsa-accounts/{id}/entries` | Account's ledger entries | PlatformAdmin, BillingSpecialist, Patient |
| POST | `/api/fitting-samples` | Request a free fitting sample; rolling 90-day limit of 2 per patient and category | IntakeCoordinator |
| GET | `/api/fitting-samples/{id}` | Read one sample | PlatformAdmin, IntakeCoordinator, Patient |
| POST | `/api/fitting-samples/{id}/ship` | Ship a `REQUESTED` sample | FulfillmentAgent |
| POST | `/api/fitting-samples/{id}/record-outcome` | Record the fitting outcome for a `SHIPPED` sample | IntakeCoordinator |
| POST | `/api/_clock/set_current_utc` | Set the logical clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ORDER_NOT_DRAFT` | 409 Conflict |
| `ERR_PROGRAM_SUSPENDED` | 409 Conflict |
| `ERR_PROGRAM_NOT_SUSPENDED` | 409 Conflict |
| `ERR_PATIENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_DUPLICATE_PROGRAM` | 409 Conflict |
| `ERR_DUPLICATE_STOCK_LEVEL` | 409 Conflict |
| `ERR_PRESCRIPTION_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_AUTH_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_SHIPMENT_BACKORDERED` | 409 Conflict |
| `ERR_CLAIM_NOT_SUBMITTABLE` | 409 Conflict |
| `ERR_HSA_ENTRY_NOT_REVERSIBLE` | 409 Conflict |
| `ERR_NO_VALID_PRESCRIPTION` | 422 Unprocessable Entity |
| `ERR_DIAGNOSIS_REQUIRED` | 422 Unprocessable Entity |
| `ERR_SAMPLE_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_PRIOR_AUTH_REQUIRED` | 422 Unprocessable Entity |
| `ERR_PRIOR_AUTH_EXPIRED` | 422 Unprocessable Entity |
| `ERR_ITEM_NOT_ON_FORMULARY` | 422 Unprocessable Entity |
| `ERR_SIZE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_QUANTITY_EXCEEDS_ALLOWANCE` | 422 Unprocessable Entity |
| `ERR_RESUPPLY_WINDOW_NOT_OPEN` | 422 Unprocessable Entity |
| `ERR_NO_ELIGIBLE_ITEM` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_HSA` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_STALE_ORDER_VERSION` | 412 Precondition Failed |
