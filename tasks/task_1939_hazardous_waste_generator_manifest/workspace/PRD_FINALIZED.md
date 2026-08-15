# Hazardous Waste Generator & Manifest Management API — Product Requirements Document

## 1. Introduction

Large-quantity generator facilities live under a permanent regulatory microscope. Every drum of spent solvent staged on the shop floor has an EPA identification number behind it, an accumulation clock ticking against it, a manifest chain waiting to follow it off-site, and a paper trail that state and federal inspectors will reconstruct years later during a biennial review. The EHS office that runs such a site juggles waste-stream characterization, satellite-area accumulation limits, transporter and disposal-facility vetting, land-disposal-restriction notifications, and fee-bearing biennial reports — each with its own clocks, thresholds, and segregation-of-duties rules.

This document specifies a REST API that gives that EHS office a single system of record. The API models generator sites, their waste streams and accumulation areas, the physical containers moving through them, the transporters and treatment/storage/disposal facilities (TSDFs) that take waste off-site, the uniform hazardous waste manifests that carry each shipment, and the biennial reports that close the compliance loop with the regulator. A logical clock drives every time-sensitive rule in the system — month boundaries, accumulation deadlines, inspection intervals, manifest return windows, audit coverage windows — so compliance behavior is deterministic and testable rather than wall-clock dependent.

