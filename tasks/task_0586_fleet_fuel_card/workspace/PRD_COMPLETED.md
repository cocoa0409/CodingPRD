# Fleet Fuel Card & Telematics API — Product Requirements Document

## 1. Introduction

This document specifies the Fleet Fuel Card & Telematics platform, a WEX/Fleetcor-style back office that governs the full life of a commercial fueling program: issuing cards and binding them to vehicles and drivers, enforcing purchase controls at the pump, holding and settling credit against a revolving account ledger, accruing network rebates, monitoring fuel economy and telematics faults, and producing quarterly fuel-tax (IFTA) filings and general-ledger expense exports.

The platform serves five very different operators. A platform administrator stands up fleet accounts and runs regulatory reporting; a fleet manager owns the vehicles, drivers, cards, and assignments of a single account; a fuel-network merchant terminal authorizes and settles purchases; a fraud analyst works the alert queue; and a telematics gateway streams vehicle fault codes that can force a truck out of service. Because money, safety, and compliance all intersect on a single transaction, the system is built around two ideas that recur throughout this document: purchases carry two independent status axes — one for money movement and one for fraud review — and many operations produce cascading side effects that ripple across cards, assignments, transactions, and vehicles.

All monetary state is tracked in integer cents, all time is expressed in UTC against a server-controlled logical clock, and every mutation is reconciled immediately so that ledgers, holds, rebates, and derived economy figures are always internally consistent.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contracts, envelope formats, and cross-cutting principles that apply to every endpoint.

### 2.1. Users and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming its operational capacity. If either header is missing, or `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (401). If the role is recognized but not permitted to invoke the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (403).

The system recognizes exactly five roles: `ProgramAdmin`, `FleetManager`, `Merchant`, `FraudAnalyst`, and `TelematicsGateway`.

- `ProgramAdmin` is the platform operator. It creates fleet accounts, generates and files IFTA reports, drives the logical clock, and may read every resource in the system.
- `FleetManager` owns the vehicles, drivers, fuel cards, and card assignments belonging to a single fleet account.
- `Merchant` is the fuel-network point-of-sale terminal; it authorizes, captures, settles, and voids purchases.
- `FraudAnalyst` works the fraud-alert queue.
- `TelematicsGateway` ingests vehicle telemetry, reporting faults and maintenance progress.

Identity binding differs by role. When `X-User-Role` is `FleetManager`, `X-User-ID` is the `id` of the acting `FleetAccount`; ownership checks on any resource that belongs to a fleet — directly through its `fleet_account_id`, or transitively through the card, vehicle, or driver it references — compare that owning account to `X-User-ID`. A `FleetManager` acting on a resource outside its own account is rejected with `ERR_FORBIDDEN_FLEET` (403). When `X-User-Role` is `ProgramAdmin`, `Merchant`, `FraudAnalyst`, or `TelematicsGateway`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`. On list endpoints the same rule is applied as an implicit scope rather than as an error: a `FleetManager`'s listings are silently narrowed to its own account's resources, except that on the listings that expose an explicit `fleet_account_id` filter (vehicles, drivers, fuel cards, and IFTA reports) naming another account in that filter is rejected with `ERR_FORBIDDEN_FLEET`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Out-of-range or non-integer values are rejected rather than clamped: a `limit` below 1 or above 100, a negative `offset`, or a non-integer value for either is rejected with `ERR_VALIDATION` (400).

Unless a specific endpoint states otherwise, list results are sorted by `created_at` in ascending order, with ties broken by creation sequence so that ordering is stable even when several resources share a `created_at` (the logical clock makes that common). Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the envelope's `meta` object; `total_count` is the size of the filtered set before paging, and `has_more` is true when `offset` plus the number of returned items is still less than `total_count`.

### 2.4. The Logical Clock and Temporal Fields

The platform does not read wall-clock time. Instead it maintains a server logical clock that a `ProgramAdmin` sets by submitting a `to_iso8601` instant; the clock-set capability returns the new value as `now`, echoing back verbatim the exact ISO string that was submitted. Before any call is made, the clock defaults to `2026-05-01T00:00:00Z`, and it never falls back to wall-clock time. Every timestamp the system stamps itself — a transaction's `purchased_at`, an assignment's auto-filled `effective_to`, and a report's `filed_at` — is read from this logical clock at the moment of the action, and each of these three is likewise rendered as the exact ISO string the clock was last set with, character for character, rather than reformatted. The `created_at` and `updated_at` audit fields of §2.5 are the exception: they render the logical instant in the canonical three-fractional-digit form. (Only the envelope's `api_request_timestamp` is drawn from real wall-clock time.)

All datetime fields are ISO 8601 UTC. Where a field describes an interval, the interval is half-open unless explicitly stated otherwise: the start is inclusive and the end is exclusive.

### 2.5. Common Resource Properties and Optimistic Concurrency

Every primary resource in this system — `FleetAccount`, `Vehicle`, `Driver`, `FuelCard`, `CardAssignment`, `Transaction`, `FraudAlert`, `TelematicsFault`, and `IftaReport` — carries the same system-managed fields. `id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits set at creation. `updated_at` is an ISO 8601 UTC timestamp refreshed on every mutation. `version` is an integer that starts at 1 on creation and increments by one on every mutation of the resource; it exists so clients can detect concurrent modification. All nine resource types carry all four of these fields.

Optimistic concurrency control is enforced on exactly one write path: creating a card assignment. A create-assignment request must include `expected_card_version`, carrying the client's last observed `version` of the target `FuelCard`. Because creating a new assignment supersedes the card's prior active assignment and advances the card's `version`, a second create carrying a now-stale `expected_card_version` would silently clobber an assignment the client never saw. Therefore, if `expected_card_version` does not equal the card's current `version`, the create is rejected with `ERR_STALE_CARD_VERSION` (412). No other endpoint accepts or requires a version field.

### 2.6. Monetary Values, Cents, and Rounding

