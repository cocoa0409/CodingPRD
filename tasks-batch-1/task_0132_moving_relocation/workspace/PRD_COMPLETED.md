# Moving & Relocation Booking API — Product Requirements Document

## 1. Introduction

Relocating a household is one of the most logistically dense consumer transactions a moving company handles, and the price a customer ultimately pays depends on a long chain of decisions: how much volume the goods occupy, whether the quote is locked or re-rated at delivery, how much insurance the customer buys, whether the move is a local hourly job or a long-haul weight-tariff job, and what happens when goods sit in a warehouse or arrive damaged. This document specifies a REST API that governs that entire chain — from the first walk-through inventory survey to the final damage settlement — as a single, auditable booking system.

The product serves five operational constituencies. Booking customers create jobs, accept priced estimates, pay deposits and balances, and file claims when something breaks. Estimators conduct surveys and author the priced estimates that turn a pile of furniture into a number. Dispatchers own the truck and crew pool and run the physical move from scheduling through delivery, including any storage-in-transit. Claims adjusters adjudicate damage. Platform administrators handle fleet onboarding, final job closure, and goodwill waivers. The design goal is a system where every dollar is traceable to a rule, every state transition is guarded, and two operators working the same job cannot silently overwrite each other's work.

A recurring theme throughout the specification is the separation of two financial dimensions from the operational one: a job's physical progress (quoting, booked, in transit, delivered, closed) evolves independently of its money progress (unpaid, deposit paid, paid in full, refunded), and the ledger that ties them together is recomputed deterministically on every charge, payment, waiver, and refund.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Every request must include `X-User-ID` to identify the acting user and `X-User-Role` to declare their operational capacity. If either header is missing, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are present and valid but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes exactly five roles, spelled precisely as follows: `Customer`, `Estimator`, `Dispatcher`, `ClaimsAdjuster`, and `PlatformAdmin`.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` entity; ownership checks on any resource that references a `Customer` compare the resource's foreign-key field to `X-User-ID` — concretely, a `MoveJob` is owned by the `Customer` whose `id` equals the job's `customer_id`. When `X-User-Role` is `Estimator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it as `estimator_user_id` on an `Estimate` at generation time but never compares it to any entity's `id`. When `X-User-Role` is `Dispatcher`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity. When `X-User-Role` is `ClaimsAdjuster`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it as `filed_by_user_id` when a claim is intook and as `adjudicated_by_user_id` when a claim is approved or denied, and it compares these two recorded values to enforce segregation of duties, but it does not compare either to any entity's `id`. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator superuser identifier not tied to any persisted entity.

Two ownership rules layer on top of basic role permission. First, for customer-owned operations — accepting an estimate, cancelling a job, and applying a payment — the acting `Customer`'s `X-User-ID` must equal the targeted `MoveJob`'s `customer_id`, or the request is rejected with `ERR_NOT_RESOURCE_OWNER`. Second, a strict segregation-of-duties rule governs claim adjudication, described in §2.4 and §3.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0. A `limit` outside the range 1 through 100, or a negative `offset`, is rejected with `ERR_PAGINATION_INVALID`.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Version Semantics

Most top-level resources — `Customer`, `MoveJob`, `InventorySurvey`, `Estimate`, `PackingOrder`, `Truck`, `Crew`, `Dispatch`, `StorageLot`, and `DamageClaim` — carry a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits indicating when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp, refreshed on every modification to the resource.
- `version` (integer): a system-managed integer that starts at its initial value of 1 and increments by one on every mutation of the resource. It underpins optimistic concurrency control.

Two entities are deliberate exceptions. A `SurveyItem` and a `ClaimItem` are append-only line items; each carries only `id` and `created_at`. Neither `updated_at` nor `version` exists on a `SurveyItem` or a `ClaimItem`.

Whenever the system recomputes a derived field on a resource — for example, a `MoveJob`'s ledger totals when a charge or credit lands — that recomputation is a mutation: it refreshes the resource's `updated_at`. The job's `version` is incremented by one specifically when a SIT waiver is applied and when an estimate is generated against it (see §2.6 and §3); other internal ledger refreshes that the specification does not explicitly tie to a version bump refresh `updated_at` without otherwise inventing extra increments.

### 2.5. Nested Resource Retrieval and Referential Existence

Several endpoints address a line-item collection beneath a parent — survey items beneath a survey, claim items beneath a claim. When an endpoint path contains multiple identifiers, the system validates them left-to-right: the parent identifier is resolved first, and if it does not exist the request fails immediately with `ERR_NOT_FOUND` before any child or body validation runs. The same ordering governs body foreign keys: after path identifiers are confirmed, referenced resources named in the body (for example a `move_job_id`, `survey_id`, `truck_id`, or `crew_id`) are checked for existence, and any miss yields `ERR_NOT_FOUND`. Existence checks always precede business-rule checks.

### 2.6. Optimistic Concurrency Control

Two write operations require the client to prove it is acting on a current view of the parent `MoveJob` by supplying `expected_move_job_version`, the job `version` the client last observed.

Generating a new estimate is the first. A request to author an estimate must carry `expected_move_job_version` matching the target `MoveJob`'s current `version`. If another writer has advanced the job's `version` since the client last read it — for instance because an earlier estimate was already generated and that estimate locked the survey, bumping the job — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), so a second author working from a stale view cannot silently append a divergent price sheet.

