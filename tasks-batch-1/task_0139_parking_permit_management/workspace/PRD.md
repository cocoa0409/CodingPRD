# Parking & Permit Management API — Product Requirements Document

## 1. Introduction

This document specifies the Parking & Permit Management API, a backend service for operating gated parking facilities end to end. The platform models a facility's physical inventory — garages, parking zones, and individual stalls — alongside the commercial and regulatory machinery that sits on top of it: transient hourly billing, monthly permit programs with bounded capacity and ordered waitlists, merchant-funded validation discounts, dynamic event surcharges, and license-plate-recognition (LPR) enforcement that produces citations and an appeals process.

The system serves four distinct constituencies whose concerns frequently collide. Facility administrators manage inventory, rate schedules, and the permit lifecycle; motorists request permits, wait for capacity, and contest fines; merchants subsidize parking through validations drawn from a finite budget; and enforcement officers run camera-driven compliance and adjudicate appeals. Because a single physical stall, a single permit slot, and a single merchant budget are all scarce resources contended for by independent actors, the API treats allocation, pricing, and concurrency control as first-class concerns rather than incidental details. Every mutation is atomic, derived counts and balances are recomputed synchronously within the same request, and stale-read conflicts on contended capacity are surfaced explicitly rather than silently lost.

This specification defines the global contract (authentication, response envelope, pagination, and cross-cutting consistency rules), the business workflows that govern each entity's lifecycle, the complete endpoint surface, and the catalogue of error conditions. Times are stored and compared in UTC throughout; a facility's local timezone is carried only for display.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated with two mandatory HTTP headers. `X-User-ID` identifies the acting principal, and `X-User-Role` declares the capacity in which they act. If either header is missing, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly four roles: `FacilityAdmin`, `Motorist`, `Merchant`, and `EnforcementOfficer`.

- A `FacilityAdmin` owns the facility: garage inventory, zones, spaces, rate plans, event pricing, the full permit lifecycle, gate sessions, and waitlist promotion. When `X-User-Role` is `FacilityAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit but never compares it to any entity's `id`, and a `FacilityAdmin` is never subject to resource-ownership checks.
- When `X-User-Role` is `EnforcementOfficer`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity. An `EnforcementOfficer` operates LPR enforcement, issues citations, and decides appeals; the server may record the identifier but does not compare it to any entity's `id`.
- When `X-User-Role` is `Motorist`, `X-User-ID` is the `id` of the acting `Motorist`. Ownership checks on any resource that references a `Motorist` compare the resource's `motorist_id` to `X-User-ID`. This applies to a motorist acting on their own permits, waitlist entries, appeals, sessions, and to paying their own citations.
- When `X-User-Role` is `Merchant`, `X-User-ID` is the `id` of the acting `Merchant`. Ownership checks on a `Validation` compare the validation's `merchant_id` to `X-User-ID`.

When a `Motorist` or a `Merchant` targets a resource they do not own, the request is rejected with `ERR_NOT_RESOURCE_OWNER`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0. A `limit` below 1 or above 100, or an `offset` below 0, is rejected with `ERR_PAGINATION_INVALID`.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order. The single documented exception is the per-zone waitlist listing, which is ordered by `sequence` ascending so that earlier-joined motorists appear first.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Identifiers

Every primary resource carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp expressed as an ISO 8601 UTC instant with three fractional digits. Most resources additionally carry two system-managed fields: `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, and `version`, an integer that begins at its initial value and increments by one on every mutation. Recomputation of a derived field — for example, refreshing a garage's `occupied_count` or a zone's `permits_active_count` — is itself a mutation that refreshes `updated_at` and increments `version` on the affected resource.

`PlateRead` is the sole exception: an LPR read is immutable once recorded, so a `PlateRead` carries only `id` and `created_at`. It has no `updated_at` field and no `version` field. Every other entity in the system — `Garage`, `Zone`, `Space`, `RatePlan`, `EventPricing`, `Permit`, `PermitWaitlistEntry`, `Motorist`, `AccessSession`, `Validation`, `Merchant`, `Citation`, and `Appeal` — carries the full set of `id`, `created_at`, `updated_at`, and `version`.

### 2.5. Nested Resource Retrieval and Referential Existence

Many read endpoints address a resource through a parent path segment, such as listing the zones of a garage or the spaces of a zone. For any request whose path contains a resource identifier, the system validates each identifier left to right and rejects the first one that does not resolve to an existing resource with `ERR_NOT_FOUND`. The same existence check governs foreign keys supplied in the request body: after path identifiers are confirmed, each referenced body identifier is validated, and a dangling reference is rejected with `ERR_NOT_FOUND`. This existence pass runs after authentication and authorization but before any state or business-rule evaluation.

### 2.6. Monetary Values, Durations, and Precision

