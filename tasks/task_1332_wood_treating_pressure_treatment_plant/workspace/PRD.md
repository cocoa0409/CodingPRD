# Wood Treating Plant API — Product Requirements Document

## 1. Introduction

Treated lumber leaves a plant with two promises attached: a chemical one — that preservative retention meets the standard demanded by the lumber's use category — and a documentary one — that an independent agency can audit how that retention was achieved. A modern pressure-treatment plant runs those promises across a busy floor: cylinders cycling around the clock, bulk preservative tanks whose assays drift, custom-treat customers sending their own material in on credit, drip pads catching hazardous drippage, and agency inspectors arriving on their own schedule. Paper logs and tribal knowledge do not survive that audit.

This document specifies the Wood Treating Plant API, the system of record for that operation. It governs plant registration and license posture; cylinder fleet management and schedule slotting; preservative concentrate stewardship from receipt through assay, replenishment, quarantine, and depletion; charge composition by species group and use category; treatment-cycle execution and retention verification; incising, drip-pad dwell, tagging, and warranty registration; and the supervisory apparatus of customer credit, hazardous-waste liability, and agency inspection. The API mounts plant-scoped resources under `/treatment-plants`, customer accounts under `/customers`, and two administrative test-driving hooks under `/_clock` and `/_charges`.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and boilerplate that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the capacity in which they act. Six roles are recognized, spelled exactly as follows: `PlantOperator`, who runs the physical plant — loading charges, running cycles, incising and tagging lumber, and booking cylinder slots; `LabTechnician`, who runs the wet lab, assaying and quarantining preservative concentrates and recording retention assays; `QualityManager`, the plant-side quality owner who orders re-treats, rejections, and scraps; `QualityAgencyInspector`, the third-party agency inspector (from ALSC, SPIB, TPI, or WCLIB) who schedules and executes inspections; `ComplianceOfficer`, the regulator-level role that registers plants and suspends, reinstates, or revokes their licenses; and `AccountsReceivable`, the customer-finance role that opens customer accounts, records payments, and settles liability. A request missing either header, or carrying a syntactically invalid header value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (400). A request whose role is not permitted on the target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (403).

For every one of these roles — `PlantOperator`, `LabTechnician`, `QualityManager`, `QualityAgencyInspector`, `ComplianceOfficer`, and `AccountsReceivable` alike — the `X-User-ID` value is an opaque operator identifier that is not tied to any persisted entity. The server may record it for traceability (for example, as `registered_by_user_id` on a WarrantyRegistration, where a transition writes it) but never compares it against any entity's `id`.

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

### 2.3. Pagination, Sorting, and List Filtering

List endpoints paginate through two query parameters. `limit` sets the maximum number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and caps at 100. `offset` sets how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order — oldest first. The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

Beyond pagination, most listings accept filters keyed to the resource. A `status` filter is accepted by the plant, cylinder, preservative, customer, charge, piece, cycle, inspection, and warranty listings. Inspection listings add `severity`. Charge listings add `use_category`, `customer_id`, and `cylinder_id`. Piece, cycle, assay, drip pad log, warranty, and slot listings accept `charge_id`; cycle listings also accept `preservative_id`, and assay listings accept `cycle_id`. Slot listings accept `slot_kind`; the filtered slot listing adds `cylinder_id` and `charge_id`, and the cylinder-scoped slot listings accept `from_iso` and `to_iso` to bound the window of interest. Drip pad log listings accept `containment_breach`. The filtered cylinder, preservative, and inspection listings accept `plant_id`.

### 2.4. Resource Identity and Common Properties

