# Aerospace Machining & AS9100 Program API — Product Requirements Document

## 1. Introduction

A tier-2 aerospace machining supplier lives and dies by its ability to prove — not merely claim — that every serialized part shipped to a prime contractor was produced under an AS9100D quality system, from conforming material, by approved processes, against the correct drawing revision. This document specifies the Aerospace Machining & AS9100 Program API, the system of record for that proof. It governs the full program arc: negotiating long-term agreements and customer purchase orders, flowing quality clauses down to the shop floor, demonstrating part conformance through AS9102 first-article inspection, serializing and tracing every unit back to its mill heat, and shipping only when every airworthiness gate has cleared.

The quality spine of the system is deliberately conservative. Ballooned characteristics are measured one by one before a first article may be submitted for customer approval; key characteristics are watched by statistical process control throughout production, and a capability collapse automatically opens a nonconformance and forces a 100-percent inspection posture. Counterfeit-part prevention is structural rather than procedural: material certifications may only be registered against approved sources, receiving inspection is segregated from registration, and revoking a certification cascades containment through quarantined serials, held work orders, and auto-generated nonconformance reports — with customer escape reports due within forty-eight hours whenever suspect product has already shipped. Commercial health is policed with equal rigor through monthly rate-readiness audits that can suspend an agreement without human intervention.

Technically, the API is a REST service mounted under `/api`. All time-dependent rules — approval windows, delegation windows, escape deadlines, monthly audit attribution, and annual rebate attribution — read a server-side logical clock rather than wall-clock time, and the commercial heart of the system (agreement pricing and amendment) is guarded by optimistic concurrency. Sections 2 and 3 define the rules; Sections 4 and 5 summarize the HTTP contract.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. A request in which either header is missing or empty is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (400). The system recognizes exactly eight roles: `ContractsManager`, `SupplyChainManager`, `ManufacturingPlanner`, `QualityInspector`, `MRBMember`, `QualityManager`, `CustomerQualityRep`, and `SystemAdmin`. An attempt to perform an operation outside the caller's designated role is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (403).

Role portfolios follow a segregation-of-duties model. A `ContractsManager` owns the commercial agreement lifecycle: long-term agreements, customer purchase orders, and flow-down review. A `SupplyChainManager` owns approved sources, material-certification registration, and special-process approvals. A `ManufacturingPlanner` owns work orders, serialization, and shipment. A `QualityInspector` performs FAI ballooning and measurement, receiving inspection of material certifications, SPC recording, and nonconformance initiation and verification. An `MRBMember` sits on the Material Review Board and dispositions nonconformances. A `QualityManager` provides quality leadership: MRB submission, nonconformance closure, counterfeit revocation, escape submission, rate audits, and hold release. A `CustomerQualityRep` represents the customer's quality organization: FAI approval and rejection, delegation grants and revocations, escape acknowledgement, customer concessions, and source inspection. A `SystemAdmin` operates the logical-clock test-driving capability.

All eight roles share one identity model: `X-User-ID` is an opaque operator identifier not tied to the `id` of any persisted entity. When `X-User-Role` is `ContractsManager`, `SupplyChainManager`, `ManufacturingPlanner`, `QualityInspector`, `MRBMember`, `QualityManager`, `CustomerQualityRep`, or `SystemAdmin`, the server never compares `X-User-ID` to any entity's `id`. The identifier may, however, be recorded on resources — for example as `submitted_by_user_id` on a first-article inspection, `measured_by_user_id` on a characteristic, `created_by_user_id` on a material certification, `discovered_by_user_id` or `disposition_by_user_id` on a nonconformance report, `granted_by_user_id` on a delegation, `inspector_user_id` within a delegation window, or `recorded_by_user_id` on an SPC measurement — and later requests are compared against those recorded identifiers by the segregation-of-duties and delegation rules described below.

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

