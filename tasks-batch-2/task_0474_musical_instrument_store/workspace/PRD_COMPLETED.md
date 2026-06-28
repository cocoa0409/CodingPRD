# Musical Instrument Store API — Product Requirements Document

## 1. Introduction

A full-service musical instrument retailer — the kind of store that sells new, used, and vintage guitars, band and orchestra horns, and keyboards — runs far more than a simple point of sale. The same physical instrument may be sold outright, rented to a beginning band student, placed on a rent-to-own track that slowly converts monthly payments into ownership, held on layaway, taken in trade, listed on consignment for a third party, special-ordered from a distributor, or sent to the bench for a luthier's setup. Every one of these dispositions competes for the same serial-numbered unit, and each carries its own money trail: store credit from trade-ins, commission splits on consignment, amortized financing, restock fees, late fees, and early-buyout payoffs.

This API is the system of record that keeps those competing claims honest. It treats each serial-tracked instrument as a finite resource that can be committed to exactly one disposition at a time, and it treats each rent-to-own agreement as a ledger whose payment stream must be reconciled two different ways — once to tell a customer how much equity they have earned, and once to tell them what it would cost to buy the instrument out today. The two figures are deliberately not the same number, and the system must keep them straight. The remainder of this document specifies the entities, their lifecycles, the financial calculations, and the validation and access-control rules that govern the store's operations.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contracts, and cross-cutting principles that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. The `X-User-ID` header identifies the acting user, and the `X-User-Role` header declares the capacity in which they act. The system recognizes exactly four roles: `SalesAssociate`, `Luthier`, `StoreManager`, and `Customer`. If the `X-User-Role` header is missing or does not name one of these four declared roles, the request is rejected with `ERR_UNAUTHENTICATED`. When the role is valid but is not permitted to perform the requested operation under the access-control matrix, the request is rejected with `ERR_FORBIDDEN`.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `SalesAssociate`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it against any record's `id`. The same is true when `X-User-Role` is `StoreManager` and when `X-User-Role` is `Luthier` — both are opaque operator identifiers. For the `Luthier` role, the server does record the identifier: when a luthier claims a repair ticket, the server writes that operator's `X-User-ID` into the ticket's `assigned_luthier_id` field and later compares subsequent bench actions against that stored value, but it never treats the identifier as a foreign key to any entity. By contrast, when `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` (for example, an agreement's `customer_id`, a layaway's `customer_id`, an enrollment's `student_id`, or a consignment's `consignor_id`) compare that foreign-key field to `X-User-ID`. A `Customer` may read and act only on their own resources.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and the accepted range is a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip from the start of the result set; when omitted it defaults to 0. A `limit` or `offset` outside its accepted range — or one that is not a parseable integer — is rejected with `ERR_VALIDATION`.

Unless otherwise specified, every list endpoint returns its resources sorted by their `created_at` timestamp in ascending order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Logical Clock

Most resources in this system share a common set of system-managed properties. Every resource carries an `id`, which is a server-minted UUID with no type prefix and serves only as identity. Every resource also carries a `created_at` timestamp, an ISO 8601 UTC value rendered with three fractional digits. Resources that may be modified after creation additionally carry an `updated_at` timestamp — refreshed on every mutation, including mutations that arrive as cascades from other resources — and a `version` integer that begins at 1 and increases by exactly 1 on every mutation.

Two entities are append-only ledger events and therefore do **not** carry `updated_at` or `version`: a `PaymentRecord` and a `LayawayPayment` each carry only an `id` and a `created_at`. They are never updated once written. All other entities — `Customer`, `InventoryUnit`, `RentalAgreement`, `LayawayPlan`, `RepairTicket`, `ConsignmentListing`, `TradeIn`, `FinancingApplication`, `SpecialOrder`, and `LessonEnrollment` — carry the full `id`, `created_at`, `updated_at`, and `version` set.

All timestamps are stamped from a server-controlled logical clock rather than wall-clock time. On startup the clock reads exactly `2026-01-01T00:00:00Z`, and until a manager explicitly sets it, every `created_at` and `updated_at` reads from this default — the server never falls back to wall-clock time. A `StoreManager` may advance or set the clock by supplying a `to_iso8601` instant; that instant governs all subsequent `created_at`/`updated_at` stamps and all chronological replay of ledger events.

### 2.5. Monetary Values, Precision, and Rounding

All monetary amounts are stored and returned as integer cents — never as fractional dollars or strings. Because every calculation in this system terminates in integer cents, each rule names its own rounding discipline, and the implementer must apply the named discipline exactly. Where a rule rounds, it uses **round half up** unless it explicitly names a floor (truncation toward zero for non-negative values) or a ceiling. Percentage and rate inputs such as `equity_rate_pct`, `equity_cap_pct`, `commission_pct`, `restock_fee_pct`, `deposit_pct`, and `apr_pct` are fractions (for example, `0.20` means twenty percent) and preserve their input precision; only the resulting cent amounts are rounded. Several rules pin the **order** in which rounding happens; those orderings are part of the contract and are spelled out in the relevant workflow narrative in §3. Computed balances that represent money owed or held — such as a layaway's `remaining_cents`, an agreement's `late_fee_balance_cents`, and a customer's `store_credit_cents` — are floored at zero and never go negative.

### 2.6. Inventory as a Finite Allocation Resource

Each `InventoryUnit` is serial-tracked and exists in quantity one; it can be committed to only one disposition at a time, and its `status` is the single source of truth for that commitment. A unit moves through the allocation states `AVAILABLE`, `RESERVED`, `ON_RENT`, `ON_LAYAWAY`, `SOLD`, `IN_REPAIR`, `CONSIGNED`, and `RETIRED`, starting life `AVAILABLE` (except for consigned and special-ordered units, described in §3). `RETIRED` is terminal. `RESERVED` is a soft hold: it records, in a transient marker the system keeps for the unit (`reserved_for_customer_id`), which customer the hold is for, and it is consumed by exactly one downstream agreement or layaway. Reserving a unit is the system's optimistic-concurrency guard point, described in §2.8.

