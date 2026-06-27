# Medical Spa & Aesthetics API — Product Requirements Document

## 1. Introduction

A medical spa offering injectable aesthetic treatments — neurotoxins such as `BOTOX` and `DYSPORT`, dermal fillers such as `JUVEDERM` and `RESTYLANE` — operates at the intersection of clinical regulation and retail commerce. Every injection must trace back to a documented good-faith exam, a signed standing order from a supervising medical director, an unexpired product lot, and a patient who has consented to photographic documentation. At the same time, the business sells multi-session treatment series, takes deposits, honors membership discounts, and funds two branded loyalty programs (`ALLE` and `ASPIRE`). This API is the system of record that reconciles those two worlds.

The platform governs the full lifecycle of aesthetic care: registering providers and tracking which ones are authorized to inject versus authorized to sign orders; intaking injectable lots and tracking their units from reservation through consumption while honoring expiration; running consultations and standing orders that establish legal authority to treat; proposing and activating treatment plans; booking, committing, and resolving individual sessions; and handling the unhappy path where a session produces a complication that may require touch-up rounds or a refund. Throughout, the system enforces a strict separation between the medical director who authorizes treatment and the injector who performs it, and it keeps an exact, conserved ledger of money, loyalty points, and injectable units.

Because aesthetic medicine is time-sensitive — exams expire, orders expire, lots expire — the system runs on an explicit logical clock rather than wall-clock time, so that expiry and validity windows are deterministic and auditable. This document specifies the global contracts every endpoint shares and then the business workflows that the implementation must realize.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that apply across the entire API. All resources are served under the `/aesthetics` mount.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying a value the system cannot interpret, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. When the headers are present and valid but the role is not permitted to perform the requested operation, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

The system recognizes exactly two roles: `ClinicAdmin` and `Provider`.

When `X-User-Role` is `Provider`, `X-User-ID` is the `id` of the acting `Provider` entity; any ownership or duties check on a resource that references a `Provider` — for example the injector who performs a session or the director who signs an order — compares that resource's provider foreign-key field to `X-User-ID`. When `X-User-Role` is `ClinicAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`.

The `ClinicAdmin` role owns front-office and operational concerns: registering and suspending providers, creating membership packages, intaking and quarantining injectable lots, registering patients, opening loyalty accounts, voiding consultations, posting deposits, cancelling plans, cancelling or marking sessions as no-show, and controlling the logical clock. A `ClinicAdmin` may never perform a clinical injection or sign an order. The `Provider` role represents licensed clinical staff and owns all clinical actions: opening consultations and finalizing good-faith exams, signing and revoking standing orders, proposing/activating/completing plans, booking/committing/resolving sessions, recording photos, and managing complications and touch-ups. Both roles may call any read or list (GET) endpoint.

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

List endpoints accept two query parameters. The `limit` parameter caps how many items are returned; it defaults to 10, may not be smaller than 1, and may not exceed 100. The `offset` parameter is the number of items to skip from the start of the result set; it defaults to 0 and may not be negative. A `limit` outside the 1–100 range, a negative `offset`, or a non-integer value for either is rejected with `ERR_INVALID_REQUEST`.

Unless an endpoint states otherwise, list results are sorted by `created_at` in ascending order, with insertion order breaking ties on identical `created_at` values. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and the Logical Clock

Every resource carries a system-generated `id` formatted as a UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits, set when the resource is first persisted.

Most resources additionally carry an `updated_at` timestamp (ISO 8601 UTC, three fractional digits, refreshed on every mutation) and a `version` integer that begins at its initial value of 1 and increments by one on every mutation of that resource. The single exception is the `ConsentPhoto`, which is an immutable event record: of the common audit fields it carries only `id` and `created_at` (in addition to its own descriptive fields `patient_id`, `treatment_session_id`, `kind`, `signed`, and `storage_uri`), and has neither an `updated_at` field nor a `version` field. Whenever a derived field on a resource changes — for instance a plan's `provisional_series_cost_cents` or a lot's `remaining_units` — that change is itself a mutation that refreshes `updated_at` and increments `version` on the owning resource.

All time-sensitive domain logic reads from a server-managed logical clock rather than wall-clock time. The logical clock governs domain expiry/validity checks only; the audit timestamps `created_at` and `updated_at`, the `api_request_timestamp` in the response envelope, and the `Consultation.exam_clock_utc` stamp are the exception — `created_at`, `updated_at`, and `api_request_timestamp` are always real wall-clock UTC instants and do not follow the logical clock, while `exam_clock_utc` is stamped from the logical clock (see §3.2). On startup the clock reads exactly `2026-01-01T00:00:00Z`, and before any clock is explicitly set it holds that default and never falls back to real time. An administrative test-driving capability advances the logical clock to a supplied `to_iso8601` instant; every expiry and validity-window check — lot expiration, standing-order validity, good-faith-exam freshness — is evaluated against the clock's current value.

### 2.5. Monetary, Unit, and Points Precision

All money is expressed in whole cents as integers; the API never returns fractional cents. The session charge calculation is the only place rounding arises, and it uses the round-half-up method applied per product line before the lines are summed — never sum-then-round (see §3.6). Injectable units and loyalty points are always whole integers and are never rounded. Provider complication rates are expressed as whole-number basis points, rounded half up.

