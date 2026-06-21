# Mobile Carrier Plan & Device Management API — Product Requirements Document

## 1. Introduction

This document specifies the Mobile Carrier Plan & Device Management API, the back-office system that a regional mobile carrier uses to run the full commercial lifecycle of its subscribers. The platform sits at the intersection of three operational worlds that rarely agree with one another: the provisioning desk that stands lines up and tears them down, the porting desk that negotiates phone numbers in and out of rival carriers, and the billing engine that reconciles everything into money at the end of each cycle. A line does not exist in isolation — it carries a plan, possibly a financed device, optionally a roaming pass, a SIM or eSIM, and a number that may have been imported from a competitor and might one day leave again. Every one of those facets has its own small lifecycle, and every one of them touches the subscriber's bill.

The hard problems this API exists to solve are problems of consistency under change. When a subscriber cancels a line mid-cycle, the system must simultaneously settle the unused portion of the plan fee, accelerate any outstanding device financing, cancel pending roaming passes, deactivate the SIM, release the phone number back to the pool, and re-derive the household's multi-line discount — all atomically, because a half-applied cancellation corrupts the next bill. Multi-line discounts mean that provisioning the third line on an account silently re-prices the first two, so the system tracks an account version and rejects stale provisioning attempts that were composed against an out-of-date discount tier. Device financing, overage pricing, and proration each carry their own rounding discipline, and the order in which discounting, proration, and summation are applied is fixed because a different order yields a different bill by a cent or two.

The intended readers are the engineers building the service. The sections below first fix the universal contract — authentication, response envelope, pagination, concurrency, money precision — and then narrate the business workflows in the language of the domain. Field names, thresholds, and state transitions are deliberately woven into the narrative where they make business sense rather than collected into schema tables; the endpoint and error tables at the end are intentionally terse, and the prose is where the behavior actually lives.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules that hold across every endpoint regardless of domain workflow.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated with two mandatory HTTP headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which declares the operational capacity under which the request is made. If either header is missing, or if `X-User-Role` does not name a role the system recognizes, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). This authentication check runs before any other validation.

The system recognizes exactly four roles, spelled here exactly as they must appear in the header: `CarrierAgent`, `Subscriber`, `PortingOps`, and `BillingSystem`. Once a request is authenticated, the system confirms that the acting role is permitted to perform the requested operation. A recognized but unauthorized role is rejected with `ERR_FORBIDDEN` (HTTP 403). The role-to-endpoint permissions are summarized in the endpoint table in §4; the narrative in §3 attaches each operation to its acting role.

The four roles differ in how `X-User-ID` is interpreted. When `X-User-Role` is `Subscriber`, `X-User-ID` is the `id` of the acting `Account`; that subscriber owns exactly the account whose `id` equals their `X-User-ID`, and ownership checks on any resource that references an account compare the resource's owning `account_id` to `X-User-ID`. A line, for example, is owned by the subscriber whose `X-User-ID` equals the line's `account_id`. When `X-User-Role` is `CarrierAgent`, `PortingOps`, or `BillingSystem`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit but does not compare it to any entity's `id`. A subscriber who acts on an account or line they do not own — for instance by cancelling a line, cancelling an add-on, or opening a port request against another account's line — is rejected with `ERR_NOT_ACCOUNT_OWNER` (HTTP 403).

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and the accepted range is a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip from the front of the result set and defaults to 0. A `limit` outside 1..100, a negative `offset`, or a non-integer value for either parameter is rejected with `ERR_VALIDATION`.

Unless a specific endpoint states otherwise, all list endpoints return their resources sorted by `created_at` in ascending order.

Every list response carries the pagination bookkeeping in the envelope's `meta` object, specifically the fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Resource Topology and Reverse Reachability

The system models every entity as a top-level collection. Accounts, plans, devices, lines, SIM assignments, installment plans, add-ons, port requests, upgrade orders, billing cycles, charges, and usage records each live at their own root path and are linked to one another by foreign-key fields carried inside the resource body rather than by nesting under a parent URL segment. A line references its account through `account_id` and its plan through `plan_id`; a SIM assignment, installment plan, add-on, port request, and usage record each reference their owning line through `line_id`; an installment plan references its financed device through `device_id`; a charge references its cycle through `billing_cycle_id` and its line through `line_id`; a billing cycle references its account through `account_id`.

Because children are not nested under parents in the path, the way to discover the children of a parent is to query a child collection filtered by the relevant foreign key. Lines are discoverable by `account_id` or by `plan_id`; SIM assignments, installment plans, add-ons, port requests, and usage records by `line_id`; installment plans also by `device_id`; billing cycles by `account_id`; charges by `billing_cycle_id` or `line_id`; upgrade orders by `line_id`, `old_installment_plan_id`, `new_installment_plan_id`, or `new_device_id`. These filtered listings additionally accept a `status` filter (and usage records a `usage_type` filter, charges a `charge_type` filter) so a caller can narrow a collection to a single lifecycle state.

For any endpoint whose path contains a resource identifier, that identifier is validated for existence before the operation runs. When more than one identifier appears in a path, validation proceeds left to right and the first identifier that does not resolve to a stored entity produces `ERR_NOT_FOUND` (HTTP 404). A body foreign key that fails to resolve — a `plan_id` with no matching plan, a `device_id` with no matching device, or an `old_installment_plan_id` that names no active installment plan on the target line — is a distinct failure reported as `ERR_FK_NOT_FOUND` (HTTP 422). A request body that is missing a required field or supplies a field of the wrong type is rejected with `ERR_VALIDATION` (HTTP 422).

### 2.5. Common Resource Properties and Mutation Semantics

