# Oversize / Overweight Permit API — Product Requirements Document

## 1. Introduction

State departments of transportation must let commercial carriers move loads that exceed the ordinary legal envelope — a wind-turbine blade that overhangs the trailer by several feet, a transformer that pushes a bridge to the edge of its rated capacity — while protecting the public infrastructure those loads travel over. This API is the system of record for that regulatory workflow. It governs the full life of an oversize/overweight permit: a carrier drafts an application describing the load's dimensions and weight and the exact route it intends to travel, the system classifies the load and prices it, engineers analyse every bridge on the route, escorts and pilot cars are booked, and — only when every structural, financial, and scheduling constraint is satisfied — an officer issues the permit and reserves capacity on the crossed structures.

The domain is deliberately interlocking. Issuing a single permit commits tonnage on shared bridges, encumbers escrow against a surety bond, and reserves pilot-car windows; completing or revoking that permit must unwind each of those commitments in the correct order. Superloads — the heaviest and largest class — follow a divergent path with mandatory engineering review and a posted bond. Enforcement officers cite violations in the field, which can suspend or revoke a live permit and cascade a bond forfeiture back onto the carrier's account. This document specifies every entity, state transition, calculation, and validation an implementation must honour so that the behaviour is fully determined by the requirements below.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. All resource paths are mounted at the server root.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares their operational capacity. If either header is missing, or `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes exactly five roles, spelled precisely as follows: `Carrier`, `PermitOfficer`, `BridgeEngineer`, `EnforcementOfficer`, and `DOTAdmin`. When a role is authenticated but not permitted to perform the requested operation — including a `Carrier` acting on a resource it does not own, or a `PermitOfficer` attempting to begin review on a superload, which only a `BridgeEngineer` may do — the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

Identity binds to ownership as follows. When `X-User-Role` is `Carrier`, `X-User-ID` is the `id` of the acting `Carrier`; ownership checks on any resource that references a carrier compare that resource's `carrier_id` to `X-User-ID`, and ownership checks on any child of a permit (route segments, escort assignments, bridge analyses, bonds) compare the owning `Permit`'s `carrier_id` to `X-User-ID`. When `X-User-Role` is `PermitOfficer`, `BridgeEngineer`, `EnforcementOfficer`, or `DOTAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit purposes but does not compare it to any entity's `id`.

The `Carrier` role owns applications and their route segments and escorts, submits and completes permits, accepts bridge conditions, and contests violations. A `PermitOfficer` reviews and issues standard (non-superload) permits. A `BridgeEngineer` performs bridge analysis and conducts superload review. An `EnforcementOfficer` cites and adjudicates violations. A `DOTAdmin` manages reference data — carriers, structures, pilot cars, travel restrictions, escrow deposits — and the logical clock. All roles may perform read (GET) operations across the system.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

List-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`. List endpoints additionally accept domain filters — for example permits may be filtered by `carrier_id` and `status`; route segments and bridge analyses by `permit_id` and `structure_id`; escort assignments by `permit_id` and `pilot_car_id`; bonds by `permit_id`; and violations by `permit_id`, `carrier_id`, and `status`.

### 2.4. Common Resource Properties and Identifiers

Every persisted resource carries a server-minted `id`, formatted as a UUID with no type prefix, and a `created_at` timestamp — an ISO 8601 UTC value with three fractional digits recorded when the resource is first created.

