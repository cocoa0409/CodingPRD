# Grain Receipt Collateral API — Product Requirements Document

## 1. Introduction

Licensed grain warehousing is one of the few businesses where a piece of paper is legally interchangeable with a commodity sitting in a steel bin two hundred miles away. A warehouse receipt is all at once a title document, a delivery obligation, a bank's collateral, and — when the warehouseman fails — the only evidence a farmer has that the crop was ever delivered. The Grain Receipt Collateral API is the system of record for that whole chain of custody: it licenses the facility, prices and books the grain in, prints and tracks the receipt, records the lender's security interest, reconciles stored obligations against physical inventory for the regulator, settles the grain back out with a quality adjustment, and — in the worst case — allocates a failed warehouse's bond and the state indemnity fund across competing depositor claims.

The system exists because three parties with genuinely conflicting interests need one shared ledger. The **warehouse operator** wants to take grain in, keep bins full, and bill storage. The **secured lender** wants to know that the bushels behind its advance are still there, still of the certified grade, and still legally under its control. The **state or federal regulator** wants to know, at any instant, whether the facility's receipted and unreceipted obligations are covered by sound physical grain within an examination tolerance — and to be able to shut the facility's intake off the moment they are not. Every rule in this document exists to keep those three views of the same bushel from drifting apart.

Two design commitments run through the specification and should be read as global. First, **money is always integer cents and quantity is always whole bushels**; there are no floating-point balances anywhere in the persisted model, and every rounding step is specified individually rather than deferred to a final pass. Second, the facility's ability to operate is **derived, never asserted**: an operator never sets a status meaning "I am open for business". Licensing state, insolvency state, bin condition, and position variance all feed a single computed posture, and that posture is what gates intake, issuance, and encumbrance.

## 2. Global Specifications & System-Wide Principles

Every resource in this system is a root collection: warehouses, parties, storage agreements, bins, deposit tickets, receipts, collateral liens, position reports, delivery orders, and indemnity claims all sit at the top of the URL space with no parent nesting in their paths. Relationships are carried in request bodies and query filters rather than in path hierarchy. The subsections below define the contract that holds across all of them.

### 2.1. User and Role-Based Access Control

Every request other than the logical-clock control endpoint must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which it is acting. Exactly five roles exist, spelled as follows: `StateRegulator`, `WarehouseOperator`, `Depositor`, `Lender`, and `RegistryAdministrator`. A request that omits either header, or that supplies an `X-User-Role` value outside that set of five, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A well-authenticated request whose role is not listed as authorized for the endpoint it addresses is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

Authorization does not stop at the role. Three of the five roles are **entity-backed**, meaning the caller's `X-User-ID` is itself a primary key in the system and constrains which rows the caller may touch.

- When `X-User-Role` is `WarehouseOperator`, `X-User-ID` is the `id` of the acting `Warehouse`. Ownership checks on any resource that references a `Warehouse` compare the resource's warehouse reference to `X-User-ID` — directly for bins, storage agreements and position reports, and transitively for deposit tickets, receipts and delivery orders reached through their bin, agreement or receipt.
- When `X-User-Role` is `Depositor`, `X-User-ID` is the `id` of the acting `Party`. Ownership checks compare it either to the addressed `StorageAgreement`'s depositor reference or to the addressed receipt's current holder reference. On a delivery order it is compared to the order's `requester_party_id`, to the underlying receipt's `holder_party_id` and to that receipt's `registry_control_party_id`, and matching any one of the three suffices — although cancelling an order is reserved to its requester alone. Bins, deposit tickets and position reports carry no depositor ownership test at all, so a depositor may read any of them.
- When `X-User-Role` is `Lender`, `X-User-ID` is the `id` of the acting `Party`. Every lien write, and every single-lien read, requires the lien's lender reference to equal `X-User-ID`; on a delivery order a lender is tested exactly as a depositor is, and on bins, tickets, agreements and reports it is not tested at all.

The remaining two roles are opaque.

- When `X-User-Role` is `StateRegulator`, `X-User-ID` is an opaque regulator identifier not tied to any persisted entity. The server records it — as `licensed_by_user_id` on a `Warehouse` when a licensing decision is made, as `examined_by_user_id` on a `PositionReport` when an examination result is recorded, and as `adjudicated_by_user_id` on an `IndemnityClaim` when a claim is decided — but it is never compared to any entity's `id`. The one place two such recorded identifiers are compared to each other is the examination-independence rule of §3.7.
- When `X-User-Role` is `RegistryAdministrator`, `X-User-ID` is an opaque registry-operator identifier not tied to any persisted entity. The server neither records nor compares it.

A caller whose role is authorized for the endpoint but whose entity-backed identity does not match the addressed row is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). This ownership rule guards every write and every single-resource read across warehouses, bins, storage agreements, deposit tickets, receipts, collateral liens, position reports and delivery orders.

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

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`, that literal prefix being followed by twenty characters drawn from the uppercase letters and the digits.
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

List endpoints are paginated through two query parameters. `limit` caps the number of items returned; when omitted it defaults to 10, and a supplied value must be at least 1 and at most 100. `offset` is the number of items to skip and defaults to 0. A `limit` or `offset` that is not a base-ten integer, a `limit` below 1 or above 100, or a negative `offset` is rejected with `ERR_VALIDATION`.

Unless a specific endpoint states otherwise, list results are ordered by `created_at` ascending, rows sharing a `created_at` instant keeping the order in which they were created. Ordering and the optional filters of §4 are both applied before `offset` and `limit` are taken, and no list endpoint is narrowed by caller identity — the ownership rule of §2.1 guards single-resource reads only, so a list read returns rows the caller could not have fetched individually.

Every list response carries `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope described in §2.2.

### 2.4. Common Resource Properties and Left-to-Right Resolution

All ten resource types — `Warehouse`, `Party`, `StorageAgreement`, `Bin`, `DepositTicket`, `WarehouseReceipt`, `CollateralLien`, `PositionReport`, `DeliveryOrder` and `IndemnityClaim` — carry the same four system-managed properties:

- `id` (string): a server-minted UUID. It carries no type prefix and no embedded meaning.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, recording when the row was first written.
- `updated_at` (string): an ISO 8601 UTC timestamp in the same format, refreshed on every mutation of the row, including mutations caused by cascade rather than by a direct request against that row.
- `version` (integer): a counter that increments by one on every mutation of the row, starting at 1 on the row as first written. Recomputation of a derived figure that is materialised onto the row counts as a mutation; figures instead recomputed at read time do not, so they move without touching `version` or `updated_at` on the row that reports them. The read-time figures are the warehouse's obligation, physical, variance, tolerance, posture and claim roll-ups, a party's `committed_advance_cents`, `available_credit_cents` and `settlement_balance_cents`, a bin's `held_bushels`, `available_bushels`, `scheduled_inbound_bushels` and `blended_grade`, and a receipt's `quality_flag` and `provisional_storage_charge_cents`. A write that only moves such a figure — accepting a ticket, voiding a receipt, settling a delivery, submitting a report — therefore leaves the warehouse row's own `version` exactly where it was.

No resource type in this system omits `updated_at` or `version`.

Identifier resolution is strictly ordered. When a request carries several identifiers — some in the path, some in the body — the server resolves them left to right in a fixed precedence: the warehouse first, then the bin or storage agreement, then the deposit ticket, receipt, position report, delivery order, collateral lien or indemnity claim, and finally the party. The first identifier that fails to resolve determines the response, so a lien request naming a non-existent receipt and a non-existent lender party reports `ERR_RECEIPT_NOT_FOUND` rather than `ERR_PARTY_NOT_FOUND`. The full set of resolution failures is `ERR_WAREHOUSE_NOT_FOUND`, `ERR_BIN_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`, `ERR_RECEIPT_NOT_FOUND`, `ERR_LIEN_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_DELIVERY_ORDER_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND` and `ERR_PARTY_NOT_FOUND`, each HTTP 404. In a path such as `/warehouses/{warehouse_id}/position-summary` or `/bins/{bin_id}/condition-assessment` the path identifier is resolved before any body field is examined.

Request-shape failures — a missing required field, an enum value outside its declared set, an integer outside its declared bounds, a malformed ISO date or datetime, or an interval whose end instant is not strictly after its start instant — are all reported as `ERR_VALIDATION` (HTTP 422).

### 2.5. The Logical Clock

The server does not read wall-clock time. Every server-assigned instant — `created_at`, `updated_at`, `accepted_at`, `issued_at`, `perfected_at`, `released_at`, `loaded_at`, `settled_at`, `cancelled_at`, `submitted_at`, `last_assessed_at` and `insolvency_declared_at` — and every window, buffer or expiry comparison in this document reads a single logical clock. Before the clock has ever been set it reads exactly `2026-08-01T00:00:00Z`; it must never fall back to real time. An administrative test-driving capability sets the clock to a supplied `current_utc` instant and is open to all five roles; it is the only endpoint exempt from the header-presence requirement of §2.1. `current_utc` is required and must parse as an ISO 8601 datetime, failing which the call is rejected with `ERR_VALIDATION`; the response `data` echoes the accepted instant back as `current_utc`, normalised to UTC with three fractional digits. Because read-time accruals such as a receipt's provisional storage charge are evaluated against this clock, moving the clock forward changes what subsequent reads return without any write having occurred.

### 2.6. Money, Bushels and Rounding Discipline

All monetary amounts are integer counts of cents and all quantities are whole bushels; no field in the persisted model carries a fractional cent or a fractional bushel. Storage rates are the one place a finer unit appears: `storage_rate_millicents_per_bushel_day` is quoted in millicents, that is thousandths of a cent, per bushel per day.

Wherever a computation produces a non-integer intermediate, it is rounded **half up** — to the nearest integer, with ties resolved away from zero — and the specification names each rounding point individually. Two consequences matter enough to state globally. First, when a calculation is defined as a sequence of rounded steps, each step is rounded on its own before feeding the next; collapsing two factors into a single multiplication and rounding once is incorrect and will produce different persisted values. Second, when a total is defined as a sum of separately rounded components, each component is rounded to whole cents before the addition, never after.

Percentage-like rates are expressed in **basis points**, one basis point being one ten-thousandth. A field whose name ends in `_bps` stores the integer basis-point value, so a rate of one and a half percent is persisted as 150, not as 1.5.

### 2.7. Optimistic Concurrency on the Warehouse and the Bin

Two write operations in this system admit a load-bearing amount of grain or obligation on the strength of a figure the client read a moment earlier, and both are therefore protected by an explicit optimistic-concurrency check. In each case the field is a required, non-optional part of the request body.

Issuing a warehouse receipt requires `expected_warehouse_version`, carrying the client's last observed `version` of the target `Warehouse`. If it does not equal the warehouse's current `version`, the issuance is rejected with `ERR_STALE_WAREHOUSE_VERSION` (HTTP 412). Issuance is admitted against `licensed_capacity_bushels` using the warehouse's receipted obligation, so issuing a receipt for a second, different accepted ticket is a perfectly legitimate operation that would otherwise succeed; the stale version is what identifies an operator working from an outdated view of the remaining licensed capacity.