Most resources carry a standard set of system-managed fields. Every account, plan, device, line, SIM assignment, installment plan, add-on, port request, upgrade order, and billing cycle includes an `id` (a server-minted UUID with no type prefix), a `created_at` timestamp (ISO 8601 UTC with three fractional digits) marking creation, an `updated_at` timestamp in the same format marking the most recent modification, and a `version` integer that begins at 1 and increments by one on every mutation of that resource. The `version` integer is the basis for the optimistic concurrency control described in §2.7.

Two entities are deliberate exceptions because they are append-only ledger events: `Charge` and `UsageRecord` carry only an `id` and a `created_at`. They have no `updated_at` and no `version`, because once written they are never modified.

Many fields are computed rather than supplied by the client, and they are kept continuously reconciled. Whenever a line's activation, cancellation, or port-out completion changes which lines count toward an account, the account's `active_line_count` and `group_discount_pct` are recomputed, its `updated_at` is refreshed, and its `version` is incremented. Whenever an installment plan is opened, paid off, accelerated, or superseded, the account's `total_eip_outstanding_cents` is recomputed. A line's `cycle_data_used_mb` is recomputed as data usage is ingested. These derived-field refreshes are mutations: each one updates the owning resource's `updated_at` and bumps its `version` exactly as a client-driven change would.

### 2.6. Money, Units, and Rounding Discipline

All monetary amounts in the system are integers expressed in cents, except for plan overage rates, which are expressed in milli-cents where one thousand milli-cents equal one cent. Whenever a calculation in milli-cents must be converted to cents, the milli-cent total is divided by one thousand and rounded to the nearest whole cent using the round-half-up rule (a fractional remainder of exactly one half rounds up). The round-half-up rule is the system's universal tie-breaking convention for every monetary rounding step described in §3, including the discount multiply, the proration multiply, and the milli-cent-to-cent overage conversion.

Two device-financing computations round upward rather than half-up. The per-cycle device installment is the financed amount divided by the term and rounded up to the next whole cent (ceiling), and the data-overage tier boundaries are counted in whole megabytes. Where a sequence of rounded steps feeds a later step, the rounding happens at each named step in the order the workflow prescribes; §3 pins these orders explicitly because applying them in a different sequence changes the result by a cent.

### 2.7. Optimistic Concurrency on Line Provisioning

Provisioning a new line is the one write that is guarded by optimistic concurrency control, because it is the one create whose correctness depends on an account-level value the client must have read first. A request to provision a line must carry `expected_account_version`, a non-optional field whose value is the `version` of the target `Account` as the client last observed it. The server compares `expected_account_version` to the account's current `version`. If they match, provisioning proceeds; if they differ — meaning some earlier line provisioning or line state change has already advanced the account's `version`, and therefore possibly its `active_line_count` and `group_discount_pct` — the request is rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412). The rejection forces the client to re-read the account, observe the new discount tier, and re-compose its request against current data before committing. No other endpoint accepts or requires a version field; the OCC guard exists only on line provisioning.

## 3. Business Logic & Workflows

### 3.1. Building the Catalog: Accounts, Plans, and Devices

Everything begins with three independent catalog entities that a `CarrierAgent` stands up before any line can exist. An account is created by supplying the `holder_name`, the `holder_email` (which doubles as the login identity for the `Subscriber` who owns the account), and a `billing_day_of_month` that anchors the billing cycle and must be an integer from 1 through 28 inclusive, a value outside that range being rejected with `ERR_VALIDATION`. On creation the account's `status` is `ACTIVE`, its `active_line_count` is 0, its `group_discount_pct` is 0.00, its `wallet_credit_cents` is 0, its `total_eip_outstanding_cents` is 0, and its `version` is 1. The account `status` is an enumeration of exactly `ACTIVE` and `DELINQUENT`; it is toggled only by the billing back office, never supplied at creation.