### 2.6. Conserved-Quantity Invariants

Three ledgers in this system are conserved quantities, and the implementation must keep their derived totals exactly reconciled at all times.

For every `InjectableLot`, the relationship `remaining_units` equals `total_units` minus `reserved_units` minus `consumed_units` holds after every operation; `total_units` is fixed at intake and never changes thereafter, while `reserved_units` and `consumed_units` move as sessions reserve, commit, cancel, or no-show. For every `LoyaltyAccount`, `points_balance` equals `points_earned` minus `points_redeemed` after every operation, and one point is worth exactly one cent of redemption value. For every `TreatmentPlan`, `deposit_paid_cents` is the sum of `amount_cents` over its `POSTED` deposits, `finalized_series_cost_cents` is the chronological running sum of committed session charges net of any refund compensations, and `sessions_committed` counts the sessions that have reached a committed or post-committed state. A forward action followed by its compensating reversal must leave every one of these totals back at its pre-action value.

### 2.7. Nested Reference Validation Order

Several endpoints address a resource by an `id` in the URL path, and several creation endpoints carry foreign-key references in the body. Path identifiers are validated first and left to right: the addressed resource must exist or the request is rejected with the not-found error specific to that resource type — `ERR_PROVIDER_NOT_FOUND`, `ERR_PATIENT_NOT_FOUND`, `ERR_MEMBERSHIP_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_CONSULTATION_NOT_FOUND`, `ERR_STANDING_ORDER_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, or `ERR_CASE_NOT_FOUND`. Three resource types have no dedicated not-found error in the catalogue, so addressing a non-existent one by path id reuses a neighboring error: a missing loyalty account on `GET /loyalty-accounts/{id}` returns `ERR_PATIENT_NOT_FOUND`, a missing deposit on `GET /deposits/{id}` returns `ERR_PLAN_NOT_FOUND`, and a missing consent photo on `GET /consent-photos/{id}` returns `ERR_SESSION_NOT_FOUND`. Once path identifiers resolve, every foreign key supplied in a creation body must resolve to an existing record — `membership_id`, `patient_id`, `consultation_id`, `treatment_plan_id`, `standing_order_id`, `injectable_lot_id`, `injector_provider_id`, `director_provider_id`, `exam_provider_id`, and `treatment_session_id` — failing with the corresponding `ERR_MEMBERSHIP_NOT_FOUND`, `ERR_PATIENT_NOT_FOUND`, `ERR_CONSULTATION_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_STANDING_ORDER_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`, or `ERR_SESSION_NOT_FOUND`. A malformed body — a missing required field, a type mismatch, an unrecognized enum value, or a non-positive amount or unit count where a positive value is required — is rejected with `ERR_INVALID_REQUEST`.

### 2.8. Validation Precedence

When an endpoint must apply several checks, they are evaluated in a fixed precedence so that the returned error is deterministic. First, header presence and validity are checked (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`); second, the role's permission for the operation (`ERR_INSUFFICIENT_PERMISSIONS`); third, existence of any resource named by a path identifier (the relevant not-found error); fourth, existence of any foreign-key reference in the body (the relevant not-found error); fifth, any program-agreement constraint such as the loyalty-program match described below; sixth, the target resource's source-state requirement for the requested transition (the relevant not-in-state error); seventh, the optimistic-concurrency version check (§2.9); and only then the domain-specific safety, compliance, and fiscal checks described in §3. (For every transition that carries both a source-state requirement and an OCC version field — plan activation, completion, cancellation, and session booking — the source-state requirement is checked first, so a request that is both in the wrong state and stale returns the not-in-state error rather than `ERR_STALE_PLAN_VERSION`.) Within those domain checks the workflow narratives state the order in which they apply.

### 2.9. Optimistic Concurrency Control

Several write operations require the client to declare the version of the parent resource it last observed, so that a writer never overwrites changes it has not seen. Each such operation takes a non-optional version field that must equal the parent's current `version`; if it does not match, the write is rejected with the corresponding stale-version error and HTTP status 412, and no change is made.

Plan activation, completion, and cancellation, posting a deposit, and booking a treatment session each require `expected_treatment_plan_version` to equal the target `TreatmentPlan`'s current `version`, failing with `ERR_STALE_PLAN_VERSION`. Quarantining a lot requires `expected_lot_version` to equal the `InjectableLot`'s current `version`, failing with `ERR_STALE_LOT_VERSION`. Suspending a provider requires `expected_provider_version` to equal the `Provider`'s current `version`, failing with `ERR_STALE_PROVIDER_VERSION`. Revoking a standing order requires `expected_standing_order_version` to equal the `StandingOrder`'s current `version`, failing with `ERR_STALE_STANDING_ORDER_VERSION`. Endpoints not named here take no version field.

Booking a treatment session deserves special emphasis. The booking request must carry `expected_treatment_plan_version` matching the target plan's current `version`. Because a prior booking against the same plan reserves lot units and advances the plan's `version` — which legitimately changes `provisional_series_cost_cents` and how many units remain reservable — a client whose observed version has fallen behind is working from a stale view of both the plan and the remaining reservable capacity. Such a booking is rejected with `ERR_STALE_PLAN_VERSION` (HTTP 412), forcing the client to refresh before retrying rather than reserve against a plan state it never saw.

