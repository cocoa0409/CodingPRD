# Vault Cash & Federal Reserve Currency Ordering API — Product Requirements Document

## 1. Introduction

Community and regional banks operate a quiet but unforgiving discipline: every branch and central vault must hold enough physical currency to serve customers, yet every dollar sitting in a vault is both unproductive and a regulatory/insurance exposure. Cash moves in from the Federal Reserve, out to ATMs, back through fitness sorting, and occasionally into the hands of the Secret Service when counterfeit notes surface. Each of those movements must be booked, reconciled, and defensible in an audit.

This document specifies the Vault Cash & Federal Reserve Currency Ordering API, the system of record for that discipline. It covers the full cash lifecycle across a bank's vault sites: ordering currency from the Federal Reserve and depositing surplus or unfit notes back; scheduling and tracking armored-carrier shipments between the Fed, vaults, and branches; forecasting ATM cash demand (including holiday and seasonal surges); sorting unfit currency and recovering fit notes; detecting, seizing, and reporting counterfeit currency under segregation of duties; and reconciling physical counts against the book of record every business day.

The system is designed around an append-only cash ledger per site. Every physical or administrative movement posts a ledger entry, and every derived quantity — on-hand fit and unfit balances, committed inbound exposure, insurance headroom, vault posture — is recomputed from the ledger and related state. Reconciliation is continuous, not periodic: a physical count is compared against both a provisional expectation frozen when the day is opened and a final expectation that keeps absorbing late, backdated ledger entries. The result is a vault operation that can prove, for any value date, exactly where every cent was supposed to be and where it actually was.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` identifying the acting principal, and `X-User-Role` naming the role under which the principal acts. A request missing either header, naming an undeclared role, or presenting an entity-backed `X-User-ID` that does not resolve to an existing, active identity record is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). If authentication succeeds but the role is not listed among the endpoint's permitted roles, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The declared roles, spelled exactly as the server expects them, are:

- `CashOperationsAdmin` — bank cash-operations administrator. Configures vault sites, staff, carriers, ATMs, and seasonal windows; approves escalated reconciliation variances; and drives the logical clock. When `X-User-Role` is `CashOperationsAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `approved_by_staff_id` on a `Reconciliation` where a transition writes it) but does not compare it to any entity's `id`.
- `VaultCustodian` — site-scoped vault custodian responsible for fitness sorting, physical counts, ledger adjustments, and counterfeit seizure. When `X-User-Role` is `VaultCustodian`, `X-User-ID` is the `id` of the acting `StaffMember`; ownership checks on any resource that references a `StaffMember` compare the resource's foreign-key field to `X-User-ID`, and the staff member's `home_site_id` must equal the target resource's site.
- `FedCoordinator` — site-scoped Federal Reserve ordering desk operator who runs the order lifecycle, records Fed advices, and schedules and loads shipments. Identity is entity-backed: `X-User-ID` is the `id` of the acting `StaffMember`, and the staff member's `home_site_id` must equal the target resource's site.
- `CarrierDispatcher` — armored carrier dispatcher who departs and verifies shipments belonging to their carrier. When `X-User-Role` is `CarrierDispatcher`, `X-User-ID` is the `id` of the acting `Carrier`; a dispatcher may only depart or verify a shipment whose `carrier_id` equals `X-User-ID`, and a mismatch is rejected with `ERR_RESOURCE_OWNERSHIP_VIOLATION` (HTTP 403).
- `AtmAnalyst` — site-scoped ATM cash analyst responsible for forecasting, loads, settlement, and service toggles. Identity is entity-backed: `X-User-ID` is the `id` of the acting `StaffMember`, scoped by `home_site_id`.
- `ComplianceOfficer` — site-scoped compliance officer who reports, releases, and settles counterfeit cases under segregation from the seizer. Identity is entity-backed: `X-User-ID` is the `id` of the acting `StaffMember`, scoped by `home_site_id`.

Site-scoped staff roles — `VaultCustodian`, `FedCoordinator`, `AtmAnalyst`, and `ComplianceOfficer` — may act only on resources belonging to their home site; acting on a resource of another site is rejected with `ERR_SITE_SCOPE_VIOLATION` (HTTP 403). The `CashOperationsAdmin` role is global and has no site scope. A `StaffMember` whose `active` flag is `false` is rejected at authentication as if the identity did not exist.

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

All list endpoints accept two query parameters: `limit` and `offset`. The `limit` parameter defaults to 10, with a minimum of 1 and a maximum of 100; a `limit` outside that range is rejected with `ERR_INVALID_REQUEST` (HTTP 400). The `offset` parameter defaults to 0. Results are always sorted by `created_at` ascending. The `meta` object of a list response includes the fields `limit`, `offset`, `total_count`, and `has_more`, where `has_more` indicates whether additional results exist beyond the current page.

### 2.4. The Logical Clock and Monetary Units

All money in the system is represented as integer cents; no fractional cents ever appear. Dates are strings in `YYYY-MM-DD` format, and datetimes are ISO 8601 UTC. Time-dependent rules — the Fed order submission cutoff, counterfeit reporting deadlines, seasonal window membership, the business date stamped on ledger entries — are all evaluated against a server-side logical clock, never the wall clock. The logical clock starts at exactly 2026-08-01T00:00:00Z before any call is made, and a `CashOperationsAdmin` advances it via an admin-only test-driving capability that sets the current instant to a supplied `to_iso8601` value. Advancing the clock re-derives the posture of any site holding a `SEIZED` counterfeit case, since deadline pressure changes as time passes.

### 2.5. Common Resource Properties

Every resource carries an `id` that is a server-minted UUID with no type prefix. Resources created with full audit fields — `VaultSite`, `StaffMember`, `Carrier`, `AtmMachine`, `SeasonalWindow`, `FedOrder`, `CashShipment`, `FitnessBatch`, `CounterfeitCase`, `Reconciliation`, and `AtmForecast` — additionally carry `created_at` (ISO 8601 UTC with three fractional digits), `updated_at` (same format, refreshed on every mutation), and `version`, an integer starting at 1 that increments by 1 on every mutation of the resource, including system-driven mutations. Two resource types are intentionally lighter: `DenominationLine` and `CashLedgerEntry` carry only `id` and `created_at` — both `updated_at` and `version` are absent on those two types.

Where an endpoint addresses a specific resource in its path, the path parameter names used throughout this document and the endpoint table are `siteId` for a vault site, `staffId` for a staff member, `carrierId` for a carrier, `atmId` for an ATM, `windowId` for a seasonal window, `orderId` for a Fed order, `shipmentId` for a shipment, `batchId` for a fitness batch, `caseId` for a counterfeit case, `entryId` for a ledger entry, `reconId` for a reconciliation, and `forecastId` for a forecast. Path identifiers are validated left to right per §2.8.

