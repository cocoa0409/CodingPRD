# National Cemetery API — Product Requirements Document

## 1. Introduction

This document specifies the National Cemetery & Veteran Burial API, a system modeled on the operations of a national cemetery administration. The domain it governs is one of scarce, physical resources — finite in-ground gravesites and columbarium niches — that eligible veterans and their dependents compete for, layered on top of a regulatory eligibility regime that must be adjudicated case by case before any plot can be committed. The API therefore has two intertwined responsibilities: it is a quota-allocation engine that reserves and occupies a limited inventory of burial units, and it is a compliance-audit engine that gates every commitment behind statutory entitlement rules.

A single burial is not one action but a chain of them. An eligibility officer must first determine whether the applicant qualifies for interment, and on what basis. A scheduling clerk then draws a suitable plot from inventory, books an interment window, and drives the case to completion. A marker clerk orders and engraves the headstone, subject to inscription limits and per-character pricing. A honors coordinator arranges the military-honors detail and the ceremonial flag, constrained by how many details the cemetery can field on a given day. Because each of these workflows mutates shared inventory and cross-references the others, the system enforces immediate consistency: reserving a plot bumps that unit's version, cancelling a schedule cascades back through honors, and completing an interment recomputes the parent section's rolled-up counts. Pre-need reservations add a further temporal dimension, holding inventory for a bounded window against a living applicant's future need.

The sections that follow define the global contract every endpoint honors (§2), the business logic and lifecycle workflows that carry a case from submission to interment (§3), the endpoint surface (§4), and the catalogue of error identifiers (§5).

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope format, and cross-cutting principles that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header is rejected with `ERR_UNAUTHENTICATED`. When the headers are present but the declared role is not permitted for the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly five roles: `NCA_Admin`, `EligibilityOfficer`, `SchedulingClerk`, `MarkerClerk`, and `HonorsCoordinator`. An `NCA_Admin` manages the physical estate — cemeteries, sections, and the inventory of gravesites and niches — and performs administrative sweeps such as pre-need expiry. An `EligibilityOfficer` adjudicates veteran and dependent eligibility and owns the pre-need memorial certificate determinations. A `SchedulingClerk` owns plot assignment, interment scheduling, and the burial case's lifecycle after eligibility. A `MarkerClerk` owns headstone and marker orders. A `HonorsCoordinator` owns the military-honors detail and burial-flag issuance. Opening a burial case is shared between the `EligibilityOfficer` and the `SchedulingClerk`; all read (GET) operations are available to every authenticated role.

Each of the five roles is an **opaque operator identity**: when `X-User-Role` is any of `NCA_Admin`, `EligibilityOfficer`, `SchedulingClerk`, `MarkerClerk`, or `HonorsCoordinator`, the accompanying `X-User-ID` is an operator identifier that is not tied to any persisted entity and is never compared against any resource's `id`. The server may record such an identifier where a workflow calls for it — for example, an eligibility determination captures the adjudicating officer's identifier in its `decided_by_user_id` field — but it does not use `X-User-ID` for ownership checks on any resource.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, may not be less than 1, and may not exceed 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless a specific endpoint states otherwise, list results are sorted by their creation timestamp in ascending order.

Every list response echoes four fields inside the envelope's `meta` object: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Most resources in the system carry a common set of server-managed fields. The `id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp (with three fractional digits) recording when the resource was first created. `updated_at` is an ISO 8601 UTC timestamp recording the last modification. `version` is an integer that starts at its initial value and increments by one on every mutation of the resource; it is the value used for optimistic concurrency control (see §2.9).

One entity is exempt from part of this convention. The `EligibilityDetermination` is an immutable audit record: it carries only an `id` and a `created_at`, and it has neither an `updated_at` nor a `version` field, because once written it is never modified. Every other entity — `Cemetery`, `Section`, `Gravesite`, `Niche`, `BurialCase`, `PreNeedDetermination`, `IntermentSchedule`, `MarkerOrder`, and `MilitaryHonors` — carries the full set of common fields including `updated_at` and `version`.

Whenever a computed or derived field changes — a section's rolled-up counts, a case's assignment pointers, a unit's status — that change is a mutation of the owning resource: it refreshes `updated_at` and increments `version`.

### 2.5. Nested Resource Retrieval and Reference Resolution

Many paths address a resource nested beneath one or more parents, for example a gravesite that lives under a section that lives under a cemetery. The server validates the identifiers in the path from left to right and rejects the request with `ERR_NOT_FOUND` at the first identifier in the path that does not name an existing resource. A gravesite request under a non-existent cemetery therefore fails on the cemetery before the section or gravesite is ever considered.

