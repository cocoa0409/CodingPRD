# Home Warranty Service API — Product Requirements Document

## 1. Introduction

The Home Warranty Service API governs the back-office machinery of a residential appliance-warranty business: the catalog of plan offerings a homeowner can buy into, the contracts those homeowners hold, the appliances each contract covers, and the field-service workflow that runs whenever something breaks. The same system that prices a plan at sign-up must also price a single repair after the fact — and the second price depends, fact by fact, on the first.

Two business pressures dominate the design. First, money: every repair splits its cost between the warranty and the homeowner along a contract-defined cap, and a recurring Trip Charge (Service Fee) sits on top of that split unless the technician is making a guaranteed return visit. Second, time: warranties run on annual cycles, with auto-emitted reminders thirty days before expiry, customer-initiated renewal, and a pricing penalty for waiting too long to renew. The system must hold all of this internally consistent across many concurrent actors — homeowners filing claims, dispatchers scheduling technicians, technicians completing visits, and the platform itself ticking the clock forward — while remaining auditable down to the cent.

This document specifies the structure of the API, the lifecycle and business rules that bind its entities together, and the contracts an implementation must satisfy.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which declares the role under which the action is performed. The system recognizes five roles: `Anonymous`, `Customer`, `Dispatcher`, `Technician`, and `PlatformAdmin`. A request that omits either header on a protected endpoint is rejected with `ERR_UNAUTHENTICATED`. A request whose `X-User-Role` is not authorized to perform the requested operation is rejected with `ERR_FORBIDDEN`. Customer registration is the sole endpoint open to `Anonymous` callers and does not require these headers.

The interpretation of `X-User-ID` depends on the role. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any contract, covered item, claim, or renewal reminder that references a `Customer` compare the resource's `customer_id` (directly on a `Contract`, or transitively through `contract_id` for covered items, claims, and reminders) to `X-User-ID`. When `X-User-Role` is `Anonymous`, `Dispatcher`, `Technician`, or `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. The `Dispatcher`, `Technician`, and `PlatformAdmin` operator identities are recorded only insofar as the role's operations transition resources; they are not back-pointers to customer rows. The `technician_id` carried on a `Dispatch` is the value the assigning dispatcher chose and likewise has no `Technician`-entity row behind it.

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

All list endpoints accept two query parameters that control the page window: `limit`, which sets the maximum number of items in the response, and `offset`, which sets the number of leading items to skip. The default `limit` is 10, the minimum is 1, and the maximum is 100; the default `offset` is 0 with no upper bound beyond the underlying row count. Unless the endpoint section says otherwise, list results are sorted by `created_at` ascending. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object.

### 2.4. Common Resource Properties

Each first-class resource carries a system-issued `id` formatted as a UUID with no type prefix, and a `created_at` timestamp captured when the row is first written. Timestamps are emitted as ISO 8601 UTC strings with three fractional digits (e.g., `2025-05-24T10:30:00.123Z`).

Mutable resources additionally carry an `updated_at` timestamp, which the server refreshes on every mutation to the row, and a `version` integer that begins at 1 on creation and increments by one on every server-side mutation — including auto-fired transitions driven by the clock-tick capability described below. The `ContractPackage`, `Customer`, `Contract`, `CoveredItem`, `ClaimTicket`, and `Dispatch` resources all carry `updated_at` and `version`. The `RenewalReminder` resource is immutable once written; it carries `id` and `created_at` only and exposes neither `updated_at` nor `version`.

Recomputation of derived fields such as `claims_in_period_count`, `total_paid_out_cents`, `last_dispatch_completed_utc`, and `last_dispatch_id` counts as a mutation: it bumps `updated_at` and increments `version` on the affected row.

### 2.5. Nested Resource Retrieval and Existence Validation

When an endpoint path contains multiple identifiers — for example, `renewal-reminders` listed under a parent contract — existence is validated strictly left-to-right against the URL. The outermost path identifier is resolved first; if it does not point to a row, the request is rejected immediately with `ERR_NOT_FOUND`, before any inner identifier or payload field is examined. The same `ERR_NOT_FOUND` is returned when a foreign-key field in a request body — `customer_id`, `package_id`, `contract_id`, `covered_item_id`, or `claim_id` — does not resolve to an existing row at the moment the request is processed.

Cross-aggregate referential integrity is enforced one step beyond mere existence: when a claim is filed, the supplied `covered_item_id` must reference a `CoveredItem` whose `contract_id` matches the claim's `contract_id`. A mismatch is rejected with `ERR_ITEM_NOT_ON_CONTRACT`.

### 2.6. Validation Priority

