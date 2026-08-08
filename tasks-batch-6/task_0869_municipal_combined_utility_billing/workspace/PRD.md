# Municipal Combined Utility Billing API — Product Requirements Document

## 1. Introduction

Municipalities that deliver water, sewer, electric, and refuse service on a single consolidated statement face a deceptively hard billing problem: one household's monthly charge is the sum of several independently metered utilities, each priced on its own tiered rate schedule, and all of it must roll up into a single account balance that collections, assistance, and finance teams can trust. This document specifies the REST API for such a combined municipal utility billing platform. The system is, at heart, two engines fused together — a **pricing engine** that turns meter readings into consolidated bills across four utilities, and a **ledger-and-collections engine** that tracks what each account owes, ages the debt, offers relief, and, when all else fails, transfers arrears to the property tax roll as a lien.

The platform serves six operational audiences whose duties are deliberately kept separate: billing specialists who open accounts and cut bills, meter technicians who record reads and perform field shutoffs, collections officers who manage delinquency and moratoria, assistance caseworkers who enroll relief programs and request bill corrections, supervisors who independently approve those corrections, and customers who view and pay their own accounts. Because a single payment or a single missed installment can cascade through meters, bills, shutoff orders, and account status simultaneously, the specification below is exacting about the order in which effects apply and the exact conditions under which each transition fires.

A note on determinism: every monetary figure is expressed in integer **cents**, every date/time is UTC, and the system runs against a controllable logical clock rather than wall-clock time so that delinquency aging and moratorium coverage can be exercised precisely. Implementers should treat the rounding discipline, the allocation ordering, and the state-transition preconditions in this document as the literal contract.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request (except the logical-clock setter described in §2.6) must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming that principal's role. If either header is missing or malformed, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well-formed but the named role is not permitted to invoke the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

There are exactly six roles, spelled precisely as follows: `BillingSpecialist`, `MeterTech`, `CollectionsOfficer`, `AssistanceCaseworker`, `Supervisor`, and `Customer`.

Five of these roles are **operator roles** whose `X-User-ID` is an opaque operator identifier not tied to any persisted entity. When `X-User-Role` is `BillingSpecialist`, `MeterTech`, `CollectionsOfficer`, `AssistanceCaseworker`, or `Supervisor`, the server treats `X-User-ID` as an operator handle: it may record that handle where a workflow captures it — for example, an adjustment's `requested_by` is set to the requesting `AssistanceCaseworker`'s `X-User-ID`, and its `approved_by` is set to the approving `Supervisor`'s `X-User-ID` — but it never compares that handle to any entity's `id`.

The `Customer` role is different: it is entity-backed. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Account`. Ownership checks on any resource that references an account compare that resource's `account_id` to `X-User-ID`; a customer may view and pay only their own account, bills, payments, arrangements, and plan.

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

List endpoints accept two query parameters, `limit` and `offset`. The `limit` defaults to 10, with a minimum of 1 and a maximum of 100; a requested limit above 100 is clamped to 100 and a value below 1 is treated as invalid. The `offset` defaults to 0 and has no upper bound. Results are ordered by `created_at` ascending unless a specific endpoint states otherwise. Each list response reports `limit`, `offset`, `total_count`, and `has_more` in its `meta` block, where `total_count` is the count of all matching records before pagination and `has_more` is true when records remain beyond the current page.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource carries a server-minted `id` that is a UUID with no type prefix. Most resources also carry three system-managed fields: `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and `version`, an integer that begins at 1 when the resource is created and increments by 1 on every mutation of that resource. The `created_at` value is fixed at creation; `updated_at` is refreshed on every mutation.

One entity is an exception: a `MeterReading` carries only `id` and `created_at`. It has no `updated_at` and no `version`, because a reading is an immutable append-only fact — once recorded it is never altered.

### 2.5. Monetary Precision and Rounding

All money is stored and returned as integer **cents**. Wherever a computation produces a fractional cent, the result is rounded **half up** (a value exactly halfway between two integers rounds to the larger magnitude). The rounding discipline for bills is strict and consequential: each per-service line charge is rounded to whole cents **first**, and only then are the rounded line charges summed. The system never sums fractional line charges and rounds once at the end. This "round-per-line-then-sum" order is the single most important precision rule in the pricing engine and is reiterated in §3.3. Where a calculation is a pure integer difference (for example, budget-billing true-up or deposit settlement), the result is exact and no rounding occurs.

### 2.6. The Logical Clock

The system does not read wall-clock time. All time-dependent logic — computing a bill's `due_date`, aging a bill toward delinquency, and checking whether a moratorium window covers a shutoff date — consults a logical clock. At server startup the clock reads exactly `2026-05-01T00:00:00Z` and holds that value until it is first set; it never falls back to wall-clock time. An administrative test-driving capability advances the clock to a supplied instant via the `to_iso8601` field. This capability is the only operation exempt from the authentication requirement in §2.1.