All monetary amounts in the system are integer cents — rates, caps, fees, fines, discounts, balances, and budgets alike — and are returned as integers. There are no fractional-cent representations. Where a calculation introduces a multiplier (event pricing or fine escalation), the intermediate product is rounded to the nearest whole cent using the round-half-up convention, and only at that single multiplier step. Counts of billable time blocks — started hours and 24-hour day blocks — are always rounded up to the next whole block. Discount steps that divide (a percentage discount) round down to the nearest whole cent. These precision rules are restated alongside each calculation in §3 so they are unambiguous at the point of use.

Durations are measured in whole minutes between two UTC instants. The constants that govern block arithmetic are sixty minutes to an hour and one thousand four hundred forty minutes to a 24-hour day.

### 2.7. Synchronous Consistency and Cascading Side Effects

All mutations are atomic within a single request, and every derived field is recomputed synchronously in the same transaction that triggers it. Three derived counters and one balance are maintained this way and must never drift from their defining queries:

- A garage's `total_space_count` is the number of `Space` rows whose `zone_id` resolves into that garage, regardless of stall status, and its `occupied_count` is the number of those spaces whose `is_occupied` is true. The garage's `occupied_count` is recomputed on every session open (incremented) and on every session close or void (decremented).
- A zone's `permits_active_count` is the number of `Permit` rows in that zone whose `status` is `ACTIVE`. It is recomputed on every permit activation (which raises it by one), revocation, and expiry (each of which lowers it by one).
- A space's `is_occupied` is true exactly when an `AccessSession` with `status` `OPEN` currently references that space, and false otherwise.
- A motorist's `outstanding_balance_cents` is the sum of `amount_due_cents` across that motorist's citations whose `status` is `ISSUED` or `UPHELD`. It is recomputed on every citation issuance and on every appeal resolution or payment that changes a citation's status.

When a single operation mutates more than one entity, each affected entity independently has its `updated_at` refreshed and its `version` incremented. The specific cascades — waitlist promotion on freed capacity, validation redemption and merchant-budget debit on session exit, and the appeal-to-citation-to-balance chain — are detailed in §3 at the workflow that drives them.

### 2.8. Optimistic Concurrency Control on Contended Capacity

Two operations contend for resources that other writers can advance between a client's read and its write, and both therefore require an optimistic-concurrency token in the request body.

Activating a permit consumes one of a zone's finite capacity slots. The activation request must carry `expected_zone_version` holding the client's last observed `version` of the target permit's zone. A zone's `version` advances every time a permit it holds is activated, revoked, or expired, because each of those recomputes `permits_active_count`. If `expected_zone_version` does not equal the zone's current `version` — meaning another writer has changed the zone's capacity picture since the client last read it — the activation is rejected with `ERR_STALE_ZONE_VERSION` and an HTTP 412 status, preventing the client from acting on a stale view of remaining capacity.

Paying a citation requires `expected_citation_version` holding the client's last observed `version` of the citation being paid. If it does not equal the citation's current `version`, the payment is rejected with `ERR_STALE_ZONE_VERSION` (HTTP 412). Endpoints not named here do not accept a version field and perform no concurrency check.

### 2.9. Validation Ordering

Any request whose body is malformed, omits a required field, or supplies an invalid enum value is rejected with `ERR_INVALID_REQUEST` (HTTP 400) as a baseline well-formedness check.

When several checks guard one endpoint, they are evaluated in a fixed priority order so that the rejection a client receives is deterministic. Authentication (`ERR_UNAUTHENTICATED`) is checked first, then authorization by role (`ERR_UNAUTHORIZED`), then existence of every referenced resource (`ERR_NOT_FOUND`), then whether the target is in a state that permits the requested transition (`ERR_INVALID_STATE`), then resource ownership for motorist- and merchant-owned mutations (`ERR_NOT_RESOURCE_OWNER`). Only after these structural checks pass does the system evaluate domain-specific business constraints — zone-type eligibility, uniqueness, validation redeemability, event-window well-formedness, stall occupancy, gate admission, permit capacity, merchant budget, and finally the optimistic-concurrency token. The effect of this ordering is that, for example, a request against a non-existent resource always yields `ERR_NOT_FOUND` even if it would also have violated a business rule, and a state violation surfaces before a capacity or concurrency conflict.

## 3. Business Logic & Workflows

### 3.1. Facility Inventory: Garages, Zones, and Spaces

A `FacilityAdmin` establishes a facility by creating a **garage**, supplying a human-readable `name`. The garage optionally takes a `timezone` — an IANA timezone name used purely for display, defaulting to `UTC` when omitted — and a `gate_mode`, which controls entry admission policy and defaults to `PERMIT_OR_TRANSIENT`. The garage's `total_space_count` and `occupied_count` are computed fields that begin at zero and track inventory as spaces and sessions come and go. The `gate_mode` may later be changed by updating the garage, which takes effect for subsequent entry attempts; the legal values are `PERMIT_OR_TRANSIENT`, `PERMIT_ONLY`, and `CLOSED`.

