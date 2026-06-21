# Car Wash Membership API — Product Requirements Document

## 1. Introduction

The Car Wash Membership platform turns a chain of physical wash sites into a single subscription business. Drivers enroll a vehicle in a recurring plan, pull up to any participating site, and a license-plate-recognition (LPR) camera decides — in the moment — whether to raise the gate. Behind that one-second decision sits a surprising amount of machinery: recurring monthly billing with retries and write-offs, two fundamentally different plan economics (an all-you-can-wash *unlimited* tier and a metered *single-wash* credit tier), volume discounts for fleet operators, abuse throttling so a single vehicle cannot wash ten times a day, a prepaid wallet that absorbs refunds and top-ups, and freeze/cancellation flows that have to return money fairly when a customer pauses or leaves.

This document specifies the API that runs that business. It is written for the engineers who will implement it and the operators who will run it. Four kinds of actor touch the system: customers who own accounts and vehicles, site staff (and their cameras) who submit wash entries, finance operators who run billing, and platform operators who configure the catalog and drive the test clock. The sections below define the global contract that every request obeys (Section 2), the business logic that governs each entity's life from creation to settlement (Section 3), the full endpoint surface (Section 4), and the catalogue of error identifiers the API can return (Section 5). Monetary amounts are expressed throughout in integer cents; the system never stores a fractional cent.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules and conventions that apply uniformly across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which they act. A request that omits either header, or supplies a malformed value, is rejected with `ERR_UNAUTHENTICATED`. This authentication check is the very first gate on every protected endpoint; the only operations exempt from it are account self-registration and the read-only catalog lookups (listing and fetching plans, locations, and add-ons). For these exempt operations the headers are optional, but when they are supplied they are still honored: account self-registration carrying authentication headers requires the declared role to be one permitted for that endpoint (`PlatformAdmin` or `AccountHolder`) and otherwise is rejected with `ERR_FORBIDDEN`, while the catalog lookups ignore any supplied headers entirely. Once a request is authenticated, the system checks whether the declared role is permitted to perform the requested operation; if it is not, the request is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly four roles, spelled precisely as follows: `PlatformAdmin`, `AccountHolder`, `LocationOperator`, and `BillingAdmin`.

`PlatformAdmin` is an operator identity. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. A `PlatformAdmin` configures the catalog (plans, locations, add-ons), drives account suspension and closure, advances the logical clock, simulates payment outcomes, and may additionally perform any account, vehicle, membership, wash, or invoice operation that another role can — it is a superset operator.

`AccountHolder` is the only entity-backed role. When `X-User-Role` is `AccountHolder`, `X-User-ID` is the `id` of the acting `Account`; ownership checks on any resource that references an `Account` compare the resource's owning-account foreign key to `X-User-ID`. Concretely, a holder may only act on accounts, vehicles, memberships, freezes, add-ons, invoices, wallet ledgers, and wash events that resolve back to the account whose `id` equals their `X-User-ID`. An `AccountHolder` who targets a resource owned by a different account is rejected with `ERR_FORBIDDEN`.

`LocationOperator` is an operator identity representing site staff or a camera. When `X-User-Role` is `LocationOperator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. A `LocationOperator` submits wash entries, completes admitted washes, and reads location, wash-event, and vehicle usage-intensity data.

`BillingAdmin` is likewise an operator identity. When `X-User-Role` is `BillingAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. A `BillingAdmin` runs billing cycles, manages invoice retries, write-offs, and voids, posts manual wallet adjustments, and reads accounts, memberships, invoices, wallet ledgers, and plans.

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

List endpoints are paginated through two query parameters. `limit` controls the maximum number of items returned; it defaults to 10 when omitted, may be no smaller than 1, and may be no larger than 100. A supplied `limit` outside that range is not rejected but is clamped into it (a value below 1 becomes 1, a value above 100 becomes 100). `offset` controls how many leading items to skip; it defaults to 0, and a supplied negative `offset` is likewise clamped up to 0.

Unless a specific endpoint states otherwise, every list endpoint returns its resources sorted by their creation timestamp in ascending order — that is, by `created_at` from oldest to newest. The account wallet ledger, in particular, is browsed in this chronological order so that running-balance reconciliation reads naturally.

Every list response reports the pagination state in the `meta` object via the fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Most resources in the system carry a common set of system-managed fields. Each has an `id`, a server-minted UUID with no type prefix that serves as identity only. Each carries a `created_at` timestamp (ISO 8601 UTC with millisecond precision, three fractional digits) marking when it was first persisted. Each carries an `updated_at` timestamp, refreshed on every mutation — including mutations that arrive as a cascade from some other operation rather than from a direct request on that resource. Each carries a `version`, an integer that starts at 1 on creation and increases by exactly 1 on every mutation, cascades included.

Two entities are deliberately leaner because they are immutable audit records. A `WashEvent` carries only `id` and `created_at`; it has neither an `updated_at` nor a `version`. A `WalletTransaction` likewise carries only `id` and `created_at`; it too has neither `updated_at` nor `version`. Once written, a ledger transaction and a wash-event record are never modified.

### 2.5. Hierarchical Consistency and Cascades

Many operations in this domain touch more than one entity. When that happens, the system applies every consequence atomically and refreshes `updated_at` and increments `version` on each entity it mutates. A suspension of an account, for example, does not merely flip the account's own `status`; it ripples down through the account's memberships and their add-ons. Whenever a derived count or balance on a parent changes because a child changed, the parent is itself re-derived and re-stamped. The downstream sections describe each cascade where it belongs in the business narrative; the principle here is simply that no cascade leaves a stale parent behind, and every entity altered by a cascade has both its timestamp and its version advanced.