Whenever a downstream workflow finalizes, the system propagates the result back to the underlying unit. These propagations are cascades: the unit's own `status` changes, its `version` increments by 1, and its `updated_at` refreshes — without the client issuing a separate request against the unit. The specific cascade for each workflow is described where that workflow lives in §3; the universal rule is that any cascade that touches a unit increments that unit's `version` and refreshes its `updated_at`, and the same holds for any `Customer` whose `store_credit_cents` is adjusted by a cascade.

### 2.7. Validation Order and the Layered Rejection Sequence

When a request could fail more than one check, the checks are evaluated in a fixed priority order so that the returned error is deterministic. Authentication comes first: a missing or unrecognized role yields `ERR_UNAUTHENTICATED`. Authorization comes second: a recognized role that is not permitted for the operation yields `ERR_FORBIDDEN`. Existence comes third: every resource referenced by the request — both path identifiers and body foreign keys — must exist, validated left-to-right in the order they appear, and the first missing reference yields `ERR_NOT_FOUND`. After existence, business-referential linkage is checked (for example, the reservation-mismatch rule on agreement and layaway creation, yielding `ERR_RESERVATION_MISMATCH`). Then state validity is checked: the target resource must be in a state from which the requested transition is legal, otherwise `ERR_INVALID_STATE`. Then optimistic-concurrency is checked, yielding `ERR_STALE_VERSION`. Only after all of those do the operation-specific business rules run (plan eligibility, payoff exactness, credit thresholds, deposit sufficiency, layaway-paid checks, and so on), each with its own error described alongside its workflow. Request well-formedness — required fields present, enum members valid, numeric ranges satisfied — is enforced as part of accepting any body and yields `ERR_INVALID_REQUEST`.

This ordering matters because a single request can plausibly trip several rules at once; evaluating them in this sequence guarantees that, for example, a stale-version conflict surfaces before a payoff-amount mismatch on the same buyout request, and that a forbidden role is reported before a not-found resource.

### 2.8. Optimistic Concurrency Control on Inventory and Agreements

Two write operations are guarded by optimistic concurrency control, and only these two. The first is reserving a unit. A reserve request must carry `expected_inventory_unit_version`, a non-optional field whose value is the `version` of the target `InventoryUnit` as the client last observed it. If another writer has advanced the unit's `version` since the client read it — most commonly because the unit was already reserved or otherwise mutated out from under this client — the supplied `expected_inventory_unit_version` no longer matches the unit's current `version`, the client's view of the unit is stale, and the reserve is rejected with `ERR_STALE_VERSION` (HTTP 412). This prevents two associates from each believing they have reserved the same serial-numbered instrument.

The second guarded operation is exercising an early buyout on a rent-to-own agreement. A buyout request must carry `expected_agreement_version`, a non-optional field whose value is the `version` of the target `RentalAgreement` as the client last observed it when it computed the payoff quote. If an intervening rent payment or late-fee accrual has advanced the agreement's `version` since that read, the accrued equity — and therefore the payoff figure — has changed, so the buyout is operating on a stale quote and is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint accepts or requires a version field; all other mutations proceed without an OCC check.

### 2.9. Nested Resource Retrieval and Left-to-Right Validation

Several endpoints address a sub-collection beneath a parent resource — for example, the payment records under an agreement or the installments under a layaway plan. For any such request, the system validates the path identifiers from left to right and rejects with `ERR_NOT_FOUND` at the first identifier in the path that does not name an existing resource, before attempting to resolve anything further to its right. Body foreign keys are validated in the same left-to-right spirit after path identifiers, so a request naming a non-existent agreement is rejected before the system inspects any other reference in the body.

## 3. Business Logic & Workflows

### 3.1. Customers, Store Credit, and Stocking Inventory

A customer record is the anchor for every downstream relationship. A `SalesAssociate` or `StoreManager` creates a customer by supplying a `full_name`, an `email`, and a `credit_score`. The email must be unique among customers. The credit score is a FICO-style integer that must fall at or above 300 and at or below 850; it later drives financing eligibility and pricing. A new customer begins with a `store_credit_cents` balance of 0 — this is a running balance, never negative, fed by trade-in acceptances, consignment payouts, and various refunds described throughout this section, and it is always system-computed rather than client-set.

Stocking an instrument creates an `InventoryUnit`. The associate or manager supplies a `model_name`, a `category` that is one of `BAND`, `ORCHESTRA`, `GUITAR`, `KEYBOARD`, or `OTHER`, a `condition` that is one of `NEW`, `USED`, or `VINTAGE`, a `serial_number`, an `acquisition_cost_cents` (what the store paid, at least 0), a `list_price_cents` (the outright sticker price, at least 0), and a `monthly_rent_cents` (the rent-to-own or rental monthly rate, at least 0). An optional `source_kind` records how the unit entered stock and is one of `STORE_PURCHASE`, `TRADE_IN`, or `CONSIGNMENT`, defaulting to `STORE_PURCHASE` when omitted. The serial number need only be unique among units that share the same `model_name`; two different models may carry the same manufacturer serial, but stocking a second unit of the same model with an already-used serial is rejected with `ERR_DUPLICATE_SERIAL`. A unit created through the ordinary stocking path begins `AVAILABLE` at `version` 1. A unit's `consignment_listing_id` foreign key is populated by the system only when the unit was minted to back a consignment listing, and is otherwise null.

