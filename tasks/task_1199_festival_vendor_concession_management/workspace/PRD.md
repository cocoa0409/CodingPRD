# Festival Vendor & Concession Management API — Product Requirements Document

## 1. Introduction

Running the vendor program of a multi-day music festival is a logistics, safety, and revenue operation compressed into a few unforgiving days. Hundreds of food, beverage, dessert, and merchandise vendors compete for a limited number of booths; each booth draws against a finite pool of electrical capacity and potable water hookups; county health inspectors and fire marshals must clear every stall before the gates open; and once the crowd arrives, every cashless sale flowing through a vendor's point-of-sale terminal becomes part of a revenue-share or flat-fee settlement that both sides must be able to audit line by line. Missed load-in windows, contaminated compost streams, and grease-disposal violations carry real financial penalties, and a vendor's conduct this year determines whether they are invited back next year.

This document specifies the Festival Vendor & Concession Management API, the system of record for that entire operation. It governs the full lifecycle — festival setup with zones and booths, vendor onboarding, application curation with category exclusivity and per-category caps, booth assignment under zone utility budgets, health and fire inspection gating, scheduled vehicle load-in windows, cashless point-of-sale reporting, settlement with provisional and final financial variants, compliance fines with segregation of duties, and post-festival performance scoring that drives return invitations. All temporal behavior in the system is driven by a single logical clock, and all money is accounted in integer cents under a pinned rounding policy, so that two competent readers of this document arrive at the same numbers.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Every request must carry `X-User-ID` identifying the acting party and `X-User-Role` naming their operational capacity. A request in which either header is missing or empty is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The system recognizes exactly seven roles: `FestivalDirector`, `VendorManager`, `OperationsLead`, `HealthInspector`, `SustainabilityOfficer`, `FinanceLead`, and `Vendor`. Every endpoint admits a fixed set of roles (enumerated in §4); a caller whose role is not admitted is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `Vendor`, `X-User-ID` is the `id` of the acting `Vendor`; ownership checks on any resource that references a vendor compare the resource's vendor foreign key — or the vendor reached by following an assignment back to its application — to `X-User-ID`, and a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). When `X-User-Role` is `FestivalDirector`, `VendorManager`, `OperationsLead`, `HealthInspector`, `SustainabilityOfficer`, or `FinanceLead`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `created_by_user_id` or `waived_by_user_id` on a fine, or as `reconciled_by_user_id` or `finalized_by_user_id` on a settlement — but it never compares such an identifier to any entity's `id`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every primary resource carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps rendered with three fractional digits; `updated_at` is refreshed on any mutation of the resource. The `version` field is an integer that increments by one with every mutation and anchors optimistic concurrency control where that mechanism applies. One entity deviates from this convention: an `InspectionRecord` is an immutable event and carries only `id` and `created_at` — `updated_at` and `version` are absent, and no endpoint modifies an inspection after it is recorded.

### 2.5. The Logical Clock

All temporal rules in the system — slot lock horizons, check-in grace periods, festival start and end gates, sweeps — read a single server-side logical clock, never wall-clock time. At server startup the logical clock is exactly `2026-05-01T00:00:00Z` and it must not fall back to wall-clock time under any circumstance. A director-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`. Clients that need determinism set the clock explicitly before exercising time-dependent behavior.

### 2.6. Flat Topology, Denormalized Festival Identity, and Cross-Festival Integrity

The API has a flat topology: every resource is a peer mounted at the root, and resources are joined by foreign keys rather than nested paths, with filtered list queries providing reverse reachability. For any parameterized path, identifiers are validated for existence left to right, and every foreign key supplied in a request body must reference an existing resource; the first missing reference surfaces the corresponding not-found error — one of `ERR_FESTIVAL_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_ZONE_NOT_FOUND`, `ERR_BOOTH_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, `ERR_SLOT_NOT_FOUND`, `ERR_RESERVATION_NOT_FOUND`, `ERR_TRANSACTION_NOT_FOUND`, `ERR_SETTLEMENT_NOT_FOUND`, `ERR_FINE_NOT_FOUND`, or `ERR_REVIEW_NOT_FOUND` (HTTP 404).