## 3. Business Logic & Workflows

### 3.1. Providers, Membership, Lots, and Patients: the Catalog Foundations

A `ClinicAdmin` registers each clinical staff member as a `Provider`, supplying the `full_name`, the state `license_number`, and the `role_kind`, which is either `INJECTOR` or `MEDICAL_DIRECTOR`. An `INJECTOR` performs good-faith exams and injections; a `MEDICAL_DIRECTOR` signs standing orders. Every provider begins with `status` of `ACTIVE`, and the computed counters `open_complication_count`, `resolved_complication_count`, and `committed_session_count` all start at 0. Suspending a provider sets `status` to `SUSPENDED`; a `SUSPENDED` provider may not perform any new clinical action. Providers may be listed with optional `role_kind` and `status` filters.

Membership is described by a `MembershipPackage`, created by a `ClinicAdmin` with a `tier` of `BASIC`, `PLUS`, or `VIP`, a `member_discount_pct` expressed as a fraction at least 0 and strictly below 1 (for example 0.15 for fifteen percent), a `loyalty_program` of either `ALLE` or `ASPIRE`, and an informational `monthly_fee_cents`. The discount is the per-line fraction applied during charge calculation. Packages may be listed with an optional `tier` filter.

Injectable inventory is tracked as an `InjectableLot`, intaken by a `ClinicAdmin` with the `product` (`BOTOX`, `DYSPORT`, `JUVEDERM`, or `RESTYLANE`), the manufacturer `lot_number`, the `expiration_date` as an ISO 8601 UTC instant, and the `total_units` it contains at intake, which must be greater than 0 and is immutable afterward. At intake `reserved_units` and `consumed_units` are both 0, `remaining_units` equals `total_units`, and `status` is `AVAILABLE`. A lot is treated as expired once the logical clock reaches or passes its `expiration_date`. Quarantining a lot sets `status` to `QUARANTINED`; a `QUARANTINED` lot can no longer back new reservations. Lots may be listed with optional `product` and `status` filters.

A `Patient` is registered by a `ClinicAdmin` with a `full_name`, a `date_of_birth` as an ISO 8601 UTC instant, and an optional `membership_id` referencing a `MembershipPackage`; a patient with no membership receives no discount and is priced at list. Each patient carries the computed flag `photo_consent_on_file`, which begins `false` and becomes `true` once a signed consent record exists for that patient (see §3.5). Patients may be listed with an optional `membership_id` filter.

A patient earns and redeems loyalty through a `LoyaltyAccount`, opened by a `ClinicAdmin` with the `patient_id` it belongs to (conceptually one account per patient, though the system does not reject opening a second account for a patient that already has one) and a `program` of either `ALLE` or `ASPIRE`. The account's `program` must equal the loyalty program of the patient's membership — that is, the `loyalty_program` on the `MembershipPackage` the patient's `membership_id` points to — otherwise the request is rejected with `ERR_LOYALTY_PROGRAM_MISMATCH`; a patient with no membership at all likewise fails with `ERR_LOYALTY_PROGRAM_MISMATCH` (there is no membership loyalty program to match). A new account opens with `points_earned`, `points_redeemed`, and `points_balance` all at 0. Sessions later earn and redeem against this account at commit, and refund compensations reverse those movements (see §3.6 and §3.7). Loyalty accounts may be listed with an optional `patient_id` filter.

### 3.2. Consultations, Standing Orders, and the Authority to Treat

Before anyone may be treated, a good-faith exam must be on record. A `Provider` opens a `Consultation` by supplying the `patient_id`, the `exam_provider_id` of the injector who will perform the exam, and the patient's `chief_complaint`; it begins in `DRAFT`. Finalizing the exam advances the consultation from `DRAFT` to `EXAM_COMPLETE`, which is permitted only while it is in `DRAFT` (otherwise `ERR_CONSULTATION_NOT_DRAFT`) and only when the exam provider is an `INJECTOR` whose `status` is `ACTIVE` (otherwise `ERR_PROVIDER_NOT_ELIGIBLE`). On finalization the system stamps `exam_clock_utc` with the current logical-clock instant, which opens the validity window for the good-faith exam.

A consultation may be voided by a `ClinicAdmin`. Voiding from `EXAM_COMPLETE` to `VOID` is permitted only when no `TreatmentPlan` in `PROPOSED` or `ACTIVE` status references this consultation; if one does, the void is rejected with `ERR_CONSULTATION_IN_USE`. A consultation may also be voided directly from `DRAFT` to `VOID`. An attempt to void a consultation that is in neither an eligible source state is rejected with `ERR_CONSULTATION_NOT_DRAFT`. `VOID` is terminal. Consultations may be listed with optional `patient_id`, `exam_provider_id`, and `status` filters.

The legal authority to inject comes from a `StandingOrder`, signed by a medical director against a completed exam. A `Provider` signs one by supplying the `consultation_id` it authorizes treatment against, the `director_provider_id` of the signing medical director, the `product` it authorizes, the `max_units_authorized` per session (which must be greater than 0), and the `valid_until_utc` instant after which it expires. The signing director must be a `MEDICAL_DIRECTOR` whose `status` is `ACTIVE` (otherwise `ERR_PROVIDER_NOT_ELIGIBLE`). The order is created with `status` of `SIGNED`. An order is active only while its `status` is `SIGNED` and the logical clock is strictly before its `valid_until_utc`. Revoking an order sets `status` to `REVOKED`; a `REVOKED` order can authorize no further sessions. Standing orders may be listed with optional `consultation_id`, `director_provider_id`, and `status` filters.

