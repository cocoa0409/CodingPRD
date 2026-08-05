# Mobile-Vendor & Sidewalk-Cart Permit API — Product Requirements Document

## 1. Introduction

Cities that host street vendors face a persistent tension: sidewalk frontage is scarce and highly desirable, public-health obligations are non-negotiable, and enforcement must be even-handed and auditable. This document specifies the backend service that a municipality uses to license mobile vendors and sidewalk carts, to allocate a finite pool of vending spots across zones and routes, and to run the compliance machinery — inspections, insurance verification, violations, impounds, and public complaints — that keeps the program lawful.

The platform models the full lifecycle of a permit from a vendor's first application through issuance, renewal, suspension, and eventual revocation. Prime sidewalk locations are contested through a deterministic lottery that ranks entrants by seniority, standing, and citation history rather than by chance, while standard locations are assigned on demand subject to strict time-window and physical-spacing rules. Money flows — permit fees, fines, impound-release charges, lottery entry fees, and vendor payments — are tracked on a conserved per-vendor ledger so that every charge is balanced by an explicit credit. Because several administrative roles (permit officers, health inspectors, and field enforcement) act on the same resources with separated duties, the service enforces role-based authorization and four-eyes segregation on the most consequential decisions.

All time-dependent behavior in the system is evaluated against a server-managed **logical clock**, never against real wall-clock time. This makes fee windows, inspection expiry, insurance coverage windows, and renewal grace periods fully reproducible.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the calling principal, and `X-User-Role`, naming the principal's role. If either header is missing or malformed, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are present but the named role is not permitted to invoke the target operation per the authorization matrix in Section 4, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

There are exactly five roles, spelled precisely as follows: `Vendor`, `PermitOfficer`, `HealthInspector`, `EnforcementOfficer`, and `Resident`.

When `X-User-Role` is `Vendor`, `X-User-ID` is the `id` of the acting `Vendor`. Ownership checks on any resource that references a vendor compare the resource's owning `vendor_id` to `X-User-ID`: for a `Cart` or `Permit`, the resource's own `vendor_id`; for a `Violation`, `Complaint`, `LotteryEntry`, or `SpotAssignment`, the `vendor_id` of the `Permit` the resource belongs to. A `Vendor` acting on a resource it does not own is rejected with `ERR_OWNERSHIP` (HTTP 403). This ownership comparison is enforced only on the state-changing operations a `Vendor` initiates against its own resources — insurance submission, payment, cart and permit creation, permit submission and renewal, violation contest and withdrawal, lottery entry, and spot-assignment release; read and list endpoints perform no ownership filtering (any authorized `Vendor` may read any such resource), and filing a complaint is permitted against any permit.

When `X-User-Role` is `PermitOfficer`, `HealthInspector`, `EnforcementOfficer`, or `Resident`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. The server may nonetheless record it where a workflow requires provenance — in particular, when an `EnforcementOfficer` issues a citation the server records that officer's `X-User-ID` as the violation's `issuer_user_id`, and that stored value is later used to enforce four-eyes segregation on adjudication. A `Resident` is a member of the public whose only capabilities are filing a complaint against a permit and reading a complaint.

Validation is evaluated in a fixed precedence so that failures surface predictably: authentication first, then role authorization, then vendor ownership, then existence of every referenced resource, then body well-formedness, then enum membership, then state legality, and finally the business-specific checks described throughout Sections 2 and 3. Where multiple business checks apply to one operation, their relative order is stated with the workflow that owns them.

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

All list endpoints accept two optional query parameters, `limit` and `offset`. The `limit` defaults to 10, with a minimum of 1 and a maximum of 100; a requested limit above 100 is capped at 100. The `offset` defaults to 0 and its minimum is 0. List results are ordered by `created_at` ascending; where several records share a `created_at`, ties are broken by ascending creation order (the sequence in which the server minted them). Each list response reports `limit`, `offset`, `total_count`, and `has_more` in the `meta` object, where `total_count` is the number of records matching the filter before pagination and `has_more` is true when records remain beyond the current page.

### 2.4. Common Resource Properties, Identifiers, and the Logical Clock

Every persisted resource carries a server-minted `id`, which is a UUID with no type prefix, and a `created_at` timestamp recorded in ISO 8601 UTC with three fractional digits. All entities in this system additionally carry an `updated_at` timestamp and an integer `version`. The `version` begins at 1 when the resource is created and increments by 1 on every mutation of that resource; `updated_at` is refreshed to the current logical-clock instant whenever the resource changes. Clients never set `id`, `created_at`, `updated_at`, or `version` directly.

