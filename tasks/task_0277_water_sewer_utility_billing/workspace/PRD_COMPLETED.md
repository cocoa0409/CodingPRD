# Water Sewer Utility Billing API — Product Requirements Document

## 1. Introduction

This document specifies the Water & Sewer Utility Billing API, a back-office platform that turns raw meter telemetry into defensible monthly bills and manages the full collections lifecycle that follows. A municipal water utility must reconcile several moving parts at once: cumulative odometer readings arriving from Advanced Metering Infrastructure (AMI) and from manual field reads; a tiered, marginal water-consumption price book; a sewer charge that is derived from potable consumption rather than measured directly; second (irrigation) meters that draw water but never discharge to the sewer; and a patchwork of consumer-protection programs — leak forgiveness, budget billing, low-income assistance, and cold-weather shutoff moratoriums — that each bend the arithmetic in their own way.

The platform exists to make those interactions deterministic. Every charge a customer sees must be reproducible from the meter reads, the governing rate schedule, and the account's enrollment state; every collections action — a late fee, a scheduled shutoff, a service suspension, a reconnect fee — must be traceable to an explicit rule and an explicit operator role. The account itself carries two independent dimensions of status: a **financial standing** that tracks whether the account is current or in arrears, and a **physical service** dimension that tracks whether water is flowing. These two axes move on their own clocks, and a great deal of the system's behavior lives in keeping them consistent without conflating them.

Four operator roles share the system. Back-office billing staff own the price book, account creation, meter and read ingestion, billing cycles, and bill generation. Field operations staff own the physical acts of shutoff, execution, reconnection, and cancellation. Caseworkers own assistance enrollment and leak adjudication. And the account holder — the customer — can read their own data, enroll in budget billing, make payments, and request leak credits. The remainder of this document defines the contracts, the cross-cutting principles, and the detailed workflows that bind these actors together.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contracts, and cross-cutting principles that govern every endpoint. Domain-specific workflows are detailed in Section 3.

### 2.1. User and Role-Based Access Control

Every request must carry two authentication headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the operational capacity under which the request is made. If `X-User-Role` is missing or does not name one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`. If the header names a valid role but that role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes exactly four roles: `BillingClerk`, `FieldOps`, `AssistanceCaseworker`, and `Customer`.

Three of these roles are operator identities not tied to any persisted entity. When `X-User-Role` is `BillingClerk`, `X-User-ID` is an opaque operator identifier; the server may record it but does not compare it to any entity's `id`. The same holds for `FieldOps` and for `AssistanceCaseworker`: in each case `X-User-ID` is an opaque operator identifier, recorded if useful but never matched against a stored entity.

The `Customer` role is different: it is entity-backed by an account. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Account`. Ownership checks on any resource that references an account compare that resource's account foreign key (its `account_id`, or for resources reached through a bill, the account behind that bill) to `X-User-ID`. A customer who attempts to read or write a resource belonging to a different account is rejected with `ERR_NOT_RESOURCE_OWNER`. This ownership constraint applies to every customer-scoped read and write — fetching an account, its bills, meters, reads, payments, budget plans, leak adjustments, and shutoff orders, as well as the customer-initiated writes (budget-billing enrollment, payments, and leak-adjustment requests).

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with no upper bound. A `limit` below 1 or above 100, or a negative `offset`, is rejected with `ERR_VALIDATION_LIMIT`.

Unless a particular endpoint states otherwise, list results are sorted by their creation timestamp (`created_at`) in ascending order.

Every list response includes the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the response envelope's `meta` object.

### 2.4. Common Resource Properties and the Two Status Axes

Most resources in this system are full first-class records that carry a standard set of system-managed properties: an `id` (a server-minted UUID, with no type prefix), a `created_at` timestamp (ISO 8601 UTC with three fractional digits), an `updated_at` timestamp in the same format that advances on every mutation, and a `version` integer that begins at 1 and increments by one on every mutation. The `RateSchedule`, `Account`, `Meter`, `BillingCycle`, `Bill`, `BudgetBillingPlan`, `AssistanceEnrollment`, `LeakAdjustment`, `ShutoffOrder`, and `Moratorium` resources all carry this full set.

Two resource types are immutable append-only records and carry only `id` and `created_at` — they have neither an `updated_at` field nor a `version` field. These are the `MeterRead` (an imported odometer reading) and the `Payment` (a posted financial credit). Once written, neither is mutated in place.

The `Account` is unusual in that it tracks two independent status dimensions that never collapse into one another. The first, `billing_status`, is the financial standing axis and takes one of `CURRENT`, `PAST_DUE`, `SHUTOFF_PENDING`, or `DELINQUENT_PROTECTED`; it begins at `CURRENT`. The second, `service_status`, is the physical water-service axis and takes one of `ACTIVE`, `SUSPENDED`, or `RESTORED`; it begins at `ACTIVE`. A change along one axis does not, by itself, imply a change along the other — though several workflows deliberately move both, as Section 3 describes.