Path identifiers are distinct from foreign keys carried in a request body. When a create or action endpoint carries a body-level reference — such as `burial_case_id`, `section_id`, `interment_schedule_id`, `reserving_case_id`, or an explicit `unit_id` — and that reference does not resolve to an existing record, the request is rejected with `ERR_REFERENCE_NOT_FOUND`. Both `ERR_NOT_FOUND` and `ERR_REFERENCE_NOT_FOUND` carry HTTP 404, but they distinguish a broken path from a broken body reference.

### 2.6. Ordering of Validation

When several conditions could reject a single request, they are evaluated in a fixed priority order so that the returned error is deterministic. Authentication comes first: a request with missing headers fails with `ERR_UNAUTHENTICATED` before anything else. Authorization is second: a present-but-forbidden role fails with `ERR_UNAUTHORIZED`. Third, path-referenced resources are checked left-to-right, yielding `ERR_NOT_FOUND` on the first missing identifier. Fourth, body-referenced foreign keys are resolved, yielding `ERR_REFERENCE_NOT_FOUND`. Fifth, the target resource's state is checked against the requested transition, yielding `ERR_INVALID_STATE` when the transition is not defined from the current state. Malformed bodies, missing required fields, and invalid enum values surface as `ERR_VALIDATION`.

Only after these structural checks pass does the system evaluate domain rules — unit-kind compatibility (`ERR_UNIT_KIND_MISMATCH`), window well-formedness (`ERR_INVALID_WINDOW`), scheduling conflicts (`ERR_GRAVESITE_WINDOW_CONFLICT` / `ERR_NICHE_WINDOW_CONFLICT`), inscription limits (`ERR_INSCRIPTION_LIMIT_EXCEEDED`), honors entitlement (`ERR_HONORS_ENTITLEMENT_INSUFFICIENT`), optimistic-concurrency staleness (`ERR_STALE_GRAVESITE_VERSION` / `ERR_STALE_PMC_VERSION`), honors capacity (`ERR_HONORS_CAPACITY_FULL`), and unit availability (`ERR_NO_AVAILABLE_UNIT`). Within a given endpoint the specific ordering of these domain checks is described alongside the workflow that triggers them in §3.

### 2.7. Section Inventory Reconciliation

Every `Section` publishes three derived counts that summarize its child units, and these are always recomputed from the current children rather than stored independently. A section's `capacity_units` is the count of all its child units — gravesites when the section's `kind` is `IN_GROUND`, niches when its `kind` is `COLUMBARIUM`. Its `available_units` is the count of those children whose status is `AVAILABLE`. Its `interred_units` is the count of those children whose status is `OCCUPIED`. A unit in the intermediate `RESERVED` status counts toward neither `available_units` nor `interred_units`, and a `DECOMMISSIONED` unit counts toward none of the three occupancy tallies.

These counts are re-derived on every event that changes a child unit's status — a plot assignment, a plot release, an interment completion, or a pre-need expiry sweep — and each such recomputation is a mutation of the section, refreshing its `updated_at` and incrementing its `version`.

### 2.8. Cascading State Effects

Several operations touch more than one entity. When an interment schedule is cancelled, the effect does not stop at the schedule: the owning burial case reverts from `SCHEDULED` back to `ASSIGNED`, and every military-honors record linked to that schedule that is still in `REQUESTED` or `CONFIRMED` is driven to `CANCELLED`; any such honors record that had already issued its flag has that flag withdrawn. When an interment schedule is completed, the case advances to `INTERRED` and every linked `CONFIRMED` honors record is driven to `RENDERED`. Each of these secondary mutations refreshes the affected resource's `updated_at` and increments its `version` in the same way a direct write would. The precise triggers and preconditions for each cascade are given in the workflow narratives of §3.

### 2.9. Optimistic Concurrency Control

Two operations in the system require the caller to prove they are acting on a version of a parent resource they have actually observed, guarding against a write that would silently overwrite a newer state.

The first guards explicit plot assignment. When a scheduling clerk assigns a specific in-ground gravesite to a case by supplying its `unit_id`, the request must also carry `expected_gravesite_version`, holding the `version` of that `Gravesite` the caller last observed. If the gravesite's current `version` has advanced since — for instance because another case already reserved it, which moves the unit from `AVAILABLE` to `RESERVED` and increments its `version` — the assignment is rejected as stale with `ERR_STALE_GRAVESITE_VERSION` at HTTP 412. This prevents a clerk from reserving a plot they believed available but which another case has legitimately claimed.