Accepting a weighed deposit ticket into a bin requires `expected_bin_version`, carrying the client's last observed `version` of the target `Bin`. If it does not equal the bin's current `version`, the acceptance is rejected with `ERR_STALE_BIN_VERSION` (HTTP 412). Accepting a second, different weighed ticket into the same bin is likewise a legitimate operation, so the version check is the only deterministic guard against admitting grain on a stale reading of the bin's free space.

No other endpoint in this system accepts a version field, and no other endpoint performs a version check.

### 2.8. The Order in Which a Request Fails

Many operations here are guarded by half a dozen rules at once, and which error a caller sees is part of the contract rather than an implementation detail. Checks are evaluated in the following fixed order, and the **first** rule violated determines the response; later rules are not evaluated and their errors are not reported.

1. Header presence and role validity — `ERR_UNAUTHENTICATED`.
2. Role authorization for the endpoint — `ERR_UNAUTHORIZED`.
3. Entity-backed ownership of the addressed row — `ERR_NOT_RESOURCE_OWNER`.
4. Examination independence — `ERR_SEGREGATION_OF_DUTIES`.
5. Transfer-channel eligibility — `ERR_TRANSFER_CHANNEL_INVALID`.
6. Request shape, enum membership, integer bounds, date and interval well-formedness — `ERR_VALIDATION`.
7. Existence of every identifier, resolved left to right per §2.4 — the 404 family.
8. Referential consistency of the resolved rows, including party-kind fitness and bin/agreement commodity agreement — `ERR_PARTY_KIND_INVALID` and `ERR_COMMODITY_MISMATCH`.
9. Optimistic-concurrency version match per §2.7 — `ERR_STALE_WAREHOUSE_VERSION` and `ERR_STALE_BIN_VERSION`.
10. State admissibility of the requested transition — `ERR_INVALID_STATE`.
11. Licensing gate — `ERR_WAREHOUSE_NOT_LICENSED`.
12. Insolvency gate — `ERR_WAREHOUSE_INSOLVENT`.
13. Operational-posture gate — `ERR_POSTURE_RESTRICTED`.
14. Bin condition gate — `ERR_BIN_OUT_OF_CONDITION`.
15. Minimum grade — `ERR_GRADE_BELOW_MINIMUM`.
16. Commingling eligibility — `ERR_COMMINGLING_NOT_PERMITTED`.
17. Receipt form, medium and perfection-method compatibility — `ERR_RECEIPT_NOT_NEGOTIABLE`, `ERR_REGISTRY_NOT_PARTICIPANT` and `ERR_PERFECTION_METHOD_MISMATCH`.
18. Outstanding encumbrance — `ERR_RECEIPT_ENCUMBERED`.
19. The receipt void window — `ERR_VOID_WINDOW_EXPIRED`.
20. Bin fill-window conflict — `ERR_BIN_WINDOW_CONFLICT`.
21. Loadout lane availability — `ERR_LOADOUT_CAPACITY_EXCEEDED`.
22. Reporting-period overlap — `ERR_REPORT_PERIOD_OVERLAP`.
23. Receipt-number uniqueness — `ERR_RECEIPT_NUMBER_DUPLICATE`.
24. Duplicate claim on a receipt — `ERR_CLAIM_DUPLICATE`.
25. Net-worth adequacy — `ERR_NET_WORTH_INSUFFICIENT`.
26. Bond adequacy — `ERR_BOND_INSUFFICIENT`.
27. Licensed capacity — `ERR_LICENSED_CAPACITY_EXCEEDED`.
28. Bin capacity — `ERR_BIN_CAPACITY_EXCEEDED`.
29. Lender credit line — `ERR_CREDIT_LINE_EXCEEDED`.
30. Delivery quantity against the receipt — `ERR_DELIVERY_EXCEEDS_RECEIPT`.
31. Claim eligibility — `ERR_CLAIM_NOT_ELIGIBLE`.

The placement of the three regulatory gates (ranks 11 through 13) **above** the safety, constraint and fiscal checks is deliberate policy, not an accident of ordering: an unlicensed, insolvent or position-restricted facility is not permitted to explain itself with a capacity or bond error. Where a rule's trigger condition is described in §3, that description is complete; this ladder fixes only precedence. One qualification: rank 3 can only be reached once the row it guards is in hand. Where an entity-backed caller's own identity is carried as a plain body field — a `warehouse_id` on a storage agreement, a bin or a position report, or a `claimant_party_id` on an indemnity claim — a string value differing from `X-User-ID` is rejected with `ERR_NOT_RESOURCE_OWNER` ahead of rank 6, so a malformed body from the wrong operator still reports the ownership failure. Where ownership must instead be read off a resolved row — a ticket's, receipt's or lien's warehouse, holder or lender reference — the check necessarily follows that row's rank-7 lookup and therefore also follows rank 6.

### 2.9. The Federal Grade Standard

Grain is graded from three measured factors, and the same standard is applied twice in a load's life: once at weigh-in, and once again when grain is loaded out for delivery. The grade assigned is the **best** grade whose three thresholds are all satisfied at once — equivalently, the worst factor governs.

- `US_NO_1` requires a test weight of at least 56.0 pounds per bushel, damage of at most 3.0 percent, and foreign material of at most 2.0 percent.
- `US_NO_2` requires a test weight of at least 54.0 pounds per bushel, damage of at most 5.0 percent, and foreign material of at most 3.0 percent.
- `US_NO_3` requires a test weight of at least 52.0 pounds per bushel, damage of at most 7.0 percent, and foreign material of at most 4.0 percent.
- Anything that fails all three tiers is `SAMPLE_GRADE`.

Grades also carry a rank used whenever two grades are compared: `US_NO_1` ranks 1, `US_NO_2` ranks 2, `US_NO_3` ranks 3 and `SAMPLE_GRADE` ranks 4. A lower rank is a better grade, so "at or above a minimum grade" means a rank numerically less than or equal to that minimum's rank.

Grade drives money through a discount schedule quoted in basis points: `US_NO_1` attracts a discount of 0 basis points, `US_NO_2` 150 basis points (one and a half percent), `US_NO_3` 400 basis points (four percent) and `SAMPLE_GRADE` 1200 basis points (twelve percent). This one schedule serves both collateral valuation (§3.6) and delivery settlement (§3.8).

### 2.10. Storage Accrual: Provisional and Final

Storage charges accrue against a receipt's outstanding quantity from the day it was issued, and the accrual is computed in two variants that differ in exactly one respect. Both share the following construction.

The day count is the number of calendar days from the date part of the receipt's `issued_at` to the evaluation date, counting **both** endpoints — a receipt evaluated on the day it was issued has a day count of one. The chargeable days are then split at a base tier of 90 days: the base days are the lesser of the chargeable days and 90, and the surcharge days are the chargeable days in excess of 90, or zero if there is no excess. Base days are billed at the agreement's `storage_rate_millicents_per_bushel_day`; the base component in cents is the product of the outstanding bushels, that millicent rate and the base days, divided by one thousand to convert millicents to cents, then rounded half up to whole cents. Surcharge days are billed at 12500 basis points of the same rate — one and a quarter times the base rate — so the surcharge component in cents is the product of the outstanding bushels, the millicent rate, the surcharge days and 12500, divided by ten million, again rounded half up to whole cents. The two components are rounded separately and only then added; never round once on a combined day count.

The sum of the two components is the raw charge. If the raw charge is exactly zero the storage charge is zero; otherwise the storage charge is the greater of the raw charge and a 500-cent (five dollar) minimum. A facility never bills a nominal amount for storage: either it bills nothing at all, or it bills at least five dollars.

The two variants differ only in how the chargeable days are derived from the day count:

- The **PROVISIONAL** variant sets the chargeable days equal to the day count and **ignores** the agreement's `free_storage_days` allowance entirely. It is used for every read-time accrual: the `provisional_storage_charge_cents` reported on a receipt, the warehouseman's lien inside collateral valuation, and the warehouseman deduction inside an indemnity entitlement. Ignoring the free days makes this figure the larger of the two, so a lender never over-advances against grain whose free period might still be revoked.
- The **FINAL** variant sets the chargeable days to the day count less the agreement's `free_storage_days`, floored at zero. It is used at settlement time, for a delivery order's `storage_charge_cents`. For the same receipt on the same date, the final figure is therefore never larger than the provisional one, and is strictly smaller whenever the day count is positive and free days were granted.

### 2.11. Operational Posture: One Derived Gate

A warehouse never declares itself open. `operational_posture` is recomputed from scratch on every write that touches `license_state`, `insolvency_state`, a bin's condition, receipt issuance or voiding, deposit acceptance, or a position-report examination, and it is evaluated top-down with the first matching clause winning:

1. If `license_state` is anything other than `LICENSED`, or `insolvency_state` is anything other than `SOLVENT`, the posture is `CLOSED`.
2. Otherwise, if the absolute value of `position_variance_bushels` is strictly greater than `examination_tolerance_bushels`, or the most recently submitted position report of this warehouse is in `report_state` `REJECTED`, the posture is `RESTRICTED`.
3. Otherwise the posture is `OPEN`.

"Most recently submitted" means the report with the latest `submitted_at`, with ties broken by the earlier `created_at`. Reports that have never been submitted do not participate.

Note what this construction excludes: bin condition never sets `RESTRICTED` directly. A bin going out of condition reaches the posture only by removing its bushels from `sound_physical_bushels`, thereby moving `position_variance_bushels`, and only then possibly tripping clause 2.

`CLOSED` and `RESTRICTED` bite in different places. `CLOSED` blocks lien perfection outright, and blocks a delivery order at both ends — booking it and loading it out — because each of those three operations independently demands that the warehouse be `LICENSED` and `SOLVENT`, which is exactly the negation of clause 1. `RESTRICTED` blocks the three operations that would grow or newly encumber the obligation — deposit acceptance, receipt issuance and lien perfection — with `ERR_POSTURE_RESTRICTED`, while leaving delivery out of store available so that depositors can still get their grain.

### 2.12. Cascade Discipline

Several operations in this system mutate rows the caller never named. Three properties hold for all of them. Every cascaded row is a real mutation: its `updated_at` is refreshed and its `version` increments. Every cascade is applied immediately and synchronously within the triggering request, so a read issued straight afterwards observes the fully settled result. And every cascade that has a documented reverse — a lien release against a perfection, a receipt void against an issuance, a bin returning to sound condition after an impairment — must restore the affected ledger figures to their pre-cascade values, so that the conserved quantities named in §3 (a lender's available credit, a warehouse's total stored obligation) genuinely return to where they were.

## 3. Business Logic & Workflows

### 3.1. Licensing a Facility: Capacity, Net Worth and the Bond

The lifecycle starts with the regulator, not the operator. A `StateRegulator` files the licence application, supplying the facility's `name`, the `operator_name` of the legal entity that will run it, the `state_code` of the physical site, the `license_program` under which it is applying — either `STATE` or `FEDERAL` — the `licensed_capacity_bushels` applied for (at least one whole bushel), the `bond_amount_cents` of the surety bond posted (zero or more), the `net_worth_cents` from the audited statement submitted with the application (also zero or more), the `loadout_lane_count` of parallel loadout lanes the facility can run (at least one), and `registry_participant`, a flag declaring whether the facility participates in the electronic warehouse receipt registry. The application is created in `license_state` `APPLIED` and `insolvency_state` `SOLVENT`, and its `operational_posture` is `CLOSED` for as long as the licence is merely applied for. Because the operator's own identity is the warehouse row's `id`, an operator literally does not exist until this call returns.