The API is mounted under `/hazwaste`. All rules in this document apply within that mount.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the operational capacity in which that user is acting. The system recognizes five distinct roles, spelled exactly as follows: `EHSManager`, `WasteCoordinator`, `ComplianceAuditor`, `TransporterAgent`, and `TSDFAgent`. A request missing either header, or carrying a role value outside this set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not in the endpoint's authorized role list is rejected with `ERR_FORBIDDEN` (HTTP 403).

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `EHSManager`, `WasteCoordinator`, or `ComplianceAuditor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it on resources it touches (for example as `created_by_user_id` on a site, partner, or manifest, as `generator_signed_by_user_id` on a manifest, as `last_action_user_id` on a container, or as `auditor_user_id` on a compliance audit) but never compares it to any entity's `id`. When `X-User-Role` is `TransporterAgent` or `TSDFAgent`, `X-User-ID` is the `id` of the acting `WastePartner`; ownership checks on a manifest compare the manifest's partner foreign-key field to `X-User-ID`, so a `TransporterAgent` may only countersign manifests whose `transporter_id` equals the agent's `X-User-ID`, and a `TSDFAgent` may only receive or flag manifests whose `tsdf_id` equals the agent's `X-User-ID`. A mismatch on those partner-backed operations is rejected with `ERR_PARTNER_IDENTITY_MISMATCH` (HTTP 403).

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

Endpoints that return lists of resources accept two query parameters controlling pagination. The `limit` parameter specifies the maximum number of items to return; it defaults to 10 when not provided, and accepts values from a minimum of 1 up to a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0.

Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp (`created_at`) in ascending order.

List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the response envelope.

### 2.4. Common Resource Properties

Every primary resource in the system — GeneratorSite, WasteStream, AccumulationArea, Container, ContainerInspection, WastePartner, ComplianceAudit, Manifest, and BiennialReport — carries a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by one on every mutation, serving as the basis for optimistic concurrency control.

The one exception is the LDRNotification resource: it carries `id` and `created_at` only. Because an LDR notice is immutable once filed, it has no `updated_at` field and no `version` field, and no OCC rule ever applies to it.

### 2.5. The Logical Clock and Time-Driven Sweeps

Every temporal rule in this system is evaluated against a server-side logical clock, not wall-clock time. At startup the logical clock reads exactly 2026-08-01T00:00:00Z, and the clock never falls back to wall-clock time thereafter. An admin-style capability, available to `EHSManager`, `WasteCoordinator`, and `ComplianceAuditor` roles, advances the logical clock to a supplied instant `to_iso8601` and returns the resulting current time as `current_utc`.

Advancing the clock triggers a deterministic sweep with four families of side effects. First, calendar-month rollover: any site whose logical month has changed resets its monthly generation total to zero, updates its `current_month_key` to the new month in `YYYY-MM` format, and re-evaluates its generator category from that zeroed total. Second, manifest exception sweeps: every manifest in `IN_TRANSIT`, `DELIVERED`, or `DISCREPANCY_RAISED` status whose 45-day return window has passed transitions to `EXCEPTION_REQUIRED` and increments the site's open-exception counter. Third, container overdue flags: accumulation-deadline and inspection-currency flags on central-accumulation and staged containers are recomputed against the new time. Fourth, audit currency: each partner's `is_audit_current` flag is recomputed against its coverage window. Deadline comparisons throughout the system are strictly greater-than — a clock sitting exactly on a deadline timestamp has not yet tripped that deadline.

### 2.6. Generator Category Thresholds and the Monthly Generation Ledger

Each GeneratorSite maintains a running monthly generation total, `current_month_generated_kg`, equal to the sum of `quantity_kg` over that site's containers created within the site's current calendar month (per the logical clock) whose status is anything other than `VOIDED`. The total is maintained incrementally rather than recomputed on demand: creating a container adds its `quantity_kg`, voiding a container subtracts it (only when the voided container was created in the current month — containers created in earlier months belong to those months forever), and the clock sweep resets the total to zero when the calendar month rolls over. Quantities are stored as given, at one decimal place of precision.

The site's `generator_category` is a pure function of this monthly total, re-evaluated on every change, including the month-rollover reset. When the total reaches at least 1000.0 kilograms the category is `LQG`; when the total is strictly above 100.0 kilograms but below 1000.0 the category is `SQG`; otherwise the category is `VSQG`. Boundaries are exact: a site at exactly 100.0 kilograms remains `VSQG`, and a site at exactly 1000.0 kilograms is `LQG`. The category is stored on the site so that downstream rules (accumulation deadlines, biennial fees) can snapshot it at the moment they need it.

### 2.7. Cascading Consistency Across Sites, Reports, and Containers

The system is a web of derived state rather than a set of isolated records, and mutations cascade through it immediately. When a container is created or voided, three hops follow in order: the site's monthly generation total moves (hop 1); the category is re-evaluated and flips on a threshold crossing (hop 2); and every `DRAFT` BiennialReport belonging to that site recomputes its provisional fee against the new category and the current manifest set (hop 3). The same hop-2/hop-3 recomputation happens when a manifest's return is confirmed for an in-period report. Each such reconciliation is a genuine mutation of the affected parent resource — `updated_at` refreshes and `version` increments on any entity whose stored fields actually change.

References between resources are validated for same-site coherence wherever an operation crosses aggregates. Creating a container requires the named accumulation area to belong to the same site as the named waste stream; moving a container requires the target area to belong to the container's own site; manifest line items require each referenced container to belong to the manifest's site and to carry the line's declared stream. A violation of any of these is rejected with `ERR_CROSS_SITE_REFERENCE` (HTTP 409), except the line-item stream check, which is a malformed-line rejection carrying `ERR_LINE_CONTAINER_MISMATCH` (HTTP 400).

### 2.8. Optimistic Concurrency Control

Two write operations carry explicit optimistic concurrency guards; no other endpoint takes a version field.

Characterizing a waste stream requires the request to carry `expected_waste_stream_version` holding the client's last observed `version` of the stream. If the stream's current `version` has advanced past that value — for instance because another writer has just recharacterized the same stream, legitimately superseding the prior characterization — the write is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting a characterization it has never observed.

Updating a waste partner's registration (its `name`, its `permitted_waste_codes`, or both) requires `expected_waste_partner_version` holding the client's last observed `version` of that partner. A mismatch with the partner's current `version` is likewise rejected with `ERR_STALE_VERSION` (HTTP 412), so a stale writer cannot silently overwrite a permit change another writer just applied.

The OCC check is evaluated after request-shape validation but before any state-machine or business-rule validation, so a stale write surfaces as `ERR_STALE_VERSION` even when the request would also have failed a later check.

### 2.9. Validation Order and Error Precedence

A single request can violate several rules at once; the system evaluates checks in a fixed priority order and returns the first failure. The order is: first, user-context headers (missing or invalid headers yield `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`); second, role authorization for the endpoint (`ERR_FORBIDDEN`); third, partner-identity ownership for the partner-backed manifest operations (`ERR_PARTNER_IDENTITY_MISMATCH`); fourth, existence of every path- and body-referenced identifier, validated left to right — site, then stream, then area, then container, then partner, then manifest, then report (`ERR_NOT_FOUND`); fifth, request shape — required fields present, types matching, enum members valid, unknown request fields rejected, quantities strictly positive, `coverage_to` strictly later than `coverage_from` (`ERR_INVALID_REQUEST`); sixth, OCC stale-version checks (`ERR_STALE_VERSION`); seventh, state-machine legality (`ERR_INVALID_STATE` or the more specific state errors); eighth and onward, the business, segregation-of-duties, referential, and temporal rules described throughout §3.

Within the shape band, two domain-specific errors win over the generic `ERR_INVALID_REQUEST` when they apply: an even `report_year` is reported as `ERR_REPORT_YEAR_NOT_ODD`, and a `FAIL` inspection without a `deficiency_note` is reported as `ERR_INSPECTION_NOTE_REQUIRED`. Within the state band, a specific error always beats the generic one: signing a manifest that is not in `DRAFT` yields `ERR_MANIFEST_NOT_DRAFT`, activating a non-hazardous stream yields `ERR_STREAM_NOT_HAZARDOUS`, and an entity already in a terminal state (`RETIRED`, `EMPTIED`, `VOIDED`, `RETURNED`, `ACCEPTED`, or `REJECTED`) rejects every further transition with `ERR_ALREADY_TERMINAL`.

### 2.10. Monetary Precision

All money in the system is tracked as integer cents — there are no fractional-cent amounts anywhere. Manifest tonnage fees are computed per line item: each line's `quantity_kg` is multiplied by a rate of 10.5 cents per kilogram and the result is rounded half-up to a whole cent, and only then are the per-line amounts summed into the manifest's `tonnage_fee_cents`. The rounding order is pinned: round each line first, then sum. The alternative order (sum quantities across lines, multiply by the rate, then round) is a rejected implementation, because it produces different totals — two lines of 1.0 kilogram each yield 11 + 11 = 22 cents under the pinned order but a single rounded 21 cents under sum-first. Biennial report fees combine a category base amount with the sum of per-manifest tonnage fees and, where applicable, a late penalty, all in integer cents; the only rounding that ever occurs inside the fee stack is the half-up rounding already applied inside manifest line items.

## 3. Business Logic & Workflows

### 3.1. Registering Sites and Profiling Waste Streams

An `EHSManager` onboards a facility by registering a GeneratorSite with a display `name` and an `epa_id_number`. The EPA identification number must be unique across all registered sites — a duplicate is rejected with `ERR_DUPLICATE_EPA_ID` — and must be non-empty. A newly registered site starts with `current_month_key` set to the logical clock's calendar month, `current_month_generated_kg` at zero, `generator_category` of `VSQG`, and both `open_exception_count` and `open_discrepancy_count` at zero. Every site is readable by any role, and the site record always exposes its computed category and counters alongside its registration data.

Once a site exists, a `WasteCoordinator` profiles its waste by creating a WasteStream with a `name` (such as "spent solvent"), a `physical_state` of `LIQUID`, `SOLID`, `SLUDGE`, or `GAS`, and an initial `waste_codes` array (for example `["D001","F003"]`), which may be empty before laboratory characterization. The stream references its owning site via `site_id` and begins life in `DRAFT` status with `characterization_version` at zero and `total_generated_kg` at zero.

Laboratory characterization is the pivotal step. A `WasteCoordinator` characterizes a stream by submitting the determination `is_hazardous`, the full `waste_codes` array, and the land-disposal-restriction treatment standard code `ldr_treatment_standard` — all three are required on every characterize call — together with `expected_waste_stream_version` for the OCC guard described in §2.8. When `is_hazardous` is true, the lab's `flash_point_c` (flash point in Celsius) is required as well; the `ph` reading is optional and defaults to null when omitted. Characterization is permitted from either `DRAFT` or `ACTIVE` status — any other state yields `ERR_INVALID_STATE` — and on success the stream lands in `CHARACTERIZED`, `characterization_version` increments by one, the stream's `version` increments by one, and the five characterization fields (`is_hazardous`, `flash_point_c`, `ph`, `ldr_treatment_standard`, `waste_codes`) are overwritten wholesale with the new values. Recharacterizing an `ACTIVE` stream deliberately loops it back to `CHARACTERIZED`, which pulls it out of service: until the stream is re-activated, new containers may not be created against it.

An `EHSManager` activates a `CHARACTERIZED` stream, moving it to `ACTIVE`, only when its characterization concluded `is_hazardous` is true; attempting to activate a non-hazardous stream is rejected with `ERR_STREAM_NOT_HAZARDOUS`, and attempting it from any state other than `CHARACTERIZED` is `ERR_INVALID_STATE`. Retirement is the terminal move: an `EHSManager` may retire a stream from `DRAFT`, `CHARACTERIZED`, or `ACTIVE`, but only while no container of that stream sits in `ACCUMULATING_AT_SATELLITE`, `SATELLITE_LIMIT_EXCEEDED`, `IN_CENTRAL_ACCUMULATION`, or `STAGED_FOR_SHIPMENT` — otherwise the retire is rejected with `ERR_STREAM_HAS_OPEN_CONTAINERS`. A retired stream accepts no further transitions of any kind, per the terminal-state rule in §2.9.

### 3.2. Accumulation Areas and the Container Lifecycle

Waste physically accumulates in areas. A `WasteCoordinator` creates an AccumulationArea with a `name` (such as "Paint booth SAA") and an `area_type` of either `SATELLITE` or `CENTRAL_90DAY`, tied to its owning site via `site_id`. Satellite areas are where waste originates at the point of generation; central areas are where the regulatory accumulation clock runs.

A `WasteCoordinator` places a new container by naming its `waste_stream_id` and `accumulation_area_id` and declaring `quantity_gallons` and `quantity_kg`, both strictly positive — a non-positive quantity is `ERR_INVALID_REQUEST`. Creation requires the stream to be `ACTIVE` (otherwise `ERR_STREAM_NOT_ACTIVE`) and the area to belong to the same site as the stream (otherwise `ERR_CROSS_SITE_REFERENCE`). The container's own `site_id` is derived from the area's site, never taken from the request, and the server records the caller in both `created_by_user_id` and `last_action_user_id`. Every creation feeds the monthly ledger and the stream's lifetime `total_generated_kg`, and triggers the three-hop cascade of §2.7.

The state the container lands in depends on where it was placed. A container created into a `CENTRAL_90DAY` area enters `IN_CENTRAL_ACCUMULATION` immediately: `accumulation_start_date` is set to the current logical instant and `accumulation_deadline_at` is computed from it. A container created into a `SATELLITE` area enters `ACCUMULATING_AT_SATELLITE` with no central clock running — `accumulation_start_date` stays null — but it is immediately evaluated against the satellite limit described in §3.3.

### 3.3. Satellite Limits, Moves, and the Accumulation Clock

Satellite accumulation areas are capped per stream: the total `quantity_gallons` of all containers sharing the same `accumulation_area_id` and `waste_stream_id` in either `ACCUMULATING_AT_SATELLITE` or `SATELLITE_LIMIT_EXCEEDED` status — including the incoming container — must not exceed 55.0 gallons. When a newly created container pushes that per-stream total strictly over 55.0 gallons, the incoming container alone transitions to `SATELLITE_LIMIT_EXCEEDED`; `satellite_exceeded_at` is stamped with the current instant and `move_deadline_at` is set to three days after it. At exactly 55.0 gallons the limit is not exceeded, and pre-existing containers in the area are untouched — only the container whose arrival crossed the line flips.

From either satellite state, a `WasteCoordinator` moves the container into a `CENTRAL_90DAY` area by naming `target_area_id`. The target area must exist, must have `area_type` `CENTRAL_90DAY` (otherwise `ERR_AREA_TYPE_MISMATCH`), and must belong to the same site as the container (otherwise `ERR_CROSS_SITE_REFERENCE`). The move rewrites `accumulation_area_id`, sets `accumulation_start_date` to the current instant, snapshots the accumulation allowance, updates `last_action_user_id` to the mover, and computes `is_move_late`: true when the container is leaving `SATELLITE_LIMIT_EXCEEDED` and the move happens strictly after `move_deadline_at`, false in every other case.

The accumulation allowance is snapshotted from the site's `generator_category` at the exact moment `accumulation_start_date` is set — a site category of `LQG` at that moment grants 90 days; `SQG` or `VSQG` grants 180 days. This is the category-at-start rule: once `deadline_days` is snapshotted, later flips of the site's category never move an existing container's deadline. For container creation specifically, evaluation order is pinned: the creation's own month-total increment and category re-evaluation are applied first, and only then is the new container's `deadline_days` snapshotted — so a container whose own mass tips the site into `LQG` receives the 90-day allowance, not 180. `accumulation_deadline_at` is the start instant plus `deadline_days` whole days. While a container sits in `IN_CENTRAL_ACCUMULATION` or `STAGED_FOR_SHIPMENT`, its `is_accumulation_overdue` flag is true exactly when the logical clock is strictly later than `accumulation_deadline_at`; at the deadline instant itself the container is not overdue.

A container that will never ship can be voided from `ACCUMULATING_AT_SATELLITE`, `SATELLITE_LIMIT_EXCEEDED`, `IN_CENTRAL_ACCUMULATION`, or `STAGED_FOR_SHIPMENT`, provided it has never been linked to a shipped manifest — a container whose `shipped_manifest_id` is set is beyond voiding and the attempt is `ERR_INVALID_STATE`. Voiding is a compensating reversal through the same three-hop cascade as creation: the month's total is decremented by the container's `quantity_kg` (only when the container was created in the site's current month), the category is re-evaluated and flips downward on a threshold crossing, every `DRAFT` BiennialReport of the site recomputes its provisional fee, and the stream's `total_generated_kg` is decremented. `VOIDED` is terminal.

### 3.4. Labeling, Weekly Inspections, and Staging for Shipment

Before a container can leave central accumulation it must be labeled and inspected. A `WasteCoordinator` affixes the hazardous-waste label by submitting `label_text` and `label_accumulation_start_marked`. The label text must contain the exact substring "Hazardous Waste" — a label lacking it is rejected with `ERR_LABEL_MISSING_HAZARD_TEXT` — and the marked start date must equal the container's `accumulation_start_date` exactly, to the millisecond, or the call is rejected with `ERR_LABEL_START_DATE_MISMATCH`. A successful label sets `is_labeled` to true and records the label fields; `is_labeled` is never cleared by any later transition.

Weekly inspection is a standing obligation while a container occupies central accumulation or sits staged. A `WasteCoordinator` records an inspection against a container with a `result` of `PASS` or `FAIL`; a `FAIL` result must carry a `deficiency_note` (otherwise `ERR_INSPECTION_NOTE_REQUIRED`), while the note is ignored on a `PASS`. Segregation of duties applies here: the inspector's `X-User-ID`, recorded on the inspection as `inspector_user_id`, must differ from the container's `last_action_user_id` — the user who created or most recently moved the container may not inspect it, and the attempt is rejected with `ERR_SOD_SELF_INSPECTION`. Each inspection stamps `inspected_at` with the logical instant and refreshes the container's `last_inspected_at`. A container's `is_inspection_overdue` flag is true when it sits in `IN_CENTRAL_ACCUMULATION` or `STAGED_FOR_SHIPMENT` and the logical clock is strictly more than seven days past the most recent inspection — or past `accumulation_start_date` if the container has never been inspected. At exactly seven days the container is not overdue. Inspections are listed per container, oldest first, and the inspection records carry their own `container_id` back-reference.

Staging is the gate that makes a container shippable: a `WasteCoordinator` stages a container sitting in `IN_CENTRAL_ACCUMULATION`, moving it to `STAGED_FOR_SHIPMENT`. Three gates guard the transition, and all three must pass: the container must be labeled (otherwise `ERR_CONTAINER_NOT_LABELED`), the inspection clock must be current (otherwise `ERR_INSPECTION_OVERDUE`), and the accumulation deadline must not have passed (otherwise `ERR_ACCUMULATION_LIMIT_EXCEEDED`). Once staged, a container waits for its manifest.

### 3.5. Vetting the Downstream Chain: Partners, Approvals, and Audits

No waste moves until the companies that will touch it are vetted. A `ComplianceAuditor` registers each transporter and each treatment, storage, and disposal facility as a WastePartner with a `partner_type` of `TRANSPORTER` or `TSDF`, a legal `name`, an `epa_id_number` unique across all partners (duplicates are `ERR_DUPLICATE_EPA_ID`, in a namespace separate from site EPA IDs), and the `permitted_waste_codes` the partner is permitted to handle. New partners start in `PENDING` status with the registrar recorded in `created_by_user_id` and no audit coverage window — `audit_coverage_start` and `audit_coverage_end` are null until the first audit, and `is_audit_current` is false.

Partner status transitions are driven by a `ComplianceAuditor` setting `to_status`. Approval moves a partner from `PENDING` — or from `SUSPENDED`, as a reinstatement — to `APPROVED`, and is segregated from registration: the approver's `X-User-ID` must differ from the partner's `created_by_user_id`, or the call is rejected with `ERR_SOD_PARTNER_SELF_APPROVE`. Suspension moves an `APPROVED` partner to `SUSPENDED`, and a suspended partner immediately fails the approval precondition on any subsequent manifest creation or signature. Rejection moves a `PENDING` partner to `REJECTED`, which is terminal. Any of these calls made from a state where the requested transition is not defined is `ERR_INVALID_STATE`. A `ComplianceAuditor` may also update a partner's `name` or `permitted_waste_codes` through the OCC-guarded update described in §2.8, which increments the partner's `version` by one on success.

Approval is necessary but not sufficient: manifest operations also demand current audit coverage. A `ComplianceAuditor` records a compliance audit against a partner with an inclusive `coverage_from`, an exclusive `coverage_to` (which must be strictly later than `coverage_from`, else `ERR_INVALID_REQUEST`), and an `outcome` of `PASS` or `FAIL`. The audit names its subject in `waste_partner_id`, stamps `audited_at` with the logical instant, and records the auditor in `auditor_user_id`. The partner's coverage window is the half-open interval from `audit_coverage_start` up to but not including `audit_coverage_end`, and `is_audit_current` is true exactly when the logical clock sits before `audit_coverage_end` — at the end instant itself the audit is expired. A new audit whose window overlaps or exactly abuts the current window merges into it when its outcome is `PASS`: the window becomes the earliest start to the latest end. A new `PASS` window entirely disjoint and later than the current window replaces it outright. Two regressions are rejected: a window entirely disjoint and earlier than the current window is `ERR_AUDIT_WINDOW_REGRESSIVE`, and a `FAIL`-outcome audit whose window strictly overlaps the current window's interior is `ERR_AUDIT_COVERAGE_OVERLAP` — a failing audit may not be blended into a passing record. A partner's full audit history is listable, oldest first.

### 3.6. Manifesting a Shipment

With containers staged and partners vetted, a `WasteCoordinator` drafts a Manifest by naming the shipping `site_id`, a `transporter_id` referencing a partner of type `TRANSPORTER`, a `tsdf_id` referencing a partner of type `TSDF` (a wrong-typed reference in either slot is `ERR_PARTNER_TYPE_MISMATCH`), a generator-assigned `manifest_tracking_number` unique within the site (duplicates are `ERR_DUPLICATE_TRACKING_NUMBER`), and at least one entry in `line_items`, each naming a `waste_stream_id`, a `container_id`, and a `quantity_kg`. Creation enforces the full battery of preconditions, and each has its own rejection: the site must have zero open exceptions (`ERR_OPEN_EXCEPTION_BLOCKS_MANIFEST` while `open_exception_count` is positive); every line-item container must belong to the manifest's site (`ERR_CROSS_SITE_REFERENCE`) and carry the line's declared stream (`ERR_LINE_CONTAINER_MISMATCH`); every line-item container must currently be `STAGED_FOR_SHIPMENT` (`ERR_CONTAINER_NOT_STAGED`); both partners must be `APPROVED` (`ERR_PARTNER_NOT_APPROVED`); both partners must be audit-current (`ERR_PARTNER_AUDIT_STALE`); and the TSDF's `permitted_waste_codes` must cover every waste code of every line's stream (`ERR_TSDF_WASTE_CODE_NOT_PERMITTED`). A drafted manifest starts in `DRAFT` with `total_quantity_kg` equal to the sum of the lines' `quantity_kg` and `tonnage_fee_cents` computed per the pinned rounding of §2.10; the creator is recorded in `created_by_user_id`.

Before the generator may sign, the land-disposal-restriction paperwork must be attached. An `EHSManager` files an LDRNotification against a `DRAFT` manifest with `treatment_standard_codes` covering every waste code on the manifest and a non-empty `certification_statement`; the notice records the manifest it accompanies in `manifest_id` and stamps `notified_at` with the logical instant. LDR notices for a manifest are listable.

The generator signature itself is the regulated act, performed by an `EHSManager`, and it revalidates everything: the manifest must be `DRAFT` (otherwise `ERR_MANIFEST_NOT_DRAFT`); the signer's `X-User-ID` must differ from the manifest's `created_by_user_id` — the coordinator who drafted the manifest may not also certify it, a segregation rejected with `ERR_SOD_MANIFEST_SELF_SIGN`; at least one LDRNotification must exist for the manifest (otherwise `ERR_LDR_NOTICE_MISSING`); every line-item container must still be `STAGED_FOR_SHIPMENT` (otherwise `ERR_CONTAINER_NOT_STAGED`); transporter and TSDF must still be `APPROVED` (`ERR_PARTNER_NOT_APPROVED`) and audit-current (`ERR_PARTNER_AUDIT_STALE`); and the TSDF's permit coverage is rechecked against every line's stream codes (`ERR_TSDF_WASTE_CODE_NOT_PERMITTED`). On success the manifest moves to `GENERATOR_SIGNED` and the signer is recorded in `generator_signed_by_user_id`.

### 3.7. Transit, Receipt, Discrepancies, and the 45-Day Return

The transporter countersigns at pickup. A `TransporterAgent` whose `X-User-ID` equals the manifest's `transporter_id` (otherwise `ERR_PARTNER_IDENTITY_MISMATCH`) signs a `GENERATOR_SIGNED` manifest, moving it to `IN_TRANSIT`. This stamps `shipped_at` with the logical instant and opens the return window: `return_due_at` is exactly 45 days after `shipped_at`. The signature cascades to the cargo — every line-item container moves from `STAGED_FOR_SHIPMENT` to `SHIPPED` and has its `shipped_manifest_id` set to this manifest's id.

Receipt at the destination is mirrored by the facility. A `TSDFAgent` whose `X-User-ID` equals the manifest's `tsdf_id` receives an `IN_TRANSIT` manifest, moving it to `DELIVERED`, stamping `delivered_at`, and cascading every line-item container from `SHIPPED` to `EMPTIED` — a terminal state for the container.

When the facility spots a problem, the same `TSDFAgent` raises a discrepancy on a `DELIVERED` manifest, moving it to `DISCREPANCY_RAISED` and incrementing the site's `open_discrepancy_count` by one. A `ComplianceAuditor` later resolves the discrepancy, returning the manifest to `DELIVERED` and decrementing the same counter by one — the pair nets to zero, and `DISCREPANCY_RAISED` never blocks the return confirmation that follows. State mismatches on either action are `ERR_INVALID_STATE`.

The generator closes the loop by confirming the signed manifest copy came back. An `EHSManager` confirms return on a manifest in `DELIVERED`, `EXCEPTION_REQUIRED`, or `EXCEPTION_REPORT_FILED` (any other state is `ERR_INVALID_STATE`), moving it to the terminal state `RETURNED`. The confirmation stamps `returned_at` and sets `is_return_late` to true when the clock is strictly past `return_due_at` — which it always is when confirming out of either exception state. When the transition leaves `EXCEPTION_REQUIRED` or `EXCEPTION_REPORT_FILED`, the site's `open_exception_count` is decremented by one. Every `DRAFT` BiennialReport of the site whose period covers this manifest's `shipped_at` recomputes its shipped quantities and provisional fee.

### 3.8. The Exception Clock and Exception Reports

The 45-day return window is enforced by the clock sweep, not by any user action. When the logical clock advances past a manifest's `return_due_at` while the manifest sits in `IN_TRANSIT`, `DELIVERED`, or `DISCREPANCY_RAISED`, the sweep moves it to `EXCEPTION_REQUIRED` and increments the site's `open_exception_count` by one per manifest. At exactly `return_due_at` the manifest is not yet overdue — the comparison is strictly greater-than. The consequence is immediate: while `open_exception_count` is positive, the site may not create new manifests, per the `ERR_OPEN_EXCEPTION_BLOCKS_MANIFEST` rule of §3.6.

A `ComplianceAuditor` discharges the exception paperwork by filing an exception report on an `EXCEPTION_REQUIRED` manifest, supplying an `exception_note`. Filing moves the manifest to `EXCEPTION_REPORT_FILED` and stores the note; the manifest continues to count toward `open_exception_count` until a return is confirmed. The only exits from either exception state are the return confirmation of §3.7.

### 3.9. Biennial Reporting and Fees

Every odd-numbered calendar year, an `EHSManager` opens a BiennialReport for a site by naming `site_id` and `report_year`. The year must be an odd integer — an even year is rejected with `ERR_REPORT_YEAR_NOT_ODD` — and only one report may exist per site per odd-year grid cell; a second report for the same `site_id` and `report_year` is `ERR_REPORT_PERIOD_OVERLAP`. The report's period runs from January 1 of `report_year` (inclusive, `period_start`) to January 1 of the following year (exclusive, `period_end`), and the filing deadline `due_at` is March 1 of that following year. A submission strictly after `due_at` is late.

At creation the report computes its provisional picture: `provisional_shipped_kg` is the sum of `total_quantity_kg` over the site's manifests whose `shipped_at` falls within the period and whose status is any of `IN_TRANSIT`, `DELIVERED`, `DISCREPANCY_RAISED`, `RETURNED`, `EXCEPTION_REQUIRED`, or `EXCEPTION_REPORT_FILED`. The provisional fee, `provisional_fee_cents`, is the category base amount plus the sum of `tonnage_fee_cents` over that same provisional manifest set, with no late penalty ever applied while the report is a draft. The category base is read from `category_snapshot`, which captures the site's `generator_category` at the moment the fee is computed: 250000 cents for `LQG`, 100000 cents for `SQG`, 25000 cents for `VSQG`. Because the snapshot is re-read at each computation, every site-category flip while the report is in `DRAFT` re-derives the provisional fee, as does every relevant manifest return.

Submission finalizes the numbers. An `EHSManager` submits a `DRAFT` report, stamping `submitted_at` and moving the report to `SUBMITTED`. At that moment `final_shipped_kg` is computed as the sum of `total_quantity_kg` over in-period manifests in `RETURNED` status only, and `final_fee_cents` is the category base plus the tonnage sum over that returned-only set plus a late penalty when `submitted_at` is strictly after `due_at`. The penalty is 5000 cents per whole day late, capped at 150000 cents; `is_late` records whether the deadline was missed and `days_late` counts the whole days between `due_at` and `submitted_at` (zero when not late). The evaluation order is pinned: the category snapshot is read first, then the manifest set is filtered, then the late branch applies last. For identical site data, the provisional and final fees differ whenever any in-period manifest has not yet returned or the submission is late.

Regulator review closes the cycle. A `ComplianceAuditor` reviews a `SUBMITTED` report with an `outcome`: `ACCEPT` moves the report to the terminal state `ACCEPTED`, while `REJECT` sends it back to `DRAFT` for amendment, clearing `submitted_at` and leaving the provisional fee to be re-derived on the next category flip or manifest return. Reviewing a report not in `SUBMITTED` is `ERR_INVALID_STATE`.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`; operations that modify an existing resource in place, including all state transitions, return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/hazwaste/generator-sites` | Register a generator site | EHSManager |
| GET | `/hazwaste/generator-sites` | List generator sites (paginated) | EHSManager, WasteCoordinator, ComplianceAuditor, TransporterAgent, TSDFAgent |
| GET | `/hazwaste/generator-sites/{siteId}` | Get one generator site including computed category and counters | EHSManager, WasteCoordinator, ComplianceAuditor, TransporterAgent, TSDFAgent |
| POST | `/hazwaste/waste-streams` | Create a waste stream (starts DRAFT) | WasteCoordinator |
| GET | `/hazwaste/waste-streams` | List waste streams, optionally filtered by `site_id` | EHSManager, WasteCoordinator, ComplianceAuditor, TransporterAgent, TSDFAgent |
| GET | `/hazwaste/waste-streams/{streamId}` | Get one waste stream | EHSManager, WasteCoordinator, ComplianceAuditor, TransporterAgent, TSDFAgent |
| POST | `/hazwaste/waste-streams/{streamId}/characterize` | Characterize/recharacterize a stream (OCC-guarded) | WasteCoordinator |
| POST | `/hazwaste/waste-streams/{streamId}/activate` | Activate a characterized hazardous stream | EHSManager |
| POST | `/hazwaste/waste-streams/{streamId}/retire` | Retire a stream with no open containers | EHSManager |
| POST | `/hazwaste/accumulation-areas` | Create an accumulation area (SATELLITE or CENTRAL_90DAY) | WasteCoordinator |
| GET | `/hazwaste/accumulation-areas` | List accumulation areas, optionally filtered by `site_id` | EHSManager, WasteCoordinator, ComplianceAuditor, TransporterAgent, TSDFAgent |
| GET | `/hazwaste/accumulation-areas/{areaId}` | Get one accumulation area | EHSManager, WasteCoordinator, ComplianceAuditor, TransporterAgent, TSDFAgent |
| POST | `/hazwaste/containers` | Place a new waste container into an area | WasteCoordinator |
| GET | `/hazwaste/containers` | List containers, optionally filtered by `waste_stream_id`, `accumulation_area_id`, `site_id`, or `shipped_manifest_id` | EHSManager, WasteCoordinator, ComplianceAuditor, TransporterAgent, TSDFAgent |
| GET | `/hazwaste/containers/{containerId}` | Get one container including computed deadline/overdue fields | EHSManager, WasteCoordinator, ComplianceAuditor, TransporterAgent, TSDFAgent |
| POST | `/hazwaste/containers/{containerId}/move` | Move a satellite container into a CENTRAL_90DAY area | WasteCoordinator |
| POST | `/hazwaste/containers/{containerId}/label` | Affix the hazardous-waste label | WasteCoordinator |
| POST | `/hazwaste/containers/{containerId}/stage` | Stage a central-accumulation container for shipment | WasteCoordinator |
| POST | `/hazwaste/containers/{containerId}/void` | Void a container never shipped | WasteCoordinator |
| POST | `/hazwaste/containers/{containerId}/inspections` | Record a weekly inspection (segregated from last mover) | WasteCoordinator |
| GET | `/hazwaste/containers/{id}/inspections` | List a container's inspection log | EHSManager, WasteCoordinator, ComplianceAuditor, TransporterAgent, TSDFAgent |
| POST | `/hazwaste/waste-partners` | Register a transporter or TSDF (starts PENDING) | ComplianceAuditor |
| GET | `/hazwaste/waste-partners/{partnerId}` | Get one waste partner including audit currency | EHSManager, WasteCoordinator, ComplianceAuditor, TransporterAgent, TSDFAgent |
| PUT | `/hazwaste/waste-partners/{partnerId}` | Update partner name/permitted codes (OCC-guarded) | ComplianceAuditor |
| POST | `/hazwaste/waste-partners/{partnerId}/status` | Approve, suspend, or reject a partner | ComplianceAuditor |
| POST | `/hazwaste/waste-partners/{partnerId}/audits` | Record a compliance audit with a coverage window | ComplianceAuditor |
| GET | `/hazwaste/waste-partners/{id}/audits` | List a partner's audit history | EHSManager, WasteCoordinator, ComplianceAuditor, TransporterAgent, TSDFAgent |
| POST | `/hazwaste/manifests` | Create a manifest for staged containers | WasteCoordinator |
| GET | `/hazwaste/manifests` | List manifests, optionally filtered by `site_id`, `transporter_id`, or `tsdf_id` | EHSManager, WasteCoordinator, ComplianceAuditor, TransporterAgent, TSDFAgent |
| GET | `/hazwaste/manifests/{manifestId}` | Get one manifest | EHSManager, WasteCoordinator, ComplianceAuditor, TransporterAgent, TSDFAgent |
| POST | `/hazwaste/manifests/{manifestId}/ldr-notifications` | Attach the land-disposal-restriction notification to a DRAFT manifest | EHSManager |
| GET | `/hazwaste/manifests/{id}/ldr-notifications` | List LDR notifications for a manifest | EHSManager, WasteCoordinator, ComplianceAuditor, TransporterAgent, TSDFAgent |
| POST | `/hazwaste/manifests/{manifestId}/sign-generator` | Generator signature (EHSManager, not the creator) | EHSManager |
| POST | `/hazwaste/manifests/{manifestId}/sign-transporter` | Transporter signature at pickup; starts the 45-day window | TransporterAgent |
| POST | `/hazwaste/manifests/{manifestId}/receive` | TSDF receipt; empties the containers | TSDFAgent |
| POST | `/hazwaste/manifests/{manifestId}/raise-discrepancy` | TSDF raises a quantity/type discrepancy | TSDFAgent |
| POST | `/hazwaste/manifests/{manifestId}/resolve-discrepancy` | Resolve an open discrepancy | ComplianceAuditor |
| POST | `/hazwaste/manifests/{manifestId}/confirm-return` | Confirm the signed manifest copy returned; closes the 45-day window | EHSManager |
| POST | `/hazwaste/manifests/{manifestId}/file-exception-report` | File the 45-day exception report | ComplianceAuditor |
| POST | `/hazwaste/biennial-reports` | Open a biennial report for a site and odd report year | EHSManager |
| GET | `/hazwaste/biennial-reports` | List biennial reports, optionally filtered by `site_id` | EHSManager, WasteCoordinator, ComplianceAuditor, TransporterAgent, TSDFAgent |
| GET | `/hazwaste/biennial-reports/{reportId}` | Get one biennial report | EHSManager, WasteCoordinator, ComplianceAuditor, TransporterAgent, TSDFAgent |
| POST | `/hazwaste/biennial-reports/{reportId}/submit` | Submit the report; computes final fee and late penalty | EHSManager |
| POST | `/hazwaste/biennial-reports/{reportId}/review` | Regulator review: ACCEPT or REJECT back to DRAFT | ComplianceAuditor |
| POST | `/hazwaste/_clock/set_current_utc` | Set the server's logical clock and run the deadline sweep | EHSManager, WasteCoordinator, ComplianceAuditor |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_PARTNER_IDENTITY_MISMATCH` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_MANIFEST_NOT_DRAFT` | 409 Conflict |
| `ERR_STREAM_NOT_HAZARDOUS` | 409 Conflict |
| `ERR_STREAM_NOT_ACTIVE` | 409 Conflict |
| `ERR_STREAM_HAS_OPEN_CONTAINERS` | 409 Conflict |
| `ERR_SOD_MANIFEST_SELF_SIGN` | 403 Forbidden |
| `ERR_SOD_PARTNER_SELF_APPROVE` | 403 Forbidden |
| `ERR_SOD_SELF_INSPECTION` | 403 Forbidden |
| `ERR_TSDF_WASTE_CODE_NOT_PERMITTED` | 409 Conflict |
| `ERR_LDR_NOTICE_MISSING` | 409 Conflict |
| `ERR_CONTAINER_NOT_LABELED` | 409 Conflict |
| `ERR_LABEL_MISSING_HAZARD_TEXT` | 400 Bad Request |
| `ERR_LABEL_START_DATE_MISMATCH` | 400 Bad Request |
| `ERR_CROSS_SITE_REFERENCE` | 409 Conflict |
| `ERR_LINE_CONTAINER_MISMATCH` | 400 Bad Request |
| `ERR_PARTNER_TYPE_MISMATCH` | 409 Conflict |
| `ERR_PARTNER_NOT_APPROVED` | 409 Conflict |
| `ERR_PARTNER_AUDIT_STALE` | 409 Conflict |
| `ERR_AREA_TYPE_MISMATCH` | 409 Conflict |
| `ERR_CONTAINER_NOT_STAGED` | 409 Conflict |
| `ERR_ACCUMULATION_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_INSPECTION_OVERDUE` | 409 Conflict |
| `ERR_INSPECTION_NOTE_REQUIRED` | 400 Bad Request |
| `ERR_OPEN_EXCEPTION_BLOCKS_MANIFEST` | 409 Conflict |
| `ERR_REPORT_YEAR_NOT_ODD` | 400 Bad Request |
| `ERR_DUPLICATE_EPA_ID` | 409 Conflict |
| `ERR_DUPLICATE_TRACKING_NUMBER` | 409 Conflict |
| `ERR_REPORT_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_AUDIT_COVERAGE_OVERLAP` | 409 Conflict |
| `ERR_AUDIT_WINDOW_REGRESSIVE` | 409 Conflict |