The system maintains a single logical clock that governs every deadline, expiry, coverage window, and time-comparison in the platform. Before any call is made, the clock reads `2026-05-01T00:00:00Z`. A `PermitOfficer` may advance or set the clock by supplying a target instant `to_iso8601`; this is an administrative test-driving capability and has no side effect other than moving the clock. All rules that reference "the clock" below read this value, never the host machine's wall-clock time.

### 2.5. Monetary Precision, the Vendor Ledger, and Money Conservation

All monetary amounts are expressed and stored in whole cents (integers). Wherever a fee computation multiplies by a rate, the result is rounded half up to a whole number of cents. Where a fee is assembled from several components each carrying tax, the tax on each component is rounded half up independently and only then are the components and their taxes summed — the system never sums first and rounds once.

Each `Vendor` maintains a running ledger through three fields. `total_charged_cents` is the cumulative sum of every charge levied on the vendor: permit fees at issuance and renewal, violation fines at issuance, impound release fees, and lottery entry fees. `total_credited_cents` is the cumulative sum of every credit: payments the vendor makes and compensating reversals of dismissed fines. The derived `balance_owed_cents` is always `total_charged_cents` minus `total_credited_cents`. Both accumulators begin at 0 for a new vendor. This ledger is conserved: every forward charge that is later reversed (for example, a fine that is dismissed) is offset by an equal credit, so the outstanding balance returns to exactly its pre-charge value with no drift.

### 2.6. Slot Conservation and Zone Capacity Integrity

Each `Zone` publishes its occupancy as two derived counters. `assigned_slots` is the number of `SpotAssignment` records in that zone whose status is `ACTIVE`. `available_slots` is the zone's `capacity_slots` minus its `assigned_slots`. These two counters observe a strict partition invariant: `assigned_slots` plus `available_slots` always equals `capacity_slots`. A newly created zone begins with `assigned_slots` at 0 and `available_slots` equal to `capacity_slots`. Any operation that creates an active assignment increments `assigned_slots` and decrements `available_slots`; any release does the reverse. Because both are derived counters, they are never set directly.

### 2.7. Cascading Suspension and Release Semantics

Several events suspend a permit, and every permit suspension carries the same cascade. When a permit leaves `ISSUED` for `SUSPENDED`, every `SpotAssignment` that belongs to that permit and is still `ACTIVE` transitions to `RELEASED`. Each such release sets the freed `Spot` back to `AVAILABLE`, decrements the owning zone's `assigned_slots`, recomputes that zone's `available_slots`, and increments the zone's `version` by 1. Because a single suspension can free several spots across a zone, each freed spot bumps the zone version once. Suspension is triggered directly by a permit officer or enforcement officer, and also indirectly as a cascade — from a failed cart inspection, from a cart impound, and from a violation or complaint that pushes a permit's points to the suspension threshold. Reinstating a permit does **not** automatically restore any previously released spot assignments; the vendor must re-acquire spots after a reinstatement.

### 2.8. Optimistic Concurrency Control on Zone Slots

Creating a direct spot assignment consumes a slot in the target zone and advances that zone's `version`. To protect a client from acting on a stale view of a zone's remaining capacity and occupied positions, the direct-assignment operation requires the caller to supply `expected_zone_version` carrying the `version` of the `Zone` the client last observed. If `expected_zone_version` does not equal the zone's current `version` — because another assignment has legitimately consumed or freed a slot since the client last read the zone — the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and no assignment is created. This is the only operation that takes a version field; no other endpoint accepts or requires one.

### 2.9. Nested Resource Retrieval and Path Validation

Many resources are addressed through nested paths — spots under a zone, violations, complaints and spot-assignments under a permit, impounds under a cart, entries under a lottery. Path parameters are validated left to right, and every referenced resource in the path and body must exist; the first missing reference yields `ERR_NOT_FOUND` (HTTP 404). List endpoints support reverse lookups by foreign key: carts may be filtered by `vendor_id`, `commissary_id`, or `status`; permits by `vendor_id`, `cart_id`, `zone_id`, or `status`; spots by `status` within a zone; violations and complaints by `status` within a permit; impounds by `status` within a cart; lotteries by `zone_id` or `status`; lottery entries by `lottery_id`, `permit_id`, or `status`; and spot assignments by `spot_id`, `permit_id`, `zone_id`, or `status`.

