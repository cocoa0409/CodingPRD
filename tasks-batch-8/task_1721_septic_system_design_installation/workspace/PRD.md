# Septic System Contracting API — Product Requirements Document

## 1. Introduction

Onsite wastewater work sits at the intersection of public health regulation and heavy construction. A licensed septic installer company does not merely dig and set tanks: it coordinates licensed soil scientists who evaluate parcels, licensed designers who size treatment systems against that science, county health officers who adjudicate designs and issue permits, and inspectors who sign off on mandated hold points before soil is backfilled. Every handoff is auditable, every approval is pinned to a specific revision of a specific design, and a single late-season groundwater reading can freeze a parcel for months. Mistakes are expensive — a drain field installed against superseded percolation data, or a tank set before its hold-point inspection passes, means excavation, fines, and a failed final.

This document specifies a compliance-first operations API for that business, mounted under `/septic-ops`. It covers the full lifecycle of a septic installation contract: company and staff registration, customer and parcel intake, soil evaluation and percolation testing with automatic supersession of stale science, system design and sizing with a regulator-facing amendment chain, variance relief for non-conforming parcels, permit issuance and enforcement, hold-point-gated installation with material verification and budget ceilings, homeowner education, ongoing maintenance contracts, and repair or replacement of failed systems. Time inside the platform is deterministic: each site carries its own logical period clock, and every temporal rule — science staleness, permit validity, freeze windows, contract lapse — is evaluated against that clock rather than against wall-clock time. Six segregated roles share the surface, and every mutating workflow is guarded by explicit state machines, ownership checks, and optimistic concurrency controls.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming exactly one of the six roles below. A request missing either header, or carrying an empty value for either, is rejected with `ERR_MISSING_AUTH` (HTTP 401). A request whose role is not permitted for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

The six roles, spelled exactly as the API expects them:

- `PlatformAdmin` — the back-office operator who registers installer companies and all licensed staff. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it against any resource's `id`.
- `ProjectManager` — runs the customer, site, installation, inspection-scheduling, material, contract, education, and repair-case lifecycle. When `X-User-Role` is `ProjectManager`, `X-User-ID` is the `id` of the acting `ProjectManager` staff record; ownership checks on any resource that references a project manager — for example, a material verification's `verified_by` — compare that foreign-key field to `X-User-ID`.
- `SystemDesigner` — authors and submits designs and files variance requests. When `X-User-Role` is `SystemDesigner`, `X-User-ID` is the `id` of the acting `SystemDesigner` record, and ownership checks compare a design's `designer_id` to `X-User-ID`.
- `SoilScientist` — records and voids soil evaluations and percolation tests. When `X-User-Role` is `SoilScientist`, `X-User-ID` is the `id` of the acting `SoilScientist` record, and ownership checks compare the evaluation or test's `evaluator_id` to `X-User-ID`.
- `Inspector` — decides hold-point inspections. When `X-User-Role` is `Inspector`, `X-User-ID` is the `id` of the acting `Inspector` record, and ownership checks compare an inspection's `inspector_id` to `X-User-ID`.
- `HealthOfficer` — the authority officer who decides designs and variance requests and who issues, suspends, reinstates, and revokes permits. When `X-User-Role` is `HealthOfficer`, `X-User-ID` is the `id` of the acting `HealthOfficer` record; where a workflow records the deciding officer, the supplied `officer_id` (or the persisted `decided_by`) is expected to equal `X-User-ID`.

All six roles may use every read endpoint. Write privileges are exclusive per role as detailed throughout §3 and summarized in §4.

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

### 2.3. Pagination and List Filtering

Every list endpoint accepts two optional query parameters: `limit`, the page size, defaulting to 10 with a minimum of 1 and a maximum of 100; and `offset`, the number of records to skip, defaulting to 0. List responses are always sorted by `created_at` in ascending order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

Beyond paging, most list endpoints expose domain filters. Site, soil evaluation, percolation test, design, permit, installation, variance request, maintenance contract, and repair case lists accept a `status` filter; inspection lists accept a `result` filter; material verification lists accept a `verified` filter. The flat read surface described in §2.5 additionally accepts foreign-key filters — `installer_company_id`, `customer_id`, `site_id`, `evaluator_id`, `superseded_by_id`, `designer_id`, `soil_evaluation_id`, `percolation_test_id`, `supersedes_design_id`, `design_id`, `permit_id`, `installation_id`, `inspector_id`, `verified_by`, `decided_by`, `contract_id`, `failed_installation_id`, and `replacement_design_id` — each narrowing the list to rows whose matching field equals the supplied value.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource in the platform carries four common properties. The `id` is a server-minted UUID with no type prefix. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits, recorded at creation and refreshed on every mutation respectively. `version` is an integer that increments by one on every mutation of the resource, whether the mutation arrives through a direct client action or through an internal cascade. A handful of workflows call out their version bumps explicitly — design revision, permit reinstatement, and contract renewal among them — but the general rule holds everywhere: any state change bumps `version` and refreshes `updated_at`.

### 2.5. Resource Hierarchy, Path Validation, and the Flat Read Surface

Resources form a strict hierarchy. An installer company sits at the root; beneath it live customers and the five staff registries (soil scientists, system designers, inspectors, health officers, project managers); beneath a customer live sites; and beneath a site live the working records — soil evaluations, percolation tests, designs, permits, installations, variance requests, maintenance contracts, and repair cases. Inspections and material verifications nest beneath an installation, and maintenance visits nest beneath a contract. Nested URLs encode this chain left to right through path variables named `cid` for the company, `cuid` for the customer, `sid` for the site, `ssid` for a soil scientist, `dsid` for a designer, `iid` for an inspector in the company registry or an installation under a site (context disambiguates), `hid` for a health officer, `pmid` for a project manager, `eid` for a soil evaluation, `ptid` for a percolation test, `did` for a design, `pid` for a permit, `inspid` for an inspection, `mvid` for a material verification, `vid` for a variance request or a visit (context disambiguates), `mcid` for a maintenance contract, and `rid` for a repair case — rendered in §4 paths in their braced form (for example, `{cid}`).

Nested path validation proceeds strictly left to right: every identifier in the path must exist, and each resource must belong to its declared parent chain — company to customer to site to the child record. Any break in that chain is `ERR_NOT_FOUND` (HTTP 404); the server never reveals whether the failing segment was the parent or the child.

In parallel with the nested surface, the platform exposes a flat alias read surface for walking the graph in reverse: endpoints such as the flat site, design, permit, installation, inspection, material verification, variance request, maintenance contract, visit, and repair case lists return the same entity shapes as their nested counterparts and accept the foreign-key filters enumerated in §2.3. Alias endpoints exist for reading a designer's designs, a scientist's evaluations and tests, an inspector's inspections, an officer's decided variances, a manager's verified materials, a design's permits, variance requests, and replacement repair cases, a permit's installations, and an installation's contracts and repair cases.