A foundational safety principle threads through the entire program: the medical director who signs a standing order may not also be the injector who performs an authorized session against it. This segregation of duties is enforced at session booking, described in §3.4.

### 3.3. Treatment Plans: the Series, the Deposit, and the Cost Ledger

A `TreatmentPlan` represents a planned series of sessions for one patient against one product. A `Provider` proposes a plan by supplying the `patient_id`, the `consultation_id` of the completed exam it is built on, the `product`, the `planned_sessions` count (at least 1), the `planned_units_per_session` estimate (greater than 0), the `list_price_per_unit_cents` snapshotted at proposal time (greater than 0), and the `required_deposit_cents` that must be collected before activation (at least 0). A new plan begins in `PROPOSED` with `deposit_paid_cents` and `finalized_series_cost_cents` at 0, `sessions_committed` at 0, and `provisional_series_cost_cents` computed forward over the full series (see §3.6). Plans may be listed with optional `patient_id`, `consultation_id`, and `status` filters.

Deposits fund a plan. A `ClinicAdmin` posts a `Deposit` by supplying the `treatment_plan_id` it funds and the `amount_cents` (greater than 0), along with `expected_treatment_plan_version`. A posted deposit begins with `status` of `POSTED`; posting it adds its `amount_cents` to the plan's `deposit_paid_cents` and increments the plan's `version` by 1. Deposits may be listed with optional `treatment_plan_id` and `status` filters.

Activating a plan advances it from `PROPOSED` to `ACTIVE`. Activation is permitted only when the plan is in `PROPOSED` (otherwise `ERR_PLAN_NOT_PROPOSED`), when `expected_treatment_plan_version` matches the plan's current `version` (otherwise `ERR_STALE_PLAN_VERSION`), when the referenced consultation is in `EXAM_COMPLETE` (otherwise `ERR_NO_GOOD_FAITH_EXAM`), and when `deposit_paid_cents` is at least `required_deposit_cents` (otherwise `ERR_DEPOSIT_REQUIRED`). On activation the plan recomputes `provisional_series_cost_cents` over all planned sessions, none of which are committed yet, and increments its `version` by 1.

Completing a plan advances it from `ACTIVE` to `COMPLETED`. It is permitted only when the plan is `ACTIVE` (otherwise `ERR_PLAN_NOT_ACTIVE`), when `expected_treatment_plan_version` matches the plan's current `version` (otherwise `ERR_STALE_PLAN_VERSION`), and when no session on the plan is in `BOOKED`, `COMMITTED`, or `COMPLICATION_OPEN` (otherwise `ERR_OPEN_SESSIONS_EXIST`). On completion the plan recomputes `provisional_series_cost_cents` to 0, since no sessions remain, and increments its `version` by 1. `COMPLETED` is terminal.

Cancellation, performed by a `ClinicAdmin`, applies from either `PROPOSED` or `ACTIVE` and moves the plan to `CANCELLED`. It is permitted only when the plan is in `PROPOSED` or `ACTIVE` (otherwise `ERR_PLAN_NOT_CANCELLABLE`), when `expected_treatment_plan_version` matches the plan's current `version` (otherwise `ERR_STALE_PLAN_VERSION`), and when `sessions_committed` equals 0 (otherwise `ERR_PLAN_HAS_COMMITTED_SESSIONS`). Cancellation runs two compensating cascades: every `POSTED` deposit on the plan is set to `REFUNDED`, after which `deposit_paid_cents` recomputes to 0; and every `BOOKED` session on the plan is set to `CANCELLED`, which releases the lot units each had reserved (described in §3.4). The plan's `version` increments by 1. `CANCELLED` is terminal.

### 3.4. Booking a Session and Reserving Inventory

A `TreatmentSession` is one injection appointment within an active plan. A `Provider` books one against the plan by supplying the `treatment_plan_id`, the `standing_order_id` authorizing it, the `injector_provider_id` who will perform it, the `injectable_lot_id` recorded as the lot of entry, the `planned_units` to reserve (greater than 0), an optional `loyalty_points_redeemed` count (at least 0, defaulting to 0), and `expected_treatment_plan_version`. The session begins in `BOOKED`, with `final_charge_cents`, `balance_due_cents`, and `points_earned_cents_basis` all at 0 and `actual_units` at `null` until commit.