Every primary resource carries four system-managed properties. `id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created. `updated_at` is the same format, refreshed upon any change to the resource's properties. `version` is a system-managed integer that increments with every modification to the resource, whether the mutation is client-driven or system-driven — automatic status transitions and computed-field updates count as mutations and therefore refresh `updated_at` and advance `version`. Three resources are exceptions by design: a RetentionAssay, a DripPadLog, and a CylinderScheduleSlot each carry only `id` and `created_at`; both `updated_at` and `version` are absent from them, and nothing about them is mutable after creation.

### 2.5. Licensing Posture and the Plant Compliance Score

A treatment plant is registered under its `plant_name` and `alsc_license_number` and immediately enters `LICENSED` status with a `compliance_score` of 1000 and a `hazardous_waste_liability_cents` ledger of zero. The compliance score only moves downward from there: issued inspection findings deduct 200 points at `CRITICAL` severity, 100 at `MAJOR`, and 25 at `MINOR`; a large containment breach deducts 50; scrapping a charge deducts 100. The score is floored at zero — any deduction that would take it negative clamps at 0. Once the score sits at or below 300 the plant is exposed to suspension, and only at exactly 0 can its license be revoked; §3.1 details those mechanics.

Licensing posture gates production. Four operations require the plant to be `LICENSED` and are rejected with `ERR_PLANT_NOT_LICENSED` (409) when it is not: loading a charge into a cylinder, starting a treatment cycle, ordering a re-treat, and registering a warranty. The liability ledger accrues remediation charges from containment events and scrap disposals; an `AccountsReceivable` operator settles it back to zero when the plant has paid for its remediation.

### 2.6. Numerical Precision and Rounding

Retention chemistry is specified at three decimal places. `target_retention_pcf`, `provisional_retention_pcf`, `final_retention_pcf`, `mean_retention_pcf`, `min_sample_retention_pcf`, and `pass_threshold_pcf` are all carried to three decimals with round-half-up, applied only after the underlying multiplications finish; the final-retention workflow adds an intermediate four-decimal rounding at the per-piece level (see §3.7). Money is integer cents throughout: registration fees and drip-pad liabilities round half-up to whole cents, and the registration fee rounds at each multiplication step in its pinned order (see §3.8). Cylinder capacity is an exact numeric comparison with no rounding. Schedule-slot boundaries compare UTC timestamps at millisecond precision.

### 2.7. Optimistic Concurrency Control on Charge-Mutating Writes

Two write endpoints carry an optimistic-concurrency obligation, and both concern the Charge. A request to `POST /treatment-plants/{plantId}/charges/{chargeId}/order-retreat` must include `expected_charge_version`, a non-optional field carrying the `version` of the charge as the `QualityManager` last observed it; if the charge's current `version` has advanced beyond that value, the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing a re-treat from being ordered against a charge the requester has not re-read. The same rule binds `POST /treatment-plants/{plantId}/charges/{chargeId}/warranty-registrations`: the request must carry `expected_charge_version` matching the charge's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). A charge's `version` advances whenever a retention assay is recorded against it, a re-treat is ordered, a tag is applied, or a warranty is registered — each of these invalidates prior warranty and re-treat calculations, which is exactly what the stale-version rejection protects. Endpoints not listed in this subsection take no version field at all.

### 2.8. Nested Path Resolution and Existence Checking

Requests that target nested resources are validated left-to-right along the path. Each path-templated identifier — `plantId`, `cylinderId`, `preservativeId`, `customerId`, `chargeId`, `pieceId`, `cycleId`, `assayId`, `inspectionId`, `logId`, `warrantyId`, `slotId` — is resolved in order, and the request is rejected immediately with the 404 corresponding to the first identifier that does not resolve: `ERR_PLANT_NOT_FOUND`, `ERR_CYLINDER_NOT_FOUND`, `ERR_PRESERVATIVE_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, `ERR_CHARGE_NOT_FOUND`, `ERR_PIECE_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND`, `ERR_ASSAY_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, `ERR_DRIP_LOG_NOT_FOUND`, `ERR_WARRANTY_NOT_FOUND`, or `ERR_SLOT_NOT_FOUND`. A request addressed to a charge beneath a non-existent plant therefore fails with `ERR_PLANT_NOT_FOUND` before the charge is ever consulted. Alongside the deeply nested paths, every resource is also addressable through a flat retrieval route under the API mount (for example, a cylinder via `/treatment-plants/cylinders/{cylinderId}`), and the same left-to-right existence rule applies there.

### 2.9. Validation Evaluation Order

When several validation rules apply to a single request, the server evaluates them in a fixed order and surfaces only the first failure. Request shaping comes before the ordered cascade: a malformed body, a missing required field, or a value outside a declared enum set is rejected up front with `ERR_INVALID_REQUEST` (400) or `ERR_INVALID_ENUM` (400). The ordered cascade itself then runs as follows:

1. Header presence and syntactic validity — `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (400).
2. Role authorization for the target endpoint — `ERR_INSUFFICIENT_PERMISSIONS` (403).
3. Path existence, left to right — the resource-specific 404 family of §2.8.
4. Plant licensing, where the operation requires it — `ERR_PLANT_NOT_LICENSED` (409).
5. Resource state preconditions — a state-specific 409 such as `ERR_CYLINDER_NOT_IDLE`, `ERR_CYLINDER_NOT_LOADED`, `ERR_CYCLE_NOT_RUNNING`, `ERR_CYCLE_NOT_DRAINING`, `ERR_CHARGE_NOT_ASSAYED_PASS`, `ERR_CHARGE_NOT_TAGGED`, `ERR_CHARGE_NOT_ASSAYED_FAIL`, `ERR_INSPECTION_NOT_SCHEDULED`, or `ERR_INSPECTION_NOT_IN_PROGRESS`, with `ERR_INVALID_STATE` (409) as the generic form when a resource is simply not in a valid from-state.
6. Cylinder capacity on charge loading — `ERR_CYLINDER_CAPACITY_EXCEEDED` (409).
7. Schedule-slot overlap on slot booking — `ERR_CYLINDER_SLOT_CONFLICT` (409).
8. Working-solution assay minimum at cycle start — `ERR_ASSAY_BELOW_WORKING_MINIMUM` (422).
9. Preservative quarantine at cycle start — `ERR_PRESERVATIVE_QUARANTINED` (422).
10. Incising completeness at tagging — `ERR_INCISING_REQUIRED` (422).
11. Drip-pad containment at tagging — `ERR_DRIP_PAD_CONTAINMENT_BREACH` (422).
12. Drip-pad dwell duration at tagging — `ERR_DRIP_DWELL_TOO_SHORT` (422).
13. Inspection window at inspection begin — `ERR_INSPECTION_WINDOW_MISSED` (409).
14. Assay-to-cycle referential match — `ERR_ASSAY_CYCLE_MISMATCH` (422).
15. Slot-to-charge referential validity — `ERR_SLOT_CHARGE_INVALID` (422).
16. Slot presence for a loading charge — `ERR_NO_SLOT_FOR_CHARGE` (409).
17. Customer credit standing — `ERR_CUSTOMER_CREDIT_HOLD` (402).
18. Re-treat eligibility — `ERR_RETREAT_NOT_PERMITTED` (422).
19. Optimistic-concurrency staleness — `ERR_STALE_VERSION` (412).

The ordering is observable. A re-treat order against a suspended plant reports `ERR_PLANT_NOT_LICENSED` even if the charge's version is also stale, because licensing outranks staleness; a stale version is reported only after every business rule ahead of it has passed.

### 2.10. Logical Time and Test-Driving Hooks

Time-gated rules in this system — drip-pad dwell, inspection windows, slot boundaries — all read a single server-side logical clock. A `ComplianceOfficer` may set that clock through an administrative capability that accepts `to_iso8601`, an ISO 8601 UTC timestamp, and makes it the server's current instant; before any such call, the logical clock defaults at server startup to exactly 2026-08-01T00:00:00Z. A second `ComplianceOfficer`-only capability forces a Charge into an arbitrary state, bypassing the normal transition rules: the caller supplies `target_status`, the charge's `status` is set to that value, and the charge's `version` increments by 1. Both hooks exist so that time-gated and corner-case behavior can be exercised deterministically; they appear in §4 alongside the production endpoints.

## 3. Business Logic & Workflows

### 3.1. Plant Registration and License Governance

A `ComplianceOfficer` brings a plant onto the system by registering it with its `plant_name` and `alsc_license_number`. The new plant starts in `LICENSED` status, its `compliance_score` initialized to 1000 and its `hazardous_waste_liability_cents` ledger to zero. From that moment the plant's standing is a function of what happens on its floor: findings, breaches, and scraps erode the score per §2.5, and containment events accumulate in the liability ledger.

Suspension is a `ComplianceOfficer` action available while the plant is `LICENSED`, and it is warranted when the `compliance_score` has fallen to 300 or below, or when a `CRITICAL`-severity inspection stands in `FINDINGS_ISSUED`. Suspension moves the plant to `SUSPENDED` and freezes production in place: cylinders sitting `IDLE` are unaffected, but every `LOADED` or `CYCLE_RUNNING` cylinder is frozen — no new cycle may start on them — and any `SCHEDULED` inspection remains on the books yet cannot move to `IN_PROGRESS` until the plant is re-licensed.

Reinstatement, again by a `ComplianceOfficer`, moves a `SUSPENDED` plant back to `LICENSED`, but only once two conditions both hold: every open QualityInspection has reached `CLOSED_PASS`, and the liability ledger has been settled to zero — an `AccountsReceivable` operator performs that settlement, zeroing `hazardous_waste_liability_cents`. Reinstatement lifts the cylinder freeze. When a suspended plant's `compliance_score` reaches exactly 0, a `ComplianceOfficer` may instead revoke the license; `REVOKED` is terminal, and the cascade is severe: every cylinder moves to `DECOMMISSIONED` and every charge not already in a terminal state is moved to `SCRAPPED`.

### 3.2. Cylinder Fleet Management and Schedule Slotting

A `PlantOperator` registers each cylinder under its plant with a `cylinder_code` (the physical label, such as CYL-1), a `max_volume_mbf` capacity expressed in thousand board-feet, and the `supported_process_types` it can run — drawn from `FULL_CELL`, `LOWRY`, `RUEPING`, and `SAP_DISPLACEMENT`. A cylinder is born `IDLE` and walks a working loop: `IDLE` to `LOADED` when a charge enters, `LOADED` to `CYCLE_RUNNING` when a cycle starts, `CYCLE_RUNNING` to `DRAINING` when draining begins, and `DRAINING` to `NEEDS_CLEANING` when the cycle completes; aborting a running cycle likewise drops the cylinder to `NEEDS_CLEANING`. Only after the operator marks the cylinder cleaned does it return to `IDLE` — an act that also closes the cylinder's `CLEANING` slot — and only an `IDLE` cylinder with no future slot (no slot whose `slot_end` lies beyond the present moment) may be decommissioned, which is terminal.