Reserving an `AVAILABLE` unit is how the store places a soft hold before any rental, rent-to-own, or layaway can begin. A `SalesAssociate` reserves a unit by supplying the `customer_id` the hold is for together with `expected_inventory_unit_version`. The unit must currently be `AVAILABLE`, and the supplied version must match per §2.8; on success the unit moves `AVAILABLE → RESERVED`, the transient `reserved_for_customer_id` marker is set to that customer, and the unit's `version` increments by 1. Releasing a reservation returns a `RESERVED` unit to `AVAILABLE`, clears `reserved_for_customer_id`, and increments the unit's `version` by 1. A unit not in the required state for either action is rejected with `ERR_INVALID_STATE`.

### 3.2. Rental and Rent-to-Own Agreements: Opening and Paying

Opening an agreement consumes a reservation. A `SalesAssociate` opens a `RentalAgreement` by supplying the `customer_id`, the `inventory_unit_id` of the reserved unit, and a `plan` that is one of `RENTAL` or `RENT_TO_OWN`. Two optional fractions may accompany a rent-to-own agreement: `equity_rate_pct`, the fraction of each paid month credited toward purchase, defaulting to 0.50 and constrained to the closed range from 0 to 1; and `equity_cap_pct`, the maximum fraction of the purchase price that accrued equity may reach, defaulting to 1.0 and constrained to be greater than 0 and at most 1. For a `RENTAL` plan the equity rate is treated as zero regardless of any supplied value. The reserved unit must be held for this same customer — the unit's `reserved_for_customer_id` must equal the payload `customer_id` — otherwise the create is rejected with `ERR_RESERVATION_MISMATCH`. On success the system snapshots the unit's current `monthly_rent_cents` into the agreement's immutable `monthly_rate_cents` and the unit's `list_price_cents` into the agreement's immutable `purchase_price_cents`; these snapshots are the rent-to-own target price and never change for the life of the agreement. The unit moves `RESERVED → ON_RENT`, its `version` increments by 1, and the agreement begins `ACTIVE` at `version` 1.

Reading an agreement is more than a lookup: it recomputes and surfaces the agreement's live derived figures — `months_paid`, `accrued_equity_cents`, `payoff_quote_cents`, `late_fee_balance_cents`, and `missed_streak`. The `months_paid` figure is the count of this agreement's payment records whose `kind` is `RENT` and whose `status` is `POSTED`. Agreements can be listed and filtered by `customer_id` or `inventory_unit_id`.

A rent payment is posted against an agreement by a `Customer` or `SalesAssociate`, who supplies the `billing_cycle_index` the payment covers. The agreement must be in a payable state — either `ACTIVE` or `DEFAULTED` — and a payment attempted against any other (terminal) agreement state is rejected with `ERR_INVALID_STATE`. Posting appends a `PaymentRecord` whose `kind` is `RENT`, whose `status` is `POSTED`, whose `amount_cents` the system sets to the agreement's snapshotted `monthly_rate_cents`, and whose `billing_cycle_index` records the covered cycle (the index is null for any non-rent payment). The append recomputes `months_paid`, `accrued_equity_cents`, and `missed_streak`, and increments the agreement's `version` by 1. A payment record is an append-only event: it carries only `id`, `agreement_id`, `kind`, `amount_cents`, `billing_cycle_index`, `status`, and `created_at`, and its `created_at` is the chronological replay key. The `kind` of a record is one of `RENT`, `LATE_FEE`, `BUYOUT`, or `REFUND`, where a `REFUND` record represents money the store returns to the customer; its `status` is either `POSTED` or `WAIVED`. The `amount_cents` on a record is signed — positive when the customer pays the store, negative when the store refunds the customer. If a rent payment is posted on an agreement that had fallen into default and the payment brings the consecutive-missed count back below the default threshold, the agreement recovers from `DEFAULTED → ACTIVE` and the missed streak resets to 0, as described in §3.3. The chronological payment log on an agreement can be listed.

**Equity accrual.** An agreement's `accrued_equity_cents` is a capped running credit recomputed on every posted rent payment, on every buyout-quote read, and at agreement creation. The system first forms the raw equity as the number of posted rent months multiplied by the agreement's monthly rate multiplied by the equity rate — that is, `months_paid` times `monthly_rate_cents` times `equity_rate_pct` — and rounds that product half up to whole cents. It then forms the cap as the purchase price multiplied by the equity-cap fraction — `purchase_price_cents` times `equity_cap_pct` — taking the floor of that product to whole cents. The accrued equity is the smaller of the rounded raw equity and the floored cap. For a `RENTAL` plan the equity rate is zero, so accrued equity is always 0. Only this agreement's own posted rent records feed the months-paid count.

### 3.3. Billing Cycles, Late Fees, and Default

Advancing a billing cycle is how time moves forward on an agreement. A `StoreManager` or `SalesAssociate` advances an agreement by supplying the `billing_cycle_index` being closed; the agreement must be `ACTIVE` or `DEFAULTED` to advance, and advancing from any other (terminal) state is rejected with `ERR_INVALID_STATE`. The system processes cycles strictly by `billing_cycle_index` ascending, breaking ties by the payment record's `created_at` ascending (never by `id`). If a posted rent record already exists for that cycle index, the consecutive-missed count resets to 0. If no posted rent record exists for that cycle, the consecutive-missed count increases by 1 and the system appends a late-fee payment record — a `PaymentRecord` with `kind` `LATE_FEE`, `status` `POSTED`, and an `amount_cents` of 1,500 cents (fifteen dollars) for the missed cycle. After each advance the agreement's `late_fee_balance_cents` is recomputed as the sum of posted late-fee amounts minus the sum of waived late-fee amounts, floored at 0. The advance increments the agreement's `version` by 1.