Multiple checks may apply to the same endpoint, and they are evaluated in a fixed order so that the rejection error a caller observes is deterministic. The system first verifies that authentication headers are present (`ERR_UNAUTHENTICATED`), then that the caller's role is authorized (`ERR_FORBIDDEN`), then that path-templated identifiers resolve to rows in left-to-right order (`ERR_NOT_FOUND` against the path), then that foreign-key identifiers in the payload resolve to rows (`ERR_NOT_FOUND` against the payload), then cross-aggregate consistency (`ERR_ITEM_NOT_ON_CONTRACT`), then state-machine eligibility for the requested transition (`ERR_INVALID_STATE`), then the pre-existing exclusion against the covered item (`ERR_PRE_EXISTING_EXCLUDED`), then the coverage-window check for new claims (`ERR_OUT_OF_COVERAGE`), then the per-package covered-item capacity (`ERR_ITEM_LIMIT_EXCEEDED`), then that a dispatch is not scheduled in the past (`ERR_SCHEDULED_IN_PAST`), then the technician double-booking guard (`ERR_TECHNICIAN_DOUBLE_BOOKED`), then the rule that an active contract with open claims cannot be cancelled (`ERR_OPEN_CLAIMS_BLOCK_CANCEL`), then the optimistic-concurrency check on renewal (`ERR_STALE_VERSION`), and finally the request-body shape, type, and bound checks (`ERR_INVALID_REQUEST`). This ordering means, for example, that a renewal request with both a stale version and a malformed body surfaces `ERR_STALE_VERSION` rather than `ERR_INVALID_REQUEST`.

### 2.7. Optimistic Concurrency on Renewal

Renewing a contract is the one operation where the server must protect against the client acting on a stale view of the parent row. The renewal endpoint at the contract path requires `expected_contract_version` as a non-optional input field carrying the client's last observed `version` of the target `Contract`. If that value does not equal the contract's current `version` at the moment the request is processed — typically because a background `_clock/tick` advanced the contract's lifecycle since the client last read it — the renewal is rejected with `ERR_STALE_VERSION` and HTTP status 412. No other endpoint in the system accepts a `expected_contract_version`-style field, and no other endpoint applies an OCC stale-version check.

### 2.8. Monetary Precision and Rounding

All monetary values in this system — premiums, caps, fees, repair costs, and co-pays — are stored and returned as integer cents. Decimal multiplications that arise during pricing (the co-pay share above the cap, the early-renewal discount, the per-item surcharge) are computed and then rounded to the nearest cent using **round half up**. No second rounding is applied after addition. The exact ordering of round-then-multiply versus multiply-then-round is fixed per calculation and is called out in §3 where each calculation is described, because for the per-item renewal surcharge the two orderings can disagree by up to several cents.

### 2.9. Cascading Side Effects and Aggregate Recomputation

A handful of mutations have effects that reach beyond the row the caller named, and those effects must be applied atomically with the primary mutation:

- Completing a dispatch stamps the dispatch's `completed_utc` to the current clock and also writes back to the parent covered item: the item's `last_dispatch_completed_utc` is set to the same instant, and its `last_dispatch_id` is set to the completed dispatch's `id`. Both writes count as mutations on the covered item — its `updated_at` advances and its `version` increments.
- Resolving a claim recomputes the parent contract's `total_paid_out_cents` and `claims_in_period_count` aggregates and, separately, refreshes the contract's `updated_at` and bumps `version`.
- Rejecting a claim recomputes the parent contract's `claims_in_period_count`.
- The clock-tick capability that auto-transitions contracts (active to expiring-soon, active or expiring-soon to expired) bumps the contract's `version` on each fired transition; when an active contract enters the expiring-soon state it also writes a `RenewalReminder` row and stamps `renewal_reminder_sent_at` on the contract.

A claim that has been resolved contributes to `total_paid_out_cents` the difference between its final `repair_cost_cents` and its `final_copay_cents`, which represents the portion the warranty paid. A claim that has been rejected contributes nothing to `total_paid_out_cents` but is counted toward `claims_in_period_count`.

### 2.10. Coverage Window and the In-Period Aggregate

Every claim and every aggregated dollar is bounded by the contract's coverage window, which is the half-open interval running from `coverage_start_utc` (inclusive) to `coverage_end_utc` (exclusive). The window is exactly 365 days wide, opened by the activation transition and closed at the moment `coverage_end_utc` is reached. Claims may only be filed while the server clock falls inside this window and the contract is in `ACTIVE` or `EXPIRING_SOON`; an attempt to file outside the window or against a contract in any other status is rejected with `ERR_OUT_OF_COVERAGE`.

The contract's `claims_in_period_count` counts every `ClaimTicket` on the contract whose `status` is any of `SUBMITTED`, `ASSESSED`, `DISPATCHED`, `RESOLVED`, or `REJECTED` and whose `created_at` falls inside the same half-open window. The contract's `total_paid_out_cents` is the sum, across `RESOLVED` claims in the same window, of each claim's final `repair_cost_cents` minus its `final_copay_cents`. Both aggregates are recomputed deterministically on every claim transition that affects the count or sum: resolving (which updates both), rejecting (which updates the count), and the initial submission (which increments the count). The recomputation iterates qualifying claims in `created_at` ascending order; because addition commutes, the resulting sum is order-invariant.

