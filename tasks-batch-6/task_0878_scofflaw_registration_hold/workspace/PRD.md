# Scofflaw & Registration-Hold Program API — Product Requirements Document

## 1. Introduction

Municipal parking-enforcement agencies lose enormous sums to habitual offenders — the so-called "scofflaws" who accumulate unpaid citations and continue to drive and re-register vehicles as though nothing were owed. This document specifies the backend service for a Scofflaw & Registration-Hold Program: a single system of record that aggregates a vehicle's outstanding citations, decides when that vehicle's owner has crossed the line into scofflaw status, and coordinates the escalating consequences that follow — booting, towing, and, most consequentially, placing a hold on the vehicle's DMV registration so it cannot be renewed until the debt is cleared.

The service must reconcile several constituencies at once. Enforcement officers file citations and dispatch physical enforcement; owners contest citations, pay their debts, negotiate installment plans, and petition for hardship relief; hearing clerks run the due-process side; and collections administrators handle referral to outside agencies and the eventual release of holds. Because money, physical vehicles, and a person's ability to legally operate a car are all at stake, the system treats every balance as an auditable ledger, enforces separation of duties on the most coercive actions, and recomputes each case's posture deterministically after every event so that two observers of the same case always see the same numbers.

This document defines the complete contract: the resource model, the derived-posture state machines, the monetary calculations, the validation and authorization rules, and every endpoint and error the service exposes.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming that principal's role. If either header is missing, or if `X-User-Role` is not one of the five roles defined below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The five roles are `PlatformAdmin`, `EnforcementOfficer`, `HearingClerk`, `CollectionsAdmin`, and `Owner`.

- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the platform administrator provisions owners, vehicles, hearing officers, tow yards, and cases, controls the logical clock, and may read everything, but the identifier is not compared to any entity's `id`.
- When `X-User-Role` is `EnforcementOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it — it is written to `dispatched_by_user_id` when an enforcement order is dispatched and to `applied_by_user_id` when one is applied — but it is never compared to any entity's `id`.
- When `X-User-Role` is `HearingClerk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity and is not compared to any entity's `id`.
- When `X-User-Role` is `CollectionsAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity and is not compared to any entity's `id`.
- When `X-User-Role` is `Owner`, `X-User-ID` is the `id` of the acting `Owner`. Ownership checks on any case-scoped resource compare the owning `ScofflawCase`'s `owner_id` to `X-User-ID`: an owner may only file or withdraw disputes, make payments, open payment plans, request hardship waivers, and pay release fees on cases whose `owner_id` equals their own `X-User-ID`. An owner acting on a case they do not own is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

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

List endpoints accept two query parameters: `limit` and `offset`. The `limit` defaults to 10, must be at least 1, and may not exceed 100. The `offset` defaults to 0 and must be at least 0. List results are always sorted by `created_at` in ascending order. Every list response echoes `limit` and `offset` in `meta`, alongside `total_count` (the total number of records matching the filter before pagination) and `has_more` (a boolean, true when records remain beyond the current page).

### 2.4. Resource Identity, Timestamps, and Optimistic Concurrency

Every resource is assigned a server-minted `id`, a UUID carrying no type prefix, generated at creation and never reused. Most resources also carry three common properties: `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and `version`, an integer that begins at 1 and increments by 1 on every mutation of that resource. The `HearingOfficer`, `TowYard`, and `Payment` resources are the exceptions: each carries only `id` and `created_at`. They have neither `updated_at` nor `version`, because an officer record, a tow-yard record, and a posted payment are never mutated after creation — a payment in particular is immutable once written.

The `ScofflawCase` is the concurrency anchor of the system, and two write operations against it are guarded by optimistic concurrency control. Creating a payment plan for a case requires the caller to submit `expected_scofflaw_case_version`, carrying the `version` of the `ScofflawCase` the client last observed. If that value does not equal the case's current `version` — because another writer has advanced it since the client last read the case — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). This matters because a new plan legitimately supersedes (cancels) the case's prior active plan; a client holding a stale version, one that predates another writer's supersede, must be stopped rather than allowed to silently cancel a plan it never saw. Dispatching a boot or tow order carries the identical guard: it, too, requires `expected_scofflaw_case_version` to equal the case's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), because an escalated tow dispatch can supersede a still-pending boot order and a stale writer must not act on a case posture it has not observed. No other endpoint accepts a version field.

### 2.5. The Case Ledger, Posture Recomputation, and the Parallel Hold Axis

A `ScofflawCase` is a running ledger over the citations filed against one vehicle. It exposes two independent status axes that evolve separately. The first is `case_status`, a derived posture taking one of `COMPLIANT`, `SCOFFLAW`, or `RESOLVED`. The second is `hold_status`, taking one of `NO_HOLD`, `HOLD_PLACED`, or `HOLD_RELEASED`. These axes are orthogonal: the posture is recomputed by the system, while the hold axis is driven by explicit place-hold and release-hold actions (with one system-driven release described below).

