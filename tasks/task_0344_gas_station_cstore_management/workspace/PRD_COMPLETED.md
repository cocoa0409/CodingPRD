# Gas Station & C-Store Management API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Gas Station & C-Store Management API, the back-office and point-of-sale platform that runs a branded fueling site together with its attached convenience store. A single station is the organizing root of the system; underneath it sit the fuel grades posted at the islands, the underground tanks that hold the wet stock, the dispensing pumps, the cashier shifts that own the cash drawer, and the running ledger of fuel sales, store sales, vendor deliveries, loyalty memberships, and car-wash codes.

The platform exists to reconcile two facts that are always in tension at a fuel retailer: the physical reality of cash and gallons on one side, and the book record of what *should* be there on the other. Every shift ends with a drawer count that must be squared against expected cash; every tank's volume must track deliveries in and gallons dispensed out; every gallon's profit depends on what the wet stock actually cost when it was pumped underground. The API therefore treats pricing, inventory, cash reconciliation, loyalty accrual, age-restricted compliance, and fuel-margin reporting as one connected workflow rather than independent modules. Operations cascade — a posted delivery moves a tank's volume and recomputes the weighted-average cost that later drives a margin report; a settled cash sale debits the drawer that a cashier will count at close.

Because two operators may act on the same shift or tank from different terminals, the system enforces optimistic concurrency on the highest-contention writes so that no operator silently overwrites cash math or wet-stock math computed against a stale view. The sections that follow define the global request/response contract, the cross-cutting fiscal and inventory principles, and the detailed business workflows that govern each entity's lifecycle.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and boilerplate that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated with two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the operational capacity under which the request is made. If either header is missing or malformed, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are present but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN`.

The system recognizes three roles, spelled exactly as follows: `StationManager`, `CashierAttendant`, and `LoyaltyMember`.

A `StationManager` owns pricing, the physical plant, vendor receiving, and reporting: creating stations, setting the business clock, creating and repricing fuel grades, creating tanks and taking them down or restoring them, creating pumps, creating and posting/rejecting/voiding deliveries, reissuing expired car-wash codes, and computing margin reports. A `StationManager` cannot ring sales or operate a shift drawer. A `CashierAttendant` runs the register and the drawer: opening shifts, recording cash drops, beginning the count and closing shifts, authorizing/capturing/settling/reversing fuel sales, ringing and reversing store sales, and issuing and redeeming car-wash codes. Both a `CashierAttendant` and a `LoyaltyMember` may enroll a loyalty member and redeem loyalty points. Read (GET) access to the collections is broadly shared; the §4 table lists the authorized roles per endpoint.