## 3. Business Logic & Workflows

### 3.1. Vendor Registration, Insurance, and Payments

A `PermitOfficer` registers a vendor by supplying the business's `legal_name`, a `contact_email`, and optionally the vendor's `seniority_years` (defaulting to 0 when omitted). A new vendor starts with `status` of `ACTIVE` (the vendor-level standing enum ranges over `ACTIVE`, `SUSPENDED`, and `REVOKED`), an `insurance_status` of `NONE`, and both ledger accumulators at 0. A vendor read exposes the computed `insurance_status`, `balance_owed_cents`, and `compliance_score` alongside the stored fields.

Liability insurance is submitted by the vendor itself. The vendor provides `insurance_effective_at`, `insurance_expires_at`, and `insurance_coverage_cents`; each submission replaces the current coverage window. If the submitted `insurance_coverage_cents` is below the minimum liability requirement of $1,000,000 — that is, below 100,000,000 cents — the submission is rejected with `ERR_INSUFFICIENT_COVERAGE`. Otherwise the coverage fields are stored and `insurance_status` is recomputed against the clock. The `insurance_status` reads `NONE` until a first policy is submitted; it reads `ACTIVE` when the clock is at or after `insurance_effective_at` and strictly before `insurance_expires_at` and `insurance_coverage_cents` is at least 100,000,000 cents; otherwise it reads `LAPSED`.

The vendor records a payment against its outstanding balance by supplying `amount_cents`. The payment must be strictly greater than zero and must not exceed the current `balance_owed_cents`; a non-positive amount or an amount above the outstanding balance is rejected with `ERR_PAYMENT_INVALID`. A valid payment adds `amount_cents` to `total_credited_cents` and the balance is recomputed.

### 3.2. Commissaries and the Cart Lifecycle

A `HealthInspector` registers a commissary — the licensed base-of-operations facility — with a `name`, a `health_grade` of `A`, `B`, or `C`, and a `license_expires_at` timestamp. A commissary starts `ACTIVE` (its status enum is `ACTIVE` or `SUSPENDED`). An inspector may later amend a commissary, optionally changing its `status` or its `license_expires_at`; amending a commissary does not retroactively un-approve carts that were already approved against it. A commissary is usable for cart approval only while it is `ACTIVE` and its `license_expires_at` is strictly after the clock.

A `Vendor` registers a cart by supplying `vendor_id`, `commissary_id`, a `cart_type` of `FOOD`, `PRODUCE`, or `MERCHANDISE`, and its footprint `size_sqft`. A new cart begins with `status` `PENDING` (the cart status enum ranges over `PENDING`, `APPROVED`, `IMPOUNDED`, and `RETIRED`) and `inspection_status` `PENDING`.

A `HealthInspector` records an inspection on a cart by supplying the `inspection_type`, a `result` of `PASS` or `FAIL`, a numeric `score`, and, on a pass, an `inspection_expires_at`. The recorded result becomes the cart's `inspection_status`, the score is stored as `inspection_score`, and the expiry is stored as `inspection_expires_at`; recording an inspection responds with HTTP 201. A cart's `inspection_status` is considered a valid `PASS` only when the latest result was `PASS` and `inspection_expires_at` is strictly after the clock. When an inspection result is `FAIL`, every `ISSUED` permit that operates this cart is suspended (`ISSUED → SUSPENDED`), which in turn releases those permits' active spot assignments as described in Section 2.7.

A `PermitOfficer` approves a cart for operation, advancing it from `PENDING` to `APPROVED`. Approval requires that the cart currently holds a valid, unexpired `PASS` inspection — otherwise `ERR_INSPECTION_NOT_PASSED` — and that its commissary is `ACTIVE` with an unexpired license — otherwise `ERR_COMMISSARY_NOT_ACTIVE`.

### 3.3. Zones, Spots, and Permit Issuance

A `PermitOfficer` creates a vending zone or route with a `name`, a `zone_type` of `PRIME` or `STANDARD`, a `capacity_slots` count, and a `spacing_min_feet` buffer. Prime zones allocate their spots by lottery; standard zones are assigned directly. A zone opens with `status` `OPEN` (the enum is `OPEN` or `CLOSED`); new assignments are blocked while a zone is `CLOSED`. Within a zone the officer creates spots, each with a human `label` and a `position_feet` giving its linear position along the route; a spot begins `AVAILABLE` (its status enum is `AVAILABLE`, `ASSIGNED`, or `BLOCKED`) and reads `ASSIGNED` exactly while it carries an active assignment.