A plan is the recurring product a line subscribes to. A `CarrierAgent` creates one by supplying a `code` that must be unique across all plans (a duplicate `code` is rejected with `ERR_VALIDATION`), a marketing `name`, a `monthly_fee_cents` base recurring fee, an `included_data_mb` allowance, the overage tier-1 megabyte cap `overage_tier1_cap_mb` (defaulting to 5120 megabytes — that is, five gibibytes' worth at 1024 per unit is not assumed; the cap is literally 5120 MB), the tier-1 overage price `overage_tier1_rate_milli_cents`, and the tier-2 overage price `overage_tier2_rate_milli_cents`. A new plan's `status` is `ACTIVE`. The plan `status` enumeration is `ACTIVE` and `RETIRED`; retiring a plan moves it from `ACTIVE` to `RETIRED`, after which it can no longer back a new line. Any attempt to provision a line on, or upgrade onto, a `RETIRED` plan is rejected with `ERR_PLAN_RETIRED` (HTTP 409).

A device is the financeable hardware. A `CarrierAgent` creates one with a `model`, a `sku` that must be unique across all devices (a duplicate `sku` is rejected with `ERR_VALIDATION`), a `retail_price_cents` full price, and an initial `stock_count` of available units. A device's `status` is always `AVAILABLE` — this is the only device state, and stock exhaustion is tracked entirely through `stock_count` reaching zero, never through a status change. Opening an installment plan or an upgrade against a device decrements its `stock_count` by one.

### 3.2. Provisioning and Activating a Line

A line is the central operational entity, and a `CarrierAgent` provisions one by naming the owning `account_id`, the `plan_id` it subscribes to, the `sim_type` it will use (either `PHYSICAL` or `ESIM`), and the `expected_account_version` that guards the create as described in §2.7. A newly provisioned line enters `status` `PENDING_ACTIVATION` with its `phone_number` held at null, and the act of provisioning increments the owning account's `version` by one. The line `status` enumeration is `PENDING_ACTIVATION`, `ACTIVE`, `SUSPENDED`, and `CANCELLED`, with `CANCELLED` being terminal. Before provisioning is allowed, the body foreign keys must resolve — an unresolvable `account_id` or `plan_id` yields `ERR_FK_NOT_FOUND` — and the named plan must not be `RETIRED`. These checks run in a fixed order: both body foreign keys are resolved first (account, then plan), then the `expected_account_version` optimistic-concurrency comparison of §2.7 runs, and only then is the plan-retired check applied; so a stale `expected_account_version` against a `RETIRED` plan surfaces as `ERR_STALE_ACCOUNT_VERSION` rather than `ERR_PLAN_RETIRED`.

Activation is the transition that turns a provisioned line into a working one, moving `status` from `PENDING_ACTIVATION` to `ACTIVE`. A `CarrierAgent` performs it, and three preconditions guard the transition. First, the line must already have a SIM assignment in `status` `ISSUED`; absent one, activation fails with `ERR_SIM_NOT_ISSUED` (HTTP 409). Second, the plan referenced by `plan_id` must still be `ACTIVE`, failing with `ERR_PLAN_RETIRED` otherwise. Third, the owning account must be `ACTIVE`; if the account `status` is `DELINQUENT`, activation fails with `ERR_ACCOUNT_NOT_ACTIVE` (HTTP 409). When all three hold, activation assigns the line a `phone_number` from the carrier number pool (unless a previously completed port-in has already placed the imported number on the line, in which case that number stands), stamps `activated_at` with the current time, transitions the linked SIM assignment from `ISSUED` to `ACTIVATED` — populating `esim_activation_code` at that moment if the SIM is an eSIM — recomputes the account's `active_line_count` and `group_discount_pct`, and increments the account's `version` by one.

The day count behind proration begins at `activated_at`: the line's prorated base for a cycle reflects only the whole UTC days the line spent in `ACTIVE` or `SUSPENDED` within that cycle window. Concretely, the active-day count is the whole UTC days in the intersection of the half-open interval from `activated_at` up to the line's end instant with the cycle window `[cycle_start, cycle_end)`, where the end instant is the earliest of the cycle's `cycle_end`, the line's cancellation time if it was cancelled, and the server's current clock; a line that was never activated counts zero active days. Because the end instant is clamped at the current clock, a usage-summary read mid-cycle prorates only the days elapsed so far, whereas a cycle close (which is permitted only once the clock has reached `cycle_end`) counts the days through `cycle_end`. The `cycle_data_used_mb` field tracks, for the current open billing cycle, the sum of data megabytes the line has consumed; it begins at 0 and is recomputed as usage arrives.

### 3.3. SIM and eSIM Assignment

A SIM assignment is the physical or virtual credential that lets a line onto the network. A `CarrierAgent` issues one by naming the `line_id` it belongs to and the `sim_type`, which is `PHYSICAL` or `ESIM`. When the `sim_type` is `PHYSICAL`, an `iccid` must accompany the request, identifying the physical card; for an eSIM the `iccid` is omitted and the server later issues the `esim_activation_code` — the LPA activation string a handset scans — at line activation time. A freshly issued SIM assignment enters `status` `ISSUED`. The SIM `status` enumeration is `ISSUED`, `ACTIVATED`, and `DEACTIVATED`. As described in §3.2, line activation advances the SIM from `ISSUED` to `ACTIVATED`. Suspending the line moves its SIM from `ACTIVATED` to `DEACTIVATED`, reconnecting moves it back from `DEACTIVATED` to `ACTIVATED`, and the cancellation cascade leaves the SIM `DEACTIVATED`.

### 3.4. The Suspend / Reconnect Loop

A line in service can be parked and brought back without being torn down. Suspending an `ACTIVE` line moves its `status` to `SUSPENDED`; the request supplies a `suspend_reason`, which is one of `VOLUNTARY`, `NONPAYMENT`, or `LOST_STOLEN`, and that reason is recorded on the line. Suspension is only defined from `ACTIVE`; attempting it from any other state fails with `ERR_INVALID_STATE` (HTTP 409). When a line is suspended, its linked SIM assignment moves from `ACTIVATED` to `DEACTIVATED`, and any add-ons on the line keep their own status but are excluded from billing for the days the line spends suspended. Critically, suspension does not change the account's `active_line_count`: a `SUSPENDED` line still counts toward the multi-line group discount exactly as an `ACTIVE` line does. Because the active-line set is unchanged, suspension touches the owning account not at all — it neither refreshes the account's `updated_at` nor bumps its `version` — and reconnect likewise leaves the account untouched.

Reconnecting reverses the park, moving the line from `SUSPENDED` back to `ACTIVE`. A reconnect is only defined from `SUSPENDED`, again failing with `ERR_INVALID_STATE` otherwise, and it additionally requires the owning account to be `ACTIVE`, failing with `ERR_ACCOUNT_NOT_ACTIVE` if the account is `DELINQUENT`. There is one further guard tied to the reason the line was parked: if the line was suspended for `NONPAYMENT`, reconnect is permitted only when the account's `wallet_credit_cents` is at least 0 and the account `status` is not `DELINQUENT`; either a `DELINQUENT` account or a negative `wallet_credit_cents` blocks a non-payment reconnect with `ERR_RECONNECT_BLOCKED` (HTTP 409), and this non-payment guard is evaluated before the generic account-active check so that `ERR_RECONNECT_BLOCKED` takes precedence over `ERR_ACCOUNT_NOT_ACTIVE` for a delinquent non-payment reconnect. A successful reconnect clears the line's `suspend_reason` and returns the SIM assignment from `DEACTIVATED` to `ACTIVATED`.

### 3.5. Cancelling a Line and the Provisional Settlement

Cancellation is the most consequential single action in the system because one request fans out across the line's entire dependent graph. A `Subscriber` cancels their own line; the transition is defined from either `ACTIVE` or `SUSPENDED`, and an attempt from any other state fails with `ERR_INVALID_STATE`. Before the cancel proceeds, the line must have no port request in flight: if any port request on the line is in `REQUESTED` or `VALIDATED` status, the cancel is rejected with `ERR_PORT_IN_PROGRESS` (HTTP 409). Because the actor is a `Subscriber`, ownership is enforced — cancelling a line the caller does not own yields `ERR_NOT_ACCOUNT_OWNER`.

When the cancel proceeds, the line moves to `CANCELLED` and the following cascade runs atomically. The provisional cancellation settlement is computed in its forward-looking variant (detailed in §3.10): the unused portion of the discounted base is credited back, and any active device financing is accelerated. Concretely, each installment plan on the line whose `status` is `ACTIVE` is driven to `PAID_OFF` with its `remaining_balance_cents` set to 0, and that outstanding balance is posted immediately as a single payoff charge. Each add-on on the line whose `status` is `SCHEDULED` or `ACTIVE` is moved to `CANCELLED`. The linked SIM assignment is moved to `DEACTIVATED`. The line's `phone_number` is released back to the carrier number pool and set to null. Finally the account's `active_line_count`, `group_discount_pct`, and `total_eip_outstanding_cents` are all recomputed, and the account's `version` is incremented by one.

### 3.6. Device Financing: Installment Plans and Upgrades

A device installment plan — an EIP — is how a subscriber finances hardware over time. A `CarrierAgent` opens one by naming the `line_id` financing the device, the `device_id` being financed, a `term_months` that must be one of 12, 24, or 36 (any other value being rejected with `ERR_VALIDATION`), and a `down_payment_cents` paid up front. Two preconditions guard creation: the device must have stock, meaning `stock_count` is greater than 0, and the down payment must be strictly less than the device's retail price, meaning `down_payment_cents` is less than `retail_price_cents`; either failure is reported as `ERR_DEVICE_UNAVAILABLE` (HTTP 409). On creation the financed amount `financed_cents` is the device's `retail_price_cents` minus the `down_payment_cents`. The per-cycle charge `monthly_installment_cents` is `financed_cents` divided by `term_months`, rounded up to the next whole cent, so that the schedule never under-collects; the final installment absorbs the rounding remainder so that the sum of all installments equals `financed_cents` exactly. The outstanding `remaining_balance_cents` starts equal to `financed_cents`, the `installments_paid` counter starts at 0, and the plan's `status` is `ACTIVE`. The installment `status` enumeration is `ACTIVE`, `PAID_OFF`, and `CANCELLED`, where `CANCELLED` arises only through a superseding upgrade. Opening the EIP decrements the device's `stock_count` by one and recomputes the account's `total_eip_outstanding_cents`.

At each billing-cycle close, an active installment plan has its `remaining_balance_cents` decremented by its `monthly_installment_cents` (floored at zero), its `installments_paid` advanced by one, and — if the remaining balance reaches 0 — its `status` driven from `ACTIVE` to `PAID_OFF`. Whenever any plan pays off, accelerates, or is superseded, the account's `total_eip_outstanding_cents` is recomputed; that field is at all times the sum of `remaining_balance_cents` across the installment plans whose `status` is `ACTIVE` belonging to the account's lines.

An upgrade swaps one financed device for another in a single atomic action performed by a `CarrierAgent`. The request names the `line_id` being upgraded, the `old_installment_plan_id` to be superseded (which must be an `ACTIVE` installment plan on that line), the `new_device_id` to be financed, the `new_term_months` (again one of 12, 24, or 36, any other value rejected with `ERR_VALIDATION`), the `new_down_payment_cents`, and a `trade_in_credit_cents` applied against the old device's balance. The same device-availability precondition applies to the new device, so a `new_device_id` with no stock fails with `ERR_DEVICE_UNAVAILABLE`. The one-time settlement charge `payoff_charge_cents` is the old plan's `remaining_balance_cents` at upgrade time minus the `trade_in_credit_cents`, floored at zero so it is never negative; this amount is always recorded on the upgrade order as `payoff_charge_cents`, but it is posted to the ledger as an `EIP_PAYOFF` charge only when the account has an `OPEN` cycle and the amount is strictly positive (a zero payoff, or an upgrade with no open cycle, posts no charge). The old installment plan is moved to `CANCELLED` with its `remaining_balance_cents` settled to 0. A brand-new installment plan is created `ACTIVE` whose financed amount is the new device's `retail_price_cents` minus `new_down_payment_cents` and whose monthly installment is that new financed amount divided by `new_term_months` rounded up to the next whole cent; the new plan's identifier is recorded on the upgrade as `new_installment_plan_id`. The upgrade decrements the new device's `stock_count`, recomputes the account's `total_eip_outstanding_cents`, and is recorded with `status` `COMPLETED`, which is the upgrade's only state because it applies atomically.

### 3.7. Number Portability: Port-In and Port-Out

A port request moves a phone number across a carrier boundary, and it runs as a small adjudicated workflow owned by `PortingOps`. Either a `Subscriber` (on their own line) or a `CarrierAgent` opens the request, naming the `line_id` the port targets, the `direction` (`PORT_IN` to import a number or `PORT_OUT` to surrender one), the `external_number` in E.164 form (the number being imported, or the line's number leaving), the `donor_carrier` name (the carrier surrendering the number on a port-in or receiving it on a port-out), and the `account_pin` transfer-authorization PIN the subscriber supplies. A new port request enters `status` `REQUESTED`. The port `status` enumeration is `REQUESTED`, `VALIDATED`, `COMPLETED`, `REJECTED`, and `REVERTED`. For a port-in, the requested `external_number` must not already be live on another line: if any line currently holds that number as a non-null `phone_number`, the request is rejected with `ERR_NUMBER_IN_USE` (HTTP 409), and the same uniqueness guard is re-checked at completion.

`PortingOps` validates a `REQUESTED` port, moving it to `VALIDATED`. Validation is only defined from `REQUESTED`, failing with `ERR_INVALID_STATE` otherwise. The validate request re-supplies the `account_pin`; if it does not match the PIN stored on the port request, the port is not validated but instead transitions to `REJECTED` with its `reject_reason` set to `PIN_MISMATCH`. The `reject_reason` enumeration is `PIN_MISMATCH`, `NUMBER_NOT_PORTABLE`, and `DONOR_REFUSED`. For a port-out specifically, the targeted line must be `ACTIVE` at validation, and no number actually moves yet at this step.

`PortingOps` completes a `VALIDATED` port, moving it to `COMPLETED`; completion is only defined from `VALIDATED`, again guarded by `ERR_INVALID_STATE`. Completion behaves differently by direction. On a port-in, the line's `phone_number` is set to the imported `external_number`; if the line is still `PENDING_ACTIVATION` it stays pending until it is separately activated. On a port-out, the line's `phone_number` is released to null and the line is driven to `CANCELLED` through the very same cancellation cascade described in §3.5 — the active EIP is accelerated, add-ons are cancelled, the SIM is deactivated, the number-pool invariant is restored, and the account's group discount and version are recomputed and incremented.

`PortingOps` may reject a port from either `REQUESTED` or `VALIDATED`, moving it to `REJECTED`; an attempt from any other state fails with `ERR_INVALID_STATE`. Rejection records the supplied `reject_reason` and touches the line not at all, because the number never moved. Finally, `PortingOps` may revert a completed port, but only a completed `PORT_IN`: revert is defined only from `COMPLETED`, and only for a port-in. A revert attempted on a port-out, or on any port not in `COMPLETED`, is rejected with `ERR_PORT_NOT_REVERTABLE` (HTTP 409); other state mismatches surface as `ERR_INVALID_STATE`. A successful port-in revert clears the line's `phone_number` back to null, returning the number to the donor and restoring the conserved number-pool invariant.

### 3.8. Roaming and International Add-Ons

An add-on attaches a travel data product to a line, and it has a windowed lifecycle driven partly by the clock. Either a `Subscriber` or a `CarrierAgent` attaches one by naming the `line_id`, the `addon_type` (`ROAMING_DAYPASS`, priced per UTC day, or `INTL_MONTHLY`, priced per cycle), the coverage window's inclusive `window_start` and exclusive `window_end`, and the relevant fee: `daily_fee_cents` for a daypass, `monthly_fee_cents` for a monthly. A new add-on enters `status` `SCHEDULED`. The add-on `status` enumeration is `SCHEDULED`, `ACTIVE`, `EXPIRED`, and `CANCELLED`.

Two temporal validations guard add-on creation. The window must be well-formed: `window_end` must be strictly after `window_start`, and for a `ROAMING_DAYPASS` the window must span a whole number of UTC days; either violation is rejected with `ERR_INVALID_WINDOW` (HTTP 422). Additionally, two `ROAMING_DAYPASS` add-ons on the same line must not overlap: their half-open day-ranges from `window_start` (inclusive) to `window_end` (exclusive) must not intersect, though exact adjacency where one ends precisely as the next begins is permitted. The overlap guard considers only existing daypasses in `SCHEDULED`, `ACTIVE`, or `EXPIRED` status; a `CANCELLED` daypass is disregarded and its window may be reused. An overlap is rejected with `ERR_ADDON_OVERLAP` (HTTP 409).

An add-on becomes billable when its window opens. A `SCHEDULED` add-on transitions to `ACTIVE` either automatically when the server clock reaches `window_start`, or explicitly when an operator activates it; in both cases the current UTC must be at or past `window_start` (otherwise `ERR_ADDON_WINDOW_NOT_STARTED`, HTTP 409) and the parent line must be `ACTIVE` (otherwise `ERR_INVALID_STATE`). Once active, an add-on accrues its fee until the clock reaches `window_end`, at which point it moves from `ACTIVE` to `EXPIRED` and stops accruing. A `Subscriber` or `CarrierAgent` may cancel an add-on from either `SCHEDULED` or `ACTIVE`, moving it to `CANCELLED`; a cancel from any other state fails with `ERR_INVALID_STATE`. A cancelled add-on is no longer billed going forward, but for a daypass the days that have already elapsed remain on the cycle ledger.

### 3.9. Usage Ingestion and the Usage Summary

Usage events feed the overage engine. A `CarrierAgent` or the `BillingSystem` ingests one by naming the `line_id` that incurred it, the `usage_type` (`DATA`, `VOICE`, or `TEXT`), the `data_mb` consumed (which defaults to 0 and is 0 for voice and text records), and the `occurred_at` instant. The `occurred_at` must fall inside an open billing cycle for the line's account — that is, at or after the cycle's `cycle_start` and strictly before its `cycle_end`, with the cycle in `OPEN` status; a usage event outside any open cycle is rejected with `ERR_USAGE_OUTSIDE_CYCLE` (HTTP 422). Ingesting a `DATA` record inside the open cycle recomputes the line's `cycle_data_used_mb`.

A line's usage summary is a computed read that a `CarrierAgent`, `Subscriber`, or `BillingSystem` can pull at any time. It returns the current-cycle `cycle_data_used_mb`, the `overage_cents` accrued so far, the `prorated_base_cents` for the cycle to date, and the `projected_line_total_cents`. The overage figure is the tiered-pricing computation detailed in §3.10; the prorated base is the discounted, prorated plan fee; and the projected line total is the sum a closing cycle would currently attribute to the line.

### 3.10. Billing-Cycle Settlement and the Money Math

The `BillingSystem` opens a cycle for an account by naming the `account_id`, the inclusive `cycle_start`, and the exclusive `cycle_end`; the cycle enters `OPEN` status and its `days_in_cycle` is computed as the whole number of UTC days between `cycle_start` and `cycle_end`, which serves as the proration denominator. The supplied window must be well-formed — `cycle_end` strictly after `cycle_start`, otherwise `ERR_VALIDATION` — and an unresolvable `account_id` yields `ERR_FK_NOT_FOUND`. Only one cycle per account may be `OPEN` at a time; attempting to open a second `OPEN` cycle for an account that already has one is rejected with `ERR_INVALID_STATE`. The cycle `status` enumeration is `OPEN` and `CLOSED`. Closing a cycle is the system's heaviest single operation; it is performed by the `BillingSystem` and is defined only from `OPEN` (otherwise `ERR_INVALID_STATE`), and only once the clock has reached the cycle's end, meaning current UTC is at or after `cycle_end` (otherwise `ERR_CYCLE_NOT_ENDED`, HTTP 409). The close posts the cycle's charges, sets the cycle's `total_charges_cents`, and opens a successor cycle.

The arithmetic of a cycle close is precise and order-dependent, and it rests on a small stack of named calculations.

**The multi-line group discount.** The account's `group_discount_pct` is a table lookup keyed on `active_line_count`, where `active_line_count` is the count of lines on the account whose `status` is `ACTIVE` or `SUSPENDED` (lines in `PENDING_ACTIVATION` or `CANCELLED` are excluded). One line or fewer yields a discount of 0.00; exactly two lines yields 0.05; exactly three lines yields 0.10; exactly four lines yields 0.15; five or more lines yields 0.20, which is the cap. The result is exact — it is a table lookup, with no rounding.

**The discounted, prorated plan base.** For each line, the discounted base is the plan's `monthly_fee_cents` multiplied by the quantity one minus `group_discount_pct`, rounded half-up to whole cents. This rounding happens first, before proration. The prorated base is then that discounted base multiplied by the line's active days and divided by `days_in_cycle`, rounded half-up to whole cents — where active days is the count of whole UTC days the line spent in `ACTIVE` or `SUSPENDED` within the cycle window. The order is fixed as round-the-discount-then-prorate, never prorate-then-round: applying the discount and rounding to whole cents must precede the proration multiply and its own rounding.

**The tiered data overage.** For each line, the overage megabytes is the line's `cycle_data_used_mb` minus the plan's `included_data_mb`, floored at zero; if that is zero the overage is zero cents. Otherwise the overage splits across two tiers. The tier-1 megabytes is the lesser of the total overage and the plan's `overage_tier1_cap_mb`; the tier-2 megabytes is the remainder of the overage beyond that cap, floored at zero. The raw milli-cent total is the tier-1 megabytes multiplied by `overage_tier1_rate_milli_cents` plus the tier-2 megabytes multiplied by `overage_tier2_rate_milli_cents`. That milli-cent total is divided by one thousand and rounded half-up to whole cents to give the overage in cents.

**The per-line and account totals.** At close, the account's `group_discount_pct` is computed once from the active line set. Then for each line whose `status` is `ACTIVE` or `SUSPENDED`, the system posts a `PLAN_BASE` charge equal to the line's prorated discounted base, an `OVERAGE` charge equal to the tiered overage, an `EIP_INSTALLMENT` charge equal to the sum of `monthly_installment_cents` across that line's `ACTIVE` installment plans, and `ADDON` charges (for a daypass, `daily_fee_cents` multiplied by the number of billed days, where billed days is the whole UTC days in the intersection of the daypass window with the cycle window irrespective of the daypass's current status, so a cancelled daypass still bills the days that had already elapsed; for a monthly, `monthly_fee_cents` charged once when the monthly is in `ACTIVE` or `EXPIRED` status and its window overlaps the cycle, and never charged while it is still `SCHEDULED` or once `CANCELLED`). Each per-line `ADDON` total is posted as a single combined `ADDON` charge for that line. Any one of these four per-line charges whose computed amount is exactly 0 is not posted at all; only non-zero line items reach the ledger. The line total is the sum of those four parts, and each part is already an integer number of cents. The account cycle total is the integer sum of the per-line totals — that is, each line is rounded into whole cents and then the rounded per-line totals are summed; the system never sums unrounded sub-amounts and rounds once at the end. To make the order unambiguous: with a `monthly_fee_cents` of 6995 across three lines at a 0.10 discount, each line's discounted base is 6296 (because 6295.5 rounds half-up), so the base subtotal across the three lines is 18888 — not the 18887 that a sum-then-round order would have produced. During the close, each active installment plan's `remaining_balance_cents` is decremented by its `monthly_installment_cents` (floored at zero) and its `installments_paid` advanced by one, the plan moving to `PAID_OFF` if its balance reaches zero; the account's `wallet_credit_cents`, when non-zero, is applied against the total by posting a single account-level negative `CREDIT` charge (its `line_id` null) for that wallet amount; the cycle's `total_charges_cents` is set to the sum of the `amount_cents` posted by this close operation — the per-line `PLAN_BASE`, `OVERAGE`, `EIP_INSTALLMENT`, and `ADDON` charges plus the wallet `CREDIT` — and does not re-sum any `EIP_PAYOFF` or `CREDIT` charges that an earlier mid-cycle cancellation already posted into this cycle; and a fresh `OPEN` successor cycle is created for the account whose `cycle_start` equals the closing cycle's `cycle_end` and whose window spans the same number of UTC days (so its `days_in_cycle` equals the closing cycle's), the successor's `total_charges_cents` beginning at 0. The cycle close recomputes the account's derived fields (`active_line_count`, `group_discount_pct`, and `total_eip_outstanding_cents`) and refreshes the account's `updated_at`, but — as a deliberate exception to the §2.5 rule that derived-field refreshes bump `version` — the close does not increment the account's `version`.