Within a garage, the administrator carves out **zones**. A zone is created against its garage by supplying the `garage_id`, a short `code` that must be unique among the zones of that garage, a `zone_type`, a `permit_capacity`, and the `rate_plan_id` of the transient rate schedule that applies to sessions parked there. The `zone_type` is one of `TRANSIENT`, `PERMIT`, or `MIXED`, and governs what may park there: a `TRANSIENT` zone admits only pay-as-you-go parkers, a `PERMIT` zone admits only permit holders, and a `MIXED` zone admits both. The `permit_capacity` is the maximum number of `ACTIVE` permits the zone may hold and must be zero or greater; a capacity of zero disallows permits entirely. The zone's `permits_active_count` is computed and starts at zero. Creating a zone whose `code` collides with an existing zone in the same garage is rejected with `ERR_DUPLICATE`.

Each zone is subdivided into physical **spaces**. A space is created by supplying its `zone_id` and a `label` that must be unique within that zone, and optionally a `status` that defaults to `AVAILABLE`; the only other status value is `OUT_OF_SERVICE`. A space additionally exposes a computed `is_occupied` flag, which defaults to false and is true exactly while an `OPEN` session references it. Creating a space whose `label` duplicates another in the same zone is rejected with `ERR_DUPLICATE`, and each space creation recomputes the owning garage's `total_space_count`.

### 3.2. Rate Plans and Event Pricing

Transient billing is parameterized by a **rate plan**, created by a `FacilityAdmin` with a `name`, an `hourly_cents` rate charged for each started hour, a `daily_cap_cents` ceiling that bounds accrual within any 24-hour block, a `monthly_permit_cents` flat fee charged when a permit on a zone bound to this plan is activated, and an optional `grace_minutes` free-leading-minutes allowance that defaults to fifteen minutes. All four cents amounts and the grace allowance must be zero or greater.

Dynamic surcharges are expressed as **event pricing** windows attached to a garage. A `FacilityAdmin` creates a window by supplying the `garage_id`, a `name`, a `window_start_utc` (inclusive), a `window_end_utc` (exclusive), a `flat_surcharge_cents` amount, and an optional `multiplier` that defaults to 1.0 and must be at least 1.0. The half-open interval runs from `window_start_utc` up to but not including `window_end_utc`; creation requires `window_end_utc` to fall strictly after `window_start_utc`, and a window that does not satisfy this is rejected with `ERR_EVENT_WINDOW_OVERLAP`. A newly created window has `status` `DRAFT` and is ignored by pricing. Publishing the window moves its `status` to `PUBLISHED` so it begins pricing sessions; the only legal `status` values are `DRAFT` and `PUBLISHED`. Publishing is rejected with `ERR_EVENT_WINDOW_OVERLAP` if the window's half-open interval overlaps that of any other already-`PUBLISHED` window for the same garage. The surcharge applies to transient sessions whose entry falls inside a published window, as detailed in §3.6.

### 3.3. The Permit Lifecycle and Zone Capacity

Before a person can request a permit, they must exist as a **motorist** in the system. A motorist is registered — either self-service by a `Motorist` or on their behalf by a `FacilityAdmin` — with a `full_name`, an `email` that must be globally unique (a collision is rejected with `ERR_DUPLICATE`), and a normalized `default_plate`. A motorist also carries a computed `outstanding_balance_cents` that begins at zero and tracks unpaid fines as described in §3.9.

Permits move through a branching lifecycle. A `Motorist` requests a permit by supplying the `zone_id` of the permit zone, their `motorist_id`, and the `plate` — a normalized license plate, uppercased with spaces removed — that the permit will be bound to. The new permit is created in `REQUESTED` status; its `status` is one of `REQUESTED`, `ACTIVE`, `REVOKED`, `EXPIRED`, or `REJECTED`. The fields `valid_from_utc`, `valid_until_utc`, and `monthly_fee_charged_cents` are computed and remain unset (the fee defaulting to zero) until activation.

A `FacilityAdmin` decides each requested permit. Activation, which transitions a permit from `REQUESTED` to `ACTIVE`, is the gatekeeping operation for zone capacity and is governed by three preconditions evaluated against the structural ordering of §2.9. First, the permit must currently be in `REQUESTED` status, or the request is rejected with `ERR_INVALID_STATE`. Second, the permit's zone must have a `zone_type` of either `PERMIT` or `MIXED`; a permit cannot be activated in a `TRANSIENT` zone, and an attempt is rejected with `ERR_ZONE_TYPE_FORBIDDEN`. Third, the zone's `permits_active_count` must be strictly less than its `permit_capacity`; if the count has already reached or would reach the capacity, the activation is rejected with `ERR_ZONE_AT_CAPACITY`. The same capacity check (strictly-less-than) and the same `ERR_ZONE_AT_CAPACITY` rejection also guard waitlist promotion described below. Activation additionally requires the optimistic-concurrency token `expected_zone_version` as specified in §2.8.

