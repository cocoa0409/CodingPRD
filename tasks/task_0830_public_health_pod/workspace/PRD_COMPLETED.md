# Public-Health-Pod-Preparedness API — Product Requirements Document

## 1. Introduction

Jurisdictional public-health departments plan for mass-casualty and mass-prophylaxis events long before those events happen, and then execute those plans under time pressure once a hazard is declared. This system gives a health department a single operational backbone for that lifecycle: authoring a hazard/scenario plan, standing up points-of-dispensing (POD) sites and modeling their throughput, rostering and credentialing Medical Reserve Corps volunteers, tracking Strategic National Stockpile (SNS) and mutual-aid countermeasure inventory, registering and dispensing to the public at scale, running preparedness drills with after-action follow-up, and rolling all of it up into situational reports for incident command.

The domain is deliberately cross-referential rather than strictly hierarchical: an allocation request ties a requesting POD, a countermeasure, and — for mutual aid — a lending partner POD together in one record; a dispensing event ties a POD, a countermeasure, an inventory lot, and (twice) a staff member. Only the hazard plan's relationship to its PODs, drills, and situation reports is a clean parent-child pairing. Several entities — the POD's operational posture, the dispensing workflow, and a drill's corrective-action tracking — cycle back and forth between states rather than progressing monotonically toward a terminal state, and a number of operations cascade automatically across two or three entities in a single request (a dispensing event that drains a lot below its reorder point can, in the same call, restrict the POD and auto-file a new SNS request). Every derived figure — a POD's operational status and risk posture, a hazard plan's readiness score, an inventory lot's available quantity, an allocation request's reimbursement cost — is recomputed synchronously inside the request that triggers it, so callers can always trust the value they read back.

## 2. Global Specifications & System-Wide Principles

This section defines the rules, formats, and cross-cutting principles that apply uniformly across every resource and endpoint in the system.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the operational capacity in which they are acting. Five roles are recognized, spelled exactly as follows: `PublicHealthAdmin`, `LogisticsCoordinator`, `MutualAidPartner`, `ClinicalLead`, and `Volunteer`. A request missing either header, or presenting an `X-User-Role` value outside this set of five, is rejected with `ERR_UNAUTHENTICATED` (401). A request from a recognized role attempting an operation outside that role's authorized surface is rejected with `ERR_FORBIDDEN` (403).

`PublicHealthAdmin` owns the hazard-plan lifecycle, the POD lifecycle, the staff roster and credentialing, the countermeasure formulary, and drills. `LogisticsCoordinator` manages inventory receipt and drives the SNS-cache side of the allocation pipeline. `MutualAidPartner` responds to mutual-aid allocation requests directed at their POD. `ClinicalLead` supervises clinical operations at a POD — shift confirmation and check-out, screening, and dispensing. For all four of these roles, identity is opaque: `X-User-ID` is an operator identifier that is not tied to any persisted entity, and the server never compares it against a stored `id`. The server may still record an opaque `X-User-ID` value on a resource — for example, `screened_by_staff_member_id` or `dispensed_by_staff_member_id` on a `DispensingEvent` are supplied explicitly in the request payload rather than derived from the header.

`Volunteer`, by contrast, is entity-backed: when `X-User-Role` is `Volunteer`, `X-User-ID` is the `id` of the acting `StaffMember`. Ownership checks compare this value to the `staff_member_id` field of the resource being acted on. Specifically, when the acting role is `Volunteer` on the shift-proposal endpoint, the shift-cancellation endpoint, or the shift-check-in endpoint, `X-User-ID` must equal the resource's `staff_member_id` (or, on creation, the `staff_member_id` supplied in the payload); a mismatch is rejected with `ERR_OWNERSHIP_MISMATCH` (403).

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