## 3. Business Logic & Workflows

### 3.1. Plan Catalog and Customer Onboarding

The catalog of warranty offerings is maintained by `PlatformAdmin` operators as a collection of **Contract Packages**. Each package is identified by a public `code` — an uppercase A–Z string between 3 and 16 characters (matching `^[A-Z]{3,16}$`), unique across the catalog (a duplicate `code` is rejected with `ERR_INVALID_REQUEST`) — and a human-readable `name`. The package carries the pricing parameters that drive everything downstream: `annual_premium_cents` is the yearly charge applied at activation or renewal; `service_fee_cents` is the Trip Charge billed per dispatch; `copay_cap_cents` is the per-claim repair-cost cap below which the warranty pays the full repair; `copay_share_pct` is the homeowner's share of any repair cost above that cap, stored as a decimal between 0 and 1 inclusive; `return_visit_window_days` is the size, in days, of the free-return-visit guarantee window after a completed dispatch; and `max_covered_items` is the ceiling on how many appliances a contract on this package may register. All numeric parameters must be non-negative integers, except `copay_share_pct` which is a decimal in the closed interval from 0 to 1 and `max_covered_items` which must be at least 1.

A package's lifecycle is governed by its `status`, which begins at `ACTIVE` on creation and may be moved to `RETIRED` by a `PlatformAdmin`. Retirement is only permitted from `ACTIVE`; a retire request against a package already in `RETIRED` is rejected with `ERR_INVALID_STATE`. Retirement does not invalidate existing contracts, but it blocks new contracts from being created against the package and blocks renewals that try to switch to the retired package; either attempt is rejected with `ERR_PACKAGE_RETIRED`.

Homeowners enter the system by registering as a **Customer** through the open registration endpoint, the one operation a caller may perform without authentication headers (any auth headers a caller does supply on `POST /customers` are simply ignored). Registration takes the customer's `email` (which serves as their unique login identifier and must be a valid email matching a `local@domain.tld`-shape pattern; a duplicate `email` is rejected with `ERR_INVALID_REQUEST`), `full_name` (non-empty string), and `home_address` (the service address technicians will visit; non-empty string).

### 3.2. Contract Activation and the Annual Cycle

A `Customer` (or a `PlatformAdmin` acting on their behalf) opens a contract by submitting a `customer_id` and a `package_id`. When the caller's role is `Customer`, the supplied `customer_id` must equal the caller's `X-User-ID`; otherwise the request is rejected with `ERR_FORBIDDEN`. The contract is created in `PENDING_PAYMENT` with `version` set to 1, with no coverage window yet, and with `annual_premium_due_cents` initialized to zero — it has not yet been pinned. The covered-item slots, the claim history, and both aggregates (`claims_in_period_count` and `total_paid_out_cents`) all start empty or at zero.

The contract is brought to life through an activation step exercised exclusively by `PlatformAdmin`, transitioning `PENDING_PAYMENT → ACTIVE`. Activation is only permitted from `PENDING_PAYMENT`; an activate request against a contract already in `ACTIVE`, `EXPIRING_SOON`, `EXPIRED`, `CANCELLED`, or `RENEWED` is rejected with `ERR_INVALID_STATE`. Activation is also only permitted when the contract's referenced package is itself `ACTIVE`; an activation pointed at a retired package fails state validation (`ERR_INVALID_STATE`). On activation, the server stamps `coverage_start_utc` to the current clock, stamps `coverage_end_utc` to exactly 365 days after `coverage_start_utc`, pins `annual_premium_due_cents` to the package's `annual_premium_cents` (only when the existing `annual_premium_due_cents` is zero — i.e., unless renewal has already stamped a non-zero successor premium; see §3.6), and increments `version` by one.

A `Customer` may cancel their own contract while it is still in `PENDING_PAYMENT` with no further conditions; this transitions the contract to `CANCELLED`. Cancellation from `ACTIVE` is also permitted, but only when no `ClaimTicket` on the contract is in `SUBMITTED`, `ASSESSED`, or `DISPATCHED` — that is, no open claim is in flight. If any such open claim exists, the cancellation is rejected with `ERR_OPEN_CLAIMS_BLOCK_CANCEL`. Cancellation is allowed only from `PENDING_PAYMENT` or `ACTIVE`; a cancel request against a contract in `EXPIRING_SOON`, `EXPIRED`, `CANCELLED`, or `RENEWED` is rejected with `ERR_INVALID_STATE`. A `Customer` caller cancelling a contract whose `customer_id` does not match their `X-User-ID` is rejected with `ERR_FORBIDDEN`. Cancellation transitions the contract to `CANCELLED` and increments `version` by one. Both `CANCELLED` and `EXPIRED` and `RENEWED` are terminal contract states; no further transition leaves them.

### 3.3. Registering Covered Items and the Pre-Existing Exclusion

