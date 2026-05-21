# Commercial Fleet Leasing API — Product Requirements Document

## 1. Introduction

Commercial trucking fleets sit at the intersection of three persistently messy domains: capital-intensive vehicle allocation, multi-jurisdiction fuel taxation, and incident-driven liability accounting. A fleet operator who leases tractors to a regional carrier must, on any given day, decide which `CLASS_8` rig is fit to leave the yard, whether a particular fuel card may still post a transaction in Texas at 03:00, and how a fender-bender in Pennsylvania will be split between the lessee's deductible and the operator's reserves — and must reconcile all three concerns under an immutable, auditable ledger because the IRS, the DOT, and the lessee's own accountants will, sooner or later, ask for the receipts.

This document specifies the Commercial Fleet Leasing API, a back-office system mounted under `/lease-agreements` that manages this full operational arc: registering lessees and vehicles, drafting and activating lease agreements, issuing fuel cards and posting purchases at the pump, ingesting telematics-driven odometer readings, opening and closing maintenance tickets, filing and adjudicating collision claims, settling monthly mileage overages, and preparing quarterly IFTA filings. The system is explicitly designed around two intertwined calculation engines — a tiered mileage-overage settlement and a per-jurisdiction fuel-tax computation — both of which must be reproducible to the cent across draft, finalize, and audit boundaries.

