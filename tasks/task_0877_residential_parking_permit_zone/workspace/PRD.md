# Residential Parking Permit Zone API — Product Requirements Document

## 1. Introduction

Municipalities that operate residential parking permit zones face a persistent scarcity problem: the number of curbside slots in a neighborhood is finite, yet demand from residents, their additional vehicles, and their visitors is not. This system is the administrative backbone for running such a program end to end. It models the geographic **zones** that hold a fixed density of permits, the **households** that live in them, the **vehicles** those households own, and the residency proof that gates eligibility. On top of that foundation it runs a two-stage permit application workflow, a waitlist that fills freed slots in strict arrival order, visitor-pass issuance, renewals, transfers and refunds, and a field-enforcement track covering citations, disputes, adjudication, and complaints.

The hard part is the coupling. A per-zone density limit and a per-household vehicle cap are competed for through the same issuance path, and every action that frees a slot — a refund, a revocation, an expiry, a third upheld citation — must ripple forward into an automatic waitlist promotion that issues a new permit. Two quantities must be conserved across all of these compensating actions: the count of slots a zone has consumed, and the money ledger of fees collected against fees refunded. Because supervisors and clerks act on shared state, issuance and renewal are guarded by optimistic concurrency so that a decision taken against a stale view of a zone or a permit is rejected rather than allowed to over-fill capacity. This document specifies every entity, state transition, calculation, validation, and endpoint required to implement that behavior precisely.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request other than household self-registration must carry two headers: `X-User-ID`, identifying the calling principal, and `X-User-Role`, naming the caller's role. If either header is missing, or `X-User-Role` is not one of the roles below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the role is not permitted to perform the requested operation — or an ownership check fails — the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes five roles, spelled exactly as follows: `Resident`, `ParkingClerk`, `PermitSupervisor`, `EnforcementOfficer`, and `Anonymous`.