A rent-to-own or rental agreement begins to **default** when the consecutive-missed count reaches the default threshold. The threshold is three consecutive missed cycles: if an advance pushes the consecutive-missed count to three or more while the agreement is `ACTIVE`, the agreement transitions `ACTIVE → DEFAULTED`, and the late fee for that missed cycle is posted as part of the same advance. `DEFAULTED` is not the end of the road — it is an intermediate state. A subsequent rent payment that brings the consecutive-missed count back below three recovers the agreement `DEFAULTED → ACTIVE`, appending the posted rent record and resetting the missed streak to 0. Alternatively, a `StoreManager` may repossess a defaulted unit: repossession moves the agreement `DEFAULTED → REPOSSESSED`, cascades the underlying unit `ON_RENT → IN_REPAIR` (a repossessed instrument is routed to the bench for refurbishment before resale), forfeits any accrued equity, writes off the outstanding late-fee balance by moving those late-fee records to `WAIVED` status, and increments the agreement's `version` by 1. Repossession is permitted only from `DEFAULTED`; attempting it from any other state is rejected with `ERR_INVALID_STATE`. `BOUGHT_OUT`, `RETURNED`, and `REPOSSESSED` are the three terminal outcomes of an agreement.

### 3.4. Closing an Agreement: Buyout and Return

A rent-to-own customer may convert their agreement into ownership through an early buyout. Buyout is restricted to agreements whose `plan` is `RENT_TO_OWN`; attempting it on a plain `RENTAL` agreement is rejected with `ERR_PLAN_NOT_RENT_TO_OWN`. The customer or associate submits the buyout with `amount_cents`, the exact payment they intend to make, and `expected_agreement_version` for the concurrency check described in §2.8. The agreement must be `ACTIVE`, and the submitted `amount_cents` must equal the agreement's current `payoff_quote_cents` to the cent; any other amount is rejected with `ERR_PAYOFF_MISMATCH`. On success the system appends a `PaymentRecord` with `kind` `BUYOUT`, `status` `POSTED`, and `amount_cents` equal to the payoff quote; transitions the agreement `ACTIVE → BOUGHT_OUT`; cascades the underlying unit `ON_RENT → SOLD` (the unit's `list_price_cents` is left unchanged and its `version` increments by 1); and increments the agreement's `version` by 1.

**Buyout payoff.** The payoff quote is a deliberately different computation over the same payment stream than equity accrual, and the two will not generally agree for the same number of months paid. Where equity accrual counts **up** from zero toward the cap and excludes any fees, the payoff counts **down** from the purchase price and **adds** fees. Concretely, the system first forms the remaining balance as the purchase price minus the accrued equity — `purchase_price_cents` minus `accrued_equity_cents`. It then adds a flat early-buyout fee of 5,000 cents (fifty dollars) and adds the current outstanding late-fee balance. The payoff quote is the greater of zero and that sum, so it can never be negative. The equity figure that a customer reads off the agreement (`accrued_equity_cents`) reflects equity earned so far and never includes the buyout fee or late fees; the payoff figure (`payoff_quote_cents`) is the buy-it-out-today number and does include them. For a plain `RENTAL` agreement the payoff is undefined and buyout is barred by the plan precondition above.

Returning the instrument is the other voluntary close. A `Customer` or `SalesAssociate` returns the unit on an `ACTIVE` agreement, but only if there is no outstanding late-fee balance — if `late_fee_balance_cents` is greater than 0 the return is blocked with `ERR_OUTSTANDING_LATE_FEES`. On success the agreement transitions `ACTIVE → RETURNED`, the underlying unit cascades `ON_RENT → AVAILABLE` with its `reserved_for_customer_id` cleared, any accrued rent-to-own equity is forfeited rather than refunded, and the agreement's `version` increments by 1.

### 3.5. Layaway Plans

Layaway lets a customer hold an instrument while paying it off in installments, without the equity mechanics of rent-to-own. A `SalesAssociate` opens a `LayawayPlan` against a reserved unit by supplying the `customer_id`, the `inventory_unit_id`, an initial `deposit_cents` (at least 0), and an optional `restock_fee_pct` defaulting to 0.10 and constrained to the closed range from 0 to 1. As with agreements, the unit's `reserved_for_customer_id` must match the payload `customer_id`, or the create is rejected with `ERR_RESERVATION_MISMATCH`. On success the system snapshots the unit's `list_price_cents` into the plan's immutable `total_price_cents`, cascades the unit `RESERVED → ON_LAYAWAY`, and starts the plan `OPEN` at `version` 1.

Reading a layaway plan recomputes and surfaces `paid_cents` and `remaining_cents`. The paid figure is the initial deposit plus the sum of all installment amounts recorded against the plan — `deposit_cents` plus the total of every `LayawayPayment.amount_cents` on the plan. The remaining figure is the total price minus the paid figure, floored at 0 so it never goes negative. Plans can be listed and filtered by `customer_id` or `inventory_unit_id`.

A layaway installment is recorded by a `Customer` or `SalesAssociate`, who supplies a positive `amount_cents`. Recording appends a `LayawayPayment` — an append-only event carrying only `id`, `layaway_plan_id`, `amount_cents`, and `created_at`, whose `created_at` is its chronological key — recomputes `paid_cents` and `remaining_cents`, and increments the plan's `version` by 1. The installment log can be listed.

Completing a layaway is permitted only when the plan is fully paid — `remaining_cents` must equal 0 — otherwise the completion is rejected with `ERR_LAYAWAY_NOT_PAID`. Completing an `OPEN` plan transitions it `OPEN → COMPLETED`, cascades the unit `ON_LAYAWAY → SOLD`, and increments the plan's `version` by 1. Cancelling an `OPEN` plan instead transitions it `OPEN → CANCELLED`, cascades the unit `ON_LAYAWAY → AVAILABLE` (also clearing the unit's `reserved_for_customer_id`), and refunds the customer as store credit. The refund is computed by first forming the restock fee as the total price multiplied by the restock-fee fraction — `total_price_cents` times `restock_fee_pct` — rounded half up to whole cents, then taking the refund as the greater of zero and the paid amount minus that restock fee. When that refund amount is greater than 0 it is added to the customer's `store_credit_cents` (a cascade that bumps the customer's `version` and `updated_at`); a refund of 0 adds nothing and triggers no customer cascade. The plan's `version` increments by 1. `COMPLETED` and `CANCELLED` are terminal.