Endpoints returning lists of resources are paginated through two query parameters. `limit` caps the number of items returned; when omitted it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` skips that many items from the front of the result set and defaults to 0.

Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp (`created_at`) in ascending order.

The `meta` object of every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource — long-term agreements, purchase orders, first-article inspections, ballooned characteristics, work orders, serial numbers, material certifications, approved sources, special-process approvals, nonconformance reports, escape reports, and delegated inspection authorities — carries four system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a bare UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every modification of the resource.
- `version` (integer): a system-managed integer that increments by one with every modification of the resource, serving optimistic concurrency control where applicable.

The one exception is the SPC measurement record: it is an append-only observation carrying only `id` and `created_at`. Both `updated_at` and `version` are absent from it, because a measurement is never mutated after being recorded.

### 2.5. The Logical Clock

All date- and time-dependent rules read a server-side logical clock, never wall-clock time: special-process approval windows, delegation windows and the post-revocation cooling-off period, the escape-report deadline, monthly rate-audit attribution, annual rebate attribution, and the logical timestamps stamped onto resources (`completed_at`, `shipped_at`, `submitted_at`, `revoked_at`). At server startup the logical clock is set to exactly 2026-08-01T00:00:00Z, and it must not fall back to wall-clock time under any circumstance. A `SystemAdmin`-only test-driving capability sets the clock by supplying a `to_iso8601` instant; the response reports the resulting `current_utc` value.

### 2.6. Nested Resource Retrieval and Existence Checks

Requests that carry resource identifiers — in the URL path or in the request body — are validated for existence before any state or business rule runs. Path identifiers are validated strictly left to right; the request is rejected with the not-found error corresponding to the first identifier that does not resolve, before later identifiers or body references are examined. Body-referenced foreign keys are checked after the path. Each resource family has its own 404 error: `ERR_LTA_NOT_FOUND` for agreements, `ERR_PO_NOT_FOUND` for purchase orders, `ERR_FAI_NOT_FOUND` for first-article inspections, `ERR_CHARACTERISTIC_NOT_FOUND` for ballooned characteristics, `ERR_WO_NOT_FOUND` for work orders, `ERR_SERIAL_NOT_FOUND` for serial numbers (including ids listed inside `affected_serial_ids` of a nonconformance report), `ERR_MATERIAL_CERT_NOT_FOUND` for material certifications, `ERR_SOURCE_NOT_FOUND` for approved sources, `ERR_PROCESS_APPROVAL_NOT_FOUND` for special-process approvals, `ERR_NCR_NOT_FOUND` for nonconformance reports, `ERR_ESCAPE_REPORT_NOT_FOUND` for escape reports, and `ERR_DELEGATION_NOT_FOUND` for delegated inspection authorities.

### 2.7. Optimistic Concurrency Control

Two write operations on the commercial record are guarded by optimistic concurrency: creating a purchase order against an agreement, and amending an agreement's commercial terms. Both requests must carry `expected_lta_version`, a non-optional input field holding the agreement `version` the client last observed. If the value does not match the agreement's current `version` — because another write has advanced the agreement since the client last read it — the request is rejected with `ERR_STALE_LTA_VERSION` (HTTP 412), preventing the client from building on commercial terms it has not observed. Purchase-order pricing is pinned from the agreement's tier table at creation, so a write based on a stale agreement version would price against superseded terms; amendments legitimately re-base those terms, so the later writer must re-read the agreement before re-applying. No endpoint other than these two accepts a version field.

### 2.8. Precision, Rounding, and Monetary Representation

All monetary values are carried as integer cents — never floating-point dollars. Rounding is always round half up, and each calculation names the single point at which it rounds. Purchase-order unit prices are rounded half up to integer cents exactly once, at the end of the pricing computation; intermediate values are never rounded. Nonconformance costs round each affected unit's cost half up to integer cents first and only then multiply by the affected quantity. Statistical capability reporting rounds the capability index half up to three decimal places, and rounds the reported mean and standard deviation half up to four decimal places for display only; the capability verdict compares the rounded three-decimal index against its threshold. The monthly rate-audit percentage is rounded half up to an integer. The annual volume rebate is rounded half up to integer cents at the rebate step.

### 2.9. Segregation of Duties

Three operations enforce segregation of duties by comparing the caller's `X-User-ID` to an identifier anchored on the resource, rejecting a match with `ERR_SOD_VIOLATION` (403). First, the inspector who submits a first-article inspection must not be the inspector who recorded any of its characteristic measurements: the submitter's `X-User-ID` must differ from the `measured_by_user_id` of every characteristic on the inspection. Second, the Material Review Board member who dispositions a nonconformance report must not be the person who discovered it: the disposer's `X-User-ID` must differ from the report's `discovered_by_user_id`. Third, the inspector who accepts a material certification at receiving inspection must not be the person who registered it: the acceptor's `X-User-ID` must differ from the certification's `created_by_user_id`.

### 2.10. Hierarchical Consistency and Cascading Containment

State changes propagate across aggregate boundaries so that parents and children never disagree. Cancelling a purchase order cancels its unstarted work orders and restores the agreement's funds ceiling; shipping a serial increments the parent order's delivered count and closes the order automatically when the last unit ships; revoking a material certification quarantines the serials machined from it, places their in-production work orders on quality hold, opens counterfeit-suspect nonconformances, and raises escape reports when suspect units already shipped; scrapping the last good serial of an in-production work order drives the order onto quality hold; approving a first article supersedes every previously approved inspection of the same part and revision. Each such mutation refreshes the mutated resource's `updated_at` and increments its `version`, and several cascades deliberately advance the parent agreement's `version` so that observers of the commercial record see the movement.

### 2.11. Validation Priority

When several checks guard the same endpoint, they are evaluated in a fixed priority order, and an earlier failure masks later checks. The order is: (1) header presence — a missing or empty `X-User-ID` or `X-User-Role` fails with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`; (2) role permission — a role not permitted on the endpoint fails with `ERR_INSUFFICIENT_PERMISSIONS`; (3) existence — path identifiers left to right, then body foreign keys, fail with the resource-specific 404 errors of §2.6; (4) optimistic concurrency — a stale `expected_lta_version` fails with `ERR_STALE_LTA_VERSION` on the two guarded endpoints; (5) state-transition validity — a target resource in the wrong state fails with that transition's state-specific 409 error (for example `ERR_LTA_NOT_ACTIVE`, `ERR_PO_NOT_ACCEPTED`, `ERR_WO_NOT_RELEASABLE`, `ERR_CERT_ALREADY_REVOKED`, or the generic `ERR_INVALID_STATE`); (6) segregation of duties on the three anchored operations, failing with `ERR_SOD_VIOLATION`; (7) counterfeit-prevention and source-approval gates on material-certification registration, process-approval creation, source approval, serial batch creation, and serial shipment; (8) airworthiness release gates on work-order release, work-order final acceptance, and serial shipment; (9) uniqueness and completeness constraints; (10) temporal windows and deadlines; and (11) fiscal and quantity capacity. Malformed request payloads — a missing or invalid required field, an invalid enum value, an unknown field, or a non-positive quantity — fail with `ERR_INVALID_REQUEST` (400).

## 3. Business Logic & Workflows

### 3.1. Long-Term Agreements and Rate Readiness

The commercial frame of every program is the long-term agreement. A `ContractsManager` opens one by supplying the `customer_name`, a `ceiling_cents` total value ceiling (a positive integer number of cents), a `pricing_tiers` table, an `escalation_pct_per_year` annual escalation rate, an `award_year` base calendar year, a `rebate_tiers` table, and a `committed_monthly_rate_units` committed production rate in units per calendar month (also positive). The pricing tiers pair a `min_qty` quantity threshold with a `unit_price_cents`; they are kept in ascending `min_qty` order, must be non-empty, and must include a tier whose `min_qty` is 1, so that every positive quantity selects a tier. The rebate tiers pair a `min_invoiced_cents` threshold with a `rebate_pct`, are kept in ascending order, and are keyed on the year's gross invoiced subtotal before any rebate. A new agreement starts in `DRAFT` with `remaining_ceiling_cents` initialized to the full `ceiling_cents`, `consecutive_not_ready_count` at zero, and `last_audit_month` and `last_audit_result` unset until the first audit runs.

Activation moves the agreement `DRAFT → ACTIVE`. Activation from any other state is rejected with `ERR_INVALID_STATE`, and activation additionally requires a non-empty pricing table together with positive `ceiling_cents` and `committed_monthly_rate_units`, failing with `ERR_INVALID_REQUEST` otherwise. While the agreement is `DRAFT` or `ACTIVE`, the `ContractsManager` may amend its commercial terms — any of `pricing_tiers`, `ceiling_cents`, `escalation_pct_per_year`, `rebate_tiers`, or `committed_monthly_rate_units` may be resubmitted. Amendment leaves the agreement's state unchanged, attempts to amend in any other state are rejected with `ERR_INVALID_STATE`, and the amendment is OCC-guarded per §2.7: a stale `expected_lta_version` yields `ERR_STALE_LTA_VERSION` (412). Every amendment increments the agreement's `version` by one. When the ceiling changes, `remaining_ceiling_cents` is re-derived as the new ceiling minus the totals of all non-`CANCELLED` purchase orders. Crucially, amendment never reprices existing purchase orders: their pricing stays pinned to the agreement version recorded on each order as `lta_version_pinned`.

Commercial health is audited monthly by the rate-readiness audit, run by a `QualityManager`. The audit takes the current logical-clock calendar month, sums the `quantity` of every work order of the agreement's purchase orders that reached `COMPLETED` with a `completed_at` inside that month, and divides that demonstrated total by `committed_monthly_rate_units`; the ratio is multiplied by one hundred and rounded half up to an integer readiness percentage. A percentage of at least 100 records a `READY` result in `last_audit_result`; at least 80 but below 100 records `MARGINAL`; below 80 records `NOT_READY`. The audited month — expressed as a YYYY-MM string — is stored in `last_audit_month`. A `NOT_READY` outcome increments `consecutive_not_ready_count` by one; any `READY` or `MARGINAL` outcome resets it to zero. Re-running the audit within the same calendar month replaces the stored result rather than double-counting: the consecutive count is adjusted to exactly what it would be if this rerun were the month's only audit. When `consecutive_not_ready_count` reaches 2, the agreement transitions `ACTIVE → SUSPENDED` automatically, with no human in the loop. While an agreement is `SUSPENDED`, its purchase orders can be neither created nor released — both fail with `ERR_LTA_NOT_ACTIVE` — until a `ContractsManager` reinstates it: reinstatement moves `SUSPENDED → ACTIVE` (any other state fails with `ERR_INVALID_STATE`) and resets `consecutive_not_ready_count` to zero.