The second guards pre-need approval. When an eligibility officer approves a pre-need determination, the request must carry `expected_pmc_version`, holding the `version` of that `PreNeedDetermination` the caller last observed. If the record's current `version` has advanced since — for instance because a denial has already been recorded against the pending certificate — the approval is rejected as stale with `ERR_STALE_PMC_VERSION` at HTTP 412, rather than overwriting the newer decision.

Endpoints other than these two do not accept a version field and perform no concurrency check.

### 2.10. Overseas and Domestic Cemeteries

A `Cemetery` is created with a `country_code`, defaulting to `US`. From this the system computes the boolean `is_overseas`, which is true exactly when the `country_code` is not `US`. An overseas cemetery accepts only overseas cases. This is enforced during eligibility adjudication (see §3.2): a mismatch between a case's overseas designation and its cemetery's overseas designation is a denial condition, not merely a warning.

### 2.11. Precision of Monetary and Counted Quantities

Eligibility scoring, inventory counts, and honors-capacity tallies are all integer quantities and involve no rounding beyond the floor operations spelled out in their formulas. Marker charges are computed in whole cents. Where a formula divides to determine a number of pricing blocks, the block count is rounded up to the next whole block before pricing, as detailed in §3.6. There are no fractional-currency or decimal-place representations anywhere in the system; all amounts that reach the API are integers.

## 3. Business Logic & Workflows

### 3.1. Establishing the Physical Estate

Before any burial can be adjudicated, an `NCA_Admin` builds out the physical hierarchy. A cemetery is created with a `name`, an optional `country_code` (defaulting to `US`), and an `honors_squad_capacity` — the maximum number of simultaneous military-honors details the cemetery can field on a single day. The `is_overseas` flag is derived at creation from the country code as described in §2.10.

Within a cemetery, an admin creates one or more sections, each bound to its parent through the section's `cemetery_id`, with a `code` unique within its cemetery and a `kind` that is either `IN_GROUND` or `COLUMBARIUM`. The section's `kind` fixes what it can hold: an `IN_GROUND` section holds gravesites, a `COLUMBARIUM` section holds niches. A newly created section begins with its `capacity_units`, `available_units`, and `interred_units` all at zero, and these counts thereafter track its children per §2.7.

Into an `IN_GROUND` section an admin adds gravesites. Each gravesite carries a `grid_ref` (a row/column reference unique within its section), a `gravesite_class` of `STANDARD`, `OVERSIZE`, or `CREMATION`, and a `depth_capacity` — the number of interments the plot can hold, such as one for a single depth or two for a double-depth plot. A new gravesite starts with `status` of `AVAILABLE` and an `interment_count` of zero; its `reserved_by_case_id` is null while it remains available. Attempting to add a gravesite under a `COLUMBARIUM` section is rejected with `ERR_UNIT_KIND_MISMATCH`.

Into a `COLUMBARIUM` section an admin adds niches. Each niche carries a `niche_ref` (a column/tier reference unique within its section) and an `urn_capacity` — the number of urns the niche can hold, one for a single niche or two for a companion niche. A new niche starts with `status` of `AVAILABLE` and an `inurnment_count` of zero, with a null `reserved_by_case_id`. Adding a niche under an `IN_GROUND` section is likewise rejected with `ERR_UNIT_KIND_MISMATCH`.

An admin may retire an unused plot: decommissioning a gravesite is permitted only while it is `AVAILABLE`, moving it from `AVAILABLE` to `DECOMMISSIONED` and removing it from all future allocation. Because the unit's status has changed, the parent section's inventory counts are recomputed.

### 3.2. Adjudicating Eligibility

A burial case is opened against a target cemetery by either an `EligibilityOfficer` or a `SchedulingClerk`. The creator supplies the `case_type` (`AT_NEED` for a decedent or `PRE_NEED` for a living applicant), the `applicant_role` (`VETERAN`, `SPOUSE`, or `DEPENDENT`), and the `requested_class` (`STANDARD`, `OVERSIZE`, or `CREMATION`). For a `SPOUSE` or `DEPENDENT` case the creator also supplies `reserving_case_id`, naming the sponsoring veteran's case from which eligibility is derived; for a `VETERAN` case this is null. Optional inputs include `is_overseas_case` (defaulting to false), and — used only when the applicant is a veteran — `character_of_discharge` (`HONORABLE`, `GENERAL`, `OTHER_THAN_HONORABLE`, or `DISHONORABLE`), `service_days` (total active-duty days, defaulting to zero), and `died_on_active_duty` (defaulting to false). A freshly opened case starts in `SUBMITTED`.