Once a contract exists, the holder may register the appliances it will protect (the contract may be in any status — there is no state-machine guard on `POST /covered-items`). A **Covered Item** is registered by submitting `contract_id`, the appliance `category`, the `brand`, the `model`, and the `install_year`. The `category` must be one of the supported enums: `HVAC`, `WATER_HEATER`, `REFRIGERATOR`, `DISHWASHER`, `WASHER`, `DRYER`, or `OVEN`. The `install_year` must be a year between 1900 and the server's current wall-clock UTC year inclusive (this bound is read from the host's wall clock, not from the logical clock that §3.9 drives).

Registration also accepts an optional `pre_existing_flag` which defaults to false if omitted or supplied as `null`; when supplied it must be a JSON boolean (any other type — string, number — is rejected with `ERR_INVALID_REQUEST`). This flag captures, at the moment of registration, whether the homeowner is declaring the item already broken. Crucially, the flag is pinned at registration and is immutable thereafter — neither subsequent operations nor administrative overrides can flip it. A covered item whose `pre_existing_flag` is true cannot be assessed for repair: a claim filed against such an item can be submitted but, at the assessment step, will be rejected with `ERR_PRE_EXISTING_EXCLUDED`. The only legal disposition for such a claim is the rejection path with a `rejection_reason` of `PRE_EXISTING_EXCLUDED`.

A covered item also carries two computed fields used by the return-visit guarantee: `last_dispatch_completed_utc` and `last_dispatch_id`. Both are null until a dispatch on the item completes for the first time, at which point they are stamped to the completion time and the completing dispatch's `id` respectively, and re-stamped on every subsequent completion.

Each contract's covered-item roster is bounded. Attempting to register a new covered item that would push the contract's total past the package's `max_covered_items` is rejected with `ERR_ITEM_LIMIT_EXCEEDED`. The capacity check counts every covered item currently associated with the contract regardless of whether it has any claim history.

### 3.4. Claim Filing and Triage

A **Claim Ticket** is filed against a covered item under an active or expiring-soon contract. The filing payload carries `contract_id`, `covered_item_id`, and `issue_summary` — the homeowner's free-text description of what is wrong. The new claim is written in `SUBMITTED` with all computed fields cleared: `repair_cost_cents` zero, `provisional_copay_cents` zero, `final_copay_cents` zero, `service_fee_charged_cents` zero, `is_return_visit` false, `prior_dispatch_id` null, and `rejection_reason` null.

The coverage-window guard is enforced at filing time: the request is rejected with `ERR_OUT_OF_COVERAGE` unless the server clock is in the half-open interval from `coverage_start_utc` (inclusive) to `coverage_end_utc` (exclusive) and the contract's `status` is one of `ACTIVE` or `EXPIRING_SOON`. The cross-aggregate consistency check is enforced in the same step: the supplied `covered_item_id` must reference a covered item whose `contract_id` matches the claim's `contract_id`, otherwise the request is rejected with `ERR_ITEM_NOT_ON_CONTRACT`. Filing also increments the parent contract's `claims_in_period_count`.

From `SUBMITTED`, a `Dispatcher` (or `PlatformAdmin`) routes the claim down one of two paths. The first path is **assessment**, transitioning the claim from `SUBMITTED` to `ASSESSED`. The assessment payload carries `estimated_repair_cost_cents`, which must be strictly greater than zero. Assessment is only permitted when the covered item's `pre_existing_flag` is false (else `ERR_PRE_EXISTING_EXCLUDED`) and the parent contract is in `ACTIVE` or `EXPIRING_SOON`. On a successful assessment, the server sets the claim's `repair_cost_cents` to the supplied `estimated_repair_cost_cents` and computes the provisional co-pay (see §3.7).

The second path is **rejection**, transitioning the claim directly from `SUBMITTED` to `REJECTED`. The reject payload carries `rejection_reason`, which must be one of `PRE_EXISTING_EXCLUDED`, `OUT_OF_COVERAGE`, or `NOT_COVERED_CATEGORY`. On rejection, the server stamps `rejection_reason` and recomputes the parent contract's `claims_in_period_count`. `RESOLVED` and `REJECTED` are terminal claim states.

### 3.5. Dispatching a Technician and the Return-Visit Guarantee

From `ASSESSED`, the dispatcher schedules a technician visit, transitioning the claim from `ASSESSED` to `DISPATCHED`. The dispatch payload carries `technician_id` (a non-empty string) and `scheduled_utc` (a parseable ISO 8601 UTC timestamp string; non-string or unparseable values are rejected with `ERR_INVALID_REQUEST`) which must be at or after the current server clock — a `scheduled_utc` strictly before the clock yields `ERR_SCHEDULED_IN_PAST` (an exact equality with the clock is allowed).

