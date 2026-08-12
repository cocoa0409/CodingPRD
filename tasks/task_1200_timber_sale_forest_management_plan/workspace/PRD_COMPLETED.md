# Timber Sale & Forest Management Plan API — Product Requirements Document

## 1. Introduction

Consulting foresters run a long, document-heavy pipeline for every timber sale: they cruise the stand to estimate volume, write a harvest prescription, secure the landowner's approval, advertise the sale, take bids, paper a contract with a performance bond, police the logging for best-management-practice compliance, verify every truckload of logs against the scale, settle payments, and then stay on the hook for reforestation until a survival survey proves the stand is re-established. Each step has money attached to it, most steps have a deadline attached to them, and several steps are legally required to be performed by different people — the forester who records a scale ticket may not be the forester who verifies it. Today this pipeline lives in spreadsheets and filing cabinets, which makes the audit trail fragile exactly where it matters most: who approved what, which cruise underpins which sale, and whether the bond was large enough when the buyer had defaulted before.

This document specifies a single REST API, mounted under `/forestry`, that runs the entire pipeline as one consistent system of record. It covers the party registry (foresters, landowners, buyers, logging contractors), forest tracts and stands, inventory cruises with statistical volume certification, harvest prescriptions, timber sale offerings with both lump-sum and per-unit bidding, harvest contracts and their performance bonds, scale tickets and payment settlements, BMP inspections with a stop-work cascade, reforestation obligations with survival surveys, and — as an alternative to harvesting at all — carbon-credit valuations that can enroll a tract in conservation. The system is built for compliance and audit first: every state change is explicit, every financial figure is derivable from recorded inputs, and a logical clock governs every deadline so that the entire lifecycle is reproducible.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID`, identifying the acting party, and `X-User-Role`, identifying the capacity in which that party acts. A request missing either header, or carrying a role value outside the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the role is declared but not listed among the roles authorized for the target endpoint, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). Where a role is entity-backed and the endpoint is ownership-scoped, acting on a resource the party does not own is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

Six roles exist, spelled exactly as follows:

- `PlatformAdmin` — the platform operator. It provisions the party registry (foresters, landowners, buyers, contractors), adjudicates bond forfeiture claims, and drives the logical clock. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- `Forester` — the consulting forester running the management plan: inventory, prescriptions, sales, contracts administration, settlements, inspection scheduling, and verifications. When `X-User-Role` is `Forester`, `X-User-ID` is the `id` of the acting Forester; ownership checks on any resource that references a Forester compare the resource's foreign-key field to `X-User-ID`.
- `Landowner` — the tract owner. A landowner approves harvest prescriptions and settlements, may dispute verified scale tickets, may cancel an open sale on their own tract, and decides the fate of carbon valuations. When `X-User-Role` is `Landowner`, `X-User-ID` is the `id` of the acting Landowner; ownership checks compare the tract's `landowner_id` to `X-User-ID`, and a landowner acting on anything rooted in a tract they do not own is rejected with `ERR_NOT_RESOURCE_OWNER`.
- `Buyer` — a timber buyer or mill. A buyer submits and withdraws bids, posts the performance bond, assigns the logging contractor, cures defaults, and may dispute verified scale tickets on its own contract. When `X-User-Role` is `Buyer`, `X-User-ID` is the `id` of the acting Buyer; ownership checks on bids and contracts compare the resource's `buyer_id` to `X-User-ID`.
- `Contractor` — the logging contractor assigned to a contract. A contractor starts and completes the harvest, records scale tickets, and records plantings. When `X-User-Role` is `Contractor`, `X-User-ID` is the `id` of the acting Contractor; ownership checks compare the contract's `contractor_id` to `X-User-ID`, and acting on a contract not assigned to that contractor is rejected with `ERR_NOT_RESOURCE_OWNER`.
- `AgencyInspector` — an external BMP compliance inspector who conducts and closes inspections and verifies corrective action. When `X-User-Role` is `AgencyInspector`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.

Read endpoints are shared: every role may fetch or list any resource. Write endpoints are restricted per endpoint as specified in §4.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, taken from the logical clock of §2.5 — never from wall-clock time.
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

All list endpoints accept two query parameters: `limit` and `offset`. The `limit` defaults to 10, must be at least 1, and may not exceed 100. The `offset` defaults to 0. A `limit` or `offset` that is not a well-formed integer, a `limit` outside 1–100, or a negative `offset` is a malformed request (`ERR_INVALID_REQUEST`, HTTP 400). Results are always sorted by `created_at` in ascending order, with ties broken by creation (insertion) order — because the logical clock advances only on administrative action, identical `created_at` values are common and the insertion-order tiebreak governs. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`, where `has_more` indicates whether further pages exist beyond the returned window.

List endpoints additionally accept resource-scoped filter parameters, each matching the named field exactly: tracts filter by `landowner_id`, `forester_id`, and `status`; stands by `tract_id` and `certified_cruise_id`; cruises by `stand_id` and `status`; prescriptions by `stand_id`, `cruise_id`, and `status`; sales by `tract_id`, `stand_id`, `prescription_id`, and `status`; bids by `sale_id`, `buyer_id`, and `status`; contracts by `sale_id`, `buyer_id`, `contractor_id`, and `status`; bonds by `contract_id` and `status`; scale tickets by `contract_id` and `status`; settlements by `contract_id` and `status`; inspections by `contract_id` and `status`; reforestation obligations by `contract_id` and `status`; survival surveys by `obligation_id` and `status`; carbon valuations by `tract_id` and `status`.

### 2.4. Resource Identity, Timestamps, and Versioning

Every persisted resource has an `id` that is a server-minted UUID with no type prefix. Most resources additionally carry `created_at` and `updated_at` — ISO 8601 UTC timestamps with three fractional digits — and a `version`, an integer that starts at 1 on creation and increments by exactly 1 on every mutation of the resource, including every state-machine transition. Four registry entities are deliberately lighter: a Forester, a Landowner, a Buyer, and a Contractor each carry only `id` and `created_at`; both `updated_at` and `version` are absent from these four entities, and nothing about them is ever versioned. All other entities — tracts, stands, cruises, prescriptions, sales, bids, contracts, bonds, scale tickets, settlements, inspections, obligations, surveys, and carbon valuations — carry the full set.

When one operation mutates several resources, each mutated resource's `version` increments and its `updated_at` refreshes; the workflow sections that follow call out every such cross-entity increment explicitly.

### 2.5. Money, Measurement, and the Logical Clock

All monetary amounts are integer cents; no fractional cents exist anywhere in the system. Board-foot volumes are integer board feet. Percentages are carried to two decimal places. Unless a rule explicitly names floor rounding, all rounding is round half up. Where a rounded percentage is itself an input to a further computation — the sampling error on a certified cruise is the canonical case — the rounded value, not the unrounded one, is what the downstream formula applies.

All deadlines, windows, and age checks in this document are evaluated against a single logical clock, never against wall-clock time. At server startup the logical clock reads exactly 2026-05-01T00:00:00Z. It advances only when a `PlatformAdmin` operator invokes the admin-only clock-setting capability with a `to_iso8601` ISO 8601 UTC instant; the response reports the clock's new `current_utc`, echoing the supplied `to_iso8601` string exactly as received. The clock never falls back to wall-clock time under any circumstances. Date-valued fields in this domain are calendar dates in `YYYY-MM-DD` form, and window checks on them use day granularity as each rule specifies.

### 2.6. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control, because each of them supersedes or displaces state that other clients may have observed:

- Certifying an inventory cruise requires the request to carry `expected_stand_version`, the client's last observed `version` of the stand. If the stand's current `version` differs — for example because another cruise was certified against the stand since the client read it — the certification is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Submitting a bid on a sale requires the request to carry `expected_sale_version`, the client's last observed `version` of the sale. If the sale's current `version` differs — every accepted bid advances it — the submission is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Creating a carbon valuation requires the request to carry `expected_tract_version`, the client's last observed `version` of the tract. If the tract's current `version` differs — for example because another valuation on the tract advanced it — the creation is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint accepts a version field; sending one elsewhere is an unknown field and is rejected as a malformed request.

### 2.7. The Validation Pipeline

Every request passes through a fixed pipeline of validation layers, and within each endpoint the applicable checks are evaluated in a single global priority order. The layers, earliest first, are:

1. Authentication: the two headers are present and the role is a declared role (`ERR_UNAUTHENTICATED`).
2. Role authorization: the acting role is listed for the endpoint (`ERR_FORBIDDEN_ROLE`).
3. Ownership: an entity-backed actor owns the target resource — a landowner only their own tracts, a buyer only their own bids and contracts, a contractor only contracts assigned to them (`ERR_NOT_RESOURCE_OWNER`).
4. Existence: every resource referenced by path parameters or by body references exists, resolved left to right along the path (per-entity 404 errors, §2.8).
5. Request schema: required fields are present, types are valid, enum values fall in their declared sets, dates are well-formed, amounts declared non-negative are non-negative, and unknown fields are rejected (`ERR_INVALID_REQUEST`, HTTP 400).
6. State-machine admissibility: the requested transition is valid from the entity's current state (`ERR_INVALID_TRANSITION`, HTTP 409), and no transition is ever permitted out of a terminal state (`ERR_ALREADY_TERMINAL`, HTTP 409); the terminal-state check fires before the generic invalid-transition check.
7. Domain state gates: cross-entity state preconditions such as the contract being mid-harvest for scaling work (`ERR_CONTRACT_SUSPENDED`), the sale being open for bidding (`ERR_SALE_NOT_OPEN_FOR_BIDDING`), the awarded bid matching the computed winner (`ERR_NOT_WINNING_BID`), and the absence of open major findings (`ERR_OPEN_MAJOR_FINDING`).
8. Business safety, constraint, temporal, and fiscal rules: enrollment conflicts, certification and freshness gates, window overlaps, deadline checks, minimum-rate and allowance checks, and exact-amount checks, each paired with its own error code as narrated in §3.
9. Optimistic concurrency: the `expected_<parent>_version` checks of §2.6 (`ERR_STALE_VERSION`, HTTP 412) are the last gate before the write commits.

Where several rules of these layers apply to one endpoint, their relative order is stated in prose at the workflow itself — for instance, on cruise certification the minimum-plot-count check is evaluated before the sampling-error check, and both precede the stale-version rejection.

### 2.8. Resolving Nested Resources and Missing References

Several paths nest one resource beneath another — a bid submission lives beneath its sale, addressed by the sale's path parameter `sale_id`, while most action endpoints address their target by a bare `id`. Path parameters are validated left to right: the outermost resource is resolved first, and a failure at any level produces the error for that resource type before inner segments are examined. Each resource type has its own not-found error, so a caller can tell exactly which reference failed: `ERR_PARTY_NOT_FOUND` for any of the four registry parties (forester, landowner, buyer, contractor), `ERR_TRACT_NOT_FOUND` for a tract, `ERR_STAND_NOT_FOUND` for a stand, `ERR_CRUISE_NOT_FOUND` for a cruise, `ERR_PRESCRIPTION_NOT_FOUND` for a prescription, `ERR_SALE_NOT_FOUND` for a sale, `ERR_BID_NOT_FOUND` for a bid, `ERR_CONTRACT_NOT_FOUND` for a contract, `ERR_BOND_NOT_FOUND` for a bond, `ERR_TICKET_NOT_FOUND` for a scale ticket, `ERR_SETTLEMENT_NOT_FOUND` for a settlement, `ERR_INSPECTION_NOT_FOUND` for an inspection, `ERR_OBLIGATION_NOT_FOUND` for a reforestation obligation, `ERR_SURVEY_NOT_FOUND` for a survival survey, and `ERR_VALUATION_NOT_FOUND` for a carbon valuation. All carry HTTP 404.

## 3. Business Logic & Workflows

### 3.1. Parties, Tracts, and Stands

Before any forestry work begins, a `PlatformAdmin` operator builds the party registry. Registering a forester records the state consulting-forester `license_no` (unique per forester — a duplicate is refused as a malformed request, `ERR_INVALID_REQUEST`, HTTP 400), the `full_name`, and a contact `email`. Registering a landowner records `full_name`, `email`, and the `tax_id` used on disbursement paperwork. Registering a timber buyer records the mill's `company_name` and its timber-buyer `license_no`, and optionally accepts a `prior_defaults` count that seeds the buyer's contract-default history — it starts at 0 when not supplied and is incremented by the system each time one of that buyer's contracts reaches `TERMINATED`. Registering a logging contractor records the contractor's `company_name` and logger `license_no`.

A `Forester` then establishes the land base. Creating a forest tract requires a `name`, the `county` it lies in, `total_acres` strictly greater than zero, the owning `landowner_id`, and the `forester_id` of the consulting forester of record; each of the two party references must name a registered party of its own kind, else `ERR_PARTY_NOT_FOUND` (HTTP 404). Every tract begins life with `status` `OPEN`, and its `conservation_enrollment_start` and `conservation_enrollment_end` remain null unless a carbon valuation is later accepted against it. Within a tract, the forester delineates stands: each stand takes its `tract_id`, a `name`, its `acres` — strictly greater than zero and no more than the tract's `total_acres`, with an oversized stand refused as a malformed request (`ERR_INVALID_REQUEST`, HTTP 400) — and a `primary_species` code. A stand's `certified_cruise_id` is null until the first inventory cruise is certified against it.

Ownership is anchored here and enforced everywhere downstream: a landowner may act only on resources rooted in tracts whose `landowner_id` matches their identity, a buyer only on bids and contracts bearing their `buyer_id`, and a contractor only on contracts whose `contractor_id` names them.

### 3.2. Cruising the Stand: From Tally Sheets to a Certified Volume

Inventory starts in the field. A `Forester` creates an inventory cruise against a stand by supplying the `stand_id`, the `cruise_date` of the field work, and the `plots` tally — one row per plot per species, each row carrying a `plot_number` (an integer), a `species` code, and the tallied `volume_bf` (a number). The cruise is born in `DRAFT`, and the system derives `n_plots`, the count of distinct plot numbers in the tally. Plots are one fifth of an acre each, a constant that drives all volume expansion.

Finalizing the tally moves the cruise `DRAFT → TALLIED` and requires at least one plot on the sheet — an empty sheet is refused with `ERR_INVALID_TRANSITION` (HTTP 409). Reconciliation is the analytical heart of the inventory: the forester submits `reconciled_plot_numbers`, a non-empty list of integers in which every plot number must actually appear in the tally (a repeated plot number is honored as submitted, counting once per occurrence in the model below), and the cruise moves `TALLIED → RECONCILED` while the system recomputes the full volume model. The per-plot total is the sum of `volume_bf` over all rows sharing that plot number. The `expansion_factor` is the stand's `acres` divided by the product of the plot size (0.2 acres) and `n_plots`. Two volume variants then diverge deliberately:

- The **provisional** estimate, `provisional_volume_bf`, is the advertised rough figure: the sum of per-plot totals across *all* tallied plots — reconciled or not — multiplied by the `expansion_factor`, rounded half up to a whole board foot. It applies no sampling-error deduction.
- The **certified** estimate considers only the reconciled plots. Let their combined tally, expanded by the same `expansion_factor`, be the base. The `sampling_error_pct` is the population standard deviation of the per-plot totals across the reconciled plots, divided by the mean of those totals, divided by the square root of the number of reconciled plots, multiplied by 100, and rounded half up to two decimal places; if the mean of the reconciled per-plot totals is zero, `sampling_error_pct` is 0.00. The `certified_volume_bf` is then the base multiplied by one minus the (rounded) sampling error expressed as a fraction — that is, base × (1 − `sampling_error_pct`/100) — rounded half up to a whole board foot. The `certified_volume_by_species` breakdown applies the identical adjustment per species: for each species, the reconciled rows of that species are summed, multiplied by the `expansion_factor`, multiplied by one minus the rounded sampling error fraction, and rounded half up. The breakdown is rendered as an array of objects, one per species, each `{"species": <code>, "volume_bf": <board feet>}`, sorted by species code ascending. Because of the sampling deduction, identical tallies always yield a certified volume strictly smaller than the provisional one whenever `sampling_error_pct` exceeds zero.

A reconciliation that fails audit is not fatal: reopening the cruise moves it `RECONCILED → TALLIED`, clearing `reconciled_plot_numbers`, `certified_volume_bf`, `certified_volume_by_species`, and `sampling_error_pct` back to null while the tally and provisional machinery survive; the tally may then be adjusted and reconciled again, with no limit on how many times the loop turns.

Certification is the point of no return and the most heavily gated transition in the inventory workflow. The checks fire in this order. The cruise must be `RECONCILED`. The number of reconciled plots must be at least 5 — fewer is rejected with `ERR_MIN_PLOTS_NOT_MET` (HTTP 422). Only after the plot-count check passes is the sampling error examined: a `sampling_error_pct` above 10.00 is rejected with `ERR_SAMPLING_ERROR_TOO_HIGH` (HTTP 422). Finally the optimistic-concurrency gate applies: the request must carry `expected_stand_version` equal to the stand's current `version`, or the certification is rejected with `ERR_STALE_VERSION` (HTTP 412). On success the cruise becomes `CERTIFIED`, `certified_at` is stamped from the logical clock, whichever cruise previously held certification on the same stand is moved to `SUPERSEDED` — without its own `version` or `updated_at` changing — the stand's `certified_cruise_id` is repointed at the newly certified cruise, and both the newly certified cruise's and the stand's `version` increment. A cruise that should never have existed can be voided from `DRAFT` or `TALLIED` into `VOID`. `CERTIFIED`, `SUPERSEDED`, and `VOID` are terminal.