On successful activation, the permit's `status` becomes `ACTIVE`, its `valid_from_utc` is set to the current clock instant, its `valid_until_utc` is set to thirty days after `valid_from_utc`, and its `monthly_fee_charged_cents` is set to a snapshot of the `monthly_permit_cents` of the rate plan bound to the permit's zone. The zone's `permits_active_count` is incremented by one, and because that recomputation mutates the zone, the zone's `version` advances — which is precisely what later activations test against via `expected_zone_version`.

A `FacilityAdmin` may instead reject a still-`REQUESTED` permit, moving it from `REQUESTED` to `REJECTED`; this requires only that the permit be in `REQUESTED` status, failing otherwise with `ERR_INVALID_STATE`. An administrator may revoke an `ACTIVE` permit, moving it from `ACTIVE` to `REVOKED`; this requires the permit to be `ACTIVE`, again rejecting with `ERR_INVALID_STATE` otherwise. Revocation lowers the zone's `permits_active_count` by one and, because a slot has been freed, triggers the waitlist promotion cascade described in §3.4. The terminal states `REVOKED`, `EXPIRED`, and `REJECTED` admit no further transitions.

Permit expiry is driven by a system sweep that a `FacilityAdmin` invokes per permit. The sweep expires an `ACTIVE` permit — moving it from `ACTIVE` to `EXPIRED` — only when the current clock instant is at or after the permit's `valid_until_utc`; a permit that has not yet reached its expiry instant is left untouched. Expiry, like revocation, lowers the zone's `permits_active_count` by one and triggers the same waitlist promotion cascade. The current clock instant referenced throughout permit expiry, validation redemption, and LPR evaluation is settable by a `FacilityAdmin` through an administrative test-driving capability that fixes the server's notion of current UTC to a supplied `to_iso8601` instant.

### 3.4. Permit Waitlists and the Promotion Cascade

When a permit zone is full, a `Motorist` may join its **waitlist**. A waitlist entry is created against a zone by supplying the `motorist_id` and the `plate` to bind to the eventual permit. The entry receives `status` `WAITING` and a `sequence` — a monotonically increasing per-zone insertion index assigned by the server at creation, where a lower value means an earlier position and ties are impossible by construction. The system permits at most one `WAITING` entry per combination of zone and motorist; a second concurrent `WAITING` entry for the same motorist in the same zone is rejected with `ERR_DUPLICATE`. A waitlist entry's `status` is one of `WAITING`, `PROMOTED`, or `CANCELLED`, and its `promoted_permit_id` is computed, populated only on promotion. A `Motorist` may cancel their own `WAITING` entry, moving it from `WAITING` to `CANCELLED`; this requires the entry to be `WAITING` and the acting motorist to own it, failing with `ERR_INVALID_STATE` or `ERR_NOT_RESOURCE_OWNER` respectively.

Promotion off the waitlist happens in two ways that share identical effects. It occurs automatically as a cascade whenever a permit revocation or expiry frees a capacity slot, and it can also be driven manually by a `FacilityAdmin` operator action that promotes the lowest-sequence waiting entry if capacity is free; the manual action is idempotent and safe to retry. In either case, promotion selects the `WAITING` entry with the lowest `sequence` for the zone, and proceeds only when that entry is genuinely the lowest-sequence waiter and the zone's `permits_active_count` is below its `permit_capacity`. Promotion creates a brand-new `Permit` in `REQUESTED` status, copying the entry's `zone_id`, `motorist_id`, and `plate` onto it; sets the entry's `status` to `PROMOTED`; and records the new permit's id in the entry's `promoted_permit_id`. Crucially, promotion does not itself activate the new permit — it only creates a `REQUESTED` permit. A `FacilityAdmin` must still activate that permit, and it is the activation, not the promotion, that re-consumes the freed slot and re-advances the zone's `permits_active_count` and `version`.

### 3.5. Gate Admission and Access Sessions

A vehicle's stay is modeled as an **access session**, opened at the entry gate by a `FacilityAdmin` on behalf of the gate hardware. Entry is requested with the `garage_id`, the `plate` read at the gate, the `entry_at_utc` instant the gate reports, and an optional `permit_id`. The server, not the client, assigns the stall: it selects an `AVAILABLE` and unoccupied space in an eligible zone per its selector policy and records the chosen `space_id`. The server also classifies the session's `session_kind` at entry and fixes it for the life of the session: a session is `PERMIT` when admitted under a valid permit and `TRANSIENT` otherwise. A new session has `status` `OPEN`; its `status` is one of `OPEN`, `CLOSED`, or `VOIDED`. The computed fields `exit_at_utc`, `gross_charge_cents`, and `net_charge_cents` remain unset (the charges defaulting to zero) until exit.