**The two cancellation-settlement variants.** A single device balance must never be billed to two cycles, and the two settlement variants are precisely the mechanism that prevents it. The forward, provisional variant runs at the moment a line is cancelled mid-cycle (§3.5): it credits the unused base and accelerates the device. The unused days are `days_in_cycle` minus the active days the line has accrued so far; the forward credit is the discounted base multiplied by those unused days divided by `days_in_cycle`, rounded half-up, and posted as a negative `CREDIT` charge; simultaneously the entire `remaining_balance_cents` of each `ACTIVE` installment plan on the line is posted as a positive `EIP_PAYOFF` charge, settling the device immediately as if kept. These ledger postings are emitted only into the account's currently `OPEN` cycle and only when their amount is strictly positive: the `CREDIT` is posted only when the computed unused-base credit exceeds zero, and each `EIP_PAYOFF` only when the plan's remaining balance exceeds zero; if the account has no `OPEN` cycle at cancel time, no settlement charges are posted at all, yet the cascade's state changes (the installment plans still move to `PAID_OFF` with their balances zeroed, the add-ons still cancel, the SIM still deactivates, the number is still released, and the account is still recomputed) run regardless. The chronological, final variant runs at cycle close for a line that was cancelled during that cycle: it bills only the active days of base as a normal prorated `PLAN_BASE` charge (with no separate unused-day credit), and it posts neither an `OVERAGE` nor an `ADDON` charge for that line. It charges no EIP at close either — it neither accelerates nor bills an ordinary installment — because the cancellation cascade already drove the line's installment plans to `PAID_OFF`, leaving no `ACTIVE` plan to bill; the device was settled in full at cancel time. The two variants therefore attribute the device balance to different cycles and legitimately produce different per-line totals, which is the intended design, not a discrepancy.