### 3.6. The Luthier's Bench: Repair Tickets

The repair workflow serves both store-owned instruments and customers' own outside instruments. A `SalesAssociate` opens a `RepairTicket` by supplying the `customer_id`, an estimate of `labor_hours` (at least 0), a `labor_rate_cents` per-hour rate (at least 0), and optionally an `inventory_unit_id` (null for a customer's own outside instrument), a `parts_cost_cents` defaulting to 0 (at least 0), and a `rush` flag defaulting to false. When the ticket names a store-owned unit that is currently `AVAILABLE`, opening the ticket cascades that unit `AVAILABLE → IN_REPAIR` and bumps the unit's `version`; if the named unit is in any other state the ticket still opens but no unit cascade occurs. The ticket starts `INTAKE` at `version` 1, and its `quoted_total_cents` is computed at creation and recomputed on any field edit. The ticket's `assigned_luthier_id` is null until a luthier claims it. Tickets can be listed and filtered by `customer_id`, `inventory_unit_id`, or `status`.

**Repair invoice.** The quoted total is built from at least three inputs with a non-linear rush branch and a minimum bench floor. The system first forms labor as the estimated hours multiplied by the hourly rate — `labor_hours` times `labor_rate_cents` — rounded half up to whole cents. It then floors that labor at a minimum bench charge of 4,000 cents (forty dollars): the labor used in the rest of the computation is the greater of the rounded labor and 4,000 cents, regardless of how few hours were entered. The subtotal is that floored labor plus the parts cost. If `rush` is true, a rush surcharge equal to twenty-five percent of the **subtotal** (not of labor alone) is added; if `rush` is false the surcharge is zero. The quoted total is the subtotal plus the surcharge, rounded half up to whole cents.

The bench workflow is a `Luthier`'s responsibility and is gated by assignment. A luthier claims an `INTAKE` ticket, which moves it `INTAKE → IN_PROGRESS`, writes that luthier's `X-User-ID` into `assigned_luthier_id`, and increments the ticket's `version`. From there, only the luthier whose identifier matches the ticket's `assigned_luthier_id` may act on it; a different luthier attempting to work the ticket is rejected with `ERR_TICKET_NOT_ASSIGNED`. The assignment gate is checked after the state precondition, so a bench action attempted from a state that does not permit it surfaces `ERR_INVALID_STATE` even when the acting luthier is not the assigned one. The assigned luthier may move an in-progress ticket `IN_PROGRESS → AWAITING_PARTS` while waiting on a part, and later resume it `AWAITING_PARTS → IN_PROGRESS`. When the work is done the assigned luthier marks the ticket ready, moving it `IN_PROGRESS → READY` and freezing `quoted_total_cents` as the final invoice (no further edits change it). Each of these bench transitions increments the ticket's `version`.

Closing and cancelling return to sales staff. A `SalesAssociate` closes a `READY` ticket when the customer picks up, moving it `READY → CLOSED`; if the ticket is linked to a store-owned unit, that unit cascades `IN_REPAIR → AVAILABLE`. A `SalesAssociate` may cancel a ticket that is in `INTAKE`, `IN_PROGRESS`, or `AWAITING_PARTS`, moving it to `CANCELLED`; here too, a linked store-owned unit cascades `IN_REPAIR → AVAILABLE`. Both close and cancel increment the ticket's `version`. `CLOSED` and `CANCELLED` are terminal, and any transition attempted from a state that does not permit it is rejected with `ERR_INVALID_STATE`.

### 3.7. Consignment and Trade-In: Two Paths to Store Credit

Consignment lets the store sell an instrument on a third party's behalf for a commission. A `SalesAssociate` or `StoreManager` creates a `ConsignmentListing` by supplying the `consignor_id` (the consigning customer), the `model_name`, a positive `ask_price_cents`, and an optional `commission_pct` defaulting to 0.20 and constrained to the closed range from 0 to 1. Creating the listing mints a backing `InventoryUnit` in the `CONSIGNED` state, linked one-to-one through the unit's `consignment_listing_id`, and the listing begins `LISTED` at `version` 1. That backing unit carries the listing's `model_name`, a `source_kind` of `CONSIGNMENT`, a `list_price_cents` equal to the `ask_price_cents`, a `category` of `OTHER`, a `condition` of `USED`, a system-generated `serial_number`, and `acquisition_cost_cents` and `monthly_rent_cents` of 0. The listing's `consignor_payout_cents` is 0 until the instrument sells. Listings can be listed and filtered by `consignor_id` or `status`.