The audience for this document is the engineering team implementing the API. The voice is product-to-engineering: domain rules first, with enough precision that the same rules can be re-derived by tests without consulting the implementation. Where two rules interact (for example, a collision claim's revision count interacting with the discount applied at approval), the interaction is described in narrative rather than left as an exercise.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two custom HTTP headers identifying the caller: `X-User-ID` and `X-User-Role`. Both must be present and non-empty; a request that omits or empties either header is rejected with `ERR_AUTH_REQUIRED` and HTTP 401. The `X-User-Role` value is then compared against the system's role registry, and any value that does not exactly match one of the declared role names is also rejected with `ERR_AUTH_REQUIRED`. Once the role is recognised, it is checked against the per-endpoint authorisation matrix in §4; a recognised role attempting an operation it is not permitted to invoke is rejected with `ERR_FORBIDDEN` and HTTP 403.

The system recognises exactly five roles, spelled as follows: `FleetManager`, `TaxAdmin`, `ClaimAdjuster`, `VendorOps`, and `Lessee`. A `FleetManager` is an operator employed by the fleet who allocates vehicles, manages lessees, and supervises returns; a `TaxAdmin` administers IFTA filings and is the only role permitted to open, prepare, or file quarters; a `ClaimAdjuster` reviews and decides collision claims and may neither file new claims nor post telematics events; a `VendorOps` user represents a maintenance or repair vendor who progresses workshop tickets, posts telematics readings, and submits revised collision estimates; the `Lessee` role is the leasing customer, who can dispute settlements on their own lease and read resources belonging to their own account.

When `X-User-Role` is `FleetManager`, `TaxAdmin`, `ClaimAdjuster`, or `VendorOps`, the `X-User-ID` value is treated as an opaque operator identifier — it is not tied to any persisted entity, and the server may record it on audit metadata but does not compare it to any entity's `id` for ownership purposes. When `X-User-Role` is `Lessee`, by contrast, `X-User-ID` is the `id` of the acting `Lessee` row; ownership checks on any resource that ultimately references a `Lessee` (a lease agreement, a fuel card under that lease, a settlement on that lease) compare the resource's foreign-key chain back to `X-User-ID`. Specifically, a `Lessee` caller invoking the dispute operation on an `OverageSettlement` must have an `X-User-ID` that matches the `lessee_id` of the parent `LeaseAgreement`; mismatch yields `ERR_FORBIDDEN`.

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

List endpoints accept two query parameters that govern the slice of the result set returned: `limit` and `offset`. The default `limit` is 10; the minimum accepted value is 1 and the maximum is 100. The default `offset` is 0. Values outside these bounds are rejected as input-shape failures. Results are always sorted by `created_at` in ascending order, so two callers issuing the same query at the same moment with the same `limit` and `offset` receive identical pages. The pagination block in the `meta` object exposes four fields — `limit`, `offset`, `total_count` (the size of the unsliced result set after filters are applied), and `has_more` (true when there exist further records past the current slice).

### 2.4. Common Resource Properties

Every persisted resource owns a server-minted `id` formatted as a bare UUID with no type prefix; the same UUID format is used in foreign-key fields such as `lessee_id`, `vehicle_id`, `lease_agreement_id`, `fuel_card_id`, and `current_lease_id`. All resources carry a `created_at` timestamp written in ISO 8601 UTC with three fractional digits and never mutated after birth. Most resources additionally carry an `updated_at` timestamp in the same format that refreshes on every mutation, and an integer `version` field that begins at 1 on creation and increments by one on every server-acknowledged mutation. Two entities — `FuelCardTransaction` and `TelematicsEvent` — are immutable append-only records: they carry `id` and `created_at` only, and both `updated_at` and `version` are absent because there is no in-place edit path that could refresh them.

### 2.5. Nested Resource Resolution

Several endpoints embed parent identifiers in the URL path itself (for example, the fuel-card issuance path embeds `lease_id`, and the IFTA quarter creation path embeds `lessee_id`). Path parameters are validated strictly from left to right: the leftmost id is resolved against its entity first, and only if it exists does the next id along the path get resolved. Any unresolved id along the chain yields `ERR_NOT_FOUND` with HTTP 404 for that id; the system does not bypass an earlier missing parent to surface a downstream conflict. This same ordering applies to single-id paths during state-transition calls — the row must exist before any state, ownership, or business-rule check is evaluated.

### 2.6. Optimistic Concurrency Control

The PATCH operation on a `CollisionClaim` accepts an optional `version` field in its request body. When `version` is provided and equals the resource's currently stored `version`, the mutation proceeds and the stored `version` increments by one. When `version` is provided but does not match the stored value, the request is rejected with `ERR_VERSION_CONFLICT` and HTTP 409 — the writer is presumed to have read a stale copy. Omitting `version` from the body opts the caller out of the concurrency check entirely; the mutation proceeds unconditionally and the stored `version` still advances.

### 2.7. Monetary Precision and Tiered Rounding

All money in this system is stored and transmitted as integer cents — there are no floating-point dollar amounts anywhere in the schema. Whenever a calculation introduces a fractional cent (most commonly through the tiered overage multipliers expressed in basis points or through the IFTA per-gallon rate), the result is rounded half-up to the nearest whole cent. Where a calculation aggregates multiple components — for instance, an overage settlement that sums three tier sub-totals, or an IFTA filing that sums per-jurisdiction tax amounts — the rounding is applied to each line item first and only then are the rounded line items summed. The reverse order (sum first, then round once at the end) is explicitly forbidden because it produces a different value by a few cents on most realistic inputs; the system's tests assert the per-line-item-then-sum convention. Mileage figures are stored as integer miles and the ingest path drops any fractional information; fuel quantities are stored as decimal `gallons` with up to three fractional digits and are preserved at that precision throughout the IFTA computation.

### 2.8. Compound Lease State and Cascading Effects

The `lease_state` field on a `LeaseAgreement` is derived: it summarises the lease's position in a compound workflow that touches the parent `Vehicle`, every `FuelCard` issued under the lease, and any active `OverageSettlement` or `CollisionClaim`. State transitions on the lease therefore radiate side effects outward. Activating a lease flips the underlying `Vehicle` from `AVAILABLE` to `ALLOCATED`, sets the vehicle's `current_lease_id` to the lease's `id`, and resets `odometer_current_miles` to the recorded `odometer_baseline_miles`. Beginning the return phase flips the same vehicle to `IN_SHOP` and synthesises a draft final-month settlement. Finalising the return flips the vehicle back to `AVAILABLE`, clears `current_lease_id`, and closes every `FuelCard` under that lease. Suspending a lessee whose balance has crossed the default threshold cascades through every `ACTIVE` lease that lessee owns — each such lease moves to `DEFAULTED`, the underlying vehicle is moved to `GROUNDED`, and every fuel card under each defaulted lease is blocked. Every such side-effect mutation refreshes `updated_at` and advances `version` on each affected entity individually.

### 2.9. Ledger Integrity for the Lessee Balance

The `outstanding_balance_cents` field on a `Lessee` is the system's authoritative running ledger of money owed by that lessee. It is a derived field but is materialised on the row: every approval of a `CollisionClaim` adds the computed `lessee_deductible_cents` to the balance, and every `OverageSettlement` that transitions into the paid state subtracts that settlement's `balance_cents` from the balance. The two threshold-driven account effects — suspension and default — read this value live: when the balance reaches or exceeds the suspend threshold, the lessee is suspended; when the balance reaches or exceeds the (strictly higher) default threshold, every active lease owned by that lessee is moved to the defaulted state by the cascade described above. The system uses the suspend threshold for the move into the suspended state and the default threshold for the move into the defaulted state; reinstatement requires the balance to fall strictly below the suspend threshold.

### 2.10. Telematics, Odometer Reconciliation, and Stale Ingest

Odometer readings on a `Vehicle` advance only through the telematics ingest path. A device may emit any number of `TelematicsEvent` rows in any order, and the system reconciles each event against the vehicle's current odometer at arrival time: if the incoming `odometer_reading` is strictly less than the vehicle's current `odometer_current_miles`, the event is stored with `ingest_status` set to `REJECTED_STALE` and the vehicle's odometer is not advanced; otherwise, the event is stored with `ingest_status` set to `ACCEPTED` and the vehicle's `odometer_current_miles` is overwritten with the incoming reading. Rejected events remain visible in the event history and never participate in any downstream calculation. Accepted events feed both the overage settlement (whose period odometer endpoints are derived from `ACCEPTED` telematics) and the collision-settlement discount (whose telematics-quality lookup considers `ACCEPTED` events in a narrow window around the incident).

### 2.11. Validation Priority

When a request fails multiple checks at once, the system evaluates them in a fixed priority order so that the returned `error_id` is deterministic. The order is: authentication of the headers first (the headers must be present, the role must be a recognised name); then the role's authorisation for the endpoint; then, for endpoints that require resource ownership, the ownership check; then path-existence (left to right); then the state-machine check that the resource admits the requested transition; then the optimistic-concurrency `version` check on PATCH; and only after all of those, the endpoint-specific business rules in the order listed in §3 (which broadly runs from referential safety, through fiscal/temporal gates, to constraint-level boundary checks). A header-level failure therefore masks any business failure beneath it, and a state-level failure masks any business-rule failure beneath it, so that test fixtures probing the topmost layer always see that layer's `error_id` regardless of the deeper state of the world.

## 3. Business Logic & Workflows

### 3.1. Onboarding Lessees and Vehicles

A `FleetManager` brings a new operator onto the platform by registering a `Lessee` with three pieces of input: the registered business name as `legal_name`, the US Department of Transportation operator number as `dot_number`, and the two-letter US state code that will serve as the lessee's IFTA `base_jurisdiction`. The legal name is a free-form string of one to one-hundred-and-twenty characters that must be non-empty after trimming whitespace. The DOT number must be a digits-only string between six and eight digits long and must not collide with any other lessee's number — the field is unique across the entire `Lessee` table. The base jurisdiction must come from the supported set of ten US states: `CA`, `TX`, `NY`, `IL`, `FL`, `OH`, `PA`, `GA`, `WA`, or `AZ`. A fresh lessee is born in the `ACTIVE` account state with `outstanding_balance_cents` equal to zero.

Vehicles are likewise added by a `FleetManager`, who supplies the seventeen-character `vin` (composed of uppercase letters with `I`, `O`, and `Q` excluded plus the digits `0`–`9`, unique across the fleet), the tractor's `vehicle_class` chosen from `CLASS_3`, `CLASS_5`, `CLASS_7`, or `CLASS_8`, the `model_year` (an integer between 2000 and 2030 inclusive), and the recorded `odometer_baseline_miles` at fleet entry (a non-negative integer that defaults to zero when omitted). A newly added vehicle's `vehicle_status` is `AVAILABLE`, its `current_lease_id` is null, and its `odometer_current_miles` is initialised to the supplied baseline. Across its life a vehicle's `vehicle_status` cycles through `AVAILABLE`, `ALLOCATED`, `IN_SHOP`, and `GROUNDED` as workflows progress, and a terminal `RETIRED` state exists for vehicles permanently removed from the fleet (never re-allocated thereafter).

### 3.2. Drafting and Activating a Lease

The lease itself is created by a `FleetManager` who supplies the foreign keys `lessee_id` and `vehicle_id` along with `term_start_date` and `term_end_date`, the `monthly_mileage_allowance` (an integer between 1000 and 15000 miles inclusive), and the `overage_rate_cents_per_mile` (an integer between 5 and 100 cents inclusive). The end date must be strictly after the start date, and the spanning period must not exceed sixty months. An optional boolean `tiered_overage_enabled` flag defaults to false; when omitted, the lease will charge a single flat rate for every mile over allowance, and when set to true, the lease will use the three-tier multiplier schedule described in §3.6. The freshly drafted lease begins in the `DRAFT` state with `cumulative_overage_miles`, `collision_open_count`, and the computed compound `lease_state` field all initialised to zero / `DRAFT` respectively.

Activation by a `FleetManager` advances the lease from `DRAFT` to `ACTIVE` and is gated by four preconditions, each of which produces a distinct rejection. The lease itself must still be in `DRAFT` (otherwise `ERR_INVALID_STATE`). The target vehicle must currently be `AVAILABLE` and its `current_lease_id` must be null; either condition's failure yields `ERR_VEHICLE_ALREADY_ALLOCATED`. The owning lessee must be in `ACTIVE` account status. And the lessee's `outstanding_balance_cents` must fall strictly below the suspend threshold — a delinquent lessee cannot pick up new vehicles. On success, the vehicle moves to `ALLOCATED`, its `current_lease_id` is set to the lease's `id`, and `odometer_current_miles` is reset to the recorded `odometer_baseline_miles` so that subsequent telematics-driven overage math is measured against a clean baseline. Two activations arriving simultaneously against the same vehicle serialise on the `AVAILABLE` → `ALLOCATED` flip: exactly one writer wins, and the other receives `ERR_VEHICLE_ALREADY_ALLOCATED` with HTTP 409.

### 3.3. Issuing Fuel Cards and Posting Pump Transactions

Once a lease is active, a `FleetManager` issues a `FuelCard` under it by supplying `card_pan_last4` (exactly four digits — the system stores no full PAN) and `monthly_limit_cents` (an integer cap between 50,000 and 1,000,000 cents inclusive, applied as a spend ceiling per calendar month). The card is born `ACTIVE` with `current_period_spend_cents` initialised to zero.

Pump transactions are posted as `FuelCardTransaction` rows by either a `FleetManager` or a `VendorOps` user. The payload contains the `fuel_card_id`, the wall-clock `posted_at` timestamp (the moment the transaction occurred at the pump), the two-letter `jurisdiction` (one of the same ten supported states `CA`, `TX`, `NY`, `IL`, `FL`, `OH`, `PA`, `GA`, `WA`, `AZ` — the state in which the fuel was dispensed, not necessarily the lessee's base), the `gallons` decimal (strictly positive, at most 200, up to three fractional digits), and the `amount_cents` integer (strictly positive, at most 100,000 cents). A successfully posted transaction is born with `txn_status` of `POSTED`. The system additionally computes a derived `ifta_eligible` boolean on each transaction: a transaction is eligible if and only if the parent `FuelCard`'s vehicle has a `vehicle_class` in the set `CLASS_7` or `CLASS_8` at the moment of `posted_at` — lighter classes are out of scope for federal fuel-tax accounting and remain ineligible regardless of jurisdiction.

A posted transaction is rejected if the parent card's `card_status` is not `ACTIVE` or the parent lease's `lease_state` is not `ACTIVE`; the rejection in either case is `ERR_CARD_INACTIVE`. Posting is also rejected with `ERR_QUARTER_CLOSED` if the proposed `posted_at` falls inside the calendar quarter of an `IFTAQuarter` row already in the closed filing state for the same lessee — once a quarter is filed, no further IFTA-influencing activity may land in its window. If a posting attempt and a quarter-filing operation race to completion against the same window, exactly one wins on the quarter's flip from `READY` to `CLOSED`; if the transaction lands first it ends up posted (and is subsequently flipped to `IFTA_INCLUDED` when the quarter closes), otherwise the transaction loser receives `ERR_QUARTER_CLOSED` with HTTP 409.

The remaining gate is fiscal: the proposed `amount_cents` plus the card's current `current_period_spend_cents` for the calendar month must not exceed the card's `monthly_limit_cents`. Equality with the cap is permitted — the boundary is non-strict on the way up — and the request is rejected with `ERR_CARD_LIMIT_EXCEEDED` only when the sum strictly exceeds the cap. After acceptance, `current_period_spend_cents` is recomputed as the sum of `amount_cents` over every `POSTED` transaction on the same card whose `posted_at` falls inside the current calendar month (its first day at midnight UTC through its last day at one millisecond before the next midnight). A `FleetManager` may reverse a posted transaction by invoking the reversal capability on its `id`; reversal flips `txn_status` to `REVERSED` and triggers the same monthly-spend recomputation, which decrements the card's running total. Reversal must be applied before the parent IFTA quarter is filed; once filed, the transactions become immutable.

### 3.4. Telematics Ingest and the Vehicle Odometer

Either a `FleetManager` or a `VendorOps` user may post a `TelematicsEvent` against a vehicle's `id`. The payload carries the device-produced `event_ts`, the cumulative `odometer_reading`, an optional `harsh_event_count` (a non-negative integer counting harsh-brake and harsh-acceleration triggers since the previous event; defaults to zero), and an optional `fault_code` string (OEM-specific or empty string by default). Every accepted event is appended to the vehicle's history. The reconciliation rule is strict and chronological in arrival order: if `odometer_reading` is strictly less than the vehicle's existing `odometer_current_miles`, the event is recorded with `ingest_status` of `REJECTED_STALE` and the vehicle's odometer is not advanced; otherwise the event is recorded with `ingest_status` of `ACCEPTED` and the vehicle's `odometer_current_miles` is set to the new reading. Both events return 201 — the rejected-stale outcome is a stored record, not an HTTP error — but only accepted events feed overage and collision math downstream.

### 3.5. Maintenance Tickets

A `MaintenanceTicket` is opened against a `vehicle_id` by either a `FleetManager` or a `VendorOps` user, who supplies the `ticket_kind` (either `PM` for mileage-triggered preventive maintenance or `REPAIR` for ad-hoc work) and a vendor `estimate_cents` (a non-negative integer, defaulting to zero). At creation, the ticket records the vehicle's then-current `odometer_current_miles` into its own `opened_at_odometer` field as a permanent stamp. The ticket is born in `OPEN`.

A `VendorOps` user starts the work, advancing the ticket from `OPEN` to `IN_SHOP` (i.e. the ticket's `ticket_status` field moves from `OPEN` to `IN_SHOP`). The starting precondition is that the ticket is `OPEN` and the vehicle's `vehicle_status` is either `ALLOCATED` or `GROUNDED` — a vehicle that is not currently held by an active or defaulted lease cannot enter the workshop through this path. Starting the ticket flips the vehicle's `vehicle_status` to `IN_SHOP`. The same `VendorOps` user closes the ticket from `IN_SHOP` to `CLOSED` by supplying the final `actual_cents`; closure requires `actual_cents` to be strictly greater than zero (a value of zero is rejected with `ERR_ACTUAL_COST_REQUIRED`). On closure, the vehicle is restored to its prior workflow state — `ALLOCATED` if the vehicle is currently tied to a `current_lease_id`, otherwise `GROUNDED`. A `FleetManager` may also cancel a ticket that is still `OPEN`, sending it to `CANCELLED` with no further side effects; tickets that have already entered `IN_SHOP` may no longer be cancelled and must be closed instead.

### 3.6. Mileage Overage Settlement

Mileage overages are accounted on a per-calendar-month basis through `OverageSettlement` rows. A `FleetManager` creates a settlement by supplying `lease_agreement_id`, `period_year` (an integer in the 2000-to-2099 range inclusive), and `period_month` (an integer 1 through 12 inclusive). A duplicate row for the same combination of lease, year, and month is forbidden: zero existing rows are allowed, but one existing row blocks creation with `ERR_DUPLICATE_SETTLEMENT_PERIOD`. A draft row is also synthesised automatically when a lease begins its return phase — that synthesised row covers the partial last month between the prior period's end and the return-begin instant. A newly created or synthesised settlement is in `DRAFT` (the row's `settlement_status` field), with `provisional_overage_miles`, `final_overage_miles`, `provisional_balance_cents`, and `balance_cents` initialised by the calculation described below.

The calculation has two variants, provisional and final, which share most of their structure but differ in which telematics events define the period's end. To compute either variant, the system first resolves the period's odometer endpoints. The period's start odometer is the `odometer_reading` of the latest `ACCEPTED` telematics event whose `event_ts` is at or before the first day of the period at midnight UTC; if no such event exists, the start odometer falls back to the vehicle's `odometer_baseline_miles`. For the provisional variant — the one used while the row is in `DRAFT` and also on read-through when retrieving the settlement — the period's end odometer is the latest `ACCEPTED` event for the vehicle taken as of the current wall-clock, which may extend past the calendar end of the period (this is the forward-looking variant; it deliberately admits readings beyond the period boundary so a mid-period preview reflects the most recent telemetry). For the final variant — the one used by finalisation — the period's end odometer is the largest `odometer_reading` among `ACCEPTED` events whose `event_ts` is at or before the last instant of the period (the last day at twenty-three hours, fifty-nine minutes, fifty-nine seconds and nine-hundred-ninety-nine milliseconds UTC). The period miles equal the end odometer minus the start odometer, floored at zero when negative. The overage miles are then the period miles minus the lease's `monthly_mileage_allowance`, floored at zero.

Pricing then branches on `tiered_overage_enabled`. When the flag is false, the row's money figure is simply the overage miles multiplied by the lease's `overage_rate_cents_per_mile`. When the flag is true, the overage miles are split across three tiers with breakpoints at five-hundred miles and at two-thousand miles: the first tier covers overage miles from zero up to but not including five-hundred and charges at the base `overage_rate_cents_per_mile`; the second tier covers overage miles from five-hundred up to but not including two-thousand and charges at the base rate multiplied by 12500 basis points and divided by ten thousand (which is one-and-a-quarter times the base rate); the third tier covers all overage miles at or above two-thousand and charges at the base rate multiplied by 15000 basis points and divided by ten thousand (which is one-and-a-half times the base rate). The number of miles in each tier is computed by clipping the overall overage to the tier's bounds: the first-tier miles are the overage miles capped at five-hundred; the second-tier miles are the overage miles capped at two-thousand and then reduced by five-hundred, floored at zero; the third-tier miles are the overage miles minus two-thousand, floored at zero. Within each tier the system multiplies the tier's miles by its rate (which, for the second and third tiers, involves the basis-point divisor of ten thousand), rounds the resulting cents half-up, and only then sums the three rounded tier totals to produce the row's money figure. The first tier — whose effective rate equals the integer base rate — needs no rounding because its product is already an integer. Summing un-rounded values and rounding at the end is forbidden; the per-line-item-then-sum order is the contracted convention.

For the provisional variant the resulting overage miles and balance write into `provisional_overage_miles` and `provisional_balance_cents`. For the final variant they write into `final_overage_miles` and `balance_cents`. Finalisation by a `FleetManager` advances the row from `DRAFT` to `FINAL`, recomputes the final variant, and adds the final overage miles to the lease's running `cumulative_overage_miles`. Two finalise calls landing simultaneously on the same row serialise on the settlement-state flip; the loser is rejected with `ERR_INVALID_STATE` because by the time it reaches the state-machine check the row has already advanced past `DRAFT`.

A `FleetManager` may then mark a finalised settlement as paid, which advances it from `FINAL` to `PAID` and subtracts the row's `balance_cents` from the owning lessee's `outstanding_balance_cents`. Alternatively, the lessee themselves may dispute a finalised settlement, advancing it from `FINAL` to `DISPUTED`. The dispute path is exclusive to the `Lessee` role and is further gated by ownership (`X-User-ID` must equal the parent lease's `lessee_id`, else `ERR_FORBIDDEN`) and by a time window: the current clock must be at or before the row's `created_at` plus the dispute window in days (a non-strict upper bound — equality is permitted). A dispute lodged strictly after that point is rejected with `ERR_DISPUTE_WINDOW_CLOSED`. A disputed settlement does not reduce the lessee's balance — that subtraction happens only on the paid transition.

### 3.7. Collision Claims with Revision Cycles

A `CollisionClaim` is filed against a lease's `lease_id` by either a `FleetManager` or a `VendorOps` user. The payload carries `incident_ts` (the wall-clock moment of the collision) and an initial `estimate_cents` (a non-negative integer from the vendor). The system copies the lease's `vehicle_id` onto the claim as an immutable stamp at create time and increments `collision_open_count` on the parent lease by one. The claim is born in `FILED` with `revised_estimate_cents` of zero, `lessee_deductible_cents` of zero, and `revision_round` of zero.

A `ClaimAdjuster` then begins reviewing the claim, advancing it from `FILED` to `UNDER_REVIEW`; this transition requires the parent lease to be in either `ACTIVE` or `IN_RETURN` (a defaulted or closed lease cannot have its claims progressed) and has no further side effects beyond the state flip. From under review, the adjuster has three options: approve the claim outright, reject it outright, or request a revision from the vendor.

Requesting a revision advances the claim from `UNDER_REVIEW` to `REVISION_REQUESTED` and increments `revision_round` by one. The transition is bounded by a hard cap: `revision_round` must be strictly less than the configured maximum revision rounds at the moment of the request, and a request that would push the counter to or past that limit is rejected with `ERR_REVISION_LIMIT_REACHED`. A `VendorOps` user replies with a revised estimate via the PATCH path on the claim, supplying a strictly positive `revised_estimate_cents` along with the optional `version` for optimistic concurrency. A successful PATCH cycles the claim back from `REVISION_REQUESTED` to `UNDER_REVIEW`, leaving the next adjudication decision open to the adjuster. A PATCH whose body carries a `version` mismatching the stored value is rejected with `ERR_VERSION_CONFLICT`; one that races with another state-changing call on the same claim is also serialised by the `version` mechanism, and the loser receives the same `ERR_VERSION_CONFLICT`.

Rejection from `UNDER_REVIEW` advances the claim to `REJECTED` and decrements the parent lease's `collision_open_count` by one with no money side effects. Approval likewise advances the claim from `UNDER_REVIEW` to `APPROVED` and decrements `collision_open_count` by one, but additionally computes and stores the lessee's `lessee_deductible_cents` per the collision settlement rule described next, and adds that amount to the owning lessee's `outstanding_balance_cents`.

The deductible calculation starts from the relevant estimate: if no revision was ever supplied (`revised_estimate_cents` is zero) the system uses the original `estimate_cents`; otherwise it uses the revised value. That raw figure is capped at a fixed two-thousand-five-hundred-dollar (two-hundred-and-fifty-thousand-cent) deductible ceiling — anything above the cap is absorbed by the fleet operator. The capped amount is then conditionally discounted by twenty-five percent (twenty-five hundred basis points): the discount applies only when the claim went through at least one revision round (`revision_round` is at least one and `revised_estimate_cents` is strictly positive) *and* the vehicle's telematics history contains no non-empty `fault_code` in the window strictly after `incident_ts` minus twenty-four hours up to and including `incident_ts` itself (the window is left-exclusive and right-inclusive, and only `ACCEPTED` telematics on the same `vehicle_id` count). If both conditions hold, the system multiplies the capped figure by (10000 minus 2500) basis points and divides by ten thousand, rounds the result half-up to whole cents, and stores that as the final `lessee_deductible_cents`. If either condition fails — there was no revision cycle, or there was a fault code in the look-back window — the raw capped figure becomes the deductible without discount. Approval is otherwise unconditional from `UNDER_REVIEW`.

The interaction between collisions and lease return is structural: a `FleetManager` may not begin a lease's return phase while any collision claim on that lease remains in a non-terminal state. The `collision_open_count` field counts exactly those claims whose `claim_status` is not in the set `APPROVED` or `REJECTED`; when the field is positive, beginning return is rejected with `ERR_OPEN_COLLISION_BLOCKS_RETURN`.

### 3.8. Lease Return and Closure

Once a lease is ready to wind down, a `FleetManager` advances it from `ACTIVE` to `IN_RETURN`. The transition requires the lease to currently be `ACTIVE` and `collision_open_count` to be exactly zero, and it has two side effects: the underlying vehicle's `vehicle_status` is flipped to `IN_SHOP` (for end-of-lease inspection and reconditioning), and a draft final-month `OverageSettlement` is synthesised covering the partial month between the last finalised settlement's period and the current instant.

Finalising the return then closes the lease, advancing it from `IN_RETURN` to `CLOSED`. The preconditions are deliberately strict: the lease must currently be `IN_RETURN`; every `MaintenanceTicket` on the vehicle must be either `CLOSED` or `CANCELLED` (no work-in-progress); and every `OverageSettlement` on the lease must be either `PAID`, `DISPUTED`, or in `FINAL` with `balance_cents` of zero. If any of these preconditions fail, the call is rejected with `ERR_VEHICLE_NOT_RETURNABLE`. On success, the underlying vehicle is restored to `AVAILABLE`, its `current_lease_id` is set to null, and every `FuelCard` issued under that lease is moved to its closed state — the card may no longer be used after lease closure regardless of its prior `card_status`.

The alternative terminal state for a lease is `DEFAULTED`, reached not by a deliberate command on the lease itself but by the cascade out of a lessee suspension. A `FleetManager` may suspend a lessee whose `outstanding_balance_cents` has reached or crossed the suspend threshold; on suspension, the lessee's `account_status` flips to `SUSPENDED`, and the system then walks every `ACTIVE` lease the lessee owns and, for each one where `outstanding_balance_cents` has reached or crossed the (strictly higher) default threshold, flips that lease's `lease_state` to `DEFAULTED`, moves the underlying vehicle to `GROUNDED`, and blocks every `FuelCard` under that lease (`card_status` flips to `BLOCKED`). Reinstatement reverses the lessee step alone: the `FleetManager` may move the lessee back from `SUSPENDED` to `ACTIVE` if and only if `outstanding_balance_cents` has fallen strictly below the suspend threshold; reinstatement has no cascade and does not automatically un-default any lease.

### 3.9. IFTA Quarterly Filing

For IFTA accounting the system models a separate `IFTAQuarter` row per lessee per (year, quarter) pair. A `TaxAdmin` opens a quarter on a lessee by supplying `year` (an integer 2000 to 2099 inclusive) and `quarter` (an integer 1 to 4 inclusive); the row is born in `OPEN` (the `filing_status` field) with `total_taxable_gallons` and `total_tax_cents` initialised to zero.

Preparation by a `TaxAdmin` advances the quarter from `OPEN` to `READY` and recomputes both totals. The transition is temporally gated: the call may run only when the current clock is at or after the last instant of the quarter — preparing a quarter that has not yet ended is rejected with `ERR_QUARTER_NOT_READY`. Filing the prepared quarter then advances it from `READY` to `CLOSED`, and as its side effect the system iterates every `POSTED` `FuelCardTransaction` in the quarter window whose `ifta_eligible` is true and flips each one's `txn_status` from `POSTED` to `IFTA_INCLUDED`. Those transactions are then immutable: no reversal, no further mutation. Once closed, the quarter accepts no new IFTA-influencing activity in its window; new transactions whose `posted_at` falls inside a closed quarter are rejected with `ERR_QUARTER_CLOSED`, and a quarter cannot be reopened.

The IFTA computation itself runs at preparation time and is the system's most arithmetically precise rule. Inputs are scoped to one lessee and one (year, quarter): the window runs from the first day of the quarter at midnight UTC through the last day at twenty-three hours, fifty-nine minutes, fifty-nine seconds and nine-hundred-ninety-nine milliseconds UTC. Within this window the system collects every `FuelCardTransaction` whose parent `FuelCard` belongs to a lease owned by this lessee, whose `txn_status` is `POSTED` (`REVERSED` and `IFTA_INCLUDED` are excluded), and whose `ifta_eligible` is true. When ordering matters — for example when reconstructing a per-jurisdiction trace — the system uses `posted_at` ascending, then `id` ascending as the tie-breaker.

From those transactions the system groups by `jurisdiction` and sums the `gallons` field within each group, giving a per-jurisdiction gallon count. The `total_taxable_gallons` field on the quarter is the sum of those per-jurisdiction counts (which, by group-then-sum identity, is also the simple sum of `gallons` across the entire eligible set). The system then computes a per-jurisdiction tax owed: for each jurisdiction `j`, multiply that jurisdiction's gallons by the configured per-jurisdiction rate in cents-per-gallon (the rates are `CA` = 87, `TX` = 20, `NY` = 45, `IL` = 47, `FL` = 36, `OH` = 47, `PA` = 75, `GA` = 32, `WA` = 49, and `AZ` = 26), round the resulting cents half-up to a whole cent, and add the rounded amount to a running tax-owed total. The system separately computes a tax credit, which is granted at the rate of the lessee's `base_jurisdiction` applied uniformly to the entire `total_taxable_gallons` regardless of where the fuel was bought: multiply `total_taxable_gallons` by the base-jurisdiction rate from the same table, then round that result half-up to a whole cent. The quarter's `total_tax_cents` is the tax-owed total minus the tax-credit value; the result is a signed integer, where a positive value means money owed by the lessee to the IFTA authority and a negative value means a refund owed to the lessee. The rounding order is contractual: each jurisdiction's owed amount is rounded individually before being added into the owed total, and the credit is rounded once after multiplication; summing un-rounded amounts and rounding once at the end is the explicitly forbidden anti-pattern.

### 3.10. Time-Travel for Time-Gated Tests

Time-gated rules — the dispute window on an overage settlement, the quarter-end check on IFTA prepare — are evaluated against a clock the system itself controls so that test scenarios can be deterministic. An admin-only test-driving capability advances the system clock to a supplied target instant `to` (an ISO 8601 UTC timestamp); the operation is idempotent in the past direction, meaning a `to` value at or before the current logical time is a no-op and is not treated as an error. The capability is restricted to `FleetManager` and `TaxAdmin` callers and is the only mechanism through which the logical clock changes; outside of this advance, the clock progresses with wall time.

## 4. Endpoint Definitions

All endpoints emit JSON bodies wrapped in the standard envelope of §2.2. Endpoints that create a new resource return HTTP 201 with the newly created resource in `data`; endpoints that mutate or read an existing resource return HTTP 200. Validation, authentication, authorisation, and state-machine errors are surfaced as the appropriate 4xx status described in §5.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/lessees` | Register a new lessee. | FleetManager |
| GET | `/lessees/{id}` | Retrieve a lessee. | FleetManager, TaxAdmin, ClaimAdjuster, VendorOps, Lessee |
| POST | `/lessees/{id}/suspend` | Suspend the lessee; may cascade to defaulted leases. | FleetManager |
| POST | `/lessees/{id}/reinstate` | Reinstate a suspended lessee. | FleetManager |
| POST | `/vehicles` | Add a vehicle to the fleet. | FleetManager |
| GET | `/vehicles/{id}` | Retrieve a vehicle. | FleetManager, TaxAdmin, ClaimAdjuster, VendorOps |
| POST | `/vehicles/{id}/telematics-events` | Post a telematics event; drives odometer reconciliation. | FleetManager, VendorOps |
| POST | `/lease-agreements` | Draft a lease agreement. | FleetManager |
| GET | `/lease-agreements/{id}` | Retrieve a lease agreement. | FleetManager, TaxAdmin, ClaimAdjuster, VendorOps, Lessee |
| POST | `/lease-agreements/{id}/activate` | Allocate the lease's vehicle and move lease to active. | FleetManager |
| POST | `/lease-agreements/{id}/begin-return` | Move the lease to the return phase. | FleetManager |
| POST | `/lease-agreements/{id}/finalize-return` | Close the lease when preconditions are met. | FleetManager |
| POST | `/lease-agreements/{lease_id}/fuel-cards` | Issue a fuel card under a lease. | FleetManager |
| GET | `/fuel-cards/{id}` | Retrieve a fuel card. | FleetManager, TaxAdmin, VendorOps, Lessee |
| POST | `/fuel-card-transactions` | Post a fuel transaction. | FleetManager, VendorOps |
| POST | `/fuel-card-transactions/{id}/reverse` | Reverse a posted transaction. | FleetManager |
| POST | `/vehicles/{vehicle_id}/maintenance-tickets` | Open a maintenance ticket. | FleetManager, VendorOps |
| POST | `/maintenance-tickets/{id}/start` | Vendor starts the work. | VendorOps |
| POST | `/maintenance-tickets/{id}/close` | Vendor closes the ticket with `actual_cents`. | VendorOps |
| POST | `/maintenance-tickets/{id}/cancel` | Cancel an open ticket. | FleetManager |
| POST | `/lease-agreements/{lease_id}/collision-claims` | File a collision claim. | FleetManager, VendorOps |
| POST | `/collision-claims/{id}/start-review` | Begin adjudication of a filed claim. | ClaimAdjuster |
| POST | `/collision-claims/{id}/request-revision` | Send the claim back for a revised estimate. | ClaimAdjuster |
| PATCH | `/collision-claims/{id}` | Submit a revised estimate with optional `version`. | VendorOps |
| POST | `/collision-claims/{id}/approve` | Approve the claim and compute the lessee deductible. | ClaimAdjuster |
| POST | `/collision-claims/{id}/reject` | Reject the claim under review. | ClaimAdjuster |
| POST | `/overage-settlements` | Create a draft overage settlement for a lease and month. | FleetManager |
| GET | `/overage-settlements/{id}` | Retrieve a settlement with provisional and (if finalised) final values. | FleetManager, TaxAdmin, Lessee |
| POST | `/overage-settlements/{id}/finalize` | Finalise a draft settlement. | FleetManager |
| POST | `/overage-settlements/{id}/mark-paid` | Mark a finalised settlement as paid. | FleetManager |
| POST | `/overage-settlements/{id}/dispute` | Lessee disputes a finalised settlement within the dispute window. | Lessee |
| POST | `/lessees/{lessee_id}/ifta-quarters` | Open an IFTA quarter for a lessee. | TaxAdmin |
| GET | `/ifta-quarters/{id}` | Retrieve an IFTA quarter with computed totals. | FleetManager, TaxAdmin |
| POST | `/ifta-quarters/{id}/prepare` | Recompute totals from eligible fuel transactions. | TaxAdmin |
| POST | `/ifta-quarters/{id}/file` | File the quarter; locks eligible transactions. | TaxAdmin |
| POST | `/_clock/advance` | Test-only — advance the logical clock to a supplied `to` instant. | FleetManager, TaxAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_AUTH_REQUIRED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_VERSION_CONFLICT` | 409 |
| `ERR_VALIDATION` | 422 |
| `ERR_VEHICLE_ALREADY_ALLOCATED` | 409 |
| `ERR_OPEN_COLLISION_BLOCKS_RETURN` | 409 |
| `ERR_CARD_INACTIVE` | 409 |
| `ERR_QUARTER_CLOSED` | 409 |
| `ERR_QUARTER_NOT_READY` | 409 |
| `ERR_REVISION_LIMIT_REACHED` | 422 |
| `ERR_CARD_LIMIT_EXCEEDED` | 422 |
| `ERR_DISPUTE_WINDOW_CLOSED` | 409 |
| `ERR_DUPLICATE_SETTLEMENT_PERIOD` | 409 |
| `ERR_ACTUAL_COST_REQUIRED` | 422 |
| `ERR_VEHICLE_NOT_RETURNABLE` | 409 |