The charge ledger records every line item. A charge carries its `billing_cycle_id`, the `line_id` it is attributed to (null for account-level charges), a `charge_type` drawn from the enumeration `PLAN_BASE`, `OVERAGE`, `EIP_INSTALLMENT`, `ADDON`, `EIP_PAYOFF`, and `CREDIT`, a signed `amount_cents` where a positive value is owed and a negative value is a credit or refund, and a human-readable `memo`.

### 3.11. Delinquency and the Operator Clock

The `BillingSystem` can flag an account delinquent through a back-office operation that carries a `delinquent` boolean: when `delinquent` is true the account `status` moves to `DELINQUENT`, and when it is false the account returns to `ACTIVE`. The delinquency flag is the gate behind several guards already described — a `DELINQUENT` account cannot have lines activated or reconnected, and it blocks a non-payment reconnect with `ERR_RECONNECT_BLOCKED`.

For deterministic handling of windowed add-ons and cycle closes, the `BillingSystem` controls a logical clock. Setting the clock supplies a `to_iso8601` instant that becomes the server's current UTC and returns a `data` object carrying a single `current_utc` field echoing that instant as an ISO 8601 UTC timestamp with three fractional digits; advancing it may bring `SCHEDULED` add-ons whose `window_start` has been reached into eligibility for activation, and `ACTIVE` add-ons past their `window_end` are treated as `EXPIRED` on the next read (the clock-set itself eagerly reconciles such add-ons to `EXPIRED`). This capability is an operator and test surface, not part of any subscriber-facing workflow.