The system's consistency is immediate: derived fields such as an account's `wallet_balance_cents`, `active_vehicle_count`, and `fleet_discount_pct`, and a membership's `credit_balance` and `freeze_count`, always reflect the current state at the moment a request returns.

### 2.6. Nested and Filtered Resource Retrieval

Several paths name a parent resource before the child collection they expose — for instance, the vehicles, wallet ledger, or freezes belonging to a particular account or membership. The system validates the identifiers in such a path strictly left to right. If the first (parent) identifier names no existing resource, the request fails immediately with `ERR_NOT_FOUND` for that parent, before any attempt to resolve or filter the child collection. The same left-to-right existence rule applies to any single-resource path: the path-referenced resource must exist or the request is rejected with `ERR_NOT_FOUND`.

Collection endpoints additionally accept filter query parameters that restrict the returned set by a referenced foreign key or by status — for example, memberships may be filtered by `account_id`, `vehicle_id`, `plan_id`, or `status`; invoices by `account_id`, `membership_id`, `status`, or `kind`; membership add-ons by `membership_id`, `addon_id`, or `status`; wash events by `membership_id`, `vehicle_id`, `location_id`, or `status`; the wallet ledger by `reason`; plans by `tier_type` or `status`; locations by `status` or `in_network`; vehicles by `status`; and freezes by `status`. These filters never bypass the parent-existence check above.

### 2.7. Monetary Precision and Rounding

All money is stored and returned as integer cents. Where a calculation produces a fractional cent — invariably because a percentage or a daily proration is applied — the system rounds to a whole number of cents using the round-half-up convention (a value whose fractional part is exactly one half rounds away from zero, upward). The precise point at which rounding is applied differs by calculation and is stated with each formula in Section 3; the global rule is only that the stored result is always an integer number of cents and that round-half-up is the tie-breaker.

### 2.8. Optimistic Concurrency Control

Two write operations on a membership are guarded against acting on a stale view of that membership, because both depend on counters that an intervening mutation may already have advanced. Each such request must include `expected_membership_version`, carrying the `version` of the target membership that the client last observed; this field is mandatory on those two endpoints and is not accepted anywhere else.

The first guarded operation is attaching a recurring add-on to a membership. The request must carry `expected_membership_version` equal to the membership's current `version`. If a prior mutation — another add-on attachment that consumed the last available slot, or a freeze that paused the add-ons — has advanced the membership's `version` since the client last read it, the attach is rejected with `ERR_STALE_VERSION` (HTTP 412) before the add-on-capacity check is ever evaluated, so the capacity rule is never tested against an outdated add-on set.

The second guarded operation is purchasing additional single-wash credits (a top-up). The request must carry `expected_membership_version` equal to the membership's current `version`. If an intervening top-up has already raised the granted-credit total and advanced the membership's `version`, the current request is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than stacking on a credit balance the client never saw.

No other endpoint takes a version field, and endpoints that are not so guarded perform their mutations without any optimistic-concurrency check.

### 2.9. The Prepaid Wallet Ledger

Every account owns a prepaid wallet. The wallet is not a directly editable number; it is the running sum of an append-only ledger of `WalletTransaction` rows. An account's `wallet_balance_cents` equals the sum of the `amount_cents` of every wallet transaction belonging to that account, considered in chronological order by `created_at` ascending. Each transaction is signed: a positive `amount_cents` credits the wallet (a refund), and a negative `amount_cents` debits it (a top-up payment or a charge taken from the wallet). Every transaction also records a `reason` drawn from `CANCEL_REFUND`, `FREEZE_REFUND`, `TOPUP_DEBIT`, `INVOICE_CHARGE`, and `MANUAL_ADJUSTMENT`, and — when it settles a particular invoice — a `related_invoice_id` pointing to that `Invoice`'s identity for audit purposes (informational only; it is browsed through the account ledger, not followed as a navigation link, and is null when no invoice applies).

Each transaction additionally stores `balance_after_cents`: the value of `wallet_balance_cents` immediately after that transaction is applied. Because the ledger is chronological, the `balance_after_cents` of the latest transaction always equals the account's current `wallet_balance_cents`. The wallet may never go negative. Any debit — a top-up paid from the wallet, or a manual adjustment — that would drive `wallet_balance_cents` below 0 is rejected with `ERR_INSUFFICIENT_WALLET` before any transaction row is written.

### 2.10. Fleet Volume Discounts

Accounts come in two shapes, fixed at creation by `account_type`: `INDIVIDUAL` and `FLEET`. The discount an account earns on its recurring bills is derived, never set by hand, and lives in `fleet_discount_pct`. For an `INDIVIDUAL` account the discount is always 0, regardless of how many vehicles it carries. For a `FLEET` account the discount is selected by a volume tier keyed on `active_vehicle_count` — the number of the account's vehicles whose membership currently sits in `ACTIVE`, `FROZEN`, or `PAST_DUE`. The tiers are: 15 percent (a rate of 0.15) when the active-vehicle count is at least 10; otherwise 10 percent (0.10) when the count is at least 5; otherwise 5 percent (0.05) when the count is at least 2; and otherwise 0. The tier is re-evaluated whenever the active-vehicle count changes, so the discount a fleet sees on its next bill always reflects its current fleet size.