Booking is the system's busiest gate, and its preconditions apply in this order. The plan must be `ACTIVE` (otherwise `ERR_PLAN_NOT_ACTIVE`), and `expected_treatment_plan_version` must match the plan's current `version` (otherwise `ERR_STALE_PLAN_VERSION`, HTTP 412 — see §2.9). The standing order must be active, meaning its `status` is `SIGNED` and the logical clock is strictly before its `valid_until_utc` (otherwise `ERR_STANDING_ORDER_INACTIVE`). The good-faith exam on the plan's consultation must be in `EXAM_COMPLETE` (otherwise `ERR_NO_GOOD_FAITH_EXAM`) and must not have expired: the exam is fresh only while `exam_clock_utc` plus the good-faith-exam validity window is strictly after the current clock, where that window is 365 days; once the clock reaches or passes that horizon the booking is rejected with `ERR_GOOD_FAITH_EXAM_EXPIRED`. The product must agree across all three sources — the standing order's `product`, the plan's `product`, and the chosen lot's `product` must be identical (otherwise `ERR_PRODUCT_MISMATCH`). The `planned_units` must not exceed the standing order's `max_units_authorized` (otherwise `ERR_UNITS_EXCEED_ORDER`). The injector must be an `INJECTOR` whose `status` is `ACTIVE` (otherwise `ERR_PROVIDER_NOT_ELIGIBLE`). The injector must not be the same provider as the standing order's `director_provider_id`, enforcing segregation of duties (otherwise `ERR_SEGREGATION_OF_DUTIES`). The patient's `photo_consent_on_file` must be `true` (otherwise `ERR_CONSENT_PHOTO_REQUIRED`). Finally, there must be enough inventory: the sum of `remaining_units` across all `AVAILABLE`, non-expired lots of the plan's product must be at least `planned_units` (otherwise `ERR_INSUFFICIENT_LOT_UNITS`).

When all preconditions pass, the system reserves units on a first-expiry-first-out basis. It gathers every lot whose `product` equals the plan's product, whose `status` is `AVAILABLE`, and whose `expiration_date` is strictly after the current clock, then orders that candidate set by `expiration_date` ascending and, where two lots share an expiration, by `created_at` ascending; the lot `id` is never used as a tiebreaker. Walking that ordered list, it takes from each lot the smaller of the units still needed and that lot's `remaining_units`, incrementing the lot's `reserved_units` and recomputing its `remaining_units`, until the full `planned_units` are reserved. (The `injectable_lot_id` supplied on the session records the entry lot; the actual reservation may straddle several lots resolved server-side.) Booking then increments the plan's `version` by 1 and recomputes `provisional_series_cost_cents` over the sessions not yet committed.

A `ClinicAdmin` may cancel a booked session or mark it a no-show. Cancelling is permitted only from `BOOKED` (otherwise `ERR_SESSION_NOT_BOOKED`) and moves the session to `CANCELLED`, releasing every reserved unit the session holds back to the relevant lots' `remaining_units` and recomputing the plan's `provisional_series_cost_cents`. Marking a no-show is likewise permitted only from `BOOKED` (otherwise `ERR_SESSION_NOT_BOOKED`), moves the session to `NO_SHOW`, releases all the session's reserved units back to lot `remaining_units`, and recomputes the plan's `provisional_series_cost_cents`. Both `CANCELLED` and `NO_SHOW` are terminal. Sessions may be listed with optional `treatment_plan_id`, `standing_order_id`, `injector_provider_id`, `injectable_lot_id`, and `status` filters.

### 3.5. Photo Documentation and Consent Gating

Photographic documentation is recorded as a `ConsentPhoto`, captured by a `Provider` with the `patient_id` it concerns, the `kind` (one of `CONSENT`, `BEFORE`, or `AFTER`), an opaque `storage_uri` pointing at the stored artifact, an optional `treatment_session_id` identifying the session the photo documents (omitted for standalone consent capture), and an optional `signed` flag that defaults to `false`. A `CONSENT` record with `signed` set to `true` represents a signed consent; recording such a record flips the subject patient's `photo_consent_on_file` to `true`. `BEFORE` and `AFTER` records are the clinical before/after images. Photo records are immutable once written. Photos may be listed with optional `patient_id`, `treatment_session_id`, and `kind` filters.

These records gate three clinical transitions. A signed `CONSENT` photo must exist for the patient before a session can be booked, or booking fails with `ERR_CONSENT_PHOTO_REQUIRED`. A `BEFORE` photo tied to the session must exist before that session can be committed, or commit fails with `ERR_BEFORE_PHOTO_REQUIRED`. An `AFTER` photo tied to the session must exist before that session can be resolved, or resolve fails with `ERR_AFTER_PHOTO_REQUIRED`.

### 3.6. Committing a Session: Charge, Loyalty, and the Cost Ledger

Committing advances a session from `BOOKED` to `COMMITTED`. It is permitted only when the session is `BOOKED` (otherwise `ERR_SESSION_NOT_BOOKED`), when the `actual_units` actually injected — supplied at commit as a positive integer (rejected with `ERR_INVALID_REQUEST` if present but not a positive integer), defaulting to `planned_units` when omitted or null — do not exceed the standing order's `max_units_authorized` (otherwise `ERR_UNITS_EXCEED_ORDER`), and when a `BEFORE` photo tied to the session exists (otherwise `ERR_BEFORE_PHOTO_REQUIRED`).

On commit the system first settles inventory: it converts reserved units to consumed for the `actual_units`, walking the same lots the session reserved in the same `expiration_date` ascending then `created_at` ascending order, decrementing each lot's `reserved_units` and incrementing its `consumed_units`; any leftover reservation — the `planned_units` minus the `actual_units` — is released back to the lots' `remaining_units`.