Slotting disciplines the fleet. Booking a slot on a cylinder takes a `slot_start` and a `slot_end` that must be strictly later than the start (an inverted or empty window is rejected with `ERR_INVALID_TIME_RANGE`), a `slot_kind` of `TREATMENT`, `CLEANING`, or `MAINTENANCE`, an optional `charge_id`, and an optional `buffer_minutes` turnover buffer that defaults to 30 when omitted. When `charge_id` is present it must reference a charge currently in `STAGED` or `RE_TREAT_PENDING`; any other charge state is rejected with `ERR_SLOT_CHARGE_INVALID` (422).

Overlap is judged on effective intervals: each slot effectively occupies the half-open interval from its `slot_start` to its `slot_end` plus its `buffer_minutes`. A booking is rejected with `ERR_CYLINDER_SLOT_CONFLICT` (409) when its effective interval intersects the effective interval of any other slot on the same cylinder — intersection meaning the new slot's start falls before the existing slot's effective end and the existing slot's start falls before the new slot's effective end. Because the intervals are half-open, a new slot whose start coincides exactly with an existing slot's effective end is merely adjacent, not overlapping, and is permitted. Only slots whose `slot_end` lies in the future participate in the comparison; past slots are ignored. `CLEANING` and `MAINTENANCE` slots block `TREATMENT` slots under the same rule, and two `TREATMENT` slots may never overlap each other on one cylinder. All comparisons use UTC timestamps at millisecond precision.

A slot may be cancelled, but only while its `slot_start` still lies in the future; cancelling a slot whose start has passed is rejected with `ERR_SLOT_IN_PAST` (409), and a successful cancellation removes the slot and answers 204 No Content. Slot listings on a cylinder may be filtered by `slot_kind` or bounded by `from_iso` and `to_iso`.

### 3.3. Preservative Concentrates and Working-Solution Assay

A `LabTechnician` registers each preservative concentrate with its `chemical_family` — one of `CCA`, `ACQ`, `CA`, `CREOSOTE`, or `PENTA` — its `concentrate_assay_pct` (active-ingredient concentration, between 0 and 100), the starting `inventory_gallons` (0 if the tank begins empty), and the `min_working_assay_pct` below which the concentrate may not feed a cycle. The concentrate enters `IN_STOCK`, or `LOW_STOCK` immediately if the registered inventory already sits below the plant's low-stock gallon threshold.

Inventory movement drives two automatic transitions. Whenever `inventory_gallons` falls below the low-stock threshold the concentrate moves from `IN_STOCK` to `LOW_STOCK` on its own; when replenishment lifts it back above the threshold it returns from `LOW_STOCK` to `IN_STOCK` just as automatically. A `LOW_STOCK` concentrate whose tank reaches exactly zero gallons becomes `DEPLETED`, which is terminal.

Re-assaying is a `LabTechnician` action that supplies `new_assay_pct`: the concentrate's `concentrate_assay_pct` is overwritten with that value and the concentrate's `version` increments by 1. Replenishment supplies `additional_gallons`, which is added to `inventory_gallons` and may trigger the automatic return from `LOW_STOCK` to `IN_STOCK` described above.

Quarantine is the lab's containment tool. When a re-assay shows the concentrate has drifted below its own `min_working_assay_pct`, or contamination is suspected, a `LabTechnician` quarantines it with a recorded `reason`, moving it from `IN_STOCK` to `QUARANTINED`. The consequence lands at the cylinder: any `SCHEDULED` cycle that references the quarantined concentrate is blocked when an operator tries to start it, rejected with `ERR_PRESERVATIVE_QUARANTINED` (422). Release from quarantine is equally deliberate — a confirming re-assay must show `concentrate_assay_pct` at or above `min_working_assay_pct` before the lab releases the concentrate back to `IN_STOCK`.

### 3.4. Customer Accounts and Credit Discipline

Custom-treat work runs on credit, and `AccountsReceivable` owns the ledger. Opening a customer account takes the `customer_name` and a `credit_limit_cents` cap; the account starts `ACTIVE` with an `outstanding_balance_cents` of zero.

The account watches its own exposure. The moment `outstanding_balance_cents` exceeds `credit_limit_cents`, the account moves automatically from `ACTIVE` to `CREDIT_HOLD`, and from then on any attempt to create a new custom-treat charge for that customer is rejected with `ERR_CUSTOMER_CREDIT_HOLD` (402). Recording a payment subtracts the supplied `amount_cents` from `outstanding_balance_cents`; when the resulting balance falls back to at or below the credit limit, the account automatically returns from `CREDIT_HOLD` to `ACTIVE`. Closing an account is permitted only when `outstanding_balance_cents` is exactly zero — otherwise the close is rejected with `ERR_CUSTOMER_BALANCE_NOT_ZERO` (409) — and when no charge in a non-terminal state still references the customer. `CLOSED` is terminal.

### 3.5. Composing and Loading a Charge

A `PlantOperator` composes a charge by declaring its `ownership_type` — `PLANT_STOCK` for the plant's own inventory or `CUSTOM_TREAT` for customer material — its `species_group` (`SPF`, `SYP`, `DOUGLAS_FIR`, `HEM_FIR`, or `PONDEROSA_PINE`), its `use_category` (`UC3B`, `UC4A`, `UC4B`, or `UC4C`, which drives the retention target), and its `volume_mbf` in thousand board-feet. For custom-treat work the payload also carries the `customer_id`; plant-owned stock leaves it absent. A `piece_manifest` enumerates the physical tally, one entry per piece carrying its `piece_tag`, `length_ft`, `width_in`, and `thickness_in`.

Several properties are derived the moment the charge is composed. The `target_retention_pcf` comes from a fixed lookup keyed by `use_category`. The `requires_incising` flag is true precisely when the species group is `DOUGLAS_FIR` or `HEM_FIR` and the use category is `UC4B` or `UC4C`. The `is_custom_treat` flag mirrors whether `ownership_type` is `CUSTOM_TREAT`. The `provisional_retention_pcf` and `final_retention_pcf` both start at 0, each piece's `penetration_pct` starts at 0 with `incised` false, and the charge's `hazard_containment_flag` starts false.