An agreement closes from either `ACTIVE` or `SUSPENDED` to the terminal `CLOSED` state; closing from any other state is rejected with `ERR_INVALID_STATE`, and closing is blocked while any of its purchase orders remains in `RECEIVED`, `ACCEPTED`, or `RELEASED`, failing with `ERR_LTA_HAS_OPEN_ORDERS`. Separately, any role may preview the annual volume rebate for a calendar `year`, which defaults to the current logical-clock year when omitted. The evaluation order is pinned to break the apparent circularity between the rebate tier and the net total. First, `gross_invoiced_cents` is the sum of `total_cents` over the agreement's purchase orders that reached `CLOSED` during the requested year — closure being the moment the final serial shipment pushed `delivered_quantity` to the ordered quantity, attributed by the logical timestamp of that shipment. Second, the selected tier is the rebate-tier element with the largest `min_invoiced_cents` that the gross meets or exceeds, the boundary being inclusive. Third, `rebate_cents` is the gross multiplied by the tier's `rebate_pct`, rounded half up to integer cents. Fourth, `net_cents` is the gross minus the rebate. The preview response reports `year`, `gross_invoiced_cents`, `rebate_pct`, `rebate_cents`, and `net_cents`. Agreement lists may be filtered by `status`.

### 3.2. Purchase Orders, Pricing, and Agreement Funds

Against an `ACTIVE` agreement, a `ContractsManager` places a purchase order supplying `lta_id`, the customer's `po_number`, the `part_number` and `part_revision` being ordered, a positive integer `quantity`, the `flowdown_clauses` flowed to this order, an optional `requires_special_process` flag (defaulting to false), the `delivery_year` of contract delivery, and the OCC field `expected_lta_version`. The clause vocabulary is exactly `AS9102_FAI`, `AS9100D_QMS`, `DFARS_COUNTERFEIT_PREVENTION`, `CUSTOMER_SOURCE_INSPECTION`, and `DELEGATED_INSPECTION_PERMITTED`. Per the priority order of §2.11, the stale-version check (`ERR_STALE_LTA_VERSION`, 412) runs before the active-agreement check — creating an order against an agreement that is not `ACTIVE` fails with `ERR_LTA_NOT_ACTIVE` — which in turn precedes the uniqueness check, `po_number` being unique per agreement (`ERR_PO_NUMBER_EXISTS`, 409); the ceiling check runs last. An unknown `lta_id` fails with `ERR_LTA_NOT_FOUND`.

Pricing is computed once at creation and pinned forever. The applicable tier is the pricing-table element with the largest `min_qty` that the ordered `quantity` meets or exceeds — a quantity exactly equal to a tier's `min_qty` selects that tier. The unit price starts at that tier's `unit_price_cents`. When `requires_special_process` is true, the unit price is increased by a ten-percent surcharge. The result is then escalated by annual compounding: it is multiplied by one plus `escalation_pct_per_year`, raised to the power of `delivery_year` minus `award_year`. This final figure is rounded half up exactly once to integer cents and stored as `unit_price_cents`; intermediate values are never rounded. The order's `total_cents` is then its `quantity` multiplied by `unit_price_cents`. The agreement version observed at creation is recorded as `lta_version_pinned`, and later amendments never reprice the order — two orders for identical quantities placed before and after an amendment can legitimately carry different unit prices. A new order starts in `RECEIVED` with `unreleased_quantity` equal to `quantity` and `delivered_quantity` at zero.

Every purchase order debits the agreement's funds: `remaining_ceiling_cents` is reduced by the order's `total_cents`, and an order whose total would drive the remainder negative is rejected with `ERR_LTA_CEILING_EXCEEDED` (402). Order creation also increments the agreement's `version` by one, so observers of the agreement see the commitment. Acceptance — the `RECEIVED → ACCEPTED` transition — marks flow-down review passed; accepting from any other state fails with `ERR_INVALID_STATE`, and acceptance requires a non-empty `flowdown_clauses` list, failing with `ERR_INVALID_REQUEST` otherwise. Release moves `ACCEPTED → RELEASED`; releasing an order that is not `ACCEPTED` fails with `ERR_PO_NOT_ACCEPTED`, and release additionally requires the parent agreement to be `ACTIVE`, failing with `ERR_LTA_NOT_ACTIVE` while it is `SUSPENDED` or otherwise not active. An order closes automatically — `RELEASED → CLOSED` — the moment `delivered_quantity` reaches the ordered `quantity`, and the closed order's `total_cents` then contributes to the agreement's rebate gross for the calendar year of closure.

Cancellation moves an order from `RECEIVED`, `ACCEPTED`, or `RELEASED` to the terminal `CANCELLED` state; an order in any other state is not cancellable, and the attempt fails with `ERR_PO_NOT_CANCELLABLE`. Cancellation is blocked while any of the order's work orders is in `IN_PRODUCTION`, `QUALITY_HOLD`, or `FINAL_INSPECTION`, failing with `ERR_PO_HAS_ACTIVE_WORK`. The cancellation cascade then restores consistency: every work order of the order still in `PLANNED` or `RELEASED` is cancelled, each first returning its `quantity` to the order's `unreleased_quantity`; the order's `total_cents` is added back to the agreement's `remaining_ceiling_cents`; and the agreement's `version` increments by one. Order lists may be filtered by `lta_id`, `part_number`, or `status`.

### 3.3. Sourcing: Approved Sources, Material Certifications, and Special-Process Approvals

Counterfeit-part prevention begins at the source register. A `SupplyChainManager` registers a candidate with a unique `supplier_code`, an `approval_scope` of `RAW_MATERIAL`, `SPECIAL_PROCESS`, or `DISTRIBUTOR`, and a `counterfeit_risk_rating` of `LOW`, `MEDIUM`, or `HIGH`; the source starts `PROVISIONAL`. Approval moves `PROVISIONAL → APPROVED` (from any other state, `ERR_SOURCE_NOT_APPROVABLE`), with one counterfeit gate: a source rated `HIGH` risk may not be approved for the `RAW_MATERIAL` or `DISTRIBUTOR` scope, the attempt failing with `ERR_COUNTERFEIT_RISK_TOO_HIGH`. Disqualification moves `APPROVED → DISQUALIFIED` (from any other state, `ERR_SOURCE_NOT_APPROVABLE`), records a `reason`, and — as a containment side effect — suspends every special-process approval of that source currently `ACTIVE`. A `PROVISIONAL` source may also be disqualified directly, carrying it straight to the terminal `DISQUALIFIED` state. Referencing an unknown source id fails with `ERR_SOURCE_NOT_FOUND`; source lists may be filtered by `status` or `approval_scope`.