The financial test is recomputed on every read of the warehouse, and its two verdicts are enforced as a precondition of the issuance and reinstatement decisions only: an application may be filed, and its figures freely restated, with an unforgivable shortfall or a deficient bond, the derived figures simply reporting the fact rather than the call failing. **Required net worth** is the greater of a programme floor and a per-bushel scale: the floor is 5,000,000 cents (fifty thousand dollars) under the `STATE` programme and 10,000,000 cents (one hundred thousand dollars) under `FEDERAL`, and the scale is 4 cents per applied bushel under `STATE` and 8 cents per applied bushel under `FEDERAL`. `required_net_worth_cents` is whichever of those two is larger. `net_worth_shortfall_cents` is the amount by which required net worth exceeds the submitted `net_worth_cents`, floored at zero. `net_worth_tolerance_cents` is 2500 basis points — one quarter — of the required net worth, rounded half up to whole cents.

The bond is where the two tests interact, and the interaction is asymmetric in a way that matters. **Base bond** is again the greater of a programme floor and a per-bushel scale: the floor is 2,500,000 cents (twenty-five thousand dollars) under `STATE` and 6,000,000 cents (sixty thousand dollars) under `FEDERAL`, while the scale runs the other way — 5 cents per applied bushel under `STATE` but only 3 cents per applied bushel under `FEDERAL`. `required_bond_cents` is that base bond **plus** a shortfall surcharge of 15000 basis points, that is one and a half times, the net-worth shortfall, rounded half up to whole cents. The critical subtlety: the surcharge is levied on the *whole* shortfall whenever a shortfall exists, even when that shortfall is small enough to be forgiven by the tolerance. Forgiveness excuses the net-worth failure; it does not excuse the bond top-up. `bond_deficiency_cents` is the amount by which the required bond exceeds the posted `bond_amount_cents`, floored at zero.

A licence may be issued only when the shortfall is **less than or equal to** the tolerance and the bond deficiency is **exactly** zero. A shortfall greater than the tolerance is reported as `ERR_NET_WORTH_INSUFFICIENT`; a bond deficiency greater than zero as `ERR_BOND_INSUFFICIENT`. Both derived figures, along with `required_net_worth_cents`, `net_worth_shortfall_cents`, `net_worth_tolerance_cents`, `required_bond_cents` and `bond_deficiency_cents`, are readable on the warehouse at any time. The applied capacity, the posted bond and the audited net worth may all be restated after filing — a restatement accepts any combination of `licensed_capacity_bushels`, `bond_amount_cents` and `net_worth_cents`, re-runs the whole financial test, and increments the warehouse's `version` by one. Both the regulator and the operator may restate them.

A licensing decision carries a `decision` of `ISSUE`, `DENY`, `SUSPEND`, `REINSTATE` or `REVOKE`, optional `license_effective_date` and `license_expiry_date` ISO dates, and an optional free-text `note` which is accepted for the record but neither persisted nor reported. The licensing dimension is branching, not linear, and its permitted moves are these:

- `APPLIED → LICENSED` on `ISSUE`, permitted only while the licence is `APPLIED` and only when the net-worth and bond tests above both pass. Issuance records the deciding regulator's `X-User-ID` in `licensed_by_user_id`, sets `license_effective_date` and `license_expiry_date` from the request — writing null for either date the request omits — and recomputes `operational_posture` — which reaches `OPEN` when the facility is `SOLVENT` and its position variance is inside tolerance.
- `APPLIED → DENIED` on `DENY`, permitted only while the licence is `APPLIED`. Denial also records the deciding regulator in `licensed_by_user_id`, and leaves `operational_posture` `CLOSED` permanently. `DENIED` is terminal: a denied application cannot be revived, and a fresh warehouse row must be filed instead.
- `LICENSED → SUSPENDED` on `SUSPEND`, permitted only from `LICENSED`. Suspension drives `operational_posture` to `CLOSED` and cascades: every deposit ticket of this warehouse still in `ticket_state` `WEIGHED` moves to `REJECTED` with `rejection_reason` `LICENSE_SUSPENDED`. Tickets already `ACCEPTED` and receipts already `ISSUED` are deliberately left untouched — the stored obligation survives suspension, because the depositors' grain is still in the bins. The same transition can also be reached as a system cascade from a `CRITICAL` examination result (§3.7).
- `SUSPENDED → LICENSED` on `REINSTATE`, the revert edge. It requires that the licence be `SUSPENDED` and that no position report of this warehouse currently sit in `report_state` `UNDER_EXAMINATION` — both of those being `ERR_INVALID_STATE`, and both therefore reported ahead of the financial tests per the ladder of §2.8 — and then that the net-worth shortfall again be within tolerance and the bond deficiency again be exactly zero. Reinstatement recomputes the posture, which returns to `OPEN` only if the position variance is inside tolerance and the most recently submitted report is not `REJECTED`.
- `SUSPENDED → REVOKED` and `LICENSED → REVOKED`, both on `REVOKE`. Revocation may skip suspension entirely. Either way the posture becomes `CLOSED` permanently and every `WEIGHED` deposit ticket moves to `REJECTED` with `rejection_reason` `LICENSE_SUSPENDED`.

`REVOKED` and `DENIED` are the terminal licence states. Any decision issued against a licence not in the required source state is rejected with `ERR_INVALID_STATE` (HTTP 409), and every licensing decision increments the warehouse's `version` by one.

### 3.2. Counterparties, Storage Agreements and Bins

Counterparties are registered as `Party` rows by either a `StateRegulator` or a `RegistryAdministrator`, each with a legal `name`, a `party_kind` of `PRODUCER_DEPOSITOR`, `COMMERCIAL_DEPOSITOR` or `LENDER`, a `state_code` of record, and an optional `credit_line_cents` committed advance capacity that defaults to zero and is meaningful only for lenders. `party_kind` is a hard gate on which slot a party may fill, and a party supplied for a slot its kind does not fit is rejected with `ERR_PARTY_KIND_INVALID`. A newly registered party starts with `committed_advance_cents` at zero and therefore `available_credit_cents` equal to its credit line. A lender's credit line may later be restated by a regulator, which recomputes `available_credit_cents` and increments the party's `version` by one. The restatement requires `credit_line_cents` of zero or more and does not test the addressed party's kind, so it will rewrite the line on a depositor row as readily as on a lender's.

Three derived figures are always readable on a party. `committed_advance_cents` is the sum of `advance_limit_cents` across every lien naming this party as lender whose `lien_state` is `PERFECTED`. `available_credit_cents` is `credit_line_cents` less that committed advance — the conserved quantity of the perfect-and-release pair described in §3.6. `settlement_balance_cents` is the sum of `net_settlement_cents` across every settled delivery order whose requester is this party; a negative balance means the depositor owes the warehouse rather than the other way round.

A `WarehouseOperator` opens a **storage agreement** naming its own `warehouse_id` and a `depositor_party_id` whose kind must be `PRODUCER_DEPOSITOR` or `COMMERCIAL_DEPOSITOR`. The agreement fixes the `commodity` — `CORN`, `SOYBEANS` or `WHEAT` — and the `storage_kind`, either `COMMINGLED` for grain that joins a fungible common mass or `IDENTITY_PRESERVED` for a lot stored separately and returned in kind. It declares a `min_grade`, the worst grade the warehouse will accept under this agreement, drawn from the four grades of §2.9; a `max_moisture_pct` contract moisture ceiling carried to one decimal place; and its commercial terms: `storage_rate_millicents_per_bushel_day`, a one-time `receiving_charge_cents_per_bushel`, a `loadout_charge_cents_per_bushel` applied per delivered bushel at settlement, a count of `free_storage_days`, and a `declared_value_cents_per_bushel` of at least one cent. The three charge rates and the free-day count may each be zero. A new agreement starts in `agreement_state` `ACTIVE`.

An agreement reaches `TERMINATED` only when nothing is outstanding under it: no receipt under the agreement may be in `receipt_state` `ISSUED`, and no deposit ticket under it may be in `ticket_state` `WEIGHED` or `ACCEPTED`. Termination records the supplied `termination_reason`, a required non-empty string — the field is null while the agreement is `ACTIVE` — and releases any bin whose `dedicated_agreement_id` points at this agreement. Attempting to terminate an agreement that is already `TERMINATED`, or one that still has live tickets or receipts, is rejected with `ERR_INVALID_STATE`.

Bins are the physical side of the same picture. An operator adds a bin to its own warehouse with a `bin_code` label unique within that warehouse, a `capacity_bushels` of at least one, the `commodity` the bin holds, a `commingling_allowed` flag marking it as a common-mass bin, and optionally a `dedicated_agreement_id`. A `bin_code` already in use at that warehouse is a request-shape failure reported as `ERR_VALIDATION`, and a supplied `dedicated_agreement_id` is resolved for existence only — an unknown one is `ERR_AGREEMENT_NOT_FOUND`, while an agreement belonging to a different warehouse, or one whose `storage_kind` disagrees with the flag just set, is accepted here and bites only at weigh-in. A new bin starts in `condition_state` `SOUND` with `stored_bushels`, `held_bushels`, `scheduled_inbound_bushels` and `cumulative_shrink_bushels` all at zero, `blended_grade` null, and `last_moisture_pct`, `last_temperature_f` and `last_assessed_at` all null until its first condition assessment. Four derived quantities describe a bin's position at any instant: `stored_bushels` is the physical inventory actually on hand; `held_bushels` is the sum of `requested_bushels` across delivery orders drawn from this bin whose `delivery_state` is `REQUESTED` or `LOADED`; `available_bushels` is stored less held; and `scheduled_inbound_bushels` is the sum of `net_bushels` across tickets destined for this bin that are still merely `WEIGHED`. `blended_grade` is the worst — highest-ranked — `assigned_grade` among the tickets that have been accepted into the bin; because receipting a ticket is paperwork that moves no grain, a ticket counts towards the blend while its `ticket_state` is either `ACCEPTED` or `RECEIPTED`. `blended_grade` is null while the bin is empty — that is, whenever the bin's `stored_bushels` is zero or less, whatever tickets the bin has held — and also null when the bin holds grain but no ticket of its own is in either of those two states.

### 3.3. Taking Grain In: Weigh-In, Fill Windows and Acceptance

Intake is two-phase by design: the scale ticket is written first, and admission into the bin is a separate, concurrency-guarded decision.

At weigh-in the operator records a `storage_agreement_id` whose agreement must be `ACTIVE`, a `bin_id`, the `gross_bushels` off the scale (at least one), the four grade factors `test_weight_lbs`, `moisture_pct`, `damage_pct` and `foreign_material_pct` each to one decimal place, a `dockage_pct` also to one decimal place, and the `fill_start_at` and `fill_end_at` instants of the bin fill window this load will occupy — the end instant must be strictly after the start. Of the two rank-7 lookups the `bin_id` is resolved before the `storage_agreement_id`, so a request naming neither an existing bin nor an existing agreement reports `ERR_BIN_NOT_FOUND`. The bin must belong to the agreement's warehouse, or the request is rejected with `ERR_PARTY_KIND_INVALID`; and the bin's `commodity` must equal the agreement's `commodity`, or the request is rejected with `ERR_COMMODITY_MISMATCH`. An agreement that is not `ACTIVE` is refused with `ERR_INVALID_STATE`, and weigh-in further requires the warehouse to be `LICENSED` and `SOLVENT` — but, unlike acceptance, it is indifferent to a `RESTRICTED` posture and indifferent to the load's grade.

