# Rail Siding Track Agreements API — Product Requirements Document

## 1. Introduction

Rail-served industrial shippers live and die by the private track that connects their plant to the railroad's main line. The paperwork behind that connection — the industrial track agreement — is a long-lived commercial contract that allocates construction costs, pins engineering specifications, divides maintenance and inspection duties, prices switching service and car dwell, governs car storage on private track, apportions liability when something goes wrong, and ultimately dictates how the track is abandoned and removed when the relationship ends. Today these obligations are tracked in spreadsheets and filing cabinets, which makes renewal windows, inspection cadences, demurrage accruals, and indemnity caps easy to miss and hard to audit.

This document specifies an API that operationalizes the full lifecycle of a rail siding and industrial track agreement between a railroad and a shipper. It covers agreement drafting, countersignature, amendment, renewal, termination, abandonment, and removal verification; construction projects with specification approval and cost-share settlement; track segments, derail devices, and the safety inspection cycle; switching service orders and car demurrage; private-track car storage; and liability claims with fault apportionment against an aggregate cap. The intended readers are the engineers who will build the service and the operations staff who will run against it.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting operator and `X-User-Role` to specify their operational capacity. The system recognizes five distinct roles: `RailroadContractsManager`, `ShipperFacilityManager`, `RailroadEngineer`, `SafetyInspector`, and `RailroadServiceManager`. Failure to provide both headers, or presenting a role outside these five, results in an `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` error. Once the user context is well-formed, the caller's role must also be authorized for the specific operation; an attempt to perform an action outside of a role's designated operations is rejected with an `ERR_UNAUTHORIZED_ROLE` error.

For every one of the five roles — `RailroadContractsManager`, `ShipperFacilityManager`, `RailroadEngineer`, `SafetyInspector`, and `RailroadServiceManager` — the `X-User-ID` header is an opaque operator identifier that is not tied to any persisted entity; the server never compares it to any entity's `id`. There is, however, one domain-specific use of the identifier: party binding on the shipper side. Every agreement records a `shipper_user_id` value supplied at creation time, and operations that belong to the shipper side of the relationship (countersigning, accepting a renewal, filing an abandonment notice, requesting construction or service, installing devices, releasing stored cars, accepting or disputing a claim apportionment) require the caller's `X-User-ID` to equal the agreement's stored `shipper_user_id`; otherwise the request is rejected with `ERR_NOT_AGREEMENT_PARTY`. The server may also record the caller's identity for audit purposes — for example, every amendment carries `proposed_by_role` and `proposed_by_user_id` copied from the caller's headers at creation — but such recordings are never compared to an entity `id`. A related segregation-of-duties rule governs amendments: the party responding to a proposed amendment must not be the party that proposed it, and a violation is rejected with `ERR_SAME_PARTY_RESPONSE`.

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

Requests to a path (or with a method) the API does not define are rejected with a 404 status and an `ERR_INVALID_REQUEST` error body. An unexpected server failure returns a 500 status with an `ERR_INTERNAL` error body.

---

### 2.3. Pagination

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. A non-integer `limit` or `offset`, a `limit` outside the 1–100 range, or a negative `offset` is rejected with `ERR_INVALID_REQUEST`.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order, with ties broken by `id`.

Paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`. `has_more` is true exactly when `offset` + `limit` is less than `total_count`.

### 2.4. The Logical Clock and Read-Time State Sweeps

The server maintains a logical clock that governs every time-dependent rule in the system — renewal windows, agreement expiry, inspection overdue detection, provisional demurrage accrual, and provisional storage accrual. At startup, before any adjustment, the logical clock reads exactly `2026-08-01T00:00:00Z`, and the server must never fall back to wall-clock time. An administrative test-driving capability — setting the logical clock, available to all five roles — advances it to a supplied `to_iso8601` instant (ISO 8601 UTC); the supplied instant is normalized to UTC `Z` form with three fractional digits, and the response returns that normalized value as `current_utc`. Wherever this document says "current logical date", it means the UTC calendar date of the logical clock.

Two automatic state sweeps are anchored to the logical clock. The agreement expiry sweep moves an agreement in `ACTIVE` or `RENEWAL_OFFERED` to `EXPIRED` whenever the current logical date is later than the agreement's `term_end_date`; it is evaluated on every read of an agreement (single-resource reads and, row by row, list reads), on every clock adjustment, and at the start of every write operation that resolves an agreement — applied immediately after the agreement is loaded, before any further validation of the request — with one exception: releasing a car dwell loads the parent agreement without sweeping it. The inspection overdue sweep moves an inspection in `SCHEDULED` to `OVERDUE` whenever the current logical date is later than the inspection's `due_date`; it is likewise evaluated on every read of an inspection, on every clock adjustment, and at the start of result recording. Both sweeps are mutations like any other: each transitioned row has its `version` incremented and its `updated_at` refreshed.

### 2.5. Common Resource Properties

Every primary resource in the system — agreements, amendments, construction projects, track segments, safety inspections, derail devices, service orders, car dwells, storage placements, and liability claims — carries a standard set of system-managed fields:

- **`id` (string):** a unique, server-generated identifier for the resource, formatted as a UUID with no type prefix.
- **`created_at` (string):** an ISO 8601 timestamp in UTC with three fractional digits (e.g., `2026-08-14T10:30:00.123Z`) indicating when the resource was first created.
- **`updated_at` (string):** an ISO 8601 UTC timestamp with three fractional digits, refreshed on every change to the resource.
- **`version` (integer):** a system-managed integer that starts at 1 on creation and increments by exactly 1 on every mutation of the resource — including mutations caused by cascaded side effects from an operation on a different resource.

This version discipline is what makes cascades observable: if filing an abandonment notice force-releases three stored cars, each of those three placement rows also gains a `version` increment and a fresh `updated_at`, alongside the agreement's own increment.

### 2.6. Monetary Precision and Rounding Discipline

All monetary amounts in the system are integer cents; rates, caps, and charges are carried and returned as integer cent values. Where a calculation requires division, the rounding rule is fixed per calculation rather than left to the implementer:

- Cost-share computations on construction projects (estimated and final) and the raw shipper share on a liability claim are rounded half-up to 0 decimal places — whole cents — at the moment the share is computed.
- The storage daily rate is the agreement's monthly per-car rate divided by 30, rounded half-up to 2 decimal places; each car's final storage charge then multiplies that daily rate by the number of days charged and is rounded half-up to 0 decimal places. A segment's accrued storage total is the integer sum of already-rounded per-car charges — never a rounding of an unrounded sum.
- Demurrage performs its only division — chargeable minutes divided by the 1,440 minutes in a day — as a ceiling to whole days before any multiplication, so no fractional-cent rounding ever occurs in that calculation.

Date arithmetic throughout the system uses whole ISO calendar days unless stated otherwise; inspection scheduling and removal-penalty computations carry no time-of-day component.

Percentage fields (`shipper_cost_share_pct`, `shipper_indemnity_default_pct`, `shipper_share_pct`, `shipper_fault_pct`, and the amendment new-value percentage `new_shipper_cost_share_pct`) are numeric rather than integer-only: any value within the stated 0–100 range, including fractional values, is accepted and used as-is in the calculations above.

### 2.7. Optimistic Concurrency Control on Amendment Proposals

Exactly one write operation in the system is guarded by optimistic concurrency control: proposing an amendment to an agreement. The proposal request must carry `expected_agreement_version`, a non-optional field holding the agreement `version` the caller last observed. If that value does not equal the agreement's current `version` at write time — for instance, because another writer has since created an amendment of their own, which legitimately superseded the prior pending one and advanced the agreement's version — the proposal is rejected with `ERR_STALE_AGREEMENT_VERSION` (HTTP 412). This prevents a negotiator from building on an agreement state they have not observed. No other endpoint accepts or requires a version field; all other mutations proceed without an OCC check.

### 2.8. Cascading Consistency Across the Facility Hierarchy

The system maintains strict consistency across the agreement-to-facility hierarchy. When a parent resource undergoes a state transition that renders it non-operational — termination, abandonment, removal — dependent child resources are resolved automatically in a defined cascade, without requiring explicit client requests on each child. Cascades are chained: a single shipper action can move segments out of service, which in turn force-releases stored cars and cancels pending switching requests, which in turn recomputes segment ledgers. Every entity touched at any link of such a chain is mutated in the ordinary sense: its `status` or derived fields change, its `version` increments by 1, and its `updated_at` refreshes. Conversely, operations that look similar but are defined as non-cascading — taking a single segment out of service for maintenance possession, for example — leave orders and placements untouched, and this distinction is contractual.

### 2.9. Nested Resource Retrieval

The API enforces a strict, hierarchical validation protocol for requests whose paths contain resource identifiers. Identifiers are validated in left-to-right order, and the request is rejected immediately with the 404 error corresponding to the first identifier that does not resolve to an existing resource: `ERR_AGREEMENT_NOT_FOUND` for a missing agreement, `ERR_AMENDMENT_NOT_FOUND` for a missing amendment, `ERR_PROJECT_NOT_FOUND` for a missing construction project, `ERR_SEGMENT_NOT_FOUND` for a missing segment, `ERR_INSPECTION_NOT_FOUND` for a missing inspection, `ERR_DEVICE_NOT_FOUND` for a missing derail device, `ERR_SERVICE_ORDER_NOT_FOUND` for a missing service order, `ERR_CAR_DWELL_NOT_FOUND` for a missing car dwell, `ERR_STORAGE_PLACEMENT_NOT_FOUND` for a missing storage placement, and `ERR_CLAIM_NOT_FOUND` for a missing liability claim. Foreign keys supplied in request bodies — an `agreement_id` or `segment_id` on a creation payload — are checked for existence at the same stage, before any business rule is evaluated.

### 2.10. Precedence of Checks on Write Operations

When several validation rules could reject the same request, the order in which they fire is part of the contract — the first matching failure determines the error returned. Write operations evaluate, in order: first, presence and validity of the user context headers (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`); second, whether the caller's role is authorized for the endpoint (`ERR_UNAUTHORIZED_ROLE`); third, existence of path identifiers and body foreign keys (the 404 family, left to right); fourth, party ownership and segregation-of-duties (`ERR_NOT_AGREEMENT_PARTY`, `ERR_SAME_PARTY_RESPONSE`) — these checks evaluate against an already-loaded agreement, so the 404 for that agreement necessarily precedes them; fifth, request body shape and field-level validity — required fields present, enum members valid, dates well-ordered, percentages within range (`ERR_INVALID_REQUEST`); sixth, whether the target resource's own status permits the transition (the per-entity invalid-state errors such as `ERR_AGREEMENT_INVALID_STATE` or `ERR_ORDER_INVALID_STATE`); seventh, cross-entity state gates such as the requirement that a parent agreement be `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE`, `ERR_OPEN_CLAIMS_BLOCK_RENEWAL`); eighth, segment safety gates, with the in-service requirement checked before the suspension requirement (`ERR_SEGMENT_OUT_OF_SERVICE`, then `ERR_SEGMENT_SAFETY_SUSPENDED`); ninth, temporal rules (`ERR_RENEWAL_WINDOW_CLOSED`, `ERR_NOT_A_SERVICE_DAY`); tenth, uniqueness, overlap, and frequency rules (`ERR_CAR_ALREADY_SPOTTED`, `ERR_POSSESSION_OVERLAP`, `ERR_POSSESSION_BUFFER_CONFLICT`, `ERR_SWITCH_LIMIT_EXCEEDED`, `ERR_STORAGE_CAPACITY_EXCEEDED`); eleventh, cross-reference consistency between supplied foreign keys (`ERR_CROSS_REFERENCE_MISMATCH`); twelfth, money checks (`ERR_OVERPAYMENT`, `ERR_REFUND_EXCEEDS_PAID`); and thirteenth, the optimistic-concurrency version check (`ERR_STALE_AGREEMENT_VERSION`). Four pinned exceptions refine this list where an endpoint evaluates out of its strict order: on countersign, accept-renewal, and file-abandonment-notice the agreement's own status check (the sixth rule) fires before the party-binding check; on amendment respond the amendment's `PENDING` status check fires before the segregation-of-duties check; and on the car-dwell and storage-placement release endpoints the own-status check fires before the temporal validity of the supplied release instant is evaluated (`ERR_INVALID_RELEASE_TIME` for dwells, and the `released_date`-on-or-after-`placed_date` rule for placements, which reports `ERR_INVALID_REQUEST`).