## 4. Endpoint Definitions

Endpoints that create a new, standalone resource return `201 Created`; endpoints that modify an existing resource — including all state-transition actions and the close/settlement operations — return `200 OK`. The request and response bodies are not repeated here; they are specified in the §3 narratives. List endpoints accept the pagination and filter query parameters described in §2.3 and §2.4.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/accounts` | Create a billing account | CarrierAgent |
| GET | `/accounts/{accountId}` | Fetch an account with computed billing fields | CarrierAgent, Subscriber, BillingSystem |
| POST | `/accounts/{accountId}/mark-delinquent` | Toggle an account's delinquency flag | BillingSystem |
| POST | `/plans` | Create a plan in the catalog | CarrierAgent |
| GET | `/plans/{planId}` | Fetch a plan | CarrierAgent, Subscriber, BillingSystem |
| POST | `/plans/{planId}/retire` | Retire a plan so it can no longer back new lines | CarrierAgent |
| POST | `/devices` | Create a device in the catalog | CarrierAgent |
| GET | `/devices/{deviceId}` | Fetch a device | CarrierAgent, Subscriber, BillingSystem |
| POST | `/lines` | Provision a new line (OCC-guarded) | CarrierAgent |
| GET | `/lines` | List lines, filterable by account_id or plan_id | CarrierAgent, Subscriber, BillingSystem |
| GET | `/lines/{lineId}` | Fetch a single line | CarrierAgent, Subscriber, BillingSystem |
| POST | `/lines/{lineId}/activate` | Activate a pending line | CarrierAgent |
| POST | `/lines/{lineId}/suspend` | Suspend an active line | CarrierAgent |
| POST | `/lines/{lineId}/reconnect` | Reconnect a suspended line | CarrierAgent |
| POST | `/lines/{lineId}/cancel` | Cancel a line (forward provisional settlement) | Subscriber |
| GET | `/lines/{lineId}/usage-summary` | Computed current-cycle usage and projected total | CarrierAgent, Subscriber, BillingSystem |
| POST | `/sim-assignments` | Issue a SIM/eSIM for a line | CarrierAgent |
| GET | `/sim-assignments/{simAssignmentId}` | Fetch a single SIM assignment | CarrierAgent, Subscriber, BillingSystem |
| GET | `/sim-assignments` | List SIM assignments, filterable by line_id | CarrierAgent, Subscriber, BillingSystem |
| POST | `/installment-plans` | Create a device installment plan on a line | CarrierAgent |
| GET | `/installment-plans/{installmentPlanId}` | Fetch a single installment plan | CarrierAgent, Subscriber, BillingSystem |
| GET | `/installment-plans` | List installment plans, filterable by line_id or device_id | CarrierAgent, Subscriber, BillingSystem |
| POST | `/upgrades` | Upgrade device: pay off old EIP and open a new EIP atomically | CarrierAgent |
| GET | `/upgrades/{upgradeOrderId}` | Fetch a single upgrade order | CarrierAgent, Subscriber, BillingSystem |
| GET | `/upgrades` | List upgrade orders, filterable by line_id, old_installment_plan_id, new_installment_plan_id, or new_device_id | CarrierAgent, Subscriber, BillingSystem |
| POST | `/port-requests` | Open a number port-in or port-out request | Subscriber, CarrierAgent |
| GET | `/port-requests/{portRequestId}` | Fetch a single port request | CarrierAgent, Subscriber, PortingOps, BillingSystem |
| GET | `/port-requests` | List port requests, filterable by line_id | CarrierAgent, Subscriber, PortingOps, BillingSystem |
| POST | `/port-requests/{portRequestId}/validate` | Validate the port request (PIN check) | PortingOps |
| POST | `/port-requests/{portRequestId}/complete` | Complete the port (moves the number) | PortingOps |
| POST | `/port-requests/{portRequestId}/reject` | Reject the port (no number movement) | PortingOps |
| POST | `/port-requests/{portRequestId}/revert` | Revert a completed PORT_IN | PortingOps |
| POST | `/addons` | Attach a roaming/international add-on to a line | Subscriber, CarrierAgent |
| GET | `/addons/{addonId}` | Fetch a single add-on | CarrierAgent, Subscriber, BillingSystem |
| GET | `/addons` | List add-ons, filterable by line_id | CarrierAgent, Subscriber, BillingSystem |
| POST | `/addons/{addonId}/activate` | Activate a scheduled add-on | CarrierAgent, Subscriber |
| POST | `/addons/{addonId}/cancel` | Cancel an add-on | Subscriber, CarrierAgent |
| POST | `/usage-records` | Ingest a usage event for a line | CarrierAgent, BillingSystem |
| GET | `/usage-records/{usageRecordId}` | Fetch a single usage record | CarrierAgent, Subscriber, BillingSystem |
| GET | `/usage-records` | List usage records, filterable by line_id | CarrierAgent, Subscriber, BillingSystem |
| POST | `/billing-cycles` | Open the first/next billing cycle for an account | BillingSystem |
| GET | `/billing-cycles/{cycleId}` | Fetch a single billing cycle | CarrierAgent, Subscriber, BillingSystem |
| GET | `/billing-cycles` | List billing cycles, filterable by account_id | CarrierAgent, Subscriber, BillingSystem |
| POST | `/billing-cycles/{cycleId}/close` | Close a cycle: settle, post charges, open successor | BillingSystem |
| GET | `/charges/{chargeId}` | Fetch a single charge | CarrierAgent, Subscriber, BillingSystem |
| GET | `/charges` | List charges, filterable by billing_cycle_id or line_id | CarrierAgent, Subscriber, BillingSystem |
| POST | `/_clock/set_current_utc` | Set the server's current UTC instant | BillingSystem |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_ACCOUNT_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_FK_NOT_FOUND` | 422 Unprocessable Entity |
| `ERR_VALIDATION` | 422 Unprocessable Entity |
| `ERR_STALE_ACCOUNT_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_PLAN_RETIRED` | 409 Conflict |
| `ERR_SIM_NOT_ISSUED` | 409 Conflict |
| `ERR_ACCOUNT_NOT_ACTIVE` | 409 Conflict |
| `ERR_NUMBER_IN_USE` | 409 Conflict |
| `ERR_PORT_IN_PROGRESS` | 409 Conflict |
| `ERR_PORT_NOT_REVERTABLE` | 409 Conflict |
| `ERR_INVALID_WINDOW` | 422 Unprocessable Entity |
| `ERR_ADDON_OVERLAP` | 409 Conflict |
| `ERR_ADDON_WINDOW_NOT_STARTED` | 409 Conflict |
| `ERR_USAGE_OUTSIDE_CYCLE` | 422 Unprocessable Entity |
| `ERR_DEVICE_UNAVAILABLE` | 409 Conflict |
| `ERR_RECONNECT_BLOCKED` | 409 Conflict |
| `ERR_CYCLE_NOT_ENDED` | 409 Conflict |