### 2.6. Logical Site Time and the Seasonal Clock

Time inside the platform is deterministic and per-site. Every site carries a `current_period_index`, an integer logical clock that starts at 0 when the site is registered and advances only when a `ProjectManager` explicitly advances it, supplying a `by_periods` increment. The clock never reads wall-clock time, and no temporal rule in this document consults anything but the site's own period index. All dated workflow records — an evaluation's `evaluation_date_period`, a perc test's `test_date_period`, a permit's `issued_period` and `expires_period`, an installation's `started_period` and `completed_period`, an inspection's `scheduled_period` and `decided_period`, a verification's `verified_period`, a contract's `start_period` and `end_period`, a visit's `visit_period`, and an education delivery's `delivery_period` — are expressed in these site-relative period indices.

Advancing the clock is a cascading event. When the new `current_period_index` moves past a frozen site's `seasonal_freeze_until`, the site thaws automatically, returning to `OPEN` with its freeze marker reset to -1. Each `ISSUED` permit whose `expires_period` now lies behind the clock transitions to `EXPIRED`, and every non-terminal installation authorized by such a permit is forced to `FAILED_HOLD`. Each `ACTIVE` maintenance contract whose `end_period` now lies behind the clock transitions to `LAPSED`, and each contract already `LAPSED` whose grace window — its `end_period` plus the lapse grace period count — now lies behind the clock transitions to `EXPIRED`.

### 2.7. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control, each pinning a parent entity's version at call time:

- Returning a rejected design to draft requires `expected_design_version`, carrying the client's last observed `version` of that design. If the design's current `version` has advanced since — for instance because another writer already revised it, legitimately moving it back to `DRAFT` and bumping the version — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from revising a design it has not observed.
- Reinstating a suspended permit requires `expected_permit_version`, carrying the client's last observed `version` of that permit. A mismatch with the permit's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Renewing a lapsed maintenance contract requires `expected_contract_version`, carrying the client's last observed `version` of that contract. A mismatch with the contract's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412).

These three fields are non-optional on their respective endpoints. Endpoints not named in this section take no version field at all.

### 2.8. Cascading State Propagation Across the Design–Permit–Installation Chain

Several single operations fan out into multi-hop cascades, and every hop is part of the contract. Recording a fresh soil evaluation or percolation test supersedes the previously `RECORDED` record for the site, and every `DRAFT` design still pinning that now-stale science is automatically withdrawn; a later attempt to submit a design pinning superseded or voided science is refused outright. Approving a design when the site already holds another `APPROVED` design supersedes the older design, which in turn suspends any permit pinning it, which in turn forces any non-terminal installation under such a permit into `FAILED_HOLD`. Suspending or expiring a permit forces its non-terminal installations to `FAILED_HOLD`, while revoking a permit forces them to `ABANDONED`. A passing final inspection completes the installation, finalizes the authorizing permit, and arms homeowner education for the customer. Cancelling a maintenance contract deletes its future visits while retaining past ones. Every row touched by a cascade follows the common mutation rule of §2.4.

Reinstatement is deliberately asymmetric with these cascades: installations forced to `FAILED_HOLD` by a suspension are not restored when the permit is reinstated. Each such installation requires an explicit remediation action by a `ProjectManager` to return to `READY_FOR_FINAL`.

### 2.9. Validation Order and Error Discipline

When a single request violates more than one rule, the applicable checks are evaluated in a fixed precedence order and only the first failure is reported. The order is: (1) authentication header presence — `ERR_MISSING_AUTH`; (2) role authorization for the endpoint — `ERR_FORBIDDEN`; (3) existence of every path identifier and its agreement with the declared parent chain — `ERR_NOT_FOUND`; (4) existence and same-company/same-site scope of every foreign key supplied in the request body (`evaluator_id`, `designer_id`, `soil_evaluation_id`, `percolation_test_id`, `permit_id`, `design_id`, `installation_id`, `inspector_id`, `officer_id`, `failed_installation_id`, `replacement_design_id`) — `ERR_FK_NOT_FOUND` (HTTP 422); (5) admissibility of the requested state transition — `ERR_INVALID_STATE`; (6) seasonal freeze blocking — `ERR_SITE_FROZEN`; (7) permit expiry — `ERR_PERMIT_EXPIRED`; (8) pinned science status — `ERR_STALE_SCIENCE`; (9) science age — `ERR_SCIENCE_EXPIRED`; (10) variance prerequisites — `ERR_VARIANCE_REQUIRED`; (11) segregation of duties — `ERR_SEGREGATION_OF_DUTIES`; (12) hold-point passage — `ERR_HOLD_POINT_NOT_PASSED`; (13) material verification completeness — `ERR_MATERIALS_UNVERIFIED`; (14) permit status for installation work — `ERR_PERMIT_NOT_ISSUED`; (15) replacement design approval — `ERR_REPLACEMENT_DESIGN_NOT_APPROVED`; (16) inspection scheduling maturity — `ERR_INSPECTION_TOO_EARLY`; (17) visit window membership — `ERR_VISIT_OUTSIDE_CONTRACT`, followed immediately by inspector scheduling capacity — `ERR_SCHEDULING_CONFLICT`; (18) narrative minimum lengths — `ERR_INSUFFICIENT_NOTE`; (19) field ranges and uniqueness — `ERR_INVALID_REQUEST`; (20) the material budget ceiling — `ERR_MATERIAL_BUDGET_EXCEEDED`; (21) freeze windows set in the past — `ERR_FREEZE_IN_PAST`; (22) renewal monotonicity — `ERR_INVALID_RENEWAL`; (23) site-close completeness — `ERR_OPEN_WORK_REMAINS`; (24) final-inspection readiness — `ERR_INSTALLATION_NOT_READY`; (25) stale-version optimistic concurrency — `ERR_STALE_VERSION`; (26) live-design pinning — `ERR_PINNED_BY_LIVE_DESIGN`; (27) remediation start prerequisites — `ERR_REMEDIATION_NOT_STARTED`; (28) enumerated decision payloads — `ERR_INVALID_DECISION`; and finally (29) creation-time state prerequisites — `ERR_INVALID_STATE` in its creation-scope guise, covering contracts over non-completed installations, education delivered before any installation has completed, repair cases over non-completed installations, and permits issued over non-approved designs.

All errors share the envelope of §2.2. Trigger conditions for each error live with the workflows that raise them in §3; §5 is a catalogue of identifiers and HTTP statuses only.

## 3. Business Logic & Workflows

