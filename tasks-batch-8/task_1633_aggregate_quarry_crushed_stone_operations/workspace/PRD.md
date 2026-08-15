# Aggregate Quarry & Crushed-Stone Operations API — Product Requirements Document

## 1. Introduction

An aggregate quarry is a tightly regulated, capital-intensive operation: a pit is developed bench by bench from the top down, rock is drilled and blasted into muckpiles, muck is crushed and screened into specification products, and every ton that leaves the gate crosses a certified truck scale under a freight-inclusive delivered price. This document specifies the Aggregate Quarry & Crushed-Stone Operations API, a system that coordinates that entire value chain as one consistent whole — pit and bench planning with permit-acreage tracking, the drilling program and shot firing, crusher plant runs and circuit yield, stockpile inventory by gradation specification, scale-house ticketing, landowner royalty accounting, MSHA inspection and training compliance, reclamation bonding, and haul-truck dispatch.

Two ideas organize the design. First, every quarry **site** carries a derived regulatory *posture*, computed from its open citations and its reclamation-bond coverage, which gates what the site may do: blasting, bench release, plant runs, and even truck weigh-outs are all subordinate to it, and a site that slips into suspension drags its benches and shot plans into hold automatically. Second, tonnage and money are accounted exactly: inventory is reserved against confirmed orders and swept to backorders the moment new production lands, royalty accrues provisionally at the scale house and is finalized per statement period against a calendar-year tier, and reclamation bonds are phased to the disturbance they actually cover. All resources are exposed as flat, top-level collections joined by identifier references — there are no nested URL hierarchies anywhere in this API.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming the operational capacity in which they act. The declared roles are exactly `QuarryAdmin`, `SiteManager`, `BlastForeman`, `PlantOperator`, `ScaleHouseOperator`, `QCTechnician`, `SalesAgent`, `FinanceClerk`, and `SafetyOfficer`. A request whose `X-User-Role` header is missing or names no declared role, or whose `X-User-ID` header is missing or empty, is rejected with `ERR_UNAUTHENTICATED` (401). A request whose role is not authorized for the target endpoint is rejected with `ERR_FORBIDDEN` (403).

All nine roles use opaque operator identities. When `X-User-Role` is `QuarryAdmin`, when it is `SiteManager`, when it is `BlastForeman`, when it is `PlantOperator`, when it is `ScaleHouseOperator`, when it is `QCTechnician`, when it is `SalesAgent`, when it is `FinanceClerk`, or when it is `SafetyOfficer`, the `X-User-ID` value is an opaque operator identifier not tied to any persisted entity. The server records it where a workflow captures an actor — for example as `submitted_by_user_id` and `approved_by_user_id` on a shot plan, as `reported_by_user_id` and `confirmed_by_user_id` on a gradation test, or as `generated_by_user_id` and `issued_by_user_id` on a royalty statement — and segregation-of-duties checks compare those recorded values against the caller's `X-User-ID`, but the identifier is never compared to any resource's `id`. The single exception is the blasting-safety check: at shot firing, the caller's `X-User-ID` is matched against the `miner_user_id` stored on training records.

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order. List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

Many list endpoints additionally accept optional filters named after resource fields — for example `site_id`, `status`, `bench_id`, `shot_plan_id`, `stockpile_id`, `product_spec_id`, `scale_id`, `scale_type`, `muckpile_id`, `belt_scale_id`, `circuit_line`, `production_status`, `freight_zone_id`, `sales_order_id`, `queue_entry_id`, `scale_ticket_id`, `royalty_agreement_id`, `msha_inspection_id`, `supersedes_agreement_id`, `miner_user_id`, `course_type`, or `truck_id`.

### 2.4. The Logical Clock

The server maintains a logical clock that is the sole source of "now" for every date- and time-dependent rule in this document — the daily blasting window, scale certification windows, training-record currency, royalty statement periods, citation overdue evaluation, and every recorded timestamp. The server must never fall back to wall-clock time. At startup, before any adjustment, the logical clock reads exactly 2026-08-01T00:00:00Z.

An administrator-only test-driving capability, restricted to `QuarryAdmin`, sets the logical clock to a supplied `to_iso8601` instant and reports the resulting `current_utc`. Advancing the clock triggers no automatic recomputation of anything; operators re-derive a site's posture explicitly through the recompute capability described in §3.1 after the clock moves.

### 2.5. Common Resource Properties