Commingling rules bind at weigh-in. An `IDENTITY_PRESERVED` agreement may only direct grain into a bin whose `commingling_allowed` is false and whose `dedicated_agreement_id` is either null or already equal to this agreement; the first identity-preserved lot accepted into such a bin sets `dedicated_agreement_id` to its agreement. A `COMMINGLED` agreement may only direct grain into a bin whose `commingling_allowed` is true. Any violation — an identity-preserved lot into a commingling bin, a commingled lot into a non-commingling bin, or use of a bin already dedicated to a different agreement — is rejected with `ERR_COMMINGLING_NOT_PERMITTED`.

Fill windows are treated as **closed** intervals inflated by a four-hour settling buffer, because grain needs time to stop moving before the next load goes on top of it. A proposed window conflicts with an existing ticket's window on the same bin, over tickets in `ticket_state` `WEIGHED` or `ACCEPTED`, when the new start is at or before the existing end advanced by 240 minutes **and** the existing start is at or before the new end advanced by 240 minutes. A conflict is rejected with `ERR_BIN_WINDOW_CONFLICT` (HTTP 409). Rejecting a weighed ticket frees its window for other loads.

Weigh-in grades and quantifies the load in one pass. The `assigned_grade` comes from the factor table of §2.9 applied to `test_weight_lbs`, `damage_pct` and `foreign_material_pct`. The quantity is then computed in **two sequential rounded steps**, and the sequence is normative. First, `dockage_bushels` is the `gross_bushels` multiplied by `dockage_pct` and divided by one hundred, rounded half up to a whole bushel; `clean_bushels` is `gross_bushels` less `dockage_bushels`. Second, the excess moisture is the amount by which `moisture_pct` exceeds the agreement's `max_moisture_pct`, floored at zero, and `shrink_bushels` is the product of `clean_bushels`, that excess expressed in percentage points, and one hundred eighteen ten-thousandths, rounded half up to a whole bushel. `net_bushels` is `clean_bushels` less `shrink_bushels`. Applying dockage and shrink as a single combined multiplication rounded once is wrong; the dockage rounding must land before the shrink step reads its base.

Which of two settlement variants applies is fixed at weigh-in and recorded on the ticket as `settlement_variant`, copied from the agreement's `storage_kind`:

- Under `COMMINGLED`, the moisture shrink is assessed exactly as written above. The depositor bears the drying loss, so whenever moisture exceeds the agreement ceiling the net bushels come out below the clean bushels.
- Under `IDENTITY_PRESERVED`, `shrink_bushels` is forced to exactly zero regardless of moisture, so `net_bushels` equals `clean_bushels`. The dockage step is unchanged and still applies in full.

A new ticket lands in `ticket_state` `WEIGHED`, with `accepted_at` null, and raises the bin's `scheduled_inbound_bushels` by its `net_bushels` as a soft reservation.

Acceptance is the moment the grain legally becomes the warehouse's obligation, and it is the most heavily guarded write in the intake path. It carries `expected_bin_version` and nothing else. Beyond the version match of §2.7, the ticket must still be `WEIGHED`; the warehouse's `license_state` must be `LICENSED` and its `insolvency_state` `SOLVENT`; the posture must not be `RESTRICTED`; the bin's `condition_state` must not be `OUT_OF_CONDITION`, or the request is rejected with `ERR_BIN_OUT_OF_CONDITION`; the ticket's `assigned_grade` must rank at or above the agreement's `min_grade`, or the request is rejected with `ERR_GRADE_BELOW_MINIMUM`; and the bin must have room. The room test is the bin's remaining headroom — its `capacity_bushels` less `stored_bushels` less `held_bushels` less `scheduled_inbound_bushels`, with the accepting ticket's own reservation excluded from that last term since it is the very load being admitted — measured against the ticket's `net_bushels`, and a shortfall is rejected with `ERR_BIN_CAPACITY_EXCEEDED`. The same headroom test also runs at weigh-in, where the new ticket has no reservation yet to exclude.

Acceptance then sets `accepted_at` from the logical clock, moves the ticket to `ACCEPTED`, increments the bin's `version` by one, raises the bin's `stored_bushels` by the ticket's `net_bushels`, raises the bin's `cumulative_shrink_bushels` by the ticket's `shrink_bushels`, clears the ticket's scheduled-inbound reservation, recomputes the bin's `blended_grade`, and raises the warehouse's `obligation_bushels` and `system_physical_bushels` before recomputing the posture. `cumulative_shrink_bushels` is the audit accumulator for every bushel that entered the paperwork but never the bin — moisture shrink at acceptance plus blend-out loss during conditioning — and it is the documented drift term in the bushel-conservation invariant.

A weighed load may instead be rejected before it enters the bin, which moves the ticket to `REJECTED`, releases its `scheduled_inbound_bushels` and frees its fill window. An operator-initiated rejection may supply a `rejection_reason`; the reason is one of `OPERATOR_REJECTED` for a manual rejection, `LICENSE_SUSPENDED` when the rejection is a cascade from a suspension, revocation or critical examination finding, or `INSOLVENCY_DECLARED` when it is a cascade from an insolvency declaration, and it is null on any ticket that was never rejected. An operator-initiated rejection that omits the field records `OPERATOR_REJECTED`, and a supplied string is stored as given rather than checked against that set. Only `WEIGHED` tickets are rejectable — an already-accepted ticket has entered the commingled mass and can no longer be turned away — so rejecting an accepted, receipted or already-rejected ticket is refused with `ERR_INVALID_STATE`. `RECEIPTED` and `REJECTED` are the two terminal ticket states.

### 3.4. Issuing, Transferring and Voiding Warehouse Receipts

A receipt is issued against exactly one accepted ticket. The operator supplies the `deposit_ticket_id` of a ticket in `ticket_state` `ACCEPTED`, the `holder_party_id` of the party that will hold the receipt, an operator-assigned `receipt_number`, the `form` — `NEGOTIABLE` or `NON_NEGOTIABLE` — the `medium` — `PAPER` or `ELECTRONIC` — and the `expected_warehouse_version` of §2.7. Only `NEGOTIABLE` receipts may ever be transferred or pledged, and any attempt to transfer or pledge a `NON_NEGOTIABLE` receipt is refused with `ERR_RECEIPT_NOT_NEGOTIABLE`. An `ELECTRONIC` receipt may only be issued at a warehouse whose `registry_participant` is true; otherwise the issuance is refused with `ERR_REGISTRY_NOT_PARTICIPANT`. `receipt_number` must be unique within the warehouse across **every** receipt state, including numbers already used by voided and cancelled receipts, and a collision is refused with `ERR_RECEIPT_NUMBER_DUPLICATE` (HTTP 409). Issuance is also blocked when the ticket's bin is `OUT_OF_CONDITION`, and — like acceptance — when the warehouse is not `LICENSED`, not `SOLVENT` or `RESTRICTED`. The holder party must exist, an unknown one being `ERR_PARTY_NOT_FOUND`, but its `party_kind` is not constrained and need not be the agreement's depositor: a lender, or any registered party, may be named holder at issuance.

The capacity gate at issuance is the reason the warehouse version matters: the sum of the warehouse's `receipted_obligation_bushels` and the ticket's `net_bushels` must not exceed `licensed_capacity_bushels`, and an overrun is refused with `ERR_LICENSED_CAPACITY_EXCEEDED`. Only receipted obligation counts here — accepted but unreceipted grain does not consume licensed capacity.

Issuance copies a great deal onto the receipt and freezes it there. `warehouse_id`, `storage_agreement_id` and `bin_id` are copied from the ticket's agreement and bin. `quantity_bushels` is initialised to the ticket's `net_bushels`. `grade` is copied from the ticket's `assigned_grade` and `moisture_pct` from the ticket's moisture reading. `face_price_cents_per_bushel` is pinned from the agreement's `declared_value_cents_per_bushel` at this instant, and later edits to the agreement do not move it. `receiving_charge_cents` is the quantity at issuance multiplied by the agreement's `receiving_charge_cents_per_bushel`, rounded half up to whole cents, and becomes a fixed component of the warehouseman's lien for the life of the receipt. `issued_at` is taken from the logical clock and is both day zero of storage accrual and the start of the void window. `registry_control_party_id` is null, and `transfer_log` starts as an empty array. The source ticket moves from `ACCEPTED` to `RECEIPTED`, which shifts its bushels from the unreceipted to the receipted side of the warehouse's `obligation_bushels` without changing that total, and the warehouse's `version` increments by one. A ticket already referenced by a receipt cannot be receipted twice.

Each receipt carries two independent state dimensions. The lifecycle dimension, `receipt_state`, starts at `ISSUED` and has two terminal states, `CANCELLED` and `VOIDED`. The collateral dimension, `encumbrance_state`, starts at `UNENCUMBERED`, cycles through `PLEDGED` and `RELEASED`, and has no terminal state at all — a released receipt can be pledged again. The two dimensions move independently, and neither one's value constrains which values the other may take beyond the explicit preconditions stated here and in §3.6.

A third derived flag, `quality_flag`, is `IMPAIRED` whenever the bin named by the receipt's `bin_id` is in `condition_state` `OUT_OF_CONDITION`, and `SOUND` otherwise. It is the channel through which physical grain condition reaches collateral value. Alongside it, every read of a receipt reports `provisional_storage_charge_cents`, the `PROVISIONAL` accrual of §2.10 evaluated at the current logical clock.

**Transfer.** A negotiable receipt changes hands through one of two channels, and the channel, the medium and the caller's role must agree. A `PAPER` receipt is transferred by its current holder — acting as `Depositor` or `Lender` — with `transfer_channel` `ENDORSEMENT`. An `ELECTRONIC` receipt is transferred only by a `RegistryAdministrator` with `transfer_channel` `REGISTRY`, and only at a registry-participating warehouse. Any other combination of channel, medium and role is refused with `ERR_TRANSFER_CHANNEL_INVALID` (HTTP 403); a `REGISTRY` transfer attempted at a warehouse whose `registry_participant` is false is refused with `ERR_REGISTRY_NOT_PARTICIPANT`. The request supplies the `to_party_id` receiving the receipt and the `transfer_channel`. Because that eligibility test sits at rank 5 of §2.8, above request shape, it also swallows a `transfer_channel` outside the two-member set: an unrecognised channel value is reported as `ERR_TRANSFER_CHANNEL_INVALID`, not as `ERR_VALIDATION`, while a `transfer_channel` that is absent, null, non-string or blank remains `ERR_VALIDATION`. A transfer is admissible only while `receipt_state` is `ISSUED`; a cancelled or voided receipt is refused with `ERR_INVALID_STATE`, ahead of the negotiability and encumbrance tests. A successful transfer moves `holder_party_id` to `to_party_id` and appends one record to `transfer_log` — an append-only, chronologically ordered array of objects each carrying `transfer_channel`, `from_party_id`, `to_party_id` and `effective_at`. A receipt whose `encumbrance_state` is `PLEDGED` may not be transferred by its pledgor and is refused with `ERR_RECEIPT_ENCUMBERED` (HTTP 409).