List endpoints accept `limit` and `offset` query parameters. `limit` defaults to 10 when omitted, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. A `limit` below 1 or above 100, or a negative `offset`, is silently clamped to the nearest valid bound rather than rejected with a validation error. Unless a subsection below states otherwise, list endpoints return resources ordered by `created_at` ascending. The response `meta` object for every list endpoint includes `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Every top-level resource — `HazardPlan`, `POD`, `StaffMember`, `ShiftAssignment`, `Countermeasure`, `InventoryLot`, `AllocationRequest`, `DispensingEvent`, and `Drill` — carries an `id` (a server-minted UUID, with no type prefix), a `created_at` timestamp (ISO 8601 UTC, three fractional digits), an `updated_at` timestamp of the same format that advances on every mutation, and an integer `version` that starts at 1 on creation and increments by exactly 1 on every mutation to that resource. Both `created_at`/`updated_at` and every other system-stamped timestamp (for instance `HazardPlan.activated_at`) are derived from the logical clock defined in §2.5, not wall-clock time; because that clock only advances on an explicit clock-set call, resources created without an intervening clock advance share an identical `created_at`, and any ordering that sorts on `created_at` (§2.3, §2.9, §3.5) breaks such ties by the server's actual creation order — the sequence in which it processed the creating requests — never by `id`. `SituationReport` is the one exception: it is an immutable point-in-time snapshot, so it carries only `id` and `created_at` — it has no `updated_at` field and no `version` field, because it is never modified after creation.

Recomputation of a derived field — for instance, `POD.risk_tier`, `POD.queue_backlog_count`, or `HazardPlan.readiness_score` — is itself a mutation of the owning resource: it advances that resource's `updated_at` and increments its `version`, exactly as an input-field edit would, even when no client-supplied field changed.

### 2.5. The Logical Clock and Time-Dependent Rules

Every datetime-sensitive rule in this system — credential expiry, inventory-lot expiration, shift-overlap windows, and the "current" variant of throughput capacity — is evaluated against a single server-side logical clock rather than wall-clock time, so that scenarios can be driven forward deterministically. `PublicHealthAdmin` alone may advance this clock by supplying `to_iso8601` in the body of the clock-set operation; before any such call, the clock reads `2026-03-01T00:00:00Z`. A successful clock-set returns the new value in the response envelope's `data` field as `{"current_utc": "<iso8601>"}`.

### 2.6. Cross-Entity Consistency, Cascades, and Reference Validation

Requests are validated in a fixed order before any business rule is evaluated. First, the presence and validity of the auth headers (§2.1). Second, role authorization for the endpoint. Third, for the shift-assignment ownership case described in §2.1. Fourth, every resource identifier that appears in the URL path is confirmed to exist — the corresponding not-found error (`ERR_HAZARD_PLAN_NOT_FOUND`, `ERR_POD_NOT_FOUND`, `ERR_STAFF_MEMBER_NOT_FOUND`, `ERR_SHIFT_ASSIGNMENT_NOT_FOUND`, `ERR_COUNTERMEASURE_NOT_FOUND`, `ERR_INVENTORY_LOT_NOT_FOUND`, `ERR_ALLOCATION_REQUEST_NOT_FOUND`, `ERR_DISPENSING_EVENT_NOT_FOUND`, `ERR_DRILL_NOT_FOUND`, or `ERR_SITUATION_REPORT_NOT_FOUND`) is returned for the first path identifier that fails to resolve. Fifth, every foreign key referenced in the request body — `hazard_plan_id`, `pod_id`, `staff_member_id`, `countermeasure_id`, `partner_pod_id` — is confirmed to reference an existing resource, using the same not-found error family. Only after both existence passes succeed does the system evaluate whether the target resource is in a state from which the requested trigger has a declared transition (`ERR_INVALID_STATE`, 409), followed by the endpoint's specific business-safety, business-temporal, business-referential, and business-constraint checks, each of which is scattered through §3 alongside the workflow it guards.

Several operations reach across entity boundaries in a single request:

- Confirming a `ShiftAssignment` reads the linked `StaffMember`'s credential state directly — this is the `ShiftAssignment`↔`StaffMember` pairing.
- Reserving or denying an `AllocationRequest` reads the `HazardPlan` reached indirectly through the request's `pod_id` → `POD.hazard_plan_id` — the `AllocationRequest`↔`HazardPlan` pairing.
- Screening or dispensing at a `DispensingEvent` reads the linked `POD`'s operational posture — the `DispensingEvent`↔`POD` pairing.
- Standing down a `HazardPlan` reads every child `POD`'s operational posture — the `HazardPlan`↔`POD` pairing.

Two multi-hop cascades exist. The first ("Cascade A") begins when a `DispensingEvent` is dispensed: the selected `InventoryLot`'s `on_hand_quantity` is decremented (hop 1); if the resulting `available_quantity` falls below the countermeasure's reorder threshold while the POD is `OPERATIONAL`, the POD auto-transitions to `RESTRICTED` (hop 2); if that auto-transition occurs, the system auto-creates a new `AllocationRequest` against the SNS cache for that POD and countermeasure and increments the POD's open-request counter (hop 3). The second ("Cascade B") begins when a `StaffMember`'s credential is revoked: every `PENDING` or `CONFIRMED` `ShiftAssignment` for that staff member is auto-cancelled (hop 1); if a cancelled assignment leaves confirmed coverage for its `assigned_role` at that POD below one, and the POD is `OPERATIONAL`, the POD auto-transitions to `RESTRICTED` (hop 2). Both cascades are described in full in §3.

### 2.7. Precision, Rounding, and Monetary Values

Every rounded figure in this system uses the round-half-up method unless stated otherwise. `AllocationRequest.priority_score` and `AllocationRequest.reimbursement_cost_usd` are each rounded to 2 decimal places. `SituationReport.staffing_fill_rate_pct` is rounded to 1 decimal place; `HazardPlan.readiness_score` is rounded to the nearest whole number (0 decimal places). Counting fields (`pods_operational_count`, `pods_restricted_count`, `total_doses_dispensed`, `total_on_hand_inventory`) are always exact integers. The two throughput-capacity figures and the two demand-forecast figures returned by the operational-metrics read are integers produced by truncating (flooring) at each intermediate step as specified in §3.8 — never rounded upward except where a ceiling is explicitly called for. `Countermeasure.unit_cost_cents` is stored as whole US cents and is never itself rounded; it is only divided and rounded downstream, at the point a reimbursement is computed.

`SituationReport.total_mutual_aid_reimbursement_usd` deserves a specific rule because of how easily it can drift: each `AllocationRequest.reimbursement_cost_usd` addend is already rounded to 2 decimals at the moment that individual request is fulfilled. The situational-report rollup sums those already-rounded addends exactly as stored — it never re-derives a per-dose cost and sums unrounded products before rounding once at the report level. This "round-per-line-then-sum" order is pinned deliberately: summing raw, unrounded per-dose costs across many fulfilled requests and rounding only at the end can diverge from the pinned order by as much as one cent per request when the per-dose cost is a repeating decimal.

### 2.8. Optimistic Concurrency Control

Two write operations require the caller to prove they last observed the resource's current state before mutating a related resource. Creating an `AllocationRequest` (`POST /allocation-requests`) requires the request body to carry `expected_pod_version`, matching the target POD's current `version`. If another writer has advanced the POD's version — for instance, its operational posture or `open_allocation_request_count` changed — since the client last read it, the create is rejected with `ERR_STALE_VERSION` (HTTP 412); this prevents an allocation request's later priority scoring from acting on a stale view of the POD's posture. Reserving an `AllocationRequest` (`POST /allocation-requests/{id}/reserve`) requires the request body to carry `expected_inventory_lot_version`, matching the resolved source `InventoryLot`'s current `version`. If another writer has already reserved against, or cancelled a reservation against, that same lot since the client last observed it, the reserve is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from reserving against a lot balance it never actually saw. Both OCC fields treat an omitted value the same as a mismatched one — rejected with `ERR_STALE_VERSION`, not `ERR_VALIDATION`. No other endpoint in this system takes a version-expectation field; endpoints not named above proceed without an OCC check.

### 2.9. Inventory Ledger Principles

An `InventoryLot` with a null `pod_id` is the central SNS cache lot for its countermeasure; a lot with a non-null `pod_id` is scoped to that POD's own on-site stock. Every lot's `available_quantity` is defined as `on_hand_quantity` minus `reserved_quantity`, and is recomputed the instant either of those two inputs changes — there is no background reconciliation anywhere in this system, consistent with the immediate-consistency model that governs every derived field. `reserved_quantity` rises when an `AllocationRequest` reserves against the lot and falls when that reservation is cancelled or fulfilled. Two selection rules govern which lot a given operation draws against: dispensing at a POD selects, among that POD's lots for the relevant countermeasure with sufficient `available_quantity`, the one with the earliest `expiration_date` (first-expire-first-out), tie-broken by earliest `created_at` — never by `id`. When reserving an `AllocationRequest`, the source lot (the central cache lot for `SNS_CACHE`, or the `partner_pod_id`'s own lot for `MUTUAL_AID`) is likewise resolved by earliest `created_at` when more than one lot qualifies for that countermeasure, and a countermeasure with no qualifying source lot at all is treated identically to a resolved lot with zero `available_quantity` — rejected with `ERR_INSUFFICIENT_INVENTORY`. Fulfilling a mutual-aid or SNS-cache allocation credits the requesting POD's own lot for that countermeasure, selecting the existing lot with the earliest `created_at` if more than one qualifies, or creating a new lot on the spot — with `on_hand_quantity` set directly to the credited `fulfilled_quantity` (the lot is not created at 0 and then separately incremented, so its `version` stays at 1), a `lot_number` of `AUTO-<AllocationRequest.id>`, and an `expiration_date` copied from the source lot — if none exists yet.

### 2.10. Staffing Capacity and Scheduling Safeguards

Two independent capacity checks govern whether a proposed shift can be confirmed. The first is pairwise: no two `ShiftAssignment` rows for the same `staff_member_id`, both in `CONFIRMED` or `CHECKED_IN` status, may have overlapping `[start_time, end_time)` intervals — the interval is half-open, so a shift ending exactly when another begins does not count as an overlap. The second is aggregate: counting every `CONFIRMED` or `CHECKED_IN` `ShiftAssignment` at the same POD whose interval overlaps the one being confirmed (including the one being confirmed itself), that count may not exceed the POD's `staffing_capacity_lanes`. A staff member's credential must additionally be `VERIFIED`, and its `credential_expires_at` must be strictly later than the current logical clock time, before any shift for that staff member can be confirmed.

## 3. Business Logic & Workflows

### 3.1. The Hazard Plan Lifecycle and Readiness Scoring

A `PublicHealthAdmin` opens a `HazardPlan` by supplying a `hazard_type` — one of `PANDEMIC_INFLUENZA`, `BIOTERRORISM_ANTHRAX`, `RADIOLOGICAL_INCIDENT`, `CHEMICAL_RELEASE`, `NATURAL_DISASTER`, or `OUTBREAK_OTHER` — along with a human-readable `title`, the owning `jurisdiction_code`, and a `target_population` (the estimated population requiring dispensing, which must be zero or greater). The plan starts in `DRAFT`. Activation moves it to `ACTIVATED` and stamps `activated_at` with the current logical clock time; a plan can only be activated while it is `DRAFT`. Activation is a prerequisite scattered throughout the rest of the system — opening a POD, and reserving or denying an allocation request against one of that plan's PODs, both require the owning `HazardPlan.status` to be `ACTIVATED` (rejected with `ERR_HAZARD_PLAN_NOT_ACTIVATED` when it is not).

Standing a plan down moves it from `ACTIVATED` to `STOOD_DOWN` and stamps `stood_down_at`, but only once every `POD` that references this plan's id via `hazard_plan_id` has reached `operational_status` `CLOSED`; if any child POD is not yet closed, the request is rejected with `ERR_POD_NOT_READY_FOR_STAND_DOWN`. `STOOD_DOWN` is the plan's only terminal state.

A plan's `readiness_score` is a 0–100 figure, rounded to the nearest whole number, expressing the fraction of this plan's drills that have been fully resolved. It is computed as one hundred times the count of this plan's `Drill` rows that are `COMPLETED` with a `corrective_action_status` of either `NONE` or `CLOSED`, divided by the total count of this plan's drills (with that denominator floored at 1 so a plan with zero drills scores 0 rather than dividing by zero). It starts at 0 on plan creation and is recomputed synchronously every time a drill is completed or has its corrective action closed — see §3.7.

### 3.2. Standing Up and Operating a POD

Once a hazard plan is active, `PublicHealthAdmin` stands up one or more Points of Dispensing under it by supplying `hazard_plan_id`, a `site_name`, a `site_type` — one of `FIXED_POD`, `MOBILE_POD`, `DRIVE_THROUGH`, or `CLOSED_POD` — a street `address`, a `staffing_capacity_lanes` count (which must be greater than zero, and caps how many dispensing lanes can run at once), and a `lane_throughput_rate_per_hour` (doses one staffed lane can move per hour, required to be a positive integer). The POD begins `STAGING`.

Opening a POD moves it from `STAGING` to `OPERATIONAL`, but only while its owning hazard plan is `ACTIVATED`. From `OPERATIONAL`, a POD can be manually restricted by `PublicHealthAdmin`, or automatically restricted by the system as the second hop of either cascade described in §2.6 — the InventoryLot-depletion cascade triggered by dispensing (§3.6) or the credential-revocation cascade triggered by revoking a staff member's credential (§3.3) — landing in `RESTRICTED` either way. A `RESTRICTED` POD can be resumed back to `OPERATIONAL` by `PublicHealthAdmin`. Closing a POD is permitted from `STAGING`, `OPERATIONAL`, or `RESTRICTED`, moves it to the terminal `CLOSED` state, and is blocked (`ERR_POD_STAFF_ONSITE`) while any `ShiftAssignment` at that POD is currently `CHECKED_IN`; closing also auto-cancels every `PENDING` or `CONFIRMED` `ShiftAssignment` still open at that POD — unlike a standalone cancel, this close-triggered auto-cancellation does not subtract the cancelled `CONFIRMED` assignments' hours back out of `committed_staff_hours`, which is left at its last-computed value.

A POD carries three derived operational figures that a caller can rely on without recomputing them client-side. `risk_tier` is `CRITICAL` whenever `operational_status` is `RESTRICTED`; otherwise it is `ELEVATED` once the POD's registration backlog reaches or passes twenty pending registrants, and `STANDARD` below that. It is recomputed the instant `operational_status` or `queue_backlog_count` changes, but it is deliberately *not* recomputed as a side effect of the allocation-priority scoring calculation that reads it (see §3.5) — that calculation only ever reads whatever value is already stored. `queue_backlog_count` counts this POD's `DispensingEvent` rows currently sitting in `REGISTERED`, `SCREENED`, or `DEFERRED`; it rises by one on every new registration and falls by one on every refusal or successful dispense. `open_allocation_request_count` counts this POD's `AllocationRequest` rows currently in `REQUESTED`; it rises by one on every new request and falls by one the moment that request is reserved or denied — and, distinctly, it also rises by one whenever the system auto-files a replenishment request as the third hop of the dispensing-depletion cascade. `committed_staff_hours` sums, in hours, the `end_time` minus `start_time` interval of every `ShiftAssignment` at this POD currently `CONFIRMED`, `CHECKED_IN`, or `COMPLETED`; confirming a shift adds its duration, and cancelling a `CONFIRMED` shift subtracts the exact same amount back out, so the two operations always net to zero for a shift that is confirmed and later cancelled without ever being checked in.

### 3.3. Volunteer Roster, Credentialing, and Shift Assignments

`PublicHealthAdmin` registers each Medical Reserve Corps volunteer by supplying a `full_name`, a contact `email` (which must be unique across every `StaffMember`), a `primary_role` — one of `CLINICAL_LEAD`, `SCREENER`, `VACCINATOR`, `RUNNER`, `TRAFFIC_CONTROL`, or `GREETER` — an `mrc_unit` affiliation, a `credential_type` — one of `RN_LICENSE`, `MD_LICENSE`, `EMT_CERT`, `NIMS_IS100_700`, `BACKGROUND_CHECK`, or `PODS_TRAINING` — and that credential's `credential_expires_at` timestamp. The volunteer's `credential_status` starts `PENDING`. `PublicHealthAdmin` verifies the credential to move it to `VERIFIED`, or revokes it — from either `PENDING` or `VERIFIED` — to move it to the terminal `REVOKED` state.

Revocation is not an isolated edit: it is the trigger of Cascade B described in §2.6. Every `ShiftAssignment` referencing this staff member's id via `staff_member_id` that is currently `PENDING` or `CONFIRMED` is auto-cancelled as the cascade's first hop. If any of those auto-cancellations leaves confirmed coverage for that assignment's `assigned_role` at its POD below one — and that POD's `operational_status` was `OPERATIONAL` — the POD auto-transitions to `RESTRICTED` as the cascade's second hop, exactly as described for the dispensing-side cascade in §3.6.

A `ShiftAssignment` is proposed by an `assigned_role` — again one of `CLINICAL_LEAD`, `SCREENER`, `VACCINATOR`, `RUNNER`, `TRAFFIC_CONTROL`, or `GREETER` — that a volunteer or clinical lead will cover at a given POD. The proposer supplies `pod_id`, `staff_member_id`, `assigned_role`, a `start_time`, and an `end_time`; the request is rejected with `ERR_INVALID_TIME_RANGE` unless `start_time` is strictly before `end_time`. A `Volunteer` proposing an assignment must supply their own `id` as `staff_member_id` (§2.1's ownership rule). The assignment starts `PENDING`.

Confirming a `PENDING` assignment — advancing it to `CONFIRMED` — runs four checks in this order: first, that the assignment is actually `PENDING` (`ERR_INVALID_STATE`); second, the credential checks from §2.10 — `VERIFIED` status and an unexpired `credential_expires_at` (`ERR_CREDENTIAL_NOT_VERIFIED` or `ERR_CREDENTIAL_EXPIRED` respectively); third, the pairwise overlap check against the same staff member's other `CONFIRMED`/`CHECKED_IN` shifts (`ERR_SHIFT_OVERLAP`); fourth, the aggregate lane-capacity check against the POD's `staffing_capacity_lanes` (`ERR_POD_CAPACITY_EXCEEDED`). A successful confirm adds the shift's duration, in hours, to the POD's `committed_staff_hours`.

From `CONFIRMED`, checking in — moving the assignment to `CHECKED_IN` — is only permitted while the POD's `operational_status` is `STAGING`, `OPERATIONAL`, or `RESTRICTED`, and, when the actor is a `Volunteer`, only for their own assignment. From `CHECKED_IN`, only a `ClinicalLead` may check the volunteer back out, completing the assignment (terminal `COMPLETED`). An assignment may instead be cancelled — from `PENDING` or from `CONFIRMED` — by the assigned `Volunteer` (their own assignment only), by `PublicHealthAdmin`, by `ClinicalLead`, or automatically by the system as part of the two cascades described above; cancelling a `CONFIRMED` assignment restores the POD's `committed_staff_hours` by subtracting exactly the amount that confirming it had added.

### 3.4. Formulary and Inventory Management

`PublicHealthAdmin` maintains the countermeasure formulary: each `Countermeasure` has a display `name`, a `countermeasure_type` of `VACCINE`, `ANTIVIRAL`, or `ANTIBIOTIC_PEP`, a `doses_required` count (the number of doses that make up one complete regimen, required to be positive), a `dose_interval_days` (days between doses in a multi-dose regimen, defaulting to 0 for single-dose products, never negative), a `unit_cost_cents` (the whole-cent cost of one complete regimen, never negative), and a `reorder_point_quantity` (never negative) — the threshold whose crossing is central to Cascade A (§2.6, §3.6).

`LogisticsCoordinator` receives physical stock by creating an `InventoryLot`: a `countermeasure_id`, an optional `pod_id` (omitted for a central SNS-cache lot, supplied for a POD-scoped lot), a `lot_number`, an `on_hand_quantity` (never negative), and an `expiration_date` that must be strictly later than the current logical clock time at the moment of creation — a lot created with a quantity below zero or an expiration in the past or present is rejected with `ERR_INVALID_EXPIRATION`; a malformed or unparseable `expiration_date` is rejected with this same `ERR_INVALID_EXPIRATION`, not `ERR_VALIDATION`. A freshly created lot starts with `reserved_quantity` at 0 and `available_quantity` equal to its full `on_hand_quantity`; both derived fields evolve exactly as described in §2.9 as reservations, fulfillments, and dispenses move against the lot.

### 3.5. Allocation Requests: SNS Cache and Mutual Aid

A `LogisticsCoordinator` files an `AllocationRequest` on behalf of a POD that needs more of a given countermeasure — supplying `pod_id` (the requesting POD), `countermeasure_id`, a `requested_quantity` (which must be positive), and `expected_pod_version` (the OCC guard from §2.8). Two sourcing shapes are supported via `source_type`, which defaults to `SNS_CACHE`: when `source_type` is `SNS_CACHE`, `partner_pod_id` must be left null; when `source_type` is `MUTUAL_AID`, `partner_pod_id` must be supplied and must differ from `pod_id` — the lending POD or jurisdiction. Violating either pairing is rejected with `ERR_INVALID_SOURCE_CONFIGURATION`. Creation also requires the requesting POD's owning hazard plan to be `ACTIVATED` (§3.1). The request starts `REQUESTED`; creating it increments the requesting POD's `open_allocation_request_count` by one and — because a newly filed request changes what a future reader of that POD needs to know — also increments the POD's own `version` by one. At creation, `priority_score`, `reserved_quantity`, and `fulfilled_quantity` all read 0 and `reimbursement_cost_usd` reads 0 (matching its permanent `SNS_CACHE` value below) until reserve or fulfill actually sets them.

Reserving a request — moving it from `REQUESTED` to `RESERVED` — is where the sourcing distinction becomes an authorization rule: `LogisticsCoordinator` may only reserve requests with `source_type` `SNS_CACHE`, and `MutualAidPartner` may only reserve requests with `source_type` `MUTUAL_AID` (a mismatch is `ERR_SOURCE_ROLE_MISMATCH`); the same role pairing governs denial. Reserving is checked in this order: the request must be `REQUESTED`; the owning hazard plan (resolved through `pod_id` → the POD's `hazard_plan_id`) must be `ACTIVATED`; the acting role must match `source_type` as just described; the resolved source lot — the central cache lot for `SNS_CACHE`, or the `partner_pod_id`'s own lot for `MUTUAL_AID`, in both cases matched on `countermeasure_id` — must have `available_quantity` at least equal to `requested_quantity` (`ERR_INSUFFICIENT_INVENTORY` if not, including the boundary case where the lot is already fully depleted); and finally, `expected_inventory_lot_version` in the payload must match that source lot's current `version` (`ERR_STALE_VERSION`, §2.8). A successful reserve sets `status` to `RESERVED`, sets `reserved_quantity` to `requested_quantity`, increases the source lot's `reserved_quantity` by that same amount and bumps the source lot's `version` by one, records the resolved lot's id in `source_inventory_lot_id`, computes and stores `priority_score` (below), and decrements the requesting POD's `open_allocation_request_count` by one. Denial, requiring only the state and role-match checks, moves the request straight to the terminal `DENIED` and likewise decrements `open_allocation_request_count`.

`priority_score` is a weighted figure computed once, at reserve time, and never recalculated afterward. It is the sum of two terms, rounded to 2 decimal places: a quantity term equal to 0.01 multiplied by the smaller of `requested_quantity` and a cap of 5,000 doses, plus a risk-tier term drawn from the requesting POD's `risk_tier` at the moment reserve begins executing — `STANDARD` contributes 1, `ELEVATED` contributes 2, and `CRITICAL` contributes 3. That risk-tier read is pinned deliberately: `risk_tier` is read as whatever value is already stored on the POD and is never recomputed inline as part of this same reserve request, even though reserving also touches inventory state that could in principle influence risk. A later reserve request only ever sees an updated `risk_tier` once some other request — opening, restricting, resuming, or closing the POD, or a dispensing cascade — has actually recomputed it. When a listing shows two requests with an equal `priority_score`, they are ordered by `created_at` ascending, never by `id`.

Fulfilling a `RESERVED` request, restricted to `LogisticsCoordinator`, moves it to the terminal `FULFILLED`, sets `fulfilled_quantity` equal to `reserved_quantity`, and physically moves stock: the requesting POD's own lot for this countermeasure gains `fulfilled_quantity` in `on_hand_quantity` (selecting, if more than one such lot exists, the one with the earliest `created_at`, or auto-creating one as described in §2.9 if none exists), while the source lot loses the same amount from both `on_hand_quantity` and `reserved_quantity`. When the fulfilled request's `source_type` is `MUTUAL_AID`, this is also the moment `reimbursement_cost_usd` is computed and stored: the countermeasure's `unit_cost_cents` divided by its `doses_required` gives a cost-per-dose in cents, which is multiplied by `fulfilled_quantity`, divided by 100 to convert to dollars, and rounded to 2 decimal places, round-half-up — for an `SNS_CACHE` request, `reimbursement_cost_usd` remains 0. This per-request rounding is pinned, not incidental: §3.8's report rollup sums these already-rounded figures rather than re-deriving and summing unrounded ones (§2.7). Cancelling a `RESERVED` request, available to the same two roles that can reserve or deny — `LogisticsCoordinator` or `MutualAidPartner` regardless of the request's own `source_type`, since cancellation does not repeat reserve/deny's source-type-to-role matching check — moves it to the terminal `CANCELLED` and releases the reservation by decreasing the source lot's `reserved_quantity` by `reserved_quantity` — restoring the invariant that `reserved_quantity` plus `available_quantity` equals `on_hand_quantity`.

### 3.6. Registration, Screening, and Dispensing at the POD

A `Volunteer` or `ClinicalLead` registers a member of the public arriving at a POD by creating a `DispensingEvent`: `pod_id`, `countermeasure_id`, the `registrant_full_name`, the `registrant_risk_group` — one of `GENERAL_PUBLIC`, `HEALTHCARE_WORKER`, `FIRST_RESPONDER`, or `HIGH_RISK_MEDICAL` — and an optional `dose_count` (defaulting to 1, always positive). The event starts `REGISTERED`, and creating it increments the POD's `queue_backlog_count` by one.

A `ClinicalLead` clinically screens the registrant, moving the event from `REGISTERED` to `SCREENED` and recording the screening staff member's id in `screened_by_staff_member_id` (supplied in the request payload, but not required — the field is left null if omitted). From `SCREENED`, the `ClinicalLead` can defer the registrant to `DEFERRED`, which requires a non-empty `deferral_reason` in the payload (`ERR_VALIDATION` if it is blank) — that reason is stored, and clears automatically the moment the registrant is rescreened back to `SCREENED`. From `SCREENED`, the `ClinicalLead` may instead refuse the registrant outright, moving the event to the terminal `REFUSED` and decrementing the POD's `queue_backlog_count` by one — the same decrement that a successful dispense produces.

Dispensing — moving a `SCREENED` event to the terminal `DISPENSED` — is the trigger of Cascade A (§2.6). It first requires the POD's `operational_status` to be `OPERATIONAL` or `RESTRICTED` (`ERR_POD_NOT_OPERATIONAL` otherwise — the same rule that gates screening), and requires a POD-scoped `InventoryLot` for this countermeasure with `available_quantity` at least `dose_count` (`ERR_INSUFFICIENT_INVENTORY`), selected first-expire-first-out per §2.9. A successful dispense records the dispensing staff member's id (payload field `dispensed_by_staff_member_id`, likewise optional and left null if omitted) into `dispensed_by_staff_member_id`, decrements `queue_backlog_count` by one, records the selected lot's id into `inventory_lot_id`, and decreases that lot's `on_hand_quantity` by `dose_count` — hop 1 of Cascade A. If the lot's resulting `available_quantity` drops below the countermeasure's `reorder_point_quantity` while the POD is still `OPERATIONAL`, the POD auto-transitions to `RESTRICTED` — hop 2. If that auto-transition fires, the system auto-files a fresh `AllocationRequest` in the same request: `pod_id` set to this POD, `countermeasure_id` unchanged, `source_type` forced to `SNS_CACHE`, `requested_quantity` set to the countermeasure's own `reorder_point_quantity`, and `status` `REQUESTED` — and increments this POD's `open_allocation_request_count` by one — hop 3, closing the loop back to §3.5's allocation pipeline.

### 3.7. Drills, After-Action Review, and Corrective Actions

`PublicHealthAdmin` schedules a preparedness exercise under a hazard plan by supplying `hazard_plan_id`, a `drill_type` — `TABLETOP`, `FUNCTIONAL`, or `FULL_SCALE` — and a `scheduled_at` timestamp. Every drill carries two dimensions that evolve independently of one another rather than as a single linear lifecycle: `status`, which starts `SCHEDULED`, and `corrective_action_status`, which starts `NONE`.

From `SCHEDULED`, `status` moves either to the terminal `CANCELLED`, or to `COMPLETED` when the drill is completed — at which point an optional after-action `finding` and an optional `corrective_action` can be recorded in the same request. Completion only ever advances `status`; it advances `corrective_action_status` from `NONE` to `OPEN` as a side effect, but only when a `corrective_action` was actually supplied in that request — a completed drill with no `corrective_action` leaves `corrective_action_status` at `NONE` indefinitely. Completing a drill (or, separately, closing its corrective action) recomputes the owning `HazardPlan.readiness_score` exactly as specified in §3.1, because both events change the count of drills that count as fully resolved.

Closing the corrective action — moving `corrective_action_status` from `OPEN` to `CLOSED` — is available only once `status` is `COMPLETED` and `corrective_action_status` is `OPEN`; it operates purely on the corrective-action dimension and leaves `status` at `COMPLETED` throughout.

### 3.8. Operational Metrics and Situational Reporting

A single read, scoped to one POD and one `countermeasure_id` query parameter, always returns two independent pairs of figures together: a throughput-capacity pair and a demand-forecast pair. An absent or non-existent `countermeasure_id` is rejected with `ERR_COUNTERMEASURE_NOT_FOUND` (404).

The throughput-capacity pair estimates how many doses per hour a POD can move for the given countermeasure. Two lane-staffing counts are derived first: `lanes_staffed_current` is the count of this POD's `ShiftAssignment` rows that are `CHECKED_IN` and whose `[start_time, end_time)` interval contains the current logical clock time, divided by 2 (two staff cover one lane) and truncated down; `lanes_staffed_planned` is the same computation but counting rows in `CONFIRMED` or `CHECKED_IN` — a forward-looking count that includes staff not yet on site. For each of the two, the number of *effective* lanes is the smaller of that staffing count and the POD's `staffing_capacity_lanes`. A staff-driven hourly capacity is the effective-lane count multiplied by `lane_throughput_rate_per_hour`; an inventory-driven hourly capacity is the sum of `available_quantity` across this POD's lots for the given countermeasure, divided by that countermeasure's `doses_required`, truncated down. The smaller of those two hourly figures is the base capacity; if the effective-lane count reaches or exceeds six lanes, a 1.15x surge bonus is applied to the base capacity and the result is truncated down again, otherwise the base capacity stands as-is. The result of this calculation using the current-staffing variant is returned as `current_throughput_capacity_per_hour`; the planned-staffing variant is returned as `planned_throughput_capacity_per_hour`. Both are plain integers with no rounding beyond the truncation already described.

The demand-forecast pair estimates dosing pressure for that same POD and countermeasure. `provisional_demand_doses` looks forward: it counts this POD's `DispensingEvent` rows for the countermeasure currently in `REGISTERED`, `SCREENED`, or `DEFERRED`, discounts that count by a 10 percent no-show rate (i.e., multiplies by 0.90), multiplies by the countermeasure's `doses_required`, and rounds the result up to the next whole dose. `final_demand_doses` looks backward: it is the exact integer sum of `dose_count` across this POD's `DISPENSED` events for the countermeasure, with no discount applied.

Separately, `PublicHealthAdmin` or `LogisticsCoordinator` snapshots a `SituationReport` for a hazard plan's current operational period, supplying `hazard_plan_id`, a `report_period_label` (for example, an operational-period identifier), and an optional free-text `narrative`. Every other field on a situation report is computed once, at creation, from every `POD`, `DispensingEvent`, `InventoryLot`, `ShiftAssignment`, and `AllocationRequest` row that belongs to this hazard plan (directly, or via a POD that belongs to it) — this is a permanent snapshot; it is never recomputed later. `pods_operational_count` and `pods_restricted_count` count this plan's PODs by `operational_status`. `total_doses_dispensed` sums `dose_count` across this plan's `DISPENSED` events. `total_on_hand_inventory` sums `on_hand_quantity` across every lot belonging to one of this plan's PODs. `staffing_fill_rate_pct` is 0 when this plan's PODs have no `ShiftAssignment` rows at all; otherwise it is 100 times the count of those assignments in `CONFIRMED`, `CHECKED_IN`, or `COMPLETED`, divided by the total assignment count, rounded to 1 decimal place. `total_mutual_aid_reimbursement_usd` sums `reimbursement_cost_usd` across this plan's `FULFILLED`, `MUTUAL_AID` allocation requests — summing the already-rounded per-request values, per §2.7 and §3.5's pinned rounding order. Finally, `readiness_status` is `RED` when `pods_restricted_count` is one or more, or when `staffing_fill_rate_pct` falls below 50.0; otherwise it is `YELLOW` when `staffing_fill_rate_pct` falls below 80.0; otherwise it is `GREEN`.

## 4. Endpoint Definitions

Creating a new resource returns `201 Created`; every other successful operation — transitions, updates, and computed reads — returns `200 OK`. Query parameters marked with a trailing `?` in the descriptions above (`limit`, `offset`, and the various filters) are optional on every list endpoint.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/hazard-plans` | Create a hazard/scenario plan | PublicHealthAdmin |
| GET | `/hazard-plans/{id}` | Fetch a hazard plan by id | PublicHealthAdmin, LogisticsCoordinator, MutualAidPartner, ClinicalLead, Volunteer |
| GET | `/hazard-plans` | List hazard plans, optionally filtered by status | PublicHealthAdmin, LogisticsCoordinator, MutualAidPartner, ClinicalLead, Volunteer |
| POST | `/hazard-plans/{id}/activate` | Activate a DRAFT hazard plan | PublicHealthAdmin |
| POST | `/hazard-plans/{id}/stand_down` | Stand down an ACTIVATED hazard plan | PublicHealthAdmin |
| POST | `/pods` | Stand up a new POD under a hazard plan | PublicHealthAdmin |
| GET | `/pods/{id}` | Fetch a POD by id | PublicHealthAdmin, LogisticsCoordinator, MutualAidPartner, ClinicalLead, Volunteer |
| GET | `/pods` | List PODs, optionally filtered by hazard plan or posture | PublicHealthAdmin, LogisticsCoordinator, MutualAidPartner, ClinicalLead, Volunteer |
| POST | `/pods/{id}/open` | Open a STAGING POD for operations | PublicHealthAdmin |
| POST | `/pods/{id}/restrict` | Manually restrict an OPERATIONAL POD | PublicHealthAdmin |
| POST | `/pods/{id}/resume` | Resume a RESTRICTED POD to OPERATIONAL | PublicHealthAdmin |
| POST | `/pods/{id}/close` | Close a POD | PublicHealthAdmin |
| GET | `/pods/{id}/operational-metrics` | Computed read exposing throughput capacity and demand forecast for one countermeasure | PublicHealthAdmin, LogisticsCoordinator, ClinicalLead |
| POST | `/staff-members` | Register an MRC volunteer with their primary credential | PublicHealthAdmin |
| GET | `/staff-members` | List staff members, optionally filtered by mrc_unit, primary_role, or credential_status | PublicHealthAdmin, LogisticsCoordinator, ClinicalLead, Volunteer |
| POST | `/staff-members/{id}/verify-credential` | Verify a volunteer's credential | PublicHealthAdmin |
| POST | `/staff-members/{id}/revoke-credential` | Revoke a volunteer's credential | PublicHealthAdmin |
| POST | `/shift-assignments` | Propose a shift assignment | Volunteer, PublicHealthAdmin, ClinicalLead |
| GET | `/shift-assignments/{id}` | Fetch a shift assignment by id | PublicHealthAdmin, LogisticsCoordinator, MutualAidPartner, ClinicalLead, Volunteer |
| GET | `/shift-assignments` | List shift assignments, filtered by POD, staff member, and/or status | PublicHealthAdmin, LogisticsCoordinator, ClinicalLead, Volunteer |
| POST | `/shift-assignments/{id}/confirm` | Confirm a pending shift assignment | ClinicalLead, PublicHealthAdmin |
| POST | `/shift-assignments/{id}/check_in` | Check a volunteer into their confirmed shift | Volunteer, ClinicalLead |
| POST | `/shift-assignments/{id}/check_out` | Check a volunteer out at end of shift | ClinicalLead |
| POST | `/shift-assignments/{id}/cancel` | Cancel a pending or confirmed shift assignment | Volunteer, PublicHealthAdmin, ClinicalLead |
| POST | `/countermeasures` | Add a countermeasure to the formulary | PublicHealthAdmin |
| GET | `/countermeasures` | List formulary countermeasures, optionally filtered by countermeasure_type | PublicHealthAdmin, LogisticsCoordinator, MutualAidPartner, ClinicalLead, Volunteer |
| POST | `/inventory-lots` | Receive a new inventory lot (central SNS cache or POD-scoped) | LogisticsCoordinator |
| GET | `/inventory-lots/{id}` | Fetch an inventory lot by id | PublicHealthAdmin, LogisticsCoordinator, MutualAidPartner |
| GET | `/inventory-lots` | List inventory lots, filtered by countermeasure and/or POD | PublicHealthAdmin, LogisticsCoordinator, MutualAidPartner |
| POST | `/allocation-requests` | Request a quantity of a countermeasure for a POD | LogisticsCoordinator |
| GET | `/allocation-requests/{id}` | Fetch an allocation request by id | PublicHealthAdmin, LogisticsCoordinator, MutualAidPartner |
| GET | `/allocation-requests` | List allocation requests, filtered by POD, countermeasure, partner POD, source lot, or status | PublicHealthAdmin, LogisticsCoordinator, MutualAidPartner |
| POST | `/allocation-requests/{id}/reserve` | Reserve the requested quantity against the resolved source lot | LogisticsCoordinator, MutualAidPartner |
| POST | `/allocation-requests/{id}/deny` | Deny a requested allocation | LogisticsCoordinator, MutualAidPartner |
| POST | `/allocation-requests/{id}/fulfill` | Fulfill a reserved allocation | LogisticsCoordinator |
| POST | `/allocation-requests/{id}/cancel` | Cancel a reserved allocation | LogisticsCoordinator, MutualAidPartner |
| POST | `/dispensing-events` | Register a person for dispensing at a POD | Volunteer, ClinicalLead |
| GET | `/dispensing-events/{id}` | Fetch a dispensing event by id | PublicHealthAdmin, LogisticsCoordinator, ClinicalLead, Volunteer |
| GET | `/dispensing-events` | List dispensing events, filtered by POD, countermeasure, lot, screening staff, dispensing staff, or status | PublicHealthAdmin, LogisticsCoordinator, ClinicalLead, Volunteer |
| POST | `/dispensing-events/{id}/screen` | Clinically screen a registrant | ClinicalLead |
| POST | `/dispensing-events/{id}/defer` | Defer a screened registrant | ClinicalLead |
| POST | `/dispensing-events/{id}/rescreen` | Return a deferred registrant to screened status | ClinicalLead |
| POST | `/dispensing-events/{id}/refuse` | Record a registrant's refusal after screening | ClinicalLead |
| POST | `/dispensing-events/{id}/dispense` | Dispense the countermeasure to a screened registrant | ClinicalLead |
| POST | `/drills` | Schedule a preparedness drill | PublicHealthAdmin |
| GET | `/drills/{id}` | Fetch a drill by id | PublicHealthAdmin, LogisticsCoordinator, ClinicalLead |
| GET | `/drills` | List drills, filtered by hazard plan and/or status | PublicHealthAdmin, LogisticsCoordinator, ClinicalLead |
| POST | `/drills/{id}/complete` | Complete a drill and record after-action findings | PublicHealthAdmin |
| POST | `/drills/{id}/cancel` | Cancel a scheduled drill | PublicHealthAdmin |
| POST | `/drills/{id}/close_corrective_action` | Close the corrective action recorded at drill completion | PublicHealthAdmin |
| POST | `/situation-reports` | Snapshot a situational report for a hazard plan's current period | PublicHealthAdmin, LogisticsCoordinator |
| GET | `/situation-reports/{id}` | Fetch a situation report by id | PublicHealthAdmin, LogisticsCoordinator, MutualAidPartner, ClinicalLead, Volunteer |
| GET | `/situation-reports` | List situation reports, filtered by hazard plan | PublicHealthAdmin, LogisticsCoordinator, MutualAidPartner, ClinicalLead, Volunteer |
| POST | `/_clock/set_current_utc` | Test-driving endpoint: sets the server's logical clock | PublicHealthAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_OWNERSHIP_MISMATCH` | 403 |
| `ERR_HAZARD_PLAN_NOT_FOUND` | 404 |
| `ERR_POD_NOT_FOUND` | 404 |
| `ERR_STAFF_MEMBER_NOT_FOUND` | 404 |
| `ERR_SHIFT_ASSIGNMENT_NOT_FOUND` | 404 |
| `ERR_COUNTERMEASURE_NOT_FOUND` | 404 |
| `ERR_INVENTORY_LOT_NOT_FOUND` | 404 |
| `ERR_ALLOCATION_REQUEST_NOT_FOUND` | 404 |
| `ERR_DISPENSING_EVENT_NOT_FOUND` | 404 |
| `ERR_DRILL_NOT_FOUND` | 404 |
| `ERR_SITUATION_REPORT_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CREDENTIAL_EXPIRED` | 422 |
| `ERR_CREDENTIAL_NOT_VERIFIED` | 422 |
| `ERR_INVALID_TIME_RANGE` | 400 |
| `ERR_SHIFT_OVERLAP` | 409 |
| `ERR_POD_CAPACITY_EXCEEDED` | 409 |
| `ERR_POD_NOT_OPERATIONAL` | 409 |
| `ERR_HAZARD_PLAN_NOT_ACTIVATED` | 409 |
| `ERR_SOURCE_ROLE_MISMATCH` | 403 |
| `ERR_INSUFFICIENT_INVENTORY` | 409 |
| `ERR_INVALID_SOURCE_CONFIGURATION` | 400 |
| `ERR_POD_NOT_READY_FOR_STAND_DOWN` | 409 |
| `ERR_POD_STAFF_ONSITE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_EXPIRATION` | 400 |
| `ERR_VALIDATION` | 400 |