## 3. Business Logic & Workflows

### 3.1. Drafting, Countersigning, and the Life of an Agreement

A `RailroadContractsManager` drafts the relationship by creating a **TrackAgreement**. The creation payload names the counterparty through `shipper_name` and `shipper_user_id` — the latter being the opaque identifier that later binds shipper-side actions to this agreement — and identifies the plant via `facility_name`. The commercial spine of the agreement is its term: `term_start_date` and `term_end_date`, where the end date must be strictly later than the start date (otherwise `ERR_INVALID_REQUEST`). Renewal mechanics are set at birth: `renewal_notice_days` (zero or greater) defines how many days before `term_end_date` the renewal window closes, and `renewal_term_months` (at least 1) defines the length added when a renewal is accepted.

The same creation payload carries the financial and operating parameters that later calculations consume: `shipper_cost_share_pct` (the default shipper percentage of construction cost, between 0 and 100 inclusive), `liability_cap_cents` (the aggregate cap on shipper liability, zero or greater), `shipper_indemnity_default_pct` (the default shipper fault percentage, 0–100), `free_time_hours` (free dwell hours before demurrage accrues on railroad-owned cars, zero or greater), `demurrage_base_rate_cents` and `demurrage_escalated_rate_cents` (per-chargeable-day rates for the early and late tiers, each an integer zero or greater), `storage_rate_per_car_month_cents` (the monthly private-track storage fee per car, an integer zero or greater), `inspection_cadence_days` (at least 1), `removal_period_days` (at least 1), `removal_penalty_per_day_cents` (zero or greater), `service_days_of_week` (a non-empty subset of `MON`, `TUE`, `WED`, `THU`, `FRI`, `SAT`, `SUN` on which switching service may be scheduled), and `max_switches_per_day` (at least 1). A new agreement is born in `DRAFT` status with `removal_penalty_cents` at 0 and both `abandonment_notice_date` and `removal_deadline_date` null.

Submission by a `RailroadContractsManager` moves the agreement from `DRAFT` to `PENDING_COUNTERSIGN`; attempting submission from any other status is rejected with `ERR_AGREEMENT_INVALID_STATE`. Countersigning is the shipper's act: a `ShipperFacilityManager` whose `X-User-ID` matches the agreement's `shipper_user_id` moves `PENDING_COUNTERSIGN` to `ACTIVE`. A countersign attempt by anyone else is rejected with `ERR_NOT_AGREEMENT_PARTY`, and from the wrong status with `ERR_AGREEMENT_INVALID_STATE`. Both transitions increment the agreement's `version` by 1. Only an `ACTIVE` agreement supports child creation — segments, projects, inspections, devices, service orders, car dwells, storage placements, claims, and amendments all require it, failing with `ERR_AGREEMENT_NOT_ACTIVE` otherwise.

Renewal is a two-step negotiation. A `RailroadContractsManager` may offer renewal only while the agreement is `ACTIVE`, only while no liability claim of the agreement sits in `FILED`, `APPORTIONED`, or `DISPUTED` status (an open claim rejects the offer with `ERR_OPEN_CLAIMS_BLOCK_RENEWAL`), and only while the current logical date is on or before the date `renewal_notice_days` days before `term_end_date` — past that closing date the offer is rejected with `ERR_RENEWAL_WINDOW_CLOSED`. A successful offer moves the agreement to `RENEWAL_OFFERED`. The shipper accepts through a `ShipperFacilityManager` party-bound call, subject to the same window check (`ERR_RENEWAL_WINDOW_CLOSED` applies to acceptance as well) and the `RENEWAL_OFFERED` status requirement; acceptance returns the agreement to `ACTIVE` and extends `term_end_date` by exactly `renewal_term_months` months, preserving the day of month — an agreement ending 2027-07-31 renewed for twelve months ends 2028-07-31 — and when the target month has fewer days than the day of month being carried over, the date clamps to the target month's last day.

Expiry needs no actor: per the sweep in §2.4, an agreement in `ACTIVE` or `RENEWAL_OFFERED` whose `term_end_date` is earlier than the current logical date becomes `EXPIRED` — a pending offer simply lapses unaccepted. Termination, by contrast, is deliberate: a `RailroadContractsManager` moves an `ACTIVE` agreement to `TERMINATED`; the request may optionally carry a `reason`, which is accepted but not persisted on the agreement. Termination cascades directly — every service order of the agreement still `REQUESTED` becomes `CANCELLED`, and every amendment still `PENDING` becomes `SUPERSEDED` — and bumps the agreement's `version`. Both `TERMINATED` and `EXPIRED` feed the abandonment workflow of §3.8; `CLOSED` is the agreement's terminal state.

### 3.2. Mid-Term Changes: The Amendment Protocol

Either commercial counterparty — a `RailroadContractsManager` or a party-bound `ShipperFacilityManager` — may propose an **Amendment** against an `ACTIVE` agreement. The proposal names an `amendment_type`, and the type pins exactly which new-value fields must be present, with any mismatch rejected as `ERR_INVALID_REQUEST`: `COST_SHARE` requires `new_shipper_cost_share_pct`; `LIABILITY_CAP` requires `new_liability_cap_cents`; `STORAGE_RATE` requires `new_storage_rate_per_car_month_cents`; `DEMURRAGE_RATES` requires both `new_demurrage_base_rate_cents` and `new_demurrage_escalated_rate_cents` together; `TERM` requires `new_term_end_date`. Fields not pinned by the chosen type must be absent (null). New cent values (`new_liability_cap_cents`, `new_storage_rate_per_car_month_cents`, and both demurrage rates) must be integers zero or greater; no date-ordering validation is applied to `new_term_end_date`, at proposal or at acceptance. The system records `proposed_by_role` and `proposed_by_user_id` from the caller's headers at creation, and the amendment is born `PENDING`.

Because only one negotiation can be live at a time, creating an amendment immediately moves any existing `PENDING` amendment on the same agreement to `SUPERSEDED`, and the creation itself advances the parent agreement's `version` by 1. That is precisely why proposal is the system's OCC-guarded write: per §2.7 the request must carry `expected_agreement_version` equal to the agreement's current `version`, and a stale value is rejected with `ERR_STALE_AGREEMENT_VERSION` (HTTP 412). The `agreement_id` of the new amendment is taken from the creation path, not the body.