**Void.** Voiding is the compensating move for an issuance made in error, and it exists precisely to conserve the warehouse's total obligation. It may supply an optional `void_reason`, which is accepted but neither persisted nor reported. It requires that the receipt still be `ISSUED` and that no delivery order on the receipt be in `delivery_state` `REQUESTED` or `LOADED` — both `ERR_INVALID_STATE`, and both evaluated before the encumbrance test — that its `encumbrance_state` not be `PLEDGED`, and that the current logical clock be within 72 hours of `issued_at`, the boundary being inclusive so that an attempt at exactly 72 hours still succeeds; a later attempt is refused with `ERR_VOID_WINDOW_EXPIRED`. A void moves `receipt_state` to `VOIDED`, zeroes `quantity_bushels`, and thereby removes the receipt from the warehouse's `receipted_obligation_bushels`; returns the source deposit ticket from `RECEIPTED` back to `ACCEPTED`, so the very same bushels re-enter `obligation_bushels` as unreceipted stock; and leaves the bin's `stored_bushels` completely unchanged, because voiding a receipt does not move grain. The warehouse's total obligation before and after a void is therefore identical, while its receipted obligation falls — that pairing is the whole point of the transition.

### 3.5. Grade Maintenance and Out-of-Condition Grain

Stored grain deteriorates, and the operator is obliged to watch it. A condition assessment records a `moisture_pct` reading of zero or more, a `temperature_f` reading which is unbounded and may be negative, and an optional `treatment_action` drawn from `NONE`, `AERATE`, `TURN` and `BLEND_OUT`, an omitted `treatment_action` being recorded as `NONE`. From the two readings the system re-derives the bin's `condition_state`, evaluated top-down with the first matching clause winning:

1. If `moisture_pct` is at least 15.5, **or** `temperature_f` is strictly above 95, **or** `moisture_pct` is at least 14.0 *and* `temperature_f` is strictly above 85, the target is `OUT_OF_CONDITION`.
2. Otherwise, if `moisture_pct` is at least 14.0 **or** `temperature_f` is strictly above 85, the target is `WATCH`.
3. Otherwise the target is `SOUND`.

Moisture comparisons are inclusive at one decimal place; temperature comparisons are strict. Note that the third clause of the first test makes a bin that is merely damp *and* merely warm out of condition, even though neither reading alone would do more than put it on watch.

Every assessment stores `last_moisture_pct`, `last_temperature_f`, `last_treatment_action` and `last_assessed_at`, and increments the bin's `version` by one. When the recorded `treatment_action` is `BLEND_OUT`, the bin is physically mixed and loses volume: the blend loss is 150 basis points — one and a half percent — of the bin's `stored_bushels`, rounded half up to a whole bushel; `stored_bushels` falls by that amount and `cumulative_shrink_bushels` rises by exactly the same amount. The blend loss lands before the condition state is rewritten and before any cascade fires, so a cascade fired by this same assessment already sees the reduced `stored_bushels`; and it is applied on every `BLEND_OUT` assessment, whether or not the assessment moves the bin across the out-of-condition boundary.

The condition dimension is non-linear and fully reversible: `SOUND → WATCH`, `WATCH → OUT_OF_CONDITION`, `SOUND → OUT_OF_CONDITION` (skipping watch entirely), `OUT_OF_CONDITION → WATCH`, `OUT_OF_CONDITION → SOUND` and `WATCH → SOUND` are all reachable, purely as a function of the derived target. There is no terminal condition state.

**Entering `OUT_OF_CONDITION` fires a three-hop cascade plus a warehouse-level effect, and every hop matters.** Whether the bin arrives from `WATCH` or directly from `SOUND`, the cascade is identical. Every `ISSUED` receipt on that bin recomputes `quality_flag` to `IMPAIRED`. Every `PERFECTED` lien on those receipts is revalued, its `grade_discount_bps` gaining the 2500-basis-point impairment penalty, which lowers `eligible_value_cents`, lowers `advance_limit_cents`, and may flip `margin_status` to `DEFICIENT`. Revaluation here is the whole seven-step sequence of §3.6 re-run at the current logical clock against the lien's stored `mark_price_cents_per_bushel`, so the provisional storage charge inside the warehouseman lien is re-read alongside the discount; on a `FACE_ADVANCE` lien, whose `grade_discount_bps` is pinned at zero, that re-read of the storage charge is the only thing the cascade moves. Each affected lender party then has `committed_advance_cents` and `available_credit_cents` recomputed from the new advance limits. Finally the warehouse's `sound_physical_bushels` drops by this bin's entire `stored_bushels`, which moves `position_variance_bushels` and may push `operational_posture` to `RESTRICTED`.

**Leaving `OUT_OF_CONDITION` reverses that cascade in full**, and again identically whether the bin lands on `WATCH` or straight back on `SOUND`. Every `ISSUED` receipt on the bin recomputes `quality_flag` to `SOUND`, every `PERFECTED` lien on those receipts is revalued upward with the impairment penalty removed, each affected lender's committed advance and available credit are restored accordingly, and the warehouse's `sound_physical_bushels` regains the bin's `stored_bushels`. If the treating assessment carried `BLEND_OUT`, the blend loss described above is applied as well, so the bushels regained are the post-blend figure.

A `WATCH → SOUND` assessment stores its readings and produces no receipt or lien effect at all, because `quality_flag` was already `SOUND` throughout — watch is a warning level, not an impairment.

While a bin is `OUT_OF_CONDITION` it is frozen for grain movement in both directions: grain may not be weighed in against it, accepted into it, receipted out of it, made the subject of a new delivery order, or loaded out of it. All five refusals carry `ERR_BIN_OUT_OF_CONDITION`. The bin must be conditioned back to `WATCH` or `SOUND` first.

### 3.6. Lender Interest: Valuation, Perfection, Revaluation and Release

A `Lender` records an advance against a negotiable receipt by supplying the `receipt_id`, its own `lender_party_id` — which must be a party of kind `LENDER` and must equal the caller's `X-User-ID` — the `principal_cents` it intends to carry (at least one cent), a `valuation_basis` of `MARK_TO_MARKET` or `FACE_ADVANCE`, a `mark_price_cents_per_bushel` of at least one cent, and a `perfection_method` of `POSSESSION` or `ELECTRONIC_CONTROL`. The referenced receipt must be `ISSUED`, `NEGOTIABLE`, and not currently `PLEDGED` — refused in that order with `ERR_INVALID_STATE`, `ERR_RECEIPT_NOT_NEGOTIABLE` and `ERR_RECEIPT_ENCUMBERED` respectively. Recording a request applies no licensing, insolvency or posture gate; those bite only at perfection. Recording the request captures `pledgor_party_id` from the receipt's current `holder_party_id`, so that release can later restore possession to whoever gave it up, and the lien lands in `lien_state` `REQUESTED` with `perfected_at`, `released_at` and `payoff_received_cents` all null. **No credit is committed at this point** — recording a request costs the lender nothing against its line.

The valuation runs immediately and is a **seven-step sequence whose order is normative**.

1. **Gross value.** `gross_value_cents` is the receipt's outstanding `quantity_bushels` multiplied by a price. Under `MARK_TO_MARKET` the price is the lender's `mark_price_cents_per_bushel`; under `FACE_ADVANCE` it is the receipt's pinned `face_price_cents_per_bushel`.
2. **Quality discount.** `grade_discount_bps` is the discount for the receipt's `grade` from the schedule in §2.9, plus 2500 basis points when the receipt's `quality_flag` is `IMPAIRED`.
3. **Eligible value.** `eligible_value_cents` is the gross value reduced by the discount — the gross value multiplied by the complement of `grade_discount_bps` within ten thousand, divided by ten thousand — rounded half up to whole cents.
4. **Administration fee.** `admin_fee_cents` is 25 basis points, one quarter of one percent, of the **eligible** value from step 3, rounded half up to whole cents. It is keyed on the pre-lien eligible value: not on the gross value, and not on the post-lien net value.
5. **The warehouseman's prior lien.** `warehouseman_lien_cents` is the sum of the receipt's `provisional_storage_charge_cents`, its `receiving_charge_cents` and the `admin_fee_cents` from step 4. This is the claim that outranks the lender's interest, and `net_collateral_cents` is the eligible value less that lien, floored at zero.
6. **Advance-rate tier.** `advance_rate_bps` is 8000 basis points (eighty percent) when `net_collateral_cents` is at least 10,000,000 cents — one hundred thousand dollars — and 7000 basis points (seventy percent) otherwise. The tier is keyed on the **post**-lien net collateral value produced by step 5, and the threshold test is inclusive.
7. **Limit and margin.** `advance_limit_cents` is `net_collateral_cents` multiplied by `advance_rate_bps` and divided by ten thousand, rounded half up to whole cents. `margin_deficiency_cents` is the amount by which `principal_cents` exceeds that limit, floored at zero, and `margin_status` is `SUFFICIENT` when the deficiency is exactly zero and `DEFICIENT` otherwise.

Rounding happens at steps 3, 4 and 7 only. The two valuation bases diverge on both the numerator and the deduction, and the difference is worth spelling out because it is easy to under-specify:

- Under `MARK_TO_MARKET`, the price is the lender's own `mark_price_cents_per_bushel`, the grade and impairment discounts of step 2 apply in full, and the step-4 administration fee is charged and therefore enters the warehouseman lien.
- Under `FACE_ADVANCE`, the price is the receipt's `face_price_cents_per_bushel`, `grade_discount_bps` is forced to exactly zero because the declared face value already embeds the grade, and `admin_fee_cents` is exactly zero — which makes the warehouseman lien smaller as well. The supplied `mark_price_cents_per_bushel` is still required by the request but is ignored by the computation.

**Perfection** is where the lender's interest becomes real and where its credit line is actually charged. It may carry an optional `attestation_note`, which is accepted but neither persisted nor reported. It requires the lien to be `REQUESTED`; the lender's `lender_party_id` to equal the caller's `X-User-ID`; the receipt to be `ISSUED`, `NEGOTIABLE` and not currently `PLEDGED`; the warehouse to be `LICENSED`, `SOLVENT` and not `RESTRICTED`, and its `operational_posture` not `CLOSED`; the `perfection_method` to match the receipt's `medium`; and the lender's `available_credit_cents` to be at least the lien's `advance_limit_cents`. A method mismatch — `POSSESSION` against an `ELECTRONIC` receipt, or `ELECTRONIC_CONTROL` against a `PAPER` one — is refused with `ERR_PERFECTION_METHOD_MISMATCH`; `ELECTRONIC_CONTROL` additionally requires the warehouse's `registry_participant` to be true, failing which the refusal is `ERR_REGISTRY_NOT_PARTICIPANT`. That registry test is reached only once the method already agrees with the medium, so `ELECTRONIC_CONTROL` presented against a `PAPER` receipt reports `ERR_PERFECTION_METHOD_MISMATCH` whatever the warehouse's registry standing. An insufficient line is refused with `ERR_CREDIT_LINE_EXCEEDED`, the comparison being against the advance limit produced by the re-run valuation described next.