Admission is governed by several business checks. Gate-mode policy is decisive: when the garage's `gate_mode` is `CLOSED`, every entry is rejected with `ERR_GATE_CLOSED`, and when it is `PERMIT_ONLY`, an entry whose plate has no valid `ACTIVE` permit is likewise rejected with `ERR_GATE_CLOSED`. Zone-type policy applies symmetrically to the permit case: a transient session may only park in a zone whose `zone_type` is `TRANSIENT` or `MIXED`, and an attempt to admit a transient parker into a permit-only zone is rejected with `ERR_ZONE_TYPE_FORBIDDEN`. Stall availability is enforced as well: if no `AVAILABLE` and unoccupied space remains in an eligible zone — that is, the stall the gate would assign is already held by a time-overlapping `OPEN` occupation — the entry is rejected with `ERR_SPACE_OCCUPIED`. On successful entry, the chosen space's `is_occupied` becomes true and the garage's `occupied_count` is recomputed upward by one.

Exit closes the session. A `FacilityAdmin` submits the `exit_at_utc` instant and, optionally, a `validation_id` to redeem a merchant validation. Exit requires the session to be `OPEN`, rejecting otherwise with `ERR_INVALID_STATE`, and requires `exit_at_utc` to fall strictly after the session's `entry_at_utc`, rejecting otherwise with `ERR_INVALID_TIME_RANGE`. If a `validation_id` is supplied, the validation must be redeemable: its `status` must be `ISSUED`, the `exit_at_utc` must fall strictly before the validation's `expires_at_utc`, and the validation's `garage_id` must match the session's garage; any failure rejects the exit with `ERR_VALIDATION_NOT_REDEEMABLE`. On a successful exit the session's `exit_at_utc` is recorded, `gross_charge_cents` is computed per §3.6, `net_charge_cents` is computed per §3.7, the session's `status` becomes `CLOSED`, the space's `is_occupied` becomes false, and the garage's `occupied_count` is recomputed downward by one. A `FacilityAdmin` may instead void an `OPEN` session — a gate-error correction — moving it from `OPEN` to `VOIDED` (rejecting with `ERR_INVALID_STATE` if it is not `OPEN`); voiding likewise frees the space and decrements the garage's `occupied_count` but computes no charges. The terminal states `CLOSED` and `VOIDED` admit no further transitions.

### 3.6. Transient Charge Computation

The metered charge recorded in a session's `gross_charge_cents` is computed at exit and depends entirely on the session's `session_kind`. A `PERMIT` session is always billed zero, regardless of how long the vehicle stayed, because the monthly permit fee already covers it. A `TRANSIENT` session runs the full metered pipeline below, using the rate plan bound to the zone the session parked in.

The pipeline begins from the stay's duration, the whole number of minutes from `entry_at_utc` to `exit_at_utc` (which is always strictly positive because exit must follow entry). If the duration is at or below the rate plan's `grace_minutes`, the charge is exactly zero and computation stops; grace does not subtract time from longer stays, it only zeroes out sub-grace visits. Otherwise the system counts billable hours by taking the duration in minutes, dividing by sixty, and rounding up to the next whole hour — every started hour is billed. The base metered amount is that billable-hour count multiplied by the rate plan's `hourly_cents`.

An event surcharge is layered on next, but only when exactly one published event window applies. Among the garage's `PUBLISHED` event-pricing windows, the system selects the single window whose half-open interval from `window_start_utc` up to `window_end_utc` contains the session's `entry_at_utc`; if more than one qualifies, it chooses the one with the latest `window_start_utc`, breaking any remaining tie by earliest `created_at`. When such a window applies, the metered amount is multiplied by the window's `multiplier` and the product is rounded to the nearest whole cent using round-half-up — this multiplier step is the only place rounding occurs in the pipeline.

The daily cap is applied after the multiplier. The system counts cap blocks by taking the duration in minutes, dividing by one thousand four hundred forty, and rounding up to the next whole 24-hour block, then caps the metered amount at that block count multiplied by the rate plan's `daily_cap_cents` — the metered amount becomes the smaller of its current value and the cap. Finally, if an event window applied, the window's `flat_surcharge_cents` is added once, after the cap rather than before it. The resulting integer is the session's `gross_charge_cents`.

### 3.7. Merchant Validations and the Discount Calculation

Merchants subsidize parking through **validations** drawn from a finite budget. A `FacilityAdmin` enrolls a `Merchant` into a garage with a `garage_id`, a `name`, and an initial `validation_budget_cents` that is zero or greater. A `Merchant` then issues a `Validation` by supplying the `garage_id` where it may be redeemed, their own `merchant_id`, a `discount_kind`, a `discount_value`, and an `expires_at_utc` after which it is unusable. The `discount_kind` is one of `FLAT_CENTS`, `PERCENT`, or `FREE_HOURS`, and `discount_value` is interpreted accordingly: cents for `FLAT_CENTS`, a whole percentage from zero to one hundred for `PERCENT`, and whole hours for `FREE_HOURS`. A validation begins with `status` `ISSUED` and becomes `REDEEMED` once consumed; it is single-use, and those are its only two status values. Issuing a validation when the merchant's `validation_budget_cents` is zero is rejected with `ERR_MERCHANT_BUDGET_EXHAUSTED`.