A vendor applies for a permit by supplying `vendor_id`, `cart_id`, `zone_id`, and a `permit_type` of `FOOD`, `PRODUCE`, or `MERCHANDISE`. The permit begins in `DRAFT` (its lifecycle enum ranges over `DRAFT`, `SUBMITTED`, `ISSUED`, `SUSPENDED`, and `REVOKED`). The owning vendor submits the draft, moving it `DRAFT → SUBMITTED`.

A `PermitOfficer` issues a submitted permit, advancing it `SUBMITTED → ISSUED`. Issuance is gated by three checks, in this order: the vendor's `insurance_status` must be `ACTIVE`, otherwise `ERR_INSURANCE_NOT_ACTIVE`; the permit's cart must be `APPROVED`, otherwise `ERR_CART_NOT_APPROVED`; and no other permit for the same cart may already be `ISSUED` with a validity window that overlaps the new term, otherwise `ERR_PERMIT_OVERLAP`. Overlap is measured as closed intervals: an existing issued permit's `[issued_at, expires_at]` window overlaps the prospective term `[clock, clock + 365 days]` whenever the existing `issued_at` is at or before `clock + 365 days` and `clock` is at or before the existing `expires_at`. On issuance the fee variant is set to `NEW` and the permit fee is assessed as described in Section 3.4; `issued_at` is set to the clock and `expires_at` is set to the clock plus 365 days; the assessed `fee_amount_cents` is added to the vendor's `total_charged_cents` and the balance is recomputed.

### 3.4. Permit Fees, Renewal, and the Renewal Window

A permit's `fee_amount_cents` is assessed at issuance and re-assessed at each renewal, and the `fee_variant` field records which of `NEW`, `RENEWAL_EARLY`, or `RENEWAL_LATE` produced the current amount. The fee is built from three components in whole cents. The **base component** is 20,000 cents for a `NEW` issuance and for a `RENEWAL_LATE` renewal; for a `RENEWAL_EARLY` renewal it is the base fee discounted to 80% — that is, 20,000 multiplied by 0.80 and rounded half up, giving 16,000 cents. The **zone component** is a surcharge determined by the permit's zone type: 15,000 cents for a `PRIME` zone and 5,000 cents for a `STANDARD` zone. The **size component** is a tier fee determined by the cart's `size_sqft`: a small cart of 20 square feet or fewer costs 3,500 cents, a medium cart of 21 through 40 square feet costs 6,500 cents, and a large cart above 40 square feet costs 11,000 cents.

Tax is applied per component at a rate of 8.75%: the tax is computed as the base component times 0.0875 rounded half up, plus the zone component times 0.0875 rounded half up, plus the size component times 0.0875 rounded half up — each rounding performed before the three tax figures are summed. The fee is then the base component plus the zone component plus the size component plus that summed tax. For a `RENEWAL_LATE` renewal only, a late penalty of 7,500 cents is added after the tax has been included.

A vendor renews an `ISSUED` permit. The variant is chosen by renewal timing relative to the permit's `expires_at`. When the clock is strictly before `expires_at`, the renewal is `RENEWAL_EARLY`. When the clock is at or after `expires_at` but strictly before `expires_at` plus the 30-day grace period, the renewal is `RENEWAL_LATE`. When the clock has reached or passed `expires_at` plus 30 days, the renewal window has closed and the request is rejected with `ERR_RENEWAL_WINDOW_CLOSED`. A successful renewal recomputes `fee_amount_cents` for the chosen variant, adds it to the vendor's `total_charged_cents`, and resets `expires_at` to the clock plus 365 days.

### 3.5. Direct Spot Assignment, Time Conflicts, and Spacing

For standard zones, a `PermitOfficer` assigns a spot to a permit directly. The request names the `spot_id`, the occupation window bounds `start_at` and `end_at`, and the `expected_zone_version` described in Section 2.8. The occupation window is half-open, `[start_at, end_at)`: the start is inclusive and the end is exclusive. On success the assignment is created `ACTIVE` with `origin` `DIRECT`, its `zone_id` and `position_feet` are denormalized from the referenced spot, the spot becomes `ASSIGNED`, the zone's `assigned_slots` is incremented by 1, `available_slots` is recomputed, and the zone's `version` is incremented by 1.