Because assignments, inspections, reservations, transactions, settlements, fines, and reviews all live inside exactly one festival, each of those resources carries a denormalized `festival_id` stamped at creation from the referenced chain (an assignment additionally carries a denormalized `zone_id` taken from its booth's zone, refreshed on reassignment). Linked resources must belong to the same festival: a booth assignment requires that the application's festival equals the booth's zone's festival, and a load-in reservation requires that the slot and the assignment share a festival. A cross-festival link is rejected with `ERR_CROSS_FESTIVAL_REFERENCE` (HTTP 409).

### 2.7. Monetary Precision and Rounding

All monetary amounts are integer cents; the API never represents money as a fractional quantity. Wherever a per-transaction or per-tier-portion festival share is produced, that share is rounded half-up to whole cents first, and the festival share is the sum of those individually rounded shares. Summing raw fractional shares and rounding once at the end produces a different number and is explicitly rejected as an implementation strategy. Performance percentiles and scores are integers between 0 and 100, rounded half-up. Electrical draws, vehicle counts, and hookup counts are integers with no rounding.

### 2.8. Optimistic Concurrency Control

Exactly two write operations carry optimistic concurrency protection; endpoints not listed here accept no version field.

Reassigning a booth assignment requires the request to carry `expected_assignment_version`, the client's last observed `version` of the assignment. If the assignment's current `version` has advanced beyond what the client observed — for example because another writer has already reassigned the same assignment, a legitimate state-preserving mutation that bumps the version — the reassignment is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting an assignment state it has not observed.

Voiding a point-of-sale transaction requires the request to carry `expected_settlement_version`, the client's last observed `version` of the settlement that parents the transaction's assignment. A mismatch with the settlement's current `version` is rejected with `ERR_STALE_SETTLEMENT_VERSION` (HTTP 412). This matters because every successful void itself advances the settlement's `version` by one and recomputes its provisional figures, so a client working from a stale read would otherwise corrupt the provisional variant.

### 2.9. Segregation of Duties

Two operations enforce a strict separation between the party who creates a liability and the party who discharges it. Waiving a compliance fine requires that the acting `FestivalDirector`'s `X-User-ID` differ from the fine's `created_by_user_id`, unless the issuer is the literal `system` — auto-issued fines may be waived by any director. A self-waiver attempt is rejected with `ERR_SOD_FINE_WAIVER` (HTTP 403). Finalizing a settlement requires that the acting `FinanceLead`'s `X-User-ID` differ from the settlement's recorded `reconciled_by_user_id`; the same person may not reconcile and finalize the same settlement, and a violation is rejected with `ERR_SOD_SETTLEMENT_FINALIZE` (HTTP 403).

### 2.10. Validation Order

When a request could fail several checks at once, the server evaluates them in a fixed order so the surfaced error is deterministic. First, the presence and non-emptiness of `X-User-ID` and `X-User-Role` (1). Second, role authorization for the endpoint (2). Third, the segregation-of-duties screens on the two guarded operations (3). Fourth, existence of every path identifier, left to right, and of every foreign key in the body (4). Fifth, entity-backed ownership for `Vendor` actors (5). Sixth, festival posture gates — application intake, assignment intake, live-gated writes, and settlement-gated creates (6). Seventh, vendor standing (7). Eighth, state-machine legality of the requested transition, including terminal-state lockdown, together with request-shape validity — missing required fields, malformed values, and enum violations surface as `ERR_INVALID_REQUEST` (HTTP 400), while an illegal transition surfaces as `ERR_INVALID_STATE_TRANSITION` (HTTP 409) (8). Ninth, cross-referential integrity — shared festival, supersede validity, the one-settlement-per-assignment rule, and the fine and settlement completion gates (9). Tenth, the public-safety pre-open inspection gate (10). Eleventh, temporal clock rules (11). Twelfth, resource constraints — category exclusivity and caps, booth availability, outlet and hookup fit, zone budgets, slot capacity, window overlap, and the review-round limit (12). Thirteenth, fiscal checks — fee-term completeness, positive amounts, and optimistic-concurrency freshness (13). A failure at any step stops evaluation and returns that step's error.

## 3. Business Logic & Workflows

### 3.1. Festival Setup: Site Plan, Zones, and Booths

A `FestivalDirector` opens a new festival by supplying its display `name`, the gates-open instant `event_start`, the closing instant `event_end` (both ISO 8601 UTC), and `category_cap_per_category`, the maximum number of applications that may be accepted per category within the festival. A new festival begins in `PLANNING` status. The festival lifecycle is linear and forward-only — `PLANNING` → `APPLICATIONS_OPEN` → `CURATED` → `LIVE` → `SETTLEMENT` → `CLOSED` — and the advance operation takes a `to_status` that must be the immediate successor of the current state; asking for any other target is rejected with `ERR_INVALID_STATE_TRANSITION`. The festival list can be filtered by `status`.

While the festival is in `PLANNING`, an `OperationsLead` builds the site plan. Each zone is created with its `festival_id`, a `name` such as North Meadow, a `power_capacity_amps` budget of at least 1, and a `water_hookup_total` of zero or more. Zones expose two computed counters that start at zero: `reserved_power_amps`, the sum of `power_draw_amps` over the zone's assignments in `RESERVED`, `CONFIRMED`, or `ACTIVE`, and `reserved_water_hookups`, the count of those assignments whose `requires_water` is true; assignments in `RELEASED`, `FORFEITED`, or `COMPLETED` never count. Within a zone, booths are created with a `zone_id`, a `label` such as N-12, a `power_outlet_max_amps` of at least 1, and a `has_water_hookup` flag. A booth's `status` is `AVAILABLE` at creation and is driven solely by assignment side effects thereafter — it moves to `RESERVED` when an assignment reserves it and to `ASSIGNED` when that assignment is confirmed, and returns to `AVAILABLE` when the assignment is released or forfeited. The zone list filters by `festival_id`; the booth list filters by `zone_id` and `status`.

Opening applications — advancing from `PLANNING` to `APPLICATIONS_OPEN` — requires that at least one zone exists for the festival; otherwise the advance is rejected with `ERR_FESTIVAL_NOT_CONFIGURED`.

### 3.2. Vendor Onboarding and the Application Pipeline

A `FestivalDirector` or `VendorManager` onboards a vendor with its `legal_name` and `contact_email`. A new vendor starts in `APPROVED` status with `compliance_strikes` at zero; the `legal_name` later serves as the deterministic tie-break in waitlist promotion, so it must be recorded accurately. The vendor list filters by `status`.

Once a festival is accepting applications, a `Vendor` submits one with a payload naming the `vendor_id` — which must equal the caller's `X-User-ID`, otherwise `ERR_NOT_RESOURCE_OWNER` — the `festival_id`, a `category` of `FOOD_HOT`, `FOOD_COLD`, `BEVERAGE_ALCOHOL`, `BEVERAGE_NA`, `DESSERT`, or `MERCHANDISE`, a proposed `fee_model` of `FLAT_FEE`, `REVENUE_SHARE`, or `HYBRID`, the booth's peak electrical draw `power_needed_amps` (at least 1), and whether the booth `requires_water`. When the fee model is `FLAT_FEE` or `HYBRID`, `proposed_flat_fee_cents` is required and must be zero or more; when it is `REVENUE_SHARE` or `HYBRID`, `proposed_revenue_share_pct_bp` is required and must lie between 1 and 10,000 basis points. Submitting while the festival is not in `APPLICATIONS_OPEN` is rejected with `ERR_FESTIVAL_NOT_ACCEPTING_APPLICATIONS`; submitting as a `SUSPENDED` vendor is rejected with `ERR_VENDOR_SUSPENDED`. A fresh application enters `SUBMITTED` with `review_round` zero. The application list filters by `festival_id`, `vendor_id`, `status`, `category`, and `supersedes_application_id`.

A `VendorManager` begins evaluation by starting review, moving the application from `SUBMITTED` — or from `WAITLISTED`, for example after an automatic promotion — to `UNDER_REVIEW`. If the proposal needs work, requesting changes moves it to `CHANGES_REQUESTED` and may carry optional reviewer `notes`; this loop is bounded — requesting changes when `review_round` has already reached 3 is rejected with `ERR_REVIEW_ROUND_LIMIT`. The vendor answers by resubmitting: a new application whose `supersedes_application_id` points at the `CHANGES_REQUESTED` one. The supersede is valid only when the source is in `CHANGES_REQUESTED` and belongs to the same vendor and the same festival, otherwise `ERR_SUPERSEDE_SOURCE_INVALID`; on success the source moves to `SUPERSEDED` and the new application enters `SUBMITTED` with `review_round` set to the source's round plus one.

The curation decision moves an `UNDER_REVIEW` application to `ACCEPTED`, `REJECTED`, or `WAITLISTED` according to the submitted `decision`. Acceptance fixes the commercial terms permanently: the caller supplies a `curated_fee_model` and the matching term set, and acceptance is rejected with `ERR_FEE_TERMS_INCOMPLETE` (HTTP 400) when the set is incomplete — `FLAT_FEE` requires `curated_flat_fee_cents`; `REVENUE_SHARE` requires `curated_revenue_share_pct_bp` together with `curated_tier_mode` of `MARGINAL` or `WHOLE_TIER`; `HYBRID` requires `curated_flat_fee_cents`, `curated_revenue_share_pct_bp`, `curated_minimum_guarantee_cents`, and `curated_free_allowance_cents`. Acceptance is also subject to the per-category cap: if the number of the festival's already-accepted applications in the same category has reached `category_cap_per_category`, the decision is rejected with `ERR_CATEGORY_CAP_REACHED`. Once written, the curated terms are immutable.

A vendor may withdraw its own application from any of `SUBMITTED`, `UNDER_REVIEW`, `CHANGES_REQUESTED`, or `WAITLISTED`, moving it to `WITHDRAWN`; the ownership check applies here as everywhere. Separately, if the owning vendor is suspended through strike contagion (§3.7), every application of that vendor in any of those four states is moved to `REJECTED` by the system in the same request. Closing curation — advancing the festival from `APPLICATIONS_OPEN` to `CURATED` — requires that no application remain in `SUBMITTED`, `UNDER_REVIEW`, or `CHANGES_REQUESTED`; otherwise the advance is rejected with `ERR_APPLICATIONS_PENDING_REVIEW`. `WAITLISTED` applications may remain.

### 3.3. Booth Assignment and Site Utility Budgets

With the festival `CURATED`, an `OperationsLead` reserves a booth for an accepted application by submitting the `application_id`, the `booth_id`, the reserved electrical draw `power_draw_amps` (at least 1), and whether the assignment `requires_water`. Creating an assignment while the festival is not `CURATED` is rejected with `ERR_FESTIVAL_NOT_ACCEPTING_ASSIGNMENTS`, and the application must be `ACCEPTED` — reserving against an application in any other state is rejected with `ERR_INVALID_STATE_TRANSITION`. The booth must be `AVAILABLE` (`ERR_BOOTH_NOT_AVAILABLE`) and in the same festival as the application (`ERR_CROSS_FESTIVAL_REFERENCE`). The draw may not exceed the booth's `power_outlet_max_amps` (`ERR_POWER_DRAW_EXCEEDS_OUTLET`, HTTP 400), and a water-requiring assignment may not land on a booth without a hookup (`ERR_WATER_HOOKUP_UNAVAILABLE`, HTTP 400). Category exclusivity applies within a zone: if any assignment in `RESERVED`, `CONFIRMED`, or `ACTIVE` already exists in the zone with the application's category, the create is rejected with `ERR_CATEGORY_EXCLUSIVITY_CONFLICT`. The assignment list filters by `festival_id`, `application_id`, `booth_id`, `zone_id`, and `status`.

Zone utility admission is inclusive at the boundary. The create is rejected with `ERR_POWER_CAPACITY_EXCEEDED` only when the zone's `reserved_power_amps` plus the new `power_draw_amps` would exceed `power_capacity_amps` — landing exactly on capacity is allowed — and with `ERR_WATER_CAPACITY_EXCEEDED` only when the assignment requires water and `reserved_water_hookups` plus one would exceed `water_hookup_total`. A successful create stamps the assignment's `festival_id` and `zone_id` from the booth's chain, flips the booth from `AVAILABLE` to `RESERVED`, and raises the zone's reserved totals; the assignment begins in `RESERVED` status with `utility_status` `PENDING`.

Confirming the assignment moves it from `RESERVED` to `CONFIRMED` and pins a fee-terms snapshot from the application's curated terms onto the assignment's `fee_model`, `flat_fee_cents`, `revenue_share_pct_bp`, `tier_mode`, `minimum_guarantee_cents`, and `free_allowance_cents`; the booth moves from `RESERVED` to `ASSIGNED`. The assignment's `status` (its lifecycle) and its `utility_status` (`PENDING` or `PROVISIONED`) are parallel dimensions that evolve independently; only activation couples them.

An assignment in `RESERVED` or `CONFIRMED` may be moved to a different booth by reassignment. The request carries the `new_booth_id` and the OCC field `expected_assignment_version` described in §2.8, and re-runs every admission check against the new booth and its zone — availability, same festival, outlet headroom, water hookup, category exclusivity, and zone power and water budgets. On success the old booth returns to `AVAILABLE`, the old zone's reserved totals decrease by the assignment's draw, the new booth is held and the new zone's totals increase, the assignment's `booth_id` and `zone_id` are refreshed, and its `version` increments by one while `status` stays put.

Utility provisioning moves `utility_status` from `PENDING` to `PROVISIONED` and is permitted only while `status` is `CONFIRMED` — otherwise `ERR_INVALID_STATE_TRANSITION`. Provisioning re-validates the zone budget, so a zone that has since filled rejects with `ERR_POWER_CAPACITY_EXCEEDED` or `ERR_WATER_CAPACITY_EXCEEDED`. Releasing an assignment from `RESERVED` or `CONFIRMED` moves it to `RELEASED`, returns the booth to `AVAILABLE`, decrements the zone's reserved totals, and runs a waitlist promotion pass for the festival and freed zone (§3.5).

### 3.4. Inspections and Opening the Gates

A `HealthInspector` records completed walk-up inspections against an assignment, supplying the `assignment_id`, the inspection `type` — `HEALTH_PREOPEN`, `HEALTH_SPOT`, or `FIRE_SAFETY` — the `result` of `PASS`, `CONDITIONAL_PASS`, or `FAIL`, and optional `notes`. An inspection is recorded with its outcome already known, so its `status` is always `COMPLETED` at creation, and its `festival_id` is denormalized from the assignment. Inspection records are immutable: they carry only `id` and `created_at` (per §2.4) and there is no update endpoint. The inspection list filters by `assignment_id`, `festival_id`, `type`, and `result`. One outcome has teeth: recording a `HEALTH_SPOT` inspection with `result` `FAIL` auto-issues a `HEALTH_VIOLATION` compliance fine of 50,000 cents (five hundred dollars) against the assignment, with `created_by_user_id` set to the literal `system` and status `ISSUED`.

Activation is the public-safety moment of the lifecycle. Moving an assignment from `CONFIRMED` to `ACTIVE` enforces three checks. Utilities must already be provisioned — `utility_status` `PENDING` yields `ERR_UTILITIES_NOT_PROVISIONED`. The latest `HEALTH_PREOPEN` inspection for the assignment — latest meaning the greatest `created_at` — must have `result` `PASS`; if no pre-open inspection exists, or the latest one is `CONDITIONAL_PASS` or `FAIL`, activation is rejected with `ERR_PREOPEN_INSPECTION_MISSING`. And the festival must be `LIVE`, otherwise `ERR_FESTIVAL_NOT_LIVE`.

Going live is itself gated. Advancing the festival from `CURATED` to `LIVE` requires that no assignment of the festival remain in `RESERVED` — every reserved assignment must have been confirmed or released first, otherwise `ERR_ASSIGNMENTS_UNCONFIRMED` — and that the logical clock has reached the festival's `event_start`; advancing early is rejected with `ERR_FESTIVAL_NOT_STARTED`.

### 3.5. Load-In Logistics and Vehicle Access Windows

Load-in is organized as bookable vehicle windows. An `OperationsLead` creates a slot with its `festival_id`, a `gate` of `GATE_A`, `GATE_B`, or `GATE_C`, the half-open window bounds `window_start` and `window_end` — the close must be strictly after the open, otherwise `ERR_INVALID_WINDOW` (HTTP 400) — and `max_vehicles`, the aggregate vehicle capacity of the window, at least 1. A slot's `reserved_vehicle_count` is the sum of `vehicle_count` over its reservations in `BOOKED` or `CHECKED_IN`. The slot list filters by `festival_id` and `gate`.

An `OperationsLead`, or the owning `Vendor`, books vehicles into a window by submitting the `assignment_id`, the `slot_id`, and the `vehicle_count` (at least 1). The slot must belong to the same festival as the assignment (`ERR_CROSS_FESTIVAL_REFERENCE`). Capacity admission is inclusive at the boundary: the booking is rejected with `ERR_SLOT_CAPACITY_EXCEEDED` only when the slot's reserved count plus the new `vehicle_count` would exceed `max_vehicles`. Two windows never overlap for the same assignment: the new reservation's slot window must be geometrically disjoint from the window of every other reservation of that assignment in `BOOKED`, `CHECKED_IN`, or `COMPLETED` — overlap exists exactly when the existing window starts before the new window ends and the new window starts before the existing window ends, under half-open semantics where adjacency (one window's close equal to the other's open) is not an overlap; a violation is rejected with `ERR_VEHICLE_WINDOW_OVERLAP`. A successful booking enters `BOOKED` and raises the slot's reserved count. The reservation list filters by `assignment_id`, `slot_id`, `festival_id`, and `status`.

Both booking and cancellation lock two hours before the window opens: once the logical clock reaches the instant 120 minutes before `window_start`, creating a reservation in that slot or cancelling an existing one is rejected with `ERR_SLOT_LOCKED`. A vendor cancelling must own the reservation's vendor (`ERR_NOT_RESOURCE_OWNER`). Cancellation moves a `BOOKED` reservation to `CANCELLED` and decrements the slot's reserved count by its `vehicle_count`.

Gate check-in moves a reservation from `BOOKED` to `CHECKED_IN` and is allowed only from `window_start` through thirty minutes after `window_end`, inclusive at both ends; outside that span the check-in is rejected with `ERR_CHECKIN_WINDOW_CLOSED`. A successful check-in stamps `checked_in_at` with the logical clock.

The operations sweep is the checkpoint that reconciles plans with reality; an `OperationsLead` or `FestivalDirector` triggers it for a festival. The sweep marks every `BOOKED` reservation whose `window_end` plus the thirty-minute grace lies strictly before the logical clock as `NO_SHOW` — a clock exactly equal to the grace boundary does not mark — and every such new no-show decrements the slot's reserved count and auto-issues a `NO_SHOW_PENALTY` fine of 25,000 cents (two hundred fifty dollars) on the reservation's assignment, recorded with `created_by_user_id` `system` in status `ISSUED`. Every `CHECKED_IN` reservation past the same strict grace boundary moves to `COMPLETED` and likewise releases its vehicles from the slot count. Every assignment of the festival still in `CONFIRMED` once the clock is past `event_start` is moved to `FORFEITED`, which returns its booth to `AVAILABLE`, decrements the zone's reserved totals, and runs waitlist promotion; the same forfeiture cascade applies when a fresh no-show's own assignment is still `CONFIRMED` past gates-open. The sweep response reports `no_shows_marked`, the `forfeited_assignment_ids`, and the `promoted_application_ids`.

Waitlist promotion runs whenever a release or forfeiture frees booth capacity, after the booth and zone effects land. A `WAITLISTED` application of the same festival is eligible only when all of the following hold: no assignment in `RESERVED`, `CONFIRMED`, or `ACTIVE` exists in the freed zone with the application's `category`; the count of the festival's `ACCEPTED` applications in that category is below `category_cap_per_category`; the application's `power_needed_amps` does not exceed the zone's remaining headroom — `power_capacity_amps` minus the post-release `reserved_power_amps`; and either the application does not require water or the zone's `reserved_water_hookups` is still below `water_hookup_total`. Eligible candidates rank by `created_at` ascending with ties broken by the vendor's `legal_name` ascending, never by identifier, and exactly one candidate — the top-ranked — moves from `WAITLISTED` to `UNDER_REVIEW`. An empty candidate set is a silent no-op, not an error.

### 3.6. Point-of-Sale Reporting and Cashless Settlement

Once the festival is `LIVE`, cashless sales flow in. A sale is reported by the owning `Vendor` or a `FinanceLead` with the `assignment_id`, the gross `amount_cents` (at least 1, otherwise `ERR_INVALID_AMOUNT`, HTTP 400), the sale instant `occurred_at`, and a client-supplied `idempotency_key`. Reporting while the festival is not `LIVE` is rejected with `ERR_FESTIVAL_NOT_LIVE`; the assignment must be `ACTIVE`, otherwise `ERR_INVALID_STATE_TRANSITION`; and `occurred_at` must lie within the festival window from `event_start` through `event_end`, inclusive at both ends, otherwise `ERR_TRANSACTION_OUT_OF_WINDOW` (HTTP 400). A new transaction enters `REPORTED` status with its `festival_id` denormalized from the assignment. Reporting is idempotent on the pair of assignment and key: a duplicate submission carrying an already-used `idempotency_key` for the same `assignment_id` returns HTTP 200 with the existing transaction and creates nothing. The transaction list filters by `assignment_id`, `festival_id`, `status`, and `idempotency_key`.

Each assignment has exactly one settlement, created by a `FinanceLead` naming the `assignment_id`; a second attempt is rejected with `ERR_SETTLEMENT_EXISTS`. Creation requires the festival to be `LIVE` or `SETTLEMENT`, otherwise `ERR_FESTIVAL_NOT_IN_SETTLEMENT`. A new settlement begins in `OPEN`. The settlement list filters by `assignment_id`, `festival_id`, and `status`.

Reconciliation moves a settlement from `OPEN` — or, after a dispute, from `DISPUTED` — to `RECONCILING` and computes the provisional variant: `provisional_gross_cents` is the sum of `amount_cents` over the assignment's transactions currently in `REPORTED`, excluding voided ones; `provisional_share_cents` is the festival share over that gross under the pinned fee terms with no fine deduction; and `provisional_payout_cents` is the provisional gross minus the provisional share, floored at zero. Reconciliation records the caller as `reconciled_by_user_id`, overwriting any previous value, and a re-reconcile from `DISPUTED` recomputes over the current `REPORTED` set so that voids and late reports since the last reconcile are reflected.

The festival share depends on the assignment's pinned `fee_model`. Under `FLAT_FEE`, it is simply the pinned `flat_fee_cents`. Under `REVENUE_SHARE`, the included transactions are walked in chronological order — sorted by `occurred_at` ascending with ties broken by `created_at` ascending, never by identifier — while a running gross of already-processed transactions is maintained. Two tier ceilings apply to the running gross: the first tier covers running gross up to and including 500,000 cents (five thousand dollars), the second covers running gross above that up to and including 2,000,000 cents (twenty thousand dollars), and the third covers anything beyond. Each tier carries a multiplier in basis points — 10,000 (a 1.0× rate) for the first tier, 15,000 (1.5×) for the second, 20,000 (2.0×) for the third — and a tier's effective rate is the pinned `revenue_share_pct_bp` multiplied by the tier multiplier and divided by 10,000, rounded half-up to a whole basis point. Under `MARGINAL` tier mode, each transaction's amount is split into portions according to where it lands on the running-gross ladder, each portion's share is that portion multiplied by its tier's effective rate and divided by 10,000, rounded half-up to whole cents, and the transaction's share is the sum of its tier portions. Under `WHOLE_TIER` mode, a single multiplier is chosen once per transaction — the tier in which the running gross sits after the transaction is added (first tier when the new running gross is at most 500,000 cents, second when at most 2,000,000, otherwise third) — and the whole transaction amount is charged at that tier's effective rate. Under `HYBRID`, the variable component is the pinned `revenue_share_pct_bp` multiplied by the excess of gross over `free_allowance_cents` (zero when gross does not exceed the allowance), divided by 10,000 and rounded half-up to whole cents; the festival share is the greater of `minimum_guarantee_cents` and `flat_fee_cents` plus the variable component — the allowance gates the variable part while the guarantee floors the total.

Per §2.7, rounding is pinned per line: every per-transaction or per-tier-portion share is rounded half-up to whole cents first, and the festival share is the sum of those rounded shares. Consider a pinned rate of 1,000 basis points (ten percent) under `MARGINAL` with three transactions of 101 cents each, all within the first tier: each transaction's share is 10.1 cents rounded half-up to 10, and the festival share is 30 cents. With amounts of 105 cents each, per-line rounding yields 11 cents per transaction for a total of 33 cents, whereas the rejected sum-then-round order would yield 32 — the pinned order is observable and must be reproduced exactly.

A vendor who disagrees with a reconciliation disputes it, moving the settlement from `RECONCILING` to `DISPUTED`; the caller must own the settlement's vendor (`ERR_NOT_RESOURCE_OWNER`) and supplies a `reason`, which is recorded as `dispute_reason`. The loop back to `RECONCILING` is another reconcile.

Finalization moves a settlement from `RECONCILING` to `FINALIZED` and is the most heavily guarded transition in the system. The segregation-of-duties screen of §2.9 applies: the caller's `X-User-ID` must differ from `reconciled_by_user_id`, otherwise `ERR_SOD_SETTLEMENT_FINALIZE`. No fine of the assignment may remain in `ISSUED` or `DISPUTED` — liability must be resolved first, otherwise `ERR_FINES_UNRESOLVED`; fines in `ACKNOWLEDGED` are allowed and will be deducted. And the logical clock must be strictly past the festival's `event_end`, otherwise `ERR_FESTIVAL_NOT_ENDED`. Finalization computes the final variant: `gross_sales_cents` includes every non-voided transaction whose `occurred_at` lies inside the festival window, including late arrivals reported after the last reconcile; `festival_share_cents` follows the pinned fee terms over that gross; `fine_deduction_cents` is the sum of `amount_cents` of the assignment's fines in `ACKNOWLEDGED` at finalize time — `WAIVED` fines are forgiven and excluded, and `PAID` fines were already collected out of band and are likewise excluded. The payout figures obey a conservation identity. Net after share is gross minus share and may be negative; the deductions actually applied are the lesser of the fine deduction and the positive part of net after share; `vendor_payout_cents` is the positive part of net after share minus the deductions applied; and `vendor_balance_due_cents` — the amount the vendor still owes the festival — is the positive part of share plus fine deductions minus gross. Consequently, gross plus balance due always equals share plus payout plus deductions applied, exactly. Finalization also sweeps every remaining `REPORTED` transaction of the assignment to `SETTLED`, records the caller as `finalized_by_user_id`, and auto-creates a `PerformanceReview` for the assignment in `PENDING` status if none exists.

A void moves a transaction from `REPORTED` to `VOIDED` and is guarded by the settlement-side OCC of §2.8: the request carries `expected_settlement_version`, a missing settlement on the assignment yields `ERR_SETTLEMENT_NOT_FOUND`, and the settlement must be in `OPEN`, `RECONCILING`, or `DISPUTED` — otherwise `ERR_INVALID_STATE_TRANSITION`. Each successful void advances the settlement's `version` by one, and when the settlement is `RECONCILING` its provisional fields are recomputed over the remaining `REPORTED` transactions.

Once finalized, a `FinanceLead` marks the settlement `PAID`. Closing the festival — advancing from `SETTLEMENT` to `CLOSED` — requires every settlement of the festival to be `PAID`, otherwise `ERR_SETTLEMENTS_OPEN`. Earlier, advancing from `LIVE` to `SETTLEMENT` requires the logical clock to be strictly past `event_end` (`ERR_FESTIVAL_NOT_ENDED`), and that advance completes every `ACTIVE` assignment of the festival: each moves to `COMPLETED`, and because `COMPLETED` is outside the reserved set, the zone's `reserved_power_amps` and `reserved_water_hookups` decrease accordingly.

### 3.7. Compliance Fines, Strikes, and Vendor Standing

Waste sorting, compost contamination, grease disposal, health, and no-show liabilities are tracked as compliance fines. A `SustainabilityOfficer` or `FestivalDirector` issues a fine with the `assignment_id`, a `type` of `WASTE_SORTING`, `COMPOST_CONTAMINATION`, `GREASE_DISPOSAL`, `HEALTH_VIOLATION`, or `NO_SHOW_PENALTY`, an `amount_cents` of at least 1 (otherwise `ERR_INVALID_AMOUNT`), and an optional free-text `description`. A fine enters `ISSUED` with `created_by_user_id` recording the issuer — or the literal `system` for auto-issued fines such as the sweep's no-show penalty and the spot-inspection failure penalty. The fine list filters by `assignment_id`, `festival_id`, `status`, and `type`.

The owning vendor responds to a fine with a `response` of `ACKNOWLEDGED` or `DISPUTED`: from `ISSUED` a fine may move to either state, and from `DISPUTED` it may later move to `ACKNOWLEDGED`; ownership is checked as usual. A `FestivalDirector` may waive a fine in `ISSUED`, `ACKNOWLEDGED`, or `DISPUTED`, moving it to `WAIVED` and recording `waived_by_user_id`; the segregation-of-duties rule of §2.9 applies, so the issuer may not waive their own fine unless the issuer is `system`. A `SustainabilityOfficer` issues fines but may never waive them — waiver is exclusive to the director role.

Collection is where fines bite. A `FinanceLead` marks an `ACKNOWLEDGED` fine `PAID`, which increments the vendor's `compliance_strikes` by one. When a vendor's strike count reaches 3 — exactly three suspends; the threshold is inclusive — the vendor moves to `SUSPENDED`, and in the same request every application of that vendor in `SUBMITTED`, `UNDER_REVIEW`, `CHANGES_REQUESTED`, or `WAITLISTED` is moved to `REJECTED` by strike contagion. A suspended vendor may not submit new applications (§3.2).

### 3.8. Performance Reviews and Return Invitations

When a settlement is finalized, the system auto-creates a performance review for the assignment in `PENDING` status, denormalizing its `festival_id` from the assignment and its `vendor_id` from the application's vendor. The review list filters by `assignment_id`, `festival_id`, `vendor_id`, and `status`.

A `VendorManager` computes the score. The `sales_percentile` ranks the assignment's final gross against its peers: the population is every assignment of the same festival whose settlement is in `FINALIZED` or `PAID` at compute time, the scored assignment included, and the percentile is one hundred times the number of population members whose final gross is strictly less than this assignment's final gross, divided by the population size, rounded half-up to an integer between 0 and 100. Because every peer's settlement is already final, the population grosses are simply read — no recursion into scoring occurs. The `compliance_component` starts at 100 and loses 15 points for each of the assignment's fines in `ISSUED`, `ACKNOWLEDGED`, or `PAID`, floored at zero. The `operations_component` is zero when the assignment ended `FORFEITED`; otherwise it starts at 100 and loses 30 points for each of the assignment's reservations in `NO_SHOW`, floored at zero. The `official_score` is the weighted blend — forty times the sales percentile plus thirty times the compliance component plus thirty times the operations component, divided by one hundred and rounded half-up to an integer from 0 to 100. The `strict_score` uses identical weights, but the compliance base is additionally reduced by 8 points per `WAIVED` fine, floored at zero: a waiver forgives money, not the incident, so identical inputs yield a lower strict score whenever waived fines exist. The official score gates return invitations; the strict score feeds suspension audits and vendor standing reviews. If the `official_score` is below 70, the review moves directly to `INELIGIBLE` rather than `SCORED`.

From `SCORED` — which implies a score of at least 70 — issuing an invitation moves the review to `INVITED`; calling for an invitation on an `INELIGIBLE` review is rejected with `ERR_SCORE_THRESHOLD_NOT_MET`. The owning vendor then answers the invitation with a `response` of `ACCEPTED` or `DECLINED`, moving the review to the corresponding terminal state, subject to the usual ownership check.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource return `200 OK`. The one nuance is idempotent sale reporting: a duplicate submission returns `200 OK` with the pre-existing transaction rather than creating anything.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/festivals` | Create a festival | FestivalDirector |
| GET | `/festivals` | List festivals | All roles |
| GET | `/festivals/{festivalId}` | Get a festival | All roles |
| POST | `/festivals/{festivalId}/advance-status` | Advance the festival lifecycle one step | FestivalDirector |
| POST | `/festivals/{festivalId}/sweep-operations` | Ops checkpoint: no-shows, forfeits, waitlist promotion | OperationsLead, FestivalDirector |
| POST | `/vendors` | Onboard a vendor | FestivalDirector, VendorManager |
| GET | `/vendors` | List vendors | FestivalDirector, VendorManager, OperationsLead, HealthInspector, SustainabilityOfficer, FinanceLead |
| GET | `/vendors/{vendorId}` | Get a vendor | All roles |
| POST | `/vendor-applications` | Submit (or resubmit via supersede) an application | Vendor |
| GET | `/vendor-applications` | List/filter applications | FestivalDirector, VendorManager, OperationsLead, FinanceLead, Vendor |
| GET | `/vendor-applications/{applicationId}` | Get an application | FestivalDirector, VendorManager, OperationsLead, FinanceLead, Vendor |
| POST | `/vendor-applications/{applicationId}/start-review` | Begin review of an application | VendorManager |
| POST | `/vendor-applications/{applicationId}/request-changes` | Request changes (bounded review rounds) | VendorManager |
| POST | `/vendor-applications/{applicationId}/decide` | Accept, reject, or waitlist with curated terms | VendorManager |
| POST | `/vendor-applications/{applicationId}/withdraw` | Owner withdraws a non-terminal application | Vendor |
| POST | `/zones` | Create a zone with utility budgets | OperationsLead |
| GET | `/zones` | List zones | All roles |
| GET | `/zones/{zoneId}` | Get a zone (incl. computed reserved totals) | All roles |
| POST | `/booths` | Create a booth in a zone | OperationsLead |
| GET | `/booths` | List booths | All roles |
| GET | `/booths/{boothId}` | Get a booth | All roles |
| POST | `/booth-assignments` | Reserve a booth for an accepted application | OperationsLead |
| GET | `/booth-assignments` | List assignments | All roles |
| GET | `/booth-assignments/{assignmentId}` | Get an assignment | All roles |
| POST | `/booth-assignments/{assignmentId}/confirm` | Confirm; pins the fee-terms snapshot | OperationsLead |
| POST | `/booth-assignments/{assignmentId}/reassign` | Move the assignment to a different booth (OCC-guarded) | OperationsLead |
| POST | `/booth-assignments/{assignmentId}/provision-utilities` | Mark utilities provisioned | OperationsLead |
| POST | `/booth-assignments/{assignmentId}/activate` | Activate after utilities, inspection, and live gates | OperationsLead |
| POST | `/booth-assignments/{assignmentId}/release` | Release; frees booth and budget, promotes waitlist | OperationsLead |
| POST | `/inspection-records` | Record a completed walk-up inspection | HealthInspector |
| GET | `/inspection-records` | List inspection records | FestivalDirector, VendorManager, OperationsLead, HealthInspector, FinanceLead, Vendor |
| GET | `/inspection-records/{inspectionId}` | Get an inspection record | FestivalDirector, VendorManager, OperationsLead, HealthInspector, FinanceLead, Vendor |
| POST | `/load-in-slots` | Create a vehicle access window | OperationsLead |
| GET | `/load-in-slots` | List load-in slots | FestivalDirector, VendorManager, OperationsLead, FinanceLead, Vendor |
| GET | `/load-in-slots/{slotId}` | Get a slot (incl. reserved vehicle count) | FestivalDirector, VendorManager, OperationsLead, FinanceLead, Vendor |
| POST | `/load-in-reservations` | Book vehicles into a slot window | OperationsLead, Vendor |
| GET | `/load-in-reservations` | List reservations | FestivalDirector, VendorManager, OperationsLead, FinanceLead, Vendor |
| GET | `/load-in-reservations/{reservationId}` | Get a reservation | FestivalDirector, VendorManager, OperationsLead, FinanceLead, Vendor |
| POST | `/load-in-reservations/{reservationId}/check-in` | Gate check-in within the window plus grace | OperationsLead |
| POST | `/load-in-reservations/{reservationId}/cancel` | Cancel a booking before the lock horizon | OperationsLead, Vendor |
| POST | `/pos-transactions` | Report a cashless sale (idempotent) | Vendor, FinanceLead |
| GET | `/pos-transactions` | List transactions | FestivalDirector, VendorManager, OperationsLead, FinanceLead, Vendor |
| GET | `/pos-transactions/{transactionId}` | Get a transaction | FestivalDirector, VendorManager, OperationsLead, FinanceLead, Vendor |
| POST | `/pos-transactions/{transactionId}/void` | Void a reported transaction (OCC on settlement) | FinanceLead |
| POST | `/settlements` | Create the single settlement for an assignment | FinanceLead |
| GET | `/settlements` | List settlements | FestivalDirector, VendorManager, FinanceLead, Vendor |
| GET | `/settlements/{settlementId}` | Get a settlement | FestivalDirector, VendorManager, FinanceLead, Vendor |
| POST | `/settlements/{settlementId}/reconcile` | Compute the provisional variant | FinanceLead |
| POST | `/settlements/{settlementId}/dispute` | Vendor disputes a reconciliation | Vendor |
| POST | `/settlements/{settlementId}/finalize` | Finalize (SoD, fines gate, post-event gate) | FinanceLead |
| POST | `/settlements/{settlementId}/mark-paid` | Mark a finalized settlement paid | FinanceLead |
| POST | `/compliance-fines` | Issue a compliance fine against an assignment | SustainabilityOfficer, FestivalDirector |
| GET | `/compliance-fines` | List fines | FestivalDirector, VendorManager, OperationsLead, SustainabilityOfficer, FinanceLead, Vendor |
| GET | `/compliance-fines/{fineId}` | Get a fine | FestivalDirector, VendorManager, OperationsLead, SustainabilityOfficer, FinanceLead, Vendor |
| POST | `/compliance-fines/{fineId}/respond` | Vendor acknowledges or disputes a fine | Vendor |
| POST | `/compliance-fines/{fineId}/waive` | Waive a non-terminal fine (SoD vs issuer) | FestivalDirector |
| POST | `/compliance-fines/{fineId}/mark-paid` | Collect a fine; strike contagion | FinanceLead |
| GET | `/performance-reviews` | List performance reviews | FestivalDirector, VendorManager, FinanceLead, Vendor |
| GET | `/performance-reviews/{reviewId}` | Get a performance review | FestivalDirector, VendorManager, FinanceLead, Vendor |
| POST | `/performance-reviews/{reviewId}/compute-score` | Compute percentile, components, and scores | VendorManager |
| POST | `/performance-reviews/{reviewId}/issue-invitation` | Invite a sufficiently scored vendor back | VendorManager |
| POST | `/performance-reviews/{reviewId}/respond` | Vendor accepts or declines the invitation | Vendor |
| POST | `/_clock/set_current_utc` | Set the logical clock (test-driving) | FestivalDirector |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_SOD_FINE_WAIVER` | 403 Forbidden |
| `ERR_SOD_SETTLEMENT_FINALIZE` | 403 Forbidden |
| `ERR_FESTIVAL_NOT_FOUND` | 404 Not Found |
| `ERR_VENDOR_NOT_FOUND` | 404 Not Found |
| `ERR_APPLICATION_NOT_FOUND` | 404 Not Found |
| `ERR_ZONE_NOT_FOUND` | 404 Not Found |
| `ERR_BOOTH_NOT_FOUND` | 404 Not Found |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_INSPECTION_NOT_FOUND` | 404 Not Found |
| `ERR_SLOT_NOT_FOUND` | 404 Not Found |
| `ERR_RESERVATION_NOT_FOUND` | 404 Not Found |
| `ERR_TRANSACTION_NOT_FOUND` | 404 Not Found |
| `ERR_SETTLEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_FINE_NOT_FOUND` | 404 Not Found |
| `ERR_REVIEW_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_AMOUNT` | 400 Bad Request |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_FESTIVAL_NOT_ACCEPTING_APPLICATIONS` | 409 Conflict |
| `ERR_FESTIVAL_NOT_ACCEPTING_ASSIGNMENTS` | 409 Conflict |
| `ERR_FESTIVAL_NOT_LIVE` | 409 Conflict |
| `ERR_FESTIVAL_NOT_IN_SETTLEMENT` | 409 Conflict |
| `ERR_FESTIVAL_NOT_CONFIGURED` | 409 Conflict |
| `ERR_APPLICATIONS_PENDING_REVIEW` | 409 Conflict |
| `ERR_ASSIGNMENTS_UNCONFIRMED` | 409 Conflict |
| `ERR_SETTLEMENTS_OPEN` | 409 Conflict |
| `ERR_FESTIVAL_NOT_STARTED` | 409 Conflict |
| `ERR_FESTIVAL_NOT_ENDED` | 409 Conflict |
| `ERR_VENDOR_SUSPENDED` | 409 Conflict |
| `ERR_CROSS_FESTIVAL_REFERENCE` | 409 Conflict |
| `ERR_SUPERSEDE_SOURCE_INVALID` | 409 Conflict |
| `ERR_SETTLEMENT_EXISTS` | 409 Conflict |
| `ERR_FINES_UNRESOLVED` | 409 Conflict |
| `ERR_PREOPEN_INSPECTION_MISSING` | 409 Conflict |
| `ERR_UTILITIES_NOT_PROVISIONED` | 409 Conflict |
| `ERR_SLOT_LOCKED` | 409 Conflict |
| `ERR_CHECKIN_WINDOW_CLOSED` | 409 Conflict |
| `ERR_TRANSACTION_OUT_OF_WINDOW` | 400 Bad Request |
| `ERR_INVALID_WINDOW` | 400 Bad Request |
| `ERR_CATEGORY_EXCLUSIVITY_CONFLICT` | 409 Conflict |
| `ERR_CATEGORY_CAP_REACHED` | 409 Conflict |
| `ERR_BOOTH_NOT_AVAILABLE` | 409 Conflict |
| `ERR_POWER_DRAW_EXCEEDS_OUTLET` | 400 Bad Request |
| `ERR_WATER_HOOKUP_UNAVAILABLE` | 400 Bad Request |
| `ERR_POWER_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_WATER_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_SLOT_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_VEHICLE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_REVIEW_ROUND_LIMIT` | 409 Conflict |
| `ERR_FEE_TERMS_INCOMPLETE` | 400 Bad Request |
| `ERR_SCORE_THRESHOLD_NOT_MET` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_STALE_SETTLEMENT_VERSION` | 412 Precondition Failed |