The dispatcher's roster is protected by a technician-buffer rule: a new dispatch is rejected with `ERR_TECHNICIAN_DOUBLE_BOOKED` when there already exists another `Dispatch` row carrying the same `technician_id` whose `status` is `SCHEDULED` or `IN_PROGRESS` and whose `scheduled_utc` falls within a ±60-minute window of the new one. The window comparison is strict: the existing visit conflicts only when the absolute difference between its `scheduled_utc` and the new `scheduled_utc` is less than 3600 seconds; an exact 3600-second gap is permitted.

The dispatch transition does three things at once that are easy to confuse. First, it creates a new `Dispatch` row carrying the supplied `claim_id`, `technician_id`, and `scheduled_utc` and a `status` of `SCHEDULED`. Second, it evaluates whether the new dispatch enjoys the **return-visit guarantee** and pins the result onto the claim. Third, it pins the Trip Charge component the homeowner will owe.

The return-visit evaluation reads the covered item's `last_dispatch_completed_utc` and the package's `return_visit_window_days`. When `last_dispatch_completed_utc` is null — i.e., there has never been a completed dispatch on this item — the result is unconditionally false: this is a first visit. When `last_dispatch_completed_utc` is non-null, the current server clock is compared to the prior completion time plus `return_visit_window_days` days. If the current clock is strictly earlier than that boundary, `is_return_visit` is pinned to true and `prior_dispatch_id` is pinned to the covered item's current `last_dispatch_id` — the dispatch that began the window. If the current clock has reached or passed the boundary, `is_return_visit` is pinned to false and `prior_dispatch_id` stays null. The boundary is exclusive on the right: an exact equality between the current clock and `last_dispatch_completed_utc` plus `return_visit_window_days` days evaluates as **not** within the window (the window has just closed). Datetime comparisons resolve at one-second granularity.

The Trip Charge pin reads the just-pinned `is_return_visit`: when it is true, `service_fee_charged_cents` is set to zero (the return-visit guarantee waives the Trip Charge); when it is false, `service_fee_charged_cents` is set to the package's `service_fee_cents`.

In the field, a `Technician` (or `PlatformAdmin`) starts the visit by transitioning the dispatch from `SCHEDULED` to `IN_PROGRESS`. The start endpoint is only legal once the server clock has reached `scheduled_utc` — earlier starts are blocked by the state-machine eligibility check. From `IN_PROGRESS`, the technician closes the visit one of two ways. A successful repair completes the dispatch (`IN_PROGRESS → COMPLETED`), which stamps `completed_utc` on the dispatch to the current clock, copies that timestamp into the parent covered item's `last_dispatch_completed_utc`, and writes the completing dispatch's `id` into the covered item's `last_dispatch_id`. A repair that needs follow-up flips the dispatch to `RETURN_NEEDED` (`IN_PROGRESS → RETURN_NEEDED`), which opens the door to reopening the underlying claim.

### 3.6. Resolution, Reopening, and the Claim Cycle

A claim in `DISPATCHED` is closed by the dispatcher with a final accounting, transitioning the claim from `DISPATCHED` to `RESOLVED`. The resolve payload carries `actual_repair_cost_cents`, which must be strictly greater than zero. Resolution is only legal when the `Dispatch` linked to the claim has reached `COMPLETED`; "the linked dispatch" here means the **most recently created** `Dispatch` row whose `claim_id` equals the claim's `id` (ordered by `created_at` ascending — the latest is the one that matters), so that after a reopen-and-redispatch cycle only the new dispatch's status governs eligibility. A claim whose latest linked dispatch is still in `SCHEDULED`, `IN_PROGRESS`, or `RETURN_NEEDED` cannot resolve, and the attempt is blocked by state-machine eligibility (`ERR_INVALID_STATE`). On resolution, the server updates `repair_cost_cents` to `actual_repair_cost_cents`, computes the final co-pay (see §3.7), and recomputes the parent contract's `total_paid_out_cents` and `claims_in_period_count`.

If the dispatch was instead flagged `RETURN_NEEDED`, the same claim may be reopened (`DISPATCHED → ASSESSED`) so that a follow-up dispatch can be scheduled under the same `ClaimTicket` rather than opening a fresh one. As with resolution, "the dispatch" here means the most recently created `Dispatch` row on the claim (ordered by `created_at` ascending); reopen is only permitted when that latest dispatch's status is `RETURN_NEEDED`, otherwise the request is rejected with `ERR_INVALID_STATE`. Reopening resets `provisional_copay_cents` to zero pending re-assessment. The cycle picks up where it left off: the next assessment writes a new provisional co-pay, and the next dispatch evaluates `is_return_visit` again — this time against the now-stamped `last_dispatch_completed_utc` from the prior completing dispatch. This is the system's primary cyclic edge: a single claim may pass through `SUBMITTED → ASSESSED → DISPATCHED → ASSESSED → DISPATCHED → RESOLVED` if the first dispatch needed a return.

### 3.7. Co-Pay Computation: Provisional and Final