### 2.7. Optimistic Concurrency Control

Creating a payment arrangement is guarded by optimistic concurrency on the parent account. A `POST /accounts/{id}/payment-arrangements` request must carry `expected_account_version` as a non-optional field, holding the client's last observed `version` of the target `Account`. If that value does not equal the account's current `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412). The rationale is that a newly created arrangement legitimately supersedes the account's prior `ACTIVE` arrangement; a caseworker acting on a stale account view — one captured before another writer advanced the account's version (for instance, by enrolling assistance or by creating a competing arrangement) — would otherwise silently discard an arrangement it never observed. No other endpoint takes a version field.

### 2.8. Cascading Recomputation and Hierarchical Consistency

The `Account` is the aggregate root. Its balance fields are always derived, never directly set by clients. Specifically, `current_balance_cents` is the sum, over the account's bills, of each bill's `total_due_cents` minus its `amount_paid_cents`, adjusted by any budget-billing levelization true-up charge or credit and reduced by deposit credit applied at finalize. `delinquent_balance_cents` is the sum, over only those bills whose `collection_status` is `DELINQUENT`, of `total_due_cents` minus `amount_paid_cents`. `deposit_on_hand_cents` is the sum of `amount_cents` across the account's deposits whose `status` is `HELD`. These three figures are recomputed on every side effect that could move them — bill generation, payment, payment reversal, adjustment approval, arrangement default, mark-delinquent, true-up, and finalize.

When an operation mutates a resource, that resource's `updated_at` is refreshed and its `version` incremented; when the same operation cascades into a second resource, the second resource's `updated_at` and `version` are likewise updated. Several operations in this domain touch more than one entity in a single call, and every such cascade is specified explicitly in §3; implementers must apply all links of a cascade, not merely the primary effect.

### 2.9. Nested Resource Path Validation

Many resources are addressed through a parent path — a meter's readings hang under the meter, an account's bills and payments hang under the account, a bill's adjustments hang under the bill. Path parameters are validated left to right. If a path-referenced `Account` does not exist, the response is `ERR_ACCOUNT_NOT_FOUND` (404); a missing `Meter` yields `ERR_METER_NOT_FOUND` (404); a missing `Bill` yields `ERR_BILL_NOT_FOUND` (404); a missing `RateSchedule` yields `ERR_RATE_SCHEDULE_NOT_FOUND` (404); and a missing adjustment, payment arrangement, shutoff order, lien transfer, or budget-billing plan yields `ERR_RESOURCE_NOT_FOUND` (404). The outermost path segment is checked first, so a request naming a nonexistent account under one of its sub-collections fails with the account error before any child is consulted.

### 2.10. Segregation of Duties

Bill adjustments enforce a four-eyes control. The `AssistanceCaseworker` who requests an adjustment is recorded as its `requested_by`. Approval or rejection of that adjustment is reserved for a `Supervisor`, and the approving supervisor's `X-User-ID` must differ from the recorded `requested_by`; the deciding supervisor is recorded as `approved_by`. If the acting `X-User-ID` on an approve or reject equals `requested_by`, the request is rejected with `ERR_SOD_VIOLATION` (HTTP 403).

### 2.11. Validation Ordering and Error Precedence

When several checks could fail on one request, they are evaluated in a fixed precedence so that the returned `error_id` is deterministic. Authentication (`ERR_UNAUTHENTICATED`, 401) is checked first, then role authorization (`ERR_UNAUTHORIZED`, 403), then existence of every path-referenced resource (the 404 family in §2.9). Only after a resource is known to exist are state preconditions evaluated: a transition attempted from an invalid current state yields `ERR_INVALID_STATE` (409); an attempt to mutate an account that is `FINALED` or `LIEN_TRANSFERRED` yields `ERR_ACCOUNT_NOT_ACTIVE` (409); marking an already-`PAID` bill delinquent yields `ERR_BILL_ALREADY_PAID` (409). Business-safety checks come next — segregation of duties (`ERR_SOD_VIOLATION`) and moratorium enforcement (`ERR_MORATORIUM_ACTIVE`) — followed by referential-business checks (`ERR_NO_ACTIVE_PLAN`, `ERR_NO_DELINQUENT_BALANCE`, `ERR_INSUFFICIENT_ARREARS`), temporal checks (`ERR_PERIOD_OVERLAP`, `ERR_MORATORIUM_OVERLAP`), field constraints (`ERR_READING_REGRESSION`, `ERR_VALIDATION`), and finally the fiscal checks (`ERR_PAYMENT_EXCEEDS_BALANCE`) and the concurrency check (`ERR_STALE_VERSION`). Within an endpoint, a check earlier in this ordering masks a later one: for example, a caller lacking permission is told `ERR_UNAUTHORIZED` even if the target resource also does not exist.

## 3. Business Logic & Workflows

### 3.1. Rate Schedules and Account Onboarding

The pricing engine is fed by **rate schedules**. A billing specialist defines a schedule for one utility by supplying its `service_type` — one of `WATER`, `SEWER`, `ELECTRIC`, or `REFUSE` — and its metering `unit`, one of `GALLON`, `KWH`, or `FLAT`. Every schedule carries a `fixed_charge_cents` (a flat monthly service charge, at least 0 cents, added into a line before that line is rounded), an `effective_date` marking when the schedule becomes usable, and an `active` flag (defaulting to true) governing whether the schedule may be selected during bill generation. Volumetric utilities carry an ordered `tiers` array of marginal blocks, each block naming an `upper_bound_units` and a `rate_cents_per_1000`; the blocks are ordered ascending by bound and the final block must have a null `upper_bound_units`, signifying "everything above the previous bound." Flat and sewer schedules leave `tiers` empty. A sewer schedule instead carries `sewer_rate_cents_per_1000` — the volumetric rate charged against the account's water consumption — and `sewer_cap_units`, the ceiling on billable water gallons; both are null on non-sewer schedules. When a bill is generated, the schedule chosen for each service line is the active schedule for that `service_type` whose `effective_date` is on or before the bill's `period_start`; where more than one qualifies, the one with the latest `effective_date` governs. Fetching a schedule that does not exist returns `ERR_RATE_SCHEDULE_NOT_FOUND`.

A billing specialist opens an account by supplying the `account_holder_name`, the `service_address` (which doubles as the tax-parcel key should arrears ever transfer to a lien), and the `occupant_type`, either `RESIDENTIAL` or `COMMERCIAL`. An optional `prior_annual_charges_cents` (defaulting to 0) seeds later budget-billing levelization. A freshly opened account begins in `status` `ACTIVE` with `version` 1, with `assistance_program` null, `assistance_discount_pct` 0, and all of `current_balance_cents`, `delinquent_balance_cents`, `deposit_on_hand_cents` at 0 and `move_out_date` null. Accounts may be listed with an optional `status` filter and standard pagination. Any mutating operation attempted against an account that has reached `FINALED` or `LIEN_TRANSFERRED` is refused with `ERR_ACCOUNT_NOT_ACTIVE`.

### 3.2. Service Meters and Readings

A billing specialist attaches a service line to an account by adding a meter, naming its `service_type` and optionally an `estimated_monthly_units` (defaulting to 0) that will serve as fallback consumption. Each meter tracks an `account_id` linking it to its account and a `status` that is `ACTIVE` while billable and `REMOVED` once service ends. Meters for an account are reverse-reachable through the account, and a single meter may be fetched directly.

A meter technician records a reading against a meter by supplying the `read_date`, the `reading_value` (the cumulative index on the dial, which must be at least 0), and the `read_type`, either `ACTUAL` for a field read or `ESTIMATED` for an estimate. Each reading carries a `meter_id` binding it to its meter. Readings are append-only and immutable. One integrity rule governs field reads: a new `ACTUAL` reading's `reading_value` must be at least as large as the meter's latest existing `reading_value` — dials do not run backward — and a regression is rejected with `ERR_READING_REGRESSION`. Readings for a meter are reverse-reachable through that meter.

### 3.3. Consolidated Bill Generation — the Pricing Engine

Generating a consolidated bill is the platform's central operation. A billing specialist requests a bill for a service period defined by `period_start` (inclusive) and `period_end` (exclusive); an optional `budget_billed` flag (defaulting to false) selects budget billing, discussed in §3.4. Before anything is priced, the proposed period is checked for conflict: the half-open interval from `period_start` up to `period_end` must not overlap any existing bill on the account. Because the interval is half-open, a new period may begin exactly where a prior period ended without conflict, but any true overlap is rejected with `ERR_PERIOD_OVERLAP`. The bill's `due_date` is set to its `period_end` plus 20 days.

Consumption is determined per active meter. For a **metered** utility (`WATER` or `ELECTRIC`), the meter's readings are ordered by `read_date` ascending, breaking ties by `created_at` ascending. If the latest reading is `ESTIMATED`, or if the meter has no readings at all, the line falls back to the meter's `estimated_monthly_units` and the line is flagged estimated; this is the **estimated-read variant**. Otherwise the latest reading is `ACTUAL`, and consumption is that latest `reading_value` minus the immediately prior reading's value (or minus 0 when there is only one reading); this is the **actual-read variant**. The two variants generally yield different totals because the estimated variant ignores the dial entirely and bills the flat monthly estimate. A `SEWER` line takes its consumption from the account's water consumption for the period (detailed below), and a `REFUSE` line has zero consumption and bills purely as a flat charge.

A **metered line** is priced by marginal block pricing over the schedule's tiers. Walking the tiers from lowest bound upward, the units falling into each block — that is, the portion of consumption above the previous block's bound and up to this block's bound — are multiplied by that block's `rate_cents_per_1000` and divided by 1000, and these block amounts are accumulated into a raw volumetric charge; the final unbounded tier catches all remaining units. The line charge is then the `fixed_charge_cents` plus that raw volumetric amount, rounded half up to whole cents once for the line. Under the test water schedule, the first 6,000 gallons are priced at 315 cents per 1,000 gallons, the next block up to 12,000 gallons (the 6,000 gallons above 6,000) at 500 cents per 1,000 gallons, and every gallon beyond 12,000 at 800 cents per 1,000 gallons. Under the test electric schedule, the first 500 kWh are priced at 12,000 cents per 1,000 kWh and every kWh beyond 500 at 18,000 cents per 1,000 kWh.

The **sewer line** is a capped volumetric charge on water. Billable sewer volume is the account's water consumption for the period but no greater than `sewer_cap_units`; that billable volume divided by 1,000 and multiplied by `sewer_rate_cents_per_1000` gives the raw sewer charge, to which `fixed_charge_cents` is added and the sum rounded half up once. Under the test sewer schedule, the rate is 250 cents per 1,000 gallons and the cap is 10,000 gallons. The **refuse line** is simply its schedule's flat `fixed_charge_cents`.

Each per-service result is recorded in the bill's `line_charges` array as an entry naming the `service_type`, the `consumption_units` billed, and the rounded `charge_cents`. The bill's `pre_discount_total_cents` is the sum of those already-rounded line charges — round each line, then sum. The bill's `read_basis` is `ESTIMATED` if any metered line fell back to its estimate and `ACTUAL` only when every metered line used an actual delta. An assistance discount, if the account carries one, produces `assistance_credit_cents` equal to the account's `assistance_discount_pct` multiplied by `pre_discount_total_cents`, rounded half up; with no assistance this credit is 0. The bill's `actual_charges_cents` is `pre_discount_total_cents` minus `assistance_credit_cents` — the true metered cost regardless of budget billing. For an ordinary bill, `total_due_cents` equals `actual_charges_cents`. A newly generated bill starts with `amount_paid_cents` 0, `payment_status` `UNPAID`, and `collection_status` `CURRENT`, and generating it recomputes the account's balances.

### 3.4. Assistance Enrollment and Budget Billing

An assistance caseworker enrolls an account in relief by supplying a `program` — one of `LIHEAP`, `LIFELINE`, or `SENIOR` — and a fractional `discount_pct`. Enrollment writes the account's `assistance_program` and `assistance_discount_pct` and increments the account's `version` by 1. From that point, every bill's `assistance_credit_cents` is computed against the pre-discount total as described in §3.3.

Budget billing levels a customer's payments across a year. When a billing specialist enrolls an account by supplying a `plan_year`, the plan's `monthly_budget_cents` is computed as the account's `prior_annual_charges_cents` divided by 12, rounded half up, and the plan opens in `status` `ACTIVE`. The plan tracks its `account_id`, a running `cumulative_budgeted_cents`, a running `cumulative_actual_cents`, and a `deferred_balance_cents` that is 0 until true-up. Each time a bill is generated with `budget_billed` true, that bill's `total_due_cents` is set to the plan's `monthly_budget_cents` rather than to the actual metered cost — the actual charge is deferred — and the plan accrues: `cumulative_budgeted_cents` grows by `monthly_budget_cents` and `cumulative_actual_cents` grows by that bill's `actual_charges_cents`. A budget-billed bill requires an `ACTIVE` plan on the account; requesting one without such a plan is rejected with `ERR_NO_ACTIVE_PLAN`. Plans for an account are reverse-reachable through the account.

Levelization reconciles the two running sums. When a billing specialist trues up an `ACTIVE` plan, its `deferred_balance_cents` is set to `cumulative_actual_cents` minus `cumulative_budgeted_cents` — positive when the customer under-paid relative to true cost, negative when they over-paid — the plan advances `ACTIVE → TRUED_UP`, and the account's `current_balance_cents` is adjusted by that deferred balance (a charge when positive, a credit when negative). A plan still `ACTIVE` when its account is finalized is instead moved `ACTIVE → CANCELLED`, its deferred balance settled into the final bill.

### 3.5. Payments, Allocation, and Reversal

A customer (on their own account) or a billing specialist records a payment by supplying an `amount_cents` (which must be greater than 0), a `method` — one of `CASH`, `CARD`, `ACH`, or `CHECK` — and optionally a `payment_date`, which defaults to the current logical clock when omitted. Each payment records its `account_id` and opens in `status` `POSTED`.

Payments are applied by a strict **oldest-first waterfall**. The candidate bills are the account's bills whose `payment_status` is `UNPAID` or `PARTIAL` and whose `collection_status` is not `IN_LIEN`, ordered by `period_end` ascending and breaking ties by `created_at` ascending — never by `id`. The payment's remaining amount is walked across the candidates: for each bill, the amount taken is the smaller of the remaining payment and that bill's outstanding balance (`total_due_cents` minus `amount_paid_cents`); the taken amount is added to the bill's `amount_paid_cents` and recorded as an entry in the payment's `allocation` array naming the `bill_id` and the `applied_cents`; the remaining payment shrinks accordingly and the walk stops once the payment is exhausted. If any amount remains after every candidate has been filled, the whole payment is rejected with `ERR_PAYMENT_EXCEEDS_BALANCE`. As each bill absorbs money, its `payment_status` advances: a bill goes `UNPAID → PARTIAL` when it receives a positive amount short of its full balance, `PARTIAL → PAID` when a later allocation covers the remainder, and `UNPAID → PAID` when a single allocation covers the whole balance at once.

Payment also drives collections recovery. When an allocation drives a `DELINQUENT` bill's balance to 0, that bill returns `collection_status` `DELINQUENT → CURRENT`. When a payment reduces the account's `delinquent_balance_cents` to 0, any `SCHEDULED` shutoff order for the account is cancelled and the account recovers — `DELINQUENT → ACTIVE`, or `SHUTOFF → ACTIVE` with its previously removed water and electric meters restored from `REMOVED` back to `ACTIVE`. Every payment recomputes the account's balances. Payments for an account are reverse-reachable through the account.

A billing specialist may reverse a posted payment as a compensating action. Reversal moves the payment `POSTED → REVERSED`, and each allocation it made is unwound: the reversed `applied_cents` is subtracted from each affected bill's `amount_paid_cents`, that bill's `payment_status` is recomputed, and the account's receivable is restored to its pre-payment value. A bill that had been fully satisfied by the reversed payment moves `PAID → PARTIAL` as its balance reopens. Only a payment currently in `POSTED` status may be reversed.

### 3.6. Delinquency, Shutoff, and Moratoria

A bill ages toward collections independently of how much has been paid on it; the payment axis (`UNPAID`, `PARTIAL`, `PAID`) and the collections axis (`CURRENT`, `DELINQUENT`, `IN_LIEN`) evolve on separate tracks. A collections officer marks a bill delinquent only when it is not yet `PAID`, is currently `CURRENT`, and at least 21 days have elapsed since its `due_date` as measured against the logical clock. Marking too early — before the 21-day grace has fully elapsed — is refused with `ERR_NOT_YET_DELINQUENT`, and attempting to mark an already-`PAID` bill is refused with `ERR_BILL_ALREADY_PAID`. A successful mark moves the bill `CURRENT → DELINQUENT`, bubbles the account `ACTIVE → DELINQUENT`, and recomputes the account's `delinquent_balance_cents` as the sum over all `DELINQUENT` bills of their outstanding balance. Operations that require a bill already in delinquent collection status but find it otherwise are refused with `ERR_BILL_NOT_DELINQUENT`.

A collections officer schedules a shutoff for a delinquent account by supplying a `scheduled_date` and an optional `reason` (defaulting to `DELINQUENCY`, the alternative being `ARRANGEMENT_DEFAULT`). Scheduling requires the account to be `DELINQUENT` with a positive delinquent balance; otherwise the request is refused with `ERR_NO_DELINQUENT_BALANCE`. A manually scheduled order records `origin` `MANUAL` and opens in `status` `SCHEDULED`. Shutoff orders for an account are reverse-reachable through the account with an optional `status` filter.

A meter technician executes a scheduled shutoff in the field. Execution requires the order to be `SCHEDULED` and the account to still be `DELINQUENT` with a positive delinquent balance — if the account has since cured, execution is refused with `ERR_NO_DELINQUENT_BALANCE`. Critically, execution is blocked by any protective **moratorium**: if an `ACTIVE` moratorium window — either a `SYSTEM`-scoped window or an `ACCOUNT`-scoped window for this account — covers the order's `scheduled_date`, the execution is refused with `ERR_MORATORIUM_ACTIVE`. A moratorium covers a date when its closed range from `start_date` through `end_date`, inclusive of both ends, contains the scheduled date. A permitted execution moves the order `SCHEDULED → EXECUTED`, transitions the account `DELINQUENT → SHUTOFF`, and removes the account's water and electric meters (`ACTIVE → REMOVED`).

A collections officer creates a moratorium window by supplying its `scope` (`SYSTEM` for all accounts or `ACCOUNT` for a single account), a `start_date`, an `end_date`, a `reason` (`WEATHER`, `MEDICAL`, or `LEGISLATIVE`), and, for an account-scoped window, the `account_id` it protects (null for system scope). Windows are created in `status` `ACTIVE` and remain enforced across their date range. Because system moratoria protect everyone, a new `SYSTEM` window may not overlap or even touch an existing `ACTIVE` `SYSTEM` window: treated as closed date ranges, two system windows conflict whenever they share any day — including the case where one ends on the very day the other begins — and such a conflict is refused with `ERR_MORATORIUM_OVERLAP`. (This closed-range treatment is deliberately stricter than the half-open bill-period rule, where abutting boundaries are allowed.) Account-scoped windows for an account are reverse-reachable through the account, and any window may be fetched directly.

### 3.7. Payment Arrangements

An assistance caseworker offers a delinquent customer an installment plan by creating a payment arrangement, supplying the `total_arranged_cents` to spread (greater than 0), the `installment_count` (at least 2), and the `expected_account_version` that guards the create under optimistic concurrency (§2.7). The arrangement's `installment_amount_cents` is the total divided by the installment count, rounded half up. Creating an arrangement supersedes any prior `ACTIVE` arrangement on the account — the prior one moves `ACTIVE → SUPERSEDED` — the new arrangement opens `ACTIVE`, and the account's `version` increments by 1. Arrangements for an account are reverse-reachable through the account with an optional `status` filter.

Missed installments trigger a three-link default cascade. When a collections officer records a missed installment against an `ACTIVE` arrangement, the arrangement moves `ACTIVE → DEFAULTED`; the account moves `ACTIVE → DELINQUENT`; the account's `UNPAID` and `PARTIAL` bills move `collection_status` `CURRENT → DELINQUENT` (driving the recompute of `delinquent_balance_cents`); and a `CASCADE`-origin shutoff order is auto-created in `status` `SCHEDULED` for the account. All three links apply together.

A defaulted arrangement can be reinstated. When an assistance caseworker reinstates a `DEFAULTED` arrangement, it moves `DEFAULTED → ACTIVE`, any `SCHEDULED` `CASCADE` shutoff order created by that default is cancelled (`SCHEDULED → CANCELLED`), and — if the arrangement covers the account's arrears — the account recovers `DELINQUENT → ACTIVE`. This reinstatement loop between `ACTIVE` and `DEFAULTED` may repeat.

### 3.8. Bill Adjustments — Leak, Estimate, and Goodwill Relief

An assistance caseworker requests an adjustment against a specific bill, identifying the `bill_id` and naming the `adjustment_type`: `LEAK` for leak relief, `ESTIMATE_CORRECTION` to re-bill an estimate against actual reads, or `GOODWILL` for a flat courtesy credit. The request may carry a `relief_method` (used only for leaks), a `baseline_units` figure (the customer's normal non-leak consumption, defaulting to 0), and a `goodwill_amount_cents` (used only for goodwill, defaulting to 0). The requesting caseworker is recorded as `requested_by`, the adjustment's `credit_cents` starts at 0, `approved_by` starts null, and the adjustment opens in `status` `REQUESTED`. Adjustments for a bill are reverse-reachable through the bill.

A supervisor decides the adjustment, and the segregation-of-duties rule of §2.10 applies to both approval and rejection: the deciding `X-User-ID` must differ from `requested_by`, else `ERR_SOD_VIOLATION`. Rejecting an adjustment moves it `REQUESTED → REJECTED` with no financial effect and its `credit_cents` remaining 0. Approving an adjustment moves it `REQUESTED → APPROVED`, computes its `credit_cents`, adds that credit to the target bill's `amount_paid_cents`, and recomputes the account's balances.

The credit computation depends on the adjustment type. For a `GOODWILL` adjustment, the credit is simply the requested `goodwill_amount_cents`. For an `ESTIMATE_CORRECTION`, the credit is the bill's `actual_charges_cents` minus the actual charges recomputed from true reads, floored at 0 (never negative). For a `LEAK`, the excess is the bill's water consumption minus `baseline_units`, floored at 0, and the credit depends on the `relief_method`. Under `SEWER_RELIEF`, the credit is the sewer volumetric rate applied to the excess only — the excess gallons divided by 1,000, multiplied by 250 cents per 1,000 gallons, rounded half up. Under `TIER_REPRICE`, the excess gallons are first charged at the actual marginal water tiers they occupied — the charge over the gallons above `baseline_units` up to the current water consumption, computed with the water tier schedule and rounded half up — and then repriced by charging all of those excess gallons at the lowest water tier rate of 315 cents per 1,000 gallons, rounded half up; the credit is the first (actual tiered) amount minus the second (repriced) amount. For the same excess, these two relief methods generally produce different credits.

### 3.9. Move-Out Finalization, Deposit Settlement, and Lien Transfer

Deposits protect the municipality against unpaid final bills. A billing specialist collects a deposit by supplying an `amount_cents` (greater than 0) and a `reason` (`NEW_SERVICE`, `DELINQUENCY`, or `COMMERCIAL`). A deposit records its `account_id`, opens in `status` `HELD` with `applied_cents` and `refunded_cents` both 0, and raises the account's `deposit_on_hand_cents`. Deposits for an account are reverse-reachable through the account. Attempting to settle a deposit that is already `APPLIED` or `REFUNDED` is refused with `ERR_DEPOSIT_ALREADY_SETTLED`.

Finalization closes an account on move-out and may be invoked while the account is `ACTIVE`, `DELINQUENT`, or `SHUTOFF`. A billing specialist supplies the final `period_start` and `period_end`. The operation runs as a chain: first a final bill is generated for the account's active meters over that closing period, priced exactly as in §3.3; then any still-`ACTIVE` budget-billing plan is cancelled with its deferred balance settled into that final bill; then the account's `HELD` deposits are settled against the final outstanding balance. Deposit settlement walks the held deposits oldest first by `created_at`: for each deposit, the amount applied is the smaller of the deposit's `amount_cents` and the remaining final balance, the remainder of the deposit is refunded, and the applied amount reduces the running final balance. A deposit that contributes any money moves `HELD → APPLIED` with `applied_cents` set to the applied portion and `refunded_cents` to the rest; a deposit against a fully satisfied balance moves `HELD → REFUNDED` with its whole `amount_cents` refunded and `applied_cents` 0. In every case a deposit's `amount_cents` equals its `applied_cents` plus its `refunded_cents`. Applied deposit money is added to the final bill's `amount_paid_cents`, and when a deposit exceeds the balance a refund payment is issued for the difference. Finalization then sets the account's `move_out_date` to the current clock, removes the account's meters (`status → REMOVED`), transitions the account to `FINALED`, and increments the account's `version`.

For accounts that never cure, arrears can be transferred to the property tax roll as a lien. A collections officer initiates a transfer by supplying the `tax_parcel_ref` that will receive the lien; initiation requires the account's `delinquent_balance_cents` to be at least 10,000 cents, otherwise `ERR_INSUFFICIENT_ARREARS`. The transfer records its `account_id`, opens in `status` `PENDING`, and its `amount_cents` will snapshot the delinquent balance at certification. Lien transfers for an account are reverse-reachable through the account with an optional `status` filter. Certification then posts the lien: it requires the transfer to be `PENDING` (an out-of-state attempt yields `ERR_INVALID_STATE`), the account to be in `DELINQUENT` or `SHUTOFF` status, and the delinquent balance to still be at least 10,000 cents (else `ERR_INSUFFICIENT_ARREARS`). On certification the transfer's `amount_cents` snapshots the account's current delinquent balance and the transfer advances `PENDING → CERTIFIED`; posting to tax then advances `CERTIFIED → TRANSFERRED`, moves the account to `LIEN_TRANSFERRED`, and moves the account's delinquent bills `collection_status` `DELINQUENT → IN_LIEN`. A bill in `IN_LIEN` is frozen and no longer accepts payment allocation.

## 4. Endpoint Definitions

All endpoints return the standard envelope of §2.2. Creating a new resource returns HTTP 201; operations that modify or transition an existing resource, and all reads, return HTTP 200. Request bodies, response payloads, and side effects are intentionally omitted from this table — reconstruct them from the workflow narratives in §3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/rate-schedules` | Create a rate schedule for a utility. | BillingSpecialist |
| GET | `/rate-schedules/{id}` | Fetch a rate schedule. | BillingSpecialist, CollectionsOfficer, AssistanceCaseworker, MeterTech, Supervisor |
| POST | `/accounts` | Open a utility account (starts ACTIVE). | BillingSpecialist |
| GET | `/accounts/{id}` | Fetch an account with computed balances. | BillingSpecialist, CollectionsOfficer, AssistanceCaseworker, MeterTech, Supervisor, Customer |
| GET | `/accounts` | List accounts (paginated). | BillingSpecialist, CollectionsOfficer, AssistanceCaseworker |
| POST | `/accounts/{id}/assistance` | Enroll the account in an assistance program. | AssistanceCaseworker |
| POST | `/accounts/{id}/finalize` | Move-out finalize: final bill, settle deposits, remove meters. | BillingSpecialist |
| POST | `/accounts/{id}/meters` | Add a service meter to an account. | BillingSpecialist |
| GET | `/accounts/{id}/meters` | List meters for an account. | BillingSpecialist, MeterTech, CollectionsOfficer, AssistanceCaseworker |
| GET | `/meters/{id}` | Fetch a meter. | BillingSpecialist, MeterTech |
| POST | `/meters/{id}/readings` | Record a meter reading. | MeterTech |
| GET | `/meters/{id}/readings` | List readings for a meter. | BillingSpecialist, MeterTech |
| POST | `/accounts/{id}/bills` | Generate a consolidated bill for a service period. | BillingSpecialist |
| GET | `/bills/{id}` | Fetch a bill. | BillingSpecialist, CollectionsOfficer, AssistanceCaseworker, Customer |
| GET | `/accounts/{id}/bills` | List bills for an account. | BillingSpecialist, CollectionsOfficer, AssistanceCaseworker, Customer |
| POST | `/bills/{id}/mark-delinquent` | Mark a past-grace unpaid bill delinquent. | CollectionsOfficer |
| POST | `/accounts/{id}/payments` | Record a payment; waterfall-allocate oldest bill first. | BillingSpecialist, Customer |
| GET | `/accounts/{id}/payments` | List payments for an account. | BillingSpecialist, CollectionsOfficer, Customer |
| POST | `/payments/{id}/reverse` | Reverse a posted payment. | BillingSpecialist |
| POST | `/accounts/{id}/budget-billing-plan` | Enroll account in budget billing. | BillingSpecialist |
| GET | `/accounts/{id}/budget-billing-plan` | List budget billing plans for an account. | BillingSpecialist, CollectionsOfficer, Customer |
| POST | `/budget-billing-plans/{id}/true-up` | Levelize: reconcile cumulative actual vs budgeted. | BillingSpecialist |
| POST | `/accounts/{id}/deposits` | Collect a deposit (HELD). | BillingSpecialist |
| GET | `/accounts/{id}/deposits` | List deposits for an account. | BillingSpecialist, CollectionsOfficer |
| POST | `/accounts/{id}/payment-arrangements` | Create a payment arrangement (OCC on account version). | AssistanceCaseworker |
| GET | `/accounts/{id}/payment-arrangements` | List payment arrangements for an account. | AssistanceCaseworker, CollectionsOfficer, Customer |
| POST | `/payment-arrangements/{id}/record-missed` | Record a missed installment (triggers default cascade). | CollectionsOfficer |
| POST | `/payment-arrangements/{id}/reinstate` | Reinstate a defaulted arrangement. | AssistanceCaseworker |
| POST | `/bills/{id}/adjustments` | Request a bill adjustment (leak/estimate/goodwill). | AssistanceCaseworker |
| GET | `/bills/{id}/adjustments` | List adjustments for a bill. | AssistanceCaseworker, BillingSpecialist, Supervisor |
| POST | `/adjustments/{id}/approve` | Approve an adjustment; compute and apply credit. | Supervisor |
| POST | `/adjustments/{id}/reject` | Reject an adjustment (no financial effect). | Supervisor |
| POST | `/accounts/{id}/shutoff-orders` | Schedule a shutoff for a delinquent account. | CollectionsOfficer |
| GET | `/accounts/{id}/shutoff-orders` | List shutoff orders for an account. | CollectionsOfficer, MeterTech |
| POST | `/shutoff-orders/{id}/execute` | Execute a scheduled shutoff (blocked by moratorium). | MeterTech |
| POST | `/accounts/{id}/lien-transfers` | Initiate a lien transfer of arrears to the tax roll. | CollectionsOfficer |
| GET | `/accounts/{id}/lien-transfers` | List lien transfers for an account. | CollectionsOfficer, BillingSpecialist |
| POST | `/lien-transfers/{id}/certify` | Certify then post the lien to tax. | CollectionsOfficer |
| POST | `/moratorium-windows` | Create a shutoff moratorium window (SYSTEM or ACCOUNT). | CollectionsOfficer |
| GET | `/accounts/{id}/moratorium-windows` | List moratorium windows scoped to an account. | CollectionsOfficer, MeterTech |
| GET | `/moratorium-windows/{id}` | Fetch a moratorium window. | CollectionsOfficer, MeterTech |
| POST | `/_clock/set_current_utc` | Test-driving logical clock setter. | BillingSpecialist, CollectionsOfficer, MeterTech, AssistanceCaseworker, Supervisor |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_ACCOUNT_NOT_FOUND | 404 |
| ERR_METER_NOT_FOUND | 404 |
| ERR_BILL_NOT_FOUND | 404 |
| ERR_RATE_SCHEDULE_NOT_FOUND | 404 |
| ERR_RESOURCE_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_ACCOUNT_NOT_ACTIVE | 409 |
| ERR_BILL_ALREADY_PAID | 409 |
| ERR_BILL_NOT_DELINQUENT | 409 |
| ERR_NOT_YET_DELINQUENT | 409 |
| ERR_SOD_VIOLATION | 403 |
| ERR_MORATORIUM_ACTIVE | 403 |
| ERR_NO_ACTIVE_PLAN | 409 |
| ERR_NO_DELINQUENT_BALANCE | 409 |
| ERR_INSUFFICIENT_ARREARS | 409 |
| ERR_PERIOD_OVERLAP | 409 |
| ERR_MORATORIUM_OVERLAP | 409 |
| ERR_READING_REGRESSION | 422 |
| ERR_VALIDATION | 422 |
| ERR_PAYMENT_EXCEEDS_BALANCE | 422 |
| ERR_STALE_VERSION | 412 |
| ERR_DEPOSIT_ALREADY_SETTLED | 409 |
