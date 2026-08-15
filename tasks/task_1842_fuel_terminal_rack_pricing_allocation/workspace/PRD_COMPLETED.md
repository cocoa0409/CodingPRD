# Fuel Terminal Rack Pricing API — Product Requirements Document

## 1. Introduction

A refiner's rack marketing desk lives and dies by the morning price sheet. Every day, pricing analysts post rack prices per product and terminal, allocation managers decide how many gallons the rack will honor when supply runs tight, and terminal operators load trucks against customer entitlements while the credit desk watches exposure accumulate in near real time. This document specifies the Fuel Terminal Rack Pricing API, the system of record for that desk: daily rack price setting by product and terminal, customer lifting rights with ratable allocation under shortage, exchange agreements between suppliers, bill-of-lading capture with inventory drawdown, branded additive injection at the load rack, four-level motor-fuel tax determination, and credit-hold enforcement at the moment of lifting.

Two properties of the domain shape the design. First, almost everything is dated: prices, allocation notices, and tax rules all take effect on a logical date, so the server runs on its own logical clock rather than wall-clock time. Second, money moves through the system as integer cents at every stage — from the posted rack price through additive line items and excise tax to the open credit exposure that can flip a customer onto hold mid-shift. The API is mounted under `/rack` and is organized so that pricing, allocation, credit, and contract administration remain segregated duties, each owned by a distinct role.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming the capacity in which they act. A request missing either header, or presenting a role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The recognized roles, spelled exactly as the server expects them, are `PlatformAdmin`, `RackPriceAnalyst`, `AllocationManager`, `TerminalOperator`, `ExchangeCoordinator`, `CreditAnalyst`, `BillingClerk`, and `ContractAdministrator`. Each endpoint admits a defined subset of these roles; a caller whose role is not admitted to the endpoint they invoked is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

For every one of these roles — `PlatformAdmin`, `RackPriceAnalyst`, `AllocationManager`, `TerminalOperator`, `ExchangeCoordinator`, `CreditAnalyst`, `BillingClerk`, and `ContractAdministrator` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server never compares `X-User-ID` against the `id` of a customer, terminal, or any other resource; authorization is decided by role alone. This is a deliberate segregation-of-duties model: the `ContractAdministrator` who owns supply contracts cannot place or release credit holds, the `CreditAnalyst` who manages holds cannot close contracts, and only the `TerminalOperator` may capture a bill of lading.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. A non-integer `limit` falls back to the default of 10, and an out-of-range integer is clamped into [1, 100]. The `offset` parameter skips that many items from the front of the result set and defaults to 0; a non-integer `offset` falls back to 0 and a negative integer is clamped up to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, with ties broken by creation order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true exactly when `offset + (number of items returned) < total_count`.

### 2.4. The Logical Clock and Effective Dating

The server keeps its own logical clock. On startup the clock reads 2026-08-01T00:00:00Z, and it does not advance with wall-clock time; an admin-only, test-driving capability moves it to a caller-supplied `to_iso8601` timestamp and answers with the resulting `current_utc`. The supplied `to_iso8601` must be a parseable ISO 8601 timestamp (a trailing `Z` or a numeric offset are both accepted); an unparseable value is rejected with `ERR_VALIDATION` (HTTP 400). The returned `current_utc` renders whole-second values without a fractional part (for example `2026-08-15T00:00:00Z`) and sub-second values with three fractional digits. This logical clock — never the wall clock — decides which calendar date a price schedule or allocation notice takes effect on, whether a contract is inside its effective window, which calendar month an exchange delivery counts toward, and whether the 24-hour bill-of-lading reversal window is still open.

Advancing the clock is not inert. When the logical date moves past a supply contract's `end_date`, every lifting right tied to that contract — whether `ACTIVE` or `SUSPENDED` — automatically transitions to `EXPIRED` without any client call on the right itself.

### 2.5. Common Resource Properties

Every primary resource — terminals, products, customers, price schedules, lifting rights, supply contracts, exchange agreements, allocation notices, lifting tickets, and tax jurisdiction rules — carries a standard system-managed quartet:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, fixed at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that starts at 1 at creation and increments with every mutation, including mutations driven by cascading side effects.

The two audit resources are the exception. A BOL event and a credit hold log entry are immutable once recorded: each carries `id` and `created_at` plus its own `occurred_at` logical-clock timestamp, and both `updated_at` and `version` are absent from these records.

### 2.6. Integer-Cent Arithmetic and Rounding Discipline

All money in this system is integer cents, and all per-gallon rates are whole cents per gallon unless a rule explicitly denominates otherwise. Per-gallon unit prices on a lifting ticket are integer cents per gallon. Motor-fuel excise is computed as whole gallons times a whole-cents-per-gallon rate, so no rounding ever arises in the tax stack. Branded additive injection is the one place rounding exists, and its discipline is pinned: each additive recipe line is converted from millicents to cents and rounded half up to a whole cent *before* the lines are summed — the ticket's additive cost is a sum of rounded lines, never a rounding of the sum, and on a multi-line recipe the two orders can differ by real cents. Gallon arithmetic for allocation shares uses whole gallons throughout, with proportional shares rounded down as described in §3.4.

### 2.7. Optimistic Concurrency on Terminal Writes