Special-process approvals grant a processor a dated window of authority. A `SupplyChainManager` creates one with `source_id`, a `process_code` of `HEAT_TREAT`, `NDT`, `PLATING`, `WELDING`, or `SHOT_PEEN`, a `valid_from` window start, a `valid_to` window end, and a `cert_reference` audit reference such as a Nadcap certificate number. The referenced source must be `APPROVED` with the `SPECIAL_PROCESS` scope, failing with `ERR_SOURCE_NOT_APPROVED` otherwise. The window is half-open: it covers dates from `valid_from` inclusive up to but not including `valid_to`, and a `valid_to` not later than `valid_from` is rejected with `ERR_INVALID_WINDOW` (400). Two `ACTIVE` windows for the same source and `process_code` may not overlap — a conflicting grant is rejected with `ERR_APPROVAL_WINDOW_OVERLAP` (409) — but because the window is half-open, adjacency is permitted: a new window whose `valid_from` equals an existing window's `valid_to` does not overlap it. A new approval starts `ACTIVE`. Suspension moves `ACTIVE → SUSPENDED` and reinstatement moves `SUSPENDED → ACTIVE`, each from its named state only (`ERR_INVALID_STATE` otherwise); reinstatement re-applies the window-overlap rule against the source's other `ACTIVE` approvals of the same process, failing with `ERR_APPROVAL_WINDOW_OVERLAP` on conflict. Unknown approval ids fail with `ERR_PROCESS_APPROVAL_NOT_FOUND`; approval lists filter by `source_id`, `process_code`, or `status`.

Material certifications tie physical stock to its pedigree. A `SupplyChainManager` registers a mill cert with `source_id`, `heat_number`, a `material_spec` such as AMS 5643, and a positive `quantity_received`. The source must be `APPROVED` with `RAW_MATERIAL` or `DISTRIBUTOR` scope, failing with `ERR_SOURCE_NOT_APPROVED` otherwise. The new cert starts `RECEIVED` with `quantity_available` equal to `quantity_received`, and `created_by_user_id` anchored to the registrar's `X-User-ID`. Receiving inspection moves `RECEIVED → ACCEPTED` — from any other state, `ERR_CERT_NOT_ACCEPTABLE` — under segregation of duties: the accepting inspector's `X-User-ID` must differ from `created_by_user_id`, failing with `ERR_SOD_VIOLATION` on a match. Thereafter `quantity_available` at all times equals `quantity_received` minus the units already allocated to serial batches, as §3.5 describes. Unknown cert ids fail with `ERR_MATERIAL_CERT_NOT_FOUND`; cert lists filter by `source_id` or `status`.

Revocation is the containment hammer. A `QualityManager` revokes a cert — recording a `reason` — from `RECEIVED` or `ACCEPTED` to the terminal `REVOKED` state; revoking an already-`REVOKED` cert fails with `ERR_CERT_ALREADY_REVOKED`. The revocation cascade then runs four links. First, every serial number machined from this cert — every serial whose `material_cert_id` references it — that is still `CREATED` moves to `QUARANTINED`. Second, every work order owning a serial that just became `QUARANTINED`, and currently `IN_PRODUCTION`, moves to `QUALITY_HOLD`. Third, each work order pushed to `QUALITY_HOLD` gets an auto-created nonconformance report with `origin` `AUTO_COUNTERFEIT`, `defect_code` `COUNTERFEIT_SUSPECT`, `quantity_affected` equal to the number of serials quarantined on that work order, and status `OPEN`. Fourth, if any serial traced to this cert had already been `SHIPPED`, the affected order's auto-created report also spawns a `DRAFT` escape report flagged `detected_post_shipment`, starting the customer's forty-eight-hour notification clock.

### 3.4. First-Article Inspection and Ballooned Characteristics

An AS9102 first-article inspection demonstrates that production can actually make the drawing. A `QualityInspector` opens an FAI with a `part_number`, a `part_revision`, and a `fai_type` — `FULL` for a new part or revision, `PARTIAL` for a delta or change FAI — and the inspection starts in `DRAFT`. Unknown inspection ids fail with `ERR_FAI_NOT_FOUND`; inspection lists filter by `part_number`, `part_revision`, or `status`.

Ballooning decomposes the drawing into numbered characteristics. The inspector adds each characteristic with a `balloon_number` unique within the inspection (a duplicate fails with `ERR_BALLOON_NUMBER_EXISTS`, 409), a `nominal` dimension, a non-negative `tolerance_plus` and `tolerance_minus`, and an optional `is_key_characteristic` flag (defaulting to false) designating a key characteristic that will require SPC in production. Characteristics may only be added while the inspection is `DRAFT` or `IN_INSPECTION`; a locked inspection fails with `ERR_CHARACTERISTIC_LOCKED`. On creation the characteristic computes its specification limits — `usl` as the nominal plus the upper tolerance, `lsl` as the nominal minus the lower tolerance — starts with `result` `UNMEASURED`, and links back to its inspection via `fai_id`. The very first characteristic added moves the inspection `DRAFT → IN_INSPECTION` automatically. Unknown characteristic ids fail with `ERR_CHARACTERISTIC_NOT_FOUND`.

Measurement records the as-built truth. Recording a `measured_value` is permitted only while the characteristic's `result` is `UNMEASURED` or `FAIL` — re-measuring a `PASS` characteristic fails with `ERR_CHARACTERISTIC_NOT_MEASURABLE` — and only while the parent inspection remains `DRAFT` or `IN_INSPECTION` (`ERR_CHARACTERISTIC_LOCKED` otherwise). The result recomputes from the limits: `PASS` when the measured value is at least `lsl` and at most `usl`, `FAIL` when it falls outside. The recorder's identity is anchored as `measured_by_user_id`, and a re-measurement after rework overwrites both the stored value and the anchor. After every characteristic added and every measurement recorded, the inspection recomputes its completeness bookkeeping: `characteristic_count` counts its ballooned characteristics, `measured_count` counts those whose `result` is `PASS` or `FAIL`, and `characteristics_complete` is true exactly when at least one characteristic exists and every one of them has been measured.

Submission moves `IN_INSPECTION → SUBMITTED` and is where the inspection proves itself. The checks run in §2.11 order: an inspection not in `IN_INSPECTION` fails with `ERR_FAI_NOT_SUBMITTABLE`; then segregation of duties — the submitter's `X-User-ID` must differ from the `measured_by_user_id` of every characteristic, failing with `ERR_SOD_VIOLATION`; then the content gates — an inspection with zero characteristics or any still `UNMEASURED` fails with `ERR_FAI_INCOMPLETE_CHARACTERISTICS`, and one carrying any `FAIL` result fails with `ERR_FAI_CHARACTERISTIC_FAILURE`. A successful submit anchors `submitted_by_user_id` to the submitting inspector.

The customer decides. A `CustomerQualityRep` approves a `SUBMITTED` inspection to `APPROVED` — from any other state, `ERR_FAI_NOT_SUBMITTED` — which pins `approved_revision` equal to the inspection's `part_revision`, freezing the approved revision at the moment of approval, and supersedes every other `APPROVED` inspection of the same `part_number` and `part_revision`, moving each to the terminal `SUPERSEDED` state. Rejection instead moves `SUBMITTED → REJECTED` with a recorded `reason`. A `QualityInspector` may reopen a rejected inspection — `REJECTED → IN_INSPECTION`, the rework loop — while reopening from any other state fails with `ERR_FAI_NOT_REOPENABLE`. An approved first article is what unlocks production: as §3.5 describes, releasing a work order whose purchase order flowed down `AS9102_FAI` demands an `APPROVED` inspection matching the order's `part_number` and `part_revision`.

### 3.5. Work Orders, Serialization, and Shipment