### 3.1. Company Onboarding, Staff Registries, Customers, and Sites

A `PlatformAdmin` opens engagement by registering an installer company with its `legal_name`, a state contractor `license_number` that is unique across registered companies, and the `county_codes` listing the counties the company is licensed to operate in. The same operator then staffs the company through five registries: soil scientists, system designers, and inspectors each registered with a `full_name` and a `license_number`; health officers with a `full_name` and an authority `badge_number`; and project managers with a `full_name` and an internal `employee_number`. Each license, badge, or employee number must be unique within its company registry; a duplicate is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Every staff record carries its employing company's `installer_company_id`, and inspectors are attached to the company deliberately segregated from installers so the same hands never both build and approve.

With staff in place, a `ProjectManager` registers customers with `full_name`, `email`, and `phone`; the email must be unique within the installer company, again enforced as `ERR_INVALID_REQUEST`. Each customer record carries the owning `installer_company_id` and an `education_completed_at` timestamp that stays null until the homeowner education record is delivered at the end of a successful build.

Sites — county tax parcels — are registered beneath a customer with a `parcel_id` unique within the installer company, an `address_line`, a `county_code` that must appear in the installer company's `county_codes` (a parcel in an uncovered county is `ERR_INVALID_REQUEST`), and a `high_water_table` flag marking parcels with a documented seasonal high water table, which forces elevated design constraints downstream. Every site also carries the customer's `customer_id` and a denormalized `installer_company_id` for scoping. A new site's `status` is `OPEN`, its `current_period_index` is 0, and its `seasonal_freeze_until` is -1, meaning no freeze.

### 3.2. Soil Science: Evaluations and Percolation Tests

Before any design exists, a `SoilScientist` visits the parcel and records two pieces of science. The soil evaluation captures the `evaluator_id` of the recording scientist, the `soil_class` — one of `SAND`, `LOAM`, `CLAY_LOAM`, or `CLAY` — and the `limiting_layer_inches`, the depth in inches to the limiting layer (rock, water table, or hardpan), which must lie between 1 and 240 inches. The percolation test captures its own `evaluator_id`, the measured `minutes_per_inch` rate between 0.5 and 240.0 recorded to a tenth of a minute, and a `test_pit_count` between 2 and 12. Out-of-range values on any of these are `ERR_INVALID_REQUEST`. At recording time the server stamps the evaluation's `evaluation_date_period` and the test's `test_date_period` with the site's current period index, and both records enter life in `RECORDED` status.

Science is single-generational per site. Recording a new evaluation for a site automatically transitions whichever evaluation was previously `RECORDED` to `SUPERSEDED`, writing the new record's id into the old record's `superseded_by_id`; the same rule governs percolation tests. Supersession then cascades into design work: every `DRAFT` design still pinning the superseded record is automatically moved to `WITHDRAWN`. A design that survives this cascade — because it was already beyond draft, or because its pinned record was voided rather than superseded — is still refused at submit time, where pinning anything but `RECORDED` science surfaces as `ERR_STALE_SCIENCE`.

A scientist may also void a record outright, but only the recording scientist may do so: the acting scientist's id must equal the record's `evaluator_id`, otherwise the call is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Voiding requires the record to be `RECORDED` (otherwise `ERR_INVALID_STATE`) and is refused with `ERR_PINNED_BY_LIVE_DESIGN` while any design in `SUBMITTED` or `APPROVED` status pins the record. A successful void leaves the record in `VOIDED`, one of the two terminal states alongside `SUPERSEDED`.

### 3.3. System Design, Sizing Derivations, and the Amendment Chain

A `SystemDesigner` authors a design for a site by pinning the science it derives from: the payload names the `designer_id`, a `soil_evaluation_id`, a `percolation_test_id`, a `bedroom_count` between 1 and 12, and a `system_type` of `GRAVITY`, `PRESSURE_DISTRIBUTION`, `MOUND`, or `AEROBIC` chosen within the envelope the site data allows. The design is born in `DRAFT` status with a `design_version` of 1 — unless it is created as an amendment, as described below. Four sizing figures are computed at creation and re-derived every time the design is submitted, because variance context may have changed since creation.

The **design daily flow** is the bedroom count multiplied by 150 gallons per bedroom per day; when the site's `high_water_table` flag is true, that product is multiplied by 1.5 before anything else happens. The resulting `design_daily_flow_gpd` is recorded rounded half-up to one decimal place.

The **required absorption area** divides the flow by the soil application rate implied by the pinned evaluation's `soil_class` — 1.20 gallons per day per square foot for `SAND`, 0.80 for `LOAM`, 0.50 for `CLAY_LOAM`, and 0.30 for `CLAY`. If the pinned evaluation's `limiting_layer_inches` is less than 24 inches, the quotient is multiplied by 1.25 for the shallow-layer penalty. The final `required_absorption_area_sqft` is the result rounded up to the next whole square foot, with that ceiling applied exactly once at the very end of the chain: no intermediate rounding occurs between the surcharge, the division, and the shallow-layer multiplier, and rounding the pre-multiplier quotient first produces a different, incorrect integer.

One approved variance changes this picture. When an `APPROVED` variance request of relief kind `AREA_REDUCTION` exists for the design, the absorption-area leg alone substitutes a reduced figure of 120 gallons per bedroom per day for the standard 150. The design's `design_daily_flow_gpd` and the tank-sizing leg both continue to use the book figure of 150, so the two legs deliberately diverge within a single design.

The **tank capacity** always derives from the book flow — bedroom count times 150 gallons per day, regardless of any approved area-reduction variance — multiplied by a retention of 2.0 days. The raw requirement is then stepped up to the smallest catalog size greater than or equal to it, chosen from 750, 1000, 1250, 1500, 2000, 2500, 3000, 4000, and 5000 gallons; a raw requirement landing exactly on a catalog size keeps that size. The result is recorded as `tank_capacity_gal`.

The **reserve area** is the mandated replacement area. `reserve_area_sqft` equals the final, post-ceiling `required_absorption_area_sqft` multiplied by the reserve fraction of 1.0, rounded half-up to a whole square foot. The rule is stated so the order is pinned: the reserve derives from the ceiled absorption area, never from the pre-ceiling quotient, so the two fields can never drift apart by a rounding artifact.

Amendments form an explicit chain. A designer may pass `supersedes_design_id` at creation; the new design then carries a `design_version` one greater than the superseded design's counter, and when the named design was in `REJECTED` or `WITHDRAWN` status it transitions to `SUPERSEDED`. The new design's own `supersedes_design_id` records the link, while a first design carries null. Each design also carries a `provisional_estimate_cents` field that stays null until the design is first referenced as the replacement design of a repair case, as detailed in §3.9.