Every resource in this API carries four system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` timestamps are ISO 8601 UTC values with three fractional digits; `updated_at` refreshes on every mutation, including automatic mutations performed as cascade side effects. The `version` is an integer that increments on every mutation of the resource and underpins optimistic concurrency control (§2.8). All twenty resource kinds — sites, benches, shot plans, muckpiles, product specs, stockpiles, gradation tests, scales, scale calibrations, plant runs, freight zones, sales orders, scale tickets, royalty agreements, royalty statements, MSHA inspections, MSHA citations, training records, reclamation bonds, and truck queue entries — share this convention without exception. Where a cascade touches several resources inside one request, each touched resource's `updated_at` and `version` reflect that touch, and every effect of a request is visible in that same request's response.

### 2.6. Units, Precision, and Rounding

One rounding method is used throughout the system: round half-up. Monetary values — prices, royalty amounts, bond amounts, penalties — are carried to exactly 2 decimal places, as are powder factors. Weighed net tonnage (`net_tons`), stockpile tonnage bookkeeping (`on_hand_tons`, `reserved_tons`, `available_tons`), and royalty statement tonnage use 3 decimal places. Blast design tonnage, muckpile balances, and disturbed-acreage figures use 1 decimal place. Percentages use 1 decimal place in crusher-yield reporting and 2 decimal places in the tare-variance check. The `run_hours` figure is reported to 2 decimal places.

Weights enter the system in pounds and convert to tons at exactly 2,000 pounds per short ton. Money is denominated in US dollars. Elevations, burdens, spacings, and hole depths are measured in feet; blast pattern volumes convert at 27 cubic feet per cubic yard; in-situ rock is estimated at 1.6 tons per cubic yard.

### 2.7. Validation Order and First-Failure Semantics

Every request is validated against a fixed sequence of rule tiers, and the sequence is part of the contract: when several rules fail at once, the rejection returned is the one belonging to the earliest tier. The tiers, in evaluation order, are:

1. **Authentication** — the `X-User-Role` header must name a declared role and the `X-User-ID` header must be present and non-empty, otherwise `ERR_UNAUTHENTICATED` (401).
2. **Endpoint authorization** — the role must appear in the endpoint's authorized list, otherwise `ERR_FORBIDDEN` (403).
3. **Request shape** — required fields present, types valid, enum values within their declared sets, numeric bounds such as strictly positive quantities satisfied, and any reported sieve analysis covering exactly the band sieves of the stockpile's specification, otherwise `ERR_INVALID_REQUEST` (400).
4. **Existence** — path identifiers must resolve, then body foreign-key identifiers must resolve, checked left-to-right in input order; the first unresolvable identifier determines the rejection, `ERR_NOT_FOUND` (404).
5. **Own state** — the target resource's own state must permit the requested transition, and terminal states accept no further transitions at all, otherwise `ERR_INVALID_STATE` (409).
6. **Site posture** — the site's derived posture must meet the endpoint's minimum: bench release and shot firing require `OPERATING`, while bench resume, reclamation start and completion, shot-plan approval, the start of drilling, explosive loading, plant-run starts, and ticket weigh-in and weigh-out require any posture other than `SUSPENDED`; otherwise `ERR_SITE_POSTURE_BLOCKED` (409).
7. **Regulatory safety gates** — the firing operator must hold current task training (`ERR_TRAINING_EXPIRED`, 409), and a bench release must keep disturbed acreage within the permit (`ERR_PERMIT_ACREAGE_EXCEEDED`, 409).
8. **Temporal gates** — firing is allowed only inside the daily blasting window (`ERR_OUTSIDE_BLAST_WINDOW`, 422), and scales must be certified and in-date at ticket weigh-in, ticket weigh-out, and run start (`ERR_SCALE_NOT_CERTIFIED`, 409).
9. **Cross-entity state** — linked resources must stand in their required states: bench `RELEASED` for shot operations (`ERR_BENCH_NOT_RELEASED`), the muckpile open with sufficient remaining tonnage (`ERR_MUCKPILE_DEPLETED`), the stockpile `OPEN` for order confirmation, ticket weigh-in, and run credit (`ERR_STOCKPILE_QUARANTINED`), the specification and the freight zone active (`ERR_SPEC_RETIRED`, `ERR_ZONE_INACTIVE`), an active royalty agreement covering the relevant date (`ERR_ROYALTY_AGREEMENT_REQUIRED`), no live statement covering the date of a ticket being voided (`ERR_STATEMENT_LOCKED`), every citation terminal before an inspection closes (`ERR_OPEN_CITATIONS`), and no live shot plans on a bench being declared mined out (`ERR_ACTIVE_SHOT_PLAN`).
10. **Uniqueness, overlap, segregation of duties, and physical balance** — one stockpile per site-and-specification pair (`ERR_STOCKPILE_EXISTS`), one active royalty agreement per site (`ERR_AGREEMENT_ALREADY_ACTIVE`), one active queue entry per truck per site (`ERR_TRUCK_ALREADY_QUEUED`), statement periods that neither overlap nor break chronological order (`ERR_STATEMENT_PERIOD_OVERLAP`, `ERR_STATEMENT_NOT_CHRONOLOGICAL`), crusher-circuit exclusivity and cooldown (`ERR_CIRCUIT_OVERLAP`), top-down bench release ordering (`ERR_BENCH_SEQUENCE_VIOLATION`), the same-user prohibitions on approve-versus-submit, confirm-versus-report, and issue-versus-generate (`ERR_SOD_VIOLATION`, 403), drilled-hole completeness (`ERR_HOLES_INCOMPLETE`, 422), run output balance within tolerance (`ERR_OUTPUT_IMBALANCE`, 422), and the tare-variance tolerance (`ERR_TARE_VARIANCE`, 422).
11. **Inventory, capacity, and fiscal guards** — stockpile capacity (`ERR_STOCKPILE_CAPACITY_EXCEEDED`), adjustments that would push physical inventory below reservations (`ERR_ADJUSTMENT_BELOW_RESERVED`), over-shipment beyond the order tolerance (`ERR_OVER_SHIPMENT`), truck payload legality (`ERR_TRUCK_OVERWEIGHT`, 422), bond coverage after a release (`ERR_BOND_BELOW_REQUIRED`), closing only empty stockpiles (`ERR_STOCKPILE_NOT_EMPTY`), and dispatch from an empty queue (`ERR_QUEUE_EMPTY`).
12. **Concurrency** — on the three version-guarded writes of §2.8, the expected-version field must equal the parent resource's current `version`, otherwise `ERR_STALE_VERSION` (412). This tier is evaluated last, after every state and business rule above has passed.

### 2.8. Optimistic Concurrency Control

Exactly three write operations are guarded by optimistic concurrency control, each against the `version` of the resource it modifies:

- A manual stockpile inventory adjustment (`POST /stockpiles/{id}/adjustments`) must carry `expected_stockpile_version`, the stockpile's `version` as the client last observed it. Because adjustments do not read one another's results, the version precondition is what makes a second writer's intent well-defined.
- A requote of a quoted sales order (`POST /sales-orders/{id}/reprice`) must carry `expected_sales_order_version`, since repricing recomputes and supersedes the quote terms the client last observed.
- A reclamation-bond release (`POST /reclamation-bonds/{id}/release`) must carry `expected_reclamation_bond_version`, because a release is an independent decrement validated only against site coverage — no state precondition catches a release built on a stale read of the remaining amount.

In each case, if the supplied value does not equal the resource's current `version` — because an accepted write (a production credit, a ticket draw, a reservation, a prior adjustment, a prior release, or a prior reprice) has advanced it since the client last read the resource — the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and nothing is mutated. No other endpoint accepts an expected-version field; requests to other endpoints simply omit it.

### 2.9. Derived Site Posture and Cascading Consistency

Each site exposes a computed `posture` of `OPERATING`, `RESTRICTED`, or `SUSPENDED`, derived from its citations and bond coverage as specified in §3.1. The derivation is recomputed synchronously — within the same request — whenever a citation is created, abated, or vacated; a reclamation bond is created or released; a bench changes status; or an authorized operator invokes the posture-recompute capability. Posture changes can cascade outward: entering `SUSPENDED` automatically holds benches and shot plans, and leaving `SUSPENDED` automatically resumes exactly the holds that the suspension created (§3.9). Cascades never span requests: every mutation a request triggers, however indirect, is committed and visible within that request's response.

Because resources are flat peers joined by identifier references rather than nested paths, existence checking is exactly the left-to-right resolution of tier 4 in §2.7 — path identifiers first, then body references in input order.

### 2.10. Segregation of Duties

Three workflows forbid the same operator from performing both sides of a control pair, enforced by comparing `X-User-ID` values. A shot plan may not be approved by the operator who submitted it. A gradation test may not be confirmed by the technician who reported it. A royalty statement may not be issued by the clerk who generated it. Each violation is rejected with `ERR_SOD_VIOLATION` (403). The recorded actor fields are the basis of comparison in each case: `submitted_by_user_id` against the approver, `reported_by_user_id` against the confirmer, and `generated_by_user_id` against the issuer.

## 3. Business Logic & Workflows

### 3.1. Establishing a Site: Permits, Bonding, and the Posture Model

A `QuarryAdmin` establishes a quarry site by supplying its `name`, the `permitted_acres` authorized by the mining permit (a strictly positive number; disturbance may never exceed it), and the `bond_rate_per_acre_usd` that the permit sets per disturbed acre (also strictly positive). A new site starts clean: `disturbed_acres`, `bond_required_usd`, and `bond_posted_usd` are all zero, `bond_adequacy` reads `ADEQUATE`, and `posture` reads `OPERATING`.

Four of the site's fields are computed rather than stored from input. The `disturbed_acres` figure sums the `acreage` of the site's benches whose status is `RELEASED`, `ON_HOLD`, `MINED_OUT`, or `RECLAMATION_IN_PROGRESS`; benches still `PLANNED` and benches already `RECLAIMED` are excluded. The `bond_required_usd` figure is phased to the life-cycle stage of the disturbance: acres on benches that are `RELEASED`, `ON_HOLD`, or `MINED_OUT` count at the full `bond_rate_per_acre_usd`, while acres on benches in `RECLAMATION_IN_PROGRESS` count at half that rate. The `bond_posted_usd` figure sums, over the site's reclamation bonds whose status is `POSTED` or `PARTIALLY_RELEASED`, each bond's face `amount_usd` minus its cumulative `released_usd`; fully released bonds drop out of the sum. The `bond_adequacy` reads `ADEQUATE` when posted coverage is at least the requirement, and `DEFICIENT` the moment coverage falls below it.

Posture itself is derived in a pinned evaluation order, recomputed synchronously after every citation creation, abatement, or vacatur; after every bond creation or release; after every bench transition; and whenever a `SiteManager` or `SafetyOfficer` invokes the posture-recompute capability on the site. The order is: first recompute `disturbed_acres` from bench statuses; then recompute `bond_required_usd` at the phased rates and `bond_posted_usd` from the bonds; then recompute `bond_adequacy`; and only then derive `posture`. The site is `SUSPENDED` when any citation belonging to the site through its inspections stands `ISSUED`, is flagged significant-and-substantial, and has an `abatement_due_on` date earlier than the current logical date. Failing that, the site is `RESTRICTED` when `bond_adequacy` is `DEFICIENT` or when any citation of the site stands `ISSUED` at all. Otherwise the site is `OPERATING`. Transition guards that consult posture — such as the reclamation-completion guard in §3.2 — always evaluate against the posture in force *before* the transition commits; the recomputation above applies only afterwards. Evaluating the guard with the new acreage already folded in would be a circular misreading, and the pinned order forbids it.

A `FinanceClerk` posts surety instruments against the site by supplying `site_id`, the `surety_name`, and the face `amount_usd` (strictly positive). A new bond starts `POSTED` with `released_usd` at zero, and its arrival immediately recomputes the site's coverage and posture. Later, the clerk may release bond value back to the surety through a release request carrying `release_amount_usd` and the OCC field `expected_reclamation_bond_version` (§2.8). The governing rule is post-release coverage: the site's posted coverage after the release must remain at least `bond_required_usd`, otherwise the release is rejected with `ERR_BOND_BELOW_REQUIRED`. A release that leaves a remainder moves the bond from `POSTED` to `PARTIALLY_RELEASED`, or keeps it in `PARTIALLY_RELEASED` if it was already there; a release exactly equal to the remaining unreleased amount — equality is the boundary — moves the bond to `FULLY_RELEASED`, whether from `POSTED` or from `PARTIALLY_RELEASED`. Every accepted release adds to `released_usd`, increments the bond's `version`, and recomputes the site's `bond_posted_usd`, adequacy, and posture in the same request.

### 3.2. The Bench Lifecycle: Release, Hold, Mined-Out, and Reclamation

Within a site, a `SiteManager` plans benches by supplying the owning `site_id`, a human `bench_label` such as BENCH-1400, the bench floor `elevation_ft`, and the `acreage` of disturbance the bench will represent once released (strictly positive). A bench is born `PLANNED` and counts against nothing.

Releasing a bench for mining moves it `PLANNED` → `RELEASED` and is one of the most heavily gated acts in the system, evaluated under the tier order of §2.7. The site's posture must be `OPERATING` — a `RESTRICTED` or `SUSPENDED` site rejects the release with `ERR_SITE_POSTURE_BLOCKED`. Top-down ordering is enforced by elevation: every bench of the same site whose `elevation_ft` is greater than this bench's must already stand `MINED_OUT`, `RECLAMATION_IN_PROGRESS`, or `RECLAIMED`, otherwise the release fails with `ERR_BENCH_SEQUENCE_VIOLATION`. Permit headroom is checked last among the release gates: the site's `disturbed_acres` after the release — the current figure plus this bench's `acreage` — must not exceed `permitted_acres`, with equality permitted, otherwise `ERR_PERMIT_ACREAGE_EXCEEDED`. A successful release adds the bench's acres to `disturbed_acres`, recomputes `bond_required_usd`, and recomputes posture — which can drop the site from `OPERATING` to `RESTRICTED` in the same request if the enlarged requirement outruns the posted bond.

A released bench may be held two ways. A `SiteManager` may hold it manually by supplying a `reason`, which is recorded verbatim as the bench's `hold_reason`. Or the site may fall into `SUSPENDED`, in which case the posture cascade of §3.9 holds every `RELEASED` bench with the sentinel hold_reason `MSHA_SUSPENSION`. Either way the bench rests in `ON_HOLD`. Resuming returns the bench `ON_HOLD` → `RELEASED`: for a manual hold, a `SiteManager` resumes it explicitly, which is rejected with `ERR_SITE_POSTURE_BLOCKED` while the site remains `SUSPENDED`; for a suspension hold, the system auto-resumes when posture leaves `SUSPENDED`. Resumption clears `hold_reason` to null and returns every `ON_HOLD` shot plan on the bench to its captured `hold_return_state`, clearing that field as well.

When the bench's rock is exhausted, a `SiteManager` declares it mined out, moving it `RELEASED` → `MINED_OUT`. The declaration is refused with `ERR_ACTIVE_SHOT_PLAN` while any shot plan on the bench stands in `APPROVED`, `DRILLING`, `DRILLED`, `LOADED`, or `ON_HOLD`. A mined-out bench keeps counting its acres at the full bond rate — the phase does not change — and the site's posture is recomputed. Reclamation then proceeds in two steps. Starting reclamation moves the bench `MINED_OUT` → `RECLAMATION_IN_PROGRESS`, requires that the site is not `SUSPENDED` (`ERR_SITE_POSTURE_BLOCKED`), and shifts the bench's acres to the half-rate phase of `bond_required_usd`, recomputing posture. Completing reclamation moves the bench `RECLAMATION_IN_PROGRESS` → `RECLAIMED`; its posture guard is evaluated against the site's *pre-transition* posture, again rejecting a `SUSPENDED` site with `ERR_SITE_POSTURE_BLOCKED`. After the transition commits, the pinned order of §3.1 runs in full — the bench's acres leave the disturbed set, the requirement is recomputed, adequacy is re-derived, and posture is re-derived — so a reclamation that cures a bond deficiency flips the site from `RESTRICTED` back to `OPERATING` inside the same request. `RECLAIMED` is terminal.

### 3.3. The Drill-and-Blast Program

A `BlastForeman` authors a shot plan against a bench by supplying the `bench_id` and the pattern geometry: `hole_count` (at least one hole), `burden_ft`, `spacing_ft`, `hole_depth_ft`, and the design charge `explosive_per_hole_lbs` (each strictly positive). The plan is born in `DRAFT` with `drilled_hole_count` at zero and `loaded_explosive_lbs` unset. At creation the system computes the design blast tonnage: the pattern volume is `hole_count` times `burden_ft` times `spacing_ft` times `hole_depth_ft` cubic feet, divided by 27 cubic feet per cubic yard; that volume times the in-situ density of 1.6 tons per cubic yard gives `estimated_tons`, rounded half-up to one decimal place. The `powder_factor` — pounds of explosive per estimated ton, rounded half-up to two decimals — is computed against the design load of `hole_count` times `explosive_per_hole_lbs` until an actual load is reported, and against `loaded_explosive_lbs` thereafter.

Submission moves the plan `DRAFT` → `SUBMITTED` and records the caller in `submitted_by_user_id`. Approval by a `SiteManager` moves it `SUBMITTED` → `APPROVED` under three gates: the bench must stand `RELEASED` (`ERR_BENCH_NOT_RELEASED`), the site posture must be `OPERATING` or `RESTRICTED` (`ERR_SITE_POSTURE_BLOCKED`), and the approver must not be the operator recorded as the submitter (`ERR_SOD_VIOLATION`). The approver is recorded in `approved_by_user_id`. Field work then advances `APPROVED` → `DRILLING` when drilling starts — again requiring a `RELEASED` bench and a posture of `OPERATING` or `RESTRICTED` — and `DRILLING` → `DRILLED` when the foreman reports completion with a payload `drilled_hole_count` that must reach at least the designed `hole_count` (`ERR_HOLES_INCOMPLETE`, 422, when it falls short); the reported count is stored. Collapsed or flooded holes reopen the loop: a redrill returns the plan `DRILLED` → `DRILLING`, requires a `RELEASED` bench and a non-`SUSPENDED` posture, and resets `drilled_hole_count` to zero. Loading explosives with a payload `loaded_explosive_lbs` moves the plan `DRILLED` → `LOADED`, requires a `RELEASED` bench, and recomputes `powder_factor` from the actual load.

Firing is the climax and carries the strictest gates. The bench must stand `RELEASED`; the site posture must be exactly `OPERATING` — a merely `RESTRICTED` site may not blast (`ERR_SITE_POSTURE_BLOCKED`); the firing operator must hold a current task-training record as detailed in §3.9 (`ERR_TRAINING_EXPIRED`); and the shot must fall inside the daily blasting window, meaning the current logical-clock UTC hour is at least 8 and strictly less than 17 — from 08:00 up to but not including 17:00 UTC (`ERR_OUTSIDE_BLAST_WINDOW`, 422). A successful firing stamps `fired_at` from the logical clock, moves the plan to the terminal state `FIRED`, and creates exactly one **muckpile** as its child: the muckpile records the originating `shot_plan_id`, copies `estimated_tons` from the plan, opens with `remaining_tons` equal to that estimate and `actual_fed_tons` at zero, and stands `OPEN`. The new pile is discoverable through the muckpile list filtered by `shot_plan_id`.

A plan may instead be cancelled by a `BlastForeman` from `DRAFT`, from `SUBMITTED`, or from `APPROVED`, each path landing in the terminal state `CANCELLED`. Once fired or cancelled, a plan accepts no further transitions. Separately, if the site's posture collapses into `SUSPENDED`, the cascade of §3.9 moves every plan on the site's benches that stands in `APPROVED`, `DRILLING`, `DRILLED`, or `LOADED` into `ON_HOLD`, capturing the prior status in `hold_return_state`; when posture recovers, each held plan returns to exactly that captured state and `hold_return_state` clears to null.

The muckpile tracks its own drawdown. Every completed plant run that feeds from the pile adds its `input_tons` to `actual_fed_tons` — the reconciled-actual variant of blast tonnage, summed over the pile's completed runs regardless of reconciliation status, excluding voided and cancelled runs — and subtracts the same amount from `remaining_tons`. Debits apply in completion order; a voided run removes its own contribution regardless of that order. When `remaining_tons` reaches exactly zero the pile auto-transitions `OPEN` → `DEPLETED`; if a later run void restores tonnage above zero, a `DEPLETED` pile auto-reopens to `OPEN`. The design estimate and the belt-measured actuals legitimately diverge: one is geometric, the other is measured through dilution and recovery.

### 3.4. Product Specifications, Stockpiles, and Quality Control

A `QuarryAdmin` defines each sellable gradation by supplying a `spec_code` (unique across all specifications, such as ASTM-57), a `category` of `COARSE`, `FINE`, or `RIPRAP`, the `gradation_bands` — an array of sieve entries each carrying a `sieve` name with an inclusive pass band from `min_pct` to `max_pct`, requiring at least one band and `min_pct` no greater than `max_pct` — and the list material price `base_price_per_ton` (strictly positive). Specifications are born `ACTIVE`. The `RIPRAP` category carries one commercial privilege: it is exempt from the fuel surcharge in delivered pricing (§3.6). Retiring a specification moves it `ACTIVE` → `RETIRED`, which blocks the creation and the confirmation of new orders against it (`ERR_SPEC_RETIRED`) and blocks any further plant-run output credit to its stockpiles (`ERR_SPEC_RETIRED`); existing orders are unaffected.

A `SiteManager` then creates physical stockpiles by supplying `site_id`, `product_spec_id`, and `capacity_tons` (strictly positive). There is at most one stockpile per site-and-specification pair; a duplicate is rejected with `ERR_STOCKPILE_EXISTS`. A pile is born `OPEN` with `on_hand_tons`, `reserved_tons`, and `available_tons` all at zero. One invariant governs the pile at all times: `available_tons` always equals `on_hand_tons` minus `reserved_tons`, and every mutation — production credits, ticket draws, manual adjustments, reservations and their release, voids — maintains it. Physical stock may never exceed `capacity_tons`: any run credit or manual adjustment that would push `on_hand_tons` above capacity is rejected with `ERR_STOCKPILE_CAPACITY_EXCEEDED`.

Manual inventory corrections are made by a `SiteManager` through an adjustment carrying `delta_tons`, a free-text `reason`, and the OCC field `expected_stockpile_version` (§2.8). The adjustment adds `delta_tons` to `on_hand_tons` and increments the pile's `version`. A negative adjustment may not drive `on_hand_tons` below `reserved_tons` (`ERR_ADJUSTMENT_BELOW_RESERVED`). A positive adjustment on an `OPEN` pile fires the backorder allocation sweep of §3.6. Closing a pile — from either `OPEN` or `QUARANTINED` — requires that both `on_hand_tons` and `reserved_tons` stand at exactly zero (`ERR_STOCKPILE_NOT_EMPTY`); `CLOSED` is terminal.

Quality control runs on sieve analyses. A `QCTechnician` reports a gradation test against a pile by supplying `stockpile_id`, the `sampled_at` timestamp, and the `sieve_results` — an array pairing each `sieve` with its measured `pct_passing` — which must cover exactly the band sieves declared by the pile's specification, otherwise `ERR_INVALID_REQUEST`. The test's `result` is computed at creation and is immutable thereafter: the result is `PASS` when every sieve's `pct_passing` falls within its band from `min_pct` through `max_pct` with both bounds included — a measurement exactly on either bound passes — and `FAIL` otherwise. A reported test stands `REPORTED` with the technician recorded in `reported_by_user_id`.

Confirmation moves a test `REPORTED` → `CONFIRMED` under two gates: the confirmer must not be the recorded reporter (`ERR_SOD_VIOLATION`), and the pile must not be `CLOSED` (`ERR_INVALID_STATE`). The confirmer is recorded in `confirmed_by_user_id`, and the pile's quality gate responds to the confirmed result. A confirmed `FAIL` drives the pile `OPEN` → `QUARANTINED`, which blocks new order confirmations and ticket weigh-ins against it (`ERR_STOCKPILE_QUARANTINED`) as well as plant-run output credits. A confirmed `PASS` restores the pile `QUARANTINED` → `OPEN` only when no later confirmed, non-voided `FAIL` exists for the pile: the latest confirmed test decides, selected by the greatest `sampled_at` with ties broken by the greatest `created_at`. Voiding is available from both `REPORTED` and `CONFIRMED` and lands in `VOIDED`; voiding a confirmed test re-evaluates the pile from the remaining confirmed, non-voided tests under the same latest-confirmed rule — voiding the latest confirmed `FAIL` reopens the pile when the new latest confirmed result is a `PASS` or none remains, while voiding a `PASS` that unmasks a later confirmed `FAIL` quarantines it.

### 3.5. Plant Runs, Circuit Yield, and Reconciliation

A `PlantOperator` schedules a plant run by supplying the `site_id`, the `muckpile_id` that will feed the crusher, the `belt_scale_id` that will measure the feed, and the `circuit_line` — `PRIMARY` or `SECONDARY`. A run carries two independent state dimensions on the same row: `production_status`, born `SCHEDULED`, and `reconciliation_status`, born `UNRECONCILED`. Scheduling performs no gate checks; every gate below bites when the run starts.

Starting a run moves production `SCHEDULED` → `RUNNING` under four gates. The site posture must not be `SUSPENDED` (`ERR_SITE_POSTURE_BLOCKED`). The muckpile must stand `OPEN` (`ERR_MUCKPILE_DEPLETED`). The belt scale must stand `CERTIFIED` with a `certified_through` date on or after the current logical date (`ERR_SCALE_NOT_CERTIFIED`). And the circuit must be free: no other run of the same site and `circuit_line` may be `RUNNING`, and no completed run on the same circuit may have ended so recently that thirty minutes have not yet elapsed since its `ended_at` (`ERR_CIRCUIT_OVERLAP`). A started run stamps `started_at` from the logical clock.

Completion, reported by the operator with a payload `input_tons` and an `outputs` array of entries each naming a `stockpile_id`, its `product_spec_id`, and the credited `tons`, closes the production phase `RUNNING` → `COMPLETED`. The balance gate requires the absolute difference between the summed output tonnage and `input_tons` to be at most three percent of `input_tons`, with exactly three percent passing (`ERR_OUTPUT_IMBALANCE`, 422). The feed gate requires `input_tons` not to exceed the muckpile's `remaining_tons` (`ERR_MUCKPILE_DEPLETED`). Each output row is checked individually: the pile must stand `OPEN` (`ERR_STOCKPILE_QUARANTINED`); its specification must be `ACTIVE` (`ERR_SPEC_RETIRED`); the pile must belong to the run's site and its `product_spec_id` must match the pile's own specification (`ERR_INVALID_REQUEST`); and crediting `tons` must not push the pile past `capacity_tons` (`ERR_STOCKPILE_CAPACITY_EXCEEDED`). A successful completion stamps `ended_at`, computes `run_hours` as the elapsed time between `started_at` and `ended_at` in hours to two decimals, and stores `input_tons` and the `outputs` array. Its cascades then fire in the same request: the muckpile's `actual_fed_tons` gains and `remaining_tons` loses `input_tons` (auto-depleting at exactly zero per §3.3); each output pile's `on_hand_tons` gains its credited `tons` with `available_tons` recomputed; and each credited pile triggers the backorder allocation sweep of §3.6.

Completion also computes the run's `yield_summary`, keyed by each output specification's `spec_code`. For every output row, the measured share is one hundred times the row's `tons` divided by `input_tons`, rounded half-up to one decimal, recorded as `measured_pct`. The design share depends on the circuit and on the category of the output's specification: on the `PRIMARY` circuit the design is 65.0 for `COARSE`, 35.0 for `FINE`, and 50.0 for `RIPRAP`; on the `SECONDARY` circuit it is 55.0 for `COARSE`, 45.0 for `FINE`, and 60.0 for `RIPRAP` — recorded as `design_pct`. The deviation `variance_pts` is the measured share minus the design share, rounded half-up to one decimal.

Reconciliation is the second dimension. While a completed run stands `UNRECONCILED`, the operator may submit an independent feed figure `reconciled_input_tons`. Reconciliation requires production to be `COMPLETED` (`ERR_INVALID_STATE` otherwise). When the reconciled figure differs from `input_tons` by at most two percent of `input_tons`, inclusive, the run moves to `RECONCILED` and the figure is stored; when it differs by more, the run routes to `DISPUTED` instead — a threshold branch, not an error. A later corrected submission moves the run `DISPUTED` → `RECONCILED` under the same two-percent tolerance and overwrites `reconciled_input_tons` with the corrected value.

Two unwind paths exist. A scheduled run may be cancelled, moving production `SCHEDULED` → `CANCELLED`. A completed run may be voided, but only while its reconciliation still stands `UNRECONCILED` — once `RECONCILED` or `DISPUTED`, the attempt is rejected with `ERR_INVALID_STATE` — and only while the reversal is absorbable, meaning every credited pile still holds at least the tonnage it was credited (`ERR_REVERSAL_BLOCKED` when shipped tons have already drawn a pile below its credit). Voiding moves production to `VOIDED` and compensates everything: each credited pile loses its credited `tons` from `on_hand_tons` with `available_tons` recomputed, and the muckpile regains `input_tons` in `remaining_tons` while losing it from `actual_fed_tons` — reopening the pile from `DEPLETED` back to `OPEN` if the restoration lifts it above zero. `VOIDED` and `CANCELLED` are the terminal production states; the reconciliation dimension retains whatever value it last held.

### 3.6. Freight Zones, Delivered Pricing, and the Order Lifecycle

A `QuarryAdmin` publishes freight-inclusive pricing zones by supplying a unique `zone_code`, the one-way haul `distance_miles` (strictly positive), and the flat freight component `base_freight_per_ton` (zero or greater). Zones are born `ACTIVE`. Deactivating a zone moves it `ACTIVE` → `INACTIVE`; new order creation against an inactive zone is rejected with `ERR_ZONE_INACTIVE`, while existing orders keep their pinned prices.

A `SalesAgent` opens an order by supplying the shipping `site_id`, the `product_spec_id`, the `freight_zone_id`, the `customer_name`, and the ordered `quantity_tons` (strictly positive). Creation already enforces an `ACTIVE` specification and an `ACTIVE` zone (`ERR_SPEC_RETIRED`, `ERR_ZONE_INACTIVE`). The order is born `QUOTED` with `fulfilled_tons` at zero, `prices_pinned` false, and `stockpile_id` unset, and the system computes a full delivered-price quote. The evaluation order is pinned. First the material component: `base_price_per_ton` is multiplied by a volume factor chosen by `quantity_tons` — the full price (a factor of 1.00) for orders of at most 100 tons; five percent off (a factor of 0.95) for orders above 100 tons and at most 1,000 tons; ten percent off (a factor of 0.90) for orders above 1,000 tons — an average-rate discount in which the single selected factor applies to every ton, rounded half-up to two decimals and stored as `quoted_material_per_ton`. Second, the freight component is the zone's `base_freight_per_ton` rounded half-up to two decimals, stored as `quoted_freight_per_ton`. Third, the two rounded components are summed, and the fuel surcharge is taken from that subtotal: specifications in the `RIPRAP` category are exempt and always show 0.00; otherwise the rate is eight percent when the subtotal is below $20.00, twelve percent when it is at least $20.00 and below $40.00, and fifteen percent when it is at least $40.00, with the surcharge rounded half-up to two decimals as `quoted_surcharge_per_ton`. The unit delivered price `quoted_unit_delivered_per_ton` is the sum of the three components, and `quoted_total_usd` is that unit price times `quantity_tons`, rounded half-up to two decimals. Rounding is pinned per component: round each component first, then sum — never round once at the end.

While the order remains `QUOTED`, the agent may reprice it against the current price book by supplying the OCC field `expected_sales_order_version` (§2.8); an accepted reprice recomputes every `quoted_` field and increments the order's `version`. Confirmation is the pinning point. Confirming moves the order out of `QUOTED` and freezes all five `quoted_` fields — `prices_pinned` becomes true — so that identical inputs afterwards produce the pinned values even if the price book later changes, while a reprice before confirmation, after a price-book change, yields different numbers than the original quote. Confirmation by a `SalesAgent` requires the specification `ACTIVE` and the zone `ACTIVE` (re-checked here), and resolves the order's stockpile by selector: the site's stockpile for the ordered specification must exist and stand `OPEN`, otherwise confirmation fails with `ERR_STOCKPILE_QUARANTINED`. The availability branch then routes the order without any error: when the pile's `available_tons` is at least `quantity_tons` — equality confirms — the order lands `QUOTED` → `CONFIRMED`, its `stockpile_id` is set, and the pile's `reserved_tons` gains `quantity_tons`; when availability falls short, the order lands `QUOTED` → `BACKORDERED` with `stockpile_id` still set and prices still pinned, but no reservation made.

Backorders are serviced by an allocation sweep. Whenever a pile is credited — a plant-run completion or a positive manual adjustment — and the pile stands `OPEN`, the system walks the `BACKORDERED` orders of the same site and specification in strict first-in-first-out order: ranked by `created_at` ascending, ties broken by `quantity_tons` ascending and then by `customer_name` ascending. Each order promotes `BACKORDERED` → `CONFIRMED` only if, at its turn, the pile's `available_tons` covers its full `quantity_tons`; promotion reserves that tonnage in `reserved_tons`. The sweep stops at the first order that does not fit — no skipping ahead to smaller orders behind it.

Fulfillment proceeds at the scale house. The first completed weigh-out against an order moves it `CONFIRMED` → `IN_FULFILLMENT` and adds the ticket's `net_tons` to `fulfilled_tons`; the reservation shrinks to the unfulfilled balance, floored at zero. When a draw brings `fulfilled_tons` to at least `quantity_tons` — reaching it exactly completes the order — the order auto-transitions to the terminal state `COMPLETED` and its reservation drops to zero. Cancellation by a `SalesAgent` is possible from `QUOTED`, `CONFIRMED`, `BACKORDERED`, and `IN_FULFILLMENT`, landing in the terminal state `CANCELLED`, with compensation matched to the state: a quoted order holds no reservation and releases nothing; a backordered order never reserved, so it too releases nothing; a confirmed order releases its full `quantity_tons` reservation; and an in-fulfillment order releases the unfulfilled balance — `quantity_tons` minus `fulfilled_tons`, floored at zero — while its `fulfilled_tons` stands, because shipped tons remain billable.

### 3.7. Scale-House Operations: Scales, the Truck Queue, and Ticketing

Scale accuracy is administered centrally. A `QuarryAdmin` registers each scale with its `site_id`, a `scale_code` unique within the site, and a `scale_type` of `TRUCK` for scale-house ticketing or `BELT` for plant feed measurement. A scale is born `OUT_OF_SERVICE` with `certified_through` unset. Calibrations are recorded against a scale with `scale_id`, the `calibrated_on` date, the `as_found_error_pct`, and the `as_left_error_pct`; the calibration's `result` is `PASS` when the absolute as-left error is at most 0.25 percent — exactly 0.25 passes — and `FAIL` otherwise, and the record stands `RECORDED`. A recorded `PASS` moves the scale to `CERTIFIED` and sets `certified_through` to `calibrated_on` plus 180 days, that date being the inclusive last valid day of certification; a newer `PASS` supersedes the window with its own `calibrated_on` plus 180 days while the scale stays `CERTIFIED`. A recorded `FAIL` takes the scale `OUT_OF_SERVICE` — or leaves it there if it already was. Voiding a calibration, an admin act that moves the record `RECORDED` → `VOIDED`, recomputes certification from the remaining non-voided `PASS` calibrations, taking the latest `calibrated_on`; if none remain, the scale falls `OUT_OF_SERVICE` with `certified_through` unset. Wherever this document requires a usable scale — ticket weigh-in, ticket weigh-out, run start — usable means `CERTIFIED` with `certified_through` on or after the current logical date, and failure is `ERR_SCALE_NOT_CERTIFIED`.

Trucks arriving at the gate are queued by a `ScaleHouseOperator` with the `site_id`, the external `truck_id`, a `priority_class` of `CONTRACT`, `SPOT`, or `INTERNAL`, the registered empty weight `certified_tare_lbs`, and the legal payload `max_payload_lbs` (both strictly positive). The entry is born `QUEUED` with `queued_at` stamped from the logical clock and `scale_ticket_id` unset. A truck may hold at most one active entry per site — active meaning `QUEUED`, `AT_SCALE_IN`, `LOADING`, or `AT_SCALE_OUT` — and a duplicate is rejected with `ERR_TRUCK_ALREADY_QUEUED`. Dispatch works by selector: calling the next truck for a site considers only its `QUEUED` entries, ranks `CONTRACT` ahead of `SPOT` ahead of `INTERNAL`, breaks ties by the earlier `queued_at` and then by `truck_id` in ascending string order, and moves the winner `QUEUED` → `AT_SCALE_IN`; an empty pool is rejected with `ERR_QUEUE_EMPTY`. A queued truck that never appears may be marked `QUEUED` → `NO_SHOW`.

Weigh-in opens a scale ticket. Against an entry that stands `AT_SCALE_IN`, the operator supplies the `queue_entry_id`, the `sales_order_id` being fulfilled, the `scale_id` of the truck scale, and the loaded weight `gross_lbs` (strictly positive). The order must stand `CONFIRMED` or `IN_FULFILLMENT`; the scale must be certified and in-date; the order's stockpile must stand `OPEN` (`ERR_STOCKPILE_QUARANTINED`); and the site posture must not be `SUSPENDED`. The ticket is created `OPEN`: `site_id` is copied from the queue entry, `stockpile_id` from the sales order, and `truck_id` from the entry, while `tare_lbs`, `net_tons`, `tare_variance_pct`, `royalty_provisional_usd`, and `completed_at` remain unset and `void_reason` stays null. The entry advances `AT_SCALE_IN` → `LOADING` and records the new ticket in `scale_ticket_id`. When loading finishes, the operator sends the truck to the outbound scale, moving the entry `LOADING` → `AT_SCALE_OUT`.

Weigh-out completes the ticket against a payload `tare_lbs` and an optional `allow_tare_variance` flag. The queue entry must stand `AT_SCALE_OUT` (`ERR_INVALID_STATE`); posture must still permit shipping; the scale is re-checked as certified and in-date; and four business gates follow. The tare-variance check compares the observed empty weight against the registered one: `tare_variance_pct` is the absolute difference between `tare_lbs` and the entry's `certified_tare_lbs`, expressed as a percentage of `certified_tare_lbs` and rounded half-up to two decimals — a variance of at most 2.00 passes, while a greater variance is rejected with `ERR_TARE_VARIANCE` (422) unless the payload sets `allow_tare_variance` to true. The legal-weight check requires `gross_lbs` minus `tare_lbs` not to exceed the entry's `max_payload_lbs` (`ERR_TRUCK_OVERWEIGHT`, 422). Royalty coverage must exist: an `ACTIVE` royalty agreement of the site whose `effective_from` is on or before the current date and whose `effective_to` is either unset or after the current date (`ERR_ROYALTY_AGREEMENT_REQUIRED`). Finally the over-shipment guard requires that the order's `fulfilled_tons` plus this draw's `net_tons` not exceed one hundred ten percent of `quantity_tons`, computed as `quantity_tons` times 1.10 and rounded half-up to three decimals, with exactly that bound allowed (`ERR_OVER_SHIPMENT`).

A completed weigh-out computes and commits everything in one request. The `net_tons` are `gross_lbs` minus `tare_lbs`, divided by 2,000 pounds per ton, rounded half-up to three decimals. The provisional royalty `royalty_provisional_usd` accrues at the flat base rate — `net_tons` times the covering agreement's `base_rate_per_ton`, rounded half-up to two decimals — with no tier awareness; §3.8 finalizes it. The timestamp `completed_at` is stamped from the logical clock and will later drive statement-period membership. The stockpile's `on_hand_tons` drops by `net_tons` with `available_tons` recomputed. The order's `fulfilled_tons` grows by `net_tons`, moving `CONFIRMED` → `IN_FULFILLMENT` on the first draw and on to `COMPLETED` when fulfillment reaches the ordered quantity, its reservation recomputed as the unfulfilled balance floored at zero. The queue entry exits `AT_SCALE_OUT` → `EXITED`, and the ticket stands `COMPLETED`.

Voiding a ticket is a `SiteManager` act carrying a `void_reason`. Only a `COMPLETED` ticket may be voided, and only while no royalty statement in `DRAFT`, `ISSUED`, or `PAID` has a period containing the ticket's `completed_at` (`ERR_STATEMENT_LOCKED`). The void moves the ticket to the terminal state `VOIDED` and compensates in full: the stockpile regains `net_tons` in `on_hand_tons`; the order's `fulfilled_tons` loses `net_tons`, its reservation is recomputed as the unfulfilled balance floored at zero, and an order that had auto-completed reverts from `COMPLETED` back to `IN_FULFILLMENT`; and the voided ticket is excluded from every subsequent royalty statement sweep — voided tickets never enter the final royalty input set of §3.8.

### 3.8. Royalty Agreements and Statements

A `FinanceClerk` establishes the landowner royalty for a site by supplying `site_id`, the `landowner_name`, the `base_rate_per_ton` paid per ton, the `tier_threshold_tons` of calendar-year cumulative tonnage at which the tier rate begins, the `tier_rate_per_ton` applied marginally to tons beyond the threshold, and the `effective_from` date on which coverage begins; the three numeric terms are each strictly positive. At most one agreement per site may stand `ACTIVE` — a second creation is rejected with `ERR_AGREEMENT_ALREADY_ACTIVE`, directing the clerk to amendments — and a new agreement is born `ACTIVE` with `effective_to` unset and `supersedes_agreement_id` null.

Agreements evolve as a self-referential amendment chain. Amending is a create-with-supersede act against an agreement that must stand `ACTIVE` — attempting it against an already superseded or terminated agreement is a state failure, `ERR_INVALID_STATE`, not a race. The old agreement moves `ACTIVE` → `SUPERSEDED`, its `effective_to` is set to the amendment's `effective_from`, and its `version` increments; the payload rates (`base_rate_per_ton`, `tier_threshold_tons`, `tier_rate_per_ton`, `effective_from`) create a new agreement that is born `ACTIVE` with its `supersedes_agreement_id` pointing back at the old one. Termination moves an `ACTIVE` agreement to `TERMINATED`; thereafter, weigh-outs with no other `ACTIVE` agreement covering their date fail with `ERR_ROYALTY_AGREEMENT_REQUIRED`.

Statement generation is also a `FinanceClerk` act, supplying the `site_id`, a `period_start`, and a `period_end`. Periods are half-open: a ticket belongs to the period when its `completed_at` falls on or after `period_start` and strictly before `period_end`. A site's non-`VOID` statement periods must not overlap under that half-open comparison (`ERR_STATEMENT_PERIOD_OVERLAP`) and must be generated in chronological order — a new `period_start` earlier than an existing statement's `period_end` is rejected with `ERR_STATEMENT_NOT_CHRONOLOGICAL`. An `ACTIVE` agreement must cover the period (`ERR_ROYALTY_AGREEMENT_REQUIRED`), and that agreement is pinned onto the statement as `royalty_agreement_id` at generation, so later amendments do not disturb a generated statement. The generator is recorded in `generated_by_user_id`, and the statement is born `DRAFT` with `issued_by_user_id`, `issued_on`, `due_on`, `paid_on`, and `penalty_usd` unset.

The statement's figures are computed at generation. The input set is the site's tickets standing `COMPLETED` — voided tickets are never included — with `completed_at` inside the half-open period, processed in chronological order by `completed_at` with ties broken by `created_at` ascending; order matters because of the year-to-date tier. The running total starts at `ytd_tons_before`: the sum of `tons_sold` over the site's other non-`VOID` statements whose `period_start` lies in the same calendar year as this statement's `period_start` and is strictly earlier, ties among them broken by `created_at` ascending. Each ticket in turn is split at the tier threshold against the running total: the below-tier portion is the smaller of the ticket's `net_tons` and the distance remaining from the running total up to `tier_threshold_tons`, floored at zero when the threshold is already passed, and the above-tier portion is whatever tonnage remains. The ticket's royalty is the below-tier portion times `base_rate_per_ton` plus the above-tier portion times `tier_rate_per_ton`, rounded half-up to two decimals per ticket, and the running total then advances by the ticket's full `net_tons`. The statement's `royalty_due_usd` is the sum of those per-ticket rounded amounts, `tons_sold` is the sum of the swept tickets' `net_tons`, and `ytd_tons_after` is `ytd_tons_before` plus `tons_sold`. The rounding order is part of the contract: each ticket is rounded to cents first and the cents are summed — summing tonnage first and rounding once yields different cents and is wrong. This final variant diverges from the provisional weigh-out accrual of §3.7 exactly when the year-to-date tier is crossed inside the period, since the provisional figure never applies the tier rate.

Issuance is segregated: a `SiteManager` issues a `DRAFT` statement, and the issuer must not be the clerk recorded as generator (`ERR_SOD_VIOLATION`). Issuance moves the statement `DRAFT` → `ISSUED`, records `issued_by_user_id`, stamps `issued_on` from the logical date, and sets `due_on` thirty days after `issued_on`. Payment is recorded by a `FinanceClerk` with a `paid_on` date, moving the statement `ISSUED` → `PAID` and computing `penalty_usd`: zero when `paid_on` is on or before `due_on` — paying exactly on the due date incurs no penalty — and otherwise five percent of `royalty_due_usd`, rounded half-up to two decimals. A draft statement may instead be voided by a `FinanceClerk`, moving it `DRAFT` → `VOID`; the period then becomes available for regeneration, and `VOID` statements are excluded from the `ytd_tons_before` of every later statement. `PAID` and `VOID` are terminal.

### 3.9. MSHA Compliance: Inspections, Citations, Training, and the Posture Cascade

A `SafetyOfficer` opens an MSHA inspection against a site by supplying `site_id` and an `inspection_type` of `REGULAR`, `SPOT`, or `COMPLAINT`; the inspection is born `OPEN` with `opened_on` stamped from the logical date and `closed_on` unset. Citations are issued under an inspection that still stands `OPEN`, each carrying the `msha_inspection_id`, a 30 CFR `citation_code`, the significant-and-substantial flag `s_and_s`, and the `abatement_due_on` deadline. A citation is born `ISSUED` with `abated_on` unset, and it is overdue when its `abatement_due_on` falls earlier than the current logical date while it still stands `ISSUED`. Creating a citation recomputes the site's posture immediately, so an already-overdue significant-and-substantial citation suspends the site on the spot. Abatement, recorded with a payload `abated_on`, moves a citation `ISSUED` → `ABATED`; vacatur moves it `ISSUED` → `VACATED`. Both are terminal, both store their outcome, and both recompute the site's posture in the same request — which is what lifts a suspension when the last overdue significant-and-substantial citation clears. Closing the inspection moves it `OPEN` → `CLOSED` and stamps `closed_on`, but only once every citation of the inspection stands `ABATED` or `VACATED`; otherwise the close is rejected with `ERR_OPEN_CITATIONS`.

The posture rule, restated from §3.1 in enforcement terms, is what the cascades hang on: the site is `SUSPENDED` when any citation reachable through its inspections stands `ISSUED`, is flagged significant-and-substantial, and is past its abatement deadline; it is otherwise `RESTRICTED` when bond coverage is `DEFICIENT` or any citation stands `ISSUED`; and it is `OPERATING` otherwise. Entering `SUSPENDED` fires the hold cascade: every bench of the site standing `RELEASED` moves to `ON_HOLD` with `hold_reason` set to the sentinel value `MSHA_SUSPENSION`, and every shot plan on those benches standing `APPROVED`, `DRILLING`, `DRILLED`, or `LOADED` moves to `ON_HOLD` with its prior status captured in `hold_return_state`. Leaving `SUSPENDED` for `OPERATING` or `RESTRICTED` fires the recovery cascade: exactly the benches whose `hold_reason` is `MSHA_SUSPENSION` are released back to `RELEASED`, and their held shot plans return to their captured `hold_return_state`, which then clears to null. Benches held manually — any other `hold_reason` — are untouched by recovery and resume only through an explicit resume by a `SiteManager`.

Blaster qualification runs on training records. A `SafetyOfficer` records each completed course with the `miner_name`, the opaque `miner_user_id`, a `course_type` of `NEW_MINER`, `ANNUAL_REFRESHER`, or `TASK_TRAINING`, and the `completed_on` date. The record's `expires_on` is twelve months after `completed_on`, and `is_current` is true when `expires_on` falls on or after the current logical date — the expiry day itself still counts. Firing a shot, as gated in §3.3, requires the firing operator's `X-User-ID` to match the `miner_user_id` of some training record whose `course_type` is `TASK_TRAINING` and whose `is_current` is true; without one the firing is rejected with `ERR_TRAINING_EXPIRED`.

Because the logical clock can move without side effects, the site also offers a posture-recompute capability to `SiteManager` and `SafetyOfficer`: it re-derives the site's acreage, bond, adequacy, and posture figures from current citations, bonds, benches, and the logical clock, and fires the same hold and recovery cascades whenever the recomputed posture changes.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that act on an existing resource — transitions, completions, voids, recomputes — return `200 OK`. Amending a royalty agreement also returns `201 Created`, because the amendment is born as a new agreement resource. Endpoints marked "All roles" are readable by every declared role; all other endpoints accept exactly the roles listed.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/sites` | Create a quarry site | QuarryAdmin |
| GET | `/sites` | List sites (paginated) | All roles |
| GET | `/sites/{id}` | Get one site incl. computed posture/bond/acreage fields | All roles |
| POST | `/sites/{id}/recompute-posture` | Re-derive posture/bond fields; fires hold/resume cascades on change | SiteManager, SafetyOfficer |
| POST | `/benches` | Plan a bench | SiteManager |
| GET | `/benches` | List benches | All roles |
| GET | `/benches/{id}` | Get one bench | All roles |
| POST | `/benches/{id}/release` | Release a planned bench for mining | SiteManager |
| POST | `/benches/{id}/hold` | Manually hold a released bench | SiteManager |
| POST | `/benches/{id}/resume` | Resume a held bench | SiteManager |
| POST | `/benches/{id}/mark-mined-out` | Declare a bench mined out | SiteManager |
| POST | `/benches/{id}/start-reclamation` | Begin reclamation (half-rate bond phase) | SiteManager |
| POST | `/benches/{id}/complete-reclamation` | Complete reclamation | SiteManager |
| POST | `/shot-plans` | Create a drill/blast plan on a bench | BlastForeman |
| GET | `/shot-plans` | List shot plans | All roles |
| GET | `/shot-plans/{id}` | Get one shot plan | All roles |
| POST | `/shot-plans/{id}/submit` | Submit a plan for review | BlastForeman |
| POST | `/shot-plans/{id}/approve` | Approve a submitted plan | SiteManager |
| POST | `/shot-plans/{id}/start-drilling` | Begin drilling | BlastForeman |
| POST | `/shot-plans/{id}/complete-drilling` | Report all holes drilled | BlastForeman |
| POST | `/shot-plans/{id}/redrill` | Re-open drilling; drilled count resets | BlastForeman |
| POST | `/shot-plans/{id}/load` | Load explosives | BlastForeman |
| POST | `/shot-plans/{id}/fire` | Fire the shot; creates the muckpile | BlastForeman |
| POST | `/shot-plans/{id}/cancel` | Cancel a plan from DRAFT/SUBMITTED/APPROVED | BlastForeman |
| GET | `/muckpiles` | List muckpiles | All roles |
| GET | `/muckpiles/{id}` | Get one muckpile | All roles |
| POST | `/product-specs` | Create a product gradation spec | QuarryAdmin |
| GET | `/product-specs` | List specs | All roles |
| GET | `/product-specs/{id}` | Get one spec | All roles |
| POST | `/product-specs/{id}/retire` | Retire a spec | QuarryAdmin |
| POST | `/stockpiles` | Create a stockpile for a spec at a site | SiteManager |
| GET | `/stockpiles` | List stockpiles | All roles |
| GET | `/stockpiles/{id}` | Get one stockpile | All roles |
| POST | `/stockpiles/{id}/adjustments` | Manual inventory adjustment (OCC-guarded) | SiteManager |
| POST | `/stockpiles/{id}/close` | Close an empty stockpile | SiteManager |
| POST | `/gradation-tests` | Report a sieve analysis on a stockpile | QCTechnician |
| GET | `/gradation-tests` | List gradation tests | All roles |
| GET | `/gradation-tests/{id}` | Get one gradation test | All roles |
| POST | `/gradation-tests/{id}/confirm` | Confirm a reported test | QCTechnician |
| POST | `/gradation-tests/{id}/void` | Void a test; quarantine re-evaluated | QCTechnician |
| POST | `/scales` | Register a truck or belt scale | QuarryAdmin |
| GET | `/scales` | List scales | All roles |
| GET | `/scales/{id}` | Get one scale | All roles |
| POST | `/scale-calibrations` | Record a calibration; drives certification | QuarryAdmin |
| GET | `/scale-calibrations` | List calibrations | All roles |
| GET | `/scale-calibrations/{id}` | Get one calibration | All roles |
| POST | `/scale-calibrations/{id}/void` | Void a calibration; certification recomputed | QuarryAdmin |
| POST | `/plant-runs` | Schedule a plant run | PlantOperator |
| GET | `/plant-runs` | List plant runs | All roles |
| GET | `/plant-runs/{id}` | Get one plant run | All roles |
| POST | `/plant-runs/{id}/start` | Start a scheduled run | PlantOperator |
| POST | `/plant-runs/{id}/complete` | Close a run with input tons and outputs | PlantOperator |
| POST | `/plant-runs/{id}/reconcile` | Reconcile belt input against an independent figure | PlantOperator |
| POST | `/plant-runs/{id}/void` | Void a completed, unreconciled run | PlantOperator |
| POST | `/plant-runs/{id}/cancel` | Cancel a scheduled run | PlantOperator |
| POST | `/freight-zones` | Create a freight-inclusive pricing zone | QuarryAdmin |
| GET | `/freight-zones` | List zones | All roles |
| GET | `/freight-zones/{id}` | Get one zone | All roles |
| POST | `/freight-zones/{id}/deactivate` | Deactivate a zone | QuarryAdmin |
| POST | `/sales-orders` | Create a quote | SalesAgent |
| GET | `/sales-orders` | List orders | All roles |
| GET | `/sales-orders/{id}` | Get one order | All roles |
| POST | `/sales-orders/{id}/confirm` | Confirm a quote; reserves tons or backorders | SalesAgent |
| POST | `/sales-orders/{id}/cancel` | Cancel an order; releases the unfulfilled reservation | SalesAgent |
| POST | `/sales-orders/{id}/reprice` | Re-quote a QUOTED order (OCC-guarded) | SalesAgent |
| POST | `/scale-tickets` | Weigh-in: open a ticket for a called queue entry | ScaleHouseOperator |
| GET | `/scale-tickets` | List tickets | All roles |
| GET | `/scale-tickets/{id}` | Get one ticket | All roles |
| POST | `/scale-tickets/{id}/weigh-out` | Weigh-out: compute net tons, draw, fulfill, accrue royalty | ScaleHouseOperator |
| POST | `/scale-tickets/{id}/void` | Void a completed ticket; full compensation | SiteManager |
| POST | `/royalty-agreements` | Create the landowner royalty agreement for a site | FinanceClerk |
| GET | `/royalty-agreements` | List agreements | All roles |
| GET | `/royalty-agreements/{id}` | Get one agreement | All roles |
| POST | `/royalty-agreements/{id}/amendments` | Amend an ACTIVE agreement (create-with-supersede) | FinanceClerk |
| POST | `/royalty-agreements/{id}/terminate` | Terminate an ACTIVE agreement | FinanceClerk |
| POST | `/royalty-statements` | Generate the statement for a period | FinanceClerk |
| GET | `/royalty-statements` | List statements | All roles |
| GET | `/royalty-statements/{id}` | Get one statement | All roles |
| POST | `/royalty-statements/{id}/issue` | Issue a DRAFT statement | SiteManager |
| POST | `/royalty-statements/{id}/pay` | Record payment; late payment accrues penalty | FinanceClerk |
| POST | `/royalty-statements/{id}/void` | Void a DRAFT statement | FinanceClerk |
| POST | `/msha-inspections` | Open an MSHA inspection | SafetyOfficer |
| GET | `/msha-inspections` | List inspections | All roles |
| GET | `/msha-inspections/{id}` | Get one inspection | All roles |
| POST | `/msha-inspections/{id}/close` | Close an inspection | SafetyOfficer |
| POST | `/msha-citations` | Issue a citation under an open inspection | SafetyOfficer |
| GET | `/msha-citations` | List citations | All roles |
| GET | `/msha-citations/{id}` | Get one citation | All roles |
| POST | `/msha-citations/{id}/abate` | Abate a citation | SafetyOfficer |
| POST | `/msha-citations/{id}/vacate` | Vacate a citation | SafetyOfficer |
| POST | `/training-records` | Record MSHA training | SafetyOfficer |
| GET | `/training-records` | List training records | All roles |
| GET | `/training-records/{id}` | Get one training record | All roles |
| POST | `/reclamation-bonds` | Post a surety bond instrument | FinanceClerk |
| GET | `/reclamation-bonds` | List bonds | All roles |
| GET | `/reclamation-bonds/{id}` | Get one bond | All roles |
| POST | `/reclamation-bonds/{id}/release` | Release bond amount (OCC-guarded) | FinanceClerk |
| POST | `/queue-entries` | Truck arrival: join the scale-house queue | ScaleHouseOperator |
| GET | `/queue-entries` | List queue entries | All roles |
| GET | `/queue-entries/{id}` | Get one queue entry | All roles |
| POST | `/queue-entries/call-next` | Dispatch the next truck per the dispatch selector | ScaleHouseOperator |
| POST | `/queue-entries/{id}/begin-scale-out` | Loaded truck proceeds to the outbound scale | ScaleHouseOperator |
| POST | `/queue-entries/{id}/mark-no-show` | Mark a QUEUED truck as no-show | ScaleHouseOperator |
| POST | `/_clock/set_current_utc` | Set the logical clock | QuarryAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflows that raise them in §2 and §3; this catalogue fixes only the identifier and the HTTP status.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_SITE_POSTURE_BLOCKED` | 409 |
| `ERR_TRAINING_EXPIRED` | 409 |
| `ERR_PERMIT_ACREAGE_EXCEEDED` | 409 |
| `ERR_OUTSIDE_BLAST_WINDOW` | 422 |
| `ERR_SCALE_NOT_CERTIFIED` | 409 |
| `ERR_BENCH_NOT_RELEASED` | 409 |
| `ERR_BENCH_SEQUENCE_VIOLATION` | 409 |
| `ERR_ACTIVE_SHOT_PLAN` | 409 |
| `ERR_HOLES_INCOMPLETE` | 422 |
| `ERR_MUCKPILE_DEPLETED` | 409 |
| `ERR_STOCKPILE_EXISTS` | 409 |
| `ERR_STOCKPILE_QUARANTINED` | 409 |
| `ERR_STOCKPILE_NOT_EMPTY` | 409 |
| `ERR_STOCKPILE_CAPACITY_EXCEEDED` | 409 |
| `ERR_ADJUSTMENT_BELOW_RESERVED` | 409 |
| `ERR_SPEC_RETIRED` | 409 |
| `ERR_ZONE_INACTIVE` | 409 |
| `ERR_OVER_SHIPMENT` | 409 |
| `ERR_TRUCK_OVERWEIGHT` | 422 |
| `ERR_TARE_VARIANCE` | 422 |
| `ERR_STATEMENT_LOCKED` | 409 |
| `ERR_STATEMENT_PERIOD_OVERLAP` | 409 |
| `ERR_STATEMENT_NOT_CHRONOLOGICAL` | 409 |
| `ERR_ROYALTY_AGREEMENT_REQUIRED` | 409 |
| `ERR_AGREEMENT_ALREADY_ACTIVE` | 409 |
| `ERR_BOND_BELOW_REQUIRED` | 409 |
| `ERR_OPEN_CITATIONS` | 409 |
| `ERR_OUTPUT_IMBALANCE` | 422 |
| `ERR_CIRCUIT_OVERLAP` | 409 |
| `ERR_TRUCK_ALREADY_QUEUED` | 409 |
| `ERR_QUEUE_EMPTY` | 409 |
| `ERR_SOD_VIOLATION` | 403 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_REVERSAL_BLOCKED` | 409 |