Work orders carve a purchase order into producible lots. A `ManufacturingPlanner` creates one against an order via `po_id`, a positive `quantity`, and an optional `special_processes_required` list (defaulting to empty; values drawn from `HEAT_TREAT`, `NDT`, `PLATING`, `WELDING`, `SHOT_PEEN`). The quantity may not exceed the order's `unreleased_quantity` — `ERR_QUANTITY_EXCEEDS_UNRELEASED` on overflow, with equality allowed — and creation debits `unreleased_quantity` by the planned quantity. A new work order starts `PLANNED` with `serials_created_count`, `good_quantity`, and `scrapped_quantity` at zero, `spc_status` at `MONITORING`, and `requires_100pct_inspection` false. Unknown order ids fail with `ERR_PO_NOT_FOUND`; work-order lists filter by `po_id` or `status`.

Release is where the airworthiness gates bite, evaluated in §2.11 order with the state checks preceding the gate checks. Releasing from any state but `PLANNED` fails with `ERR_WO_NOT_RELEASABLE`; the parent order must be `RELEASED`, failing with `ERR_PO_NOT_RELEASED` otherwise. Then the gates: if the order's `flowdown_clauses` contain `AS9102_FAI`, an `APPROVED` first-article inspection must exist for the order's `part_number` and `part_revision`, failing with `ERR_FAI_REQUIRED` otherwise; and for each process named in `special_processes_required`, an `ACTIVE` special-process approval must exist for that `process_code`, whose window covers the current logical date — `valid_from` at or before it and the date before `valid_to` — held by an `APPROVED` source, failing with `ERR_PROCESS_NOT_APPROVED` otherwise. A clean release moves `PLANNED → RELEASED`.

Serialization turns plans into traceable units. The planner creates a batch by supplying a `material_cert_id` and a `count`. The work order must be `RELEASED` or `IN_PRODUCTION`, failing with `ERR_WO_NOT_ACCEPTING_SERIALS` otherwise; per §2.11 this state check precedes the certificate checks, which precede the quantity checks. The referenced certification must be `ACCEPTED`: a cert still `RECEIVED` fails with `ERR_MATERIAL_CERT_NOT_ACCEPTED`, and a `REVOKED` cert fails with `ERR_MATERIAL_CERT_REVOKED`. The batch size may not exceed the cert's `quantity_available` (`ERR_INSUFFICIENT_MATERIAL_QUANTITY`, equality allowed), and `serials_created_count` plus the batch `count` may not exceed the work order's `quantity` (`ERR_SERIAL_BATCH_EXCEEDS_QUANTITY`). Each created serial receives a system-assigned `serial_number` of the form SN-NNNN — a four-digit, zero-padded sequence per work order in creation order, beginning SN-0001 — and records its `wo_id` and `material_cert_id`; the cert's `quantity_available` is debited by the batch size. The first successful batch moves the work order `RELEASED → IN_PRODUCTION` automatically. Serials begin life `CREATED`; at all times a work order's `good_quantity` counts its serials in `CREATED`, `SHIPPED`, or `QUARANTINED`, and `scrapped_quantity` counts those `SCRAPPED`.

Completion and acceptance close the production loop. Completing moves `IN_PRODUCTION → FINAL_INSPECTION` — from any other state, `ERR_WO_NOT_IN_PRODUCTION` — and requires the serial count to be complete, `serials_created_count` equal to the work order's `quantity` (`ERR_SERIALS_INCOMPLETE` otherwise), with no nonconformance report on this work order sitting in `OPEN` or `MRB_REVIEW` (`ERR_WO_OPEN_NCR` otherwise). Completion also freezes the statistical picture: for each key characteristic with at least five SPC measurements on this work order, the final capability index is computed with the population-standard-deviation variant of §3.6 and stored as `cpk_final`. Final acceptance moves `FINAL_INSPECTION → COMPLETED` — from any other state, `ERR_WO_NOT_ACCEPTABLE` — and stamps `completed_at` with the current logical clock. A `CustomerQualityRep` may always accept; that is customer source inspection. A `QualityInspector` may accept only under delegated authority: an `ACTIVE` delegation must exist whose `po_id` matches the work order's parent order, whose `inspector_user_id` equals the caller's `X-User-ID`, and whose closed window covers the current logical date — `valid_from` at or before it and `valid_to` at or after it — failing with `ERR_DELEGATION_REQUIRED` (403) otherwise. Cancellation moves `PLANNED` or `RELEASED` to `CANCELLED` — from any other state, `ERR_WO_NOT_CANCELLABLE` — and returns the work order's `quantity` to the order's `unreleased_quantity`.

Quality holds interrupt production without ending it. A work order lands in `QUALITY_HOLD` only by system action — the material-cert revocation cascade of §3.3, or a scrap disposition that removes its last good serial per §3.7. A `QualityManager` releases the hold — `QUALITY_HOLD → IN_PRODUCTION` — only from `QUALITY_HOLD` itself (`ERR_WO_NOT_ON_HOLD` otherwise), only while no serial of the work order remains `QUARANTINED`, and only while no nonconformance report on the work order sits in `OPEN` or `MRB_REVIEW`; either blocking condition fails with `ERR_WO_OPEN_NCR`.

Shipment is the last gate. Shipping moves one serial `CREATED → SHIPPED` — from any other state, `ERR_SERIAL_NOT_SHIPPABLE` — and its preconditions run in §2.11 order: the parent work order must be `COMPLETED` (`ERR_WO_NOT_ACCEPTABLE` otherwise); the serial's material cert must be `ACCEPTED` (`ERR_MATERIAL_CERT_REVOKED` otherwise); and no nonconformance report in `OPEN` or `MRB_REVIEW` may list this serial in its `affected_serial_ids` (`ERR_SERIAL_UNDER_NCR` otherwise). A successful shipment stamps `shipped_at` with the logical clock, increments the parent order's `delivered_quantity` by one, and — when the delivered count reaches the ordered `quantity` — bubbles the order `RELEASED → CLOSED` automatically, contributing the order's `total_cents` to that calendar year's rebate gross per §3.1. A bulk-shipment capability ships every `CREATED` serial of a `COMPLETED` work order in one call under the same per-serial preconditions, and it is atomic: if any `CREATED` serial fails a ship precondition — a revoked cert, a serial under an open nonconformance — the entire batch is rejected with that error and nothing ships; otherwise the order's `delivered_quantity` advances by the number shipped and may close the order. Unknown serial ids fail with `ERR_SERIAL_NOT_FOUND`; serial lists filter by `wo_id`, `material_cert_id`, or `status`, and a work order's serial list filters by `status`.

### 3.6. Statistical Process Control on Key Characteristics

Key characteristics carry the production risk, so each one is watched statistically. A `QualityInspector` records an SPC measurement by naming a `characteristic_id` and a `measured_value`. The parent work order must be `IN_PRODUCTION`, failing with `ERR_WO_NOT_IN_PRODUCTION` otherwise, and the characteristic must actually be a key characteristic — `is_key_characteristic` true — failing with `ERR_INVALID_REQUEST` otherwise. The created observation records its `wo_id`, anchors `recorded_by_user_id` to the recording inspector, and — per §2.4 — carries only `id` and `created_at` as system fields.