Most resources additionally carry two system-managed fields: `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, and `version`, an integer that begins at 1 on creation and increments by one on every mutation of that resource. These common fields are present on `Carrier`, `Permit`, `RouteSegment`, `Structure`, `BridgeAnalysis`, `PilotCar`, `EscortAssignment`, `Bond`, and `Violation`. The one exception is `TravelRestriction`, which is immutable after creation: it carries only `id` and `created_at`, and has neither an `updated_at` nor a `version` field.

When a derived field on a resource changes as a side effect of some operation — for instance a structure's `committed_tonnage` shifting because a permit was issued, or a carrier's `compliance_standing` recomputing after a violation is adjudicated — that counts as a mutation of the affected resource: its `updated_at` is refreshed and its `version` is incremented.

### 2.5. Numeric Precision, Money, and Tonnage

Monetary amounts are stored and returned as whole integer cents; field names ending in `_cents` are always integers. Wherever a calculation produces a fractional cent, the result is rounded using the round-half-up method to a whole cent. This applies to the permit fee, the bond amount, and each violation penalty. The bridge rating factor is the sole non-cent computed quantity: it is rounded half up to exactly four decimal places.

Tonnage values (`rated_capacity_tonnage`, `dead_load_tonnage`, `committed_tonnage`, `available_tonnage`, and a route segment's `load_tonnage`) are numbers and are not rounded to cents. Load classification comparisons operate on integer inches and integer pounds exactly as supplied; there is no tolerance band on any threshold.

### 2.6. Optimistic Concurrency Control on Permit Edits

Editing a permit's load fields is guarded by optimistic concurrency control. A request to edit a permit must carry `expected_permit_version`, and this field is required — it is not optional. The value must equal the target `Permit`'s current `version`. Because adding a route segment, resubmitting, or any prior edit advances the permit's `version`, a client that read the permit before one of those mutations holds a stale view; its edit is therefore rejected with `ERR_STALE_PERMIT_VERSION` (HTTP 412). This is a version-staleness guard rather than a state precondition: a second sequential edit made against an already-advanced version is deterministically refused even though the permit is still editable and the edit would otherwise have succeeded. This concurrency check applies only to the permit-edit operation; no other endpoint accepts or checks a version field.

### 2.7. Cascading Reservations and State Reconciliation

Permit issuance and its inverse events are the system's principal source of cascading side effects, and the reconciliations they trigger are immediate and consistent. When a permit is issued, each of its route segments moves from `PLANNED` to `RESERVED`; for any segment that crosses a structure, the segment's `load_tonnage` is added to that structure's `committed_tonnage`, and the structure's `available_tonnage` and `posture` are recomputed. For a superload, issuance also activates the bond and debits the carrier's escrow (see §2.9). Trip completion, permit expiry, and permit revocation each unwind these commitments: reserved segments release or complete, the crossed structures' `committed_tonnage` is reduced by the corresponding `load_tonnage`, and their `available_tonnage` and `posture` are recomputed. These automatic transitions occur without an explicit client request against the child resources; the server performs them as part of the driving operation, and each affected resource's `updated_at` and `version` advance accordingly.

### 2.8. Nested Resource and Reference Resolution

Requests carry resource identifiers both in the path and in the request body as foreign keys. The system resolves them left to right — carrier, permit, structure, pilot car, route segment, bridge analysis, escort assignment, violation — and rejects the request at the first identifier that does not resolve, returning the corresponding not-found error (`ERR_CARRIER_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_STRUCTURE_NOT_FOUND`, `ERR_PILOT_CAR_NOT_FOUND`, `ERR_ROUTE_SEGMENT_NOT_FOUND`, `ERR_BRIDGE_ANALYSIS_NOT_FOUND`, `ERR_ESCORT_ASSIGNMENT_NOT_FOUND`, or `ERR_VIOLATION_NOT_FOUND`, each HTTP 404). Existence is verified before any business rule is evaluated.

### 2.9. Escrow, Bonds, and Carrier Standing

Each carrier maintains a small internal ledger. `total_escrow_deposited_cents` is the lifetime sum of escrow deposits; it is an invariant baseline that never decreases. `escrow_balance_cents` is the currently unencumbered escrow available to back a bond. `active_bond_amount_cents` is the sum of `amount_cents` over the carrier's bonds whose status is `ACTIVE`, and it is the invariant partner of the escrow balance — when a bond activates, the escrow balance is debited and the active-bond total is credited by the bond amount; when a bond releases, the escrow balance is credited and the active-bond total is debited by the same amount. A bond forfeiture is the asymmetric case: the active-bond total is debited but the escrow is retained by the DOT and not refunded. `unpaid_fee_balance_cents` accumulates violation penalties as violations are upheld.

A carrier's `compliance_standing` is a computed enum recomputed on every violation uphold or dismiss. Counting the carrier's `UPHELD` violations: standing is `GOOD_STANDING` while that count is fewer than 3; `PROBATION` while the count is 3 or 4; and `SUSPENDED` once the count reaches 5 or more.

### 2.10. Validation Ordering and Precedence

When several checks apply to one operation, they are evaluated in a fixed precedence so the returned error is deterministic. The global order is: authentication of headers and known role (`ERR_UNAUTHENTICATED`); authorization including role permission and carrier ownership (`ERR_UNAUTHORIZED`); existence of every path id and body foreign key (the 404 family); request well-formedness — required fields present, enum values valid, and unknown fields rejected (`ERR_INVALID_REQUEST`); field-level shape constraints on dimensions and windows (`ERR_INVALID_DIMENSIONS`); the validity-window rule (`ERR_VALIDITY_WINDOW_INVALID`); the permit-edit version check (`ERR_STALE_PERMIT_VERSION`); the state-machine precondition that the target is in a state from which the transition is defined (`ERR_INVALID_PERMIT_STATE`, `ERR_INVALID_ANALYSIS_STATE`, `ERR_INVALID_ESCORT_STATE`, or `ERR_INVALID_VIOLATION_STATE` as appropriate); and finally the domain-specific business rules, whose relative ordering is stated within the workflow narratives of §3. Field-shape validation covers: every dimension and weight strictly positive; both overhang values at least 0; `num_axles` at least 2; a route segment's `to_milepost` strictly greater than its `from_milepost`; a crossing's `planned_cross_end_utc` strictly after its `planned_cross_start_utc`; and an escort's `window_end_utc` strictly after its `window_start_utc` — any violation yields `ERR_INVALID_DIMENSIONS` (HTTP 422). Separately, `valid_from` must be strictly before `valid_until`, or the request is rejected with `ERR_VALIDITY_WINDOW_INVALID` (HTTP 422).

## 3. Business Logic & Workflows

### 3.1. Carriers, Escrow, and Reference Data

The registry is seeded by a `DOTAdmin`. Registering a carrier records its `legal_name` and `usdot_number`, the latter being unique across all carriers. A newly registered carrier starts with its lifetime deposit total, escrow balance, active-bond total, and unpaid-fee balance all at zero and its `compliance_standing` at `GOOD_STANDING`. To fund future superload bonds, an administrator records an escrow deposit of `amount_cents` against a carrier, which increases both `escrow_balance_cents` and `total_escrow_deposited_cents` by that amount.

An administrator also maintains the structures, pilot cars, and travel restrictions that permits reference. A structure is created with its `name`, the `highway_id` it carries, its `milepost`, its `rated_capacity_tonnage` (which must be positive), and its `dead_load_tonnage` (at least 0). On creation its `committed_tonnage` is 0 and its `available_tonnage` equals its rated capacity. A structure's `posture` is a computed enum reflecting how much live-load capacity remains: it is `OPEN` when the ratio of `available_tonnage` to `rated_capacity_tonnage` is at least 0.5; `RESTRICTED` when that ratio is greater than 0 but less than 0.5; and `CLOSED` when `available_tonnage` is at most 0.

A pilot car is registered with its `company_name` and a unique `cert_number`; its `status` may be supplied and is one of `AVAILABLE` (the default, eligible for confirmation) or `OUT_OF_SERVICE`. A travel restriction records a `restriction_type` of `CURFEW` or `HOLIDAY`, a window bounded by `start_utc` and `end_utc` (the end strictly after the start, both inclusive when tested against crossings), and an `applies_to_classification` naming which loads it blocks — either `ALL` or a specific classification value among `OVERSIZE`, `OVERWEIGHT`, `OVERSIZE_OVERWEIGHT`, or `SUPERLOAD`.

### 3.2. Drafting a Permit Application

A `Carrier` initiates an application, which is created in the `DRAFT` state with `version` 1. The application declares the applicant via `carrier_id`, the `permit_type` (either `SINGLE_TRIP` or `ANNUAL`), the load geometry — `length_in`, `width_in`, `height_in`, and the optional `front_overhang_in` and `rear_overhang_in` (each defaulting to 0) — the `gross_weight_lbs`, the `num_axles`, and the requested validity window `valid_from` to `valid_until`. All lengths, the height, the width, and the weight must be strictly positive, each overhang at least 0, and the axle count at least 2; the requested `valid_until` must be strictly after `valid_from`.

While the permit sits in `DRAFT` or `RETURNED_FOR_CORRECTION`, the carrier may revise the load fields. Such an edit accepts a new `permit_type`, `length_in`, `width_in`, `height_in`, `front_overhang_in`, `rear_overhang_in`, `gross_weight_lbs`, `num_axles`, `valid_from`, or `valid_until`, and it must carry the `expected_permit_version` described in §2.6; a successful edit increments the permit's `version`. Attempting to edit from any other state is refused with `ERR_INVALID_PERMIT_STATE`.

Building the route is done one segment at a time while the permit is `DRAFT` or `RETURNED_FOR_CORRECTION`. Each `RouteSegment` supplies a 1-based `sequence_index` (at least 1), the `highway_id` it travels, and its `from_milepost` and `to_milepost` (the latter strictly greater than the former, both at least 0). A segment may name the `structure_id` of a bridge it crosses; when it does, the crossing must also carry `planned_cross_start_utc` and, if the end is supplied, `planned_cross_end_utc` strictly after the start. On creation the segment's `miles` is computed as `to_milepost` minus `from_milepost`, its `load_tonnage` is computed as the owning permit's `gross_weight_lbs` divided by 2000 (tons), and its `reservation_status` begins at `PLANNED`; adding a segment increments the owning permit's `version`. Adding a segment whose `to_milepost` does not exceed its `from_milepost`, or whose crossing end does not follow its start, is rejected with `ERR_INVALID_DIMENSIONS`.

The carrier also arranges escorts ahead of review. Creating an `EscortAssignment` names the `pilot_car_id`, the `role` it will serve (`FRONT`, `REAR`, or `POLICE`), and the duty window `window_start_utc` to `window_end_utc`, with the end strictly after the start. A new assignment starts in `PENDING`.

### 3.3. Submission: Classification, Fee, Escort, and Bond

Submitting an application — whether the first submission from `DRAFT` or a resubmission from `RETURNED_FOR_CORRECTION` after corrections — is a carrier action that moves the permit to `SUBMITTED` and recomputes its derived attributes. Several preconditions guard submission, evaluated in this order: the carrier's `compliance_standing` must not be `SUSPENDED`, or the request is rejected with `ERR_CARRIER_SUSPENDED`; the permit must have at least one route segment, or `ERR_ROUTE_EMPTY`; the load must not be an `ANNUAL` superload, or `ERR_ANNUAL_SUPERLOAD_FORBIDDEN`; and the carrier's `unpaid_fee_balance_cents` must be exactly 0, or `ERR_UNPAID_FEES`. The acting carrier must own the permit, and submission must be a defined transition from the current state or it is refused with `ERR_INVALID_PERMIT_STATE`.

On a successful submission the system computes, in order, the load's `classification`, the `requires_superload_review` flag, the `required_escort_count`, and the `fee_cents`; it creates a `BridgeAnalysis` in `REQUESTED` status for each route segment that names a structure; and, for a superload, it creates a `Bond` in `DRAFT` status. On a resubmission from `RETURNED_FOR_CORRECTION`, the classification, escort count, and fee are recomputed, and any missing bridge analysis rows for structures now on the route are created while existing `REQUESTED` rows are kept.

**Classification.** The `classification` is one of `LEGAL`, `OVERSIZE`, `OVERWEIGHT`, `OVERSIZE_OVERWEIGHT`, or `SUPERLOAD`, derived from the load's own dimensions and weight with no cross-entity input. The load is *oversize* if its `width_in` exceeds 102 inches, or its `height_in` exceeds 162 inches, or its `length_in` exceeds 1020 inches, or the greater of its front and rear overhang exceeds 72 inches. It is *overweight* if its `gross_weight_lbs` exceeds 80000 pounds. It is a *superload* if its `width_in` is at least 192 inches, or its `height_in` is at least 204 inches, or its `length_in` is at least 1560 inches, or its `gross_weight_lbs` is at least 200000 pounds — so a load of exactly 200000 pounds is a superload while 199999 pounds is not. The classification is chosen by priority: if the superload test holds the classification is `SUPERLOAD`; otherwise if the load is both oversize and overweight it is `OVERSIZE_OVERWEIGHT`; otherwise if only oversize it is `OVERSIZE`; otherwise if only overweight it is `OVERWEIGHT`; otherwise `LEGAL`. The `requires_superload_review` flag is true exactly when the classification is `SUPERLOAD`, and it routes review to a `BridgeEngineer`.

**Escort requirement.** The `required_escort_count` is assembled from four components. A width component is 0 when `width_in` is at most 120 inches, 1 when it is at most 168 inches, and 2 otherwise. A length component is 0 when `length_in` is at most 960 inches, 1 when it is at most 1440 inches, and 2 otherwise. A height (pole-car) component is 1 when `height_in` exceeds 168 inches and 0 otherwise. A police component is 1 when `width_in` exceeds 192 inches or `gross_weight_lbs` is at least 200000 pounds, and 0 otherwise. The required escort count is the greater of the width and length components, plus the height component, plus the police component.

**Fee.** The `fee_cents` depends on the `permit_type`. Three surcharge terms are computed first. The oversize surcharge is 3000 cents when the classification is `OVERSIZE`, `OVERSIZE_OVERWEIGHT`, or `SUPERLOAD`, and 0 otherwise. The overweight surcharge applies only when `gross_weight_lbs` exceeds 80000 pounds: take the amount by which the gross weight exceeds 80000 pounds, divide by 1000, round that quotient up to the next whole number, and multiply by 1000 cents per thousand pounds; when the gross weight does not exceed 80000 pounds the overweight surcharge is 0. The superload surcharge is 50000 cents when the classification is `SUPERLOAD` and 0 otherwise. For a `SINGLE_TRIP` permit, the fee is a base of 1500 cents, plus a mileage total, plus all three surcharges; the mileage total is computed by taking each route segment's `miles` multiplied by 25 cents per mile, rounding that per-segment product half up to whole cents first, and then summing the rounded per-segment amounts (segments taken in ascending `sequence_index` order) — the per-segment rounding happens before summation, never after. For an `ANNUAL` permit, the fee is a flat base of 40000 cents plus the oversize and overweight surcharges only, with no mileage term and no superload surcharge (an annual superload is disallowed at submission).

**Bond.** For a superload, the `Bond` created at submission has its `amount_cents` computed as a base of 5000000 cents plus, for the amount by which `gross_weight_lbs` exceeds 200000 pounds divided by 1000 and rounded up to the next whole number, 100000 cents per each such thousand pounds.

### 3.4. Bridge Analysis and Structural Clearance

Each `BridgeAnalysis` ties a `permit_id` to the `structure_id` it examines and begins life in `REQUESTED`. A `BridgeEngineer` reviews it, supplying the rating `method` — either `LFR` (Load Factor Rating) or `LRFR` (Load and Resistance Factor Rating). Review is permitted only while the owning permit is in `UNDER_STANDARD_REVIEW` or `UNDER_SUPERLOAD_REVIEW`; from any other analysis status the review is refused with `ERR_INVALID_ANALYSIS_STATE`.

The review computes the `rating_factor` and records the chosen `method`. First the live-load tonnage is the owning permit's `gross_weight_lbs` divided by 2000. The `rating_factor` is then the structure's `rated_capacity_tonnage` minus the product of a dead-load factor and the structure's `dead_load_tonnage`, all divided by the product of a live-load factor and the live-load tonnage, rounded half up to four decimal places. The two factors depend on the method: `LFR` uses a dead-load factor of 1.30 and a live-load factor of 2.17, while `LRFR` uses a dead-load factor of 1.25 and a live-load factor of 1.75 — so the same structure and load yield a different rating factor under each method. The resulting factor branches the analysis: a factor of at least 1.00 clears it, moving the status to `CLEARED`; a factor of at least 0.90 but below 1.00 makes it `CONDITIONAL` and records a `conditions_note` describing the restriction (for example reduced speed or single-lane crossing); a factor below 0.90 rejects it, moving the status to `REJECTED`, and the route is infeasible until it is re-routed or edited.

When an analysis is `CONDITIONAL`, the owning carrier may accept the conditions, which advances the analysis to `CLEARED` so that it counts as cleared for approval. Accepting conditions requires the acting carrier to own the owning permit. An analysis becomes `SUPERSEDED` automatically when its owning permit is revoked or the trip completes (from `REQUESTED`), or when the permit is revoked (from `CONDITIONAL`).

### 3.5. Escort Confirmation and Pilot-Car Scheduling

Before a permit can be approved, its escorts must be booked. Confirming a `PENDING` escort assignment is a carrier action requiring ownership of the owning permit and moves the assignment to `CONFIRMED`. Two further conditions guard confirmation: the referenced pilot car's `status` must be `AVAILABLE`, or the request is rejected with `ERR_PILOT_CAR_UNAVAILABLE`; and no other `CONFIRMED` assignment for the same `pilot_car_id` may overlap the half-open window from `window_start_utc` up to but not including `window_end_utc`, or the request is rejected with `ERR_PILOT_CAR_DOUBLE_BOOKED` — because the interval is half-open, two back-to-back windows that merely touch at an endpoint do not conflict. Confirming from a status where confirmation is undefined yields `ERR_INVALID_ESCORT_STATE`.

An escort assignment may be cancelled by the owning carrier. A `PENDING` assignment cancels unconditionally to `CANCELLED`. A `CONFIRMED` assignment may also be cancelled to `CANCELLED`, freeing the pilot car for its window, but only while the owning permit is not yet `ISSUED`; once the permit is issued its confirmed escorts are locked. Cancelling from a status where cancellation is undefined yields `ERR_INVALID_ESCORT_STATE`. When the trip completes, every `CONFIRMED` escort assignment on the permit is moved automatically to `COMPLETED`.

### 3.6. Review, Approval, and Issuance

Review begins when an officer picks up a `SUBMITTED` permit. The fork is driven by `requires_superload_review`: a standard load is taken up by a `PermitOfficer` and moves to `UNDER_STANDARD_REVIEW`, whereas a superload is taken up by a `BridgeEngineer` and moves to `UNDER_SUPERLOAD_REVIEW`, a path on which an active bond will be mandatory before issuance. A reviewer may return the permit for correction — optionally recording a `reason` — sending it to `RETURNED_FOR_CORRECTION`, from which the carrier revises and resubmits. A reviewer may also reject the permit outright — again optionally recording a `reason` — moving it to the terminal `REJECTED` state.

Approval is a reviewer action moving the permit from its review state to `APPROVED`, and it enforces a sequence of safety checks. First, no bridge analysis for the permit may be `REJECTED`; if one is, approval is refused with `ERR_BRIDGE_REJECTED`. Next, every bridge analysis must be `CLEARED` — none may still be `REQUESTED` or `CONDITIONAL` (that is, pending) — or approval is refused with `ERR_BRIDGE_ANALYSIS_INCOMPLETE`. Then the count of `CONFIRMED` escort assignments must be at least the permit's `required_escort_count`, or approval is refused with `ERR_ESCORT_REQUIREMENT_UNMET`. For a superload approved out of `UNDER_SUPERLOAD_REVIEW`, a `DRAFT` bond must also exist for the permit. Approval from a state where it is undefined yields `ERR_INVALID_PERMIT_STATE`.

Issuance is a `PermitOfficer` action that moves an `APPROVED` permit to `ISSUED` and commits all of its downstream reservations. Issuance re-verifies that no bridge analysis is `REJECTED` (`ERR_BRIDGE_REJECTED`) and that every bridge analysis is `CLEARED` (`ERR_BRIDGE_ANALYSIS_INCOMPLETE`). It also requires that `valid_until` is strictly after the current clock and `valid_from` is strictly before `valid_until`. Then, for each route segment that crosses a structure, the checks proceed in this order: the structure's `posture` must not be `CLOSED`, or issuance fails with `ERR_STRUCTURE_CLOSED`; the structure's `available_tonnage` must be at least the segment's `load_tonnage`, or `ERR_STRUCTURE_CAPACITY_EXCEEDED`; and no other `RESERVED` route segment on the same structure may lie within 30 minutes of this segment's crossing window `[planned_cross_start_utc, planned_cross_end_utc]` (the interval closed and extended by the 30-minute clearance buffer on each side), or `ERR_STRUCTURE_WINDOW_CONFLICT`. Additionally, no route segment's crossing window may intersect a travel-restriction window applicable to the permit's `classification` (a restriction whose `applies_to_classification` is `ALL` or matches the classification), or issuance fails with `ERR_TRAVEL_TIME_RESTRICTED`. Finally, for a superload, a `DRAFT` bond must exist and the carrier's `escrow_balance_cents` must be at least the bond's `amount_cents`, or issuance fails with `ERR_INSUFFICIENT_ESCROW`.

Upon issuance the permit's `issued_at` is set to the current clock and its validity window is fixed. Each route segment moves from `PLANNED` to `RESERVED`; for a crossing segment, its `load_tonnage` is added to the structure's `committed_tonnage` and that structure's `available_tonnage` and `posture` are recomputed. For a superload, the bond moves from `DRAFT` to `ACTIVE`: the carrier's `escrow_balance_cents` is reduced by the bond `amount_cents`, the carrier's `active_bond_amount_cents` is increased by the same amount, and the carrier's `compliance_standing` is recomputed.

### 3.7. Trip Completion, Expiry, and Travel Timing

A carrier completes the trip on an `ISSUED` permit, provided the carrier owns it and the current clock is at or before `valid_until`; the permit moves to the terminal `COMPLETED` state. Completion releases the committed resources: each `RESERVED` route segment moves to `COMPLETED` and its `load_tonnage` is subtracted from the crossed structure's `committed_tonnage` (with `available_tonnage` and `posture` recomputed); each `CONFIRMED` escort assignment moves to `COMPLETED`; and if a bond is `ACTIVE` it moves to `RELEASED`, crediting the carrier's `escrow_balance_cents` by the bond `amount_cents` and debiting `active_bond_amount_cents` by the same amount, conserving the escrow.

The logical clock underpins expiry. An administrator-only clock capability sets the current instant to a supplied `to_iso8601` value; the default at startup is 2026-03-01T00:00:00Z, and the clock never falls back to wall-clock time. When the clock is advanced past an issued permit's `valid_until`, that permit moves automatically to the terminal `EXPIRED` state: each `RESERVED` route segment releases (subtracting its `load_tonnage` from the crossed structure's `committed_tonnage`, with recomputation), and any `ACTIVE` bond moves to `RELEASED`, crediting `escrow_balance_cents` and debiting `active_bond_amount_cents` by the bond `amount_cents`. Because issuance forbids any crossing window that intersects an applicable travel restriction, curfew and holiday windows are enforced at the moment of issuance rather than during travel.

### 3.8. Enforcement: Violations, Suspension, and Revocation

An `EnforcementOfficer` cites a violation against a permit, supplying the `permit_id`, the `violation_type` (`OVER_DIMENSION`, `OFF_ROUTE`, `OFF_SCHEDULE`, `NO_ESCORT`, or `EXPIRED_PERMIT`), and the `severity` (`MINOR`, `MAJOR`, or `CRITICAL`). The violation is created in `OPEN` status, its `carrier_id` is copied from the cited permit, and its `penalty_cents` is computed at creation. The penalty begins from a base that depends on the violation type — 100000 cents for `OVER_DIMENSION`, 150000 for `OFF_ROUTE`, 75000 for `OFF_SCHEDULE`, 200000 for `NO_ESCORT`, and 50000 for `EXPIRED_PERMIT` — multiplied by a severity multiplier of 1 for `MINOR`, 2 for `MAJOR`, or 3 for `CRITICAL`, and then by a repeat multiplier. The repeat multiplier is 1 plus 0.5 times the number of the carrier's violations already in `UPHELD` status, counted in ascending `created_at` order as of the instant of creation; the final product is rounded half up to whole cents. If the severity is `MAJOR` or `CRITICAL` and the cited permit is `ISSUED`, creating the violation immediately moves that permit to `SUSPENDED`, freezing it so that no completion is allowed until the violation is dismissed or the permit is revoked.

The carrier may contest an `OPEN` violation it is cited under, moving it to `CONTESTED`. An `EnforcementOfficer` adjudicates a violation that is `OPEN` or `CONTESTED`, either upholding or dismissing it; adjudicating from any other status yields `ERR_INVALID_VIOLATION_STATE`. Upholding moves the violation to `UPHELD`, adds its `penalty_cents` to the carrier's `unpaid_fee_balance_cents`, and recomputes the carrier's `compliance_standing`; if the severity is `CRITICAL` and the cited permit is currently `SUSPENDED`, the permit moves to the terminal `REVOKED` state. Dismissing moves the violation to `DISMISSED`; if the cited permit is `SUSPENDED` and no other non-`DISMISSED` violation remains for that permit, the permit is reinstated from `SUSPENDED` back to `ISSUED`.

Revocation triggered by a upheld critical violation fires the full unwind cascade: each `RESERVED` route segment moves to `RELEASED` and its `load_tonnage` is subtracted from the crossed structure's `committed_tonnage` (with `available_tonnage` and `posture` recomputed), and if a bond is `ACTIVE` it moves to `FORFEITED` — the carrier's `active_bond_amount_cents` is reduced by the bond `amount_cents`, but the escrow is retained by the DOT and is not refunded, which is the one case where escrow does not return to `escrow_balance_cents`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource or add a new resource to a collection return a `201 Created` status code. Operations that modify an existing resource — including all state-transition actions and escrow deposits — return a `200 OK` status code. To reconstruct the request body, response body, and side effects of any endpoint, refer to the workflow narratives in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/carriers` | Register a carrier | DOTAdmin |
| GET | `/carriers/{id}` | Read a carrier (escrow, bond, standing) | Carrier, PermitOfficer, BridgeEngineer, EnforcementOfficer, DOTAdmin |
| POST | `/carriers/{id}/escrow-deposits` | Deposit escrow for a carrier | DOTAdmin |
| POST | `/structures` | Create a bridge/structure | DOTAdmin |
| GET | `/structures/{id}` | Read a structure (tonnage, posture) | Carrier, PermitOfficer, BridgeEngineer, EnforcementOfficer, DOTAdmin |
| POST | `/pilot-cars` | Register a pilot car | DOTAdmin |
| GET | `/pilot-cars/{id}` | Read a pilot car | Carrier, PermitOfficer, BridgeEngineer, EnforcementOfficer, DOTAdmin |
| POST | `/travel-restrictions` | Create a time-of-travel restriction window | DOTAdmin |
| POST | `/permits` | Create a permit application (DRAFT) | Carrier |
| GET | `/permits/{id}` | Read a permit | Carrier, PermitOfficer, BridgeEngineer, EnforcementOfficer, DOTAdmin |
| GET | `/permits` | List permits (filter by carrier, status) | Carrier, PermitOfficer, BridgeEngineer, EnforcementOfficer, DOTAdmin |
| PATCH | `/permits/{id}` | Edit load fields while DRAFT/RETURNED_FOR_CORRECTION (OCC-guarded) | Carrier |
| POST | `/permits/{id}/route-segments` | Add a route segment while DRAFT/RETURNED_FOR_CORRECTION | Carrier |
| GET | `/route-segments` | List route segments (filter by permit, structure) | Carrier, PermitOfficer, BridgeEngineer, EnforcementOfficer, DOTAdmin |
| GET | `/route-segments/{id}` | Read a route segment | Carrier, PermitOfficer, BridgeEngineer, EnforcementOfficer, DOTAdmin |
| POST | `/permits/{id}/escort-assignments` | Add an escort assignment (PENDING) | Carrier |
| GET | `/escort-assignments` | List escort assignments (filter by permit, pilot car) | Carrier, PermitOfficer, BridgeEngineer, EnforcementOfficer, DOTAdmin |
| GET | `/escort-assignments/{id}` | Read an escort assignment | Carrier, PermitOfficer, BridgeEngineer, EnforcementOfficer, DOTAdmin |
| POST | `/escort-assignments/{id}/confirm` | Confirm an escort (books the pilot car) | Carrier |
| POST | `/escort-assignments/{id}/cancel` | Cancel an escort assignment | Carrier |
| POST | `/permits/{id}/submit` | Submit or resubmit (classify, price, spawn analyses/bond) | Carrier |
| POST | `/permits/{id}/begin-review` | Start review (standard vs superload fork) | PermitOfficer, BridgeEngineer |
| POST | `/permits/{id}/return` | Return a permit for correction | PermitOfficer, BridgeEngineer |
| POST | `/permits/{id}/approve` | Approve a permit | PermitOfficer, BridgeEngineer |
| POST | `/permits/{id}/reject` | Reject a permit (terminal) | PermitOfficer, BridgeEngineer |
| POST | `/permits/{id}/issue` | Issue an approved permit (reserve, activate bond) | PermitOfficer |
| POST | `/permits/{id}/complete` | Mark the trip completed | Carrier |
| GET | `/bridge-analyses` | List bridge analyses (filter by permit, structure) | Carrier, PermitOfficer, BridgeEngineer, EnforcementOfficer, DOTAdmin |
| GET | `/bridge-analyses/{id}` | Read a bridge analysis | Carrier, PermitOfficer, BridgeEngineer, EnforcementOfficer, DOTAdmin |
| POST | `/bridge-analyses/{id}/review` | Review a bridge analysis (compute rating, branch) | BridgeEngineer |
| POST | `/bridge-analyses/{id}/accept-conditions` | Accept CONDITIONAL restrictions (→ CLEARED) | Carrier |
| GET | `/bonds` | List bonds (filter by permit) | Carrier, PermitOfficer, BridgeEngineer, EnforcementOfficer, DOTAdmin |
| GET | `/bonds/{id}` | Read a bond | Carrier, PermitOfficer, BridgeEngineer, EnforcementOfficer, DOTAdmin |
| POST | `/violations` | Cite a violation against a permit | EnforcementOfficer |
| GET | `/violations/{id}` | Read a violation | Carrier, PermitOfficer, BridgeEngineer, EnforcementOfficer, DOTAdmin |
| GET | `/violations` | List violations (filter by permit, carrier, status) | Carrier, PermitOfficer, BridgeEngineer, EnforcementOfficer, DOTAdmin |
| POST | `/violations/{id}/contest` | Carrier contests a violation | Carrier |
| POST | `/violations/{id}/uphold` | Uphold a violation (accrue penalty; may revoke) | EnforcementOfficer |
| POST | `/violations/{id}/dismiss` | Dismiss a violation (may reinstate) | EnforcementOfficer |
| POST | `/_clock/set_current_utc` | Set the logical clock (may expire permits) | DOTAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_CARRIER_NOT_FOUND` | 404 Not Found |
| `ERR_PERMIT_NOT_FOUND` | 404 Not Found |
| `ERR_STRUCTURE_NOT_FOUND` | 404 Not Found |
| `ERR_PILOT_CAR_NOT_FOUND` | 404 Not Found |
| `ERR_ROUTE_SEGMENT_NOT_FOUND` | 404 Not Found |
| `ERR_BRIDGE_ANALYSIS_NOT_FOUND` | 404 Not Found |
| `ERR_ESCORT_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_VIOLATION_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_DIMENSIONS` | 422 Unprocessable Entity |
| `ERR_VALIDITY_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_STALE_PERMIT_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_PERMIT_STATE` | 409 Conflict |
| `ERR_INVALID_ANALYSIS_STATE` | 409 Conflict |
| `ERR_INVALID_ESCORT_STATE` | 409 Conflict |
| `ERR_INVALID_VIOLATION_STATE` | 409 Conflict |
| `ERR_CARRIER_SUSPENDED` | 403 Forbidden |
| `ERR_ROUTE_EMPTY` | 422 Unprocessable Entity |
| `ERR_ANNUAL_SUPERLOAD_FORBIDDEN` | 422 Unprocessable Entity |
| `ERR_BRIDGE_ANALYSIS_INCOMPLETE` | 409 Conflict |
| `ERR_BRIDGE_REJECTED` | 409 Conflict |
| `ERR_ESCORT_REQUIREMENT_UNMET` | 409 Conflict |
| `ERR_STRUCTURE_CLOSED` | 409 Conflict |
| `ERR_STRUCTURE_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_PILOT_CAR_UNAVAILABLE` | 409 Conflict |
| `ERR_PILOT_CAR_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_STRUCTURE_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_TRAVEL_TIME_RESTRICTED` | 409 Conflict |
| `ERR_UNPAID_FEES` | 402 Payment Required |
| `ERR_INSUFFICIENT_ESCROW` | 402 Payment Required |
