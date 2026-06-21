# Pawn Shop Loan & Inventory API — Product Requirements Document

## 1. Introduction

A pawnbroker operates at the intersection of three pressures that rarely align: a customer who needs cash against a physical item today, a patchwork of state lending statutes that dictate how much may be lent and what may be charged, and a law-enforcement obligation to track potentially stolen goods. This API is the system of record for that business. It governs the full arc of a collateralized loan — taking in an item, valuing it, lending against it, servicing the debt through extensions and renewals, and resolving the loan either by redemption (the customer pays and reclaims the item) or by forfeiture (the item becomes shop inventory for resale).

The system is deliberately built around two anti-fraud and compliance disciplines. First, the person who appraises an item must never be the person who originates the loan against it — a four-eyes separation that prevents an employee from inflating a valuation to over-lend. Second, every loan and every forfeiture is potentially reportable to police, and an active law-enforcement hold must be able to freeze any item — in a borrower's collateral or already on the resale floor — independently of where that item sits in its normal lifecycle. Layered on top is a small pricing engine: interest and fees accrue per thirty-day period according to the governing state schedule, forfeited items are priced for optimistic resale while never being sold below the shop's unrecovered cost, and buyers may purchase resale goods outright or through a layaway installment plan.

Because loan math depends on the passage of time, the system runs against a test-controllable simulated clock rather than the host wall clock. All term, grace, and accrual computations read this clock, and loans transition lazily into their grace window when the clock is observed to have advanced — there is no background scheduler.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the operational capacity under which the request is made. A request missing either header, or presenting an `X-User-Role` that is not one of the recognized roles, is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes five roles, spelled exactly as follows: `Appraiser`, `LoanOfficer`, `ShopManager`, `Customer`, and `LawEnforcement`.

- An `Appraiser` values intake items and is the only role that may set an item's appraised value. An `Appraiser`'s `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it on the item it appraises (as `appraised_by_user_id`) but never compares it to any entity's `id`.
- A `LoanOfficer` originates, extends, renews, redeems, and voids loans, and may register customers and intake items. A `LoanOfficer`'s `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; it is the value compared against an item's `appraised_by_user_id` to enforce the separation-of-duties control, but it is not matched to any entity's `id`.
- A `ShopManager` is the operator/administrator: it configures shops and state schedules, forfeits grace-expired loans, runs resale and layaway, and drives the simulated clock. A `ShopManager`'s `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- A `LawEnforcement` user places, releases, and executes police holds and reads items and inventory for investigations. A `LawEnforcement` user's `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- A `Customer` is the borrower/buyer, persisted as an entity. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` compare the resource's customer foreign key to `X-User-ID`. A `Customer` may read its own customer record.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items are returned; it defaults to 10, may be no smaller than 1, and may be no larger than 100. The `offset` parameter sets how many leading items to skip and defaults to 0. A `limit` or `offset` outside its allowed range is rejected with `ERR_VALIDATION_PAGINATION`.

Unless an endpoint states otherwise, every list is returned sorted by the resource's creation timestamp in ascending order.

List responses surface the pagination state inside the `meta` object using the fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Resource Identity

Most resources carry a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, fixed at creation. The `updated_at` field is an ISO 8601 UTC timestamp refreshed on every mutation of the resource. The `version` field is an integer that starts at creation and increments by one on every mutation; it is the basis for optimistic concurrency control (see §2.7).

Two entity types are append-only event records and therefore carry **only** `id` and `created_at` — they have no `updated_at` and no `version`: the `FinanceTransaction` ledger entry and the `LayawayInstallment` schedule row. The simulated clock holder, `ClockState`, is likewise a system singleton that is not a versioned business resource. Every other resource type — `PawnShop`, `StorageBin`, `StateRateSchedule`, `Customer`, `PawnItem`, `Loan`, `InventoryItem`, `LayawayPlan`, `PoliceHold`, and `CashDrawer` — carries the full `id`, `created_at`, `updated_at`, and `version` set.

Each lifecycle-bearing resource — a pawn item, a loan, an inventory item, a layaway plan, a police hold — exposes its current lifecycle position in a `status` field whose permitted values are enumerated for that entity in §3.

When a derived field on a resource changes — for example a loan's `periods_charged` advancing, its `status` re-deriving from `ACTIVE` to `IN_GRACE`, or its `police_hold_flag` flipping — that counts as a mutation of the owning resource: it refreshes `updated_at` and increments `version` exactly as a direct field edit would.

### 2.5. Nested Resource Retrieval and Reverse Reachability

Several endpoints address a resource through a path that contains one or more identifiers, and several list endpoints reach a child or related collection from a parent — a shop's drawer, a shop's loans, a shop's inventory, a bin's loans, a loan's transactions, a plan's installments. For any such path, identifiers are validated strictly left to right: the request is rejected with `ERR_NOT_FOUND` against the **first** path identifier that does not resolve to an existing resource, before any deeper identifier or any body foreign key is examined. Body foreign keys are checked after all path identifiers resolve; a missing referenced resource named in a body also yields `ERR_NOT_FOUND`.

### 2.6. Monetary Precision and Rounding