The session charge is then computed. The applicable discount fraction is the patient's membership `member_discount_pct` if the patient has a membership, or 0 if the patient has no membership. The committed session has a single product line. That line's cost is the `actual_units` multiplied by the plan's `list_price_per_unit_cents` multiplied by one minus the discount fraction, rounded half up to whole cents. (The rounding is applied to the line before any summing; for the single line here the subtotal equals that rounded line total. This per-line-then-sum order is deliberate and load-bearing — sum-then-round would diverge by cents on fractional-cent lines.) The loyalty redemption is the session's `loyalty_points_redeemed` multiplied by the per-point value, where one point is worth one cent. The `final_charge_cents` is the subtotal minus the loyalty redemption, floored at 0 so it can never go negative.

From the final charge the system derives two more figures and updates the ledgers. The deposit allocated to this session is the smaller of `final_charge_cents` and the plan's `deposit_paid_cents`; `balance_due_cents` is `final_charge_cents` minus that allocated deposit, but never less than 0. The loyalty basis `points_earned_cents_basis` is `final_charge_cents` divided by 100, taking the floor (one point per whole dollar). The patient's loyalty account then adds `points_earned_cents_basis` to its `points_earned`, adds the session's `loyalty_points_redeemed` to its `points_redeemed`, and recomputes `points_balance`. The plan's `finalized_series_cost_cents` increases by `final_charge_cents`, its `sessions_committed` increases by 1, its `provisional_series_cost_cents` recomputes over the remaining sessions, and its `version` increments by 1. Finally the injecting provider's `committed_session_count` is recomputed.

The two series-cost figures answer different questions. The forward-looking `provisional_series_cost_cents` is an estimate over the sessions not yet committed: the number of remaining sessions — the plan's `planned_sessions` minus its `sessions_committed`, treated as 0 if that difference would be negative — multiplied by `planned_units_per_session` multiplied by `list_price_per_unit_cents`. This estimate uses list price only, with no member discount and no loyalty applied, and is recomputed on activation and on every session book, commit, cancel, or no-show. The realized `finalized_series_cost_cents` is instead the chronological running sum of the actual member-discounted, loyalty-adjusted `final_charge_cents` of committed sessions (net of refund compensations). Because the realized figure honors discount and loyalty while the provisional one does not, the two diverge even for identical planned inputs.

### 3.7. Resolving a Session and Handling Complications

A committed session reaches its happy-path terminal state when it is resolved. Resolution advances the session from `COMMITTED` to `RESOLVED` and is permitted only when the session is `COMMITTED` (otherwise `ERR_SESSION_NOT_COMMITTED`), when an `AFTER` photo tied to the session exists (otherwise `ERR_AFTER_PHOTO_REQUIRED`), and when no `ComplicationCase` for the session is in `OPEN` or `IN_TOUCHUP` (otherwise `ERR_COMPLICATION_OPEN`). Resolution makes no ledger change. `RESOLVED` is terminal for a session.

When a committed session goes wrong, a `Provider` opens a `ComplicationCase` against it by supplying the `treatment_session_id` and the `severity` (one of `MINOR`, `MODERATE`, or `SEVERE`). The originating session must be `COMMITTED` (otherwise `ERR_SESSION_NOT_COMMITTED`). Opening a case moves the session from `COMMITTED` to `COMPLICATION_OPEN`, creates the case in `OPEN` with `touchup_rounds` and `refund_cents` at 0, copies the originating session's injector into the case's `injector_provider_id` for provider risk scoring, and recomputes that provider's `open_complication_count`. Complication cases may be listed with optional `treatment_session_id`, `injector_provider_id`, and `status` filters.

A complication is worked through touch-up rounds. Opening a touch-up advances the case from `OPEN` to `IN_TOUCHUP` and is permitted only when the case is `OPEN` (otherwise `ERR_CASE_NOT_OPEN`), when the `severity` is `MINOR` or `MODERATE` — a `SEVERE` complication is refund-only and may never open a touch-up (otherwise `ERR_SEVERE_NO_TOUCHUP`) — when `touchup_rounds` is strictly less than the round cap of 2 (otherwise `ERR_TOUCHUP_LIMIT_REACHED`), and when the originating session's standing order is still active, that is its `status` is `SIGNED` and the logical clock is strictly before its `valid_until_utc` (otherwise `ERR_STANDING_ORDER_INACTIVE`). Opening a touch-up increments the case's `touchup_rounds` by 1. If the touch-up does not succeed, the case is looped back from `IN_TOUCHUP` to `OPEN` — permitted only when the case is `IN_TOUCHUP` (otherwise `ERR_CASE_NOT_IN_TOUCHUP`) — making it eligible for another round, up to the cap, or for refund resolution.

