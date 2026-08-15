# Sawmill Lumber Production API — Product Requirements Document

## 1. Introduction

Running a sawmill profitably is a discipline of reconciliations. The log yard buys raw material by the thousand board feet against species and grade commitments; the saw floor converts decked logs into green packages at a recovery factor that only becomes provable weeks later when the kiln and the grader have finished with the wood; sales commits volume against contracts that must neither be over-reserved nor left to rot unexpired. Between those stations sit two slow drifts that quietly erode margin — logs degrade while they wait in the deck, and lumber shrinks while it dries — and a commercial split between fixed-price contract business and a spot market whose price depends on species, grade, length, and order size.

This document specifies a mill operations API that carries a log load from the scale house to the log deck, through a sawing run and its kiln charge, into grade stamping and order allocation, and out the gate as shipped lumber or byproduct tons. Every commercial figure the system reports — purchase cost, recovery percent, contract drawdown, order totals — is pinned to an explicit formula so that two engineers reading this document independently arrive at the same numbers. Time itself is a first-class input: deck degrade, kiln windows, contract expiry, and price effectiveness all read a single logical clock rather than the wall clock, so the mill's behavior is reproducible end to end.

The intended readers are the engineers implementing this service. They should be able to build the entire system from this document alone, without access to any internal design tables.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API carries two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming the role under which that operator acts. A request missing either header, or presenting a role value the system does not declare, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Once authenticated, the role is checked against the endpoint's authorized role list; a role not on that list is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system declares exactly six roles:

- `Scaler` — the log yard scaler, who receives, scales, disputes, decks, and undecks log loads.
- `Sawyer` — the saw line operator, who plans and completes sawing runs.
- `KilnOperator` — the kiln operator, who schedules, starts, completes, and aborts kiln charges.
- `Grader` — the lumber grader, who stamps and re-stamps package grades.
- `SalesRep` — the sales representative, who places, allocates, ships, and cancels orders and records byproduct sales.
- `MillManager` — the mill manager, who resolves scale disputes, publishes price lists, creates and amends contracts, activates them, runs ops checkpoints, and sets the logical clock.

For every role, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server never compares `X-User-ID` against any resource's `id`; ownership-style checks do not exist in this domain. Access control is purely role-based: the peer roles partition the write surface (each action endpoint lists exactly one acting role in §4), while all read endpoints are shared by all six roles.

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

List endpoints accept two query parameters: `limit` and `offset`. When `limit` is omitted it defaults to 10; the accepted range is a minimum of 1 and a maximum of 100, and values outside that range are rejected as `ERR_INVALID_REQUEST`. When `offset` is omitted it defaults to 0. Every list response sorts by `created_at` ascending, and every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object, where `total_count` is the full count of matching resources ignoring pagination and `has_more` indicates whether further pages exist beyond the returned window.

### 2.4. Resource Identity and Mutation Semantics