A certified cruise does not stay fresh forever: 24 months is the maximum age a certification may have when a sale built on it is offered, a rule that surfaces in §3.4.

### 3.3. Prescribing the Harvest: Methods, Windows, and the Revision Loop

With a certified volume in hand, the forester writes the harvest prescription. Creating one records the `stand_id`, the `cruise_id` of the underpinning cruise, the `silvicultural_method` — one of `CLEARCUT`, `SHELTERWOOD`, `SEED_TREE`, `SELECTION`, or `COMMERCIAL_THINNING` — and the harvest window `window_start` to `window_end`, a half-open interval in which the end date must fall after the start date. The prescription begins in `DRAFT`.

Proposing moves it `DRAFT → PROPOSED`, after which only the landowner can move it forward: approval is the exclusive act of the landowner who owns the tract containing the prescribed stand, and it is refused with `ERR_CRUISE_NOT_CERTIFIED` (HTTP 409) unless the cruise named by `cruise_id` is `CERTIFIED` at that moment. An approved prescription is not frozen — the forester may send it back through the revision loop `APPROVED → PROPOSED`, optionally applying new `window_start`, `window_end`, or `silvicultural_method` values in the same motion, and the cycle between `PROPOSED` and `APPROVED` may repeat without bound as conditions on the ground change.

Activation is what makes a prescription live on the calendar: `APPROVED → ACTIVE` is refused with `ERR_STAND_WINDOW_OVERLAP` (HTTP 409) if any *other* `ACTIVE` prescription exists on the same stand whose half-open window overlaps this one — and because both windows are half-open, windows that merely touch at an endpoint do not overlap and are allowed. When the work governed by a prescription is done, completing it moves it `ACTIVE → COMPLETED`. At any point before activation the forester may abandon it: withdrawing from `DRAFT`, `PROPOSED`, or `APPROVED` lands in `WITHDRAWN`. `COMPLETED` and `WITHDRAWN` are terminal.

### 3.4. Offering the Sale: Advertising, Bidding, and Award

A timber sale binds a tract, a stand, and a prescription into an offering. Creating one records `tract_id`, `stand_id`, `prescription_id`, the `sale_type` — `LUMP_SUM` or `PER_UNIT` — the `scaling_rule` that will govern payment, either `DOYLE` or `INTERNATIONAL_14`, the `advertised_minimum_cents` floor on the total bid (zero or more), the bid window `bid_open_at` to `bid_close_at` with the close strictly after the open, and the allowed harvest window `harvest_window_start` to `harvest_window_end` as a half-open interval. Two structural checks guard creation. First, geometry must agree: the sale's `stand_id` must be the prescription's stand and the sale's `tract_id` must be the tract containing that stand, otherwise `ERR_SALE_PRESCRIPTION_STAND_MISMATCH` (HTTP 422). Second, a `PER_UNIT` sale must advertise its per-species floor rates in `species_minimum_rates` — entries pairing each species with a `min_rate_cents_per_mbf`, a non-negative integer of cents — while a `LUMP_SUM` sale must not carry them; violations are `ERR_SPECIES_RATE_MISSING` (HTTP 422). The sale is born `DRAFT`.

Offering the sale is a four-gate transition `DRAFT → OFFERED`, evaluated in this order. No conservation enrollment window on the tract may overlap the sale's harvest window — the comparison uses closed-interval day semantics, so overlap exists whenever the harvest start falls on or before the enrollment end and the enrollment start falls on or before the harvest end — and the tract must still be `OPEN`; violation is `ERR_CONSERVATION_ENROLLMENT_CONFLICT` (HTTP 409). The prescription must be `APPROVED`, else `ERR_PRESCRIPTION_NOT_APPROVED` (HTTP 409). The prescription's cruise must be `CERTIFIED`, else `ERR_CRUISE_NOT_CERTIFIED` (HTTP 409). And the cruise's `certified_at` must lie within 24 months of the logical clock, else the cruise is stale and the offer is refused with `ERR_CRUISE_EXPIRED` (HTTP 422); the boundary is exclusive — only a clock strictly later than `certified_at` plus 24 months is stale, so a cruise exactly 24 months old may still be offered. Once offered, opening bidding moves the sale `OFFERED → BIDDING_OPEN`.

Bidding is the buyers' arena. A `Buyer` submits a bid carrying `expected_sale_version` for optimistic concurrency, a `deposit_cents` amount of zero or more, and exactly one pricing payload: `lump_sum_amount_cents` (likewise zero or more) for a `LUMP_SUM` sale, or `species_rates` for a `PER_UNIT` sale covering every advertised species with a `rate_cents_per_mbf` (a non-negative integer of cents) for each — entries naming species beyond the advertised set are accepted, but they are exempt from the floor check and contribute nothing to `bid_total_cents`. Supplying the wrong payload for the sale type — or mixing both — is `ERR_SPECIES_RATE_MISSING` (HTTP 422). The `buyer_id` is not supplied; it is taken from the acting buyer's `X-User-ID`, which must name a registered buyer — an unregistered one is refused with `ERR_PARTY_NOT_FOUND` (HTTP 404) before the request body is examined — and `submitted_at` is stamped from the logical clock. Acceptance is gated, in order, by the sale being `BIDDING_OPEN` (`ERR_SALE_NOT_OPEN_FOR_BIDDING`, HTTP 409), by the pricing-payload shape check above (`ERR_SPECIES_RATE_MISSING`, HTTP 422), by the clock lying at or after `bid_open_at` and strictly before `bid_close_at` (`ERR_BID_WINDOW_NOT_OPEN`, HTTP 409), by each per-unit species rate meeting or exceeding the advertised `min_rate_cents_per_mbf` floor for that species (`ERR_BID_BELOW_MINIMUM`, HTTP 422), and finally by the stale-version gate (`ERR_STALE_VERSION`, HTTP 412). The bid's `bid_total_cents` is computed at submission: for `LUMP_SUM` it is simply `lump_sum_amount_cents`; for `PER_UNIT` it is the sum over the advertised species of each species' rate multiplied by the certified volume for that species from the sale's underpinning certified cruise — an advertised species absent from the certified breakdown contributes a volume of zero — and divided by 1000, each species line rounded half up to whole cents *before* the lines are summed. Every accepted bid also advances the sale's `version` by 1, which is exactly what arms the OCC gate for the next bidder. A buyer who bids again on the same sale replaces their own prior entry: the earlier `SUBMITTED` bid moves to `SUPERSEDED` with its `version` incremented, and the new bid becomes that buyer's sole `SUBMITTED` bid, born at `version` 1. A buyer may also bow out: withdrawing is allowed on the buyer's own `SUBMITTED` bid while the sale is `BIDDING_OPEN` (otherwise `ERR_SALE_NOT_OPEN_FOR_BIDDING`, HTTP 409) and the clock has not yet reached `bid_close_at` (otherwise `ERR_BID_WINDOW_NOT_OPEN`, HTTP 409), moving the bid to `WITHDRAWN`.

Closing the bidding requires the clock to have reached `bid_close_at` — an earlier close is refused with `ERR_INVALID_TRANSITION` (HTTP 409) — and moves the sale `BIDDING_OPEN → BIDDING_CLOSED` while the bid book is evaluated. Every `SUBMITTED` bid whose `bid_total_cents` falls below `advertised_minimum_cents` is moved to `DISQUALIFIED` — a bid exactly equal to the minimum qualifies. Among the bids that remain, `winning_bid_id` is the highest `bid_total_cents`; ties break first toward the larger `deposit_cents`, then toward the earlier `submitted_at`, then toward the buyer whose `created_at` is earliest, and any tie still unresolved falls to the bid recorded earliest. If no bid qualifies, `winning_bid_id` is null. Every bid evaluated has its `version` incremented. `WITHDRAWN` and `SUPERSEDED` bids play no part in the evaluation.

Award converts the book into a contract: from `BIDDING_CLOSED`, the forester's award request must name a `bid_id` — one naming no existing bid is `ERR_BID_NOT_FOUND` (HTTP 404), checked before the sale's state — exactly equal to the computed `winning_bid_id`, or it is refused with `ERR_NOT_WINNING_BID` (HTTP 409). On award the sale becomes `AWARDED`, `awarded_value_cents` is set to the winning `bid_total_cents`, the winning bid moves to `WINNING`, every other `SUBMITTED` bid moves to `LOST`, and a harvest contract is created in `PENDING_BOND` bearing the winning buyer, the awarded value, the sale's scaling rule, and a computed bond requirement (§3.5). The award response is HTTP 200 carrying the updated sale, not the new contract. When `winning_bid_id` is null the forester instead declares no-sale — declaring one while a qualifying winner exists is refused with `ERR_INVALID_TRANSITION` (HTTP 409): the sale moves `BIDDING_CLOSED → NO_SALE` and all `SUBMITTED` bids move to `LOST`. A no-sale is not the end — reoffering moves `NO_SALE → OFFERED` with a fresh bid window supplied in the request (`bid_open_at` and `bid_close_at`, close strictly after open) and optionally a new `advertised_minimum_cents`; the closed-interval conservation-enrollment overlap check is re-run against the sale's harvest window, and a conflict is again `ERR_CONSERVATION_ENROLLMENT_CONFLICT`. The reoffer loop may repeat. Cancellation is available to the forester or the tract-owning landowner from `DRAFT`, `OFFERED`, `BIDDING_OPEN`, `BIDDING_CLOSED`, or `NO_SALE` and lands in `CANCELLED`; cancelling from any state that can still hold live bids moves every `SUBMITTED` bid on the sale to `WITHDRAWN` (by the time a sale sits in `NO_SALE`, its bids have already been resolved to `LOST`, so none remain to withdraw). `AWARDED` and `CANCELLED` are terminal. Bid terminal states are `WITHDRAWN`, `DISQUALIFIED`, `WINNING`, `LOST`, and `SUPERSEDED`.