Resolving a complication moves the case to `RESOLVED` and may be requested from either `OPEN` or `IN_TOUCHUP`; resolving from `OPEN` requires the case to be `OPEN` (otherwise `ERR_CASE_NOT_OPEN`) and resolving from `IN_TOUCHUP` requires the case to be `IN_TOUCHUP` (otherwise `ERR_CASE_NOT_OPEN`). The request supplies a `resolution_mode`. When the mode is `REFUND`, the system runs a compensation: it sets the case's `refund_cents` to the originating session's `final_charge_cents`; it reverses that session's loyalty by subtracting the session's `points_earned_cents_basis` from the loyalty account's `points_earned` and subtracting the session's `loyalty_points_redeemed` from its `points_redeemed`, then recomputing `points_balance`; and it subtracts the session's `final_charge_cents` from the plan's `finalized_series_cost_cents`. When the mode is `CLINICAL`, `refund_cents` stays 0 and no ledger changes. In both modes the originating injector's `open_complication_count` and `resolved_complication_count` are recomputed. Both branches of resolution apply identically whether the case was resolved from `OPEN` or from `IN_TOUCHUP`. `RESOLVED` is terminal for a case.

### 3.8. Provider Risk Scoring

A provider's record exposes a complication rate in two variants, recomputed whenever the provider is read and whenever a complication opens or resolves. Both variants are expressed in basis points using a scale of 10,000, and both divide a numerator of complication counts by the provider's `committed_session_count`. When `committed_session_count` is 0, the rate is 0 by definition, with no division performed. Otherwise the rate is the numerator multiplied by 10,000 divided by `committed_session_count`, rounded half up to a whole number of basis points.