- When `X-User-Role` is `Resident`, `X-User-ID` is the `id` of the acting `Household`. Ownership checks on any resource that references a household compare that resource's owning-household field (its `household_id`, or for a household record its own `id`) to `X-User-ID`; a resident may only act on and read its own household, vehicles, applications, permits, visitor passes, and citations. A resident is created through self-registration, which is why registering a household is the one operation an `Anonymous` caller may perform.
- When `X-User-Role` is `Anonymous`, `X-User-ID` is an opaque identifier not tied to any persisted entity. An anonymous caller may only self-register a household; the household record returned by that call supplies the `id` the resident then uses as its `X-User-ID`.
- When `X-User-Role` is `ParkingClerk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where a transition writes it — as `reviewer_user_id` on a `ProofSubmission` the clerk reviews and on a `PermitApplication` the clerk moves into review — but it is never compared to any entity's `id`.
- When `X-User-Role` is `PermitSupervisor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it as `decided_by_user_id` on an application the supervisor approves or denies, but does not compare it to any entity's `id`.
- When `X-User-Role` is `EnforcementOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it as `issuing_officer_id` when the officer issues a citation and as `adjudicator_id` when the officer adjudicates a dispute, but does not compare it to any entity's `id`. The segregation-of-duties rule described in §2.7 constrains how those two recorded values may relate.

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

List endpoints accept two query parameters, `limit` and `offset`. The `limit` parameter defaults to 10, has a minimum of 1, and a maximum of 100. The `offset` parameter defaults to 0 and has a minimum of 0. Results are always ordered by `created_at` ascending. Each list response reports `limit`, `offset`, `total_count` (the total number of matching records before pagination), and `has_more` (true when records remain beyond the current page) inside the `meta` object.

### 2.4. Common Resource Properties, Identifiers, and Versioning

Every resource carries a server-minted `id`, which is a UUID with no type prefix, and a `created_at` timestamp. All entities in this system additionally carry `updated_at` and an integer `version`. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits. The `version` begins at 1 when a resource is created and increments by one on every mutation of that resource, and `updated_at` is refreshed to the current clock time on every mutation. Where a specific transition is documented in §3 as bumping a parent entity's version (an issuance bumping the zone, a renewal or transfer bumping the permit), that increment is in addition to the routine per-mutation bump and is the value the optimistic-concurrency checks in §2.8 read against.

### 2.5. Nested Resource Retrieval and Path Validation

Several resources are addressed under a parent path — vehicles and proof submissions are created beneath a `household_id`, and many actions target a resource by its own identifier such as `zone_id`, `vehicle_id`, `proof_id`, `application_id`, `permit_id`, `pass_id`, `entry_id`, `citation_id`, or `complaint_id`. Path parameters are validated left to right: each referenced resource must exist before the next is considered, and any missing resource yields `ERR_NOT_FOUND` (HTTP 404). When a nested resource is addressed under a parent, it must genuinely belong to that parent; a mismatch is treated as a not-found condition on the nested resource.

### 2.6. The Logical Clock and Time Semantics

All deadline, expiry, proration, and window computations read a server-controlled **logical clock** rather than wall-clock time. At startup the clock reads exactly `2026-05-01T00:00:00Z` and never falls back to the host wall clock before it is set. An administrative test-driving capability advances the clock to a supplied instant, provided as a `to_iso8601` value; every subsequent time-dependent computation then uses that value as "now". Renewal windows, proof validity, permit expiry, refund proration, and visitor-pass validity all resolve against this clock.

### 2.7. Validation Ordering and Error Precedence

When several checks could fail on one request, they are evaluated in a fixed priority order and the first failure determines the returned error. The order is: (1) authentication of the headers (`ERR_UNAUTHENTICATED`); (2) role authorization, including entity-backed ownership (`ERR_UNAUTHORIZED`); (3) existence of every path- and body-referenced resource, left to right (`ERR_NOT_FOUND`); (4) whether the target resource is in a legal state for the requested transition (`ERR_INVALID_STATE`, HTTP 409); (5) business-safety checks — segregation of duties, proof-of-residency verification, and zone/household activity; (6) business-referential checks that bind vehicles and permits to the right household; (7) business-temporal checks — visitor-pass overlap, permit-period overlap, and the renewal window; (8) business-constraint checks — the household vehicle cap, the guest-pass daily limit, and duplicate applications; (9) the zone density limit (`ERR_ZONE_AT_CAPACITY`); and finally (10) the optimistic-concurrency version checks. A body that is malformed, omits a required field, carries a bad enum value, sets a visitor pass's `valid_until` at or before its `valid_from`, or supplies a negative amount is rejected with `ERR_VALIDATION` (HTTP 400).

Among the priority-5 business-safety checks: segregation of duties on citation adjudication raises `ERR_SEGREGATION_OF_DUTIES` (HTTP 403); a household whose proof is not verified raises `ERR_PROOF_NOT_VERIFIED` (HTTP 422) on review, approve, and renew-approve; and a suspended zone raises `ERR_ZONE_SUSPENDED` (HTTP 409) on review, approve, and waitlist, while a suspended household raises `ERR_HOUSEHOLD_SUSPENDED` (HTTP 409).

### 2.8. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency, each keyed to a parent entity's `version`.

The approve-and-issue operation must carry `expected_zone_version` matching the target zone's current `version`. Every approval bumps the zone's `version` and consumes a slot; if another approval, refund, or suspension has advanced the zone's `version` since the supervisor last read it, the request is rejected with `ERR_ZONE_VERSION_CONFLICT` (HTTP 412), so a decision taken against a stale view of the zone can never silently over-fill it. The `expected_zone_version` input is mandatory on this operation.

The renewal-approval operation must carry `expected_permit_version` matching the target permit's current `version`. A transfer or a prior renewal-approval bumps the permit's `version`; if the permit's `version` has advanced since the supervisor last read it, the request is rejected with `ERR_PERMIT_VERSION_CONFLICT` (HTTP 412), so a renewal is never applied to a superseded permit view. The `expected_permit_version` input is mandatory on this operation. No other operation takes a version field.

### 2.9. Conserved Quantities, Precision, and Rounding

Two quantities per zone are computed on read and must remain exactly conserved across every compensating action. All monetary values are integer cents; where a division is involved, the result is rounded half-up to a whole number of cents according to the rule stated for that calculation.

The **slot count**, `active_permit_count`, is defined on each zone as the number of that zone's permits whose status is `ACTIVE`, `SUSPENDED`, or `RENEWAL_PENDING`; the identical definition applied to a single household's permits gives that household's `active_permit_count`. After any issuance adds one and its compensating action — a refund, revocation, or expiry — removes one, the stored count stays exactly equal to that live count. A transfer mints a successor and terminates the predecessor in the same step, leaving both the zone and household counts unchanged.

The **fee ledger** tracks two sums per zone. `fees_collected_cents` is the sum of `fee_paid_cents` across every permit ever issued in the zone, including renewal collections; `fees_refunded_cents` is the sum of `refund_amount_cents` across the zone's permits whose status is `REFUNDED`. The net revenue is `fees_collected_cents` minus `fees_refunded_cents`, and that net must equal the sum over all permits of each permit's `fee_paid_cents` minus its `refund_amount_cents`. A refund moves money from the collected side to the refunded side; the identity holds exactly. A zone additionally exposes `waitlist_count`, the number of that zone's waitlist entries whose status is `WAITING`.

### 2.10. Cascading State Effects and Version Semantics

Many transitions mutate more than one resource. Zone suspension freezes the permits and passes beneath it; zone reactivation selectively thaws them; proof expiry suspends a household's active permits; a slot freed by refund, revocation, expiry, or a revocation-by-citation triggers a waitlist promotion that issues a new permit. Each such cascade mutates every affected resource — refreshing its `updated_at` and incrementing its `version` — and the specific chains are specified in §3. When a cascade issues or removes a permit, the zone's and household's `active_permit_count` values move accordingly, and where §3 says the zone's or permit's `version` is bumped by the operation, that bump is what the §2.8 concurrency checks observe.

## 3. Business Logic & Workflows

### 3.1. Zones: Configuration and Lifecycle

A `PermitSupervisor` establishes a residential parking permit zone by supplying its human-readable `name`, a short unique `zone_code` (for example `RPZ-A`, unique across all zones), the density limit `permit_capacity`, the per-household `max_permits_per_household` vehicle cap, the `guest_pass_daily_limit`, the full-year `permit_annual_fee_cents`, and the flat `visitor_pass_fee_cents` charged per temporary visitor pass. A new zone opens in status `ACTIVE` with its `active_permit_count`, `waitlist_count`, `fees_collected_cents`, and `fees_refunded_cents` all at zero and `version` at 1.

A zone lives in one of two states, `ACTIVE` or `SUSPENDED`. Suspending an `ACTIVE` zone drives it `ACTIVE → SUSPENDED` and fires a two-link cascade: first, every permit in the zone whose status is `ACTIVE` or `RENEWAL_PENDING` is moved to `SUSPENDED`; second, for each permit just suspended, every visitor pass issued under it whose status is `ACTIVE` is moved to `CANCELLED`. While the zone is `SUSPENDED` no new approvals or issuances may occur. Reactivating a `SUSPENDED` zone drives it `SUSPENDED → ACTIVE` and thaws only the eligible permits: every permit in the zone that is currently `SUSPENDED` and whose owning household's `proof_status` is `VERIFIED` returns to `ACTIVE`, while a permit whose household proof is not verified stays `SUSPENDED`. Attempting to suspend a zone that is not `ACTIVE`, or reactivate one that is not `SUSPENDED`, fails as an invalid state.

### 3.2. Households and Proof of Residency

A household enters the system through anonymous self-registration, supplying the `zone_id` it belongs to, its `unit_address`, its `resident_name`, and a `contact_email`. It opens `ACTIVE` with `proof_status` `UNVERIFIED`, with `proof_verified_at` and `proof_expires_at` both null and `active_permit_count` zero. The returned `id` becomes the resident's `X-User-ID`. A household's `status` is either `ACTIVE` or `SUSPENDED`.

Proof of residency is never set directly; it is driven by clerk review and by the expiry sweep. A resident submits a proof document by supplying its `document_type`, one of `LEASE`, `UTILITY_BILL`, `DEED`, or `ID_CARD`; the submission opens `PENDING`. A `ParkingClerk` reviews a `PENDING` submission with an `outcome`. A verify outcome drives the submission `PENDING → VERIFIED`, records the clerk's identity as `reviewer_user_id`, sets the submission's `verified_at` to the current clock time and its `expires_at` to that instant plus the proof validity term of 365 days, and in turn drives the household's `proof_status` to `VERIFIED` — setting the household's `proof_verified_at` to now and its `proof_expires_at` to now plus that same 365-day term. Because the household transition accepts an already-verified or previously-expired household as well as an unverified one, a fresh verification always refreshes the clock. A reject outcome drives the submission `PENDING → REJECTED`, records `reviewer_user_id`, and leaves the household's `proof_status` unchanged. Reviewing a submission that is not `PENDING` fails as an invalid state.

Verified proof does not last forever. During the zone expiry sweep, any household whose proof has passed its `proof_expires_at` — that is, the current clock is strictly later than `proof_expires_at` — moves from `VERIFIED` to `EXPIRED`, and as a cascade every one of that household's permits still in `ACTIVE` status is suspended.

### 3.3. Vehicles

A resident registers a vehicle beneath its household by supplying the vehicle's `license_plate`, `make`, and `model`; the owning `household_id` is taken from the path. The vehicle opens `ACTIVE`, and a `license_plate` must be unique per household among that household's `ACTIVE` vehicles. A vehicle's `status` is either `ACTIVE` or `REMOVED`.

### 3.4. Permit Applications: The Two-Stage Review

A resident applies for a permit by supplying the `zone_id`, the `household_id`, and the `vehicle_id` the permit is for; the application opens `SUBMITTED`. The named vehicle must be an `ACTIVE` vehicle of the applying household — otherwise `ERR_VEHICLE_HOUSEHOLD_MISMATCH` (HTTP 409). A household may not have a second open application for the same vehicle: if an application for the same household and vehicle already sits in `SUBMITTED`, `UNDER_REVIEW`, or `WAITLISTED`, the new application is rejected with `ERR_DUPLICATE_APPLICATION` (HTTP 409). An application progresses through `SUBMITTED`, `UNDER_REVIEW`, and then one of the terminal outcomes `APPROVED`, `WAITLISTED`, or `DENIED`.

A `ParkingClerk` starts review, driving the application `SUBMITTED → UNDER_REVIEW` and recording the clerk as `reviewer_user_id`. Review requires the applying household's `proof_status` to be `VERIFIED` and the zone to be `ACTIVE`; a household without verified proof fails with `ERR_PROOF_NOT_VERIFIED` and a suspended zone with `ERR_ZONE_SUSPENDED`.

From `UNDER_REVIEW` there are three paths. A `PermitSupervisor` may approve (see §3.5), producing a permit and driving the application to `APPROVED` with the supervisor recorded as `decided_by_user_id` and the resulting permit's id stored as the application's `permit_id`. A `PermitSupervisor` may instead deny, supplying a `denial_reason`, which drives the application `UNDER_REVIEW → DENIED`, stores the reason, and records `decided_by_user_id`. A `ParkingClerk` may waitlist the application, but only when the zone is genuinely full — the zone's `active_permit_count` must be at least its `permit_capacity`; waitlisting drives the application `UNDER_REVIEW → WAITLISTED`, creates a waitlist entry in status `WAITING`, and increments the zone's `waitlist_count`. Any of these actions on an application not in the required state fails as an invalid state.

### 3.5. Issuance: Density, Vehicle Cap, and the Fee Ledger

Approval is the moment a slot is consumed and money is collected, and it is gated on five conditions checked in the priority order of §2.7. The application must be `UNDER_REVIEW`; the zone must be `ACTIVE`; the applying household's `proof_status` must be `VERIFIED`. The household must be below the vehicle cap — its `active_permit_count` must be strictly less than the zone's `max_permits_per_household`, or the request fails with `ERR_HOUSEHOLD_VEHICLE_CAP` (HTTP 409). The zone must be below the density limit — its `active_permit_count` must be strictly less than its `permit_capacity`, or the request fails with `ERR_ZONE_AT_CAPACITY` (HTTP 409). Finally the supplied `expected_zone_version` must match the zone's current `version`, per §2.8. Additionally, the vehicle may not already hold an overlapping permit: a vehicle may not hold two occupying permits whose closed validity intervals — from `issued_at` through `expires_at` inclusive — intersect, so a new permit's `issued_at` must be strictly after any prior permit's `expires_at`; a shared endpoint counts as an overlap and fails with `ERR_PERMIT_PERIOD_OVERLAP` (HTTP 409).

On success the system mints a `Permit` in status `ACTIVE`, links it back to its `application_id`, records the `zone_id`, `household_id`, and `vehicle_id`, mints a human-readable `permit_number`, snapshots the bound vehicle's plate as the permit's own `license_plate`, sets `issued_at` to the current clock, and computes `expires_at` as the end of the term: `23:59:59.000Z` on the first fiscal-year-end date on or after `issued_at`, where the fiscal year ends on March 31. The approval bumps the zone's `version` by one, increments both the zone's and the household's `active_permit_count` by one, and collects the issuance fee.

The **issuance fee** is prorated by the remaining whole months of the term. First, the monthly rate is the zone's `permit_annual_fee_cents` divided by twelve, rounded half-up to a whole number of cents. Then the number of remaining whole months is the expiry month minus the issuance month, where each month is expressed as its calendar year times twelve plus its month number — that is, the difference `(expires_at.year × 12 + expires_at.month) − (issued_at.year × 12 + issued_at.month)`. The permit's `fee_paid_cents` is the rounded monthly rate multiplied by that month count. The monthly rate must be rounded before it is multiplied ("round per month, then sum"); do not instead multiply the annual fee by the month count, divide by twelve, and round only at the end, because when the annual fee is not divisible by twelve the two orders diverge. The collected `fee_paid_cents` is added to the zone's `fees_collected_cents`.

### 3.6. The Permit Lifecycle: Renewal, Transfer, Refund, Revocation, Expiry

A permit occupies exactly one of these states: `ACTIVE`, `SUSPENDED`, `RENEWAL_PENDING`, `EXPIRED`, `REVOKED`, `TRANSFERRED`, or `REFUNDED`. Permits in `ACTIVE`, `SUSPENDED`, or `RENEWAL_PENDING` occupy a slot and count toward capacity; the four terminal states do not.

**Renewal.** A resident requests renewal of an `ACTIVE` permit only within the renewal window — the current clock must be at or after the permit's `expires_at` minus 60 days. Outside that window the request fails with `ERR_RENEWAL_WINDOW` (HTTP 422). A valid request drives the permit `ACTIVE → RENEWAL_PENDING`; no fee is collected yet and the slot is still held, because `RENEWAL_PENDING` counts toward capacity. A `PermitSupervisor` then approves the renewal, which requires the permit to be `RENEWAL_PENDING`, the owning household's `proof_status` to be `VERIFIED`, and the supplied `expected_permit_version` to match the permit's current `version` (else `ERR_PERMIT_VERSION_CONFLICT`). Approval drives the permit `RENEWAL_PENDING → ACTIVE`, advances `expires_at` to the next fiscal-year-end after the current `expires_at`, adds the full-year `permit_annual_fee_cents` to the permit's `fee_paid_cents` and the same amount to the zone's `fees_collected_cents`, and increments the permit's `version` by one.

**Suspension and reactivation of a permit** are system-driven, arising only from the zone-suspend cascade or the proof-expiry sweep (`ACTIVE → SUSPENDED`) and from the zone-reactivate cascade when the household proof is verified (`SUSPENDED → ACTIVE`); a suspended permit keeps its slot.

**Transfer.** A `PermitSupervisor` transfers an `ACTIVE` permit to another vehicle by supplying the target `vehicle_id`, which must be an `ACTIVE` vehicle of the same household — otherwise `ERR_VEHICLE_HOUSEHOLD_MISMATCH`, and the same closed-interval permit-period-overlap check applies to the successor. Transfer drives the predecessor `ACTIVE → TRANSFERRED`, mints a successor `Permit` in status `ACTIVE` bound to the new vehicle that inherits the predecessor's `issued_at`, `expires_at`, and `fee_paid_cents`, and stores the successor's id on the predecessor as `transferred_to_permit_id`. No new fee is collected, and neither the zone's nor the household's `active_permit_count` changes, because a slot is surrendered and reclaimed in the same step.

**Refund.** A `PermitSupervisor` refunds a permit that is `ACTIVE` or `SUSPENDED` by supplying the `refund_type`, either `VOLUNTARY` or `ADMINISTRATIVE`. This drives the permit to `REFUNDED`, computes the `refund_amount_cents` as described below and records the chosen `refund_type`, adds that amount to the zone's `fees_refunded_cents`, decrements both the zone's and the household's `active_permit_count` by one, and then attempts a waitlist promotion of the oldest waiting entry. The refund amount starts from the unused-time proration: let the total term be the whole number of days between the permit's `issued_at` date and its `expires_at` date, and let the remaining days be the whole number of days from the current clock date to the `expires_at` date, floored at zero. The prorated unused amount is `fee_paid_cents` multiplied by the remaining days divided by the total term days, rounded half-up to whole cents. For a `VOLUNTARY` refund, the administrative fee of 2000 cents is withheld — the refund is the prorated unused amount minus 2000 cents, floored at zero. For an `ADMINISTRATIVE` refund (a municipality-initiated surrender such as a zone decommission), the full prorated unused amount is refunded with no administrative fee withheld.

**Revocation.** A `PermitSupervisor` may revoke a permit for cause by supplying a `reason`, and the system revokes a permit automatically when a third citation against it is upheld (see §3.8). Revocation applies to a permit in `ACTIVE`, `SUSPENDED`, or `RENEWAL_PENDING`, drives it to `REVOKED` with no refund, decrements both the zone's and the household's `active_permit_count` by one, and attempts a waitlist promotion of the oldest waiting entry.

**Expiry.** The zone expiry sweep moves any permit in `ACTIVE`, `SUSPENDED`, or `RENEWAL_PENDING` whose `expires_at` is strictly before the current clock to `EXPIRED`, decrements both the zone's and the household's `active_permit_count` by one, and attempts a waitlist promotion of the oldest waiting entry.

**Waitlist and promotion.** A waitlist entry records its `zone_id`, the `application_id` it represents, and the `household_id`, and carries a computed `position` and a `status` of `WAITING`, `PROMOTED`, `CANCELLED`, or `EXPIRED`. The `position` is the 1-based rank of the entry among the zone's `WAITING` entries ordered by `created_at` ascending (ties broken by `created_at` ascending); the entry's own `id` is never used for ordering. Whenever a slot is freed — by refund, revocation, an upheld-citation revocation, or expiry — the system attempts to promote the single `WAITING` entry at position 1, the oldest, provided a slot is actually free (the zone's `active_permit_count` is below its `permit_capacity`) and the promoted entry's household still has verified proof and remains below the vehicle cap. Promotion drives that entry `WAITING → PROMOTED`, decrements the zone's `waitlist_count`, drives the entry's application `WAITLISTED → APPROVED`, and mints a new `ACTIVE` permit exactly as an approval would — collecting the issuance fee, setting the application's `permit_id`, incrementing the zone's and household's `active_permit_count`, and bumping the zone's `version`.

The expiry sweep runs proof expiry, permit and visitor-pass expiry, and freed-slot promotions together for a zone at the current clock; visitor passes past their `valid_until` are expired as described in §3.7.

### 3.7. Visitor Passes

A resident issues a visitor pass under one of its own active permits, supplying the sponsoring `household_id`, the `permit_id`, the `pass_type` (`GUEST_DAILY` or `TEMPORARY`), the visiting vehicle's `guest_plate`, and the validity window `valid_from` and `valid_until` (which must be strictly after `valid_from`, else `ERR_VALIDATION`). The referenced permit must be an `ACTIVE` permit owned by the same household, or the request fails with `ERR_PERMIT_HOUSEHOLD_MISMATCH` (HTTP 409). The pass opens `ACTIVE`; its `fee_charged_cents` is the zone's `visitor_pass_fee_cents` for a `TEMPORARY` pass and zero for a `GUEST_DAILY` pass.

Two limits guard issuance. First, a new pass may not overlap an existing `ACTIVE` pass for the same household and the same `guest_plate`; validity intervals are half-open `[valid_from, valid_until)`, so exact adjacency where one pass's `valid_until` equals the next pass's `valid_from` is allowed, but any true overlap fails with `ERR_VISITOR_PASS_OVERLAP` (HTTP 409). Second, for a `GUEST_DAILY` pass, the household may not exceed the zone's `guest_pass_daily_limit` on the pass's calendar day: taking the UTC calendar date of the new pass's `valid_from`, count the household's existing `GUEST_DAILY` passes whose status is `ACTIVE` or `EXPIRED` and whose `valid_from` calendar date equals that day; if that count is already at or above the limit — so the new pass would be the one past the limit — it fails with `ERR_GUEST_PASS_LIMIT` (HTTP 409).

A visitor pass ends in `EXPIRED` or `CANCELLED`. A resident may cancel an `ACTIVE` pass, driving it `ACTIVE → CANCELLED`; the system also cancels active passes as part of the zone-suspend cascade. During the expiry sweep, any `ACTIVE` pass whose `valid_until` is at or before the current clock is moved `ACTIVE → EXPIRED`.

### 3.8. Enforcement: Citations, Disputes, and Adjudication

An `EnforcementOfficer` issues a citation by supplying the `zone_id`, the cited `license_plate`, the `violation_type` (`NO_PERMIT`, `EXPIRED_PERMIT`, or `ZONE_VIOLATION`), and, when the offending resident's permit is identified, the `permit_id` (which is null for a `NO_PERMIT` violation on an unknown plate). The citation opens `ISSUED`, records the officer as `issuing_officer_id`, and computes its fine.

The **fine** begins from a base that depends on the violation: 7500 cents for `NO_PERMIT`, and 5000 cents each for `EXPIRED_PERMIT` and `ZONE_VIOLATION`. The system then counts the prior upheld citations on the same plate in the same zone — citations with that `license_plate` and `zone_id` whose status is `UPHELD` — and snapshots that count into the citation's `prior_upheld_count`. If the prior upheld count is strictly less than the repeat threshold of 2, the citation is the `STANDARD` variant and its `fine_amount_cents` is the base fine, with `fine_variant` recorded as `STANDARD`. Otherwise the citation is the `REPEAT_OFFENDER` variant: a raw amount is the base multiplied by two raised to the power of (the prior upheld count minus the repeat threshold of 2, then plus one), and the `fine_amount_cents` is that raw amount clamped to be at least 2500 cents and at most 25000 cents, with `fine_variant` recorded as `REPEAT_OFFENDER`.

A citation moves through `ISSUED`, `PAID`, `DISPUTED`, `UPHELD`, and `DISMISSED`. A resident may pay an `ISSUED` citation, driving it `ISSUED → PAID`, or dispute it, driving it `ISSUED → DISPUTED`. A resident may also pay a citation that has been upheld, driving it `UPHELD → PAID`. A `DISPUTED` citation is adjudicated by an `EnforcementOfficer` who supplies an `outcome`, but that officer must not be the one who issued it — the adjudicating `X-User-ID` must differ from the citation's `issuing_officer_id`, or the request fails with `ERR_SEGREGATION_OF_DUTIES`. A dismiss outcome drives the citation `DISPUTED → DISMISSED`, records the officer as `adjudicator_id`, and leaves no fine owed. An uphold outcome drives the citation `DISPUTED → UPHELD`, records `adjudicator_id`, and triggers a three-link cascade: first, if the citation names a `permit_id` and that permit's `upheld_citation_count` — the count of upheld citations against it — has reached the revocation threshold of 3, the permit is revoked; second, revoking that permit frees a zone slot and promotes the oldest `WAITING` waitlist entry; third, the promoted entry's application is approved and a new permit is issued, exactly as in §3.6. Adjudicating a citation that is not `DISPUTED` fails as an invalid state.

### 3.9. Complaints

A `Resident` or an `EnforcementOfficer` files a complaint about a zone by supplying the `zone_id`, the `complaint_type` (`ILLEGAL_PARKING`, `PERMIT_ABUSE`, `SIGNAGE`, or `OTHER`), an optional `target_plate` (the plate complained about, null when the complaint is not plate-specific), and a `description`. The complaint opens `OPEN`. An `EnforcementOfficer` resolves an `OPEN` complaint by supplying an `outcome` and, where applicable, a `resolution_note`.

A resolve outcome drives the complaint `OPEN → RESOLVED` and stores the `resolution_note`; a dismiss outcome drives it `OPEN → DISMISSED` and stores the `resolution_note`. An escalate outcome drives it `OPEN → ESCALATED`, but only when the complaint carries a non-null `target_plate` — otherwise the request fails with `ERR_ESCALATION_REQUIRES_PLATE` (HTTP 422). Escalation synthesizes a new citation in the same zone with `violation_type` `ZONE_VIOLATION`, its `license_plate` set to the complaint's `target_plate`, and its `permit_id` null, and stores that citation's id on the complaint as `created_citation_id`. Resolving a complaint that is not `OPEN` fails as an invalid state.

## 4. Endpoint Definitions

Endpoints that create a new resource return HTTP 201; endpoints that read or modify an existing resource return HTTP 200. All list endpoints honor the pagination and ordering rules of §2.3, and every request/response payload beyond the summary here is reconstructed from the narratives in §3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/_clock/set_current_utc` | Set the server logical clock | PermitSupervisor, ParkingClerk |
| POST | `/zones` | Create a residential parking permit zone | PermitSupervisor |
| GET | `/zones/{zone_id}` | Get a zone | PermitSupervisor, ParkingClerk, EnforcementOfficer, Resident |
| POST | `/zones/{zone_id}/suspend` | Suspend a zone (cascade freeze) | PermitSupervisor |
| POST | `/zones/{zone_id}/reactivate` | Reactivate a suspended zone | PermitSupervisor |
| POST | `/zones/{zone_id}/run-expiry` | Run the expiry/promotion sweep for a zone | ParkingClerk |
| POST | `/households` | Self-register a household in a zone | Anonymous |
| GET | `/households/{household_id}` | Get a household | PermitSupervisor, ParkingClerk, EnforcementOfficer, Resident |
| GET | `/households` | List households, optionally filtered by zone | PermitSupervisor, ParkingClerk |
| POST | `/households/{household_id}/vehicles` | Register a vehicle for a household | Resident |
| GET | `/vehicles/{vehicle_id}` | Get a vehicle | PermitSupervisor, ParkingClerk, Resident |
| GET | `/vehicles` | List vehicles, optionally filtered by household | PermitSupervisor, ParkingClerk, Resident |
| POST | `/households/{household_id}/proof-submissions` | Submit a proof-of-residency document | Resident |
| GET | `/proof-submissions/{proof_id}` | Get a proof submission | PermitSupervisor, ParkingClerk, Resident |
| GET | `/proof-submissions` | List proof submissions, optionally filtered by household | PermitSupervisor, ParkingClerk, Resident |
| POST | `/proof-submissions/{proof_id}/review` | Clerk reviews a proof submission | ParkingClerk |
| POST | `/permit-applications` | Resident submits a permit application | Resident |
| GET | `/permit-applications/{application_id}` | Get an application | PermitSupervisor, ParkingClerk, Resident |
| GET | `/permit-applications` | List applications, optionally filtered | PermitSupervisor, ParkingClerk, Resident |
| POST | `/permit-applications/{application_id}/review` | Clerk starts review | ParkingClerk |
| POST | `/permit-applications/{application_id}/approve` | Supervisor approves and issues a permit | PermitSupervisor |
| POST | `/permit-applications/{application_id}/waitlist` | Clerk waitlists an application at capacity | ParkingClerk |
| POST | `/permit-applications/{application_id}/deny` | Supervisor denies an application | PermitSupervisor |
| GET | `/permits/{permit_id}` | Get a permit | PermitSupervisor, ParkingClerk, EnforcementOfficer, Resident |
| GET | `/permits` | List permits, optionally filtered | PermitSupervisor, ParkingClerk, EnforcementOfficer, Resident |
| POST | `/permits/{permit_id}/renew` | Resident requests renewal | Resident |
| POST | `/permits/{permit_id}/renew-approve` | Supervisor approves renewal | PermitSupervisor |
| POST | `/permits/{permit_id}/transfer` | Supervisor transfers a permit to another vehicle | PermitSupervisor |
| POST | `/permits/{permit_id}/refund` | Supervisor refunds/surrenders a permit | PermitSupervisor |
| POST | `/permits/{permit_id}/revoke` | Supervisor revokes a permit for cause | PermitSupervisor |
| POST | `/visitor-passes` | Issue a guest/temporary visitor pass | Resident |
| GET | `/visitor-passes/{pass_id}` | Get a visitor pass | PermitSupervisor, ParkingClerk, EnforcementOfficer, Resident |
| GET | `/visitor-passes` | List visitor passes, optionally filtered | PermitSupervisor, ParkingClerk, EnforcementOfficer, Resident |
| POST | `/visitor-passes/{pass_id}/cancel` | Resident cancels an active visitor pass | Resident |
| GET | `/waitlist-entries/{entry_id}` | Get a waitlist entry | PermitSupervisor, ParkingClerk, Resident |
| GET | `/waitlist-entries` | List waitlist entries, optionally filtered | PermitSupervisor, ParkingClerk, Resident |
| POST | `/citations` | Officer issues a citation | EnforcementOfficer |
| GET | `/citations/{citation_id}` | Get a citation | PermitSupervisor, ParkingClerk, EnforcementOfficer, Resident |
| GET | `/citations` | List citations, optionally filtered | PermitSupervisor, ParkingClerk, EnforcementOfficer, Resident |
| POST | `/citations/{citation_id}/pay` | Resident pays a citation | Resident |
| POST | `/citations/{citation_id}/dispute` | Resident disputes a citation | Resident |
| POST | `/citations/{citation_id}/adjudicate` | A different officer adjudicates a disputed citation | EnforcementOfficer |
| POST | `/complaints` | File a complaint about a zone/plate | Resident, EnforcementOfficer |
| GET | `/complaints/{complaint_id}` | Get a complaint | PermitSupervisor, ParkingClerk, EnforcementOfficer, Resident |
| GET | `/complaints` | List complaints, optionally filtered by zone | PermitSupervisor, ParkingClerk, EnforcementOfficer, Resident |
| POST | `/complaints/{complaint_id}/resolve` | Officer resolves/dismisses/escalates a complaint | EnforcementOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_VALIDATION | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_PROOF_NOT_VERIFIED | 422 |
| ERR_ZONE_SUSPENDED | 409 |
| ERR_HOUSEHOLD_SUSPENDED | 409 |
| ERR_VEHICLE_HOUSEHOLD_MISMATCH | 409 |
| ERR_PERMIT_HOUSEHOLD_MISMATCH | 409 |
| ERR_VISITOR_PASS_OVERLAP | 409 |
| ERR_PERMIT_PERIOD_OVERLAP | 409 |
| ERR_RENEWAL_WINDOW | 422 |
| ERR_HOUSEHOLD_VEHICLE_CAP | 409 |
| ERR_GUEST_PASS_LIMIT | 409 |
| ERR_DUPLICATE_APPLICATION | 409 |
| ERR_ZONE_AT_CAPACITY | 409 |
| ERR_ZONE_VERSION_CONFLICT | 412 |
| ERR_PERMIT_VERSION_CONFLICT | 412 |
| ERR_ESCALATION_REQUIRES_PLATE | 422 |
