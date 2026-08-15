# Anodizing Electroplating Line API — Product Requirements Document

## 1. Introduction

A metal finishing job shop lives and dies by two clocks: the process clock that decides whether a load of parts meets its thickness specification, and the compliance clock that decides whether the plant may legally discharge effluent and ship hazardous waste at all. Work arrives as customer job lots — a part number, an alloy, a rack- or barrel-routing preference, a thickness band — and must be routed onto chemical baths whose remaining lives are measured in amp-hours and whose chemistry drifts with every load processed and every corrective dose added. Meanwhile the shop operates under discharge permits with per-analyte concentration limits and monthly mass caps, and every bath dump and press of sludge must leave the plant on a waste manifest that no single person may both create and finalize.

This document specifies the Anodizing & Electroplating Line API, the system of record for that operation. It covers master data (customers, fixtures, alloy compatibility rules), bath chemistry control (titrations, dosing, bath-life accounting), the thirteen-state work order lifecycle from receipt through preparation, routing, processing, inspection, rework, salt-spray qualification, and shipment, and the environmental chain of discharge permits, waste samples, exceedance cascades, and waste manifests. The API is built for an audit-heavy environment: titrations, doses, inspections, and samples are append-only records; every mutation is guarded by explicit state machines and a fixed twelve-tier validation order; and four write operations carry mandatory optimistic concurrency checks so that a decision made against a stale view of a bath, a work order, or a manifest is rejected rather than silently applied on top of changes the caller never saw.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` identifying the acting user and `X-User-Role` declaring their operational capacity. The API recognizes exactly six roles: `Customer`, `LineOperator`, `LabChemist`, `QCInspector`, `EHSOfficer`, and `ShopManager`. A request missing either header, or carrying a role outside this declared set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not authorized for the target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` record; ownership checks on any resource that references a customer compare the resource's `customer_id` field to `X-User-ID`, and a mismatch is rejected with `ERR_RESOURCE_NOT_OWNED` (HTTP 403). A `Customer` caller creating a work order must pass its own id as the body's `customer_id`. When `X-User-Role` is `LineOperator`, `LabChemist`, `QCInspector`, `EHSOfficer`, or `ShopManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example as `created_by_user_id` on a waste manifest at creation or `finalized_by_user_id` at finalization — but does not compare it to any entity's `id` except where segregation of duties explicitly requires it (§3.9).

The roles divide the shop along segregation-of-duties lines. A `LineOperator` drives the shop floor: preparation, pre-dip recording, routing, load runs, strips, and shipping. A `LabChemist` owns the wet lab: titrations, dosing, alloy compatibility rules, and salt-spray testing. A `QCInspector` records inspections and dispositions. An `EHSOfficer` owns discharge permits, waste samples, and waste manifests, and shares bath quarantine authority with the manager. A `ShopManager` is the hierarchical override — permitted on every endpoint and the sole actor for customer administration, fixture creation, bath creation, bath dump and renewal, late-state work order cancellation, and the logical clock — but remains bound by segregation of duties on manifest finalization like every other role.

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

List endpoints accept the query parameters `limit` and `offset`. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter states how many items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp `created_at` in ascending order.

Paginated list responses include the fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. Common Resource Properties and Append-Only Records

All primary resources — Customer, Fixture, AlloyCompatibilityRule, PlatingBath, WorkOrder, LoadRun, SaltSprayLot, DischargePermit, WasteManifest, and ManifestLineItem — carry a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed upon any modification of the resource's properties.
- `version` (integer): a system-managed integer that increments with every modification of the resource, including modifications caused by a cascade from another resource's operation. This field backs the optimistic concurrency controls of §2.7.

Four entities are append-only event records and carry only `id` and `created_at` — both `updated_at` and `version` are absent from them: **BathTitration**, **DoseEvent**, **InspectionReport**, and **WasteSample**. Once recorded, such an event is never modified; history questions are answered by listing the events in arrival order.

Cascaded mutations count as ordinary mutations. When a single request mutates several resources — for example a bath dump that also appends a manifest line item and re-computes the manifest's total mass — each affected resource has its own `updated_at` refreshed and its own `version` incremented.

### 2.5. Units, Precision, and Rounding

Numeric precision is pinned per measurement family so that independent implementations agree bit-for-bit:

- **Chemistry concentrations** (grams per liter): titration results, dose results, dragout adjustments, and stored bath concentrations are rounded half-up to exactly three decimal places.
- **Amp-hour figures**: estimated and consumed amp-hours are rounded half-up to exactly two decimal places; the `effective_remaining_ah` bath-life variant is always an integer produced by flooring; the `nameplate_remaining_ah` variant carries two decimal places.
- **Money**: all prices, fees, and invoice lines are integer cents. Every pricing line is rounded half-up to whole cents before the lines are combined — rounding happens per line, never after summation. The one exception is fixture amortization, which is rounded up (ceiling) to the next whole cent at fixture creation.
- **Waste masses**: per-analyte sample masses are rounded half-up to exactly three decimal places in grams before any summation; manifest line masses and totals are kilograms at three decimal places.
- **Thickness readings** are compared exactly as submitted; no rounding is applied to them.

All numeric values in API payloads are JSON numbers, not strings.

### 2.6. The Logical Clock

The system keeps its own logical UTC clock and never falls back to wall-clock time. At startup, before any set call has been made, the logical clock reads exactly `2026-08-01T00:00:00Z`. A `ShopManager` may set the clock through the test-driving clock capability, passing the target instant as `to_iso8601`; the response carries the resulting `current_utc`, rendered as the set instant normalized to UTC in `YYYY-MM-DDTHH:MM:SS` form with a trailing `Z`, with a three-digit millisecond fraction inserted before the `Z` exactly when the set instant carries a non-zero sub-second component (any precision finer than milliseconds is truncated) — so setting `2026-08-10T00:00:00.000Z` yields a `current_utc` of `2026-08-10T00:00:00Z`.

The logical clock is the only time source the API consults. It stamps load run `started_at` and `ended_at` values, determines a salt-spray lot's elapsed `hours_run`, decides whether a waste sample's `sampled_at` falls inside a permit window, supplies the default `sampled_at` when a sample omits it, and fixes the calendar month used for permit mass bucketing. Every timestamp the API derives from the logical clock — the `created_at` and `updated_at` fields of §2.4, a load run's `started_at` and `ended_at`, and a waste sample's `sampled_at` whether defaulted or supplied by the caller (the permit's `last_sampled_at` carries this same serialized value) — is serialized in ISO 8601 UTC with exactly three fractional digits (for example `2026-08-10T00:00:00.000Z`), regardless of the textual form in which the clock or the value was supplied.

### 2.7. Optimistic Concurrency Control

Four write operations require a non-optional version field carrying the client's last-observed `version` of a parent entity. If the supplied value does not equal the parent entity's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). The check is evaluated at priority tier 6 — after schema validation, before all state-machine and business-logic checks. Endpoints not listed here accept no version field at all.

- Recording a dose (`POST /baths/{id}/doses`) requires `expected_bath_version` matching the target PlatingBath's current `version`. A dose written against a fresh view and a dose written against a stale view would each legitimately succeed if issued sequentially — the bath is dosable and its concentration is below target in both cases — so the stale request is rejected purely because its view of the bath is stale.
- Starting a load run (`POST /work-orders/{id}/load-runs`) requires `expected_bath_version` matching the routed PlatingBath's current `version`. Because the stale-version check fires before the state checks, a stale-version start is rejected with HTTP 412 even when the bath is already occupied by another running load — a situation that would otherwise surface as `ERR_BATH_OCCUPIED`.
- Adding a line item to a manifest (`POST /waste-manifests/{id}/line-items`) requires `expected_manifest_version` matching the WasteManifest's current `version`, because the client may have computed totals against a line-item set it last observed.
- Amending a received work order (`PATCH /work-orders/{id}`) requires `expected_work_order_version` matching the WorkOrder's current `version`; every successful amendment recomputes the provisional quote, so an amendment based on a stale quote view is rejected.

Every successful mutation increments the parent's `version`, so a version-locked client must re-read the parent before its next write.

### 2.8. Validation Priority Order

All requests pass through a fixed twelve-tier validation cascade, and a request fails at the earliest tier that rejects it — earlier tiers mask later ones.

1. **Header presence and role validity.** `X-User-ID` and `X-User-Role` must be present and the role must be one of the six declared roles, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Applies to every endpoint.
2. **Role authorization.** The role must be listed among the endpoint's authorized roles, else `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403). Applies to every endpoint.
3. **Ownership scoping.** For `Customer`-role calls on work order resources and on the customer list: the caller may only reach resources whose `customer_id` equals `X-User-ID`, and a work order creation body must name the caller's own id, else `ERR_RESOURCE_NOT_OWNED` (HTTP 403).
4. **Existence.** Path identifiers are validated left-to-right — the first path id that does not correspond to an existing resource yields `ERR_NOT_FOUND` (HTTP 404) before any later segment is examined — followed by foreign-key references in the body (`bath_id`, `fixture_id`, `manifest_id`, `work_order_id`), which must also exist.
5. **Request schema.** Required fields present, types correct, enum members valid, ranges valid: the thickness minimum must not exceed the thickness maximum, an inspection must carry at least three thickness readings, a permit's `limits` must be non-empty with no repeated analyte, a sample must not repeat an analyte across its readings, and a manifest ship request must include the transporter. Violations yield `ERR_INVALID_REQUEST` (HTTP 400).
6. **Optimistic concurrency.** For the four endpoints of §2.7, the supplied expected version must equal the parent's current `version`, else `ERR_STALE_VERSION` (HTTP 412). This tier runs after schema validation and before every state and business rule.
7. **State preconditions.** The target entity's state machine must admit the transition: work order routable/routed/stripping/complete states, bath active/quarantined/dumped states, load run `RUNNING`, salt-spray lot `PENDING`, manifest `DRAFT`/`FINALIZED`/`SHIPPED`, permit `EXCEEDED` for clearing. Violations yield the corresponding 409 state error (for example `ERR_WORK_ORDER_NOT_ROUTABLE`, `ERR_BATH_NOT_ACTIVE`, `ERR_MANIFEST_NOT_DRAFT`). Within this tier, the work order's own state is checked before the state of its linked bath.
8. **Chemistry and alloy safety.** Alloy compatibility (a missing rule or an `INCOMPATIBLE` rule rejects, checked at routing), the pre-dip gate for `CONDITIONAL` compatibility (checked at load start), bath concentration titrated at least once (checked at routing) and within its inclusive control band (checked at load start and at quarantine release — deliberately not at routing, so a titrated bath whose concentration has drifted outside its band may still be routed), and no unverified dose (checked at load start and at quarantine release). Violations yield `ERR_ALLOY_BATH_INCOMPATIBLE`, `ERR_PREDIP_REQUIRED`, `ERR_BATH_CONCENTRATION_OUT_OF_BAND`, or `ERR_DOSE_VERIFICATION_PENDING` (HTTP 422). This tier guards routing, load starts, and quarantine release.
9. **Temporal and overlap rules.** Permit window containment for samples (a closed interval), sample month regression, permit window overlap at creation (closed-closed windows, so sharing a boundary date counts as overlap), fixture occupation (half-open intervals, so a load starting exactly at the previous load's end is not a conflict), and the salt-spray hours gate. Violations yield `ERR_SAMPLE_OUTSIDE_PERMIT_WINDOW`, `ERR_SAMPLE_MONTH_REGRESSION`, `ERR_PERMIT_WINDOW_OVERLAP`, `ERR_FIXTURE_OCCUPIED`, or `ERR_LOT_HOURS_INSUFFICIENT` (HTTP 409).
10. **Structural constraints.** Process type agreement, routing mode support, fixture mode agreement and capacity, dose necessity (current below target), manifest non-empty at finalization, segregation of duties at finalization, and uniqueness of `bath_code`, `fixture_code`, and the compatibility-rule triple. Violations yield `ERR_PROCESS_TYPE_MISMATCH`, `ERR_ROUTING_MODE_NOT_SUPPORTED`, `ERR_FIXTURE_ROUTING_MODE_MISMATCH`, `ERR_FIXTURE_CAPACITY_INSUFFICIENT`, `ERR_DOSE_NOT_NEEDED`, `ERR_MANIFEST_EMPTY`, `ERR_SEGREGATION_OF_DUTIES`, or `ERR_DUPLICATE_COMPATIBILITY_RULE` (HTTP 422 and 403 respectively for the segregation check).
11. **Capacity and fiscal gates.** Route-time effective bath-life sufficiency, load-start nameplate capacity (used plus reserved plus estimate must not exceed capacity, equality allowed), and customer credit hold or suspension. Violations yield `ERR_BATH_LIFE_INSUFFICIENT`, `ERR_BATH_CAPACITY_EXCEEDED` (HTTP 409), `ERR_CUSTOMER_CREDIT_HOLD` (HTTP 402), or `ERR_CUSTOMER_SUSPENDED` (HTTP 403). These gates apply to routing, load starts, shipping, and work order creation.
12. **Compliance hold.** Manifest finalization is blocked while any discharge permit has an active exceedance, yielding `ERR_DISCHARGE_EXCEEDANCE_HOLD` (HTTP 409).

One safety rule deliberately sits at two tiers depending on the operation: the discharge-exceedance hold is evaluated at tier 8 when releasing an exceedance-quarantined bath, but at tier 12 when finalizing a manifest. Per-endpoint ordering is pinned accordingly — manifest finalization checks segregation of duties (tier 10) before the exceedance hold (tier 12), and load-start checks the bath version (tier 6) before any state check (tier 7).

### 2.9. Atomic Cascades and Nested Resource Validation

Several operations touch more than one entity; all of their effects commit atomically within the request. A recorded waste sample that breaches a limit flips its permit to `EXCEEDED`, quarantines every matching bath, and holds every routed work order on those baths in one indivisible step (§3.8). A bath quarantine, exhaustion, dump, release, or renewal propagates to the work orders routed on it in the same request (§3.3). A load completion updates the load run, the bath's amp-hour accounts, the bath's concentration, the bath's status when capacity is reached, and the work order's progress counters together (§3.5).

Requests that target nested resources validate path identifiers sequentially from left to right and are rejected with `ERR_NOT_FOUND` at the first identifier that does not resolve to an existing resource; the system never evaluates a child segment before its parent. The same left-to-right discipline applies to creation and modification operations, so a request under a non-existent parent fails on the parent before any child-specific rule is considered.

## 3. Business Logic & Workflows

### 3.1. Master Data: Customers, Fixtures, and Alloy Compatibility Rules

Before any work reaches the line, the shop maintains three bodies of master data. A `ShopManager` registers each **Customer** with a `company_name`, an optional `priority_tier` of `STANDARD` (the default) or `PREFERRED`, an optional `credit_hold` flag (default false), and an optional `status` that begins as `ACTIVE`. When a customer is patched to `SUSPENDED`, new work orders for that customer are rejected while in-flight work orders are unaffected; patching back to `ACTIVE` restores intake. The same patch operation may adjust `credit_hold` and `priority_tier`, and each successful patch increments the customer's `version`. When `credit_hold` is true, routing new work and shipping are blocked at the fiscal gate of §2.8 with `ERR_CUSTOMER_CREDIT_HOLD`; a `SUSPENDED` customer hits `ERR_CUSTOMER_SUSPENDED` at work order creation, routing, load start, and shipping. Customer-role callers browsing the customer list see only their own record.

A **Fixture** is a rack or barrel carrier created by a `ShopManager` with a `fixture_code` unique across all fixtures, a `routing_mode` of `RACK` or `BARREL`, a `capacity_dm2` greater than zero describing the maximum total part surface area it holds per load, a `purchase_cost_cents` of zero or more, and a `rated_uses` of at least one — the rated load cycles before retirement. From these, the system computes `amortization_cents_per_use` at creation time as the purchase cost divided by the rated uses, rounded up to the next whole cent; the amortization is immutable thereafter and feeds the pricing formula of §3.4.

The **AlloyCompatibilityRule** table is the shop's chemistry-safety memory. A `LabChemist` or `ShopManager` records a rule whose `compatibility` for an `alloy_code` (for example AL6061, AL2024, CRS1018, or C360) combined with a `process_type` of `ANODIZE` or `PLATE` and a `chemistry_family` of `SULFURIC`, `CHROMIC`, `NICKEL`, `ZINC`, `COPPER`, or `CYANIDE` is `COMPATIBLE`, `CONDITIONAL`, or `INCOMPATIBLE`, with optional free-text `notes` recording the rationale. A system-maintained `uniqueness` constraint spans the triple of alloy, process, and chemistry family: a duplicate submission is rejected with `ERR_DUPLICATE_COMPATIBILITY_RULE`. The rule list supports optional `alloy_code` and `chemistry_family` filters. Deleting a rule — a `LabChemist` or `ShopManager` operation returning 204 with no body — reopens the fail-closed default: routing afterwards treats the now-missing triple as incompatible (§3.5).

### 3.2. Bath Commissioning, Titration, and Dosing

A `ShopManager` commissions a **PlatingBath** with a `bath_code` unique across all baths, a `process_type` of `ANODIZE` or `PLATE`, a `chemistry_family` from the same six-value set used by the compatibility rules, and `routing_modes_supported`, a non-empty subset of `RACK` and `BARREL` declaring which fixture styles the line can run. The bath's physical envelope is its `volume_liters` (greater than zero) and its `amp_hour_capacity` (greater than zero) — the total bath-life budget in amp-hours. Its chemistry envelope is a target `target_concentration_g_l` (greater than zero) bracketed by an inclusive lower control limit `low_concentration_g_l` (greater than zero and strictly below target) and an inclusive upper control limit `high_concentration_g_l` (strictly above target). A new bath starts `ACTIVE` with `amp_hour_used` and `amp_hour_reserved` at zero, `current_concentration_g_l` null until the first titration, `dose_verification_pending` false, `active_load_run_id` null, and `quarantine_cause` null.

Chemistry truth is established by titration. A `LabChemist` or `ShopManager` records a **BathTitration** against a bath in `ACTIVE` or `QUARANTINED` status — titrating an `EXHAUSTED`, `DUMPED`, or `DECOMMISSIONED` bath is rejected with `ERR_BATH_NOT_DOSABLE` — supplying the burette readings `titrant_volume_ml`, `titrant_normality`, and `sample_volume_ml`, each greater than zero. The `measured_concentration_g_l` is the titrant volume multiplied by the titrant normality multiplied by the equivalent weight of the bath's chemistry family, divided by the sample volume, rounded half-up to three decimal places. Equivalent weights per family: `SULFURIC` 49.0, `CHROMIC` 33.3, `NICKEL` 29.35, `ZINC` 32.69, `COPPER` 31.77, and `CYANIDE` 49.0. On success the bath's `current_concentration_g_l` becomes the measured value, `dose_verification_pending` is cleared to false, and the bath's `version` increments. Titrations apply in arrival order — creation order — and the bath's titration history is listed in that same order.

Correction chemistry flows through dose events. Recording a **DoseEvent** names the `chemical_code` (for example NISO4 or H2SO4) and `quantity_g` added (greater than zero), and is allowed only while the bath is `ACTIVE` or `QUARANTINED` — `EXHAUSTED`, `DUMPED`, and `DECOMMISSIONED` baths reject dosing with `ERR_BATH_NOT_DOSABLE`. A dose recorded while the current concentration is already at or above the target is rejected with `ERR_DOSE_NOT_NEEDED`. On success the bath's new concentration is the current concentration plus the dosed grams divided by the bath's volume in liters, rounded half-up to three decimal places; this value is stored on the dose event as `resulting_concentration_g_l` and becomes the bath's `current_concentration_g_l`. Every dose sets `dose_verification_pending` to true and increments the bath's `version`; only the next recorded titration clears the flag. Because dosing mutates the bath, the dose request must carry `expected_bath_version` per §2.7, and a stale value is rejected with `ERR_STALE_VERSION` before any other dose logic runs.

While `dose_verification_pending` is true, two operations refuse to run: starting a load on the bath (`ERR_DOSE_VERIFICATION_PENDING`, §3.5) and releasing the bath from quarantine (§3.3). The bath detail read also exposes a dose recommendation — the shortfall of the current concentration below target, floored at zero when the bath is at or above target, multiplied by the bath volume and rounded half-up to whole grams — alongside the two bath-life projections of §3.3.

### 3.3. Bath-Life Accounting and the Bath Lifecycle

Every bath carries two amp-hour accounts. `amp_hour_used` is the sum of `amp_hours_consumed` over the bath's `COMPLETED` load runs — the irrevocable spend. `amp_hour_reserved` is the sum of `estimated_amp_hours` over the bath's `RUNNING` load runs — the committed-but-unspent reserve. Aborted runs contribute to neither account: an abort releases its reservation and leaves `amp_hour_used` untouched, and these two identities hold as invariants at every instant.

A load's amp-hour estimate is its surface area in square decimeters multiplied by the applied current density in amperes per square decimeter multiplied by the duration in minutes, divided by sixty, rounded half-up to two decimal places. The same formula is used with planned values at routing time and with actual values at load start.

Bath-life projection comes in two variants, both exposed on the bath detail read. The optimistic `nameplate_remaining_ah` is simply the bath's amp-hour capacity minus its amp-hours used, carried to two decimal places. The pessimistic `effective_remaining_ah` first derives a chemistry efficiency: 1.0 when the current concentration is at or above target, otherwise the ratio of current to target concentration, but never below 0.5. The effective figure is then the capacity minus the used, multiplied by that efficiency, floored to a whole number. Routing decisions consult only the pessimistic variant: a route is accepted only when `effective_remaining_ah` is at least the planned load's estimated amp-hours, else `ERR_BATH_LIFE_INSUFFICIENT`. Because the pessimistic variant needs a real concentration, routing a bath that has never been titrated is rejected with `ERR_BATH_CONCENTRATION_OUT_OF_BAND`. Load start re-checks the physical ceiling instead: the bath's used plus reserved plus the new estimate must be less than or equal to `amp_hour_capacity`, with equality permitted, else `ERR_BATH_CAPACITY_EXCEEDED`.

The bath lifecycle has five states: `ACTIVE`, `QUARANTINED`, `EXHAUSTED`, `DUMPED`, and the terminal `DECOMMISSIONED`. Three forces move a bath through them.

Quarantine first. An `EHSOfficer` or `ShopManager` may manually quarantine an `ACTIVE` bath — any other status rejects with `ERR_BATH_NOT_ACTIVE` — which sets `quarantine_cause` to `MANUAL`; the same transition fires automatically with cause `DISCHARGE_EXCEEDANCE` when a waste-sample exceedance matches the bath's chemistry (§3.8). Either way, every work order in `ROUTED` status linked to the bath is cascaded to `ROUTE_HELD` in the same request, and the bath's `version` increments. A load already `RUNNING` on the bath is deliberately not aborted — it may still run to completion against the quarantined bath.

Release is the reverse gate. Releasing a quarantine — an `EHSOfficer` or `ShopManager` action — requires, in order of the validation cascade: the bath is `QUARANTINED` (else `ERR_BATH_NOT_QUARANTINED`); no dose is awaiting verification, so `dose_verification_pending` must be false (else `ERR_DOSE_VERIFICATION_PENDING`); the current concentration lies within the inclusive band from `low_concentration_g_l` to `high_concentration_g_l` (else `ERR_BATH_CONCENTRATION_OUT_OF_BAND`); and, when the `quarantine_cause` is `DISCHARGE_EXCEEDANCE`, no discharge permit may currently have `exceedance_active` true with a limit on an analyte of this bath's chemistry family (else `ERR_DISCHARGE_EXCEEDANCE_HOLD`, evaluated at tier 8 for this operation). If the bath's amp-hours used have reached or exceeded its capacity at release time, the bath lands on `EXHAUSTED` instead of `ACTIVE`. Only when the bath actually reaches `ACTIVE` does the cascade run: every work order in `ROUTE_HELD` linked to the bath returns to `ROUTED`, the `quarantine_cause` clears to null, and the bath's `version` increments.

Exhaustion is automatic and inclusive: the moment a load completion makes `amp_hour_used` reach or exceed `amp_hour_capacity`, the bath transitions `ACTIVE` to `EXHAUSTED` and every `ROUTED` work order on it cascades to `ROUTE_HELD` within the same request (§3.5). Dumping and renewal — the paths out of `EXHAUSTED`, and the `DUMPED` state's entry and exit — are told with the waste-manifest story in §3.9, because every dump writes a line onto a draft manifest.

### 3.4. Work Order Intake, Quoting, and Amendment

A job enters the shop as a **WorkOrder**. Creation is open to a `Customer` creating for itself — the body's `customer_id` must equal the caller's `X-User-ID`, else `ERR_RESOURCE_NOT_OWNED` — or to a `ShopManager` creating on any customer's behalf. The intake payload names the `part_number`, the `alloy_code` of the parts, the `process_type` (`ANODIZE` or `PLATE`), the `routing_mode` (`RACK` or `BARREL`), a `part_count` of at least one, the `surface_area_dm2_per_part` (greater than zero), and the inclusive thickness band `thickness_spec_min_um` (greater than zero and not above the maximum) and `thickness_spec_max_um` (not below the minimum). Two flags shape downstream gates: `requires_masking` and `requires_salt_spray`, both defaulting to false. The system derives `surface_area_total_dm2` as the part count multiplied by the per-part area. A new order is `RECEIVED` with `rework_count` zero, `pending_strip` false, `predip_completed` false, `completed_load_count` zero, `bath_id` and `fixture_id` null, and `final_invoice_cents` null until shipment. Creation is fiscally gated: a customer on credit hold is rejected with `ERR_CUSTOMER_CREDIT_HOLD` (HTTP 402) and a suspended customer with `ERR_CUSTOMER_SUSPENDED` (HTTP 403).

Creation also produces `provisional_quote_cents`, the provisional variant of the pricing calculation, recomputed on every amendment and again at preparation once actual masking minutes exist. The quote is assembled in nine pinned steps, each line rounded half-up to whole cents before any summation:

1. **Masking line.** When the order requires masking, the actual `masking_minutes_actual` recorded at preparation — zero if preparation has not happened yet — multiplied by 85 cents per minute; when masking is not required, zero.
2. **Fixture line.** For a `RACK` order, the assigned fixture's `amortization_cents_per_use` multiplied by the number of planned runs; for a `BARREL` order, a flat 1200 cents per planned run. The provisional variant always plans exactly one run. A rack order with no fixture yet assigned — always the case at creation — instead uses an unassigned-fixture fee of 2000 cents for the planned run.
3. **Billing thickness.** The midpoint of `thickness_spec_min_um` and `thickness_spec_max_um`, rounded half-up to one decimal place.
4. **Processing line.** `surface_area_total_dm2` multiplied by the billing thickness multiplied by the tier rate, rounded half-up to whole cents. The tier rate is 12 when the billing thickness is below 10 micrometers, 15 when it is at least 10 and below 25, and 19 when it is at least 25.
5. **Rework surcharge.** The processing line multiplied by 0.20, rounded half-up to whole cents, then multiplied by `rework_count`. The provisional variant uses a rework count of zero, so the line is zero.
6. **Subtotal.** The sum of the masking, fixture, processing, and rework lines.
7. **Discount.** The pre-discount subtotal determines the rate: 0.08 when the subtotal is at least 1000000 cents, 0.05 when it is at least 500000 cents but below 1000000, and zero below 500000. The discount line is the subtotal multiplied by that rate, rounded half-up to whole cents.
8. **Hazmat fee.** A flat 2500 cents when the routed chemistry family snapshot is `CHROMIC` or `CYANIDE`, otherwise zero. The provisional variant is computed before any bath is routed, so its hazmat fee is always zero.
9. **Total.** The subtotal minus the discount plus the hazmat fee.

While an order remains `RECEIVED`, its owner — or a `ShopManager` — may amend `part_count`, `surface_area_dm2_per_part`, `thickness_spec_min_um`, `thickness_spec_max_um`, `requires_masking`, or `requires_salt_spray`. The amendment must carry `expected_work_order_version` matching the order's current `version`; a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412) before any other rule runs, protecting clients from repricing a spec they never saw. Each successful amendment recomputes `provisional_quote_cents` and increments the order's `version`. The work order list supports the filters `customer_id`, `bath_id`, `fixture_id`, and `status`, letting staff trace every order a bath or fixture has touched; `Customer` callers are always scoped to their own orders, on the list, the detail, and every child collection.

### 3.5. Preparation, Routing, and Load Execution

Preparation moves an order from `RECEIVED` to `READY_FOR_ROUTING`. A `LineOperator` or `ShopManager` performs it; an order in any other state rejects with `ERR_WORK_ORDER_NOT_RECEIVED`. When `requires_masking` is true, the request must supply `masking_minutes`; when masking is not required, the field must be absent — either violation is `ERR_MASKING_MINUTES_REQUIRED`. The minutes are recorded as `masking_minutes_actual` (zero when masking is not required) and `provisional_quote_cents` is recomputed with the real masking figure. Separately, recording pre-dip completion sets `predip_completed` to true; the flag matters only at load start for conditionally compatible alloys, and a completed strip later resets it.

Routing assigns a bath and, for rack work, a fixture, moving the order from `READY_FOR_ROUTING` — or from `ROUTE_HELD` when re-routing to a healthy bath — to `ROUTED`. Any other status rejects with `ERR_WORK_ORDER_NOT_ROUTABLE`. The request carries `bath_id`, an optional `fixture_id`, and the planning pair `planned_duration_minutes` and `planned_current_density_a_dm2` used for the bath-life estimate. The checks fire in the cascade order of §2.8: the bath must exist; within the state tier the order's own routability is checked before the bath's state; the bath must be `ACTIVE` (else `ERR_BATH_NOT_ACTIVE`); then the safety tier — the alloy compatibility rule for the order's alloy, process, and the bath's chemistry family must exist and not be `INCOMPATIBLE` (a missing rule fails closed and either case yields `ERR_ALLOY_BATH_INCOMPATIBLE`), a `CONDITIONAL` rule is allowed with its pre-dip gate deferred to load start, and the bath must have been titrated at least once so a current concentration exists for the pessimistic projection (else `ERR_BATH_CONCENTRATION_OUT_OF_BAND`); the inclusive control-band check itself is not applied at routing — it is deferred to load start — so a titrated bath whose current concentration sits outside its band may still be routed, with the pessimistic bath-life projection of §3.3 the only chemistry-driven gate remaining; then the structural tier — the bath's `process_type` must equal the order's (else `ERR_PROCESS_TYPE_MISMATCH`), the order's `routing_mode` must appear in the bath's `routing_modes_supported` (else `ERR_ROUTING_MODE_NOT_SUPPORTED`), and for a `RACK` order `fixture_id` is required, the fixture's `routing_mode` must be `RACK` (else `ERR_FIXTURE_ROUTING_MODE_MISMATCH`), and its `capacity_dm2` must be at least the order's `surface_area_total_dm2` (else `ERR_FIXTURE_CAPACITY_INSUFFICIENT`), while for a `BARREL` order `fixture_id` must be null (supplying one is the same mismatch error); finally the fiscal tier — the bath's `effective_remaining_ah` must be at least the estimated amp-hours of the planned load computed from the planning pair and the order's total surface area (else `ERR_BATH_LIFE_INSUFFICIENT`), and the customer must be off credit hold (`ERR_CUSTOMER_CREDIT_HOLD`) and `ACTIVE` (`ERR_CUSTOMER_SUSPENDED`). On success the order records `bath_id`, `fixture_id`, and a snapshot of the bath's chemistry family as `routed_chemistry_family` — the snapshot that later drives the hazmat fee.

Starting a load moves the order from `ROUTED` to `IN_PROCESS` and creates the **LoadRun**. The order must be `ROUTED` (else `ERR_WORK_ORDER_NOT_ROUTED`), and the request carries `duration_minutes` (at least one), `current_density_a_dm2` (greater than zero), and the concurrency field `expected_bath_version`. The stale-version check fires first among the operation's own rules — tier 6, before the state checks — so a version mismatch is `ERR_STALE_VERSION` even when the bath happens to be occupied. Then: the bath must be `ACTIVE` (else `ERR_BATH_NOT_ACTIVE`) with no `RUNNING` load — a bath runs at most one load at a time, tracked by `active_load_run_id`, and a busy bath yields `ERR_BATH_OCCUPIED`; `dose_verification_pending` must be false (else `ERR_DOSE_VERIFICATION_PENDING`); the current concentration must sit within the inclusive band from `low_concentration_g_l` to `high_concentration_g_l` (else `ERR_BATH_CONCENTRATION_OUT_OF_BAND`); when the applicable compatibility rule is `CONDITIONAL`, `predip_completed` must be true (else `ERR_PREDIP_REQUIRED`); for rack work no other `RUNNING` load may reference the same fixture (else `ERR_FIXTURE_OCCUPIED`) — fixture occupation follows a half-open interval from a load's `started_at` up to but not including its `ended_at`, so a load starting at the exact instant the previous load ended is allowed; the nameplate ceiling must hold, meaning the bath's used plus reserved plus the new estimate is at most `amp_hour_capacity` with equality permitted (else `ERR_BATH_CAPACITY_EXCEEDED`); and the customer gates of credit hold and suspension apply again. On success the load run is created `RUNNING` with `bath_id` copied from the order's routing, `fixture_id` snapshotted from the order (null for barrel work), `surface_area_dm2` snapshotted from the order's `surface_area_total_dm2`, `estimated_amp_hours` computed by the amp-hour formula, and `started_at` set to the logical clock; `amp_hours_consumed` and `ended_at` stay null while running. The bath's `amp_hour_reserved` grows by the estimate, `active_load_run_id` points at the new run, and the bath's `version` increments — all atomically.

Completing the run — allowed only while the load is `RUNNING`, else `ERR_LOAD_RUN_NOT_RUNNING` — moves it to `COMPLETED`, sets `amp_hours_consumed` equal to the estimate, stamps `ended_at` from the logical clock, and drives the work order to `AWAITING_INSPECTION`. The bath's reserved account drops by the estimate and its used account grows by the consumed amount, keeping both invariants of §3.3; `active_load_run_id` clears and the bath's `version` increments. Dragout depletion then lowers the bath's chemistry: the new `current_concentration_g_l` is the current value minus the load's `surface_area_dm2` multiplied by 0.0008 grams per liter per square decimeter, floored at zero, rounded half-up to three decimal places. The order's `completed_load_count` grows by one. If the debit makes the bath's used reach or exceed its capacity, the bath becomes `EXHAUSTED` in the same request and every `ROUTED` order on it cascades to `ROUTE_HELD`.

Aborting — likewise only while `RUNNING`, else `ERR_LOAD_RUN_NOT_RUNNING` — moves the load to `ABORTED`, stamps `ended_at`, leaves `amp_hours_consumed` null, returns the reservation to the bath, clears `active_load_run_id`, increments the bath's `version`, and returns the work order to `ROUTED`. No amp-hours are debited; `amp_hour_used` is invariant under abort.

### 3.6. Inspection, Rework, and Salt-Spray Qualification

Quality control begins once an order reaches `AWAITING_INSPECTION`. A `QCInspector` or `ShopManager` records an **InspectionReport** against an order in exactly that state — any other state is `ERR_WORK_ORDER_NOT_AWAITING_INSPECTION` — submitting `thickness_readings_um`, an array of at least three positive readings in micrometers, and a `defect_type` of `NONE`, `BURN`, `STAIN`, `PITTING`, `ADHESION`, or `UNDERTHICKNESS`. The report is system-linked to the order's latest `COMPLETED` load run via `load_run_id` — unique because the `AWAITING_INSPECTION` state admits exactly one uninspected completed load — and carries three computed values: `thickness_min_um` as the smallest reading, `thickness_max_um` as the largest, and `thickness_ok`, true exactly when the minimum reading is at least `thickness_spec_min_um` and the maximum reading is at most `thickness_spec_max_um`, both bounds inclusive so a reading equal to a spec bound passes.

The computed `disposition` decides the transition. `PASS` requires `thickness_ok` and a `defect_type` of `NONE`: the order moves to `COMPLETE`, unless `requires_salt_spray` is true, in which case it moves to `AWAITING_LOT_TEST` instead. `SCRAP_REJECT` applies when the defect is `BURN` or `ADHESION` regardless of thickness, or whenever the inspection does not pass and the order's `rework_count` has already reached the maximum of two completed reworks; the order moves to the terminal `SCRAPPED` state and no strip cycle is created. Everything else — defects `STAIN`, `PITTING`, or `UNDERTHICKNESS`, or a thickness failure with `rework_count` below two — is a `REWORKABLE_REJECT`: the order moves to `REJECTED` with `pending_strip` set true and the defect recorded as `last_defect_type`. The report persists regardless of outcome.

Rework is a strip-and-replate loop. Starting a strip moves a `REJECTED` order to `STRIPPING` — the operator supplies a `strip_method`, and an order not in `REJECTED` rejects with `ERR_WORK_ORDER_NOT_REJECTED`; because `REJECTED` is only reachable with `pending_strip` true, no separate check is needed. Completing the strip returns the order from `STRIPPING` to `READY_FOR_ROUTING` — any other state is `ERR_WORK_ORDER_NOT_STRIPPING` — and increments `rework_count` by one, clears `pending_strip`, clears `bath_id`, `fixture_id`, and `routed_chemistry_family` so the order must be routed afresh, and resets `predip_completed` to false so a conditional alloy must be pre-dipped again on the next cycle. An order accommodates at most two completed strip-and-replate cycles; the disposition rules above ensure a third strike scraps the order rather than looping it again.

Salt-spray qualification gates orders flagged `requires_salt_spray`. A `LabChemist` or `ShopManager` creates a **SaltSprayLot** for an order in `AWAITING_LOT_TEST` — any other state rejects with `ERR_WORK_ORDER_NOT_AWAITING_LOT_TEST` — naming the `work_order_id`, a `sample_count` of at least one panel, and `hours_required` of at least one (typical specifications run 96, 336, or 500 hours). The lot's `allowed_failures` is computed at creation: two when the sample count is at least ten, one when it is at least five but below ten, and zero below five — so counts of 4, 5, 9, and 10 yield 0, 1, 1, and 2 respectively. The lot's `result` begins `PENDING`, and its `hours_run` is recomputed at every read as the whole-hour floor of the elapsed time between the lot's `created_at` and the current logical clock.

Evaluating a lot takes the observed `panels_failed` and runs two gates in cascade order: the lot's `result` must still be `PENDING` (else `ERR_LOT_NOT_RUNNING`), and `hours_run` must be at least `hours_required` (else `ERR_LOT_HOURS_INSUFFICIENT`). A lot passes when `panels_failed` is at most `allowed_failures`, inclusive; a `PASSED` lot moves the linked order from `AWAITING_LOT_TEST` to `COMPLETE`. Otherwise the lot is `FAILED` and the order moves to `REJECTED` with `pending_strip` true and `last_defect_type` set to `LOT_CORROSION` — unless the order's `rework_count` has already reached two, in which case the order goes straight to `SCRAPPED`.

### 3.7. Shipment, Invoicing, and Cancellation

Shipping a `COMPLETE` order — a `LineOperator` or `ShopManager` action, rejected with `ERR_WORK_ORDER_NOT_COMPLETE` from any other state — runs the customer fiscal gates one last time: `credit_hold` true rejects with `ERR_CUSTOMER_CREDIT_HOLD` and a non-`ACTIVE` customer with `ERR_CUSTOMER_SUSPENDED`. Shipment computes `final_invoice_cents`, the final variant of the pricing formula, and moves the order to the terminal `SHIPPED` state. The final variant follows the identical nine-line structure and pinned evaluation order of §3.4 with three substitutions: the number of planned runs becomes the actual `completed_load_count`, the rework surcharge uses the actual `rework_count`, and the hazmat fee of 2500 cents applies when the `routed_chemistry_family` snapshot is `CHROMIC` or `CYANIDE`. The provisional quote therefore diverges from the invoice through exactly three channels: fixture amortization or barrel fees multiply actual runs rather than one planned run, rework surcharges apply for real, and the hazmat fee appears when the routed family demands it.

Cancellation splits by actor and state, and every accepted cancellation lands the order in the terminal `CANCELLED` state. The owner `Customer` — or a `ShopManager` — may cancel an order in any of the early states `RECEIVED`, `READY_FOR_ROUTING`, `ROUTED`, or `ROUTE_HELD`; the cancellation is free, so `cancellation_fee_cents` is set to zero, and the fixture and bath links are cleared, releasing the routing. A `ShopManager` alone may cancel from the late states `AWAITING_INSPECTION`, `REJECTED`, `STRIPPING`, and `AWAITING_LOT_TEST`; this manager cancel charges `cancellation_fee_cents` equal to the processing line of the pricing formula — step 4 evaluated on the order's current specification — multiplied by 0.5, rounded half-up to whole cents, and likewise clears the links. Every other combination is rejected with `ERR_WORK_ORDER_NOT_CANCELLABLE`: an owner attempting a late-state cancel, and anyone at all attempting to cancel an `IN_PROCESS` order, a `COMPLETE` order, or an order already in a terminal state.

### 3.8. Discharge Permits, Waste Sampling, and Exceedance Response

Environmental discharge is governed by **DischargePermit** records created by an `EHSOfficer` or `ShopManager`. A permit names an `outfall_code` (for example OUTFALL-001) and a closed effective window: `effective_from` and `effective_to` as dates, with the end not before the start and both boundaries inclusive. Its `limits` are a non-empty array of entries, each pairing an `analyte_code` — one of `NICKEL`, `ZINC`, `COPPER`, `CHROME`, or `CYANIDE`, unique within the permit — with a `max_concentration_mg_l` instantaneous limit and a `monthly_mass_cap_g` monthly mass cap. Two permits for the same outfall may not overlap: the windows are closed on both ends, so sharing even a single boundary date counts as overlap and the creation is rejected with `ERR_PERMIT_WINDOW_OVERLAP`. A new permit starts `ACTIVE` with `exceedance_active` false, `current_month` null until the first accepted sample, and an empty `cumulative_mass_g` map.

Each discharge event is reported as a **WasteSample** against a permit, recorded by an `EHSOfficer` or `ShopManager`. The sample names the `permit_id`, a `flow_liters` greater than zero describing the discharge volume since the previous sample, and `readings` — a non-empty array of `analyte_code` and `concentration_mg_l` pairs where every analyte must exist in the permit's limits and no analyte may appear twice in one sample, violations being `ERR_INVALID_REQUEST`. The `sampled_at` timestamp is optional and defaults to the current logical clock when omitted. The sample's date must fall inside the permit's closed window from `effective_from` to `effective_to`, else `ERR_SAMPLE_OUTSIDE_PERMIT_WINDOW`.

Mass accounting follows a pinned rounding order. For each analyte reading, the sample's `masses_g` entry is the concentration in milligrams per liter multiplied by the flow in liters, divided by one thousand, rounded half-up to three decimal places — each per-analyte mass rounded first, and the monthly cumulative for that analyte is the plain sum of those already-rounded per-sample masses, never re-rounded and never computed as a sum-then-round. Month bucketing follows the calendar month of `sampled_at`: when the permit's `current_month` is null or the sample's month is later, `current_month` advances to the sample's month and `cumulative_mass_g` resets to just this sample's masses; when the sample's month equals `current_month`, each analyte's rounded mass accumulates into the running totals; when the sample's month is earlier, the sample is rejected with `ERR_SAMPLE_MONTH_REGRESSION`. Samples within the same month whose timestamps tie are applied in arrival order, and each accepted sample is remembered through the permit's `last_sampled_at`.

A sample is an exceedance — `is_exceedance` true — when any reading's concentration is strictly greater than its limit's `max_concentration_mg_l`, or when any analyte's cumulative mass after adding the sample is strictly greater than its `monthly_mass_cap_g`; equality on either measure is compliant. Recording an exceedance sample flips the permit from `ACTIVE` to `EXCEEDED`, sets `exceedance_active` true, and cascades in the same request: every `ACTIVE` bath whose chemistry family maps to an exceeded analyte is quarantined with `quarantine_cause` `DISCHARGE_EXCEEDANCE`, and every work order `ROUTED` on those baths moves to `ROUTE_HELD`. The chemistry-to-analyte map is exact — a `NICKEL` bath answers to the `NICKEL` analyte, `ZINC` to `ZINC`, `COPPER` to `COPPER`, `CHROMIC` to `CHROME`, and `CYANIDE` to `CYANIDE` — while a `SULFURIC` bath maps to no analyte and is never quarantined by an exceedance.

An `EHSOfficer` or `ShopManager` clears an exceeded permit after review; the permit must be `EXCEEDED`, else `ERR_PERMIT_NOT_EXCEEDED`. Clearing returns the permit to `ACTIVE` and sets `exceedance_active` false, but deliberately does not release any bath quarantines — each quarantined bath is released individually through the release gate of §3.3, which for exceedance-caused quarantines verifies that no permit still holds an active exceedance over the bath's chemistry analyte.

### 3.9. Waste Manifests, Bath Dumping, and Renewal

Hazardous waste leaves the plant on a **WasteManifest**, created in `DRAFT` status by an `EHSOfficer` or `ShopManager` with the `generator_epa_id`; the caller's `X-User-ID` is recorded as `created_by_user_id`, and an optional `transporter_name` stays null until shipment. The manifest's `total_mass_kg` starts at zero.

While the manifest is `DRAFT`, line items may be added and removed. Adding a **ManifestLineItem** supplies the `waste_code` (an EPA code such as F006, F007, or D007), a `source_type` of `BATH_DUMP`, `SLUDGE_PRESS`, or `RINSE_CONCENTRATE`, a free-text `description`, a `volume_liters` greater than zero, and the concurrency field `expected_manifest_version` — a stale version is `ERR_STALE_VERSION` per §2.7, guarding clients who computed totals against an older line set. The line's `mass_kg` is its volume multiplied by the density of its source type — 1.2 kilograms per liter for `BATH_DUMP` and `RINSE_CONCENTRATE`, 1.5 for `SLUDGE_PRESS` — rounded half-up to three decimal places. Each addition or removal recomputes `total_mass_kg` as the sum of the lines' masses at three decimals and increments the manifest's `version`; line operations on a non-draft manifest are rejected with `ERR_MANIFEST_NOT_DRAFT`, and removals return 204 with no body. Lines created manually carry a null `origin_bath_id`.

Dumping a bath writes onto this chain. A `ShopManager` dumps a bath in `ACTIVE`, `QUARANTINED`, or `EXHAUSTED` status — a `DUMPED` or `DECOMMISSIONED` bath rejects with `ERR_BATH_NOT_DUMPABLE` — provided no load is `RUNNING` on it (else `ERR_BATH_OCCUPIED`) and the request's `manifest_id` references a manifest still in `DRAFT` (else `ERR_MANIFEST_NOT_DRAFT`). The dump transitions the bath to `DUMPED`, creates a manifest line on that manifest with `waste_code` F006, `source_type` `BATH_DUMP`, the bath's `volume_liters` as its volume, and `origin_bath_id` pointing back at the bath; the manifest's `total_mass_kg` is recomputed and its `version` incremented, and the bath's `version` increments too, all atomically. Any work order `ROUTED` or `ROUTE_HELD` on the dumped bath stays in or moves to `ROUTE_HELD` — it remains held until renewal of the bath or a re-route to a healthy bath resolves it. Passing `decommission` true on the same operation writes the identical manifest line but retires the bath permanently to `DECOMMISSIONED` instead of `DUMPED`; a decommissioned bath never returns.

Renewal resurrects a dumped bath. A `ShopManager` renews a bath that is `DUMPED` — any other status rejects with `ERR_BATH_NOT_DUMPED` — supplying fresh burette readings `titrant_volume_ml`, `titrant_normality`, and `sample_volume_ml`. The renewal records a new BathTitration using the same equivalent-weight conversion as §3.2, sets the bath's `current_concentration_g_l` to the measured value, zeroes both `amp_hour_used` and `amp_hour_reserved`, clears `dose_verification_pending` and `quarantine_cause`, returns the bath to `ACTIVE`, increments its `version`, and cascades every work order `ROUTE_HELD` on the bath back to `ROUTED`.

Manifest close-out enforces segregation of duties. Finalizing — an `EHSOfficer` or `ShopManager` action — requires the manifest to be `DRAFT` (else `ERR_MANIFEST_NOT_DRAFT`), at least one line item (else `ERR_MANIFEST_EMPTY`), and no discharge permit anywhere with `exceedance_active` true (else `ERR_DISCHARGE_EXCEEDANCE_HOLD`, evaluated at tier 12 for this operation). Above all, the finalizer's `X-User-ID` must differ from the manifest's `created_by_user_id` — a rule that binds every role including `ShopManager`, rejected as `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), and per the pinned ordering of §2.8 the segregation check fires at tier 10, before the exceedance hold at tier 12. Finalization records `finalized_by_user_id`, locks the line items, and moves the manifest to `FINALIZED`. Shipping a manifest requires it to be `FINALIZED` (else `ERR_MANIFEST_NOT_FINALIZED`) and requires the `transporter_name` to be provided (else `ERR_INVALID_REQUEST`); the manifest moves to `SHIPPED`. Confirming receipt requires `SHIPPED` (else `ERR_MANIFEST_NOT_SHIPPED`) and lands the manifest in the terminal `RECEIVED` state.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — state transitions, patches, and record-keeping actions — return `200 OK`. Deletions return `204 No Content`. The full request payloads, computed fields, and side effects of each operation are specified in §2 and §3; this table is only the HTTP contract.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/customers` | Create a customer | ShopManager |
| GET | `/customers` | List customers; a `Customer` caller sees only its own record | Customer, LineOperator, LabChemist, QCInspector, EHSOfficer, ShopManager |
| PATCH | `/customers/{id}` | Update `credit_hold`, `status`, or `priority_tier` | ShopManager |
| POST | `/fixtures` | Create a fixture; amortization computed at creation | ShopManager |
| GET | `/fixtures` | List fixtures | LineOperator, LabChemist, QCInspector, EHSOfficer, ShopManager |
| POST | `/alloy-compatibility-rules` | Create an alloy compatibility rule | LabChemist, ShopManager |
| GET | `/alloy-compatibility-rules` | List rules with optional `alloy_code` and `chemistry_family` filters | LineOperator, LabChemist, QCInspector, EHSOfficer, ShopManager |
| DELETE | `/alloy-compatibility-rules/{id}` | Delete a rule, reopening the fail-closed default | LabChemist, ShopManager |
| POST | `/baths` | Create a plating bath (`ACTIVE`, untitrated) | ShopManager |
| GET | `/baths/{id}` | Bath detail including both bath-life variants and the dose recommendation | LineOperator, LabChemist, QCInspector, EHSOfficer, ShopManager |
| POST | `/baths/{id}/titrations` | Record a titration; sets concentration and clears dose-verification | LabChemist, ShopManager |
| GET | `/baths/{id}/titrations` | List a bath's titration events in arrival order | LineOperator, LabChemist, QCInspector, EHSOfficer, ShopManager |
| POST | `/baths/{id}/doses` | Record a dose; OCC on the bath version | LabChemist, ShopManager |
| GET | `/baths/{id}/doses` | List a bath's dose events | LineOperator, LabChemist, QCInspector, EHSOfficer, ShopManager |
| POST | `/baths/{id}/quarantine` | Manually quarantine an `ACTIVE` bath | EHSOfficer, ShopManager |
| POST | `/baths/{id}/release-quarantine` | Release a `QUARANTINED` bath after verification | EHSOfficer, ShopManager |
| POST | `/baths/{id}/dump` | Dump bath contents to a `DRAFT` manifest; `decommission` retires the bath | ShopManager |
| POST | `/baths/{id}/renew` | Renew a `DUMPED` bath with a baseline titration | ShopManager |
| GET | `/baths/{id}/load-runs` | List load runs processed on a bath | LineOperator, LabChemist, QCInspector, EHSOfficer, ShopManager |
| POST | `/work-orders` | Create a work order with its provisional quote | Customer, ShopManager |
| GET | `/work-orders` | List work orders with `customer_id`, `bath_id`, `fixture_id`, `status` filters; `Customer` callers see only their own | Customer, LineOperator, LabChemist, QCInspector, EHSOfficer, ShopManager |
| GET | `/work-orders/{id}` | Work order detail | Customer, LineOperator, LabChemist, QCInspector, EHSOfficer, ShopManager |
| PATCH | `/work-orders/{id}` | Amend the spec while `RECEIVED`; OCC on the work order version | Customer, ShopManager |
| POST | `/work-orders/{id}/prepare` | Record masking and preparation; `RECEIVED` → `READY_FOR_ROUTING` | LineOperator, ShopManager |
| POST | `/work-orders/{id}/complete-predip` | Record pre-dip completion for `CONDITIONAL` compatibility | LineOperator, ShopManager |
| POST | `/work-orders/{id}/route` | Assign bath and fixture; `READY_FOR_ROUTING`/`ROUTE_HELD` → `ROUTED` | LineOperator, ShopManager |
| POST | `/work-orders/{id}/load-runs` | Start a load run on the routed bath; OCC on the bath version | LineOperator, ShopManager |
| GET | `/work-orders/{id}/load-runs` | List a work order's load runs | Customer, LineOperator, LabChemist, QCInspector, EHSOfficer, ShopManager |
| POST | `/load-runs/{id}/complete` | Complete a running load; debits amp-hours, applies dragout, may exhaust the bath | LineOperator, ShopManager |
| POST | `/load-runs/{id}/abort` | Abort a running load; releases the reservation without debit | LineOperator, ShopManager |
| POST | `/work-orders/{id}/inspections` | Record a QC inspection; computes disposition and drives the transition | QCInspector, ShopManager |
| GET | `/work-orders/{id}/inspections` | List a work order's inspection reports | Customer, LineOperator, LabChemist, QCInspector, EHSOfficer, ShopManager |
| POST | `/work-orders/{id}/start-strip` | Begin stripping a rejected order | LineOperator, ShopManager |
| POST | `/work-orders/{id}/complete-strip` | Finish stripping; returns the order to routing and increments the rework count | LineOperator, ShopManager |
| POST | `/work-orders/{id}/ship` | Ship a `COMPLETE` order; computes the final invoice | LineOperator, ShopManager |
| POST | `/work-orders/{id}/cancel` | Cancel an order — owner from early states, manager from late states | Customer, ShopManager |
| POST | `/salt-spray-lots` | Create a salt spray lot for an `AWAITING_LOT_TEST` order | LabChemist, ShopManager |
| POST | `/salt-spray-lots/{id}/evaluate` | Evaluate a `PENDING` lot after the hours gate | LabChemist, ShopManager |
| GET | `/work-orders/{id}/salt-spray-lots` | List a work order's salt spray lots | Customer, LineOperator, LabChemist, QCInspector, EHSOfficer, ShopManager |
| POST | `/discharge-permits` | Create a discharge permit; closed-window overlap per outfall rejected | EHSOfficer, ShopManager |
| GET | `/discharge-permits/{id}` | Permit detail including cumulative masses | LineOperator, LabChemist, QCInspector, EHSOfficer, ShopManager |
| POST | `/discharge-permits/{id}/samples` | Record a waste sample; mass accounting and the exceedance cascade | EHSOfficer, ShopManager |
| GET | `/discharge-permits/{id}/samples` | List a permit's samples | LineOperator, LabChemist, QCInspector, EHSOfficer, ShopManager |
| POST | `/discharge-permits/{id}/clear-exceedance` | Clear an `EXCEEDED` permit after review | EHSOfficer, ShopManager |
| POST | `/waste-manifests` | Create a `DRAFT` manifest; creator recorded | EHSOfficer, ShopManager |
| GET | `/waste-manifests/{id}` | Manifest detail including total mass | LineOperator, LabChemist, QCInspector, EHSOfficer, ShopManager |
| POST | `/waste-manifests/{id}/line-items` | Add a line item to a `DRAFT` manifest; OCC on the manifest version | EHSOfficer, ShopManager |
| DELETE | `/waste-manifests/{id}/line-items/{lineItemId}` | Remove a line item from a `DRAFT` manifest | EHSOfficer, ShopManager |
| GET | `/waste-manifests/{id}/line-items` | List a manifest's line items | LineOperator, LabChemist, QCInspector, EHSOfficer, ShopManager |
| POST | `/waste-manifests/{id}/finalize` | Finalize a `DRAFT` manifest; segregation of duties enforced | EHSOfficer, ShopManager |
| POST | `/waste-manifests/{id}/ship` | Ship a `FINALIZED` manifest; transporter required | EHSOfficer, ShopManager |
| POST | `/waste-manifests/{id}/receive` | Confirm receipt of a `SHIPPED` manifest (terminal) | EHSOfficer, ShopManager |
| POST | `/_clock/set_current_utc` | Set the logical clock | ShopManager |

## 5. Error Code Catalogue

The catalogue below fixes every error identifier and its HTTP status. The trigger conditions for each error are specified in the narratives of §2 and §3, next to the workflow they guard.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_RESOURCE_NOT_OWNED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_WORK_ORDER_NOT_RECEIVED` | 409 Conflict |
| `ERR_WORK_ORDER_NOT_ROUTABLE` | 409 Conflict |
| `ERR_WORK_ORDER_NOT_ROUTED` | 409 Conflict |
| `ERR_WORK_ORDER_NOT_AWAITING_INSPECTION` | 409 Conflict |
| `ERR_WORK_ORDER_NOT_REJECTED` | 409 Conflict |
| `ERR_WORK_ORDER_NOT_STRIPPING` | 409 Conflict |
| `ERR_WORK_ORDER_NOT_COMPLETE` | 409 Conflict |
| `ERR_WORK_ORDER_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_WORK_ORDER_NOT_AWAITING_LOT_TEST` | 409 Conflict |
| `ERR_LOAD_RUN_NOT_RUNNING` | 409 Conflict |
| `ERR_LOT_NOT_RUNNING` | 409 Conflict |
| `ERR_BATH_NOT_ACTIVE` | 409 Conflict |
| `ERR_BATH_OCCUPIED` | 409 Conflict |
| `ERR_BATH_NOT_QUARANTINED` | 409 Conflict |
| `ERR_BATH_NOT_DUMPED` | 409 Conflict |
| `ERR_BATH_NOT_DOSABLE` | 409 Conflict |
| `ERR_BATH_NOT_DUMPABLE` | 409 Conflict |
| `ERR_MANIFEST_NOT_DRAFT` | 409 Conflict |
| `ERR_MANIFEST_NOT_FINALIZED` | 409 Conflict |
| `ERR_MANIFEST_NOT_SHIPPED` | 409 Conflict |
| `ERR_PERMIT_NOT_EXCEEDED` | 409 Conflict |
| `ERR_ALLOY_BATH_INCOMPATIBLE` | 422 Unprocessable Entity |
| `ERR_PREDIP_REQUIRED` | 422 Unprocessable Entity |
| `ERR_BATH_CONCENTRATION_OUT_OF_BAND` | 422 Unprocessable Entity |
| `ERR_DOSE_VERIFICATION_PENDING` | 422 Unprocessable Entity |
| `ERR_DISCHARGE_EXCEEDANCE_HOLD` | 409 Conflict |
| `ERR_SAMPLE_OUTSIDE_PERMIT_WINDOW` | 409 Conflict |
| `ERR_SAMPLE_MONTH_REGRESSION` | 409 Conflict |
| `ERR_PERMIT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_FIXTURE_OCCUPIED` | 409 Conflict |
| `ERR_LOT_HOURS_INSUFFICIENT` | 409 Conflict |
| `ERR_PROCESS_TYPE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_ROUTING_MODE_NOT_SUPPORTED` | 422 Unprocessable Entity |
| `ERR_FIXTURE_ROUTING_MODE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_FIXTURE_CAPACITY_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_DOSE_NOT_NEEDED` | 422 Unprocessable Entity |
| `ERR_MANIFEST_EMPTY` | 422 Unprocessable Entity |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_DUPLICATE_COMPATIBILITY_RULE` | 409 Conflict |
| `ERR_MASKING_MINUTES_REQUIRED` | 422 Unprocessable Entity |
| `ERR_BATH_LIFE_INSUFFICIENT` | 409 Conflict |
| `ERR_BATH_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_CUSTOMER_CREDIT_HOLD` | 402 Payment Required |
| `ERR_CUSTOMER_SUSPENDED` | 403 Forbidden |