Perfection re-runs the whole seven-step valuation at the current logical clock — which matters, because the provisional storage charge inside the warehouseman lien has grown since the request was recorded — then sets `perfected_at`, moves `lien_state` to `PERFECTED`, drives the receipt's `encumbrance_state` to `PLEDGED`, and raises the lender's `committed_advance_cents` by `advance_limit_cents`. The two perfection methods differ in exactly which possession field moves: `POSSESSION` moves the receipt's `holder_party_id` to the lender and leaves `registry_control_party_id` null, while `ELECTRONIC_CONTROL` sets `registry_control_party_id` to the lender and leaves `holder_party_id` exactly where it was.

**Revaluation** re-marks a lien at a new `mark_price_cents_per_bushel` — required, and at least one cent — re-runs the seven steps at the current logical clock, and rewrites `advance_limit_cents`, `margin_deficiency_cents` and `margin_status` along with every other valuation field. On a lien that is already `PERFECTED`, it also adjusts the lender's `committed_advance_cents` by the difference between the new and the old advance limit, so the lender's committed exposure tracks the mark. It is admissible only while the lien is `REQUESTED` or `PERFECTED`; a `RELEASED` lien is refused with `ERR_INVALID_STATE`. No credit-line test runs on this path, so an upward re-mark may legitimately carry a lender's committed advance past its line and drive `available_credit_cents` negative.

**Release** carries the `payoff_received_cents` recorded against the lien, a required integer of zero or more on both of the release paths below. From `PERFECTED`, release requires the lien to be `PERFECTED` and the caller to be its lender; it sets `released_at` and `payoff_received_cents`, moves `lien_state` to `RELEASED`, drives the receipt's `encumbrance_state` from `PLEDGED` to `RELEASED`, restores `holder_party_id` to the captured `pledgor_party_id`, clears `registry_control_party_id`, and lowers the lender's `committed_advance_cents` by the amount **currently** committed for this lien — including any revaluation delta applied in the meantime — so that the lender's `available_credit_cents` returns exactly to its pre-perfection value. That exact restoration is the conservation property the release edge exists to guarantee.

A lien may also be released straight from `REQUESTED`, withdrawing an advance request that was never perfected. Perfection may therefore be skipped entirely. That path sets `released_at` with `payoff_received_cents` forced to zero whatever the request supplied, and has **no** credit-line effect and **no** effect on the receipt's encumbrance dimension, `holder_party_id` or `registry_control_party_id`, because nothing was ever committed and no possession was ever taken. `RELEASED` is the lien's only terminal state.

Because the receipt's encumbrance dimension is cyclic, a released receipt can be pledged again by a later lien: `RELEASED → PLEDGED` requires the receipt still to be `ISSUED` and `NEGOTIABLE` and requires that no other lien on that receipt currently be `PERFECTED` — a violation of either the encumbrance state or that no-other-perfected-lien rule being refused with `ERR_RECEIPT_ENCUMBERED` — and its side effects are identical to the first pledge. A receipt whose `encumbrance_state` is `PLEDGED` cannot be voided, cannot be transferred by its pledgor, and cannot be settled out of store; all three are refused with `ERR_RECEIPT_ENCUMBERED`.

### 3.7. Position Reporting, Examination and Segregation of Duties

Reconciliation is the regulator's core instrument, and it compares four numbers that ought to agree. The **obligation** is what the warehouse owes: the sum of `quantity_bushels` across receipts in `receipt_state` `ISSUED`, plus the sum of `net_bushels` across deposit tickets in `ticket_state` `ACCEPTED`. Weighed, receipted and rejected tickets are excluded from that sum, as are cancelled and voided receipts. `receipted_obligation_bushels` is the first of those two sums alone, and it is the figure the licensed-capacity gate of §3.4 tests. The **system physical** figure, `system_physical_bushels`, is the sum of `stored_bushels` across every bin of the warehouse, whatever each bin's condition. The **sound physical** figure, `sound_physical_bushels`, is the same sum restricted to bins whose `condition_state` is `SOUND` or `WATCH`, excluding out-of-condition bins entirely.

From these come three deltas. `position_variance_bushels` is the sound physical figure less the obligation; a negative value means a shortage. `count_discrepancy_bushels` is the operator's declared `reported_physical_bushels` less the system physical figure. `obligation_misstatement_bushels` is the operator's declared `reported_obligation_bushels` less the computed obligation.

The tolerance against which all three are judged is `examination_tolerance_bushels`: the greater of a 500-bushel floor and 50 basis points — one half of one percent — of the obligation, rounded half up to a whole bushel. `examination_required` is true when the absolute value of **any** of the three deltas is **strictly greater** than that tolerance; a delta exactly equal to the tolerance does not require examination. All of these figures, plus `operational_posture`, are also available as a computed read on the warehouse recomputed at the current logical clock, which lets an operator check its own position before committing to a filing. That read returns the whole warehouse object of §3.1 with exactly two additions: `warehouse_id`, repeating the row's own `id`, and `unreceipted_obligation_bushels`, the accepted-but-unreceipted half of the obligation.

A `WarehouseOperator` opens a report for its own warehouse with a `warehouse_id`, a `period_start_date` and `period_end_date` bounding the reporting period inclusively — the end must not precede the start — and an `as_of_date` on which the physical count was taken, which must fall inside that closed period. A period whose end precedes its start, or an `as_of_date` outside the closed period, is a request-shape failure reported as `ERR_VALIDATION`. The period must not overlap the closed period of any other report of the same warehouse in `report_state` `DRAFT`, `UNDER_EXAMINATION` or `ACCEPTED`; an overlap is refused with `ERR_REPORT_PERIOD_OVERLAP` (HTTP 409). A new report starts in `DRAFT` with `revision_count` zero, `reported_physical_bushels` and `reported_obligation_bushels` null, every snapshot figure null, and `examination_result`, `examined_by_user_id`, `findings_note` and `submitted_at` all null.

Submission supplies `reported_physical_bushels` and `reported_obligation_bushels`, both required integers of zero or more, and is admissible only while the report is `DRAFT` or `REJECTED` — an `UNDER_EXAMINATION` or `ACCEPTED` report is refused with `ERR_INVALID_STATE` — while applying no licensing, insolvency or posture gate of its own. It is the branch point of the whole workflow: the same operation reaches two different states purely from the computed tolerance test. In both branches the submission snapshots `obligation_bushels`, `system_physical_bushels`, `sound_physical_bushels`, the three deltas and `examination_tolerance_bushels` onto the report, sets `submitted_at` from the logical clock, and recomputes the warehouse's posture.

- When `examination_required` computes false, a `DRAFT` report goes straight to `ACCEPTED`, with `examination_result` set to `PASS` and `examined_by_user_id` left null — nobody examined it. Acceptance also clears any `RESTRICTED` posture that a previously rejected report had caused.
- When `examination_required` computes true, a `DRAFT` report goes to `UNDER_EXAMINATION` instead, and this branch additionally requires that no other report of the same warehouse already sit in `UNDER_EXAMINATION`; a second referral while another remains under examination is refused with `ERR_INVALID_STATE`.

A rejected report can be corrected and re-submitted, and this is the system's one deliberate cycle. From `REJECTED`, a re-submission with corrected figures whose `examination_required` computes true returns the report to `UNDER_EXAMINATION`, subject to the same "no other report under examination" guard; it increments `revision_count` by one, clears `examination_result`, `examined_by_user_id` and `findings_note`, and re-snapshots every derived figure. From `REJECTED`, a re-submission whose `examination_required` computes false goes instead to `ACCEPTED`, likewise incrementing `revision_count` by one, setting `examination_result` to `PASS`, and clearing the `RESTRICTED` posture attributable to this report. `revision_count` is the loop counter for `REJECTED → UNDER_EXAMINATION → REJECTED`, which may repeat any number of times. `ACCEPTED` is the report's only terminal state.

Examination is a `StateRegulator` action recording a `result` of `PASS`, `DEFICIENT` or `CRITICAL` together with an optional `findings_note`. It is admissible only from `UNDER_EXAMINATION`, and it is subject to **examination independence**: the examining regulator's `X-User-ID` must differ from the `licensed_by_user_id` recorded on the warehouse. A regulator may not examine a facility whose licence that same regulator issued or denied, and an attempt to do so is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403); a second regulator identity must record the result. A warehouse with no `licensed_by_user_id` yet recorded imposes no such constraint, there being nothing to compare against. Every examination records `examination_result`, `examined_by_user_id` and `findings_note` — the last one null when the request omits it — and increments the warehouse's `version` by one whenever the warehouse row is touched.

The three results diverge sharply, and each of the two rejecting results carries its own distinct effect set even though they share a state target:

- `PASS` moves the report to `ACCEPTED` and does nothing further — the warehouse row is not touched at all, so its `version` does not move.
- `DEFICIENT` moves the report to `REJECTED` and drives the warehouse's `operational_posture` to `RESTRICTED`. The licence is untouched.
- `CRITICAL` moves the report to `REJECTED` and, on top of the deficient effects, escalates: the warehouse's `license_state` moves from `LICENSED` to `SUSPENDED`, `operational_posture` becomes `CLOSED`, and every deposit ticket of that warehouse in `ticket_state` `WEIGHED` moves to `REJECTED` with `rejection_reason` `LICENSE_SUSPENDED`. A `CRITICAL` result recorded against a warehouse whose licence is not `LICENSED` is not an error: the licence is left exactly as it stands, while the ticket cascade and the warehouse's `version` increment happen regardless.

Reinstatement after a critical finding is therefore not merely a paperwork step — it must clear the financial tests of §3.1 and requires that no report remain under examination.

### 3.8. Delivery Out of Store and Quality-Adjusted Settlement

The delivery right belongs to whoever holds the receipt, so a `Depositor` or a `Lender` books the loadout. The request names the `receipt_id`, the `requested_bushels` demanded out of store (at least one), and the `appointment_start_at` and `appointment_end_at` bounds of the loadout appointment, the end strictly after the start. `requester_party_id` is set from the caller's `X-User-ID`, which must be the receipt's current `holder_party_id`. Booking further requires the receipt to be in `receipt_state` `ISSUED`, refused with `ERR_INVALID_STATE`; the warehouse to be `LICENSED` and `SOLVENT`, so that a `CLOSED` posture blocks booking just as it blocks loadout; and the receipt's bin not to be `OUT_OF_CONDITION`. A merely `RESTRICTED` posture does not block booking, and neither does a `PLEDGED` encumbrance. The requested quantity must not exceed the receipt's outstanding `quantity_bushels`, or the request is refused with `ERR_DELIVERY_EXCEEDS_RECEIPT`.