### 3.4. Authority Review: Design Decisions and Variance Relief

Submitting a design moves it from `DRAFT` to `SUBMITTED` and is a guarded gate. Only the authoring designer may submit — the acting designer's id must equal the design's `designer_id`, else `ERR_SEGREGATION_OF_DUTIES` — and the design must actually be in `DRAFT`, else `ERR_INVALID_STATE`. The site must be `OPEN`; a submit against a `FROZEN` site is refused with `ERR_SITE_FROZEN`. Both pinned science records must still be `RECORDED`, else `ERR_STALE_SCIENCE`. Finally, the science must still be fresh: the site's `current_period_index` minus the evaluation's `evaluation_date_period`, and minus the test's `test_date_period`, must each be at most 24 periods. An age of exactly 24 periods is still valid — only an age strictly greater than 24 is stale — and a violation surfaces as `ERR_SCIENCE_EXPIRED`. A successful submit also re-derives the four sizing figures of §3.3 against current variance context.

Decision power over a submitted design rests with a `HealthOfficer`, who supplies a `decision` of `APPROVE` or `REJECT` together with an `officer_id`; any other decision value is `ERR_INVALID_DECISION` (HTTP 400). Approval carries two further guards. First, independence: the officer must not be the same person as the authoring designer, and a health officer row whose `badge_number` equals the authoring designer's `license_number` is treated as the same person, failing with `ERR_SEGREGATION_OF_DUTIES`. Second, high-water relief: when the site's `high_water_table` flag is true and the design's `system_type` is `GRAVITY`, an `APPROVED` variance request of relief kind `HIGH_WATER_TABLE` must already exist for this design, else the approval fails with `ERR_VARIANCE_REQUIRED`. Approval moves the design to `APPROVED`, a terminal state, and triggers the supersession cascade of §2.8 — any other `APPROVED` design for the same site moves to `SUPERSEDED`, permits pinning it move to `SUSPENDED`, and their non-terminal installations are forced to `FAILED_HOLD`. Rejection moves the design to `REJECTED` and requires a `decision_note` of at least 20 characters, else `ERR_INSUFFICIENT_NOTE`.

Rejection is not the end of the road. The authoring designer may return a `REJECTED` design to `DRAFT` for rework — the cyclic edge of the design machine — through the revision action, which requires the OCC token `expected_design_version` equal to the design's current `version` per §2.7 and bumps `version` by one on success. A designer may also withdraw a `DRAFT` design outright, moving it to `WITHDRAWN`; only the design's own designer may do so manually, under the same ownership rule, and the same terminal state is reached automatically when pinned science is superseded, as §3.2 described.

Variance relief runs on its own track. A `SystemDesigner` files a variance request against a design by supplying the `design_id`, a `relief_kind` of `SETBACK_REDUCTION`, `AREA_REDUCTION`, `HIGH_WATER_TABLE`, or `REPAIR_IN_KIND`, and a written `justification` of at least 20 characters; short justifications fail with `ERR_INSUFFICIENT_NOTE`. The request waits in `PENDING` until a `HealthOfficer` decides it with a `decision` of `APPROVE` or `DENY` — anything else is `ERR_INVALID_DECISION` — and an `officer_id` whose `badge_number` must differ from the referenced design's designer `license_number`, else `ERR_SEGREGATION_OF_DUTIES`. Approval moves the request to `APPROVED`, records `decided_by` as the deciding officer, and keeps any supplied `decision_note`; denial moves it to `DENIED` and requires a `decision_note` of at least 20 characters. A designer may also withdraw a still-`PENDING` request, moving it to `WITHDRAWN`. An approved area-reduction variance reshapes sizing per §3.3; an approved high-water-table variance unlocks gravity approval above; an approved repair-in-kind variance gates structural-collapse triage in §3.9.

### 3.5. Permits: Issuance, Suspension, Reinstatement, Expiry, and Revocation

A permit is the authority's executable approval of one specific design revision. A `HealthOfficer` issues one for a site by naming the `design_id` and the acting `officer_id`; the referenced design must be `APPROVED` for the same site, and issuing against any other status fails with `ERR_INVALID_STATE`. Issuance mints a unique `permit_number`, records the `issued_period` as the site's current period index, and computes the `expires_period` as the issued period plus 6 minus 1 — a validity window of six periods inclusive on both ends, so a permit issued at period 0 covers periods 0 through 5 and is expired once the site clock reaches period 6. The permit is born `ISSUED`.

Three things can interrupt an issued permit. A health officer may suspend it manually, and approval of a competing design suspends it automatically per §3.4; either path moves the permit from `ISSUED` to `SUSPENDED` and forces every installation it authorizes that sits in a non-terminal state — anywhere from `NOT_STARTED` through `READY_FOR_FINAL` — into `FAILED_HOLD`. The clock can expire it: when the site's `current_period_index` advances beyond `expires_period`, the permit moves to `EXPIRED` and its non-terminal installations are likewise forced to `FAILED_HOLD`. Or a health officer may revoke it outright from either `ISSUED` or `SUSPENDED` — any other status is `ERR_INVALID_STATE` — supplying a `revoke_note` of at least 20 characters (`ERR_INSUFFICIENT_NOTE`); revocation moves the permit to `REVOKED` and forces its non-terminal installations to `ABANDONED`.

Suspension is survivable. Reinstating moves a `SUSPENDED` permit back to `ISSUED`, but only when three guards pass: the permit's pinned design must currently be `APPROVED` — a reinstate over a design since superseded fails with `ERR_PINNED_BY_LIVE_DESIGN`; the site's clock must not have moved past `expires_period`, else `ERR_PERMIT_EXPIRED`; and the request must carry `expected_permit_version` equal to the permit's current `version` per §2.7, with a mismatch rejected as `ERR_STALE_VERSION`. A successful reinstatement bumps the permit's `version` by one. Crucially, installations forced to `FAILED_HOLD` by the suspension are not restored; each one needs an explicit remediation action under §3.6. The happy-path ending is simpler: when the authorized installation reaches `COMPLETED`, the permit automatically transitions to `FINALIZED`, its work done.

### 3.6. Installation Execution: Hold Points, Inspections, and Material Control

Construction begins when a `ProjectManager` creates an installation against a site, supplying the `permit_id` of the authorizing permit — which is expected to be `ISSUED` at this point — and the `crew_lead`, the name of the on-site crew lead. The installation is born `NOT_STARTED` and progresses one leg at a time through the advance action: `NOT_STARTED` → `ROUGH_IN_PROGRESS` → `TANK_SET` → `FIELD_INSTALLED` → `READY_FOR_FINAL`, with `COMPLETED`, `FAILED_HOLD`, and `ABANDONED` as the outcomes beyond. Two standing guards apply to every advance and every remediation: the authorizing permit must be `ISSUED`, else `ERR_PERMIT_NOT_ISSUED`, and the site must be `OPEN`, else `ERR_SITE_FROZEN`.