An `EligibilityOfficer` then runs the determination, which is the branch point of the case lifecycle: the same operation drives the case from `SUBMITTED` either to `ELIGIBLE` or to `INELIGIBLE`, and it writes an `EligibilityDetermination` recording the outcome. That record carries the `burial_case_id` it adjudicated, a `decision` of `APPROVED` or `DENIED`, and the adjudicating officer's identifier in `decided_by_user_id`. On approval it records a `basis`; on denial it records a `denial_reason` and leaves `basis` unfilled, and it leaves `denial_reason` unfilled on approval.

The decision follows a fixed evaluation order, and the first matching branch wins. First, if the case's overseas designation does not equal its cemetery's overseas designation — that is, `is_overseas_case` differs from the cemetery's `is_overseas` — the case is denied with `denial_reason` of `CEMETERY_MISMATCH`. Otherwise, for a veteran applicant the rules read the discharge and service facts directly: if `died_on_active_duty` is true, the case is approved with `basis` of `DIED_IN_SERVICE`, which waives both the discharge and the minimum-service tests; failing that, if `character_of_discharge` is either `OTHER_THAN_HONORABLE` or `DISHONORABLE`, the case is denied with `denial_reason` of `DISCHARGE_BAR`; failing that, if `service_days` is less than the minimum of 730 active-duty days, the case is denied with `denial_reason` of `INSUFFICIENT_SERVICE`; otherwise it is approved with `basis` of `VETERAN_SERVICE`. For a spouse or dependent applicant the rules ignore the applicant's own discharge and service entirely and look only to the sponsor: the sponsor is the case named by `reserving_case_id`, and if that sponsor is absent or its status is not one of `ELIGIBLE`, `ASSIGNED`, `SCHEDULED`, or `INTERRED`, the case is denied with `denial_reason` of `SPONSOR_NOT_ELIGIBLE`; otherwise it is approved with `basis` of `DERIVED_SPONSOR`. Finally, as an overriding refinement: when a case that would otherwise be approved is both an overseas case and targets an overseas cemetery, its `basis` is set to `OVERSEAS_ONLY` in place of the basis the branch above would have assigned.

A denied case lands in `INELIGIBLE`, which is terminal and cannot proceed. An approved case lands in `ELIGIBLE`, and at that moment the system computes its `entitlement_score`.

### 3.3. The Entitlement Score

The `entitlement_score` is a weighted priority score computed only for approved cases, at the moment the case becomes `ELIGIBLE`. It is built up term by term, summed, and clamped last.

The base term is fixed by the applicant's role: 100 points for a `VETERAN`, 60 for a `SPOUSE`, and 40 for a `DEPENDENT`. A service bonus is then computed from whole years of service: take the `service_days`, divide by 365 and take the floor to get completed years, multiply by 3 points per year, and cap the result at 30 points — whichever is smaller, the computed value or 30, is the service bonus. A death-in-service term adds 25 points when `died_on_active_duty` is true and nothing otherwise. A discharge term adds 10 points when `character_of_discharge` is exactly `HONORABLE` and nothing otherwise. The four terms are summed, and the total is then clamped so that the final `entitlement_score` is the smaller of that sum and a ceiling of 150.

For a spouse or dependent case the score is derived from the sponsor: the base term still uses the dependent's own role weight (60 or 40), but the service-bonus, death-in-service, and discharge terms all read the sponsor case's `service_days`, `died_on_active_duty`, and `character_of_discharge` rather than the dependent's own. For a veteran case every term reads the case's own fields.

### 3.4. Assigning a Plot from Inventory

Once a case is `ELIGIBLE`, a `SchedulingClerk` assigns it a burial unit, advancing it from `ELIGIBLE` to `ASSIGNED`. For a `PRE_NEED` case, this is permitted only when a pre-need determination for the case exists in `APPROVED` status; if none does, the assignment is rejected with `ERR_PMC_REQUIRED`, and if the approved certificate's reservation window has already elapsed — that is, the current time is at or past its expiry — it is rejected with `ERR_PMC_EXPIRED`.

Assignment comes in two modes. If the clerk supplies an explicit `unit_id` (and, where needed to disambiguate, a `unit_type`), that named unit is used; it must belong to the case's own cemetery — a unit outside it is rejected with `ERR_UNIT_KIND_MISMATCH` — and it must be `AVAILABLE` (or already reserved by this same case). Because an explicit gravesite assignment is an optimistic-concurrency write, it must carry `expected_gravesite_version` and is rejected with `ERR_STALE_GRAVESITE_VERSION` on a version mismatch, as detailed in §2.9. If no explicit unit is supplied, the server auto-selects a unit through the allocation waterfall.

