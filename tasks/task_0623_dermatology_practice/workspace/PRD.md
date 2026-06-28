# Dermatology Practice API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the **Dermatology Practice API**, a back-office system that runs the front-to-back operations of a combined medical and cosmetic dermatology clinic. A single patient may pass through several parallel storylines on the same day: a medical office visit that produces a skin biopsy sent off to a pathology lab, a Mohs procedure that must be booked into a credentialed surgical suite, a prepaid cosmetic membership redeemed against a wallet of prepaid units, and a specialty biologic that cannot be charged until the payer's prior-authorization and step-therapy gates have been cleared. The system must keep all of these threads coherent — biopsy results must drive recall reminders and unblock the clinical close of a visit, membership redemptions must debit a wallet without ever going negative, and every charge must be split correctly between what the insurer allows and what the patient owes in cash.

The financial heart of the system is a **dual-path ledger**. The same clinical event can be billed two entirely different ways: on the insurance path a charge runs a deductible waterfall followed by a coinsurance split, while on the cash path the same charge simply applies a flat prompt-pay discount and the insurer owes nothing. Layered on top of that is a compliance regime — biologic charges are gated behind an approved prior authorization whose step-therapy requirements have been met — and a scheduling regime that enforces room turnover buffers, provider double-booking rules, and Mohs-suite credentialing. Recall reminders are scheduled against a logical clock that the practice controls explicitly, so that follow-up horizons (three, six, or twelve months out) can be tested deterministically.

Because clinical, billing, scheduling, and pathology responsibilities live with different staff, the API is organized around five cooperating operator roles and a strict access-control model. The remainder of this document defines the global contract (Section 2), the business logic and workflows where the rules are scattered through the narrative (Section 3), the endpoint surface (Section 4), and the complete error catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope formats, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory HTTP headers: `X-User-ID`, which identifies the acting operator, and `X-User-Role`, which declares the operational capacity under which the request is made. If either header is missing or malformed, the request is rejected with `ERR_MISSING_AUTH_CONTEXT`. If the headers are present but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes exactly five roles, spelled precisely as follows: `PracticeAdmin`, `FrontDesk`, `Provider`, `PathLab`, and `BillingSpecialist`. `PracticeAdmin` is the operational superset responsible for practice setup (creating providers and rooms), driving the logical clock, and running the recall sweep. `FrontDesk` owns scheduling and registration — registering patients, scheduling encounters, checking patients in, cancelling, booking procedures, and dismissing recalls. `Provider` owns clinical acts — starting and clinically closing encounters, collecting and resulting-out biopsies, completing bookings, attaching photos, and performing cosmetic treatments. `PathLab` is a narrow role that posts biopsy pathology results and nothing else. `BillingSpecialist` owns the revenue cycle — charges, prior authorizations and step therapy, cosmetic memberships, and the billing finalize/void transitions.