Waiving a storage lot's SIT charge is the second. Because a waiver credits the parent job's ledger, the waive request must carry `expected_move_job_version` matching the `MoveJob`'s current `version`. If the job's `version` has advanced since the operator read it — for example a balance payment or another waiver already mutated the ledger — the waive is rejected with `ERR_STALE_VERSION` (HTTP 412), so the compensating credit is never applied against an outdated ledger snapshot. The `expected_move_job_version` field is non-optional on both of these operations; an `expected_move_job_version` that is not an integer is rejected with `ERR_INVALID_FIELD` before the version is compared. No other endpoint accepts a version field, and endpoints that take no version field perform no version check.

### 2.7. The Job Ledger and Conservation of Charges

Every `MoveJob` carries a running ledger expressed entirely in integer cents. It tracks `gross_charges_cents` (the conserved baseline of everything ever charged before any credit), `paid_cents` (the sum of payments applied), `waived_cents` (the sum of SIT charges forgiven as compensating credits), and `refunded_cents` (the sum returned to the customer on cancellation plus any approved claim payouts). From these, `balance_due_cents` is always recomputed as `gross_charges_cents` minus `paid_cents` minus `waived_cents` minus `refunded_cents`. This identity is re-evaluated every time any of its inputs changes — on estimate acceptance, on each payment, on a storage release, on a waiver, on a refund, on a claim approval, and on a claim reopen.

The conservation rule for waivers is strict: a waiver leaves `gross_charges_cents` untouched and instead increases `waived_cents`, so the balance falls by exactly the waived SIT charge while the gross baseline is preserved. The separate `final_charge_cents` field records the reconciled billable amount that is computed once at delivery and does not itself replace the running gross totals except as described in §3.

### 2.8. Monetary Precision and Rounding

All money is stored and returned as integer cents. Where a calculation produces a fractional cent before storage, the system rounds half up to the nearest whole cent. The pricing engine pins a specific rounding discipline: each charge component is independently rounded half up to integer cents first, and only then are the components summed. This round-per-component-then-sum order is mandatory wherever an estimate or a final charge is assembled; summing first and rounding once is not equivalent and is not permitted. Counts of days and counts of cubic feet follow their own rounding rules stated where each calculation is described.

### 2.9. Independent Job Dimensions and State Consistency

A `MoveJob` tracks two parallel lifecycles that advance independently. The operational dimension is `job_status`, one of `QUOTING`, `BOOKED`, `IN_TRANSIT`, `DELIVERED`, `CLOSED`, or `CANCELLED`. The financial dimension is `payment_status`, one of `UNPAID`, `DEPOSIT_PAID`, `PAID_IN_FULL`, or `REFUNDED`. A new job begins at `QUOTING` and `UNPAID`. Some transitions in one dimension are gated on the other — departure requires the money dimension to have reached at least a deposit — but neither dimension is a function of the other.

When an operation on one entity changes the state of another, the system performs every cascade the workflow defines rather than only the directly named effect. Marking a dispatch under way bubbles the parent job from `BOOKED` to `IN_TRANSIT`; completing it bubbles the job to `DELIVERED` and runs final reconciliation; cancelling a job propagates downward to its scheduled dispatches and frees the resources they held. Each entity touched by a cascade has its own `updated_at` refreshed.

## 3. Business Logic & Workflows

### 3.1. Onboarding Customers and the Fleet