All monetary quantities are stored and returned as integer cents. Where a calculation rounds, the system uses round-half-up unless a step explicitly specifies a different operation (such as flooring the loan-to-value multiply, or rounding a resale price to a whole dollar). Each calculation in §3 states its own rounding sequence precisely; the order in which rounding is applied is part of the contract and is not interchangeable with a mathematically "equivalent" reordering.

### 2.7. Optimistic Concurrency Control on Loan Servicing

Two loan-servicing operations are guarded by optimistic concurrency control: extending a loan and renewing a loan. Both require the caller to supply `expected_loan_version` in the request body, carrying the `version` of the target loan that the client last observed. Before the operation proceeds, the server compares `expected_loan_version` against the loan's current `version`. The `version` used for this comparison is the value as it stood at the start of the servicing request — captured before the request's own lazy `ACTIVE`-to-`IN_GRACE` re-derive (§2.9). Because that lazy re-derive is itself a mutation that bumps `version` (§2.4), the comparison deliberately excludes the request's own passive read-time grace recompute, which is not "another servicing write": a version advance produced solely by this request's grace transition does not trip the check. Any version advance committed by a prior, separate write (another extension, renewal, or any other mutation reflected in `version` by the time this request begins) is still caught. If another servicing write has advanced the loan's `version` since the client read it, the two values disagree and the request is rejected with `ERR_STALE_LOAN_VERSION` at HTTP status 412. This prevents a client from re-applying an extension or renewal against a loan whose accrual baseline and `periods_charged` have already moved — which would otherwise double-charge a finance period. The check is framed entirely in terms of the observed-versus-current `version`; it does not depend on requests overlapping in time. No endpoint other than extend and renew accepts or requires a version field.

### 2.8. The Cash Drawer Ledger and Conservation Invariants

Each `PawnShop` owns exactly one `CashDrawer`, minted at shop creation with `balance_cents` of 0 and linked back through the drawer's `shop_id`; the shop also keeps a denormalized `cash_drawer_id` pointer for convenience, while the canonical link lives on the drawer. The drawer's `balance_cents` is the shop's net cash position and is recomputed on every cash-moving event: it decreases when cash leaves the drawer (a loan disbursement, a layaway refund) and increases when cash enters (extension fees, renewal fees, redemption payoffs, layaway deposits and installments, and inventory sale proceeds, and a void's reversal of a disbursement).

Two invariants govern the ledger. **Disbursement/void conservation:** for any single loan, the sum of its `FinanceTransaction` amounts across the disbursement entry (recorded as a negative equal to the disbursed principal) and any void-reversal entry (recorded as a positive equal to that same principal) is exactly zero — voiding a loan must return the drawer to its pre-origination balance with respect to that loan. **Item conservation:** for any shop, the combined count of pawn items currently `PLEDGED` plus inventory items currently `AVAILABLE` or `ON_LAYAWAY` is preserved by a forfeit-then-recall pair, so reversing a forfeiture never creates or destroys an item.

### 2.9. The Simulated Clock and Lazy Grace Transition

All term, grace, and period arithmetic reads a single simulated clock, the `current_utc` field held by `ClockState`, rather than the host wall clock. It begins at a fixed epoch and is moved only by the test-driving clock-setting capability. Setting the clock does not itself transition any loan; instead, a loan's drift from `ACTIVE` into its grace window is applied lazily. Whenever a loan is read or any servicing action touches it, the server re-derives its status: if the loan is `ACTIVE` and the clock has reached or passed the loan's `term_end_at`, the loan is moved to `IN_GRACE` before the read or action is evaluated. This makes payoff and forfeiture eligibility observable without a background job.

### 2.10. Police Holds as a Cross-Cutting Freeze

A police hold is an association that can name either a pawn item still serving as collateral or an inventory item already on the resale floor; its `subject_kind` selects which. An `ACTIVE` hold acts as a freeze that overrides the normal lifecycle of whatever it names, and its effects are detailed in §3. The hold dimension on a loan is tracked independently of the loan's servicing status through the loan's `police_hold_flag`, so a hold can block a redemption or forfeiture regardless of where the loan otherwise sits.

### 2.11. Validation Ordering