Four of the five roles are **opaque operators**. When `X-User-Role` is `PracticeAdmin`, `FrontDesk`, `PathLab`, or `BillingSpecialist`, the `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may record it for audit but never compares it to any entity's `id`. The `Provider` role is the single exception: when `X-User-Role` is `Provider`, the `X-User-ID` is the `id` of the acting `Provider` entity. Ownership checks on any resource that references a `Provider` (for example an encounter's or booking's provider linkage) compare that resource's provider foreign key to `X-User-ID`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Every primary resource — `Provider`, `Room`, `Patient`, `Encounter`, `Biopsy`, `ProcedureBooking`, `PriorAuthorization`, `StepTherapyTrial`, `CosmeticMembership`, `CosmeticTreatment`, `Charge`, and `RecallReminder` — carries a standard set of system-managed fields:

- `id`: a unique, server-minted UUID with no type prefix.
- `created_at`: an ISO 8601 UTC timestamp with three fractional digits indicating when the resource was first created.
- `updated_at`: an ISO 8601 UTC timestamp indicating when the resource was last modified; it is refreshed on every mutation.
- `version`: a system-managed integer that begins at its initial value and increments by exactly one on every mutation of the resource. It is the basis for optimistic concurrency control (Section 2.7).

One entity is deliberately append-only and therefore an exception. A `SkinExamPhoto` is immutable documentation: it carries only `id` and `created_at`. It has **no** `updated_at` field and **no** `version` field, because it is never modified after creation.

The logical clock that the system reads for every "now" comparison, every recall horizon, and every recall sweep is a server-managed value, not the real wall clock. On server startup the clock reads exactly `2026-01-01T00:00:00Z`, and before any clock-setting call it stays at that default and never falls back to real time. An administrative test-driving capability sets the clock to a supplied absolute UTC instant, provided in the request body as `to_iso8601`, after which all due-date and recall computations read the new value.

### 2.5. Hierarchical Consistency and Derived-Field Reconciliation

Several fields on parent entities are **derived** — they are recomputed by the server as child entities change, never set directly by a client. When a derived field changes, that change is a mutation of the parent: it refreshes the parent's `updated_at` and increments the parent's `version`.

An `Encounter` carries a derived `open_biopsy_count` equal to the number of its child `Biopsy` rows whose `status` is either `COLLECTED` or `AT_LAB`. Whenever a biopsy moves into or out of those two states, the parent encounter's `open_biopsy_count` is recomputed and the encounter's `updated_at` is refreshed. A `Patient` carries a derived `last_skin_check_at`, set to the clock's current time when a `SKIN_CHECK` encounter is clinically closed; when this changes, the patient's `updated_at` is refreshed. A `PriorAuthorization` carries a derived `satisfied_step_count` and `submission_round`, and a `CosmeticMembership` carries a derived `unit_balance_cents`; all are maintained by the server.

When a parent entity transitions in a way that invalidates committed children, the system cascades the resolution automatically without requiring a separate client request on each child. The two principal cascades — billing void cascading to charges, and biologic biopsy sign-out cascading to recall reminders — are detailed in Section 3, but the governing principle is stated here: each cascaded mutation independently updates the affected resource's `updated_at` and increments its `version`.

### 2.6. Monetary Precision and Rounding

All monetary amounts are stored and transmitted as integer cents. Field names ending in `_cents` are always whole-cent integers.

Wherever a calculation multiplies an amount by a rate (a coinsurance fraction, a cash discount, a tier discount, a tier bonus, a step-down factor, or an administration uplift), the result is rounded to whole cents using the **round-half-up** method. Rounding is always applied **after** the multiply, never before — except where a calculation explicitly pins a different order, in which case the pinned order governs (see Section 3.7 for the deductible waterfall, where each charge's coinsurance is rounded per charge before the per-charge values are summed, and Section 3.6 for the membership redemption, where the discounted price is rounded before it is compared against the wallet balance).

### 2.7. Optimistic Concurrency Control

Two write operations require the client to present the version of a parent resource that it last observed, so that a writer cannot act on a wallet or a room schedule that has silently moved underneath it. These are the only two endpoints that take a version field; no other endpoint accepts one.

Redeeming a cosmetic treatment requires the request body to carry `expected_membership_version`, holding the client's last observed `version` of the target `CosmeticMembership`. Before any balance arithmetic runs, the server compares `expected_membership_version` against the membership's current `version`. If a prior redemption has advanced the membership's version since the client last read it, the create is rejected with `ERR_STALE_MEMBERSHIP_VERSION` (HTTP 412), because the client's view of the wallet balance is stale and must not be drawn against.

Creating a procedure booking requires the request body to carry `expected_room_version`, holding the client's last observed `version` of the target `Room`. Before any overlap geometry is evaluated, the server compares `expected_room_version` against the room's current `version`. If a prior booking has advanced the room's version since the client last read it, the create is rejected with `ERR_STALE_ROOM_VERSION` (HTTP 412), because the client's view of the room's occupied intervals is stale. In both cases the stale-version check runs before the business geometry or balance checks of the operation.

### 2.8. Nested Resource Retrieval and Validation Ordering

The topology is flat: every entity is addressable as a top-level collection (`/patients`, `/encounters`, `/biopsies`, and so on), and relationships are navigated through filtered list endpoints rather than nested URL paths. The one genuinely nested resource is the step-therapy trial, which lives under its owning prior authorization. When a request carries a path identifier — and equally when a write body carries a foreign-key reference such as `patient_id`, `encounter_id`, `room_id`, `provider_id`, `membership_id`, or `prior_auth_id` — the referenced rows must exist; identifiers in a path are validated left-to-right, and the first one that does not resolve produces the corresponding `404` not-found error before any later identifier is considered. The not-found error is resource-specific: an unresolved patient yields `ERR_PATIENT_NOT_FOUND`, a provider `ERR_PROVIDER_NOT_FOUND`, a room `ERR_ROOM_NOT_FOUND`, an encounter `ERR_ENCOUNTER_NOT_FOUND`, a biopsy `ERR_BIOPSY_NOT_FOUND`, a procedure booking `ERR_BOOKING_NOT_FOUND`, a prior authorization `ERR_PA_NOT_FOUND`, a cosmetic membership `ERR_MEMBERSHIP_NOT_FOUND`, a cosmetic treatment `ERR_TREATMENT_NOT_FOUND`, a charge `ERR_CHARGE_NOT_FOUND`, and a recall reminder `ERR_RECALL_NOT_FOUND`. A request whose body is malformed, is missing a required field, or carries an out-of-range enum value that is not otherwise covered by a more specific rule is rejected with `ERR_INVALID_REQUEST`.

The system evaluates validations in a fixed priority order, so that an earlier failure masks a later one and the rejection a client sees is deterministic. The order is: first, authentication context (`ERR_MISSING_AUTH_CONTEXT`, HTTP 401); then role authorization (`ERR_FORBIDDEN_ROLE`, HTTP 403); then existence of path-referenced resources (HTTP 404); then existence of body foreign-key references (HTTP 404); then the optimistic-concurrency version check on the two endpoints that declare one (HTTP 412); then the target resource's state being correct for the requested transition (the various bad-state errors, HTTP 409); and only then the business-specific safety, temporal, referential, and fiscal checks described in Section 3. Within the booking endpoint specifically, this means the room-version check precedes the Mohs-suite check, which precedes the credential check, which precedes the interval-validity check, which precedes the room-overlap and provider-double-booking checks, as detailed in Section 3.4.

### 2.9. The Insurance-versus-Cash Ledger Principle

Every billable event resolves down one of two mutually exclusive pay paths, and the same charge is computed by a completely different algorithm depending on which path applies. On the **INSURANCE** path a charge first draws down the patient's remaining deductible, then splits the remainder between patient coinsurance and insurer responsibility. On the **CASH** path the charge ignores the insurer's allowed amount and the deductible entirely, instead applying a flat prompt-pay discount, with the insurer owing nothing. The pay path of a charge is not chosen freely at posting time: it is copied from the parent encounter. An encounter's own pay path is `INSURANCE` or `CASH`, defaulting for `MEDICAL` and `SKIN_CHECK` visits from the patient's `has_active_insurance` flag when omitted, and always forced to `CASH` for `COSMETIC` visits. The detailed split formulas live in Sections 3.6 and 3.7.

## 3. Business Logic & Workflows

### 3.1. Practice Setup: Providers and Rooms

Before any clinical work can occur, a `PracticeAdmin` establishes the practice's resources. A provider is created with a `full_name` and an `npi` (a free-form national-provider-identifier string, unique among providers). Two boolean attributes govern how a provider may be used: `can_perform_mohs` declares whether the provider is credentialed for Mohs surgery and defaults to `false`, and `active` declares whether the provider may be assigned to encounters and bookings and defaults to `true`. An encounter may only reference a provider that is active at the moment the encounter is created.

Rooms are likewise created by a `PracticeAdmin`. A room has a `name` label and a `room_kind`, which is one of `STANDARD` or `MOHS_SUITE`; only a `MOHS_SUITE` room may host a Mohs booking. Each room also has a `turnover_buffer_minutes` value, defaulting to 0, which is a mandatory idle buffer enforced after each booking on that room: the next booking's start must be no earlier than the prior booking's end plus this buffer. The role of that buffer in overlap geometry is described in Section 3.4.

### 3.2. Patient Registration and the Skin-Check Recall Cycle

A patient is registered by `FrontDesk` (or by a `PracticeAdmin`) with a `full_name` and a `date_of_birth` given as an ISO date in `YYYY-MM-DD` form. Three optional billing attributes describe how the patient is covered. The `has_active_insurance` flag, defaulting to `false`, marks whether the patient carries billable insurance and drives the default billing path on medical and skin-check encounters. The `insurance_coinsurance_rate`, defaulting to `0.2`, is the fraction of the insurer-allowed remainder the patient owes (a value between 0 and 1, meaningful only when insurance is active). The `insurance_deductible_remaining_cents`, defaulting to 0, is the patient's remaining unmet deductible in cents, which insurance-path charges consume in posting order.

A patient also carries a computed `last_skin_check_at`, which starts null and is set to the clock's current time whenever one of the patient's `SKIN_CHECK` encounters is clinically closed. That same clinical-close event spawns a routine recall: a `RecallReminder` is created with `reason` of `ROUTINE_SKIN_CHECK`, a null `biopsy_id`, a `due_at` set to twelve months after the clock's current time, and a `status` of `PENDING`. The routine recall horizon is fixed at twelve months. Routine reminders may also be created directly by `FrontDesk` or a `PracticeAdmin` by supplying a `patient_id`, a `reason`, and a `due_at`.

### 3.3. The Encounter: Parallel Clinical and Billing Dimensions

An encounter — scheduled by `FrontDesk` or a `PracticeAdmin` — is the visit record, and it tracks **two independent status dimensions at once**. It is created with a `patient_id`, a `provider_id` (which must reference an active provider), a `visit_type` of `MEDICAL`, `SKIN_CHECK`, or `COSMETIC`, and a `scheduled_at` clock time. The optional `pay_path` defaults as described in Section 2.9. On creation the encounter's `clinical_status` is `SCHEDULED`, its `billing_status` is `BILLING_OPEN`, and its `open_biopsy_count` is 0.

The **clinical dimension** advances `SCHEDULED → CHECKED_IN → IN_PROGRESS → CLINICALLY_CLOSED`, with `CANCELLED` as an alternative terminal state. `FrontDesk` checks a patient in, moving `SCHEDULED → CHECKED_IN`; this is permitted only while the encounter is `SCHEDULED` (otherwise `ERR_ENCOUNTER_BAD_CLINICAL_STATE`), and early check-in is allowed — the clock need not have reached `scheduled_at`. A `Provider` starts the visit, moving `CHECKED_IN → IN_PROGRESS`, permitted only from `CHECKED_IN` (otherwise `ERR_ENCOUNTER_BAD_CLINICAL_STATE`). A `Provider` clinically closes the visit, moving `IN_PROGRESS → CLINICALLY_CLOSED`, permitted only from `IN_PROGRESS` (otherwise `ERR_ENCOUNTER_BAD_CLINICAL_STATE`) and only when `open_biopsy_count` is exactly 0, that is, no child biopsy remains in `COLLECTED` or `AT_LAB` (otherwise `ERR_OPEN_BIOPSY_BLOCKS_CLOSE`). On clinical close, if the visit type is `SKIN_CHECK`, the patient's `last_skin_check_at` is set and a routine recall is spawned per Section 3.2. `FrontDesk` may cancel an encounter, moving it to `CANCELLED`, but only from `SCHEDULED` or from `CHECKED_IN` (otherwise `ERR_ENCOUNTER_BAD_CLINICAL_STATE`). Every one of these clinical transitions increments the encounter's `version` by one.

The **billing dimension** is entirely independent and advances `BILLING_OPEN → BILLING_FINALIZED`, with `BILLING_VOID` as an alternative terminal state. A `BillingSpecialist` finalizes billing, moving `BILLING_OPEN → BILLING_FINALIZED`; this requires the encounter's `billing_status` to currently be `BILLING_OPEN` (otherwise `ERR_ENCOUNTER_BAD_BILLING_STATE`) and, as a cross-dimension guard, requires the `clinical_status` to already be `CLINICALLY_CLOSED` (otherwise `ERR_ENCOUNTER_NOT_CLINICALLY_CLOSED`). Finalizing billing increments the encounter's `version` and locks the encounter against any further charge posting: a subsequent attempt to post a charge against it is rejected with `ERR_ENCOUNTER_BILLING_LOCKED`. A `BillingSpecialist` may instead void billing, moving `BILLING_OPEN → BILLING_VOID`; this requires `billing_status` to be `BILLING_OPEN` (otherwise `ERR_ENCOUNTER_BAD_BILLING_STATE`) and requires the `clinical_status` to be `CANCELLED` — void-billing exists only for cancelled encounters (otherwise `ERR_ENCOUNTER_NOT_CANCELLED`). Voiding billing increments the encounter's `version` and triggers the charge-void cascade described in Section 3.8.

### 3.4. Mohs and Procedure Scheduling on Rooms

A procedure booking reserves a time interval on a room for a procedure tied to an in-progress medical encounter. `FrontDesk` or a `PracticeAdmin` books a procedure by supplying a `room_id`, a `provider_id`, an `encounter_id`, a `procedure_kind` of `EXCISION` or `MOHS`, a `start_at`, an `end_at`, and the `expected_room_version` value required for the concurrency check of Section 2.7. A new booking begins in `status` `BOOKED`, and a successful create increments the room's `version` by one to record that the room's interval set has changed.

The booking endpoint enforces a chain of business rules in the priority order fixed in Section 2.8, after the room-version check. First, if the procedure kind is `MOHS`, the room's `room_kind` must be `MOHS_SUITE`; otherwise the booking is rejected with `ERR_MOHS_REQUIRES_MOHS_SUITE`. Second, if the procedure kind is `MOHS`, the booked provider's `can_perform_mohs` must be `true`; otherwise the booking is rejected with `ERR_PROVIDER_NOT_MOHS_CREDENTIALED`. Third, `end_at` must be strictly after `start_at`; an interval whose end is not after its start is rejected with `ERR_INVALID_INTERVAL`.

Two distinct overlap rules then apply, and their geometry is deliberately different. **For the room**, each prior `BOOKED` or `COMPLETED` booking on the same room reserves the half-open window that begins at that booking's start and extends to its end plus the room's `turnover_buffer_minutes`. The new booking conflicts if its interval overlaps any such window; a conflict is rejected with `ERR_ROOM_INTERVAL_CONFLICT`. Because the window is half-open and the buffer is additive, a new booking whose start exactly equals a prior booking's end plus the buffer does **not** overlap and is allowed. **For the provider**, each prior `BOOKED` or `COMPLETED` booking for the same provider is treated as a closed interval from its start to its end with no buffer at all. The new booking conflicts if its interval overlaps any such closed interval; a conflict is rejected with `ERR_PROVIDER_DOUBLE_BOOKED`. Because the provider interval is closed, a new booking whose start exactly equals a prior booking's end **does** overlap and is rejected — a provider cannot be in two procedures whose endpoints merely touch. The room rule treats touching endpoints as free; the provider rule treats touching endpoints as a conflict.

A `Provider` completes a booking, moving `BOOKED → COMPLETED`, but only while the booking is `BOOKED` (otherwise `ERR_BOOKING_BAD_STATE`) and only while the linked encounter is `IN_PROGRESS` (otherwise `ERR_ENCOUNTER_NOT_IN_PROGRESS`); completion increments the booking's `version`. `FrontDesk` may cancel a booking, moving `BOOKED → CANCELLED`, permitted only from `BOOKED` (otherwise `ERR_BOOKING_BAD_STATE`); cancellation increments the booking's `version` and frees the room interval so a later booking on the same room may reuse the time window.

### 3.5. Biopsies, Pathology, and the Recall Cascade

A biopsy is collected by a `Provider` during a visit. Collecting one requires only an `encounter_id` and a `body_site`; the encounter must be `IN_PROGRESS`, and the biopsy's `patient_id` is copied from that encounter at creation. A new biopsy starts in `status` `COLLECTED`, and creating it recomputes the parent encounter's `open_biopsy_count`. The biopsy lifecycle is `COLLECTED → AT_LAB → RESULTED → SIGNED_OUT`, with `CANCELLED` as an alternative terminal state, and it branches on the pathology result.

A `Provider` sends a specimen to the lab, moving `COLLECTED → AT_LAB`, permitted only from `COLLECTED` (otherwise `ERR_BIOPSY_BAD_STATE`); this increments the biopsy's `version`, and the parent encounter's `open_biopsy_count` is unchanged because both `COLLECTED` and `AT_LAB` count as open. `PathLab` posts the result, moving `AT_LAB → RESULTED`, permitted only from `AT_LAB` (otherwise `ERR_BIOPSY_BAD_STATE`); the supplied `result` must be one of `BENIGN`, `MALIGNANT`, or `INDETERMINATE` (otherwise `ERR_INVALID_BIOPSY_RESULT`). Posting the result sets the biopsy's `result`, increments its `version`, and — because a `RESULTED` biopsy no longer counts as open — recomputes the parent encounter's `open_biopsy_count` and refreshes the encounter's `updated_at`. This bubble-up is precisely what can unblock a clinical close that was previously held by `ERR_OPEN_BIOPSY_BLOCKS_CLOSE`.

A `Provider` signs out a resulted biopsy, moving `RESULTED → SIGNED_OUT`, permitted only from `RESULTED` (otherwise `ERR_BIOPSY_BAD_STATE`). Sign-out increments the biopsy's `version` and sets the biopsy's `recall_months` from its result: a `BENIGN` result yields a twelve-month horizon, an `INDETERMINATE` result a six-month horizon, and a `MALIGNANT` result a three-month horizon. Sign-out then spawns a follow-up recall: a `RecallReminder` is created with `reason` of `BIOPSY_FOLLOWUP`, its `biopsy_id` set to this biopsy, a `due_at` equal to the clock's current time plus `recall_months` months, and a `status` of `PENDING`; creating that reminder refreshes the patient's `updated_at`. Furthermore, if the result was `MALIGNANT`, the newly spawned follow-up takes precedence over routine surveillance: every existing `ROUTINE_SKIN_CHECK` reminder for that patient that is still `PENDING` is transitioned `PENDING → DISMISSED` as superseded.

A `Provider` may cancel a biopsy, moving `COLLECTED → CANCELLED`, permitted only from `COLLECTED` (otherwise `ERR_BIOPSY_BAD_STATE`); cancellation increments the biopsy's `version` and recomputes the parent encounter's `open_biopsy_count` because a cancelled biopsy no longer counts as open. Independently of biopsies, a `Provider` (or a `PracticeAdmin`) may attach mole-map documentation to an encounter as an append-only `SkinExamPhoto`, supplying the `encounter_id`, a `body_site` label, the normalized mole-map coordinates `mole_map_x` and `mole_map_y` (each between 0 and 1), and an opaque `image_ref` storage reference.

### 3.6. Cosmetic Memberships and Wallet Redemption

The cosmetic side of the practice runs on prepaid membership wallets. A `BillingSpecialist` or `FrontDesk` creates a `CosmeticMembership` for a patient by supplying a `patient_id`, a `tier` of `SILVER` or `GOLD`, and a `purchased_unit_cents` amount the patient prepays. A new membership starts in `status` `PENDING` with a `unit_balance_cents` of 0. The membership lifecycle is `PENDING → ACTIVE → {EXHAUSTED, CANCELLED}`.

A `BillingSpecialist` activates a membership, moving `PENDING → ACTIVE`, permitted only from `PENDING` (otherwise `ERR_MEMBERSHIP_BAD_STATE`). Activation grants the wallet: the `unit_balance_cents` is set to the prepaid amount plus a tier bonus, where the bonus is the prepaid amount multiplied by the tier's bonus rate — 0 percent for `SILVER` and 10 percent for `GOLD` — rounded half-up to whole cents. Thus a `SILVER` activation grants exactly the prepaid amount, while a `GOLD` activation grants the prepaid amount plus ten percent of it. A `BillingSpecialist` may cancel a membership, moving it to `CANCELLED` from either `PENDING` or `ACTIVE` (otherwise `ERR_MEMBERSHIP_BAD_STATE`); cancellation increments the membership's `version`, and when cancelling from `ACTIVE` it forfeits the wallet by setting `unit_balance_cents` to 0.

A cosmetic treatment redeems the wallet and is performed by a `Provider` or `BillingSpecialist`. The redemption request supplies an `encounter_id`, a `membership_id`, a `service_name`, a `list_price_cents`, and the `expected_membership_version` for the concurrency check of Section 2.7. The treatment is only permitted when its encounter's `visit_type` is `COSMETIC` and its membership's `status` is `ACTIVE`; if either condition fails, the redemption is rejected with `ERR_MEMBERSHIP_NOT_ACTIVE`.

The redemption splits the price between the wallet and the patient's pocket through a waterfall, wallet first. The list price is first discounted by the tier discount — 5 percent for `SILVER` and 15 percent for `GOLD` — giving a discounted price equal to the list price multiplied by one minus the tier discount, rounded half-up to whole cents. The amount drawn from the wallet, recorded as `redeemed_cents`, is the smaller of that rounded discounted price and the membership's currently available `unit_balance_cents`. The residual, recorded as `out_of_pocket_cents`, is the discounted price minus the redeemed amount, which the patient pays in cash. Note that the discount multiply is rounded **before** the wallet comparison, so the wallet draws against the already-rounded discounted price. Redeeming debits the wallet by `redeemed_cents` (the balance can reach 0 but never goes negative) and increments the membership's `version`. If the debit leaves `unit_balance_cents` at exactly 0, the membership auto-transitions `ACTIVE → EXHAUSTED` as a bubble-up, which itself increments the membership's `version`.

For an encounter's overall cosmetic position, a computed read returns the encounter's total cosmetic out-of-pocket. Because each treatment's out-of-pocket depends on the wallet balance left by all earlier treatments, the evaluation order is pinned: the encounter's cosmetic treatments are applied in `created_at` ascending order (ties broken by `created_at` ascending, never by id), each one fully resolving its `redeemed_cents` and `out_of_pocket_cents` against the running wallet balance before the next is considered. The total due is then the sum of `out_of_pocket_cents` over those treatments, expressed in whole cents; the read returns the `encounter_id`, the `total_due_cents`, and the `treatment_count`.

### 3.7. Charges: The Dual-Path Split and the Deductible Waterfall

A `BillingSpecialist` posts a charge against an encounter by supplying a `patient_id`, an `encounter_id`, a `source_kind`, a `charge_kind`, a `billed_amount_cents`, and — depending on the kind and path — an `insurer_allowed_cents`, a `prior_auth_id`, and a `cosmetic_treatment_id`. The `source_kind` is the polymorphic origin selector and is one of `ENCOUNTER`, `COSMETIC_TREATMENT`, or `PROCEDURE_BOOKING`; the `charge_kind` is one of `OFFICE_VISIT`, `PROCEDURE`, `BIOLOGIC`, or `COSMETIC`. A new charge starts in `status` `POSTED`. No charge may be posted against an encounter whose `billing_status` is not `BILLING_OPEN`; such an attempt is rejected with `ERR_ENCOUNTER_BILLING_LOCKED`. When `source_kind` is `COSMETIC_TREATMENT`, the `cosmetic_treatment_id` identifies the treatment whose wallet draw this charge represents; voiding such a charge restores that treatment's redeemed amount to its membership wallet (Section 3.8).

The charge's `pay_path` is not supplied by the client; it is copied from the parent encounter at posting time and is one of `INSURANCE` or `CASH`. On the `INSURANCE` path a non-null `insurer_allowed_cents` is required; on the `CASH` path it must be omitted or null. A violation of either rule is rejected with `ERR_ALLOWED_AMOUNT_REQUIRED`.

**Biologic charges** are gated and self-priced. A charge whose `charge_kind` is `BIOLOGIC` requires a non-null `prior_auth_id` referencing a `PriorAuthorization` whose `status` is `APPROVED`; otherwise it is rejected with `ERR_PA_NOT_APPROVED`. For a biologic charge the server **overwrites** the client-supplied `billed_amount_cents` with a computed amount (and, on the `INSURANCE` path, copies that computed amount into `insurer_allowed_cents`); the client's billed input is ignored. The computation starts from the prior authorization's `list_price_cents` as the base. A multi-round resubmission step-down is applied: the round factor is one minus five percent for each resubmission round beyond the first — that is, one minus 0.05 multiplied by the prior authorization's `submission_round` minus one — but never below a floor of 0.80. The allowed-after-rounds amount is the base multiplied by that round factor, rounded half-up to whole cents. An in-office administration uplift is then added: the uplift is four percent of the allowed-after-rounds amount, rounded half-up to whole cents, but capped at 25000 cents (that is, $250.00). The final billed amount is the allowed-after-rounds amount plus the uplift. Each named step rounds half-up to whole cents in the stated order. For all non-biologic charge kinds, `billed_amount_cents` is taken directly from the client input.

**The split itself** resolves down the charge's pay path, in a fixed evaluation order: first the deductible draw, then the insurer-versus-patient split, then integer rounding. On the `INSURANCE` path the allowed amount is `insurer_allowed_cents`. The deductible applied, recorded as `deductible_applied_cents`, is the smaller of the allowed amount and the patient's `insurance_deductible_remaining_cents`. The remainder is the allowed amount minus the deductible applied. The patient's coinsurance portion is that remainder multiplied by the patient's `insurance_coinsurance_rate`, rounded half-up to whole cents. The `patient_responsibility_cents` is the deductible applied plus the coinsurance portion, and the `insurer_responsibility_cents` is the allowed amount minus the patient responsibility. As a write-back side effect, the patient's `insurance_deductible_remaining_cents` is reduced by the deductible applied. On the `CASH` path the insurer-allowed amount and the deductible are ignored entirely: the `patient_responsibility_cents` is the `billed_amount_cents` multiplied by one minus a ten-percent prompt-pay discount, rounded half-up to whole cents; the `insurer_responsibility_cents` is 0; and the `deductible_applied_cents` is 0.

When several insurance-path charges for one patient are considered together, the order in which the deductible is consumed is load-bearing and is pinned to chronological `created_at` ascending order (ties broken by `created_at` ascending, never by id). Each insurance charge consumes the patient's remaining deductible before its own coinsurance is computed, and the rounding order is pinned: each charge's coinsurance is rounded per charge — applied after that charge's deductible draw — and only then are the already-rounded per-charge responsibilities summed. This round-per-charge-then-sum order is deliberate and can differ by a cent from a sum-then-round implementation, so it must be preserved. Concretely, processing the patient's insurance charges in `created_at` ascending order, each charge draws the smaller of its allowed amount and the deductible remaining before it, reduces the running deductible remaining by that draw, computes its coinsurance as the post-draw remainder times the coinsurance rate rounded half-up, and sets that charge's patient portion to the draw plus the rounded coinsurance; the patient total is the sum of those already-rounded per-charge portions.

A `BillingSpecialist` may transition a charge `POSTED → PAID`, permitted only from `POSTED` (otherwise `ERR_CHARGE_BAD_STATE`); paying increments the charge's `version`. The void transition and its compensations are covered next.

### 3.8. Void Compensations and the Billing-Void Cascade

A `BillingSpecialist` voids a charge directly, moving `POSTED → VOIDED`, permitted only from `POSTED` (otherwise `ERR_CHARGE_BAD_STATE`). Voiding increments the charge's `version` and runs two conservation compensations. First, if the charge's `pay_path` is `INSURANCE`, the patient's `insurance_deductible_remaining_cents` is increased by the charge's `deductible_applied_cents`, restoring whatever deductible the charge had consumed. Second, if the charge's `source_kind` is `COSMETIC_TREATMENT`, the linked `CosmeticTreatment`'s `redeemed_cents` (found via the charge's `cosmetic_treatment_id`) is added back to that treatment's `CosmeticMembership` wallet `unit_balance_cents`; the membership's status is not auto-reverted from `EXHAUSTED` — only the wallet balance is restored.

The same compensations are driven in bulk when a `BillingSpecialist` voids an encounter's billing (Section 3.3). Void-billing cascades over every child charge of that encounter currently in `POSTED` status, transitioning each to `VOIDED` and reversing any deductible it consumed: for each such insurance charge the patient's `insurance_deductible_remaining_cents` is increased by that charge's `deductible_applied_cents`. Each cascaded charge mutation increments that charge's `version`, consistent with the reconciliation principle of Section 2.5.

### 3.9. Prior Authorization and Step Therapy

Specialty and biologic drugs must clear a payer prior authorization before a biologic charge can be posted, and the prior-authorization lifecycle is cyclic to model step-therapy resubmission. A `BillingSpecialist` creates a `PriorAuthorization` with a `patient_id`, a `drug_name`, a `required_step_count` (the number of step-therapy trials the payer requires before approval, which must be at least 0), and a `list_price_cents` that will become the basis for the eventual biologic charge. A new prior authorization starts in `status` `DRAFT` with `satisfied_step_count` of 0 and `submission_round` of 0. Its lifecycle is `DRAFT → SUBMITTED → {APPROVED, DENIED}`, with a `DENIED → SUBMITTED` resubmission loop.

To satisfy step therapy, a `BillingSpecialist` records prior drug trials as child `StepTherapyTrial` rows under the prior authorization, each supplying a `drug_name` and an `outcome` of `FAILED`, `EFFECTIVE`, or `NOT_TRIED`. Only a `FAILED` outcome counts toward the requirement: the prior authorization's `satisfied_step_count` is the count of its child trials whose `outcome` is `FAILED`, and recording a trial recomputes that count and increments the prior authorization's `version`. Step therapy is met when `satisfied_step_count` is greater than or equal to `required_step_count`.

A `BillingSpecialist` submits a prior authorization, moving `DRAFT → SUBMITTED`. Submission requires the current status to be `DRAFT` (otherwise `ERR_PA_BAD_STATE`) and requires step therapy to be met, that is, `satisfied_step_count` at least `required_step_count` (otherwise `ERR_STEP_THERAPY_NOT_MET`). Submission increments the prior authorization's `version` and increments its `submission_round` by one. A `BillingSpecialist` then adjudicates a submitted prior authorization by supplying a `decision`. When the decision is to approve, the prior authorization moves `SUBMITTED → APPROVED`; when the decision is to deny, it moves `SUBMITTED → DENIED`; either transition requires the current status to be `SUBMITTED` (otherwise `ERR_PA_BAD_STATE`) and increments the `version`. After a denial the practice adds another step-therapy trial and resubmits: the `DENIED → SUBMITTED` transition requires the current status to be `DENIED` (otherwise `ERR_PA_BAD_STATE`) and again requires step therapy to be met against the freshly augmented trials (otherwise `ERR_STEP_THERAPY_NOT_MET`); this resubmission likewise increments the `version` and increments `submission_round` by one. Each completed resubmission round is what feeds the step-down in the biologic pricing of Section 3.7.

### 3.10. Recall Reminders and the Deferred Sweep

Recall reminders are the system's scheduled-action mechanism, fired against the logical clock rather than in real time. A reminder carries a `patient_id`, an optional `biopsy_id` (set when it was auto-spawned from a signed-out biopsy, null for routine skin-check recalls), a `reason` of `ROUTINE_SKIN_CHECK` or `BIOPSY_FOLLOWUP`, a `due_at` clock time at which it becomes fireable, and a `status`. A new reminder starts `PENDING`, and its lifecycle is `PENDING → {SENT, DISMISSED}`.

A reminder reaches `SENT` only through the recall sweep, an administrative capability runnable by a `PracticeAdmin` or `FrontDesk` that fires all `PENDING` reminders whose `due_at` is at or before the clock's current time, transitioning each `PENDING → SENT` and incrementing each swept reminder's `version`; the sweep returns the swept reminders. A reminder whose `due_at` is still in the future is simply skipped by the sweep, not errored. Separately, `FrontDesk` may dismiss a reminder, moving `PENDING → DISMISSED`, permitted only from `PENDING` (otherwise `ERR_RECALL_BAD_STATE`); dismissal increments the reminder's `version`. Reminders may also be filtered by `status` when listed.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code. State-transition operations and other modifications of an existing resource return a `200 OK` status code; the administrative clock-set, recall-sweep, and computed-read endpoints also return `200 OK`. Every list endpoint accepts the `limit` and `offset` pagination query parameters described in Section 2.3, in addition to any resource-specific filters noted below.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock to an absolute UTC instant | PracticeAdmin |
| POST | `/_recall/sweep` | Fire all due PENDING recall reminders (PENDING → SENT) | PracticeAdmin, FrontDesk |
| POST | `/providers` | Create a provider | PracticeAdmin |
| GET | `/providers/{id}` | Get a provider | PracticeAdmin, FrontDesk, Provider, BillingSpecialist, PathLab |
| GET | `/providers` | List providers | PracticeAdmin, FrontDesk, Provider, BillingSpecialist, PathLab |
| POST | `/rooms` | Create a procedure room | PracticeAdmin |
| GET | `/rooms/{id}` | Get a room | PracticeAdmin, FrontDesk, Provider |
| GET | `/rooms` | List rooms | PracticeAdmin, FrontDesk, Provider |
| POST | `/patients` | Register a patient | FrontDesk, PracticeAdmin |
| GET | `/patients/{id}` | Get a patient | FrontDesk, PracticeAdmin, Provider, BillingSpecialist |
| GET | `/patients` | List patients | FrontDesk, PracticeAdmin, Provider, BillingSpecialist |
| POST | `/encounters` | Schedule an encounter | FrontDesk, PracticeAdmin |
| GET | `/encounters/{id}` | Get an encounter | FrontDesk, PracticeAdmin, Provider, BillingSpecialist |
| GET | `/encounters` | List encounters; filter by `patient_id`, `provider_id` | FrontDesk, PracticeAdmin, Provider, BillingSpecialist |
| POST | `/encounters/{id}/check-in` | Clinical transition SCHEDULED → CHECKED_IN | FrontDesk |
| POST | `/encounters/{id}/start` | Clinical transition CHECKED_IN → IN_PROGRESS | Provider |
| POST | `/encounters/{id}/clinical-close` | Clinical transition IN_PROGRESS → CLINICALLY_CLOSED | Provider |
| POST | `/encounters/{id}/cancel` | Clinical transition SCHEDULED\|CHECKED_IN → CANCELLED | FrontDesk |
| POST | `/encounters/{id}/finalize-billing` | Billing transition BILLING_OPEN → BILLING_FINALIZED | BillingSpecialist |
| POST | `/encounters/{id}/void-billing` | Billing transition BILLING_OPEN → BILLING_VOID; cascade-void charges | BillingSpecialist |
| GET | `/encounters/{id}/cosmetic-summary` | Computed read: total cosmetic out-of-pocket due | FrontDesk, PracticeAdmin, BillingSpecialist |
| POST | `/skin-exam-photos` | Attach a mole-map photo to an encounter | Provider, PracticeAdmin |
| GET | `/skin-exam-photos/{id}` | Get a mole-map photo | Provider, PracticeAdmin, FrontDesk |
| GET | `/skin-exam-photos` | List mole-map photos; filter by `encounter_id` | Provider, PracticeAdmin, FrontDesk |
| POST | `/biopsies` | Collect a biopsy during an encounter | Provider |
| GET | `/biopsies/{id}` | Get a biopsy | Provider, PathLab, PracticeAdmin, BillingSpecialist |
| GET | `/biopsies` | List biopsies; filter by `encounter_id`, `patient_id` | Provider, PathLab, PracticeAdmin, BillingSpecialist |
| POST | `/biopsies/{id}/send-to-lab` | Transition COLLECTED → AT_LAB | Provider |
| POST | `/biopsies/{id}/result` | Post pathology result; AT_LAB → RESULTED | PathLab |
| POST | `/biopsies/{id}/sign-out` | Transition RESULTED → SIGNED_OUT; spawn recall | Provider |
| POST | `/biopsies/{id}/cancel` | Transition COLLECTED → CANCELLED | Provider |
| POST | `/procedure-bookings` | Book a procedure interval on a room (OCC on room version) | FrontDesk, PracticeAdmin |
| GET | `/procedure-bookings/{id}` | Get a booking | FrontDesk, PracticeAdmin, Provider |
| GET | `/procedure-bookings` | List bookings; filter by `room_id`, `provider_id`, `encounter_id` | FrontDesk, PracticeAdmin, Provider |
| POST | `/procedure-bookings/{id}/complete` | Transition BOOKED → COMPLETED | Provider |
| POST | `/procedure-bookings/{id}/cancel` | Transition BOOKED → CANCELLED; free room interval | FrontDesk |
| POST | `/prior-authorizations` | Create a prior-authorization request (DRAFT) | BillingSpecialist |
| GET | `/prior-authorizations/{id}` | Get a prior-authorization | BillingSpecialist, PracticeAdmin, Provider |
| GET | `/prior-authorizations` | List prior-authorizations; filter by `patient_id` | BillingSpecialist, PracticeAdmin, Provider |
| POST | `/prior-authorizations/{id}/step-therapy-trials` | Record a step-therapy trial under a PA | BillingSpecialist |
| GET | `/prior-authorizations/{id}/step-therapy-trials` | List step-therapy trials under a PA | BillingSpecialist, PracticeAdmin, Provider |
| POST | `/prior-authorizations/{id}/submit` | Transition DRAFT\|DENIED → SUBMITTED | BillingSpecialist |
| POST | `/prior-authorizations/{id}/adjudicate` | Transition SUBMITTED → APPROVED or DENIED | BillingSpecialist |
| POST | `/cosmetic-memberships` | Create a prepaid cosmetic membership (PENDING) | BillingSpecialist, FrontDesk |
| GET | `/cosmetic-memberships/{id}` | Get a membership | BillingSpecialist, FrontDesk, PracticeAdmin |
| GET | `/cosmetic-memberships` | List memberships; filter by `patient_id` | BillingSpecialist, FrontDesk, PracticeAdmin |
| POST | `/cosmetic-memberships/{id}/activate` | Transition PENDING → ACTIVE; grant wallet | BillingSpecialist |
| POST | `/cosmetic-memberships/{id}/cancel` | Transition PENDING\|ACTIVE → CANCELLED; forfeit wallet | BillingSpecialist |
| POST | `/cosmetic-treatments` | Redeem a treatment against a membership (OCC on membership version) | Provider, BillingSpecialist |
| GET | `/cosmetic-treatments/{id}` | Get a cosmetic treatment | Provider, BillingSpecialist, PracticeAdmin |
| GET | `/cosmetic-treatments` | List cosmetic treatments; filter by `encounter_id`, `membership_id` | Provider, BillingSpecialist, PracticeAdmin |
| POST | `/charges` | Post a charge against an encounter | BillingSpecialist |
| GET | `/charges/{id}` | Get a charge | BillingSpecialist, PracticeAdmin, Provider |
| GET | `/charges` | List charges; filter by `patient_id`, `encounter_id`, `prior_auth_id`, `cosmetic_treatment_id` | BillingSpecialist, PracticeAdmin, Provider |
| POST | `/charges/{id}/pay` | Transition POSTED → PAID | BillingSpecialist |
| POST | `/charges/{id}/void` | Transition POSTED → VOIDED; restore deductible/wallet | BillingSpecialist |
| POST | `/recall-reminders` | Create a routine recall reminder manually | FrontDesk, PracticeAdmin |
| GET | `/recall-reminders/{id}` | Get a recall reminder | FrontDesk, PracticeAdmin, Provider |
| GET | `/recall-reminders` | List recall reminders; filter by `patient_id`, `biopsy_id`, `status` | FrontDesk, PracticeAdmin, Provider |
| POST | `/recall-reminders/{id}/dismiss` | Transition PENDING → DISMISSED | FrontDesk |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH_CONTEXT` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_PATIENT_NOT_FOUND` | 404 Not Found |
| `ERR_PROVIDER_NOT_FOUND` | 404 Not Found |
| `ERR_ROOM_NOT_FOUND` | 404 Not Found |
| `ERR_ENCOUNTER_NOT_FOUND` | 404 Not Found |
| `ERR_BIOPSY_NOT_FOUND` | 404 Not Found |
| `ERR_BOOKING_NOT_FOUND` | 404 Not Found |
| `ERR_PA_NOT_FOUND` | 404 Not Found |
| `ERR_MEMBERSHIP_NOT_FOUND` | 404 Not Found |
| `ERR_TREATMENT_NOT_FOUND` | 404 Not Found |
| `ERR_CHARGE_NOT_FOUND` | 404 Not Found |
| `ERR_RECALL_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 422 Unprocessable Entity |
| `ERR_INVALID_BIOPSY_RESULT` | 422 Unprocessable Entity |
| `ERR_INVALID_INTERVAL` | 422 Unprocessable Entity |
| `ERR_ALLOWED_AMOUNT_REQUIRED` | 422 Unprocessable Entity |
| `ERR_STALE_MEMBERSHIP_VERSION` | 412 Precondition Failed |
| `ERR_STALE_ROOM_VERSION` | 412 Precondition Failed |
| `ERR_ENCOUNTER_BAD_CLINICAL_STATE` | 409 Conflict |
| `ERR_ENCOUNTER_BAD_BILLING_STATE` | 409 Conflict |
| `ERR_ENCOUNTER_NOT_CLINICALLY_CLOSED` | 409 Conflict |
| `ERR_ENCOUNTER_NOT_CANCELLED` | 409 Conflict |
| `ERR_ENCOUNTER_NOT_IN_PROGRESS` | 409 Conflict |
| `ERR_BIOPSY_BAD_STATE` | 409 Conflict |
| `ERR_BOOKING_BAD_STATE` | 409 Conflict |
| `ERR_PA_BAD_STATE` | 409 Conflict |
| `ERR_MEMBERSHIP_BAD_STATE` | 409 Conflict |
| `ERR_CHARGE_BAD_STATE` | 409 Conflict |
| `ERR_RECALL_BAD_STATE` | 409 Conflict |
| `ERR_MOHS_REQUIRES_MOHS_SUITE` | 422 Unprocessable Entity |
| `ERR_PROVIDER_NOT_MOHS_CREDENTIALED` | 422 Unprocessable Entity |
| `ERR_ROOM_INTERVAL_CONFLICT` | 409 Conflict |
| `ERR_PROVIDER_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_OPEN_BIOPSY_BLOCKS_CLOSE` | 409 Conflict |
| `ERR_PA_NOT_APPROVED` | 422 Unprocessable Entity |
| `ERR_STEP_THERAPY_NOT_MET` | 422 Unprocessable Entity |
| `ERR_ENCOUNTER_BILLING_LOCKED` | 409 Conflict |
| `ERR_MEMBERSHIP_NOT_ACTIVE` | 409 Conflict |