Beyond authentication, ownership, existence, body validity, and state legality, the direct assignment is subjected to these business checks, evaluated in the following order. First, a **time conflict** on the same spot: the request is rejected with `ERR_SPOT_TIME_CONFLICT` if any active assignment on that same `spot_id` overlaps the requested window, where two half-open windows overlap when the new `start_at` is before the existing `end_at` and the existing `start_at` is before the new `end_at`; two windows that merely touch at a boundary do not conflict. Second, a **spacing violation** across the zone: the request is rejected with `ERR_SPACING_VIOLATION` if any active assignment in the same zone occupies a position whose distance from the requested spot — the absolute difference of their `position_feet` — is strictly less than the zone's `spacing_min_feet`, and whose occupation window overlaps the requested window under the same half-open rule; a distance exactly equal to the buffer is permitted. Third, **zone availability**: if the zone's `available_slots` is at or below zero the request is rejected with `ERR_ZONE_CAPACITY_FULL`, and if the zone is `CLOSED` the request is rejected with `ERR_ZONE_CLOSED`. Finally, the **stale-version** check compares `expected_zone_version` to the zone's current `version`, rejecting a mismatch with `ERR_STALE_VERSION`.

Either a `PermitOfficer` or the owning `Vendor` may release an active assignment, moving it `ACTIVE → RELEASED`; the freed spot returns to `AVAILABLE`, the zone's `assigned_slots` is decremented, `available_slots` is recomputed, and the zone's `version` is incremented by 1.

### 3.6. Prime-Spot Lottery Allocation

Prime sidewalk spots are contested through a lottery rather than assigned first-come. A `PermitOfficer` opens a lottery over a prime zone (the server does not reject a `zone_id` that references a non-`PRIME` zone) by supplying `zone_id`, a non-refundable `entry_fee_cents`, and the term bounds `term_start_at` and `term_end_at` that will be applied as the `start_at` and `end_at` of any spot assignments the draw mints. A lottery opens `OPEN` (its enum is `OPEN` or `DRAWN`, and `DRAWN` is terminal). A vendor enters under one of its issued permits by supplying `permit_id` and an ordered `preferred_spot_ids` list, most-preferred first; entry requires that the referenced permit is `ISSUED`, otherwise `ERR_NOT_ELIGIBLE_LOTTERY`; the lottery's own `status` is not checked at entry time, so an entry may be created even after the lottery has been drawn. A valid entry is created `ENTERED` (the entry enum ranges over `ENTERED`, `AWARDED`, and `WAITLISTED`) and the lottery's `entry_fee_cents` is charged to the vendor's `total_charged_cents`.

A `PermitOfficer` draws the lottery, moving it `OPEN → DRAWN`; a draw on a non-open lottery is rejected with `ERR_LOTTERY_NOT_OPEN`, and the lottery's zone must itself be `OPEN`, otherwise `ERR_ZONE_CLOSED`. The draw first determines eligibility for each `ENTERED` entry: an entry is ineligible — and is forced to `WAITLISTED` without competing — if its permit is not `ISSUED` or if the entrant's vendor has any cart with an impound currently in `HELD`. Each eligible entry receives a deterministic `rank_score` equal to the vendor's `seniority_years` times 10, plus the vendor's `compliance_score` times 1, minus the permit's `violation_points` times 5. Eligible entries are ordered by `rank_score` descending, and ties are broken by the entry's `created_at` ascending — never by id and never randomly. Proceeding down that ordered list, each entry is awarded the first spot in its `preferred_spot_ids` that is still available, and this continues while the zone's `available_slots` remains above zero; any eligible entry that reaches no available preferred spot, and every entry once capacity is exhausted, becomes `WAITLISTED`. An awarded entry moves to `AWARDED` with its `awarded_spot_id` set, mints a `SpotAssignment` with `origin` `LOTTERY` in `ACTIVE` status, marks that spot `ASSIGNED`, increments the zone's `assigned_slots`, and increments the zone's `version`; a waitlisted entry keeps a null `awarded_spot_id`. The lottery's `awarded_count` reflects the number of entries that ended `AWARDED`.

### 3.7. Violations, Contest, and Four-Eyes Adjudication