The first leg, breaking ground into `ROUGH_IN_PROGRESS`, additionally requires the permit to be within its validity window — the site's `current_period_index` must not exceed the permit's `expires_period`, else `ERR_PERMIT_EXPIRED` — and records the current period as the installation's `started_period`. The second leg, into `TANK_SET`, requires a passed hold-point inspection of kind `TANK_SET` for the installation, else `ERR_HOLD_POINT_NOT_PASSED`, and requires every delivered material of kind `TANK` to be verified, else `ERR_MATERIALS_UNVERIFIED`. The third leg, into `FIELD_INSTALLED`, mirrors this with a passed `FIELD_LAYOUT` inspection and full verification of every `PIPE`, `AGGREGATE`, and `CHAMBER` delivery. The fourth leg, into `READY_FOR_FINAL`, gates on the pump: when the pinned design's `system_type` is `PRESSURE_DISTRIBUTION` or `AEROBIC`, every `PUMP` delivery must be verified; designs of type `GRAVITY` or `MOUND` carry no pump requirement. Attempting a leg from the wrong state is `ERR_INVALID_STATE`.

Inspections are scheduled by a `ProjectManager`, who names the `hold_point` — `TANK_SET`, `FIELD_LAYOUT`, or `FINAL` — the `inspector_id`, and a `scheduled_period` of 0 or greater. An inspector's calendar is a hard constraint: no inspector may hold two `PENDING` inspections at the same `scheduled_period`, so scheduling a second one while the first remains undecided fails with `ERR_SCHEDULING_CONFLICT`; deciding an inspection frees the slot. A scheduled inspection's `result` starts as `PENDING`. Decision belongs to the inspector of record: the acting inspector's id must equal the inspection's `inspector_id`, and the inspector's `full_name` must differ from the installation's `crew_lead` — either violation is `ERR_SEGREGATION_OF_DUTIES`. The decision cannot be recorded before its time: the site's `current_period_index` must be at least the `scheduled_period`, else `ERR_INSPECTION_TOO_EARLY`. The `decision` payload is `PASS` or `FAIL` — anything else is `ERR_INVALID_DECISION`. A pass moves `result` to `PASSED` and stamps `decided_period`; a fail moves it to `FAILED` and requires a `decision_note` of at least 20 characters (`ERR_INSUFFICIENT_NOTE`). One more guard applies specifically to the `FINAL` hold point: passing it requires the installation to be sitting in `READY_FOR_FINAL`, else `ERR_INSTALLATION_NOT_READY`.

The final hold point is where the cascades of §2.8 fire. A passed `FINAL` inspection moves a `READY_FOR_FINAL` installation to `COMPLETED`, stamps the `completed_period`, copies the pinned design's `required_absorption_area_sqft` into the installation's `final_absorption_area_sqft` as the as-built record, transitions the authorizing permit to `FINALIZED`, and arms homeowner education for the customer — the customer's `education_completed_at` remains null until the education record is actually delivered per §3.8. A failed `FINAL` inspection against a `READY_FOR_FINAL` installation instead forces it to `FAILED_HOLD`. From there, a `ProjectManager` may remediate — returning the installation to `READY_FOR_FINAL` for re-inspection under the standing permit-and-site guards above — or abandon it. Abandonment is available from any non-terminal state, manual by a project manager or automatic when the authorizing permit is revoked, and is terminal alongside `COMPLETED`.

Materials are tracked as deliveries against an installation. A `ProjectManager` records each delivery with its `material_kind` — `TANK` (measured in gallons), `PIPE` (linear feet), `AGGREGATE` (cubic yards), `CHAMBER` or `PUMP` (count) — a `quantity` greater than 0, and a `unit_cost_cents` of 0 or more; violations are `ERR_INVALID_REQUEST`. Deliveries arrive with `verified` false. Verification, also by a project manager, flips `verified` to true, records the acting manager's id in `verified_by` and the site period in `verified_period`, and runs the budget ceiling: the cumulative cost of all verified deliveries for the installation — each delivery contributing its `quantity` times its `unit_cost_cents` — plus the candidate delivery's own quantity-cost product, must not exceed the ceiling, which is the pinned design's `required_absorption_area_sqft` times 900 cents per square foot. A verification whose resulting total would strictly exceed the ceiling is rejected with `ERR_MATERIAL_BUDGET_EXCEEDED` (HTTP 402); a total landing exactly on the ceiling is accepted.

### 3.7. Seasonal Freeze Windows and Site Closure

Winter and high-water seasons take parcels out of play without closing them. A `ProjectManager` freezes an `OPEN` site by supplying a `freeze_until_period`; the value must not lie in the past — it must be at least the site's `current_period_index`, else `ERR_FREEZE_IN_PAST` — and freezing a site that is not `OPEN` is `ERR_INVALID_STATE`. A successful freeze moves the site's `status` to `FROZEN` and records the bound in `seasonal_freeze_until`. While frozen, four operations are refused with `ERR_SITE_FROZEN`: design submission, installation advance, installation remediation, and repair-case remediation start. When the site's clock eventually advances past `seasonal_freeze_until`, the site returns to `OPEN` automatically and the freeze marker resets to -1, as §2.6 described.

Closure is the site's terminal act. A `ProjectManager` may close an `OPEN` site only when no open work remains: no design in `DRAFT` or `SUBMITTED`, no installation in any non-terminal state from `NOT_STARTED` through `READY_FOR_FINAL` or sitting in `FAILED_HOLD`, and no repair case in `OPEN`, `TRIAGED`, or `IN_REMEDIATION`. Any residue fails with `ERR_OPEN_WORK_REMAINS`. A clean close moves the site to `CLOSED`, its terminal state.

### 3.8. Homeowner Education, Maintenance Contracts, and Service Visits

Completing an installation arms the education obligation. A `ProjectManager` delivers the homeowner education record at the customer level, naming the `site_id` and the `delivery_period`; delivery requires at least one `COMPLETED` installation on the referenced site and otherwise fails with `ERR_INVALID_STATE`. Delivery stamps the customer's `education_completed_at` with a logical timestamp derived from the site's `current_period_index`, closing the loop that installation completion armed.