Appointments are **half-open** intervals: a new appointment overlaps an existing one when the new start is strictly before the existing end and the existing start is strictly before the new end, considered over orders in `delivery_state` `REQUESTED` or `LOADED`. Overlapping appointments are fine as long as there is a free lane. `lane_index` is assigned as the lowest integer from zero up to but excluding the warehouse's `loadout_lane_count` that no overlapping order already occupies — occupancy being counted across every live order of the same warehouse, whichever bin or receipt it draws on, since the lanes are a facility-wide resource; when every lane is taken, the booking is refused with `ERR_LOADOUT_CAPACITY_EXCEEDED` (HTTP 409), and that refusal precedes the quantity test above per §2.8. Booking raises the bin's `held_bushels` by `requested_bushels`, which is what keeps the same grain from being promised twice, and the order starts in `REQUESTED` with `delivered_bushels`, `delivered_grade`, `settlement_price_cents_per_bushel`, `loaded_at`, `settled_at`, `cancelled_at` and `cancellation_reason` all null.

An unloaded order may be cancelled by the party that requested it — its `requester_party_id`, and no one else, so a later holder of the receipt is refused with `ERR_NOT_RESOURCE_OWNER` — with an optional `cancellation_reason` that stays null when omitted. Cancellation moves the order to `CANCELLED`, releases the held bushels back into the bin's `available_bushels`, frees its `lane_index`, and sets `cancelled_at`. Only `REQUESTED` orders are cancellable, and the `lane_index` recorded at booking is left on the row rather than nulled.

**Loadout** is the operator's action. It records `delivered_bushels` (at least one, and no greater than `requested_bushels`, on pain of `ERR_DELIVERY_EXCEEDS_RECEIPT`) together with the four factors measured on the grain actually loaded: `delivered_test_weight_lbs`, `delivered_moisture_pct`, `delivered_damage_pct` and `delivered_foreign_material_pct`. It requires the order to be `REQUESTED`, the warehouse to be `LICENSED` and `SOLVENT` with `operational_posture` not `CLOSED`, and the bin not to be `OUT_OF_CONDITION`; the `delivered_bushels` ceiling is the order's own `requested_bushels`, not the receipt's outstanding quantity, since booking already tested that. Loadout grades the delivered grain through the same factor table of §2.9 that was used at weigh-in, writing `delivered_grade`; computes `grade_delta_bps`; sets `loaded_at`; computes `storage_charge_cents` using the **FINAL** storage variant of §2.10 evaluated on the receipt's outstanding `quantity_bushels` as of the loadout date; and computes `loadout_charge_cents` as `delivered_bushels` multiplied by the agreement's `loadout_charge_cents_per_bushel`, rounded half up to whole cents. Two details are load-bearing. Storage is charged on the receipt's whole outstanding quantity, **not** on the delivered bushels, because the entire lot occupied the bin up to this moment. And the free-day allowance appears here and only here: this is the one place the final variant is used.

`grade_delta_bps` is **asymmetric**, and deliberately so. It is the discount for `delivered_grade` less the discount for the receipt's certified `grade`, both from the §2.9 schedule, floored at zero. When the warehouse delivers grain worse than it certified, the difference is positive and the depositor is compensated; when it delivers grain *better* than it certified, the delta is zero and the warehouse keeps no credit for the upgrade.

**Settlement** supplies a `settlement_price_cents_per_bushel` of at least one cent and requires the order to be `LOADED` and the receipt's `encumbrance_state` not to be `PLEDGED`. `quality_adjustment_cents` is the product of `delivered_bushels`, that settlement price and `grade_delta_bps`, divided by ten thousand and rounded half up to whole cents; it is a credit owed to the depositor. `net_settlement_cents` is that quality adjustment less `storage_charge_cents` less `loadout_charge_cents`, and it may well be negative — a negative net settlement means the depositor owes the warehouse. The quality adjustment and the loadout charge are each rounded independently before the subtraction. Settlement sets `settled_at`, lowers the bin's `stored_bushels` by `delivered_bushels`, lowers `held_bushels` by releasing the order's hold, adjusts the requesting party's `settlement_balance_cents` by `net_settlement_cents`, and recomputes the warehouse's `obligation_bushels` and `operational_posture`.

Settlement then branches on a quantity comparison, and the two branches differ only in what happens to the receipt:

- When `delivered_bushels` equals the receipt's outstanding `quantity_bushels`, the order reaches `SETTLED_FULL`. The receipt's `quantity_bushels` drops to zero and its `receipt_state` moves from `ISSUED` to `CANCELLED`, so the receipt leaves the warehouse's `obligation_bushels` entirely. This is cancellation on delivery — the receipt has been fully performed.
- When `delivered_bushels` is less than the receipt's outstanding `quantity_bushels`, the order reaches `SETTLED_PARTIAL`. The quality adjustment and net settlement are computed on the delivered quantity only, and the receipt stays in `receipt_state` `ISSUED` with its `quantity_bushels` reduced by `delivered_bushels`, so a residual obligation and a residual collateral base both remain.

`SETTLED_FULL`, `SETTLED_PARTIAL` and `CANCELLED` are the three terminal delivery states.

### 3.9. Insolvency, Indemnity Claims and the Two-Tier Waterfall

The insolvency dimension is entirely independent of the licensing dimension. A `LICENSED` warehouse can be declared insolvent, and a `SUSPENDED` warehouse can remain `SOLVENT`. `insolvency_state` runs `SOLVENT` → `DECLARED` → `CLAIMS_OPEN` → `ALLOCATED` → `CLOSED`, with `CLOSED` terminal, and each step is a regulator action carrying an `action` of `DECLARE`, `OPEN_CLAIMS`, `ALLOCATE` or `CLOSE`, an optional `insolvency_price_cents_per_bushel` of zero or more, and an optional `note` which is accepted but neither persisted nor reported. The price is written only by an action that actually supplies it, so it remains null when `DECLARE` omits it, and a null price is then read as zero by every entitlement computed in the proceeding. Every such action increments the warehouse's `version` by one, and any action taken out of sequence is refused with `ERR_INVALID_STATE`.

`DECLARE` requires the warehouse to be `SOLVENT` and its `license_state` to be anything other than `DENIED`. It sets `insolvency_declared_at` to the current logical clock and fixes `insolvency_price_cents_per_bushel` from the request — one posted commodity price that will govern every entitlement in the proceeding. Declaration drives `operational_posture` to `CLOSED` regardless of `license_state`, cancels every delivery order in `delivery_state` `REQUESTED` with `cancellation_reason` `INSOLVENCY_DECLARED` and releases their held bushels, and moves every deposit ticket in `ticket_state` `WEIGHED` to `REJECTED` with `rejection_reason` `INSOLVENCY_DECLARED`. `OPEN_CLAIMS` then makes claim filing permitted for this warehouse and does nothing else.

A claim is filed by a `Depositor` or a `Lender` against a warehouse whose `insolvency_state` is `CLAIMS_OPEN`, naming the `warehouse_id`, the `receipt_id` the claim is founded on, the `claimant_party_id` — which must equal the caller's `X-User-ID` and must be either the receipt's `holder_party_id` or its `registry_control_party_id`, a claimant matching neither of those two references being rejected with `ERR_NOT_RESOURCE_OWNER` — and the `claimed_cents` asserted, at least one cent. The underlying receipt must be in `receipt_state` `ISSUED` so that an entitlement can exist; a claim founded on a cancelled or voided receipt, or asserting less than one cent, is refused with `ERR_CLAIM_NOT_ELIGIBLE`. A claimant may hold at most one live claim per receipt, counting claims in `claim_state` `FILED`, `ALLOWED` or `SETTLED`; a duplicate is refused with `ERR_CLAIM_DUPLICATE` (HTTP 409). A `DISALLOWED` claim, by contrast, may be re-filed. A warehouse whose `insolvency_state` is anything other than `CLAIMS_OPEN` — not yet declared, merely `DECLARED`, already `ALLOCATED` or `CLOSED` — refuses the filing with `ERR_INVALID_STATE`, and that refusal precedes both the duplicate test and the eligibility test. A new claim starts `FILED` with `entitlement_cents`, `allowed_cents`, `bond_share_cents`, `fund_share_cents` and `unpaid_cents` all zero, `fund_eligible` already set from the claimant's `party_kind`, and `adjudicated_by_user_id` and `adjudication_note` null.

Adjudication is a regulator action carrying a `decision` of `ALLOW` or `DISALLOW` and an optional `adjudication_note`. It is admissible only while the claim is `FILED` and the warehouse is `CLAIMS_OPEN`, and it records `adjudicated_by_user_id`.

- `ALLOW` fixes the claim's economics **at adjudication time, not at allocation time**. `entitlement_cents` is the receipt's outstanding `quantity_bushels` valued at the warehouse's `insolvency_price_cents_per_bushel`, less the warehouseman's prior claim — which here is the `PROVISIONAL` storage accrual of §2.10 computed on that same outstanding quantity as of the date of `insolvency_declared_at`, plus the receipt's `receiving_charge_cents` — with the whole result floored at zero. `allowed_cents` is the lesser of `claimed_cents` and `entitlement_cents`: a claimant can never recover more than it asserted, nor more than the grain was worth net of storage. `fund_eligible` is set true only when the claimant party's `party_kind` is `PRODUCER_DEPOSITOR`; commercial depositors and lenders are not fund-eligible, which is the depositor-protection restriction at the heart of the scheme. The claim moves to `ALLOWED`.
- `DISALLOW` moves the claim to `DISALLOWED` and leaves both `entitlement_cents` and `allowed_cents` at zero, so the claim draws nothing from either tier of the waterfall and contributes nothing to the pro-rata base.

`ALLOCATE` runs the waterfall. It requires the warehouse to be `CLAIMS_OPEN` and requires that **no** claim of this warehouse remain in `claim_state` `FILED` — every claim must have been adjudicated one way or the other first, or the run is refused with `ERR_INVALID_STATE`. The run operates over the warehouse's claims in `claim_state` `ALLOWED` only; disallowed claims are excluded from the pro-rata base entirely. Let the total allowed be the sum of `allowed_cents` across those claims.

**Tier one is the warehouse bond, and it is shared by every allowed claimant regardless of kind.** The bond pool is the warehouse's `bond_amount_cents`. If the total allowed is less than or equal to the pool, every claim's `bond_share_cents` is simply its own `allowed_cents` and no pro-rating is needed. Otherwise each claim's `bond_share_cents` is the pool multiplied by that claim's `allowed_cents`, divided by the total allowed, rounded **down** to a whole cent — floor, not half up. Flooring leaves a remainder equal to the pool less the sum of the floored shares, and that remainder is distributed one cent at a time to claims taken in a fixed order: descending `allowed_cents` first, then ascending `created_at` as the tie-break, and never by `id` — claims still tied on both keys are taken in the order they were created. The first as many claims as there are remainder cents each receive one additional cent, so the shares sum to the pool exactly.

**Tier two is the state indemnity fund, and only producer depositors reach it.** The fund starts each proceeding with an aggregate capacity of 100,000,000 cents — one million dollars — and no single claimant may draw more than 30,000,000 cents, three hundred thousand dollars, from it. The tier is walked **sequentially** in the same order used for the remainder distribution: descending `allowed_cents`, then ascending `created_at`. For each claim in that order, the residual is its `allowed_cents` less its `bond_share_cents`. If the claim's `fund_eligible` is false, or the fund's remaining capacity has already reached zero, its `fund_share_cents` is zero. Otherwise its `fund_share_cents` is the smallest of the residual, the 30,000,000-cent per-claimant cap and the fund's remaining capacity, and the fund's remaining capacity is reduced by that share before the next claim is considered. Because the walk is sequential, the ordering is genuinely observable whenever the aggregate cap binds: an earlier claim in the ordering can exhaust the fund and leave a later eligible claim with nothing.