An `EnforcementOfficer` issues a citation against a permit by supplying a `violation_type` of `MINOR`, `MAJOR`, or `CRITICAL` and a free-text `description`. The new violation begins `ISSUED` (its enum ranges over `ISSUED`, `CONTESTED`, `UPHELD`, and `DISMISSED`; `UPHELD` and `DISMISSED` are terminal). Its `points` are set from the violation type — 3 for `MINOR`, 6 for `MAJOR`, 12 for `CRITICAL` — and its `fine_cents` is set likewise: 5,000 for `MINOR`, 12,000 for `MAJOR`, 30,000 for `CRITICAL`. The issuing officer's identity is recorded as `issuer_user_id`, the fine is charged to the vendor's `total_charged_cents` at issuance, and `source_complaint_id` is left null for officer-issued citations.

The owning vendor may contest a citation, moving it `ISSUED → CONTESTED`, and may later withdraw that contest, moving it `CONTESTED → ISSUED`; this negotiation loop may repeat.

An `EnforcementOfficer` adjudicates a violation with an `outcome` of `UPHOLD` or `DISMISS`, from either `ISSUED` or `CONTESTED`. Adjudication enforces four-eyes segregation: the adjudicating officer's `X-User-ID` must differ from the violation's `issuer_user_id`, otherwise the request is rejected with `ERR_SELF_ADJUDICATION`. An `UPHOLD` outcome moves the violation to `UPHELD` and its points begin counting toward the cited permit's `violation_points`; the permit's points are recomputed over the trailing window, and if they reach or exceed the suspension threshold of 12 while the permit is `ISSUED`, the permit is suspended (`ISSUED → SUSPENDED`) with the spot-release cascade of Section 2.7. A `DISMISS` outcome moves the violation to `DISMISSED` and reverses the issue-time charge by adding the violation's `fine_cents` to the vendor's `total_credited_cents`, recomputing the balance.

A permit's `violation_points` is the sum of the point values of that permit's `UPHELD` violations whose `updated_at` falls within the trailing 365-day window ending at the clock; violations that are `ISSUED`, `CONTESTED`, or `DISMISSED` contribute nothing. A vendor's `compliance_score` is 100 reduced by 5 for each `UPHELD` violation across all of that vendor's permits, clamped to a floor of 0 and a ceiling of 100. Both figures feed lottery ranking.

### 3.8. Public Complaints and the Substantiation Cascade

A `Resident` or a `Vendor` files a complaint against a permit by supplying a `complaint_type` of `NOISE`, `SANITATION`, `BLOCKING`, or `UNPERMITTED` and a free-text `description`. A complaint opens `OPEN` (its enum ranges over `OPEN`, `SUBSTANTIATED`, and `UNFOUNDED`; the latter two are terminal), with a null `resolution` and a null `generated_violation_id`.

An `EnforcementOfficer` resolves an open complaint by supplying a `resolution_outcome` of `SUBSTANTIATED` or `UNFOUNDED` and an optional `resolution` note. Resolving as `UNFOUNDED` moves the complaint to `UNFOUNDED` and produces no fiscal or permit-state effect. Resolving as `SUBSTANTIATED` moves the complaint to `SUBSTANTIATED` and auto-creates a violation of severity `MAJOR` on the complained-about permit; that violation is created `ISSUED` and immediately upheld by the resolving officer — recording a null `issuer_user_id` and levying no fine charge on the vendor's ledger, so although its `fine_cents` carries the `MAJOR` value that amount is never added to `total_charged_cents` — carries the complaint's id as its `source_complaint_id`, and its id is recorded on the complaint as `generated_violation_id`. Because the generated violation is upheld, it recomputes the permit's `violation_points`, which may push the permit to or past the threshold and trigger the same `ISSUED → SUSPENDED` suspension and spot-release cascade — a chain that runs from complaint to violation to permit to spot assignments to the zone counters.

### 3.9. Impound, Release, and Forfeiture

An `EnforcementOfficer` impounds an approved cart by supplying an impound `reason` of `UNPERMITTED`, `HEALTH_HAZARD`, `ABANDONMENT`, or `SPACING`, together with the `impounded_at` instant that starts storage accrual. Impounding creates an `Impound` in `HELD` status (its enum ranges over `HELD`, `RELEASED`, and `FORFEITED`, and both `RELEASED` and `FORFEITED` are terminal — a release or forfeit attempted on an impound already in one of those states returns `ERR_TERMINAL_STATE`), moves the cart `APPROVED → IMPOUNDED`, and suspends every `ISSUED` permit operating that cart (`ISSUED → SUSPENDED`), each suspension releasing its active spot assignments. Carts that remain unclaimed in storage beyond a 30-day horizon are the typical candidates for forfeiture.