### 3.5. The Harvest Contract: Bonding, Assignment, and the Default–Cure Loop

The contract created at award opens in `PENDING_BOND` with `contractor_id` still null. Its ledgers all start at zero: `cumulative_verified_bf` at 0, `verified_volume_by_species` empty, `billed_total_cents`, `disbursed_total_cents`, `refunded_total_cents`, `holdback_balance_cents`, and `consulting_fee_total_cents` each 0, `open_major_findings_count` 0, and `defaulted_at` and `harvest_completed_at` null. Three of these — `cumulative_verified_bf`, `verified_volume_by_species` (rendered as an array of `{"species": <code>, "volume_bf": <board feet>}` entries sorted by species code ascending), and `open_major_findings_count` — are derived projections recomputed from the ticket and inspection books on every read, not stored counters. The sale's scaling rule is frozen onto the contract as `governing_scaling_rule`, and the awarded value is copied onto it as `awarded_value_cents`.

The performance bond requirement, `required_bond_amount_cents`, is computed at award and never changes thereafter. The base rate is tiered on the awarded value: 10 percent when `awarded_value_cents` is at most 10,000,000 cents, 7 percent when it is at most 50,000,000 cents, and 5 percent above that. The tiered percentage is applied to the awarded value and then surcharged by 25 percent per prior default on the winning buyer's record — the multiplier is one plus 0.25 times the buyer's `prior_defaults` — and the result is rounded half up to whole cents. Finally the amount is clamped: never less than 500,000 cents, never more than 10,000,000 cents.

The winning buyer activates the contract by posting the bond: the posted `amount_cents` must equal `required_bond_amount_cents` exactly, neither over nor under, or the posting is refused with `ERR_BOND_AMOUNT_MISMATCH` (HTTP 422). Posting creates the performance bond in `POSTED` and moves the contract `PENDING_BOND → ACTIVE`; the response is HTTP 201 carrying the created bond. The bond immediately earmarks a reforestation reserve: `reforestation_hold_cents` is the smaller of the posted amount and the stand's `acres` multiplied by 35,000 cents per acre, that product rounded half up to whole cents. While the contract is `PENDING_BOND` or `ACTIVE`, the buyer may assign or reassign the logging contractor by naming a `contractor_id`; the contractor must exist, else `ERR_PARTY_NOT_FOUND`. Assignment changes nothing else about the contract's state.

Breaking ground is the assigned contractor's act, and it is heavily gated: starting the harvest moves `ACTIVE → HARVESTING` only when the acting contractor is the contract's `contractor_id`, when `open_major_findings_count` is zero — any open `MAJOR` BMP finding refuses the start with `ERR_OPEN_MAJOR_FINDING` (HTTP 409), and this check precedes the window checks — when the clock's date lies within the sale's harvest window and within the prescription's window, both treated as half-open intervals (violation: `ERR_SEASON_WINDOW_VIOLATION`, HTTP 422), and when the prescription itself is `APPROVED` or `ACTIVE` — a check evaluated after the window checks, a failure being `ERR_PRESCRIPTION_NOT_APPROVED` (HTTP 409).

Suspension is the system's emergency brake. A forester may suspend a `HARVESTING` contract directly, and §3.7 describes how a major inspection finding does so automatically; either way the contract moves `HARVESTING → SUSPENDED` and the stop-work cascade runs in three links. Link one is the contract's own transition. Link two flags the scale records: every scale ticket of the contract in `DRAFT` or `VERIFIED` has `flagged_for_review` set to true, without incrementing the tickets' versions. Link three unwinds unsettled money: every settlement of the contract still in `DRAFT` whose `ticket_ids` intersect the newly flagged tickets is moved to `VOID`, reversing its `gross_cents` out of `billed_total_cents`, its `holdback_cents` out of `holdback_balance_cents`, and its `fee_cents` out of `consulting_fee_total_cents`. Each voided settlement's `version` increments, and the contract's `version` increments once for the suspension itself and once more per settlement the cascade voids. Resuming returns `SUSPENDED → HARVESTING` and is allowed only when no open `MAJOR` finding remains (`ERR_OPEN_MAJOR_FINDING`). Completing the harvest is again the assigned contractor's act, from `HARVESTING` with zero open major findings: the contract moves to `HARVEST_COMPLETE`, `harvest_completed_at` is stamped from the clock, and — as §3.8 details — a reforestation obligation is created in `IMPOSED` with a planting deadline 365 days out.

When things go wrong, the default machinery takes over. A forester may declare default from `ACTIVE`, `HARVESTING`, or `SUSPENDED`, optionally carrying a `reason` string, which is validated but not persisted on the contract; the contract moves to `DEFAULTED`, `defaulted_at` is stamped, and the bond — if `POSTED` — is automatically claimed, moving to `FORFEIT_CLAIMED` without any separate filing. The buyer then has a cure window: curing moves `DEFAULTED → HARVESTING`, requires the acting party to be the contract's buyer, requires the clock to be no more than 14 days past `defaulted_at` (a later cure is `ERR_CURE_PERIOD_EXPIRED`, HTTP 422), and requires the bond to sit in `FORFEIT_CLAIMED` — a bond in any other state refuses the cure with `ERR_INVALID_TRANSITION` (HTTP 409); on cure the pending claim is automatically denied and the bond returns to `POSTED`, with both the contract's and the bond's versions incrementing. If the claim has instead been upheld, the forester terminates: `DEFAULTED → TERMINATED` requires the bond to be `FORFEITED` — a bond in any other state refuses termination with `ERR_INVALID_TRANSITION` (HTTP 409) — and termination increments the buyer's `prior_defaults` by one — the same counter that will surcharge this buyer's next bond by 25 percent per default.

The bond's own lifecycle revolves around the claim loop. Any forester may file a forfeiture claim against a `POSTED` bond, moving it to `FORFEIT_CLAIMED`; declaration of default and declaration of reforestation delinquency file such claims automatically. Adjudication belongs to the `PlatformAdmin` alone and takes a `decision` of `UPHELD` or `DENIED` along with two optional figures, `remediation_cost_cents` and `resale_shortfall_cents`, each a non-negative integer of cents defaulting to zero when omitted. A denied claim returns the bond `FORFEIT_CLAIMED → POSTED`, exactly as a cure does. An upheld claim moves the bond to `FORFEITED` and runs the forfeiture waterfall, which drains `amount_cents` through four buckets in a fixed order: first `admin_fee_cents` takes the smaller of 250,000 cents and the remaining balance; then `remediation_offset_cents` takes the smaller of the payload's `remediation_cost_cents` and what remains; then `shortfall_offset_cents` takes the smaller of the payload's `resale_shortfall_cents` and what remains; and everything left is `refunded_cents`, returned to the buyer. The four buckets always sum exactly to `amount_cents`. At the happy end of a contract, the forester releases the bond: release requires the bond `POSTED`, the contract in `HARVEST_COMPLETE` or `CLOSED` (otherwise `ERR_INVALID_TRANSITION`, HTTP 409), and the reforestation obligation `SATISFIED` — an outstanding obligation refuses the release with `ERR_BOND_HOLD_OUTSTANDING` (HTTP 409) — whereupon `released_cents` is set to the full `amount_cents` and the bond becomes `RELEASED`. Bond terminal states are `RELEASED` and `FORFEITED`.

Two closing acts finish the contract's story. Once the obligation is satisfied, a forester may release the retained reforestation holdback: the release is refused with `ERR_REFORESTATION_UNSATISFIED` (HTTP 409) while the obligation is not `SATISFIED`, and on success the entire `holdback_balance_cents` is moved into `disbursed_total_cents` and the holdback balance returns to zero, all without incrementing the contract's `version`. Final close moves `HARVEST_COMPLETE → CLOSED` behind three gates evaluated in order: no bond hold outstanding (`ERR_BOND_HOLD_OUTSTANDING`), every settlement of the contract in `PAID`, `REFUNDED`, or `VOID` (`ERR_UNPAID_SETTLEMENTS`, HTTP 409), and the reforestation obligation `SATISFIED` (`ERR_REFORESTATION_UNSATISFIED`). `TERMINATED` and `CLOSED` are terminal.