Exactly two write operations are guarded by optimistic concurrency control against the Terminal aggregate: publishing a price schedule and publishing an allocation notice. Each of those requests must carry `expected_terminal_version` in its body, holding the terminal `version` the caller last observed. If the value does not equal the Terminal's current `version` — for example because another writer has since published a competing schedule for the same terminal, product, and date, or a competing notice for the same terminal and date, each of which legitimately increments the terminal's version — the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and nothing is mutated. The caller is expected to re-read the terminal and decide afresh. No other endpoint accepts a version field; all other writes proceed without an OCC check.

### 2.8. Request Validation Pipeline

Every request is checked against a fixed pipeline, and earlier failures mask later ones. Authentication comes first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_UNAUTHORIZED`), then existence: every identifier in the path and every referenced resource in the body must resolve, or the request fails with `ERR_NOT_FOUND` (HTTP 404). Next, on every action endpoint — publish, void, suspend, reinstate, activate, close, terminate, freeze, unfreeze, post-bol, reverse-bol, cancel, invoice, place-hold, and release-hold — the target resource must be in a state from which the requested transition is allowed; each transition names its own specific state error in §3, and where no more specific state error applies, the generic rejection is `ERR_INVALID_STATE` (HTTP 409). Only after state admissibility do business rules run, and where several business rules guard one endpoint they run in the orders stated in §3 — so, for instance, a frozen terminal surfaces before a missing published price, and a customer credit hold surfaces before an allocation shortfall.

### 2.9. Open Credit Exposure and Hold Contagion

A customer's `open_lifting_exposure_cents` is the live sum of `gross_cents` across that customer's lifting tickets in `RESERVED` or `BOL_ISSUED` status — the post-reservation, pre-invoice pipeline. Reservation adds a provisional gross to the exposure; cancellation and invoicing each subtract the ticket's gross; posting a bill of lading replaces the provisional figure with the final one, so the exposure can drift up or down at post time without any new reservation. The exposure is enforced in two places with two different postures: at reservation time it is a hard gate (a reservation that would push exposure past `credit_limit_cents` is refused), while at bill-of-lading time it is a contagion trigger — the load posts anyway, and the over-limit condition flips the customer onto credit hold so that no further reservations or postings can follow. Every placement and every release of a hold is written to an append-only credit hold log described in §3.2.

## 3. Business Logic & Workflows

### 3.1. Rack Master Data: Terminals, Products, and Tax Jurisdictions

A `PlatformAdmin` onboards a terminal by supplying its `terminal_code` (for example `LAX-01`), the operator's `legal_name`, and three geography codes that later drive taxation: `state_code` (the two-letter state), `county_code` (the county FIPS code, which may add a county-level motor-fuel excise), and `city_code` (which may add a city-level excise). A new terminal opens with `rack_status` of `OPEN`, zero `inventory_gallons`, and zero `daily_allocation_pool_gallons`. The terminal list can be filtered by `state_code` or `rack_status`.

Physical stock reaches the books two ways. Bills of lading debit inventory automatically (§3.6), and a `TerminalOperator` may post a manual inventory adjustment carrying a signed `delta_gallons` — positive adds gallons, negative removes them — together with a free-text `reason`; the `reason` is accepted but not persisted on the terminal, a missing or non-integer `delta_gallons` is treated as 0, and the adjustment lands directly on `inventory_gallons` and increments the terminal's `version`. Freezing is the emergency brake: a `TerminalOperator` may freeze a terminal that is `OPEN` or `SHORTAGE`, moving `rack_status` to `FROZEN` and incrementing `version`; attempting to freeze a terminal that is not `OPEN` (including one already `FROZEN`) is rejected with `ERR_TERMINAL_NOT_OPEN`. Unfreezing returns a `FROZEN` terminal to `OPEN` and likewise increments `version`; unfreezing a terminal that is not `FROZEN` fails with `ERR_TERMINAL_NOT_FROZEN`. A `FROZEN` rack blocks all bill-of-lading capture, as §3.6 details.

Products are simpler. A `PlatformAdmin` creates each sellable product with a unique `product_code` (such as `REG87`, `PREM93`, or `ULSD`), a human-readable `display_name`, a `product_family` of `GASOLINE`, `DIESEL`, or `JET` — the family selects both the eligible additive packages and the excise tax tables — and an optional `is_brandable` flag that defaults to false and governs whether branded additive injection may be sold against the product. The product list filters by `product_family`.

Tax jurisdiction rules complete the master data. Each rule, created by a `PlatformAdmin`, binds a `jurisdiction_level` of `FEDERAL`, `STATE`, `COUNTY`, or `CITY` to a `jurisdiction_code` — `US` for federal, a state code such as `CA`, a county FIPS such as `06037`, or a city code such as `LAX` — plus a `product_family`, an excise `rate_cents_per_gal`, and an effective window from `effective_start_date` through `effective_end_date`, both dates inclusive. A rule's `status` is `ACTIVE` while the rate is in force and `RETIRED` once withdrawn; the rule list filters by `jurisdiction_level`, `jurisdiction_code`, `product_family`, or `status`. How these rules combine at load time is specified in §3.6.

### 3.2. Customers, Credit Governance, and Supply Contracts

A `PlatformAdmin` registers each customer with a unique `customer_code`, a `legal_name`, and a `credit_limit_cents` ceiling. New customers start with `credit_status` of `GOOD`, zero `open_lifting_exposure_cents`, and no `hold_reason`. The customer list filters by `credit_status`.

Credit holds come in three flavors, all converging on the same `GOOD` → `HOLD` transition. A `CreditAnalyst` may place a manual hold, passing a `reason` that is recorded as the customer's `hold_reason`; the manual placement requires the customer to currently be in `GOOD` — placing a hold on a customer not in `GOOD` is rejected with `ERR_INVALID_STATE` (HTTP 409). The system itself places holds: when a posted bill of lading pushes a customer's open exposure past the credit ceiling (§3.6), the customer flips to `HOLD` with `hold_reason` set to `OVER_LIMIT`, and when a supply contract closes in default (below), the customer flips to `HOLD` with `hold_reason` set to `CONTRACT_DEFAULT`. Every placement appends a `PLACED` entry to the credit hold log — an immutable record carrying the `customer_id`, an `event_type` of `PLACED` or `RELEASED`, a `trigger_reason` explaining why the event fired (`OVER_LIMIT`, `MANUAL`, `SHORTAGE_ABUSE`, `RELEASED`, or `CONTRACT_DEFAULT`), a snapshot `open_exposure_cents_at_event`, and the `occurred_at` logical timestamp. Release is exclusively a `CreditAnalyst` action: it requires the customer to currently be in `HOLD` (otherwise `ERR_CUSTOMER_NOT_ON_HOLD`, HTTP 409), moves the customer back to `GOOD`, clears `hold_reason`, and appends a `RELEASED` log entry. The log is read-only and can be listed filtered by `customer_id` or `event_type`. While a customer is in `HOLD`, two operations are refused with `ERR_CUSTOMER_ON_CREDIT_HOLD` (HTTP 402): creating a lifting ticket and posting a bill of lading.

Supply contracts sit between the customer and their lifting rights. A `ContractAdministrator` creates a contract for a `customer_id` with a `start_date`, an `end_date` that must not fall before the start date (an `end_date` earlier than `start_date` is rejected with `ERR_VALIDATION`, HTTP 422), a `volume_commitment_gallons` total for the term, and a `pricing_tier` of `RACK`, `RACK_MINUS_1`, or `RACK_MINUS_2` that keys the per-gallon discount applied at bill-of-lading price determination. Contracts are born in `DRAFT` with `lifted_to_date_gallons` at zero; the contract list filters by `customer_id` or `status`.

Activation moves a contract `DRAFT` → `ACTIVE`. It requires the contract to currently be `DRAFT` (`ERR_CONTRACT_NOT_DRAFT`, HTTP 409) and the logical clock's current date to fall within the contract window — on or after `start_date` and on or before `end_date` — failing which the request is rejected with `ERR_CONTRACT_NOT_IN_WINDOW` (HTTP 422).

Closing a contract is where the volume commitment is judged. The `ContractAdministrator`'s close call accepts an optional `outcome` hint. When lifted gallons meet or exceed the commitment, the contract transitions `ACTIVE` → `CLOSED`. When `lifted_to_date_gallons` falls short of `volume_commitment_gallons`, the server instead transitions the contract `ACTIVE` → `DEFAULTED` — unless the caller explicitly passed `outcome` as `CLOSED`, in which case the shortfall is an error, `ERR_VOLUME_SHORTFALL` (HTTP 422), and nothing changes. A close attempted on a contract that is not `ACTIVE` fails with `ERR_CONTRACT_NOT_ACTIVE` (HTTP 409). Either close outcome cascades: every lifting right tied to the contract that is still `ACTIVE` transitions to `EXPIRED`. A default additionally places the customer on credit hold — `GOOD` → `HOLD` with `hold_reason` of `CONTRACT_DEFAULT` and a `PLACED` credit hold log entry whose `trigger_reason` is `CONTRACT_DEFAULT`; if the customer is already on `HOLD`, the default-driven hold placement is a no-op (no state change and no additional log entry).

### 3.3. Daily Rack Price Setting

Each morning the `RackPriceAnalyst` drafts price schedules. Creating a schedule names the `terminal_id` and `product_id`, an `effective_date` on which the price takes effect at 00:00 local terminal time, the unbranded `posted_rack_cents_per_gal`, and an optional `branded_premium_cents_per_gal` that defaults to zero and is added per gallon when a buyer elects branded additive injection. A schedule is born in `DRAFT`, and the schedule list filters by `terminal_id`, `product_id`, `effective_date`, or `status`. At most one schedule is ever `PUBLISHED` for a given terminal, product, and effective date.

Publishing is the consequential act, and its checks run in a fixed order. The schedule must currently be `DRAFT`, else `ERR_SCHEDULE_NOT_DRAFT` (HTTP 409). Its `effective_date` must not be earlier than the logical clock's current date, else `ERR_SCHEDULE_DATE_IN_PAST` (HTTP 422). The `posted_rack_cents_per_gal` must be greater than zero, else `ERR_INVALID_PRICE` (HTTP 422). Finally the optimistic concurrency guard of §2.7 runs: the body's `expected_terminal_version` must equal the terminal's current `version`, else `ERR_STALE_VERSION` (HTTP 412). On success the schedule transitions `DRAFT` → `PUBLISHED`, its `published_at` is stamped once and is immutable thereafter, any other `PUBLISHED` schedule for the same terminal, product, and effective date cascades to `SUPERSEDED`, and the terminal's `version` increments with its `updated_at` refreshed. A schedule the analyst decides not to use may be voided while still `DRAFT` (`ERR_SCHEDULE_NOT_DRAFT` otherwise), moving it `DRAFT` → `VOIDED`; both `SUPERSEDED` and `VOIDED` are terminal.

The published schedule is what a bill of lading prices against. The per-gallon `unit_price_cents_per_gal` starts from the schedule's `posted_rack_cents_per_gal`, adds the `branded_premium_cents_per_gal` if the load is branded, then subtracts the contract tier discount — zero cents per gallon for `RACK`, one cent for `RACK_MINUS_1`, two cents for `RACK_MINUS_2` — with the result floored at zero so the unit price never goes negative. Should a race ever leave two `PUBLISHED` schedules covering the same terminal, product, and date, the one with the later `published_at` wins, with earlier `created_at` breaking a tie. Timing matters as much as arithmetic: a reservation prices provisionally against the schedule in effect on the reservation's logical date, while the final price re-reads the schedule in effect on the posting date — so if a new schedule publishes between reservation and posting, the new price wins and the provisional figure is discarded.

### 3.4. Lifting Rights and Shortage Allocation

A lifting right is the customer's entitlement to pull a product from a terminal. An `AllocationManager` creates one by naming the `customer_id`, `terminal_id`, `product_id`, the `contract_id` of the governing supply contract, and the customer's `daily_ratable_gallons` — the daily entitlement under normal operations. The right is born `ACTIVE` with `lifted_today_gallons`, `reserved_gallons`, and `allocated_gallons` all at zero; the rights list filters by `customer_id`, `terminal_id`, `product_id`, `contract_id`, or `status`. While no allocation notice governs the current date — equivalently, while the terminal is `OPEN` — a right's `allocated_gallons` simply mirrors its `daily_ratable_gallons`; once a shortage notice publishes, `allocated_gallons` carries the output of the allocation math below.

Suspending a right (`ACTIVE` → `SUSPENDED`) is an `AllocationManager` action that requires the right to currently be `ACTIVE`, failing `ERR_RIGHT_NOT_ACTIVE` (HTTP 409). Suspension cascades through the right's open pipeline: every lifting ticket of that right still in `RESERVED` transitions to `CANCELLED`, each cancelled ticket's gallons are credited back out of the right's `reserved_gallons`, and the customer's `open_lifting_exposure_cents` is credited by the sum of those tickets' `gross_cents`. Reinstatement (`SUSPENDED` → `ACTIVE`) requires the right to currently be `SUSPENDED` (`ERR_RIGHT_NOT_SUSPENDED`, HTTP 409) and additionally requires the customer's `credit_status` to be `GOOD` — reinstating a right for a customer on hold is refused with `ERR_CUSTOMER_ON_CREDIT_HOLD`. Rights also die with their contract: when the logical clock moves past the contract's `end_date`, the right transitions to `EXPIRED` whether it was `ACTIVE` or `SUSPENDED`, and `EXPIRED` is terminal.

When supply runs short, the `AllocationManager` drafts an allocation notice naming the `terminal_id`, the `effective_date` it governs, the `total_pool_gallons` the terminal will sell across all customers that day, and an `allocation_method` of `PRO_RATA` or `RATCHET`. The notice is born in `DRAFT`; the notice list filters by `terminal_id`, `effective_date`, or `status`. Publishing a notice runs its own ordered gauntlet: the notice must be `DRAFT` (`ERR_NOTICE_NOT_DRAFT`, HTTP 409), its `effective_date` must not precede the logical clock's date (`ERR_NOTICE_DATE_IN_PAST`, HTTP 422), `total_pool_gallons` must be greater than zero (`ERR_INVALID_POOL`, HTTP 422), and the §2.7 optimistic concurrency guard applies — the body's `expected_terminal_version` must match the terminal's current `version`, else `ERR_STALE_VERSION` (HTTP 412).

A successful publish reshapes the whole terminal. The notice transitions `DRAFT` → `PUBLISHED` with its `published_at` stamped at that moment, and any previously `PUBLISHED` notice for the same terminal and effective date cascades to `SUPERSEDED`. The terminal's `daily_allocation_pool_gallons` is set to the notice's pool. The terminal's posture is re-evaluated: if the pool is smaller than the combined `daily_ratable_gallons` of the `ACTIVE` rights at that terminal, an `OPEN` terminal moves `OPEN` → `SHORTAGE`; if the pool meets or exceeds that combined entitlement, a `SHORTAGE` terminal returns to `OPEN`. A `FROZEN` terminal's `rack_status` is not altered by notice publication. Every `ACTIVE` right at the terminal has its `lifted_today_gallons` reset to zero for the new effective date, and the terminal's `version` increments. Only rights `ACTIVE` on the notice's effective date participate in the pool; `SUSPENDED` and `EXPIRED` rights are excluded entirely.

The two allocation methods then write each participating right's `allocated_gallons` in whole gallons. Under `PRO_RATA`, each right's initial share is the largest whole number of gallons not exceeding the pool multiplied by that right's `daily_ratable_gallons` and divided by the sum of `daily_ratable_gallons` across all participating rights. Because every share is rounded down, the distributed total may fall short of the pool, and the leftover gallons are dealt out one gallon at a time to rights in order of descending `daily_ratable_gallons`, ties broken by earlier `created_at`, until the remainder is gone. Under `RATCHET`, the pool is first divided into an equal share — the largest whole number of gallons not exceeding the pool divided by the number of participating rights — and each right receives the lesser of its `daily_ratable_gallons` and that equal share. The surplus remaining after this first pass is then distributed one gallon at a time to rights still below their `daily_ratable_gallons`, again visiting rights in order of descending `daily_ratable_gallons` with ties broken by earlier `created_at`, and repeating until no surplus remains or every right has reached its full entitlement.

While a terminal is in `SHORTAGE`, reservations are capped at this rationed share rather than the full daily ratable; §3.6 states the exact reservation gate.

### 3.5. Exchange Agreements Between Suppliers

Exchange agreements let the rack deliver product on behalf of a counterparty supplier. An `ExchangeCoordinator` creates one by naming the `delivering_terminal_id` that physically delivers, an opaque `receiving_supplier_code` identifying the external counterparty (no counterparty entity is persisted), the `product_id`, and the `monthly_exchange_cap_gallons` the delivering terminal will honor for that counterparty in a calendar month. The agreement's `delivered_this_month_gallons` starts at zero and accumulates every gallon delivered under the agreement; the counter is never reset by month rollover and is not enforced against `monthly_exchange_cap_gallons` at bill-of-lading time — the cap is recorded on the agreement but not gated on by posting. Agreements are listed with filters on `delivering_terminal_id`, `product_id`, or `status`.

The lifecycle runs `PROPOSED` → `ACTIVE` → `SUSPENDED` → back to `ACTIVE`, with `TERMINATED` as the terminal state reachable from either `ACTIVE` or `SUSPENDED`. Activation requires the agreement to currently be `PROPOSED`, else `ERR_AGREEMENT_NOT_PROPOSED` (HTTP 409). Suspension requires `ACTIVE`, else `ERR_AGREEMENT_NOT_ACTIVE` (HTTP 409). Reinstatement requires `SUSPENDED`, else `ERR_AGREEMENT_NOT_SUSPENDED` (HTTP 409). Termination from `ACTIVE` carries the same `ACTIVE` requirement (an attempt from `PROPOSED` fails with `ERR_AGREEMENT_NOT_ACTIVE`), while termination from `SUSPENDED` requires the agreement to be `SUSPENDED`. Only an `ACTIVE` agreement accumulates deliveries: §3.6 describes how a posted bill of lading increments `delivered_this_month_gallons` when the load matches an active agreement's terminal and product.

### 3.6. Reserving and Posting a Lifting

The daily flow at the rack begins when a `TerminalOperator` reserves a lifting. The reservation payload names the entitlement via `lifting_right_id` and the `requested_gallons`; a branded load additionally sets `branded` to true — it defaults to false when omitted — and supplies an `additive_package_code` selecting the injection recipe. The created ticket denormalizes the right's context onto its own `customer_id`, `terminal_id`, and `product_id` fields so ticket lists can filter by any of `lifting_right_id`, `customer_id`, `terminal_id`, `product_id`, or `status`. The ticket enters `RESERVED`; the right's `reserved_gallons` grows by the requested gallons; a provisional `gross_cents` is computed from the price schedule in effect on the reservation's logical date and added to the customer's `open_lifting_exposure_cents`; and a `RESERVED` entry lands in the BOL event audit trail. Reservation does not require a published price: when no `PUBLISHED` schedule covers the terminal, product, and reservation date, the ticket's `unit_price_cents_per_gal`, `additive_cost_cents`, `tax_cents`, and `gross_cents` are all provisionally zero (the published-price gate exists only at post-bol).

Reservation enforces four business gates, evaluated in order after authentication, authorization, and existence. First, the customer's `credit_status` must be `GOOD` — a hold surfaces as `ERR_CUSTOMER_ON_CREDIT_HOLD` (HTTP 402) rather than being masked by the later checks. Second, the requested gallons must fit the right's remaining entitlement: under `OPEN` that remainder is `daily_ratable_gallons` minus `lifted_today_gallons` minus `reserved_gallons`, and when the terminal is in `SHORTAGE` with a notice published for the current date, the right's `allocated_gallons` takes the place of `daily_ratable_gallons` in that computation — an overrun is `ERR_ALLOCATION_EXCEEDED` (HTTP 422). Third, a branded request requires the product's `is_brandable` to be true and the `additive_package_code` to name a known recipe, else `ERR_INVALID_ADDITIVE_PACKAGE` (HTTP 422). Fourth, the credit gate: after adding this reservation, the customer's `open_lifting_exposure_cents` — including the new provisional `gross_cents` — must not exceed `credit_limit_cents`, else the reservation is refused with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402).

Posting the bill of lading is the point of no return, executed by a `TerminalOperator`. Its five checks also run in order: the ticket must be `RESERVED` (`ERR_TICKET_NOT_RESERVED`, HTTP 409); the terminal must not be `FROZEN` (`ERR_TERMINAL_FROZEN`, HTTP 409); the customer must be `GOOD` (`ERR_CUSTOMER_ON_CREDIT_HOLD`, HTTP 402); the terminal's `inventory_gallons` must be at least the `requested_gallons` (`ERR_INSUFFICIENT_INVENTORY`, HTTP 422); and a `PUBLISHED` price schedule must cover the terminal, product, and the logical clock's date (`ERR_NO_PUBLISHED_PRICE`, HTTP 422).

A successful post reprices everything final. The `unit_price_cents_per_gal` is recomputed per §3.3 against the schedule in effect on the posting date. The `additive_cost_cents` is zero for an unbranded load; for a branded load it sums the recipe's lines, where each line contributes the `requested_gallons` multiplied by the line's millicents-per-gallon rate, divided by one thousand to convert millicents to cents and rounded half up to a whole cent, plus the line's flat fee in cents — with rounding applied per line before summation, per §2.6. Three recipes exist: `PKG_A` blends two lines, one at 250 millicents per gallon with a 500-cent flat fee and one at 100 millicents per gallon with no flat fee; `PKG_B` is a single line at 175 millicents per gallon with a 750-cent flat fee; `PKG_C` stacks three lines at 333 millicents per gallon with no flat fee, 167 millicents per gallon with a 250-cent flat fee, and 100 millicents per gallon with no flat fee. The `tax_cents` then stacks up to four levels of motor-fuel excise — `FEDERAL` matched on jurisdiction code `US`, `STATE` matched on the terminal's `state_code`, `COUNTY` on its `county_code`, and `CITY` on its `city_code`. At each level the system selects the `ACTIVE` tax rule matching that level, jurisdiction code, and the product's `product_family` whose effective window contains the logical date; if several active rules match one level, the one with the latest `effective_start_date` wins, with earlier `created_at` breaking a tie. Each selected level contributes the `requested_gallons` multiplied by its `rate_cents_per_gal`, and a branded load at a California terminal — one whose `state_code` is `CA` — carries an additional 2 cents per gallon of branded-blend uplift at the `STATE` level, added before the levels are summed. The ticket's `gross_cents` is then the `requested_gallons` multiplied by the `unit_price_cents_per_gal`, plus the `additive_cost_cents`, plus the `tax_cents`, and this final figure replaces the provisional gross inside the customer's exposure.

Posting then ripples outward. A `bol_number` is minted in the format `BOL-<terminal_code>-<yyyymmdd>-<seq>`. The terminal's `inventory_gallons` is debited by the requested gallons; the right's `lifted_today_gallons` grows and its `reserved_gallons` shrinks by the same amount; the governing contract's `lifted_to_date_gallons` grows by it; and when an `ACTIVE` exchange agreement matches the terminal and product, its `delivered_this_month_gallons` grows too. A `POSTED` BOL event is appended with a snapshot `event_payload` of the computed price, tax, and inventory deltas. Finally the contagion rule of §2.9 fires: the load posts regardless, but if the customer's `open_lifting_exposure_cents` exceeds `credit_limit_cents` once the final gross is in place, the customer transitions `GOOD` → `HOLD` with `hold_reason` of `OVER_LIMIT` and a `PLACED` credit hold log entry — blocking that customer's next reservation and next posting even though this one went through.

### 3.7. Reversal, Cancellation, Invoicing, and the Audit Trail

Three exits remain once a ticket exists. Cancellation, by a `TerminalOperator`, applies only while the ticket is `RESERVED` (`ERR_TICKET_NOT_RESERVED` otherwise): the right's `reserved_gallons` is relieved by the requested gallons, the customer's `open_lifting_exposure_cents` drops by the ticket's `gross_cents`, the ticket transitions `RESERVED` → `CANCELLED`, and a `CANCELLED` BOL event is appended.

Reversal is the compensating action for a mis-posted load, and the clock bounds it. Per the §2.8 pipeline the state check runs first — the ticket must be `BOL_ISSUED`, else `ERR_TICKET_NOT_BOL_ISSUED` (HTTP 409) — and only then is the clock consulted: reversal must execute within 24 logical hours of the posting call, else `ERR_REVERSAL_WINDOW_EXPIRED` (HTTP 422). A reversal returns the ticket `BOL_ISSUED` → `RESERVED` and unwinds the posting symmetrically — the terminal's `inventory_gallons` is credited back, the right's `lifted_today_gallons` is decremented and its `reserved_gallons` restored, the contract's `lifted_to_date_gallons` is decremented, and any exchange agreement counter previously incremented is decremented in turn. A `REVERSED` BOL event is appended carrying the original posting's `event_payload`. The customer's `open_lifting_exposure_cents` is deliberately untouched by a reversal: the ticket is back in `RESERVED`, so its gross remains inside the exposure.

Invoicing is the `BillingClerk`'s finalization: the ticket must be `BOL_ISSUED` (`ERR_TICKET_NOT_BOL_ISSUED` otherwise), transitions `BOL_ISSUED` → `INVOICED`, and the customer's `open_lifting_exposure_cents` drops by the ticket's `gross_cents`, closing out that load's claim on the credit line. Both `INVOICED` and `CANCELLED` are terminal.

Every state change above is visible in the append-only BOL event stream. Each event records the `lifting_ticket_id` it belongs to, an `event_type` of `RESERVED`, `POSTED`, `REVERSED`, or `CANCELLED`, an `event_payload` snapshotting the computed price, tax, and inventory deltas at event time, and the `occurred_at` logical timestamp. Invoicing does not append an event. The payload shape depends on the event type: a `RESERVED` payload carries `requested_gallons`, `unit_price_cents_per_gal`, `additive_cost_cents`, `tax_cents`, `gross_cents`, `provisional` (true), and `inventory_delta_gallons` (0); a `POSTED` payload carries the same pricing fields with `provisional` false, plus `bol_number`, `inventory_delta_gallons` (the negated posted gallons), and `exchange_agreement_ids` (the list of agreement ids whose monthly counter was incremented); a `REVERSED` payload is the verbatim copy of the original `POSTED` payload; and a `CANCELLED` payload carries `requested_gallons`, `gross_cents`, and `inventory_delta_gallons` (0). The stream is read-only, fetchable one event at a time or as a list filtered by `lifting_ticket_id` or `event_type` — together with the credit hold log of §3.2, it is the desk's complete after-the-fact account of who lifted what, at which price, and under whose credit.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that read or modify an existing resource — including all state-transition actions — return `200 OK`. Errors carry the envelope and codes of §2.2 and §5.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/rack/terminals` | Create a terminal | PlatformAdmin |
| GET | `/rack/terminals/{terminalId}` | Fetch a terminal | PlatformAdmin, RackPriceAnalyst, AllocationManager, TerminalOperator, ExchangeCoordinator, CreditAnalyst, BillingClerk, ContractAdministrator |
| GET | `/rack/terminals` | List terminals | PlatformAdmin, RackPriceAnalyst, AllocationManager, TerminalOperator, ExchangeCoordinator, CreditAnalyst, BillingClerk, ContractAdministrator |
| POST | `/rack/terminals/{terminalId}/freeze` | Freeze a terminal (block all liftings) | TerminalOperator |
| POST | `/rack/terminals/{terminalId}/unfreeze` | Unfreeze a terminal | TerminalOperator |
| POST | `/rack/terminals/{terminalId}/inventory/adjust` | Manual inventory adjustment (positive adds gallons, negative removes) | TerminalOperator |
| POST | `/rack/products` | Create a product | PlatformAdmin |
| GET | `/rack/products/{productId}` | Fetch a product | PlatformAdmin, RackPriceAnalyst, AllocationManager, TerminalOperator, ExchangeCoordinator, CreditAnalyst, BillingClerk, ContractAdministrator |
| GET | `/rack/products` | List products | PlatformAdmin, RackPriceAnalyst, AllocationManager, TerminalOperator, ExchangeCoordinator, CreditAnalyst, BillingClerk, ContractAdministrator |
| POST | `/rack/customers` | Create a customer | PlatformAdmin |
| GET | `/rack/customers/{customerId}` | Fetch a customer | PlatformAdmin, CreditAnalyst, BillingClerk, ContractAdministrator, TerminalOperator |
| GET | `/rack/customers` | List customers | PlatformAdmin, CreditAnalyst, BillingClerk, ContractAdministrator |
| POST | `/rack/customers/{customerId}/place-hold` | Manually place customer on credit hold | CreditAnalyst |
| POST | `/rack/customers/{customerId}/release-hold` | Release customer credit hold | CreditAnalyst |
| POST | `/rack/supply-contracts` | Create a supply contract | ContractAdministrator |
| GET | `/rack/supply-contracts/{contractId}` | Fetch a supply contract | PlatformAdmin, ContractAdministrator, CreditAnalyst, BillingClerk |
| GET | `/rack/supply-contracts` | List supply contracts (filterable by customer or status) | PlatformAdmin, ContractAdministrator, CreditAnalyst, BillingClerk |
| POST | `/rack/supply-contracts/{contractId}/activate` | Activate a supply contract | ContractAdministrator |
| POST | `/rack/supply-contracts/{contractId}/close` | Close a supply contract; CLOSED if volume met, DEFAULTED otherwise | ContractAdministrator |
| POST | `/rack/lifting-rights` | Create a lifting right for a customer at a terminal for a product under a contract | AllocationManager |
| GET | `/rack/lifting-rights/{rightId}` | Fetch a lifting right | PlatformAdmin, AllocationManager, TerminalOperator, ContractAdministrator |
| GET | `/rack/lifting-rights` | List lifting rights | PlatformAdmin, AllocationManager, TerminalOperator, ContractAdministrator |
| POST | `/rack/lifting-rights/{rightId}/suspend` | Suspend a lifting right; cancels all RESERVED tickets | AllocationManager |
| POST | `/rack/lifting-rights/{rightId}/reinstate` | Reinstate a suspended lifting right | AllocationManager |
| POST | `/rack/price-schedules` | Create a draft price schedule | RackPriceAnalyst |
| GET | `/rack/price-schedules/{scheduleId}` | Fetch a price schedule | PlatformAdmin, RackPriceAnalyst, TerminalOperator |
| GET | `/rack/price-schedules` | List price schedules | PlatformAdmin, RackPriceAnalyst, TerminalOperator |
| POST | `/rack/price-schedules/{scheduleId}/publish` | Publish a price schedule (OCC-guarded on terminal version); supersedes prior PUBLISHED for same terminal, product, date | RackPriceAnalyst |
| POST | `/rack/price-schedules/{scheduleId}/void` | Void a draft price schedule | RackPriceAnalyst |
| POST | `/rack/allocation-notices` | Create a draft allocation notice | AllocationManager |
| GET | `/rack/allocation-notices/{noticeId}` | Fetch an allocation notice | PlatformAdmin, AllocationManager, TerminalOperator |
| GET | `/rack/allocation-notices` | List allocation notices | PlatformAdmin, AllocationManager, TerminalOperator |
| POST | `/rack/allocation-notices/{noticeId}/publish` | Publish an allocation notice (OCC-guarded on terminal version) | AllocationManager |
| POST | `/rack/exchange-agreements` | Create an exchange agreement | ExchangeCoordinator |
| GET | `/rack/exchange-agreements/{agreementId}` | Fetch an exchange agreement | PlatformAdmin, ExchangeCoordinator, TerminalOperator |
| GET | `/rack/exchange-agreements` | List exchange agreements | PlatformAdmin, ExchangeCoordinator, TerminalOperator |
| POST | `/rack/exchange-agreements/{agreementId}/activate` | Activate an exchange agreement | ExchangeCoordinator |
| POST | `/rack/exchange-agreements/{agreementId}/suspend` | Suspend an exchange agreement | ExchangeCoordinator |
| POST | `/rack/exchange-agreements/{agreementId}/reinstate` | Reinstate a suspended exchange agreement | ExchangeCoordinator |
| POST | `/rack/exchange-agreements/{agreementId}/terminate` | Terminate an exchange agreement | ExchangeCoordinator |
| POST | `/rack/lifting-tickets` | Reserve a lifting (creates ticket in RESERVED state, computes provisional gross) | TerminalOperator |
| GET | `/rack/lifting-tickets/{ticketId}` | Fetch a lifting ticket | PlatformAdmin, TerminalOperator, BillingClerk, AllocationManager, CreditAnalyst |
| GET | `/rack/lifting-tickets` | List lifting tickets | PlatformAdmin, TerminalOperator, BillingClerk, AllocationManager, CreditAnalyst |
| POST | `/rack/lifting-tickets/{ticketId}/post-bol` | Capture BOL and post the lifting (finalizes pricing and tax, debits inventory) | TerminalOperator |
| POST | `/rack/lifting-tickets/{ticketId}/reverse-bol` | Reverse a posted BOL within 24 logical hours (compensating action) | TerminalOperator |
| POST | `/rack/lifting-tickets/{ticketId}/cancel` | Cancel a RESERVED ticket | TerminalOperator |
| POST | `/rack/lifting-tickets/{ticketId}/invoice` | Invoice a BOL_ISSUED ticket (removes exposure, finalizes revenue) | BillingClerk |
| GET | `/rack/bol-events/{eventId}` | Fetch a single BOL event | PlatformAdmin, TerminalOperator, BillingClerk |
| GET | `/rack/bol-events` | List BOL events (filterable by ticket) | PlatformAdmin, TerminalOperator, BillingClerk |
| POST | `/rack/tax-rules` | Create a tax jurisdiction rule | PlatformAdmin |
| GET | `/rack/tax-rules/{ruleId}` | Fetch a tax rule | PlatformAdmin, RackPriceAnalyst, TerminalOperator |
| GET | `/rack/tax-rules` | List tax rules | PlatformAdmin, RackPriceAnalyst, TerminalOperator |
| GET | `/rack/credit-hold-logs/{logId}` | Fetch a single credit hold log event | PlatformAdmin, CreditAnalyst |
| GET | `/rack/credit-hold-logs` | List credit hold log events | PlatformAdmin, CreditAnalyst |
| POST | `/rack/_clock/set_current_utc` | Set the server's logical clock to a specific ISO 8601 UTC timestamp | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_SCHEDULE_NOT_DRAFT` | 409 |
| `ERR_NOTICE_NOT_DRAFT` | 409 |
| `ERR_SCHEDULE_DATE_IN_PAST` | 422 |
| `ERR_NOTICE_DATE_IN_PAST` | 422 |
| `ERR_INVALID_PRICE` | 422 |
| `ERR_INVALID_POOL` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_RIGHT_NOT_ACTIVE` | 409 |
| `ERR_RIGHT_NOT_SUSPENDED` | 409 |
| `ERR_CONTRACT_NOT_DRAFT` | 409 |
| `ERR_CONTRACT_NOT_ACTIVE` | 409 |
| `ERR_CONTRACT_NOT_IN_WINDOW` | 422 |
| `ERR_VOLUME_SHORTFALL` | 422 |
| `ERR_AGREEMENT_NOT_PROPOSED` | 409 |
| `ERR_AGREEMENT_NOT_ACTIVE` | 409 |
| `ERR_AGREEMENT_NOT_SUSPENDED` | 409 |
| `ERR_TICKET_NOT_RESERVED` | 409 |
| `ERR_TICKET_NOT_BOL_ISSUED` | 409 |
| `ERR_TERMINAL_FROZEN` | 409 |
| `ERR_TERMINAL_NOT_OPEN` | 409 |
| `ERR_TERMINAL_NOT_FROZEN` | 409 |
| `ERR_CUSTOMER_ON_CREDIT_HOLD` | 402 |
| `ERR_CUSTOMER_NOT_ON_HOLD` | 409 |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 |
| `ERR_ALLOCATION_EXCEEDED` | 422 |
| `ERR_INVALID_ADDITIVE_PACKAGE` | 422 |
| `ERR_INSUFFICIENT_INVENTORY` | 422 |
| `ERR_NO_PUBLISHED_PRICE` | 422 |
| `ERR_REVERSAL_WINDOW_EXPIRED` | 422 |
| `ERR_VALIDATION` | 400 or 422 (malformed input only; the clock-set endpoint uses 400, the contract window check on create uses 422) |