Capability evaluation always works on a fixed window: the last 25 measurements recorded for the work-order-and-characteristic pair, ordered by `created_at` ascending, with ties broken by timestamp alone. Fewer than 5 measurements in the window yields no index at all, and the characteristic's `spc_eval_status` rests at `MONITORING`. With 5 or more, the mean is the arithmetic average of the windowed values. Two standard-deviation variants exist: the provisional variant, recomputed on every measurement during production, divides the sum of squared deviations from the mean by one less than the count — the sample standard deviation — while the final variant, computed once at work-order completion, divides by the full count — the population standard deviation — so identical measurements yield a `cpk_final` larger than the `cpk_provisional`. The capability index itself is the smaller of two margins — the `usl` minus the mean, and the mean minus the `lsl` — divided by three times the applicable standard deviation. The reported index is rounded half up to three decimal places; the reported mean and standard deviation are rounded half up to four decimal places for display only; and the verdict compares the rounded three-decimal index against the capability threshold of 1.33: an index of at least 1.33 sets the characteristic's `spc_eval_status` to `CAPABLE`, while anything below sets `INCAPABLE`. The provisional result is stored as `cpk_provisional`; the completion-time result as `cpk_final`. Before any evaluation, a characteristic's `spc_eval_status` is `NONE`.

Crossing into incapability is an escape-prevention event. When a characteristic's posture transitions into `INCAPABLE`, the work order's `spc_status` becomes `INCAPABLE`, its `requires_100pct_inspection` flag is set true — and never auto-clears — and a nonconformance report is auto-created with `origin` `AUTO_SPC`, `defect_code` `SPC_CAPABILITY_LOSS`, `quantity_affected` one, and status `OPEN`. More broadly, a work order's `spc_status` always reflects the worst posture across its key characteristics: `INCAPABLE` if any key characteristic is `INCAPABLE`; otherwise `CAPABLE` if every key characteristic with at least five measurements is `CAPABLE` and at least one characteristic has been evaluated; otherwise `MONITORING`. SPC measurement history can be listed per characteristic, or per work order with an optional `characteristic_id` filter.

### 3.7. Nonconformance, MRB Disposition, and Escape Reporting

When something goes wrong, the system opens a nonconformance report. A `QualityInspector` creates one with `wo_id`, a `defect_code`, a `description`, a positive `quantity_affected`, an optional `affected_serial_ids` list (defaulting to empty), and a `detected_post_shipment` flag (defaulting to false) marking an escape discovered after shipment. Every id in `affected_serial_ids` must exist — an unknown id fails with `ERR_SERIAL_NOT_FOUND` — and must belong to the named work order, failing with `ERR_INVALID_REQUEST` otherwise. The new report starts `OPEN` with `origin` `MANUAL`, `discovered_by_user_id` anchored to the creator, and `concession_approved` false; `disposition`, `disposition_by_user_id`, `estimated_cost_cents`, and `actual_cost_cents` remain unset until later stages. When `detected_post_shipment` is true, creation also spawns a `DRAFT` escape report whose `due_at` is exactly 48 hours after the report's `created_at`. Unknown work-order ids fail with `ERR_WO_NOT_FOUND`; report lists filter by `wo_id`, `status`, or `disposition`, and unknown report ids fail with `ERR_NCR_NOT_FOUND`.

The Material Review Board pipeline runs `OPEN → MRB_REVIEW → DISPOSITIONED → VERIFIED → CLOSED`, with a kickback loop. A `QualityManager` submits an `OPEN` report to the board — `OPEN → MRB_REVIEW` — from that state only (`ERR_INVALID_STATE` otherwise). An `MRBMember` may kick a report back — `MRB_REVIEW → OPEN` — recording a `reason`, when containment information is insufficient, likewise from `MRB_REVIEW` only (`ERR_INVALID_STATE` otherwise).

Disposition is the consequential act: `MRB_REVIEW → DISPOSITIONED`, performed by an `MRBMember`, from `MRB_REVIEW` only (`ERR_INVALID_STATE` otherwise), and — evaluated after the state check per §2.11 — under segregation of duties: the disposer's `X-User-ID` must differ from the report's `discovered_by_user_id`, failing with `ERR_SOD_VIOLATION`. The payload carries the `disposition` itself — one of `USE_AS_IS`, `REWORK`, `SCRAP`, or `RETURN_TO_SUPPLIER` — plus the planner-estimated `rework_hours_per_unit` and `material_cost_per_unit_cents` cost inputs. Disposition stores the decision, anchors `disposition_by_user_id` to the board member, and computes `estimated_cost_cents`: each affected unit's raw cost is `rework_hours_per_unit` multiplied by the standard labor rate of 12,500 cents per hour, plus `material_cost_per_unit_cents`; that per-unit figure is rounded half up to integer cents first, and only then multiplied by `quantity_affected`. The rounding order is pinned — round each unit, then multiply — because summing raw costs across units before rounding yields a different result and is not permitted. The four branches then diverge. Under `SCRAP`, every affected serial in `CREATED` or `QUARANTINED` moves to `SCRAPPED`, the owning work order's `scrapped_quantity` and `good_quantity` are recomputed, and if the work order's `good_quantity` has fallen to zero while at least one serial was ever created and the work order is `IN_PRODUCTION`, the work order moves to `QUALITY_HOLD`. Under `USE_AS_IS`, every affected serial in `QUARANTINED` is released back to `CREATED`. Under `REWORK`, no serial changes hands, but verification will expect actual cost inputs. Under `RETURN_TO_SUPPLIER`, no serial changes.

Two customer-facing steps follow. A `CustomerQualityRep` records a customer concession — supplying a `concession_reference` — only while the report is `DISPOSITIONED` with a `USE_AS_IS` disposition, failing with `ERR_INVALID_STATE` otherwise, and the recording sets `concession_approved` true. Verification then moves `DISPOSITIONED → VERIFIED` under a `QualityInspector`, from that state only (`ERR_INVALID_STATE` otherwise); a `USE_AS_IS` disposition may not verify until the concession is recorded, failing with `ERR_NCR_REQUIRES_CONCESSION` while `concession_approved` is false. Verification accepts the optional actuals `actual_rework_hours_per_unit` and `actual_material_cost_per_unit_cents`; when supplied, `actual_cost_cents` is computed with the same per-unit-round-then-multiply formula as the estimate, substituting the actual inputs — the same formula over different inputs legitimately producing a different value for identical quantities. Closure moves `VERIFIED → CLOSED` under a `QualityManager`, from that state only (`ERR_INVALID_STATE` otherwise), with one escape gate: when `detected_post_shipment` is true, the linked escape report must already be `ACKNOWLEDGED`, failing with `ERR_ESCAPE_NOT_ACKNOWLEDGED` otherwise.

Escape reports carry the customer's statutory notification. Each report links back to its originating nonconformance via `ncr_id`, with `due_at` fixed at creation as described above. A `QualityManager` submits — `DRAFT → SUBMITTED` — from `DRAFT` only (`ERR_INVALID_STATE` otherwise), and the submission must land within the window: the current logical clock at or before `due_at`, the 48-hour boundary being inclusive; a later attempt is rejected with `ERR_ESCAPE_WINDOW_EXCEEDED` (422). A successful submit stamps `submitted_at` with the logical clock. A `CustomerQualityRep` then acknowledges — `SUBMITTED → ACKNOWLEDGED`, the terminal state — supplying an `acknowledgement_reference`, from `SUBMITTED` only (`ERR_INVALID_STATE` otherwise). Unknown escape ids fail with `ERR_ESCAPE_REPORT_NOT_FOUND`; escape lists filter by `ncr_id` or `status`.