The discount is computed at session exit only for `TRANSIENT` sessions that supply a redeemable `validation_id`, and operates on the `gross_charge_cents` produced in §3.6. The raw discount depends on the kind: a `FLAT_CENTS` validation yields its `discount_value` directly; a `PERCENT` validation yields the gross multiplied by `discount_value` divided by one hundred, rounded down to the nearest whole cent; and a `FREE_HOURS` validation yields `discount_value` multiplied by the zone rate plan's `hourly_cents`. The applied discount is then the smallest of three quantities: the raw discount, the gross charge, and the merchant's remaining `validation_budget_cents` — a merchant can never grant more than its budget, and the discount can never exceed the charge. The session's `net_charge_cents` is the gross charge minus the applied discount, which is at least zero by construction. When the applied discount is greater than zero, the validation's `status` is set to `REDEEMED` and the merchant's `validation_budget_cents` is debited by exactly the applied amount — this redemption-and-debit cascade runs only for transient sessions that actually applied a discount. If the raw discount would have exceeded the merchant's remaining budget, the applied amount is clipped to that budget and the net charge is correspondingly higher than the nominal discount would have produced.

### 3.8. LPR Enforcement and Plate Reads

Compliance is driven by **plate reads** submitted by an `EnforcementOfficer`. A read is recorded with the `garage_id`, the normalized `plate` the camera reported, the `zone_id` the camera observed the vehicle in, and the `read_at_utc` instant of the read. The server then evaluates the read and records two computed outcomes on it: `enforcement_outcome`, one of `COMPLIANT`, `VIOLATION_NO_PERMIT`, `VIOLATION_EXPIRED_PERMIT`, or `VIOLATION_WRONG_ZONE`; and `matched_permit_id`, the id of the permit that explains the outcome, or null. A `PlateRead` is immutable after creation and therefore carries no `updated_at` or `version`.

The evaluation follows a fixed resolution order that short-circuits at the first match. First, if there is an `OPEN` access session in the read's garage for the same plate, the outcome is `COMPLIANT` with a null `matched_permit_id` — a transient parker mid-stay is compliant even without a permit. Otherwise, the system looks for an `ACTIVE` permit bound to the same plate in the read's own zone: if one exists and the current clock instant is at or after its `valid_until_utc` (a defensive check for a permit that should already have expired) the outcome is `VIOLATION_EXPIRED_PERMIT` with that permit's id; if one exists and is still within its validity window the outcome is `COMPLIANT` with that permit's id. If no in-zone permit matches, the system looks for an `ACTIVE` permit bound to the plate in a different zone of the same garage; if one exists, the outcome is `VIOLATION_WRONG_ZONE` with that out-of-zone permit's id. If none of the above matches — no open session and no active permit anywhere in the garage — the outcome is `VIOLATION_NO_PERMIT` with a null `matched_permit_id`.

### 3.9. Citations, Fine Escalation, and Appeals

When enforcement establishes a violation, an `EnforcementOfficer` issues a **citation** from the offending read by supplying the `garage_id`, the cited `plate`, the `plate_read_id` of the triggering read, a `violation_code`, and a `base_fine_cents`. The `violation_code` is one of `NO_PERMIT`, `EXPIRED_PERMIT`, `WRONG_ZONE`, or `OVERSTAY`. At issue time the server resolves the citation's `motorist_id` from the plate if a matching motorist exists (otherwise null), computes the escalated `amount_due_cents`, snapshots the `prior_citation_count`, and sets the citation's `status` to `ISSUED`. A citation's `status` is one of `ISSUED`, `UPHELD`, `DISMISSED`, or `PAID`.

The fine escalates by repeat-offender history. At issue time the server counts the prior citations for the same plate whose `status` is `ISSUED` or `UPHELD` — excluding `DISMISSED` and `PAID` — and records that count as `prior_citation_count`. The escalation multiplier tiers on that prior count: zero priors apply a multiplier of 1.00, exactly one prior applies 1.50, exactly two priors apply 2.00, and three or more priors apply 3.00, with the ceiling locked at 3.00 from the third prior onward. The `amount_due_cents` is the `base_fine_cents` multiplied by the applicable multiplier, rounded to the nearest whole cent using round-half-up. A first offense therefore leaves the amount equal to the base fine, while a repeat offender's amount is escalated by the tiered multiplier. Issuing a citation recomputes the cited motorist's `outstanding_balance_cents`, since the new `ISSUED` citation now counts toward it.

A `Motorist` may pay one of their own citations that is in either `ISSUED` or `UPHELD` status, moving it to `PAID`; the request must carry `expected_citation_version` per §2.8, the citation must be in one of those two states (failing with `ERR_INVALID_STATE` otherwise), and the acting motorist must own the citation. Payment recomputes the motorist's `outstanding_balance_cents`, removing the now-`PAID` citation from the sum.