### 2.5. Derived Ledger Reconciliation

The account's money fields are never set directly by a client; they are **derived** and recomputed whenever an underlying fact changes — a bill being posted or voided, a payment being applied, a reconnect fee being charged, a leak credit being granted, or a late fee being assessed at cycle close.

The `balance_due_cents` on an account is the sum of `total_cents` across all of that account's bills whose status is `POSTED` or `PAID`, plus the sum of `late_fee_cents` across those same bills, plus the sum of `reconnect_fee_charged_cents` across all of that account's shutoff orders that have reached `RECONNECTED`, minus the sum of `amount_cents` across all of that account's payments; the result is then floored so it never drops below zero.

The `past_due_cents` on an account is a narrower figure: take every bill of the account whose status is `POSTED` and whose owning billing cycle has reached `CLOSED`, sum each such bill's `total_cents` together with its `late_fee_cents`, subtract the payments already absorbed by those specific bills, and floor the result at zero. All of these figures are whole integer cents.

Two further account fields are derived booleans rather than money: `budget_billing_enrolled` is true exactly when the account has a budget-billing plan in `ACTIVE` status, and `assistance_enrolled` is true exactly when the account has an assistance enrollment in `ACTIVE` status. Each derived-field recomputation is a mutation of the account and therefore refreshes its `updated_at` and increments its `version`.

### 2.6. Monetary Precision and Rounding

All monetary values are stored and returned as whole integer cents. Wherever a calculation divides by 1000 to convert a per-thousand-gallon rate into cents — or applies a percentage — the result is rounded using the round-half-up method to the nearest whole cent. Where a calculation specifies that rounding happens once at the end, intermediate subtotals are accumulated without rounding and only the final figure is rounded; where a calculation specifies rounding at an intermediate stage, that stage is rounded before the next stage consumes it. The specific rounding points for each charge are spelled out alongside the formulas in Section 3.

### 2.7. Optimistic Concurrency on Budget-Plan Enrollment

Enrolling an account in a new budget-billing plan is the one operation in this system guarded by optimistic concurrency control. Because a new plan legitimately supersedes any prior `ACTIVE` plan (the prior plan is auto-cancelled), two enrollment attempts can both observe the same eligible account state, and the system must resolve which one wins without silently letting the second overwrite a plan the client never saw.

To that end, the enroll-in-budget-billing request must carry `expected_account_version`, a non-optional field carrying the `version` of the target `Account` that the client last observed. The server compares it to the account's current `version`. If another writer has advanced the account's `version` since the client read it, the two will not match and the enrollment is rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412). When they do match, the enrollment proceeds and increments the account's `version` by one. No other endpoint in the system takes a version field; only budget-plan enrollment is version-gated.

### 2.8. Nested Resource Resolution and Existence Ordering

Several endpoints address a resource through a parent in the path — for example, attaching a meter under an account, importing a read under a meter, or enrolling a plan under an account. For any such request, the server validates the path identifiers left to right and rejects the request with `ERR_NOT_FOUND` at the first identifier that does not resolve to an existing resource, before considering the body. Foreign-key references named in a request body (an account, a bill, a billing cycle, a rate schedule) are likewise checked for existence, and a reference to a non-existent resource yields `ERR_NOT_FOUND`. Only after existence is confirmed does the server validate the body's required fields and enum domains; a missing or ill-typed field, or an enum value outside its declared set, is rejected with `ERR_INVALID_REQUEST`.

### 2.9. Validation Ordering