The waterfall first forms the candidate set: units in the case's cemetery that are `AVAILABLE` and whose class matches the request. A `STANDARD` or `OVERSIZE` request targets an in-ground gravesite whose `gravesite_class` equals the `requested_class`. A `CREMATION` request may be satisfied either by a gravesite whose `gravesite_class` is `CREMATION` or, as a fallback, by any niche. The candidates are then ranked by four keys in order: first by unit-kind priority, where a gravesite whose class exactly matches the requested class ranks ahead of a niche fallback; then by the section's `code` in ascending order; then by the unit's `grid_ref` or `niche_ref` in ascending lexicographic order; and finally, as the last deterministic tie-break, by `created_at` ascending — never by `id`. The first candidate in this ranking is selected. If the candidate set is empty, the assignment is rejected with `ERR_NO_AVAILABLE_UNIT`; the same error also covers the case where an explicitly named unit is not in an assignable state or does not match the requested class.

On a successful assignment the system records the chosen unit on the case by setting `assigned_unit_type` (`GRAVESITE` or `NICHE`), and setting `assigned_gravesite_id` for an in-ground plot or `assigned_niche_id` for a niche while leaving the other null. It moves the chosen unit from `AVAILABLE` to `RESERVED`, sets that unit's `reserved_by_case_id` to the case's `id`, and increments the reserved unit's `version` by one. The parent section's inventory counts are recomputed. For a `PRE_NEED` case, the successful assignment also drives the linked pre-need determination from `APPROVED` to `RESERVED`.

A clerk may undo an assignment by releasing the plot, reverting the case from `ASSIGNED` back to `ELIGIBLE`. This is permitted only when no interment schedule in `SCHEDULED` or `COMPLETED` status references the case. Releasing moves the reserved unit from `RESERVED` back to `AVAILABLE`, clears its `reserved_by_case_id`, clears the case's `assigned_unit_type`, `assigned_gravesite_id`, and `assigned_niche_id`, and recomputes the parent section's inventory. Separately, a clerk may cancel a case that is still `ELIGIBLE` with no plot reserved, driving it from `ELIGIBLE` to `CANCELLED` with no inventory impact.

### 3.5. Pre-Need Memorial Certificates

A pre-need case reserves a future interment right for a living applicant, and it is gated by a pre-need memorial certificate. An `EligibilityOfficer` opens a pending certificate for a case by supplying its `burial_case_id` — the case must be `PRE_NEED` — and the new `PreNeedDetermination` begins in `PENDING`, with its `pmc_number` and `expires_on` unset.

The officer then either approves or denies the pending certificate; both are permitted only from `PENDING`. Approval requires the linked burial case to be `PRE_NEED` and in `ELIGIBLE` status, and it is an optimistic-concurrency write: the request carries `expected_pmc_version` and is rejected with `ERR_STALE_PMC_VERSION` on a version mismatch (§2.9). On approval the determination moves to `APPROVED`, a `pmc_number` is issued, `expires_on` is set to the approval instant plus a reservation window of 365 days, and its `version` is incremented. Denial moves the determination to `DENIED` and increments its `version`.

The reservation is bounded in time. An approved certificate becomes `RESERVED` automatically when the linked case is successfully assigned a plot before the window elapses, as described in §3.4, and this transition increments the determination's `version`. If instead the window elapses with no plot assigned, an `NCA_Admin` runs an expiry sweep: when the current time is at or past `expires_on` and no plot has been assigned to the linked case, the certificate moves from `APPROVED` to `EXPIRED`. If at that point the linked case still holds a reserved unit, that unit is moved from `RESERVED` back to `AVAILABLE` and its `reserved_by_case_id` is cleared; the sweep increments the determination's `version`. The states `DENIED`, `RESERVED`, and `EXPIRED` are all terminal.

The logical clock that governs `expires_on` and all window comparisons starts, at server startup, at exactly `2026-05-01T00:00:00Z` and stays there until explicitly moved; it never falls back to wall-clock time. An `NCA_Admin` may advance or set the clock by supplying a `to_iso8601` instant, and every expiry and window computation thereafter reads the logical clock.

### 3.6. Headstone and Marker Orders

A `MarkerClerk` drafts a marker order for a case that has reached at least `ASSIGNED`, supplying the `burial_case_id`, a `marker_type` (`UPRIGHT_MARBLE`, `FLAT_GRANITE`, `FLAT_BRONZE`, or `NICHE_COVER`), the `inscription_lines` (an ordered list of line strings), and an optional approved `emblem_of_belief` code. The order begins in `DRAFT`, with its `billable_characters` and `marker_charge_cents` unset until submission.