### 3.6. Scaling the Logs, Disputing the Scale, and Settling the Money

Once trucks start rolling, every load is captured as a scale ticket. Either the assigned `Contractor` or a `Forester` may record one, supplying the `contract_id`, the `scaled_date`, the `species` code, the `small_end_diameter_in` (strictly greater than zero), the `length_ft` (strictly greater than zero), and the `log_count` of identical logs on the ticket (at least 1). The creator's `X-User-ID` is persisted as `recorded_by_id`, and the ticket is born in `DRAFT` with `flagged_for_review` false. Tickets may only be recorded against a contract that is `HARVESTING`; a contract in `SUSPENDED` or any other state refuses the ticket with `ERR_CONTRACT_SUSPENDED` (HTTP 409).

Board feet are computed once, at creation, and never recomputed. The ticket carries both log rules. Under Doyle, the per-log figure takes the small-end diameter in inches, subtracts 4, divides by 4, squares the result, multiplies by the length in feet, and rounds the product *down* to a whole board foot; `bf_doyle` is that per-log value multiplied by `log_count`. Under International 1/4-inch, the per-log figure is 0.79 times the square of the diameter, minus twice the diameter, minus 4, the difference multiplied by the length and divided by 16, rounded half up to a whole board foot; `bf_international` is that per-log value multiplied by `log_count`. In both rules the rounding happens per log *before* the log-count multiplication. The `bf_governing` used for payment is whichever of the two the contract's `governing_scaling_rule` selects — `DOYLE` selects `bf_doyle`, `INTERNATIONAL_14` selects `bf_international` — and identical log dimensions yield different figures under the two rules.

A volume allowance protects the landowner from overcut relative to the certified inventory. For the ticket's species, the allowance is the certified per-species volume from the contract's underpinning certified cruise multiplied by 110 percent and rounded half up to whole board feet — a species absent from the certified breakdown has an allowance of zero. The running cumulative is the sum of `bf_governing` over all of the contract's tickets of that species in `DRAFT`, `VERIFIED`, or `DISPUTED` — `VOID` tickets do not count. If the running cumulative plus the new ticket's `bf_governing` would strictly exceed the allowance, the ticket is refused with `ERR_VOLUME_ALLOWANCE_EXCEEDED` (HTTP 422); landing exactly on the allowance is permitted.

Verification converts a tally into payable volume and is deliberately a two-person job: the verifying forester's `X-User-ID` must differ from the ticket's `recorded_by_id`, or the verify is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Verification also requires the contract to be `HARVESTING` (`ERR_CONTRACT_SUSPENDED` otherwise); the gates fire in this order — state admissibility, then the contract-state gate, then the segregation-of-duties check. On success the ticket moves `DRAFT → VERIFIED`, `verified_at` is stamped from the clock, `verified_by_id` records the verifier, `flagged_for_review` is cleared, the contract's `cumulative_verified_bf` and `verified_volume_by_species` are recomputed over its `VERIFIED` tickets, and both the ticket's and the contract's versions increment. The verified volume is not beyond challenge: within 10 days of `verified_at`, the tract-owning landowner or the contract's buyer may dispute the ticket — later disputes are refused with `ERR_DISPUTE_WINDOW_PASSED` (HTTP 422), the comparison being made on instants rather than calendar dates so that a dispute exactly 10 days after `verified_at` is still admissible — optionally carrying a `reason` string, which is validated (before the ownership check fires) but not persisted on the ticket, moving it `VERIFIED → DISPUTED` and recomputing the contract's cumulative verified figures with the disputed ticket excluded — a recompute that happens on read, so the contract's `version` does not increment on dispute or on resolution. Resolution belongs to the forester: resolving with `resolution` `ACCEPT` returns the ticket `DISPUTED → VERIFIED` and re-includes it in the cumulative figures, while resolving with `resolution` `VOID` moves it to `VOID`. A ticket still in `DRAFT` may be voided directly. `VOID` is the only terminal ticket state; the dispute loop between `VERIFIED` and `DISPUTED` may repeat.

Settlements turn verified volume — or contract milestones — into money. A forester creates a settlement against a contract with a `kind` that must match the contract's sale type — a mismatch is a malformed request (`ERR_INVALID_REQUEST`, HTTP 400): `PER_UNIT_PERIOD` for a per-unit sale, `LUMP_MILESTONE` for a lump-sum sale. The two kinds' payloads are exclusive: a `PER_UNIT_PERIOD` settlement must carry `period_start` and `period_end` and no `milestone`, while a `LUMP_MILESTONE` settlement must carry a `milestone` and no period dates; a payload that mixes or omits these is rejected as a malformed request (`ERR_INVALID_REQUEST`, HTTP 400). A `PER_UNIT_PERIOD` settlement carries `period_start` and `period_end`, the end strictly after the start, treated as a half-open interval; the period may not overlap the period of any existing non-`VOID` period settlement on the same contract (`ERR_SETTLEMENT_PERIOD_OVERLAP`, HTTP 422), and touching endpoints do not overlap. The system then sweeps the ticket book: eligible tickets are those of the contract in `VERIFIED` whose `scaled_date` falls within the period and whose ids do not already appear in any non-`VOID` settlement's `ticket_ids`. A period that sweeps no eligible ticket at all is refused with `ERR_SETTLEMENT_PERIOD_EMPTY` (HTTP 422). The swept tickets are recorded in the settlement's `ticket_ids`, ordered by ticket creation order, and `gross_cents` is the sum over them of the winning bid's per-species rate applied to each ticket's `bf_governing` divided by 1000 — a ticket whose species the winning bid does not price contributes zero — each ticket line rounded half up to whole cents *before* the lines are summed, never sum-then-round. The reforestation `holdback_cents` is ten percent of the gross, rounded half up. A `LUMP_MILESTONE` settlement instead carries a `milestone` — `MOBILIZATION`, `MIDPOINT`, or `COMPLETION` — each usable exactly once and only in that order, counting only non-`VOID` milestone settlements, so a voided milestone settlement frees its milestone for reuse; an out-of-order or repeated milestone is refused with `ERR_INVALID_TRANSITION` (HTTP 409). Mobilization and midpoint each pay forty percent of `awarded_value_cents`, rounded half up; mobilization requires the contract to be `HARVESTING` (otherwise `ERR_INVALID_TRANSITION`, HTTP 409), while midpoint is gated on volume alone, requiring `cumulative_verified_bf` to have reached at least half of the certified total volume, the half itself rounded half up to whole board feet (otherwise `ERR_INVALID_TRANSITION`, HTTP 409). Completion pays the remainder — the awarded value minus the mobilization and midpoint grosses — and requires the contract to be `HARVEST_COMPLETE` (otherwise `ERR_INVALID_TRANSITION`, HTTP 409). Milestone settlements carry no holdback: `holdback_cents` is always zero.

The consulting fee rides on every settlement regardless of kind, and its tier is keyed on cumulative gross, never on net or post-fee values. The evaluation order is pinned: first form the tentative billed total as the contract's `billed_total_cents` before this settlement plus this settlement's `gross_cents`; then select the tier from that tentative figure — 8.0 percent when it is at most 5,000,000 cents, 6.5 percent when it is at most 20,000,000 cents, and 5.0 percent above that; then `fee_cents` is this settlement's gross multiplied by the tier percentage, rounded half up. The `net_cents` payable to the landowner is the gross minus the holdback minus the fee. At creation the settlement sits in `DRAFT` and its figures immediately flow into the contract ledgers: `billed_total_cents` increases by `gross_cents`, `holdback_balance_cents` by `holdback_cents`, and `consulting_fee_total_cents` by `fee_cents` — ledger updates that do not increment the contract's `version`. The billed total accumulates settlements in `DRAFT`, `APPROVED`, `PAID`, and `REFUNDED`; `VOID` settlements never count.

Approval belongs to the landowner who owns the contract's tract: approving moves `DRAFT → APPROVED` and sets `due_date` to the clock's date plus 30 days. Payment discipline is enforced on read: whenever an `APPROVED` settlement is fetched or listed and the clock's date has passed `due_date`, `accrued_interest_cents` is computed on the fly as simple interest on the net — the number of whole 30-day periods contained in the days late, times 1.5 percent of `net_cents` per period, the final product rounded down to whole cents. Negative days late count as zero, no compounding occurs, and a payment 29 days late accrues nothing at all. The `accrued_interest_cents` field is present on every settlement read and reads 0 whenever the settlement is not `APPROVED`. Disbursement by a forester moves `APPROVED → PAID` and adds `net_cents` into the contract's `disbursed_total_cents`. A payment made in error is unwound by refunding: `PAID → REFUNDED` subtracts `net_cents` from `disbursed_total_cents` and adds it to `refunded_total_cents`, a compensating move that keeps the sum of disbursed and refunded conserved. Voiding a settlement still in `DRAFT` moves it to `VOID` and reverses its gross, holdback, and fee out of the contract's billed, holdback, and fee ledgers — the same reversal the stop-work cascade applies to affected draft settlements. `PAID`, `REFUNDED`, and `VOID` are terminal.

