# Vocational Rehabilitation (State VR) API — Product Requirements Document

## 1. Introduction

State Vocational Rehabilitation (VR) agencies help people with disabilities prepare for, obtain, and retain employment. The journey of a single consumer touches a long chain of decisions: a referral arrives, a signed application is taken, an eligibility and disability-significance determination is made, an Individualized Plan for Employment (IPE) is authored and approved, services such as training and assistive technology are authorized against a case budget, vendors are paid, a job placement is recorded, and — after a stabilization period — the case is closed and reported to the federal RSA-911 data system. This document specifies the REST API that orchestrates that end-to-end workflow.

The system exists to make three difficult things trustworthy at once: **fiscal integrity** (every dollar authorized, committed, paid, and reversed must reconcile against a case budget and a provider ledger), **order-of-selection fairness** (when funded slots are scarce, eligible consumers are served or waitlisted strictly by priority and arrival order), and **outcome accountability** (a case may only be reported as "rehabilitated" after a verified 90-day stabilization). Because several people act on the same case concurrently — a Counselor requests, a Supervisor approves and commits funds, a Fiscal Officer disburses, and a Provider reports delivery — the API leans on immediate consistency, explicit state machines, cascading side effects, and optimistic concurrency control to keep the shared financial picture correct.

A logical clock underpins every time-sensitive rule so that stabilization windows and service periods are deterministic and testable. Rather than reading wall-clock time, the system tracks time through an administratively settable instant that defaults, at startup, to `2026-05-01T00:00:00Z`.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the principal's role. If `X-User-Role` is missing or is not one of the five recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the role is recognized but not permitted for the requested operation — or if an ownership-scoped role acts on a resource it does not own — the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The five roles are `VRAdmin`, `Counselor`, `Supervisor`, `FiscalOfficer`, and `Provider`.

- `VRAdmin` is an administrative role responsible for onboarding counselors, supervisors, providers, and priority categories; opening and closing categories and adjusting capacity; promoting waitlisted cases; and setting the logical clock. When `X-User-Role` is `VRAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- When `X-User-Role` is `Counselor`, `X-User-ID` is the `id` of the acting `Counselor`. Ownership checks on any case compare the case's `counselor_id` to `X-User-ID`: a Counselor may drive application, eligibility, IPE authoring, authorization requests, placements, progress reviews, and closure only on cases it owns.
- When `X-User-Role` is `Supervisor`, `X-User-ID` is the `id` of the acting `Supervisor`. The server records it (for example as `approved_by_supervisor_id` on an IPE or a ServiceAuthorization when a transition writes it) but does not otherwise tie it to resource ownership; any Supervisor may approve.
- When `X-User-Role` is `FiscalOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example as `issued_by` on a Payment at issue time) but does not compare it to any entity's `id`.
- When `X-User-Role` is `Provider`, `X-User-ID` is the `id` of the acting `Provider`. Ownership checks on a service authorization compare the authorization's `provider_id` to `X-User-ID`: a Provider may report service delivery only on its own authorizations.

All five roles may set the logical clock and may call every read (GET) endpoint. The write operations reserved to each role are enumerated in §3 and summarized by the Authorized Role(s) column in §4.

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