Whenever a citation is filed, a payment is applied, a dispute is filed or decided or withdrawn, a hardship waiver is approved, or a collections referral changes state, the system recomputes the owning case's ledger: `outstanding_count`, `assessed_balance_cents`, `collectible_balance_cents`, the posture, and the two eligibility flags. This recomputation is also performed on read, so a fetched case always reflects the current logical clock. Every such balance-affecting write that occurs through a case-scoped endpoint increments the case's `version` by 1.

Any operation that changes more than one resource must apply every cascade. When a case reaches full resolution, if the case is currently holding a registration hold (`hold_status` is `HOLD_PLACED`), the system moves `hold_status` to `HOLD_RELEASED` and clears the vehicle's `hold_flag` to false as part of the same resolution. When posture de-escalates out of scofflaw standing, any still-pending enforcement order on the case is cancelled as described in §3.6. These cascades, and the `updated_at`/`version` bumps that accompany every mutation, are part of the contract, not optional bookkeeping.

### 2.6. Monetary Precision and Rounding

All monetary values are integer cents. Wherever a calculation introduces a fractional cent — a late penalty computed as a percentage of a fine, a per-installment amount, a hardship credit — the result is rounded half up to the nearest whole cent. Where a rule requires summing several rounded quantities (for example, a late penalty computed for each of several violations), the rounding is applied to each per-violation quantity first and the rounded quantities are then summed; the system never sums raw fines first and applies the rate to the aggregate. Storage-day counts round up (ceiling) to whole days, as described in §3.6.

### 2.7. Scofflaw, Boot, and Tow Thresholds

The program's coercive powers switch on at fixed breakpoints, all evaluated inclusively (a case exactly at a breakpoint has crossed it). A case becomes a scofflaw when its collectible balance reaches at least 50,000 cents (five hundred dollars) — the `SCOFFLAW_AMOUNT_THRESHOLD_CENTS` — or when its `outstanding_count` reaches at least five outstanding citations — the `SCOFFLAW_COUNT_THRESHOLD`. Either condition alone suffices.

Two further eligibility flags refine what enforcement the scofflaw posture unlocks. A case is `eligible_for_boot` when it is in `SCOFFLAW` posture and its `outstanding_count` is at least the `BOOT_COUNT_THRESHOLD` of five outstanding citations. A case is `eligible_for_tow` when it is in `SCOFFLAW` posture and its `collectible_balance_cents` is at least the `TOW_AMOUNT_THRESHOLD_CENTS` of 100,000 cents (one thousand dollars). Both flags are recomputed together with the balances.

### 2.8. The Logical Clock and Temporal Windows

The service runs on a logical clock, not wall-clock time. On startup the clock reads exactly `2026-05-01T00:00:00Z` and stays there until advanced; before any advance it never falls back to real time. A platform administrator advances the clock by supplying a target instant as `to_iso8601`. Time-gated derivations — whether a citation's late penalty has begun to accrue, whether a dispute is still within its filing window, whether a case's oldest citation is old enough to refer to collections, how many storage days a tow has accrued — are all evaluated against this logical clock and re-derive on the next read after the clock moves.

### 2.9. Validation Ordering and Error Precedence