### 3.8. Delegated Inspection Authority

Customer source inspection can be delegated to a named supplier inspector for a named purchase order. A `CustomerQualityRep` grants a delegation with `po_id`, `inspector_user_id`, `valid_from`, and `valid_to`. Unlike the half-open special-process windows, a delegation window is closed: it covers `valid_from` through `valid_to`, both dates inclusive, and a `valid_to` earlier than `valid_from` is rejected with `ERR_INVALID_WINDOW`. Two `ACTIVE` delegations for the same `po_id` and `inspector_user_id` may not intersect — because both endpoints of the window are inclusive, touching boundaries count as overlap — and a conflicting grant is rejected with `ERR_DELEGATION_WINDOW_OVERLAP` (409). Revocation carries a tail: after a delegation is revoked, a re-grant to the same `po_id` and `inspector_user_id` whose `valid_from` falls earlier than thirty days after the `revoked_at` date is rejected with `ERR_DIA_COOLING_OFF` (409). A new delegation starts `ACTIVE` with `granted_by_user_id` anchored to the granting representative. Unknown order ids fail with `ERR_PO_NOT_FOUND`, unknown delegation ids with `ERR_DELEGATION_NOT_FOUND`; delegation lists filter by `po_id`, `inspector_user_id`, or `status`.