The two variants differ only in the numerator. The provisional (live) rate counts both still-open and resolved complications — its numerator is `open_complication_count` plus `resolved_complication_count` — treating still-open complications as adverse pending outcomes, which is the appropriate view before authorizing a new session. The settled (credentialing) rate counts only resolved complications — its numerator is `resolved_complication_count` alone — excluding still-open cases. Because the same inputs feed two different inclusion sets, the two rates can differ for the same provider.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — including all state-transition actions and the clock-control capability — return `200 OK`. List and single-resource reads return `200 OK`. For complete request and response semantics, consult the workflow narratives in §3; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/aesthetics/providers` | Register a provider | ClinicAdmin |
| GET | `/aesthetics/providers` | List providers (filter by role_kind/status) | ClinicAdmin, Provider |
| GET | `/aesthetics/providers/{id}` | Get a provider with complication-rate variants | ClinicAdmin, Provider |
| POST | `/aesthetics/providers/{id}/suspend` | Suspend a provider | ClinicAdmin |
| POST | `/aesthetics/membership-packages` | Create a membership tier | ClinicAdmin |
| GET | `/aesthetics/membership-packages` | List membership packages (filter by tier) | ClinicAdmin, Provider |
| GET | `/aesthetics/membership-packages/{id}` | Get a membership package | ClinicAdmin, Provider |
| POST | `/aesthetics/injectable-lots` | Intake an injectable lot | ClinicAdmin |
| GET | `/aesthetics/injectable-lots` | List lots (filter by product/status) | ClinicAdmin, Provider |
| GET | `/aesthetics/injectable-lots/{id}` | Get a lot with its unit ledger | ClinicAdmin, Provider |
| POST | `/aesthetics/injectable-lots/{id}/quarantine` | Quarantine a lot | ClinicAdmin |
| POST | `/aesthetics/patients` | Register a patient | ClinicAdmin |
| GET | `/aesthetics/patients` | List patients (filter by membership_id) | ClinicAdmin, Provider |
| GET | `/aesthetics/patients/{id}` | Get a patient | ClinicAdmin, Provider |
| POST | `/aesthetics/loyalty-accounts` | Open a patient's loyalty account | ClinicAdmin |
| GET | `/aesthetics/loyalty-accounts` | List loyalty accounts (filter by patient_id) | ClinicAdmin, Provider |
| GET | `/aesthetics/loyalty-accounts/{id}` | Get a loyalty account with its points ledger | ClinicAdmin, Provider |
| POST | `/aesthetics/consultations` | Open a consultation (good-faith exam draft) | Provider |
| GET | `/aesthetics/consultations` | List consultations (filter by patient_id/exam_provider_id/status) | ClinicAdmin, Provider |
| GET | `/aesthetics/consultations/{id}` | Get a consultation | ClinicAdmin, Provider |
| POST | `/aesthetics/consultations/{id}/complete-exam` | Finalize the good-faith exam | Provider |
| POST | `/aesthetics/consultations/{id}/void` | Void a consultation | ClinicAdmin |
| POST | `/aesthetics/standing-orders` | Sign a standing order | Provider |
| GET | `/aesthetics/standing-orders` | List standing orders (filter by consultation_id/director_provider_id/status) | ClinicAdmin, Provider |
| GET | `/aesthetics/standing-orders/{id}` | Get a standing order | ClinicAdmin, Provider |
| POST | `/aesthetics/standing-orders/{id}/revoke` | Revoke a standing order | Provider |
| POST | `/aesthetics/consent-photos` | Record a consent/before/after photo | Provider |
| GET | `/aesthetics/consent-photos` | List photos (filter by patient_id/treatment_session_id/kind) | ClinicAdmin, Provider |
| GET | `/aesthetics/consent-photos/{id}` | Get a photo record | ClinicAdmin, Provider |
| POST | `/aesthetics/treatment-plans` | Propose a treatment plan/series | Provider |
| GET | `/aesthetics/treatment-plans` | List plans (filter by patient_id/consultation_id/status) | ClinicAdmin, Provider |
| GET | `/aesthetics/treatment-plans/{id}` | Get a plan with its cost ledger | ClinicAdmin, Provider |
| POST | `/aesthetics/treatment-plans/{id}/activate` | Activate a plan | Provider |
| POST | `/aesthetics/treatment-plans/{id}/complete` | Complete a plan | Provider |
| POST | `/aesthetics/treatment-plans/{id}/cancel` | Cancel a plan (cascade refunds + session cancels) | ClinicAdmin |
| POST | `/aesthetics/deposits` | Post a deposit against a plan | ClinicAdmin |
| GET | `/aesthetics/deposits` | List deposits (filter by treatment_plan_id/status) | ClinicAdmin, Provider |
| GET | `/aesthetics/deposits/{id}` | Get a deposit | ClinicAdmin, Provider |
| POST | `/aesthetics/treatment-sessions` | Book a session (FEFO-reserves lot units) | Provider |
| GET | `/aesthetics/treatment-sessions` | List sessions (filter by treatment_plan_id/standing_order_id/injector_provider_id/injectable_lot_id/status) | ClinicAdmin, Provider |
| GET | `/aesthetics/treatment-sessions/{id}` | Get a session | ClinicAdmin, Provider |
| POST | `/aesthetics/treatment-sessions/{id}/commit` | Commit a session (consume units, compute charge, earn/redeem loyalty) | Provider |
| POST | `/aesthetics/treatment-sessions/{id}/resolve` | Resolve a committed session | Provider |
| POST | `/aesthetics/treatment-sessions/{id}/cancel` | Cancel a booked session | ClinicAdmin |
| POST | `/aesthetics/treatment-sessions/{id}/no-show` | Mark a booked session no-show | ClinicAdmin |
| POST | `/aesthetics/complication-cases` | Open a complication on a committed session | Provider |
| GET | `/aesthetics/complication-cases` | List complications (filter by treatment_session_id/injector_provider_id/status) | ClinicAdmin, Provider |
| GET | `/aesthetics/complication-cases/{id}` | Get a complication case | ClinicAdmin, Provider |
| POST | `/aesthetics/complication-cases/{id}/open-touchup` | Open a touch-up round | Provider |
| POST | `/aesthetics/complication-cases/{id}/touchup-failed` | Loop case back to OPEN after a failed touch-up | Provider |
| POST | `/aesthetics/complication-cases/{id}/resolve` | Resolve a complication (REFUND or CLINICAL) | Provider |
| POST | `/_clock/set_current_utc` | Set the server logical clock | ClinicAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_PROVIDER_NOT_FOUND` | 404 Not Found |
| `ERR_PATIENT_NOT_FOUND` | 404 Not Found |
| `ERR_MEMBERSHIP_NOT_FOUND` | 404 Not Found |
| `ERR_LOT_NOT_FOUND` | 404 Not Found |
| `ERR_CONSULTATION_NOT_FOUND` | 404 Not Found |
| `ERR_STANDING_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_SESSION_NOT_FOUND` | 404 Not Found |
| `ERR_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_PLAN_VERSION` | 412 Precondition Failed |
| `ERR_STALE_LOT_VERSION` | 412 Precondition Failed |
| `ERR_STALE_PROVIDER_VERSION` | 412 Precondition Failed |
| `ERR_STALE_STANDING_ORDER_VERSION` | 412 Precondition Failed |
| `ERR_CONSULTATION_NOT_DRAFT` | 409 Conflict |
| `ERR_CONSULTATION_IN_USE` | 409 Conflict |
| `ERR_PLAN_NOT_PROPOSED` | 409 Conflict |
| `ERR_PLAN_NOT_ACTIVE` | 409 Conflict |
| `ERR_PLAN_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_PLAN_HAS_COMMITTED_SESSIONS` | 409 Conflict |
| `ERR_OPEN_SESSIONS_EXIST` | 409 Conflict |
| `ERR_SESSION_NOT_BOOKED` | 409 Conflict |
| `ERR_SESSION_NOT_COMMITTED` | 409 Conflict |
| `ERR_CASE_NOT_OPEN` | 409 Conflict |
| `ERR_CASE_NOT_IN_TOUCHUP` | 409 Conflict |
| `ERR_COMPLICATION_OPEN` | 409 Conflict |
| `ERR_NO_GOOD_FAITH_EXAM` | 409 Conflict |
| `ERR_GOOD_FAITH_EXAM_EXPIRED` | 409 Conflict |
| `ERR_STANDING_ORDER_INACTIVE` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_PROVIDER_NOT_ELIGIBLE` | 409 Conflict |
| `ERR_CONSENT_PHOTO_REQUIRED` | 409 Conflict |
| `ERR_BEFORE_PHOTO_REQUIRED` | 409 Conflict |
| `ERR_AFTER_PHOTO_REQUIRED` | 409 Conflict |
| `ERR_PRODUCT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_UNITS_EXCEED_ORDER` | 422 Unprocessable Entity |
| `ERR_SEVERE_NO_TOUCHUP` | 409 Conflict |
| `ERR_TOUCHUP_LIMIT_REACHED` | 409 Conflict |
| `ERR_LOYALTY_PROGRAM_MISMATCH` | 422 Unprocessable Entity |
| `ERR_DEPOSIT_REQUIRED` | 402 Payment Required |
| `ERR_INSUFFICIENT_LOT_UNITS` | 409 Conflict |
