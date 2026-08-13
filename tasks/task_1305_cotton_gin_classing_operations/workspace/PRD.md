# Cotton Gin Classing API — Product Requirements Document

## 1. Introduction

A Delta cotton gin co-operative processes seed cotton from its member growers through a tightly sequenced physical and financial pipeline: modules arrive at the yard on grower tickets, are conditioned for moisture, queued into gin shifts, ginned into bales, classed by USDA offices, receipted into warehouses, pledged against CCC marketing assistance loans, sold or shipped, and finally settled back to the grower with charges, credits, and patronage allocated. Every pound of lint and seed is accounted for, every cent traces to a ledger posting, and every custody change is recorded against an auditable receipt. This document specifies the API that backs that pipeline.

The co-op's business rests on three invariants that the API must hold at all times. First, **mass is conserved**: the sum of lint, seed, and waste leaving a gin shift must equal the seed cotton that entered it, and pooled seed proceeds must allocate back to growers without a cent of drift. Second, **money is ledgered**: every charge, credit, advance, repayment, and payout is an append-only posting against a grower account, and the grower's running balance is always the plain sum of those postings. Third, **duties are segregated**: the operator who ginned a module may not issue the warehouse receipt that moves its bales into storage, because that receipt is the collateral anchor for downstream lending.