Each claim's `unpaid_cents` is then its `allowed_cents` less its `bond_share_cents` less its `fund_share_cents`, and each allowed claim moves from `ALLOWED` to `SETTLED`. The run also materialises five roll-ups onto the warehouse: `allowed_claim_total_cents`, the sum of `allowed_cents` across claims in `claim_state` `ALLOWED` or `SETTLED`; `bond_allocated_cents` and `fund_allocated_cents`, the sums of the two share fields taken over every claim of the warehouse whatever its state, both zero before the run because a `FILED` or `DISALLOWED` claim carries zero shares; `allocated_total_cents`, their sum; and `unpaid_claim_total_cents`, the sum of `unpaid_cents` over that same full set. All five are read-time sums over the claim rows rather than stored figures, so they do not of themselves move the warehouse's `version`. Once the warehouse is `ALLOCATED`, further claim filing is refused, because the allocation basis is frozen.

`CLOSE` moves an `ALLOCATED` proceeding to `CLOSED`, after which no further insolvency action is accepted at all.

## 4. Endpoint Definitions

Operations that bring a new resource into existence return `201 Created`. Every other operation — state transitions, restatements, condition assessments, examinations, adjudications, reads and the logical-clock control — returns `200 OK`. Request bodies, response bodies and side effects are not restated in this table; they are specified in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | StateRegulator, WarehouseOperator, Depositor, Lender, RegistryAdministrator |
| POST | `/warehouses` | File a warehouse licence application | StateRegulator |
| GET | `/warehouses` | List warehouses with optional filters | StateRegulator, WarehouseOperator, RegistryAdministrator, Depositor, Lender |
| GET | `/warehouses/{warehouse_id}` | Read one warehouse with every derived licensing, position and insolvency figure | StateRegulator, WarehouseOperator, RegistryAdministrator, Depositor, Lender |
| PATCH | `/warehouses/{warehouse_id}/financials` | Restate applied capacity, posted bond or audited net worth | StateRegulator, WarehouseOperator |
| POST | `/warehouses/{warehouse_id}/license-decision` | Drive the licensing dimension | StateRegulator |
| POST | `/warehouses/{warehouse_id}/insolvency` | Drive the insolvency dimension | StateRegulator |
| GET | `/warehouses/{warehouse_id}/position-summary` | Computed position and posture read at the current logical clock | StateRegulator, WarehouseOperator |
| POST | `/parties` | Register a depositor or lender counterparty | StateRegulator, RegistryAdministrator |
| GET | `/parties` | List parties with optional filters | StateRegulator, WarehouseOperator, RegistryAdministrator, Depositor, Lender |
| GET | `/parties/{party_id}` | Read one party with committed advance, available credit and settlement balance | StateRegulator, WarehouseOperator, RegistryAdministrator, Depositor, Lender |
| PATCH | `/parties/{party_id}/credit-line` | Restate a lender's credit line | StateRegulator |
| POST | `/storage-agreements` | Open a storage agreement | WarehouseOperator |
| GET | `/storage-agreements` | List storage agreements | StateRegulator, WarehouseOperator, Depositor, Lender |
| GET | `/storage-agreements/{agreement_id}` | Read one storage agreement | StateRegulator, WarehouseOperator, Depositor, Lender |
| POST | `/storage-agreements/{agreement_id}/terminate` | Terminate an agreement | WarehouseOperator |
| POST | `/bins` | Add a storage bin | WarehouseOperator |
| GET | `/bins` | List bins | StateRegulator, WarehouseOperator, Depositor, Lender |
| GET | `/bins/{bin_id}` | Read one bin | StateRegulator, WarehouseOperator, Depositor, Lender |
| POST | `/bins/{bin_id}/condition-assessment` | Record a condition assessment and re-derive bin condition | WarehouseOperator |
| POST | `/deposit-tickets` | Weigh, grade and quantify an inbound load | WarehouseOperator |
| GET | `/deposit-tickets` | List deposit tickets | StateRegulator, WarehouseOperator, Depositor, Lender |
| GET | `/deposit-tickets/{ticket_id}` | Read one deposit ticket | StateRegulator, WarehouseOperator, Depositor, Lender |
| POST | `/deposit-tickets/{ticket_id}/accept` | Accept a weighed load into the bin | WarehouseOperator |
| POST | `/deposit-tickets/{ticket_id}/reject` | Reject a weighed load | WarehouseOperator |
| POST | `/receipts` | Issue a warehouse receipt against an accepted ticket | WarehouseOperator |
| GET | `/receipts` | List warehouse receipts | StateRegulator, WarehouseOperator, RegistryAdministrator, Depositor, Lender |
| GET | `/receipts/{receipt_id}` | Read one receipt | StateRegulator, WarehouseOperator, RegistryAdministrator, Depositor, Lender |
| POST | `/receipts/{receipt_id}/transfer` | Transfer a negotiable receipt by endorsement or registry entry | Depositor, Lender, RegistryAdministrator |
| POST | `/receipts/{receipt_id}/void` | Void a receipt inside the void window | WarehouseOperator |
| POST | `/collateral-liens` | Record a lender advance request and value the collateral | Lender |
| GET | `/collateral-liens` | List collateral liens | StateRegulator, WarehouseOperator, RegistryAdministrator, Depositor, Lender |
| GET | `/collateral-liens/{lien_id}` | Read one lien with its full valuation breakdown | StateRegulator, WarehouseOperator, RegistryAdministrator, Depositor, Lender |
| POST | `/collateral-liens/{lien_id}/perfect` | Perfect the lender's interest | Lender |
| POST | `/collateral-liens/{lien_id}/release` | Release the lien | Lender |
| POST | `/collateral-liens/{lien_id}/revalue` | Re-mark the collateral | Lender |
| POST | `/position-reports` | Open a draft position report | WarehouseOperator |
| GET | `/position-reports` | List position reports | StateRegulator, WarehouseOperator |
| GET | `/position-reports/{report_id}` | Read one position report | StateRegulator, WarehouseOperator |
| POST | `/position-reports/{report_id}/submit` | Submit declared figures | WarehouseOperator |
| POST | `/position-reports/{report_id}/examine` | Record the examination result | StateRegulator |
| POST | `/delivery-orders` | Exercise a delivery right and book a loadout lane | Depositor, Lender |
| GET | `/delivery-orders` | List delivery orders | StateRegulator, WarehouseOperator, Depositor, Lender |
| GET | `/delivery-orders/{order_id}` | Read one delivery order | StateRegulator, WarehouseOperator, Depositor, Lender |
| POST | `/delivery-orders/{order_id}/load` | Record loadout weights and grade factors | WarehouseOperator |
| POST | `/delivery-orders/{order_id}/settle` | Settle the delivery | WarehouseOperator |
| POST | `/delivery-orders/{order_id}/cancel` | Cancel an unloaded delivery order | Depositor, Lender |
| POST | `/indemnity-claims` | File a depositor-protection claim | Depositor, Lender |
| GET | `/indemnity-claims` | List indemnity claims | StateRegulator, WarehouseOperator, Depositor, Lender |
| GET | `/indemnity-claims/{claim_id}` | Read one claim with its entitlement and allocation shares | StateRegulator, WarehouseOperator, Depositor, Lender |
| POST | `/indemnity-claims/{claim_id}/adjudicate` | Allow or disallow a filed claim | StateRegulator |

List endpoints accept the filters named in §2.3 and, where the resource supports them, the following optional query parameters: warehouses accept `state_code`, `license_program`, `license_state` and `insolvency_state`; parties accept `party_kind` and `state_code`; storage agreements accept `warehouse_id`, `depositor_party_id`, `agreement_state` and `storage_kind`; bins accept `warehouse_id`, `dedicated_agreement_id`, `condition_state` and `commodity`; deposit tickets accept `storage_agreement_id`, `bin_id` and `ticket_state`; receipts accept `warehouse_id`, `deposit_ticket_id`, `storage_agreement_id`, `bin_id`, `holder_party_id`, `registry_control_party_id`, `receipt_state`, `encumbrance_state`, `form` and `medium`; collateral liens accept `receipt_id`, `lender_party_id`, `pledgor_party_id`, `lien_state`, `valuation_basis` and `margin_status`; position reports accept `warehouse_id`, `report_state` and `examination_result`; delivery orders accept `receipt_id`, `requester_party_id` and `delivery_state`; and indemnity claims accept `warehouse_id`, `receipt_id`, `claimant_party_id` and `claim_state`. Every list endpoint also accepts `limit` and `offset`.

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_TRANSFER_CHANNEL_INVALID` | 403 Forbidden |
| `ERR_VALIDATION` | 422 Unprocessable Entity |
| `ERR_WAREHOUSE_NOT_FOUND` | 404 Not Found |
| `ERR_PARTY_NOT_FOUND` | 404 Not Found |
| `ERR_AGREEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_BIN_NOT_FOUND` | 404 Not Found |
| `ERR_TICKET_NOT_FOUND` | 404 Not Found |
| `ERR_RECEIPT_NOT_FOUND` | 404 Not Found |
| `ERR_LIEN_NOT_FOUND` | 404 Not Found |
| `ERR_REPORT_NOT_FOUND` | 404 Not Found |
| `ERR_DELIVERY_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_PARTY_KIND_INVALID` | 422 Unprocessable Entity |
| `ERR_COMMODITY_MISMATCH` | 422 Unprocessable Entity |
| `ERR_STALE_WAREHOUSE_VERSION` | 412 Precondition Failed |
| `ERR_STALE_BIN_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_WAREHOUSE_NOT_LICENSED` | 422 Unprocessable Entity |
| `ERR_WAREHOUSE_INSOLVENT` | 422 Unprocessable Entity |
| `ERR_POSTURE_RESTRICTED` | 422 Unprocessable Entity |
| `ERR_BIN_OUT_OF_CONDITION` | 422 Unprocessable Entity |
| `ERR_GRADE_BELOW_MINIMUM` | 422 Unprocessable Entity |
| `ERR_COMMINGLING_NOT_PERMITTED` | 422 Unprocessable Entity |
| `ERR_RECEIPT_NOT_NEGOTIABLE` | 422 Unprocessable Entity |
| `ERR_REGISTRY_NOT_PARTICIPANT` | 422 Unprocessable Entity |
| `ERR_PERFECTION_METHOD_MISMATCH` | 422 Unprocessable Entity |
| `ERR_RECEIPT_ENCUMBERED` | 409 Conflict |
| `ERR_VOID_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_BIN_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_LOADOUT_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_REPORT_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_RECEIPT_NUMBER_DUPLICATE` | 409 Conflict |
| `ERR_CLAIM_DUPLICATE` | 409 Conflict |
| `ERR_NET_WORTH_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_BOND_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_LICENSED_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_BIN_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_CREDIT_LINE_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_DELIVERY_EXCEEDS_RECEIPT` | 422 Unprocessable Entity |
| `ERR_CLAIM_NOT_ELIGIBLE` | 422 Unprocessable Entity |