Revocation moves `ACTIVE → REVOKED`, terminal, performed by a `CustomerQualityRep` with a recorded `reason`; revoking from any other state fails with `ERR_INVALID_STATE`. The revocation stamps `revoked_at` with the current logical clock, and that timestamp anchors the thirty-day cooling-off rule above. The delegation's only consumer is final acceptance, as §3.5 describes: a `QualityInspector` accepting a completed work order must hold an `ACTIVE` delegation for the order and inspector whose closed window covers the current logical date, failing with `ERR_DELEGATION_REQUIRED` otherwise, while a `CustomerQualityRep` accepts without one.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource, drive a state transition, or read data return `200 OK`. The table below is a summary only — request payloads, computed fields, side effects, and error triggers are defined by the narratives of Sections 2 and 3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/ltas` | Create a long-term agreement (starts `DRAFT`) | ContractsManager |
| GET | `/api/ltas` | List long-term agreements | Any |
| GET | `/api/ltas/{ltaId}` | Get one long-term agreement | Any |
| POST | `/api/ltas/{ltaId}/activate` | Activate a draft agreement | ContractsManager |
| POST | `/api/ltas/{ltaId}/amend` | Amend commercial terms (OCC-guarded) | ContractsManager |
| POST | `/api/ltas/{ltaId}/close` | Close an agreement with no open orders | ContractsManager |
| POST | `/api/ltas/{ltaId}/reinstate` | Reinstate a suspended agreement | ContractsManager |
| POST | `/api/ltas/{ltaId}/run-rate-audit` | Run the monthly rate-readiness audit | QualityManager |
| GET | `/api/ltas/{ltaId}/rebate-preview` | Preview the annual volume rebate for a year | Any |
| POST | `/api/purchase-orders` | Create a purchase order against an agreement (OCC-guarded) | ContractsManager |
| GET | `/api/purchase-orders` | List purchase orders | Any |
| GET | `/api/purchase-orders/{poId}` | Get one purchase order | Any |
| POST | `/api/purchase-orders/{poId}/accept` | Accept an order after flow-down review | ContractsManager |
| POST | `/api/purchase-orders/{poId}/release` | Release an order to production | ContractsManager |
| POST | `/api/purchase-orders/{poId}/cancel` | Cancel an order and restore agreement funds | ContractsManager |
| POST | `/api/first-articles` | Create a first-article inspection | QualityInspector |
| GET | `/api/first-articles` | List first-article inspections | Any |
| GET | `/api/first-articles/{faiId}` | Get one first-article inspection | Any |
| POST | `/api/first-articles/{faiId}/characteristics` | Add a ballooned characteristic | QualityInspector |
| GET | `/api/first-articles/{id}/characteristics` | List characteristics of an inspection | Any |
| POST | `/api/first-articles/{faiId}/submit` | Submit an inspection for customer review | QualityInspector |
| POST | `/api/first-articles/{faiId}/approve` | Approve an inspection (pins revision, supersedes siblings) | CustomerQualityRep |
| POST | `/api/first-articles/{faiId}/reject` | Reject an inspection | CustomerQualityRep |
| POST | `/api/first-articles/{faiId}/reopen` | Reopen a rejected inspection for rework | QualityInspector |
| GET | `/api/characteristics/{charId}` | Get one ballooned characteristic | Any |
| POST | `/api/characteristics/{charId}/record-measurement` | Record an FAI measurement and recompute the result | QualityInspector |
| GET | `/api/characteristics/{id}/spc-measurements` | List SPC measurements of a characteristic | Any |
| POST | `/api/work-orders` | Create a work order under a purchase order | ManufacturingPlanner |
| GET | `/api/work-orders` | List work orders | Any |
| GET | `/api/work-orders/{woId}` | Get one work order | Any |
| POST | `/api/work-orders/{woId}/release` | Release a work order through the airworthiness gates | ManufacturingPlanner |
| POST | `/api/work-orders/{woId}/serials` | Create a batch of serialized units against a material cert | ManufacturingPlanner |
| GET | `/api/work-orders/{woId}/serials` | List serials of a work order | Any |
| POST | `/api/work-orders/{woId}/spc-measurements` | Record an SPC measurement on a key characteristic | QualityInspector |
| GET | `/api/work-orders/{id}/spc-measurements` | List SPC measurements of a work order | Any |
| POST | `/api/work-orders/{woId}/complete` | Complete production and enter final inspection | ManufacturingPlanner |
| POST | `/api/work-orders/{woId}/accept` | Final acceptance of a work order | CustomerQualityRep, QualityInspector |
| POST | `/api/work-orders/{woId}/cancel` | Cancel a planned or released work order | ManufacturingPlanner |
| POST | `/api/work-orders/{woId}/release-hold` | Release a work order from quality hold | QualityManager |
| POST | `/api/work-orders/{woId}/ship-all` | Ship every created serial of a completed work order (atomic) | ManufacturingPlanner |
| GET | `/api/serials` | List serialized units | Any |
| GET | `/api/serials/{serialId}` | Get one serialized unit | Any |
| POST | `/api/serials/{serialId}/ship` | Ship one serialized unit | ManufacturingPlanner |
| POST | `/api/material-certs` | Register a material certification from an approved source | SupplyChainManager |
| GET | `/api/material-certs` | List material certifications | Any |
| GET | `/api/material-certs/{certId}` | Get one material certification | Any |
| POST | `/api/material-certs/{certId}/accept` | Accept a certification at receiving inspection | QualityInspector |
| POST | `/api/material-certs/{certId}/revoke` | Revoke a certification (counterfeit containment cascade) | QualityManager |
| POST | `/api/sources` | Register an approved-source candidate | SupplyChainManager |
| GET | `/api/sources` | List approved sources | Any |
| GET | `/api/sources/{sourceId}` | Get one approved source | Any |
| POST | `/api/sources/{sourceId}/approve` | Approve a provisional source | SupplyChainManager |
| POST | `/api/sources/{sourceId}/disqualify` | Disqualify a source and suspend its process approvals | SupplyChainManager |
| POST | `/api/process-approvals` | Grant a special-process approval window | SupplyChainManager |
| GET | `/api/process-approvals` | List special-process approvals | Any |
| GET | `/api/process-approvals/{paId}` | Get one special-process approval | Any |
| POST | `/api/process-approvals/{paId}/suspend` | Suspend a special-process approval | SupplyChainManager |
| POST | `/api/process-approvals/{paId}/reinstate` | Reinstate a suspended approval (overlap rule re-applied) | SupplyChainManager |
| POST | `/api/ncrs` | Open a nonconformance report on a work order | QualityInspector |
| GET | `/api/ncrs` | List nonconformance reports | Any |
| GET | `/api/ncrs/{ncrId}` | Get one nonconformance report | Any |
| POST | `/api/ncrs/{ncrId}/submit-mrb` | Submit a nonconformance to the Material Review Board | QualityManager |
| POST | `/api/ncrs/{ncrId}/disposition` | Disposition a nonconformance (per-branch cascades) | MRBMember |
| POST | `/api/ncrs/{ncrId}/verify` | Verify a dispositioned nonconformance | QualityInspector |
| POST | `/api/ncrs/{ncrId}/close` | Close a verified nonconformance | QualityManager |
| POST | `/api/ncrs/{ncrId}/kickback` | Return a nonconformance to open for more containment | MRBMember |
| POST | `/api/ncrs/{ncrId}/customer-concession` | Record a customer concession for a use-as-is disposition | CustomerQualityRep |
| GET | `/api/escape-reports` | List escape reports | Any |
| GET | `/api/escape-reports/{erId}` | Get one escape report | Any |
| POST | `/api/escape-reports/{erId}/submit` | Submit an escape report within its 48-hour window | QualityManager |
| POST | `/api/escape-reports/{erId}/acknowledge` | Acknowledge an escape report | CustomerQualityRep |
| POST | `/api/delegations` | Grant delegated inspection authority for an order | CustomerQualityRep |
| GET | `/api/delegations` | List delegations | Any |
| GET | `/api/delegations/{diaId}` | Get one delegation | Any |
| POST | `/api/delegations/{diaId}/revoke` | Revoke a delegation (anchors cooling-off) | CustomerQualityRep |
| POST | `/api/_clock/set_current_utc` | Set the server logical clock (test-driving) | SystemAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error live in the narratives of Sections 2 and 3; this catalogue fixes only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_WINDOW` | 400 Bad Request |
| `ERR_LTA_NOT_FOUND` | 404 Not Found |
| `ERR_PO_NOT_FOUND` | 404 Not Found |
| `ERR_FAI_NOT_FOUND` | 404 Not Found |
| `ERR_CHARACTERISTIC_NOT_FOUND` | 404 Not Found |
| `ERR_WO_NOT_FOUND` | 404 Not Found |
| `ERR_SERIAL_NOT_FOUND` | 404 Not Found |
| `ERR_MATERIAL_CERT_NOT_FOUND` | 404 Not Found |
| `ERR_SOURCE_NOT_FOUND` | 404 Not Found |
| `ERR_PROCESS_APPROVAL_NOT_FOUND` | 404 Not Found |
| `ERR_NCR_NOT_FOUND` | 404 Not Found |
| `ERR_ESCAPE_REPORT_NOT_FOUND` | 404 Not Found |
| `ERR_DELEGATION_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_LTA_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_LTA_NOT_ACTIVE` | 409 Conflict |
| `ERR_LTA_HAS_OPEN_ORDERS` | 409 Conflict |
| `ERR_PO_NOT_ACCEPTED` | 409 Conflict |
| `ERR_PO_NOT_RELEASED` | 409 Conflict |
| `ERR_PO_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_FAI_NOT_SUBMITTABLE` | 409 Conflict |
| `ERR_FAI_NOT_SUBMITTED` | 409 Conflict |
| `ERR_FAI_NOT_REOPENABLE` | 409 Conflict |
| `ERR_CHARACTERISTIC_LOCKED` | 409 Conflict |
| `ERR_CHARACTERISTIC_NOT_MEASURABLE` | 409 Conflict |
| `ERR_WO_NOT_RELEASABLE` | 409 Conflict |
| `ERR_WO_NOT_IN_PRODUCTION` | 409 Conflict |
| `ERR_WO_NOT_ACCEPTING_SERIALS` | 409 Conflict |
| `ERR_WO_NOT_ACCEPTABLE` | 409 Conflict |
| `ERR_WO_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_WO_NOT_ON_HOLD` | 409 Conflict |
| `ERR_SERIAL_NOT_SHIPPABLE` | 409 Conflict |
| `ERR_CERT_NOT_ACCEPTABLE` | 409 Conflict |
| `ERR_CERT_ALREADY_REVOKED` | 409 Conflict |
| `ERR_SOURCE_NOT_APPROVABLE` | 409 Conflict |
| `ERR_SOD_VIOLATION` | 403 Forbidden |
| `ERR_SOURCE_NOT_APPROVED` | 422 Unprocessable Entity |
| `ERR_COUNTERFEIT_RISK_TOO_HIGH` | 422 Unprocessable Entity |
| `ERR_MATERIAL_CERT_NOT_ACCEPTED` | 422 Unprocessable Entity |
| `ERR_MATERIAL_CERT_REVOKED` | 422 Unprocessable Entity |
| `ERR_FAI_REQUIRED` | 422 Unprocessable Entity |
| `ERR_PROCESS_NOT_APPROVED` | 422 Unprocessable Entity |
| `ERR_DELEGATION_REQUIRED` | 403 Forbidden |
| `ERR_SERIAL_UNDER_NCR` | 422 Unprocessable Entity |
| `ERR_PO_NUMBER_EXISTS` | 409 Conflict |
| `ERR_BALLOON_NUMBER_EXISTS` | 409 Conflict |
| `ERR_FAI_INCOMPLETE_CHARACTERISTICS` | 422 Unprocessable Entity |
| `ERR_FAI_CHARACTERISTIC_FAILURE` | 422 Unprocessable Entity |
| `ERR_SERIALS_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_WO_OPEN_NCR` | 409 Conflict |
| `ERR_PO_HAS_ACTIVE_WORK` | 409 Conflict |
| `ERR_NCR_REQUIRES_CONCESSION` | 422 Unprocessable Entity |
| `ERR_ESCAPE_NOT_ACKNOWLEDGED` | 409 Conflict |
| `ERR_APPROVAL_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_DELEGATION_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_DIA_COOLING_OFF` | 409 Conflict |
| `ERR_ESCAPE_WINDOW_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_LTA_CEILING_EXCEEDED` | 402 Payment Required |
| `ERR_QUANTITY_EXCEEDS_UNRELEASED` | 422 Unprocessable Entity |
| `ERR_SERIAL_BATCH_EXCEEDS_QUANTITY` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_MATERIAL_QUANTITY` | 422 Unprocessable Entity |