Loading the charge into a cylinder is guarded end to end. The plant must be `LICENSED` (§2.5). The cylinder must be `IDLE` — loading against a busy cylinder fails with `ERR_CYLINDER_NOT_IDLE` (409). Capacity is checked exactly: the cylinder's current loaded volume is the sum of `volume_mbf` across the charges physically present in it, meaning those in `IN_CYLINDER` or `CYCLE_COMPLETE` status, summed oldest-first by creation for determinism, and the load is rejected with `ERR_CYLINDER_CAPACITY_EXCEEDED` (409) only when that current total plus the new charge's `volume_mbf` is strictly greater than `max_volume_mbf` — a total exactly equal to the maximum is permitted. A `TREATMENT` slot must exist on the cylinder whose window covers the requested treatment start through the estimated cycle and whose `charge_id` matches the charge being loaded; its absence is `ERR_NO_SLOT_FOR_CHARGE` (409). And a custom-treat charge requires its customer account to be `ACTIVE`, failing with `ERR_CUSTOMER_CREDIT_HOLD` (402) otherwise.

A successful load is atomic in effect: the charge, which begins `STAGED`, moves immediately to `IN_CYLINDER`, the cylinder moves to `LOADED`, the ChargePiece rows are auto-created from the manifest in `RAW` status, and both the cylinder's `version` and the charge's `version` increment.

### 3.6. Executing the Treatment Cycle

With a charge in the cylinder, a `PlantOperator` schedules a treatment cycle by naming the `process_type` (`FULL_CELL`, `LOWRY`, `RUEPING`, or `SAP_DISPLACEMENT`), the `preservative_id` of the concentrate to run, and the cycle parameters `vacuum_inhg` (initial vacuum, in inches of mercury), `pressure_psi` (peak pressure), and `pressure_minutes` (hold time at pressure). The cycle enters `SCHEDULED` with a `cycle_number` of 1 for a charge's first treatment or one greater than the previous cycle's number for a re-treat, and its `gross_absorption_pcf` sits at 0 until completion supplies the measured value; scheduling leaves the cylinder `LOADED`, moving it there first if it had drifted back to `IDLE`.

Starting the cycle is the chemically committed step, and three guards stand in front of it. The cylinder must be `LOADED` (otherwise `ERR_CYLINDER_NOT_LOADED`, 409). The referenced concentrate must be `IN_STOCK`; a quarantined concentrate blocks the start with `ERR_PRESERVATIVE_QUARANTINED` (422). And the concentrate's `concentrate_assay_pct` must be at least its `min_working_assay_pct` — a weaker solution is rejected with `ERR_ASSAY_BELOW_WORKING_MINIMUM` (422). On a successful start the cycle's `solution_assay_at_start_pct` snapshots the concentrate's assay at that instant, the cycle's estimated consumption is subtracted from the concentrate's `inventory_gallons` (which may in turn trigger the automatic stock-level transitions of §3.3), the cycle moves to `RUNNING`, and the cylinder moves to `CYCLE_RUNNING`.

Draining and completing unwind the run in order. Beginning the drain requires the cycle to be `RUNNING` (otherwise `ERR_CYCLE_NOT_RUNNING`, 409) and moves both cycle and cylinder to `DRAINING`. Completing the cycle requires it to be `DRAINING` (otherwise `ERR_CYCLE_NOT_DRAINING`, 409); the operator supplies the measured `gross_absorption_pcf` — solution uptake per cubic foot of wood — and completion moves the cycle to `COMPLETE`, the cylinder to `NEEDS_CLEANING` (where it must be cleaned before accepting another load), and the parent charge to `CYCLE_COMPLETE`. At that moment the charge's `provisional_retention_pcf` is computed forward-looking: the cycle's `gross_absorption_pcf` is multiplied by the working-solution strength expressed as a fraction — `solution_assay_at_start_pct` divided by one hundred — and by the species penetration factor, piece by piece. The factor is 0.85 for `SPF`, 0.92 for `SYP`, 0.65 for `DOUGLAS_FIR`, 0.72 for `HEM_FIR`, and 0.78 for `PONDEROSA_PINE`; where the charge's `requires_incising` is true and the individual piece's `incised` flag is true, the higher incised factor applies to that piece's contribution instead — 0.95 for `DOUGLAS_FIR` and 0.93 for `HEM_FIR`. The charge-level provisional figure is the average of the per-piece contributions, and the rounding to three decimal places, half-up, happens only after all multiplications are complete.

A run can also be abandoned: aborting requires a recorded `abort_reason` and moves the cycle from `RUNNING` to `ABORTED`. The cylinder drops to `NEEDS_CLEANING`, the parent charge remains `IN_CYLINDER`, and — pointedly — the preservative already consumed is not refunded to the tank.

### 3.7. Laboratory Assay, Verdicts, and the Re-Treat Loop

Once a charge reports `CYCLE_COMPLETE`, a `LabTechnician` records a retention assay against it. The record names the `cycle_id` being assayed — which must reference a cycle belonging to this same charge, or the recording is rejected with `ERR_ASSAY_CYCLE_MISMATCH` (422) — the `assay_method` (`XYLENE_EXTRACTION`, `ASHING`, or `TITRATION`), the `sample_count` of core samples taken, the `mean_retention_pcf` across samples, the `min_sample_retention_pcf` of the weakest individual sample, who recorded it (`recorded_by_agency`, either `PLANT_LAB` or `THIRD_PARTY_AGENCY`), and the `recorded_at` timestamp. Each piece's `penetration_pct` captures the assay's penetration measurement for that piece.

The verdict derives from a single rule. The assay's `pass_threshold_pcf` is ninety percent of the charge's `target_retention_pcf`. The `outcome` is `PASS` when `mean_retention_pcf` is at least `target_retention_pcf` and `min_sample_retention_pcf` is at least `pass_threshold_pcf`; it is `FAIL_MARGINAL` when `mean_retention_pcf` is at least `pass_threshold_pcf` yet still below `target_retention_pcf` while `min_sample_retention_pcf` falls below `pass_threshold_pcf`; and it is `FAIL_GROSS` when `mean_retention_pcf` is below `pass_threshold_pcf`. The boundaries are inclusive at both ends — a mean exactly equal to the target is a `PASS`, provided the minimum sample also meets the threshold.

Recording the assay moves the charge: `CYCLE_COMPLETE` to `ASSAYED_PASS` on a `PASS`, or to `ASSAYED_FAIL` on either failing verdict, and the pieces follow their parent from `TREATED` to the matching assay state. Either way the charge's `final_retention_pcf` is fixed. It is anchored to the assay's `mean_retention_pcf`, but the stored charge-level value is recomputed as a volume-weighted mean across the charge's pieces: each piece's retention is the recorded mean multiplied by that piece's applicable species factor — the incised factor when the piece is incised, otherwise the base factor — divided by the charge-wide average species factor; each piece's volume in cubic feet is its `length_ft` times its `width_in` times its `thickness_in` divided by twelve; and the charge-level figure is the sum of each piece's retention times its volume, divided by the sum of the piece volumes. Pieces are processed oldest first by their `created_at`, pieces in `SCRAPPED` status are excluded, each per-piece contribution is rounded to four decimal places before the sum is taken, and the final ratio is then rounded half-up to three decimal places. That rounding order is load-bearing — rounding per piece first yields a different figure than summing raw and rounding once — and on a `FAIL_MARGINAL` verdict the provisional and final figures diverge by 0.05 pcf or more as a consequence of this per-piece rounding order together with the incised adjustments. Recording an assay also increments the charge's `version` by 1.