### 3.7. BMP Compliance: Inspections and the Stop-Work Cascade

Best-management-practice oversight runs on inspections. A forester schedules one by naming the `contract_id`, the `inspection_type` — `PRE_HARVEST`, `ACTIVE_HARVEST`, or `CLOSEOUT` — and the `scheduled_date`; the inspection opens in `SCHEDULED`. From there the badge passes to the `AgencyInspector`. Conducting the field visit moves `SCHEDULED → CONDUCTED`. Closing the visit requires an `outcome`: `COMPLIANT` ends the inspection cleanly, while `NONCOMPLIANT` requires a `severity` of `MINOR` or `MAJOR` — a missing `severity` on `NONCOMPLIANT`, or a `severity` supplied with `COMPLIANT`, is a malformed request (`ERR_INVALID_REQUEST`, HTTP 400) — and may record a `remediation_cost_estimate_cents` figure (a non-negative integer of cents, zero when omitted) and free-text `findings` (empty when omitted); on a `COMPLIANT` close any supplied remediation figure or findings text is accepted but not persisted, the fields remaining zero and empty.

A `MAJOR` noncompliance on a contract that is currently `HARVESTING` is the automatic trigger for the stop-work cascade of §3.5: the contract is suspended on the spot — which itself flags every `DRAFT` and `VERIFIED` scale ticket of the contract for review and voids every affected `DRAFT` settlement with its billed, holdback, and fee reversals — and the contract's `open_major_findings_count` is recomputed. A `MINOR` finding, or a `MAJOR` finding on a contract not currently harvesting, records the noncompliance and recomputes the count without disturbing the contract's state. Either way, an open `MAJOR` finding blocks three operations until cleared: starting the harvest, resuming from suspension, and completing the harvest all refuse with `ERR_OPEN_MAJOR_FINDING`. Once the operator demonstrates corrective action, the inspector verifies it, moving the inspection `NONCOMPLIANT → CORRECTIVE_VERIFIED` and recomputing the count again — but note the asymmetry: corrective verification does not itself resume the contract; only a forester's explicit resume does, and only once the count of open major findings has fallen to zero. `COMPLIANT` and `CORRECTIVE_VERIFIED` are terminal.

### 3.8. Reforestation: Planting Deadlines, Survival Surveys, and Delinquency

Completing a harvest automatically imposes a reforestation obligation on the contract, one obligation per contract, created in `IMPOSED` with `plant_by_date` set to the harvest completion date plus 365 days, `current_planted_count` at 0, and `planted_date` null. Planting is the assigned contractor's job: recording a planting supplies the `planted_date` and the `seedlings_planted` count (zero or more), moves the obligation from `IMPOSED` — or, on the replant loop, from `REPLANT_REQUIRED` — into `PLANTED`, and replaces `current_planted_count` with the seedlings figure from this most recent planting and `planted_date` with the supplied date. Planting after the deadline is refused: the clock's date must fall on or before `plant_by_date`, else `ERR_PLANTING_DEADLINE_PASSED` (HTTP 422).

Proof comes a growing season later. A forester opens a survival survey against a `PLANTED` obligation, supplying the `survey_date` and the `live_seedlings_count` of zero or more; the survey date must fall at least 365 days after the most recent `planted_date` — an earlier survey is `ERR_SURVEY_TOO_EARLY` (HTTP 422). Creating the survey places it in `RECORDED` and moves the obligation `PLANTED → SURVEYED`. Finalizing the survey requires it to be `RECORDED`, the obligation to be `SURVEYED`, and `current_planted_count` to be greater than zero — the latter two failures are refused with `ERR_INVALID_TRANSITION` (HTTP 409); the `survival_pct` is then the live count divided by the current planted count, multiplied by 100, rounded half up to two decimal places, and the `result` is `PASS` when the rounded percentage is at least 85.00 — a survival of exactly 85.00 passes — and `FAIL` below it. A pass moves the obligation `SURVEYED → SATISFIED`, which is the terminal state that unblocks both the bond release and the contract close. A fail moves it `SURVEYED → REPLANT_REQUIRED`, resets `plant_by_date` to the `survey_date` plus another 365 days, and reaches across to the performance bond: `reforestation_hold_cents` is recomputed upward as the smaller of the bond's `amount_cents` and the stand's `acres` multiplied by 45,000 cents per acre — up from the 35,000-per-acre figure used at posting — incrementing the bond's `version` alongside the obligation's, and applying whenever a bond exists for the contract, whatever the bond's current status. The replant loop then turns again: the contractor records a new planting, a new survey follows no earlier than 365 days later, and so on until a survey passes. A survey recorded in error can be voided while still `RECORDED`, which returns the obligation from `SURVEYED` to `PLANTED` — without incrementing the obligation's `version` — so a corrected survey can be taken; `FINALIZED` and `VOID` are the survey's terminal states.

When no planting happens at all, the obligation curdles. A forester may declare delinquency on an `IMPOSED` obligation once the clock's date has passed `plant_by_date` — an attempt on or before that date is refused with `ERR_INVALID_TRANSITION` (HTTP 409) — moving it to `DELINQUENT`, a state no transition leaves (further lifecycle actions on a `DELINQUENT` obligation are refused with `ERR_INVALID_TRANSITION`, not `ERR_ALREADY_TERMINAL`); if the contract's bond is still `POSTED`, the declaration automatically files a forfeiture claim against it, moving the bond to `FORFEIT_CLAIMED` for adjudication under the waterfall of §3.5.

### 3.9. The Conservation Alternative: Carbon Valuation and Enrollment

Not every tract should be cut. A forester may prepare a carbon valuation for a tract, supplying the `tract_id`, the optimistic-concurrency field `expected_tract_version`, the `annual_credits_tco2e` expected from the project (strictly greater than zero), the `baseline_credits_tco2e` representing business-as-usual credits (zero or more, and strictly less than the annual figure), the `price_cents_per_tco2e` (strictly greater than zero), the forester's `estimated_timber_net_cents` for comparison (zero or more), and the proposed `enrollment_start` date. Creation requires the tract to be `OPEN` — valuing a tract already enrolled in conservation is refused with `ERR_CONSERVATION_ENROLLMENT_CONFLICT` (HTTP 409) — and the stale-tract gate rejects a client whose view of the tract is out of date with `ERR_STALE_VERSION` (HTTP 412).

Both net-present-value variants are computed at creation. The annuity factor is twenty years of credits discounted at five percent: one minus the quantity 1.05 raised to the negative-twentieth power, the whole divided by 0.05, carried at full precision with no intermediate rounding. The `gross_npv_cents` multiplies the full `annual_credits_tco2e` by the price and by the annuity factor, rounded half up to whole cents. The `net_npv_cents` first subtracts the baseline — so identical inputs yield a strictly smaller net whenever the baseline exceeds zero — then applies the same price and annuity, again rounded half up only at the end. The `enrollment_end` is computed as `enrollment_start` plus twenty years, landing on the same month and day (a February 29 start lands on February 28 of the target year). The `recommendation` compares the two land uses: `CONSERVATION_FAVORED` when `net_npv_cents` is at least the estimated timber net marked up by ten percent — that markup itself rounded half up to whole cents — and `TIMBER_FAVORED` otherwise. The valuation opens in `VALUED`, and creating a new valuation on a tract that already has a `VALUED` one supersedes the predecessor: the prior valuation moves to `SUPERSEDED` with its `version` incremented — the new valuation is born at `version` 1 — and the tract's own `version` advances, which is what arms the next creator's `expected_tract_version` gate.

The decision belongs to the landowner who owns the tract. Rejecting moves `VALUED → REJECTED` and ends the matter. Accepting moves `VALUED → ACCEPTED` but is blocked while any harvest contract rooted in any sale of the tract is still live — that is, in `PENDING_BOND`, `ACTIVE`, `HARVESTING`, `SUSPENDED`, `HARVEST_COMPLETE`, or `DEFAULTED`; the block surfaces as `ERR_ACTIVE_CONTRACT_BLOCKS_CONSERVATION` (HTTP 409). On acceptance the tract moves `OPEN → ENROLLED_CONSERVATION`, its `conservation_enrollment_start` and `conservation_enrollment_end` are set from the valuation's enrollment window — a closed interval, so a harvest window touching either bound counts as overlapping — and the cascade cleans the slate: every sale of the tract in `DRAFT`, `OFFERED`, `BIDDING_OPEN`, `BIDDING_CLOSED`, or `NO_SALE` is moved to `CANCELLED`, and every `SUBMITTED` bid on those sales moves to `WITHDRAWN`. From then on, the enrollment window stands as a permanent gate of §3.4: no sale on the tract may be offered or reoffered with a harvest window overlapping it, under the same closed-interval day semantics. `ACCEPTED`, `REJECTED`, and `SUPERSEDED` are terminal for a valuation; a tract in `ENROLLED_CONSERVATION` stays there.