When several checks could reject the same request, they are evaluated in a fixed priority order so that the returned error is deterministic. The global order is: (1) authentication of the headers (`ERR_UNAUTHENTICATED`); (2) role authorization for the operation (`ERR_FORBIDDEN_ROLE`); (3) existence of every referenced resource, path identifiers left to right then body foreign keys (`ERR_NOT_FOUND`); (4) well-formedness of the request body — required fields present, enum values in range, integers non-negative where required (`ERR_INVALID_REQUEST`); (5) that the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`); and then the operation-specific business rules, which are introduced alongside the workflows they guard in §3. Within a single operation, the business rules following step (5) are themselves ordered, and each workflow in §3 states the order that applies to it.

## 3. Business Logic & Workflows

### 3.1. Configuring the Shop, Its State Schedule, and Storage

Before any lending can happen, a `ShopManager` lays down the regulatory and physical scaffolding. Each US state the business operates in is governed by a state rate schedule, created by a `ShopManager` with a `state_code` (one of `FL`, `TX`, or `CA`) and the full set of statutory parameters: the `monthly_interest_bps` (monthly finance interest in basis points, applied to principal, where 1000 basis points means ten percent per month), the `monthly_storage_fee_cents` (a flat storage and handling charge added on top of interest for each thirty-day period), the `setup_fee_cents` (a one-time origination ticket fee added to the redemption payoff but not collected at disbursement), the `term_days` (length of the initial loan term before the grace window opens, which must be greater than zero), the `grace_days` (days after the term ends during which the loan stays redeemable before it may be forfeited, zero or more), the `max_principal_cents` (the statutory cap on loan principal in this state, greater than zero), the `max_periods_total` (the cap on how many thirty-day finance periods may ever be charged on a single loan across its whole life, at least one), the `loan_to_value_bps` (the loan-to-value ratio in basis points used to derive the offered amount from the appraised value, greater than zero and at most 10000, where 5000 means fifty percent), and the `layaway_buffer_days` (the mandatory restock cool-down gap, zero or more, enforced between one layaway plan's end on an item and the next plan's reservation start). The `state_code` is unique across schedules; attempting to create a second schedule for a state that already has one is rejected with `ERR_DUPLICATE_SCHEDULE`. All of the basis-point and cents quantities must be non-negative as noted, and interest and storage fees specifically are at least zero.

A `ShopManager` then creates one or more shop branches. A shop carries a `name`, the `state_code` it operates in (again one of `FL`, `TX`, or `CA`), and a `police_reporting_enabled` flag that defaults to true. The shop's `state_code` selects which state schedule governs loans originated there. Creating a shop also mints that shop's single cash drawer at a zero balance and records the convenience `cash_drawer_id` pointer; the drawer is reachable from the shop as an array of zero or one.

Physical collateral is held in storage bins. A `ShopManager` creates a `StorageBin` for a shop, providing the owning `shop_id`, a human `label` such as "A-12", and a `capacity` — the maximum number of pledged items the bin may hold concurrently at any instant, which must be at least 1. Bins are listable filtered by `shop_id`, and a bin's occupying loans are reachable directly.

### 3.2. Intake, Appraisal, and the Separation-of-Duties Control

When a borrower brings in an item, a `LoanOfficer` or `ShopManager` first registers the borrower as a `Customer`, recording the customer's `full_name` and the `gov_id_number` shown on a government ID. The `gov_id_number` is unique; re-registering an already-known government ID is rejected with `ERR_DUPLICATE_GOV_ID`. A customer also carries a system-managed `is_flagged` boolean, defaulting to false, which law enforcement can later set to block new lending.

The physical item is then taken in. Intaking a `PawnItem` records the owning `shop_id`, the `customer_id` of the owner, a free-text `description` (serial, make, model), and an optional `serial_number` used for police-database matching (defaulting to null when omitted). A fresh item begins in `INTAKE` status. Its `police_report_status` is seeded according to the shop: if the shop has `police_reporting_enabled`, the item starts at `PENDING_REPORT`; otherwise it is set to `NOT_REQUIRED`. The full set of reporting states is `NOT_REQUIRED`, `PENDING_REPORT`, and `REPORTED`. A `ShopManager` or `LoanOfficer` may later mark an item's reporting as complete, advancing `police_report_status` from `PENDING_REPORT` to `REPORTED` as a compliance step.

Valuation is the exclusive work of an `Appraiser`. Appraising an item drives it from `INTAKE` to `APPRAISED`: the appraiser supplies an `appraised_value_cents`, which must be greater than zero, and the system records that value plus the appraiser's identity in `appraised_by_user_id` (taken from `X-User-ID`). Appraising an item that is not in `INTAKE` is an invalid state transition. The recorded `appraised_by_user_id` exists for one reason: at loan origination the system enforces a four-eyes control. The originating `LoanOfficer`'s `X-User-ID` must not equal the `appraised_by_user_id` of the pledged item; if the same user attempts to both appraise and lend, origination is rejected with `ERR_SEGREGATION_OF_DUTIES`. The full lifecycle of a pawn item runs across `INTAKE`, `APPRAISED`, `PLEDGED`, `REDEEMED`, `FORFEITED`, and `RELEASED_TO_POLICE`, with the last three terminal.

### 3.3. Originating a Loan

Originating a loan is the exclusive work of a `LoanOfficer`, who supplies the `shop_id`, the `pawn_item_id` of the collateral, and the `storage_bin_id` of the bin chosen to hold it. Origination drives the pledged item from `APPRAISED` to `PLEDGED` and creates a `Loan` in `ACTIVE` status. The loan's full servicing lifecycle spans `ACTIVE`, `IN_GRACE`, `REDEEMED`, `FORFEITED`, `VOIDED`, and `POLICE_HELD`.

At origination several values are computed and snapshotted onto the loan so that later rate changes cannot disturb a loan in flight. The loan copies the `customer_id` from the pledged item and copies the shop's `state_code`, which pins the governing state schedule for the loan's whole life. It snapshots the schedule's `setup_fee_cents` into the loan's own `setup_fee_cents`. It records the origination instant from the simulated clock as `origination_at`, the accrual baseline. It sets `term_end_at` to the origination instant advanced by the schedule's `term_days`, and `grace_end_at` to `term_end_at` advanced by the schedule's `grace_days`. The loan's `periods_charged` begins at 0 (origination locks no finance period; the live period is computed on demand), its `renewal_count` begins at 0, and its `police_hold_flag` begins false.

The disbursed `principal_cents` is derived from the collateral's value and the governing schedule. First the loan-to-value figure is computed: multiply the item's `appraised_value_cents` by the schedule's `loan_to_value_bps`, divide by 10000, and take the floor of the result to whole cents. The principal is then the smaller of that loan-to-value figure and the schedule's `max_principal_cents`. If the resulting principal is not strictly positive, the collateral is too low to lend against and origination is rejected with `ERR_PRINCIPAL_NON_POSITIVE`.

Origination is only permitted when the item is in `APPRAISED` status; an attempt against an item that has not yet been appraised is rejected with `ERR_ITEM_NOT_APPRAISED`. Several further gates apply before the loan is created, evaluated in this order after existence, body well-formedness, and state are satisfied: the separation-of-duties check of §3.2 (`ERR_SEGREGATION_OF_DUTIES`); the police-hold check, where no `ACTIVE` police hold may name the collateral (`ERR_POLICE_HOLD_ACTIVE`); the customer-flag check, where the named customer must not be flagged by law enforcement (`ERR_CUSTOMER_FLAGGED`); the storage-bin capacity check described below (`ERR_BIN_CAPACITY_EXCEEDED`); and the positive-principal check (`ERR_PRINCIPAL_NON_POSITIVE`).

The chosen bin must have room for the new collateral across the loan's occupation interval, which runs from `origination_at` up to but not including `grace_end_at` — a half-open interval. The system considers every other loan assigned to the same bin that is not in a terminal state (those in `ACTIVE`, `IN_GRACE`, or `POLICE_HELD`) and counts how many of their half-open occupation intervals share any instant with the new loan's interval. Two intervals that merely touch at an endpoint — one loan's `grace_end_at` equal to the new loan's `origination_at` — do not overlap and are not a conflict. If that overlapping count plus the new loan would exceed the bin's `capacity`, origination is rejected with `ERR_BIN_CAPACITY_EXCEEDED`.

On success the loan is created in `ACTIVE`, the bin is occupied, the item moves to `PLEDGED`, the item's `police_report_status` stays `PENDING_REPORT` where the shop has reporting enabled (or `NOT_REQUIRED` otherwise), and the cash is disbursed: a `FinanceTransaction` of kind `DISBURSEMENT` is appended to the loan's ledger with an `amount_cents` equal to the negative of the principal and a `periods_in_charge` of 0, and the drawer's `balance_cents` is decreased by the principal. Each ledger entry records the owning `loan_id`, its `kind`, the signed `amount_cents`, and the `periods_in_charge` it settled. The recognized ledger kinds are `DISBURSEMENT`, `EXTENSION_FEE`, `RENEWAL_FEE`, `REDEMPTION_PAYOFF`, and `VOID_REVERSAL`; disbursement and void-reversal amounts are negative and positive cash movements respectively as described in §2.8.

### 3.4. The Payoff Quote and Per-Period Accrual

At any time a `LoanOfficer` or `ShopManager` may request the current redemption payoff for a loan as a computed read; the same figure is what a redemption collects. The read returns three quantities: the `payoff_cents`, the `total_periods` that figure covers, and the `per_period_charge_cents`.

The payoff is built from per-period accrual against the governing schedule. First the elapsed time is measured: take the difference between the current clock instant and the loan's `origination_at` and floor it to whole days to get the elapsed days. The number of currently-live periods is the elapsed days divided by thirty and rounded up to the next whole period, then clamped to lie between a minimum of one period and a maximum equal to the schedule's `max_periods_total` minus the periods already locked in by the loan's `periods_charged`. The total number of chargeable periods is the loan's `periods_charged` plus that live-period count. The charge for a single period is computed by taking the loan's `principal_cents`, multiplying by the schedule's `monthly_interest_bps`, dividing by 10000, rounding that interest portion half-up to whole cents, and then adding the flat `monthly_storage_fee_cents`. The payoff is then the loan's `principal_cents` plus the loan's snapshotted `setup_fee_cents` plus the total period count multiplied by that per-period charge.

The rounding sequence here is binding: the interest portion is rounded half-up **per period first**, the flat storage fee is then added to form the per-period charge, and only then is that charge multiplied by the period count and summed with principal and setup fee. This is deliberately not the same as multiplying principal, rate, and period count together and rounding once at the end.

### 3.5. Servicing a Loan: Extension, Renewal, and the Period Cap

A loan that is drifting toward its deadline can be kept alive in two distinct ways, both performed by a `LoanOfficer` and both guarded by the optimistic-concurrency check of §2.7 requiring `expected_loan_version` to match the loan's current `version` (else `ERR_STALE_LOAN_VERSION`, HTTP 412).

An **extension** keeps the loan `ACTIVE` by buying exactly one more finance period. It is permitted while the loan is `ACTIVE` or `IN_GRACE` and its `police_hold_flag` is false. The fee charged is exactly one per-period charge — computed as in §3.4 (the rounded interest portion plus the flat storage fee) — regardless of how many days have actually elapsed, and it does not include principal or setup fee. On success the system appends a `FinanceTransaction` of kind `EXTENSION_FEE` with a positive `amount_cents` equal to that one-period fee and `periods_in_charge` of 1, increases the drawer's `balance_cents` by the fee, increments the loan's `periods_charged` by one, advances `term_end_at` by another `term_days` and `grace_end_at` by the same `term_days`, shifts the accrual baseline so the live period restarts, returns the loan to `ACTIVE` if it had drifted to `IN_GRACE`, and increments the loan's `version` by one. Extensions may repeat across many rounds.

A **renewal** is a full re-term performed only while the loan is `IN_GRACE` with `police_hold_flag` false. Unlike an extension, a renewal collects **all** the finance charges accrued to date — the live-period count times the per-period charge, again excluding principal and setup fee — and resets the clock baseline to now. On success it appends a `FinanceTransaction` of kind `RENEWAL_FEE` with a positive `amount_cents` equal to that accrued total, increases the drawer's `balance_cents` by it, increments the loan's `renewal_count` by one, increases `periods_charged` by the number of periods due to date, resets `term_end_at` to the current clock instant advanced by `term_days` and `grace_end_at` to that new `term_end_at` advanced by `grace_days`, moves the loan to `ACTIVE`, and increments `version` by one.

Both operations honor the lifetime period cap. An extension is refused if charging one more period would push the loan's total finance periods past the schedule's `max_periods_total`; a renewal is refused if the periods due to date would push the total past the same cap. Either breach is rejected with `ERR_PERIOD_CAP_EXCEEDED`. While a loan is `POLICE_HELD`, extension and renewal are both blocked along with redemption and forfeiture (`ERR_POLICE_HOLD_ACTIVE`).

### 3.6. Redemption and the Void Compensation

Redemption is the happy ending: the borrower pays the full payoff and reclaims the item. A `LoanOfficer` may redeem a loan that is `ACTIVE` or `IN_GRACE` with `police_hold_flag` false, when the redemption payoff is paid in full. On redemption the system appends a `FinanceTransaction` of kind `REDEMPTION_PAYOFF` with a positive `amount_cents` equal to the payoff (computed as in §3.4), increases the drawer's `balance_cents` by the payoff, and moves both the loan and its pawn item to `REDEEMED`. Redemption against a loan whose `police_hold_flag` is true, or that is `POLICE_HELD`, is blocked with `ERR_POLICE_HOLD_ACTIVE`.

Voiding is the compensating action for a same-session origination mistake, performed by a `LoanOfficer`. A void is only permitted while the loan is still `ACTIVE` and no chargeable ledger entry — none of kind `EXTENSION_FEE`, `RENEWAL_FEE`, or `REDEMPTION_PAYOFF` — yet exists for the loan; a void attempted on a loan that has already been serviced is rejected with `ERR_LOAN_ALREADY_SERVICED`. A void appends a `FinanceTransaction` of kind `VOID_REVERSAL` with a positive `amount_cents` equal to the loan's `principal_cents` (cash returns to the drawer), increases the drawer's `balance_cents` by that principal, moves the loan to `VOIDED`, and reverts the pawn item to `APPRAISED` so it can be re-pledged. As stated in §2.8, the disbursement and its reversal sum to zero for that loan.

### 3.7. Forfeiture and the Two-Hop Resale Cascade

When the grace window has fully elapsed without redemption, a `ShopManager` may forfeit the loan, converting the collateral into shop inventory. Forfeiture is permitted only when the loan is `IN_GRACE`, the simulated clock has reached or passed the loan's `grace_end_at`, and the loan's `police_hold_flag` is false. A forfeiture attempted before the clock reaches `grace_end_at` is rejected with `ERR_GRACE_NOT_ELAPSED`; an `ACTIVE` police hold on the collateral or a `POLICE_HELD` loan blocks it with `ERR_POLICE_HOLD_ACTIVE`.

Forfeiture is a two-hop cascade. First, the loan moves to `FORFEITED` and its pawn item moves to `FORFEITED`, and the system computes the **cost basis** — the unrecovered debt the shop is owed at the forfeiture instant. This cost basis is exactly the redemption payoff of §3.4 evaluated at the forfeiture moment (the clock at or after `grace_end_at`), reusing the same round-per-period rule. No cash moves at forfeiture, so the drawer's `balance_cents` is unchanged.

Second, that cost basis drives the creation of a new `InventoryItem` in `AVAILABLE` status. The inventory item carries forward the `shop_id` from the forfeited loan's shop, records the `source_loan_id` of the loan whose forfeiture created it, carries the `pawn_item_id` of the now shop-owned physical item, and copies the pawn item's `appraised_value_cents` as the markup base. Its `cost_basis_cents` is set to the just-computed unrecovered debt. Its resale prices are then computed: the `floor_price_cents` is set equal to the `cost_basis_cents` — the pessimistic, cost-recovery minimum below which the item may never be sold. The `list_price_cents` is the forward-looking, optimistic target: take the `appraised_value_cents`, multiply by the quantity ten-thousand plus the resale markup of 3500 basis points (that is, a thirty-five-percent markup), divide by 10000, then round that raw figure half-up to the nearest whole dollar (a whole multiple of 100 cents), and finally clamp the result upward to be no less than the `cost_basis_cents` so the listing never sits below cost. The inventory item's `sold_price_cents` remains null until it sells, and its `last_layaway_end_at` remains null until a layaway plan on it ends. An inventory item's resale lifecycle runs across `AVAILABLE`, `ON_LAYAWAY`, `SOLD`, and `RECALLED`, the last two terminal.

### 3.8. Direct Resale and the Reverse-Forfeiture Recall

A `ShopManager` may sell an `AVAILABLE` inventory item outright by supplying the `sold_price_cents`. The sale is permitted only when the item is `AVAILABLE`, no `ACTIVE` police hold names it, and the offered `sold_price_cents` is at or above the item's `floor_price_cents`. A price below the floor is rejected with `ERR_PRICE_BELOW_FLOOR`; an active hold blocks the sale with `ERR_POLICE_HOLD_ACTIVE`. On success the item records its `sold_price_cents`, moves to `SOLD`, and the drawer's `balance_cents` increases by the sale price.

Recall is the compensating action for a forfeiture that should be undone — for instance when a customer arrives shortly after forfeiture wanting to settle. A `ShopManager` may recall an `AVAILABLE` inventory item back into its loan, but only when that item's `source_loan_id` loan is currently `FORFEITED` and no `ACTIVE` police hold names the inventory item (else `ERR_POLICE_HOLD_ACTIVE`). Recall moves the inventory item to `RECALLED`, returns the source loan to `IN_GRACE` so it is redeemable again, and returns the pawn item to `PLEDGED`. As stated in §2.8, a forfeit-then-recall pair conserves the shop's item count.

### 3.9. Layaway: Reservation, Schedule, Installments, and Default

Rather than buy outright, a buyer may put an `AVAILABLE` inventory item on layaway. A `ShopManager` creates a `LayawayPlan` by supplying the `inventory_item_id`, the buyer's `customer_id`, the `installment_count` (the number of equal installments scheduled after the deposit, at least 1 and at most 12), and a buyer-chosen `reserved_until_at` payment deadline. The plan's `reserved_from_at` is set to the current clock instant, and `reserved_until_at` must be later than `reserved_from_at`. The pair `[reserved_from_at, reserved_until_at]` is the item's closed exclusive reservation interval.

A restock cool-down protects against churning the same item between buyers. A new plan's `reserved_from_at` must be at or after the inventory item's `last_layaway_end_at` advanced by the schedule's `layaway_buffer_days`; the buffer endpoint itself is inclusive, so a `reserved_from_at` earlier than that buffered instant conflicts and the creation is rejected with `ERR_LAYAWAY_RESERVATION_CONFLICT`. (This single-occupant, closed-interval-with-additive-buffer rule is distinct from the bin's half-open aggregate-capacity geometry of §3.3.) A plan may not be opened on an item that is not `AVAILABLE`, and an `ACTIVE` police hold on the item blocks creation with `ERR_POLICE_HOLD_ACTIVE`.

On creation the plan snapshots its `total_price_cents` from the inventory item's `list_price_cents`, then builds its schedule. The required up-front `deposit_cents` is the total price multiplied by the deposit rate of 2000 basis points (twenty percent), divided by 10000, rounded half-up. The remainder after the deposit is split into `installment_count` equal scheduled installments: each non-final installment's `amount_cents` is the floor of the remainder divided by the installment count, and the final installment absorbs whatever is left so the deposit plus all installments sum exactly to the total price. Each scheduled `LayawayInstallment` records its parent `layaway_plan_id`, its 1-based `sequence` position, its scheduled `amount_cents`, and a `paid` flag (initially false). Creating the plan moves the inventory item to `ON_LAYAWAY`, sets the plan's `reserved_from_at` to the clock, collects the deposit (the plan's `paid_cents` starts at the deposit), and increases the drawer's `balance_cents` by the deposit. A layaway plan's lifecycle runs across `ACTIVE`, `DEFAULTED`, and `COMPLETED`.

Installments are posted one at a time by a `ShopManager`, each supplying the payment `amount_cents`. A posting is accepted only while the plan is `ACTIVE`, there is a next unpaid scheduled installment, and the supplied amount equals that installment's scheduled `amount_cents`; a mismatched amount or an exhausted schedule is rejected with `ERR_INSTALLMENT_MISMATCH`. Posting marks that installment `paid`, adds the amount to the plan's `paid_cents`, and increases the drawer's `balance_cents` by the amount. When the installment posted is the final one — that is, when the plan's `paid_cents` now equals its `total_price_cents` — the plan moves to `COMPLETED` and, bubbling up, the inventory item is auto-sold: it moves to `SOLD` with its `sold_price_cents` set to the plan's `total_price_cents`.

Cancellation always terminates the plan as `DEFAULTED`, regardless of how far the buyer paid, and the refund-minus-restocking path always applies. A `ShopManager` may cancel an `ACTIVE` plan. On cancellation the plan moves to `DEFAULTED`, the inventory item returns to `AVAILABLE`, and the item's `last_layaway_end_at` is set to the current clock instant (which is what the next plan's cool-down buffer measures from). The refund is computed as the plan's `paid_cents` minus a restocking fee, with the result floored at zero so the shop never pays out more than it collected. The restocking fee is the plan's `total_price_cents` multiplied by the restocking rate of 1000 basis points (ten percent), divided by 10000, rounded half-up. The drawer's `balance_cents` decreases by the refund actually paid.

### 3.10. Police Holds: Placement, Release, and Execution

A `LawEnforcement` user places a police hold by supplying the `subject_kind` (either `PAWN_ITEM` or `INVENTORY_ITEM`), a law-enforcement `case_number`, and the matching subject foreign key: `pawn_item_id` when the subject kind is `PAWN_ITEM`, or `inventory_item_id` when it is `INVENTORY_ITEM` (the other is left null). A hold begins `ACTIVE`; its lifecycle is `ACTIVE`, `RELEASED`, and `EXECUTED`.

Placing a hold on a pawn item that is currently collateral on a live loan sets that loan's `police_hold_flag` to true, moves the loan to `POLICE_HELD`, and flags the borrowing customer's `is_flagged` to true — which is what later blocks new originations naming that customer. A loan in `ACTIVE` or `IN_GRACE` thus moves to `POLICE_HELD`, and while `POLICE_HELD` all of redeem, extend, renew, and forfeit are frozen. Placing a hold whose subject is an inventory item instead blocks that item's sale, recall, and new-layaway operations while the hold is `ACTIVE`. Across the board, the operations that an `ACTIVE` hold (or the `POLICE_HELD`/flag state it induces) blocks — and that therefore surface `ERR_POLICE_HOLD_ACTIVE` — are: loan redemption, loan extension, loan renewal, loan forfeiture, inventory sale, inventory recall, and layaway creation.

Releasing a hold is a `LawEnforcement` action permitted while the hold is `ACTIVE`. It moves the hold to `RELEASED` and clears the `police_hold_flag` on the linked loan provided no other `ACTIVE` hold still names that collateral; when the flag clears, a loan that was `POLICE_HELD` returns to `ACTIVE` (and will be re-derived to `IN_GRACE` on its next read if the grace window has since opened).

Executing a hold is the surrender of the item to law enforcement, a `LawEnforcement` action permitted while the hold is `ACTIVE`. It moves the hold to `EXECUTED` and surrenders the named subject: a pawn-item subject moves to `RELEASED_TO_POLICE`. If that surrendered pawn item is collateral on a loan that is still live (`ACTIVE` or `POLICE_HELD`), the loan is voided — it moves to `VOIDED`, a `FinanceTransaction` of kind `VOID_REVERSAL` is appended with a positive `amount_cents` equal to the loan's `principal_cents`, and the drawer's `balance_cents` increases by that principal, returning the disbursed cash.

### 3.11. The Simulated Clock as a Test-Driving Capability

A `ShopManager` drives the system's logical time. An administrative clock-setting capability accepts a target instant as `to_iso8601` and sets `ClockState.current_utc` to it; this does not itself transition any loan, since grace drift is applied lazily on the next read or action as described in §2.9. The current clock value is itself readable. Loan and shop list reads re-derive each loan's lazy `ACTIVE`-to-`IN_GRACE` drift as they are returned, so the effect of advancing the clock becomes visible the moment the affected loans are next observed.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including state transitions and reads — return a `200 OK` status code. All list endpoints accept the pagination query parameters `limit` and `offset` from §2.3; collection-filtering query parameters are noted in the relevant §3 narrative.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/pawn/state-schedules` | Create a state rate/fee schedule | ShopManager |
| GET | `/pawn/state-schedules` | List state schedules (filterable by `state_code`) | ShopManager, LoanOfficer, Appraiser |
| POST | `/pawn/shops` | Create a shop branch; mints its 1:1 cash drawer at balance 0 | ShopManager |
| GET | `/pawn/shops/{id}` | Fetch a shop | ShopManager, LoanOfficer, Appraiser |
| GET | `/pawn/shops/{id}/drawer` | The shop's cash drawer (array of 0..1) | ShopManager, LoanOfficer |
| GET | `/pawn/shops/{id}/loans` | Loans of a shop (re-derives lazy grace on read) | ShopManager, LoanOfficer, Appraiser |
| GET | `/pawn/shops/{id}/inventory` | Inventory items of a shop | ShopManager, LoanOfficer |
| POST | `/pawn/storage-bins` | Create a physical storage bin for a shop | ShopManager |
| GET | `/pawn/storage-bins/{id}` | Fetch a storage bin | ShopManager, LoanOfficer |
| GET | `/pawn/storage-bins` | List storage bins (filterable by `shop_id`) | ShopManager, LoanOfficer |
| GET | `/pawn/storage-bins/{id}/loans` | Loans occupying this bin | ShopManager, LoanOfficer |
| POST | `/pawn/customers` | Register a customer | LoanOfficer, ShopManager |
| GET | `/pawn/customers/{id}` | Fetch a customer (shows `is_flagged`) | LoanOfficer, ShopManager, LawEnforcement |
| POST | `/pawn/items` | Take in a physical item (INTAKE) | LoanOfficer, ShopManager |
| GET | `/pawn/items/{id}` | Fetch a pawn item | LoanOfficer, ShopManager, Appraiser, LawEnforcement |
| GET | `/pawn/items` | List pawn items (filterable by `shop_id`, `customer_id`) | LoanOfficer, ShopManager, Appraiser, LawEnforcement |
| POST | `/pawn/items/{id}/appraise` | Set the appraised value (INTAKE → APPRAISED) | Appraiser |
| POST | `/pawn/items/{id}/report-police` | Mark the item REPORTED to police | ShopManager, LoanOfficer |
| POST | `/pawn/loans` | Originate a loan against an APPRAISED item | LoanOfficer |
| GET | `/pawn/loans` | List loans (filterable by `pawn_item_id`, `customer_id`, `storage_bin_id`, `shop_id`) | LoanOfficer, ShopManager, Appraiser |
| GET | `/pawn/loans/{id}` | Fetch a loan; re-derives lazy grace | LoanOfficer, ShopManager, Appraiser |
| GET | `/pawn/loans/{id}/payoff` | The current redemption payoff | LoanOfficer, ShopManager |
| GET | `/pawn/loans/{id}/transactions` | The loan's finance-transaction ledger | LoanOfficer, ShopManager |
| POST | `/pawn/loans/{id}/extend` | Extension: pay one live period, advance the term | LoanOfficer |
| POST | `/pawn/loans/{id}/renew` | Renewal: pay accrued charges, re-term to now | LoanOfficer |
| POST | `/pawn/loans/{id}/redeem` | Redeem: pay the full payoff; loan & item REDEEMED | LoanOfficer |
| POST | `/pawn/loans/{id}/forfeit` | Forfeit a grace-expired loan; spawns inventory | ShopManager |
| POST | `/pawn/loans/{id}/void` | Void an un-serviced loan; returns cash, reverts item | LoanOfficer |
| GET | `/pawn/inventory/{id}` | Fetch an inventory item | ShopManager, LoanOfficer |
| GET | `/pawn/inventory` | List inventory (filterable by `shop_id`, `source_loan_id`, `pawn_item_id`) | ShopManager, LoanOfficer, LawEnforcement |
| POST | `/pawn/inventory/{id}/sell` | Direct sale at or above floor price; item → SOLD | ShopManager |
| POST | `/pawn/inventory/{id}/recall` | Reverse-forfeiture: recall an item back to its loan | ShopManager |
| POST | `/pawn/layaway-plans` | Put an AVAILABLE item on layaway; collects deposit | ShopManager |
| GET | `/pawn/layaway-plans/{id}` | Fetch a layaway plan | ShopManager, LoanOfficer |
| GET | `/pawn/layaway-plans` | List layaway plans (filterable by `inventory_item_id`, `customer_id`) | ShopManager, LoanOfficer |
| GET | `/pawn/layaway-plans/{id}/installments` | Scheduled installments of a plan | ShopManager, LoanOfficer |
| POST | `/pawn/layaway-plans/{id}/installments` | Post the next scheduled installment | ShopManager |
| POST | `/pawn/layaway-plans/{id}/cancel` | Cancel/default a layaway; refund minus restocking | ShopManager |
| POST | `/pawn/police-holds` | Place a hold on a pawn item or inventory item | LawEnforcement |
| GET | `/pawn/police-holds/{id}` | Fetch a police hold | LawEnforcement, ShopManager |
| GET | `/pawn/police-holds` | List police holds (filterable by `pawn_item_id`, `inventory_item_id`) | LawEnforcement, ShopManager |
| POST | `/pawn/police-holds/{id}/release` | Release a hold; clear the loan flag if last | LawEnforcement |
| POST | `/pawn/police-holds/{id}/execute` | Execute a hold; surrender the item, void the loan | LawEnforcement |
| POST | `/pawn/_clock/set_current_utc` | Set the simulated clock | ShopManager |
| GET | `/pawn/_clock` | Read the simulated clock | ShopManager, LoanOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_POLICE_HOLD_ACTIVE` | 409 |
| `ERR_CUSTOMER_FLAGGED` | 409 |
| `ERR_GRACE_NOT_ELAPSED` | 409 |
| `ERR_BIN_CAPACITY_EXCEEDED` | 409 |
| `ERR_LAYAWAY_RESERVATION_CONFLICT` | 409 |
| `ERR_PERIOD_CAP_EXCEEDED` | 409 |
| `ERR_LOAN_ALREADY_SERVICED` | 409 |
| `ERR_PRICE_BELOW_FLOOR` | 422 |
| `ERR_INSTALLMENT_MISMATCH` | 422 |
| `ERR_PRINCIPAL_NON_POSITIVE` | 422 |
| `ERR_STALE_LOAN_VERSION` | 412 |
| `ERR_ITEM_NOT_APPRAISED` | 409 |
| `ERR_DUPLICATE_GOV_ID` | 409 |
| `ERR_DUPLICATE_SCHEDULE` | 409 |
| `ERR_VALIDATION_PAGINATION` | 422 |