A failed charge is not necessarily lost. A `QualityManager` may order a re-treat, but only from `ASSAYED_FAIL` (any other charge state fails with `ERR_CHARGE_NOT_ASSAYED_FAIL`, 409), only while the plant is `LICENSED`, only when the last assay's `outcome` was `FAIL_MARGINAL` — a `FAIL_GROSS` charge may not be re-treated and must be scrapped — and only while the charge's `cycle_number` is still below 3; violating the eligibility rule is rejected with `ERR_RETREAT_NOT_PERMITTED` (422). The order must also carry `expected_charge_version` per §2.7, and a stale value is rejected with `ERR_STALE_VERSION` (412). Ordering the re-treat moves the charge to `RE_TREAT_PENDING`, voids every `ACTIVE` WarrantyRegistration on the charge — each moves to `VOIDED_BY_RETREAT` — and increments the charge's `version` by 1. To run the re-treat, a `TREATMENT` slot for it must exist, and scheduling the new cycle returns the charge from `RE_TREAT_PENDING` to `IN_CYLINDER` with a `cycle_number` one greater than the cycle before.

Two terminal dispositions sit on either side of the loop. When a charge's last assay was `FAIL_GROSS`, or the re-treat allowance is exhausted because `cycle_number` has reached 3, a `QualityManager` scraps the charge: it moves to `SCRAPPED`, its `ASSAYED_FAIL` pieces move to `SCRAPPED` with it, its `volume_mbf` times seventy-five thousand cents per mbf (a $750-per-mbf disposal cost) is added to the plant's `hazardous_waste_liability_cents`, and the plant's `compliance_score` drops by 100, clamped at zero. Separately, from `CYCLE_COMPLETE`, a `QualityManager` may reject a charge outright when a `CRITICAL` finding from an agency inspection cites it; rejection moves the charge to `REJECTED`, and the cylinder still holding it moves to `NEEDS_CLEANING`.

### 3.8. Incising, Drip-Pad Containment, Tagging, and Release

Some lumber will not take preservative without mechanical help. When a charge's `requires_incising` is true, a `PlantOperator` incises each piece while the charge is `STAGED` or `IN_CYLINDER`; the operation sets the piece's `incised` flag true and moves it from `RAW` to `INCISED`. When the parent charge later completes its cycle, every piece — whether still `RAW` or already `INCISED` — moves to `TREATED`.

Out of the cylinder, freshly treated lumber drips, and the drip pad is where containment is proven. A `PlantOperator` logs each dwell with the `pad_code`, the `entered_pad_at` and `exited_pad_at` timestamps (exit must be strictly later than entry, or the log is rejected with `ERR_INVALID_TIME_RANGE`), the recovered `drip_volume_liters`, and an optional `containment_breach` flag that defaults to false. The log's `liability_cents` starts at 0 and stays there for an uneventful dwell. A breach is expensive and precise: the log's `liability_cents` is the `drip_volume_liters` multiplied by 250 cents per liter ($2.50/L), rounded half-up to whole cents, and that amount is added to the plant's `hazardous_waste_liability_cents` while the charge's `hazard_containment_flag` is set true. When the spilled `drip_volume_liters` exceeds 50 liters, a 250000-cent surcharge ($2,500) is added on top and the plant's `compliance_score` drops by 50, never below zero.

Tagging applies the end-tag and end-plate that make a charge saleable, and it is gated three deep. The charge must be `ASSAYED_PASS` (otherwise `ERR_CHARGE_NOT_ASSAYED_PASS`, 409). If `requires_incising` is true, every piece must already be incised — a single missed piece fails the tag with `ERR_INCISING_REQUIRED` (422). The drip-pad record must show no containment breach — a latest log with `containment_breach` true fails with `ERR_DRIP_PAD_CONTAINMENT_BREACH` (422) — and the dwell itself, `exited_pad_at` minus `entered_pad_at`, must be at least 24 hours, failing with `ERR_DRIP_DWELL_TOO_SHORT` (422) when shorter. A successful tag moves the charge to `TAGGED` and each `ASSAYED_PASS` piece to `TAGGED` with it.

Release is a commercial act as much as a physical one. A `PlantOperator` registers the warranty with the `registered_by_user_id` of the operator recording it and a `warranty_term_years` of 5, 25, or 50. The charge must be `TAGGED` (otherwise `ERR_CHARGE_NOT_TAGGED`, 409), the request must carry `expected_charge_version` per §2.7 — a stale value fails with `ERR_STALE_VERSION` (412) — and for a custom-treat charge the customer account must be `ACTIVE` with enough headroom that posting the fee does not push `outstanding_balance_cents` past `credit_limit_cents`, failing with `ERR_CUSTOMER_CREDIT_HOLD` (402) otherwise. The `registration_fee_cents` is computed in a pinned order: start from the base fee for the charge's `use_category` — 1500 cents for `UC3B`, 3200 for `UC4A`, 5800 for `UC4B`, 9100 for `UC4C`; apply the volume discount keyed to `volume_mbf` — none at ten mbf or below, five percent off the base above ten and up to and including fifty mbf, twelve percent off above fifty; then apply the custom-treat uplift of eighteen percent when `is_custom_treat` is true (nothing when it is not); then multiply by the warranty-term multiplier — 1.00 for five years, 1.45 for twenty-five, 1.95 for fifty. Each multiplication is rounded half-up to whole cents before the next factor is applied, and applying the factors in any other order can yield a different cent figure and is non-conformant. Registration moves the charge to `RELEASED`, moves each `TAGGED` piece to `RELEASED`, debits the fee for custom-treat work by adding `registration_fee_cents` to the customer's `outstanding_balance_cents`, and increments the charge's `version` by 1. The warranty itself starts `ACTIVE` and ends one of two ways: it lapses to `LAPSED` when its `warranty_term_years` elapse from the registration date, or it is voided to `VOIDED_BY_RETREAT` the moment a re-treat is ordered against its charge, as §3.7 describes.

### 3.9. Agency Inspections and Compliance Enforcement

Oversight arrives on a schedule the plant does not control. A `QualityAgencyInspector` — or a `ComplianceOfficer` — schedules an inspection with the `agency_code` (`ALSC`, `SPIB`, `TPI`, or `WCLIB`), the `inspection_window_start` and `inspection_window_end` (the end must be strictly later than the start, else `ERR_INVALID_TIME_RANGE`), the `charges_in_scope` listing the charge ids the agency sampled, an optional `findings_count` defaulting to 0, and the `severity` of `MINOR`, `MAJOR`, or `CRITICAL`. The inspection enters `SCHEDULED`.