The system computes the homeowner's share of a repair twice. The first computation, the **provisional co-pay**, is pinned at the assessment step from the estimated repair cost, and is the figure quoted to the homeowner so they know what they are agreeing to before the technician arrives. The second computation, the **final co-pay**, is pinned at resolution from the actual repair cost, and is what the homeowner is ultimately billed.

Both computations follow the same threshold structure. Start with the repair cost in cents — call it the repair amount. Subtract the package's `copay_cap_cents` from the repair amount. If the difference is zero or negative, the excess above the cap is zero; otherwise the excess equals that difference. Multiply the excess by the package's `copay_share_pct` and round the product to the nearest cent using round half up. This rounded value is the co-pay portion attributable to the share above the cap. Add the applicable Trip Charge to that figure to obtain the co-pay. No further rounding is applied after the addition.

The two computations differ only in what they treat as the Trip Charge. The provisional co-pay always assumes the Trip Charge will apply, because at assessment time the return-visit evaluation has not yet happened; it therefore reads `service_fee_cents` directly from the package. The result is written into the claim's `provisional_copay_cents`. The final co-pay uses the Trip Charge that was pinned at dispatch — the claim's `service_fee_charged_cents`, which is zero when `is_return_visit` is true and equals the package's `service_fee_cents` otherwise. Critically, the final computation does **not** re-read the package's current `service_fee_cents`; it uses the pinned value, so that a mid-flight catalog change to the package cannot alter the homeowner's bill after dispatch. The result is written into the claim's `final_copay_cents`.

Four scenarios cover the final co-pay:

- **First visit, under cap.** When `is_return_visit` is false and the actual repair amount is at most `copay_cap_cents`, the final co-pay equals the package's `service_fee_cents`: the homeowner pays only the Trip Charge.
- **First visit, over cap.** When `is_return_visit` is false and the actual repair amount exceeds `copay_cap_cents`, the final co-pay equals the package's `service_fee_cents` plus the rounded share of the excess.
- **Return visit, under cap.** When `is_return_visit` is true and the actual repair amount is at most `copay_cap_cents`, the final co-pay is zero: the Trip Charge is waived and there is no excess to share.
- **Return visit, over cap.** When `is_return_visit` is true and the actual repair amount exceeds `copay_cap_cents`, the final co-pay equals the rounded share of the excess: the Trip Charge is waived but co-pay sharing still applies to the portion above the cap.

### 3.8. The Renewal Cycle and Premium Calculation

Thirty days before a contract expires, the system surfaces the upcoming renewal. The clock-tick capability scans every contract in `ACTIVE` or `EXPIRING_SOON` and, for any active contract whose `coverage_end_utc` is at most 30 days away (and not yet reached), drives the auto-transition `ACTIVE → EXPIRING_SOON`. This transition fires at most once per contract — it is guarded by the contract's `renewal_reminder_sent_at` field, which is null until the transition and pinned to the current clock at the moment it fires. The same transition writes a `RenewalReminder` row carrying the parent `contract_id`, `sent_utc` equal to the contract's just-stamped `renewal_reminder_sent_at`, and `days_to_expiry` equal to the whole number of days between the current clock and the contract's `coverage_end_utc`, computed by taking the total seconds remaining, dividing by 86400, and rounding down to a whole number. Each fired auto-transition increments the contract's `version`. The reminder row is immutable thereafter: it carries `id` and `created_at` only and is not subject to OCC or further mutation.

When the clock advances past `coverage_end_utc`, the same capability drives a second auto-transition: any contract in `ACTIVE` or `EXPIRING_SOON` whose `coverage_end_utc` has been reached is transitioned to `EXPIRED`, with `version` incremented. `EXPIRED` is terminal.

While the contract is in `EXPIRING_SOON`, the homeowner may renew it, transitioning the original contract from `EXPIRING_SOON` to `RENEWED`; a renew request against a contract in any other status (`PENDING_PAYMENT`, `ACTIVE`, `EXPIRED`, `CANCELLED`, or `RENEWED`) is rejected with `ERR_INVALID_STATE`. A `Customer` caller renewing a contract whose `customer_id` does not match their `X-User-ID` is rejected with `ERR_FORBIDDEN`. The renewal payload carries `expected_contract_version` (the OCC field — see §2.7; missing or non-integer values are rejected with `ERR_INVALID_REQUEST`) and an optional `new_package_id` that lets the homeowner switch packages on renewal; when `new_package_id` is omitted or supplied as `null`, the successor inherits the original contract's `package_id`. If `new_package_id` is supplied, it must resolve to an existing package (else `ERR_NOT_FOUND`) and that package must be `ACTIVE`, else the renewal is rejected with `ERR_PACKAGE_RETIRED`. Renewal creates a new contract row (a successor) with a fresh `id`, `status` of `PENDING_PAYMENT`, `version` of 1, the same `customer_id`, and either the original or the newly-specified `package_id`. The successor's `annual_premium_due_cents` is stamped per the renewal-premium calculation below. The original contract's `status` is set to `RENEWED` and its `version` is incremented by one. `RENEWED` is terminal on the original; the successor begins the cycle anew and must itself be activated (which will stamp its `coverage_start_utc`, `coverage_end_utc`, and any not-yet-stamped `annual_premium_due_cents`).