Settlement of an impound depends on how it ends, and its `settlement_variant` records which of `RELEASE` or `FORFEITURE` applied. In both cases billed storage is computed the same way: `storage_days` is the number of whole days between `impounded_at` and the settlement instant, rounded up to the next whole day and never less than 1. Storage cost is tiered — the first 7 storage days are billed at 2,500 cents per day and every day beyond the seventh at 4,000 cents per day.

When the owner reclaims the cart, an officer releases the impound, moving it `HELD → RELEASED`; `settled_at` is set to the supplied `release_at`, the settlement variant is `RELEASE`, and the `release_fee_cents` charged to the vendor is a base impound fee of 10,000 cents plus the tiered storage cost plus an administrative fee of 5,000 cents, with `municipal_writeoff_cents` left at 0. That release fee is added to the vendor's `total_charged_cents`, and the cart returns `IMPOUNDED → APPROVED`. When the cart is instead forfeited, an officer forfeits the impound, moving it `HELD → FORFEITED`; `settled_at` is set to the supplied `forfeit_at`, the settlement variant is `FORFEITURE`, `release_fee_cents` is 0 (no charge to the vendor), and `municipal_writeoff_cents` is recorded as the base impound fee of 10,000 cents plus the tiered storage cost, with no administrative fee included. Forfeiture retires the cart permanently (`IMPOUNDED → RETIRED`). Both release and forfeit require the impound to be in `HELD`.

Once a permit has been suspended, a `PermitOfficer` may reinstate it (`SUSPENDED → ISSUED`), but only when the permit's `violation_points` is below the suspension threshold of 12 — otherwise `ERR_INVALID_STATE` — and its cart is `APPROVED` — otherwise `ERR_CART_NOT_APPROVED`; reinstatement refreshes `updated_at` and does not restore released spot assignments. From `SUSPENDED`, a `PermitOfficer` may instead revoke the permit (`SUSPENDED → REVOKED`), a terminal state permitting no further transitions.

## 4. Endpoint Definitions