## 4. Endpoint Definitions

All endpoints live under the `/forestry` mount (the clock utility aside). Endpoints that create a new resource return HTTP 201; endpoints that modify, transition, or read an existing resource return HTTP 200. Request and response payloads follow the envelope of §2.2, and the full parameter semantics for each operation are those narrated in §2 and §3 — this table is a locator, not a schema.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /forestry/foresters | Register a consulting forester | PlatformAdmin |
| POST | /forestry/landowners | Register a landowner | PlatformAdmin |
| POST | /forestry/buyers | Register a timber buyer; optional `prior_defaults` seeds the default counter | PlatformAdmin |
| POST | /forestry/contractors | Register a logging contractor | PlatformAdmin |
| POST | /forestry/tracts | Create a forest tract under a landowner with a consulting forester of record | Forester |
| GET | /forestry/tracts/{id} | Fetch a tract | PlatformAdmin, Forester, Landowner, Buyer, Contractor, AgencyInspector |
| GET | /forestry/tracts | List tracts | PlatformAdmin, Forester, Landowner, Buyer, Contractor, AgencyInspector |
| POST | /forestry/stands | Create a stand on a tract | Forester |
| GET | /forestry/stands/{id} | Fetch a stand | PlatformAdmin, Forester, Landowner, Buyer, Contractor, AgencyInspector |
| GET | /forestry/stands | List stands | PlatformAdmin, Forester, Landowner, Buyer, Contractor, AgencyInspector |
| POST | /forestry/cruises | Create an inventory cruise (`DRAFT`) with plot tally rows | Forester |
| GET | /forestry/cruises/{id} | Fetch a cruise | PlatformAdmin, Forester, Landowner, Buyer, Contractor, AgencyInspector |
| GET | /forestry/cruises | List cruises | PlatformAdmin, Forester, Landowner, Buyer, Contractor, AgencyInspector |
| POST | /forestry/cruises/{id}/finalize-tally | Finalize the tally: `DRAFT → TALLIED` | Forester |
| POST | /forestry/cruises/{id}/reconcile | Reconcile plots: `TALLIED → RECONCILED`; computes provisional and certified volumes and sampling error | Forester |
| POST | /forestry/cruises/{id}/reopen | Reopen a reconciliation: `RECONCILED → TALLIED`; clears certified computed fields | Forester |
| POST | /forestry/cruises/{id}/certify | Certify a cruise under OCC on the stand; supersedes the prior certified cruise | Forester |
| POST | /forestry/cruises/{id}/void | Void a cruise from `DRAFT` or `TALLIED` | Forester |
| POST | /forestry/prescriptions | Create a harvest prescription (`DRAFT`) | Forester |
| GET | /forestry/prescriptions/{id} | Fetch a prescription | PlatformAdmin, Forester, Landowner, Buyer, Contractor, AgencyInspector |
| GET | /forestry/prescriptions | List prescriptions | PlatformAdmin, Forester, Landowner, Buyer, Contractor, AgencyInspector |
| POST | /forestry/prescriptions/{id}/propose | Propose: `DRAFT → PROPOSED` | Forester |
| POST | /forestry/prescriptions/{id}/approve | Approve: `PROPOSED → APPROVED` by the tract-owning landowner; requires a certified cruise | Landowner |
| POST | /forestry/prescriptions/{id}/revise | Revise: `APPROVED → PROPOSED` with optional field updates | Forester |
| POST | /forestry/prescriptions/{id}/activate | Activate: `APPROVED → ACTIVE`; enforces half-open window non-overlap per stand | Forester |
| POST | /forestry/prescriptions/{id}/complete | Complete: `ACTIVE → COMPLETED` | Forester |
| POST | /forestry/prescriptions/{id}/withdraw | Withdraw from `DRAFT`, `PROPOSED`, or `APPROVED` | Forester |
| POST | /forestry/sales | Create a timber sale (`DRAFT`); `species_minimum_rates` required iff `PER_UNIT` | Forester |
| GET | /forestry/sales/{id} | Fetch a sale | PlatformAdmin, Forester, Landowner, Buyer, Contractor, AgencyInspector |
| GET | /forestry/sales | List sales | PlatformAdmin, Forester, Landowner, Buyer, Contractor, AgencyInspector |
| POST | /forestry/sales/{id}/offer | Offer: `DRAFT → OFFERED`; gates on prescription, cruise certification and freshness, enrollment non-conflict | Forester |
| POST | /forestry/sales/{id}/open-bidding | Open bidding: `OFFERED → BIDDING_OPEN` | Forester |
| POST | /forestry/sales/{id}/close-bidding | Close bidding at or after `bid_close_at`; evaluates bids and sets `winning_bid_id` | Forester |
| POST | /forestry/sales/{id}/award | Award: `BIDDING_CLOSED → AWARDED`; payload `bid_id` must equal `winning_bid_id`; creates the harvest contract | Forester |
| POST | /forestry/sales/{id}/no-sale | Declare no-sale when no qualifying bid: `BIDDING_CLOSED → NO_SALE` | Forester |
| POST | /forestry/sales/{id}/reoffer | Reoffer: `NO_SALE → OFFERED` with a new bid window | Forester |
| POST | /forestry/sales/{id}/cancel | Cancel a non-terminal sale; its `SUBMITTED` bids are withdrawn | Forester, Landowner |
| POST | /forestry/sales/{sale_id}/bids | Submit a bid under OCC on the sale; a buyer's new bid supersedes their prior `SUBMITTED` bid | Buyer |
| GET | /forestry/bids/{id} | Fetch a bid | PlatformAdmin, Forester, Landowner, Buyer, Contractor, AgencyInspector |
| GET | /forestry/bids | List bids | PlatformAdmin, Forester, Landowner, Buyer, Contractor, AgencyInspector |
| POST | /forestry/bids/{id}/withdraw | Withdraw a `SUBMITTED` bid while bidding is open | Buyer |
| GET | /forestry/contracts/{id} | Fetch a contract | PlatformAdmin, Forester, Landowner, Buyer, Contractor, AgencyInspector |
| GET | /forestry/contracts | List contracts | PlatformAdmin, Forester, Landowner, Buyer, Contractor, AgencyInspector |
| POST | /forestry/contracts/{id}/bond | Post the performance bond: `PENDING_BOND → ACTIVE`; amount must equal `required_bond_amount_cents` | Buyer |
| POST | /forestry/contracts/{id}/assign-contractor | Assign the logging contractor while `PENDING_BOND` or `ACTIVE` | Buyer |
| POST | /forestry/contracts/{id}/start-harvest | Start harvest: `ACTIVE → HARVESTING`; gated on findings, windows, and assignment | Contractor |
| POST | /forestry/contracts/{id}/suspend | Suspend: `HARVESTING → SUSPENDED`; runs the stop-work cascade | Forester |
| POST | /forestry/contracts/{id}/resume | Resume: `SUSPENDED → HARVESTING` when no open `MAJOR` findings | Forester |
| POST | /forestry/contracts/{id}/complete-harvest | Complete harvest: `HARVESTING → HARVEST_COMPLETE`; creates the reforestation obligation | Contractor |
| POST | /forestry/contracts/{id}/declare-default | Declare default from `ACTIVE`, `HARVESTING`, or `SUSPENDED`; auto-claims the bond | Forester |
| POST | /forestry/contracts/{id}/cure | Cure: `DEFAULTED → HARVESTING` within the cure window; auto-denies the pending bond claim | Buyer |
| POST | /forestry/contracts/{id}/terminate | Terminate: `DEFAULTED → TERMINATED` after bond forfeiture; bumps the buyer's `prior_defaults` | Forester |
| POST | /forestry/contracts/{id}/close | Close: `HARVEST_COMPLETE → CLOSED`; requires resolved settlements, released bond, satisfied obligation | Forester |
| POST | /forestry/contracts/{id}/release-holdback | Release the retained holdback to disbursed once the obligation is `SATISFIED` | Forester |
| GET | /forestry/bonds/{id} | Fetch a bond | PlatformAdmin, Forester, Landowner, Buyer, Contractor, AgencyInspector |
| GET | /forestry/bonds | List bonds | PlatformAdmin, Forester, Landowner, Buyer, Contractor, AgencyInspector |
| POST | /forestry/bonds/{id}/claim-forfeiture | Claim forfeiture: `POSTED → FORFEIT_CLAIMED` | Forester |
| POST | /forestry/bonds/{id}/adjudicate | Adjudicate a claim: `FORFEIT_CLAIMED → FORFEITED` (`UPHELD`, runs the waterfall) or back to `POSTED` (`DENIED`) | PlatformAdmin |
| POST | /forestry/bonds/{id}/release | Release: `POSTED → RELEASED` when the obligation is satisfied and harvest is complete | Forester |
| POST | /forestry/scale-tickets | Record a scale ticket (`DRAFT`) under a `HARVESTING` contract; enforces the overrun allowance | Contractor, Forester |
| GET | /forestry/scale-tickets/{id} | Fetch a scale ticket | PlatformAdmin, Forester, Landowner, Buyer, Contractor, AgencyInspector |
| GET | /forestry/scale-tickets | List scale tickets | PlatformAdmin, Forester, Landowner, Buyer, Contractor, AgencyInspector |
| POST | /forestry/scale-tickets/{id}/verify | Verify: `DRAFT → VERIFIED` by a forester other than the recorder | Forester |
| POST | /forestry/scale-tickets/{id}/dispute | Dispute: `VERIFIED → DISPUTED` within the dispute window | Landowner, Buyer |
| POST | /forestry/scale-tickets/{id}/resolve | Resolve a dispute: `DISPUTED → VERIFIED` (`ACCEPT`) or `DISPUTED → VOID` (`VOID`) | Forester |
| POST | /forestry/scale-tickets/{id}/void | Void a `DRAFT` ticket | Forester |
| POST | /forestry/settlements | Create a settlement (`DRAFT`): period settlements sweep eligible `VERIFIED` tickets; milestone settlements pay fixed installments | Forester |
| GET | /forestry/settlements/{id} | Fetch a settlement; computes `accrued_interest_cents` on read | PlatformAdmin, Forester, Landowner, Buyer, Contractor, AgencyInspector |
| GET | /forestry/settlements | List settlements | PlatformAdmin, Forester, Landowner, Buyer, Contractor, AgencyInspector |
| POST | /forestry/settlements/{id}/approve | Approve: `DRAFT → APPROVED` by the tract-owning landowner; sets `due_date` | Landowner |
| POST | /forestry/settlements/{id}/disburse | Disburse: `APPROVED → PAID`; moves `net_cents` to disbursed | Forester |
| POST | /forestry/settlements/{id}/refund | Refund: `PAID → REFUNDED`; compensating move of `net_cents` | Forester |
| POST | /forestry/settlements/{id}/void | Void a `DRAFT` settlement; reverses billed, holdback, and fee | Forester |
| POST | /forestry/inspections | Schedule a BMP inspection (`SCHEDULED`) | Forester |
| GET | /forestry/inspections/{id} | Fetch an inspection | PlatformAdmin, Forester, Landowner, Buyer, Contractor, AgencyInspector |
| GET | /forestry/inspections | List inspections | PlatformAdmin, Forester, Landowner, Buyer, Contractor, AgencyInspector |
| POST | /forestry/inspections/{id}/conduct | Conduct: `SCHEDULED → CONDUCTED` | AgencyInspector |
| POST | /forestry/inspections/{id}/close | Close: `CONDUCTED → COMPLIANT` or `NONCOMPLIANT`; a `MAJOR` on a harvesting contract triggers the stop-work cascade | AgencyInspector |
| POST | /forestry/inspections/{id}/verify-corrective | Verify corrective action: `NONCOMPLIANT → CORRECTIVE_VERIFIED` | AgencyInspector |
| GET | /forestry/obligations/{id} | Fetch a reforestation obligation | PlatformAdmin, Forester, Landowner, Buyer, Contractor, AgencyInspector |
| GET | /forestry/obligations | List reforestation obligations | PlatformAdmin, Forester, Landowner, Buyer, Contractor, AgencyInspector |
| POST | /forestry/obligations/{id}/record-planting | Record a planting: `IMPOSED`/`REPLANT_REQUIRED → PLANTED` by the assigned contractor | Contractor |
| POST | /forestry/obligations/{id}/declare-delinquent | Declare delinquent: `IMPOSED → DELINQUENT` past the planting deadline; auto-claims the bond | Forester |
| POST | /forestry/obligations/{id}/surveys | Create a survival survey (`RECORDED`); obligation `PLANTED → SURVEYED` | Forester |
| GET | /forestry/surveys/{id} | Fetch a survival survey | PlatformAdmin, Forester, Landowner, Buyer, Contractor, AgencyInspector |
| GET | /forestry/surveys | List survival surveys | PlatformAdmin, Forester, Landowner, Buyer, Contractor, AgencyInspector |
| POST | /forestry/surveys/{id}/finalize | Finalize: `RECORDED → FINALIZED`; computes survival and result; obligation moves to `SATISFIED` or `REPLANT_REQUIRED` | Forester |
| POST | /forestry/surveys/{id}/void | Void a `RECORDED` survey; obligation returns to `PLANTED` | Forester |
| POST | /forestry/carbon-valuations | Create a carbon valuation under OCC on the tract; supersedes a prior `VALUED` valuation | Forester |
| GET | /forestry/carbon-valuations/{id} | Fetch a carbon valuation | PlatformAdmin, Forester, Landowner, Buyer, Contractor, AgencyInspector |
| GET | /forestry/carbon-valuations | List carbon valuations | PlatformAdmin, Forester, Landowner, Buyer, Contractor, AgencyInspector |
| POST | /forestry/carbon-valuations/{id}/accept | Accept: `VALUED → ACCEPTED`; enrolls the tract and cancels its open sales | Landowner |
| POST | /forestry/carbon-valuations/{id}/reject | Reject: `VALUED → REJECTED` | Landowner |
| POST | /_clock/set_current_utc | Set the logical clock (ISO 8601 UTC); startup default is exactly 2026-05-01T00:00:00Z and the clock never falls back to wall-clock time | PlatformAdmin |

