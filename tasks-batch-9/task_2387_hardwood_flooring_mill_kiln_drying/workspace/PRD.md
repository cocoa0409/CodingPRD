# Hardwood Flooring Mill & Kiln Drying API — Product Requirements Document

## 1. Introduction

A hardwood flooring mill lives or dies by moisture. Logs and green lumber arrive at the receiving deck at forty-odd percent moisture content; they leave the kilns at single digits; and the tongue-and-groove boards milled from them must still be dimensionally honest years later in a customer's living room. Between those two points sit a dozen decisions that today are recorded on clipboards and in spreadsheets scattered across the receiving deck, the kiln shed, the moulder line, the grading table and the prefinish building — and when a cupping claim arrives eighteen months after installation, nobody can reconstruct which charge dried the wood, what its shell-to-core gradient was at release, or how wide the boards were actually milled.

This document specifies the backend service that replaces those clipboards. It is a single system of record for the whole spine of the mill: green receipt and scaling, kiln charge scheduling against chamber occupancy, drying schedules parameterised by species and thickness, the stress test that decides between release and redry, milling with moisture-aware width planning and a strict mass balance, grading under industry rulesets with character-grade separation, prefinishing on capacity-constrained lines, byproduct sales of sawdust, shavings and shorts, and warranty adjudication against the installation conditions the claimant reports. Every quantity that matters — green board feet, kiln-dry board feet, graded board feet, warranty cents — is conserved by construction rather than reconciled after the fact.

Two design commitments run through the whole specification. First, **the mill's physical constraints are the API's validation rules**: a kiln chamber holds one charge at a time plus a cooldown period, a prefinish line has a finite linear-foot throughput across any overlapping set of windows, and core stock cannot be reserved twice. Second, **money and material are ledgers, not attributes**: the warranty reserve of a product line and the kiln-dry volume remaining on a charge are derived from the movements recorded against them, and every operation that draws them down has a compensating operation that restores them exactly. All resources described below are mounted under the `/mill` prefix, with the sole exception of the logical-clock capability described in §2.4.

## 2. Global Specifications & System-Wide Principles

### 2.1. Mill Personnel and Role-Based Access Control

Every request must identify who is acting and in what capacity. The acting user is carried in the `X-User-ID` header and the acting capacity in the `X-Role` header. For compatibility with clients that send the capacity under the conventional name, a request that omits `X-Role` but supplies `X-User-Role` is treated as carrying that same role value; the two header names are interchangeable and `X-Role` takes precedence when both are present. A request that carries no role header at all, or that carries the reserved value `Anonymous`, is an unauthenticated caller: it performs no operations and is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognised but is not on the acting endpoint's permitted list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Eight working roles are recognised, spelled exactly as follows: `MillAdmin`, `ProcurementClerk`, `KilnOperator`, `MillSupervisor`, `GradeInspector`, `PrefinishScheduler`, `ByproductBroker` and `WarrantyAdjudicator`. They are peer roles rather than a hierarchy — each owns a stretch of the mill and `MillAdmin` acts as a configuration owner and workflow backstop:

- `MillAdmin` alone registers species profiles, kiln chambers, product lines and prefinish lines, and alone funds, freezes and unfreezes a product line's warranty reserve. It also shares most workflow operations as a backstop.
- `ProcurementClerk` owns the receiving deck: recording, accepting and rejecting green receipts.
- `KilnOperator` alone loads a charge, starts its drying leg, begins conditioning, records the stress test and resumes conditioning after a redry. It shares drying-schedule creation, charge scheduling, receipt allocation and deallocation, rescheduling and chamber maintenance.
- `MillSupervisor` alone records milling completion. It shares lot planning, voiding, lot finalization, core stock registration and warranty remediation.
- `GradeInspector` alone opens a grade run, adds bundles to it and finalizes it. It shares superseding a run and finalizing a lot.
- `PrefinishScheduler` alone starts and completes a prefinish run. It shares run scheduling and hold release.
- `ByproductBroker` sells sawdust, shavings and shorts.
- `WarrantyAdjudicator` alone requests further information on a claim and alone adjudicates it. It shares claim filing, resubmission, reversal and remediation.

All eight roles may read every retrieval endpoint and may drive the logical clock. No role in this system is backed by a persisted entity: when `X-Role` is any of the eight names above, `X-User-ID` is an opaque operator identifier not tied to any stored record. The server records it where a workflow demands accountability — as `submitted_by_user_id` when a warranty claim is filed and as `adjudicated_by_user_id` when one is adjudicated — but it never compares `X-User-ID` to any entity's `id`, and there are no ownership checks of the form "the acting user must own this resource".

There is exactly one segregation-of-duties rule, and it is enforced on identifiers rather than roles: the `X-User-ID` that filed a warranty claim may not adjudicate that same claim, even when it presents the `WarrantyAdjudicator` role. Such an attempt is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

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

Every collection endpoint accepts two optional query parameters. `limit` controls page size: it defaults to 10, may not be smaller than 1 and may not be larger than 100. `offset` controls the starting position: it defaults to 0 and may not be negative. A `limit` outside 1 through 100, or a negative `offset`, is a schema failure and is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless a subsection states otherwise, collections are returned in ascending `created_at` order — oldest first — so that paging through a collection with a stable offset yields a stable sequence. The `meta` block of a list response carries `limit` and `offset` as applied, `total_count` as the number of rows matching the filters before paging, and `has_more` as a boolean indicating whether rows remain beyond the current page. Filter query parameters, where a subsection names them, combine conjunctively and are applied before paging.

### 2.4. Resource Identity, Revision Counters and the Logical Clock

Each stored resource carries a server-minted `id` in canonical UUID form with no type prefix of any kind, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Most resources additionally carry an `updated_at` timestamp in the same format and an integer `version` that starts at 1 on creation and increases by exactly 1 on every mutation of that resource — including mutations reached as a cascade from an operation aimed at some other resource. When a charge release frees its chamber, for instance, both the charge and the chamber have their `version` incremented and their `updated_at` refreshed.

`GradeBundle` is the single exception. A graded bundle is an immutable tally line: once written it is never edited, so it carries only `id` and `created_at`. It has no `updated_at` field and no `version` field at all, and neither appears in its representation.

Because warranty age, service months and future-date screening all depend on "now", the system runs on an explicit logical clock rather than wall time. A test-driving capability sets that clock to a supplied `current_utc` instant and returns it; the clock defaults to `2026-08-01T00:00:00Z` before it is ever set. Every subsequent date-dependent calculation — the whole-month service age of a claim, the warranty filing window, and the rejection of a future installation date — reads this logical instant. All eight roles may drive it.

### 2.5. Optimistic Concurrency on Species Profiles and Flooring Lots

Two creation operations are pinned to the revision of the parent record they were designed against, and both use the parent's `version` as the token.

A drying schedule is only meaningful against the species-profile revision whose density class and moisture targets it was designed for. Creating a drying schedule therefore requires a non-optional `expected_species_profile_version` field in the request body, carrying the client's last observed `version` of the referenced `SpeciesProfile`. If that value does not equal the profile's current `version`, the write is refused with `ERR_STALE_SPECIES_PROFILE_VERSION` (HTTP 412). A successful create increments `SpeciesProfile.version`, so a caller that holds a pre-write version is refused on its next attempt until it re-reads the profile.

Grading must likewise be pinned to the milled measurements it was based on. Creating a grade run requires a non-optional `expected_lot_version` field carrying the client's last observed `version` of the referenced `FlooringLot`; a value that does not equal the lot's current `version` is refused with `ERR_STALE_LOT_VERSION` (HTTP 412). A successful create increments `FlooringLot.version`, so a caller that read the lot before an intervening write is refused until it re-reads it.

No other endpoint takes a version field. Requests to `POST /mill/drying-schedules` and `POST /mill/grade-runs` are the only two writes that carry one, and omitting it from either is a schema failure rather than a concurrency failure.

### 2.6. Units, Rounding and Measurement Discipline

Every rounding operation in this specification is half-up: a value exactly on the midpoint rounds away from zero. Rounding is applied at the points named, in the order named, and no step may be algebraically collapsed into another — a total computed from pre-rounded parts is not the same number as the same total rounded once, and where the two differ this document always specifies the former.

The precisions in force are: whole hours to one decimal place for kiln schedule durations; moisture percentages, moisture gradients and moisture deltas to one decimal place; board feet to two decimal places for computed volumes (received, accepted, capacity and charged green board feet are whole integers); grade-credited board feet to four decimal places; tonnage to two decimal places; coating litres to two decimal places; per-board width movement to four decimal places and planned finished width to three decimal places; percentages such as yields, depreciation and responsibility shares to two decimal places except where a subsection names whole percentages; and every monetary amount as a whole number of cents. Instants are handled at whole-minute resolution and serialized as ISO 8601 with milliseconds in UTC. Linear feet are whole integers.

### 2.7. Request Screening Order

When several checks could fail on one request, they are evaluated in a fixed order and the first failure is the one reported. The order is not a matter of convenience: a role failure must surface as a role failure even when the payload is also malformed, and a missing parent must surface before any business rule about that parent is evaluated. The sequence is:

1. Authentication — a request without an authenticated principal is rejected with `ERR_UNAUTHENTICATED` (401). Applies to every endpoint.
2. Role authorization — `ERR_FORBIDDEN_ROLE` (403). Applies to every endpoint.
3. Schema — required fields present, types well formed, enum values within their declared sets, decimals non-negative where applicable, and pagination `limit` within 1 through 100 with `offset` at least 0. Rejected with `ERR_INVALID_REQUEST` (400). Applies to every endpoint.
4. Configuration existence — a referenced `SpeciesProfile`, `DryingSchedule`, `KilnChamber`, `ProductLine`, `CoreStock` or `PrefinishLine` must exist, whether it is named in the path or in the body. Rejected with `ERR_CONFIG_NOT_FOUND` (404).
5. Green receipt existence — `ERR_RECEIPT_NOT_FOUND` (404), on green receipt paths and on the `green_receipt_id` carried in an allocation or deallocation body.
6. Kiln charge existence — `ERR_CHARGE_NOT_FOUND` (404), on kiln charge paths and on flooring lot creation.
7. Flooring lot existence — `ERR_LOT_NOT_FOUND` (404), on flooring lot paths and on grade run creation, prefinish run creation and warranty claim creation.
8. Grade run existence — `ERR_GRADE_RUN_NOT_FOUND` (404), on grade run paths, bundle creation, lot finalization and the replacement reference of a supersede.
9. Prefinish run existence — `ERR_PREFINISH_RUN_NOT_FOUND` (404), on prefinish run paths.
10. Byproduct batch existence — `ERR_BATCH_NOT_FOUND` (404), on byproduct batch paths and on byproduct sale creation.
11. Warranty claim existence — `ERR_CLAIM_NOT_FOUND` (404), on warranty claim paths.
12. Species profile version match — `ERR_STALE_SPECIES_PROFILE_VERSION` (412), on `POST /mill/drying-schedules` only.
13. Flooring lot version match — `ERR_STALE_LOT_VERSION` (412), on `POST /mill/grade-runs` only.
14. Segregation of duties — `ERR_SEGREGATION_OF_DUTIES` (403), on `POST /mill/warranty-claims/{warranty_claim_id}/adjudicate` only.
15. Green receipt state — `ERR_RECEIPT_STATE_INVALID` (409), on accept, reject, allocation and deallocation.
16. Kiln charge state — `ERR_CHARGE_STATE_INVALID` (409), on every kiln charge action endpoint and on flooring lot creation, where the charge must be `RELEASED`.
17. Kiln chamber state — `ERR_CHAMBER_STATE_INVALID` (409), on starting maintenance, completing maintenance, charge creation and charge loading.
18. Flooring lot state — `ERR_LOT_STATE_INVALID` (409), on milling completion, lot finalization, voiding and grade run creation.
19. Grade run state — `ERR_GRADE_RUN_STATE_INVALID` (409), on bundle creation, run finalization, supersede and the run referenced by a lot finalization.
20. Prefinish run state — `ERR_PREFINISH_RUN_STATE_INVALID` (409), on start, complete and hold release.
21. Warranty claim state, in either the adjudication or the remediation dimension — `ERR_CLAIM_STATE_INVALID` (409), on requesting information, resubmission, adjudication, reversal, starting remediation and completing remediation.
22. Product line posture — the posture must be `OPEN` for prefinish scheduling, starting and hold release. Rejected with `ERR_PRODUCT_LINE_POSTURE_BLOCKED` (409), on `POST /mill/prefinish-runs`, start and hold release.
23. Redry allowance — `ERR_REDRY_LIMIT_EXCEEDED` (409), on recording a stress test.
24. Lot grading prerequisite — only a `GRADED` lot may be prefinished; `ERR_LOT_NOT_GRADED` (409), on `POST /mill/prefinish-runs`.
25. Moisture plan deviation — `ERR_MC_PLAN_DEVIATION` (422), on charge loading.
26. Profile tolerance — `ERR_PROFILE_TOLERANCE_EXCEEDED` (422), on milling completion.
27. Byproduct sales bar voiding — `ERR_BYPRODUCT_SALE_EXISTS` (409), on voiding a lot.
28. Species agreement — `ERR_SPECIES_MISMATCH` (422), on allocating a receipt.
29. Core stock required — `ERR_CORE_STOCK_REQUIRED` (422), on `POST /mill/flooring-lots`.
30. Core stock forbidden — `ERR_CORE_STOCK_NOT_ALLOWED` (422), on `POST /mill/flooring-lots`.
31. Core stock ownership — `ERR_CORE_STOCK_LINE_MISMATCH` (422), on `POST /mill/flooring-lots`.
32. Grade run belongs to the lot — `ERR_GRADE_RUN_LOT_MISMATCH` (422), on lot finalization and on supersede.
33. Character grade permission — `ERR_CHARACTER_GRADE_NOT_PERMITTED` (422), on bundle creation and on grade run finalization.
34. Prefinish window shape — `ERR_PREFINISH_WINDOW_INVALID` (422), on `POST /mill/prefinish-runs`.
35. Chamber window collision — `ERR_CHAMBER_WINDOW_CONFLICT` (409), on `POST /mill/kiln-charges` and on rescheduling.
36. Installation date not in the future — `ERR_INSTALL_DATE_IN_FUTURE` (422), on `POST /mill/warranty-claims`.
37. Warranty filing window — `ERR_WARRANTY_PERIOD_EXPIRED` (422), on `POST /mill/warranty-claims`.
38. Accepted volume within received volume — `ERR_ACCEPTED_BF_EXCEEDS_RECEIVED` (422), on accepting a receipt.
39. Chamber capacity — `ERR_CHAMBER_CAPACITY_EXCEEDED` (422), on allocating a receipt.
40. Charge kiln-dry volume — `ERR_CHARGE_DRY_BF_EXCEEDED` (422), on `POST /mill/flooring-lots`.
41. Core stock sufficiency — `ERR_CORE_STOCK_INSUFFICIENT` (422), on `POST /mill/flooring-lots`.
42. Mill mass balance — `ERR_MILL_MASS_BALANCE_VIOLATION` (422), on milling completion.
43. Waste ceiling — `ERR_WASTE_LIMIT_EXCEEDED` (422), on milling completion.
44. Bundle presence — `ERR_NO_GRADE_BUNDLES` (422), on grade run finalization.
45. Bundle volume ceiling — `ERR_BUNDLE_BF_EXCEEDS_LOT` (422), on bundle creation and grade run finalization.
46. Prefinish line loading — `ERR_PREFINISH_CAPACITY_EXCEEDED` (422), on `POST /mill/prefinish-runs`.
47. Byproduct availability — `ERR_BYPRODUCT_QUANTITY_EXCEEDS_BATCH` (422), on `POST /mill/byproduct-sales`.
48. Open claim ceiling — `ERR_TOO_MANY_OPEN_CLAIMS` (409), on `POST /mill/warranty-claims`.
49. Configuration code uniqueness — `ERR_DUPLICATE_CODE` (409), on configuration creation endpoints.
50. Adjudicated area within the claim — `ERR_ADJUDICATED_SF_EXCEEDS_CLAIM` (422), on adjudication.
51. Reserve sufficiency — `ERR_WARRANTY_RESERVE_INSUFFICIENT` (422), on adjudication with an approval decision.

Two consequences of this ordering deserve emphasis. On milling completion, the width tolerance check at step 26 precedes both mass-balance checks at steps 42 and 43, so a lot milled outside tolerance reports `ERR_PROFILE_TOLERANCE_EXCEEDED` even when its reported outputs also break the mass balance. On adjudication, the segregation-of-duties check at step 14 precedes the claim state check at step 21 and the reserve check at step 51, so the submitter of a claim is turned away with `ERR_SEGREGATION_OF_DUTIES` regardless of the claim's state or the reserve's balance.

### 2.8. The Two Conserved Ledgers

Green board feet are conserved between receipts and charges. For every kiln charge in `SCHEDULED`, `DISPLACED` or `LOADED` status, the charge's `charged_green_bf` equals the total `accepted_board_feet` of the green receipts whose `kiln_charge_id` points at that charge and whose status is `ALLOCATED` or `CONSUMED`. Allocation and deallocation are exact inverses: allocating a receipt and then deallocating it restores both `charged_green_bf` and `weighted_initial_moisture_pct` to the values they held before, and returns the receipt to `ACCEPTED` with a null `kiln_charge_id`. Board feet on this ledger are whole integers and no rounding drift is permitted across repeated allocate-and-deallocate cycles.

Warranty cents are conserved on each product line. At all times a line's `warranty_balance_cents` plus its `warranty_committed_cents` equals its `warranty_funded_total_cents`, and `warranty_committed_cents` equals the total `adjudicated_liability_cents` of the claims on that line whose adjudication status is `APPROVED`. A reversal credits back exactly the amount the approval debited, so approving a claim and then reversing it returns the line to its pre-approval balance, its pre-approval committed amount and its pre-approval posture with no residue. All amounts here are whole cents.

### 2.9. Interval Geometry: Chamber Occupancy versus Prefinish Windows

The two scheduling problems in the mill use deliberately different interval conventions, and confusing them is the most common source of double-booking.

A kiln chamber holds at most one charge over any instant, and a charge continues to hold its chamber through a **cooldown buffer of 6 hours** after its planned end. A charge's occupancy interval therefore runs from `planned_start_utc` to `blocked_until_utc` and is **closed at both ends**: two occupancy intervals that merely touch at an endpoint are in conflict. Concretely, a candidate charge conflicts with an existing charge on the same chamber when the candidate's `planned_start_utc` is at or before the existing charge's `blocked_until_utc` and the candidate's `blocked_until_utc` is at or after the existing charge's `planned_start_utc`. The existing charges considered are those on the same `kiln_chamber_id` whose status is `SCHEDULED`, `LOADED`, `DRYING`, `CONDITIONING`, `REDRY` or `RELEASED` — a `DISPLACED` or `CLOSED` charge holds no window. A collision is rejected with `ERR_CHAMBER_WINDOW_CONFLICT`. Where an existing window is blocked until a given instant, a candidate starting exactly at that instant conflicts, and a candidate starting one hour later does not.

A prefinish line, by contrast, is a throughput constraint rather than an exclusive one: several runs may share a window as long as their aggregate linear footage fits the line's daily capacity. Prefinish windows are **half-open**, running from `window_start_utc` inclusive to `window_end_utc` exclusive, so two back-to-back windows with zero gap do **not** overlap. Two windows overlap when the existing run's `window_start_utc` is strictly before the candidate's `window_end_utc` and the candidate's `window_start_utc` is strictly before the existing run's `window_end_utc`. A window must also be non-empty — its end strictly after its start — and no longer than 24 hours, or it is rejected with `ERR_PREFINISH_WINDOW_INVALID`.