A move begins with the people and equipment that will execute it. A `Customer` is registered with an `email`, a `full_name`, an `origin_state_code` (two uppercase letters identifying the origin residence's state), and a `phone`. The `email` must be unique across all customers and non-empty; registering a second customer with an `email` already on file is rejected with `ERR_DUPLICATE_EMAIL`. Either a `PlatformAdmin` or a prospective `Customer` may perform the registration.

The physical resource pool is owned by the dispatch operation. A `Truck` is registered with a `plate` (a unique, non-empty fleet identifier), a `capacity_cubic_feet` (which must be greater than zero and which later caps the volume a dispatch may carry), and a `home_state_code` naming the state the truck is domiciled in. A duplicate `plate` is rejected with `ERR_DUPLICATE_PLATE`. A `Crew` is registered with a `name`, a `head_count` (the number of movers on the team, which must be at least 2), and a `home_state_code` naming the state the crew is based in. Trucks and crews are registered by a `Dispatcher` or a `PlatformAdmin`.

### 3.2. Building the Inventory and Rolling Up Volume

Once a customer exists, a job is created in the `QUOTING` and `UNPAID` state by supplying the `customer_id` of the owning customer, a `service_type` of either `LOCAL` or `LONG_HAUL`, an `origin_zip`, a `destination_zip`, a `distance_miles` value giving door-to-door mileage (a non-negative integer that drives long-haul banding and is ignored entirely for local pricing), and a `requested_move_date` as an ISO 8601 UTC load date. Two accessorial inputs are optional and each default to 0 when omitted: `stair_flights`, the number of stair flights across origin and destination, and `long_carry_units`, the count of seventy-five-foot long-carry segments; both must be non-negative. A job may be created by a `PlatformAdmin` or by the booking `Customer`.

To price the job, an `Estimator` (or a `PlatformAdmin`) opens an `InventorySurvey` against it by supplying the `move_job_id` and a `survey_method` of `IN_HOME`, `VIRTUAL`, or `SELF_REPORTED`. A fresh survey starts with `total_cubic_feet` of 0, `estimated_weight_lbs` of 0, and `locked` set to false. The estimator then appends inventory line items, each a `SurveyItem` carrying the parent `survey_id`, a `label` describing the article, a `quantity` (at least 1), and a `cubic_feet_each` giving the cubic feet of a single unit (strictly greater than zero).

Every time a line item is appended, the survey's volume is rolled up afresh from all of its items, with no status filter and nothing excluded — items are append-only. The `total_cubic_feet` is the sum, over every survey item belonging to the survey, of that item's `quantity` multiplied by its `cubic_feet_each`, and is kept exact. The `estimated_weight_lbs` is then derived by multiplying the exact `total_cubic_feet` by a household-goods density of seven pounds per cubic foot and rounding the result half up to a whole number of pounds. A line item may only be appended while the survey is unlocked; once an estimate has been generated from a survey the survey's `locked` flag flips to true, and any further attempt to append an item is rejected with `ERR_SURVEY_LOCKED`.

### 3.3. Packing and Crating Add-Ons

Separately from the survey, a customer may purchase packing and crating, captured as a `PackingOrder` attached to a job by its `move_job_id`. A packing order carries a `crate_count` (the number of custom crates, optional and defaulting to 0 when omitted, and never negative) and `packing_lines`, a required array of material lines (which may be empty) where each line names a `material_code`, a `quantity` (a non-negative integer), and a `unit_price_cents` (a non-negative integer). A `packing_lines` that is not a list, or a line missing one of these keys, or a `quantity`/`unit_price_cents` that is not a non-negative integer, is rejected — a missing line key as `ERR_VALIDATION` and a non-list or out-of-range numeric as `ERR_INVALID_FIELD`. An `Estimator` or `PlatformAdmin` creates the order, and an `Estimator` or `PlatformAdmin` may later amend it, supplying a revised `crate_count`, a revised `packing_lines`, or both; on amendment any field omitted (or sent as null) is left unchanged.

The order's `packing_total_cents` is recomputed both at creation and on every amendment. It is the subtotal of the material lines — the sum over each line of that line's `quantity` times its `unit_price_cents` — plus a flat custom-crate fee of 9,500 cents (ninety-five dollars) for each crate counted in `crate_count`; that combined figure is rounded half up to integer cents. Because the inputs are already in whole cents, the rounding is a safeguard that leaves whole-cent inputs unchanged.

### 3.4. Generating and Revising the Priced Estimate

The pricing engine turns a survey into an `Estimate`. An `Estimator` generates one by supplying the `move_job_id`, the `survey_id` of the survey snapshot to price, a `binding_type` of `BINDING` or `NON_BINDING`, a `valuation_coverage` of `RELEASED` or `FULL_VALUE`, and — because generation is an optimistically-concurrent write against the job — `expected_move_job_version`. For full-value coverage the request also carries `declared_value_cents` (the customer-declared shipment value) and `deductible_cents`; both default to 0. Generating the estimate snapshots the author into `estimator_user_id`, locks the linked survey, computes every charge component below, and increments the job's `version` by one. A fresh estimate's `status` is `DRAFT`.

Before any pricing runs, full-value coverage is validated. When `valuation_coverage` is `FULL_VALUE`, the `declared_value_cents` must be at least the linked survey's `estimated_weight_lbs` multiplied by 600 cents (a six-dollar-per-pound minimum declared value); a declared value below that floor, or a `deductible_cents` that is not one of the allowed amounts, is rejected with `ERR_DECLARED_VALUE_TOO_LOW`. The allowed deductible amounts are exactly 0, 25,000, 50,000, or 100,000 cents. (Released coverage requires no declared value.)

**The valuation premium.** Under `RELEASED` coverage the `valuation_premium_cents` is exactly 0, and the carrier's liability falls back to the statutory sixty-cents-per-pound figure used at claim time. Under `FULL_VALUE` coverage the premium is built in two rounding steps. First a base premium is computed as the declared value divided by 10,000 and multiplied by a rate of 110 cents per hundred dollars of declared value (that is, $1.10 per $100), rounded half up to integer cents, and then floored to a minimum premium of 7,500 cents ($75) — the base is the larger of that $75 floor and the rounded rate figure. Second, a deductible credit is applied: a `deductible_cents` of 0 yields no credit, 25,000 yields a ten-percent credit, 50,000 yields an eighteen-percent credit, and 100,000 yields a thirty-percent credit. The final `valuation_premium_cents` is the base premium multiplied by one minus that credit fraction, again rounded half up to integer cents. The two roundings are independent — round the base, then multiply by the credit factor, then round again.

**The charge components.** Several components are common to both service models. The `packing_cents` on the estimate is copied from the linked packing order's `packing_total_cents` at generation, or 0 if the job has no packing order; if the job has more than one packing order the most recently created one (by `created_at`) is the one read. The `accessorial_cents` is the job's `stair_flights` multiplied by a flat 7,500 cents (seventy-five dollars) per flight, plus its `long_carry_units` multiplied by a flat 9,000 cents (ninety dollars) per segment, rounded half up. The `valuation_premium_cents` is as computed above.

For a `LONG_HAUL` job, pricing is weight-tariff driven and the labor field is 0. Let the linked survey's `estimated_weight_lbs` be the shipment weight. The weight in hundredweight is that weight divided by 100, kept exact. A per-hundredweight rate is selected by a single whole-shipment mileage band keyed on the job's `distance_miles`, with both ends of each band inclusive: a distance of 0 through 250 miles bills 9,000 cents per hundredweight, 251 through 750 miles bills 14,000 cents, 751 through 1,500 miles bills 21,000 cents, and 1,501 miles or more bills 29,000 cents. The `linehaul_cents` is the hundredweight figure multiplied by the banded rate, rounded half up. The `fuel_surcharge_cents` is the `linehaul_cents` multiplied by a fuel factor of 8.5 percent, rounded half up. For a long-haul job `labor_cents` is 0.

For a `LOCAL` job, pricing is hourly and the linehaul field is 0; `distance_miles` is ignored. The crew size is selected by the survey's `total_cubic_feet`: up to and including 300 cubic feet uses a crew of 2, 301 through 600 uses 3, 601 through 1,000 uses 4, and more than 1,000 uses 5. Raw labor hours are the `total_cubic_feet` divided by 45 cubic feet per crew-hour and then divided again by that selected crew size. Billable hours are the raw hours rounded up to the next quarter-hour, but never fewer than a three-hour minimum — that is, the billable hours are the larger of 3.0 and the quarter-hour-ceiling of the raw hours. The hourly rate is keyed on crew size: a crew of 2 bills 14,000 cents per hour, a crew of 3 bills 19,000 cents, a crew of 4 bills 24,000 cents, and a crew of 5 bills 28,500 cents. The `labor_cents` is that hourly rate multiplied by the billable hours, rounded half up. A flat travel fee equal to the hourly rate multiplied by a half-hour of travel time is rounded half up and stored in `fuel_surcharge_cents` (a local job reuses the fuel field slot for its travel charge); for a local job `linehaul_cents` is 0.

**Assembling the total.** Each of `linehaul_cents`, `labor_cents`, `fuel_surcharge_cents`, `packing_cents`, `valuation_premium_cents`, and `accessorial_cents` is rounded to integer cents on its own as described, and the `estimate_total_cents` is their integer sum — rounded per component first, then summed.

An estimate can be reworked before it is accepted. While the job is still `QUOTING`, an `Estimator` may revise a `DRAFT` estimate, which moves it `DRAFT → REVISED`; a `REVISED` estimate may be revised again and stays `REVISED → REVISED`, so the revision loop is repeatable. A revision may supply a new `binding_type`, `valuation_coverage`, `declared_value_cents`, or `deductible_cents`; on each revision the full pricing engine re-runs, every charge component and the `estimate_total_cents` are recomputed, and the estimate's own `version` increments by one. Revising an estimate that is not in `DRAFT` or `REVISED`, or revising while the job has left `QUOTING`, is rejected as an invalid state transition with `ERR_INVALID_STATE`. Beyond `ACCEPTED`, `REVISED`, and `DRAFT`, an estimate may also reach `SUPERSEDED` (when a sibling is accepted) or `EXPIRED`.

### 3.5. Acceptance, Booking, and the Two Money Dimensions

Acceptance is the customer's act and the moment the job is booked. The booking `Customer` accepts an estimate that is currently `DRAFT` or `REVISED`; the acting customer's `X-User-ID` must equal the owning job's `customer_id` (otherwise `ERR_NOT_RESOURCE_OWNER`), the estimate must belong to that same job, and the job must still be `QUOTING`. Acceptance sets the estimate's `status` to `ACCEPTED`, records the estimate's `id` on the job as `accepted_estimate_id`, moves the job's `job_status` from `QUOTING` to `BOOKED`, and adds the accepted estimate's `estimate_total_cents` to the job's `gross_charges_cents` before recomputing `balance_due_cents`. As a sibling-superseding side effect, every other estimate of the same job whose `status` is `DRAFT` or `REVISED` is set to `SUPERSEDED`. Accepting from any state other than `DRAFT` or `REVISED` is an invalid state transition (`ERR_INVALID_STATE`).

The accepted estimate is not a child pointer that can be navigated directly; the link runs the other way, from each estimate's `move_job_id` back to the job, and the accepted one is discoverable by listing the job's estimates filtered to the accepted status. The `accepted_estimate_id` is null until the job is booked.

Payments advance the second, financial dimension, and only the booking `Customer` may make them. A payment names a `kind` of either `DEPOSIT` or `BALANCE` and an `amount_cents`. A deposit may only be taken once the job is `BOOKED`; attempting a deposit before the job is booked is rejected with `ERR_DEPOSIT_BEFORE_BOOKED`. A deposit is defined only from `payment_status` `UNPAID`; once the job is booked, a deposit attempted when `payment_status` is not `UNPAID` (for example a second deposit) is rejected with `ERR_INVALID_STATE`. A successful deposit increases `paid_cents` by the `amount_cents`, moves `payment_status` from `UNPAID` to `DEPOSIT_PAID`, and recomputes `balance_due_cents`. A balance payment may only be taken once the job has been `DELIVERED` (a balance attempted while the job is not `DELIVERED` is rejected with `ERR_INVALID_STATE`) and only when `payment_status` is `DEPOSIT_PAID` (a balance attempted from any other payment status is rejected with `ERR_INVALID_STATE`), and its `amount_cents` must equal the job's current `balance_due_cents` exactly — no partial and no overpayment — or it is rejected with `ERR_PAYMENT_AMOUNT_MISMATCH`. A successful balance payment increases `paid_cents`, moves `payment_status` from `DEPOSIT_PAID` to `PAID_IN_FULL`, and recomputes `balance_due_cents` to zero. A payment that targets a job the acting customer does not own is rejected with `ERR_NOT_RESOURCE_OWNER`.

### 3.6. Scheduling the Move: Trucks, Crews, and Time Windows

With a job booked, a `Dispatcher` schedules the physical move by creating a `Dispatch` that names the `move_job_id`, the assigned `truck_id`, the assigned `crew_id`, an occupation `window_start` and `window_end` (an ISO 8601 UTC interval treated as half-open — start inclusive, end exclusive — on both the truck and the crew), and a `required_crew_size` (the minimum number of movers the job needs, at least 2). A new dispatch starts in `SCHEDULED` and occupies its truck and crew for the window.

Scheduling enforces a series of guards. The window itself must be well-formed: `window_end` must be strictly after `window_start`, or the request is rejected with `ERR_INVALID_WINDOW`. The truck must be big enough: the linked survey's `total_cubic_feet` — taken from the most recently created survey of the job (by `created_at`), or treated as 0 (so the check always passes) if the job has no survey — must not exceed the truck's `capacity_cubic_feet`, or the request is rejected with `ERR_TRUCK_CAPACITY_EXCEEDED`. The crew must be big enough: the crew's `head_count` must be at least the dispatch's `required_crew_size`, or the request is rejected with `ERR_CREW_TOO_SMALL`. The truck must be free for the window: the requested half-open interval must not overlap any non-terminal dispatch already on that truck — two windows that merely touch at a boundary, where the earlier window's `window_end` equals the later window's `window_start`, do not overlap and are allowed; a true overlap is rejected with `ERR_TRUCK_DOUBLE_BOOKED`. The crew must be free with turnaround slack: the requested window expanded by a ninety-minute turnaround buffer on each side must not overlap any non-terminal dispatch already on that crew, so two crew windows separated by less than ninety minutes are rejected while windows exactly ninety minutes apart (the later start at or after the earlier end plus ninety minutes) are allowed; a violation is rejected with `ERR_CREW_DOUBLE_BOOKED`.

### 3.7. Departure, Delivery, and Final Reconciliation

A `Dispatcher` sends the move under way by departing a `SCHEDULED` dispatch. Departure requires the job to be `BOOKED` and its `payment_status` to be either `DEPOSIT_PAID` or `PAID_IN_FULL`; if the money dimension has not reached at least a deposit, departure is blocked with `ERR_DEPENDENT_STATE_BLOCK`. A valid departure advances the dispatch `SCHEDULED → EN_ROUTE` and bubbles the job from `BOOKED` to `IN_TRANSIT`.

Completing the dispatch is where the bill is settled. The `Dispatcher` completes an `EN_ROUTE` dispatch, supplying the measured `actual_weight_lbs` and, where relevant to a binding reconciliation, an optional `actual_cubic_feet` and an optional `addendum_present` flag. Completion advances the dispatch `EN_ROUTE → COMPLETED`, bubbles the job `IN_TRANSIT → DELIVERED`, and runs the final-charge reconciliation that writes the job's `final_charge_cents`. After reconciliation the job's running gross is set to the reconciled `final_charge_cents` plus any storage or packing charges already booked into the gross baseline, and `balance_due_cents` is recomputed.

The reconciliation depends on the accepted estimate's `binding_type`. For a `BINDING` estimate the locked price holds and `final_charge_cents` equals the accepted estimate's `estimate_total_cents` exactly, with the actual weight ignored — unless both an addendum is present and the measured `actual_cubic_feet` exceeds the surveyed `total_cubic_feet` by more than a ten-percent tolerance (that is, the actual cubic feet is greater than the surveyed cubic feet times 1.10), in which case the estimate is re-rated by re-running the weight-driven components with the shipment weight taken from the actual weight while every other input — the surveyed `total_cubic_feet` (so a `LOCAL` job's crew size and labor hours are unchanged), the `distance_miles`, and the accepted estimate's `packing_cents`, `valuation_premium_cents`, and `accessorial_cents` — is held at its accepted-estimate value; the measured `actual_cubic_feet` is used only for the tolerance test, never as a pricing input. For a `NON_BINDING` estimate the weight-driven components are recomputed at the measured `actual_weight_lbs` — the linehaul (or labor) plus the fuel surcharge are re-rated to the actual weight, still using the surveyed `total_cubic_feet` for any `LOCAL` crew/hours basis — while the non-weight components carried on the accepted estimate, namely its `packing_cents`, `valuation_premium_cents`, and `accessorial_cents`, are carried over unchanged. As everywhere in the pricing engine, the reconciled figure is assembled by rounding each component half up to integer cents and then summing.

### 3.8. Storage-in-Transit and Goodwill Waivers

Goods sometimes wait in a warehouse between pickup and final delivery, tracked as a `StorageLot` opened against a job by its `move_job_id` with an `intake_date` (an ISO 8601 UTC date the goods entered the warehouse). A `Dispatcher` or `PlatformAdmin` opens the lot, which begins in `IN_STORAGE` with a null `release_date`.

A `Dispatcher` releases the lot by supplying a `release_date`, permitted while the lot is `IN_STORAGE` (releasing a lot not currently `IN_STORAGE` is an invalid state transition, `ERR_INVALID_STATE`) and while the job is `DELIVERED` or `IN_TRANSIT` (releasing while the job is in any other state is likewise rejected with `ERR_INVALID_STATE`), and only if the `release_date` is on or after the lot's `intake_date` — an earlier release date is rejected with `ERR_RELEASE_BEFORE_INTAKE`. Release computes the storage accrual and moves the lot to `RELEASED`. The raw storage days are the difference between `release_date` and `intake_date` in calendar days, rounded up to a whole day. The `billable_days` are those raw days less a three-day free allowance, floored at zero (the larger of zero and the raw days minus three). The `sit_charge_cents` is the `billable_days` multiplied by a daily storage rate of 4,200 cents (forty-two dollars) per day, plus twice a warehouse-handling fee of 11,000 cents (so 22,000 cents of handling in total), rounded half up. On release the `sit_charge_cents` is added to the job's `gross_charges_cents` and `balance_due_cents` is recomputed.

A `PlatformAdmin` may waive a `RELEASED` lot's charge as a goodwill credit. The waive is an optimistically-concurrent write: it requires `expected_move_job_version` to match the job's current `version` (otherwise `ERR_STALE_VERSION`, HTTP 412, per §2.6). A waive moves the lot `RELEASED → WAIVED`, adds the lot's `sit_charge_cents` to the job's `waived_cents` as a compensating credit, increments the job's `version` by one, and recomputes `balance_due_cents`. The conservation invariant holds: `gross_charges_cents` is unchanged and the balance drops by exactly the waived charge. A lot may be `IN_STORAGE`, `RELEASED`, or `WAIVED`; waiving anything not currently `RELEASED` is an invalid state transition (`ERR_INVALID_STATE`).

### 3.9. Cancellation and Cascades

Before goods are in motion, the booking `Customer` may cancel a job that is `QUOTING` or `BOOKED`. Cancellation is blocked if any dispatch of the job is `EN_ROUTE`, because the goods are already moving; that attempt is rejected with `ERR_CANCEL_IN_TRANSIT`. A permitted cancellation sets `job_status` to `CANCELLED` and cascades at least two levels deep: every `SCHEDULED` dispatch of the job is moved to `CANCELLED`, and each cancelled dispatch in turn frees the truck and crew occupation windows it held. If the customer had already paid anything — that is, `paid_cents` is greater than zero — the cancellation sets `refunded_cents` equal to `paid_cents`, moves `payment_status` to `REFUNDED`, and recomputes `balance_due_cents`. A cancel targeting a job the acting customer does not own is rejected with `ERR_NOT_RESOURCE_OWNER`.

A `Dispatcher` may also cancel a single `SCHEDULED` dispatch directly, which moves that dispatch to `CANCELLED` and frees the truck and crew windows for the interval `window_start` through `window_end`. A dispatch lifecycle is therefore `SCHEDULED`, then either onward through `EN_ROUTE` to `COMPLETED` or aside to `CANCELLED`.

### 3.10. Damage Claims and Settlement

After delivery, damage is handled through a `DamageClaim`. A `ClaimsAdjuster` or the `Customer` files a claim against a job by its `move_job_id`. Filing is only eligible when the job is `DELIVERED` and has an accepted estimate to draw coverage terms from; filing against an ineligible job is rejected with `ERR_CLAIM_NOT_ELIGIBLE`. At filing the claim begins `UNDER_REVIEW`, records the filer's opaque `X-User-ID` as `filed_by_user_id`, and snapshots the accepted estimate's coverage terms: `coverage_snapshot` is copied from the estimate's `valuation_coverage` (pinning whether the released or full-value settlement variant applies) and `deductible_cents` is copied from the estimate's deductible. The damaged articles are recorded as `ClaimItem` rows, each naming the parent `claim_id`, a `label`, an `item_weight_lbs` (the article weight in pounds, at least 1, which drives the released payout), a `repair_cost_cents` (a non-negative full-value input), and a `replacement_value_cents` (a non-negative full-value input). A `ClaimsAdjuster` or the `Customer` may add claim items.

Adjudication is governed first and foremost by segregation of duties: on approve, deny, and reopen, the acting `X-User-ID` must not equal the claim's `filed_by_user_id` — the adjuster who intook a claim may not adjudicate it — and a violation is rejected with `ERR_SEGREGATION_OF_DUTIES`. A `ClaimsAdjuster` approves a claim that is `UNDER_REVIEW`. Approval requires, in addition to the segregation check, that the linked job still be `DELIVERED` (a job that has since moved to `CLOSED` or `CANCELLED` rejects adjudication with `ERR_NOT_DELIVERED`) and that the claim have at least one `ClaimItem` (otherwise `ERR_CLAIM_NO_ITEMS`). On approval the settlement is computed and written to `settlement_cents`, the acting `X-User-ID` is recorded as `adjudicated_by_user_id`, the claim moves `UNDER_REVIEW → APPROVED`, and the `settlement_cents` is added to the job's `refunded_cents` as a payout credit before `balance_due_cents` is recomputed.

The settlement depends on the pinned `coverage_snapshot`. Under `RELEASED` coverage the payout is strictly weight-based: it is the sum, over every claim item, of that item's `item_weight_lbs` multiplied by sixty cents per pound, with the released sum rounded half up to integer cents; repair, replacement, and declared values are ignored, and no deductible applies. Under `FULL_VALUE` coverage the payout is the sum, over every claim item, of the smaller of that item's `repair_cost_cents` and its `replacement_value_cents`, less the claim's single `deductible_cents` applied once for the whole claim, with the result floored at zero; item weight is ignored. While a claim is `UNDER_REVIEW` or `DENIED` its `settlement_cents` is 0.

A `ClaimsAdjuster` may deny an `UNDER_REVIEW` claim (subject to the same segregation check and the same requirement that the job still be `DELIVERED`), which records the acting `adjudicated_by_user_id` and moves the claim `UNDER_REVIEW → DENIED`. An `APPROVED` claim may be reopened by a `ClaimsAdjuster` as long as the linked job is not `CLOSED` (a reopen attempted while the linked job is `CLOSED` is treated as an undefined transition and rejected with `ERR_INVALID_STATE`); reopening subtracts the prior `settlement_cents` from the job's `refunded_cents` as a compensating reversal, sets the claim's `settlement_cents` back to 0, clears `adjudicated_by_user_id`, recomputes `balance_due_cents`, and moves the claim `APPROVED → UNDER_REVIEW`. The claim cycle is therefore `UNDER_REVIEW → APPROVED → UNDER_REVIEW` when an approval is later unwound, and the reversal must exactly zero out the prior payout credit. Attempting any adjudication transition from a state where it is not defined is rejected with `ERR_INVALID_STATE`.

### 3.11. Closing the Job

A `PlatformAdmin` closes a `DELIVERED` job, which moves `job_status` to `CLOSED`. Closure is permitted only when the job is fully settled and clean: the `payment_status` must be `PAID_IN_FULL`, no `DamageClaim` of the job may be `UNDER_REVIEW`, and no `StorageLot` of the job may be `IN_STORAGE`. If a claim is still under review or a lot is still in storage, closure is blocked with `ERR_DEPENDENT_STATE_BLOCK`. `CLOSED` and `CANCELLED` are the terminal job states.

### 3.12. Validation Ordering

When several checks could fire on one request, they are evaluated in a fixed priority so that the most fundamental failure is the one reported. Authentication of the headers comes first (`ERR_UNAUTHENTICATED`), then role permission (`ERR_FORBIDDEN_ROLE`), then existence of every path identifier and body foreign key resolved left-to-right (`ERR_NOT_FOUND`), then resource-ownership for customer-owned operations (`ERR_NOT_RESOURCE_OWNER`), then segregation of duties on claim adjudication (`ERR_SEGREGATION_OF_DUTIES`), then whether the requested state transition is defined from the current state (`ERR_INVALID_STATE`), then cross-entity state guards such as the departure deposit requirement and the closure preconditions (`ERR_DEPENDENT_STATE_BLOCK`), then the survey-lock guard on item append (`ERR_SURVEY_LOCKED`), and only then the field-level and business-constraint checks — enum and range validity (`ERR_INVALID_FIELD`), the full-value declared-value floor (`ERR_DECLARED_VALUE_TOO_LOW`), the dispatch window, capacity, crew-size, and overlap checks, the balance-amount match, optimistic-concurrency version match (`ERR_STALE_VERSION`), the remaining claim and storage temporal checks, uniqueness conflicts, pagination bounds (`ERR_PAGINATION_INVALID`), and well-formed-body presence (`ERR_VALIDATION`). Malformed JSON or a missing required field surfaces as `ERR_VALIDATION`; an enum value outside its allowed set or a numeric field outside its declared range surfaces as `ERR_INVALID_FIELD`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource or append a new resource to a collection return `201 Created`. Applying a payment (`POST /move-jobs/{id}/payments`), being treated as appending a new entry to the job's ledger, likewise returns `201 Created` for both a `DEPOSIT` and a `BALANCE`. Operations that modify an existing resource — including state-transition actions (estimate accept, dispatch depart/complete/cancel, storage release/waive, claim approve/deny/reopen, job close/cancel) and amendments — return `200 OK`. List and fetch operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/customers` | Register a customer | PlatformAdmin, Customer |
| GET | `/customers/{id}` | Fetch a customer | PlatformAdmin, Customer, Estimator, Dispatcher, ClaimsAdjuster |
| POST | `/move-jobs` | Create a move job in QUOTING/UNPAID | PlatformAdmin, Customer |
| GET | `/move-jobs/{id}` | Fetch a move job with ledger fields | PlatformAdmin, Customer, Estimator, Dispatcher, ClaimsAdjuster |
| GET | `/move-jobs` | List move jobs (filter by customer_id, job_status) | PlatformAdmin, Estimator, Dispatcher, ClaimsAdjuster |
| POST | `/move-jobs/{id}/payments` | Apply a DEPOSIT or BALANCE payment | Customer |
| POST | `/move-jobs/{id}/close` | Close a fully-paid delivered job | PlatformAdmin |
| POST | `/move-jobs/{id}/cancel` | Cancel a QUOTING/BOOKED job | Customer |
| POST | `/surveys` | Create an inventory survey | Estimator, PlatformAdmin |
| GET | `/surveys/{id}` | Fetch a survey with rolled-up volume | Estimator, PlatformAdmin, Customer, Dispatcher |
| GET | `/surveys` | List surveys (filter by move_job_id) | Estimator, PlatformAdmin, Customer, Dispatcher |
| POST | `/surveys/{id}/items` | Append a survey item; recompute volume | Estimator, PlatformAdmin |
| GET | `/surveys/{id}/items` | List items of a survey | Estimator, PlatformAdmin, Customer, Dispatcher |
| POST | `/packing-orders` | Create a packing/crating add-on | Estimator, PlatformAdmin |
| GET | `/packing-orders/{id}` | Fetch a packing order | Estimator, PlatformAdmin, Customer |
| GET | `/packing-orders` | List packing orders (filter by move_job_id) | Estimator, PlatformAdmin, Customer |
| PATCH | `/packing-orders/{id}` | Update crate count / packing lines | Estimator, PlatformAdmin |
| POST | `/estimates` | Generate an estimate; locks the survey; OCC on the job | Estimator |
| GET | `/estimates/{id}` | Fetch an estimate | Estimator, PlatformAdmin, Customer |
| GET | `/estimates` | List estimates (filter by move_job_id, survey_id, status) | Estimator, PlatformAdmin, Customer |
| POST | `/estimates/{id}/revise` | Revise a DRAFT/REVISED estimate | Estimator |
| POST | `/estimates/{id}/accept` | Customer accepts; books the job | Customer |
| POST | `/trucks` | Register a truck | Dispatcher, PlatformAdmin |
| GET | `/trucks/{id}` | Fetch a truck | Dispatcher, PlatformAdmin |
| POST | `/crews` | Register a crew | Dispatcher, PlatformAdmin |
| GET | `/crews/{id}` | Fetch a crew | Dispatcher, PlatformAdmin |
| POST | `/dispatches` | Schedule a truck+crew within a window | Dispatcher |
| GET | `/dispatches/{id}` | Fetch a dispatch | Dispatcher, PlatformAdmin, Customer |
| GET | `/dispatches` | List dispatches (filter by move_job_id, truck_id, crew_id, status) | Dispatcher, PlatformAdmin, Customer |
| POST | `/dispatches/{id}/depart` | Mark a dispatch EN_ROUTE; job IN_TRANSIT | Dispatcher |
| POST | `/dispatches/{id}/complete` | Complete with actual weight; deliver and reconcile | Dispatcher |
| POST | `/dispatches/{id}/cancel` | Cancel a SCHEDULED dispatch; free windows | Dispatcher |
| POST | `/storage-lots` | Open a storage-in-transit lot | Dispatcher, PlatformAdmin |
| GET | `/storage-lots/{id}` | Fetch a storage lot | Dispatcher, PlatformAdmin, Customer |
| GET | `/storage-lots` | List storage lots (filter by move_job_id, status) | Dispatcher, PlatformAdmin, Customer |
| POST | `/storage-lots/{id}/release` | Release a lot; accrue SIT charge | Dispatcher |
| POST | `/storage-lots/{id}/waive` | Waive a released lot's charge; OCC on the job | PlatformAdmin |
| POST | `/damage-claims` | File a damage claim on a delivered job | ClaimsAdjuster, Customer |
| GET | `/damage-claims/{id}` | Fetch a damage claim | ClaimsAdjuster, PlatformAdmin, Customer |
| GET | `/damage-claims` | List damage claims (filter by move_job_id, status) | ClaimsAdjuster, PlatformAdmin, Customer |
| POST | `/damage-claims/{id}/items` | Add a damaged-item line | ClaimsAdjuster, Customer |
| GET | `/damage-claims/{id}/items` | List items of a claim | ClaimsAdjuster, PlatformAdmin, Customer |
| POST | `/damage-claims/{id}/approve` | Approve a claim (SoD enforced); compute settlement | ClaimsAdjuster |
| POST | `/damage-claims/{id}/deny` | Deny a claim (SoD enforced) | ClaimsAdjuster |
| POST | `/damage-claims/{id}/reopen` | Reopen an approved claim; reverse the payout | ClaimsAdjuster |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_DEPENDENT_STATE_BLOCK` | 409 |
| `ERR_SURVEY_LOCKED` | 409 |
| `ERR_INVALID_FIELD` | 422 |
| `ERR_DECLARED_VALUE_TOO_LOW` | 422 |
| `ERR_INVALID_WINDOW` | 422 |
| `ERR_TRUCK_CAPACITY_EXCEEDED` | 409 |
| `ERR_CREW_TOO_SMALL` | 409 |
| `ERR_TRUCK_DOUBLE_BOOKED` | 409 |
| `ERR_CREW_DOUBLE_BOOKED` | 409 |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_CLAIM_NOT_ELIGIBLE` | 409 |
| `ERR_CLAIM_NO_ITEMS` | 409 |
| `ERR_VALIDATION` | 400 |
| `ERR_NOT_DELIVERED` | 409 |
| `ERR_RELEASE_BEFORE_INTAKE` | 422 |
| `ERR_DEPOSIT_BEFORE_BOOKED` | 409 |
| `ERR_PAGINATION_INVALID` | 422 |
| `ERR_DUPLICATE_EMAIL` | 409 |
| `ERR_DUPLICATE_PLATE` | 409 |
| `ERR_CANCEL_IN_TRANSIT` | 409 |