Two calculation regimes run in parallel over the same deliveries. Before a gin shift's seed is sold, a grower's settlement carries a *provisional* seed credit built from estimated turnout; once the shift is reconciled and its seed pool sold, the *final* settlement replaces estimates with actual posted credits. The two variants legitimately disagree, and the API exposes both so growers can watch a season take shape before it closes. Similarly, classing results pin a quality snapshot at the moment the USDA office issues a grade; a later reclass supersedes the earlier snapshot and quietly recomputes every draft settlement that depended on it.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` identifying the acting principal, and `X-User-Role` naming the role that principal acts in. A request missing either header, or carrying an empty value for either, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 401). A request whose role is not permitted on the endpoint, or whose `Grower`-role caller touches a resource outside their own grower chain, is rejected with `ERR_FORBIDDEN` (HTTP 403).

Six roles are recognized, spelled exactly as follows:

- **`CoopAdmin`** — the co-op platform administrator. Owns configuration: registering growers, publishing grade schedules, commissioning warehouses, and driving the test-only logical clock. When `X-User-Role` is `CoopAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- **`GinOperator`** — the gin floor operator. Receives modules, runs conditioning and shifts, records produced bales. When `X-User-Role` is `GinOperator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it as `ginned_by_user_id` on the `ModuleReceipt` when complete-ginning runs, and later compares that stored value against the receipt issuer's `X-User-ID` for the segregation-of-duties check, but does not otherwise resolve it to an entity.
- **`ClassingClerk`** — records USDA classing results against bales. When `X-User-Role` is `ClassingClerk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- **`WarehouseManager`** — the warehouse superintendent. Issues and cancels warehouse receipts, ships confirmed orders, and shares shipping-order creation and confirmation duties with growers. When `X-User-Role` is `WarehouseManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- **`CoopAccountant`** — the co-op accountant. Runs seed sales, loan pledges, redemptions, forfeits, settlements, and manual ledger adjustments. When `X-User-Role` is `CoopAccountant`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- **`Grower`** — a co-op member. Reads their own resources and requests shipping of their own bales. When `X-User-Role` is `Grower`, `X-User-ID` is the `id` of the acting `Grower`; ownership checks on any resource that references a `Grower` compare the resource's grower-chain foreign key to `X-User-ID`, and a mismatch yields `ERR_FORBIDDEN`.

All roles share read access to every GET endpoint, subject to the `Grower` scoping rule above.

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

List endpoints accept two query parameters: `limit` (default 10, minimum 1, maximum 100) and `offset` (default 0). Results are returned sorted by `created_at` ascending. The `meta` block of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Append-Only Ledger

Every persisted resource carries an `id` that is a server-minted UUID with no type prefix, a `created_at` timestamp in ISO 8601 UTC with three fractional digits, an `updated_at` timestamp in the same format refreshed on every mutation, and a `version` integer that increments by exactly 1 on every mutation of that resource. One entity deviates: `LedgerEntry` is an append-only event log carrying only `id` and `created_at`. It has no `updated_at` and no `version`; entries are never modified after posting.

A `Grower`'s `credit_balance_cents` is a read-only running balance that starts at 0 at registration and equals the sum of `amount_cents` across every `LedgerEntry` posted for that grower. Every ledger posting recomputes the balance immediately, inside the same request, so the response of any mutating call reflects the new balance. Each `LedgerEntry` carries an `entry_type` drawn from `GINNING_CHARGE`, `SEED_CREDIT`, `STORAGE_CHARGE`, `LOAN_ADVANCE`, `LOAN_REPAYMENT`, `ADJUSTMENT`, `PATRONAGE`, or `SETTLEMENT_PAYMENT`, where charges and repayments post negative and credits post positive. A `Warehouse`'s `stored_bale_count` is likewise read-only: it counts that warehouse's receipts whose `status` is `ACTIVE`, `PLEDGED`, or `RELEASED`, starting at 0 when the warehouse is commissioned. The `status` field name recurs across most entities — gin shifts, modules, classing results, receipts, pledges, orders, and settlements each carry their own `status` state machine — while a `Bale` instead carries the two parallel dimensions `classing_status` and `custody_status`.

### 2.5. The Logical Clock

All date-stamping in the system — `storage_start_date`, `pledged_date`, `redeemed_date`, `ginned_at`, and every day count behind storage and interest accrual — reads a logical clock, never wall-clock time. Before any clock call is made, the logical clock reads exactly `2026-08-01T00:00:00Z`. An admin-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant; it mutates no entity. Dates captured from the clock are stored as a date at `00:00:00Z`.

### 2.6. Optimistic Concurrency Control

Two write operations carry an optimistic-concurrency guard because each legitimately supersedes a prior record, and a writer holding a stale view must be refused rather than overwrite a change it never saw.

Recording a classing result against a bale requires the request to carry `expected_bale_version` equal to the bale's current `version`. If the bale's version has advanced since the client last read it, the write is rejected with `ERR_STALE_VERSION` (HTTP 412).

Creating a settlement for a grower requires the request to carry `expected_grower_version` equal to the grower's current `version`. If the grower's version has advanced since the client last read it, the create is rejected with `ERR_STALE_VERSION` (HTTP 412).

Endpoints not named above do not take a version field.

### 2.7. Precision, Rounding, and Money Representation

All money is integer cents. Pounds are integer lbs except where a reading is explicitly fractional. Wherever a calculation yields a fraction of a cent or a fraction of a pound, the result is rounded half-up to the nearest whole unit; rounding is always applied at the granularity each rule names (per bale, per module, or per settlement line), never at a coarser aggregate. Points used by grade schedules are signed integers where 1 point equals 1/100 of a cent per pound. Percentages are carried as numbers (`moisture_pct`, `foreign_matter_pct`), and the patronage rate is a fraction such as 0.20.

### 2.8. Grade Schedule Windows

Pricing and loan rates come from `GradeSchedule` rows, each covering a half-open window: the window starts at `effective_from` (inclusive, stored as a date at `00:00:00Z`) and ends at `effective_to` (exclusive), and `effective_to` must be strictly later than `effective_from` or the create is rejected with `ERR_INVALID_WINDOW` (HTTP 400). For the same `grade_code`, two windows must never overlap; adjacency — one window ending exactly when the next begins — is allowed. An overlapping create is rejected with `ERR_GRADE_WINDOW_OVERLAP` (HTTP 409). Because windows do not overlap, at most one schedule covers any given date for a grade; when classing or pledging finds no covering row, the write fails with `ERR_NO_ACTIVE_GRADE_SCHEDULE` (HTTP 422).

### 2.9. Validation Priority Order

When several checks could reject the same request, they are evaluated in a fixed priority so the surfaced error is deterministic. Authentication comes first — missing or empty `X-User-ID` / `X-User-Role` yields `ERR_MISSING_OR_INVALID_USER_CONTEXT` before anything else is examined. Role authorization follows, yielding `ERR_FORBIDDEN`. Existence of every path resource id (validated left-to-right along the URL) and every body foreign-key reference is checked next, yielding the resource-specific not-found error — `ERR_GROWER_NOT_FOUND`, `ERR_MODULE_NOT_FOUND`, `ERR_BALE_NOT_FOUND`, `ERR_GIN_SHIFT_NOT_FOUND`, `ERR_WAREHOUSE_NOT_FOUND`, `ERR_WAREHOUSE_RECEIPT_NOT_FOUND`, `ERR_LOAN_PLEDGE_NOT_FOUND`, `ERR_SETTLEMENT_NOT_FOUND`, `ERR_SHIPPING_ORDER_NOT_FOUND`, `ERR_GRADE_SCHEDULE_NOT_FOUND`, or `ERR_LEDGER_ENTRY_NOT_FOUND`, each at HTTP 404. Request body shape — required fields present, enum members valid, window ordering, non-empty bale lists, numeric ranges — is checked next with `ERR_INVALID_REQUEST`, `ERR_INVALID_WINDOW`, or `ERR_EMPTY_SHIPMENT`. Only then do state-gate checks run (the transition gates and the OCC version match), then contamination and moisture safety plus segregation of duties, then uniqueness and quota rules, then temporal window rules, then cross-entity coherence, and finally money caps and exact-amount rules. A request failing an earlier tier never surfaces a later tier's error.

## 3. Business Logic & Workflows

### 3.1. Season Setup: Growers, Grade Schedules, Warehouses, and Shifts

Before the first module rolls onto the yard, a `CoopAdmin` registers each member grower with a `membership_number` unique across all growers and a `legal_name`. Registration accepts an optional `patronage_rate`; when omitted it defaults to 0.20, the fraction of season ginning charges returned to the grower as patronage at settlement. The new grower's `credit_balance_cents` starts at 0.

The administrator also publishes grade schedules. Each row prices one USDA `grade_code` such as "41-4" with a signed `premium_discount_points` quality adjustment and a `loan_rate_points` CCC loan rate, both expressed in points of 1/100 cent per pound, effective over the half-open window described in §2.8.

Warehouses are commissioned with a `name`, a `capacity_bales` ceiling on physically stored bales, and a `dock_count` that bounds loading-dock numbering. A fresh warehouse reports `stored_bale_count` of 0.

Meanwhile a `GinOperator` opens gin shifts. A shift carries a `season` label such as "2026" and a `stand_label` identifying the gin stand, and begins life `OPEN`. Modules may only ever queue into a shift of the same season, so the season label on a shift is not decorative — it gates which modules may join it.

### 3.2. Module Intake: Tickets, Weights, and the Moisture Gate

Harvest arrives as modules. A `GinOperator` receives each module by cutting a grower ticket: the payload names the delivering grower via `grower_id`, the `season`, a `ticket_number` unique per grower per season, and a `module_tag` unique per season across all growers. A duplicate ticket surfaces `ERR_DUPLICATE_TICKET_NUMBER` (HTTP 409); a duplicate tag within the season surfaces `ERR_DUPLICATE_MODULE_TAG` (HTTP 409). The scale house records `gross_weight_lbs` and `tare_weight_lbs`; the system derives `net_weight_lbs` as gross minus tare, ignoring any input value for it, and requires the result to be at least 1 or the create fails with `ERR_INVALID_REQUEST` (HTTP 400). Intake also captures the initial `moisture_pct` and `foreign_matter_pct`; a module arriving with foreign matter above 10.0 percent is rejected outright with `ERR_FOREIGN_MATTER_LIMIT_EXCEEDED` (HTTP 422) as a contamination safety measure. A successfully received module enters status `RECEIVED`.

From the same weights the system computes two estimates that follow the module through its life. Estimated lint starts from a base turnout of 38 percent of net weight, then discounts for moisture and trash: moisture above 8.0 percent subtracts 0.4 percentage points per point of excess, capped at a 2.0-point total discount; foreign matter above 4.0 percent subtracts 0.5 points per point of excess, capped at 2.5 points; and the resulting lint percentage is floored at 30 percent no matter how wet or trashy the module. `est_lint_lbs` is the module's net weight multiplied by that final percentage, rounded half-up to whole pounds. `est_seed_lbs` is simpler: net weight multiplied by 55 percent, rounded half-up to whole pounds. Both estimates are computed at receipt and recomputed on every subsequent moisture re-reading.

A module that tests too wet to gin goes to the dryer. Conditioning replaces the module's `moisture_pct` with the new reading from the payload, recomputes both estimates, and cycles the module's status: from `RECEIVED` a conditioning pass moves it to `CONDITIONING`; while in `CONDITIONING`, a reading still above 12.0 percent keeps it in `CONDITIONING` (a self-loop — the module stays in the dryer), and a reading at or below 12.0 returns it to `RECEIVED`. Conditioning is only meaningful from `RECEIVED` or `CONDITIONING`; attempting it from any later state fails with `ERR_MODULE_NOT_CONDITIONABLE` (HTTP 409). Each conditioning pass increments the module's `version`. A module that cannot be salvaged may instead be rejected: rejection moves a `RECEIVED` or `CONDITIONING` module to terminal `REJECTED`, records the operator's `reason`, and is refused from any other state with `ERR_MODULE_NOT_REJECTABLE` (HTTP 409).

### 3.3. Ginning: Queuing, the Mass Balance, and the Tiered Ginning Charge

Queuing assigns a `RECEIVED` module to a shift. The request names the target shift by `gin_shift_id`. Four checks guard the transition, in the order given by §2.9: the module must currently be `RECEIVED` (else `ERR_MODULE_NOT_QUEUABLE`, HTTP 409); its latest `moisture_pct` must be at most 12.0 percent — a reading of exactly 12.0 passes — or the queue fails with `ERR_MOISTURE_LIMIT_EXCEEDED` (HTTP 422); the target shift must be `OPEN` (else `ERR_SHIFT_NOT_OPEN`, HTTP 409); and the module's `season` must equal the shift's `season` (else `ERR_SEASON_MISMATCH`, HTTP 422). Queuing stamps `gin_shift_id` on the module, moves it to `QUEUED`, and increments its `version`.

Starting ginning moves a `QUEUED` module to `GINNING` and requires the module's shift to still be `OPEN`; a module not in `QUEUED` yields `ERR_MODULE_NOT_GINNABLE` (HTTP 409), and a closed shift yields `ERR_SHIFT_NOT_OPEN`.

Completing ginning is the pivot of the whole pipeline. The operator submits a `bales` list, one entry per produced bale, each carrying a globally unique `bale_tag` and an actual lint scale weight `net_weight_lbs` of at least 1. The module must be in `GINNING` (else `ERR_MODULE_NOT_COMPLETABLE`, HTTP 409); an empty list or a non-positive bale weight fails with `ERR_INVALID_REQUEST`; a tag already seen anywhere — including twice inside the same payload — fails with `ERR_DUPLICATE_BALE_TAG` (HTTP 409). On success the module transitions `GINNING → GINNED`, records `ginned_at` from the logical clock, and captures `ginned_by_user_id` as the acting `X-User-ID` — the value the segregation-of-duties rule will later compare against. One `Bale` is created per payload entry, each carrying a `module_id` back-reference to the module that produced it and starting with `classing_status` of `UNCLASSED` and `custody_status` of `ON_GIN_FLOOR`, and the module's `actual_lint_lbs` becomes the sum of its bales' weights (it reads 0 until the module is ginned).

Completing ginning also posts the season's incremental ginning charge, and this is where the tier boundary matters. The co-op charges 11.5 cents per pound for a grower's first 100,000 lint pounds in a season and 9.5 cents per pound beyond that. The split is computed marginally per module: take the grower's lint pounds from modules of the same season already `GINNED` strictly earlier by `ginned_at` (ties broken by module `created_at` ascending) as the cumulative base; the current module's first pounds, up to whatever remains of the 100,000-pound tier, bill at 11.5 cents, and the rest bills at 9.5 cents. The module's charge is rounded half-up to whole cents and posted as a single `LedgerEntry` of type `GINNING_CHARGE` with a negative `amount_cents` and a `memo` naming the module ticket. Rounding is pinned per module: each module's charge is rounded individually, and the grower's season total is the plain sum of those rounded module charges — never rounded per bale, and never computed by rounding a season-level raw sum. The posting immediately recomputes the grower's `credit_balance_cents`. Completing ginning also increments the module's `version`.

When the shift winds down, the operator closes it by supplying the three scale totals: `actual_lint_scale_lbs`, `actual_seed_scale_lbs`, and `waste_lbs`. Close enforces mass conservation exactly, in integer pounds: the sum of `net_weight_lbs` over the shift's `GINNED` modules must equal lint plus seed plus waste, and `actual_lint_scale_lbs` must separately equal the sum of `actual_lint_lbs` over those same modules. Either mismatch fails with `ERR_MASS_BALANCE_VIOLATION` (HTTP 422). Closing also requires the shift to be `OPEN` (else `ERR_SHIFT_NOT_OPEN`) and refuses while any module of the shift is still in `GINNING` (else `ERR_MODULES_STILL_GINNING`, HTTP 409). A successful close stores the three scale weights, moves the shift `OPEN → CLOSED`, and increments the shift's `version`.

Reconciliation then distributes the shift's actual seed scale weight back across modules. The shift must be `CLOSED` (else `ERR_SHIFT_NOT_CLOSED`, HTTP 409). Allocation uses largest-remainder apportionment over the shift's `GINNED` modules only — rejected modules never joined a shift — with each module's `est_seed_lbs` as its entitlement weight. Each module's raw share is the shift's `actual_seed_scale_lbs` multiplied by its estimated seed and divided by the total estimated seed across the shift's ginned modules; the share is floored to a whole pound, and the leftover pounds — the scale total minus the sum of floors — are distributed one pound each to the modules with the largest fractional remainders, ties broken by module `created_at` ascending. The result is written to each module's `reconciled_seed_lbs` (incrementing that module's `version`), and the invariant holds exactly: the reconciled pounds sum to the shift's seed scale total. This floor-then-largest-remainder order is pinned and must not be replaced by round-then-sum. The shift moves `CLOSED → RECONCILED` and its `version` increments. Note the dual nature of module seed quantity: before reconciliation the estimate `est_seed_lbs` stands in; after, the scale-allocated `reconciled_seed_lbs` governs, and the two differ whenever the scale total differs from the summed estimates.

### 3.4. Classing: Grade Results, Quality Points, and Reclass Supersede

Bales sit `UNCLASSED` on the gin floor until the USDA office reports. A `ClassingClerk` records each result against a bale, submitting `grade_code`, `micronaire` (one decimal, e.g. 4.5), `strength_gpt` (grams per tex, one decimal), `staple_32nds` (staple length in 32nds of an inch), `classing_office`, the office's `result_date`, and — per §2.6 — `expected_bale_version` matching the bale's current `version`, with `ERR_STALE_VERSION` (HTTP 412) on a mismatch. A covering `GradeSchedule` for the submitted grade at `result_date` must exist, or the write fails with `ERR_NO_ACTIVE_GRADE_SCHEDULE`.

Recording the first result pins a quality snapshot on the new `ClassingResult`. The snapshot's `quality_points` start from the covering schedule's `premium_discount_points`, then add a micronaire band adjustment and a strength band adjustment. Micronaire between 3.7 and 4.2 inclusive earns a premium of 25 points; micronaire outside that premium band but still within the acceptable range of 3.5 to 4.9 inclusive earns 0; anything outside the acceptable range costs 50 points. Strength of at least 29.0 grams per tex adds 15 points; strength of 26.0 or below subtracts 30 points; anything between contributes 0. The bale's `adjustment_cents` is the bale's `net_weight_lbs` multiplied by the total quality points, divided by 100, and rounded half-up to whole cents — a signed value, since discounts run negative. Both figures are pinned on the result at creation and never recomputed in place.

The new result is created `ACTIVE`, and at most one result per bale is ever `ACTIVE`. The bale recomputes its `active_grade_code`, `quality_points`, and `adjustment_cents` from the active result (these read null while the bale is `UNCLASSED`), its `classing_status` flips to `CLASSED`, and its `version` increments. Because quality feeds settlement, every `DRAFT` settlement for the bale's grower and season is then recomputed per the settlement rules of §3.8.

A reclass is the same operation run against an already-`CLASSED` bale — a `CLASSED → CLASSED` self-loop that supersedes rather than edits. The prior `ACTIVE` result flips to terminal `SUPERSEDED` (incrementing the prior result's `version`), the new result is created `ACTIVE` with its own pinned snapshot under the same OCC and schedule-coverage guards, the bale's classing fields recompute from the new snapshot, and every `DRAFT` settlement for the grower-season recomputes again. Both branches of classing — first result and reclass — carry identical guards and identical cascade shape; only the supersede step distinguishes them.

### 3.5. Warehousing: Receipts, Capacity, and Segregation of Duties

A bale leaves the gin floor when a `WarehouseManager` issues a warehouse receipt for it, naming the `bale_id` and the target `warehouse_id`. Issuance enforces three guards. The bale's custody must be `ON_GIN_FLOOR` with no existing receipt in `ACTIVE`, `PLEDGED`, or `RELEASED` status for that bale — otherwise `ERR_RECEIPT_NOT_ISSUABLE` (HTTP 409); note that custody `ON_GIN_FLOOR` itself implies the bale's module was ginned. The warehouse must have room: issuance when `stored_bale_count` equals `capacity_bales` is rejected with `ERR_WAREHOUSE_AT_CAPACITY` (HTTP 422) — at capacity exactly is rejected. And the segregation-of-duties rule forbids the acting operator from being the one who ginned the module: if the request's `X-User-ID` equals the bale's module's `ginned_by_user_id`, the issuance fails with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

A successful issuance creates the receipt `ACTIVE` with a server-minted unique `receipt_number` and a `storage_start_date` taken from the logical clock date — free-day counting starts there. The bale's `custody_status` flips to `WAREHOUSED`, the warehouse's `stored_bale_count` increases by one, and the warehouse's `version` increments.

Cancelling undoes an issuance. The receipt must be `ACTIVE` (else `ERR_RECEIPT_NOT_CANCELLABLE`, HTTP 409). Cancellation moves the receipt to terminal `CANCELLED`, returns the bale's custody to `ON_GIN_FLOOR`, and decrements the warehouse's `stored_bale_count` by one.

### 3.6. Lending: CCC Pledges, Interest, Redemption, and Forfeiture

A receipted bale can collateralize a CCC marketing assistance loan. A `CoopAccountant` pledges by naming the `warehouse_receipt_id`. The receipt must be in `ACTIVE` or `RELEASED` status (else `ERR_RECEIPT_NOT_ACTIVE`, HTTP 409) — the pledge/release cycle may repeat, so a redeemed receipt can be re-pledged under identical guards and an identical cascade. The bale must be `CLASSED` (else `ERR_BALE_NOT_CLASSED`, HTTP 409), because principal prices off the active grade: the covering `GradeSchedule` for the bale's `active_grade_code` at the pledge date must exist (else `ERR_NO_ACTIVE_GRADE_SCHEDULE`), and the pledge pins that row's `loan_rate_points`. Principal is the bale's `net_weight_lbs` multiplied by those loan-rate points, divided by 100, rounded half-up to whole cents, and stored as `principal_cents`. A season-level cap guards the co-op's exposure: the sum of `principal_cents` across the grower's `ACTIVE` pledges in this season, plus the new principal, must not exceed 50,000,000 cents, or the pledge fails with `ERR_LOAN_CAP_EXCEEDED` (HTTP 402).

Pledging creates the `LoanPledge` `ACTIVE`, stamps `pledged_date` from the logical clock, initializes `interest_cents` to 0, flips the receipt to `PLEDGED` (incrementing the receipt's `version`), posts a `LedgerEntry` of type `LOAN_ADVANCE` for positive principal with a `memo` naming the receipt, and recomputes the grower's `credit_balance_cents`.

Redemption repays the loan. The pledge must be `ACTIVE` (else `ERR_PLEDGE_NOT_ACTIVE`, HTTP 409). Interest accrues simply at 0.01 percent of principal per calendar day, counted half-open from `pledged_date` to the logical-clock redemption date — the pledge day counts, the redemption day does not, and a same-day redemption accrues zero days and zero interest. `interest_cents` is principal multiplied by the daily rate multiplied by the day count, rounded half-up to whole cents. Redemption stamps `redeemed_date`, moves the pledge to terminal `REPAID`, flips the receipt to `RELEASED`, posts a `LOAN_REPAYMENT` ledger entry for the negative of principal plus interest, and recomputes the grower's balance.

Forfeiture hands the collateral to the CCC. The pledge must likewise be `ACTIVE` (else `ERR_PLEDGE_NOT_ACTIVE`). The pledge moves to terminal `FORFEITED`, the receipt moves to terminal `FORFEITED`, the bale's `custody_status` flips to `SHIPPED`, and the warehouse's `stored_bale_count` decreases by one. Storage accrual ends at the logical-clock date, and a `STORAGE_CHARGE` ledger entry is posted per the storage rule of §3.7 — no entry at all when the charge computes to zero — followed by the grower balance recompute.

### 3.7. Shipping and Storage: Orders, Dock Windows, and the Free-Day Threshold

Shipping begins with an order. A `Grower` may create one for their own bales (passing their own id as `grower_id`; passing another grower's id fails authorization per §2.1), and a `WarehouseManager` may create one for any grower. The payload names the `warehouse_id`, the `grower_id`, an ordered `bale_ids` list of at least one element (an empty list fails with `ERR_EMPTY_SHIPMENT`, HTTP 400), a `dock_number` within the warehouse's docks from 1 to `dock_count` inclusive (out of range fails with `ERR_INVALID_REQUEST`), and a loading window from `load_start` inclusive to `load_end` exclusive, which must be strictly later than the start (else `ERR_INVALID_WINDOW`).

Create-time guards keep shipments coherent. Every listed bale must belong to the order's grower — a bale owned by someone else fails with `ERR_MIXED_GROWER_SHIPMENT` (HTTP 422) — and every bale's non-terminal receipt must sit at the order's warehouse, else `ERR_BALE_WAREHOUSE_MISMATCH` (HTTP 422). Every bale must currently satisfy the shippable predicate: custody `WAREHOUSED` with a non-terminal receipt in `ACTIVE` or `RELEASED` status; a bale failing this yields `ERR_BALE_NOT_SHIPPABLE` (HTTP 409). Dock turnaround matters too: on the same warehouse and dock, the new window must keep at least a 30-minute gap to every non-cancelled order's window — the new window must end at least 30 minutes before the existing one starts, or start at least 30 minutes after the existing one ends — and any tighter pairing fails with `ERR_DOCK_WINDOW_CONFLICT` (HTTP 409). A valid order is created `DRAFT`.

Confirmation re-validates. The order must be `DRAFT` (else `ERR_ORDER_NOT_CONFIRMABLE`, HTTP 409), and every listed bale must still satisfy the same shippable predicate (else `ERR_BALE_NOT_SHIPPABLE`) — custody may have moved since creation. Both the owning grower and a warehouse manager may confirm; the order moves `DRAFT → CONFIRMED` and its `version` increments.

Shipping executes the cascade. A `WarehouseManager` ships a `CONFIRMED` order (else `ERR_ORDER_NOT_SHIPPABLE`, HTTP 409), again re-checking every bale's shippability. On success the order moves to terminal `SHIPPED`; each listed bale's receipt flips to `SHIPPED` and each bale's `custody_status` flips to `SHIPPED`; the warehouse's `stored_bale_count` decreases by the number of listed bales; and storage accrual ends for each receipt at the logical-clock date. Cancellation is the gentler exit: an order in `DRAFT` or `CONFIRMED` may be cancelled by the owning grower or a warehouse manager, moving to terminal `CANCELLED` with a version increment; cancelling from any other state fails with `ERR_ORDER_NOT_CANCELLABLE` (HTTP 409). The bales of an order can be listed in their original `bale_ids` order.

Storage charges follow a free-day rule wherever accrual ends — at ship per listed receipt, and at forfeit per receipt. Days stored are counted in whole calendar days from `storage_start_date` to the end date, half-open: the start day counts, the end day does not. The first 15 days are free; chargeable days are the days stored minus 15, floored at zero, and each chargeable day costs 12 cents. Exactly 15 days stored means zero charge; 16 days means 12 cents. When the computed charge is zero, no `LedgerEntry` is posted at all; otherwise a `STORAGE_CHARGE` entry with a negative `amount_cents` posts against the grower with a `memo` naming the receipt, and the grower's `credit_balance_cents` recomputes.

### 3.8. Seed Sales and Grower Settlement: Provisional vs. Final

Once a shift is `RECONCILED`, its pooled seed can be sold — once. A `CoopAccountant` creates the sale naming the `gin_shift_id`, the `buyer_name`, and a `price_cents_per_lb` of at least 1 cent (else `ERR_INVALID_REQUEST`). Selling a shift that is not yet `RECONCILED` fails with `ERR_SHIFT_NOT_RECONCILED` (HTTP 409), and a shift that already has a sale fails with `ERR_SHIFT_ALREADY_SOLD` (HTTP 409) — at most one sale exists per shift, so listing a shift's seed sales returns zero or one element.

The sale's `sold_lbs` is the sum of `reconciled_seed_lbs` across the shift's ginned modules. The `net_pool_cents` is those pounds multiplied by the contract price, minus a flat handling fee of 2,500 cents. The pool then allocates back to modules by the same largest-remainder rule used at reconciliation: each module's raw share is the net pool multiplied by its `reconciled_seed_lbs` and divided by `sold_lbs`; shares floor to whole cents; the remainder distributes one cent at a time to the largest fractional parts, ties broken by module `created_at` ascending. Each grower's credit is the sum across their own modules in the shift, posted as a single positive `SEED_CREDIT` ledger entry with a `memo` naming the buyer, and every affected grower's `credit_balance_cents` recomputes. The grower credits sum to the net pool exactly.

Settlement is where the season closes out for a grower, and it runs in two variants. A `CoopAccountant` creates a settlement for a grower and `season`; per §2.6 the request must carry `expected_grower_version` matching the grower's current `version`, with `ERR_STALE_VERSION` (HTTP 412) on mismatch. Creation is refused while a `PAID` settlement exists for that grower and season — `ERR_SETTLEMENT_ALREADY_PAID` (HTTP 409). Otherwise, any existing `DRAFT` or `FINAL` settlement for the pair flips to terminal `SUPERSEDED`, and the new settlement is created `DRAFT` with `computation_variant` of `PROVISIONAL`; creation also increments the grower's `version`.

Every money line is a pure function of the grower's season-scoped inputs, evaluated in a pinned order. First, `lint_value_cents` sums each season bale's `net_weight_lbs` multiplied by the base lint price of 60 cents per pound. Second, `quality_adjustment_cents` sums the `adjustment_cents` of each season bale's `ACTIVE` classing result, with unclassed bales contributing 0. Third, `seed_credit_cents`: under `PROVISIONAL` it is the sum of posted `SEED_CREDIT` entries plus an estimate for unsold shifts — the `est_seed_lbs` of the grower's `GINNED` season modules whose shift has no seed sale, multiplied by a reference price of 25 cents per pound with no handling fee; under `FINAL` it is the posted `SEED_CREDIT` entries only, with no estimates. Fourth, the ledger-derived lines: `ginning_charge_cents` sums the grower's season `GINNING_CHARGE` entries (negative or zero), `storage_charge_cents` sums `STORAGE_CHARGE` entries (likewise negative or zero), `loan_net_cents` sums `LOAN_ADVANCE` and `LOAN_REPAYMENT` entries as a signed net, and `adjustment_net_cents` sums `ADJUSTMENT` entries as a signed net. Fifth, `patronage_cents` is the grower's `patronage_rate` multiplied by the absolute value of `ginning_charge_cents`, rounded half-up to whole cents. Sixth and last, `net_payable_cents` is the sum of the lint, quality, seed, ginning, storage, loan-net, adjustment-net, and patronage lines. The dependency order is pinned: patronage derives from ginning charges, and net payable derives from patronage — net never feeds back into patronage. The two variants legitimately differ: for identical deliveries, provisional and final disagree whenever a sold shift's posted credit differs from its estimate, or a shift is not yet sold.

Draft settlements are living documents: any classing change on a season bale recomputes every `DRAFT` settlement for the grower-season through the same rules. Between create and finalize, an accountant may also post a manual ledger adjustment — a signed `amount_cents` with a `season` and `memo` — which lands as an `ADJUSTMENT` entry, recomputes the grower's balance, and flows into the next settlement recompute through `adjustment_net_cents`.

Finalization hardens the numbers. The settlement must be `DRAFT` (else `ERR_SETTLEMENT_NOT_FINALIZABLE`, HTTP 409), and three completeness gates must all pass: every module of the grower-season must be `GINNED` or `REJECTED` (else `ERR_UNGINNED_MODULES_EXIST`, HTTP 409); every bale of the grower-season must be `CLASSED` (else `ERR_UNCLASSED_BALES_EXIST`, HTTP 409); and every shift holding a `GINNED` module of the grower-season must have its seed sold (else `ERR_UNSOLD_SEED_EXISTS`, HTTP 409). Finalizing recomputes all money lines under `computation_variant` `FINAL`, moves the settlement `DRAFT → FINAL`, and increments its `version`.

Payment closes the loop. The settlement must be `FINAL` (else `ERR_SETTLEMENT_NOT_FINAL`, HTTP 409), and the payload `amount_cents` must equal the settlement's `net_payable_cents` exactly — any other amount fails with `ERR_OVERPAYMENT` (HTTP 402). On success `paid_amount_cents` captures the amount (it reads null until paid), the settlement moves to terminal `PAID`, and two ledger entries post with `settlement_id` set: a `PATRONAGE` entry for positive `patronage_cents` and a `SETTLEMENT_PAYMENT` entry for the negative of `net_payable_cents`. Each posting recomputes the grower's `credit_balance_cents`. Ledger entries can be listed filtered by `grower_id`, `settlement_id`, or `season`, and fetched individually; a `Grower` caller sees only entries on their own account.

## 4. Endpoint Definitions

All endpoints are mounted under `/gin-ops`, except the test-driving clock at `/_clock/set_current_utc`. Creating a new resource returns HTTP 201; modifications, transitions, and reads return HTTP 200. Request and response bodies follow the envelope of §2.2 and the narratives of §3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/_clock/set_current_utc` | Advance the logical clock to `to_iso8601` | CoopAdmin |
| POST | `/gin-ops/growers` | Register a co-op grower | CoopAdmin |
| GET | `/gin-ops/growers/{id}` | Get a grower (Grower role: self only) | CoopAdmin, GinOperator, ClassingClerk, WarehouseManager, CoopAccountant, Grower |
| GET | `/gin-ops/growers/{id}/settlements` | List settlements of a grower (Grower role: self only) | CoopAdmin, GinOperator, ClassingClerk, WarehouseManager, CoopAccountant, Grower |
| POST | `/gin-ops/growers/{growerId}/settlements` | Create a superseding settlement for grower+season; OCC on Grower.version | CoopAccountant |
| POST | `/gin-ops/growers/{growerId}/ledger-adjustments` | Post a manual ADJUSTMENT ledger entry | CoopAccountant |
| GET | `/gin-ops/ledger-entries` | Filtered ledger list (Grower role: own entries only) | CoopAdmin, GinOperator, ClassingClerk, WarehouseManager, CoopAccountant, Grower |
| GET | `/gin-ops/ledger-entries/{id}` | Get a single ledger entry (Grower role: own entries only) | CoopAdmin, GinOperator, ClassingClerk, WarehouseManager, CoopAccountant, Grower |
| POST | `/gin-ops/grade-schedules` | Create a grade schedule window; same-grade half-open windows must not overlap | CoopAdmin |
| GET | `/gin-ops/grade-schedules/{id}` | Get a grade schedule | CoopAdmin, GinOperator, ClassingClerk, WarehouseManager, CoopAccountant, Grower |
| POST | `/gin-ops/warehouses` | Create a warehouse | CoopAdmin |
| GET | `/gin-ops/warehouses/{id}` | Get a warehouse | CoopAdmin, GinOperator, ClassingClerk, WarehouseManager, CoopAccountant, Grower |
| POST | `/gin-ops/gin-shifts` | Open a gin shift | GinOperator |
| GET | `/gin-ops/gin-shifts/{id}` | Get a gin shift | CoopAdmin, GinOperator, ClassingClerk, WarehouseManager, CoopAccountant, Grower |
| POST | `/gin-ops/gin-shifts/{id}/close` | Close a shift with actual scale weights; enforces exact mass balance | GinOperator |
| POST | `/gin-ops/gin-shifts/{id}/reconcile` | Run mass-balance seed allocation; CLOSED → RECONCILED | GinOperator |
| GET | `/gin-ops/gin-shifts/{id}/seed-sales` | List seed sales of a shift (0 or 1 element) | CoopAdmin, GinOperator, ClassingClerk, WarehouseManager, CoopAccountant, Grower |
| POST | `/gin-ops/modules` | Receive a module and cut the grower ticket | GinOperator |
| GET | `/gin-ops/modules/{id}` | Get a module receipt (Grower role: own modules only) | CoopAdmin, GinOperator, ClassingClerk, WarehouseManager, CoopAccountant, Grower |
| GET | `/gin-ops/modules` | Filtered module list (Grower role: own modules only) | CoopAdmin, GinOperator, ClassingClerk, WarehouseManager, CoopAccountant, Grower |
| POST | `/gin-ops/modules/{id}/condition` | Record a new moisture reading; RECEIVED↔CONDITIONING cycle | GinOperator |
| POST | `/gin-ops/modules/{id}/queue` | Queue a RECEIVED module into an OPEN same-season shift | GinOperator |
| POST | `/gin-ops/modules/{id}/start-ginning` | Begin ginning a QUEUED module | GinOperator |
| POST | `/gin-ops/modules/{id}/complete-ginning` | Record produced bales and finish ginning; posts the tiered ginning charge | GinOperator |
| POST | `/gin-ops/modules/{id}/reject` | Reject a contaminated module (RECEIVED/CONDITIONING only) | GinOperator |
| GET | `/gin-ops/modules/{id}/bales` | List bales produced by a module | CoopAdmin, GinOperator, ClassingClerk, WarehouseManager, CoopAccountant, Grower |
| GET | `/gin-ops/bales/{id}` | Get a bale (Grower role: own bales only) | CoopAdmin, GinOperator, ClassingClerk, WarehouseManager, CoopAccountant, Grower |
| POST | `/gin-ops/bales/{id}/classing-results` | Record a USDA classing result; supersedes the prior ACTIVE result; OCC on Bale.version | ClassingClerk |
| GET | `/gin-ops/bales/{id}/classing-results` | List classing results of a bale (ACTIVE and SUPERSEDED) | CoopAdmin, GinOperator, ClassingClerk, WarehouseManager, CoopAccountant, Grower |
| POST | `/gin-ops/warehouse-receipts` | Issue a warehouse receipt for an on-floor bale; segregation of duties enforced | WarehouseManager |
| GET | `/gin-ops/warehouse-receipts/{id}` | Get a warehouse receipt | CoopAdmin, GinOperator, ClassingClerk, WarehouseManager, CoopAccountant, Grower |
| GET | `/gin-ops/warehouse-receipts` | Filtered warehouse receipt list | CoopAdmin, GinOperator, ClassingClerk, WarehouseManager, CoopAccountant, Grower |
| POST | `/gin-ops/warehouse-receipts/{id}/cancel` | Cancel an ACTIVE receipt; bale returns to the gin floor | WarehouseManager |
| POST | `/gin-ops/loan-pledges` | Pledge an ACTIVE/RELEASED receipt for a CCC marketing assistance loan | CoopAccountant |
| GET | `/gin-ops/loan-pledges/{id}` | Get a loan pledge | CoopAdmin, GinOperator, ClassingClerk, WarehouseManager, CoopAccountant, Grower |
| GET | `/gin-ops/warehouse-receipts/{id}/loan-pledges` | List pledges against a receipt | CoopAdmin, GinOperator, ClassingClerk, WarehouseManager, CoopAccountant, Grower |
| POST | `/gin-ops/loan-pledges/{id}/redeem` | Repay principal plus accrued simple interest; receipt RELEASED | CoopAccountant |
| POST | `/gin-ops/loan-pledges/{id}/forfeit` | Forfeit the collateral to CCC; receipt and bale leave storage | CoopAccountant |
| POST | `/gin-ops/seed-sales` | Sell a reconciled shift's pooled seed; allocates proceeds per grower | CoopAccountant |
| GET | `/gin-ops/settlements/{id}` | Get a settlement (Grower role: own only) | CoopAdmin, GinOperator, ClassingClerk, WarehouseManager, CoopAccountant, Grower |
| POST | `/gin-ops/settlements/{id}/finalize` | Recompute with FINAL variant; requires season fully ginned, classed, seed sold | CoopAccountant |
| POST | `/gin-ops/settlements/{id}/pay` | Pay a FINAL settlement; amount must equal net_payable_cents exactly | CoopAccountant |
| POST | `/gin-ops/shipping-orders` | Create a shipping order (dock window with 30-minute turnaround buffer) | Grower, WarehouseManager |
| GET | `/gin-ops/shipping-orders/{id}` | Get a shipping order (Grower role: own only) | CoopAdmin, GinOperator, ClassingClerk, WarehouseManager, CoopAccountant, Grower |
| GET | `/gin-ops/shipping-orders` | Filtered shipping order list (Grower role: own only) | CoopAdmin, GinOperator, ClassingClerk, WarehouseManager, CoopAccountant, Grower |
| POST | `/gin-ops/shipping-orders/{id}/confirm` | Confirm a DRAFT order; revalidates bale shippability | Grower, WarehouseManager |
| POST | `/gin-ops/shipping-orders/{id}/ship` | Ship a CONFIRMED order; ends storage accrual and posts storage charges | WarehouseManager |
| POST | `/gin-ops/shipping-orders/{id}/cancel` | Cancel a DRAFT or CONFIRMED order | Grower, WarehouseManager |
| GET | `/gin-ops/shipping-orders/{id}/bales` | List bales on a shipping order, in `bale_ids` order | CoopAdmin, GinOperator, ClassingClerk, WarehouseManager, CoopAccountant, Grower |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_INVALID_REQUEST | 400 |
| ERR_GROWER_NOT_FOUND | 404 |
| ERR_MODULE_NOT_FOUND | 404 |
| ERR_BALE_NOT_FOUND | 404 |
| ERR_GIN_SHIFT_NOT_FOUND | 404 |
| ERR_WAREHOUSE_NOT_FOUND | 404 |
| ERR_WAREHOUSE_RECEIPT_NOT_FOUND | 404 |
| ERR_LOAN_PLEDGE_NOT_FOUND | 404 |
| ERR_SETTLEMENT_NOT_FOUND | 404 |
| ERR_SHIPPING_ORDER_NOT_FOUND | 404 |
| ERR_GRADE_SCHEDULE_NOT_FOUND | 404 |
| ERR_LEDGER_ENTRY_NOT_FOUND | 404 |
| ERR_MODULE_NOT_QUEUABLE | 409 |
| ERR_MODULE_NOT_CONDITIONABLE | 409 |
| ERR_MODULE_NOT_GINNABLE | 409 |
| ERR_MODULE_NOT_COMPLETABLE | 409 |
| ERR_MODULE_NOT_REJECTABLE | 409 |
| ERR_SHIFT_NOT_OPEN | 409 |
| ERR_MODULES_STILL_GINNING | 409 |
| ERR_SHIFT_NOT_CLOSED | 409 |
| ERR_SHIFT_NOT_RECONCILED | 409 |
| ERR_SHIFT_ALREADY_SOLD | 409 |
| ERR_MASS_BALANCE_VIOLATION | 422 |
| ERR_DUPLICATE_TICKET_NUMBER | 409 |
| ERR_DUPLICATE_MODULE_TAG | 409 |
| ERR_DUPLICATE_BALE_TAG | 409 |
| ERR_FOREIGN_MATTER_LIMIT_EXCEEDED | 422 |
| ERR_MOISTURE_LIMIT_EXCEEDED | 422 |
| ERR_SEASON_MISMATCH | 422 |
| ERR_GRADE_WINDOW_OVERLAP | 409 |
| ERR_NO_ACTIVE_GRADE_SCHEDULE | 422 |
| ERR_STALE_VERSION | 412 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_WAREHOUSE_AT_CAPACITY | 422 |
| ERR_RECEIPT_NOT_ISSUABLE | 409 |
| ERR_RECEIPT_NOT_CANCELLABLE | 409 |
| ERR_RECEIPT_NOT_ACTIVE | 409 |
| ERR_BALE_NOT_CLASSED | 409 |
| ERR_LOAN_CAP_EXCEEDED | 402 |
| ERR_PLEDGE_NOT_ACTIVE | 409 |
| ERR_INVALID_WINDOW | 400 |
| ERR_DOCK_WINDOW_CONFLICT | 409 |
| ERR_EMPTY_SHIPMENT | 400 |
| ERR_MIXED_GROWER_SHIPMENT | 422 |
| ERR_BALE_WAREHOUSE_MISMATCH | 422 |
| ERR_BALE_NOT_SHIPPABLE | 409 |
| ERR_ORDER_NOT_CONFIRMABLE | 409 |
| ERR_ORDER_NOT_SHIPPABLE | 409 |
| ERR_ORDER_NOT_CANCELLABLE | 409 |
| ERR_UNGINNED_MODULES_EXIST | 409 |
| ERR_UNCLASSED_BALES_EXIST | 409 |
| ERR_UNSOLD_SEED_EXISTS | 409 |
| ERR_SETTLEMENT_NOT_FINALIZABLE | 409 |
| ERR_SETTLEMENT_ALREADY_PAID | 409 |
| ERR_SETTLEMENT_NOT_FINAL | 409 |
| ERR_OVERPAYMENT | 402 |