### 2.10. Nested Paths and Reference Resolution

Several resources are addressed beneath their parent — a run's bundles beneath the run, for example. Path parameters are resolved strictly left to right, and the first segment that names a row which does not exist decides the response. A request naming an unknown grade run and an unknown bundle reports the grade run's absence, never the bundle's. Every resource is also addressable directly by its own identifier: a graded bundle by its `grade_bundle_id`, a prefinish run by its `prefinish_run_id`, a warranty claim by its `warranty_claim_id`, and a byproduct sale by its `byproduct_sale_id`. The same left-to-right discipline governs body references: parents named in a body are resolved in the order given in §2.7, so a request that names both a missing configuration row and a missing workflow row reports the configuration row.

Configuration codes are unique within their own collection: `species_code` among species profiles, `schedule_code` among drying schedules, `chamber_code` among kiln chambers, and `line_code` among product lines and, separately, among prefinish lines. Re-using a code within its collection is rejected with `ERR_DUPLICATE_CODE`. A product line and a prefinish line may share the same `line_code` value, since they are separate collections.

## 3. Business Logic & Workflows

### 3.1. Configuring the Mill: Species, Schedules, Chambers, Lines and Core Stock

Everything downstream is parameterised by species. A `MillAdmin` registers a species by supplying its `species_code` (the mill's own identifier, such as `RED_OAK`), a human-readable `common_name`, a `density_class` of `DENSE`, `MEDIUM` or `SOFT`, the `tangential_shrinkage_coefficient` expressing dimensional change per one percentage point of moisture change as a fraction of board width, the `target_moisture_pct` the kilns aim for, and the `max_moisture_gradient_pp` that caps the acceptable shell-to-core spread in percentage points. From the density class the server derives `green_to_dry_shrink_pct`, the board-foot shrink from green to kiln-dry: 7.5 percent for `DENSE`, 6.0 percent for `MEDIUM` and 5.0 percent for `SOFT`. Species profiles can be listed with an optional filter on `density_class`.

A drying schedule then couples one species to one thickness. Its payload carries the `species_profile_id` of the governing species, a unique `schedule_code`, the nominal green `thickness_in` in inches, the design green `initial_moisture_pct`, the design kiln-dry `final_moisture_pct`, the `conditioning_hours` of equalisation that follow the drying leg, the `stress_relief_hours` of steaming that follow conditioning, and the `expected_species_profile_version` described in §2.5. Either a `MillAdmin` or a `KilnOperator` may create one, and schedules can be listed filtered by `species_profile_id`.

The schedule's `planned_dry_hours` is computed at creation and is the mill's single estimate of how long the load will occupy a chamber. It begins from a base drying time set by the species density class — 96 hours for `DENSE`, 72 hours for `MEDIUM`, 54 hours for `SOFT` — to which is added a per-point allowance for every percentage point of moisture the schedule must remove, that being the design green moisture less the design kiln-dry moisture, charged at 3.5 hours per point for `DENSE`, 2.5 hours per point for `MEDIUM` and 1.8 hours per point for `SOFT`. That sum is the unscaled drying leg, and it is multiplied by a thickness tier factor: 1.00 for stock at most 1.00 inch thick, 1.45 for stock thicker than that but at most 1.25 inches, 1.95 for stock thicker than that but at most 1.50 inches, and 2.60 for anything thicker. To the scaled drying leg are added the `conditioning_hours` and the `stress_relief_hours` as supplied. The result is rounded half up to one decimal place, and only then clamped into the range 48 to 360 hours: a computed 41.3 becomes 48.0 and a computed 402.7 becomes 360.0. A dense one-inch schedule taking stock from 45.0 percent down to 7.0 percent with 24 conditioning hours and 12 stress relief hours therefore plans 265.0 hours.

Kiln chambers are registered by a `MillAdmin` with a unique `chamber_code` and a `capacity_board_feet` ceiling on green volume, and open in `AVAILABLE` status with a null `maintenance_note`. A `KilnOperator` or `MillAdmin` may take an `AVAILABLE` chamber to `MAINTENANCE`, recording the supplied `maintenance_note`, and later bring it from `MAINTENANCE` back to `AVAILABLE`, clearing that note. A chamber that is `OCCUPIED` cannot be taken out of service, and a chamber that is not in `MAINTENANCE` cannot be returned from it; both are rejected with `ERR_CHAMBER_STATE_INVALID`. Chambers may be listed filtered by `status`.

Product lines are the saleable end of the mill and the unit that carries warranty exposure. A `MillAdmin` creates one with a unique `line_code`, the `species_profile_id` of the face species, a `construction_type` of `SOLID` or `ENGINEERED`, the `nominal_width_in` face width and `nominal_thickness_in` finished thickness in inches, the `material_value_cents_per_sf` replacement value used in warranty arithmetic, and the `warranty_funded_total_cents` initially set aside. On creation `warranty_balance_cents` equals `warranty_funded_total_cents`, `warranty_committed_cents` is 0, `freeze_override` is false, and `posture` is derived as described in §3.9. Lines may be listed filtered by `species_profile_id`, `posture` or `construction_type`.

Engineered lines also consume substrate. A `MillAdmin` or `MillSupervisor` registers core inventory against a line with its `product_line_id`, a `core_material` of `BIRCH_PLY`, `HDF` or `EUCALYPTUS_PLY`, the supplier's `lot_reference`, and the `available_square_feet` on hand; `reserved_square_feet` starts at 0 and is maintained by lot planning. Core stock may be listed filtered by `product_line_id` or `core_material`. Finally, a `MillAdmin` registers each prefinishing line with a unique `line_code`, the `daily_capacity_linear_feet` it can process across any overlapping set of windows, and the number of ultraviolet-cured `coating_passes` it applies.

### 3.2. The Receiving Deck: Green Lumber Intake

A `ProcurementClerk` (or a `MillAdmin` acting as backstop) records each inbound delivery of logs or green lumber with the `species_profile_id` delivered, the `supplier_name` of record, the gross `received_board_feet` as delivered, a `receipt_grade` of `FAS`, `SELECT`, `NO1_COMMON` or `NO2_COMMON` assigned at the deck, and the measured `moisture_pct_at_receipt`. A new receipt opens in `RECEIVED` status with `accepted_board_feet` at 0, a null `kiln_charge_id` and a null `rejection_reason`. Receipts may be listed filtered by `species_profile_id`, `kiln_charge_id` or `status`.

Scaling happens next. Accepting a receipt moves it from `RECEIVED` to `ACCEPTED` and records the `accepted_board_feet` supplied in the payload — the volume that survived scaling, which may be less than the gross delivered volume but may never exceed it. A value above `received_board_feet` is rejected with `ERR_ACCEPTED_BF_EXCEEDS_RECEIVED`. Rejecting a receipt instead moves it from `RECEIVED` to `REJECTED` and records the supplied `rejection_reason`, leaving `accepted_board_feet` at 0; `REJECTED` is terminal, as is `CONSUMED` at the other end of the lifecycle. Attempting either action on a receipt that has already left `RECEIVED` — accepting an already accepted receipt, for instance — is rejected with `ERR_RECEIPT_STATE_INVALID`.

### 3.3. Charge Scheduling, Chamber Windows and Displacement

Scheduling a kiln charge is a claim on a chamber's calendar. A `KilnOperator` or `MillAdmin` supplies the `drying_schedule_id` that will govern the load, the `kiln_chamber_id` it will occupy, and the `planned_start_utc` instant at which it will begin. At creation the schedule's duration is snapshotted onto the charge as its own `planned_dry_hours`, so a later revision of the schedule never moves a charge already on the calendar. From that snapshot the server derives `planned_end_utc`, which is `planned_start_utc` advanced by `planned_dry_hours` hours, and `blocked_until_utc`, which is `planned_end_utc` advanced by the 6-hour cooldown buffer. A charge starting at `2026-08-05T00:00:00.000Z` with 265.0 planned hours ends at `2026-08-16T01:00:00.000Z` and blocks its chamber until `2026-08-16T07:00:00.000Z`.

That derived interval is then tested against the chamber's other occupancy intervals under the closed-interval rule of §2.9, and a collision is refused with `ERR_CHAMBER_WINDOW_CONFLICT`. A charge may not be scheduled into a chamber that is in `MAINTENANCE`, which is refused with `ERR_CHAMBER_STATE_INVALID`. A newly created charge opens in `SCHEDULED` status with `charged_green_bf` at 0, `redry_count` at 0, a null `weighted_initial_moisture_pct`, null stress-test readings, a null `dry_bf_out` and `remaining_dry_bf`, and a null `displaced_reason`. Charges may be listed filtered by `drying_schedule_id`, `kiln_chamber_id` or `status`.

Charges lose their slot when an upstream load overruns. A charge in `SCHEDULED` whose window is overtaken by the extended window of a redrying charge on the same chamber moves to `DISPLACED`, as described in §3.5. Rescheduling brings it back: a `KilnOperator` or `MillAdmin` supplies a fresh `planned_start_utc`, and the charge returns from `DISPLACED` to `SCHEDULED` with `planned_start_utc`, `planned_end_utc` and `blocked_until_utc` all recomputed and `displaced_reason` cleared. The new interval must not collide with any other occupancy interval on the chamber, or the reschedule is refused with `ERR_CHAMBER_WINDOW_CONFLICT`. Rescheduling a charge that is not `DISPLACED` — one that is still merely `SCHEDULED`, for instance — is rejected with `ERR_CHARGE_STATE_INVALID`. `CLOSED` is the charge lifecycle's terminal state, reached when the last of its kiln-dry volume has been drawn into flooring lots.

### 3.4. Building a Charge: Allocation, Moisture Weighting and Loading

Allocation is how green volume enters a charge. A `KilnOperator` or `MillAdmin` names a `green_receipt_id` in the payload, and the receipt moves from `ACCEPTED` to `ALLOCATED` with its `kiln_charge_id` set to the target charge. Three preconditions guard the move: the charge must be in `SCHEDULED` status, or the request is refused with `ERR_CHARGE_STATE_INVALID`; the receipt's species must be the same species as the charge's governing schedule, or the request is refused with `ERR_SPECIES_MISMATCH`; and the charge's `charged_green_bf` after adding this receipt's `accepted_board_feet` must not exceed the chamber's `capacity_board_feet`, or the request is refused with `ERR_CHAMBER_CAPACITY_EXCEEDED`. A receipt that is still `RECEIVED`, or already `CONSUMED`, cannot be allocated and yields `ERR_RECEIPT_STATE_INVALID`.

Every allocation and deallocation recomputes two derived quantities on the charge from the set of receipts currently pointing at it in `ALLOCATED` status. The first, `charged_green_bf`, is the plain total of their `accepted_board_feet`. The second, `weighted_initial_moisture_pct`, is the volume-weighted green moisture of the load: each receipt's `accepted_board_feet` is multiplied by its `moisture_pct_at_receipt`, those products are totalled, the total is divided by `charged_green_bf`, and the resulting ratio is rounded half up to one decimal place — once, on the aggregate, never per receipt. A charge holding 5800 board feet at 46.0 percent and 3900 board feet at 44.0 percent therefore carries 9700 charged board feet and a weighted moisture of 45.2 percent, since 438400 divided by 9700 is 45.195. When the allocated set is empty, `charged_green_bf` is 0 and `weighted_initial_moisture_pct` is null.

Deallocation is the exact inverse. Naming an allocated `green_receipt_id` returns that receipt from `ALLOCATED` to `ACCEPTED`, clears its `kiln_charge_id`, and recomputes both derived quantities from the receipts that remain. It is permitted while the owning charge is in either `SCHEDULED` or `DISPLACED` status — a displaced charge must be able to give its wood back before it is rescheduled — and is refused with `ERR_CHARGE_STATE_INVALID` otherwise. Deallocating a receipt that is not currently allocated yields `ERR_RECEIPT_STATE_INVALID`.

Loading is reserved to a `KilnOperator` and advances the charge from `SCHEDULED` to `LOADED`. Three things must hold. The chamber must be `AVAILABLE` and must have no other charge on it in `LOADED`, `DRYING`, `CONDITIONING` or `REDRY` status, or the load is refused with `ERR_CHAMBER_STATE_INVALID`. The charge must hold some wood — a `charged_green_bf` of 0 cannot be loaded and is refused with `ERR_CHARGE_STATE_INVALID`, as is any attempt to load a `DISPLACED` charge. And the load's actual green moisture must be one the schedule was designed for: the absolute difference between the charge's `weighted_initial_moisture_pct` and the schedule's `initial_moisture_pct`, compared at one decimal place, may be at most 3.0 percentage points, or the load is refused with `ERR_MC_PLAN_DEVIATION`. Against a schedule designed for 45.0 percent, a weighted 45.2 deviates by 0.2 and passes; a weighted 38.6 deviates by 6.4 and fails.

A successful load has two cascades. The chamber moves from `AVAILABLE` to `OCCUPIED`, and every receipt allocated to the charge moves from `ALLOCATED` to `CONSUMED`, freezing its `accepted_board_feet` and its `kiln_charge_id` against any further allocation change — a consumed receipt can no longer be deallocated.

### 3.5. Drying, Conditioning and the Stress Test

The drying legs themselves are simple state advances driven by a `KilnOperator` and carry no payload: the charge moves from `LOADED` to `DRYING` when the drying leg begins, and from `DRYING` to `CONDITIONING` when equalisation and conditioning begin. Attempting either out of order is refused with `ERR_CHARGE_STATE_INVALID`.

The stress test is where the charge's fate is decided, and it is the single most consequential operation in the kiln shed. A `KilnOperator` records a `shell_moisture_pct` and a `core_moisture_pct` on a charge in `CONDITIONING` status; recording it in any other status is refused with `ERR_CHARGE_STATE_INVALID`. Both readings are stored, and two derived figures follow: `moisture_gradient_pp` is the absolute difference between the core and shell readings, rounded half up to one decimal place, and `average_moisture_pct` is the mean of the two readings, likewise rounded half up to one decimal place. The charge is released when the gradient is at most the species' `max_moisture_gradient_pp` **and** the absolute difference between `average_moisture_pct` and the species' `target_moisture_pct` is at most 1.0 percentage point; otherwise the charge goes back for redry. With a species capped at a 2.0-point gradient and targeting 7.0 percent: a shell of 6.4 against a core of 8.2 gives a gradient of 1.8 and an average of 7.3, and releases; a shell of 6.0 against a core of 8.0 gives a gradient of exactly 2.0, which is still within the cap and releases; a shell of 5.9 against a core of 8.0 gives 2.1 and does not.

On the release branch the charge moves from `CONDITIONING` to `RELEASED`. The stored readings and both derived figures are retained, and the charge's kiln-dry output is computed: `dry_bf_out` is `charged_green_bf` reduced by the species' `green_to_dry_shrink_pct` — that is, multiplied by one minus that percentage expressed as a fraction — and rounded half up to two decimal places. `remaining_dry_bf` is initialised to the same value, since no lot has yet drawn from the charge. A charge holding 9700 green board feet of a `DENSE` species yields 8972.50 kiln-dry board feet. The chamber the charge occupied moves from `OCCUPIED` back to `AVAILABLE`, free for the next load.

On the redry branch the charge moves from `CONDITIONING` to `REDRY`. The readings and derived figures are stored exactly as on the release branch, `redry_count` is incremented, `planned_end_utc` is advanced by a further 48 hours, and `blocked_until_utc` is recomputed from the new end plus the same 6-hour cooldown buffer. Because the charge now holds its chamber longer, the extension is allowed to displace others: every `SCHEDULED` charge on the same chamber whose occupancy interval now overlaps the extended interval moves to `DISPLACED` with a `displaced_reason` recorded, and each displaced charge gives its wood back — every `ALLOCATED` receipt on it returns to `ACCEPTED` with a cleared `kiln_charge_id`, and the displaced charge's `charged_green_bf` becomes 0 with a null `weighted_initial_moisture_pct`. A charge may be sent back for redry at most twice; a failing stress test on a charge whose `redry_count` already stands at 2 is refused with `ERR_REDRY_LIMIT_EXCEEDED`, leaving the charge in `CONDITIONING`.

A redrying charge returns to the conditioning phase when a `KilnOperator` resumes it, moving it from `REDRY` back to `CONDITIONING` and clearing all four stress-test figures — `shell_moisture_pct`, `core_moisture_pct`, `moisture_gradient_pp` and `average_moisture_pct` — so that the next test starts from a clean slate. The cycle may then repeat within the redry allowance.

### 3.6. Milling a Lot: Dimensional Planning, Mass Balance and Byproducts

A milling lot converts kiln-dry lumber into tongue-and-groove flooring for one product line. A `MillSupervisor` or `MillAdmin` plans one by supplying the `product_line_id` being produced, the `kiln_charge_id` of the released charge that will supply the lumber, the `input_dry_bf` volume to be drawn, and — for engineered lines only — the `core_stock_id` of the substrate. The charge must be in `RELEASED` status, or the request is refused with `ERR_CHARGE_STATE_INVALID`, and the requested draw may not exceed the charge's `remaining_dry_bf`, or it is refused with `ERR_CHARGE_DRY_BF_EXCEEDED`. The lot snapshots the line's `construction_type` and `nominal_width_in` so that later configuration changes cannot rewrite history, and opens in `PLANNED` status.

Construction type decides the substrate rules, and the two branches are strictly symmetric. An `ENGINEERED` lot must name a `core_stock_id`; omitting it is refused with `ERR_CORE_STOCK_REQUIRED`. A `SOLID` lot must not name one; supplying it is refused with `ERR_CORE_STOCK_NOT_ALLOWED`. Where core stock is named it must belong to the same product line as the lot, or the request is refused with `ERR_CORE_STOCK_LINE_MISMATCH`. For an engineered lot the server computes `reserved_core_sf` as the drawn `input_dry_bf` multiplied by 1.10 square feet of core per board foot, rounded half up to two decimal places — a draw of 2900 board feet reserves 3190.00 square feet — and adds it to the core stock's `reserved_square_feet`, which is at all times the total `reserved_core_sf` of the non-voided lots on that stock. The reservation is refused with `ERR_CORE_STOCK_INSUFFICIENT` when the stock's `reserved_square_feet` including this new reservation would exceed its `available_square_feet`. A `SOLID` lot carries a null `reserved_core_sf`.

Moisture planning happens at the same moment, because a board milled to its nominal width will not stay that width. The lot's reference moisture is the supplying charge's `average_moisture_pct`, falling back to the species' `target_moisture_pct` when the charge has no recorded average. Against an assumed in-service moisture content of 7.5 percent, the expected movement is the lot's `nominal_width_in` multiplied by the species' `tangential_shrinkage_coefficient`, multiplied by the absolute difference between the lot's reference moisture and 7.5, then divided by 100 and rounded half up to four decimal places; that figure is stored as `dimensional_growth_allowance_in`. The `planned_finished_width_in` then starts from `nominal_width_in`, subtracts a mill kerf allowance of 0.0625 inch, and — when the lot's reference moisture is below 7.5 percent, so the boards will take up moisture and widen in service — adds the movement; when the reference moisture is at or above 7.5 percent, so the boards will give up moisture and narrow in service, it subtracts the movement instead. The result is rounded half up to three decimal places, and the two roundings happen in that order: movement first to four places, then the planned width to three. A 3.250-inch nominal face on a species with a coefficient of 0.145 dried to 7.3 percent moves 0.0009 inch and plans to 3.188 inches; the same face at 7.0 percent moves 0.0024 inch and plans to 3.190 inches.

Planning a lot draws down the charge: the charge's `remaining_dry_bf` is reduced by `input_dry_bf`, and it is always `dry_bf_out` less the total `input_dry_bf` of the non-voided lots drawn from that charge. When that remainder reaches exactly 0 the charge has nothing left to give and auto-advances from `RELEASED` to `CLOSED`. Lots may be listed filtered by `product_line_id`, `kiln_charge_id`, `core_stock_id`, `final_grade_run_id` or `status`.

Milling completion is reserved to a `MillSupervisor` and takes the lot from `PLANNED` to `MILLED`. Its payload reports the measured `actual_milled_width_in` face width, the `net_flooring_bf` of full-length flooring produced, the `shorts_bf` diverted to shorts, and the `sawdust_tons` and `shavings_tons` captured at the moulder. The first check is dimensional: the absolute difference between `actual_milled_width_in` and `planned_finished_width_in` may be at most 0.006 inch, or the report is refused with `ERR_PROFILE_TOLERANCE_EXCEEDED`. Against a planned 3.188 inches, an actual 3.190 sits 0.002 inside tolerance and passes, an actual 3.194 sits exactly at 0.006 and still passes, and an actual 3.195 exceeds it and fails.

The mass balance follows. `residue_bf` is the board-foot equivalent of the residue streams: the sum of `sawdust_tons` and `shavings_tons` multiplied by 285 board feet per ton, rounded half up to two decimal places. `waste_bf` is then the unaccounted remainder — `input_dry_bf` less `net_flooring_bf`, less `shorts_bf`, less `residue_bf` — likewise rounded half up to two decimal places, with residue computed before waste. A negative `waste_bf` means the lot reported more output than it consumed and is refused with `ERR_MILL_MASS_BALANCE_VIOLATION`. A `waste_bf` above 12 percent of `input_dry_bf`, that ceiling itself rounded half up to two decimal places, is refused with `ERR_WASTE_LIMIT_EXCEEDED`. A lot drawing 6000 board feet that reports 4680 net, 180 in shorts, 1.20 tons of sawdust and 0.80 tons of shavings yields 570.00 residue board feet and 570.00 waste board feet against a ceiling of 720.00, and is accepted. The provisional yield is recorded at the same time: `provisional_yield_pct` is `net_flooring_bf` divided by `input_dry_bf`, expressed as a percentage and rounded half up to two decimal places — 78.00 percent in that example.

Milling completion also opens the byproduct ledger. Three batches are created against the lot, one per stream, each with its `byproduct_type` set to `SAWDUST`, `SHAVINGS` and `SHORTS` respectively, `sold_tons` at 0, and `available_tons` fixed once from the milling report: the sawdust batch takes `sawdust_tons`, the shavings batch takes `shavings_tons`, and the shorts batch takes `shorts_bf` divided by the same 285 board feet per ton, rounded half up to two decimal places. Batches are never created directly and are read-only thereafter, listable filtered by `flooring_lot_id` or `byproduct_type`.

A `ByproductBroker` or `MillAdmin` sells from a batch by naming the `byproduct_batch_id`, the `buyer_name` of record, the `quantity_tons` sold, the `unit_price_cents_per_ton` agreed, and the `haul_distance_miles` billed to the buyer. The invoice is built in a fixed order, each amount rounded half up to whole cents: `gross_cents` is `quantity_tons` multiplied by `unit_price_cents_per_ton`; `discount_cents` applies a volume discount of nothing below 5 tons, 3 percent from 5 tons up to but not including 20 tons, and 6 percent at 20 tons and above, taken against the gross; `haul_cents` is a flat 2500 cents plus 180 cents per mile of `haul_distance_miles`; and `net_cents` is the gross less the discount plus the haulage. Five tons at 2200 cents per ton over 20 miles gives a gross of 11000, a discount of 330, haulage of 6100 and a net of 16770; the same sale at 4.99 tons falls below the first tier and gives a gross of 10978, no discount, the same 6100 haulage and a net of 17078. The batch's `sold_tons` is at all times the total `quantity_tons` of the sales recorded against it, and a sale whose quantity would push `sold_tons` above the batch's `available_tons` is refused with `ERR_BYPRODUCT_QUANTITY_EXCEEDS_BATCH`. Sales may be listed filtered by `byproduct_batch_id`.

Voiding is the compensating operation for a lot, available to a `MillSupervisor` or `MillAdmin` from either `PLANNED` or `MILLED` and taking the lot to the terminal `VOIDED` state with the supplied `void_reason` recorded. A void unwinds every reservation the lot made: for an `ENGINEERED` lot the `reserved_core_sf` is released back so that the core stock's `reserved_square_feet` no longer counts it; the lot's `input_dry_bf` is restored to the supplying charge's `remaining_dry_bf`, and a charge that had been auto-closed returns from `CLOSED` to `RELEASED`; and for a lot already `MILLED`, every byproduct batch of the lot has its `available_tons` set to 0. That last cascade is only safe while nothing has been sold, so a `MILLED` lot with any byproduct sale recorded against any of its batches may not be voided and is refused with `ERR_BYPRODUCT_SALE_EXISTS`. Voiding a lot that has already reached `GRADED`, `QUARANTINED` or `VOIDED` is refused with `ERR_LOT_STATE_INVALID`.

### 3.7. Grading, Tally Valuation and Lot Closeout

Grading is owned by the `GradeInspector`. Opening a grading pass names the `flooring_lot_id` being graded, the `inspector_ruleset` under which it will be judged, and the `expected_lot_version` of §2.5. Only a lot in `MILLED` status may be graded, and a lot in any other status is refused with `ERR_LOT_STATE_INVALID`. Two rulesets exist: `NHLA`, the plain industry rules, and `MILL_CHARACTER`, which permits character grade separation. A new run opens in `DRAFT` status with null tallies, and runs may be listed filtered by `flooring_lot_id`, `superseded_by_run_id` or `status`.

Bundles are then tallied onto the draft run, one line at a time, each carrying a `grade_class` of `CLEAR`, `SELECT`, `NO1_COMMON`, `NO2_COMMON`, `CHARACTER` or `CABIN`, the `bundle_board_feet` in the bundle, and the `average_length_in` average board length in inches. Bundles may only be added to a run in `DRAFT`; adding to a `FINALIZED` or `SUPERSEDED` run is refused with `ERR_GRADE_RUN_STATE_INVALID`. `CHARACTER` and `CABIN` bundles are permitted only under the `MILL_CHARACTER` ruleset and are refused on an `NHLA` run with `ERR_CHARACTER_GRADE_NOT_PERMITTED`. And a run may never tally more flooring than the lot produced: if the total `bundle_board_feet` across the run's bundles including the new one would exceed the lot's `net_flooring_bf`, the bundle is refused with `ERR_BUNDLE_BF_EXCEEDS_LOT`.

Each accepted bundle is priced and credited on the spot. Its `length_factor` is selected by average length: 0.83 for bundles averaging under 24 inches, 1.00 for bundles averaging at least 24 but under 48 inches, and 1.07 for bundles averaging 48 inches or more. Its `credit_factor` is selected by grade class: 1.00 for `CLEAR`, 0.95 for `SELECT`, 0.85 for `NO1_COMMON`, 0.70 for `NO2_COMMON`, 0.60 for `CHARACTER` and 0.40 for `CABIN`. Its `tally_value_cents` is the bundle's board feet multiplied by the per-board-foot price of its grade class — 640 cents for `CLEAR`, 520 for `SELECT`, 395 for `NO1_COMMON`, 280 for `NO2_COMMON`, 240 for `CHARACTER` and 150 for `CABIN` — multiplied by the length factor, and rounded half up to whole cents. Bundles are immutable tally lines: they carry no revision counter and are never edited or deleted. They may be read individually and listed either within their run or across runs, filtered by `grade_run_id` or `grade_class`.

Finalizing a run turns those lines into the run's tally and moves it from `DRAFT` to `FINALIZED`. Three preconditions apply: the run must carry at least one bundle, or it is refused with `ERR_NO_GRADE_BUNDLES`; the total bundle board feet must not exceed the lot's `net_flooring_bf`, or it is refused with `ERR_BUNDLE_BF_EXCEEDS_LOT`; and no `CHARACTER` or `CABIN` bundle may be present when the run's ruleset is `NHLA`, or it is refused with `ERR_CHARACTER_GRADE_NOT_PERMITTED`. Finalization then computes three figures. `tally_board_feet` is the total `bundle_board_feet` of the run's bundles, rounded half up to two decimal places. `credited_board_feet` is the total of each bundle's board feet multiplied by that bundle's credit factor, rounded half up to four decimal places. `tally_value_cents` is the exact integer sum of the bundles' already-rounded `tally_value_cents` values — the run total is never recomputed from unrounded bundle values, and the difference is real: a run of a `CLEAR` bundle of 1187.25 board feet averaging 50 inches (813029 cents), a `SELECT` bundle of 1502.60 at 36 inches (781352), a `NO1_COMMON` bundle of 1098.45 at 30 inches (433888) and a `CHARACTER` bundle of 703.10 at 20 inches (140058) totals 2168327 cents, where summing the unrounded values and rounding once would give 2168326.

A finalized run can be replaced when the grading is re-done. Superseding names a `replacement_grade_run_id`, which must exist, must belong to the same lot as the run being superseded — otherwise `ERR_GRADE_RUN_LOT_MISMATCH` — and must itself be in `FINALIZED` status. The run being superseded must also be `FINALIZED`, and it must not already be the run the lot was closed out against; a run that is still `DRAFT`, or one whose lot has already reached `GRADED` or `QUARANTINED` against it, is refused with `ERR_GRADE_RUN_STATE_INVALID`. On success the run records its `superseded_by_run_id` and moves to the terminal `SUPERSEDED` status. A `GradeInspector` or a `MillAdmin` may supersede.

Closing out a lot is the moment the provisional yield is replaced by the real one, and either a `MillSupervisor` or a `GradeInspector` may do it. The payload names the `grade_run_id` to close against; that run must be in `FINALIZED` status, or the request is refused with `ERR_GRADE_RUN_STATE_INVALID`, and it must belong to this lot, or it is refused with `ERR_GRADE_RUN_LOT_MISMATCH`. Only a `MILLED` lot may be closed out. The lot's `final_yield_pct` is the run's `credited_board_feet` divided by the lot's `input_dry_bf`, expressed as a percentage and rounded half up to two decimal places, and `final_grade_run_id` records the closing run. The branch then follows the yield floor of 55.00 percent: at or above the floor the lot moves from `MILLED` to `GRADED`; below it the lot moves from `MILLED` to `QUARANTINED` and a `quarantine_reason` is recorded. Both branches set `final_grade_run_id` and `final_yield_pct` identically; only the state and the quarantine note differ. A lot that milled 6000 board feet into 4680 net had a `provisional_yield_pct` of 78.00; credited at 3970.2625 board feet its `final_yield_pct` is 66.17 and it grades out, while a character-heavy run crediting only 2200.0000 board feet gives 36.67 and quarantines it. The provisional figure is never overwritten — it remains the milling record — and only the final figure decides the branch.

A computed read exposes both variants side by side for a lot, returning its `flooring_lot_id`, the `input_dry_bf` drawn, the `net_flooring_bf` milled, the `residue_bf` and `waste_bf` from the mass balance, the `provisional_yield_pct` and `final_yield_pct` variants, a `yield_delta_pp` giving the final yield less the provisional yield in percentage points rounded half up to two decimal places, and the `yield_floor_pct` of 55.00 in force. `yield_delta_pp` is null while `final_yield_pct` is still null.

### 3.8. Prefinishing: Window Loading, Coating and Posture Holds

Prefinishing is scheduled by a `PrefinishScheduler` or `MillAdmin` against a graded lot. The payload names the `prefinish_line_id` that will execute the run and the `flooring_lot_id` to be finished, the `window_start_utc` and `window_end_utc` bounding the half-open window, the `scheduled_linear_feet` to be pushed through, the ordered `sanding_grit_sequence` such as `80-120-150`, and an optional `stain_code` which is null for a natural finish. Only a lot in `GRADED` status may be scheduled; a `PLANNED`, `MILLED`, `QUARANTINED` or `VOIDED` lot is refused with `ERR_LOT_NOT_GRADED`. The lot's product line must be in `OPEN` posture, or the request is refused with `ERR_PRODUCT_LINE_POSTURE_BLOCKED`. The window must satisfy the shape rules of §2.9 or be refused with `ERR_PREFINISH_WINDOW_INVALID`.

Line loading is an aggregate constraint rather than an exclusive one. The runs that matter are those on the same prefinish line whose status is `SCHEDULED`, `HELD` or `RUNNING` and whose half-open window intersects the candidate's. Their `scheduled_linear_feet` are totalled, the candidate's own footage is added, and the result must be at most the line's `daily_capacity_linear_feet`, or the request is refused with `ERR_PREFINISH_CAPACITY_EXCEEDED`. On a line with a capacity of 9000 linear feet already carrying a run from 06:00 to 14:00 at 5000 linear feet, a candidate from 13:00 to 14:00 at 4000 linear feet totals exactly 9000 and is accepted, the same candidate at 4001 is refused, and a candidate from 14:00 to 22:00 at 5000 linear feet does not overlap at all and is accepted.

A new run snapshots its `product_line_id` from the lot — this is what later posture changes are matched against — opens in `SCHEDULED` status with a null `hold_reason`, and has its coating demand computed. The square footage passing through the line is `scheduled_linear_feet` multiplied by the lot's `actual_milled_width_in` and divided by 12, and `coating_liters` is that square footage multiplied by 0.012 litres per square foot and by the line's number of `coating_passes`, rounded half up to two decimal places once at the very end — the square footage is not pre-rounded. Pushing 5000 linear feet of 3.190-inch boards through a three-pass line therefore consumes 47.85 litres. Runs may be listed filtered by `prefinish_line_id`, `flooring_lot_id`, `product_line_id` or `status`.

Posture is what stops the line. When a product line's posture becomes `RESTRICTED` or `FROZEN`, every `SCHEDULED` run whose snapshotted `product_line_id` matches that line moves to `HELD` with a `hold_reason` recorded. Held runs do not resume by themselves: even after the line's posture returns to `OPEN`, a held run stays `HELD` until someone explicitly releases it. Releasing a hold moves the run from `HELD` back to `SCHEDULED` and clears `hold_reason`, and requires the product line's posture to be `OPEN` at that moment, or the release is refused with `ERR_PRODUCT_LINE_POSTURE_BLOCKED`. Releasing a run that is not `HELD` is refused with `ERR_PREFINISH_RUN_STATE_INVALID`.

Starting a run is reserved to a `PrefinishScheduler` and advances it from `SCHEDULED` to `RUNNING`; it too requires the product line's posture to be `OPEN`, refusing a restricted or frozen line with `ERR_PRODUCT_LINE_POSTURE_BLOCKED`, and it requires the run's lot to still stand in `GRADED` status, which is otherwise refused with `ERR_LOT_NOT_GRADED`. Starting a `HELD` run is refused with `ERR_PREFINISH_RUN_STATE_INVALID`. Completing a run advances it from `RUNNING` to the terminal `COMPLETED`; completing a run that is not `RUNNING` is refused with `ERR_PREFINISH_RUN_STATE_INVALID`.

### 3.9. Warranty Reserve, Claim Adjudication and Remediation

A product line's gating posture is not stored as an editable attribute; it is derived, every time the reserve moves or the freeze flag changes, from two inputs. The line's `warranty_balance_cents` is its `warranty_funded_total_cents` less its `warranty_committed_cents`. The `posture` is then `FROZEN` whenever `freeze_override` is true, regardless of money; otherwise it is `RESTRICTED` when `warranty_balance_cents` is below the restriction floor of 500000 cents; and otherwise it is `OPEN`. A line funded with 600000 cents that commits 151474 to an approved claim has a balance of 448526, which is under the floor and makes it `RESTRICTED`; funding a further 100000 cents lifts the balance to 548526 and returns it to `OPEN`.

A `MillAdmin` funds a reserve by supplying an `amount_cents` to add, which increases both `warranty_funded_total_cents` and `warranty_balance_cents` before the posture is recomputed — the path by which a `RESTRICTED` line returns to `OPEN`. The same role may administratively freeze a line with a supplied `freeze_reason`, which sets `freeze_override` to true and forces the posture to `FROZEN` from either `OPEN` or `RESTRICTED`; when the line was `OPEN`, the freeze also holds every `SCHEDULED` prefinish run on it, whereas a line that was already `RESTRICTED` has held those runs already. Unfreezing clears `freeze_override` and lets the posture fall back to the money: the line becomes `OPEN` when `warranty_balance_cents` is at least 500000 and `RESTRICTED` when it is below that floor.

Claims arrive from the field. A `WarrantyAdjudicator` or `MillAdmin` files one against a `product_line_id`, optionally naming the installed `flooring_lot_id` when it is traceable, with a `claim_type` of `CUPPING` or `GAPPING`, the `affected_square_feet` claimed, the `installation_date`, and the installation conditions the claimant reports: `subfloor_moisture_pct_at_install` and `ambient_rh_pct_at_install`. Three temporal and volume guards apply at intake. The installation date may not be after the current logical date, or the claim is refused with `ERR_INSTALL_DATE_IN_FUTURE`. A claim may not be filed more than 60 whole months after installation, or it is refused with `ERR_WARRANTY_PERIOD_EXPIRED`. And a single product line may not carry more than three claims at once in `SUBMITTED` or `INFO_REQUESTED` status; a fourth is refused with `ERR_TOO_MANY_OPEN_CLAIMS`. A new claim captures `submitted_by_user_id` from the acting `X-User-ID`, opens with an adjudication status of `SUBMITTED` and a remediation status of `NOT_STARTED`, and carries a null `adjudicated_by_user_id`, `info_request_note`, `denial_reason` and `reversal_reason`. Claims may be listed filtered by `product_line_id`, `flooring_lot_id`, `adjudication_status` or `remediation_status`.

Intake also computes an estimate, `estimated_liability_cents`, from the claimant's own figures, in four pinned steps each rounded half up to whole cents. First, a base is the `affected_square_feet` multiplied by the sum of the line's `material_value_cents_per_sf` and a remediation labour allowance of 475 cents per square foot. Second, an administrative rate is selected by that base: 8 percent while the base is below 500000 cents, 6 percent while it is at most 1500000 cents, and 4.5 percent above that. Third, the administrative amount is the base multiplied by that rate. Fourth, the estimate is the base plus the administrative amount. On a line whose material value is 895 cents per square foot, a claim of 240 square feet gives a base of 328800, an administrative amount of 26304 and an estimate of 355104 cents. This figure is informational only — it never touches the reserve.

Two moves are available before adjudication. A `WarrantyAdjudicator` may request further information, moving the claim from `SUBMITTED` to `INFO_REQUESTED` and recording the supplied `info_request_note`. The claimant's corrected figures then come back through a resubmission, which moves the claim from `INFO_REQUESTED` back to `SUBMITTED`, overwrites `affected_square_feet`, `subfloor_moisture_pct_at_install` and `ambient_rh_pct_at_install` with the supplied values, recomputes `estimated_liability_cents` from them by the same four steps, and clears `info_request_note`. Either move out of the wrong state — resubmitting a claim that is not `INFO_REQUESTED`, for instance — is refused with `ERR_CLAIM_STATE_INVALID`.

Adjudication is reserved to a `WarrantyAdjudicator` and takes a `decision` of `APPROVED` or `DENIED` together with the inspector-verified figures: `adjudicated_affected_sf`, `adjudicated_subfloor_moisture_pct` and `adjudicated_ambient_rh_pct`, plus an optional `denial_reason`. Only a claim in `SUBMITTED` status may be adjudicated; an `INFO_REQUESTED` claim or one already decided is refused with `ERR_CLAIM_STATE_INVALID`. The acting `X-User-ID` must differ from the claim's `submitted_by_user_id`, as described in §2.1. The verified area may not exceed the area claimed, or the request is refused with `ERR_ADJUDICATED_SF_EXCEEDS_CLAIM`. In both branches the inspector-verified readings are stored on the claim and `adjudicated_by_user_id` records the deciding user.

On the `DENIED` branch the claim moves from `SUBMITTED` to the terminal `DENIED` status, the supplied `denial_reason` is recorded, and the warranty reserve is left entirely untouched — `installer_share_pct`, `mill_share_pct`, `service_months`, `depreciation_pct` and `adjudicated_liability_cents` all stay null, and the line's posture does not move.

On the `APPROVED` branch the mill first decides how much of the failure is its own. The reference moisture for that judgment is the average moisture content of the kiln charge behind the claim's installed lot when a `flooring_lot_id` was given, and the species' `target_moisture_pct` when it was not. The moisture delta is the absolute difference between `adjudicated_subfloor_moisture_pct` and that reference, rounded half up to one decimal place, and it selects the `installer_share_pct` in whole percentages: 0 when the delta is at most 2.0 points, 40 when it is above 2.0 but at most 4.0, 70 when it is above 4.0 but at most 6.0, and 100 when it is above 6.0. Ambient conditions add a penalty: when `adjudicated_ambient_rh_pct` falls outside the range 30 to 50 percent inclusive, the installer share is increased by 10 percentage points, capped at 100. The `mill_share_pct` is then 100 less the installer share. A reference of 7.3 percent against a verified subfloor of 10.5 gives a delta of 3.2 and an installer share of 40; a verified ambient relative humidity of 62 percent lies outside the band and lifts the installer share to 50, leaving the mill share at 50.

The adjudicated charge is then built in six pinned steps, each rounded half up to whole cents, none of which may be collapsed into another. Step one takes a base of `adjudicated_affected_sf` multiplied by the sum of the line's `material_value_cents_per_sf` and the same 475-cent remediation labour allowance. Step two selects the administrative rate from that base by the same tiers used at intake — 8 percent below 500000 cents, 6 percent at or below 1500000, 4.5 percent above. Step three computes the administrative amount as the base multiplied by that rate. Step four sums the two into a gross. Step five ages the claim: `service_months` is the number of whole months from `installation_date` to the current logical date, `depreciation_pct` is 0.5 percentage points per whole month of service capped at 40 percent, and the depreciated amount is the gross multiplied by one less that depreciation expressed as a fraction. Step six applies responsibility: `adjudicated_liability_cents` is the depreciated amount multiplied by `mill_share_pct` and divided by 100. A verified 210 square feet on the same 895-cent line gives a base of 287700, an administrative amount of 23016 and a gross of 310716; installed on 2026-03-15 and adjudicated on 2026-08-20 the claim has 5 months of service and 2.5 percent depreciation, giving 302948; at a mill share of 50 percent the charge is 151474 cents.

The line's reserve must cover that charge: when `adjudicated_liability_cents` exceeds the line's `warranty_balance_cents`, the approval is refused with `ERR_WARRANTY_RESERVE_INSUFFICIENT` and nothing moves. Otherwise the claim advances from `SUBMITTED` to `APPROVED`, the charge is debited from `warranty_balance_cents` and credited to `warranty_committed_cents`, and the line's posture is recomputed. When that recomputation leaves the line `RESTRICTED` or `FROZEN`, every `SCHEDULED` prefinish run on the line moves to `HELD` as described in §3.8 — this is the intended serialization point between warranty exposure and further production on the affected line.

Reversal is the compensating operation, available to a `WarrantyAdjudicator` or `MillAdmin` with a supplied `reversal_reason`. It moves an `APPROVED` claim to the terminal `REVERSED` status, credits `warranty_balance_cents` and debits `warranty_committed_cents` by exactly the `adjudicated_liability_cents` the approval moved, and recomputes the line's posture; runs that were held remain `HELD` until released explicitly, even when the posture returns to `OPEN`. A reversal also cancels the remediation dimension: a remediation status of `NOT_STARTED` or `IN_PROGRESS` moves to `CANCELLED`. Work that has already finished cannot be unwound, so a claim whose remediation status is `COMPLETED` may not be reversed and is refused with `ERR_CLAIM_STATE_INVALID`, as is any attempt to reverse a claim that is not `APPROVED`.

Remediation runs on its own dimension, independent of adjudication, and may be driven by a `WarrantyAdjudicator` or a `MillSupervisor`. Starting remediation moves the claim's remediation status from `NOT_STARTED` to `IN_PROGRESS`, and completing it moves that status from `IN_PROGRESS` to `COMPLETED`; both require the claim's adjudication status to be `APPROVED`, and both are refused with `ERR_CLAIM_STATE_INVALID` when either dimension is in the wrong state — remediating an unapproved claim, starting work already in progress, or completing work never started.

## 4. Endpoint Definitions

The table below is the complete HTTP surface. Endpoints that mint a new resource answer with 201 Created; every other successful call — retrievals, state transitions, computed reads and the logical clock — answers with 200 OK. The request and response payloads are not repeated here: the fields each operation accepts, the order in which its checks run, and the cascades it triggers are specified in §2 and §3, and the narrative there is the contract. Where the authorized roles column reads "All roles", every one of the eight working roles named in §2.1 may call the endpoint.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/_clock/set_current_utc` | Test-driving endpoint: sets the logical clock used for warranty age, service months and future-date checks. Default logical clock is 2026-08-01T00:00:00Z. | All roles |
| POST | `/mill/species-profiles` | Register a wood species profile. | `MillAdmin` |
| GET | `/mill/species-profiles/{species_profile_id}` | Fetch one species profile. | All roles |
| GET | `/mill/species-profiles` | List species profiles. | All roles |
| POST | `/mill/drying-schedules` | Create a kiln drying schedule for one species and thickness. Optimistically concurrent on the species profile. | `MillAdmin`, `KilnOperator` |
| GET | `/mill/drying-schedules/{drying_schedule_id}` | Fetch one drying schedule. | All roles |
| GET | `/mill/drying-schedules` | List drying schedules, optionally by species profile. | All roles |
| POST | `/mill/green-receipts` | Record an inbound green lumber or log receipt. | `ProcurementClerk`, `MillAdmin` |
| GET | `/mill/green-receipts/{green_receipt_id}` | Fetch one green receipt. | All roles |
| GET | `/mill/green-receipts` | List green receipts, optionally by species, allocated charge or status. | All roles |
| POST | `/mill/green-receipts/{green_receipt_id}/accept` | Accept a receipt with its scaled board footage. | `ProcurementClerk`, `MillAdmin` |
| POST | `/mill/green-receipts/{green_receipt_id}/reject` | Reject a receipt at the receiving deck. | `ProcurementClerk`, `MillAdmin` |
| POST | `/mill/kiln-chambers` | Register a kiln chamber. | `MillAdmin` |
| GET | `/mill/kiln-chambers/{kiln_chamber_id}` | Fetch one kiln chamber. | All roles |
| GET | `/mill/kiln-chambers` | List kiln chambers. | All roles |
| POST | `/mill/kiln-chambers/{kiln_chamber_id}/start_maintenance` | Take a chamber out of service for maintenance. | `KilnOperator`, `MillAdmin` |
| POST | `/mill/kiln-chambers/{kiln_chamber_id}/complete_maintenance` | Return a chamber to service. | `KilnOperator`, `MillAdmin` |
| POST | `/mill/kiln-charges` | Schedule a kiln charge in a chamber against a drying schedule. | `KilnOperator`, `MillAdmin` |
| GET | `/mill/kiln-charges/{kiln_charge_id}` | Fetch one kiln charge. | All roles |
| GET | `/mill/kiln-charges` | List kiln charges, optionally by schedule, chamber or status. | All roles |
| POST | `/mill/kiln-charges/{kiln_charge_id}/allocate_receipt` | Allocate an accepted receipt to a scheduled charge. | `KilnOperator`, `MillAdmin` |
| POST | `/mill/kiln-charges/{kiln_charge_id}/deallocate_receipt` | Remove an allocated receipt from a charge. | `KilnOperator`, `MillAdmin` |
| POST | `/mill/kiln-charges/{kiln_charge_id}/load` | Load the charge into its chamber. | `KilnOperator` |
| POST | `/mill/kiln-charges/{kiln_charge_id}/start_drying` | Begin the drying leg. | `KilnOperator` |
| POST | `/mill/kiln-charges/{kiln_charge_id}/begin_conditioning` | Begin equalisation and conditioning. | `KilnOperator` |
| POST | `/mill/kiln-charges/{kiln_charge_id}/record_stress_test` | Record the shell and core moisture readings, releasing the charge or sending it back for redry. | `KilnOperator` |
| POST | `/mill/kiln-charges/{kiln_charge_id}/resume_conditioning` | Return a redrying charge to conditioning. | `KilnOperator` |
| POST | `/mill/kiln-charges/{kiln_charge_id}/reschedule` | Reschedule a displaced charge into a free window. | `KilnOperator`, `MillAdmin` |
| POST | `/mill/product-lines` | Create a solid or engineered product line with its warranty reserve. | `MillAdmin` |
| GET | `/mill/product-lines/{product_line_id}` | Fetch one product line. | All roles |
| GET | `/mill/product-lines` | List product lines, optionally by species or posture. | All roles |
| POST | `/mill/product-lines/{product_line_id}/fund_warranty` | Add funds to the warranty reserve of a product line. | `MillAdmin` |
| POST | `/mill/product-lines/{product_line_id}/freeze` | Administratively freeze a product line. | `MillAdmin` |
| POST | `/mill/product-lines/{product_line_id}/unfreeze` | Lift an administrative freeze; posture falls back to the reserve-derived value. | `MillAdmin` |
| POST | `/mill/core-stocks` | Register engineered core material inventory for a product line. | `MillAdmin`, `MillSupervisor` |
| GET | `/mill/core-stocks/{core_stock_id}` | Fetch one core stock row. | All roles |
| GET | `/mill/core-stocks` | List core stock, optionally by product line. | All roles |
| POST | `/mill/flooring-lots` | Plan a milling lot drawing kiln-dry lumber from a released charge. | `MillSupervisor`, `MillAdmin` |
| GET | `/mill/flooring-lots/{flooring_lot_id}` | Fetch one flooring lot. | All roles |
| GET | `/mill/flooring-lots` | List flooring lots, optionally by line, charge, core stock, closing grade run or status. | All roles |
| POST | `/mill/flooring-lots/{flooring_lot_id}/complete_milling` | Record milling outputs, the mass balance and the provisional yield. | `MillSupervisor` |
| POST | `/mill/flooring-lots/{flooring_lot_id}/finalize` | Close a lot against a finalized grade run, branching on the yield floor. | `MillSupervisor`, `GradeInspector` |
| POST | `/mill/flooring-lots/{flooring_lot_id}/void` | Void a lot and compensate every reservation it made. | `MillSupervisor`, `MillAdmin` |
| GET | `/mill/flooring-lots/{flooring_lot_id}/yield-summary` | Computed read: the provisional and final yield variants side by side with the mass balance. | All roles |
| POST | `/mill/grade-runs` | Open a grading pass over a milled lot. Optimistically concurrent on the lot. | `GradeInspector` |
| GET | `/mill/grade-runs/{grade_run_id}` | Fetch one grade run. | All roles |
| GET | `/mill/grade-runs` | List grade runs, optionally by lot, superseding run or status. | All roles |
| POST | `/mill/grade-runs/{grade_run_id}/bundles` | Add an immutable graded bundle to a draft run. | `GradeInspector` |
| GET | `/mill/grade-runs/{grade_run_id}/bundles` | List the bundles of a grade run. | All roles |
| GET | `/mill/grade-bundles/{grade_bundle_id}` | Fetch one graded bundle. | All roles |
| GET | `/mill/grade-bundles` | List graded bundles across runs, optionally by grade run or grade class. | All roles |
| POST | `/mill/grade-runs/{grade_run_id}/finalize` | Finalize a grade run and compute its tally. | `GradeInspector` |
| POST | `/mill/grade-runs/{grade_run_id}/supersede` | Supersede a finalized grade run with a replacement run on the same lot. | `GradeInspector`, `MillAdmin` |
| POST | `/mill/prefinish-lines` | Register a prefinishing line. | `MillAdmin` |
| GET | `/mill/prefinish-lines/{prefinish_line_id}` | Fetch one prefinish line. | All roles |
| GET | `/mill/prefinish-lines` | List prefinish lines. | All roles |
| POST | `/mill/prefinish-runs` | Schedule a prefinishing run for a graded lot. | `PrefinishScheduler`, `MillAdmin` |
| GET | `/mill/prefinish-runs/{prefinish_run_id}` | Fetch one prefinish run. | All roles |
| GET | `/mill/prefinish-runs` | List prefinish runs, optionally by line, lot, product line or status. | All roles |
| POST | `/mill/prefinish-runs/{prefinish_run_id}/release_hold` | Return a held run to the schedule once the product line posture is OPEN. | `PrefinishScheduler`, `MillAdmin` |
| POST | `/mill/prefinish-runs/{prefinish_run_id}/start` | Start sanding, staining and coating for a scheduled run. | `PrefinishScheduler` |
| POST | `/mill/prefinish-runs/{prefinish_run_id}/complete` | Complete a running prefinish run. | `PrefinishScheduler` |
| GET | `/mill/byproduct-batches/{byproduct_batch_id}` | Fetch one byproduct batch. | All roles |
| GET | `/mill/byproduct-batches` | List byproduct batches, optionally by lot or stream. | All roles |
| POST | `/mill/byproduct-sales` | Sell tonnage from a byproduct batch. | `ByproductBroker`, `MillAdmin` |
| GET | `/mill/byproduct-sales/{byproduct_sale_id}` | Fetch one byproduct sale. | All roles |
| GET | `/mill/byproduct-sales` | List byproduct sales, optionally by batch. | All roles |
| POST | `/mill/warranty-claims` | File a cupping or gapping warranty claim against a product line. | `WarrantyAdjudicator`, `MillAdmin` |
| GET | `/mill/warranty-claims/{warranty_claim_id}` | Fetch one warranty claim. | All roles |
| GET | `/mill/warranty-claims` | List warranty claims, optionally by product line, lot or either state dimension. | All roles |
| POST | `/mill/warranty-claims/{warranty_claim_id}/request_info` | Request additional information from the claimant. | `WarrantyAdjudicator` |
| POST | `/mill/warranty-claims/{warranty_claim_id}/resubmit` | Resubmit a claim with corrected figures. | `WarrantyAdjudicator`, `MillAdmin` |
| POST | `/mill/warranty-claims/{warranty_claim_id}/adjudicate` | Adjudicate a claim on inspector-verified figures, charging the reserve on approval. | `WarrantyAdjudicator` |
| POST | `/mill/warranty-claims/{warranty_claim_id}/reverse` | Reverse an approved claim and return its charge to the reserve. | `WarrantyAdjudicator`, `MillAdmin` |
| POST | `/mill/warranty-claims/{warranty_claim_id}/start_remediation` | Start remediation work on an approved claim. | `WarrantyAdjudicator`, `MillSupervisor` |
| POST | `/mill/warranty-claims/{warranty_claim_id}/complete_remediation` | Complete remediation work on an approved claim. | `WarrantyAdjudicator`, `MillSupervisor` |

## 5. Error Code Catalogue

The catalogue below lists every error identifier the API can return together with its HTTP status code. Trigger conditions are deliberately not repeated here — each error is introduced next to the rule it guards in §2 and §3.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_CONFIG_NOT_FOUND` | 404 |
| `ERR_RECEIPT_NOT_FOUND` | 404 |
| `ERR_CHARGE_NOT_FOUND` | 404 |
| `ERR_LOT_NOT_FOUND` | 404 |
| `ERR_GRADE_RUN_NOT_FOUND` | 404 |
| `ERR_PREFINISH_RUN_NOT_FOUND` | 404 |
| `ERR_BATCH_NOT_FOUND` | 404 |
| `ERR_CLAIM_NOT_FOUND` | 404 |
| `ERR_STALE_SPECIES_PROFILE_VERSION` | 412 |
| `ERR_STALE_LOT_VERSION` | 412 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_RECEIPT_STATE_INVALID` | 409 |
| `ERR_CHARGE_STATE_INVALID` | 409 |
| `ERR_CHAMBER_STATE_INVALID` | 409 |
| `ERR_LOT_STATE_INVALID` | 409 |
| `ERR_GRADE_RUN_STATE_INVALID` | 409 |
| `ERR_PREFINISH_RUN_STATE_INVALID` | 409 |
| `ERR_CLAIM_STATE_INVALID` | 409 |
| `ERR_PRODUCT_LINE_POSTURE_BLOCKED` | 409 |
| `ERR_REDRY_LIMIT_EXCEEDED` | 409 |
| `ERR_LOT_NOT_GRADED` | 409 |
| `ERR_MC_PLAN_DEVIATION` | 422 |
| `ERR_PROFILE_TOLERANCE_EXCEEDED` | 422 |
| `ERR_BYPRODUCT_SALE_EXISTS` | 409 |
| `ERR_SPECIES_MISMATCH` | 422 |
| `ERR_CORE_STOCK_REQUIRED` | 422 |
| `ERR_CORE_STOCK_NOT_ALLOWED` | 422 |
| `ERR_CORE_STOCK_LINE_MISMATCH` | 422 |
| `ERR_GRADE_RUN_LOT_MISMATCH` | 422 |
| `ERR_CHARACTER_GRADE_NOT_PERMITTED` | 422 |
| `ERR_PREFINISH_WINDOW_INVALID` | 422 |
| `ERR_CHAMBER_WINDOW_CONFLICT` | 409 |
| `ERR_INSTALL_DATE_IN_FUTURE` | 422 |
| `ERR_WARRANTY_PERIOD_EXPIRED` | 422 |
| `ERR_ACCEPTED_BF_EXCEEDS_RECEIVED` | 422 |
| `ERR_CHAMBER_CAPACITY_EXCEEDED` | 422 |
| `ERR_CHARGE_DRY_BF_EXCEEDED` | 422 |
| `ERR_CORE_STOCK_INSUFFICIENT` | 422 |
| `ERR_MILL_MASS_BALANCE_VIOLATION` | 422 |
| `ERR_WASTE_LIMIT_EXCEEDED` | 422 |
| `ERR_NO_GRADE_BUNDLES` | 422 |
| `ERR_BUNDLE_BF_EXCEEDS_LOT` | 422 |
| `ERR_PREFINISH_CAPACITY_EXCEEDED` | 422 |
| `ERR_BYPRODUCT_QUANTITY_EXCEEDS_BATCH` | 422 |
| `ERR_TOO_MANY_OPEN_CLAIMS` | 409 |
| `ERR_DUPLICATE_CODE` | 409 |
| `ERR_ADJUDICATED_SF_EXCEEDS_CLAIM` | 422 |
| `ERR_WARRANTY_RESERVE_INSUFFICIENT` | 422 |
