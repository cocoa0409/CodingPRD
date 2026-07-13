# Special Assessment District API — Product Requirements Document

## 1. Introduction

Local governments fund public improvements — sidewalks, sewers, street lighting, undergrounding — by forming a **special assessment district**: a geographic collection of benefiting parcels that jointly repay the construction cost over time through an improvement bond. This API is the system of record for that entire lifecycle. It governs how a district is proposed and either formed or abandoned after a majority-protest hearing, how construction and incidental costs are apportioned across parcels according to a chosen benefit basis, how an improvement bond is levied and amortized into annual installments, and how those installments are paid, fall delinquent, are redeemed, or ultimately drive a parcel into foreclosure.

The domain is a pricing engine wrapped in a compliance ledger. Every dollar that enters the system as a project cost must land, to the exact cent, on some parcel's assessment; every principal payment must reduce a running ledger without drift; and every state change — a district forming, a bond defaulting, a parcel redeeming out of foreclosure — must cascade cleanly to the dependent records that reference it. The consumers of this API are four distinct actors: a district administrator who runs formation and engineering, a county treasurer who moves money, a parcel owner who protests and pays, and an auditor who watches. This document specifies the contract each of them relies on.

Because the arithmetic here settles real liens against real property, correctness is not negotiable. Apportionment and reallocation conserve principal exactly through a floor-then-distribute discipline; amortization absorbs rounding drift into the final year so that principal components sum back to the original balance; and all money is held and computed in whole cents. The sections that follow define the global contract first, then the business workflows, and finally the endpoint and error catalogues.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to a protected endpoint must carry two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the caller's role. If either header is missing, or if `X-User-Role` is not one of the four recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The four roles are `DistrictAdministrator`, `CountyTreasurer`, `ParcelOwner`, and `Auditor`.

- A `DistrictAdministrator` forms districts, manages parcels, apportions rolls, authorizes and issues bonds, and drives the foreclosure procedure. When `X-User-Role` is `DistrictAdministrator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`.
- A `CountyTreasurer` handles money movement: recording payments, reversing them, marking installments delinquent, honoring payoff quotes, and advancing foreclosures to sale or redemption. When `X-User-Role` is `CountyTreasurer`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity.
- A `ParcelOwner` is the owner of record acting on a single parcel. When `X-User-Role` is `ParcelOwner`, `X-User-ID` is the `id` of the acting `Parcel`; ownership checks on any owner-scoped write compare the target parcel's `id` (or, for a resource that references a parcel, its `parcel_id` foreign key) to `X-User-ID`. A `ParcelOwner` whose `X-User-ID` does not equal the target parcel's `id` on an owner-scoped write is rejected with `ERR_UNAUTHORIZED` (HTTP 403).
- An `Auditor` has read-only oversight of every resource and every disclosure report. When `X-User-Role` is `Auditor`, `X-User-ID` is an opaque identifier not tied to any persisted entity.

All four roles may perform every `GET` read. Write authority is otherwise partitioned by role as detailed in the endpoint catalogue of §4.

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

All list endpoints accept two query parameters, `limit` and `offset`. The `limit` defaults to 10, with a minimum of 1 and a maximum of 100; a requested limit above 100 is capped at 100. The `offset` defaults to 0 and represents the number of records to skip. List results are ordered by `created_at` ascending unless a subsection states otherwise. Every list response includes `limit`, `offset`, `total_count`, and `has_more` inside `meta`, where `total_count` is the total number of records matching the filter before pagination and `has_more` is true when records beyond the current page remain.

### 2.4. Common Resource Properties and Versioning

Most resources share a common set of server-managed properties. Every resource carries an `id`, which is a server-minted UUID with no type prefix, and a `created_at` timestamp recorded in ISO 8601 UTC with three fractional digits. Resources that can be mutated after creation additionally carry an `updated_at` timestamp (same format as `created_at`) and a `version`, an integer that begins at 1 and increments by one on every mutation of that resource.