New resource creations return HTTP 201; state transitions, updates, and reads return HTTP 200. All endpoints share the response envelope of Section 2.2 and the error catalogue of Section 5. A transition attempted on a resource in an illegal state returns `ERR_INVALID_STATE`; one attempted from a terminal state returns `ERR_TERMINAL_STATE`; an enum field carrying a non-member value returns `ERR_INVALID_ENUM`.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/_clock/set_current_utc` | Set the server logical clock | PermitOfficer |
| POST | `/vendors` | Register a vendor | PermitOfficer |
| GET | `/vendors/{id}` | Get a vendor (incl. computed insurance/balance/compliance) | Vendor, PermitOfficer, EnforcementOfficer, HealthInspector |
| POST | `/vendors/{id}/insurance` | Submit/renew the vendor's liability policy | Vendor |
| POST | `/vendors/{id}/payments` | Record a payment against outstanding balance | Vendor |
| POST | `/commissaries` | Register a commissary facility | HealthInspector |
| GET | `/commissaries/{id}` | Get a commissary | Vendor, HealthInspector, PermitOfficer |
| PATCH | `/commissaries/{id}` | Update commissary status / license | HealthInspector |
| POST | `/carts` | Register a cart | Vendor |
| GET | `/carts/{id}` | Get a cart | Vendor, PermitOfficer, HealthInspector, EnforcementOfficer |
| GET | `/carts` | List carts (filterable) | Vendor, PermitOfficer, HealthInspector, EnforcementOfficer |
| POST | `/carts/{id}/inspect` | Record a health/safety inspection | HealthInspector |
| POST | `/carts/{id}/approve` | Approve a cart for operation | PermitOfficer |
| POST | `/zones` | Create a vending zone/route | PermitOfficer |
| GET | `/zones/{id}` | Get a zone (incl. computed slot counts) | Vendor, PermitOfficer |
| POST | `/zones/{id}/spots` | Create a spot in a zone | PermitOfficer |
| GET | `/zones/{id}/spots` | List spots in a zone | Vendor, PermitOfficer |
| GET | `/spots/{id}` | Get a spot | Vendor, PermitOfficer |
| POST | `/permits` | Create a permit application (DRAFT) | Vendor |
| GET | `/permits/{id}` | Get a permit (incl. computed fee/points) | Vendor, PermitOfficer, EnforcementOfficer |
| GET | `/permits` | List permits (filterable) | Vendor, PermitOfficer, EnforcementOfficer |
| POST | `/permits/{id}/submit` | Submit a DRAFT permit | Vendor |
| POST | `/permits/{id}/issue` | Issue a SUBMITTED permit | PermitOfficer |
| POST | `/permits/{id}/suspend` | Suspend an ISSUED permit | PermitOfficer, EnforcementOfficer |
| POST | `/permits/{id}/reinstate` | Reinstate a SUSPENDED permit | PermitOfficer |
| POST | `/permits/{id}/revoke` | Revoke a SUSPENDED permit (terminal) | PermitOfficer |
| POST | `/permits/{id}/renew` | Renew an ISSUED permit | Vendor |
| POST | `/permits/{id}/violations` | Issue a violation against a permit | EnforcementOfficer |
| GET | `/permits/{id}/violations` | List violations on a permit | Vendor, PermitOfficer, EnforcementOfficer |
| POST | `/permits/{id}/complaints` | File a complaint against a permit | Resident, Vendor |
| GET | `/permits/{id}/complaints` | List complaints on a permit | Vendor, PermitOfficer, EnforcementOfficer |
| GET | `/violations/{id}` | Get a violation | Vendor, PermitOfficer, EnforcementOfficer |
| POST | `/violations/{id}/contest` | Vendor contests a violation | Vendor |
| POST | `/violations/{id}/withdraw-contest` | Vendor withdraws a contest | Vendor |
| POST | `/violations/{id}/adjudicate` | Officer adjudicates a violation (four-eyes) | EnforcementOfficer |
| POST | `/carts/{id}/impounds` | Impound a cart | EnforcementOfficer |
| GET | `/carts/{id}/impounds` | List impounds for a cart | Vendor, EnforcementOfficer, PermitOfficer |
| GET | `/impounds/{id}` | Get an impound | Vendor, EnforcementOfficer, PermitOfficer |
| POST | `/impounds/{id}/release` | Release an impounded cart | EnforcementOfficer |
| POST | `/impounds/{id}/forfeit` | Forfeit an impounded cart | EnforcementOfficer |
| GET | `/complaints/{id}` | Get a complaint | Vendor, Resident, PermitOfficer, EnforcementOfficer |
| POST | `/complaints/{id}/resolve` | Resolve a complaint | EnforcementOfficer |
| POST | `/lotteries` | Open a lottery for a PRIME zone | PermitOfficer |
| GET | `/lotteries/{id}` | Get a lottery | Vendor, PermitOfficer |
| GET | `/lotteries` | List lotteries (filterable) | Vendor, PermitOfficer |
| POST | `/lotteries/{id}/entries` | Enter a lottery under an ISSUED permit | Vendor |
| POST | `/lotteries/{id}/draw` | Draw the lottery and award spots | PermitOfficer |
| GET | `/lottery-entries/{id}` | Get a lottery entry | Vendor, PermitOfficer |
| GET | `/lottery-entries` | List lottery entries (filterable) | Vendor, PermitOfficer |
| POST | `/permits/{id}/spot-assignments` | Directly assign a spot to a permit | PermitOfficer |
| GET | `/spot-assignments/{id}` | Get a spot assignment | Vendor, PermitOfficer |
| GET | `/spot-assignments` | List spot assignments (filterable) | Vendor, PermitOfficer |
| POST | `/spot-assignments/{id}/release` | Release an ACTIVE spot assignment | PermitOfficer, Vendor |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_OWNERSHIP | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_VALIDATION | 400 |
| ERR_INVALID_ENUM | 422 |
| ERR_INVALID_STATE | 409 |
| ERR_TERMINAL_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_INSURANCE_NOT_ACTIVE | 422 |
| ERR_INSUFFICIENT_COVERAGE | 422 |
| ERR_CART_NOT_APPROVED | 409 |
| ERR_COMMISSARY_NOT_ACTIVE | 422 |
| ERR_INSPECTION_NOT_PASSED | 422 |
| ERR_PERMIT_OVERLAP | 409 |
| ERR_SPOT_TIME_CONFLICT | 409 |
| ERR_SPACING_VIOLATION | 409 |
| ERR_ZONE_CAPACITY_FULL | 409 |
| ERR_ZONE_CLOSED | 409 |
| ERR_RENEWAL_WINDOW_CLOSED | 422 |
| ERR_SELF_ADJUDICATION | 403 |
| ERR_LOTTERY_NOT_OPEN | 409 |
| ERR_NOT_ELIGIBLE_LOTTERY | 422 |
| ERR_PAYMENT_INVALID | 422 |