Submitting a draft order enforces two conditions before it moves to `SUBMITTED`. The inscription must be within limits: no more than 6 lines, and each individual line no longer than 40 characters; a violation is rejected with `ERR_INSCRIPTION_LIMIT_EXCEEDED`. And the `marker_type` must agree with the unit kind — `NICHE_COVER` must be used when and only when the case's `assigned_unit_type` is `NICHE`, so a niche cover on a gravesite case, or any other marker type on a niche case, is rejected with `ERR_UNIT_KIND_MISMATCH`.

On submission the charge is computed with a pinned order of operations. First, count the exact number of characters in each line of `inscription_lines`, then sum those per-line counts into a single total across all lines. If an `emblem_of_belief` is present, add a further 15 characters to that total; otherwise add nothing. From this figure subtract a free allowance of 60 characters, and if the result is negative treat it as zero — the allowance is applied once against the summed total, never per line. The surviving figure is the order's `billable_characters`. To price it, divide the billable characters by a block size of 10 characters, round up to the next whole block, and multiply the number of whole blocks by 250 cents; the product is `marker_charge_cents`.

Engraving a submitted order moves it from `SUBMITTED` to `ENGRAVED`, and is permitted only once the linked burial case has reached `INTERRED`. A marker order may be cancelled from either `DRAFT` or `SUBMITTED`, moving it to `CANCELLED`.

### 3.7. Interment Scheduling and Completion

With a case in `ASSIGNED`, a `SchedulingClerk` books the interment, driving the case from `ASSIGNED` to `SCHEDULED`. The clerk supplies the `burial_case_id` and the requested window as `window_start` and `window_end` (both UTC). The window must be well-formed — `window_end` must be strictly later than `window_start`, else the request is rejected with `ERR_INVALID_WINDOW`. The new schedule copies its unit reference from the case: `gravesite_id` for a gravesite case or `niche_id` for a niche case. A newly created schedule begins in `SCHEDULED`.

Before the schedule is accepted, the requested window is checked for conflict against existing `SCHEDULED` and `COMPLETED` schedules on the same unit, and the two unit kinds use different interval semantics. On a gravesite the interval is closed-closed with a mandatory 48-hour teardown buffer between interments: the new window conflicts with an existing schedule on the same gravesite when the new window's start is at or before the existing window's end plus 48 hours, and at the same time the new window's end plus 48 hours is at or after the existing window's start — in other words, two interments on one plot must be separated by at least the buffer. A gravesite conflict is rejected with `ERR_GRAVESITE_WINDOW_CONFLICT`. On a niche the interval is half-open with no buffer, so back-to-back inurnments are allowed: the new window conflicts with an existing schedule on the same niche only when the new window's start is strictly before the existing window's end and the existing window's start is strictly before the new window's end; touching endpoints, where the new window's start equals the existing window's end, do not conflict. A niche conflict is rejected with `ERR_NICHE_WINDOW_CONFLICT`.

Completing a scheduled interment moves the schedule from `SCHEDULED` to `COMPLETED` and drives the case from `SCHEDULED` to `INTERRED`. It increments the assigned unit's `interment_count` (for a gravesite) or `inurnment_count` (for a niche) by one; when that count reaches the unit's `depth_capacity` (gravesite) or `urn_capacity` (niche), the unit moves from `RESERVED` to `OCCUPIED`. The parent section's inventory is recomputed. Any linked `CONFIRMED` military-honors record is driven to `RENDERED`.

Cancelling a scheduled interment moves the schedule from `SCHEDULED` to `CANCELLED` and reverts the case from `SCHEDULED` back to `ASSIGNED`. As a cascade, any linked military-honors record in `REQUESTED` or `CONFIRMED` is driven to `CANCELLED`, and if such a record had `flag_issued` set to true, that flag is reset to false. Both completion and cancellation act only on a schedule that is currently `SCHEDULED`.

### 3.8. Military Honors and the Burial Flag

A `HonorsCoordinator` requests a military-honors detail for an interment by supplying the `interment_schedule_id` — whose schedule must be `SCHEDULED` — and the `detail_size`, either `TWO_PERSON` or `FULL_SQUAD`. The new record begins in `REQUESTED` with `flag_issued` false, and its `honors_date` is derived as the date component (UTC midnight) of the linked schedule's `window_start`, which is the key used for daily capacity counting.

Confirming a requested detail moves it from `REQUESTED` to `CONFIRMED` and is gated by three conditions. The linked interment schedule must still be `SCHEDULED`. The cemetery's daily honors capacity must not be exhausted: count the confirmed honors on the same `honors_date` at the same cemetery, and if that count is already at or above the cemetery's `honors_squad_capacity`, the confirmation is rejected with `ERR_HONORS_CAPACITY_FULL` — the boundary is inclusive, so when capacity is N the Nth already-confirmed detail leaves no room for another. And a `FULL_SQUAD` detail requires that the case's `entitlement_score` be at least 110; a lesser score is rejected with `ERR_HONORS_ENTITLEMENT_INSUFFICIENT`. On confirmation the burial flag is issued by setting `flag_issued` to true.