A maintenance contract binds a completed installation to ongoing service. Creation names the `installation_id` — which must reference a `COMPLETED` installation, else `ERR_INVALID_STATE` — together with the coverage window `start_period` and `end_period` and the `annual_fee_cents`. The end of the window must lie strictly after its start, and the fee must be greater than zero; violations are `ERR_INVALID_REQUEST`. The contract's `customer_id` is set to the customer owning the site, its `site_id` to the site, and it is born `ACTIVE`. Its `prorated_fee_cents` — the fee actually charged for the coverage window — is the annual fee multiplied by the number of periods covered, counted inclusively as `end_period` minus `start_period` plus one, divided by the 12 periods in a year, with the result rounded half-up to whole cents. The rounding happens exactly once on the contract-level product; rounding per period and summing produces a different number and is incorrect.

Contracts age with the site clock. When the `current_period_index` advances past the `end_period`, an `ACTIVE` contract moves to `LAPSED`; when it advances further, past the `end_period` plus the lapse grace window, a `LAPSED` contract moves to `EXPIRED`, terminal alongside `CANCELLED`. A lapsed contract can be brought back: renewal by a `ProjectManager` supplies a `new_end_period` that must lie strictly beyond the current `end_period`, else `ERR_INVALID_RENEWAL`, plus the OCC token `expected_contract_version` equal to the contract's current `version`, else `ERR_STALE_VERSION`. Renewal writes the new end period, recomputes `prorated_fee_cents` by the same once-rounded rule over the new window, returns the contract to `ACTIVE`, and bumps `version` by one. Cancellation is simpler: cancelling an `ACTIVE` contract moves it to `CANCELLED` and deletes every future visit — those whose `visit_period` lies beyond the site's current period — while retaining past visits.

Each service visit is recorded beneath its contract with a `visit_period`, narrative `findings`, an `alarm_condition` flag set true when the visit found an alarm or failure condition — the trigger that makes the repair workflow of §3.9 eligible — and the `technician_name`. The visit is only valid while the contract is `ACTIVE` and the `visit_period` lies inside the coverage window from `start_period` through `end_period` inclusive; either violation fails with `ERR_VISIT_OUTSIDE_CONTRACT`.

### 3.9. Repair Cases and Replacement Estimation

When a completed system fails, a `ProjectManager` opens a repair case against the site, naming the `failed_installation_id` — which must reference a `COMPLETED` installation, else `ERR_INVALID_STATE` — a `failure_kind` of `HYDRAULIC_OVERLOAD`, `STRUCTURAL_COLLAPSE`, `ROOT_INTRUSION`, or `HIGH_WATER_INTRUSION`, and a `diagnosis_note` of at least 20 characters (`ERR_INSUFFICIENT_NOTE`). The case opens in `OPEN` with its `remedy` set to `UNDECIDED`.

Triage chooses the repair path. The payload's `remedy` must be `REPAIR_IN_KIND` or `REPLACEMENT` — anything else is `ERR_INVALID_DECISION`. Choosing `REPLACEMENT` requires a `replacement_design_id` referencing an `APPROVED` design for the same site, else `ERR_REPLACEMENT_DESIGN_NOT_APPROVED`; choosing `REPAIR_IN_KIND` for a case whose `failure_kind` is `STRUCTURAL_COLLAPSE` requires an `APPROVED` variance request of relief kind `REPAIR_IN_KIND` for the site, else `ERR_VARIANCE_REQUIRED`. Triage records the remedy, sets the case's `replacement_design_id` when replacing, moves the case to `TRIAGED`, and — on the replacement path — stamps the replacement design's `provisional_estimate_cents`: the replacement design row referenced at triage contributes its current `design_daily_flow_gpd`, multiplied by 4200 cents per gallon-per-day of flow. This is the provisional variant of the replacement estimate, recorded on the design the moment it is first referenced by a repair case.

Remediation begins only from `TRIAGED`, and only on an `OPEN` site — a frozen site refuses with `ERR_SITE_FROZEN`. On the replacement path there is a further gate: an installation must already exist whose permit pins the case's `replacement_design_id`, else `ERR_REMEDIATION_NOT_STARTED`. Beginning moves the case to `IN_REMEDIATION`. Resolution then splits by remedy. A repair-in-kind case is resolved manually by a project manager supplying a `resolution_note` of at least 20 characters (`ERR_INSUFFICIENT_NOTE`). A replacement case resolves automatically when the installation under the permit pinning the replacement design reaches `COMPLETED`; at that moment the final replacement estimate is computed with the same 4200-cents-per-gallon-per-day rate but against the flow of the design row pinned at permit issuance, which may differ from the provisional figure whenever the replacement plan was amended between triage and issuance. Either path lands in `RESOLVED`. Closing, by a project manager, is available from `OPEN` or `RESOLVED` — any other state is `ERR_INVALID_STATE` — and moves the case to `CLOSED`, terminal alongside `RESOLVED`. Open cases hold the site hostage: a case in `OPEN`, `TRIAGED`, or `IN_REMEDIATION` blocks site closure per §3.7.

## 4. Endpoint Definitions