All money is stored and computed in integer cents; there are no fractional cents anywhere in the system. Credit limits, holds, settled spend, rebate accruals, and tax figures are exact integers.

Where a computation produces a non-integer intermediate — a charge in cents, a per-gallon rebate applied to fractional gallons, a per-jurisdiction tax — the result is rounded half up to a whole number of cents. Fuel economy figures are rounded half up to one decimal place, and taxable-gallons figures are rounded half up to three decimal places. When a total is formed from several rounded parts, each part is rounded first and the rounded parts are then summed; the system never sums raw quantities and rounds once at the end.

### 2.7. The Account Credit Ledger

Each `FleetAccount` carries a revolving credit ceiling, `credit_limit_cents`, that backs every card on the account. Three derived figures reconcile against it on every posting transition of any of the account's transactions. `outstanding_holds_cents` is the sum of `gross_amount_cents` over the account's transactions whose `posting_status` is `AUTHORIZED` or `CAPTURED`. `settled_spend_cents` is the sum of `gross_amount_cents` over transactions whose `posting_status` is `SETTLED`. `available_credit_cents` is `credit_limit_cents` minus `outstanding_holds_cents` minus `settled_spend_cents`. These figures obey a conserved invariant at all times: `available_credit_cents` plus `outstanding_holds_cents` plus `settled_spend_cents` always equals `credit_limit_cents`. They are not stored balances that get incremented and decremented; they are pure reconciliations, recomputed from the account's transaction set every time an account is read, so the invariant holds structurally and every cascade in §2.8 is automatically reflected without a separate posting step. `rebate_accrual_cents` is derived the same way: it is the sum, over the account's transactions, of `provisional_rebate_cents` for each `CAPTURED` transaction and `final_rebate_cents` for each `SETTLED` one, with `AUTHORIZED` and `VOIDED` transactions contributing nothing.

The account also carries `rebate_accrual_cents`, a running rebate liability described in §3.5. An account additionally has a `company_name`, a `base_jurisdiction` (its home two-letter IFTA state code), a `status` that is one of `ACTIVE`, `SUSPENDED`, or `CLOSED` (defaulting to `ACTIVE`), and a `rebate_tiers` schedule (§3.5). The account `status` is descriptive bookkeeping only: it is never re-derived by the system and it gates nothing — a card on a `SUSPENDED` or `CLOSED` account still authorizes purchases normally, subject only to the controls of §3.4.

### 2.8. Cascading Consistency and Automatic State Propagation

Several operations mutate more than the resource they target. Each such cascade independently mutates every affected resource — refreshing its `updated_at` and, where the resource carries one, incrementing its `version` — exactly as if the change had been requested directly.

The principal cascades are: suspending a card voids that card's open transactions, and voiding a captured transaction reverses its accrued rebate and releases its hold; confirming a fraud alert suspends the underlying card, triggering that same void-and-reverse chain; taking a vehicle out of service (or retiring it, or cancelling a card) ends the affected active card assignments; and a critical telematics fault schedules maintenance and takes its vehicle out of service. These chains are specified in full in §3; the governing principle is that the system reaches a consistent state in a single logical operation rather than leaving dangling holds, orphaned assignments, or stale rebate liability.

### 2.9. Request Validation Order and Resource Resolution

When a request references resources by path segment or by foreign-key body field, each referenced resource must exist; existence is checked left to right, and the first missing reference produces the corresponding not-found error (`ERR_FLEET_ACCOUNT_NOT_FOUND`, `ERR_VEHICLE_NOT_FOUND`, `ERR_DRIVER_NOT_FOUND`, `ERR_CARD_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_TRANSACTION_NOT_FOUND`, `ERR_ALERT_NOT_FOUND`, `ERR_FAULT_NOT_FOUND`, or `ERR_REPORT_NOT_FOUND`, all 404). Malformed input — a missing required field, a value of the wrong type, an out-of-range number, or an unrecognized enum value — is rejected with `ERR_VALIDATION` (400); body and query shape are validated after authentication and authorization but before any existence lookup, so a syntactically bad request naming a nonexistent resource yields `ERR_VALIDATION`, not a 404.

Validations are evaluated in a fixed precedence so that a lower-ranked failure can never be masked by a higher-ranked one. The order is:

1. **Authentication** — headers present and role recognized, else `ERR_UNAUTHENTICATED` (401).
2. **Authorization** — the role may invoke this operation, else `ERR_UNAUTHORIZED` (403).
3. **Existence** — every path and foreign-key reference resolves, checked left to right, else the matching not-found error (404).
4. **Fleet ownership** — for a `FleetManager`, the target's owning `fleet_account_id` equals `X-User-ID`, else `ERR_FORBIDDEN_FLEET` (403).
5. **Transition state** — the target is in a state that permits the requested transition, else the applicable state error: `ERR_CARD_NOT_ACTIVE`, `ERR_INVALID_CARD_STATE`, `ERR_INVALID_TXN_STATE`, `ERR_INVALID_ALERT_STATE`, `ERR_INVALID_FAULT_STATE`, or `ERR_INVALID_REPORT_STATE` (all 409).
6. **Active assignment** — on authorize, an `ACTIVE` card assignment for the card covers `purchased_at` (resolving the transaction's vehicle and driver), else `ERR_NO_ACTIVE_ASSIGNMENT` (409). On the authorize path this check necessarily precedes the vehicle-status check below, because the vehicle is only knowable once the assignment has resolved: a card with no covering assignment yields `ERR_NO_ACTIVE_ASSIGNMENT` even if some vehicle of the fleet is out of service.
7. **Vehicle operational status** — on authorize, the vehicle resolved from the assignment in step 6 is neither `OUT_OF_SERVICE` nor `RETIRED`; on assignment create, the named vehicle's `status` is `ACTIVE` (this check runs in its listed position, before the interval checks below); on vehicle retire, the target vehicle is not already `RETIRED`; else `ERR_VEHICLE_OUT_OF_SERVICE` (409).
8. **Product control** — on authorize, the purchased `product` is in the card's `allowed_products`, else `ERR_PRODUCT_NOT_ALLOWED` (422).
9. **Hours control** — on authorize, the UTC hour of `purchased_at` falls within the card's permitted window, else `ERR_OUTSIDE_ALLOWED_HOURS` (422).
10. **Per-transaction gallon control** — on authorize, `gallons` does not exceed the card's `per_txn_gallon_limit`, else `ERR_GALLON_LIMIT_EXCEEDED` (422).
11. **Interval well-formedness** — on assignment create and on fault create, the relevant interval is well-formed (§3.3, §3.7), else `ERR_INVALID_INTERVAL` (422).
12. **Driver double-booking** — on assignment create, the new interval does not overlap another active assignment of the same driver, else `ERR_DRIVER_DOUBLE_BOOKED` (409).
13. **Maintenance overlap** — on critical fault create, the buffered maintenance window does not collide with another non-cleared window on the same vehicle, else `ERR_MAINTENANCE_OVERLAP` (409).
14. **Maintenance window presence** — a critical fault supplies both window bounds, else `ERR_MISSING_MAINTENANCE_WINDOW` (422).
15. **Daily spend control** — on authorize, the card's same-UTC-day held-plus-settled spend plus this charge does not exceed `daily_dollar_limit_cents`, else `ERR_DAILY_LIMIT_EXCEEDED` (402).
16. **Account credit** — on authorize, the account's `available_credit_cents` is at least this charge, else `ERR_CREDIT_EXCEEDED` (402).
17. **Period settlement** — on IFTA file, every in-period transaction is `SETTLED`, else `ERR_PERIOD_NOT_SETTLED` (409).
18. **Card version (OCC)** — on assignment create, `expected_card_version` equals the card's `version`, else `ERR_STALE_CARD_VERSION` (412).

Only the checks relevant to a given operation apply; the numbering above is the relative precedence among those that do.

## 3. Business Logic & Workflows

### 3.1. Fleet Accounts, Vehicles, and Drivers

A `ProgramAdmin` stands up a fleet by creating a `FleetAccount`, supplying its `company_name`, `base_jurisdiction`, and `credit_limit_cents` (which must be zero or greater), optionally its `rebate_tiers` and its `status`. The derived ledger figures — `outstanding_holds_cents`, `settled_spend_cents`, `available_credit_cents`, and `rebate_accrual_cents` — begin at their natural starting values (`available_credit_cents` therefore starts equal to `credit_limit_cents`, the other three at 0) and thereafter move only through the reconciliations described in §2.7 and §3.5. Anyone may retrieve an account, and the account representation itself always carries those four ledger figures alongside `company_name`, `status`, `base_jurisdiction`, `credit_limit_cents`, and `rebate_tiers`; the account's GL/expense-export view is a separate, non-resource payload that returns only the ledger snapshot (`available_credit_cents`, `outstanding_holds_cents`, `settled_spend_cents`, `rebate_accrual_cents`) alongside `gl_lines`, an array of per-transaction expense lines for accounting export — one line per transaction of the account regardless of posting status, ordered by the transaction's `created_at` ascending, each carrying `transaction_id`, `card_id`, `vehicle_id`, `driver_id`, `product`, `gallons`, `unit_price_cents`, `jurisdiction`, `gross_amount_cents`, `hold_amount_cents`, `rebate_cents`, `posting_status`, `review_status`, and `purchased_at`, where `rebate_cents` is the transaction's `final_rebate_cents` when it is `SETTLED`, its `provisional_rebate_cents` when it is `CAPTURED`, and 0 otherwise.

A `FleetManager` onboards a `Vehicle` under its own account. A vehicle is created with its owning `fleet_account_id`, a `plate`, a `tank_capacity_gallons` (strictly greater than zero, later used by the over-tank fraud check), an acceptable fuel-economy band expressed as `expected_mpg_min` (strictly greater than zero) and `expected_mpg_max` (which must be at least `expected_mpg_min`), a `home_jurisdiction`, and optionally a `starting_odometer` (zero or greater, defaulting to 0). A vehicle's `status` is system-managed, one of `ACTIVE`, `OUT_OF_SERVICE`, or `RETIRED`, starting `ACTIVE`. Its `current_odometer` is derived: it is the `odometer` of the latest `AUTHORIZED`-or-later transaction on the vehicle — "latest" by `purchased_at` ascending, ties broken by `created_at` ascending and then by creation sequence, and counting every such transaction including `VOIDED` ones, since an odometer reading is a physical fact that a money-side reversal does not undo — or the `starting_odometer` if the vehicle has no such transaction yet. A `FleetManager` may retire an `ACTIVE` or `OUT_OF_SERVICE` vehicle, moving it to the terminal `RETIRED` state; retiring a vehicle ends every `ACTIVE` card assignment bound to it (§3.3). Retiring a vehicle that is already `RETIRED` is rejected with `ERR_VEHICLE_OUT_OF_SERVICE` (409) — the same error the vehicle-status check raises elsewhere, not a card/txn-style invalid-state error.

Drivers are likewise created by a `FleetManager` under a `fleet_account_id`, with a `full_name`, a `pin` of exactly four digits entered at the pump, and an optional `status` of `ACTIVE` or `INACTIVE` (defaulting to `ACTIVE`). Like the account `status`, a driver's `status` is descriptive only and gates nothing: an `INACTIVE` driver can still be assigned a card and can still be resolved as the driver of an authorized purchase. Vehicles and drivers can both be listed and filtered by owning account and by status.

### 3.2. Fuel Cards: Issuance, Purchase Controls, and Lifecycle

A `FleetManager` issues a `FuelCard` against its account, supplying `fleet_account_id`, the display-only `last4`, and the card's purchase controls: `allowed_products` (a subset of `UNLEADED`, `PREMIUM`, `DIESEL`, and `DEF`), a `daily_dollar_limit_cents` (zero or greater) capping the card's held-plus-settled spend per UTC calendar day, a `per_txn_gallon_limit` (strictly greater than zero) capping a single fill, and an optional purchase-hour window. That window is `allowed_start_hour` (inclusive, UTC hour 0–23, defaulting to 0) through `allowed_end_hour` (exclusive, UTC hour 1–24, defaulting to 24), where `allowed_start_hour` must be strictly less than `allowed_end_hour` and `allowed_end_hour` at most 24; the permitted window is the half-open range from `allowed_start_hour` up to but not including `allowed_end_hour`. These controls are consumed at authorization time in §3.4.

A card's `status` is system-managed and moves through `ISSUED`, `ACTIVE`, `SUSPENDED`, and the terminal `CANCELLED`, starting at `ISSUED`. A `FleetManager` activates a card that is currently `ISSUED` or `SUSPENDED`, moving it to `ACTIVE` and incrementing its `version`; activating a card that is `SUSPENDED` is a reinstatement. Activating a card that is neither `ISSUED` nor `SUSPENDED` is rejected with `ERR_INVALID_CARD_STATE`.

A `FleetManager` suspends an `ACTIVE` card, moving it to `SUSPENDED` and incrementing its `version`. Suspension is not merely a flag: every transaction of this card whose `posting_status` is `AUTHORIZED` or `CAPTURED` is transitioned to `VOIDED`, which in turn releases each transaction's hold and reverses any rebate that transaction had accrued (§3.5). Suspending a card that is not `ACTIVE` is rejected with `ERR_INVALID_CARD_STATE`.

A `FleetManager` cancels a card from any non-`CANCELLED` state, moving it to the terminal `CANCELLED` and incrementing its `version`; cancellation ends every `ACTIVE` card assignment on the card (moving each to `ENDED`). Cancelling an already-`CANCELLED` card is rejected with `ERR_INVALID_CARD_STATE`. Cards can be fetched (the fetch exposes the card's `version` for OCC) and listed by account and status.

### 3.3. Card Assignments: Binding a Card to a Vehicle and Driver

A `CardAssignment` binds one card to one vehicle and one driver for a time interval, and it is the junction that lets an authorization resolve who and what a purchase belongs to. A `FleetManager` creates an assignment by supplying `card_id`, `vehicle_id`, `driver_id`, an `effective_from` instant, the OCC guard `expected_card_version`, and optionally an `effective_to` instant. The interval is half-open: `effective_from` inclusive to `effective_to` exclusive, and a null `effective_to` means open-ended. An assignment's `status` is system-managed — `ACTIVE`, `SUPERSEDED`, or `ENDED` — starting `ACTIVE`.

Creating an assignment carries several guards. The named vehicle must be `ACTIVE`, else `ERR_VEHICLE_OUT_OF_SERVICE`. The interval must be well-formed — either `effective_to` is null, or `effective_from` is strictly earlier than `effective_to` — else `ERR_INVALID_INTERVAL`. The new interval must not overlap any other `ACTIVE` assignment of the same `driver_id`; two intervals that merely touch at an endpoint do not overlap (the half-open convention), but any genuine overlap is rejected with `ERR_DRIVER_DOUBLE_BOOKED`. Finally, `expected_card_version` must equal the card's current `version`, else `ERR_STALE_CARD_VERSION` (412), as described in §2.5.

A successful create has two side effects: it increments the card's `version` by one, and it supersedes the card's prior `ACTIVE` assignment — that one assignment, and only that one, moves from `ACTIVE` to `SUPERSEDED`. Assignments of other cards are untouched. Because the create advances the card's `version`, a competing create that still carries the pre-supersession `expected_card_version` will be refused: the first writer already superseded the prior assignment and bumped the card, so the second client's observed card version is stale.

A `FleetManager` may end an `ACTIVE` assignment directly, moving it to `ENDED`; if its `effective_to` was null, ending it stamps `effective_to` with the current logical-clock value (the verbatim clock string, per §2.4). Ending an assignment that is not `ACTIVE` — one already `ENDED`, or one that has been `SUPERSEDED` — is rejected with `ERR_INVALID_CARD_STATE` (409); there is no assignment-specific state error in the catalogue, so the card-state error stands in for one. Assignments also end automatically as a cascade side effect when their vehicle goes `OUT_OF_SERVICE` or is retired, or when their card is cancelled — the same `ACTIVE → ENDED` transition, with the same null-`effective_to` backfill. Assignments can be listed and filtered by card, vehicle, driver, and status.

### 3.4. Purchasing Fuel: Authorization and Purchase Controls

A `Merchant` terminal authorizes a purchase by presenting `card_id`, `product`, `gallons` (strictly greater than zero), `unit_price_cents` (strictly greater than zero), `odometer` (zero or greater), and the two-letter `jurisdiction` where the pump sits. Authorization is where the card's purchase controls, the account's credit, the fuel-economy snapshot, and the fraud rules all execute.

Authorization proceeds through the precedence of §2.9. The card must be `ACTIVE`, else `ERR_CARD_NOT_ACTIVE`. The system stamps `purchased_at` from the logical clock and resolves the card's `ACTIVE` assignment whose interval covers `purchased_at`, thereby filling the transaction's computed `vehicle_id` and `driver_id`; with no such assignment the purchase is rejected with `ERR_NO_ACTIVE_ASSIGNMENT`. The resolved vehicle must not be `OUT_OF_SERVICE` or `RETIRED`, else `ERR_VEHICLE_OUT_OF_SERVICE`. The `product` must appear in the card's `allowed_products`, else `ERR_PRODUCT_NOT_ALLOWED`. The UTC hour of `purchased_at` must fall in the card's permitted window — at least `allowed_start_hour` and strictly less than `allowed_end_hour` — else `ERR_OUTSIDE_ALLOWED_HOURS`. The `gallons` must not exceed `per_txn_gallon_limit`; exactly equal is allowed, strictly greater is rejected with `ERR_GALLON_LIMIT_EXCEEDED`.

The charge, `gross_amount_cents`, is `gallons` multiplied by `unit_price_cents`, rounded half up to whole cents. Two fiscal gates then apply, in this order. First, the card's daily control: the sum of this card's held-and-settled spend within the same UTC calendar day as `purchased_at`, plus this `gross_amount_cents`, must not exceed the card's `daily_dollar_limit_cents`, else `ERR_DAILY_LIMIT_EXCEEDED` (402). Second, the account's credit: `available_credit_cents` must be at least this `gross_amount_cents`, else `ERR_CREDIT_EXCEEDED` (402).

On success a `Transaction` is created with `posting_status` `AUTHORIZED` and `review_status` `CLEAN`. A hold equal to the charge is placed: `hold_amount_cents` equals `gross_amount_cents` while the transaction is `AUTHORIZED` or `CAPTURED`, and becomes 0 once the transaction is `SETTLED` or `VOIDED`. The vehicle's derived `current_odometer` advances to this transaction's `odometer`. The system also computes the fuel-economy snapshot: `segment_miles` is this `odometer` minus the previous transaction's `odometer` on the same vehicle (or the vehicle's `starting_odometer` if this is the vehicle's first transaction), where "previous" is by `purchased_at` ascending, ties broken by `created_at` ascending and then by creation sequence, and where every prior transaction of the vehicle counts as a candidate predecessor regardless of posting status — `VOIDED` ones included, exactly as for `current_odometer` in §3.1. `segment_miles` is stored as computed and is not clamped: a purchase whose `odometer` is below its predecessor's yields a negative `segment_miles` (and correspondingly negative economy) rather than an error. The segment economy `mpg_snapshot` is `segment_miles` divided by `gallons`, rounded half up to one decimal place. The boolean `mpg_exception` is true when `mpg_snapshot` is below the vehicle's `expected_mpg_min` or above its `expected_mpg_max`.

Finally the fraud engine runs. A `FuelCard`'s tank-fill exposure is checked against the resolved vehicle: when a fill's `gallons` exceeds the vehicle's `tank_capacity_gallons`, the transaction still authorizes but its `review_status` is set to `FLAGGED` and a `FraudAlert` is created in status `OPEN` with a null `resolution_note`, recording the flagged `transaction_id`, the `card_id`, and a `rule_code` of `OVER_TANK_FILL`. The alert's `rule_code` is drawn from the set `OVER_TANK_FILL`, `OUTSIDE_HOURS`, and `PRODUCT_MISMATCH`; in practice `OVER_TANK_FILL` is the only member the engine can ever emit, because the other two conditions are hard controls that reject the purchase outright (`ERR_OUTSIDE_ALLOWED_HOURS`, `ERR_PRODUCT_NOT_ALLOWED`) before any transaction exists to flag. The over-tank rule is strict: `gallons` exactly equal to `tank_capacity_gallons` does not flag. A transaction can be fetched by a `Merchant`, `FleetManager`, or `ProgramAdmin`, and transactions can be listed and filtered by `card_id`, `vehicle_id`, `driver_id`, `jurisdiction`, and `posting_status`.

### 3.5. The Posting Lifecycle: Capture, Settlement, Void, and Rebates

A transaction carries two independent status axes. The money axis, `posting_status`, moves through `AUTHORIZED`, `CAPTURED`, `SETTLED`, and `VOIDED`, and is driven by the `Merchant`. The review axis, `review_status`, is independent and is discussed in §3.6. A posting transition never changes the review axis and vice versa.

Both `provisional_rebate_cents` and `final_rebate_cents` are present on a transaction from the moment it is authorized, each starting at 0, and each is populated only by the transition that owns it. A `Merchant` captures an `AUTHORIZED` transaction, moving `posting_status` to `CAPTURED`; capturing anything not `AUTHORIZED` is rejected with `ERR_INVALID_TXN_STATE`. Capture computes the provisional rebate. The account's `rebate_tiers` is an ascending schedule; each element pairs a `min_month_gallons` threshold (an integer, zero or greater) with a `cpg_rebate` cents-per-gallon rate (an integer), sorted ascending by `min_month_gallons` with a first element whose `min_month_gallons` is 0. Client-supplied tiers are normalized by sorting them ascending before that check, and a tiers array that is empty, malformed, or whose lowest threshold is not 0 is rejected at account creation with `ERR_VALIDATION`. Its default is a rate of 5 cents per gallon from 0 gallons, 8 cents per gallon once month-to-date reaches 1000 gallons, and 12 cents per gallon once it reaches 5000 gallons. To rate this transaction, compute its month-to-date gallons: the sum of `gallons` over the account's non-`VOIDED` transactions in `CAPTURED` or `SETTLED` posting status whose `purchased_at` lies in the same UTC calendar month as this transaction, counting those posted so far this month up to and including this one. Select the rate from the highest tier whose `min_month_gallons` is less than or equal to that month-to-date total; a tier applies once the total reaches its threshold, and the threshold is inclusive. The transaction's `provisional_rebate_cents` is its `gallons` multiplied by the selected per-gallon rate, rounded half up to whole cents. That amount is added to the account's `rebate_accrual_cents`.

A `Merchant` settles a `CAPTURED` transaction, moving `posting_status` to `SETTLED`; settling anything not `CAPTURED` is rejected with `ERR_INVALID_TXN_STATE`. Settlement recomputes the rebate as `final_rebate_cents` using the same tier-selection procedure, except that month-to-date gallons is replaced by the whole-month total: the sum of `gallons` across all of the account's non-`VOIDED` `CAPTURED`-or-`SETTLED` transactions in this transaction's UTC calendar month. Because a later purchase can push the month total past a higher threshold, the final rate can exceed the provisional one, so `final_rebate_cents` can be larger than `provisional_rebate_cents`. The rebate is again `gallons` times the selected rate, rounded half up to whole cents. The account's `rebate_accrual_cents` is then adjusted by `final_rebate_cents` minus `provisional_rebate_cents`. Settlement also sets `hold_amount_cents` to 0, releasing the hold so that this transaction's `gross_amount_cents` moves out of `outstanding_holds_cents` and into `settled_spend_cents`. Throughout, `rebate_accrual_cents` is maintained as the running sum of each transaction's individually rounded rebate — rounded per transaction, then summed — never by summing gallons first and rounding once.

A `Merchant` voids a transaction. Voiding an `AUTHORIZED` transaction moves it to `VOIDED` and sets `hold_amount_cents` to 0, releasing the hold; no rebate had been accrued, so none is reversed. Voiding a `CAPTURED` transaction moves it to `VOIDED`, sets `hold_amount_cents` to 0, and subtracts the previously accrued `provisional_rebate_cents` from the account's `rebate_accrual_cents`. Voiding from any other posting status is rejected with `ERR_INVALID_TXN_STATE`. This `CAPTURED → VOIDED` compensation is exactly the transition triggered as a cascade when a card is suspended (§3.2) or a fraud alert is confirmed (§3.6). Both `SETTLED` and `VOIDED` are terminal.

### 3.6. Fraud Alerts and the Review Axis

A `FraudAlert` is created by the system when an authorization trips a fraud rule (§3.4); it references its `transaction_id` and `card_id`, records the `rule_code` that fired, and starts in status `OPEN`. A `FraudAnalyst` works the queue and may attach a free-text `resolution_note` when confirming, dismissing, or reopening. Alerts can be fetched and listed by card, transaction, and status by a `FraudAnalyst`, `FleetManager`, or `ProgramAdmin`.

A `FraudAnalyst` moves an `OPEN` alert to `INVESTIGATING`; investigating anything not `OPEN` is rejected with `ERR_INVALID_ALERT_STATE`. From `INVESTIGATING`, the analyst may confirm or dismiss. Confirming requires the alert be `INVESTIGATING` and the alert's card not be `CANCELLED`; on confirm, the alert moves to `CONFIRMED` and, as the root of a cascade, its `FuelCard` is transitioned `ACTIVE → SUSPENDED` — which itself voids the card's open transactions, which themselves release holds and reverse accrued rebate. The card leg of that cascade is conditional on the card actually being `ACTIVE`: `CANCELLED` is the only card state that blocks the confirm outright, and a card that is merely `ISSUED` or already `SUSPENDED` neither blocks the confirm nor is transitioned by it — the alert still moves to `CONFIRMED`, and the card is left exactly as it was, with no status change, no `version` bump, and no void-and-reverse chain. Confirming from a non-`INVESTIGATING` state is rejected with `ERR_INVALID_ALERT_STATE`; if the underlying card is `CANCELLED` the required card suspension cannot proceed and the confirm is rejected with `ERR_INVALID_CARD_STATE`. Dismissing requires the alert be `INVESTIGATING`; it moves the alert to the terminal `DISMISSED` and, on the review axis, transitions the flagged transaction's `review_status` from `FLAGGED` to `CLEARED` (leaving `posting_status` untouched).

A confirmed alert may be reopened by a `FraudAnalyst`, cycling it from `CONFIRMED` back to `INVESTIGATING` for further review; reopening does not un-suspend the card. Reopening anything not `CONFIRMED` is rejected with `ERR_INVALID_ALERT_STATE`. The alert status set is `OPEN`, `INVESTIGATING`, `CONFIRMED`, and `DISMISSED`, with only `DISMISSED` terminal; the review axis values are `CLEAN`, `FLAGGED`, and `CLEARED`.

### 3.7. Telematics Faults and Maintenance Windows

The `TelematicsGateway` reports a `TelematicsFault` against a vehicle, supplying `vehicle_id`, a diagnostic `fault_code`, a `severity` of `INFO`, `WARN`, or `CRITICAL`, and — for critical faults — a `maintenance_window_start` and `maintenance_window_end`. A fault's `status` moves through `OPEN`, `MAINTENANCE_SCHEDULED`, `MAINTENANCE_COMPLETE`, and the terminal `CLEARED`, starting `OPEN`. Faults can be fetched and listed by vehicle, status, and severity.

A `CRITICAL` fault is handled specially at report time. It requires both `maintenance_window_start` and `maintenance_window_end`, else `ERR_MISSING_MAINTENANCE_WINDOW`. The window must be well-formed, with `maintenance_window_start` strictly earlier than `maintenance_window_end`, else `ERR_INVALID_INTERVAL`. The window, expanded by the maintenance buffer of 2 hours (`MAINTENANCE_BUFFER_HOURS`) on both sides, must not intersect any other non-`CLEARED` fault window on the same vehicle; because the comparison is buffered and closed, windows that touch within the buffer collide and are rejected with `ERR_MAINTENANCE_OVERLAP`. The buffer is applied to the incoming window only, and the fault it is tested against is compared on its own unbuffered bounds; a non-`CLEARED` fault that carries no window (any non-critical fault reported without one) is simply not a collision candidate. When these hold, the critical fault auto-transitions from `OPEN` to `MAINTENANCE_SCHEDULED`, and as the origin of a cascade transitions the `Vehicle` from `ACTIVE` to `OUT_OF_SERVICE`, which in turn ends every `ACTIVE` card assignment on that vehicle. That vehicle leg is conditional on the vehicle being `ACTIVE`: reporting a critical fault against a vehicle already `OUT_OF_SERVICE` or `RETIRED` still creates the fault and still schedules it, but leaves the vehicle's `status`, `version`, and assignments untouched. Non-critical (`INFO` or `WARN`) faults are created `OPEN` and cascade nothing; they may carry a maintenance window, which is stored and honored as a collision candidate but is not required of them and triggers no overlap check of its own.

The `TelematicsGateway` marks a `MAINTENANCE_SCHEDULED` fault complete, moving it to `MAINTENANCE_COMPLETE`; completing anything else is rejected with `ERR_INVALID_FAULT_STATE`. Completion returns the vehicle from `OUT_OF_SERVICE` to `ACTIVE`, but only when no other fault on that vehicle remains in `OPEN` or `MAINTENANCE_SCHEDULED`; if another blocking fault remains, the vehicle stays out of service. The gateway clears a fault to the terminal `CLEARED` from `MAINTENANCE_COMPLETE`, and may also clear a non-critical fault directly from `OPEN` (a clear from `OPEN` is permitted only when `severity` is not `CRITICAL`); clearing from any other state is rejected with `ERR_INVALID_FAULT_STATE`.

### 3.8. Fuel Economy Reporting

Beyond the per-transaction `mpg_snapshot` computed at authorization, a `FleetManager` or `ProgramAdmin` can query a vehicle's economy under a chosen `method`, which is either `SEGMENT` (the default) or `ROLLING`. The response returns the `method` used, the computed `mpg`, and an `exception` boolean that is true when that `mpg` falls below the vehicle's `expected_mpg_min` or above its `expected_mpg_max`.

Both methods draw on the vehicle's window of `AUTHORIZED`-or-later, non-`VOIDED` transactions, ordered by `purchased_at` ascending with ties broken by `created_at` ascending. The `SEGMENT` method uses only the most recent such transaction: its `mpg` is that transaction's `segment_miles` divided by its `gallons`, rounded half up to one decimal place. The `ROLLING` method uses the whole window: total miles is the latest transaction's `odometer` minus the earliest window transaction's own `odometer` — deliberately not the vehicle's `starting_odometer`, so the miles of the earliest fill's own segment are excluded, and a window holding exactly one transaction therefore yields 0 total miles and an `mpg` of 0 — total gallons is the sum of `gallons` across the window, and `mpg` is total miles divided by total gallons, rounded half up to one decimal place. The two methods diverge whenever per-fill economy varies across the window. If the window is empty, or its gallons sum to zero, `mpg` is reported as 0 under either method, and `exception` is then evaluated against that 0 like any other figure — so a vehicle with no qualifying transactions reports an `exception` of true whenever its `expected_mpg_min` is above zero, which it always is.

### 3.9. IFTA Tax Reporting and GL Export

A `ProgramAdmin` generates a quarterly fuel-tax report by naming a `fleet_account_id` and a `quarter` tag of the form four digits, a hyphen, `Q`, and a digit 1 through 4 (for example `2026-Q1`). Generation derives the quarter's `period_start` (inclusive UTC start) and `period_end` (exclusive UTC end) from the `quarter`, computes the tax figures, and creates the report in status `DRAFT`.

The computation gathers the account's `SETTLED` transactions whose `purchased_at` lies within the half-open period. The fleet's average economy is the sum of `segment_miles` over those settled transactions divided by the sum of their `gallons`; if that gallon total is zero, the fleet economy is treated as zero and the report has no jurisdiction lines. Otherwise, for each jurisdiction with settled activity in the period, one entry is emitted in `jurisdiction_lines` — the lines ordered by `jurisdiction` code ascending, not by transaction order — carrying: the `jurisdiction` code; `miles`, the sum of `segment_miles` for that jurisdiction's settled transactions; `gallons_purchased`, the sum of their `gallons`; `taxable_gallons`, which is that jurisdiction's `miles` divided by the fleet average economy, rounded half up to three decimal places (and zero when the fleet economy is zero); `tax_rate_cents`, the per-gallon tax rate for that jurisdiction; and `net_tax_cents`. The per-gallon jurisdiction tax rates, in cents, are 68 for `CA`, 26 for `AZ`, 33 for `NV`, 38 for `OR`, and 20 for `TX`. A purchase's `jurisdiction` is accepted at authorization as any non-empty string without being checked against that table, so a jurisdiction outside it still produces a line here, carrying a `tax_rate_cents` of 0 and hence a `net_tax_cents` of 0. A jurisdiction's `net_tax_cents` is the tax owed on taxable gallons minus the credit for tax already paid at the pump: multiply `taxable_gallons` by `tax_rate_cents` and round half up to whole cents, then subtract the result of multiplying `gallons_purchased` by `tax_rate_cents` and rounding half up to whole cents. The report's `total_tax_cents` is the sum of `net_tax_cents` across all jurisdiction lines, and may be negative when pump-paid tax exceeds the tax owed.

Those figures are stamped onto the report at generation, but while the report remains `DRAFT` they are not authoritative: a `DRAFT` report is a live view, re-deriving its `jurisdiction_lines` and `total_tax_cents` from the account's current settled activity every time it is read, so settling further in-period transactions after generation changes what an unchanged `DRAFT` report returns (and does so without touching its `updated_at` or `version`, since re-derivation is not a mutation).

A `ProgramAdmin` files a `DRAFT` report, moving it to the terminal `FILED`. Filing requires that every transaction of the report's account whose `purchased_at` falls within the period is `SETTLED` — every transaction, in any posting status, so a single lingering `AUTHORIZED` or `CAPTURED` purchase blocks the filing, while a `VOIDED` one blocks it too; if any in-period transaction is not settled the file is rejected with `ERR_PERIOD_NOT_SETTLED`, and filing a report not in `DRAFT` is rejected with `ERR_INVALID_REPORT_STATE`. On file, the system recomputes the figures one last time, freezes them into the report's `jurisdiction_lines` and `total_tax_cents`, and stamps `filed_at` from the logical clock; from then on the report reports those frozen numbers verbatim and no longer reconciles against later activity. Reports can be fetched and listed by fleet account and status.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`. All other mutations, transitions, and reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | ProgramAdmin |
| POST | `/fleet-accounts` | Create a fleet account | ProgramAdmin |
| GET | `/fleet-accounts/{id}` | Fetch a fleet account | ProgramAdmin, FleetManager |
| GET | `/fleet-accounts/{id}/summary` | Ledger snapshot and GL/expense export | ProgramAdmin, FleetManager |
| POST | `/vehicles` | Onboard a vehicle | FleetManager |
| GET | `/vehicles/{id}` | Fetch a vehicle | FleetManager, ProgramAdmin |
| GET | `/vehicles` | List/filter vehicles | FleetManager, ProgramAdmin |
| GET | `/vehicles/{id}/mpg` | Computed fuel economy | FleetManager, ProgramAdmin |
| POST | `/vehicles/{id}/retire` | Retire a vehicle | FleetManager |
| POST | `/drivers` | Create a driver | FleetManager |
| GET | `/drivers/{id}` | Fetch a driver | FleetManager, ProgramAdmin |
| GET | `/drivers` | List/filter drivers | FleetManager, ProgramAdmin |
| POST | `/fuel-cards` | Issue a fuel card | FleetManager |
| GET | `/fuel-cards/{id}` | Fetch a fuel card (includes version) | FleetManager, ProgramAdmin |
| GET | `/fuel-cards` | List/filter fuel cards | FleetManager, ProgramAdmin |
| POST | `/fuel-cards/{id}/activate` | Activate or reinstate a card | FleetManager |
| POST | `/fuel-cards/{id}/suspend` | Suspend a card | FleetManager |
| POST | `/fuel-cards/{id}/cancel` | Cancel a card | FleetManager |
| POST | `/card-assignments` | Assign a card to a vehicle and driver | FleetManager |
| GET | `/card-assignments/{id}` | Fetch an assignment | FleetManager, ProgramAdmin |
| GET | `/card-assignments` | List/filter assignments | FleetManager, ProgramAdmin |
| POST | `/card-assignments/{id}/end` | End an active assignment | FleetManager |
| POST | `/transactions/authorize` | Authorize a fuel purchase | Merchant |
| GET | `/transactions/{id}` | Fetch a transaction | Merchant, FleetManager, ProgramAdmin |
| GET | `/transactions` | List/filter transactions | Merchant, FleetManager, ProgramAdmin |
| POST | `/transactions/{id}/capture` | Capture an authorized transaction | Merchant |
| POST | `/transactions/{id}/settle` | Settle a captured transaction | Merchant |
| POST | `/transactions/{id}/void` | Void an authorized or captured transaction | Merchant |
| GET | `/fraud-alerts/{id}` | Fetch a fraud alert | FraudAnalyst, FleetManager, ProgramAdmin |
| GET | `/fraud-alerts` | List/filter fraud alerts | FraudAnalyst, FleetManager, ProgramAdmin |
| POST | `/fraud-alerts/{id}/investigate` | Move an alert into investigation | FraudAnalyst |
| POST | `/fraud-alerts/{id}/confirm` | Confirm fraud (suspends the card) | FraudAnalyst |
| POST | `/fraud-alerts/{id}/dismiss` | Dismiss an alert | FraudAnalyst |
| POST | `/fraud-alerts/{id}/reopen` | Reopen a confirmed alert | FraudAnalyst |
| POST | `/telematics-faults` | Report a telematics fault | TelematicsGateway |
| GET | `/telematics-faults/{id}` | Fetch a fault | TelematicsGateway, FleetManager, ProgramAdmin |
| GET | `/telematics-faults` | List/filter faults | TelematicsGateway, FleetManager, ProgramAdmin |
| POST | `/telematics-faults/{id}/complete-maintenance` | Mark maintenance complete | TelematicsGateway |
| POST | `/telematics-faults/{id}/clear` | Clear a fault | TelematicsGateway |
| POST | `/ifta-reports` | Generate a DRAFT IFTA report | ProgramAdmin |
| GET | `/ifta-reports/{id}` | Fetch an IFTA report | ProgramAdmin, FleetManager |
| GET | `/ifta-reports` | List/filter IFTA reports | ProgramAdmin, FleetManager |
| POST | `/ifta-reports/{id}/file` | File a DRAFT report | ProgramAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_FORBIDDEN_FLEET` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_FLEET_ACCOUNT_NOT_FOUND` | 404 |
| `ERR_VEHICLE_NOT_FOUND` | 404 |
| `ERR_DRIVER_NOT_FOUND` | 404 |
| `ERR_CARD_NOT_FOUND` | 404 |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 |
| `ERR_TRANSACTION_NOT_FOUND` | 404 |
| `ERR_ALERT_NOT_FOUND` | 404 |
| `ERR_FAULT_NOT_FOUND` | 404 |
| `ERR_REPORT_NOT_FOUND` | 404 |
| `ERR_CARD_NOT_ACTIVE` | 409 |
| `ERR_INVALID_CARD_STATE` | 409 |
| `ERR_INVALID_TXN_STATE` | 409 |
| `ERR_INVALID_ALERT_STATE` | 409 |
| `ERR_INVALID_FAULT_STATE` | 409 |
| `ERR_INVALID_REPORT_STATE` | 409 |
| `ERR_VEHICLE_OUT_OF_SERVICE` | 409 |
| `ERR_NO_ACTIVE_ASSIGNMENT` | 409 |
| `ERR_PRODUCT_NOT_ALLOWED` | 422 |
| `ERR_OUTSIDE_ALLOWED_HOURS` | 422 |
| `ERR_GALLON_LIMIT_EXCEEDED` | 422 |
| `ERR_DRIVER_DOUBLE_BOOKED` | 409 |
| `ERR_MAINTENANCE_OVERLAP` | 409 |
| `ERR_INVALID_INTERVAL` | 422 |
| `ERR_MISSING_MAINTENANCE_WINDOW` | 422 |
| `ERR_DAILY_LIMIT_EXCEEDED` | 402 |
| `ERR_CREDIT_EXCEEDED` | 402 |
| `ERR_PERIOD_NOT_SETTLED` | 409 |
| `ERR_STALE_CARD_VERSION` | 412 |