A confirmed detail advances to `RENDERED` automatically when its interment is completed, as described in §3.7. A coordinator may also cancel a detail from either `REQUESTED` or `CONFIRMED`, moving it to `CANCELLED`; if the flag had been issued, `flag_issued` is reset to false. The same cancellation, and the same flag withdrawal, also occur as a cascade when the underlying interment schedule is cancelled.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource or add a new resource to a collection return `201 Created`. Operations that modify an existing resource — including state transitions and administrative actions — return `200 OK`. Read operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock | NCA_Admin |
| POST | `/cemeteries` | Create a national cemetery | NCA_Admin |
| GET | `/cemeteries` | List cemeteries | NCA_Admin, EligibilityOfficer, SchedulingClerk, MarkerClerk, HonorsCoordinator |
| GET | `/cemeteries/{cemeteryId}` | Fetch a cemetery | NCA_Admin, EligibilityOfficer, SchedulingClerk, MarkerClerk, HonorsCoordinator |
| POST | `/cemeteries/{cemeteryId}/sections` | Create a section | NCA_Admin |
| GET | `/cemeteries/{cemeteryId}/sections` | List sections of a cemetery | NCA_Admin, EligibilityOfficer, SchedulingClerk, MarkerClerk, HonorsCoordinator |
| GET | `/cemeteries/{cemeteryId}/sections/{sectionId}` | Fetch a section with recomputed inventory | NCA_Admin, EligibilityOfficer, SchedulingClerk, MarkerClerk, HonorsCoordinator |
| POST | `/cemeteries/{cemeteryId}/sections/{sectionId}/gravesites` | Create an in-ground gravesite | NCA_Admin |
| GET | `/cemeteries/{cemeteryId}/sections/{sectionId}/gravesites` | List gravesites of a section | NCA_Admin, EligibilityOfficer, SchedulingClerk, MarkerClerk, HonorsCoordinator |
| GET | `/cemeteries/{cemeteryId}/sections/{sectionId}/gravesites/{gravesiteId}` | Fetch a gravesite | NCA_Admin, EligibilityOfficer, SchedulingClerk, MarkerClerk, HonorsCoordinator |
| POST | `/cemeteries/{cemeteryId}/sections/{sectionId}/gravesites/{gravesiteId}/decommission` | Decommission an available gravesite | NCA_Admin |
| POST | `/cemeteries/{cemeteryId}/sections/{sectionId}/niches` | Create a columbarium niche | NCA_Admin |
| GET | `/cemeteries/{cemeteryId}/sections/{sectionId}/niches` | List niches of a section | NCA_Admin, EligibilityOfficer, SchedulingClerk, MarkerClerk, HonorsCoordinator |
| GET | `/cemeteries/{cemeteryId}/sections/{sectionId}/niches/{nicheId}` | Fetch a niche | NCA_Admin, EligibilityOfficer, SchedulingClerk, MarkerClerk, HonorsCoordinator |
| POST | `/cemeteries/{cemeteryId}/burial-cases` | Open a burial case | EligibilityOfficer, SchedulingClerk |
| GET | `/cemeteries/{cemeteryId}/burial-cases` | List burial cases of a cemetery | NCA_Admin, EligibilityOfficer, SchedulingClerk, MarkerClerk, HonorsCoordinator |
| GET | `/cemeteries/{cemeteryId}/burial-cases/{caseId}` | Fetch a burial case | NCA_Admin, EligibilityOfficer, SchedulingClerk, MarkerClerk, HonorsCoordinator |
| POST | `/cemeteries/{cemeteryId}/burial-cases/{caseId}/eligibility` | Run eligibility determination | EligibilityOfficer |
| GET | `/cemeteries/{cemeteryId}/burial-cases/{caseId}/eligibility` | Fetch a case's eligibility determination | NCA_Admin, EligibilityOfficer, SchedulingClerk |
| POST | `/cemeteries/{cemeteryId}/burial-cases/{caseId}/assign-plot` | Assign a plot to an eligible case | SchedulingClerk |
| POST | `/cemeteries/{cemeteryId}/burial-cases/{caseId}/release-plot` | Release a reserved plot | SchedulingClerk |
| POST | `/cemeteries/{cemeteryId}/burial-cases/{caseId}/cancel` | Cancel an eligible case | SchedulingClerk |
| POST | `/cemeteries/{cemeteryId}/pre-need-determinations` | Open a pending PMC determination | EligibilityOfficer |
| GET | `/cemeteries/{cemeteryId}/pre-need-determinations` | List PMC determinations | NCA_Admin, EligibilityOfficer, SchedulingClerk |
| GET | `/cemeteries/{cemeteryId}/pre-need-determinations/{pmcId}` | Fetch a PMC determination | NCA_Admin, EligibilityOfficer, SchedulingClerk |
| POST | `/cemeteries/{cemeteryId}/pre-need-determinations/{pmcId}/approve` | Approve a pending PMC | EligibilityOfficer |
| POST | `/cemeteries/{cemeteryId}/pre-need-determinations/{pmcId}/deny` | Deny a pending PMC | EligibilityOfficer |
| POST | `/cemeteries/{cemeteryId}/pre-need-determinations/{pmcId}/expire-sweep` | Expire an elapsed approved PMC | NCA_Admin |
| POST | `/cemeteries/{cemeteryId}/interment-schedules` | Schedule an interment for an assigned case | SchedulingClerk |
| GET | `/cemeteries/{cemeteryId}/interment-schedules` | List interment schedules | NCA_Admin, EligibilityOfficer, SchedulingClerk, HonorsCoordinator |
| GET | `/cemeteries/{cemeteryId}/interment-schedules/{scheduleId}` | Fetch an interment schedule | NCA_Admin, EligibilityOfficer, SchedulingClerk, HonorsCoordinator |
| POST | `/cemeteries/{cemeteryId}/interment-schedules/{scheduleId}/complete` | Complete an interment | SchedulingClerk |
| POST | `/cemeteries/{cemeteryId}/interment-schedules/{scheduleId}/cancel` | Cancel a scheduled interment | SchedulingClerk |
| POST | `/cemeteries/{cemeteryId}/marker-orders` | Draft a marker order | MarkerClerk |
| GET | `/cemeteries/{cemeteryId}/marker-orders` | List marker orders | NCA_Admin, MarkerClerk, SchedulingClerk |
| GET | `/cemeteries/{cemeteryId}/marker-orders/{markerId}` | Fetch a marker order | NCA_Admin, MarkerClerk, SchedulingClerk |
| POST | `/cemeteries/{cemeteryId}/marker-orders/{markerId}/submit` | Submit a draft marker order | MarkerClerk |
| POST | `/cemeteries/{cemeteryId}/marker-orders/{markerId}/engrave` | Engrave a submitted marker order | MarkerClerk |
| POST | `/cemeteries/{cemeteryId}/marker-orders/{markerId}/cancel` | Cancel a marker order | MarkerClerk |
| POST | `/cemeteries/{cemeteryId}/military-honors` | Request military honors | HonorsCoordinator |
| GET | `/cemeteries/{cemeteryId}/military-honors` | List military honors | NCA_Admin, HonorsCoordinator, SchedulingClerk |
| GET | `/cemeteries/{cemeteryId}/military-honors/{honorsId}` | Fetch a military-honors record | NCA_Admin, HonorsCoordinator, SchedulingClerk |
| POST | `/cemeteries/{cemeteryId}/military-honors/{honorsId}/confirm` | Confirm requested honors | HonorsCoordinator |
| POST | `/cemeteries/{cemeteryId}/military-honors/{honorsId}/cancel` | Cancel requested/confirmed honors | HonorsCoordinator |