The **renewal-premium calculation** prices the successor's annual premium from three inputs: the package's `annual_premium_cents` resolved through the successor's `package_id`, the number of whole days remaining on the original contract at the moment renewal is requested, and the number of covered items the original contract carries. The days-remaining figure is computed by taking the total seconds between the original contract's `coverage_end_utc` and the current clock, dividing by 86400, and rounding down to a whole number — note that this is read off the **original** contract's `coverage_end_utc`, not the successor's, which is unset at this point. The figure may be negative (a renewal triggered when the clock has already passed the original `coverage_end_utc`); in that case it is treated as "at-expiry" — `days_remaining < 15` falls into the no-discount branch below. The covered-item count is the count of every `CoveredItem` whose `contract_id` matches the original contract, regardless of `pre_existing_flag` and regardless of whether the item has any claim history.

The premium has two parts: a base, which is the package premium possibly adjusted by an early-renewal discount, and a per-item surcharge for any item beyond the first.

- **Base part — early renewal vs at-expiry.** When the days-remaining figure is at least 15, the renewal is considered early and receives a 10% discount: the base equals the package premium minus ten percent of the package premium, where the ten-percent figure is computed by multiplying the package premium by 0.10 and rounding to the nearest cent using round half up. When the days-remaining figure is at most 14, no discount applies and the base equals the package premium directly. The 15-day boundary is inclusive on the early-renewal side: exactly 15 days remaining qualifies for the discount; exactly 14 days does not.
- **Surcharge part — per item rounding order.** Let the count of additional items equal the covered-item count minus one, clamped to zero if the contract has one or zero items. The per-item surcharge is two percent of the package premium, rounded to the nearest cent using round half up, **rounded once per item before summation**. The total surcharge is then this per-item cent amount multiplied by the count of additional items. The order matters: rounding per-item first and then multiplying is the pinned convention. Computing the un-rounded product across all items and rounding once at the end is not equivalent and is rejected — implementations using it can diverge by up to several cents at scale.

The successor's `annual_premium_due_cents` is the sum of the base part and the surcharge part. This value is stamped at the moment renewal completes and is immutable thereafter.

### 3.9. Administrative Test-Driving of the Logical Clock

Because so much of the contract and claim machinery turns on time — the 30-day renewal-reminder threshold, the 365-day coverage window, the return-visit window, the dispatch-in-future check — the system exposes two `PlatformAdmin`-only test-driving capabilities that let an operator advance the server's logical clock and fire its time-driven auto-transitions deterministically.

The first capability sets the logical clock to a supplied UTC instant. Its input field is `to_iso8601` — an ISO 8601 UTC timestamp string — and its response carries `current_utc` reflecting the just-set clock. Setting the clock does not by itself trigger any auto-transitions; it merely moves the reference point that other operations consult when they ask for the current time.

The second capability is the clock-tick scan. It takes no input. It walks every contract in `ACTIVE` or `EXPIRING_SOON` in `created_at` ascending order and, for each, applies whichever of the two auto-transitions the contract is now eligible for: the move into `EXPIRING_SOON` if `coverage_end_utc` is within thirty days, the move into `EXPIRED` if `coverage_end_utc` has been reached. The two transitions are checked in a fixed order per contract: first, if the clock has reached or passed `coverage_end_utc`, the contract jumps straight to `EXPIRED` (this is true whether the contract was in `ACTIVE` or `EXPIRING_SOON`; an `ACTIVE` contract whose tick is the first to observe that `coverage_end_utc` has already passed skips the reminder entirely — no `RenewalReminder` is written and `renewal_reminder_sent_at` remains null); otherwise, if the contract is `ACTIVE` and the clock is within the 30-day window and `renewal_reminder_sent_at` is null, the `ACTIVE → EXPIRING_SOON` transition fires. The capability's response carries `transitions_fired` (the count of contracts that changed state on this scan) and `reminders_emitted` (the count of `RenewalReminder` rows written, which equals the count of `ACTIVE → EXPIRING_SOON` transitions on this scan). Each fired transition bumps the affected contract's `version`. The reminder rows surfaced by this scan are subsequently visible through the per-contract renewal-reminder listing.

## 4. Endpoint Definitions