Beginning the inspection is permitted only while the plant is `LICENSED` and only inside the declared window: a begin attempted outside the window is rejected with `ERR_INSPECTION_WINDOW_MISSED` (409), and a begin against an inspection that is not `SCHEDULED` fails with `ERR_INSPECTION_NOT_SCHEDULED` (409). A successful begin moves the inspection to `IN_PROGRESS`. Issuing findings requires the inspection to be `IN_PROGRESS` (otherwise `ERR_INSPECTION_NOT_IN_PROGRESS`, 409) and records a non-negative `findings_count` together with the `severity`, moving the inspection to `FINDINGS_ISSUED`. The severity lands directly on the plant's `compliance_score`: 200 points for `CRITICAL`, 100 for `MAJOR`, 25 for `MINOR`. A `CRITICAL` finding additionally arms the rejection path of §3.7 — each charge id in `charges_in_scope` may be moved to `REJECTED` by a `QualityManager`.

Closing the inspection resolves it one of two ways with equal weight. When the plant's remediation is accepted, the inspection closes `CLOSED_PASS`. When remediation is rejected, it closes `CLOSED_FAIL`, and if the plant's `compliance_score` then sits at or below 300 the plant is suspended automatically, moving to `SUSPENDED` with the production freeze of §3.1. From there the governance loop of §3.1 governs what happens next: remediation, settlement of the liability ledger, reinstatement — or, at a `compliance_score` of exactly 0, revocation.

## 4. Endpoint Definitions