The list endpoints accept these filter query parameters in addition to `limit` and `offset`: gravesite and niche lists accept `status`; the burial-case list accepts `status`, `reserving_case_id`, `assigned_gravesite_id`, and `assigned_niche_id`; the pre-need list accepts `burial_case_id` and `status`; the interment-schedule list accepts `burial_case_id`, `gravesite_id`, `niche_id`, and `status`; the marker-order list accepts `burial_case_id` and `status`; the military-honors list accepts `interment_schedule_id` and `status`.

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCE_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_UNIT_KIND_MISMATCH` | 422 |
| `ERR_INVALID_WINDOW` | 422 |
| `ERR_GRAVESITE_WINDOW_CONFLICT` | 409 |
| `ERR_NICHE_WINDOW_CONFLICT` | 409 |
| `ERR_INSCRIPTION_LIMIT_EXCEEDED` | 422 |
| `ERR_HONORS_ENTITLEMENT_INSUFFICIENT` | 422 |
| `ERR_HONORS_CAPACITY_FULL` | 409 |
| `ERR_NO_AVAILABLE_UNIT` | 409 |
| `ERR_STALE_GRAVESITE_VERSION` | 412 |
| `ERR_STALE_PMC_VERSION` | 412 |
| `ERR_PMC_REQUIRED` | 409 |
| `ERR_PMC_EXPIRED` | 409 |