When multiple checks could fail on one request, they are evaluated in a fixed order so that the returned error is deterministic. Authentication is checked first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_UNAUTHORIZED`), then existence of every resource named in the path (the resource-specific 404s of §3.1, validated left to right along the URL). Only after those does the system check Owner-ownership on owner-scoped operations (`ERR_UNAUTHORIZED`), then resource-state legality (the state errors of §3), then the domain-specific business rules — temporal windows, capacity, uniqueness, plan terms, separation of duties, fiscal thresholds, release conditions — and finally the optimistic-concurrency version check (`ERR_STALE_VERSION`), which is evaluated last among the guards on the two endpoints that carry it. Malformed request bodies — a missing required field, a value of the wrong type, or an unparseable enum or timestamp — are rejected with `ERR_VALIDATION` (HTTP 400). Where the specific state guards below do not name a more precise error, an action attempted against a resource that has already reached a terminal state — a `PAID`, `WAIVED`, or `VOIDED` violation, an `UPHELD`, `DISMISSED`, or `WITHDRAWN` dispute, a `COMPLETED` or `CANCELLED` plan, a `RELEASED` or `CANCELLED` order — is rejected with `ERR_TERMINAL_STATE` (HTTP 409).

## 3. Business Logic & Workflows

### 3.1. Provisioning: Owners, Vehicles, Officers, Yards, and Cases

The platform administrator seeds the reference data. Registering an owner supplies `full_name`, `dmv_customer_id`, `email`, and `mailing_state` (a two-letter state code), and optionally `hardship_status`, which is one of `NONE`, `PENDING`, or `APPROVED` and defaults to `NONE` when omitted. The `dmv_customer_id` is unique across owners. Registering a vehicle supplies `owner_id` naming its registered owner, `plate_number`, `plate_state`, `vin`, and optionally `registration_status`, one of `ACTIVE`, `EXPIRED`, or `SUSPENDED`, defaulting to `ACTIVE`. A vehicle also carries a computed `hold_flag`, false at creation, which the case machinery raises and lowers as registration holds come and go. The administrator also creates hearing officers (each with a `full_name`) and tow yards (each with a `name` and a storage `capacity` of at least 1, plus a computed `occupied_slot_count` that starts at 0).

A scofflaw case is opened — by a platform administrator or an enforcement officer — against a single vehicle, named by `vehicle_id`. At creation the system copies the vehicle's owner into the case's `owner_id` (this denormalized copy is what later ownership checks read), and initializes `case_status` to `COMPLIANT` and `hold_status` to `NO_HOLD`.

Requests that name a resource in their path must resolve it or fail with the matching not-found error, validated left to right: `ERR_OWNER_NOT_FOUND`, `ERR_VEHICLE_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_VIOLATION_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`, `ERR_OFFICER_NOT_FOUND`, `ERR_TOW_YARD_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_WAIVER_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`, and `ERR_PAYMENT_NOT_FOUND` (all HTTP 404). Each path variable is the `id` of its resource. List endpoints support reverse lookups: vehicles by `owner_id` or `plate_number`; cases by `vehicle_id`, `owner_id`, or `case_status`; violations by `scofflaw_case_id` or `status`; disputes by `violation_id`, `officer_id`, or `status`; payments, payment plans, boot/tow orders, hardship waivers, and collections referrals by `scofflaw_case_id` and (where applicable) `status` or `tow_yard_id`.

### 3.2. Filing Citations and Escalation to Scofflaw

Only an enforcement officer files a citation, against a named case. The payload carries `citation_number` (unique across all violations), `violation_type` (one of `METER_EXPIRED`, `NO_PERMIT`, `STREET_CLEANING`, `HANDICAP`, or `FIRE_HYDRANT`), `fine_amount_cents` (a non-negative integer base fine), `issued_at` (the ISO 8601 UTC instant the citation was written, which also opens the dispute window), and `due_at` (the ISO 8601 UTC payment due date). A new violation enters `OUTSTANDING` status; its computed fields `late_penalty_cents`, `paid_amount_cents`, and `credit_cents` all begin at 0.

A citation's current amount owed is its `fine_amount_cents` plus its late penalty, less what has been paid and less any hardship credit, floored at zero. The **late penalty** is 25% of the fine (`LATE_PENALTY_PCT` is 0.25), rounded half up, but only once the logical clock has reached or passed the violation's `due_at` and only while the violation is in `OUTSTANDING` or `DISPUTED` status; before the due instant, or for a violation that is paid, waived, voided, or in collections, the penalty is 0. This penalty is computed per violation and rounded before it participates in any case total.

Filing a citation recomputes the case ledger, which may push the case across a threshold. If, after the new citation, the case's collectible balance is at least 50,000 cents or its outstanding count is at least five, the posture advances from `COMPLIANT` (or from `RESOLVED`, if a resolved case is reopened by fresh liability) to `SCOFFLAW`, and the boot/tow eligibility flags are recomputed. The filing increments the case's `version`.

### 3.3. Contesting a Citation: Disputes and Hearings

An owner contests a citation by filing a dispute, supplying a free-text `reason`. Filing is permitted only while the violation is `OUTSTANDING` (a dispute or payment targeting a violation that is not `OUTSTANDING` is rejected with `ERR_VIOLATION_NOT_OUTSTANDING`, HTTP 409), only while the logical clock is within `DISPUTE_WINDOW_DAYS` (21) days of the citation's `issued_at`, and only if no dispute has ever existed for that violation in any status — a violation may be disputed at most once in its lifetime. A dispute filed after the window has closed is rejected with `ERR_DISPUTE_WINDOW_EXPIRED` (HTTP 422). Because filing immediately flips the violation to `DISPUTED`, a second attempt while the first dispute is still live is caught by the violation-state guard; `ERR_DISPUTE_ALREADY_EXISTS` (HTTP 409) becomes reachable only after a prior dispute has reached a terminal outcome and the violation has returned to `OUTSTANDING`. Filing a dispute creates a `Dispute` in `SUBMITTED` status, moves the violation `OUTSTANDING → DISPUTED`, and recomputes the case balances — the violation's current due drops out of the collectible view (see §3.4), which can de-escalate the case out of `SCOFFLAW` and cancel any still-pending enforcement order. The filing increments the case's `version`. The dispute records `filed_at` from the logical clock.

A hearing clerk schedules the hearing, supplying `officer_id` and a window of `scheduled_start` and `scheduled_end`. Scheduling requires the dispute to be `SUBMITTED` and the linked violation to still be `DISPUTED` (a cross-entity check; failure is `ERR_INVALID_STATE`, HTTP 409). The assigned officer must be free: the new window may not overlap any other `SCHEDULED` dispute already assigned to that officer, where overlap is judged on the half-open interval from `scheduled_start` up to but not including `scheduled_end`, so two hearings that merely touch end-to-start are allowed; a genuine overlap is rejected with `ERR_OFFICER_DOUBLE_BOOKED` (HTTP 409). A successful schedule sets `officer_id`, `scheduled_start`, and `scheduled_end` and moves the dispute `SUBMITTED → SCHEDULED`. A clerk may reschedule a `SCHEDULED` dispute to a new `scheduled_start`/`scheduled_end` window; the same officer-overlap rule and the same `ERR_OFFICER_DOUBLE_BOOKED` rejection apply, and the dispute remains `SCHEDULED`.

The clerk records the decision on a `SCHEDULED` dispute by supplying `decision`. An `UPHELD` decision sets `decided_at`, moves the dispute to `UPHELD`, voids the citation (`DISPUTED → VOIDED`), and recomputes the case balances — the voided citation leaves the assessed view as well. A `DISMISSED` decision sets `decided_at`, moves the dispute to `DISMISSED`, reinstates the citation (`DISPUTED → OUTSTANDING`), and recomputes the balances, restoring the citation's collectible amount. Both decision branches increment the case's `version`. Separately, the owner may withdraw their own dispute while it is `SUBMITTED` or `SCHEDULED`; withdrawal moves the dispute to `WITHDRAWN`, reinstates the citation `DISPUTED → OUTSTANDING`, recomputes the balances (collectible restored), and increments the case's `version`. Because reinstatement restores exactly what dispute-filing removed, collectible liability is conserved across a full dispute round-trip.

The case ledger holds two distinct liability views over the same citations, differing only in which statuses they include. The **assessed** balance (`assessed_balance_cents`) is the total exposure and sums the current due of every citation that is `OUTSTANDING` or `DISPUTED`. The **collectible** balance (`collectible_balance_cents`) is what the agency may currently collect and sums the current due of only the `OUTSTANDING` citations, excluding disputed ones entirely. Citations that are `PAID`, `WAIVED`, `VOIDED`, or `IN_COLLECTIONS` contribute to neither view. The collectible balance is the figure that gates scofflaw posture, tow eligibility, and referral snapshots.

### 3.4. Paying Down a Case: Waterfall Allocation and Resolution

An owner pays their own case by submitting `amount_cents` (at least 1) and a `method` of `CARD`, `CASH`, `CHECK`, or `ACH`. The payment is allocated by a waterfall across the case's `OUTSTANDING` citations, processed oldest first: candidates are ordered by `issued_at` ascending, ties broken by `created_at` ascending — never by `id`. Walking that order, each citation absorbs the lesser of the remaining payment and its current due; the applied amount is added to that citation's `paid_amount_cents`, the remaining pool is reduced accordingly, and an allocation entry recording `violation_id` and `applied_cents` is appended to the payment's `allocation` list. A citation whose paid-plus-credit total reaches its fine-plus-late-penalty is marked `PAID` (`OUTSTANDING → PAID`). The total payment may not exceed the case's collectible balance: a payment that would leave money unallocated after every candidate is exhausted is rejected in whole with `ERR_OVERPAYMENT` (HTTP 422) — there is no partial commit. A posted `Payment` is immutable and records `applied_at` from the logical clock.

Applying a payment recomputes the case balances and may drive resolution. A case reaches `RESOLVED` (`SCOFFLAW → RESOLVED`) when its collectible balance falls to exactly 0 and no enforcement order on the case is still `DISPATCHED` or `APPLIED`. Resolution is where the four-step cascade lands: the final payment resolves the case, and if that case is currently `HOLD_PLACED`, the resolution releases the registration hold (`hold_status → HOLD_RELEASED`) and clears the vehicle's `hold_flag`. Every payment increments the case's `version`. A partial payment that reduces but does not clear the collectible balance may still de-escalate posture: a case whose collectible balance is now greater than 0 but below 50,000 cents and whose outstanding count is now below five returns `SCOFFLAW → COMPLIANT`, its eligibility flags fall to false, and any enforcement order still in `DISPATCHED` status on the case is cancelled.

### 3.5. Installment Plans

An owner may repay over time through a payment plan on their own case. The request carries `expected_scofflaw_case_version` (the OCC guard of §2.4), `total_amount_cents` (at least 1), `installment_count`, and `down_payment_cents` (a non-negative up-front amount). The `installment_count` must be between 1 and `PAYMENT_PLAN_MAX_INSTALLMENTS`, which is 12; a count outside that range is rejected with `ERR_INVALID_PLAN_TERMS` (HTTP 422). The down payment must be at least `PAYMENT_PLAN_MIN_DOWN_PCT` (0.10, i.e. 10%) of the total amount; too small a down payment is rejected with `ERR_INSUFFICIENT_DOWN_PAYMENT` (HTTP 422). On creation the plan enters `ACTIVE`, its `installment_amount_cents` is set to the total minus the down payment, divided by the installment count, rounded half up, and its `paid_to_date_cents` is initialized to the down payment. Its `missed_count` starts at 0. Creating a plan supersedes any prior plan on the case: any existing plan still in `ACTIVE` or `DEFAULTED` status is moved to `CANCELLED`, and the case's `version` increments.

The owner records an installment by supplying `amount_cents`; this adds to `paid_to_date_cents`, and when the running total reaches or exceeds `total_amount_cents` the plan completes (`ACTIVE → COMPLETED`). Recording an installment is permitted only while the plan is `ACTIVE`; otherwise `ERR_PLAN_NOT_ACTIVE` (HTTP 409). A collections administrator may mark an `ACTIVE` plan `DEFAULTED` after a missed installment, which increments `missed_count`, and may `reinstate` a `DEFAULTED` plan back to `ACTIVE`. Default requires the plan to be `ACTIVE` and reinstatement requires it to be `DEFAULTED`; an incompatible status yields `ERR_PLAN_NOT_ACTIVE` (HTTP 409).

### 3.6. Boot and Tow Enforcement

When a case is a threshold-eligible scofflaw, an enforcement officer dispatches a boot or tow order. The dispatch carries `expected_scofflaw_case_version` (OCC), `action_type` of `BOOT` or `TOW`, and for a tow the `tow_yard_id` plus the storage window `stored_from` and `stored_until` (both ISO 8601 UTC; a boot leaves these null). Dispatch requires `case_status` to be `SCOFFLAW`, failing which the order is refused with `ERR_CASE_NOT_SCOFFLAW` (HTTP 409). Beyond scofflaw posture, the fiscal thresholds gate each variant: a boot dispatch requires the case's `outstanding_count` to be at least the `BOOT_COUNT_THRESHOLD` of five, and if it is not the dispatch is rejected with `ERR_BOOT_THRESHOLD_NOT_MET` (HTTP 422); a tow dispatch requires the case's `collectible_balance_cents` to be at least the `TOW_AMOUNT_THRESHOLD_CENTS` of 100,000 cents, and if it is not the dispatch is rejected with `ERR_TOW_THRESHOLD_NOT_MET` (HTTP 422). A tow additionally consumes tow-yard capacity: if the chosen yard already has a number of overlapping active tows equal to or exceeding its `capacity` for the requested `stored_from`–`stored_until` interval, the dispatch is rejected with `ERR_TOW_YARD_FULL` (HTTP 409); a yard's `occupied_slot_count` counts its tow orders that are `DISPATCHED` or `APPLIED`. A successful dispatch creates the order in `DISPATCHED` status, records `dispatched_by_user_id` from the acting `X-User-ID`, and increments the case's `version`. A tow dispatch reserves a slot (its yard's `occupied_slot_count` rises by 1), and an escalated tow supersedes a still-`DISPATCHED` boot on the same case.

Applying the order is the coercive step and is subject to four-eyes separation of duties: the enforcement officer who applies must not be the one who dispatched. Apply is permitted only while the order is `DISPATCHED`; the acting `X-User-ID` must differ from `dispatched_by_user_id`, and if they are equal the request is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). A successful apply moves the order `DISPATCHED → APPLIED` and records `applied_by_user_id`. An order in the wrong status for apply, release, or cancel is rejected with `ERR_ORDER_NOT_ACTIVE` (HTTP 409).

Before an applied order can be released, its release fee must be paid. The **release fee** (`release_fee_cents`) is recomputed as of the logical clock (or as of `released_at` once released) and differs by action type. A **boot** release fee is a flat `BOOT_FEE_CENTS` of 15,000 cents (one hundred fifty dollars) plus an `ADMIN_FEE_CENTS` of 5,000 cents (fifty dollars), with no storage accrual. A **tow** release fee is `TOW_FEE_CENTS` of 25,000 cents (two hundred fifty dollars) plus the same `ADMIN_FEE_CENTS` of 5,000 cents, plus storage: the number of storage days is the elapsed time from `stored_from` to the as-of instant, rounded up to whole days and never negative, then capped at `MAX_STORAGE_DAYS` of 30 days, and that capped day count is multiplied by the `DAILY_STORAGE_RATE_CENTS` of 4,000 cents (forty dollars) per day. The owner pays by submitting `amount_cents`, which must equal the order's current `release_fee_cents`; any other amount is rejected with `ERR_RELEASE_FEE_UNPAID` (HTTP 409). A correct payment sets `release_fee_paid` to true.

Releasing the order requires it to be `APPLIED`, `release_fee_paid` to be true, and the owning case's `collectible_balance_cents` to be exactly 0. A release attempted while the fee is unpaid is rejected with `ERR_RELEASE_FEE_UNPAID` (HTTP 409); a release attempted while the case still carries a collectible balance is rejected with `ERR_BALANCE_OUTSTANDING` (HTTP 409). A successful release moves the order `APPLIED → RELEASED`, sets `released_at` from the logical clock, and for a tow frees the yard slot (its `occupied_slot_count` falls by 1), conserving slots across the dispatch-and-release round-trip. An officer may instead cancel a `DISPATCHED` order (`DISPATCHED → CANCELLED`), which likewise frees a reserved tow slot; the system performs this same cancellation automatically on any still-`DISPATCHED` order when a case de-escalates out of `SCOFFLAW`.

### 3.7. DMV Registration Holds

The registration hold is the program's strongest lever, and it moves along its own axis. An enforcement officer places a hold on a scofflaw case: placement requires `case_status` to be `SCOFFLAW` (otherwise `ERR_CASE_NOT_SCOFFLAW`, HTTP 409) and requires `hold_status` to be `NO_HOLD` or `HOLD_RELEASED` — a hold placed while one is already active is rejected with `ERR_HOLD_ALREADY_PLACED` (HTTP 409). Placing moves `hold_status` to `HOLD_PLACED`, sets the vehicle's `hold_flag` to true, and increments the case's `version`; a case that was reopened and re-escalated can have its hold re-placed the same way (`HOLD_RELEASED → HOLD_PLACED`). Releasing a hold — permitted to a collections administrator or an enforcement officer, with an optional `release_reason` — requires `hold_status` to be `HOLD_PLACED`; a release attempted otherwise is rejected with `ERR_NO_HOLD_TO_RELEASE` (HTTP 409). A release moves `hold_status` to `HOLD_RELEASED`, clears the vehicle's `hold_flag`, and increments the case's `version`. The same release also happens automatically, as described in §2.5, when a case resolves while holding a placed hold.

### 3.8. Hardship Relief

An owner in financial distress requests a hardship waiver on their own case, choosing a `hardship_tier` of `TIER_1` (partial relief) or `TIER_2` (full relief) and stating an informational `requested_amount_cents` (non-negative). The request is created in `REQUESTED` status; the requested amount is advisory only and does not determine what is granted. A collections administrator decides the waiver by supplying `approve`. A denial moves the waiver to `DENIED`, sets `decided_at`, and changes no balances. An approval moves the waiver to `APPROVED`, sets `decided_at`, computes `approved_amount_cents`, and recomputes the case balances, incrementing the case's `version`.

The granted amount depends on tier and is computed over the case's `OUTSTANDING` citations at decision time. Under `TIER_2` (full forgiveness, corresponding to `HARDSHIP_TIER_2_PCT` of 100%), `approved_amount_cents` equals the sum of the current due of every outstanding citation, and each such citation is moved to `WAIVED` (`OUTSTANDING → WAIVED`). Under `TIER_1` (partial forgiveness, corresponding to `HARDSHIP_TIER_1_PCT` of 50%), each outstanding citation receives a credit equal to half of its own current due, rounded half up per citation, added to that citation's `credit_cents`; `approved_amount_cents` is the sum of those per-citation rounded credits, and the citations remain `OUTSTANDING` (their reduced current due simply falls). In both tiers the per-citation rounding is applied before summation.

### 3.9. Collections Referral and Program Reporting

When a scofflaw case has gone unpaid long enough, a collections administrator refers it to an outside agency, naming the `agency_name`. Referral requires the case to be `SCOFFLAW`, requires the case's oldest `OUTSTANDING` citation to be at least `COLLECTIONS_MIN_AGE_DAYS` (90) days old as measured against the logical clock (otherwise `ERR_NOT_YET_REFERABLE`, HTTP 422), and requires that no referral on the case is already `REFERRED` (a second active referral is rejected with `ERR_REFERRAL_ALREADY_EXISTS`, HTTP 409). Referral creates a `CollectionsReferral` in `REFERRED` status, snapshots `referred_amount_cents` from the case's collectible balance at that instant, records `referred_at`, moves every `OUTSTANDING` citation on the case to `IN_COLLECTIONS`, recomputes the balances (collectible now excludes those citations), and increments the case's `version`; its `settled_amount_cents` remains 0 until settlement.

The administrator later either recalls or settles the referral. A recall moves it to `RECALLED`, returns each `IN_COLLECTIONS` citation on the case to `OUTSTANDING`, recomputes the balances, and increments the case's `version`. A settlement supplies `settled_amount_cents`, moves the referral to `SETTLED`, records that amount, moves each `IN_COLLECTIONS` citation to `PAID`, recomputes the balances, and increments the case's `version`.

A program-level report aggregates across cases and may be scoped by a `case_status` filter. It returns `total_cases`, `scofflaw_cases`, `resolved_cases`, `total_collectible_cents`, `total_assessed_cents`, and `holds_placed`.

## 4. Endpoint Definitions

New resource creations return HTTP 201; all other successful reads, actions, and state transitions return HTTP 200. Request and response bodies, side effects, and trigger conditions are specified in the §3 narratives above.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/_clock/set_current_utc` | Set the server logical clock. | PlatformAdmin |
| POST | `/owners` | Register a vehicle owner. | PlatformAdmin |
| GET | `/owners/{id}` | Fetch an owner. | PlatformAdmin, EnforcementOfficer, HearingClerk, CollectionsAdmin, Owner |
| POST | `/vehicles` | Register a vehicle. | PlatformAdmin |
| GET | `/vehicles/{id}` | Fetch a vehicle (includes hold_flag). | PlatformAdmin, EnforcementOfficer, HearingClerk, CollectionsAdmin, Owner |
| GET | `/vehicles` | List vehicles; filter by owner_id, plate_number. | PlatformAdmin, EnforcementOfficer, HearingClerk, CollectionsAdmin, Owner |
| POST | `/hearing-officers` | Create a hearing officer. | PlatformAdmin |
| GET | `/hearing-officers` | List hearing officers. | PlatformAdmin, HearingClerk |
| POST | `/tow-yards` | Create a tow yard. | PlatformAdmin |
| GET | `/tow-yards` | List tow yards (includes occupied_slot_count). | PlatformAdmin, EnforcementOfficer |
| POST | `/scofflaw-cases` | Open a scofflaw case for a vehicle. | PlatformAdmin, EnforcementOfficer |
| GET | `/scofflaw-cases/{id}` | Fetch a case; recomputes on read. | PlatformAdmin, EnforcementOfficer, HearingClerk, CollectionsAdmin, Owner |
| GET | `/scofflaw-cases` | List cases; filter by vehicle_id, owner_id, case_status. | PlatformAdmin, EnforcementOfficer, HearingClerk, CollectionsAdmin, Owner |
| POST | `/scofflaw-cases/{id}/place-hold` | Place a DMV registration hold. | EnforcementOfficer |
| POST | `/scofflaw-cases/{id}/release-hold` | Release a DMV registration hold. | CollectionsAdmin, EnforcementOfficer |
| POST | `/scofflaw-cases/{id}/violations` | File a citation against a case. | EnforcementOfficer |
| GET | `/violations/{id}` | Fetch a violation. | PlatformAdmin, EnforcementOfficer, HearingClerk, CollectionsAdmin, Owner |
| GET | `/violations` | List violations; filter by scofflaw_case_id, status. | PlatformAdmin, EnforcementOfficer, HearingClerk, CollectionsAdmin, Owner |
| POST | `/violations/{id}/disputes` | File a dispute against a violation. | Owner |
| GET | `/disputes/{id}` | Fetch a dispute. | PlatformAdmin, EnforcementOfficer, HearingClerk, CollectionsAdmin, Owner |
| GET | `/disputes` | List disputes; filter by violation_id, officer_id, status. | PlatformAdmin, EnforcementOfficer, HearingClerk, CollectionsAdmin, Owner |
| POST | `/disputes/{id}/schedule` | Schedule a hearing with an officer and window. | HearingClerk |
| POST | `/disputes/{id}/reschedule` | Move a scheduled hearing to a new window. | HearingClerk |
| POST | `/disputes/{id}/decide` | Record the hearing decision. | HearingClerk |
| POST | `/disputes/{id}/withdraw` | Owner withdraws a dispute. | Owner |
| POST | `/scofflaw-cases/{id}/payments` | Apply a payment (waterfall-allocated). | Owner |
| GET | `/payments/{id}` | Fetch a payment (immutable; includes allocation). | PlatformAdmin, EnforcementOfficer, CollectionsAdmin, Owner |
| GET | `/payments` | List payments; filter by scofflaw_case_id. | PlatformAdmin, EnforcementOfficer, CollectionsAdmin, Owner |
| POST | `/scofflaw-cases/{id}/payment-plans` | Create an installment plan (OCC on case version). | Owner |
| GET | `/payment-plans/{id}` | Fetch a payment plan. | PlatformAdmin, CollectionsAdmin, Owner |
| GET | `/payment-plans` | List payment plans; filter by scofflaw_case_id, status. | PlatformAdmin, CollectionsAdmin, Owner |
| POST | `/payment-plans/{id}/record-installment` | Record an installment payment. | Owner |
| POST | `/payment-plans/{id}/default` | Mark a plan defaulted. | CollectionsAdmin |
| POST | `/payment-plans/{id}/reinstate` | Reinstate a defaulted plan. | CollectionsAdmin |
| POST | `/scofflaw-cases/{id}/boot-tow-orders` | Dispatch a boot or tow (OCC on case version). | EnforcementOfficer |
| GET | `/boot-tow-orders/{id}` | Fetch a boot/tow order (includes release_fee_cents). | PlatformAdmin, EnforcementOfficer, Owner |
| GET | `/boot-tow-orders` | List orders; filter by scofflaw_case_id, tow_yard_id, status. | PlatformAdmin, EnforcementOfficer, Owner |
| POST | `/boot-tow-orders/{id}/apply` | Apply the boot/attach the tow (four-eyes). | EnforcementOfficer |
| POST | `/boot-tow-orders/{id}/pay-release-fee` | Pay the current release fee. | Owner |
| POST | `/boot-tow-orders/{id}/release` | Release the boot/tow. | EnforcementOfficer |
| POST | `/boot-tow-orders/{id}/cancel` | Cancel a dispatched order. | EnforcementOfficer |
| POST | `/scofflaw-cases/{id}/hardship-waivers` | Request a hardship waiver. | Owner |
| GET | `/hardship-waivers/{id}` | Fetch a hardship waiver. | PlatformAdmin, CollectionsAdmin, Owner |
| GET | `/hardship-waivers` | List hardship waivers; filter by scofflaw_case_id, status. | PlatformAdmin, CollectionsAdmin, Owner |
| POST | `/hardship-waivers/{id}/decide` | Approve or deny a hardship waiver. | CollectionsAdmin |
| POST | `/scofflaw-cases/{id}/collections-referrals` | Refer a case to a collections agency. | CollectionsAdmin |
| GET | `/collections-referrals/{id}` | Fetch a collections referral. | PlatformAdmin, CollectionsAdmin, Owner |
| GET | `/collections-referrals` | List collections referrals; filter by scofflaw_case_id, status. | PlatformAdmin, CollectionsAdmin, Owner |
| POST | `/collections-referrals/{id}/recall` | Recall a referral; violations return to OUTSTANDING. | CollectionsAdmin |
| POST | `/collections-referrals/{id}/settle` | Settle a referral; violations marked PAID. | CollectionsAdmin |
| GET | `/reports/scofflaw-summary` | Aggregate program report; filter by case_status. | PlatformAdmin, CollectionsAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_VALIDATION | 400 |
| ERR_OWNER_NOT_FOUND | 404 |
| ERR_VEHICLE_NOT_FOUND | 404 |
| ERR_CASE_NOT_FOUND | 404 |
| ERR_VIOLATION_NOT_FOUND | 404 |
| ERR_DISPUTE_NOT_FOUND | 404 |
| ERR_OFFICER_NOT_FOUND | 404 |
| ERR_TOW_YARD_NOT_FOUND | 404 |
| ERR_PLAN_NOT_FOUND | 404 |
| ERR_ORDER_NOT_FOUND | 404 |
| ERR_WAIVER_NOT_FOUND | 404 |
| ERR_REFERRAL_NOT_FOUND | 404 |
| ERR_PAYMENT_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_TERMINAL_STATE | 409 |
| ERR_VIOLATION_NOT_OUTSTANDING | 409 |
| ERR_CASE_NOT_SCOFFLAW | 409 |
| ERR_HOLD_ALREADY_PLACED | 409 |
| ERR_NO_HOLD_TO_RELEASE | 409 |
| ERR_ORDER_NOT_ACTIVE | 409 |
| ERR_PLAN_NOT_ACTIVE | 409 |
| ERR_DISPUTE_WINDOW_EXPIRED | 422 |
| ERR_DISPUTE_ALREADY_EXISTS | 409 |
| ERR_OFFICER_DOUBLE_BOOKED | 409 |
| ERR_TOW_YARD_FULL | 409 |
| ERR_BOOT_THRESHOLD_NOT_MET | 422 |
| ERR_TOW_THRESHOLD_NOT_MET | 422 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_RELEASE_FEE_UNPAID | 409 |
| ERR_BALANCE_OUTSTANDING | 409 |
| ERR_INSUFFICIENT_DOWN_PAYMENT | 422 |
| ERR_INVALID_PLAN_TERMS | 422 |
| ERR_OVERPAYMENT | 422 |
| ERR_NOT_YET_REFERABLE | 422 |
| ERR_REFERRAL_ALREADY_EXISTS | 409 |
| ERR_STALE_VERSION | 412 |