### 2.11. Validation Ordering

When several checks could reject the same request, the system evaluates them in a fixed priority order and returns the error of the first check that fails. The global order, highest priority first, is: authentication of the request headers (`ERR_UNAUTHENTICATED`); role authorization for the operation (`ERR_FORBIDDEN`); existence of every resource named in the path, left to right (`ERR_NOT_FOUND`); existence of every foreign key supplied in the body, such as `account_id`, `plan_id`, `vehicle_id`, `addon_id`, `location_id`, or `membership_id` (`ERR_FK_NOT_FOUND`); presence and well-formedness of required body fields, including correct types and valid enum values (`ERR_INVALID_REQUEST`); and only then the domain-specific business rules described throughout Section 3. The wash-admission decision has its own internal priority chain, described in Section 3.6, which determines which single rejection reason a denied entry records. Each business rule states its own relative position where it is described.

## 3. Business Logic & Workflows

### 3.1. The Catalog: Plans, Locations, and Add-Ons

Before any customer can subscribe, a `PlatformAdmin` builds the catalog. A **Plan** is created with a `name` and a `tier_type` of either `UNLIMITED` or `SINGLE_WASH`, fixed for the life of the plan. A plan also declares a recurring base fee in `monthly_fee_cents`, an `included_credits` count, a `per_credit_price_cents`, a `wash_cooldown_hours`, and a `max_addons` cap (which defaults to 3 when omitted). The shape of these numbers must be internally consistent with the tier, and the system enforces that consistency at creation time: a `SINGLE_WASH` plan must grant a positive number of `included_credits`, must set `monthly_fee_cents` to 0, and must set `wash_cooldown_hours` to 0; an `UNLIMITED` plan must set `included_credits` to 0. Any plan whose field combination violates these tier rules is rejected with `ERR_PLAN_SHAPE_INVALID`. The `monthly_fee_cents`, `included_credits`, `per_credit_price_cents`, `wash_cooldown_hours`, and `max_addons` values must each be zero or greater. For a `SINGLE_WASH` plan, `included_credits` is the number of single-wash credits granted each time a billing cycle is paid, and `per_credit_price_cents` is the price charged per credit when a customer tops up additional credits; for an `UNLIMITED` plan, `per_credit_price_cents` is ignored and `wash_cooldown_hours` is the minimum number of hours that must elapse between admitted washes on the same vehicle (an abuse throttle).

A plan begins life with a `status` of `ACTIVE`. Retiring a plan moves it to `RETIRED`; a `RETIRED` plan accepts no new memberships, though memberships already on it continue. A **Location** is created with a `name`, a two-letter `state_code` for the site, a `daily_wash_capacity` of at least 1 (the maximum number of admitted washes the site will honor in a single UTC calendar day), and an `in_network` flag that defaults to true and marks whether the site honors memberships from any account. A location begins `OPEN`; closing it transitions its `status` to `CLOSED` and reopening it returns the `status` to `OPEN`. Closing is permitted only from `OPEN` and reopening only from `CLOSED`; either action attempted from the wrong state is rejected with `ERR_INVALID_STATE`. A closed site admits no washes. An **AddOn** is a recurring service such as a tire shine; it is created with a `name` and a `recurring_fee_cents` of zero or greater, begins `ACTIVE`, and may be retired to `RETIRED`, after which it accepts no new attachments. Newly referencing a `RETIRED` plan or a `RETIRED` add-on when enrolling a membership or attaching an add-on is rejected with `ERR_RESOURCE_RETIRED`.

### 3.2. Accounts and Vehicles

A billing **Account** is created with an `account_type` of `INDIVIDUAL` or `FLEET`, a billing `contact_email`, and — only for a `FLEET` account — a `company_name`. The pairing is strict: a `FLEET` account must supply `company_name`, and an `INDIVIDUAL` account must not supply one; either violation is rejected with `ERR_INVALID_REQUEST`. A new account opens in `status` `ACTIVE` with a `wallet_balance_cents` of 0. Its `active_vehicle_count` and `fleet_discount_pct` are derived as described in Section 2.10.

A **Vehicle** is registered under an account by supplying its `license_plate` and the two-letter plate-issuing `state_code`; the system normalizes the plate to uppercase alphanumeric and pairs it with the state code to form the identity an LPR camera will later match against. A registered plate must be unique among vehicles that are still `ACTIVE`: registering a plate already held by an `ACTIVE` vehicle is rejected with `ERR_PLATE_TAKEN`. Vehicles may only be added under an account whose `status` is `ACTIVE`; attempting to register a vehicle (or to enroll a membership, or to run billing) against an account that is not `ACTIVE` is rejected with `ERR_ACCOUNT_NOT_ACTIVE`. A vehicle begins `ACTIVE`; removing it transitions its `status` to `REMOVED`, which frees its plate so it can be registered again later. An account holder may register and remove only vehicles under their own account.

### 3.3. Enrolling and Activating a Membership

A **Membership** binds one vehicle to one plan under a billing account. Enrollment supplies `account_id`, `vehicle_id`, and `plan_id`. A vehicle may carry only one membership in any of the live states `ACTIVE`, `FROZEN`, or `PAST_DUE` at a time. A newly enrolled membership begins in `PENDING` status and, in the same operation, the system raises the first recurring invoice for it (a cycle invoice, moved from draft to issued and awaiting payment). The membership does not become usable until that first invoice is paid.