## 5. Error Code Catalogue

The catalogue below fixes every error identifier and its HTTP status. The conditions that trigger each error are specified in the workflow narratives of §2 and §3.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_NOT_RESOURCE_OWNER | 403 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_PARTY_NOT_FOUND | 404 |
| ERR_TRACT_NOT_FOUND | 404 |
| ERR_STAND_NOT_FOUND | 404 |
| ERR_CRUISE_NOT_FOUND | 404 |
| ERR_PRESCRIPTION_NOT_FOUND | 404 |
| ERR_SALE_NOT_FOUND | 404 |
| ERR_BID_NOT_FOUND | 404 |
| ERR_CONTRACT_NOT_FOUND | 404 |
| ERR_BOND_NOT_FOUND | 404 |
| ERR_TICKET_NOT_FOUND | 404 |
| ERR_SETTLEMENT_NOT_FOUND | 404 |
| ERR_INSPECTION_NOT_FOUND | 404 |
| ERR_OBLIGATION_NOT_FOUND | 404 |
| ERR_SURVEY_NOT_FOUND | 404 |
| ERR_VALUATION_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_TRANSITION | 409 |
| ERR_ALREADY_TERMINAL | 409 |
| ERR_CONTRACT_SUSPENDED | 409 |
| ERR_SALE_NOT_OPEN_FOR_BIDDING | 409 |
| ERR_NOT_WINNING_BID | 409 |
| ERR_OPEN_MAJOR_FINDING | 409 |
| ERR_CONSERVATION_ENROLLMENT_CONFLICT | 409 |
| ERR_ACTIVE_CONTRACT_BLOCKS_CONSERVATION | 409 |
| ERR_STAND_WINDOW_OVERLAP | 409 |
| ERR_PRESCRIPTION_NOT_APPROVED | 409 |
| ERR_CRUISE_NOT_CERTIFIED | 409 |
| ERR_BID_WINDOW_NOT_OPEN | 409 |
| ERR_BOND_HOLD_OUTSTANDING | 409 |
| ERR_UNPAID_SETTLEMENTS | 409 |
| ERR_REFORESTATION_UNSATISFIED | 409 |
| ERR_CRUISE_EXPIRED | 422 |
| ERR_MIN_PLOTS_NOT_MET | 422 |
| ERR_SAMPLING_ERROR_TOO_HIGH | 422 |
| ERR_SALE_PRESCRIPTION_STAND_MISMATCH | 422 |
| ERR_SPECIES_RATE_MISSING | 422 |
| ERR_SEASON_WINDOW_VIOLATION | 422 |
| ERR_SURVEY_TOO_EARLY | 422 |
| ERR_PLANTING_DEADLINE_PASSED | 422 |
| ERR_DISPUTE_WINDOW_PASSED | 422 |
| ERR_CURE_PERIOD_EXPIRED | 422 |
| ERR_SETTLEMENT_PERIOD_OVERLAP | 422 |
| ERR_BID_BELOW_MINIMUM | 422 |
| ERR_VOLUME_ALLOWANCE_EXCEEDED | 422 |
| ERR_BOND_AMOUNT_MISMATCH | 422 |
| ERR_SETTLEMENT_PERIOD_EMPTY | 422 |
| ERR_STALE_VERSION | 412 |