All endpoints are mounted under `/septic-ops`. Endpoints that create a new resource respond with HTTP 201 and the created resource in the envelope's `data` field; state-changing actions, reads, and single-resource retrievals respond with HTTP 200. In the Authorized Role(s) column, "All roles" denotes the six roles of §2.1 — `PlatformAdmin`, `ProjectManager`, `SystemDesigner`, `SoilScientist`, `Inspector`, and `HealthOfficer`. Request payloads, preconditions, and side effects are defined by the workflows of §3; this table is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /septic-ops/installer-companies | Register an installer company | PlatformAdmin |
| GET | /septic-ops/installer-companies | List installer companies | All roles |
| GET | /septic-ops/installer-companies/{cid} | Get an installer company | All roles |
| POST | /septic-ops/installer-companies/{cid}/soil-scientists | Register a soil scientist | PlatformAdmin |
| GET | /septic-ops/installer-companies/{cid}/soil-scientists | List soil scientists | All roles |
| GET | /septic-ops/installer-companies/{cid}/soil-scientists/{ssid} | Get a soil scientist | All roles |
| POST | /septic-ops/installer-companies/{cid}/system-designers | Register a system designer | PlatformAdmin |
| GET | /septic-ops/installer-companies/{cid}/system-designers | List system designers | All roles |
| GET | /septic-ops/installer-companies/{cid}/system-designers/{dsid} | Get a system designer | All roles |
| POST | /septic-ops/installer-companies/{cid}/inspectors | Register an inspector | PlatformAdmin |
| GET | /septic-ops/installer-companies/{cid}/inspectors | List inspectors | All roles |
| GET | /septic-ops/installer-companies/{cid}/inspectors/{iid} | Get an inspector | All roles |
| POST | /septic-ops/installer-companies/{cid}/health-officers | Register a health officer | PlatformAdmin |
| GET | /septic-ops/installer-companies/{cid}/health-officers | List health officers | All roles |
| GET | /septic-ops/installer-companies/{cid}/health-officers/{hid} | Get a health officer | All roles |
| POST | /septic-ops/installer-companies/{cid}/project-managers | Register a project manager | PlatformAdmin |
| GET | /septic-ops/installer-companies/{cid}/project-managers | List project managers | All roles |
| GET | /septic-ops/installer-companies/{cid}/project-managers/{pmid} | Get a project manager | All roles |
| POST | /septic-ops/installer-companies/{cid}/customers | Register a customer | ProjectManager |
| GET | /septic-ops/installer-companies/{cid}/customers | List customers | All roles |
| GET | /septic-ops/installer-companies/{cid}/customers/{cuid} | Get a customer | All roles |
| POST | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites | Register a site (parcel) | ProjectManager |
| GET | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites | List sites for a customer | All roles |
| GET | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites/{sid} | Get a site | All roles |
| POST | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites/{sid}/clock/advance | Advance the site's deterministic logical clock | ProjectManager |
| POST | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites/{sid}/freeze | Set a seasonal freeze window on the site | ProjectManager |
| POST | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites/{sid}/close | Close a site once all work is complete | ProjectManager |
| POST | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites/{sid}/soil-evaluations | Record a soil evaluation; supersedes any RECORDED evaluation for the site | SoilScientist |
| GET | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites/{sid}/soil-evaluations | List soil evaluations for a site | All roles |
| GET | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites/{sid}/soil-evaluations/{eid} | Get a soil evaluation | All roles |
| POST | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites/{sid}/soil-evaluations/{eid}/void | Void a recorded evaluation (owner only) | SoilScientist |
| POST | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites/{sid}/percolation-tests | Record a percolation test; supersedes any RECORDED test for the site | SoilScientist |
| GET | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites/{sid}/percolation-tests | List percolation tests for a site | All roles |
| GET | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites/{sid}/percolation-tests/{ptid} | Get a percolation test | All roles |
| POST | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites/{sid}/percolation-tests/{ptid}/void | Void a recorded perc test (owner only) | SoilScientist |
| POST | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites/{sid}/designs | Create a system design pinning a soil evaluation and perc test | SystemDesigner |
| GET | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites/{sid}/designs | List designs for a site | All roles |
| GET | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites/{sid}/designs/{did} | Get a design | All roles |
| POST | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites/{sid}/designs/{did}/submit | Submit a DRAFT design for authority review | SystemDesigner |
| POST | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites/{sid}/designs/{did}/decide | Approve or reject a SUBMITTED design | HealthOfficer |
| POST | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites/{sid}/designs/{did}/revise | Return a REJECTED design to DRAFT for rework (OCC-guarded) | SystemDesigner |
| POST | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites/{sid}/designs/{did}/withdraw | Withdraw a DRAFT design | SystemDesigner |
| POST | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites/{sid}/permits | Issue a permit pinning an APPROVED design | HealthOfficer |
| GET | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites/{sid}/permits | List permits for a site | All roles |
| GET | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites/{sid}/permits/{pid} | Get a permit | All roles |
| POST | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites/{sid}/permits/{pid}/suspend | Suspend an ISSUED permit | HealthOfficer |
| POST | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites/{sid}/permits/{pid}/reinstate | Reinstate a SUSPENDED permit (OCC-guarded) | HealthOfficer |
| POST | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites/{sid}/permits/{pid}/revoke | Revoke a permit | HealthOfficer |
| POST | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites/{sid}/installations | Create an installation authorized by an ISSUED permit | ProjectManager |
| GET | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites/{sid}/installations | List installations for a site | All roles |
| GET | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites/{sid}/installations/{iid} | Get an installation | All roles |
| POST | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites/{sid}/installations/{iid}/advance | Advance the installation one leg (hold-point gated) | ProjectManager |
| POST | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites/{sid}/installations/{iid}/remediate | Return a FAILED_HOLD installation to READY_FOR_FINAL | ProjectManager |
| POST | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites/{sid}/installations/{iid}/abandon | Abandon a non-terminal installation | ProjectManager |
| POST | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites/{sid}/installations/{iid}/inspections | Schedule an inspection at a hold point | ProjectManager |
| GET | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites/{sid}/installations/{iid}/inspections | List inspections for an installation | All roles |
| GET | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites/{sid}/installations/{iid}/inspections/{inspid} | Get an inspection | All roles |
| POST | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites/{sid}/installations/{iid}/inspections/{inspid}/decide | Inspector records PASS or FAIL | Inspector |
| POST | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites/{sid}/installations/{iid}/material-verifications | Record a material delivery for an installation | ProjectManager |
| GET | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites/{sid}/installations/{iid}/material-verifications | List material verifications for an installation | All roles |
| GET | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites/{sid}/installations/{iid}/material-verifications/{mvid} | Get a material verification | All roles |
| POST | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites/{sid}/installations/{iid}/material-verifications/{mvid}/verify | Verify a delivered material against the bill of materials | ProjectManager |
| POST | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites/{sid}/variance-requests | File a variance request against a design | SystemDesigner |
| GET | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites/{sid}/variance-requests | List variance requests for a site | All roles |
| GET | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites/{sid}/variance-requests/{vid} | Get a variance request | All roles |
| POST | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites/{sid}/variance-requests/{vid}/decide | Approve or deny a variance request | HealthOfficer |
| POST | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites/{sid}/variance-requests/{vid}/withdraw | Withdraw a pending variance request | SystemDesigner |
| POST | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites/{sid}/maintenance-contracts | Create a maintenance contract over a COMPLETED installation | ProjectManager |
| GET | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites/{sid}/maintenance-contracts | List maintenance contracts for a site | All roles |
| GET | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites/{sid}/maintenance-contracts/{mcid} | Get a maintenance contract | All roles |
| POST | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites/{sid}/maintenance-contracts/{mcid}/renew | Renew a LAPSED contract (OCC-guarded) | ProjectManager |
| POST | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites/{sid}/maintenance-contracts/{mcid}/cancel | Cancel an ACTIVE contract; deletes future visits | ProjectManager |
| POST | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites/{sid}/maintenance-contracts/{mcid}/visits | Record a maintenance visit under a contract | ProjectManager |
| GET | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites/{sid}/maintenance-contracts/{mcid}/visits | List visits under a contract | All roles |
| GET | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites/{sid}/maintenance-contracts/{mcid}/visits/{vid} | Get a visit | All roles |
| POST | /septic-ops/installer-companies/{cid}/customers/{cuid}/education-records | Deliver the homeowner education record | ProjectManager |
| POST | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites/{sid}/repair-cases | Open a repair case for a failed installation | ProjectManager |
| GET | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites/{sid}/repair-cases | List repair cases for a site | All roles |
| GET | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites/{sid}/repair-cases/{rid} | Get a repair case | All roles |
| POST | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites/{sid}/repair-cases/{rid}/triage | Triage a repair case to REPAIR_IN_KIND or REPLACEMENT | ProjectManager |
| POST | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites/{sid}/repair-cases/{rid}/begin-remediation | Begin remediation on a triaged case | ProjectManager |
| POST | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites/{sid}/repair-cases/{rid}/resolve | Resolve a REPAIR_IN_KIND case in remediation | ProjectManager |
| POST | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites/{sid}/repair-cases/{rid}/close | Close an open or resolved repair case | ProjectManager |
| GET | /septic-ops/soil-scientists | Filtered list of soil scientists | All roles |
| GET | /septic-ops/system-designers | Filtered list of system designers | All roles |
| GET | /septic-ops/inspectors | Filtered list of inspectors | All roles |
| GET | /septic-ops/health-officers | Filtered list of health officers | All roles |
| GET | /septic-ops/project-managers | Filtered list of project managers | All roles |
| GET | /septic-ops/customers | Filtered list of customers across the company scope | All roles |
| GET | /septic-ops/customers/{cuid} | Get a customer by id | All roles |
| GET | /septic-ops/sites | Filtered list of sites | All roles |
| GET | /septic-ops/sites/{sid} | Get a site by id | All roles |
| GET | /septic-ops/soil-scientists/{ssid} | Get a soil scientist by id | All roles |
| GET | /septic-ops/soil-scientists/{ssid}/soil-evaluations | List soil evaluations authored by this scientist | All roles |
| GET | /septic-ops/soil-scientists/{ssid}/percolation-tests | List percolation tests authored by this scientist | All roles |
| GET | /septic-ops/soil-evaluations | Filtered list of soil evaluations | All roles |
| GET | /septic-ops/soil-evaluations/{eid} | Get a soil evaluation by id | All roles |
| GET | /septic-ops/percolation-tests | Filtered list of percolation tests | All roles |
| GET | /septic-ops/percolation-tests/{ptid} | Get a percolation test by id | All roles |
| GET | /septic-ops/system-designers/{dsid} | Get a system designer by id | All roles |
| GET | /septic-ops/system-designers/{dsid}/designs | List designs authored by this designer | All roles |
| GET | /septic-ops/designs | Filtered list of system designs | All roles |
| GET | /septic-ops/designs/{did} | Get a design by id | All roles |
| GET | /septic-ops/designs/{did}/permits | List permits pinning this design | All roles |
| GET | /septic-ops/designs/{did}/variance-requests | List variance requests filed against this design | All roles |
| GET | /septic-ops/designs/{did}/repair-cases | List repair cases triaged to this design as replacement | All roles |
| GET | /septic-ops/permits | Filtered list of permits | All roles |
| GET | /septic-ops/permits/{pid} | Get a permit by id | All roles |
| GET | /septic-ops/permits/{pid}/installations | List installations authorized by this permit | All roles |
| GET | /septic-ops/installations | Filtered list of installations | All roles |
| GET | /septic-ops/installations/{iid} | Get an installation by id | All roles |
| GET | /septic-ops/installations/{iid}/maintenance-contracts | List maintenance contracts covering this installation | All roles |
| GET | /septic-ops/installations/{iid}/repair-cases | List repair cases opened against this installation | All roles |
| GET | /septic-ops/inspectors/{iid} | Get an inspector by id | All roles |
| GET | /septic-ops/inspectors/{iid}/inspections | List inspections assigned to this inspector | All roles |
| GET | /septic-ops/inspections | Filtered list of inspections | All roles |
| GET | /septic-ops/inspections/{inspid} | Get an inspection by id | All roles |
| GET | /septic-ops/material-verifications | Filtered list of material verifications | All roles |
| GET | /septic-ops/material-verifications/{mvid} | Get a material verification by id | All roles |
| GET | /septic-ops/variance-requests | Filtered list of variance requests | All roles |
| GET | /septic-ops/variance-requests/{vid} | Get a variance request by id | All roles |
| GET | /septic-ops/health-officers/{hid} | Get a health officer by id | All roles |
| GET | /septic-ops/health-officers/{hid}/variance-requests | List variance requests decided by this officer | All roles |
| GET | /septic-ops/maintenance-contracts | Filtered list of maintenance contracts | All roles |
| GET | /septic-ops/maintenance-contracts/{mcid} | Get a maintenance contract by id | All roles |
| GET | /septic-ops/maintenance-contracts/{mcid}/visits | List visits under this contract (flat alias) | All roles |
| GET | /septic-ops/visits | Filtered list of maintenance visits | All roles |
| GET | /septic-ops/visits/{vid} | Get a maintenance visit by id | All roles |
| GET | /septic-ops/repair-cases | Filtered list of repair cases | All roles |
| GET | /septic-ops/repair-cases/{rid} | Get a repair case by id | All roles |
| GET | /septic-ops/project-managers/{pmid} | Get a project manager by id | All roles |
| GET | /septic-ops/project-managers/{pmid}/material-verifications | List material verifications verified by this project manager | All roles |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in §2 and §3 alongside the workflows that raise them; this catalogue maps identifiers to HTTP status codes only.

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_AUTH | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_FK_NOT_FOUND | 422 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_SITE_FROZEN | 409 |
| ERR_PERMIT_EXPIRED | 409 |
| ERR_STALE_SCIENCE | 409 |
| ERR_SCIENCE_EXPIRED | 409 |
| ERR_VARIANCE_REQUIRED | 409 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_HOLD_POINT_NOT_PASSED | 409 |
| ERR_MATERIALS_UNVERIFIED | 409 |
| ERR_PERMIT_NOT_ISSUED | 409 |
| ERR_REPLACEMENT_DESIGN_NOT_APPROVED | 409 |
| ERR_INSPECTION_TOO_EARLY | 409 |
| ERR_VISIT_OUTSIDE_CONTRACT | 409 |
| ERR_SCHEDULING_CONFLICT | 409 |
| ERR_INSUFFICIENT_NOTE | 400 |
| ERR_MATERIAL_BUDGET_EXCEEDED | 402 |
| ERR_FREEZE_IN_PAST | 409 |
| ERR_INVALID_RENEWAL | 400 |
| ERR_OPEN_WORK_REMAINS | 409 |
| ERR_INSTALLATION_NOT_READY | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_PINNED_BY_LIVE_DESIGN | 409 |
| ERR_REMEDIATION_NOT_STARTED | 409 |
| ERR_INVALID_DECISION | 400 |