Operations that create a new resource — a plant, cylinder, preservative, customer account, charge, cycle, retention assay, inspection, drip pad log, warranty registration, or schedule slot — return `201 Created`. Operations that modify or transition an existing resource return `200 OK`. Cancelling a future schedule slot returns `204 No Content` with an empty `data`. The table below is a structural index only; request payloads, derived fields, and side effects are defined by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/treatment-plants` | Register a new treatment plant | ComplianceOfficer |
| GET | `/treatment-plants` | List treatment plants | PlantOperator, LabTechnician, QualityManager, QualityAgencyInspector, ComplianceOfficer, AccountsReceivable |
| GET | `/treatment-plants/{plantId}` | Get a specific treatment plant | PlantOperator, LabTechnician, QualityManager, QualityAgencyInspector, ComplianceOfficer, AccountsReceivable |
| POST | `/treatment-plants/{plantId}/suspend` | Suspend a plant's license | ComplianceOfficer |
| POST | `/treatment-plants/{plantId}/reinstate` | Reinstate a suspended plant | ComplianceOfficer |
| POST | `/treatment-plants/{plantId}/revoke` | Revoke a plant's license (terminal) | ComplianceOfficer |
| POST | `/treatment-plants/{plantId}/settle-liability` | Zero out the hazardous-waste liability ledger | AccountsReceivable |
| GET | `/treatment-plants/{plantId}/cylinders` | List cylinders for a plant | PlantOperator, LabTechnician, QualityManager, QualityAgencyInspector, ComplianceOfficer |
| GET | `/treatment-plants/{plantId}/preservatives` | List preservatives for a plant | LabTechnician, PlantOperator, QualityManager, ComplianceOfficer |
| GET | `/treatment-plants/{plantId}/inspections` | List inspections for a plant | QualityAgencyInspector, ComplianceOfficer, QualityManager, PlantOperator, LabTechnician |
| POST | `/treatment-plants/{plantId}/cylinders` | Register a cylinder under a plant | PlantOperator |
| GET | `/treatment-plants/{plantId}/cylinders/{cylinderId}` | Get a specific cylinder | PlantOperator, LabTechnician, QualityManager, QualityAgencyInspector, ComplianceOfficer |
| POST | `/treatment-plants/{plantId}/cylinders/{cylinderId}/mark-cleaned` | Mark a NEEDS_CLEANING cylinder as cleaned (returns to IDLE) | PlantOperator |
| POST | `/treatment-plants/{plantId}/cylinders/{cylinderId}/decommission` | Decommission a cylinder (terminal) | PlantOperator |
| POST | `/treatment-plants/{plantId}/preservatives` | Register a preservative concentrate | LabTechnician |
| GET | `/treatment-plants/{plantId}/preservatives/{preservativeId}` | Get a specific preservative | LabTechnician, PlantOperator, QualityManager, ComplianceOfficer |
| POST | `/treatment-plants/{plantId}/preservatives/{preservativeId}/assay` | Re-assay the concentrate (updates its assay) | LabTechnician |
| POST | `/treatment-plants/{plantId}/preservatives/{preservativeId}/replenish` | Replenish inventory | LabTechnician |
| POST | `/treatment-plants/{plantId}/preservatives/{preservativeId}/quarantine` | Quarantine a preservative | LabTechnician |
| POST | `/treatment-plants/{plantId}/preservatives/{preservativeId}/release-quarantine` | Release a preservative from quarantine | LabTechnician |
| POST | `/customers` | Open a customer account | AccountsReceivable |
| GET | `/customers` | List customers | AccountsReceivable, PlantOperator, QualityManager, ComplianceOfficer |
| GET | `/customers/{customerId}` | Get a customer | AccountsReceivable, PlantOperator, QualityManager, ComplianceOfficer |
| POST | `/customers/{customerId}/record-payment` | Record a payment against the outstanding balance | AccountsReceivable |
| POST | `/customers/{customerId}/close` | Close a customer account | AccountsReceivable |
| POST | `/treatment-plants/{plantId}/cylinders/{cylinderId}/charges` | Stage and load a new charge into a cylinder | PlantOperator |
| GET | `/treatment-plants/{plantId}/charges` | List charges for a plant | PlantOperator, LabTechnician, QualityManager, QualityAgencyInspector, ComplianceOfficer, AccountsReceivable |
| GET | `/treatment-plants/{plantId}/cylinders/{cylinderId}/charges` | List charges for a cylinder (sub-resource) | PlantOperator, LabTechnician, QualityManager, QualityAgencyInspector, ComplianceOfficer |
| GET | `/treatment-plants/{plantId}/charges/{chargeId}` | Get a specific charge | PlantOperator, LabTechnician, QualityManager, QualityAgencyInspector, ComplianceOfficer, AccountsReceivable |
| POST | `/treatment-plants/{plantId}/charges/{chargeId}/order-retreat` | Order a re-treat for an ASSAYED_FAIL charge | QualityManager |
| POST | `/treatment-plants/{plantId}/charges/{chargeId}/reject` | Reject a charge cited by a CRITICAL inspection finding | QualityManager |
| POST | `/treatment-plants/{plantId}/charges/{chargeId}/scrap` | Scrap a charge (terminal) | QualityManager |
| POST | `/treatment-plants/{plantId}/charges/{chargeId}/tag` | Apply end-tag/end-plate to an ASSAYED_PASS charge | PlantOperator |
| GET | `/treatment-plants/{plantId}/charges/{chargeId}/pieces` | List pieces in a charge | PlantOperator, LabTechnician, QualityManager, QualityAgencyInspector, ComplianceOfficer |
| GET | `/treatment-plants/{plantId}/charges/{chargeId}/pieces/{pieceId}` | Get a specific piece | PlantOperator, LabTechnician, QualityManager, QualityAgencyInspector, ComplianceOfficer |
| POST | `/treatment-plants/{plantId}/charges/{chargeId}/pieces/{pieceId}/incise` | Mark a piece as incised | PlantOperator |
| POST | `/treatment-plants/{plantId}/cylinders/{cylinderId}/cycles` | Schedule a new treatment cycle on the loaded charge | PlantOperator |
| GET | `/treatment-plants/{plantId}/cylinders/{cylinderId}/cycles` | List cycles on a cylinder | PlantOperator, LabTechnician, QualityManager, ComplianceOfficer |
| GET | `/treatment-plants/{plantId}/cylinders/{cylinderId}/cycles/{cycleId}` | Get a specific cycle | PlantOperator, LabTechnician, QualityManager, ComplianceOfficer |
| GET | `/treatment-plants/{plantId}/charges/{chargeId}/cycles` | List cycles for a charge (reverse-reachability) | PlantOperator, LabTechnician, QualityManager, ComplianceOfficer |
| POST | `/treatment-plants/{plantId}/cylinders/{cylinderId}/cycles/{cycleId}/start` | Start a scheduled cycle | PlantOperator |
| POST | `/treatment-plants/{plantId}/cylinders/{cylinderId}/cycles/{cycleId}/begin-drain` | Begin draining the cylinder | PlantOperator |
| POST | `/treatment-plants/{plantId}/cylinders/{cylinderId}/cycles/{cycleId}/complete` | Complete the cycle (after drain) | PlantOperator |
| POST | `/treatment-plants/{plantId}/cylinders/{cylinderId}/cycles/{cycleId}/abort` | Abort a running cycle | PlantOperator |
| POST | `/treatment-plants/{plantId}/charges/{chargeId}/retention-assays` | Record a retention assay on a charge | LabTechnician |
| GET | `/treatment-plants/{plantId}/charges/{chargeId}/retention-assays` | List assays for a charge | LabTechnician, QualityManager, QualityAgencyInspector, ComplianceOfficer, PlantOperator |
| GET | `/treatment-plants/{plantId}/charges/{chargeId}/retention-assays/{assayId}` | Get a specific assay | LabTechnician, QualityManager, QualityAgencyInspector, ComplianceOfficer, PlantOperator |
| POST | `/treatment-plants/{plantId}/inspections` | Schedule a quality agency inspection | QualityAgencyInspector, ComplianceOfficer |
| GET | `/treatment-plants/{plantId}/inspections/{inspectionId}` | Get a specific inspection | QualityAgencyInspector, ComplianceOfficer, QualityManager, PlantOperator, LabTechnician |
| POST | `/treatment-plants/{plantId}/inspections/{inspectionId}/begin` | Begin a scheduled inspection | QualityAgencyInspector |
| POST | `/treatment-plants/{plantId}/inspections/{inspectionId}/issue-findings` | Issue findings for an in-progress inspection | QualityAgencyInspector |
| POST | `/treatment-plants/{plantId}/inspections/{inspectionId}/close` | Close an inspection (pass or fail) | QualityAgencyInspector |
| POST | `/treatment-plants/{plantId}/charges/{chargeId}/drip-pad-logs` | Log a drip pad dwell period for a charge | PlantOperator |
| GET | `/treatment-plants/{plantId}/charges/{chargeId}/drip-pad-logs` | List drip pad logs for a charge | PlantOperator, QualityManager, QualityAgencyInspector, ComplianceOfficer, LabTechnician |
| GET | `/treatment-plants/{plantId}/charges/{chargeId}/drip-pad-logs/{logId}` | Get a specific drip pad log | PlantOperator, QualityManager, QualityAgencyInspector, ComplianceOfficer, LabTechnician |
| POST | `/treatment-plants/{plantId}/charges/{chargeId}/warranty-registrations` | Register a warranty on a TAGGED charge (releases it) | PlantOperator |
| GET | `/treatment-plants/{plantId}/charges/{chargeId}/warranty-registrations` | List warranties for a charge | PlantOperator, QualityManager, AccountsReceivable, ComplianceOfficer, QualityAgencyInspector |
| GET | `/treatment-plants/{plantId}/charges/{chargeId}/warranty-registrations/{warrantyId}` | Get a specific warranty | PlantOperator, QualityManager, AccountsReceivable, ComplianceOfficer, QualityAgencyInspector |
| POST | `/treatment-plants/{plantId}/cylinders/{cylinderId}/slots` | Book a schedule slot on a cylinder | PlantOperator |
| GET | `/treatment-plants/{plantId}/cylinders/{cylinderId}/slots` | List slots on a cylinder | PlantOperator, QualityManager, ComplianceOfficer |
| GET | `/treatment-plants/{plantId}/cylinders/{cylinderId}/slots/{slotId}` | Get a specific slot | PlantOperator, QualityManager, ComplianceOfficer |
| DELETE | `/treatment-plants/{plantId}/cylinders/{cylinderId}/slots/{slotId}` | Cancel a future slot | PlantOperator |
| GET | `/treatment-plants/cylinders/{cylinderId}` | Get a specific cylinder (flat) | PlantOperator, LabTechnician, QualityManager, QualityAgencyInspector, ComplianceOfficer |
| GET | `/treatment-plants/preservatives/{preservativeId}` | Get a specific preservative (flat) | LabTechnician, PlantOperator, QualityManager, ComplianceOfficer |
| GET | `/treatment-plants/customers/{customerId}` | Get a specific customer (flat) | AccountsReceivable, PlantOperator, QualityManager, ComplianceOfficer |
| GET | `/treatment-plants/charges/{chargeId}` | Get a specific charge (flat) | PlantOperator, LabTechnician, QualityManager, QualityAgencyInspector, ComplianceOfficer, AccountsReceivable |
| GET | `/treatment-plants/pieces/{pieceId}` | Get a specific piece (flat) | PlantOperator, LabTechnician, QualityManager, QualityAgencyInspector, ComplianceOfficer |
| GET | `/treatment-plants/cycles/{cycleId}` | Get a specific cycle (flat) | PlantOperator, LabTechnician, QualityManager, ComplianceOfficer |
| GET | `/treatment-plants/assays/{assayId}` | Get a specific assay (flat) | LabTechnician, QualityManager, QualityAgencyInspector, ComplianceOfficer, PlantOperator |
| GET | `/treatment-plants/inspections/{inspectionId}` | Get a specific inspection (flat) | QualityAgencyInspector, ComplianceOfficer, QualityManager, PlantOperator, LabTechnician |
| GET | `/treatment-plants/drip-logs/{logId}` | Get a specific drip pad log (flat) | PlantOperator, QualityManager, QualityAgencyInspector, ComplianceOfficer, LabTechnician |
| GET | `/treatment-plants/warranties/{warrantyId}` | Get a specific warranty (flat) | PlantOperator, QualityManager, AccountsReceivable, ComplianceOfficer, QualityAgencyInspector |
| GET | `/treatment-plants/slots/{slotId}` | Get a specific slot (flat) | PlantOperator, QualityManager, ComplianceOfficer |
| GET | `/treatment-plants/customers/{customerId}/charges` | List charges for a customer | AccountsReceivable, PlantOperator, QualityManager, ComplianceOfficer |
| GET | `/treatment-plants/preservatives/{preservativeId}/cycles` | List cycles using a preservative | LabTechnician, PlantOperator, QualityManager, ComplianceOfficer |
| GET | `/treatment-plants/cycles/{cycleId}/retention-assays` | List assays for a cycle | LabTechnician, QualityManager, QualityAgencyInspector, ComplianceOfficer, PlantOperator |
| GET | `/treatment-plants/charges/{chargeId}/slots` | List slots for a charge | PlantOperator, QualityManager, ComplianceOfficer |
| GET | `/treatment-plants/cylinders/{cylinderId}/charges` | List charges for a cylinder (flat sub-resource) | PlantOperator, LabTechnician, QualityManager, QualityAgencyInspector, ComplianceOfficer |
| GET | `/treatment-plants/charges/{chargeId}/pieces` | List pieces for a charge (flat sub-resource) | PlantOperator, LabTechnician, QualityManager, QualityAgencyInspector, ComplianceOfficer |
| GET | `/treatment-plants/charges/{chargeId}/cycles` | List cycles for a charge (flat sub-resource) | PlantOperator, LabTechnician, QualityManager, ComplianceOfficer |
| GET | `/treatment-plants/charges/{chargeId}/retention-assays` | List assays for a charge (flat sub-resource) | LabTechnician, QualityManager, QualityAgencyInspector, ComplianceOfficer, PlantOperator |
| GET | `/treatment-plants/charges/{chargeId}/drip-pad-logs` | List drip pad logs for a charge (flat sub-resource) | PlantOperator, QualityManager, QualityAgencyInspector, ComplianceOfficer, LabTechnician |
| GET | `/treatment-plants/charges/{chargeId}/warranty-registrations` | List warranties for a charge (flat sub-resource) | PlantOperator, QualityManager, AccountsReceivable, ComplianceOfficer, QualityAgencyInspector |
| GET | `/treatment-plants/cylinders/{cylinderId}/slots` | List slots for a cylinder (flat sub-resource) | PlantOperator, QualityManager, ComplianceOfficer |
| GET | `/treatment-plants/cylinders` | List cylinders (filtered list) | PlantOperator, LabTechnician, QualityManager, QualityAgencyInspector, ComplianceOfficer |
| GET | `/treatment-plants/preservatives` | List preservatives (filtered list) | LabTechnician, PlantOperator, QualityManager, ComplianceOfficer |
| GET | `/treatment-plants/inspections` | List inspections (filtered list) | QualityAgencyInspector, ComplianceOfficer, QualityManager, PlantOperator, LabTechnician |
| GET | `/treatment-plants/charges` | List charges (filtered list) | PlantOperator, LabTechnician, QualityManager, QualityAgencyInspector, ComplianceOfficer, AccountsReceivable |
| GET | `/treatment-plants/pieces` | List pieces (filtered list) | PlantOperator, LabTechnician, QualityManager, QualityAgencyInspector, ComplianceOfficer |
| GET | `/treatment-plants/cycles` | List cycles (filtered list) | PlantOperator, LabTechnician, QualityManager, ComplianceOfficer |
| GET | `/treatment-plants/assays` | List assays (filtered list) | LabTechnician, QualityManager, QualityAgencyInspector, ComplianceOfficer, PlantOperator |
| GET | `/treatment-plants/drip-logs` | List drip pad logs (filtered list) | PlantOperator, QualityManager, QualityAgencyInspector, ComplianceOfficer, LabTechnician |
| GET | `/treatment-plants/warranties` | List warranties (filtered list) | PlantOperator, QualityManager, AccountsReceivable, ComplianceOfficer, QualityAgencyInspector |
| GET | `/treatment-plants/slots` | List slots (filtered list) | PlantOperator, QualityManager, ComplianceOfficer |
| POST | `/_clock/set_current_utc` | Set the server's logical clock (test-driving) | ComplianceOfficer |
| POST | `/_charges/{chargeId}/force-state` | Test-only: force a Charge into an arbitrary state | ComplianceOfficer |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this table is the structural index of identifiers and statuses.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_TIME_RANGE` | 400 Bad Request |
| `ERR_INVALID_ENUM` | 400 Bad Request |
| `ERR_PLANT_NOT_FOUND` | 404 Not Found |
| `ERR_CYLINDER_NOT_FOUND` | 404 Not Found |
| `ERR_PRESERVATIVE_NOT_FOUND` | 404 Not Found |
| `ERR_CUSTOMER_NOT_FOUND` | 404 Not Found |
| `ERR_CHARGE_NOT_FOUND` | 404 Not Found |
| `ERR_PIECE_NOT_FOUND` | 404 Not Found |
| `ERR_CYCLE_NOT_FOUND` | 404 Not Found |
| `ERR_ASSAY_NOT_FOUND` | 404 Not Found |
| `ERR_INSPECTION_NOT_FOUND` | 404 Not Found |
| `ERR_DRIP_LOG_NOT_FOUND` | 404 Not Found |
| `ERR_WARRANTY_NOT_FOUND` | 404 Not Found |
| `ERR_SLOT_NOT_FOUND` | 404 Not Found |
| `ERR_PLANT_NOT_LICENSED` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_CYLINDER_NOT_IDLE` | 409 Conflict |
| `ERR_CYLINDER_NOT_LOADED` | 409 Conflict |
| `ERR_CYCLE_NOT_RUNNING` | 409 Conflict |
| `ERR_CYCLE_NOT_DRAINING` | 409 Conflict |
| `ERR_CHARGE_NOT_ASSAYED_PASS` | 409 Conflict |
| `ERR_CHARGE_NOT_TAGGED` | 409 Conflict |
| `ERR_CHARGE_NOT_ASSAYED_FAIL` | 409 Conflict |
| `ERR_INSPECTION_NOT_SCHEDULED` | 409 Conflict |
| `ERR_INSPECTION_NOT_IN_PROGRESS` | 409 Conflict |
| `ERR_PRESERVATIVE_QUARANTINED` | 422 Unprocessable Entity |
| `ERR_SLOT_IN_PAST` | 409 Conflict |
| `ERR_CYLINDER_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_CYLINDER_SLOT_CONFLICT` | 409 Conflict |
| `ERR_NO_SLOT_FOR_CHARGE` | 409 Conflict |
| `ERR_ASSAY_BELOW_WORKING_MINIMUM` | 422 Unprocessable Entity |
| `ERR_ASSAY_CYCLE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_INCISING_REQUIRED` | 422 Unprocessable Entity |
| `ERR_DRIP_PAD_CONTAINMENT_BREACH` | 422 Unprocessable Entity |
| `ERR_DRIP_DWELL_TOO_SHORT` | 422 Unprocessable Entity |
| `ERR_INSPECTION_WINDOW_MISSED` | 409 Conflict |
| `ERR_RETREAT_NOT_PERMITTED` | 422 Unprocessable Entity |
| `ERR_SLOT_CHARGE_INVALID` | 422 Unprocessable Entity |
| `ERR_CUSTOMER_CREDIT_HOLD` | 402 Payment Required |
| `ERR_CUSTOMER_BALANCE_NOT_ZERO` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