When the first cycle invoice for a `PENDING` membership is paid, the system advances the membership from `PENDING` to `ACTIVE`. On that activation it sets the membership's `cycle_anchor_utc` to the current clock — this timestamp marks the start of the current billing cycle and advances by one cycle length on each successful future billing run. For a `SINGLE_WASH` plan, activation also grants the plan's `included_credits`: the cumulative `credits_granted` counter rises by that amount. The membership exposes `credit_balance`, which for a `SINGLE_WASH` plan is `credits_granted` minus `credits_consumed`, and which is always 0 for an `UNLIMITED` plan; it also exposes `credits_consumed` (cumulative credits used by admitted washes), `last_admitted_wash_utc` (the UTC instant of the most recent admitted wash, null until the first), `current_cycle_paid_cents` (the amount charged for the current cycle's base plus add-ons, which the refund and proration math draws on), and `freeze_count` (the number of freeze records on the membership that are scheduled, active, or ended). Activation increments the membership's `version`.

### 3.4. Recurring Billing, Retries, and Write-Offs

Each **Invoice** records the money owed for one event against one membership and account. An invoice carries a `kind`: `CYCLE` for a recurring monthly charge, `PRORATION` for a mid-cycle plan change, and `TOPUP` for a single-wash credit purchase. Its computed components are `base_fee_cents` (the plan's monthly fee, 0 for a top-up), `addon_fee_cents` (the sum of the locked fees of the membership's currently active add-ons, 0 for a top-up), `discount_cents` (the fleet discount applied to the subtotal, 0 for an individual account), and `total_cents` (the net amount owed). An invoice also tracks `attempt_count`, the number of charge attempts made against it.

**Billing run.** A finance operator runs the recurring billing cycle, optionally scoped to a single membership by `membership_id`. For each membership whose current cycle has elapsed, the run issues a `CYCLE` invoice. The cycle total is computed as follows: the subtotal is the plan's `monthly_fee_cents` plus the sum of the `locked_fee_cents` of every membership add-on that is currently `ACTIVE` (add-ons that are `PAUSED` or `DETACHED` are excluded from the sum). The discount is the subtotal multiplied by the account's `fleet_discount_pct`, rounded half-up to a whole number of cents; this is the only place rounding is applied in this calculation, and it is 0 for any `INDIVIDUAL` account. The invoice `total_cents` is the subtotal minus that discount. An invoice moves from draft to issued, and on issue its `attempt_count` is set to 1. The billing run returns an array response holding the `CYCLE` invoices it newly issued on this run (each in `ISSUED` state), ordered by `created_at` ascending; memberships that were not due raise nothing and contribute no entry.

**Charge outcome.** An issued invoice is resolved deterministically by a simulated payment. A successful charge moves the invoice to `PAID`; when the invoice is settled from the wallet, that success writes a `WalletTransaction` with reason `INVOICE_CHARGE` and an `amount_cents` equal to the negative of `total_cents` (a gateway-paid invoice writes no wallet transaction). A `CYCLE` or `PRORATION` charge resolved through the payment simulation is always treated as gateway-paid and therefore writes no `INVOICE_CHARGE` wallet transaction; the `INVOICE_CHARGE` reason exists for wallet-settled charges and is not produced by this simulated cycle/proration path. A successful first cycle invoice triggers the membership's activation from `PENDING` to `ACTIVE` as described above. A failed charge moves the invoice to `FAILED`; when the failing invoice is a cycle charge against an `ACTIVE` membership, that failure transitions the membership from `ACTIVE` to `PAST_DUE`.

**Retry and recovery.** A `BillingAdmin` may retry a `FAILED` invoice, but only while its `attempt_count` is below the maximum of 3 attempts; retrying moves the invoice from `FAILED` to `RETRYING` and increases `attempt_count` by 1. A retry that is then resolved successfully moves the invoice from `RETRYING` to `PAID`, and that success transitions the membership from `PAST_DUE` back to `ACTIVE`; on that recovery the membership's `cycle_anchor_utc` advances by one cycle length and, for a `SINGLE_WASH` plan, `credits_granted` rises again by the plan's `included_credits`. A retry that fails moves the invoice from `RETRYING` back to `FAILED`. Retrying an invoice that is not `FAILED`, or one that has already reached the maximum attempts, is rejected with `ERR_INVALID_STATE`.

**Write-off and void.** A `FAILED` invoice whose `attempt_count` has reached the maximum of 3 may be written off, moving it from `FAILED` to `WRITTEN_OFF`; writing off an invoice that is not `FAILED` or whose attempts are not yet maxed is rejected with `ERR_INVALID_STATE`. An `ISSUED` proration invoice may be voided, moving it from `ISSUED` to `VOID`; voiding is permitted only for a proration-kind invoice in the `ISSUED` state, and any other case is rejected with `ERR_INVALID_STATE`. Each invoice transition increments the invoice's `version`.

### 3.5. Changing a Plan Mid-Cycle and Buying Credits

When an `AccountHolder` changes a membership's plan mid-cycle, the request names the `new_plan_id` and may include `add_addon_ids`, a list of catalog add-ons to attach as part of the change. The membership must be `ACTIVE` for a plan change; a change attempted against a membership in any other state is rejected with `ERR_INVALID_STATE`. The system raises a `PRORATION` invoice for the difference (issued, with `attempt_count` 1, `discount_cents` 0, its `base_fee_cents` holding the plan-change line and its `addon_fee_cents` holding the summed add-on lines) and returns the updated membership. The proration is built one line at a time, and each line is rounded on its own before the lines are summed — the order is pinned, round each line first, then add the rounded cents together; the system never sums the raw amounts and rounds once at the end. First compute the number of remaining days in the cycle: the cycle length is 30 days, and the elapsed days are the whole number of days obtained by taking the time from the cycle's anchor to the current clock and discarding any partial day (floor); remaining days are 30 minus those elapsed days. The plan-change line is the difference between the new plan's monthly fee and the old plan's monthly fee, multiplied by remaining days, divided by 30, rounded half-up to whole cents. For each newly added add-on, its own line is the add-on's recurring fee multiplied by remaining days, divided by 30, rounded half-up to whole cents. The invoice `total_cents` is the plan-change line plus the sum of those already-rounded add-on lines. Each add-on named in `add_addon_ids` must reference an existing add-on (else `ERR_FK_NOT_FOUND`) that is not `RETIRED` (else `ERR_RESOURCE_RETIRED`); the add-ons attached through a plan change are each captured into a new `ACTIVE` `MembershipAddOn` with `locked_fee_cents` taken from the catalog add-on, and this attachment is not subject to the plan's `max_addons` cap. Changing a plan increments the membership's `version`.

A `SINGLE_WASH` customer may buy extra credits by topping up. The request names a `credit_quantity` (which must be at least 1) and the `expected_membership_version` described in Section 2.8. The system raises a `TOPUP` invoice (issued, with `base_fee_cents`, `addon_fee_cents`, and `discount_cents` all 0, `total_cents` equal to `credit_quantity` times the plan's `per_credit_price_cents`, and `attempt_count` 1), debits the wallet with a `WalletTransaction` of reason `TOPUP_DEBIT` whose `related_invoice_id` points at that invoice, raises the membership's `credits_granted` by `credit_quantity`, and increments the membership's `version`. The endpoint returns the created `TOPUP` invoice. Because the top-up is paid from the wallet, it is subject to the no-negative-balance rule: a top-up that would drive `wallet_balance_cents` below 0 is rejected with `ERR_INSUFFICIENT_WALLET`. A `credit_quantity` below 1 is rejected with `ERR_VALIDATION`. Among these business rules the order is fixed: the `credit_quantity` lower-bound check (`ERR_VALIDATION`) is evaluated first, then the `expected_membership_version` optimistic-concurrency check (`ERR_STALE_VERSION`), and only then the wallet-balance check (`ERR_INSUFFICIENT_WALLET`).

### 3.6. License-Plate Entry: Admitting or Rejecting a Wash

The heart of the operational flow is the wash entry. A `LocationOperator` (in practice, a camera at the gate) submits a **WashEvent** naming the `location_id`, the raw `license_plate` read by the camera, and the `state_code` as read. The system normalizes the plate, resolves the normalized plate together with the `state_code` against registered vehicles whose `status` is `ACTIVE` to populate the event's `vehicle_id`, and resolves that vehicle's live membership to populate `membership_id` (either may be null if nothing matches). For populating `membership_id`, a membership counts as live when its `status` is `ACTIVE`, `FROZEN`, `PAST_DUE`, or `CANCEL_SCHEDULED`, and when more than one qualifies the most recently created is chosen; this populated `membership_id` is independent of whether the entry is ultimately admitted, which requires an `ACTIVE` membership as below. It then decides, in one shot, whether to admit or reject. The event's `status` becomes `ADMITTED` if every admission condition holds, and `REJECTED` otherwise; a rejected event records in `rejection_error_id` the identifier of the single highest-priority condition that failed, and consumes no entitlement. In both the admitted and the rejected case the wash-event record is created and returned with HTTP `201 Created`: a rejection is recorded as a persisted `WashEvent`, not surfaced as an error response.

The admission conditions are evaluated in this exact priority order, and the first one to fail is the recorded rejection reason:

1. The location's `status` must be `OPEN`; a closed site rejects with `ERR_LOCATION_CLOSED`.
2. The recognized plate (its normalized `license_plate` together with `state_code`) must map to a vehicle whose `status` is `ACTIVE` that carries a membership whose `status` is `ACTIVE` — not `FROZEN`, `PAST_DUE`, `CANCELLED`, or any other state. If no such active membership exists, the entry is rejected with `ERR_NO_MEMBERSHIP`.
3. The location's `in_network` flag must be true; an out-of-network site does not honor the membership and rejects with `ERR_OUT_OF_NETWORK`.
4. For an `UNLIMITED` plan, the cooldown must have elapsed: the number of hours since the membership's `last_admitted_wash_utc` must be at least the plan's `wash_cooldown_hours`. The boundary is inclusive — when exactly that many hours have passed, the cooldown is satisfied. A wash inside the cooldown window is rejected with `ERR_COOLDOWN_ACTIVE`.
5. The site must have capacity: the count of admitted wash events at this location for the current UTC calendar day — that is, events whose `status` is `ADMITTED` or `COMPLETED` and whose `admitted_at_utc` falls on the current UTC calendar day — must be strictly less than the location's `daily_wash_capacity`. A site already at capacity rejects with `ERR_CAPACITY_FULL`.
6. For a `SINGLE_WASH` plan, the membership's `credit_balance` must be at least 1. A membership with no remaining credit is rejected with `ERR_NO_CREDITS`.

When all conditions hold, the event is admitted: the system sets `admitted_at_utc` and `status` to `ADMITTED`, updates the membership's `last_admitted_wash_utc` to that admission instant, and — for a `SINGLE_WASH` plan only — raises the membership's `credits_consumed` by 1 and marks the event's `consumed_credit` true (it remains false for an `UNLIMITED` admission). Admitting a wash is the one membership-touching effect that does not increment the membership's `version`: it refreshes the membership's `updated_at` but leaves `version` unchanged, an exception to the general rule of Section 2.4. An admitted wash is later marked finished, moving its `status` from `ADMITTED` to `COMPLETED`; completion is permitted only from `ADMITTED` and is otherwise rejected with `ERR_INVALID_STATE`; completing a wash mutates only the wash event (which carries no `version`) and leaves the membership untouched.

### 3.7. Usage Intensity and Abuse Gating

The system can report, and internally reasons about, how heavily a vehicle is being used through two intensity figures computed over the same set of washes — those wash events for the vehicle whose `status` is `ADMITTED` or `COMPLETED` — but over different windows. The **chronic** intensity is the vehicle's lifetime admitted-wash count divided by its active months, where active months is the greater of 1 and the number of 30-day spans (rounded up to a whole span) between the vehicle's `created_at` and the current clock; this average is reported to two decimal places, rounded half-up. The **acute** intensity is a plain integer count of the vehicle's admitted washes whose admission instant falls within the rolling 7-day window ending at the current clock (the lower bound of that window is inclusive). A vehicle is flagged as abusive when its acute intensity is at least 8, or when its chronic intensity is at least 12.00. The two figures intentionally diverge: a single heavy week can push acute intensity to its cap while chronic intensity stays low, and a long history of steady use can lift chronic intensity even when no recent week is unusual.

### 3.8. Freezing, Thawing, and the Freeze Window

An `AccountHolder` can pause a membership. **Freezing immediately** moves an `ACTIVE` membership to `FROZEN`. That transition creates an `ACTIVE` freeze record whose `start_utc` is the current clock and whose `end_utc` is null (open-ended until the membership thaws), computes a pro-rated refund, and credits it to the wallet: the refund is the membership's `current_cycle_paid_cents` multiplied by the remaining days of the cycle, divided by the 30-day cycle length, rounded half-up to whole cents, and posted as a `WalletTransaction` of reason `FREEZE_REFUND`; the freeze record stores that credited amount in its `refund_cents`. Freezing also pauses every currently active add-on on the membership, moving each from `ACTIVE` to `PAUSED`, and increments the membership's `version`. A membership may only be frozen from `ACTIVE`; attempting it from any other state is rejected with `ERR_INVALID_STATE`.

**Scheduling a future freeze** records a freeze window without pausing anything yet. The request names a `start_utc` and an `end_utc` for the **Freeze**; the window is half-open, including the start instant and excluding the end. The `end_utc` must be strictly after the `start_utc`, or the request is rejected with `ERR_INVALID_WINDOW`. The requested window must not overlap any existing non-cancelled freeze on the same membership; overlap is judged on the half-open interval, so two windows that merely touch at an endpoint do not overlap, but any true interior overlap is rejected with `ERR_FREEZE_OVERLAP`. A scheduled freeze begins in `SCHEDULED` status with a `refund_cents` of 0. When the logical clock is advanced to or past a scheduled freeze's `start_utc`, the system activates it: the freeze moves from `SCHEDULED` to `ACTIVE`, which drives the owning membership from `ACTIVE` to `FROZEN` (triggering the same freeze-refund credit and add-on pausing described above), records the credited amount in the freeze's `refund_cents`, and increments the freeze's `version`. A scheduled freeze that has not yet started may be cancelled, moving it from `SCHEDULED` to `CANCELLED`. An active freeze ends — moving from `ACTIVE` to `ENDED` — either when the holder thaws the membership or when the clock advances to or past its `end_utc`.

**Thawing** a frozen membership returns it from `FROZEN` to `ACTIVE`. Thawing is only permitted when the owning account is itself `ACTIVE`; it ends the membership's open freeze record (moving that freeze from `ACTIVE` to `ENDED`), restores every paused add-on (moving each from `PAUSED` to `ACTIVE`), and increments the membership's `version`. Thawing a membership that is not `FROZEN` is rejected with `ERR_INVALID_STATE`.

### 3.9. Attaching and Detaching Recurring Add-Ons

A membership may carry recurring add-ons, each represented by a **MembershipAddOn** junction record naming the `membership_id` it belongs to and the `addon_id` it points at. Attaching an add-on captures the catalog add-on's current `recurring_fee_cents` into the junction's `locked_fee_cents`; billing always uses this locked fee, never the live catalog fee, so a later catalog price change does not retroactively alter an existing attachment. The attach is guarded by optimistic concurrency as described in Section 2.8: it requires `expected_membership_version` and is rejected with `ERR_STALE_VERSION` on a mismatch before any capacity check runs. The number of add-ons that are `ACTIVE` or `PAUSED` on the membership must be fewer than the plan's `max_addons` before a new attachment is allowed; an attachment that would exceed the cap is rejected with `ERR_ADDON_LIMIT`. A newly attached add-on begins `ACTIVE`.

An add-on's lifecycle tracks the membership. Freezing the membership pauses each `ACTIVE` add-on to `PAUSED`; thawing restores each `PAUSED` add-on to `ACTIVE`. Detaching an add-on directly — permitted while it is `ACTIVE` or `PAUSED` — moves it to `DETACHED`, which is terminal. When a membership reaches cancellation at cycle end, every add-on still `ACTIVE` or `PAUSED` is moved to `DETACHED` as part of that closure. Each add-on transition increments the add-on's `version`.

### 3.10. Cancellation, Suspension, and Account Closure

When an `AccountHolder` cancels a membership, service continues to the end of the current cycle: the membership moves from `ACTIVE` to `CANCEL_SCHEDULED`, and the refund owed is computed and credited to the wallet immediately via a `WalletTransaction` of reason `CANCEL_REFUND`. The refund formula depends on the plan tier. For an `UNLIMITED` membership the refund is forward-looking — the unused value of the cycle: `current_cycle_paid_cents` multiplied by the remaining days of the cycle, divided by the 30-day cycle length, rounded half-up to whole cents, regardless of how many washes were taken. For a `SINGLE_WASH` membership the refund is the consumed value instead: `current_cycle_paid_cents` minus the number of credits consumed this cycle multiplied by a per-wash value of 400 cents, ignoring remaining days. Either way the refund is floored at 0 — a computed refund below zero is treated as zero. Cancellation increments the membership's `version`. The membership keeps serving until the next billing run reaches the cycle's end (the current clock has reached or passed the cycle anchor plus the 30-day cycle length), at which point the system flips it from `CANCEL_SCHEDULED` to `CANCELLED` and detaches its remaining add-ons as noted above.

A `PlatformAdmin` may **suspend** an account that is `ACTIVE`, moving its `status` to `SUSPENDED`. Suspension cascades: every membership of that account that is `ACTIVE` or `PAST_DUE` is driven to `FROZEN` (the first cascade hop), which in turn applies the freeze refund and pauses that membership's add-ons (the second and third hops); this suspension-driven freeze does not create a `Freeze` record, so it leaves the membership's `freeze_count` unchanged. The account's `version` is incremented. **Reactivating** a suspended account returns its `status` to `ACTIVE` and increments its `version`, but it deliberately does not auto-thaw the memberships the suspension froze; the holder must thaw each one explicitly. **Closing** an account moves its `status` to `CLOSED`, a terminal state, and is permitted only when the account is `ACTIVE` and none of its memberships is in any of the states `ACTIVE`, `PAST_DUE`, `FROZEN`, or `CANCEL_SCHEDULED`; closing increments the account's `version`. Suspending an account that is not `ACTIVE`, reactivating one that is not `SUSPENDED`, or closing one that fails its preconditions is rejected with `ERR_INVALID_STATE`.

A `BillingAdmin` or `PlatformAdmin` may also post a **manual wallet adjustment** of a signed `amount_cents` against an account, recorded as a `WalletTransaction` of reason `MANUAL_ADJUSTMENT`. The adjustment amount must not be zero; a zero amount is rejected with `ERR_VALIDATION`. A negative adjustment that would drive `wallet_balance_cents` below 0 is rejected with `ERR_INSUFFICIENT_WALLET`.

### 3.11. Administrative Clock and Payment Simulation

Two administrative capabilities exist for deterministic operation and testing, both restricted to a `PlatformAdmin` (payment simulation is additionally available to a `BillingAdmin`). The first advances the logical clock to a supplied `to_iso8601` instant; advancing the clock activates any scheduled freeze whose start has been reached and ends any active freeze whose end has been reached, applying their cascades, and returns an empty object in its `data` field. The second resolves a pending invoice charge deterministically: it names the `invoice_id` and an `outcome` of either `SUCCEEDED` or `DECLINED`, and drives the invoice to `PAID` (with the membership activation or reactivation cascades) or to `FAILED` (with the `ACTIVE` to `PAST_DUE` cascade for a cycle charge) accordingly, returning the resolved invoice; it acts only on an invoice in `ISSUED` or `RETRYING` state and rejects any other state with `ERR_INVALID_STATE`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`. Operations that modify an existing resource — including state transitions, lifecycle actions, and the billing run — return `200 OK`. The billing run and the clock-advance and payment-simulation capabilities return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/plans` | Create a plan tier | `PlatformAdmin` |
| GET | `/plans` | List plans | `PlatformAdmin`, `AccountHolder`, `BillingAdmin` |
| GET | `/plans/{id}` | Get a plan | `PlatformAdmin`, `AccountHolder`, `BillingAdmin` |
| POST | `/plans/{id}/retire` | Retire a plan | `PlatformAdmin` |
| POST | `/locations` | Create a wash location | `PlatformAdmin` |
| GET | `/locations` | List locations | `PlatformAdmin`, `LocationOperator` |
| GET | `/locations/{id}` | Get a location | `PlatformAdmin`, `LocationOperator` |
| POST | `/locations/{id}/close` | Close a location | `PlatformAdmin` |
| POST | `/locations/{id}/reopen` | Reopen a closed location | `PlatformAdmin` |
| POST | `/addons` | Create an add-on service | `PlatformAdmin` |
| GET | `/addons` | List add-ons | `PlatformAdmin`, `AccountHolder` |
| POST | `/accounts` | Create a billing account | `PlatformAdmin`, `AccountHolder` |
| GET | `/accounts/{id}` | Get an account | `PlatformAdmin`, `AccountHolder`, `BillingAdmin` |
| POST | `/accounts/{id}/suspend` | Suspend an account (cascades freeze) | `PlatformAdmin` |
| POST | `/accounts/{id}/reactivate` | Reactivate a suspended account | `PlatformAdmin` |
| POST | `/accounts/{id}/close` | Close an account | `PlatformAdmin` |
| POST | `/accounts/{id}/vehicles` | Register a vehicle under an account | `PlatformAdmin`, `AccountHolder` |
| GET | `/accounts/{id}/vehicles` | List vehicles for an account | `PlatformAdmin`, `AccountHolder` |
| GET | `/vehicles/{id}` | Get a vehicle | `PlatformAdmin`, `AccountHolder` |
| POST | `/vehicles/{id}/remove` | Remove a vehicle (frees the plate) | `PlatformAdmin`, `AccountHolder` |
| GET | `/vehicles/{id}/usage-intensity` | Get chronic and acute usage intensity | `PlatformAdmin`, `AccountHolder`, `LocationOperator` |
| GET | `/accounts/{id}/wallet-transactions` | List the wallet ledger for an account | `PlatformAdmin`, `AccountHolder`, `BillingAdmin` |
| POST | `/accounts/{id}/adjustments` | Manual wallet adjustment | `PlatformAdmin`, `BillingAdmin` |
| POST | `/memberships` | Enroll a vehicle in a plan | `PlatformAdmin`, `AccountHolder` |
| GET | `/memberships/{id}` | Get a membership | `PlatformAdmin`, `AccountHolder`, `BillingAdmin` |
| GET | `/memberships` | List memberships (filterable) | `PlatformAdmin`, `AccountHolder`, `BillingAdmin` |
| POST | `/memberships/{id}/change-plan` | Change plan mid-cycle | `PlatformAdmin`, `AccountHolder` |
| POST | `/memberships/{id}/freeze` | Freeze a membership immediately | `AccountHolder`, `PlatformAdmin` |
| POST | `/memberships/{id}/freeze-scheduled` | Schedule a future freeze window | `AccountHolder`, `PlatformAdmin` |
| POST | `/memberships/{id}/unfreeze` | Thaw a frozen membership | `AccountHolder`, `PlatformAdmin` |
| POST | `/memberships/{id}/cancel` | Schedule cancellation at cycle end | `AccountHolder`, `PlatformAdmin` |
| POST | `/memberships/{id}/topup` | Buy additional single-wash credits | `AccountHolder`, `PlatformAdmin` |
| POST | `/memberships/{id}/addons` | Attach a recurring add-on | `AccountHolder`, `PlatformAdmin` |
| GET | `/membership-addons` | List membership add-ons (filterable) | `PlatformAdmin`, `AccountHolder`, `BillingAdmin` |
| GET | `/membership-addons/{id}` | Get a membership add-on | `PlatformAdmin`, `AccountHolder` |
| POST | `/membership-addons/{id}/detach` | Detach a recurring add-on | `AccountHolder`, `PlatformAdmin` |
| GET | `/memberships/{id}/freezes` | List freezes for a membership | `PlatformAdmin`, `AccountHolder` |
| POST | `/freezes/{id}/cancel` | Cancel a scheduled freeze | `AccountHolder`, `PlatformAdmin` |
| POST | `/wash-events` | LPR entry: admit or reject a wash | `LocationOperator`, `PlatformAdmin` |
| GET | `/wash-events/{id}` | Get a wash event | `LocationOperator`, `PlatformAdmin`, `AccountHolder` |
| GET | `/wash-events` | List wash events (filterable) | `PlatformAdmin`, `LocationOperator`, `AccountHolder` |
| POST | `/wash-events/{id}/complete` | Mark an admitted wash complete | `LocationOperator`, `PlatformAdmin` |
| GET | `/invoices/{id}` | Get an invoice | `PlatformAdmin`, `AccountHolder`, `BillingAdmin` |
| GET | `/invoices` | List invoices (filterable) | `PlatformAdmin`, `AccountHolder`, `BillingAdmin` |
| POST | `/invoices/{id}/retry` | Retry a failed invoice charge | `BillingAdmin`, `PlatformAdmin` |
| POST | `/invoices/{id}/write-off` | Write off a failed invoice past max attempts | `BillingAdmin`, `PlatformAdmin` |
| POST | `/invoices/{id}/void` | Void an issued proration invoice | `BillingAdmin`, `PlatformAdmin` |
| POST | `/billing/run` | Run the recurring billing cycle | `BillingAdmin`, `PlatformAdmin` |
| POST | `/_clock/set_current_utc` | Set the server clock | `PlatformAdmin` |
| POST | `/_payments/simulate` | Resolve an invoice charge deterministically | `PlatformAdmin`, `BillingAdmin` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_FK_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_PLAN_SHAPE_INVALID` | 422 |
| `ERR_INVALID_WINDOW` | 422 |
| `ERR_PLATE_TAKEN` | 409 |
| `ERR_ACCOUNT_NOT_ACTIVE` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_RESOURCE_RETIRED` | 409 |
| `ERR_FREEZE_OVERLAP` | 409 |
| `ERR_COOLDOWN_ACTIVE` | 409 |
| `ERR_CAPACITY_FULL` | 409 |
| `ERR_ADDON_LIMIT` | 409 |
| `ERR_NO_CREDITS` | 409 |
| `ERR_INSUFFICIENT_WALLET` | 409 |
| `ERR_NO_MEMBERSHIP` | 409 |
| `ERR_LOCATION_CLOSED` | 409 |
| `ERR_OUT_OF_NETWORK` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_VALIDATION` | 422 |