### 2.6. Precision and Rounding

All monetary arithmetic is performed in integer cents. Where a calculation divides or applies a fractional weight, the rounding rule is round-half-up to the nearest integer cent, applied at the exact step the rule prescribes and never deferred or aggregated across steps. The two load-bearing instances are the Fed service fee (each denomination line's fee is rounded half-up to integer cents individually, and only then summed — summing the raw line values first and rounding once is a different, forbidden result) and the ATM forecast projections (round-half-up applied when computing the weighted base and again when applying a seasonal multiplier).

### 2.7. Optimistic Concurrency Control

Three write operations require the caller to supply the version of a parent entity it last observed, and reject the write when the entity has since advanced:

- Publishing a forecast for an ATM requires `expected_atm_version` matching the ATM's current `version`. A publish carrying a stale value — one older than the ATM's current version because another publish has legitimately advanced it — is rejected with `ERR_STALE_ATM_VERSION` (HTTP 412), preventing the client from superseding a forecast it has not observed.
- Updating a vault site's limits or capacity requires `expected_vault_site_version` matching the site's current `version`. Any mutation — a previous patch, a ledger-driven recompute, a posture flip — advances the version, so a patch carrying an older value is rejected with `ERR_STALE_VAULT_SITE_VERSION` (HTTP 412).
- Adding a denomination line to a draft Fed order requires `expected_fed_order_version` matching the order's current `version`. A line-add carrying an older value is rejected with `ERR_STALE_FED_ORDER_VERSION` (HTTP 412) so that draft edits serialize.

No other endpoint takes a version field.

### 2.8. Validation Order and Nested Resources

When a request fails several rules at once, the server reports the first failure in a fixed evaluation order: authentication context first (missing or invalid headers, then role permission, then site-scope or carrier ownership), then existence of path identifiers validated left-to-right along the URL, then existence of body-referenced foreign keys (`site_id`, `atm_id`, `carrier_id`, `fed_order_id`, `fitness_batch_id`), then request shape and uniqueness (`ERR_INVALID_REQUEST` for missing or mistyped fields, invalid enum members, or an end date before its start date), then the target resource's own state machine, then cross-entity state guards, then segregation-of-duties checks, then business rules (insurance headroom, cutoff and scheduling windows, denomination mix, fiscal sufficiency). Path-parameter identifiers that do not resolve produce the resource-specific not-found error — for example `ERR_VAULT_SITE_NOT_FOUND`, `ERR_FED_ORDER_NOT_FOUND`, or `ERR_SHIPMENT_NOT_FOUND` — each at HTTP 404.

### 2.9. Vault Posture: NORMAL, ELEVATED, FROZEN

Every vault site carries a derived `posture` that summarizes its risk position and gates certain operations. The derivation uses integer cross-multiplication only — no percentage rounding anywhere:

- The posture is `FROZEN` when `on_hand_total_cents` is greater than or equal to `vault_limit_cents`, or when `insurance_headroom_cents` is less than or equal to zero, or when the site holds any counterfeit case still in `SEIZED` status whose `seized_at` is more than 10 days before the current logical clock.
- Otherwise the posture is `ELEVATED` when `on_hand_total_cents` multiplied by 10 is greater than or equal to `vault_limit_cents` multiplied by 9 — meaning exactly 90.000% utilization trips `ELEVATED` — or when the site holds any `SEIZED` counterfeit case whose `seized_at` is more than 5 days before the current clock, or when the site has any reconciliation in `ESCALATED` status.
- Otherwise the posture is `NORMAL`.

Posture is re-derived on every event that changes on-hand balances, in-transit or pending inbound exposure, insurance fields, counterfeit case seize/report/release/settle, and reconciliation escalation or lock. A `FROZEN` posture blocks three operations — Fed order submission, shipment loading, and fitness batch creation — each rejected with `ERR_VAULT_FROZEN` (HTTP 409).

### 2.10. The Ledger, Derived Balances, and Cascading Recompute

Every physical or administrative cash movement posts a `CashLedgerEntry` against a site with a signed amount in cents, a `bucket` of `FIT` or `UNFIT`, and a value date. The ledger is append-only; there is no edit or delete. A site's `on_hand_fit_cents` and `on_hand_unfit_cents` are mutated only through ledger-driven recompute — never by direct writes — and `on_hand_total_cents` is always their sum. Three more derived fields track exposure: `reserved_out_cents` holds the value reserved by `SCHEDULED` or `LOADED` outbound shipments not yet departed; `in_transit_inbound_cents` holds the declared value of inbound shipments in `LOADED` or `IN_TRANSIT`; and `pending_inbound_order_cents` holds the face value of `ORDER`-direction Fed orders in `SUBMITTED`, `ACKNOWLEDGED`, or `IN_TRANSIT`. Whenever a ledger entry is appended, the owning site's totals re-derive, its posture re-derives, and any matching reconciliation in `OPEN` or `COUNTED` status refreshes its final expected balance and variance — which may flip its status, as described in §3.8.

## 3. Business Logic & Workflows

### 3.1. Establishing the Operation: Sites, Staff, Carriers, and Seasonal Windows

A `CashOperationsAdmin` begins by creating a vault site with its `name`, a `site_type` of `CENTRAL` or `BRANCH`, the regulatory `vault_limit_cents` cap, the `insurance_coverage_cents` policy ceiling, and a `dock_capacity` of at least 1 governing how many inbound shipments may share an arrival instant (each arrival occupies a window extending 30 minutes before and after its scheduled time). Optional `opening_fit_cents` and `opening_unfit_cents` seed the vault; nonzero openings post `OPENING_BALANCE` ledger entries value-dated to the current logical clock date, and the site's posture is derived immediately. The site is created with `version` equal to 1. Later, the administrator may patch the site's `vault_limit_cents`, `insurance_coverage_cents`, `dock_capacity`, or `name`; each successful patch increments the site version by 1 and re-derives posture and `insurance_headroom_cents`, and the patch must carry `expected_vault_site_version` per §2.7.

Staff onboarding anchors the site-scoped roles: registering a staff member records `full_name`, the `home_site_id` that scopes everything they touch, and an `active` flag defaulting to `true`. Armored carriers are registered with a `name` and a `liability_cap_per_truck_cents` ceiling on the declared value any one truck may carry; a carrier's `status` starts as `ACTIVE` and an administrator may later suspend or reinstate it by patching `status` to `SUSPENDED` or back, incrementing the carrier's version. A suspended carrier cannot take new shipments — shipment creation and truck loading both require the carrier to be `ACTIVE`, failing with `ERR_CARRIER_SUSPENDED` otherwise.

Holiday and seasonal demand planning is expressed through `SeasonalWindow` records per site, each with a `name`, an inclusive `start_date`, an inclusive `end_date` that must be on or after the start date, and a `multiplier_bps` strictly greater than 10000 expressing the demand uplift in basis points. Windows of one site must be disjoint as closed intervals; adjacency — one window's start falling exactly one day after another's end — is allowed, but any true overlap is rejected with `ERR_SEASONAL_WINDOW_OVERLAP` (HTTP 409).

### 3.2. Ordering Currency from the Federal Reserve

A `FedCoordinator` builds an order in two stages. First an empty `FedOrder` is created with its `site_id`, a `direction` of `ORDER` (cash coming in from the Fed) or `DEPOSIT` (cash going out to the Fed), and a `business_date` on which the order settles; it starts in `DRAFT` with version 1. Then the coordinator adds denomination lines one at a time, each carrying a `denomination_cents` face value — one of 100, 200, 500, 1000, 2000, 5000, or 10000 cents — and a `strap_count` of at least 1, where each strap holds 100 notes. For an `ORDER`-direction request the bundle rules of the Fed apply: denominations of 2000 cents or below must be requested in multiples of 10 straps, and denominations of 5000 cents or above in multiples of 5 straps; a `DEPOSIT` accepts any strap count of at least 1. A bad denomination, a strap count below 1, or a bundle-multiple violation is rejected with `ERR_INVALID_DENOMINATION_MIX` (HTTP 422). Each line-add mutates the draft order and must carry `expected_fed_order_version` per §2.7; lines may only be added while the order is `DRAFT`, otherwise `ERR_FED_ORDER_INVALID_STATE` (HTTP 409).

Every line's face value `line_cents` is computed exactly as its denomination times 100 notes per strap times its strap count, and the order's `face_total_cents` is the plain integer sum of all line values — zero lines means a face total of zero. The Fed's service fee is charged per line at one one-hundred-sixtieth of the line's value (0.625%), with each line's `fee_cents` rounded half-up to integer cents individually and only then summed into `fee_total_cents`. This pinned order matters: two lines of 10,000 cents each yield per-line fees of 63 and 63 for a total of 126 cents, whereas summing first and rounding once would incorrectly give 125. The order's `grand_total_cents` is the face total plus the fee total.

Submitting the order moves it `DRAFT → SUBMITTED` and is the most heavily guarded step in the lifecycle. The order must currently be `DRAFT` and must contain at least one denomination line — submitting an empty order fails with `ERR_ORDER_HAS_NO_LINES` (HTTP 422). The site's posture must not be `FROZEN`. The submission cutoff is strict: the current logical clock must be earlier than 18:00:00Z on the day before the order's `business_date`, or the submission is rejected with `ERR_ORDER_CUTOFF_PASSED` (HTTP 422). Beyond those, the guards fork by direction. For an `ORDER`, the face total must not exceed the site's `insurance_headroom_cents` (see §3.3), failing with `ERR_INSURANCE_HEADROOM_EXCEEDED` (HTTP 402), and the site's `on_hand_total_cents` plus the face total must not exceed `vault_limit_cents`, failing with `ERR_VAULT_LIMIT_EXCEEDED` (HTTP 402). For a `DEPOSIT`, the face total must not exceed the site's combined fit plus unfit cash on hand — deposits draw from the `UNFIT` bucket first and then the `FIT` bucket — failing with `ERR_INSUFFICIENT_CASH_FOR_DEPOSIT` (HTTP 422). A successful submission increments the order's version, and for an `ORDER` it adds the face total to the site's `pending_inbound_order_cents`, re-deriving the site's totals and posture and incrementing the site version.

While in `SUBMITTED`, the coordinator may still recall the order — `SUBMITTED → DRAFT` — which releases the pending-inbound exposure for an `ORDER` and allows editing and resubmission; or record the Fed's acknowledgement — `SUBMITTED → ACKNOWLEDGED`. Cancellation is allowed from either `DRAFT` or `SUBMITTED` and moves the order to the terminal `CANCELLED` state, releasing pending inbound exposure when a `SUBMITTED` `ORDER` is cancelled; cancelling beyond `SUBMITTED` is impossible and fails with `ERR_FED_ORDER_INVALID_STATE`. Each of these transitions increments the order's version.

Once a linked shipment departs, the order moves `ACKNOWLEDGED → IN_TRANSIT` automatically, and once that shipment is verified — whether matched or exception-accepted — the order moves `IN_TRANSIT → RECEIVED`. The settlement conversation happens through Fed advices: recording an advice with a `counted_total_cents` equal to the order's `face_total_cents` moves it to the terminal `RECONCILED` state, while a mismatched count moves it `RECEIVED → DISPUTED`. Advices may be recorded only from `RECEIVED` or `DISPUTED`. Every advice increments `advice_count` by 1 and the order version by 1. Each advice resets `settled_basis_cents` to the advice's `counted_total_cents`, and the effective basis for the next comparison is `settled_basis_cents` when set, otherwise `face_total_cents`. When the delta between an advice's counted total and the effective basis is nonzero, that signed delta posts an `ADJUSTMENT` ledger entry in the `FIT` bucket value-dated to the current clock date; the ledger append then triggers the site on-hand recompute, and that recompute cascades to a reconciliation refresh and posture re-derivation per §2.10. A repeated mismatched advice on an already `DISPUTED` order is a self-loop — the order stays `DISPUTED`, `advice_count` increments again, the delta is measured against the previously settled basis, and any nonzero delta books and cascades the same way. Note that a shipment exception-accept also writes `settled_basis_cents` directly (§3.4), so a subsequent advice's delta is measured from the counted value, not the original face.

### 3.3. Insurance Headroom and Committed Exposure

The insurance policy ceiling applies not just to cash physically on site but to everything the bank has committed to receive. The evaluation order is pinned to avoid circularity: committed exposure is `on_hand_total_cents` plus `in_transit_inbound_cents` plus `pending_inbound_order_cents`, deliberately excluding the candidate order or shipment under evaluation because it is not yet committed; headroom is `insurance_coverage_cents` minus that committed exposure; and the candidate is admitted when its value is less than or equal to headroom — an exact fit is allowed. Headroom is never re-derived after admitting a candidate within the same request. This guard applies at two points: submitting an `ORDER`-direction Fed order, and creating an inbound shipment. A candidate exceeding headroom is rejected with `ERR_INSURANCE_HEADROOM_EXCEEDED` (HTTP 402). Because `insurance_headroom_cents` may drift negative only through advice variances — never through a guarded write — a non-positive headroom also freezes the site per §2.9.

### 3.4. Armored Shipments: Scheduling, Loading, Transit, and Verification

A `FedCoordinator` schedules a shipment by naming the `carrier_id`, a `scheduled_departure_at` instant, and a `scheduled_arrival_at` strictly later than departure. Two shapes exist. A Fed-linked shipment carries a `fed_order_id`; its origin and destination sites are then derived from the linked order (an inbound `ORDER` has no origin site because cash originates at the Fed; an outbound `DEPOSIT` has no destination site), its `declared_value_cents` is taken from the order's `face_total_cents`, and the linked order must be `SUBMITTED` or `ACKNOWLEDGED` at scheduling time — otherwise `ERR_LINKED_ORDER_NOT_ACKNOWLEDGED` (HTTP 409). An inter-site transfer instead takes explicit `origin_site_id` and `destination_site_id` and a client-supplied `declared_value_cents` stored verbatim.

Scheduling enforces three commercial constraints. First, carrier liability: the declared value must not exceed the carrier's `liability_cap_per_truck_cents`, failing with `ERR_CARRIER_LIABILITY_EXCEEDED` (HTTP 402). Second, carrier turnaround: the new shipment's departure-to-arrival window, expanded by 45 minutes on both ends, must not overlap any non-cancelled shipment of the same carrier; the windows are half-open, so a gap of exactly 45 minutes is permitted, while anything closer is rejected with `ERR_CARRIER_TURNAROUND_CONFLICT` (HTTP 409). Third, dock capacity for inbound shipments: the count of inbound shipments in `SCHEDULED`, `LOADED`, or `IN_TRANSIT` whose arrival window (30 minutes on either side) contains the new arrival instant must remain below the destination's `dock_capacity`, failing with `ERR_DOCK_CAPACITY_EXCEEDED` (HTTP 409). Inbound creation also passes through the insurance-headroom guard of §3.3. A successfully scheduled shipment lands in `SCHEDULED`; an outbound schedule immediately adds its declared value to the origin site's `reserved_out_cents` and re-derives the site.

Loading the truck moves `SCHEDULED → LOADED` and requires the shipment to currently be `SCHEDULED`, failing with `ERR_SHIPMENT_INVALID_STATE` (HTTP 409) from any other state. The carrier must still be `ACTIVE`, a linked order must be `ACKNOWLEDGED` by this point (`ERR_LINKED_ORDER_NOT_ACKNOWLEDGED`), and an outbound load requires the origin site not be `FROZEN`. Outbound loading performs the physical debit: the origin site's `reserved_out_cents` decreases by the declared value, its `on_hand_fit_cents` decreases by the declared value — all outbound value is pinned to the `FIT` bucket — and a `SHIPMENT_OUT` ledger entry posts on the clock date (a `FED_DEPOSIT` entry instead when the shipment is linked to a `DEPOSIT`-direction order), followed by site re-derivation and the reconciliation refresh cascade. Inbound loading instead adds the declared value to the destination's `in_transit_inbound_cents`.

Departure and verification belong to the `CarrierDispatcher`, and only the dispatcher whose identity matches the shipment's `carrier_id` may act — anyone else is rejected with `ERR_RESOURCE_OWNERSHIP_VIOLATION` (HTTP 403). Departure moves `LOADED → IN_TRANSIT` and, if a Fed order is linked, moves the order `ACKNOWLEDGED → IN_TRANSIT` alongside it; departing from any state other than `LOADED` is rejected with `ERR_SHIPMENT_INVALID_STATE`. Verification at destination carries the counted value in `counted_value_cents`, requires the shipment to be `IN_TRANSIT` (or `EXCEPTION` for an accept-variance re-verification, with any other state again failing with `ERR_SHIPMENT_INVALID_STATE`), and forks three ways. A count equal to the declared value moves `IN_TRANSIT → VERIFIED`, records `counted_value_cents`, credits the destination for an inbound shipment — `in_transit_inbound_cents` decreases by the declared value, `on_hand_fit_cents` increases by it, and a `SHIPMENT_IN` entry posts (a `FED_RECEIPT` when linked to an `ORDER` order) — sets a linked order's `settled_basis_cents` to the declared value as the booked basis, moves the linked order to `RECEIVED`, and cascades through site totals, posture, and reconciliation refresh. A mismatched count instead moves `IN_TRANSIT → EXCEPTION`, recording the counted value but moving no cash. From `EXCEPTION`, a second verification with `accept_variance` set to `true` accepts the variance and moves to `VERIFIED`: an inbound shipment credits the destination with the counted value (releasing the full declared amount from `in_transit_inbound_cents`) and posts the corresponding `SHIPMENT_IN` or `FED_RECEIPT` entry, while an outbound shipment posts an `ADJUSTMENT` entry of the declared-minus-counted difference in the `FIT` bucket, returning undelivered value to the origin's fit balance; a linked order moves to `RECEIVED` with `settled_basis_cents` set to the counted value, and the full site cascade follows.

Cancellation is available from `SCHEDULED` or `LOADED` and compensates whatever was reserved: the origin's `reserved_out_cents` always decreases by the declared value, and a cancellation from `LOADED` additionally returns the declared value to the origin's `on_hand_fit_cents` via a `SHIPMENT_IN` reversal ledger entry, with the reconciliation refresh cascade. Each shipment transition increments the shipment's version.

### 3.5. Fitness Sorting and Unfit Currency Return

Unfit currency — torn, soiled, or worn notes — accumulates in a site's `on_hand_unfit_cents` and periodically goes through fitness sorting. A `VaultCustodian` opens a `FitnessBatch` by declaring an `input_unfit_cents` amount, which is escrowed immediately: the site's `on_hand_unfit_cents` decreases by that amount, the site re-derives, and the batch lands in `OPEN`. The declared input must not exceed the site's unfit cash on hand, failing with `ERR_INSUFFICIENT_UNFIT_BALANCE` (HTTP 422), and a `FROZEN` site may not open batches at all (`ERR_VAULT_FROZEN`).

Recording sort results moves `OPEN → SORTED` — the batch must be `OPEN`, failing with `ERR_BATCH_INVALID_STATE` (HTTP 409) otherwise — and declares three buckets: `fit_recovered_cents` for notes returned to circulation, `unfit_remaining_cents` still unfit, and `counterfeit_face_cents` for notes determined counterfeit. Their sum must not exceed the escrowed input, and the counterfeit face must be a whole multiple of 100 cents because counterfeit cases are denominated in one-dollar notes; violations are rejected with `ERR_SORT_EXCEEDS_INPUT` (HTTP 422). The batch's `shrink_cents` — the unaccounted remainder — is computed as the input minus the three declared buckets, and a conservation invariant holds after every sort and after settlement: the input always equals fit recovered plus unfit remaining plus counterfeit face plus shrink. If the count needs correction, the custodian may reopen a `SORTED` batch, returning it to `OPEN` with all buckets reset to zero; settling or reopening from any state other than `SORTED` fails with `ERR_BATCH_INVALID_STATE`, and sorting and reopening each increment the batch version.

Settling moves `SORTED → SETTLED` under a strict tolerance: `shrink_cents` must not exceed 500 cents — exactly 500 settles, 501 is rejected with `ERR_SHRINK_TOLERANCE_EXCEEDED` (HTTP 422). Settlement returns the buckets to the site: `on_hand_fit_cents` increases by the recovered fit value and `on_hand_unfit_cents` by the remaining unfit value, booked as `FITNESS_RECLASS` ledger entries into the `FIT` and `UNFIT` buckets respectively on the clock date; a positive shrink posts an additional `ADJUSTMENT` entry removing the shrink from the `FIT` bucket. When the sort found counterfeit notes, settlement also auto-creates a `CounterfeitCase` in `DETECTED` status linked to the batch via `fitness_batch_id`, denominated in 100-cent notes with a `note_count` equal to the counterfeit face divided by 100. The ledger appends cascade through site re-derivation, reconciliation refresh, and posture re-derivation. `SETTLED` is terminal.

### 3.6. Counterfeit Detection, Seizure, and Reporting

A counterfeit case enters the system in two ways: automatically at fitness-batch settlement, or directly when a `VaultCustodian` or `ComplianceOfficer` records a detection with a `site_id`, a `denomination_cents` from the standard set, a `note_count` of at least 1, and optionally a `fitness_batch_id` linking it to a sort. The case's `face_value_cents` is the denomination times the note count, and the case starts in `DETECTED`.

Seizure — `DETECTED → SEIZED` — is performed by a `VaultCustodian`, requires the case to currently be `DETECTED`, and records the acting identity in `seized_by_staff_id` and the logical clock in `seized_at`; seizing from any other state is rejected with `ERR_CASE_INVALID_STATE` (HTTP 409). The face value leaves circulation immediately: a `COUNTERFEIT_SEIZURE` ledger entry posts the negative face value against the `FIT` bucket on the clock date, the site's `on_hand_fit_cents` falls accordingly, and the site cascade re-derives posture and refreshes reconciliations. From `SEIZED` the compliance path forks, and both forks enforce segregation of duties: the reporting or releasing `ComplianceOfficer` must not be the same identity recorded as `seized_by_staff_id`, failing with `ERR_SOD_VIOLATION` (HTTP 403) if they match. Reporting moves `SEIZED → REPORTED`, recording `reported_by_staff_id` and `reported_at`, and re-derives site posture — the overdue-report pressure that builds on aging `SEIZED` cases lifts once no case remains past its deadline. Release moves `SEIZED → RELEASED` when the notes are determined genuine and returns the face value to circulation via a `COUNTERFEIT_RELEASE` ledger entry in the `FIT` bucket, again cascading. Both reporting and release require the case to be `SEIZED`, and settling requires it to be `REPORTED`; any wrong-state attempt is rejected with `ERR_CASE_INVALID_STATE`. Finally, settling a reported case moves `REPORTED → SETTLED_WITH_FED` with no cash movement — the seized face was already booked as a permanent loss at seize time. `SETTLED_WITH_FED` and `RELEASED` are terminal, and every transition increments the case version.

Time pressure on this workflow feeds posture directly (§2.9): a `SEIZED` case left unreported for more than 5 days pushes its site to `ELEVATED`, and more than 10 days freezes it. Advancing the logical clock is itself an event that re-derives posture at any site holding such cases.

### 3.7. ATM Cash Forecasting, Loading, and Settlement

An `AtmAnalyst` plans cash for each machine through a forecast lifecycle. Machines are registered by an administrator with the servicing vault's `site_id`, a unique `terminal_code`, the physical cassette `cash_capacity_cents`, and an optional `opening_balance_cents` defaulting to zero; the machine's `current_balance_cents` starts at the opening balance, its `service_status` starts `ACTIVE`, and its cash posture derives immediately. The machine carries two independent state axes: `service_status` toggles between `ACTIVE` and `OUT_OF_SERVICE` at the request of an `AtmAnalyst` (toggling from the wrong state fails with `ERR_ATM_INVALID_STATE`, and each toggle increments the machine's version), while `cash_posture` is a pure derivation — `CRITICAL` when the current balance multiplied by 20 is below capacity, otherwise `LOW` when the balance multiplied by 5 is below capacity, otherwise `NORMAL` — recomputed on every balance mutation and never gated by the service axis. The one place the axes meet is publication: a forecast may only be published for a machine whose service axis is `ACTIVE`.

Creating a forecast takes the target `atm_id`, the `forecast_date` being planned, and three trailing observations: `w1_cents`, `w2_cents`, and `w3_cents`, the withdrawals on the same weekday one, two, and three weeks prior. The projected base, `projected_base_cents`, is a weighted average — half of the most recent week, three-tenths of the week before, one-fifth of the oldest — rounded half-up to integer cents. Whether a seasonal uplift applies depends on the machine's site: if the forecast date falls inside any of that site's seasonal windows (inclusive of both ends), the `variant_applied` is `SEASONAL` and the projected final, `projected_final_cents`, is the base multiplied by the window's `multiplier_bps` and divided by 10000, again rounded half-up; otherwise the variant is `TRAILING` and `projected_final_cents` equals the base. The recommended load then rounds the projection up to whole 2,000-dollar straps (200000 cents): the load is the projection divided by the strap size rounded up to the next integer, multiplied back by the strap size, so a projection that is already an exact strap multiple stays unchanged. The `residual_target_cents` — how much cash should ideally remain at day end — is computed next: if the machine's `cash_posture` is `CRITICAL` the target is zero; otherwise the raw target is the larger of a 1,000-dollar floor (100000 cents) and 15% of the projected final (1500 basis points, applied with round-half-up), and the target is the raw value capped by the headroom left in the cassette after the recommended load, where that headroom is the capacity minus the load, floored at zero. The forecast starts in `DRAFT`.

Publishing moves `DRAFT → PUBLISHED` — the forecast must currently be `DRAFT`, failing with `ERR_FORECAST_INVALID_STATE` (HTTP 409) otherwise — and requires the machine's service axis to be `ACTIVE` (`ERR_ATM_OUT_OF_SERVICE`, HTTP 409) plus the OCC check on `expected_atm_version` from §2.7. Publication is exclusive per machine and date: any other `PUBLISHED` forecast for the same ATM and forecast date moves to `SUPERSEDED` automatically, the machine's `current_forecast_id` is set to the newly published forecast, and the machine's version increments alongside the forecast's. Loading moves `PUBLISHED → LOADED` and is only valid from `PUBLISHED` (`ERR_FORECAST_INVALID_STATE` from any other state): the site's `on_hand_fit_cents` must cover the `recommended_load_cents` (`ERR_INSUFFICIENT_FIT_BALANCE`, HTTP 422), the load is debited from the site's fit balance and credited to the machine's `current_balance_cents`, an `ATM_LOAD` ledger entry posts on the clock date, the machine's cash posture re-derives, both versions increment, and the site cascade refreshes reconciliations. Settlement closes the loop with the day's reality — again only from `LOADED`, failing with `ERR_FORECAST_INVALID_STATE` otherwise: the analyst reports `actual_withdrawals_cents`, which must not exceed the machine's current balance (`ERR_WITHDRAWAL_EXCEEDS_BALANCE`, HTTP 422). The `residual_balance_cents` is the current balance minus actual withdrawals; the machine's balance zeroes out as the residual cassette returns to the vault; the site's `on_hand_fit_cents` increases by the residual via an `ATM_RESIDUAL_RETURN` ledger entry (posted only when the residual is positive) on the clock date; and the forecast lands in the terminal `SETTLED` state with both versions incrementing and the site cascade following.

### 3.8. Daily Reconciliation and Variance Handling

Every business day, each site's physical cash is proven against the book of record. A `VaultCustodian` opens a `Reconciliation` for a `site_id` and `business_date` with a declared `opening_balance_cents`; only one reconciliation may exist per site and date, and a duplicate is rejected with `ERR_DUPLICATE_RECONCILIATION` (HTTP 409). Opening freezes a provisional expectation: `provisional_expected_cents` is the opening balance plus the sum of the signed amounts of every ledger entry for that site and business date created at or before the reconciliation was opened — entries created later, even when backdated to the same value date, are excluded from this snapshot forever. In parallel, `final_expected_cents` is the opening balance plus the sum of all ledger entries for that site and date regardless of when they were created, and it refreshes on every matching ledger append. The two diverge by exactly the sum of late-arriving entries. The reconciliation starts in `OPEN`.

Submitting the physical count — allowed only from `OPEN`, failing with `ERR_RECON_INVALID_STATE` (HTTP 409) otherwise — records `counted_on_hand_cents` and the counter's identity in `counted_by_staff_id`, computes `variance_cents` as the counted amount minus the final expected amount, and auto-forks: when the absolute variance is within 1000 cents the reconciliation moves `OPEN → COUNTED → BALANCED`; otherwise it moves `OPEN → COUNTED → VARIANCE_PENDING`. This fork is not permanent. Because every matching ledger append refreshes the final expectation, a late entry can move the variance across the tolerance line in either direction — a `BALANCED` reconciliation flips to `VARIANCE_PENDING` or back, and a `VARIANCE_PENDING` one flips to `BALANCED`, as the sweep re-evaluates the current absolute variance against the 1000-cent tolerance.

A variance that will not resolve itself has two routes. The custodian may escalate it — `VARIANCE_PENDING → ESCALATED`, allowed only from `VARIANCE_PENDING` — which pressures the site's posture toward `ELEVATED` per §2.9. A `CashOperationsAdmin` may approve a variance from either `VARIANCE_PENDING` or `ESCALATED`, recording `approved_by_staff_id`. Closure happens through locking: a reconciliation in `BALANCED` or `APPROVED` may be locked by a `VaultCustodian` or `CashOperationsAdmin`, moving it to the terminal `LOCKED` state — but under segregation of duties the locker must not be the identity that submitted the count, failing with `ERR_SOD_VIOLATION` (HTTP 403) otherwise. Escalating, approving, or locking from any state other than the ones just named is rejected with `ERR_RECON_INVALID_STATE`. Locking records `approved_by_staff_id` when it closes a balanced reconciliation, and increments the version.

### 3.9. Manual Ledger Adjustments and Late Events

Not every movement flows through a state machine. A `VaultCustodian` or `CashOperationsAdmin` may post a manual ledger entry with a `site_id`, a `business_date`, a `signed_amount_cents`, an optional `bucket` defaulting to `FIT`, and an optional free-text `note` defaulting to empty. Manual posts are always stamped with `entry_type` `ADJUSTMENT`. The value date may be earlier than the current date — late events and backdated corrections are first-class — and this is precisely what the reconciliation machinery is built to absorb: the entry immediately re-derives the owning site's totals and posture, and any matching reconciliation in `OPEN` or `COUNTED` status refreshes its `final_expected_cents` and variance, potentially flipping between `BALANCED` and `VARIANCE_PENDING` as described above. The full ledger-entry vocabulary the system itself uses — `OPENING_BALANCE`, `FED_RECEIPT`, `FED_DEPOSIT`, `SHIPMENT_IN`, `SHIPMENT_OUT`, `ATM_LOAD`, `ATM_RESIDUAL_RETURN`, `FITNESS_RECLASS`, `COUNTERFEIT_SEIZURE`, `COUNTERFEIT_RELEASE`, and `ADJUSTMENT` — appears as the `entry_type` enum on every entry.

## 4. Endpoint Definitions

All endpoints are mounted under `/vault-cash`. Resource creation returns 201 with the created resource; state transitions, modifications, and reads return 200. All write endpoints enforce the validation order of §2.8, and the three OCC-guarded writes additionally enforce the version checks of §2.7.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /vault-cash/_clock/set_current_utc | Advance the logical clock to a supplied instant | CashOperationsAdmin |
| POST | /vault-cash/vault-sites | Create a vault site with opening balances | CashOperationsAdmin |
| GET | /vault-cash/vault-sites | List vault sites | CashOperationsAdmin, VaultCustodian, FedCoordinator, AtmAnalyst, ComplianceOfficer, CarrierDispatcher |
| GET | /vault-cash/vault-sites/{siteId} | Get one site including all computed totals and posture | CashOperationsAdmin, VaultCustodian, FedCoordinator, AtmAnalyst, ComplianceOfficer, CarrierDispatcher |
| PATCH | /vault-cash/vault-sites/{siteId} | Update limits/capacity (OCC) | CashOperationsAdmin |
| POST | /vault-cash/staff-members | Register a staff member (identity anchor for site-scoped roles) | CashOperationsAdmin |
| GET | /vault-cash/staff-members | List staff | CashOperationsAdmin, VaultCustodian, FedCoordinator, AtmAnalyst, ComplianceOfficer, CarrierDispatcher |
| GET | /vault-cash/staff-members/{staffId} | Get one staff member | CashOperationsAdmin, VaultCustodian, FedCoordinator, AtmAnalyst, ComplianceOfficer, CarrierDispatcher |
| POST | /vault-cash/carriers | Register an armored carrier | CashOperationsAdmin |
| GET | /vault-cash/carriers | List carriers | CashOperationsAdmin, VaultCustodian, FedCoordinator, AtmAnalyst, ComplianceOfficer, CarrierDispatcher |
| PATCH | /vault-cash/carriers/{carrierId} | Suspend or reinstate a carrier | CashOperationsAdmin |
| POST | /vault-cash/atm-machines | Register an ATM | CashOperationsAdmin |
| GET | /vault-cash/atm-machines | List ATMs | CashOperationsAdmin, VaultCustodian, FedCoordinator, AtmAnalyst, ComplianceOfficer, CarrierDispatcher |
| GET | /vault-cash/atm-machines/{atmId} | Get one ATM including both state axes and version | CashOperationsAdmin, VaultCustodian, FedCoordinator, AtmAnalyst, ComplianceOfficer, CarrierDispatcher |
| POST | /vault-cash/atm-machines/{atmId}/set-service-status | Toggle service axis (ACTIVE / OUT_OF_SERVICE) | AtmAnalyst, CashOperationsAdmin |
| POST | /vault-cash/seasonal-windows | Create a holiday/seasonal demand window | CashOperationsAdmin |
| GET | /vault-cash/seasonal-windows | List seasonal windows | CashOperationsAdmin, VaultCustodian, FedCoordinator, AtmAnalyst, ComplianceOfficer, CarrierDispatcher |
| GET | /vault-cash/seasonal-windows/{windowId} | Get one seasonal window | CashOperationsAdmin, VaultCustodian, FedCoordinator, AtmAnalyst, ComplianceOfficer, CarrierDispatcher |
| POST | /vault-cash/fed-orders | Create an empty DRAFT Fed order/deposit | FedCoordinator |
| GET | /vault-cash/fed-orders | List Fed orders | CashOperationsAdmin, VaultCustodian, FedCoordinator, AtmAnalyst, ComplianceOfficer, CarrierDispatcher |
| GET | /vault-cash/fed-orders/{orderId} | Get one order including computed totals | CashOperationsAdmin, VaultCustodian, FedCoordinator, AtmAnalyst, ComplianceOfficer, CarrierDispatcher |
| POST | /vault-cash/fed-orders/{orderId}/lines | Add a denomination line to a DRAFT order (OCC on order version) | FedCoordinator |
| GET | /vault-cash/fed-orders/{id}/lines | List an order's denomination lines | CashOperationsAdmin, VaultCustodian, FedCoordinator, AtmAnalyst, ComplianceOfficer, CarrierDispatcher |
| POST | /vault-cash/fed-orders/{orderId}/submit | Submit order to the Fed | FedCoordinator |
| POST | /vault-cash/fed-orders/{orderId}/recall | Recall a submitted order back to DRAFT | FedCoordinator |
| POST | /vault-cash/fed-orders/{orderId}/acknowledge | Record Fed acknowledgement | FedCoordinator |
| POST | /vault-cash/fed-orders/{orderId}/cancel | Cancel a DRAFT or SUBMITTED order | FedCoordinator |
| POST | /vault-cash/fed-orders/{orderId}/record-fed-advice | Record a Fed settlement advice; variance drives DISPUTED self-loop or RECONCILED | FedCoordinator |
| POST | /vault-cash/cash-shipments | Schedule a shipment (Fed-order-linked or inter-site) | FedCoordinator |
| GET | /vault-cash/cash-shipments | List shipments | CashOperationsAdmin, VaultCustodian, FedCoordinator, AtmAnalyst, ComplianceOfficer, CarrierDispatcher |
| GET | /vault-cash/cash-shipments/{shipmentId} | Get one shipment | CashOperationsAdmin, VaultCustodian, FedCoordinator, AtmAnalyst, ComplianceOfficer, CarrierDispatcher |
| POST | /vault-cash/cash-shipments/{shipmentId}/load | Load truck at origin | FedCoordinator |
| POST | /vault-cash/cash-shipments/{shipmentId}/depart | Depart origin | CarrierDispatcher |
| POST | /vault-cash/cash-shipments/{shipmentId}/verify | Verify delivery count; mismatch raises EXCEPTION; exception with accept_variance resolves to VERIFIED | CarrierDispatcher |
| POST | /vault-cash/cash-shipments/{shipmentId}/cancel | Cancel a SCHEDULED or LOADED shipment (compensating release) | FedCoordinator |
| POST | /vault-cash/fitness-batches | Open a fitness sorting batch; escrows unfit cash | VaultCustodian |
| GET | /vault-cash/fitness-batches | List fitness batches | CashOperationsAdmin, VaultCustodian, FedCoordinator, AtmAnalyst, ComplianceOfficer, CarrierDispatcher |
| GET | /vault-cash/fitness-batches/{batchId} | Get one fitness batch | CashOperationsAdmin, VaultCustodian, FedCoordinator, AtmAnalyst, ComplianceOfficer, CarrierDispatcher |
| POST | /vault-cash/fitness-batches/{batchId}/sort-results | Record sort outcome buckets (OPEN to SORTED) | VaultCustodian |
| POST | /vault-cash/fitness-batches/{batchId}/settle | Settle a SORTED batch (shrink gate) | VaultCustodian |
| POST | /vault-cash/fitness-batches/{batchId}/reopen | Reopen a SORTED batch for recount | VaultCustodian |
| POST | /vault-cash/counterfeit-cases | Record a direct counterfeit detection | VaultCustodian, ComplianceOfficer |
| GET | /vault-cash/counterfeit-cases | List counterfeit cases | CashOperationsAdmin, VaultCustodian, FedCoordinator, AtmAnalyst, ComplianceOfficer, CarrierDispatcher |
| GET | /vault-cash/counterfeit-cases/{caseId} | Get one counterfeit case | CashOperationsAdmin, VaultCustodian, FedCoordinator, AtmAnalyst, ComplianceOfficer, CarrierDispatcher |
| POST | /vault-cash/counterfeit-cases/{caseId}/seize | Seize suspect notes | VaultCustodian |
| POST | /vault-cash/counterfeit-cases/{caseId}/report | Report seizure to the Fed/Secret Service (reporter must differ from seizer) | ComplianceOfficer |
| POST | /vault-cash/counterfeit-cases/{caseId}/release | Release notes determined genuine (releaser must differ from seizer) | ComplianceOfficer |
| POST | /vault-cash/counterfeit-cases/{caseId}/settle | Mark case settled with the Fed | ComplianceOfficer |
| POST | /vault-cash/cash-ledger-entries | Post a manual ADJUSTMENT entry; business_date may be backdated | VaultCustodian, CashOperationsAdmin |
| GET | /vault-cash/cash-ledger-entries | List ledger entries | CashOperationsAdmin, VaultCustodian, FedCoordinator, AtmAnalyst, ComplianceOfficer, CarrierDispatcher |
| GET | /vault-cash/cash-ledger-entries/{entryId} | Get one ledger entry | CashOperationsAdmin, VaultCustodian, FedCoordinator, AtmAnalyst, ComplianceOfficer, CarrierDispatcher |
| POST | /vault-cash/reconciliations | Open a daily reconciliation; provisional snapshot frozen at open | VaultCustodian |
| GET | /vault-cash/reconciliations | List reconciliations | CashOperationsAdmin, VaultCustodian, FedCoordinator, AtmAnalyst, ComplianceOfficer, CarrierDispatcher |
| GET | /vault-cash/reconciliations/{reconId} | Get one reconciliation | CashOperationsAdmin, VaultCustodian, FedCoordinator, AtmAnalyst, ComplianceOfficer, CarrierDispatcher |
| POST | /vault-cash/reconciliations/{reconId}/count | Submit physical count; auto-forks BALANCED vs VARIANCE_PENDING | VaultCustodian |
| POST | /vault-cash/reconciliations/{reconId}/escalate | Escalate a variance to operations | VaultCustodian |
| POST | /vault-cash/reconciliations/{reconId}/approve | Admin approval of a variance | CashOperationsAdmin |
| POST | /vault-cash/reconciliations/{reconId}/lock | Lock a BALANCED or APPROVED reconciliation (locker must differ from counter) | VaultCustodian, CashOperationsAdmin |
| POST | /vault-cash/atm-forecasts | Create a DRAFT forecast; all projections computed | AtmAnalyst |
| GET | /vault-cash/atm-forecasts | List forecasts | CashOperationsAdmin, VaultCustodian, FedCoordinator, AtmAnalyst, ComplianceOfficer, CarrierDispatcher |
| GET | /vault-cash/atm-forecasts/{forecastId} | Get one forecast | CashOperationsAdmin, VaultCustodian, FedCoordinator, AtmAnalyst, ComplianceOfficer, CarrierDispatcher |
| POST | /vault-cash/atm-forecasts/{forecastId}/publish | Publish forecast (OCC on ATM version; supersedes prior PUBLISHED) | AtmAnalyst |
| POST | /vault-cash/atm-forecasts/{forecastId}/load | Load recommended cash into the ATM from its vault | AtmAnalyst |
| POST | /vault-cash/atm-forecasts/{forecastId}/settle | Settle actual withdrawals; residual returns to vault | AtmAnalyst |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_INSUFFICIENT_PERMISSIONS | 403 |
| ERR_SITE_SCOPE_VIOLATION | 403 |
| ERR_RESOURCE_OWNERSHIP_VIOLATION | 403 |
| ERR_INVALID_REQUEST | 400 |
| ERR_VAULT_SITE_NOT_FOUND | 404 |
| ERR_STAFF_MEMBER_NOT_FOUND | 404 |
| ERR_CARRIER_NOT_FOUND | 404 |
| ERR_ATM_NOT_FOUND | 404 |
| ERR_SEASONAL_WINDOW_NOT_FOUND | 404 |
| ERR_FED_ORDER_NOT_FOUND | 404 |
| ERR_SHIPMENT_NOT_FOUND | 404 |
| ERR_FITNESS_BATCH_NOT_FOUND | 404 |
| ERR_COUNTERFEIT_CASE_NOT_FOUND | 404 |
| ERR_RECONCILIATION_NOT_FOUND | 404 |
| ERR_ATM_FORECAST_NOT_FOUND | 404 |
| ERR_FED_ORDER_INVALID_STATE | 409 |
| ERR_SHIPMENT_INVALID_STATE | 409 |
| ERR_BATCH_INVALID_STATE | 409 |
| ERR_CASE_INVALID_STATE | 409 |
| ERR_RECON_INVALID_STATE | 409 |
| ERR_FORECAST_INVALID_STATE | 409 |
| ERR_ATM_INVALID_STATE | 409 |
| ERR_VAULT_FROZEN | 409 |
| ERR_CARRIER_SUSPENDED | 409 |
| ERR_ATM_OUT_OF_SERVICE | 409 |
| ERR_LINKED_ORDER_NOT_ACKNOWLEDGED | 409 |
| ERR_SOD_VIOLATION | 403 |
| ERR_ORDER_CUTOFF_PASSED | 422 |
| ERR_CARRIER_TURNAROUND_CONFLICT | 409 |
| ERR_DOCK_CAPACITY_EXCEEDED | 409 |
| ERR_SEASONAL_WINDOW_OVERLAP | 409 |
| ERR_INVALID_DENOMINATION_MIX | 422 |
| ERR_DUPLICATE_RECONCILIATION | 409 |
| ERR_SORT_EXCEEDS_INPUT | 422 |
| ERR_ORDER_HAS_NO_LINES | 422 |
| ERR_INSURANCE_HEADROOM_EXCEEDED | 402 |
| ERR_CARRIER_LIABILITY_EXCEEDED | 402 |
| ERR_VAULT_LIMIT_EXCEEDED | 402 |
| ERR_INSUFFICIENT_CASH_FOR_DEPOSIT | 422 |
| ERR_INSUFFICIENT_UNFIT_BALANCE | 422 |
| ERR_SHRINK_TOLERANCE_EXCEEDED | 422 |
| ERR_INSUFFICIENT_FIT_BALANCE | 422 |
| ERR_WITHDRAWAL_EXCEEDS_BALANCE | 422 |
| ERR_STALE_ATM_VERSION | 412 |
| ERR_STALE_VAULT_SITE_VERSION | 412 |
| ERR_STALE_FED_ORDER_VERSION | 412 |