Response belongs to the counter-party. A respond call carrying a `decision` of `ACCEPT` or `REJECT` is valid only while the amendment is `PENDING` (otherwise `ERR_AMENDMENT_INVALID_STATE`), and only when the caller's role differs from the recorded `proposed_by_role` — the same party answering its own proposal is rejected with `ERR_SAME_PARTY_RESPONSE`; per §2.10 the `PENDING` status check fires before the segregation-of-duties check. When the responder is a `ShipperFacilityManager`, the party check also applies: the caller's `X-User-ID` must equal the agreement's `shipper_user_id`, else `ERR_NOT_AGREEMENT_PARTY`. Acceptance additionally requires the parent agreement to be `ACTIVE` (otherwise `ERR_AGREEMENT_NOT_ACTIVE`); rejection carries no parent-status requirement and succeeds regardless of the agreement's status. Acceptance applies the amendment's new-value fields to the parent agreement — exactly the field set pinned by its `amendment_type` — and increments the agreement's `version` by 1; the amendment becomes `ACCEPTED`. Rejection simply moves the amendment to `REJECTED` with no change to the agreement. `ACCEPTED`, `REJECTED`, and `SUPERSEDED` are all terminal.

### 3.3. Track Construction: Specifications, Cost Sharing, and Settlement

Construction under an agreement is organized as a **ConstructionProject**, created by a party-bound `ShipperFacilityManager` while the parent agreement is `ACTIVE`. The creation payload carries the `agreement_id`, a `project_name`, and the `estimated_cost_cents` (zero or greater). The shipper's share percentage for the project, `shipper_share_pct`, may be omitted, in which case it defaults to the agreement's `shipper_cost_share_pct` as captured at project creation; either way it must lie between 0 and 100. A new project starts in `DRAFT` with `spec_revision_no` 0 and `amount_paid_cents` 0; `shipper_estimated_share_cents`, `actual_cost_cents`, `shipper_final_share_cents`, and `outstanding_share_cents` remain unset until their respective milestones.