Every persisted resource exposes an `id` field: a server-minted UUID with no type prefix. Most resources additionally carry `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and an integer `version` field that starts at creation and increments by exactly 1 on every state transition or mutating update applied to that resource. Clients use `version` for optimistic concurrency where this document requires it.

Two resource kinds are deliberately lighter. A grade inspection record and a byproduct sale record are append-only ledger entries: they carry `id` and `created_at` but no `updated_at` and no `version`, because nothing about them is ever mutated after the moment of recording.

Whenever a transition described in §3 says it "increments" a resource's version, the `updated_at` of that same resource refreshes to the current logical time as part of the same write. Cross-entity cascades are always atomic with their triggering write: if a completion, allocation, or shipment flips several resources, all of those flips and recomputes succeed or fail together.

### 2.5. The Logical Clock

The mill does not read wall-clock time. A single logical clock governs every time-dependent rule in this document: deck degrade accrual, kiln scheduling windows, contract expiry, and price-list effectiveness. At server startup the logical clock reads exactly `2026-08-01T00:00:00Z`, and it advances only when a `MillManager` invokes the test-driving capability that sets the clock to a supplied `to_iso8601` instant. The clock never falls back to wall-clock time between such calls. Any timestamp this document describes as "current logical time" is a read of this clock; timestamps written onto resources at transitions (such as `decked_at`, `actual_start`, `completed_at`, `stamped_at`) are logical-clock values.

### 2.6. Numeric Precision and Rounding Conventions

All monetary amounts are integer cents; all rounding in this system is round-half-up. Four precision tiers apply depending on the quantity being computed. Purchase costs, unit prices, order totals, and byproduct sale totals are integer cents, rounded half-up at the points §3 specifies. Recovery percentages are carried to 2 decimal places, rounded half-up. Volumes measured in thousand board feet — effective volumes after degrade, estimated and actual dry volumes — are carried to 3 decimal places, rounded half-up. Deck degrade itself is an integer percent. Moisture comparisons are made at 1 decimal place with an inclusive boundary. These precisions are pinned per calculation in §3 and are part of the contract: an implementation that rounds at different points, or rounds a sum instead of rounding each term, will produce observably different totals.

### 2.7. Validation Order and Optimistic Concurrency

Incoming requests are validated in a fixed order, and the order is observable because it determines which error a malformed request receives when several problems are present at once. Authentication comes first: missing or invalid headers yield `ERR_UNAUTHENTICATED` before anything else is examined, and an authenticated role not permitted on the endpoint yields `ERR_FORBIDDEN` next. Path identifiers are then resolved left to right — each id in the URL must exist before the request proceeds, otherwise `ERR_NOT_FOUND`. Body shape is validated next: missing required fields, wrong types, invalid enum values, non-positive numeric quantities, or empty arrays where an array is required all yield `ERR_INVALID_REQUEST`. Only after the request is well-formed does the server evaluate entity state preconditions for the invoked transition (`ERR_INVALID_STATE`, or `ERR_CONTRACT_NOT_ACTIVE` where a contract order is involved), then business-temporal rules (schedule windows), then business constraints (chamber and line occupancy, deck capacity, run log-set integrity), then referential linkage (species and grade agreement), and finally fiscal rules (contract volume, price-list availability, allocation pool sufficiency, byproduct on-hand). Within the fiscal tier, a contract order is checked against its contract's remaining volume, a spot order against price-list availability, an allocation against the stamped pool, and a byproduct sale against on-hand tons.

Exactly one endpoint participates in optimistic concurrency control. Amending a sales contract requires the request to carry `expected_contract_version`, a non-optional field holding the contract `version` the client last observed. If the contract's current `version` has advanced beyond that value — because another amendment or a lifecycle transition landed in the meantime — the amendment is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from silently overwriting contract terms it never saw. No other endpoint accepts a version field; clients must not send one elsewhere.

### 2.8. Enumerated Vocabularies

Species throughout the system are exactly `DOUGLAS_FIR`, `PONDEROSA_PINE`, `HEMLOCK_FIR`, and `CEDAR`. Log purchase grades are `PEELER`, `SAWLOG_1`, `SAWLOG_2`, and `UTILITY`. Saw lines are `LINE_A` and `LINE_B`; sawing patterns are `DIMENSION_2X4`, `STUD_MIX`, and `TIMBER_4X4`. Kiln chambers are `KILN_1`, `KILN_2`, and `KILN_3`. Package dimensions are `2X4`, `2X6`, and `4X4`; package lengths in feet are 8, 10, 12, and 16. Stamped lumber grades are `SELECT_STRUCT`, `NO_2`, `NO_3`, and `ECONOMY`. An order's length specification is either `RL` — random length, accepting any package length — or one of the exact lengths 8, 10, 12, or 16. Byproduct products are `CHIP`, `SAWDUST`, and `BARK`. Pricing modes are `CONTRACT` and `SPOT`; inspection actions are `STAMP` and `RESTAMP`.

Resource statuses, enumerated fully so no reader invents others: a log load is `RECEIVED`, `SCALED`, `DISPUTED`, `DECKED`, or `CONSUMED`; a sawing run is `PLANNED` or `COMPLETED`; a kiln charge is `SCHEDULED`, `IN_PROGRESS`, `COMPLETED`, or `ABORTED`; a lumber package is `GREEN`, `IN_KILN`, `DRY`, `STAMPED`, `ALLOCATED`, or `SHIPPED`; a sales contract is `DRAFT`, `ACTIVE`, `CLOSED`, or `EXPIRED`; a sales order is `PLACED`, `ALLOCATED`, `SHIPPED`, or `CANCELLED`.

## 3. Business Logic & Workflows

### 3.1. Receiving and Scaling Log Loads

A load's life begins when a `Scaler` receives it at the scale house, supplying the `supplier_name`, the `species`, and the purchase `log_grade`. The new load enters at `RECEIVED` with `degrade_pct` at zero and no commercial terms yet: `scaled_mbf` and `price_per_mbf_cents` are unset, `purchase_cost_cents` is null, and `decked_at`, `sawing_run_id`, and `days_in_deck` have no meaningful values. Receiving returns 201.

Scaling converts the reception record into a commercial one. A `Scaler` scales a load that is currently `RECEIVED`, providing `scaled_mbf` — the scaled net volume in thousand board feet — and `price_per_mbf_cents`, the agreed purchase price per thousand board feet in cents. The server records both, then computes the load's `purchase_cost_cents` as the product of `scaled_mbf` and `price_per_mbf_cents`, rounded half-up to whole cents, and increments the load's `version`. The load moves from `RECEIVED` to `SCALED`. Both quantities must be positive numbers; a non-positive or missing value is an `ERR_INVALID_REQUEST`.

If the supplier contests the scale, the `Scaler` disputes the load, which moves a `SCALED` load to `DISPUTED` and records the `reason` supplied with the dispute, incrementing `version`. Resolution is the `MillManager`'s prerogative: resolving a `DISPUTED` load returns it to `SCALED`, replaces `scaled_mbf` and `price_per_mbf_cents` with the resolved figures supplied on the resolution call, recomputes `purchase_cost_cents` from those new figures with the same half-up-to-whole-cents rule, and increments `version` again. The dispute loop `SCALED` → `DISPUTED` → `SCALED` is unbounded — a load may cycle through dispute and resolution any number of times, each resolution replacing the commercial terms wholesale. Attempting to scale a load that is not `RECEIVED`, dispute one that is not `SCALED`, or resolve one that is not `DISPUTED` is an `ERR_INVALID_STATE` rejection.

### 3.2. The Log Deck: Capacity, Rotation, and Degrade

Decking moves a `SCALED` load into the log deck, the physical yard where logs await the saw. Only a `SCALED` load can be decked. The deck has a hard aggregate capacity of 500 thousand board feet: decking a load is allowed only when the sum of `scaled_mbf` across all loads currently `DECKED`, plus the decking load's own `scaled_mbf`, does not exceed 500 — sitting exactly at capacity is permitted. A decking that would push the aggregate over 500 is rejected with `ERR_DECK_CAPACITY_EXCEEDED` (HTTP 422). On a successful deck, the server stamps `decked_at` with the current logical time, sets `degrade_pct` to 0, starts `days_in_deck` at 0, moves the load to `DECKED`, and increments `version`.

Wood waits poorly. While a load is `DECKED`, its `days_in_deck` is the number of whole days elapsed since `decked_at` — the elapsed seconds between the current logical time and `decked_at`, divided by 86,400, with the quotient truncated to a whole number. The first 14 days in the deck are free: while `days_in_deck` is at most 14, `degrade_pct` stays at 0. Beyond the free window, degrade accrues at 3 percent per whole additional week: take the number of days past the 14-day window, divide by 7 truncating to a whole number, multiply by 3, and cap the result at 15 — degrade never exceeds 15 percent no matter how long the load sits. A load decked for 20 days therefore degrades 0 percent (six days past the window is not yet a whole week), while one decked for 22 days degrades 3 percent. Only `DECKED` loads degrade; a load that is `SCALED` or `CONSUMED` carries `degrade_pct` of 0, and `days_in_deck` reads 0 for any load not currently `DECKED`.

Degrade is not computed lazily on every read. A `MillManager` runs an ops checkpoint — described fully in §3.9 — which refreshes `degrade_pct` (and the derived `days_in_deck`) on every `DECKED` load from the logical clock. Between checkpoints the stored `degrade_pct` is the value as of the last checkpoint.

The degrade feeds the load's effective volume: `effective_mbf` is the load's `scaled_mbf` multiplied by one minus `degrade_pct` expressed as a fraction, rounded half-up to 3 decimal places, and it remains null until the load has been scaled. This effective volume, not the scaled volume, is what the saw eventually consumes — a load left too long in the deck contributes less wood to its run's recovery denominator.

Decking is reversible by design. Undecking pulls a `DECKED` load back to `SCALED`, clearing `decked_at` and resetting both `degrade_pct` and `days_in_deck` to 0, and increments `version`. Undecking is the compensating action for the deck-occupancy invariant, and it is blocked precisely when compensation would be unsafe: a load already attached to a planned sawing run — its `sawing_run_id` set — cannot be undecked, and the attempt is rejected as `ERR_INVALID_STATE`.

### 3.3. Planning and Completing Sawing Runs

A `Sawyer` plans a sawing run by naming the `saw_line` (`LINE_A` or `LINE_B`), the `scheduled_date` the run occupies that line, the `sawing_pattern` to cut, and an ordered array `log_load_ids` of decked loads to consume. The date occupies the whole calendar day: no other `PLANNED` run may share the same `saw_line` on the same `scheduled_date`, and a conflicting plan is rejected with `ERR_SAW_LINE_BOOKED` (HTTP 409). Adjacent days are free, and the other line on the same day is free — occupation is per line per day, nothing more.

The log set must be clean. Every id in `log_load_ids` must reference a load that is currently `DECKED` and not already attached to another planned run, the array must not be empty, and it must contain no duplicates; a duplicate id or a load already promised to another `PLANNED` run yields `ERR_DUPLICATE_LOAD_IN_RUN` (HTTP 422), while a load in the wrong state yields `ERR_INVALID_STATE`. At creation the run enters at `PLANNED`, and each listed load is attached: its `sawing_run_id` is set to the new run's id, which is also why such a load can no longer be undecked. Planning returns 201 with the new run; `input_mbf`, `output_green_mbf`, both recovery figures, and `completed_at` remain null, and the byproduct tonnage fields are unset until completion.

Completion is the saw floor's moment of truth. A `Sawyer` completes a run that is still `PLANNED`, provided every load in its `log_load_ids` is still `DECKED` and still attached to this run; a load pulled away or consumed elsewhere fails the precondition with `ERR_INVALID_STATE`. The completion payload carries `packages`, an array of package entries, and three byproduct tonnages: `chip_tons`, `sawdust_tons`, and `bark_tons`. Completion then fires every one of the following effects as a single write.

First, each attached load flips from `DECKED` to `CONSUMED`, snapshots its `effective_mbf` at the degrade percent current at that moment, and increments its own `version`; the sum of those snapshots becomes the run's `input_mbf`. Second, one lumber package is created per entry in `packages` — each with its supplied `species`, `dimension`, `length_ft`, `pieces`, and `green_mbf` tally measured at the saw — entering at status `GREEN` with `sawing_run_id` pointing back to this run. Third, the run's `output_green_mbf` is computed as the sum of the `green_mbf` of all packages just created, and its provisional recovery is computed immediately: `recovery_pct_provisional` is `output_green_mbf` divided by `input_mbf`, multiplied by 100, rounded half-up to 2 decimal places. Fourth, the recorded byproduct tonnages raise the mill's sellable byproduct inventory, as §3.8 details. Finally, `completed_at` is stamped with the current logical time and the run's `version` increments.

The provisional recovery is exactly that — provisional. It uses green tally at the saw, before shrink, so it overstates the wood that will eventually be sellable. The certified variant, computed later from dry volumes, is described in §3.5.

### 3.4. Drying: Kiln Charge Scheduling and the Turnaround Buffer

A `KilnOperator` schedules a kiln charge by naming the `chamber` (`KILN_1`, `KILN_2`, or `KILN_3`), the single `species` being dried, the `package_ids` to charge, a `scheduled_start`, a `scheduled_end`, and the `target_moisture_pct` the charge aims for, such as 15.0. Three families of rules guard the schedule.

Temporal rules come first. The `scheduled_start` must not lie in the past relative to the current logical time — a start before now is rejected with `ERR_SCHEDULE_IN_PAST` (HTTP 422) — and the `scheduled_end` must be strictly after `scheduled_start`, an end at or before the start drawing `ERR_END_BEFORE_START` (HTTP 422).

Occupancy comes second. A chamber turns around between charges: a new charge on a chamber may be scheduled only if, against every existing `SCHEDULED` or `IN_PROGRESS` charge on that same chamber, either the new charge's start is at least 4 hours after the existing charge's end, or the new charge's end is at least 4 hours before the existing charge's start. Exactly 4 hours of adjacency is allowed in either direction; anything less violates the buffer and is rejected with `ERR_KILN_OVERLAP` (HTTP 409). The window is half-open — the existing charge occupies from its start up to but not including its end — and the buffer applies symmetrically on both sides. Charges on different chambers never interfere.

Package linkage comes third. Every id in `package_ids` must reference a package currently `GREEN` whose `species` equals the charge's `species`; a package of the wrong species, or a contract-style mismatch of the same family on the order side, is rejected with `ERR_PRODUCT_MISMATCH` (HTTP 422), while a package not in `GREEN` state fails as `ERR_INVALID_STATE`.

A successfully created charge enters at `SCHEDULED`, returns 201, and immediately moves every charged package from `GREEN` to `IN_KILN`, stamping each package's `kiln_charge_id` with the new charge's id and incrementing each package's `version`. `actual_start` and `actual_end` remain null.

Starting a charge requires that the charge is `SCHEDULED` and that the current logical time has reached `scheduled_start`; starting early is rejected with `ERR_SCHEDULE_IN_PAST`. A successful start moves the charge to `IN_PROGRESS`, stamps `actual_start` with the current logical time, and increments the charge's `version`.

Completing a charge requires that the charge is `IN_PROGRESS` and that the current logical time has reached `scheduled_end`. The operator supplies `readings`, an array of per-package measurements that must cover exactly the charged package set — every charged package id present, no extras; a reading set that misses a charged package or names a stranger is an `ERR_INVALID_REQUEST`. Each reading carries the package's measured `exit_moisture_pct` and its measured dry tally. The moisture gate is then applied per package, with a tolerance of 2.0 percentage points: a package whose `exit_moisture_pct` is at most `target_moisture_pct` plus 2.0 passes, while one above that threshold fails — the comparison is at 1 decimal place with an inclusive boundary, so a reading exactly 2.0 points over target still passes. Passing packages flip from `IN_KILN` to `DRY`: their `actual_dry_mbf` is set from the reading, their `dry_mbf` reconciles from the estimate to the measured figure as §3.5 describes, their `kiln_charge_id` is cleared, and their `version` increments. Failing packages flip back from `IN_KILN` to `GREEN` for rework: `kiln_charge_id` is cleared, `actual_dry_mbf` is left null, and `version` increments. Completion stamps `actual_end`, moves the charge to `COMPLETED`, and increments the charge's `version`.

Aborting is the escape hatch, available from either `SCHEDULED` or `IN_PROGRESS`. An abort flips every charged package from `IN_KILN` back to `GREEN`, clears each `kiln_charge_id`, leaves `actual_dry_mbf` unset, stamps the charge's `actual_end`, moves it to `ABORTED`, and increments the charge's `version`. The rework cycle `GREEN` → `IN_KILN` → `GREEN` — whether from a moisture failure or an abort — is unbounded: a failed package may simply be charged again under a new charge.

### 3.5. Shrink, Reconciliation, and Certified Recovery

Lumber loses volume in the kiln, and the system tracks both sides of that loss. At the moment a package is created by run completion, its `estimated_dry_mbf` is computed from the green tally using a species shrink constant: `green_mbf` multiplied by one minus the shrink fraction for the package's species, rounded half-up to 3 decimal places. The shrink fractions are 0.06 for `DOUGLAS_FIR`, 0.07 for `PONDEROSA_PINE`, 0.08 for `HEMLOCK_FIR`, and 0.05 for `CEDAR`. The estimate governs from creation until the kiln measures reality: whenever `actual_dry_mbf` has been recorded — at the completion of a charge the package passed — the package's `dry_mbf` is the actual figure; until then, `dry_mbf` is the estimate. This is the reconciliation point: allocation pools, order totals, and certified recovery all read `dry_mbf`, so they all silently upgrade from estimated to measured volumes as kiln completions land.

Recovery has two variants on the run, and the difference between them is precisely this reconciliation. The provisional variant, `recovery_pct_provisional`, is computed once at run completion from green volumes, as §3.3 describes, and is available immediately. The certified variant, `recovery_pct_certified`, becomes computable only when every package the run produced has reached `STAMPED`, `ALLOCATED`, or `SHIPPED` — until that moment it is null. When the condition first holds and on every subsequent change to the stamped set, the server recomputes `recovery_pct_certified` as the sum of the current `dry_mbf` of the run's packages in those three states, divided by the run's `input_mbf`, multiplied by 100, rounded half-up to 2 decimal places, and bumps the run's `version` with the recompute. Because certified recovery uses post-shrink dry volumes, it is strictly lower than the provisional figure whenever any shrink has occurred — the gap between the two is the saw floor's honest yield report.

### 3.6. Grade Stamping, Re-Stamping, and the Release Cascade

Once a package is `DRY`, a `Grader` stamps it. Recording an inspection with `action` of `STAMP` on a `DRY` package sets the package's `stamped_grade` to the `inspector_grade` the grader observed — one of `SELECT_STRUCT`, `NO_2`, `NO_3`, or `ECONOMY` — stamps `stamped_at` with the current logical time, moves the package from `DRY` to `STAMPED`, and increments its `version`. An optional `note` may accompany any inspection. Every inspection, stamp or restamp, appends an immutable grade inspection row carrying the `package_id`, the `inspector_grade`, the `action`, and the optional `note`; the history of a package is readable as this append-only list, and the list operation returns 200 while a newly recorded inspection returns 201. Stamping is also the trigger for certified recovery: the newly `STAMPED` package now counts toward its run's stamped set, and when this stamp completes the set — every package of the run now `STAMPED`, `ALLOCATED`, or `SHIPPED` — the run's `recovery_pct_certified` is computed for the first time, per §3.5.

Re-stamping is the downfall record. On a `STAMPED` package, an inspection with `action` of `RESTAMP` replaces `stamped_grade` with the new `inspector_grade`, refreshes `stamped_at`, appends the inspection row, and increments `version` — the package stays `STAMPED`. On an `ALLOCATED` package the outcome splits on whether the new grade still satisfies the order holding it. When the `inspector_grade` equals the holding order's `grade`, nothing is released: the package stays `ALLOCATED`, keeps its `sales_order_id`, the row is appended, and `version` increments. When the `inspector_grade` differs, the release cascade fires: the package's `stamped_grade` is replaced with the `inspector_grade`, its `sales_order_id` is cleared, and it falls back from `ALLOCATED` to `STAMPED`; the order it left recomputes `allocated_mbf` and `total_cents` without it; and an order left with zero allocated packages by the release flips from `ALLOCATED` back to `PLACED`. Attempting a `STAMP` on a package that is not `DRY`, or a `RESTAMP` on one that is neither `STAMPED` nor `ALLOCATED`, is an `ERR_INVALID_STATE` rejection.

### 3.7. Pricing: Contracts, Spot Lists, and Order Placement

A `MillManager` publishes spot prices as immutable rows, each naming a `species`, a `grade`, a `base_price_per_mbf_cents`, and an `effective_from` timestamp from which the row applies. Rows are never edited or retracted; a price change is a new row with a later `effective_from`, and publication returns 201.

Contracts are the other pricing rail. A `MillManager` creates a sales contract with the `customer_name`, `species`, `grade`, the total `committed_mbf` volume commitment, the fixed `contract_price_per_mbf_cents`, a `start_date`, and an `end_date` that must fall after `start_date`. A new contract enters at `DRAFT` with `reserved_mbf` and `shipped_mbf` at zero, and returns 201. Activating moves a `DRAFT` contract to `ACTIVE` and increments its `version`; only `ACTIVE` contracts accept orders.

Amendment is a legitimate, repeatable edit on a contract in `DRAFT` or `ACTIVE` — a contract in a terminal state rejects amendment as `ERR_INVALID_STATE` — and it is the system's one OCC-guarded write, per §2.7. The amendment request must carry `expected_contract_version` equal to the contract's current `version`; a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412). The request may then supply any of `committed_mbf`, `contract_price_per_mbf_cents`, or `end_date`; the provided fields replace the current values, with one fiscal guard: an amended `committed_mbf` must remain at least the contract's current `reserved_mbf`, since volume already promised to orders cannot be amended away — a violation draws `ERR_CONTRACT_VOLUME_EXCEEDED` (HTTP 422). A successful amendment increments `version`, which is exactly the mechanism that makes the next stale writer detectable.

A `SalesRep` places an order with the `customer_name`, `species`, `grade`, `length_spec`, and `volume_mbf`, and optionally a `contract_id`. The presence of `contract_id` selects the pricing mode: with it, `pricing_mode` is `CONTRACT`; without it, `SPOT`. Placement pins the commercial terms immediately — `unit_price_cents` is fixed at placement and never re-quoted afterward — and the new order enters at `PLACED` with `allocated_mbf` and `total_cents` at zero, returning 201.

For a contract order, three checks bind at placement. The referenced contract must be `ACTIVE`, otherwise `ERR_CONTRACT_NOT_ACTIVE` (HTTP 409) — orders against `DRAFT`, `CLOSED`, or `EXPIRED` contracts are all refused here, and the same refusal applies when allocation would touch a non-active contract. The order's `species` and `grade` must equal the contract's, otherwise `ERR_PRODUCT_MISMATCH`. And the order's `volume_mbf` must not exceed the contract's `remaining_mbf`, otherwise `ERR_CONTRACT_VOLUME_EXCEEDED`. A contract's `reserved_mbf` is the sum of `volume_mbf` over its orders in `PLACED` or `ALLOCATED`, and its `remaining_mbf` is `committed_mbf` minus `reserved_mbf`; placing the order immediately adds its `volume_mbf` to that reservation. The pinned `unit_price_cents` is the contract's `contract_price_per_mbf_cents`.

For a spot order, the server quotes from the price list. The eligible rows are those matching the order's `species` and `grade` whose `effective_from` has been reached by the current logical time; among them the row with the latest `effective_from` wins, ties broken by the latest `created_at`. An empty pool — no effective row for that species and grade — rejects the placement with `ERR_NO_PRICE_LIST` (HTTP 422). The quote then applies a length multiplier to the row's base price: 0.96 for `RL`, 0.95 for length 8, 0.97 for length 10, 1.00 for length 12, and 1.08 for length 16. A volume discount follows: 5 percent off when `volume_mbf` is at least 50, otherwise 2 percent off when it is at least 10, otherwise no discount. The pinned `unit_price_cents` is computed in two rounding steps, and the order of the steps is part of the contract: first multiply the base price by the length multiplier and round half-up to whole cents, then multiply that rounded figure by one minus the discount and round half-up to whole cents again. Skipping the intermediate rounding produces observably different prices and is a rejected reading.

### 3.8. Allocation, Shipment, and Byproduct Sales

Allocation turns a placed order into held inventory. A `SalesRep` allocates an order that is `PLACED`. The eligible pool is every package mill-wide that is `STAMPED`, whose `species` equals the order's `species`, whose `stamped_grade` equals the order's `grade`, that is not already holding another order (its `sales_order_id` is null), and whose length satisfies the order's `length_spec` — any length at all when the spec is `RL`, or an exact `length_ft` match otherwise. Before anything moves, the pool's total `dry_mbf` must be at least the order's `volume_mbf`; a shortfall rejects the allocation with `ERR_INSUFFICIENT_STAMPED_VOLUME` (HTTP 422).

The selector is a first-in-first-out walk. Eligible packages are ranked by `stamped_at` ascending, ties broken by `created_at` ascending — the oldest-stamped wood ships first. The walk accumulates whole packages in ranked order until the cumulative `dry_mbf` reaches or exceeds `volume_mbf`, and it stops immediately after the package that crosses the threshold: that crossing package is included whole, so an order over-allocates by at most one package and never splits a package. Each selected package flips from `STAMPED` to `ALLOCATED`, has its `sales_order_id` set to the order, and increments its `version`. The order then computes `allocated_mbf` as the sum of the selected packages' `dry_mbf`, and `total_cents` with a pinned two-step rule: for each selected package, multiply its `dry_mbf` by the order's `unit_price_cents` and round half-up to whole cents — per package first — then sum those per-package amounts. Rounding the sum of volumes once, instead of rounding each package's extension, is a different and rejected reading. The order moves to `ALLOCATED` and its `version` increments.

Shipping releases the wood and settles the contract math. A `SalesRep` ships an order that is `ALLOCATED`. Every allocated package flips from `ALLOCATED` to `SHIPPED` — allocation guarantees stamped origin, so only grade-stamped lumber ever ships — and each flip increments the package's `version`. Each flip also re-derives the holding contract's `shipped_mbf`: the sum of `dry_mbf` over all `SHIPPED` packages whose `sales_order_id` resolves to an order of that contract. When a recomputed `shipped_mbf` reaches or exceeds the contract's `committed_mbf` while the contract is `ACTIVE`, the contract auto-transitions from `ACTIVE` to `CLOSED` and its `version` increments — no human action required. The shipped order's own `volume_mbf` is released from the contract's `reserved_mbf`, since the order is no longer `PLACED` or `ALLOCATED`; the order moves to `SHIPPED` and its `version` increments.

Cancellation unwinds. Cancelling a `PLACED` order simply releases its `volume_mbf` from the contract's `reserved_mbf` when it names one, moves the order to `CANCELLED`, and increments `version`. Cancelling an `ALLOCATED` order additionally releases the held wood: every allocated package flips back from `ALLOCATED` to `STAMPED` with its `sales_order_id` cleared and its `version` incremented, the order's `allocated_mbf` and `total_cents` reset to zero, the contract reservation releases, and the order lands at `CANCELLED`. Shipping or cancelling an order in any other state is `ERR_INVALID_STATE`.

Sawing byproducts sell on their own ledger. A `SalesRep` records a byproduct sale with the `product` (`CHIP`, `SAWDUST`, or `BARK`), the `volume_tons` sold, the `price_per_ton_cents`, and the `buyer_name`; the sale's `total_cents` is the product of `volume_tons` and `price_per_ton_cents`, rounded half-up to whole cents, and the sale returns 201. The sale is validated against on-hand inventory: per product, produced tons are the sum of the corresponding tonnage across all `COMPLETED` sawing runs, sold tons are the sum of `volume_tons` across all sales of that product — sales are final and carry no status — and on-hand tons are produced minus sold. A sale whose `volume_tons` exceeds the product's on-hand tons is rejected with `ERR_INSUFFICIENT_BYPRODUCT` (HTTP 422). The byproduct inventory read endpoint reports exactly these per-product produced, sold, and on-hand figures, with totals carried at 3 decimal places rounded half-up, and it is a computed read — no inventory rows are stored.

### 3.9. Ops Checkpoints: Contract Expiry and Degrade Refresh

The ops checkpoint is the mill's periodic sweep, invoked by a `MillManager`, and it does two jobs in one call. First, contract expiry: every contract still `ACTIVE` whose `end_date` falls before the current logical date flips to `EXPIRED` and increments its `version`. Expiry is deliberately shallow — it touches nothing already placed or allocated against the contract; existing orders ride out their own lifecycle, and only new order placements are refused by the `ERR_CONTRACT_NOT_ACTIVE` guard at the pricing rail. Second, degrade refresh: every `DECKED` log load has its `days_in_deck` and `degrade_pct` recomputed from the logical clock per the accrual rule of §3.2, so deck aging becomes visible mill-wide at checkpoint cadence rather than continuously. The checkpoint responds with the list of contracts it expired and the list of loads whose degrade it refreshed — the `expired_contract_ids` and `degraded_load_ids` arrays — and returns 200.

Reading the mill is unrestricted by specialty: every role may list and fetch every resource. Log loads list with optional `status`, `species`, and `sawing_run_id` filters; lumber packages list with optional `status`, `species`, `grade`, `sales_order_id`, `kiln_charge_id`, and `sawing_run_id` filters; sales orders list with optional `contract_id` and `status` filters; and all lists paginate per §2.3. Single-resource fetches return the full current record, computed fields included.

## 4. Endpoint Definitions

All endpoints are mounted under `/api`. Endpoints that create a new resource respond with 201; endpoints that modify an existing resource or perform an action respond with 200. Readers reconstruct full request and response bodies from the workflows in §3 — this table is the index, not the specification.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /api/log-loads | Receive a log load (status `RECEIVED`) | Scaler |
| GET | /api/log-loads | List log loads with filters | Scaler, Sawyer, KilnOperator, Grader, SalesRep, MillManager |
| GET | /api/log-loads/{id} | Get one log load | Scaler, Sawyer, KilnOperator, Grader, SalesRep, MillManager |
| POST | /api/log-loads/{id}/scale | Scale a `RECEIVED` load (`RECEIVED` → `SCALED`) | Scaler |
| POST | /api/log-loads/{id}/dispute | Raise a scale dispute (`SCALED` → `DISPUTED`) | Scaler |
| POST | /api/log-loads/{id}/resolve-scale | Resolve a scale dispute with adjusted figures (`DISPUTED` → `SCALED`) | MillManager |
| POST | /api/log-loads/{id}/deck | Move a `SCALED` load onto the log deck (`SCALED` → `DECKED`) | Scaler |
| POST | /api/log-loads/{id}/undeck | Pull a `DECKED`, unattached load back to `SCALED` (compensates deck) | Scaler |
| POST | /api/sawing-runs | Plan a sawing run; attaches `DECKED` loads (sets their `sawing_run_id`) | Sawyer |
| GET | /api/sawing-runs/{id} | Get one sawing run | Scaler, Sawyer, KilnOperator, Grader, SalesRep, MillManager |
| POST | /api/sawing-runs/{id}/complete | Complete a run: record produced packages and byproduct tons (`PLANNED` → `COMPLETED`) | Sawyer |
| POST | /api/kiln-charges | Schedule a kiln charge; charged packages `GREEN` → `IN_KILN` | KilnOperator |
| GET | /api/kiln-charges/{id} | Get one kiln charge | Scaler, Sawyer, KilnOperator, Grader, SalesRep, MillManager |
| POST | /api/kiln-charges/{id}/start | Start a scheduled charge (`SCHEDULED` → `IN_PROGRESS`); not before `scheduled_start` | KilnOperator |
| POST | /api/kiln-charges/{id}/complete | Complete a charge with per-package moisture/tally readings (`IN_PROGRESS` → `COMPLETED`) | KilnOperator |
| POST | /api/kiln-charges/{id}/abort | Abort a charge (`SCHEDULED`/`IN_PROGRESS` → `ABORTED`); packages back to `GREEN` | KilnOperator |
| GET | /api/lumber-packages | List lumber packages with filters | Scaler, Sawyer, KilnOperator, Grader, SalesRep, MillManager |
| GET | /api/lumber-packages/{id} | Get one lumber package | Scaler, Sawyer, KilnOperator, Grader, SalesRep, MillManager |
| POST | /api/lumber-packages/{id}/grade-inspections | Record a grade inspection (`STAMP` from `DRY`; `RESTAMP` from `STAMPED`/`ALLOCATED`) | Grader |
| GET | /api/lumber-packages/{id}/grade-inspections | List inspection history of a package (append-only) | Scaler, Sawyer, KilnOperator, Grader, SalesRep, MillManager |
| POST | /api/price-lists | Publish an immutable spot price row for (species, grade) effective from a timestamp | MillManager |
| POST | /api/sales-contracts | Create a sales contract (status `DRAFT`) | MillManager |
| GET | /api/sales-contracts/{id} | Get one sales contract | Scaler, Sawyer, KilnOperator, Grader, SalesRep, MillManager |
| POST | /api/sales-contracts/{id}/activate | Activate a draft contract (`DRAFT` → `ACTIVE`) | MillManager |
| PUT | /api/sales-contracts/{id} | Amend a `DRAFT` or `ACTIVE` contract; OCC-guarded via `expected_contract_version` | MillManager |
| POST | /api/sales-orders | Place an order; pins `pricing_mode` and `unit_price_cents` (`CONTRACT` or `SPOT`) | SalesRep |
| GET | /api/sales-orders | List sales orders with filters | Scaler, Sawyer, KilnOperator, Grader, SalesRep, MillManager |
| GET | /api/sales-orders/{id} | Get one sales order | Scaler, Sawyer, KilnOperator, Grader, SalesRep, MillManager |
| POST | /api/sales-orders/{id}/allocate | Allocate stamped packages to a `PLACED` order (FIFO by `stamped_at`, whole-package fill) | SalesRep |
| POST | /api/sales-orders/{id}/ship | Ship an `ALLOCATED` order; cascades to packages and contract | SalesRep |
| POST | /api/sales-orders/{id}/cancel | Cancel a `PLACED` or `ALLOCATED` order; releases allocated packages | SalesRep |
| POST | /api/byproduct-sales | Record a byproduct (chip/sawdust/bark) sale; validates on-hand | SalesRep |
| GET | /api/byproduct-inventory | Computed read: per-product produced/sold/on-hand tons | Scaler, Sawyer, KilnOperator, Grader, SalesRep, MillManager |
| POST | /api/ops/runs | Ops checkpoint: expires `ACTIVE` contracts past `end_date`; refreshes degrade of `DECKED` loads | MillManager |
| POST | /api/_clock/set_current_utc | Set the logical clock (test-driving) | MillManager |

## 5. Error Code Catalogue

Trigger conditions for each error live in the workflow narratives of §2 and §3; this table is the index of identifiers to HTTP statuses.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_SCHEDULE_IN_PAST | 422 |
| ERR_END_BEFORE_START | 422 |
| ERR_KILN_OVERLAP | 409 |
| ERR_SAW_LINE_BOOKED | 409 |
| ERR_DECK_CAPACITY_EXCEEDED | 422 |
| ERR_DUPLICATE_LOAD_IN_RUN | 422 |
| ERR_CONTRACT_NOT_ACTIVE | 409 |
| ERR_CONTRACT_VOLUME_EXCEEDED | 422 |
| ERR_NO_PRICE_LIST | 422 |
| ERR_INSUFFICIENT_STAMPED_VOLUME | 422 |
| ERR_INSUFFICIENT_BYPRODUCT | 422 |
| ERR_PRODUCT_MISMATCH | 422 |