Identity binding differs by role. When `X-User-Role` is `StationManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. When `X-User-Role` is `CashierAttendant`, `X-User-ID` is likewise an opaque operator identifier; however, the server records it as the `cashier_user_id` of any shift that cashier opens, and later compares it against that stored value for owner-only shift operations (it is not, itself, the `id` of any persisted entity). When `X-User-Role` is `LoyaltyMember`, `X-User-ID` is the `id` of the acting `LoyaltyAccount`; ownership checks on any resource that references a `LoyaltyAccount` compare the resource's loyalty-account foreign key to `X-User-ID`, so a member reads and redeems only against their own account.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0. A list request whose `limit` is below 1 or above 100, or whose `offset` is negative, is rejected with `ERR_VALIDATION`.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Nearly every resource in the system is a first-class, system-managed record carrying a standard set of fields:

- `id` — a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits indicating when the resource was created. For every stored resource its value is stamped from the owning station's `current_utc` (the business clock of §2.5) as it stood at the moment of creation, not from real wall-clock time; a `Station`'s own `created_at` is therefore its `current_utc` at creation, namely the epoch baseline. (This is what the margin-window predicate of §3.10 and the replacement-cost tie-break compare against.)
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits indicating when the resource was last modified; it is refreshed on every mutation.
- `version` — a system-managed integer used for optimistic concurrency control. It starts at 1 on creation and increases by exactly 1 on each mutation of the resource.

These common fields apply to `Station`, `FuelGrade`, `Tank`, `Pump`, `Delivery`, `Shift`, `FuelTransaction`, `StoreTransaction`, `LoyaltyAccount`, and `CarWashCode`. The `MarginReport` is the sole exception: it is an ephemeral computed snapshot, not a stored or queryable resource, so it carries only `id` and `created_at` and has neither `updated_at` nor `version`.

Recomputation of a derived field — for example a tank's `volume_gallons`, a fuel grade's `weighted_avg_cost_cents`, or a shift's `expected_drawer_cents` — is itself a mutation of the owning resource: it refreshes `updated_at` and increments `version` by 1, exactly as a direct edit would.

### 2.5. The Business Clock

The system runs on a server-controlled business clock rather than wall-clock time. Each `Station` carries a `current_utc` field, its authoritative current instant, which is initialized to a fixed epoch baseline when the station is created. Time only advances when a `StationManager` explicitly sets it through the test-driving clock capability, which writes the supplied instant into the station's `current_utc`. All time-dependent rules — most importantly car-wash code expiry and the issuance/reissue of a code's `expires_at` — are evaluated against the owning station's `current_utc`, not against real time. The clock-set request supplies a `station_id` and a target instant `to_iso8601`.

### 2.6. Left-to-Right Reference Validation

Requests carry references both in the URL path and in the body (foreign keys such as `station_id`, `tank_id`, `shift_id`, `pump_id`, `fuel_grade_id`, and `loyalty_account_id`). The system validates that every referenced resource exists, checking them left to right — path identifiers first, then body foreign keys in declaration order. The first reference that does not resolve causes the request to be rejected with `ERR_NOT_FOUND` before any later reference or business rule is evaluated. This existence pass runs after authentication and authorization but before body well-formedness and all business checks.

### 2.7. Monetary Values, Gallons, and Rounding

All monetary amounts in the system are integer cents — there are no fractional-cent fields. Gallon quantities (`net_gallons`, `capacity_gallons`, `reorder_point_gallons`, `volume_gallons`, `gallons`) are decimal numbers carried to three decimal places. Wherever a calculation produces cents from a product of gallons and a per-gallon rate, or from a percentage, the result is rounded to whole cents using the round-half-up convention (a value exactly at the halfway point rounds up). Volume comparisons at the reorder boundary, and the cash-variance tolerance comparison, use the rules stated in their respective workflow sections; those boundary inclusivities are part of the contract and are spelled out where each rule lives.

### 2.8. Validation Ordering

When several checks could reject a request, they are evaluated in a fixed priority order so that the returned `error_id` is deterministic. The order is: (1) authentication of the headers (`ERR_UNAUTHENTICATED`); (2) role authorization (`ERR_FORBIDDEN`); (3) existence of all referenced resources, left to right (`ERR_NOT_FOUND`); (4) body well-formedness — required fields present, enum values legal, numeric fields non-negative (`ERR_INVALID_REQUEST`); (5) shift-owner identity on owner-only shift operations (`ERR_NOT_SHIFT_OWNER`); (6) state correctness for the requested transition (`ERR_INVALID_STATE`); (7) the referenced shift being `OPEN` where required (`ERR_SHIFT_NOT_OPEN`); (8) the fuel transaction being captured before settlement (`ERR_PAYMENT_NOT_CAPTURED`); (9) age-restriction compliance (`ERR_AGE_VERIFICATION_FAILED`); (10) pump/tank availability at authorization (`ERR_PUMP_UNAVAILABLE`); (11) the delivery tank being active at post (`ERR_TANK_DOWN`); (12) car-wash code expiry (`ERR_CODE_EXPIRED`); (13) tank volume bounds (`ERR_TANK_CAPACITY_EXCEEDED` / `ERR_NEGATIVE_VOLUME`); (14) sufficient loyalty points (`ERR_INSUFFICIENT_POINTS`); (15) optimistic-concurrency version match (`ERR_STALE_VERSION`); (16) per-station uniqueness, which is checked after existence but before the fiscal/version checks (`ERR_DUPLICATE_GRADE` / `ERR_DUPLICATE_PUMP` / `ERR_DUPLICATE_PHONE`); and for list endpoints, pagination-range validation (`ERR_VALIDATION`). A higher-priority failure always surfaces first and masks lower-priority ones.

### 2.9. Per-Station Uniqueness

Three values must be unique within the scope of a single station. A fuel grade's `code` must be unique among the grades of its station; a duplicate is rejected with `ERR_DUPLICATE_GRADE`. A pump's `number` must be unique among the pumps of its station; a duplicate is rejected with `ERR_DUPLICATE_PUMP`. A loyalty account's `phone` must be unique among the accounts enrolled at its station; a duplicate is rejected with `ERR_DUPLICATE_PHONE`. These uniqueness checks run after the referenced resources are confirmed to exist and before any optimistic-concurrency check.

### 2.10. Optimistic Concurrency Control

Two of the highest-contention writes are guarded against lost updates by optimistic concurrency control (OCC). On these operations the client must echo back the version of the relevant parent resource that it last observed, and the server rejects the write if that version no longer matches the parent's current `version` — meaning another writer has advanced the parent since the client read it.

Settling a fuel transaction is guarded against a stale `Shift`. The settle request must carry `expected_shift_version`, which must equal the referenced shift's current `version`. If another settlement or a cash-paid delivery post has advanced the shift's version since the client last read it, the client's view of the drawer is stale, and the settle is rejected with `ERR_STALE_VERSION` (HTTP 412) so the drawer math is never applied against an outdated `expected_drawer_cents`.

Posting a delivery is guarded against a stale `Tank`. The post request must carry `expected_tank_version`, which must equal the target tank's current `version`. If another delivery post or a tank take-down has advanced the tank's version since the client last read it, the client's capacity and weighted-average-cost view is stale, and the post is rejected with `ERR_STALE_VERSION` (HTTP 412).

Closing a shift also requires the client to supply `expected_shift_version` matching the shift's current `version`; a mismatch is likewise rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint takes a version field; operations not named here are processed without an OCC check.

### 2.11. Parallel State Axes and Cyclic Lifecycles

Several entities track more than one status dimension at once, and the dimensions evolve independently. A `Shift` carries a `lifecycle_status` axis (`OPEN` → `COUNTING` → `CLOSED`) and a separate `reconcile_status` axis (`PENDING` → one of `BALANCED`, `OVER`, or `SHORT`); the reconcile axis stays `PENDING` until close, where the single close operation resolves both axes at once. A `FuelTransaction` carries a `payment_status` axis (`AUTHORIZED` → `CAPTURED` → `REFUNDED`) and a separate `settlement_status` axis (`UNSETTLED` → `SETTLED` → `REVERSED`); these advance independently except at reversal, where the one operation drives settlement to `REVERSED` and payment to `REFUNDED` together. A `Tank` is cyclic on its `status` axis: `ACTIVE` → `DOWN` → `ACTIVE`, so it may return to `ACTIVE` after having left it. A `CarWashCode` is likewise cyclic: `ISSUED` → `EXPIRED` → `ISSUED`, because a manager may reissue an expired code back to `ISSUED`.

### 2.12. Hierarchical Side-Effect Consistency

A single operation often mutates several resources at once, and every cascade is part of the contract. Taking a tank down forces its pumps out of service; posting a delivery moves tank volume, recomputes the grade's weighted-average cost, and may debit a shift drawer; settling a fuel sale moves tank volume, may debit a drawer, and may accrue loyalty points. Each cascaded resource that changes is itself mutated — its `updated_at` is refreshed and its `version` is incremented by 1. The detailed cascades are specified in the §3 workflow that drives them, and compensating operations (void, reverse) unwind exactly what their forward counterpart applied.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Station and Its Fuel Grades

A `StationManager` brings a site online by creating a `Station` with a display `name` and a `brand` banner. Two policy knobs may be supplied at creation and otherwise take their defaults: `tax_rate_bp`, the sales tax in basis points applied to taxable store items, defaults to 825 (that is, 8.25%); and `cash_variance_tolerance_cents`, the absolute drawer variance in cents within which a closing shift is judged `BALANCED`, defaults to 200 (two dollars). On creation the station's `current_utc` is set to the epoch baseline and its `version` is 1.

Against a station, the manager posts the `FuelGrade` records that name the products sold at the islands. A grade is created with its owning `station_id`, a `code` — one of `REGULAR`, `MIDGRADE`, `PREMIUM`, or `DIESEL`, unique within the station — and a posted `octane` rating. A new grade starts with `current_price_cents` and `weighted_avg_cost_cents` both at 0; `prior_price_cents` is also 0 until the first reprice. Repricing a grade records the move: the existing `current_price_cents` is copied into `prior_price_cents`, and `current_price_cents` is set to the supplied `new_price_cents`. A grade's `weighted_avg_cost_cents` is never set by a reprice — it is wet-stock cost, driven entirely by deliveries, and is discussed with the delivery workflow.

### 3.2. Tanks, Pumps, and Putting Equipment Out of Service

Wet stock lives in tanks. A `StationManager` creates a `Tank` under a `station_id` for a particular grade (`fuel_grade_id`), with a physical `label`, a `capacity_gallons` ceiling, and a `reorder_point_gallons` threshold. A fresh tank starts empty: `volume_gallons` is 0, its `status` is `ACTIVE`, and its `low_stock` flag reflects whether the starting volume is at or below the reorder point. The `low_stock` flag is true precisely when `volume_gallons` is less than or equal to `reorder_point_gallons`, and it is recomputed every time the volume moves.

A `Pump` is created under a `station_id` and bound to the tank it draws from via `tank_id`, with an island `number` that is unique within the station. A new pump's `status` is `IDLE`; over its life a pump is `IDLE`, `DISPENSING`, or `OUT_OF_SERVICE`.

A manager can take a tank out of service when it is `ACTIVE`, advancing its `status` from `ACTIVE` to `DOWN`; attempting this on a tank that is not `ACTIVE` is rejected with `ERR_INVALID_STATE`. Taking a tank down cascades to its pumps: every pump drawing from that tank whose status is not already `OUT_OF_SERVICE` is forced to `OUT_OF_SERVICE`, so none of them can dispense. The manager later restores a tank when it is `DOWN`, advancing `status` from `DOWN` back to `ACTIVE`; attempting a restore on a tank that is not `DOWN` is rejected with `ERR_INVALID_STATE`. Restoring reverses the cascade: every pump on that tank that is currently `OUT_OF_SERVICE` is returned to `IDLE`. Both the take-down and the restore increment the tank's `version` by 1, and each cascaded pump is itself mutated.

### 3.3. Receiving Vendor (DSD) Deliveries

Fuel arrives by direct store delivery from a vendor and is recorded as a `Delivery`. A manager creates a delivery in `DRAFT` against a `station_id` and the `tank_id` being filled, recording the `vendor_name`, the temperature-compensated `net_gallons`, and the vendor's `unit_cost_cents` per gallon (the wet-stock cost). At creation the system computes `invoice_total_cents` as the net gallons multiplied by the unit cost, rounded half-up to whole cents. A delivery may optionally be marked `paid_cash` (default false) when the driver was paid in cash out of the drawer; in that case the charged shift is named by `shift_id` (default null). The status axis runs `DRAFT` → `POSTED` → `VOIDED`, with `REJECTED` available as a revert directly out of `DRAFT`.

Posting a delivery commits it into wet stock and is the system's most consequential cascade. A post is allowed only when the delivery is in `DRAFT` (otherwise `ERR_INVALID_STATE`) and the target tank is `ACTIVE` (otherwise `ERR_TANK_DOWN`). The post must not overfill the tank: the tank's current volume plus the delivery's net gallons must be less than or equal to the tank's `capacity_gallons`, or the post is rejected with `ERR_TANK_CAPACITY_EXCEEDED`. When the delivery was paid in cash, the referenced shift must be `OPEN`, or the post is rejected with `ERR_SHIFT_NOT_OPEN`. The post request must also carry `expected_tank_version` for the OCC check described in §2.10. On success the delivery moves `DRAFT → POSTED`, the tank's `volume_gallons` increases by the net gallons and its `low_stock` is recomputed, the grade's `weighted_avg_cost_cents` is recomputed across all posted deliveries to that grade's tanks (see §3.4), the tank's `version` is incremented by 1, and the delivery's `version` is incremented by 1. If the delivery was paid in cash, the named shift's `cash_payouts_cents` increases by the delivery's `invoice_total_cents` and that shift's `expected_drawer_cents` is recomputed.

Rejecting a draft delivery is the clean revert: it is permitted only from `DRAFT` (otherwise `ERR_INVALID_STATE`), moves the status to `REJECTED`, touches no wet stock and no drawer, and increments the delivery's `version`. Both `VOIDED` and `REJECTED` are terminal.

Voiding unwinds a posted delivery. A void is permitted only when the delivery is `POSTED` (otherwise `ERR_INVALID_STATE`) and only when removing the gallons would not drive the tank negative — the tank's current volume minus the net gallons must be greater than or equal to 0, or the void is rejected with `ERR_NEGATIVE_VOLUME`. When the delivery was paid in cash, the referenced shift must still be `OPEN`, or the void is rejected with `ERR_SHIFT_NOT_OPEN`. A successful void moves `POSTED → VOIDED`, decreases the tank's `volume_gallons` by the net gallons and recomputes `low_stock`, recomputes the grade's `weighted_avg_cost_cents`, and — for a cash-paid delivery — decreases the charged shift's `cash_payouts_cents` by the `invoice_total_cents` and recomputes `expected_drawer_cents` as the compensating inverse of the post. The delivery's `version` is incremented.

### 3.4. Wet-Stock Cost and the Weighted Average

A grade's `weighted_avg_cost_cents` is the weighted-average cost of the wet stock sitting under it, in cents per gallon, computed across all `POSTED` deliveries to the tanks of that grade as the sum of each posted lot's `net_gallons` times its `unit_cost_cents`, divided by the sum of those net gallons. It is recomputed on every delivery post and every delivery void — the two operations that change which delivery lots are posted — so it always reflects the chronological blend of every gallon currently accounted for. A grade that has received no posted deliveries keeps the default of 0. As a per-gallon *rate* (not itself a stored cents amount) this field is carried as an exact, possibly fractional value — it is not rounded to whole cents when stored; rounding to whole cents happens only when the rate is multiplied out into a cents amount such as a transaction's `cogs_cents` or a margin report's `cogs_cents`. This weighted-average cost is the wet-stock cost the system pins as cost of goods on a settled fuel sale, and it is the cost basis a `WAC` margin report draws on.

A tank's `volume_gallons` starts at 0 and is the running balance of gallons. It increases by a delivery's net gallons when that delivery is posted and decreases by the same net gallons when the delivery is voided. It decreases by a fuel transaction's dispensed gallons when that transaction settles, and increases by the same gallons when that settlement is reversed. Only `POSTED` deliveries and `SETTLED` (non-reversed) fuel transactions ever move a tank's volume; a draft, rejected, or voided delivery and an unsettled or reversed transaction leave it untouched. Every move recomputes `low_stock`, which is true when the resulting volume is at or below the reorder point.

### 3.5. Opening, Running, and Reconciling a Shift

A `CashierAttendant` opens a `Shift` against a `station_id` with an `opening_float_cents` — the starting cash placed in the drawer. The server stamps the opening cashier's `X-User-ID` onto the shift as `cashier_user_id`, sets `lifecycle_status` to `OPEN` and `reconcile_status` to `PENDING`, initializes `cash_sales_cents`, `cash_payouts_cents`, and `cash_drops_cents` all to 0, and sets `expected_drawer_cents` equal to the opening float.

Throughout the shift the drawer is kept current. The shift's `expected_drawer_cents` is always the opening float plus accumulated cash sales, minus accumulated cash payouts, minus accumulated cash drops. The `cash_sales_cents` accumulator is the sum of the `total_cents` of CASH-tendered transactions settled into this shift and not reversed; `cash_payouts_cents` is the sum of the `invoice_total_cents` of posted cash-paid deliveries charged to this shift and not voided; and `cash_drops_cents` is the sum of every cash drop recorded on the shift. When the cashier moves cash to the safe, the recorded drop's `amount_cents` is added to `cash_drops_cents` and `expected_drawer_cents` is recomputed; the shift's `version` is incremented.

Only the cashier who owns the shift may begin the count or close it. For these two owner-only operations the acting cashier's `X-User-ID` must equal the shift's `cashier_user_id`, or the request is rejected with `ERR_NOT_SHIFT_OWNER`. Beginning the count advances `lifecycle_status` from `OPEN` to `COUNTING` (rejected with `ERR_INVALID_STATE` if the shift is not `OPEN`) and increments the shift's `version`; the reconcile axis stays `PENDING`. Once a shift is in `COUNTING`, no further transactions may settle into it — settlement attempts against a non-open shift are rejected with `ERR_SHIFT_NOT_OPEN`.

Closing the shift is the reconciliation. A close is permitted only when the shift is in `COUNTING` (otherwise `ERR_INVALID_STATE`). The request must carry the physical `counted_drawer_cents`, which must be provided and at least 0 (otherwise `ERR_INVALID_REQUEST`), and `expected_shift_version` for the OCC check in §2.10. On close the system computes `variance_cents` as the counted drawer minus the expected drawer, advances `lifecycle_status` to `CLOSED`, and resolves the independent `reconcile_status` axis from the variance against the station's `cash_variance_tolerance_cents`: the shift is `BALANCED` when the absolute value of the variance is less than or equal to the tolerance (a variance exactly at the tolerance is `BALANCED`), `OVER` when the variance is greater than the tolerance, and `SHORT` when the variance is less than the negative of the tolerance. The single close transition thus resolves both axes at once, and the shift's `version` is incremented. `CLOSED` is terminal on the lifecycle axis.

### 3.6. Fuel Sales: Authorize, Capture, Settle, Reverse

A fuel sale is a `FuelTransaction`, authorized by a `CashierAttendant` against a `station_id`, the dispensing `pump_id`, and the `shift_id` it belongs to, recording the `gallons` dispensed and the `tender` (`CASH` or `CARD`); an optional `loyalty_account_id` ties the sale to a member, and is null for a guest. Authorization is allowed only when the pump's tank is `ACTIVE` and the pump itself is not `OUT_OF_SERVICE`; otherwise the authorization is rejected with `ERR_PUMP_UNAVAILABLE`. At authorization the price is computed and frozen onto the transaction: `base_price_cents` is captured from the grade's `current_price_cents` at that moment; the per-gallon loyalty discount `discount_cents_per_gal` is determined from the member's tier (see §3.7); `net_price_cents_per_gal` is the base price minus the discount; and `total_cents` is the gallons multiplied by the net per-gallon price, rounded half-up to whole cents. The transaction is created with `payment_status` `AUTHORIZED` and `settlement_status` `UNSETTLED`, its `cogs_cents` is null (cost of goods is not known until settlement, below), and the pump moves to `DISPENSING`.

Capturing payment advances the `payment_status` axis from `AUTHORIZED` to `CAPTURED` (rejected with `ERR_INVALID_STATE` if it is not `AUTHORIZED`), returns the pump to `IDLE`, and increments the transaction's `version`; the settlement axis is untouched.

Settling drives the sale into the books. A settle is permitted only when `payment_status` is `CAPTURED` (otherwise `ERR_PAYMENT_NOT_CAPTURED`), `settlement_status` is `UNSETTLED` (otherwise `ERR_INVALID_STATE`), and the referenced shift is `OPEN` (otherwise `ERR_SHIFT_NOT_OPEN`); the request must carry `expected_shift_version` for the OCC check in §2.10. On settlement the system captures `cogs_cents` as the dispensed gallons multiplied by the tank's `weighted_avg_cost_cents`, rounded half-up; decreases the tank's `volume_gallons` by the dispensed gallons (dispense is recorded at settlement) and recomputes `low_stock`; and advances `settlement_status` to `SETTLED`. If the tender is CASH, the shift's `cash_sales_cents` increases by `total_cents` and `expected_drawer_cents` is recomputed. If a loyalty account is attached, points are accrued and the member's tier is recomputed (see §3.7). The shift's `version` is incremented by 1, and the transaction's `version` is incremented by 1. The `payment_status` stays `CAPTURED` throughout settlement.

Reversing unwinds a settled sale. A reverse is permitted only when `settlement_status` is `SETTLED` (otherwise `ERR_INVALID_STATE`) and the referenced shift is `OPEN` (otherwise `ERR_SHIFT_NOT_OPEN`). On reversal the tank's `volume_gallons` increases by the dispensed gallons again; if the tender is CASH, the shift's `cash_sales_cents` decreases by `total_cents` and `expected_drawer_cents` is recomputed as the compensating inverse; if a loyalty account is attached, exactly the points that were accrued are subtracted from both `lifetime_points` and `point_balance` and the tier is recomputed; `settlement_status` becomes `REVERSED` and `payment_status` becomes `REFUNDED`. The transaction's `version` is incremented. This is the one operation that couples the two axes.

### 3.7. Loyalty: Discounts, Points, and Tiers

A `LoyaltyAccount` is enrolled — by either a `CashierAttendant` or the member acting as a `LoyaltyMember` — against a `station_id`, with a `phone` that is unique within the station and a `name`. A new account starts with `point_balance` 0, `lifetime_points` 0, and `tier` `BRONZE`. Tier is derived from lifetime points: an account is `GOLD` once its `lifetime_points` is at least 5000, `SILVER` once its `lifetime_points` is at least 2000 (but below the gold threshold), and `BRONZE` otherwise. Tier is recomputed every time points change.

The member's tier drives the per-gallon fuel discount applied at authorization. The tier discount in cents per gallon is 0 for `BRONZE`, 3 for `SILVER`, and 5 for `GOLD`, and a guest with no loyalty account gets 0. The applied `discount_cents_per_gal` is the smaller of the tier discount and the maximum allowed discount of 10 cents per gallon. (Within the current tier table the tier discounts never exceed the cap, but the cap is enforced regardless.)

Points accrue when a transaction settles, and are reversed on a reversal or refund. The base point figure is the sum of two terms: ten points for each gallon of fuel (the whole-number floor of the dispensed gallons multiplied by 10 points per gallon), plus two points for each whole dollar of store subtotal (the whole-number floor of the store subtotal in cents divided by 100, multiplied by 2 points per dollar). For a fuel settlement only the gallon term contributes and the store term is 0; for a store settlement only the dollar term contributes and the gallon term is 0. The awarded points are the base figure multiplied by the tier multiplier for the tier read at accrual time — 1.0 for `BRONZE`, 1.25 for `SILVER`, 1.5 for `GOLD` — with the product taken down to the whole number below (floor). The flooring is applied at each stage in this order: floor the base term(s) first, then multiply by the tier multiplier and floor again; no fractional points ever persist. The awarded points are added to both `point_balance` and `lifetime_points`, and the tier is then recomputed against the thresholds above.

A member (or a cashier acting for them) may redeem points for cash value. The requested `points` to redeem must not exceed the account's `point_balance`, or the redemption is rejected with `ERR_INSUFFICIENT_POINTS`. A redemption reduces `point_balance` by the redeemed points; `lifetime_points` is unchanged, so redeeming never lowers a member's tier. The account's `version` is incremented, and the response `data` is the updated `LoyaltyAccount` resource itself — no separate cents-value field is computed or returned in the response body.

### 3.8. C-Store Sales and Age-Restricted Compliance

A `StoreTransaction` rings up a convenience-store sale. A `CashierAttendant` creates it against a `station_id` and the `shift_id` it belongs to, with a `tender` of `CASH` or `CARD`, an optional `loyalty_account_id` (null for a guest), and a `line_items` array. Each line item carries a `sku`, a `name`, a `category`, a `unit_price_cents`, a `qty`, a `taxable` flag, and a `min_age`; a `min_age` greater than 0 marks the item as age-restricted. The transaction settles immediately at creation: its `settlement_status` is `SETTLED` from the start, with `REVERSED` as the only later state.

Pricing is computed on the line items. The `subtotal_cents` is the sum over all line items of `unit_price_cents` multiplied by `qty`. The `tax_cents` is computed once on the taxable subtotal — the sum of `unit_price_cents` times `qty` over only the line items whose `taxable` flag is true — multiplied by the station's `tax_rate_bp` divided by 10000, with that single product rounded half-up to whole cents (tax is summed first, then rounded once). The `total_cents` is the subtotal plus the tax.

Age compliance is enforced before the sale completes. When any line item has a `min_age` greater than 0, the operator-supplied `verified_buyer_age` (from an ID scan) must be provided and must be at least the largest `min_age` among the restricted line items; if it is missing or below that required age, the sale is rejected with `ERR_AGE_VERIFICATION_FAILED`. When no line item is age-restricted, `verified_buyer_age` may be omitted.

A successful store sale settles the same way a fuel settlement does on the cash and loyalty sides: if the tender is CASH, the shift's `cash_sales_cents` increases by `total_cents` and `expected_drawer_cents` is recomputed, and the shift's `version` is incremented; if a loyalty account is attached, points accrue per §3.7 (store term only) and the tier is recomputed. Reversing a store sale moves `settlement_status` from `SETTLED` to `REVERSED`, and unwinds the same effects: if the tender is CASH, the shift's `cash_sales_cents` decreases by `total_cents` and `expected_drawer_cents` is recomputed; if a loyalty account is attached, the accrued points are subtracted from `lifetime_points` and `point_balance` and the tier is recomputed; the shift's `version` is incremented.

### 3.9. Car-Wash Codes

A `CarWashCode` is either purchased or earned. A `CashierAttendant` issues a code against a `station_id` with a `package` of `BASIC`, `DELUXE`, or `SUPREME`, an optional `loyalty_account_id`, and an optional `fuel_transaction_id` that names the fuel sale that earned the code. An earned code (one carrying a `fuel_transaction_id`) is free: its `price_cents` is 0. A purchased code is priced from the package list — 800 cents for `BASIC`, 1200 for `DELUXE`, 1600 for `SUPREME` — reduced by the loyalty wash discount for the member's tier, which is 0% for `BRONZE`, 10% for `SILVER`, and 20% for `GOLD` (0% with no loyalty account); the list price multiplied by one minus that discount fraction is rounded half-up to whole cents and stored as `price_cents`. At issuance the server mints a `code_value` redemption string, sets `status` to `ISSUED`, and sets `expires_at` to the station's `current_utc` plus the code time-to-live of 30 days.

Redeeming a code is performed by a `CashierAttendant`. A redeem is permitted only when the code is `ISSUED` (otherwise `ERR_INVALID_STATE`) and the station's `current_utc` is strictly before the code's `expires_at`. If the clock has reached or passed `expires_at`, the redeem attempt lazily flips the code's `status` to `EXPIRED` and is itself rejected with `ERR_CODE_EXPIRED`; the code's `version` is incremented on that flip. A successful redeem advances `status` from `ISSUED` to `REDEEMED` (terminal) and increments the `version`.

An expired code is not dead. A `StationManager` may reissue a code that is `EXPIRED` (otherwise `ERR_INVALID_STATE`), which sets a fresh `expires_at` of the station's `current_utc` plus 30 days, returns `status` to `ISSUED`, and increments the `version` — the cyclic `ISSUED → EXPIRED → ISSUED` path.

### 3.10. Fuel-Margin Reporting

A `StationManager` computes a fuel-margin report over a time window. The report is an ephemeral computed snapshot returned inline; it is not stored or queryable. The request supplies the `station_id` the report is computed over (echoed back), an inclusive `window_start`, an exclusive `window_end`, and an optional `cost_basis` of `WAC` (the default) or `REPLACEMENT`; the report echoes `window_start`, `window_end`, and the resolved `cost_basis` back in its response alongside the computed figures. The window predicate selects the fuel transactions whose `created_at` is greater than or equal to `window_start` and strictly less than `window_end`, restricted to those whose `settlement_status` is `SETTLED` (reversed transactions are excluded).

Over that set the report computes `gallons_sold` as the sum of `gallons`, and `revenue_cents` as the sum of `total_cents`. Cost of goods is computed per grade and then summed. Transactions are grouped by grade (resolved through each transaction's pump to its tank to that tank's fuel grade). For each grade, a per-gallon cost is chosen according to the cost basis: under `WAC` it is the grade's `weighted_avg_cost_cents` — the chronological weighted-average wet-stock cost accumulated across all posted deliveries; under `REPLACEMENT` it is the unit cost of the most recent posted delivery to a tank of that grade (the forward-looking replacement cost, ignoring older lots), selecting the latest by effective time with `created_at` ascending as the tie-break. Each grade's cost of goods is that grade's total gallons multiplied by its chosen per-gallon cost, rounded half-up to whole cents; `cogs_cents` is the sum of those per-grade figures (rounding is applied per grade and then the rounded grade figures are summed). The `margin_cents` is `revenue_cents` minus `cogs_cents`. The `margin_pct` is the margin divided by revenue, multiplied by 100, rounded half-up to two decimal places; when `revenue_cents` is 0 the margin percentage is 0.

## 4. Endpoint Definitions

Operations that create a new, standalone resource return a `201 Created` status code; the margin-report computation, which mints a fresh snapshot, likewise returns `201`. Operations that modify an existing resource — including the state-transition operations and the clock-set capability — return a `200 OK` status code. Read operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/stations` | Create a station | StationManager |
| GET | `/stations/{stationId}` | Get a station | StationManager, CashierAttendant, LoyaltyMember |
| POST | `/_clock/set` | Test-driving: set a station's business clock | StationManager |
| POST | `/fuel-grades` | Create a fuel grade for a station | StationManager |
| GET | `/fuel-grades` | List fuel grades, filterable by station | StationManager, CashierAttendant |
| GET | `/fuel-grades/{gradeId}` | Get a fuel grade | StationManager, CashierAttendant |
| POST | `/fuel-grades/{gradeId}/reprice` | Reprice a grade | StationManager |
| POST | `/tanks` | Create a tank for a grade | StationManager |
| GET | `/tanks` | List tanks, filterable by station and grade | StationManager, CashierAttendant |
| GET | `/tanks/{tankId}` | Get a tank | StationManager, CashierAttendant |
| POST | `/tanks/{tankId}/take-down` | Take a tank out of service | StationManager |
| POST | `/tanks/{tankId}/restore` | Restore a tank to service | StationManager |
| POST | `/pumps` | Create a pump bound to a tank | StationManager |
| GET | `/pumps` | List pumps, filterable by station and tank | StationManager, CashierAttendant |
| GET | `/pumps/{pumpId}` | Get a pump | StationManager, CashierAttendant |
| POST | `/deliveries` | Create a DSD delivery in DRAFT | StationManager |
| GET | `/deliveries` | List deliveries, filterable by station, tank, shift | StationManager, CashierAttendant |
| GET | `/deliveries/{deliveryId}` | Get a delivery | StationManager, CashierAttendant |
| POST | `/deliveries/{deliveryId}/post` | Post a delivery into wet stock | StationManager |
| POST | `/deliveries/{deliveryId}/reject` | Reject a draft delivery | StationManager |
| POST | `/deliveries/{deliveryId}/void` | Void a posted delivery | StationManager |
| POST | `/shifts` | Open a cashier shift | CashierAttendant |
| GET | `/shifts` | List shifts, filterable by station | StationManager, CashierAttendant |
| GET | `/shifts/{shiftId}` | Get a shift | StationManager, CashierAttendant |
| POST | `/shifts/{shiftId}/drops` | Record a cash drop to the safe | CashierAttendant |
| POST | `/shifts/{shiftId}/begin-count` | Move shift to COUNTING, freezing settlement | CashierAttendant |
| POST | `/shifts/{shiftId}/close` | Close shift, compute variance and reconcile status | CashierAttendant |
| POST | `/fuel-transactions` | Authorize a pump fuel sale | CashierAttendant |
| GET | `/fuel-transactions` | List fuel transactions, filterable by station, pump, shift, loyalty account | StationManager, CashierAttendant |
| GET | `/fuel-transactions/{txnId}` | Get a fuel transaction | StationManager, CashierAttendant |
| POST | `/fuel-transactions/{txnId}/capture` | Capture payment | CashierAttendant |
| POST | `/fuel-transactions/{txnId}/settle` | Settle into shift drawer and accrue points | CashierAttendant |
| POST | `/fuel-transactions/{txnId}/reverse` | Reverse a settled sale | CashierAttendant |
| POST | `/store-transactions` | Ring up a c-store sale with age-restriction compliance | CashierAttendant |
| GET | `/store-transactions` | List store transactions, filterable by station, shift, loyalty account | StationManager, CashierAttendant |
| GET | `/store-transactions/{storeTxnId}` | Get a store transaction | StationManager, CashierAttendant |
| POST | `/store-transactions/{storeTxnId}/reverse` | Reverse a store sale | CashierAttendant |
| POST | `/loyalty-accounts` | Enroll a loyalty member | CashierAttendant, LoyaltyMember |
| GET | `/loyalty-accounts` | List loyalty accounts, filterable by station | StationManager, CashierAttendant |
| GET | `/loyalty-accounts/{loyaltyId}` | Get a loyalty account | StationManager, CashierAttendant, LoyaltyMember |
| POST | `/loyalty-accounts/{loyaltyId}/redeem` | Redeem points for cents value | LoyaltyMember, CashierAttendant |
| POST | `/car-wash-codes` | Issue a car-wash code (purchased or earned) | CashierAttendant |
| GET | `/car-wash-codes` | List car-wash codes, filterable by station and fuel transaction | StationManager, CashierAttendant |
| GET | `/car-wash-codes/{codeId}` | Get a car-wash code | StationManager, CashierAttendant |
| POST | `/car-wash-codes/{codeId}/redeem` | Redeem a code | CashierAttendant |
| POST | `/car-wash-codes/{codeId}/reissue` | Reissue an expired code | StationManager |
| POST | `/margin-reports` | Compute a fuel-margin report over a window | StationManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_SHIFT_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_AGE_VERIFICATION_FAILED` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_SHIFT_NOT_OPEN` | 409 |
| `ERR_PAYMENT_NOT_CAPTURED` | 409 |
| `ERR_PUMP_UNAVAILABLE` | 409 |
| `ERR_TANK_DOWN` | 409 |
| `ERR_TANK_CAPACITY_EXCEEDED` | 409 |
| `ERR_NEGATIVE_VOLUME` | 409 |
| `ERR_CODE_EXPIRED` | 409 |
| `ERR_INSUFFICIENT_POINTS` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_DUPLICATE_GRADE` | 409 |
| `ERR_DUPLICATE_PUMP` | 409 |
| `ERR_DUPLICATE_PHONE` | 409 |
| `ERR_VALIDATION` | 422 |