When several checks could apply to one request, they are evaluated in a fixed priority order so that the returned error is deterministic. Authentication comes first: the presence and validity of `X-User-Role` (`ERR_UNAUTHENTICATED`), then role authorization for the operation (`ERR_FORBIDDEN_ROLE`), then customer ownership of the targeted account or resource (`ERR_NOT_RESOURCE_OWNER`). Existence is checked next — path and foreign-key resources must exist (`ERR_NOT_FOUND`) — followed by request well-formedness, meaning required fields are present and well-typed and enum values are in-domain (`ERR_INVALID_REQUEST`). Only then does the system evaluate state legality, namely whether the targeted resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`), then the optimistic-concurrency check on budget-plan enrollment (`ERR_STALE_ACCOUNT_VERSION`), and finally the business-rule checks specific to each workflow (duplicate bills, read regressions, moratorium and protection guards, arrears thresholds, leak-volume requirements, and the rest) described in Section 3. In short: authentication, then authorization, then ownership, then existence, then request validity, then state legality, then concurrency, then domain rules.

## 3. Business Logic & Workflows

### 3.1. The Price Book: Rate Schedules

Everything downstream begins with a **rate schedule**, the price book a `BillingClerk` creates before any account can be billed. A rate schedule is created with a human label (`name`) and a complete set of pricing parameters. Two flat monthly service charges are supplied in cents: `fixed_water_charge_cents` and `fixed_sewer_charge_cents`, each of which must be zero or greater. The volumetric water price lives in `water_tiers`, a non-empty array of tier objects ordered by ascending ceiling; each tier object names an `up_to_gallons` ceiling and a `rate_cents_per_kgal` rate expressed per one thousand gallons. The tiers are marginal (cumulative): each slice of consumption is priced at the rate of the tier whose band it falls into. Exactly one terminal tier carries an `up_to_gallons` of null, meaning it extends without upper bound, and the ceilings must strictly ascend up to that terminal entry.

The sewer side is priced from three further fields. The `sewer_rate_cents_per_kgal` is the flat volumetric sewer rate applied per thousand gallons of billable sewer volume. The `sewer_ratio_pct` is the percentage of potable consumption that is treated as discharged to the sewer; it ranges from 0 to 100 and defaults to 100 (the whole potable volume) when not supplied. The optional `sewer_cap_gallons` is a winter-average cap on billable sewer gallons; supplying it engages a capped variant of the sewer calculation, while leaving it null leaves the sewer volume uncapped. When provided it must be zero or greater.

Several policy levers round out the schedule, each a percentage between 0 and 100 with its own default. The `leak_adjustment_rate_pct` is the share of over-baseline leak volume that is forgiven, defaulting to 50. The `assistance_discount_pct` is the discount applied to fixed charges for accounts enrolled in assistance, defaulting to 25. The `late_fee_pct` is the late fee charged on unpaid principal when a cycle closes, defaulting to 5. Two further fields are amounts, not percentages: `arrears_shutoff_threshold_cents` is the minimum past-due balance at or above which a shutoff may be scheduled (default 7500 cents, i.e. seventy-five dollars), and `reconnect_fee_cents` is the fee levied on reconnection after an executed shutoff (default 5000 cents, i.e. fifty dollars); both must be zero or greater. A rate schedule can be fetched by any of the four roles.

### 3.2. Accounts, Meters, and Reads

A `BillingClerk` opens a **utility account** by supplying the governing `rate_schedule_id`, the `holder_name`, and the `service_address`. A freshly created account starts life with `balance_due_cents` at zero, `billing_status` of `CURRENT`, and `service_status` of `ACTIVE`. Its derived figures — `balance_due_cents`, `past_due_cents`, `budget_billing_enrolled`, and `assistance_enrolled` — are computed, never client-set. An account can be fetched individually by any role (subject to customer ownership), and the account list can be browsed by back-office and field roles with optional filters on `billing_status`, `service_status`, and `rate_schedule_id` alongside the usual `limit` and `offset`.

Each account is served by one or more **meters**, attached by a `BillingClerk`. A meter is created under its account with a `meter_type` and a physical `serial`. The `meter_type` is either `POTABLE` — an indoor meter whose consumption is both water-billable and sewer-billable — or `IRRIGATION` — a second, outdoor meter whose consumption is water-billable but never contributes to the sewer charge. A meter carries a system `status` of `ACTIVE` or `RETIRED`, beginning `ACTIVE`, and a derived `last_reading_gallons` holding the most recent imported reading for that meter, or zero if none has been imported. Meters for an account can be listed by reaching through the account, and an individual meter can be fetched directly.

Meter telemetry arrives as **meter reads**, each imported under its meter by a `BillingClerk` and bound to that meter through its `meter_id`. A read carries a cumulative odometer `reading_gallons` (zero or greater), the `read_date` it was taken (an ISO 8601 UTC timestamp), and a `source` that is either `AMI` or `MANUAL`, defaulting to `AMI`. On import the system computes `consumption_gallons` for the read: the difference between this read's `reading_gallons` and the prior chronological read for the same meter. The very first read for a meter has a `consumption_gallons` of zero, and the computed consumption is clamped so it is never negative, guarding against an odometer rollover. Importing a read also refreshes the owning meter's `last_reading_gallons` to the `reading_gallons` of the read with the latest `read_date` for that meter (chronological, not last-imported). A read is an append-only record: it carries `id` and `created_at` but no `updated_at` or `version`. A read whose `reading_gallons` falls below the meter's prior chronological reading is rejected with `ERR_READ_REGRESSION` unless the read is a `MANUAL` rollover correction; a `MANUAL` read below the prior reading is accepted with its `consumption_gallons` clamped to zero. Reads for a meter can be listed in chronological order, sorted by `read_date` ascending.

### 3.3. Billing Cycles and Their Closure

Billing happens against a **billing cycle**, a window a `BillingClerk` opens by supplying a `label` (such as a year-month string), an inclusive `period_start`, an exclusive `period_end`, and a `due_date` by which the cycle's bills must be paid. A cycle begins in `OPEN` status and can be fetched by back-office staff and the customer.

Closing a cycle is a consequential collections event. When a `BillingClerk` closes a cycle, the system walks every `POSTED` bill in that cycle that is still unpaid and assesses a late fee on each: the bill's `late_fee_cents` is set to the unpaid principal — taken as the bill's full `total_cents`, without subtracting any payments partially absorbed against it — multiplied by the schedule's `late_fee_pct`, divided by 100, rounded half up to whole cents. The computed value is assigned to `late_fee_cents` outright (replacing any prior value), not accumulated. The late fee is tracked on the bill separately and does not alter the bill's `total_cents`; instead it flows into the account's ledger through reconciliation. Each affected account whose closing cycle leaves an unpaid posted bill moves its `billing_status` from `CURRENT` to `PAST_DUE`, and that account's `past_due_cents` and `balance_due_cents` are recomputed. The transition to `PAST_DUE` requires the account to hold at least one `POSTED` bill in the closing cycle whose status is not `PAID`. Once a cycle is `CLOSED`, generating or posting a bill against it is barred with `ERR_CYCLE_CLOSED`.

### 3.4. Generating a Bill: The Charge Stack

Bill generation is where the price book meets the meter data. A `BillingClerk` generates a **bill** by naming the `account_id` and the `billing_cycle_id`; the system pins the governing schedule onto the bill as `rate_schedule_id` and computes the entire charge stack. At most one non-`VOID` bill may exist for a given account and cycle pairing; a second attempt is rejected with `ERR_DUPLICATE_BILL`. If the account has no meter reads within the cycle window, generation is rejected with `ERR_NO_CONSUMPTION_DATA`. Generation against a `CLOSED` cycle is rejected with `ERR_CYCLE_CLOSED`. A new bill starts in `DRAFT` status.

The consumption inputs are summed from the account's `ACTIVE` meters whose reads fall within the half-open cycle window — at or after `period_start` and strictly before `period_end`. The `potable_consumption_gallons` is the summed consumption across the account's `POTABLE` meters in that window, and `irrigation_consumption_gallons` is the summed consumption across its `IRRIGATION` meters.

**Water volumetric charge.** The tiered water charge is computed over the combined consumption — potable plus irrigation gallons together. Walking the tiers from lowest to highest, each tier prices the slice of consumption that falls within its band: the span priced at a tier is the consumption remaining when that tier is reached, but no more than the difference between that tier's ceiling and the previous tier's ceiling (the terminal null-ceiling tier absorbs whatever remains). Each tier's span in gallons is multiplied by that tier's `rate_cents_per_kgal`, and these per-tier products are accumulated without rounding. After all consumption has been allocated, the accumulated total — which is in units of cents times gallons — is divided by 1000 and rounded half up exactly once to yield `water_volumetric_cents`. Rounding happens only at the very end, never per tier.

**Sewer volumetric charge.** Sewer is derived from potable consumption alone; irrigation never contributes. First, a ratio volume is computed as `potable_consumption_gallons` multiplied by `sewer_ratio_pct`, divided by 100, rounded half up to whole gallons. If the schedule supplies a `sewer_cap_gallons`, the `billable_sewer_gallons` is the lesser of that ratio volume and the cap (the winter-capped variant); if the schedule leaves the cap null, the `billable_sewer_gallons` is the ratio volume unchanged (the uncapped variant). The `sewer_volumetric_cents` is then `billable_sewer_gallons` multiplied by `sewer_rate_cents_per_kgal`, divided by 1000, rounded half up. The two rounding stages — ratio volume, then cents — are each rounded half up.

**Fixed charge.** The `fixed_charge_cents` is the sum of `fixed_water_charge_cents` and `fixed_sewer_charge_cents`. If the account is enrolled in assistance, the fixed charge is reduced by the schedule's `assistance_discount_pct`: the combined fixed charge is multiplied by one minus that percentage (equivalently, the discount percentage of the combined fixed charge is subtracted), rounded half up to whole cents. If the account is not enrolled, the fixed charge stands at the full sum.

**Assembling the bill.** The `amount_billed_cents` — the actual computed charge for the cycle — is the fixed charge plus `water_volumetric_cents` plus `sewer_volumetric_cents` minus `leak_credit_cents`, floored at zero. The `leak_credit_cents` is zero on a freshly generated bill and only becomes non-zero when a leak adjustment is later approved (Section 3.8). The `total_cents` is the amount the account is actually asked to pay this cycle: when the account is on an `ACTIVE` budget-billing plan, `total_cents` equals the flat `budget_billing_amount_cents` installment (Section 3.7) rather than the actual computed charge; otherwise `total_cents` equals `amount_billed_cents`. The `budget_billing_amount_cents` is zero when the account is not on a plan. A bill can be fetched with its full breakdown by back-office staff, the caseworker, and the owning customer, and bills can be listed with optional filters on `account_id`, `billing_cycle_id`, `rate_schedule_id`, and `status`.

### 3.5. Posting and Voiding Bills

A `DRAFT` bill is provisional; it touches no ledger until it is posted. When a `BillingClerk` posts a bill, advancing it from `DRAFT` to `POSTED`, the system finalizes all computed charge fields, confirms the pinned `rate_schedule_id`, and increases the account's `balance_due_cents` by the bill's `total_cents` through reconciliation. Posting is permitted only when the bill's billing cycle is still `OPEN` and no other `POSTED` or `PAID` bill already exists for the same account and cycle; a duplicate is rejected with `ERR_DUPLICATE_BILL`, and a closed cycle with `ERR_CYCLE_CLOSED`. If the account is on an `ACTIVE` budget-billing plan, posting also increments that plan's `cycles_elapsed` by one and recomputes its `trued_up_delta_cents` as a cascade.

Voiding reverses a bill. A `BillingClerk` may void a bill that is in `DRAFT` or in `POSTED`. Voiding a `DRAFT` bill simply marks it `VOID` with no ledger effect. Voiding a `POSTED` bill is a compensation: the account's `balance_due_cents` is decreased by the bill's `total_cents`, reversing the original posting, and if the account is on an `ACTIVE` budget-billing plan that plan's `cycles_elapsed` is decremented by one and its `trued_up_delta_cents` recomputed. A `POSTED` bill may only be voided if no payment has yet been applied to it; an attempt to void a posted bill that already has an applied payment is rejected with `ERR_BILL_HAS_PAYMENT`. `VOID` and `PAID` are terminal bill states.

### 3.6. Payments and the Collection Waterfall

A payment is recorded by a `Customer` against their own account, or by a `BillingClerk` on the account's behalf. A payment supplies an `amount_cents` greater than zero and an optional `method` that is one of `CARD`, `ACH`, or `CASH`, defaulting to `ACH`. A payment is an append-only record carrying `id` and `created_at` but no `updated_at` or `version`.

Payments are applied oldest-first through a waterfall: the incoming amount is directed at the account's oldest `POSTED` unpaid bill, then the next oldest, and so on. The read-only `applied_to_bill_id` records the oldest `POSTED` unpaid bill the payment was applied to, or null if the payment was absorbed against the balance without landing on a specific bill. A bill transitions from `POSTED` to `PAID` once the cumulative applied payment for that bill reaches or exceeds its `total_cents`; reaching `PAID` is terminal and contributes to reducing the account's `past_due_cents`. After every payment, the account's balances are reconciled.

Payment can also resolve the account's collections posture. If, after the waterfall runs, the account's resulting `past_due_cents` is zero and the account's `billing_status` is `PAST_DUE` or `SHUTOFF_PENDING`, that `billing_status` returns to `CURRENT`; an account standing in `DELINQUENT_PROTECTED` is not moved by a payment (that axis is governed by assistance, per §3.10). There is a second, stronger consequence when a shutoff is pending: if the account is in `SHUTOFF_PENDING` and the payment drives `past_due_cents` to zero while every shutoff order on the account is still merely `SCHEDULED` (none has been `EXECUTED`), then all of those `SCHEDULED` shutoff orders are cancelled as a cascade and the account returns to `CURRENT`. Payments for an account can be listed by the customer and by back-office staff.

### 3.7. Budget Billing: Flat Installments and the Chronological True-Up

Budget billing lets an account pay a steady flat amount each cycle instead of riding the swings of actual consumption. A `Customer` (on their own account) or a `BillingClerk` enrolls the account by supplying a `monthly_amount_cents` installment (zero or greater) together with the `expected_account_version` required by the concurrency rule in §2.7. Enrollment snapshots the account's current `balance_due_cents` into the plan's `anchor_balance_cents` as the true-up baseline, sets `budget_billing_enrolled` true on the account, and — because a new plan supersedes any prior one — moves any previously `ACTIVE` plan to `CANCELLED`. Enrollment increments the account's `version` by one. A plan begins in `ACTIVE` status with `cycles_elapsed` at zero and `trued_up_delta_cents` at zero. Plans for an account can be listed by the customer and by back-office staff.

While a plan is `ACTIVE`, the **estimate** variant governs each cycle: the bill's `budget_billing_amount_cents` is set to the plan's `monthly_amount_cents`, and the bill's `total_cents` is that same flat installment — a forward estimate that is deliberately independent of the cycle's actual `amount_billed_cents`. Each posted bill against the account advances the plan's `cycles_elapsed`.

The reckoning comes at **true-up**, performed by a `BillingClerk`. The true-up uses the **chronological** variant: the system accumulates the actual `amount_billed_cents` across the account's `POSTED` and `PAID` bills since enrollment, taken in chronological order of their `created_at` ascending, to obtain the actual-to-date figure; it computes installments-to-date as the plan's `cycles_elapsed` multiplied by its `monthly_amount_cents`; and it sets `trued_up_delta_cents` to actual-to-date minus installments-to-date — a positive delta meaning the account underpaid relative to true consumption. This delta is posted to the account's ledger as an adjustment to `balance_due_cents`, and the plan moves to `TRUED_UP`. The accumulation is strictly chronological; bill `id` is never used as a tie-break. A plan that has been superseded is in `CANCELLED`; `TRUED_UP` and `CANCELLED` are the two end states of a plan.

### 3.8. Leak Adjustments

When a hidden leak inflates a customer's consumption, the system can forgive part of the resulting water charge. A `Customer` (against their own bill) or an `AssistanceCaseworker` requests a **leak adjustment** by naming the `bill_id`, supplying the customer's normal historical `baseline_gallons` (zero or greater), and a `repair_evidence_ref` pointing at uploaded repair documentation. On creation the system copies the bill's owning `account_id` onto the adjustment and starts it in `PENDING` status; its `credit_cents` is zero while pending or denied. Leak adjustments can be fetched and listed (with optional `bill_id`, `account_id`, and `status` filters) by the caseworker, back-office staff, and the owning customer.

Adjudication is the caseworker's job. **Approving** a leak adjustment moves it from `PENDING` to `APPROVED` and is permitted only when the referenced bill is in `POSTED` status — a leak credit cannot be applied to a `DRAFT`, `VOID`, or `PAID` bill, and an attempt to approve against a non-posted bill is rejected with `ERR_BILL_NOT_POSTED`. Approval also requires genuine over-baseline volume: the adjustment's `baseline_gallons` must be strictly below the bill's `potable_consumption_gallons`, otherwise the approval is rejected with `ERR_NO_LEAK_VOLUME`.

When approval proceeds, the credit is computed. The over-baseline volume is the bill's `potable_consumption_gallons` minus the adjustment's `baseline_gallons`, floored at zero. That volume is priced at the lowest tier's rate — the `rate_cents_per_kgal` of the first entry in the schedule's `water_tiers` — scaled by the schedule's `leak_adjustment_rate_pct`: multiply the over-baseline gallons by the lowest tier rate and by the leak-adjustment percentage divided by 100, divide by 1000, and round half up to whole cents. The resulting `credit_cents` is then capped so it can never exceed the bill's `water_volumetric_cents`. The computed credit is written to the adjustment's `credit_cents` and onto the bill's `leak_credit_cents`, and the bill's `amount_billed_cents` is recomputed as a cascade. If the bill is not on a budget plan, the bill's `total_cents` is recomputed as well and the account's `balance_due_cents` is decreased by the credit, compensating against the original posting. **Denying** an adjustment moves it from `PENDING` to `DENIED`, a terminal state that leaves `credit_cents` at zero with no ledger effect.

### 3.9. Arrears, Shutoffs, and Reconnection

When an account falls far enough behind, field operations can pursue a physical shutoff — but only within strict guardrails. A `FieldOps` operator **schedules a shutoff order** by naming the delinquent `account_id`, the `triggering_bill_id` that justifies the action, and the `scheduled_for` date that is the earliest the order may be executed. Scheduling is gated by several conditions evaluated as business rules. The account's `past_due_cents` must be at or above the schedule's `arrears_shutoff_threshold_cents`; below that, scheduling is rejected with `ERR_ARREARS_BELOW_THRESHOLD`. The account must not be protected: if it has an `ACTIVE` assistance enrollment that grants shutoff protection, scheduling is rejected with `ERR_SHUTOFF_PROTECTED`. And no active moratorium may cover the `scheduled_for` date; if one does, scheduling is rejected with `ERR_MORATORIUM_ACTIVE`. When scheduling succeeds, the order is created in `SCHEDULED` status and the account's `billing_status` advances to `SHUTOFF_PENDING`. The transition into `SHUTOFF_PENDING` is defined out of `PAST_DUE`. A shutoff order's `reconnect_fee_charged_cents` is zero until reconnection. Shutoff orders can be fetched and listed (with optional `account_id`, `triggering_bill_id`, and `status` filters) by field, back-office, and customer roles.

**Executing** a scheduled shutoff is the physical act of suspending service, performed by `FieldOps`. Execution advances the order from `SCHEDULED` to `EXECUTED` and, as a cross-axis effect, moves the account's `service_status` from `ACTIVE` to `SUSPENDED`. Execution is permitted only when the order is `SCHEDULED` (otherwise `ERR_INVALID_STATE`), the current server clock has reached or passed the order's `scheduled_for` (otherwise `ERR_SHUTOFF_NOT_DUE`), no active moratorium covers the current clock date (otherwise `ERR_MORATORIUM_ACTIVE`), and the account's `service_status` is still `ACTIVE` (otherwise `ERR_INVALID_STATE`). These guards are checked in that order, so the not-due check precedes the moratorium check.

**Cancelling** a shutoff, also a `FieldOps` action, is allowed only while the order is `SCHEDULED`; the order moves to `CANCELLED`, and if the account has no other still-active (`SCHEDULED` or `EXECUTED`) shutoff order and is currently `SHUTOFF_PENDING`, its `billing_status` falls back to `PAST_DUE`. Cancelling an order that is not `SCHEDULED` is an undefined transition and is rejected with `ERR_INVALID_STATE`.

**Reconnecting** restores service after an executed shutoff. A `FieldOps` operator reconnects an order that is in `EXECUTED`, moving it to `RECONNECTED`; reconnecting an order that is not `EXECUTED` is rejected with `ERR_NOT_EXECUTED`. On reconnection the order's `reconnect_fee_charged_cents` is set to the schedule's `reconnect_fee_cents`, the account's `balance_due_cents` increases by that reconnect fee as a posted charge, and the account's `service_status` moves from `SUSPENDED` to `RESTORED`. `RECONNECTED` and `CANCELLED` are the order's terminal states, though a fresh shutoff order can later re-enter the cycle for the same account if arrears recur.

### 3.10. Assistance Enrollment and Shutoff Protection

Low-income protection is administered by the `AssistanceCaseworker`. The caseworker **enrolls** an account in assistance by supplying a `program_code`, a `certified_until` eligibility-expiry timestamp, and an optional `grants_shutoff_protection` flag that defaults to true. Enrollment creates an `AssistanceEnrollment` in `ACTIVE` status and sets the account's `assistance_enrolled` true. When the enrollment grants shutoff protection and the account is currently `PAST_DUE`, the account's `billing_status` advances to `DELINQUENT_PROTECTED` — a standing in which a shutoff cannot be scheduled. This is the cross-entity dependency that ties the account's billing transition to the creation of the enrollment: the move into `DELINQUENT_PROTECTED` is defined out of `PAST_DUE`. Enrollments for an account can be listed by the caseworker, back-office staff, and the customer.

**Revoking** an enrollment is also a caseworker action. Revocation moves the enrollment to `REVOKED` and clears the account's `assistance_enrolled` flag; if the account was `DELINQUENT_PROTECTED` and still carries arrears (its `past_due_cents` is greater than zero), its `billing_status` falls back to `PAST_DUE` as a cascade. An enrollment's lifecycle states are `ACTIVE`, `EXPIRED`, and `REVOKED`.

### 3.11. Moratoriums and the Server Clock

A **moratorium** is a no-shutoff window — typically a cold-weather rule — declared by an `AssistanceCaseworker` or a `BillingClerk`. It is created with a `label`, an inclusive `window_start`, and an exclusive `window_end`. Its `active` flag is derived: it is true exactly when the current server clock falls at or after `window_start` and strictly before `window_end`. While a moratorium covers the relevant date, shutoffs may neither be scheduled nor executed, and either attempt is rejected with `ERR_MORATORIUM_ACTIVE`. Moratoriums can be listed by every role.

Because shutoff due-dates and moratorium coverage both turn on the current time, the system exposes an administrative test-driving capability that sets the server's current UTC clock to a supplied `to_iso8601` instant. This capability is available to `BillingClerk`, `FieldOps`, and `AssistanceCaseworker`, and is the mechanism by which the logical clock is advanced or rewound so that `scheduled_for` due-dates and moratorium windows can be exercised deterministically.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify, transition, or otherwise act upon an existing resource — including bill posting, voiding, cycle closure, true-up, and all shutoff and adjudication actions — return a `200 OK` status code. The request body, response body, and side effects of each endpoint are described in Section 3; the table below lists only the route, its purpose, and the roles permitted to call it.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/rate-schedules` | Create a rate schedule | BillingClerk |
| GET | `/rate-schedules/{id}` | Fetch a rate schedule | BillingClerk, FieldOps, AssistanceCaseworker, Customer |
| POST | `/accounts` | Create a utility account | BillingClerk |
| GET | `/accounts/{id}` | Fetch an account with derived balances and dual status axes | BillingClerk, FieldOps, AssistanceCaseworker, Customer |
| GET | `/accounts` | List accounts (paginated; filter by status) | BillingClerk, FieldOps, AssistanceCaseworker |
| POST | `/accounts/{id}/meters` | Attach a meter to an account | BillingClerk |
| GET | `/accounts/{id}/meters` | List meters for an account | BillingClerk, FieldOps, Customer |
| GET | `/meters/{id}` | Fetch a meter with last reading | BillingClerk, FieldOps, Customer |
| POST | `/meters/{id}/reads` | Import an AMI/manual meter read | BillingClerk |
| GET | `/meters/{id}/reads` | List reads for a meter (chronological) | BillingClerk, FieldOps, Customer |
| POST | `/billing-cycles` | Open a billing cycle window | BillingClerk |
| GET | `/billing-cycles/{id}` | Fetch a billing cycle | BillingClerk, Customer |
| POST | `/billing-cycles/{id}/close` | Close a cycle: assess late fees and flip accounts to past due | BillingClerk |
| POST | `/bills` | Generate a draft bill for an account and cycle | BillingClerk |
| GET | `/bills/{id}` | Fetch a bill with full charge breakdown | BillingClerk, AssistanceCaseworker, Customer |
| GET | `/bills` | List bills | BillingClerk, AssistanceCaseworker, Customer |
| POST | `/bills/{id}/post` | Post a draft bill to the ledger | BillingClerk |
| POST | `/bills/{id}/void` | Void a draft or unpaid posted bill | BillingClerk |
| POST | `/accounts/{id}/budget-billing-plans` | Enroll account in budget billing | Customer, BillingClerk |
| GET | `/accounts/{id}/budget-billing-plans` | List budget plans for an account | BillingClerk, Customer |
| POST | `/budget-billing-plans/{id}/true-up` | Reconcile a plan via chronological true-up | BillingClerk |
| POST | `/accounts/{id}/assistance-enrollments` | Enroll a low-income account in assistance | AssistanceCaseworker |
| GET | `/accounts/{id}/assistance-enrollments` | List assistance enrollments for an account | AssistanceCaseworker, BillingClerk, Customer |
| POST | `/assistance-enrollments/{id}/revoke` | Revoke an assistance enrollment | AssistanceCaseworker |
| POST | `/leak-adjustments` | Request a leak adjustment against a posted bill | Customer, AssistanceCaseworker |
| GET | `/leak-adjustments/{id}` | Fetch a leak adjustment | AssistanceCaseworker, Customer, BillingClerk |
| GET | `/leak-adjustments` | List leak adjustments | AssistanceCaseworker, BillingClerk, Customer |
| POST | `/leak-adjustments/{id}/approve` | Approve: compute and apply the leak credit | AssistanceCaseworker |
| POST | `/leak-adjustments/{id}/deny` | Deny a pending leak adjustment | AssistanceCaseworker |
| POST | `/shutoff-orders` | Schedule a shutoff for a past-due, unprotected account | FieldOps |
| GET | `/shutoff-orders/{id}` | Fetch a shutoff order | FieldOps, BillingClerk, Customer |
| GET | `/shutoff-orders` | List shutoff orders | FieldOps, BillingClerk, Customer |
| POST | `/shutoff-orders/{id}/execute` | Execute a due, non-moratorium shutoff: suspend service | FieldOps |
| POST | `/shutoff-orders/{id}/reconnect` | Reconnect after an executed shutoff: charge fee, restore service | FieldOps |
| POST | `/shutoff-orders/{id}/cancel` | Cancel a scheduled shutoff | FieldOps |
| POST | `/moratoriums` | Declare a shutoff moratorium window | AssistanceCaseworker, BillingClerk |
| GET | `/moratoriums` | List declared moratoriums | FieldOps, BillingClerk, AssistanceCaseworker, Customer |
| POST | `/accounts/{id}/payments` | Apply a payment; waterfall to oldest unpaid bills | Customer, BillingClerk |
| GET | `/accounts/{id}/payments` | List payments for an account | BillingClerk, Customer |
| POST | `/_clock/set_current_utc` | Set the server's current UTC clock (test-driving) | BillingClerk, FieldOps, AssistanceCaseworker |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_ACCOUNT_VERSION` | 412 |
| `ERR_DUPLICATE_BILL` | 409 |
| `ERR_READ_REGRESSION` | 422 |
| `ERR_MORATORIUM_ACTIVE` | 409 |
| `ERR_SHUTOFF_PROTECTED` | 409 |
| `ERR_SHUTOFF_NOT_DUE` | 409 |
| `ERR_BILL_NOT_POSTED` | 409 |
| `ERR_ARREARS_BELOW_THRESHOLD` | 409 |
| `ERR_NO_LEAK_VOLUME` | 422 |
| `ERR_NOT_EXECUTED` | 409 |
| `ERR_BILL_HAS_PAYMENT` | 409 |
| `ERR_CYCLE_CLOSED` | 409 |
| `ERR_NO_CONSUMPTION_DATA` | 422 |
| `ERR_VALIDATION_LIMIT` | 422 |