Two record types are append-only ledger entries and therefore carry **only** `id` and `created_at` — they have no `updated_at` and no `version`: a `ProtestFiling` (an owner's recorded protest against an assessment) and a `Payment` (a recorded remittance against an installment). Even though a `Payment` can later be reversed, that reversal is expressed by flipping its own `reversed` flag and stamping `reversed_at`; it does not carry a `version`. Every other resource — `AssessmentDistrict`, `Parcel`, `AssessmentRoll`, `ImprovementBond`, `Installment`, `PayoffQuote`, `Lien`, and `ForeclosureAction` — carries the full `id`, `created_at`, `updated_at`, and `version` quartet, and any state change or field mutation refreshes `updated_at` and increments `version`.

### 2.5. Nested Resource Retrieval and Path Validation

Several resources are reached through a parent-scoped path — a district's parcels, a parcel's protests, a parcel's payoff quotes, and so on. Path resources are validated strictly left to right. If a district `id` in the path does not exist the request fails with `ERR_DISTRICT_NOT_FOUND` (HTTP 404); a missing parcel yields `ERR_PARCEL_NOT_FOUND`, a missing roll `ERR_ROLL_NOT_FOUND`, a missing bond `ERR_BOND_NOT_FOUND`, a missing installment `ERR_INSTALLMENT_NOT_FOUND`, a missing payment `ERR_PAYMENT_NOT_FOUND`, a missing payoff quote `ERR_QUOTE_NOT_FOUND`, and a missing foreclosure `ERR_FORECLOSURE_NOT_FOUND` — each HTTP 404. The leftmost missing segment is the one reported.

### 2.6. Monetary Precision and Rounding Discipline

All monetary quantities are held and returned as whole integer cents; there are no fractional-cent values anywhere in the system. Wherever a formula produces a non-integer intermediate, the result is rounded to the nearest whole cent using **round half up** (a value ending in exactly half a cent rounds away from zero). This is the default rounding mode throughout. Two calculations override the default with a pinned evaluation order rather than a different rounding mode: apportionment and subdivision reallocation both **floor** each share to whole cents first and then distribute the leftover cents one at a time, precisely so that the parcel shares sum back to the assessable total with no drift (see §3.3 and §3.2). Amortization likewise pins its own order — it rounds each year's interest and administrative components half up but forces the final year's principal to absorb any accumulated rounding difference (see §3.4).

### 2.7. The Logical Clock and Lazy State Promotion

The system runs on a **logical clock** rather than wall-clock time. At startup the clock reads exactly `2026-03-01T00:00:00Z`, and before any client sets it the clock holds this default and never falls back to real time. A district administrator or county treasurer may advance the clock by supplying a `to_iso8601` instant. Advancing the clock has consequences that are applied **lazily**: on any subsequent read or state-affecting operation, a `SCHEDULED` installment whose `due_date` the clock has reached is promoted to `DUE`, and a `QUOTED` payoff quote whose validity window the clock has passed is promoted to `EXPIRED`. These promotions are evaluated as of the current clock value, not the time a record was created.

### 2.8. Optimistic Concurrency on Payoff Quote Creation

Creating a payoff quote against a parcel is guarded by optimistic concurrency control. A create-payoff-quote request must carry `expected_parcel_version` as a required field holding the client's last observed `version` of the target `Parcel`. If `expected_parcel_version` does not equal the parcel's current `version`, the request is rejected with `ERR_STALE_PARCEL_VERSION` (HTTP 412). Creating a new quote is a legitimate product operation that supersedes any prior outstanding quote on the same parcel, so a second create is never treated as a duplicate; the version guard exists solely to prevent computing a payoff on stale figures. For example, if an installment payment debited the parcel's `remaining_principal_cents` (advancing its `version`) after the client read the parcel but before this create arrives, the quote would otherwise be computed against principal that no longer exists — so the stale-version create is rejected. No other endpoint takes a version field.

### 2.9. Cascading Consistency and Ledger Conservation

The district is the top of a flat network of peer records linked by explicit references — a `Parcel` names its `district_id`, an `AssessmentRoll` and an `ImprovementBond` each name their `district_id`, an `Installment` names both its `parcel_id` and its `bond_id`, and protests, payments, quotes, liens, and foreclosures each name the `parcel_id` (or `installment_id`) they attach to. A `Parcel` may also name a `parent_parcel_id` when it was born from the subdivision of another parcel, forming a shallow subdivision tree.

State changes propagate along these references immediately and consistently. When a parcel is fully paid off, its liens are released and its remaining unpaid installments are cancelled; when a district is abandoned, its active parcels are withdrawn; when a foreclosure reaches sale, the parcel's delinquent installments default, its recorded liens are foreclosed, and the parent bond defaults. Each cascade refreshes `updated_at` and increments `version` on every resource it touches. The governing invariant behind all of this is **principal conservation**: apportionment spreads the assessable total to the cent, subdivision splits a parent's remaining principal to the cent, and every principal payment debits the parcel ledger by exactly the installment's principal component — no cent is ever created or lost.

### 2.10. Validation Ordering and Error Precedence

When more than one validation could fail on a single request, checks are evaluated in a fixed priority order and the first failure is the one reported. The order is: authentication first (`ERR_UNAUTHENTICATED`, HTTP 401), then authorization including parcel-ownership scope (`ERR_UNAUTHORIZED`, HTTP 403), then path-resource existence left to right (the family of 404 not-found errors above), then the optimistic-concurrency check on payoff-quote creation (`ERR_STALE_PARCEL_VERSION`, HTTP 412), then resource-state legality of the requested transition (the family of 409 invalid-state errors), then business-referential preconditions such as the district being formed or a confirmed roll existing (`ERR_DISTRICT_NOT_FORMED` and `ERR_NO_CONFIRMED_ROLL`, both HTTP 409), then business constraints such as APN uniqueness, benefit-unit conservation, installment-year collisions, bond-term overlap, and the foreclosure threshold, then business-temporal checks such as the quote date and the grace period, then the fiscal exact-amount check on payments (`ERR_PAYMENT_AMOUNT_MISMATCH`, HTTP 422), and finally generic body/field validation (`ERR_VALIDATION`, HTTP 422). Concretely, a missing header is reported before a permission problem, a permission problem before a missing path resource, a stale version before an illegal state, an illegal state before an unformed-district check, and a well-formedness problem in the body last of all.

## 3. Business Logic & Workflows

### 3.1. District Formation and the Majority-Protest Hearing

A `DistrictAdministrator` begins by proposing an assessment district, supplying its `name`, a `formation_method`, and the `total_project_cost_cents` — the construction cost to be spread across parcels. The `formation_method` is the apportionment basis and must be one of `BENEFIT_UNITS`, `FRONT_FOOTAGE`, or `LAND_AREA`. Two further inputs are optional: `incidental_cost_cents`, the engineering and incidental costs folded into the assessable total, which defaults to 0; and `protest_threshold_pct`, the majority-protest cutoff, which defaults to 50 and must be greater than 0 and at most 100. Both cost fields must be at least 0. A newly created district is stamped `PROPOSED` and has an empty `total_benefit_units`, an unset `total_apportioned_principal_cents`, and a null `formed_at`.

Into a proposed district the administrator adds parcels, one at a time. Each parcel supplies an `apn` (its assessor parcel number), an `owner_name`, and its apportionment weights — `benefit_units`, `land_area_sqft`, and `front_footage_ft`, each of which must be at least 0. The parcel inherits its `district_id` from the path and is created `ACTIVE` with a `parent_parcel_id` of null. The `apn` must be unique among the parcels of that district; a collision is rejected with `ERR_APN_DUPLICATE` (HTTP 409).

Once at least one `ACTIVE` parcel exists, the administrator opens the majority-protest window, moving the district from `PROPOSED` to `PROTEST_PERIOD`. This transition requires the district to currently be `PROPOSED` and at least one `ACTIVE` parcel to exist; attempting it from any other state fails with `ERR_INVALID_DISTRICT_STATE` (HTTP 409). As a side effect, the district's `total_benefit_units` is recomputed as the sum, over all `ACTIVE` parcels, of the single weight selected by `formation_method` — each parcel's `benefit_units` when the method is `BENEFIT_UNITS`, its `front_footage_ft` when `FRONT_FOOTAGE`, or its `land_area_sqft` when `LAND_AREA`.

During the protest window an owner of record may file a protest against their parcel's assessment. A protest supplies only `filed_by`, the name or identifier of the protesting owner; the server snapshots `weight_units` as that parcel's weight under the district's `formation_method` at the moment of filing. A single parcel may accumulate multiple filings, but it contributes its weight to the protest tally only once.

Closing the hearing forks the district. The administrator closes the protest period, and the district transitions either from `PROTEST_PERIOD` to `FORMED` or from `PROTEST_PERIOD` to `ABANDONED`; either path requires the district to currently be in `PROTEST_PERIOD`, and attempting to close from any other state fails with `ERR_INVALID_DISTRICT_STATE` (HTTP 409). The fork is decided by the **protest ratio**: the total protest weight is the sum of `weight_units`-equivalent weights over every parcel that has at least one protest filing (each such parcel counted once), and the ratio is that protest weight divided by the district's `total_benefit_units`. This ratio is compared against `protest_threshold_pct` expressed as a fraction (the percent divided by 100), using an exact rational comparison with no rounding of the ratio before comparing. Majority protest occurs only when the ratio is **strictly greater than** the threshold fraction; a ratio exactly equal to the threshold is **not** a majority. When the ratio does not exceed the threshold the district moves to `FORMED` and its `formed_at` is set to the current logical clock. When the ratio strictly exceeds the threshold the district moves to `ABANDONED`: every `ACTIVE` parcel cascades to `WITHDRAWN`, and any `SCHEDULED` or `DUE` installment of those parcels cascades to `CANCELLED` (none exist before a bond is levied, but the rule holds for completeness). `ABANDONED` is terminal.

### 3.2. Parcels, Subdivision, and Consolidation

Parcels can be browsed either within a district or across the whole system. A district-scoped listing returns that district's parcels; a global listing accepts `district_id`, `parent_parcel_id`, and `status` filters, so a caller can retrieve every child of a given parent (the reverse lookup over `parent_parcel_id`) or every parcel in a district by status. A single parcel is also fetchable by its `id`.

A parcel may be split into child parcels through **subdivision**, which advances the parent from `ACTIVE` to `SUBDIVIDED`. The request carries a `children` list, each entry describing a new parcel with its own `apn`, `owner_name`, and weights. Subdivision requires the parent to currently be `ACTIVE` — attempting it otherwise yields `ERR_INVALID_PARCEL_STATE` (HTTP 409) — and it requires **benefit-unit conservation**: the sum of the children's `benefit_units` must equal the parent's `benefit_units` exactly, or the request is rejected with `ERR_BENEFIT_UNITS_MISMATCH` (HTTP 422). Each child `apn` must also be unique within the district, or `ERR_APN_DUPLICATE` (HTTP 409) is returned.

On a successful subdivision each child parcel is created with `parent_parcel_id` pointing at the parent and status `ACTIVE`, and the parent's `remaining_principal_cents` is reallocated across the children so that principal is conserved to the cent. The reallocation floors each child's raw share first and distributes leftover cents afterward: for each child, its floored share is the largest whole number of cents not exceeding the parent's `remaining_principal_cents` multiplied by that child's `benefit_units` divided by the parent's `benefit_units`. The leftover — the parent's `remaining_principal_cents` minus the sum of all floored shares — is a non-negative number of cents, and one extra cent is handed to each child in order of descending `benefit_units`, ties broken by earlier `created_at` first, until the leftover is exhausted. Each child's `remaining_principal_cents` is its floored share plus any leftover cent it received, and its `assessed_principal_cents` is set equal to that same `remaining_principal_cents`. The children's principals therefore sum back to the parent's remaining principal exactly, and their `benefit_units` sum back to the parent's. If a bond has already been issued, the parent's `SCHEDULED` installments are cancelled and each child receives a freshly re-amortized set of `SCHEDULED` installments (see §3.4).

Subdivision is reversible through **consolidation**, which returns the parent from `SUBDIVIDED` to `ACTIVE`. Consolidation requires the parent to currently be `SUBDIVIDED`, and it requires every child parcel to be `ACTIVE` with its `remaining_principal_cents` unchanged since the subdivision; if the parent is not `SUBDIVIDED` the request fails with `ERR_INVALID_PARCEL_STATE` (HTTP 409). As a compensating action, each child transitions to `WITHDRAWN` and its `SCHEDULED` installments transition to `CANCELLED`, while the parent is restored to `ACTIVE` with its `remaining_principal_cents` unchanged from before the split — the benefit-unit total is preserved throughout the round trip. If a bond is issued, the parent's `SCHEDULED` installments are regenerated. Both `WITHDRAWN` and `SUBDIVIDED` are terminal states for a parcel.

### 3.3. The Assessment Roll and Apportionment

Once a district is `FORMED`, the administrator draws up an **assessment roll** — the document that spreads the assessable total onto the parcels. Creating a roll produces an `AssessmentRoll` in `DRAFT` status. The request may supply a `method`, one of `BENEFIT_UNITS`, `FRONT_FOOTAGE`, or `LAND_AREA`; if omitted it defaults to the district's `formation_method`. At creation the roll's `total_apportioned_cents` is fixed as the district's `total_project_cost_cents` plus its `incidental_cost_cents` — the full assessable total. Rolls of a district can be listed and filtered by `status`. Creating a second roll on an already-formed district is the reassessment path, described at the end of this subsection.

Confirming a roll advances it from `DRAFT` to `CONFIRMED` and is where apportionment actually runs. Confirmation requires the roll to currently be `DRAFT`, or `ERR_INVALID_ROLL_STATE` (HTTP 409) is returned, and it requires the parent district to be `FORMED`, or `ERR_DISTRICT_NOT_FORMED` (HTTP 409) is returned. The apportionment spreads the roll's assessable total across the district's `ACTIVE` parcels only — parcels that are `SUBDIVIDED` or `WITHDRAWN` are excluded. Each parcel's weight is the value chosen by the roll's `method`: its `benefit_units` for `BENEFIT_UNITS`, its `land_area_sqft` for `LAND_AREA`, or its `front_footage_ft` for `FRONT_FOOTAGE`. Because the same parcels can carry different relative weights under different methods, the same assessable total yields a different per-parcel principal under each method.

The apportionment discipline is floor-then-distribute, pinned so the shares reconcile exactly. Let the denominator be the sum of the chosen weight over all `ACTIVE` parcels. For each parcel, its floored share is the largest whole number of cents not exceeding the assessable total multiplied by that parcel's weight divided by the denominator. The remainder — the assessable total minus the sum of all floored shares — is a non-negative number of leftover cents, and one extra cent is awarded to each parcel in order of descending weight, ties broken by earlier `created_at` first, until the remainder is exhausted. Each parcel's `assessed_principal_cents` is its floored share plus any leftover cent it received, and the assessed principals sum back to the assessable total with no drift.

Confirmation then writes the ledger. Each `ACTIVE` parcel's `remaining_principal_cents` is set to its `assessed_principal_cents` minus any principal already paid on that parcel (zero on the first roll). The district's `total_apportioned_principal_cents` is set equal to the roll's `total_apportioned_cents`, and the roll's `confirmed_at` is stamped with the current logical clock. One `ASSESSMENT` `Lien` is recorded per `ACTIVE` parcel with its `amount_cents` equal to that parcel's `remaining_principal_cents`, skipping any parcel that already has an unreleased `ASSESSMENT` lien. Any previously `CONFIRMED` roll of the district is superseded, transitioning to the terminal `SUPERSEDED` state. Finally, if a bond of this district is already `ISSUED`, confirming a new roll re-amortizes every `SCHEDULED` installment against each parcel's new `remaining_principal_cents` (see §3.4) — this is the reassessment and reallocation path, by which a district's assessments can be recomputed after the original roll.

### 3.4. Bond Authorization, Issuance, and Amortization

To finance the improvement the administrator authorizes an **improvement bond** against the district. Authorization requires an `issuance_date` (the bond's dated date) and accepts several optional terms, each with a default applied when omitted: `coupon_rate_bps`, the annual coupon in basis points, defaults to 500 (that is, 5.00%) and must be greater than 0; `term_years`, the amortization term in whole years and the number of annual installments generated per parcel, defaults to 10 and must be at least 1; `reserve_fund_pct`, the reserve fund as a fraction of apportioned principal, defaults to 0.10 (ten percent) and must be at least 0; `issuance_cost_cents`, underwriting costs folded into par, defaults to 0 and must be at least 0; `admin_fee_bps`, the annual administrative fee in basis points of outstanding principal, defaults to 0 and must be at least 0; and `prepayment_premium_pct`, the premium charged on a payoff as a fraction of remaining principal, defaults to 0.03 (three percent) and must be at least 0. A newly authorized bond is stamped `AUTHORIZED`, with `reserve_fund_cents` and `par_amount_cents` not yet computed. Bonds of a district can be listed and filtered by `status`.

Issuance advances the bond from `AUTHORIZED` to `ISSUED` and lays down the installment schedule. Three preconditions gate it: the bond must currently be `AUTHORIZED`, or `ERR_INVALID_BOND_STATE` (HTTP 409) is returned; the parent district must have a roll in `CONFIRMED` status, or `ERR_NO_CONFIRMED_ROLL` (HTTP 409) is returned; and no other already-`ISSUED` bond of the district may have an amortization window that overlaps this bond's window, or `ERR_BOND_TERM_OVERLAP` (HTTP 409) is returned. A bond's amortization window is the half-open interval that starts at its issuance year and runs up to but not including its issuance year plus `term_years`; two windows overlap when they share any year, and merely adjacent windows (one ending exactly where the next begins) do not overlap and are allowed.

On issuance the derived amounts are computed: `reserve_fund_cents` is the district's `total_apportioned_principal_cents` multiplied by the bond's `reserve_fund_pct`, rounded half up to whole cents; and `par_amount_cents` is the district's `total_apportioned_principal_cents` plus `reserve_fund_cents` plus `issuance_cost_cents`. Then, for each `ACTIVE` parcel, a set of `term_years` installments is generated with `installment_year` running from 1 through the term, each stamped `SCHEDULED`, and each `due_date` set to the bond's `issuance_date` advanced by that many whole years (year one falls one year after the dated date). Every generated `Installment` carries the parcel's `parcel_id` and the bond's `bond_id`.

The per-parcel schedule is a **level debt-service** amortization. For a parcel it starts from a principal of that parcel's `assessed_principal_cents` (or its current `remaining_principal_cents` when a schedule is being re-amortized after reassessment, subdivision, or consolidation). Let the annual rate be `coupon_rate_bps` divided by 10000 and the term be `term_years`. The level debt service — the constant total-of-principal-and-interest targeted each year — is the starting principal multiplied by the annual rate, divided by the quantity one minus the compounding factor, where that compounding factor is one plus the annual rate raised to the power of the negative term; this level figure is rounded half up to whole cents. The schedule is then walked in strictly ascending year order with a running outstanding balance that begins at the starting principal. In each year, the `interest_cents` is the outstanding balance multiplied by the annual rate, rounded half up; the `admin_fee_cents` is the outstanding balance multiplied by `admin_fee_bps` divided by 10000, rounded half up. For every year before the last, the `principal_cents` is the level debt service minus that year's `interest_cents`; in the final year, the `principal_cents` is set to the entire remaining outstanding balance, so that the final year absorbs all accumulated rounding drift and the principal components sum back exactly to the starting principal. Each year's `amount_due_cents` is its `principal_cents` plus `interest_cents` plus `admin_fee_cents`, and the outstanding balance is reduced by that year's `principal_cents` before moving to the next year. Newly scheduled installments carry a `penalty_cents` and `redemption_interest_cents` of 0 until and unless they fall delinquent.

The bond has three system-driven terminal outcomes reached later in the lifecycle. It moves from `ISSUED` to `CALLED` when no parcel of the district has any `remaining_principal_cents` left — that is, when the last parcel prepays (see §3.7). It moves from `ISSUED` to `DEFAULTED` when a foreclosure on any parcel of the district reaches sale (see §3.8). And it moves from `ISSUED` to `RETIRED` at term end, once no installment of the bond is any longer in `SCHEDULED`, `DUE`, or `DELINQUENT` status and at least one installment of the bond has been `PAID` — the bond is then fully amortized. `CALLED`, `DEFAULTED`, and `RETIRED` are all terminal.

### 3.5. Installments, Payments, and Reversals

Beyond the schedule generated at issuance, the administrator can record a **supplemental installment** against a parcel — an adjustment or reassessment charge for a specific year. This request supplies the `bond_id` it belongs to, the `installment_year` (which must be at least 1), the `due_date`, and the `principal_cents`, and it may optionally supply `interest_cents` and `admin_fee_cents`. The new installment is created `SCHEDULED`. Because each amortization year is a discrete point, no two non-cancelled installments may share the same combination of `parcel_id`, `bond_id`, and `installment_year`; a collision with an existing non-`CANCELLED` installment is rejected with `ERR_INSTALLMENT_YEAR_CONFLICT` (HTTP 409). Installments can be fetched individually and listed with filters on `parcel_id`, `bond_id`, `status`, and `installment_year`.

An installment is not payable while `SCHEDULED`. As described in §2.7, once the logical clock reaches an installment's `due_date` the installment is lazily promoted from `SCHEDULED` to `DUE`, and only then does it become payable.

A `CountyTreasurer` records a payment against an installment, and a `ParcelOwner` may pay their own installment. A payment supplies `amount_cents` (which must be greater than 0), a `payment_date`, and `paid_by` identifying the payer, and is stored referencing the installment's `installment_id` with `reversed` false and a null `reversed_at`. Payment is accepted only when the installment is currently `DUE` or `DELINQUENT`; a `SCHEDULED` installment is not yet payable, and a `CANCELLED`, `PAID`, or `DEFAULTED` installment can never be paid, so any of these yields `ERR_INSTALLMENT_NOT_PAYABLE` (HTTP 409). The `amount_cents` must equal the installment's current `amount_due_cents` exactly — no partial or overpayment — or the request is rejected with `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 422). Payment is further only accepted while the parcel is `ACTIVE` or `IN_FORECLOSURE`. A successful payment advances the installment from `DUE` to `PAID` (or from `DELINQUENT` to `PAID` when redeeming a delinquent charge) and debits the parcel's `remaining_principal_cents` by the installment's `principal_cents`. When a delinquent installment is paid, the `DELINQUENCY` `Lien` tied to that installment is released. When the debit drives the parcel's `remaining_principal_cents` to 0, the parcel's payoff cascade fires (below).

Reaching a `remaining_principal_cents` of 0 transitions the parcel from `ACTIVE` to `PAID_OFF`. That cascade releases every unreleased `Lien` on the parcel (moving each `RECORDED` lien to `RELEASED`) and cancels any remaining `SCHEDULED` or `DUE` installment of the parcel (moving each to `CANCELLED`). `PAID_OFF` is reached only from `ACTIVE`.

A `CountyTreasurer` may reverse a prior payment as a compensating action. Reversal marks the payment's `reversed` flag true and stamps its `reversed_at`, returns the installment from `PAID` to `DUE` (or to `DELINQUENT` if the logical clock is already past the grace window described in §3.6), and credits the parcel's `remaining_principal_cents` back by the installment's `principal_cents`. If the reversal restores principal to a parcel that had been `PAID_OFF`, the parcel reverts from `PAID_OFF` to `ACTIVE` and its `ASSESSMENT` lien is re-recorded. Payments on an installment can be listed via the reverse lookup on `installment_id`.

### 3.6. Delinquency and Redemption Interest

When a due installment goes unpaid long enough, a `CountyTreasurer` marks it delinquent, advancing it from `DUE` to `DELINQUENT`. Two conditions gate this: the installment must currently be `DUE`, or `ERR_INSTALLMENT_NOT_PAYABLE` (HTTP 409) is returned; and a grace period of 30 days must have elapsed, meaning the logical clock must be at or past the installment's `due_date` plus 30 days, or the request is rejected with `ERR_GRACE_NOT_ELAPSED` (HTTP 409).

Marking delinquent applies the delinquency charges. The base for these charges is the installment's pre-delinquency amount — its `principal_cents` plus `interest_cents` plus `admin_fee_cents`. The one-time `penalty_cents` is that base multiplied by ten percent (0.10), rounded half up. The `redemption_interest_cents` accrues by whole months: the number of whole months late is the floor of the 30/360 day count from the installment's `due_date` to the current logical clock divided by 30, and the redemption interest is the base multiplied by one and one-half percent (0.015) per whole month late — that is, base multiplied by 0.015 multiplied by the whole-months-late count — rounded half up. The installment's `amount_due_cents` is then recomputed as the base plus `penalty_cents` plus `redemption_interest_cents`. A `DELINQUENCY` `Lien` is recorded on the parcel with its `amount_cents` equal to this new `amount_due_cents`. An installment that is not delinquent carries a `penalty_cents` and `redemption_interest_cents` of 0.

A delinquent installment is redeemed by paying it in full, as covered in §3.5: the `amount_cents` tendered must equal the delinquent `amount_due_cents` — principal, interest, administrative fee, penalty, and redemption interest together — and on payment the installment moves from `DELINQUENT` to `PAID` and its `DELINQUENCY` lien is released. A delinquent installment can otherwise reach the terminal `DEFAULTED` state only through a foreclosure sale (see §3.8).

### 3.7. Prepayment and Payoff Quotes

A parcel owner or the treasurer can request a **payoff quote** to prepay the parcel in full. The request supplies the `quote_mode`, either `IMMEDIATE` or `NEXT_CALL_DATE`; the `quote_date`, the as-of date for the computation; and `expected_parcel_version` for the concurrency guard of §2.8. A quote may be produced only against a parcel that is `ACTIVE` — otherwise `ERR_INVALID_PARCEL_STATE` (HTTP 409) — whose parent district is `FORMED` — otherwise `ERR_DISTRICT_NOT_FORMED` (HTTP 409) — and only when the `quote_date` is at or after the bond's `issuance_date`, since a payoff cannot be dated before the bond exists; an earlier `quote_date` is rejected with `ERR_QUOTE_DATE_INVALID` (HTTP 422). A newly created `PayoffQuote` starts `QUOTED`; it snapshots `remaining_principal_cents` from the parcel and voids any prior `QUOTED` quote on the same parcel (moving each to `VOIDED`), and it increments the parcel's `version` by 1.

The quote's figures are computed as follows. The snapshotted `remaining_principal_cents` is the outstanding principal. The `prepayment_premium_cents` is that remaining principal multiplied by the bond's `prepayment_premium_pct` (three percent by default), rounded half up. The `reserve_credit_cents` — the parcel's pro-rata refund of the reserve fund — is the remaining principal divided by the district's `total_apportioned_principal_cents`, multiplied by the bond's `reserve_fund_cents`, rounded half up. The `accrued_interest_cents` depends on the `quote_mode`, and the two modes deliberately differ. Under `IMMEDIATE`, interest is prorated to the quote date: it is the remaining principal multiplied by the annual rate (`coupon_rate_bps` divided by 10000), multiplied by the 30/360 day count from the bond's `issuance_date` to the `quote_date`, divided by the 360-day basis, rounded half up. Under `NEXT_CALL_DATE`, interest is a full year to the next annual call date: it is simply the remaining principal multiplied by the annual rate, rounded half up — which for a same-year quote is strictly larger than the immediate proration, so the two modes yield different totals. The `total_payoff_cents` is then the remaining principal plus `accrued_interest_cents` plus `prepayment_premium_cents` minus `reserve_credit_cents`. The quote's `valid_until` is its `quote_date` advanced by 30 days.

A quote does not last forever. As covered in §2.7, once the logical clock passes a quote's `valid_until` the quote is lazily promoted from `QUOTED` to `EXPIRED`. Creating a newer quote on the same parcel voids any earlier `QUOTED` quote. `HONORED`, `EXPIRED`, and `VOIDED` are all terminal for a quote.

The treasurer settles a quote by honoring it, moving it from `QUOTED` to `HONORED`. Honor requires the quote to currently be `QUOTED` — a quote past its `valid_until` has already lazily become `EXPIRED` and is therefore no longer honorable, yielding `ERR_INVALID_QUOTE_STATE` (HTTP 409) — and it requires the parcel to be `ACTIVE`. Honoring sets the parcel's `remaining_principal_cents` to 0 and fires the parcel's payoff cascade, transitioning the parcel from `ACTIVE` to `PAID_OFF`, which releases the parcel's liens and cancels its remaining `SCHEDULED` or `DUE` installments. If this was the last parcel of the district with any remaining principal, the parent bond bubbles up from `ISSUED` to `CALLED`. Quotes on a parcel can be listed and filtered by `status`.

### 3.8. Foreclosure and Redemption

When a parcel accumulates enough delinquent installments, the administrator initiates foreclosure. Initiation requires the parcel to currently be `ACTIVE`, or `ERR_INVALID_PARCEL_STATE` (HTTP 409) is returned, and it requires the count of `DELINQUENT` installments on the parcel to be at least 3; a parcel with fewer than three delinquent installments cannot be foreclosed and yields `ERR_FORECLOSURE_THRESHOLD_NOT_MET` (HTTP 409). On success, a `ForeclosureAction` is created in `INITIATED` status: its `delinquent_installment_count` is the number of `DELINQUENT` installments on the parcel at initiation, and its `delinquent_amount_cents` is the sum of `amount_due_cents` over those delinquent installments, while its `redemption_amount_cents` starts null. The parcel cascades from `ACTIVE` to `IN_FORECLOSURE`. Foreclosure actions on a parcel can be listed and filtered by `status`.

The foreclosure is then advanced through its stages by supplying a target `to_status`. The advance capability is available to both the administrator and the treasurer, but the stages divide between them: noticing, entering judgment, and cancellation are administrator actions, while ordering a sale or accepting a redemption are treasurer actions. Any advance whose requested `to_status` is not a legal transition from the foreclosure's current status is rejected with `ERR_INVALID_FORECLOSURE_STATE` (HTTP 409).

- From `INITIATED` to `NOTICED`: permitted only when the foreclosure is `INITIATED`; no side effects.
- From `NOTICED` to `JUDGMENT`: permitted only when the foreclosure is `NOTICED`; the foreclosure's `redemption_amount_cents` is set equal to its `delinquent_amount_cents`.
- From `JUDGMENT` to `SALE`: permitted only when the foreclosure is `JUDGMENT`. This is the divergent enforcement branch. The parcel remains `IN_FORECLOSURE`; every `DELINQUENT` installment of the parcel transitions to the terminal `DEFAULTED`; every `RECORDED` `Lien` of the parcel transitions to `FORECLOSED`; and the parent `ImprovementBond` transitions from `ISSUED` to `DEFAULTED`.
- From `JUDGMENT` to `REDEEMED`: permitted only when the foreclosure is `JUDGMENT`. This is the divergent recovery branch by which the owner redeems. Every `DELINQUENT` installment of the parcel transitions to `PAID` — redemption settles them — and the parcel's `remaining_principal_cents` is debited by each such installment's `principal_cents`; every `DELINQUENCY` `Lien` of the parcel transitions to `RELEASED`; and the parcel cascades from `IN_FORECLOSURE` back to `ACTIVE`.
- From `INITIATED` to `CANCELLED`: permitted only when the foreclosure is `INITIATED`. If the parcel is `IN_FORECLOSURE` and no other active foreclosure exists on it, the parcel reverts from `IN_FORECLOSURE` to `ACTIVE`.

`SALE`, `REDEEMED`, and `CANCELLED` are terminal for a foreclosure action. The parcel's `IN_FORECLOSURE` to `ACTIVE` recovery reaches back through either a redemption or a cancellation, restoring the parcel to its ordinary money lifecycle.

### 3.9. Liens and the Disclosure Report

Liens secure the assessment against the parcel and are entirely system-managed. There are two `lien_type` values. An `ASSESSMENT` lien is recorded, one per `ACTIVE` parcel, when a roll is confirmed, with its `amount_cents` equal to the parcel's `remaining_principal_cents` at that time (skipping a parcel that already has an unreleased assessment lien). A `DELINQUENCY` lien is recorded when an installment is marked delinquent, with its `amount_cents` equal to that installment's newly computed `amount_due_cents`. Each lien's `recorded_date` is the logical-clock date at recording, and a new lien starts `RECORDED`. A lien is released — moving from `RECORDED` to `RELEASED` — when the parcel is paid off or when the delinquent installment securing it is paid; a lien is foreclosed — moving from `RECORDED` to `FORECLOSED` — when a foreclosure on the parcel reaches sale. Both `RELEASED` and `FORECLOSED` are terminal. Liens on a parcel can be listed and filtered by `status` and by `lien_type`.

Any of the four roles may pull a computed **disclosure report** for a parcel — the summary a prospective buyer or lender relies on. The report is computed on demand and returns the parcel's current `remaining_principal_cents`; the `annual_installment_cents`, the amount due on the parcel's current annual installment; the `next_due_date`, the due date of the parcel's earliest not-yet-paid installment; the `delinquent_installment_count`, how many of the parcel's installments are currently `DELINQUENT`; the `lien_status`, reflecting the state of the parcel's liens; and the `foreclosure_status`, reflecting the state of any foreclosure action on the parcel. The disclosure report is read-only and never mutates the parcel.

## 4. Endpoint Definitions

Endpoints that create a brand-new resource respond with HTTP 201; endpoints that modify, transition, or read an existing resource respond with HTTP 200. Request and response bodies are not tabulated here — the fields each operation accepts and the effects it produces are specified in the §3 workflow narratives and the §2 global rules. In the Authorized Role(s) column, "All roles" means `DistrictAdministrator`, `CountyTreasurer`, `ParcelOwner`, and `Auditor`.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/districts` | Create a proposed assessment district | `DistrictAdministrator` |
| GET | `/districts/{id}` | Fetch a district | All roles |
| POST | `/districts/{id}/open-protest` | Open the majority-protest period | `DistrictAdministrator` |
| POST | `/districts/{id}/close-hearing` | Close the protest hearing; form or abandon by protest ratio | `DistrictAdministrator` |
| POST | `/districts/{id}/parcels` | Add a parcel to a district | `DistrictAdministrator` |
| GET | `/districts/{id}/parcels` | List parcels of a district | All roles |
| GET | `/parcels/{id}` | Fetch a parcel | All roles |
| GET | `/parcels` | List and filter parcels | All roles |
| POST | `/parcels/{id}/subdivide` | Split a parcel into child parcels | `DistrictAdministrator` |
| POST | `/parcels/{id}/consolidate` | Reverse a subdivision, restoring the parent parcel | `DistrictAdministrator` |
| POST | `/parcels/{id}/protests` | File a protest against the assessment | `ParcelOwner` |
| GET | `/parcels/{id}/protests` | List protests on a parcel | All roles |
| POST | `/districts/{id}/rolls` | Create a DRAFT assessment roll for a formed district | `DistrictAdministrator` |
| GET | `/districts/{id}/rolls` | List rolls of a district | All roles |
| POST | `/rolls/{id}/confirm` | Confirm a roll, apportioning principal to parcels | `DistrictAdministrator` |
| POST | `/districts/{id}/bonds` | Authorize an improvement bond for a district | `DistrictAdministrator` |
| GET | `/districts/{id}/bonds` | List bonds of a district | All roles |
| POST | `/bonds/{id}/issue` | Issue the bond and generate the per-parcel installment schedule | `DistrictAdministrator` |
| POST | `/parcels/{id}/installments` | Add a supplemental installment for a specific year | `DistrictAdministrator` |
| GET | `/installments/{id}` | Fetch an installment | All roles |
| GET | `/installments` | List and filter installments | All roles |
| POST | `/installments/{id}/payments` | Record a payment against an installment | `CountyTreasurer`, `ParcelOwner` |
| GET | `/installments/{id}/payments` | List payments on an installment | All roles |
| POST | `/payments/{id}/reverse` | Reverse a prior payment | `CountyTreasurer` |
| POST | `/installments/{id}/mark-delinquent` | Mark a past-grace due installment delinquent | `CountyTreasurer` |
| POST | `/parcels/{id}/payoff-quotes` | Compute a prepayment/payoff quote | `ParcelOwner`, `CountyTreasurer` |
| GET | `/parcels/{id}/payoff-quotes` | List payoff quotes on a parcel | All roles |
| POST | `/payoff-quotes/{id}/honor` | Settle a payoff quote, paying the parcel in full | `CountyTreasurer` |
| POST | `/parcels/{id}/foreclosures` | Initiate foreclosure on a delinquent parcel | `DistrictAdministrator` |
| GET | `/parcels/{id}/foreclosures` | List foreclosure actions on a parcel | All roles |
| POST | `/foreclosures/{id}/advance` | Advance a foreclosure to its next stage | `DistrictAdministrator`, `CountyTreasurer` |
| GET | `/parcels/{id}/liens` | List liens on a parcel | All roles |
| GET | `/parcels/{id}/disclosure` | Computed disclosure report for a parcel | All roles |
| POST | `/_clock/set_current_utc` | Set the server logical clock | `DistrictAdministrator`, `CountyTreasurer` |

## 5. Error Code Catalogue

The trigger conditions for each error are described in the §2 and §3 narratives; this catalogue lists only each error's identifier and HTTP status.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 422 |
| `ERR_DISTRICT_NOT_FOUND` | 404 |
| `ERR_PARCEL_NOT_FOUND` | 404 |
| `ERR_ROLL_NOT_FOUND` | 404 |
| `ERR_BOND_NOT_FOUND` | 404 |
| `ERR_INSTALLMENT_NOT_FOUND` | 404 |
| `ERR_PAYMENT_NOT_FOUND` | 404 |
| `ERR_QUOTE_NOT_FOUND` | 404 |
| `ERR_FORECLOSURE_NOT_FOUND` | 404 |
| `ERR_STALE_PARCEL_VERSION` | 412 |
| `ERR_INVALID_DISTRICT_STATE` | 409 |
| `ERR_INVALID_PARCEL_STATE` | 409 |
| `ERR_INVALID_ROLL_STATE` | 409 |
| `ERR_INVALID_BOND_STATE` | 409 |
| `ERR_INSTALLMENT_NOT_PAYABLE` | 409 |
| `ERR_INVALID_QUOTE_STATE` | 409 |
| `ERR_INVALID_FORECLOSURE_STATE` | 409 |
| `ERR_DISTRICT_NOT_FORMED` | 409 |
| `ERR_NO_CONFIRMED_ROLL` | 409 |
| `ERR_APN_DUPLICATE` | 409 |
| `ERR_BENEFIT_UNITS_MISMATCH` | 422 |
| `ERR_INSTALLMENT_YEAR_CONFLICT` | 409 |
| `ERR_BOND_TERM_OVERLAP` | 409 |
| `ERR_FORECLOSURE_THRESHOLD_NOT_MET` | 409 |
| `ERR_QUOTE_DATE_INVALID` | 422 |
| `ERR_GRACE_NOT_ELAPSED` | 409 |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 422 |