A `Motorist` may instead contest a citation by submitting an **appeal** against it, supplying the `citation_id`, their `motorist_id`, and a free-text `reason`. The appeal is created in `SUBMITTED` status; its `status` is one of `SUBMITTED`, `UPHELD`, or `DISMISSED`. An `EnforcementOfficer` decides the appeal by supplying a `decision`, which drives a fork that cascades into the citation and the motorist's balance. Deciding requires the appeal to be `SUBMITTED` and its linked citation to still be `ISSUED`. When the decision upholds the appeal, the appeal moves from `SUBMITTED` to `UPHELD`, and as a cascade the linked citation transitions from `ISSUED` to `DISMISSED`; because a dismissed citation no longer counts, the motorist's `outstanding_balance_cents` is recomputed downward, dropping that citation's `amount_due_cents` from the sum. When the decision dismisses the appeal, the appeal moves from `SUBMITTED` to `DISMISSED`, and the linked citation transitions from `ISSUED` to `UPHELD`; the citation still stands, so the motorist's balance is unchanged. The citation states `DISMISSED` and `PAID` are terminal, as are the appeal states `UPHELD` and `DISMISSED`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including every state transition and the administrative clock and promotion actions — return a `200 OK` status code. Each endpoint's request body, response body, and side effects must be reconstructed from the workflow narratives in §3; the table below summarizes only the method, path, purpose, and authorized roles.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/parking/garages` | Create a garage | FacilityAdmin |
| GET | `/parking/garages/{id}` | Read a garage | FacilityAdmin, EnforcementOfficer, Merchant, Motorist |
| PATCH | `/parking/garages/{id}` | Update garage gate mode | FacilityAdmin |
| GET | `/parking/garages/{id}/zones` | List a garage's zones | FacilityAdmin, EnforcementOfficer, Merchant, Motorist |
| GET | `/parking/garages/{id}/event-pricing` | List a garage's event-pricing windows | FacilityAdmin, EnforcementOfficer |
| GET | `/parking/garages/{id}/merchants` | List merchants enrolled in a garage | FacilityAdmin |
| GET | `/parking/garages/{id}/sessions` | List a garage's access sessions | FacilityAdmin, EnforcementOfficer |
| GET | `/parking/garages/{id}/citations` | List a garage's citations | FacilityAdmin, EnforcementOfficer |
| GET | `/parking/garages/{id}/validations` | List validations redeemable at a garage | FacilityAdmin, Merchant |
| GET | `/parking/garages/{id}/plate-reads` | List a garage's plate reads | FacilityAdmin, EnforcementOfficer |
| POST | `/parking/zones` | Create a zone in a garage | FacilityAdmin |
| GET | `/parking/zones/{id}` | Read a zone | FacilityAdmin, EnforcementOfficer, Merchant, Motorist |
| GET | `/parking/zones/{id}/spaces` | List a zone's spaces | FacilityAdmin, EnforcementOfficer |
| GET | `/parking/zones/{id}/permits` | List a zone's permits | FacilityAdmin, EnforcementOfficer |
| GET | `/parking/zones/{id}/waitlist` | List a zone's waitlist entries, ordered by sequence | FacilityAdmin, Motorist |
| POST | `/parking/zones/{id}/waitlist` | Add a waitlist entry for a permit zone | Motorist |
| POST | `/parking/zones/{id}/promote-waitlist` | Promote the lowest-sequence waiting entry if capacity is free | FacilityAdmin |
| GET | `/parking/zones/{id}/plate-reads` | List plate reads observed in a zone | FacilityAdmin, EnforcementOfficer |
| GET | `/parking/waitlist-entries/{id}` | Read a waitlist entry | FacilityAdmin, Motorist |
| POST | `/parking/waitlist-entries/{id}/cancel` | Cancel a waiting waitlist entry | Motorist |
| POST | `/parking/spaces` | Create a space in a zone | FacilityAdmin |
| GET | `/parking/spaces/{id}` | Read a space | FacilityAdmin, EnforcementOfficer |
| GET | `/parking/spaces/{id}/sessions` | List sessions that referenced a space | FacilityAdmin, EnforcementOfficer |
| POST | `/parking/rate-plans` | Create a rate plan | FacilityAdmin |
| GET | `/parking/rate-plans/{id}` | Read a rate plan | FacilityAdmin, EnforcementOfficer, Merchant, Motorist |
| GET | `/parking/rate-plans/{id}/zones` | List zones bound to a rate plan | FacilityAdmin, EnforcementOfficer |
| POST | `/parking/event-pricing` | Create a draft event-pricing window | FacilityAdmin |
| GET | `/parking/event-pricing/{id}` | Read an event-pricing window | FacilityAdmin, EnforcementOfficer |
| POST | `/parking/event-pricing/{id}/publish` | Publish a draft event-pricing window | FacilityAdmin |
| POST | `/parking/motorists` | Register a motorist | FacilityAdmin, Motorist |
| GET | `/parking/motorists/{id}` | Read a motorist | FacilityAdmin, EnforcementOfficer, Motorist |
| GET | `/parking/motorists/{id}/permits` | List a motorist's permits | FacilityAdmin, Motorist |
| GET | `/parking/motorists/{id}/waitlist-entries` | List a motorist's waitlist entries | FacilityAdmin, Motorist |
| GET | `/parking/motorists/{id}/citations` | List a motorist's citations | FacilityAdmin, EnforcementOfficer, Motorist |
| GET | `/parking/motorists/{id}/appeals` | List a motorist's appeals | FacilityAdmin, Motorist |
| POST | `/parking/permits` | Request a permit for a zone | Motorist |
| GET | `/parking/permits/{id}` | Read a permit | FacilityAdmin, EnforcementOfficer, Motorist |
| POST | `/parking/permits/{id}/activate` | Activate a requested permit | FacilityAdmin |
| POST | `/parking/permits/{id}/reject` | Reject a requested permit | FacilityAdmin |
| POST | `/parking/permits/{id}/revoke` | Revoke an active permit | FacilityAdmin |
| POST | `/parking/permits/{id}/expire-check` | Sweep-expire an active permit past its validity | FacilityAdmin |
| GET | `/parking/permits/{id}/waitlist-entry` | List the waitlist entry promoted into this permit | FacilityAdmin, EnforcementOfficer |
| GET | `/parking/permits/{id}/sessions` | List sessions admitted under a permit | FacilityAdmin, EnforcementOfficer, Motorist |
| GET | `/parking/permits/{id}/plate-reads` | List plate reads matched to a permit | FacilityAdmin, EnforcementOfficer |
| POST | `/parking/merchants` | Enroll a merchant in a garage | FacilityAdmin |
| GET | `/parking/merchants/{id}` | Read a merchant | FacilityAdmin, Merchant |
| GET | `/parking/merchants/{id}/validations` | List validations issued by a merchant | FacilityAdmin, Merchant |
| POST | `/parking/validations` | Issue a parking validation | Merchant |
| GET | `/parking/validations/{id}` | Read a validation | FacilityAdmin, Merchant, Motorist |
| GET | `/parking/validations/{id}/sessions` | List sessions that redeemed a validation | FacilityAdmin, Merchant |
| POST | `/parking/sessions` | Open an access session at the gate | FacilityAdmin |
| GET | `/parking/sessions/{id}` | Read an access session | FacilityAdmin, EnforcementOfficer, Motorist |
| POST | `/parking/sessions/{id}/exit` | Close a session and compute charges | FacilityAdmin |
| POST | `/parking/sessions/{id}/void` | Void an open session | FacilityAdmin |
| POST | `/parking/plate-reads` | Submit an LPR camera read | EnforcementOfficer |
| GET | `/parking/plate-reads/{id}` | Read an LPR read result | FacilityAdmin, EnforcementOfficer |
| GET | `/parking/plate-reads/{id}/citations` | List citations issued from a plate read | FacilityAdmin, EnforcementOfficer |
| POST | `/parking/citations` | Issue a citation from a violation | EnforcementOfficer |
| GET | `/parking/citations/{id}` | Read a citation | FacilityAdmin, EnforcementOfficer, Motorist |
| POST | `/parking/citations/{id}/pay` | Pay a citation | Motorist |
| GET | `/parking/citations/{id}/appeals` | List appeals for a citation | FacilityAdmin, EnforcementOfficer, Motorist |
| POST | `/parking/appeals` | Submit an appeal against an issued citation | Motorist |
| GET | `/parking/appeals/{id}` | Read an appeal | FacilityAdmin, EnforcementOfficer, Motorist |
| POST | `/parking/appeals/{id}/decide` | Decide an appeal | EnforcementOfficer |
| POST | `/parking/_clock/set_current_utc` | Set the server's current UTC for expiry and redemption checks | FacilityAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ZONE_TYPE_FORBIDDEN` | 409 Conflict |
| `ERR_DUPLICATE` | 409 Conflict |
| `ERR_VALIDATION_NOT_REDEEMABLE` | 409 Conflict |
| `ERR_EVENT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_SPACE_OCCUPIED` | 409 Conflict |
| `ERR_GATE_CLOSED` | 409 Conflict |
| `ERR_ZONE_AT_CAPACITY` | 409 Conflict |
| `ERR_MERCHANT_BUDGET_EXHAUSTED` | 409 Conflict |
| `ERR_INVALID_TIME_RANGE` | 409 Conflict |
| `ERR_STALE_ZONE_VERSION` | 412 Precondition Failed |
| `ERR_PAGINATION_INVALID` | 400 Bad Request |