Engineering approval is a revision loop. Submitting a specification — a party-bound `ShipperFacilityManager` (whose `X-User-ID` must match the agreement's `shipper_user_id`, else `ERR_NOT_AGREEMENT_PARTY`) supplying `rail_weight_lb_per_yard`, `tie_material` (`WOOD`, `CONCRETE`, or `STEEL`), and `ballast_depth_inches` — is allowed from `DRAFT` and from `SPEC_REJECTED` (any other status draws `ERR_PROJECT_INVALID_STATE`), and each submission overwrites the three spec fields and increments `spec_revision_no` by 1, landing the project in `SPEC_SUBMITTED`. A `RailroadEngineer` then either approves or rejects. Approval moves `SPEC_SUBMITTED` to `SPEC_APPROVED` and computes the estimated cost share: `shipper_estimated_share_cents` is `estimated_cost_cents` multiplied by `shipper_share_pct`, divided by 100, rounded half-up to whole cents — and this figure is pinned to the `spec_revision_no` current at approval. Rejection, which requires a `rejection_reason`, returns the project to `SPEC_REJECTED`; the shipper may then resubmit, and any previously approved estimate remains untouched until a new approval overwrites it.

When the work is done, a party-bound `ShipperFacilityManager` reports completion with `actual_cost_cents` (a caller whose identity does not match the agreement's `shipper_user_id` is rejected with `ERR_NOT_AGREEMENT_PARTY`), moving `SPEC_APPROVED` to `COMPLETED`. The final share is computed on the actual basis — `shipper_final_share_cents` is `actual_cost_cents` multiplied by `shipper_share_pct`, divided by 100, rounded half-up to whole cents — and `outstanding_share_cents` is set to the final share minus `amount_paid_cents`. The two variants of the same formula can diverge whenever actual cost differs from estimate: a project estimated at 500000 cents but completed at 450000 cents with a 40 percent share yields an estimate of 200000 and a final of 180000, and it is the final figure that settlement reconciles.

Settlement is a `RailroadContractsManager` function that records one `payment_cents` amount per call: a positive value is a payment, a negative value is a refund correction. Each call adds `payment_cents` to `amount_paid_cents` and recomputes `outstanding_share_cents` as the final share minus the running total, preserving the invariant that `amount_paid_cents` plus `outstanding_share_cents` always equals `shipper_final_share_cents`. The money checks fire in the order of §2.10: a positive payment exceeding the outstanding share is rejected with `ERR_OVERPAYMENT`, as is a payment of exactly zero; a refund whose magnitude exceeds what has actually been paid is rejected with `ERR_REFUND_EXCEEDS_PAID`. When a payment drives the outstanding share to exactly zero, the project automatically transitions from `COMPLETED` to `SETTLED` — the project's terminal state — within the same operation.

### 3.4. Segments, Derail Devices, and the Safety Inspection Cycle

A `RailroadEngineer` defines the physical plant as **TrackSegment** rows under an `ACTIVE` agreement, each with an `agreement_id`, a `segment_name`, a `length_feet` strictly greater than zero, and a `storage_capacity_cars` (zero or greater) bounding how many cars may be stored on it. Segments are born `IN_SERVICE` with `stored_car_count` 0, `accrued_storage_cents` 0, and `safety_suspended` false. An engineer may take a segment out of service for maintenance — `IN_SERVICE` to `OUT_OF_SERVICE`, permitted only from `IN_SERVICE` (else `ERR_SEGMENT_INVALID_STATE`) and only while the parent agreement is `ACTIVE` (else `ERR_AGREEMENT_NOT_ACTIVE`) — and later return it; taking a segment out of service this way is deliberately non-cascading: it neither cancels service orders nor releases stored cars. Returning a segment to service requires `OUT_OF_SERVICE` status (else `ERR_SEGMENT_INVALID_STATE`), an `ACTIVE` parent agreement (else `ERR_AGREEMENT_NOT_ACTIVE`), and a clear `safety_suspended` flag — a suspended segment refuses to return with `ERR_SEGMENT_SAFETY_SUSPENDED`. `safety_suspended` is a parallel boolean dimension on the segment, flipped only by inspection cascades, and never alters `status` by itself.

Derail and safety hardware is tracked as **DerailDevice** rows. A party-bound `ShipperFacilityManager` proposes a device on a segment, supplying `segment_id`, a `device_type` of `DERAIL`, `WHEEL_STOP`, or `BUMPING_POST`, and a `location_description`; the device starts `PROPOSED`. A `RailroadEngineer` approves it (`PROPOSED` to `APPROVED`), and the shipper marks it installed, moving `APPROVED` to `INSTALLED`; the mark-installed call is party-bound against the segment's agreement's `shipper_user_id` and takes no payload fields. Out-of-order transitions draw `ERR_DEVICE_INVALID_STATE`.

Independent oversight arrives through the **SafetyInspection**. A `SafetyInspector` schedules one with an `agreement_id`, a `segment_id`, and a `scheduled_date`; the segment must belong to the named agreement, else `ERR_CROSS_REFERENCE_MISMATCH`, and the agreement must be `ACTIVE`. The inspection's `due_date` is set equal to its `scheduled_date`, its `status` starts `SCHEDULED`, and per §2.4 it flips to `OVERDUE` once the current logical date passes the due date — an overdue inspection remains completable.

Recording a result requires the inspection to be in `SCHEDULED` or `OVERDUE` (otherwise `ERR_INSPECTION_INVALID_STATE`) and takes a `result` of `PASS` or `FAIL`, a `completed_date`, and an optional `cited_device_ids` list that defaults to empty. Every cited identifier must resolve to a derail device whose `segment_id` equals the inspection's own segment; any mismatch is rejected with `ERR_CROSS_REFERENCE_MISMATCH`. On a recorded result the inspection stores `completed_date`, `result`, and the cited list, and reaches its terminal state — `COMPLETED_PASS` for a passing result, `COMPLETED_FAIL` for a failing one — and then cascades. A `PASS` restores compliance: every cited device currently `NON_COMPLIANT` returns to `INSTALLED`, and if no device on that segment remains `NON_COMPLIANT`, the segment's `safety_suspended` clears to false. A `FAIL` does the mirror image: every cited device currently `INSTALLED` becomes `NON_COMPLIANT`, and if any device on the segment is now non-compliant the segment's `safety_suspended` sets to true — which, per §3.5 and §3.6, blocks new service orders and storage placements on that segment with `ERR_SEGMENT_SAFETY_SUSPENDED`. Either way, the cycle continues automatically: the system creates the next inspection for the same agreement and segment, scheduled for `completed_date` plus the agreement's `inspection_cadence_days` days, with its `due_date` equal to that scheduled date and status `SCHEDULED`.

### 3.5. Switching Service, Possessions, and Car Demurrage

Day-to-day railroad operations on the siding run through the **ServiceOrder**. A party-bound `ShipperFacilityManager` requests one under an `ACTIVE` agreement with an `agreement_id`, a `segment_id` that must belong to that agreement (else `ERR_CROSS_REFERENCE_MISMATCH`), an `order_type` of `SWITCHING` or `MAINTENANCE_POSSESSION`, a `service_date`, and a time window from `start_hour` (0–23) to `end_hour` (1–24, strictly greater than the start). Windows are half-open — an order occupying hours 8 to 11 conflicts with one starting at 10 but not with one starting at 11. The order is born `REQUESTED` with `cars_spotted` and `cars_pulled` unset (null) until completion.

Creation is gated by the segment's condition and by the operating rules. The segment must be `IN_SERVICE` (else `ERR_SEGMENT_OUT_OF_SERVICE`) and not safety-suspended (else `ERR_SEGMENT_SAFETY_SUSPENDED`) — in that order, per §2.10. A `SWITCHING` order may only be scheduled on a day of the week — derived from `service_date` in UTC — that appears in the agreement's `service_days_of_week`, otherwise `ERR_NOT_A_SERVICE_DAY`. Two `MAINTENANCE_POSSESSION` orders on the same segment and service date may not overlap under the half-open rule (touching endpoints are allowed), or the request fails with `ERR_POSSESSION_OVERLAP`. Switching and possessions are kept apart by a one-hour buffer in both directions: a `SWITCHING` window may not intersect any possession on the same segment and date expanded by one hour on each side, and symmetrically a new possession may not intersect existing switching windows so expanded — violations are rejected with `ERR_POSSESSION_BUFFER_CONFLICT`. Finally, the number of non-`CANCELLED` `SWITCHING` orders on a segment for a given `service_date` must stay below the agreement's `max_switches_per_day`; at the cap the request fails with `ERR_SWITCH_LIMIT_EXCEEDED`.

Execution is recorded by a `RailroadServiceManager`, who completes a `REQUESTED` order (any other status draws `ERR_ORDER_INVALID_STATE`) with the counts `cars_spotted` and `cars_pulled` (each zero or greater), moving it to `COMPLETED`. Orders are cancelled only by cascade — agreement termination, or the abandonment cascade of §3.8 — never by direct call.

Demurrage is tracked per car as a **CarDwell**. A `RailroadServiceManager` records a placement with an `agreement_id`, a `car_mark` (the car's initial and number, e.g. `RBOX1001`), a `car_ownership` of `RAILROAD` or `PRIVATE`, and the `placed_at` instant. At most one `SPOTTED` dwell may exist for a given agreement and car mark; a duplicate is rejected with `ERR_CAR_ALREADY_SPOTTED`. The dwell starts `SPOTTED` with `accrued_demurrage_cents` 0, and the provisional recomputation described below already applies at creation, so the creation response itself carries the provisional accrual as of the logical clock. While a dwell is `SPOTTED`, every read of it — single or list — recomputes its provisional charge against the logical clock; `dwell_minutes` at that point is the elapsed time from `placed_at` to the logical-clock now, expressed in whole minutes.

The demurrage charge itself is computed as follows. The effective end of the interval is the actual `released_at` for the final computation and the logical clock for the provisional one. Total elapsed time from `placed_at` to that effective end is truncated down to whole minutes. The free allowance is the agreement's `free_time_hours` converted to minutes, and it doubles for `PRIVATE` cars. Chargeable minutes are the total minutes minus the free minutes; if that difference is zero or negative — a car released exactly at the end of its free time included — no days are charged and the amount is zero. Otherwise the chargeable minutes are divided by the 1,440 minutes of a day and rounded up, so any partial day bills a full day. The first two chargeable days bill at `demurrage_base_rate_cents` each, and every day beyond the second bills at `demurrage_escalated_rate_cents`. Release — performed by a `RailroadServiceManager` with a `released_at` strictly later than `placed_at` (else `ERR_INVALID_RELEASE_TIME`), and only from `SPOTTED` (else `ERR_DWELL_INVALID_STATE`) — computes this final variant, sets `dwell_minutes`, `chargeable_days`, and `final_demurrage_cents`, freezes `accrued_demurrage_cents`, and moves the dwell to `RELEASED`, after which reads return the frozen values. Freezing means the provisional field keeps its last logical-clock-based value, recomputed one final time as of the clock at the moment of release while the dwell is still `SPOTTED`; it is not overwritten by the final charge, so after release `accrued_demurrage_cents` (the frozen clock-based accrual) and `final_demurrage_cents` (computed against the supplied `released_at`) can differ whenever `released_at` lies ahead of the logical clock.

### 3.6. Private-Track Car Storage

Cars parked on private track for storage are tracked as **StoragePlacement** rows. A party-bound `ShipperFacilityManager` places a car with a `segment_id`, a `car_mark`, and a `placed_date`, under an `ACTIVE` agreement whose segment is `IN_SERVICE` (else `ERR_SEGMENT_OUT_OF_SERVICE`) and not safety-suspended (else `ERR_SEGMENT_SAFETY_SUSPENDED`). Capacity is enforced against live inventory: if the number of `STORED` placements on the segment already equals its `storage_capacity_cars`, the placement is rejected with `ERR_STORAGE_CAPACITY_EXCEEDED`. A successful placement starts `STORED`, and the segment's `stored_car_count` increments by 1. While a placement is `STORED`, reads recompute its `accrued_storage_charge_cents` provisionally as of the current logical date; this recomputation already applies at creation, so the creation response carries the provisional accrual, while `days_charged` and `final_storage_charge_cents` stay unset until release.

The storage charge has a pinned rounding order. The daily rate is the agreement's `storage_rate_per_car_month_cents` divided by 30, rounded half-up to two decimal places. The days charged are the whole days from `placed_date` to the effective release date, with a floor of one day — even a same-day release bills one day. The per-car charge is the daily rate multiplied by the days charged, rounded half-up to whole cents. A segment's `accrued_storage_cents` is then the plain integer sum of the per-car final charges over that segment's placements in `RELEASED` or `FORCE_RELEASED` status; `STORED` placements contribute nothing to the segment aggregate, their provisional accrual being visible only on the placement itself. The alternative order — summing unrounded amounts and rounding once — is not permitted: at a monthly rate of 10012 cents with 3 days charged and 5 cars, the pinned order yields 5005 cents where sum-then-round would yield 5006.

Release is the shipper's act, party-bound, and only from `STORED` (else `ERR_PLACEMENT_INVALID_STATE`), with a `released_date` on or after `placed_date` (else `ERR_INVALID_REQUEST`). Release computes the days and final charge as above, sets `accrued_storage_charge_cents` to that final charge, moves the placement to `RELEASED`, decrements the segment's `stored_car_count` by 1 — restoring the invariant that the count equals the number of `STORED` placements — and recomputes the segment's `accrued_storage_cents` as the sum described above. A placement can also leave `STORED` without the shipper's call: the abandonment cascade of §3.8 force-releases it.

### 3.7. Liability Claims, Apportionment, and the Indemnity Cap

When an incident occurs, a `RailroadContractsManager` files a **LiabilityClaim** against an `ACTIVE` agreement, naming the `agreement_id`, the `claimant_name`, the `incident_date`, and the `claim_amount_cents`, which must be strictly positive (otherwise `ERR_INVALID_REQUEST`). The claim is born `FILED` with `shipper_fault_pct`, `shipper_liability_cents`, and `railroad_liability_cents` unset (null) until the first apportionment.

Apportionment is the railroad's act, valid from `FILED` and again from `DISPUTED` (from any other status, `ERR_CLAIM_INVALID_STATE`). The request may carry `shipper_fault_pct` between 0 and 100; when omitted, the agreement's `shipper_indemnity_default_pct` applies. The raw shipper share is `claim_amount_cents` multiplied by the fault percentage and divided by 100, rounded half-up to whole cents. The agreement's aggregate cap then constrains the allocation: the remaining headroom is `liability_cap_cents` minus the sum of `shipper_liability_cents` over this agreement's claims in `ACCEPTED` status only — claims still `FILED`, `APPORTIONED`, or `DISPUTED` are excluded from that sum, which means a claim being re-apportioned does not count its own prior amount against the cap. The allocated `shipper_liability_cents` is the smaller of the raw share and the remaining headroom, floored at zero — if accepted claims already consume or exceed the cap, the shipper allocation is 0 and the railroad bears the entire claim — and `railroad_liability_cents` is the remainder of the claim amount. Each apportionment recomputes both figures and moves the claim to `APPORTIONED`.

The shipper answers an apportionment with acceptance or dispute, both party-bound (else `ERR_NOT_AGREEMENT_PARTY`) and both valid only from `APPORTIONED` (else `ERR_CLAIM_INVALID_STATE`). Acceptance moves the claim to `ACCEPTED` — its terminal state — and locks `shipper_liability_cents`, which from then on counts toward the agreement's cap aggregate. Dispute, optionally carrying a `dispute_reason`, returns the claim to `DISPUTED`, from which the railroad may apportion again; the loop continues until the shipper accepts. Recall from §3.1 that any claim in `FILED`, `APPORTIONED`, or `DISPUTED` blocks a renewal offer on the agreement — the claims pipeline and the renewal pipeline are deliberately coupled.

### 3.8. Termination, Abandonment, and Track Removal

The end of the physical plant begins once an agreement has reached `TERMINATED` or `EXPIRED`. A party-bound `ShipperFacilityManager` files an abandonment notice carrying a `notice_date`; from any status other than `TERMINATED` or `EXPIRED` the filing is rejected with `ERR_AGREEMENT_INVALID_STATE`, and from the wrong shipper identity with `ERR_NOT_AGREEMENT_PARTY`. Filing records `abandonment_notice_date` as the supplied notice date, computes `removal_deadline_date` as that date plus the agreement's `removal_period_days` days, and moves the agreement to `ABANDONMENT_IN_PROGRESS` — and then the cascade fires, link by link.

At the first link, every segment of the agreement still `IN_SERVICE` moves to `OUT_OF_SERVICE`. Each segment's transition causes the second link: every storage placement on that segment still `STORED` becomes `FORCE_RELEASED` with its `released_date` set to the notice date and its `days_charged` and `final_storage_charge_cents` computed per the storage charge rules, and every service order on that segment still `REQUESTED` becomes `CANCELLED`. Each force-release causes the third link: the placement's segment recomputes `accrued_storage_cents` as the sum of final charges over `RELEASED` and `FORCE_RELEASED` placements, and `stored_car_count` as the count of placements still `STORED`. Every entity touched at every link gains a `version` increment per §2.5, and the agreement itself increments as well; a segment whose ledger values actually change in the third link is touched again there, so a grounded segment that had live placements gains two `version` increments from the filing — one for its own transition, one for the ledger recompute.

Closure belongs to a `RailroadEngineer`, who verifies removal with a `removal_verified_date` while the agreement is `ABANDONMENT_IN_PROGRESS` (else `ERR_AGREEMENT_INVALID_STATE`). Verification computes the late-removal penalty: the number of whole days by which the verified date falls after `removal_deadline_date`, floored at zero — verification exactly on the deadline accrues nothing — multiplied by `removal_penalty_per_day_cents`, and records the result in `removal_penalty_cents`. Every segment then `OUT_OF_SERVICE` moves to `REMOVED`, the segment's terminal state, and the agreement reaches `CLOSED`, its terminal state.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code. Operations that modify an existing resource — including all state transitions, sweeps applied during reads notwithstanding — return a `200 OK` status code, as do all reads.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/agreements` | Create a track agreement in DRAFT | RailroadContractsManager |
| GET | `/agreements` | List agreements (expiry sweep applied to each returned row) | All five roles |
| GET | `/agreements/{agreementId}` | Get one agreement (expiry sweep applied) | All five roles |
| POST | `/agreements/{agreementId}/submit` | Submit draft for countersignature (DRAFT → PENDING_COUNTERSIGN) | RailroadContractsManager |
| POST | `/agreements/{agreementId}/countersign` | Shipper countersigns (PENDING_COUNTERSIGN → ACTIVE); caller must be the agreement's shipper party | ShipperFacilityManager |
| POST | `/agreements/{agreementId}/renewal-offer` | Offer renewal (ACTIVE → RENEWAL_OFFERED); blocked by open claims or a closed renewal window | RailroadContractsManager |
| POST | `/agreements/{agreementId}/accept-renewal` | Shipper accepts renewal (RENEWAL_OFFERED → ACTIVE, term extended) | ShipperFacilityManager |
| POST | `/agreements/{agreementId}/terminate` | Terminate for cause (ACTIVE → TERMINATED); cancels requested orders and supersedes pending amendments | RailroadContractsManager |
| POST | `/agreements/{agreementId}/file-abandonment-notice` | File abandonment notice (TERMINATED/EXPIRED → ABANDONMENT_IN_PROGRESS); fires the segment/placement/ledger cascade | ShipperFacilityManager |
| POST | `/agreements/{agreementId}/verify-removal` | Verify track removal (ABANDONMENT_IN_PROGRESS → CLOSED); accrues late-removal penalty | RailroadEngineer |
| POST | `/agreements/{agreementId}/amendments` | Propose an amendment (OCC-guarded; supersedes any pending amendment on the agreement) | RailroadContractsManager, ShipperFacilityManager |
| GET | `/amendments` | List amendments, optionally filtered by `agreement_id` | All five roles |
| GET | `/amendments/{amendmentId}` | Get one amendment | All five roles |
| POST | `/amendments/{amendmentId}/respond` | Counter-party accepts or rejects a pending amendment (responder role must differ from proposer role) | RailroadContractsManager, ShipperFacilityManager |
| POST | `/construction-projects` | Create a construction project in DRAFT | ShipperFacilityManager |
| GET | `/construction-projects` | List construction projects, optionally filtered by `agreement_id` | All five roles |
| GET | `/construction-projects/{projectId}` | Get one construction project | All five roles |
| POST | `/construction-projects/{projectId}/submit-spec` | Submit or resubmit the track spec (DRAFT/SPEC_REJECTED → SPEC_SUBMITTED); bumps the spec revision | ShipperFacilityManager |
| POST | `/construction-projects/{projectId}/approve-spec` | Approve the pinned spec revision (SPEC_SUBMITTED → SPEC_APPROVED); computes the estimated cost share | RailroadEngineer |
| POST | `/construction-projects/{projectId}/reject-spec` | Reject the spec (SPEC_SUBMITTED → SPEC_REJECTED) | RailroadEngineer |
| POST | `/construction-projects/{projectId}/complete` | Report completion with actual cost (SPEC_APPROVED → COMPLETED); computes the final cost share | ShipperFacilityManager |
| POST | `/construction-projects/{projectId}/settle` | Record a cost-share payment (positive) or refund correction (negative); auto-settles when outstanding reaches exactly zero | RailroadContractsManager |
| POST | `/segments` | Define a track segment under an ACTIVE agreement | RailroadEngineer |
| GET | `/segments` | List segments, optionally filtered by `agreement_id` | All five roles |
| GET | `/segments/{segmentId}` | Get one segment | All five roles |
| POST | `/segments/{segmentId}/take-out-of-service` | Take a segment out of service for maintenance (IN_SERVICE → OUT_OF_SERVICE); does not cancel orders or release placements | RailroadEngineer |
| POST | `/segments/{segmentId}/return-to-service` | Return a segment to service (OUT_OF_SERVICE → IN_SERVICE); blocked while safety-suspended | RailroadEngineer |
| POST | `/inspections` | Schedule a safety inspection on a segment of an ACTIVE agreement | SafetyInspector |
| GET | `/inspections` | List inspections, optionally filtered by `agreement_id` and/or `segment_id` (overdue sweep applied) | All five roles |
| GET | `/inspections/{inspectionId}` | Get one inspection (overdue sweep applied) | All five roles |
| POST | `/inspections/{inspectionId}/record-result` | Record PASS/FAIL; cascades to cited devices and segment suspension; auto-schedules the next inspection | SafetyInspector |
| POST | `/derail-devices` | Propose a derail/safety device on a segment (PROPOSED) | ShipperFacilityManager |
| GET | `/derail-devices` | List derail devices, optionally filtered by `segment_id` | All five roles |
| GET | `/derail-devices/{deviceId}` | Get one derail device | All five roles |
| POST | `/derail-devices/{deviceId}/approve` | Approve installation (PROPOSED → APPROVED) | RailroadEngineer |
| POST | `/derail-devices/{deviceId}/mark-installed` | Mark device installed (APPROVED → INSTALLED) | ShipperFacilityManager |
| POST | `/service-orders` | Request a switching service or maintenance possession window; enforces service days, frequency cap, overlap, and buffer rules | ShipperFacilityManager |
| GET | `/service-orders` | List service orders, optionally filtered by `agreement_id`, `segment_id`, and/or `service_date` | All five roles |
| GET | `/service-orders/{orderId}` | Get one service order | All five roles |
| POST | `/service-orders/{orderId}/complete` | Record execution (REQUESTED → COMPLETED) | RailroadServiceManager |
| POST | `/car-dwells` | Record a car placement (SPOTTED); at most one spotted dwell per agreement and car mark | RailroadServiceManager |
| GET | `/car-dwells` | List car dwells, optionally filtered by `agreement_id` and/or `status`; provisional demurrage recomputed for spotted rows | All five roles |
| GET | `/car-dwells/{dwellId}` | Get one car dwell; provisional demurrage recomputed while spotted | All five roles |
| POST | `/car-dwells/{dwellId}/release` | Release a spotted car (SPOTTED → RELEASED); computes final demurrage | RailroadServiceManager |
| POST | `/storage-placements` | Place a car into private-track storage (STORED); enforces segment capacity | ShipperFacilityManager |
| GET | `/storage-placements` | List storage placements, optionally filtered by `segment_id` and/or `status`; provisional charges recomputed for stored rows | All five roles |
| GET | `/storage-placements/{placementId}` | Get one storage placement; provisional charge recomputed while stored | All five roles |
| POST | `/storage-placements/{placementId}/release` | Release a stored car (STORED → RELEASED); computes the final charge and updates the segment ledger | ShipperFacilityManager |
| POST | `/liability-claims` | File a liability claim against an ACTIVE agreement (FILED) | RailroadContractsManager |
| GET | `/liability-claims` | List liability claims, optionally filtered by `agreement_id` and/or `status` | All five roles |
| GET | `/liability-claims/{claimId}` | Get one liability claim | All five roles |
| POST | `/liability-claims/{claimId}/apportion` | Apportion fault (FILED/DISPUTED → APPORTIONED); percentage defaults to the agreement's indemnity default | RailroadContractsManager |
| POST | `/liability-claims/{claimId}/accept` | Shipper accepts the apportionment (APPORTIONED → ACCEPTED); locks the allocation into the cap aggregate | ShipperFacilityManager |
| POST | `/liability-claims/{claimId}/dispute` | Shipper disputes the apportionment (APPORTIONED → DISPUTED); re-apportionment loops back | ShipperFacilityManager |
| POST | `/_clock/set_current_utc` | Set the server's logical clock (ISO 8601 UTC); triggers expiry and overdue sweeps | All five roles |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_NOT_AGREEMENT_PARTY` | 403 Forbidden |
| `ERR_SAME_PARTY_RESPONSE` | 403 Forbidden |
| `ERR_AGREEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_AMENDMENT_NOT_FOUND` | 404 Not Found |
| `ERR_PROJECT_NOT_FOUND` | 404 Not Found |
| `ERR_SEGMENT_NOT_FOUND` | 404 Not Found |
| `ERR_INSPECTION_NOT_FOUND` | 404 Not Found |
| `ERR_DEVICE_NOT_FOUND` | 404 Not Found |
| `ERR_SERVICE_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_CAR_DWELL_NOT_FOUND` | 404 Not Found |
| `ERR_STORAGE_PLACEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_AGREEMENT_INVALID_STATE` | 409 Conflict |
| `ERR_AMENDMENT_INVALID_STATE` | 409 Conflict |
| `ERR_PROJECT_INVALID_STATE` | 409 Conflict |
| `ERR_INSPECTION_INVALID_STATE` | 409 Conflict |
| `ERR_DEVICE_INVALID_STATE` | 409 Conflict |
| `ERR_ORDER_INVALID_STATE` | 409 Conflict |
| `ERR_DWELL_INVALID_STATE` | 409 Conflict |
| `ERR_PLACEMENT_INVALID_STATE` | 409 Conflict |
| `ERR_CLAIM_INVALID_STATE` | 409 Conflict |
| `ERR_AGREEMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_OPEN_CLAIMS_BLOCK_RENEWAL` | 409 Conflict |
| `ERR_RENEWAL_WINDOW_CLOSED` | 409 Conflict |
| `ERR_SEGMENT_INVALID_STATE` | 409 Conflict |
| `ERR_SEGMENT_OUT_OF_SERVICE` | 409 Conflict |
| `ERR_SEGMENT_SAFETY_SUSPENDED` | 409 Conflict |
| `ERR_CAR_ALREADY_SPOTTED` | 409 Conflict |
| `ERR_NOT_A_SERVICE_DAY` | 409 Conflict |
| `ERR_SWITCH_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_POSSESSION_OVERLAP` | 409 Conflict |
| `ERR_POSSESSION_BUFFER_CONFLICT` | 409 Conflict |
| `ERR_STORAGE_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_CROSS_REFERENCE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_OVERPAYMENT` | 402 Payment Required |
| `ERR_REFUND_EXCEEDS_PAID` | 402 Payment Required |
| `ERR_INVALID_RELEASE_TIME` | 400 Bad Request |
| `ERR_STALE_AGREEMENT_VERSION` | 412 Precondition Failed |
| `ERR_INTERNAL` | 500 Internal Server Error |