The API surface is summarized below. New-resource creation endpoints return HTTP `201`; all other successful operations return `200`. List endpoints accept `limit` and `offset` query parameters per §2.3 and the relevant filter parameters noted in each row's description. Request and response payload details — including the field-level effects of each operation — live in §3; consult that section to reconstruct what each endpoint reads and writes.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/contract-packages` | Create a contract package in the catalog. | `PlatformAdmin` |
| GET | `/contract-packages` | List contract packages; supports `status` filter. | `PlatformAdmin`, `Customer`, `Dispatcher` |
| GET | `/contract-packages/{id}` | Get a contract package by id. | `PlatformAdmin`, `Customer`, `Dispatcher` |
| POST | `/contract-packages/{id}/retire` | Retire a contract package. | `PlatformAdmin` |
| POST | `/customers` | Register a customer (public; no auth headers). | `Anonymous` |
| GET | `/customers/{id}` | Get a customer by id. | `PlatformAdmin`, `Customer` |
| POST | `/contracts` | Open a contract in `PENDING_PAYMENT`. | `Customer`, `PlatformAdmin` |
| GET | `/contracts/{id}` | Get a contract by id, including computed aggregates. | `PlatformAdmin`, `Customer`, `Dispatcher` |
| GET | `/contracts` | List contracts; supports `customer_id`, `package_id`, and `status` filters. | `PlatformAdmin`, `Customer`, `Dispatcher` |
| POST | `/contracts/{id}/activate` | Activate a contract. | `PlatformAdmin` |
| POST | `/contracts/{id}/renew` | Renew an expiring-soon contract; OCC-guarded. Returns the successor contract. | `Customer`, `PlatformAdmin` |
| POST | `/contracts/{id}/cancel` | Cancel a contract from `PENDING_PAYMENT` or (with no open claims) `ACTIVE`. | `Customer`, `PlatformAdmin` |
| POST | `/covered-items` | Register a covered item on a contract. | `Customer`, `PlatformAdmin` |
| GET | `/covered-items/{id}` | Get a covered item by id. | `PlatformAdmin`, `Customer`, `Dispatcher` |
| GET | `/covered-items` | List covered items; supports `contract_id` and `last_dispatch_id` filters. | `PlatformAdmin`, `Customer`, `Dispatcher` |
| POST | `/claims` | File a claim against a covered item. | `Customer`, `PlatformAdmin` |
| GET | `/claims/{id}` | Get a claim by id. | `PlatformAdmin`, `Customer`, `Dispatcher` |
| GET | `/claims` | List claims; supports `contract_id`, `covered_item_id`, `prior_dispatch_id`, and `status` filters. | `PlatformAdmin`, `Customer`, `Dispatcher` |
| POST | `/claims/{id}/assess` | Assess a submitted claim; pins provisional co-pay. | `Dispatcher`, `PlatformAdmin` |
| POST | `/claims/{id}/reject` | Reject a submitted claim with a reason. | `Dispatcher`, `PlatformAdmin` |
| POST | `/claims/{id}/dispatch` | Dispatch an assessed claim; creates a dispatch row; pins return-visit fields. | `Dispatcher`, `PlatformAdmin` |
| POST | `/claims/{id}/resolve` | Resolve a dispatched claim; pins final co-pay; updates contract aggregates. | `Dispatcher`, `PlatformAdmin` |
| POST | `/claims/{id}/reopen` | Reopen a dispatched claim whose dispatch is in `RETURN_NEEDED`. | `Dispatcher`, `PlatformAdmin` |
| GET | `/dispatches/{id}` | Get a dispatch by id. | `PlatformAdmin`, `Dispatcher`, `Technician` |
| GET | `/dispatches` | List dispatches; supports `claim_id` and `status` filters. | `PlatformAdmin`, `Dispatcher`, `Technician` |
| POST | `/dispatches/{id}/start` | Technician marks a scheduled dispatch in-progress. | `Technician`, `PlatformAdmin` |
| POST | `/dispatches/{id}/complete` | Technician completes an in-progress dispatch; cascades to the covered item. | `Technician`, `PlatformAdmin` |
| POST | `/dispatches/{id}/mark-return-needed` | Technician flags an in-progress dispatch as needing a return. | `Technician`, `PlatformAdmin` |
| GET | `/contracts/{id}/renewal-reminders` | List renewal reminders for a contract. | `PlatformAdmin`, `Customer` |
| POST | `/_clock/set` | Set the server's logical clock. | `PlatformAdmin` |
| POST | `/_clock/tick` | Scan contracts and fire eligible time-driven auto-transitions. | `PlatformAdmin` |

## 5. Error Code Catalogue

The trigger condition for each error is described in the relevant §2 or §3 narrative; this table is a summary of error identifiers and their HTTP status codes only.

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ITEM_NOT_ON_CONTRACT` | 422 |
| `ERR_OUT_OF_COVERAGE` | 422 |
| `ERR_PRE_EXISTING_EXCLUDED` | 422 |
| `ERR_ITEM_LIMIT_EXCEEDED` | 422 |
| `ERR_SCHEDULED_IN_PAST` | 422 |
| `ERR_TECHNICIAN_DOUBLE_BOOKED` | 422 |
| `ERR_OPEN_CLAIMS_BLOCK_CANCEL` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_PACKAGE_RETIRED` | 422 |