All list endpoints accept two optional query parameters, `limit` and `offset`. The `limit` defaults to 10, with a minimum of 1 and a maximum of 100; a supplied value outside that band is clamped or rejected as an invalid body/parameter per §2.10. The `offset` defaults to 0 and represents the number of leading records to skip. List results are ordered by `created_at` ascending (oldest first). The `meta` block of a list response reports `limit`, `offset`, `total_count` (the total number of records matching the filter, before pagination), and `has_more` (true when records remain beyond the current page).

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` ISO 8601 UTC timestamp with three fractional digits recorded at creation.

Most resources additionally carry an `updated_at` ISO 8601 UTC timestamp and an integer `version` that starts at 1 and increments by one on every mutation. These full-lifecycle resources are `Provider`, `PriorityCategory`, `Case`, `IPE`, `ServiceAuthorization`, `Payment`, and `Placement`. Whenever a mutation described in §3 changes a resource — including changes to computed fields such as a case's fund balances or a category's slot counts — `updated_at` is refreshed and `version` is incremented.

Three record types are lightweight and carry only `id` and `created_at`, with no `updated_at` and no `version`: `Counselor`, `Supervisor`, and `ProgressReview`. A `ProgressReview` in particular is an append-only event; once written it is never mutated.

### 2.5. Nested Retrieval and Reference Validation

Path and body identifiers are validated left to right, and any identifier that does not resolve to an existing resource yields `ERR_NOT_FOUND` (HTTP 404). This applies to path variables such as `case_id`, `category_id`, `ipe_id`, `authorization_id`, `payment_id`, and `placement_id`, and to the placement `id` used when listing a placement's progress reviews. It likewise applies to body foreign keys such as `case_id`, `ipe_id`, `provider_id`, and `authorization_id`. Existence is checked before any state or business rule is evaluated.

### 2.6. Monetary Values, Counts, and Rounding

All monetary amounts are stored and returned as whole integer cents. Ledger arithmetic — committing, releasing, paying, and reversing — operates on exact whole cents and never rounds. Rounding appears only where a rate or an average is applied: the consumer cost-share multiplication, the federal reimbursement split, and the verified average weekly wage. In each of those cases the "round half up" method is applied to produce whole cents. Slot counts are non-negative integers.

### 2.7. Optimistic Concurrency Control

Approving a service authorization commits money against a shared case budget, so it is guarded by optimistic concurrency control on the parent `Case`. The approve-authorization operation requires an `expected_case_version` field carrying the `version` of the `Case` that the client last observed. If `expected_case_version` does not equal the case's current `version` — for example because another approval has since committed funds and advanced the case — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and no funds are committed. This prevents a Supervisor from approving against a budget snapshot that no longer reflects previously committed obligations. No other endpoint takes a version field; only authorization approval carries this check.

### 2.8. Case Fund Ledger

Each case tracks money in three computed integer-cent fields that must always reconcile. `funds_committed_cents` is the obligated-but-unpaid total: the sum, over the case's authorizations currently in `APPROVED` status, of that authorization's `agency_share_cents` minus its `amount_paid_cents`. `funds_paid_cents` is the sum of `amount_cents` over all `ISSUED` payments across the case's authorizations. `funds_available_cents` is `budget_allocated_cents` minus `funds_committed_cents` minus `funds_paid_cents`. Authorizations that are `REQUESTED`, `CANCELLED`, or `COMPLETED-but-unpaid` contribute nothing to committed funds; only `APPROVED` authorizations do.

Two aggregate views are derived from the same ledger and must not be conflated. The **total obligation** (budget-exposure / encumbrance view) is `funds_committed_cents` plus `funds_paid_cents` — money still owed plus money already spent. The **total expenditure** (cash-out / RSA-911 view) is `funds_paid_cents` alone; it excludes still-committed obligations and therefore diverges from total obligation whenever any committed balance remains.

### 2.9. Order-of-Selection Slots

Funded service capacity is rationed through priority categories. A category's `slots_used` is the count of cases assigned to that category (`priority_category_id`) whose status is one of `PLAN_DEVELOPMENT`, `SERVICES_ACTIVE`, or `EMPLOYED` — the states in which a consumer actively holds a funded slot. Waitlisted cases and cases in any terminal state hold no slot and are excluded from the count. A category's `available_slots` is its `slot_capacity` minus `slots_used`, and is never allowed to fall below zero: when no slots remain, a new reservation is blocked and the eligible case is waitlisted instead. Reserving a slot increments `slots_used` and decrements `available_slots`; releasing one does the reverse; either change increments the category's `version`.

### 2.10. Request Validation and Evaluation Order

When several checks could reject a single request, they are evaluated in a fixed priority order so that the returned `error_id` is deterministic. Authentication is checked first (`ERR_UNAUTHENTICATED`), then authorization including ownership (`ERR_FORBIDDEN`), then existence of every referenced id (`ERR_NOT_FOUND`), then body well-formedness (`ERR_VALIDATION`, HTTP 422 — required fields present, correct types, enums in range, dates parseable, and `service_period_start` not later than `service_period_end`). Positive-amount checks on monetary inputs (`ERR_AMOUNT_NOT_POSITIVE`, HTTP 422) and the eligibility category-existence check (`ERR_CATEGORY_NOT_FOUND`, HTTP 422) follow. Only then are operation-specific business rules evaluated, in the order laid out for each workflow in §3 — beginning, where applicable, with the optimistic-concurrency check (`ERR_STALE_VERSION`) ahead of the state-eligibility check (`ERR_INVALID_STATE`, HTTP 409).

### 2.11. The Logical Clock

The system reads time from a logical clock rather than the host wall clock. Before any override, the clock reads exactly `2026-05-01T00:00:00Z` and never falls back to wall-clock time. Any role may advance it by supplying a `to_iso8601` instant. The clock governs the instant a case is waitlisted (`waitlisted_at`), the date a stabilization window begins (`stabilization_start_date`), the running `days_stable` count, and the review-date window used to verify wages.

## 3. Business Logic & Workflows

### 3.1. Registration and Configuration

Before cases can flow, a `VRAdmin` populates the operational directory. Registering a counselor supplies the counselor's `name`, `email`, and field-office `unit`. Registering a supervisor supplies a `name` and `email`. Onboarding a provider supplies its `name`, its list of approved `service_categories` (a subset of `TRAINING`, `ASSISTIVE_TECH`, `ASSESSMENT`, and `SUPPORTED_EMPLOYMENT`), and its `max_concurrent_authorizations` (the ceiling on how many of the provider's `APPROVED` authorizations may have overlapping service periods at once). A provider's `status` may be supplied at onboarding as `ACTIVE` or `SUSPENDED`; when omitted it defaults to `ACTIVE`. A provider's ledger fields `pending_disbursement_cents` and `ledger_paid_cents` are initialized to zero and thereafter track, respectively, the sum of `amount_cents` over the provider's `PENDING` payments and the sum over its `ISSUED` payments.

A `VRAdmin` also creates the order-of-selection priority categories, one per rank. A category is created with its `rank`, its `label`, its `slot_capacity`, and optionally its `status`; when omitted `status` defaults to `OPEN`. Rank 1 is the `MSD` category (most significant disability, highest priority), rank 2 is `SD`, and rank 3 is `NSD`. At creation `slots_used` is zero and `available_slots` equals `slot_capacity`. A `VRAdmin` may later adjust a category by supplying a new `status` and/or a new `slot_capacity`; the system recomputes `available_slots` and increments the category's `version`. Moving a category from `OPEN` to `CLOSED` means newly eligible cases in that rank are waitlisted rather than served; moving it back from `CLOSED` to `OPEN` makes waitlisted cases eligible for promotion.

### 3.2. Referral, Application, and Eligibility

A `Counselor` opens a case by recording a referral, which supplies the `consumer_full_name`, the consumer's `consumer_dob` (YYYY-MM-DD), the `disability_type` (one of `PHYSICAL`, `COGNITIVE`, `PSYCHIATRIC`, or `SENSORY`), a `referral_source` label, the consumer's `monthly_income_cents`, and optionally `budget_allocated_cents` (defaulting to 0). The new case begins in `REFERRED`, its `counselor_id` is set from `X-User-ID`, its fund fields are initialized, and its `priority_category_id`, `disability_significance`, `waitlisted_at`, `closure_type`, and `closure_reason` are all null. Only the owning counselor may act on the case thereafter; a non-owner is rejected with `ERR_FORBIDDEN`.

Recording the signed application advances the case from `REFERRED` to `APPLICATION` and increments the case's `version`.

The eligibility determination is taken while the case is in `APPLICATION`, and the request supplies a `decision` and the `disability_significance` (`MSD`, `SD`, or `NSD`). An `INELIGIBLE` decision records the `disability_significance` and moves the case to the terminal `INELIGIBLE` state. An `ELIGIBLE` decision first locates the priority category whose `rank` matches the rank of the reported `disability_significance` (`MSD`→1, `SD`→2, `NSD`→3); if no such category exists the determination is rejected with `ERR_CATEGORY_NOT_FOUND`. The located category is assigned as the case's `priority_category_id` and the `disability_significance` is recorded. If that category is `OPEN` and has at least one available slot, the case advances to `PLAN_DEVELOPMENT` and a slot is reserved (the category's `slots_used` rises by one, `available_slots` falls by one, and the category's `version` increments). If instead the category is `CLOSED` or has zero available slots, the case moves to `WAITLISTED`, its `waitlisted_at` is stamped with the current logical clock — normalized to an ISO 8601 UTC timestamp with three fractional digits regardless of the precision the clock was set with — and no slot is reserved. Every eligibility outcome increments the case's `version`.

### 3.3. Promoting from the Waitlist

When a slot frees up in a category, a `VRAdmin` promotes the next waitlisted case. The selector first confirms the category has an available slot, rejecting with `ERR_NO_SLOT_AVAILABLE` if none remains; it then confirms at least one `WAITLISTED` case exists in the category, rejecting with `ERR_NO_WAITLISTED_CASE` if the pool is empty. Among the category's waitlisted cases, it chooses the one with the earliest `waitlisted_at`, breaking ties by the earliest `created_at` (never by `id`). The chosen case moves from `WAITLISTED` to `PLAN_DEVELOPMENT`, its `waitlisted_at` is cleared, a slot is reserved (the category's `slots_used` rises by one, `available_slots` falls by one, `version` increments), and the case's `version` increments.

### 3.4. Authoring the Individualized Plan for Employment

Once a case reaches `PLAN_DEVELOPMENT`, its `Counselor` drafts an IPE by supplying the `case_id`, an `employment_goal` (an SOC occupation title or code), and a `goal_wage_target_cents` target weekly wage. The IPE is created in `DRAFT`. A case may hold only one active IPE at a time; if the case already has an IPE in `DRAFT`, `SUBMITTED`, `APPROVED`, or `AMENDING`, creating another is rejected with `ERR_ACTIVE_IPE_EXISTS`.

Submitting a `DRAFT` IPE is permitted only while the IPE is in `DRAFT` and its case is in `PLAN_DEVELOPMENT`; it advances the IPE to `SUBMITTED`. A `Supervisor` reviews a `SUBMITTED` IPE and either returns it or approves it. Returning it moves it back to `DRAFT` for revision. Approving a `SUBMITTED` IPE moves it to `APPROVED`, records the approving supervisor in `approved_by_supervisor_id`, pins `approved_plan_version` to the IPE's `version` after that transition's increment, and — as a cross-entity effect on this first approval — advances the case from `PLAN_DEVELOPMENT` to `SERVICES_ACTIVE`, incrementing the case's `version`. Each of these IPE transitions increments the IPE's `version`.

An approved plan may be revised through an amendment loop. A `Counselor` opens an `APPROVED` IPE for amendment, moving it to `AMENDING`. A `Supervisor` then re-approves, moving `AMENDING` back to `APPROVED`, again recording `approved_by_supervisor_id` and re-pinning `approved_plan_version` to the post-increment `version`; because the case is already `SERVICES_ACTIVE` or later, its status is left unchanged. This `APPROVED → AMENDING → APPROVED` cycle may repeat.

### 3.5. Requesting Service Authorizations and Cost Share

With an IPE in hand, a `Counselor` requests a service authorization, supplying the `case_id`, the `ipe_id`, the `provider_id`, the `service_category` (`TRAINING`, `ASSISTIVE_TECH`, `ASSESSMENT`, or `SUPPORTED_EMPLOYMENT`), the gross `authorized_amount_cents`, the `service_period_start` and `service_period_end` dates (end not earlier than start), and optionally a `comparable_benefit_cents` offset (defaulting to 0). The authorization is created in `REQUESTED`, and `requested_by_counselor_id` is recorded from `X-User-ID`. The gross `authorized_amount_cents` must be greater than zero, else the request is rejected with `ERR_AMOUNT_NOT_POSITIVE`.

At creation the system computes the consumer's participation and the agency's obligation. First it derives the net cost as the greater of zero and `authorized_amount_cents` minus `comparable_benefit_cents`, applying the comparable-benefits offset before any cost share. It then selects a participation rate from the case's `monthly_income_cents`: income at or below 200,000 cents (that is, 2,000 dollars per month) carries a rate of 0%; income above that but at or below 400,000 cents (4,000 dollars) carries 10%; income above 400,000 cents carries 20%. The `consumer_share_cents` is the lesser of the net cost and the net cost multiplied by the rate rounded half up to whole cents. The `agency_share_cents` is the net cost minus `consumer_share_cents`.

An authorization may be withdrawn by its `Counselor` while still in `REQUESTED`, moving it to `CANCELLED`; because nothing was committed at `REQUESTED`, no funds are released. Authorization cancellation is also reachable from `APPROVED`, with the fund and payment consequences described in §3.6.

### 3.6. Approving Authorizations, Delivery, and Cancellation Cascades

A `Supervisor` approves a `REQUESTED` authorization. This is the system's most heavily guarded write, evaluated in this order after authentication, ownership, existence, and body checks: the optimistic-concurrency check on `expected_case_version` (mismatch → `ERR_STALE_VERSION`); the state check that the authorization is `REQUESTED` (else `ERR_INVALID_STATE`); the requirement that the case's most recent IPE is `APPROVED` (else `ERR_IPE_NOT_APPROVED`); the provider-eligibility check that the provider's `status` is `ACTIVE` and the authorization's `service_category` is among the provider's `service_categories` (else `ERR_PROVIDER_INELIGIBLE`); the period-overlap check; the provider-capacity check; and finally the budget check.

The period-overlap check rejects approval with `ERR_AUTHORIZATION_PERIOD_OVERLAP` when another `APPROVED` authorization on the **same case and same `service_category`** has a service period that overlaps the requested `[service_period_start, service_period_end]` treated as a closed interval, so that merely touching endpoints conflict. The provider-capacity check rejects with `ERR_PROVIDER_CAPACITY_EXCEEDED` when approving would cause the number of the provider's overlapping `APPROVED` authorizations — measured on the half-open interval `[start, end)`, so touching endpoints do **not** conflict — to exceed the provider's `max_concurrent_authorizations`. The budget check rejects with `ERR_BUDGET_EXCEEDED` when the authorization's `agency_share_cents` exceeds the case's current `funds_available_cents`.

On successful approval the authorization moves to `APPROVED`, `approved_by_supervisor_id` is recorded, and the agency obligation is committed: the case's `funds_committed_cents` rises by `agency_share_cents` and its `funds_available_cents` falls by the same amount, incrementing the case's `version`.

The provider reports delivery on its own `APPROVED` authorization (ownership compares `provider_id` to `X-User-ID`, else `ERR_FORBIDDEN`), moving it to `COMPLETED`; the committed funds remain obligated until paid. A non-`APPROVED` authorization rejects this with `ERR_INVALID_STATE`.

Cancelling an `APPROVED` authorization moves it to `CANCELLED` and unwinds the obligation in a cascade. The still-owed remainder — `agency_share_cents` minus `amount_paid_cents` — is released: the case's `funds_committed_cents` falls by that remainder and its `funds_available_cents` rises by it, incrementing the case's `version`. Every `PENDING` payment on the cancelled authorization is then voided, and each such void in turn decrements the provider's `pending_disbursement_cents` and increments the provider's `version`. The authorization's own `version` increments.

### 3.7. Paying Providers

A `FiscalOfficer` creates a payment against an authorization by supplying the `authorization_id` and an `amount_cents` greater than zero (else `ERR_AMOUNT_NOT_POSITIVE`). The payment is created in `PENDING`, its `provider_id` is copied from the authorization, and the provider's `pending_disbursement_cents` rises by `amount_cents`. A payment amount may not exceed the authorization's remaining obligation — `agency_share_cents` minus `amount_paid_cents` — or it is rejected with `ERR_PAYMENT_EXCEEDS_AUTHORIZATION`.

Issuing a `PENDING` payment is permitted only when the underlying authorization is in `APPROVED` or `COMPLETED` status. Issuing moves the payment to `ISSUED`, records `issued_by`, and computes the reimbursement split stored on the payment: `federal_share_cents` is `amount_cents` multiplied by the federal match rate of 0.787, rounded half up to whole cents, and `state_share_cents` is `amount_cents` minus `federal_share_cents`. Issuing also moves money on the case ledger — `funds_committed_cents` falls by `amount_cents` while `funds_paid_cents` rises by `amount_cents`, incrementing the case's `version` — updates the provider ledger — `pending_disbursement_cents` falls by `amount_cents` while `ledger_paid_cents` rises by `amount_cents`, incrementing the provider's `version` — and raises the authorization's `amount_paid_cents` by `amount_cents`. The payment's `version` increments.

A payment may be voided by a `FiscalOfficer`. Voiding a `PENDING` payment moves it to `VOIDED` and decrements the provider's `pending_disbursement_cents` by `amount_cents`, incrementing the provider's `version`. Voiding an already-`ISSUED` payment is a compensating reversal: the payment moves to `VOIDED`, the case's `funds_paid_cents` falls by `amount_cents` while `funds_committed_cents` rises by `amount_cents` (incrementing the case's `version`), the provider's `ledger_paid_cents` falls by `amount_cents` (incrementing the provider's `version`), and the authorization's `amount_paid_cents` falls by `amount_cents`. Voiding a payment in any other state is rejected with `ERR_INVALID_STATE`. Each void increments the payment's `version`.

The federal and state expenditure totals used for reporting are computed with a pinned rounding order: the already-rounded `federal_share_cents` of each `ISSUED` payment are summed to give the case's total federal expenditure, and likewise the `state_share_cents` are summed for the total state expenditure. These totals are the sums of the per-payment rounded shares, not the result of applying the match rate to a grand total — round each line first, then add.

### 3.8. Placement and the 90-Day Stabilization

Once a case is `SERVICES_ACTIVE` and its IPE is `APPROVED`, its `Counselor` records a job placement by supplying the `case_id`, the `ipe_id`, the `employer_name`, the `placement_date`, the projected `weekly_wage_cents`, the scheduled `hours_per_week`, and the `employment_type` (`COMPETITIVE_INTEGRATED`, `SUPPORTED`, or `SELF_EMPLOYMENT`). The placement is created in `PLACED`, and the case advances from `SERVICES_ACTIVE` to `EMPLOYED`, incrementing the case's `version`. If the case's IPE is not `APPROVED`, placement is rejected with `ERR_IPE_NOT_APPROVED`.

Beginning stabilization moves the placement from `PLACED` to `STABILIZING`, but only when the `employment_type` is `COMPETITIVE_INTEGRATED` or `SUPPORTED`; a `SELF_EMPLOYMENT` placement is rejected with `ERR_PLACEMENT_TYPE_INVALID`. On this transition the placement's `stabilization_start_date` is set to the current logical-clock date, and the running `days_stable` counter — the whole number of days from `stabilization_start_date` to the current logical clock, and zero whenever the placement is not stabilizing — begins to accrue.

A job may be lost mid-window: reporting a loss moves a `STABILIZING` placement to `DESTABILIZED`. Resuming after re-employment moves `DESTABILIZED` back to `STABILIZING` and **resets** `stabilization_start_date` to the current logical-clock date, restarting the 90-day count from zero. This `STABILIZING → DESTABILIZED → STABILIZING` loop may repeat. Any of these placement transitions attempted from the wrong state is rejected with `ERR_INVALID_STATE`.

Throughout stabilization a `Counselor` appends progress reviews, each supplying the `placement_id`, a `review_date`, the `reported_weekly_wage_cents` observed at that review, and an optional `status_ok` flag (defaulting to true) indicating the placement was satisfactory at that review. Progress reviews are immutable events.

Verifying stability is permitted only on a `STABILIZING` placement (else `ERR_INVALID_STATE`) whose `days_stable` is at least 90 (else `ERR_STABILIZATION_NOT_MET`). On success the placement moves to `STABLE` and its `verified_avg_weekly_wage_cents` is computed. That figure averages the progress reviews in the current window: the reviews for this placement whose `review_date` falls on or after the placement's current `stabilization_start_date` and on or before the current logical-clock date. Reviews dated before the current `stabilization_start_date` — for example those recorded before a resume reset the window — are excluded. If the window contains no reviews the verified average is null; otherwise it is the sum of `reported_weekly_wage_cents` over the window divided by the number of reviews in the window, rounded half up to whole cents. This verified average is the closure-time counterpart to the forward-looking projection captured in `weekly_wage_cents` at hire, and diverges from it whenever reported wages differ from the hire estimate.

Reaching `STABLE` closes the case as a successful outcome: the case moves from `EMPLOYED` to `CLOSED_REHABILITATED` with `closure_type` set to `REHABILITATED`. That closure releases the case's slot (the category's `slots_used` falls by one, `available_slots` rises by one, `version` increments), cancels every service authorization for the case that is still in `REQUESTED` or `APPROVED` (each such cancellation releasing its committed funds and voiding its `PENDING` payments as described in §3.6), and closes any IPE in `APPROVED` or `AMENDING` status by moving it to `CLOSED`. The case's `version` increments.

### 3.9. Closing a Case for Other Reasons

At any point before a terminal state, a `Counselor` who owns a case may close it for a non-rehabilitated reason, supplying a `closure_reason`. This is valid from `REFERRED`, `APPLICATION`, `WAITLISTED`, `PLAN_DEVELOPMENT`, `SERVICES_ACTIVE`, or `EMPLOYED`; the case moves to `CLOSED_OTHER` with `closure_type` set to `OTHER` and the `closure_reason` recorded, and the case's `version` increments. A non-owner is rejected with `ERR_FORBIDDEN`.

The side effects depend on how far the case had progressed. A `WAITLISTED` case (and likewise a `REFERRED` or `APPLICATION` case) holds no slot, so nothing is released. A `PLAN_DEVELOPMENT` case releases its slot. A `SERVICES_ACTIVE` case releases its slot, cancels every service authorization in `REQUESTED` or `APPROVED` (each cancellation releasing committed funds and voiding its `PENDING` payments), and closes any IPE in `DRAFT`, `SUBMITTED`, `APPROVED`, or `AMENDING`. An `EMPLOYED` case releases its slot, cancels every `REQUESTED` or `APPROVED` authorization with the same fund-release and payment-void cascade, closes any non-`CLOSED` IPE, and closes any non-terminal placement.

### 3.10. The RSA-911 Record

For federal reporting, a computed RSA-911 record can be retrieved for any case by a `VRAdmin`, `Counselor`, or `Supervisor`. The record echoes the `case_id`, the `disability_type`, and the `disability_significance`, and reports an `employment_outcome` reflecting the closure (rehabilitated when the case closed as `CLOSED_REHABILITATED`, otherwise other), a `competitive_integrated` boolean that is true when the case's placement `employment_type` is `COMPETITIVE_INTEGRATED`, and the `verified_weekly_wage_cents` drawn from the placement's verified average weekly wage. It also reports the `total_federal_expenditure_cents` and `total_state_expenditure_cents` computed as the per-payment-then-summed federal and state shares of the case's `ISSUED` payments, along with the `closure_type` and `closure_reason`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource, drive a state transition, or read data return `200 OK`. Every request and response body follows the envelope in §2.2; the request fields and side effects for each operation are specified in the §3 narratives above.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/vr/counselors` | Register a VR counselor | VRAdmin |
| POST | `/vr/supervisors` | Register a VR supervisor | VRAdmin |
| POST | `/vr/providers` | Onboard a service provider / vendor | VRAdmin |
| GET | `/vr/providers/{provider_id}` | Get a provider (including ledger fields) | VRAdmin, Counselor, Supervisor, FiscalOfficer, Provider |
| POST | `/vr/priority-categories` | Create an order-of-selection priority category | VRAdmin |
| GET | `/vr/priority-categories/{category_id}` | Get a priority category (with slot counts) | VRAdmin, Counselor, Supervisor, FiscalOfficer, Provider |
| GET | `/vr/priority-categories` | List priority categories | VRAdmin, Counselor, Supervisor, FiscalOfficer, Provider |
| PATCH | `/vr/priority-categories/{category_id}` | Open/close a category or adjust slot capacity | VRAdmin |
| POST | `/vr/priority-categories/{category_id}/promote-next` | Promote the next waitlisted case into PLAN_DEVELOPMENT | VRAdmin |
| POST | `/vr/_clock/set_current_utc` | Test-driving: set the logical clock | VRAdmin, Counselor, Supervisor, FiscalOfficer, Provider |
| POST | `/vr/cases` | Create a referral (opens a Case in REFERRED) | Counselor |
| GET | `/vr/cases/{case_id}` | Get a case (with fund fields) | VRAdmin, Counselor, Supervisor, FiscalOfficer, Provider |
| GET | `/vr/cases` | List cases (filterable) | VRAdmin, Counselor, Supervisor, FiscalOfficer, Provider |
| POST | `/vr/cases/{case_id}/application` | Record signed application (REFERRED → APPLICATION) | Counselor |
| POST | `/vr/cases/{case_id}/eligibility` | Record eligibility determination | Counselor |
| POST | `/vr/cases/{case_id}/close` | Close a case for a non-rehabilitated reason | Counselor |
| GET | `/vr/cases/{case_id}/rsa911` | Computed RSA-911 closure/expenditure record | VRAdmin, Counselor, Supervisor |
| POST | `/vr/ipes` | Create an IPE draft for a case in PLAN_DEVELOPMENT | Counselor |
| GET | `/vr/ipes/{ipe_id}` | Get an IPE | VRAdmin, Counselor, Supervisor, FiscalOfficer, Provider |
| GET | `/vr/ipes` | List IPEs | VRAdmin, Counselor, Supervisor, FiscalOfficer, Provider |
| POST | `/vr/ipes/{ipe_id}/submit` | Submit IPE for approval (DRAFT → SUBMITTED) | Counselor |
| POST | `/vr/ipes/{ipe_id}/approve` | Approve an IPE (SUBMITTED or AMENDING → APPROVED) | Supervisor |
| POST | `/vr/ipes/{ipe_id}/return` | Return a submitted IPE for revision (SUBMITTED → DRAFT) | Supervisor |
| POST | `/vr/ipes/{ipe_id}/amend` | Open an approved IPE for amendment (APPROVED → AMENDING) | Counselor |
| POST | `/vr/authorizations` | Request a service authorization; computes cost share | Counselor |
| GET | `/vr/authorizations/{authorization_id}` | Get a service authorization | VRAdmin, Counselor, Supervisor, FiscalOfficer, Provider |
| GET | `/vr/authorizations` | List authorizations | VRAdmin, Counselor, Supervisor, FiscalOfficer, Provider |
| POST | `/vr/authorizations/{authorization_id}/approve` | Approve an authorization; commits funds (OCC-guarded) | Supervisor |
| POST | `/vr/authorizations/{authorization_id}/complete` | Provider reports service delivery (APPROVED → COMPLETED) | Provider |
| POST | `/vr/authorizations/{authorization_id}/cancel` | Cancel an authorization; releases funds, voids pending payments | Counselor |
| POST | `/vr/payments` | Create a pending payment against an authorization | FiscalOfficer |
| GET | `/vr/payments/{payment_id}` | Get a payment | VRAdmin, Counselor, Supervisor, FiscalOfficer, Provider |
| GET | `/vr/payments` | List payments | VRAdmin, Counselor, Supervisor, FiscalOfficer, Provider |
| POST | `/vr/payments/{payment_id}/issue` | Issue a pending payment (PENDING → ISSUED) | FiscalOfficer |
| POST | `/vr/payments/{payment_id}/void` | Void a payment (PENDING or ISSUED → VOIDED) | FiscalOfficer |
| POST | `/vr/placements` | Record a job placement (case SERVICES_ACTIVE → EMPLOYED) | Counselor |
| GET | `/vr/placements/{placement_id}` | Get a placement | VRAdmin, Counselor, Supervisor, FiscalOfficer, Provider |
| GET | `/vr/placements` | List placements | VRAdmin, Counselor, Supervisor, FiscalOfficer, Provider |
| POST | `/vr/placements/{placement_id}/begin-stabilization` | Begin the 90-day stabilization window (PLACED → STABILIZING) | Counselor |
| POST | `/vr/placements/{placement_id}/report-loss` | Report job loss during stabilization (STABILIZING → DESTABILIZED) | Counselor |
| POST | `/vr/placements/{placement_id}/resume` | Resume stabilization (DESTABILIZED → STABILIZING); resets the clock | Counselor |
| POST | `/vr/placements/{placement_id}/verify-stability` | Verify 90-day stabilization (STABILIZING → STABLE); auto-closes case | Counselor |
| POST | `/vr/progress-reviews` | Append a progress review to a placement | Counselor |
| GET | `/vr/placements/{id}/progress-reviews` | List progress reviews for a placement | VRAdmin, Counselor, Supervisor, FiscalOfficer, Provider |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_VALIDATION | 422 |
| ERR_AMOUNT_NOT_POSITIVE | 422 |
| ERR_CATEGORY_NOT_FOUND | 422 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_STATE | 409 |
| ERR_ACTIVE_IPE_EXISTS | 409 |
| ERR_IPE_NOT_APPROVED | 409 |
| ERR_PROVIDER_INELIGIBLE | 422 |
| ERR_AUTHORIZATION_PERIOD_OVERLAP | 409 |
| ERR_PROVIDER_CAPACITY_EXCEEDED | 409 |
| ERR_BUDGET_EXCEEDED | 409 |
| ERR_PAYMENT_EXCEEDS_AUTHORIZATION | 409 |
| ERR_STABILIZATION_NOT_MET | 409 |
| ERR_PLACEMENT_TYPE_INVALID | 409 |
| ERR_NO_SLOT_AVAILABLE | 409 |
| ERR_NO_WAITLISTED_CASE | 409 |