Selling a listed consignment is performed by a `SalesAssociate`. The listing must be `LISTED` and its linked unit must be `CONSIGNED`. On sale the system computes the consignor payout, transitions the listing `LISTED → SOLD`, cascades the linked unit `CONSIGNED → SOLD`, credits the consignor, and increments the listing's `version`. **Consignment settlement** is a conserved-quantity split of the realized sale price: the system forms the commission as the ask price multiplied by the commission fraction — `ask_price_cents` times `commission_pct` — rounded half up to whole cents, and the consignor payout is the ask price minus that commission. The payout is written to `consignor_payout_cents` and added to the consignor's `store_credit_cents` (a cascade bumping that customer's `version` and `updated_at`). Withdrawing a listed consignment instead transitions it `LISTED → WITHDRAWN` and cascades the linked unit `CONSIGNED → RETIRED`, since the instrument is handed back to the consignor and leaves saleable stock; the listing's `version` increments. Withdrawal may be performed by a `SalesAssociate` or `StoreManager`. `SOLD` and `WITHDRAWN` are terminal.

Trade-in is the other route to store credit, and it credits the customer through a different formula than consignment even though both land on the same `store_credit_cents` field. A `StoreManager` creates a `TradeIn` by supplying the `customer_id`, the `model_name`, a `condition` that is one of `NEW`, `USED`, or `VINTAGE`, and an `appraised_value_cents` (at least 0, the manager's assessed market value). On creation the system computes the **trade-in offer** as a condition-tiered fraction of the appraised value, taking the floor to whole cents: the fraction is 0.60 for `NEW`, 0.50 for `USED`, and 0.70 for `VINTAGE`, so the offer is the appraised value multiplied by the condition's fraction, floored. The trade-in begins `OFFERED` at `version` 1 with the computed `offer_cents`, and trade-ins can be listed and filtered by `customer_id`, `resulting_unit_id`, or `status`.

Accepting a trade-in is a manager action. Acceptance transitions the trade-in `OFFERED → ACCEPTED`, mints a new `InventoryUnit` in the `AVAILABLE` state whose `source_kind` is `TRADE_IN` and whose `acquisition_cost_cents` equals the offer, records that unit's id in the trade-in's `resulting_unit_id`, and adds the offer to the customer's `store_credit_cents` (a cascade). The minted unit reflects the traded instrument's condition (a `USED` or `VINTAGE` unit), takes the trade-in's `model_name`, a `category` of `OTHER`, a system-generated `serial_number`, and a `list_price_cents` and `monthly_rent_cents` of 0. Declining a trade-in instead transitions it `OFFERED → DECLINED`; a `Customer` or `StoreManager` may decline. Both acceptance and decline increment the trade-in's `version`. `ACCEPTED` and `DECLINED` are terminal. Note the contrast that the system must keep straight: a trade-in counts **up** a generous fraction of an appraised value and floors it, while a consignment counts **down** from a realized ask price by a commission and rounds half up — two different conserved-quantity formulas writing to the same customer balance.

### 3.8. Financing and Special Orders

A special order brings in an instrument the store does not stock. A `SalesAssociate` or `Customer` creates a `SpecialOrder` by supplying the `customer_id`, the `model_name`, a positive `quoted_price_cents`, and an optional `deposit_pct` defaulting to 0.25 and constrained to the closed range from 0 to 1. On creation the system computes `required_deposit_cents` as the quoted price multiplied by the deposit fraction, rounded **up** to the next whole cent (a ceiling). The order starts `QUOTED` at `version` 1 with `deposit_paid_cents` of 0 and a null `fulfilled_unit_id`. Orders can be listed and filtered by `customer_id`, `fulfilled_unit_id`, or `status`.

Paying the deposit moves the order forward. A `Customer` or `SalesAssociate` pays a deposit by supplying `amount_cents`, which must be at least the required deposit — a smaller amount is rejected with `ERR_DEPOSIT_INSUFFICIENT`. A sufficient deposit transitions the order `QUOTED → DEPOSITED`, sets `deposit_paid_cents` to the supplied amount, and increments the order's `version`. A `SalesAssociate` then places the deposited order with the manufacturer, moving it `DEPOSITED → ORDERED`; this same transition also occurs as a cascade when financing for the order is approved (described below). When the unit arrives, a `SalesAssociate` receives it by supplying the `serial_number` and the `category` of the arrived instrument: the order moves `ORDERED → ARRIVED`, the system mints a new `InventoryUnit` in the `RESERVED` state held for the ordering customer (its `reserved_for_customer_id` set to the order's customer), and records that unit's id in `fulfilled_unit_id`. The minted unit takes the supplied `serial_number` and `category`, its `condition` is `NEW`, its `source_kind` is `STORE_PURCHASE`, its `list_price_cents` is the order's `quoted_price_cents`, and its `acquisition_cost_cents` and `monthly_rent_cents` are both 0. Fulfilling the arrived order hands the unit to the customer: the order moves `ARRIVED → FULFILLED` and the unit cascades `RESERVED → SOLD`. Cancelling a special order is permitted while it is `QUOTED`, `DEPOSITED`, or `ORDERED`, moving it to `CANCELLED`; if any deposit had been paid (`deposit_paid_cents` greater than 0), that deposit is refunded to the customer's `store_credit_cents` as a cascade. Every special-order transition increments the order's `version`. `FULFILLED` and `CANCELLED` are terminal.

Financing amortizes a purchase over time, optionally tied to a special order. A `SalesAssociate` or `Customer` submits a `FinancingApplication` by supplying the `customer_id`, a positive `principal_cents`, a `term_months` that is one of 6, 12, 24, or 36, and optionally a `special_order_id` naming the order being financed. The application starts `SUBMITTED` at `version` 1, with `apr_pct` and `monthly_payment_cents` unset until approval. Applications can be listed and filtered by `customer_id`, `special_order_id`, or `status`. A `StoreManager` approves, denies, or the customer cancels a submitted application. Approval is guarded by the applicant's credit: the applicant `Customer`'s `credit_score` must be at least the minimum financing score of 660; if it is below 660 the approval is blocked with `ERR_CREDIT_TOO_LOW` and the application is left unchanged in `SUBMITTED` (the credit floor is a guard that rejects the approval, not an automatic denial). On approval the application transitions `SUBMITTED → APPROVED`, the system computes `apr_pct` and `monthly_payment_cents`, and if the application names a special order, that order cascades from `QUOTED` or `DEPOSITED` to `ORDERED`. Denial transitions the application `SUBMITTED → DENIED`; a manager may deny directly. A `Customer` may cancel a submitted application, moving it `SUBMITTED → CANCELLED`. Each financing transition increments the application's `version`. `APPROVED`, `DENIED`, and `CANCELLED` are terminal.

**Financing terms.** The APR is tiered on the applicant's credit score: a score of at least 720 earns the prime rate of 0.0599, a score from 660 through 719 earns the near-prime rate of 0.1299, and a score below 660 would earn the subprime rate of 0.2299 (though such an applicant is blocked by the credit floor above). The monthly payment is a standard amortization, and the order of rounding is pinned: the system computes the exact monthly rate as the APR divided by 12 without rounding it, computes the exact amortized payment from that unrounded rate, and then rounds the **final** payment once to whole cents using round half up. If the monthly rate is zero, the exact payment is simply the principal divided by the number of term months; otherwise the exact payment is the principal multiplied by the monthly rate multiplied by one-plus-the-rate raised to the number of months, divided by the quantity one-plus-the-rate raised to the number of months minus one. No intermediate value is rounded — rounding the monthly rate or any intermediate factor first would yield a different cent figure, so rounding happens once, at the very end.

### 3.9. Lesson Enrollments and Bundle Pricing

The store's teaching studio links to its rental business through a bundle discount. A `SalesAssociate` or `Customer` creates a `LessonEnrollment` by supplying the `student_id`, an `instrument_family` that is one of `BAND`, `ORCHESTRA`, `GUITAR`, `KEYBOARD`, or `OTHER`, a positive `sessions_per_month`, a `base_rate_cents` per-session rate (at least 0), and optionally a `rental_agreement_id` linking the lessons to an agreement that grants the bundle discount (null for standalone lessons). The enrollment starts `ACTIVE` at `version` 1 with `monthly_tuition_cents` computed at creation. Enrollments can be listed and filtered by `student_id`, `rental_agreement_id`, or `status`.

**Lesson tuition.** Monthly tuition stacks two discounts in a pinned order — volume first, then bundle — and reversing the order would change the result. The system begins with the base monthly figure as the per-session rate multiplied by the sessions per month — `base_rate_cents` times `sessions_per_month`. Step one applies the volume discount: if `sessions_per_month` is at least 8, a volume discount of fifteen percent applies, otherwise no volume discount applies; the after-volume figure is the base monthly multiplied by one minus the volume fraction, rounded half up to whole cents. Step two applies the bundle discount to that already-volume-discounted figure: a bundle discount of twenty percent applies only when a `rental_agreement_id` is set **and** the linked `RentalAgreement` is currently `ACTIVE`, otherwise no bundle discount applies; the monthly tuition is the after-volume figure multiplied by one minus the bundle fraction, rounded half up to whole cents. The volume discount is applied before the bundle discount, and each step rounds in turn.

A `Customer` may pause an active enrollment (`ACTIVE → PAUSED`) and later resume it (`PAUSED → ACTIVE`). Resuming recomputes `monthly_tuition_cents`, because the bundle discount may have lapsed in the meantime — if the linked agreement is no longer `ACTIVE`, the resumed tuition loses the bundle portion. Ending an enrollment moves it from either `ACTIVE` or `PAUSED` to `ENDED`. Each enrollment transition increments the enrollment's `version`. `ENDED` is terminal.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including state transitions, payments posted against an existing parent, and the logical-clock setter — return a `200 OK` status code. All list and retrieval reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | StoreManager |
| POST | `/customers` | Create a customer | SalesAssociate, StoreManager |
| GET | `/customers/{customer_id}` | Get a customer | SalesAssociate, StoreManager, Customer |
| GET | `/customers` | List customers (paginated) | SalesAssociate, StoreManager |
| POST | `/units` | Add an inventory unit to stock | SalesAssociate, StoreManager |
| GET | `/units/{unit_id}` | Get an inventory unit | SalesAssociate, StoreManager, Customer |
| GET | `/units` | List inventory units (filter by status/category/consignment_listing_id) | SalesAssociate, StoreManager, Customer |
| POST | `/units/{unit_id}/reserve` | Reserve an AVAILABLE unit for a customer (OCC guard) | SalesAssociate |
| POST | `/units/{unit_id}/release` | Release a RESERVED unit back to AVAILABLE | SalesAssociate |
| POST | `/rental-agreements` | Open a rental or rent-to-own agreement on a reserved unit | SalesAssociate |
| GET | `/rental-agreements/{id}` | Get an agreement (surfaces equity and payoff) | SalesAssociate, StoreManager, Customer |
| GET | `/rental-agreements` | List agreements (filter by customer_id or inventory_unit_id) | SalesAssociate, StoreManager, Customer |
| POST | `/rental-agreements/{id}/payments` | Post a rent payment against an agreement | Customer, SalesAssociate |
| GET | `/rental-agreements/{id}/payments` | List payment records on an agreement | SalesAssociate, StoreManager, Customer |
| POST | `/rental-agreements/{id}/advance-cycle` | Advance to the next billing cycle | StoreManager, SalesAssociate |
| POST | `/rental-agreements/{id}/buyout` | Exercise rent-to-own early buyout (OCC + exact-payoff guarded) | Customer, SalesAssociate |
| POST | `/rental-agreements/{id}/return` | Return the rented unit and close the agreement | Customer, SalesAssociate |
| POST | `/rental-agreements/{id}/repossess` | Repossess a defaulted unit | StoreManager |
| POST | `/layaway-plans` | Open a layaway plan on a reserved unit | SalesAssociate |
| GET | `/layaway-plans/{id}` | Get a layaway plan (surfaces paid/remaining) | SalesAssociate, StoreManager, Customer |
| GET | `/layaway-plans` | List layaway plans (filter by customer_id or inventory_unit_id) | SalesAssociate, StoreManager, Customer |
| POST | `/layaway-plans/{id}/payments` | Record a layaway installment | Customer, SalesAssociate |
| GET | `/layaway-plans/{id}/payments` | List installments on a layaway plan | SalesAssociate, StoreManager, Customer |
| POST | `/layaway-plans/{id}/complete` | Complete a fully-paid layaway plan | SalesAssociate |
| POST | `/layaway-plans/{id}/cancel` | Cancel a layaway plan; refunds paid minus restock fee | SalesAssociate |
| POST | `/repair-tickets` | Open a luthier repair/setup ticket | SalesAssociate |
| GET | `/repair-tickets/{ticket_id}` | Get a repair ticket | SalesAssociate, StoreManager, Luthier, Customer |
| GET | `/repair-tickets` | List repair tickets (filter by customer_id/inventory_unit_id/status) | SalesAssociate, StoreManager, Luthier, Customer |
| POST | `/repair-tickets/{ticket_id}/claim` | Luthier claims an INTAKE ticket | Luthier |
| POST | `/repair-tickets/{ticket_id}/await-parts` | Move ticket to AWAITING_PARTS | Luthier |
| POST | `/repair-tickets/{ticket_id}/resume` | Resume work from AWAITING_PARTS | Luthier |
| POST | `/repair-tickets/{ticket_id}/ready` | Mark repair complete and freeze the invoice | Luthier |
| POST | `/repair-tickets/{ticket_id}/close` | Close a READY ticket (customer pickup) | SalesAssociate |
| POST | `/repair-tickets/{ticket_id}/cancel` | Cancel a ticket before completion | SalesAssociate |
| POST | `/consignment-listings` | Create a consignment listing; mints a CONSIGNED unit | SalesAssociate, StoreManager |
| GET | `/consignment-listings/{listing_id}` | Get a consignment listing | SalesAssociate, StoreManager, Customer |
| GET | `/consignment-listings` | List consignment listings (filter by consignor_id/status) | SalesAssociate, StoreManager, Customer |
| POST | `/consignment-listings/{listing_id}/sell` | Mark a listing sold; pays the consignor | SalesAssociate |
| POST | `/consignment-listings/{listing_id}/withdraw` | Withdraw a listing; returns instrument to consignor | SalesAssociate, StoreManager |
| POST | `/trade-ins` | Create a trade-in offer (computes store-credit offer) | StoreManager |
| GET | `/trade-ins/{trade_in_id}` | Get a trade-in | SalesAssociate, StoreManager, Customer |
| GET | `/trade-ins` | List trade-ins (filter by customer_id/resulting_unit_id/status) | SalesAssociate, StoreManager, Customer |
| POST | `/trade-ins/{trade_in_id}/accept` | Accept a trade-in; mints inventory and credits the customer | StoreManager |
| POST | `/trade-ins/{trade_in_id}/decline` | Decline a trade-in offer | Customer, StoreManager |
| POST | `/financing-applications` | Submit a financing application | SalesAssociate, Customer |
| GET | `/financing-applications/{application_id}` | Get a financing application | SalesAssociate, StoreManager, Customer |
| GET | `/financing-applications` | List financing applications (filter by customer_id/special_order_id/status) | SalesAssociate, StoreManager, Customer |
| POST | `/financing-applications/{application_id}/approve` | Approve financing (credit-score guarded; computes terms) | StoreManager |
| POST | `/financing-applications/{application_id}/deny` | Deny financing | StoreManager |
| POST | `/financing-applications/{application_id}/cancel` | Cancel a financing application | Customer |
| POST | `/special-orders` | Create a special order (computes required deposit) | SalesAssociate, Customer |
| GET | `/special-orders/{order_id}` | Get a special order | SalesAssociate, StoreManager, Customer |
| GET | `/special-orders` | List special orders (filter by customer_id/fulfilled_unit_id/status) | SalesAssociate, StoreManager, Customer |
| POST | `/special-orders/{order_id}/pay-deposit` | Pay the required deposit on a special order | Customer, SalesAssociate |
| POST | `/special-orders/{order_id}/place` | Place the order with the manufacturer | SalesAssociate |
| POST | `/special-orders/{order_id}/receive` | Receive the ordered unit into stock (reserved for customer) | SalesAssociate |
| POST | `/special-orders/{order_id}/fulfill` | Hand the arrived unit to the customer (sale) | SalesAssociate |
| POST | `/special-orders/{order_id}/cancel` | Cancel a special order (refunds deposit as store credit) | SalesAssociate, Customer |
| POST | `/lesson-enrollments` | Enroll a student in lessons (bundle discount if linked to ACTIVE agreement) | SalesAssociate, Customer |
| GET | `/lesson-enrollments/{enrollment_id}` | Get a lesson enrollment | SalesAssociate, StoreManager, Customer |
| GET | `/lesson-enrollments` | List lesson enrollments (filter by student_id/rental_agreement_id/status) | SalesAssociate, StoreManager, Customer |
| POST | `/lesson-enrollments/{enrollment_id}/pause` | Pause a lesson enrollment | Customer, SalesAssociate |
| POST | `/lesson-enrollments/{enrollment_id}/resume` | Resume a paused enrollment (recomputes tuition) | Customer, SalesAssociate |
| POST | `/lesson-enrollments/{enrollment_id}/end` | End a lesson enrollment | Customer, SalesAssociate |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_DUPLICATE_SERIAL` | 409 Conflict |
| `ERR_RESERVATION_MISMATCH` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_PLAN_NOT_RENT_TO_OWN` | 409 Conflict |
| `ERR_PAYOFF_MISMATCH` | 422 Unprocessable Entity |
| `ERR_OUTSTANDING_LATE_FEES` | 409 Conflict |
| `ERR_CREDIT_TOO_LOW` | 422 Unprocessable Entity |
| `ERR_DEPOSIT_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_LAYAWAY_NOT_PAID` | 422 Unprocessable Entity |
| `ERR_TICKET_NOT_ASSIGNED` | 403 Forbidden |
| `ERR_VALIDATION` | 400 Bad Request |
