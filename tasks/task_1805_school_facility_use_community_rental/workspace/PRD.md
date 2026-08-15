# School Facility Rental API — Product Requirements Document

## 1. Introduction

School districts own some of the most heavily demanded public space in their communities — gymnasiums, auditoriums, athletic fields, multipurpose rooms — and every evening and weekend much of that space sits idle while nonprofits, clubs, and private organizers struggle to find venues. This document specifies the School Facility Rental API, the system of record for a district facilities rental office that opens school sites to community use without compromising the instructional mission. The API governs the full commercial lifecycle of a community rental: facility inventory and rate policy, request intake and conflict arbitration against the school calendar, insurance vetting, deposit and fee collection, custodial staffing, cancellation refunds, post-event damage recovery, and recurring seasonal permits for long-running community programs.

Two principles dominate the design. First, schools come first: any scheduled school or district calendar event outranks every community request, and a top-priority instructional event can preempt a community permit that has already been issued, with the renter made whole automatically. Second, money is exact: every charge, deposit, discount, refund, and forfeiture is computed in integer cents under pinned rounding and evaluation-order rules, because renters, auditors, and the school board all read the same ledger. Five roles operate the system — district administrators, the facilities director, site coordinators, the custodial supervisor, and renter organization representatives — with segregation of duties enforced wherever damage money changes hands.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the caller's operational capacity. A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_OR_INVALID_CONTEXT_HEADER` (HTTP 400). The system recognizes exactly five roles, spelled exactly as follows: `DistrictAdmin`, `FacilitiesDirector`, `SiteCoordinator`, `CustodialSupervisor`, and `RenterOrgRep`.

- A `DistrictAdmin` is the district operations administrator: manages sites, facilities, rate policies, the school calendar, and the logical clock. When `X-User-Role` is `DistrictAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- A `FacilitiesDirector` heads the district facilities office: approves and denies requests, waitlists, bars renters, registers renter organizations, revokes insurance certificates, and adjudicates damage. When `X-User-Role` is `FacilitiesDirector`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- A `SiteCoordinator` is school-site staff: begins reviews, requests revisions, completes permits, and records damage intake. When `X-User-Role` is `SiteCoordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example as `recorded_by_user_id` on a damage assessment — but does not compare it to any entity's `id`.
- A `CustodialSupervisor` leads custodial operations and verifies actual hours on work orders. When `X-User-Role` is `CustodialSupervisor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- A `RenterOrgRep` is the representative of a renter organization: creates and submits requests, uploads insurance, posts payments, cancels the organization's own permits, and answers damage adjudications. When `X-User-Role` is `RenterOrgRep`, `X-User-ID` is the `id` of the acting RenterOrganization; ownership checks on any resource that references a RenterOrganization compare the resource's foreign-key field to `X-User-ID`. A `RenterOrgRep` whose `X-User-ID` does not equal the organization identifier in the path is acting on another organization's resources and is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

Any attempt to perform an operation outside the caller's role is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403). One further identity rule stands apart from role membership — segregation of duties over damage money: the operator who adjudicates a damage assessment, or resolves an appeal on one, must not be the operator who recorded that assessment's intake. A caller whose `X-User-ID` equals the assessment's `recorded_by_user_id` is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), even when the caller otherwise holds the correct role.

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

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

Beyond pagination, individual list endpoints accept the filter parameters referenced throughout §3 — the identifier filters `site_id`, `facility_id`, `permit_id`, `invoice_id`, `renter_org_id`, `rental_request_id`, `seasonal_permit_id`, and `superseded_by_permit_id`, and the status-or-class filters `facility_status`, `facility_tier`, `rate_class`, `policy_status`, `org_standing`, `request_status`, `cert_status`, `event_status`, `lifecycle_status`, `financial_status`, `invoice_kind`, `invoice_status`, `txn_kind`, `wo_status`, `assessment_status`, and `series_status`.

### 2.4. The Logical Clock, Timezones, and Interval Semantics

All deadline, expiry, activation, and window rules in the system read a single server-side logical clock — never the host machine's wall clock. At startup the logical clock is exactly 2026-08-01T00:00:00Z, and it must not fall back to wall-clock time under any circumstances. A `DistrictAdmin`-only test-driving capability sets the logical clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`. Advancing the clock is not a passive read change: it fires every time-based system transition in the domain — insurance certificates expire, unapproved requests lapse, permits activate when their occupancy begins or lapse when their deposit was never secured, renter standing is recomputed against the thirty-day arrears rule, damage appeal windows close, and seasonal series complete at season's end.

Every occupancy, coverage, blocked, and event interval in the system is half-open: the start instant is inclusive and the end instant is exclusive, written [start, end). Two intervals overlap when each begins strictly before the other ends. Wall-clock interpretation of an interval — which local calendar date an instant falls on, whether a given minute is inside business hours — uses the owning site's `rental_timezone`, an IANA timezone string that defaults to `America/Los_Angeles` when not supplied at site creation. Comparisons expressed in days (cancellation refund tiers, the fourteen-day appeal window, the thirty-day suspension clock) are made on whole calendar days in site-local time, and every day-count threshold in this document is inclusive of its lower bound.

### 2.5. Common Resource Properties

All primary resources — school sites, facilities, renter organizations, rate class policies, school calendar events, rental requests, insurance certificates, permits, custodial work orders, invoices, damage assessments, and seasonal permit series — carry a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed upon any change to the resource's properties.
- `version` (integer): a system-managed integer that increments with every modification to the resource, including system-initiated transitions and recomputation of derived fields. This field is the basis for optimistic concurrency control (§2.8).

**PaymentTransaction rows are the single exception.** A payment transaction is an immutable ledger entry that carries `id` and `created_at` only — both `updated_at` and `version` are absent — and its posting instant is recorded separately in `posted_at`, taken from the logical clock at the moment the row posts.

When one operation mutates several resources — a site closure withdrawing requests and retiring facilities, an approval spawning a permit, an invoice, and a work order — every affected resource is mutated atomically within the same request, and each mutated resource's `updated_at` is refreshed and `version` incremented independently. Derived-field recomputation (for example, recomputing a renter's `outstanding_balance_cents` when an invoice is issued) is likewise a mutation of the owning resource and advances its `updated_at` and `version`. Client-supplied `id`, `created_at`, or `version` values in a creation payload are ignored: the server mints all three.

### 2.6. Nested Resource Retrieval

Paths identify resources by id segments — `site_id`, `facility_id`, `org_id`, `request_id`, `permit_id`, `wo_id`, `invoice_id`, `payment_id`, `cert_id`, `event_id`, `assessment_id`, `series_id`, and `policy_id`. For any endpoint whose path contains more than one identifier, the server validates existence strictly left-to-right: the site segment before the facility segment, the organization segment before the request segment, the permit segment before any of its invoices, payments, work orders, or damage assessments. The first identifier that does not correspond to an existing resource aborts the request immediately with `ERR_NOT_FOUND` (HTTP 404), before any deeper path segment is examined and before any business rule runs.

### 2.7. Money, Cents, and Rounding Discipline

Every monetary value in the API is an integer number of cents; fractional cents never appear in any stored field or response. Wherever a computation produces a fractional cent, the result is rounded half-up to the nearest integer cent — at exactly the step each rule in §3 specifies, no earlier and no later. Two disciplines recur across the pricing rules: some rules round each monetary component individually before summing, and summing raw unrounded components followed by a single rounding at the end is expressly forbidden because it yields different cents; other rules round exactly once at a pinned step. Hour quantities such as `estimated_hours` and `actual_hours` are decimal numbers carried to two decimal places. Policy percentages are expressed in basis points where noted, with 10000 basis points equal to one hundred percent.

### 2.8. Optimistic Concurrency Control

Two write operations are protected by optimistic concurrency control, and each names its own expected-version field:

- **Approving a rental request** — the `POST /district/requests/{request_id}/approve` endpoint — requires the request body to carry `expected_request_version`, the approver's last observed `version` of the RentalRequest. If the request's current `version` has advanced since the approver last read it — for example because the renter resubmitted revised details, which legitimately replaces the terms under review and leaves the approver's view of the request stale — the approval is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the approver from approving terms they have not observed. A successful approval itself increments the request's `version` by one.
- **Creating a renewal seasonal series** — that is, a call to the `POST /district/seasonal_permits` endpoint whose `renewed_from_id` is set — requires the request body to carry `expected_series_version`, the client's last observed `version` of the prior SeasonalPermit series. If the prior series' current `version` has advanced since the client last read it — for example because another writer has just renewed the same series, and renewals legitimately supersede one another under the seniority rule — the creation is rejected with `ERR_STALE_VERSION` (HTTP 412).

Endpoints other than these two do not accept a version field.

### 2.9. The Validation Pipeline and Its Evaluation Order

When several checks could reject the same request, the server evaluates them in a fixed priority order and surfaces the first failure; a failure at an earlier tier masks every later tier. The tiers, in evaluation order, are:

1. **Context headers.** `X-User-ID` and `X-User-Role` must be present and well-formed, else `ERR_MISSING_OR_INVALID_CONTEXT_HEADER` (HTTP 400). Applies to all endpoints.
2. **Role authorization and ownership.** The role must be permitted for the endpoint, and entity-backed roles must own the target resource — a `RenterOrgRep`'s `X-User-ID` must equal the renter organization id in the path — else `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403). The segregation-of-duties check on damage adjudication and appeal resolution is enforced at this same tier and carries `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Applies to all endpoints.
3. **Path existence and request syntax.** Path ids are validated left-to-right per §2.6, and a missing id yields `ERR_NOT_FOUND` (HTTP 404). At this same tier, before any deeper business rule, the body itself is checked: a malformed body, a missing required field, a value of the wrong type, or an enum value outside its declared set yields `ERR_INVALID_REQUEST` (HTTP 400). Applies to all resource endpoints.
4. **Lifecycle state legality.** The target resource's current state must permit the operation — approval requires `UNDER_REVIEW`, permit cancellation requires `ISSUED`, terminal states reject all mutations — else `ERR_INVALID_STATE_TRANSITION` (HTTP 409). Applies to all action endpoints.
5. **Safety gates: capacity and insurance.** The estimated headcount must fit the facility, and the renter's insurance must be valid, cover the full event window, and meet the headcount tier — else `ERR_CAPACITY_EXCEEDED` or `ERR_INSURANCE_INSUFFICIENT` (HTTP 422). Applies to submission, resubmission, and approval.
6. **Temporal sanity.** Window shape rules — end strictly after start, duration at most twelve hours, submission start in the future, seasonal span within its limit, buffers in whole quarter-hours — else `ERR_INVALID_TIME_WINDOW` (HTTP 422). Applies to request creation, submission, and resubmission, to seasonal series creation, and to calendar event creation.
7. **Availability and schedule conflict.** The site must be `ACTIVE`, else `ERR_SITE_CLOSED` (HTTP 409); the facility must be `AVAILABLE`, else `ERR_FACILITY_NOT_AVAILABLE` (HTTP 409); and the requested interval must not collide with a `SCHEDULED` school calendar event or with the blocked interval of an `ISSUED` or `ACTIVE` permit on the same facility, else `ERR_SCHEDULE_CONFLICT` (HTTP 409). Applies to request creation and submission, to begin-review, to approval, to seasonal occurrence generation, to calendar event creation, and to facility creation. One deliberate exception: creating a tier-0 calendar event on an occupied interval is allowed and preempts the overlapping `ISSUED` permits instead of being rejected.
8. **Referential integrity.** Referenced objects must be valid in context — the facility belongs to an `ACTIVE` site, a pricing policy exists for the renter's rate class, the facility's tier, and the event start date, and a renewal source points to a real renewable series of the same renter — else `ERR_REFERENCE_INVALID` (HTTP 422). Applies to request creation, seasonal series creation, and approval.
9. **Fiscal gates.** The renter must be in `GOOD_STANDING`, a deposit capture must equal the required deposit exactly, and a fee payment must not exceed the invoice's remaining balance — else `ERR_RENTER_NOT_IN_GOOD_STANDING`, `ERR_PAYMENT_AMOUNT_MISMATCH`, or `ERR_OVERPAYMENT` (HTTP 402). Applies to submission, approval, and payment posting.
10. **Uniqueness and idempotency.** Creation-time uniqueness scopes and payment idempotency keys, per §2.10 — else `ERR_DUPLICATE` or `ERR_IDEMPOTENCY_CONFLICT` (HTTP 409). Applies to the creation endpoints and to payments.
11. **Loop caps and claim shapes.** The revision-loop cap, cancellation legality, damage-claim shape, adjudication amount caps, and the appeal window — else `ERR_REVISION_LIMIT_EXCEEDED`, `ERR_PERMIT_NOT_CANCELLABLE`, or `ERR_APPEAL_WINDOW_ELAPSED` (HTTP 409), or `ERR_EMPTY_DAMAGE_CLAIM` or `ERR_ADJUDICATION_EXCEEDS_CLAIM` (HTTP 422). Applies to revision requests, permit cancellation, and damage intake, adjudication, and appeal.
12. **Renewal linkage.** A renewal source must be a series owned by the same renter and not already renewed by another series — else `ERR_RENEWAL_NOT_RENEWABLE` (HTTP 422). Applies to seasonal series creation.

### 2.10. Uniqueness, Duplicates, and Idempotent Payments

Four uniqueness scopes are enforced at creation. A site's `site_code` is unique across all school sites in the district. A facility's `facility_code` is unique within its owning site. A renter organization's `org_name` is unique case-insensitively — two registrations whose names differ only in letter case collide. A rate class policy's `policy_code` is unique, and a policy is additionally unique per the server-composed `unique_key`, the concatenation of `rate_class`, `facility_tier`, and `effective_from` separated by pipe characters. Any violation is rejected with `ERR_DUPLICATE` (HTTP 409).

Payment posting is idempotent on the client-supplied `idempotency_key`. Reusing a key with an identical payload returns the original PaymentTransaction row unchanged and does not double-post. Reusing a key with a different payload is rejected with `ERR_IDEMPOTENCY_CONFLICT` (HTTP 409).

## 3. Business Logic & Workflows

### 3.1. District Inventory: Sites, Facilities, and the School Calendar

The district's rentable inventory is a tree: a **SchoolSite** roots it, and each site owns any number of facilities. A `DistrictAdmin` registers a site with a district-wide unique `site_code` and a human-readable `display_name`; the `rental_timezone` may be supplied and otherwise defaults to `America/Los_Angeles`. Every site is born with `site_status` `ACTIVE`. Closing a site is a one-way, terminal decision (`ACTIVE` → `CLOSED`): it is refused while any permit on any facility of the site remains `ISSUED` or `ACTIVE`, and when it succeeds the system withdraws every not-yet-decided rental request — any request in `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, `REVISION_REQUESTED`, `RESUBMITTED`, or `WAITLISTED` — that targets a facility of the site, and retires every facility of the site. From then on, a `CLOSED` site rejects new requests, new calendar events, and new facilities with `ERR_SITE_CLOSED`.

A **Facility** is created within a site with a site-local `facility_code`, a `facility_tier` of `STANDARD`, `PREMIUM`, or `ATHLETIC` that drives its base hourly rate, and a `capacity` of at least one occupant. Two scheduling guards travel with every facility: `setup_buffer_minutes` prepended to, and `teardown_buffer_minutes` appended to, every confirmed occupancy; each defaults to 30 minutes, must be at least zero, and must be a whole multiple of 15 minutes — anything else is rejected with `ERR_INVALID_TIME_WINDOW`. The `requires_custodian` flag, defaulting to true, decides whether every permit on the facility generates custodial labor. Facilities are born `AVAILABLE`.

Facility availability is managed through three transitions. Placing a facility on hold (`AVAILABLE` → `MAINTENANCE_HOLD`), with a `hold_reason` recorded, immediately demotes every pending request for that facility — those in `SUBMITTED`, `UNDER_REVIEW`, `REVISION_REQUESTED`, or `RESUBMITTED` — whose window overlaps the hold window to `WAITLISTED`, recorded with a hold reason of `MAINTENANCE`. Releasing the hold returns the facility to `AVAILABLE`; the waitlisted requests become eligible for re-review at the next conflict sweep but are not auto-approved. Retiring a facility (from either `AVAILABLE` or `MAINTENANCE_HOLD` to the terminal `RETIRED`) is refused while any permit for that facility remains `ISSUED` or `ACTIVE`; retirement withdraws the facility's pending requests, and it happens either manually or automatically when the owning site closes. Request creation, begin-review, and approval against a facility that is `MAINTENANCE_HOLD` or `RETIRED` are rejected with `ERR_FACILITY_NOT_AVAILABLE`.

The **school calendar** is the district's own claim on its space. A `DistrictAdmin` records a SchoolCalendarEvent with a `title`, a window from `starts_at` (inclusive) to `ends_at` (exclusive, and strictly after the start), and an `event_priority_tier` of 0 or 1 — tier 0 is an instructional or athletic school event, the highest claim there is; tier 1 is district-sponsored; both always outrank any community request. The optional `facility_id` scopes the event to one facility; leaving it null declares a site-wide blackout that occupies every facility of the site. Events are born `SCHEDULED`. Creating a tier-0 event whose window overlaps the blocked interval of an already-`ISSUED` community permit preempts that permit to `SUPERSEDED` with a full administrative refund (§3.7); creating any other event that collides with an `ISSUED` or `ACTIVE` permit's blocked interval is instead rejected with `ERR_SCHEDULE_CONFLICT`. Cancelling an event (`SCHEDULED` → `CANCELLED`) never un-supersedes a permit it preempted — supersession is sticky — but the freed window does trigger a waitlist promotion sweep.

### 3.2. Rate Classes and the District Pricing Policy Book

Every renter belongs to a rate class — `INTERNAL`, `NONPROFIT`, or `FOR_PROFIT` — and every facility belongs to a tier; the **RateClassPolicy** is where those two dimensions meet money. A `DistrictAdmin` authors a policy with a unique `policy_code`, the `rate_class` and `facility_tier` it prices, an `hourly_rate_cents` of at least zero — and exactly zero for `INTERNAL`, since the district does not charge itself — a `deposit_basis_points` between 0 and 10000, a `custodial_hourly_cents` labor rate for that class, and an effective window from `effective_from` to `effective_to`, where `effective_to` may be null for an open-ended policy and otherwise must be strictly after `effective_from`. The `deposit_floor_cents` is the minimum deposit regardless of fee and defaults to 10000 cents. A policy applies to events starting at or after its `effective_from` and strictly before its `effective_to`.

Only one policy per (rate class, facility tier) pair may be `ACTIVE` at any instant: creating a policy whose effective window overlaps an existing `ACTIVE` policy for the same pair supersedes the older row to `SUPERSEDED`. The district-wide invariant is that at most one `ACTIVE` row exists per pair at any moment. Approval of any rental request requires exactly one `ACTIVE` policy covering the event's start for the renter's class and the facility's tier; when none exists, approval fails with `ERR_REFERENCE_INVALID`. Policies are selected per occurrence for seasonal series, so a series that straddles a rate-year boundary bills later occurrences under the newer policy (§3.9).

### 3.3. Renter Organizations, Standing, and Insurance Compliance

A **RenterOrganization** is registered by a `FacilitiesDirector` or `DistrictAdmin` with a case-insensitively unique `org_name` and a `rate_class`; a `NONPROFIT` registration must additionally supply its `nonprofit_registration_no` (the 501(c)(3) EIN), which remains null for the other classes. The rate class becomes immutable once the organization has at least one request that has reached `SUBMITTED`. A fresh registration starts in `GOOD_STANDING` with `credit_balance_cents` at 0, `outstanding_balance_cents` at 0, and `forfeiture_count` at 0. The credit balance holds prepaid credit from over-refunds and is applied to future invoices before any card charge; the outstanding balance is the unpaid invoiced total; the forfeiture count is the lifetime number of deposits fully or partially forfeited.

Standing is enforced by the system, not by courtesy. When `outstanding_balance_cents` stays above zero continuously for thirty or more days — evaluated as the logical clock advances — or when `forfeiture_count` reaches three, the organization slides from `GOOD_STANDING` to `SUSPENDED`. Suspension blocks new request submissions and permit activations: attempts in that window are rejected with `ERR_RENTER_NOT_IN_GOOD_STANDING`. When the outstanding balance returns to zero and the forfeiture count is below three, standing is restored to `GOOD_STANDING` automatically. Barring is the terminal sanction: a `FacilitiesDirector` bars an organization with a `reason`, moving it from `GOOD_STANDING` or `SUSPENDED` to `BARRED`, withdrawing every non-terminal request the organization holds, and cancelling every `ISSUED` permit it holds under the administrative cancellation class — a full refund with no fee.

Community renters prove liability coverage with an **InsuranceCertificate**, uploaded by the organization's own representative or by the `FacilitiesDirector`, carrying the `insurer_name`, a `per_occurrence_limit_cents` strictly greater than zero, an `aggregate_limit_cents` at least as large as the per-occurrence limit, and a coverage window from `effective_from` (inclusive) to `effective_to` (exclusive and strictly after the start). A certificate is `VALID` at upload, becomes `EXPIRED` automatically when the logical clock passes its `effective_to`, and may be moved to `REVOKED` by a `FacilitiesDirector` giving a `reason`. Either loss of coverage cascades: any request sitting in `UNDER_REVIEW` that relied solely on that certificate is sent back to `REVISION_REQUESTED` for an insurance reason, and the renter must upload a new certificate.

How much insurance is enough depends on crowd size, in three tiers with inclusive lower bounds. A headcount below 100 requires a per-occurrence limit of at least 100000000 cents and an aggregate limit of at least 200000000 cents. A headcount of at least 100 but below 500 requires at least 200000000 per occurrence and at least 400000000 in aggregate. A headcount of 500 or more requires at least 500000000 per occurrence and at least 1000000000 in aggregate. A certificate satisfies a request exactly when it is `VALID`, its `effective_from` is at or before the request's `ends_at`, its `effective_to` is at or after the request's `ends_at`, and both limits meet the tier floors for the request's `headcount_estimate`. `INTERNAL` renters are exempt from the insurance gate entirely — the district self-insures. The sufficiency check runs as pre-validation when a certificate is uploaded and again as a hard gate at submission, resubmission, and approval; failure there is `ERR_INSURANCE_INSUFFICIENT`.

### 3.4. The Rental Request Pipeline: Intake, Review, and Approval

Every community booking begins as a **RentalRequest**, drafted by a `RenterOrgRep` against their own organization with the target `facility_id`, an `event_title`, a `headcount_estimate` of at least one, the requested window `starts_at` to `ends_at`, and an optional `district_sponsored` flag that defaults to false. A new request is born in `DRAFT` with `revision_round` at 0 and `submitted_at` still null.

Submission (`DRAFT` → `SUBMITTED`) is the moment a draft becomes a claim on the calendar, and it is gated: the organization must be in `GOOD_STANDING` (else `ERR_RENTER_NOT_IN_GOOD_STANDING`); the `headcount_estimate` must not exceed the facility's `capacity` (else `ERR_CAPACITY_EXCEEDED`); the `starts_at` must lie strictly after the logical clock's current instant — no past-dated submissions; and the window must satisfy the temporal rules, `ends_at` strictly after `starts_at` and the total duration at most twelve hours (else `ERR_INVALID_TIME_WINDOW`). The first successful submission stamps `submitted_at` from the logical clock, and that stamp is the canonical conflict-ordering key for the life of the request — later resubmissions never refresh it. Submission also derives the request's `request_priority_class` from the renter's rate class: `INTERNAL` requests are `P0`, `NONPROFIT` requests are `P2`, and `FOR_PROFIT` requests are `P3`; a `NONPROFIT` request flagged `district_sponsored` is eligible for promotion to `P1` at the `FacilitiesDirector`'s discretion.

A `SiteCoordinator` picks up the queue, moving `SUBMITTED` (and later `RESUBMITTED`) requests into `UNDER_REVIEW`; begin-review is only possible while the facility is `AVAILABLE`. When the details need work, the coordinator sends the request back (`UNDER_REVIEW` → `REVISION_REQUESTED`) with a `revision_note`, provided fewer than three revision loops have completed. The renter answers by resubmitting (`REVISION_REQUESTED` → `RESUBMITTED`) with any of `headcount_estimate`, `starts_at`, `ends_at`, or `event_title` revised — the revised headcount is re-checked against capacity — and resubmission increments `revision_round` by one while leaving `submitted_at` untouched, preserving the original seniority. The cycle `UNDER_REVIEW` → `REVISION_REQUESTED` → `RESUBMITTED` → `UNDER_REVIEW` may repeat at most three times; a revision request when `revision_round` is already 3 is rejected with `ERR_REVISION_LIMIT_EXCEEDED`, and at that point the only remaining outcomes are approval or denial.

Approval (`UNDER_REVIEW` → `APPROVED`) is reserved for the `FacilitiesDirector` and carries the optimistic-concurrency field `expected_request_version` per §2.8 — a stale view is rejected with `ERR_STALE_VERSION` (HTTP 412). Five preconditions guard approval. The calendar must be clear: no `SCHEDULED` SchoolCalendarEvent overlapping the requested window on the same facility, and none of the site's blackout events overlapping it either (else `ERR_SCHEDULE_CONFLICT`). The facility's committed book must be clear: no `ISSUED` or `ACTIVE` permit whose blocked interval overlaps the requested window expanded by the facility's setup and teardown buffers — that is, the span from `starts_at` minus `setup_buffer_minutes` to `ends_at` plus `teardown_buffer_minutes` (else `ERR_SCHEDULE_CONFLICT`). The insurance gate of §3.3 must pass for a non-`INTERNAL` renter (else `ERR_INSURANCE_INSUFFICIENT`). The organization must be in `GOOD_STANDING` (else `ERR_RENTER_NOT_IN_GOOD_STANDING`). And exactly one `ACTIVE` RateClassPolicy must cover the event's start for the renter's class and the facility's tier (else `ERR_REFERENCE_INVALID`). A successful approval increments the request's `version` by one and triggers a chain of creations detailed in §3.5: a Permit in `ISSUED` with `DEPOSIT_PENDING`, a `PROVISIONAL` invoice, and — when the facility's `requires_custodian` is set — a `SCHEDULED` custodial work order. Approval also arbitrates the queue: any other request in `SUBMITTED`, `UNDER_REVIEW`, `RESUBMITTED`, or `WAITLISTED` whose window overlaps the new permit's blocked interval on the same facility and whose priority is lower is demoted (or kept) at `WAITLISTED`. `APPROVED` is terminal for the request itself — the row remains `APPROVED` and the permit it spawned carries the lifecycle forward.

Denial (`UNDER_REVIEW` → `DENIED`) requires the `FacilitiesDirector` to supply a `denial_reason_code` of `CAPACITY`, `CALENDAR_CONFLICT`, `INSURANCE`, `POLICY`, or `DISCRETIONARY`; the code is null on requests in every other status and `DENIED` is terminal. Waitlisting moves a request from `SUBMITTED`, `UNDER_REVIEW`, or `RESUBMITTED` to `WAITLISTED`: a `FacilitiesDirector` may waitlist a pending request manually, supplying a `hold_reason`, and the system waitlists on its own when a higher-priority permit is issued over the window.

Waitlisting is a parking lot, not a graveyard. When a blocking permit is cancelled or superseded — or when a blocking calendar event is cancelled — a promotion sweep examines the freed interval. A `WAITLISTED` request is eligible for promotion only while no remaining `ISSUED` or `ACTIVE` permit blocks its window, its renter is in `GOOD_STANDING`, its headcount fits the facility's capacity, and the facility is `AVAILABLE`; the eligible candidate is promoted back to `UNDER_REVIEW`. An empty candidate set simply frees the interval.

Priority among competing requests is lexicographic — never a numeric score. Candidates are ordered first by `request_priority_class`, where `P0` outranks `P1`, which outranks `P2`, which outranks `P3`; ties are broken by the earlier `submitted_at`, where the original submission stamp governs because resubmissions never refresh it; any remaining tie is broken by the earlier `created_at`. The resource `id` is never used as an ordering key. Above all community requests stand the school calendar's own claims: `SCHEDULED` SchoolCalendarEvent rows outrank every community request, and tier-0 events go further, preempting even already-issued permits.

Two quieter exits close the lifecycle. The renter may withdraw a request from `DRAFT`, `SUBMITTED`, `REVISION_REQUESTED`, or `WAITLISTED`, and the system withdraws requests on its own when the organization is barred, the site closes, or the facility retires — all landing in the terminal `WITHDRAWN`. And if the logical clock passes a request's `starts_at` while it still sits in `SUBMITTED` or `WAITLISTED` without approval, the system moves it to the terminal `EXPIRED`.

### 3.5. Permits, Deposits, and Payment Posting

Approval mints the **Permit**: the district's confirmed grant of space. The permit carries `rental_request_id` back to its origin, with `renter_org_id` and `facility_id` denormalized from the request at issuance. Its confirmed event window runs from `occupancy_start` (inclusive) to `occupancy_end` (exclusive) — the requested window itself, with the setup buffer not included — while its calendar-blocked span runs from `blocked_start`, the occupancy start minus the facility's `setup_buffer_minutes`, to `blocked_end`, the occupancy end plus the `teardown_buffer_minutes`. One approved request has exactly one non-void permit. A permit minted as one occurrence of a recurring series records its `seasonal_permit_id`; `superseded_by_permit_id` stays null unless a rebooked replacement permit is ever issued.

Every permit lives on two independent state dimensions. The lifecycle dimension, `lifecycle_status`, runs `ISSUED` → `ACTIVE` → `COMPLETED`, with `ISSUED` also able to fall to `CANCELLED`, `EXPIRED`, or `SUPERSEDED`; all four of `COMPLETED`, `CANCELLED`, `EXPIRED`, and `SUPERSEDED` are terminal. The financial dimension, `financial_status`, runs its own track from `DEPOSIT_PENDING` through `SECURED`, `INVOICED`, `SETTLED`, `REFUND_PENDING`, `REFUNDED`, `FORFEIT_PENDING`, and `FORFEITED`. Transitions in one dimension never imply transitions in the other except where this section, §3.6, §3.7, and §3.8 say so explicitly.

The deposit is computed from the policy, separately from any invoice: `deposit_required_cents` is the quoted rental fee multiplied by the policy's `deposit_basis_points` and divided by 10000, rounded half-up to integer cents, and then raised to at least the policy's `deposit_floor_cents`. Until a deposit payment posts, `deposit_held_cents` remains 0. A renter secures the permit by posting a payment of kind `DEPOSIT_CAPTURE` while the permit is `ISSUED`; the posted `amount_cents` must equal `deposit_required_cents` exactly — any other amount is rejected with `ERR_PAYMENT_AMOUNT_MISMATCH` — and on success the financial dimension moves `DEPOSIT_PENDING` → `SECURED` with `deposit_held_cents` set to the captured amount. When the required deposit computes to zero — the norm for `INTERNAL` bookings — the permit secures automatically at issuance with `deposit_held_cents` of 0.

Activation belongs to the clock. When the logical clock reaches `occupancy_start` and the financial dimension is `SECURED`, the system moves the permit `ISSUED` → `ACTIVE` and starts its custodial work order. If the clock passes `occupancy_start` while the deposit is still `DEPOSIT_PENDING` — the deposit was never secured — the permit lapses to `EXPIRED`: its `PROVISIONAL` invoice is voided, its work order is cancelled, and the freed interval triggers a waitlist promotion sweep.

All money movement is recorded as **PaymentTransaction** rows posted by a `RenterOrgRep` with a `txn_kind`, an `amount_cents` that is always positive — direction is implied by the kind, with captures and fee payments debiting the renter, refunds crediting the renter, and forfeiture transferring held deposit to the district — an `idempotency_key` governed by §2.10, and an `invoice_id` that is null on `DEPOSIT_CAPTURE` and `DEPOSIT_FORFEIT` rows. The six kinds are `DEPOSIT_CAPTURE`, `FEE_PAYMENT`, `DEPOSIT_REFUND`, `DEPOSIT_FORFEIT`, `FEE_REFUND`, and `DAMAGE_CHARGE`; each row's `posted_at` is taken from the logical clock.

Fee payments retire invoices. A `FEE_PAYMENT` may not exceed the target invoice's remaining balance — its `total_cents` minus its `amount_paid_cents` so far — or the posting is rejected with `ERR_OVERPAYMENT`; when cumulative payments bring `amount_paid_cents` level with `total_cents`, the invoice becomes `PAID`. Settling the `FINAL` invoice — while that invoice is `ISSUED` — moves the permit's financial dimension `INVOICED` → `SETTLED`, reduces the renter's `outstanding_balance_cents` by the payment, and releases the deposit: a `DEPOSIT_REFUND` transaction posts for the full `deposit_held_cents`, unless a damage assessment in `OPEN`, `ADJUDICATED`, or `APPEALED` exists for the permit, in which case the deposit stays held and the financial dimension moves to `FORFEIT_PENDING` instead (§3.8). When a `FINAL` invoice's total is zero — an `INTERNAL` booking with no staffing — settlement happens automatically at issuance. Refunds post as `DEPOSIT_REFUND` and `FEE_REFUND` transactions; when a cancellation requested `refund_destination` of `CREDIT`, the refunded amount is added to the renter's `credit_balance_cents` as it posts, and that credit is applied to future invoices before any card is charged.

### 3.6. Event Completion, Custodial Verification, and Invoice Mathematics

After the logical clock has passed `occupancy_end`, a `SiteCoordinator` marks the event complete, moving the permit `ACTIVE` → `COMPLETED`. Completion voids the `PROVISIONAL` invoice, generates the `FINAL` invoice from actuals, and moves the financial dimension to `INVOICED` if it is not already there. Completion also makes the custodial work order eligible for verification — but verification is a separate, deliberate act, not an automatic consequence.

The **CustodialWorkOrder** is created in `SCHEDULED` at approval whenever the facility's `requires_custodian` flag is set. Its `scheduled_start` is the permit's `blocked_start` — the custodian arrives at setup — and its `scheduled_end` is the `blocked_end`, departing only after teardown; `estimated_hours` is that full scheduled span expressed in hours to two decimal places, which means the buffers are billable custodial time. Two flags are computed over the scheduled span in site-local time: `after_hours_flag` is true when any minute of the span falls outside the 07:00–18:00 Monday-through-Friday business window, and `weekend_flag` is true when any minute falls on a Saturday or Sunday; both flags may be true at once. When the permit activates, the work order moves `SCHEDULED` → `IN_PROGRESS`. Verification — the `CustodialSupervisor` attesting `actual_hours`, a field that is null until verification and thereafter holds a value greater than zero carried to two decimals — requires the permit to be `COMPLETED` and moves the order `IN_PROGRESS` → `VERIFIED`, recomputing the `FINAL` invoice's staffing and after-hours components from the verified hours. Once the `FINAL` invoice is `ISSUED` including that work order's charges, the order moves `VERIFIED` → `BILLED`. And whenever a permit is cancelled, lapsed, or superseded, its work orders in `SCHEDULED` or `IN_PROGRESS` are cancelled by the system.

The **Invoice** is where the money lands. Four kinds exist: `PROVISIONAL`, the estimate issued at approval; `FINAL`, the actuals issued after completion; `REFUND`, issued at cancellation; and `DAMAGE`, issued at forfeiture. An invoice is born in `DRAFT` and issued — `DRAFT` → `ISSUED` — immediately at approval for the provisional, at completion for the final, and at its trigger event for refunds and damage charges. Issuance of a `FINAL` or `DAMAGE` invoice accrues `total_cents` onto the renter's `outstanding_balance_cents`. An `ISSUED` invoice becomes `PAID` when its `amount_paid_cents` equals its `total_cents`, and payment subtracts the total from the outstanding balance — a settlement that can itself restore a `SUSPENDED` organization to `GOOD_STANDING`. A `DRAFT` or `ISSUED` invoice moves to the terminal `VOID` when the provisional is superseded by the final or when its permit is cancelled, lapsed, or superseded; voiding an invoice that was `ISSUED` subtracts its `total_cents` from the outstanding balance, reversing the accrual. An `ISSUED` refund invoice becomes `REFUNDED` once its refund transactions post. The invoice's paid-so-far field `amount_paid_cents` is the sum of posted `FEE_PAYMENT` transactions against it and starts at 0.

Invoice amounts are assembled in a pinned order, and the order is part of the contract. **First, the rental component.** The occupancy window's duration in minutes is divided into whole 30-minute blocks, any partial block rounding up to a full block; the block count halved gives the billable hours. The base rental fee is those billable hours multiplied by the covering policy's `hourly_rate_cents`, an exact multiplication with no rounding. A booking of at least 6 billable hours earns a long-booking rebate of 10 percent off that base, and the rebated figure is rounded half-up to integer cents — the single rounding step in the rental computation. The result is `rental_fee_cents`; an `INTERNAL` policy's rate of zero yields a fee of zero. **Second, the staffing component.** The hours figure — `estimated_hours` for a provisional invoice, verified `actual_hours` for a final one — is multiplied by the policy's `custodial_hourly_cents` and rounded half-up to integer cents. A minimum-shift floor applies: whenever the hours are greater than zero but less than 2.0, exactly 2.0 hours are billed instead, that product likewise rounded half-up. The result is `staffing_charge_cents`; when a facility needs no custodian there is no work order and the staffing component is zero. Each monetary component is rounded individually before any summation — summing raw values and rounding once at the end is forbidden, because it produces different cents. **Third, the after-hours uplift.** The uplift percentage is 50 percent when `after_hours_flag` is set, plus 25 percent when `weekend_flag` is set — the two compose additively on the staffing base, not multiplicatively — and the charge is the already-rounded `staffing_charge_cents` multiplied by that combined percentage, the product rounded half-up to integer cents, landing in `after_hours_charge_cents`; when neither flag is set the charge is zero. **Fourth, the subtotal**: the sum of the rental, staffing, and after-hours components. **Fifth, the volume discount**, keyed on that pre-discount subtotal with inclusive floors: a subtotal of at least 200000 cents earns 15 percent; otherwise at least 100000 cents earns 10 percent; otherwise at least 50000 cents earns 5 percent; below that, nothing. The tier is selected on the pre-discount subtotal and is not re-keyed after discounting. **Sixth**, `discount_cents` is the subtotal multiplied by the tier percentage, computed on the exact integer subtotal and rounded half-up once. **Seventh**, `total_cents` is the subtotal minus the discount, floored at zero so a total is never negative.

The provisional and final variants differ in exactly one input and one derived consequence. The rental component is re-quoted at completion over the confirmed occupancy window — identical to the requested window in practice, since partial supersession is not supported — so the money that actually moves is staffing: the provisional bills the estimated span while the final bills verified actual hours, which almost always differ. And because the discount tier re-keys on the final subtotal, actuals that push the subtotal across a tier boundary — past 100000 cents, say — move the provisional and final totals apart by more than the staffing delta alone.

### 3.7. Cancellation, Preemption, and the Refund Waterfall

Either the renter's own representative or the `FacilitiesDirector` may cancel a permit, supplying a `cancellation_reason` and optionally a `refund_destination`. Cancellation is only possible from `ISSUED` — once a permit has activated, post-event disputes travel through the damage process instead, and a cancel attempt against a permit in any other status is rejected with `ERR_PERMIT_NOT_CANCELLABLE`. A successful cancellation moves the permit `ISSUED` → `CANCELLED`, cancels its custodial work order, voids its `PROVISIONAL` invoice, runs the refund waterfall below, and sweeps the freed interval for waitlist promotion. The financial dimension moves from `SECURED` or `DEPOSIT_PENDING` to `REFUND_PENDING` when a refundable amount above zero exists, and on to `REFUNDED` once the refund transactions post; when the applicable tier refunds nothing at all, it moves instead to `SETTLED`.

The refund tier turns on how far ahead of the event the cancellation lands, measured in whole calendar days between the cancellation timestamp and `occupancy_start` in site-local dates, with every comparison inclusive of its lower bound. An administrative cancellation — supersession by a tier-0 calendar event, the renter being barred, or the site closing — refunds one hundred percent of what was paid and charges no fee. Fourteen or more days before the event likewise refunds one hundred percent with no fee. At least seven but fewer than fourteen days before, half of what was paid is refundable, less a processing fee of 2500 cents. Fewer than seven days before, nothing is refundable — the paid amounts are fully forfeited — and no fee applies. The waterfall itself runs in cents: gross paid is `deposit_held_cents` plus the sum of all `FEE_PAYMENT` amounts posted against the permit's invoices; the refundable figure is gross paid multiplied by the tier's refund percentage, rounded half-up once at that multiplication; the refund total is that figure minus the processing fee, floored at zero. The refund pays the deposit back first — the deposit refund is the smaller of the refund total and the held deposit, posted as `DEPOSIT_REFUND` — and any remainder comes back as a `FEE_REFUND`; whatever part of the held deposit is not refunded posts as `DEPOSIT_FORFEIT` to the district. A `REFUND` invoice is issued for the refundable amount, and a renter who chose a `refund_destination` of `CREDIT` sees the refund land in `credit_balance_cents` rather than on a card.

Preemption is the calendar striking back. When a tier-0 SchoolCalendarEvent is created over the blocked interval of an `ISSUED` permit, the system moves the permit `ISSUED` → `SUPERSEDED`: no replacement permit is minted, `superseded_by_permit_id` stays null, the refund waterfall runs under the administrative class — deposit and any fees returned in full, no cancellation fee — the financial dimension moves to `REFUND_PENDING`, and the work order is cancelled. Supersession is sticky: cancelling the preempting calendar event later does not reinstate the superseded permit, though the freed window does trigger a waitlist sweep. The same sweep runs whenever any permit's interval frees — cancellation, lapse, or supersession alike.

### 3.8. Damage Assessment, Adjudication, and Deposit Forfeiture

Damage money moves through a four-step ceremony designed so that no single operator controls it. Intake belongs to the `SiteCoordinator`: on a `COMPLETED` permit, they record a **DamageAssessment** whose `line_items` form a non-empty array, each entry carrying a `description` and a `repair_cost_cents` strictly greater than zero — an empty array or any non-positive cost is rejected with `ERR_EMPTY_DAMAGE_CLAIM`. The system stamps the caller's `X-User-ID` as `recorded_by_user_id`, computes `total_claimed_cents` as the sum of the line items' repair costs, opens the assessment in `OPEN`, and freezes the permit's deposit in the same motion: the financial dimension moves from `SECURED` or `INVOICED` to `FORFEIT_PENDING`, suspending any release pending adjudication.

Adjudication belongs to the `FacilitiesDirector`, who awards an `adjudicated_amount_cents` — null until this point — of at least zero and at most `total_claimed_cents`; anything above the claim is rejected with `ERR_ADJUDICATION_EXCEEDS_CLAIM`. Segregation of duties binds here: the operator who recorded the intake may not adjudicate it, and a caller whose `X-User-ID` equals the assessment's `recorded_by_user_id` is rejected with `ERR_SEGREGATION_OF_DUTIES`. Adjudication moves the assessment `OPEN` → `ADJUDICATED` and deliberately leaves the permit frozen in `FORFEIT_PENDING`.

The renter then has fourteen days, measured on the logical clock, to answer. Acceptance — or the window elapsing with no appeal — moves the assessment `ADJUDICATED` → `FINAL`. An appeal, filed with an `appeal_reason`, moves it `ADJUDICATED` → `APPEALED`; an appeal attempted after the fourteen-day window is rejected with `ERR_APPEAL_WINDOW_ELAPSED`. An appealed assessment is resolved by a `FacilitiesDirector` setting a `final_amount_cents`, again capped at `total_claimed_cents` with the same `ERR_ADJUDICATION_EXCEEDS_CLAIM` guard, and again under segregation of duties with the same `ERR_SEGREGATION_OF_DUTIES` guard; resolution overwrites `adjudicated_amount_cents` with the final amount and moves the assessment `APPEALED` → `FINAL`.

Finalization runs the deposit forfeiture allocation, an exact integer-cents waterfall with no rounding. The amount applied to damage is the smaller of the held deposit and the adjudicated amount; the rest of the held deposit comes back to the renter as a `DEPOSIT_REFUND`; and any adjudicated shortfall beyond the deposit becomes a `DAMAGE` invoice — a `DAMAGE_CHARGE` — added to the renter's `outstanding_balance_cents`. The allocation conserves on both sides: applied-to-damage plus deposit-refunded equals the held deposit, and applied-to-damage plus shortfall equals the adjudicated amount. A finalization with an adjudicated amount above zero moves the permit `FORFEIT_PENDING` → `FORFEITED` and increments the renter's `forfeiture_count` by one — and a renter whose lifetime count reaches three is suspended from that moment. A finalization with an adjudicated amount of exactly zero moves the permit `FORFEIT_PENDING` → `SETTLED` instead, releasing the full held deposit as a `DEPOSIT_REFUND`.

### 3.9. Recurring Seasonal Permits

A community program that meets every Saturday all season should not have to fight the calendar week by week. A **SeasonalPermit** series is created by the renter's representative or the `FacilitiesDirector` with the `renter_org_id` and `facility_id`, a `series_name` such as "Fall Soccer Saturdays", a `recurrence_rule` encoding the weekly pattern as weekday plus local start and end times (for example `WEEKLY:SAT:18:00-21:00`), and a season window from `season_start` (inclusive) to `season_end` (inclusive), where the end must be at or after the start and the whole span may not exceed 120 days — a longer season is rejected with `ERR_INVALID_TIME_WINDOW`.

A series may renew a prior one through `renewed_from_id`. The referenced series must belong to the same renter, must be a real series in `COMPLETED` or `ACTIVE` status, and must not already have been renewed by another series — violations are rejected with `ERR_RENEWAL_NOT_RENEWABLE`. Renewal carries the optimistic-concurrency field `expected_series_version` per §2.8, and a successful renewal increments the renewed-from series' `version` by one. Seniority is hereditary: the new series' `seniority_key` is inherited from the renewed-from series' own `seniority_key`, so the earlier chain root wins conflicts; a series that renews nothing takes its own `created_at` as its `seniority_key`.

Generation expands the recurrence rule across the season window in site-local time, producing occurrence dates in chronological order; each occurrence becomes a RentalRequest that is auto-submitted and run through the approval pipeline in date order, earliest first. A conflict on one occurrence does not block the next — failures are collected, not fatal — and every occurrence that passes the conflict and insurance checks receives its own Permit, linked back to the series through `seasonal_permit_id`. When at least one occurrence is approved, the series leaves `PENDING_GENERATION` for `ACTIVE`; when some occurrences failed but at least one succeeded, it lands in `PARTIALLY_BLOCKED` instead. Pricing is per occurrence: each occurrence is billed under the `ACTIVE` policy covering its own start, so a series that straddles a rate-year boundary bills its later occurrences at the new rate. When the logical clock passes `season_end`, an `ACTIVE` or `PARTIALLY_BLOCKED` series moves to the terminal `COMPLETED`. Cancelling a series — from `PENDING_GENERATION`, `ACTIVE`, or `PARTIALLY_BLOCKED`, by the renter or the `FacilitiesDirector` with a `reason` — cancels every future-dated permit of the series under the administrative class with a full refund; past and completed permits are unaffected.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource — a site, a facility, a rate policy, a renter registration, an insurance certificate, a calendar event, a rental request, a payment transaction, a damage assessment, or a seasonal series — return a `201 Created` status code. Operations that modify an existing resource or drive a lifecycle action — including closing, holding, releasing, retiring, barring, revoking, submitting, resubmitting, withdrawing, reviewing, approving, denying, waitlisting, cancelling, completing, verifying, adjudicating, accepting, appealing, resolving, and setting the logical clock — return a `200 OK` status code. The table below is deliberately minimal: request bodies, response payloads, and side effects are defined by the narratives in §2 and §3, not here.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/district/_clock/set_current_utc` | Set the server logical clock; advancing it fires all time-based system transitions | DistrictAdmin |
| POST | `/district/sites` | Create a school site | DistrictAdmin |
| GET | `/district/sites/{site_id}` | Get a site | All roles |
| POST | `/district/sites/{site_id}/close` | Close a site; cascades request withdrawals and facility retirement | DistrictAdmin |
| GET | `/district/sites/{site_id}/facilities` | List facilities of a site | All roles |
| POST | `/district/sites/{site_id}/facilities` | Create a facility within a site | DistrictAdmin |
| GET | `/district/facilities` | List facilities district-wide, filterable by site, status, and tier | All roles |
| GET | `/district/facilities/{facility_id}` | Get a facility | All roles |
| POST | `/district/facilities/{facility_id}/hold` | Place a facility on maintenance hold | DistrictAdmin |
| POST | `/district/facilities/{facility_id}/release_hold` | Release a maintenance hold | DistrictAdmin |
| POST | `/district/facilities/{facility_id}/retire` | Retire a facility | DistrictAdmin |
| POST | `/district/rate_policies` | Create a rate class policy for a (rate class, facility tier) pair and effective window | DistrictAdmin |
| GET | `/district/rate_policies` | List rate policies, filterable | DistrictAdmin, FacilitiesDirector, SiteCoordinator |
| GET | `/district/rate_policies/{policy_id}` | Get a rate policy | DistrictAdmin, FacilitiesDirector, SiteCoordinator |
| POST | `/district/renters` | Register a renter organization | FacilitiesDirector, DistrictAdmin |
| GET | `/district/renters/{org_id}` | Get a renter organization | FacilitiesDirector, DistrictAdmin, SiteCoordinator, RenterOrgRep |
| GET | `/district/renters` | List renter organizations | FacilitiesDirector, DistrictAdmin, SiteCoordinator |
| POST | `/district/renters/{org_id}/bar` | Bar a renter organization (terminal; cascades) | FacilitiesDirector |
| GET | `/district/renters/{org_id}/requests` | List a renter's requests | FacilitiesDirector, DistrictAdmin, SiteCoordinator, RenterOrgRep |
| GET | `/district/renters/{org_id}/insurance_certificates` | List a renter's insurance certificates | FacilitiesDirector, DistrictAdmin, SiteCoordinator, RenterOrgRep |
| GET | `/district/renters/{org_id}/seasonal_permits` | List a renter's seasonal permit series | FacilitiesDirector, DistrictAdmin, SiteCoordinator, RenterOrgRep |
| POST | `/district/renters/{org_id}/insurance_certificates` | Upload an insurance certificate | RenterOrgRep, FacilitiesDirector |
| GET | `/district/insurance_certificates` | List insurance certificates district-wide | FacilitiesDirector, DistrictAdmin, SiteCoordinator |
| GET | `/district/insurance_certificates/{cert_id}` | Get an insurance certificate | FacilitiesDirector, DistrictAdmin, SiteCoordinator, RenterOrgRep |
| POST | `/district/insurance_certificates/{cert_id}/revoke` | Revoke a certificate | FacilitiesDirector |
| POST | `/district/sites/{site_id}/calendar_events` | Create a school calendar event; tier-0 events preempt overlapping ISSUED permits | DistrictAdmin |
| GET | `/district/sites/{site_id}/calendar_events` | List calendar events for a site | All roles |
| GET | `/district/calendar_events` | List calendar events district-wide, filterable | All roles |
| GET | `/district/calendar_events/{event_id}` | Get a calendar event | All roles |
| POST | `/district/calendar_events/{event_id}/cancel` | Cancel a calendar event; does not un-supersede permits | DistrictAdmin |
| POST | `/district/renters/{org_id}/requests` | Create a rental request in DRAFT | RenterOrgRep |
| GET | `/district/requests/{request_id}` | Get a rental request | FacilitiesDirector, DistrictAdmin, SiteCoordinator, RenterOrgRep |
| GET | `/district/requests` | List requests district-wide, filterable | FacilitiesDirector, DistrictAdmin, SiteCoordinator |
| POST | `/district/renters/{org_id}/requests/{request_id}/submit` | Submit a DRAFT request | RenterOrgRep |
| POST | `/district/renters/{org_id}/requests/{request_id}/resubmit` | Resubmit a REVISION_REQUESTED request with revised fields | RenterOrgRep |
| POST | `/district/renters/{org_id}/requests/{request_id}/withdraw` | Withdraw a non-terminal request | RenterOrgRep |
| POST | `/district/requests/{request_id}/begin_review` | Move a SUBMITTED or RESUBMITTED request to UNDER_REVIEW | SiteCoordinator |
| POST | `/district/requests/{request_id}/request_revision` | Send a request back for revision | SiteCoordinator |
| POST | `/district/requests/{request_id}/approve` | Approve an UNDER_REVIEW request: issues the permit, provisional invoice, and work order; demotes lower-priority overlapping requests | FacilitiesDirector |
| POST | `/district/requests/{request_id}/deny` | Deny an UNDER_REVIEW request | FacilitiesDirector |
| POST | `/district/requests/{request_id}/waitlist` | Manually waitlist a pending request | FacilitiesDirector |
| GET | `/district/permits/{permit_id}` | Get a permit, both state dimensions | All roles |
| GET | `/district/permits` | List permits, filterable | FacilitiesDirector, DistrictAdmin, SiteCoordinator, CustodialSupervisor |
| GET | `/district/requests/{request_id}/permits` | List permits issued from a request (zero or one) | FacilitiesDirector, DistrictAdmin, SiteCoordinator, RenterOrgRep |
| POST | `/district/permits/{permit_id}/cancel` | Cancel an ISSUED permit; runs the refund waterfall and waitlist sweep | RenterOrgRep, FacilitiesDirector |
| POST | `/district/permits/{permit_id}/complete` | Mark an event completed after occupancy end; generates the FINAL invoice from actuals | SiteCoordinator |
| GET | `/district/permits/{permit_id}/work_orders` | List custodial work orders of a permit | All roles |
| GET | `/district/permits/{permit_id}/invoices` | List invoices of a permit | FacilitiesDirector, DistrictAdmin, SiteCoordinator, RenterOrgRep |
| GET | `/district/permits/{permit_id}/payments` | List payment transactions of a permit | FacilitiesDirector, DistrictAdmin, SiteCoordinator, RenterOrgRep |
| GET | `/district/permits/{permit_id}/damage_assessments` | List damage assessments of a permit | FacilitiesDirector, DistrictAdmin, SiteCoordinator, RenterOrgRep |
| POST | `/district/permits/{permit_id}/payments` | Post a payment (DEPOSIT_CAPTURE or FEE_PAYMENT) with an idempotency key | RenterOrgRep |
| GET | `/district/payments/{payment_id}` | Get a single payment transaction | FacilitiesDirector, DistrictAdmin, SiteCoordinator, RenterOrgRep |
| GET | `/district/payments` | List payment transactions district-wide, filterable | FacilitiesDirector, DistrictAdmin, SiteCoordinator |
| GET | `/district/work_orders/{wo_id}` | Get a work order | FacilitiesDirector, DistrictAdmin, SiteCoordinator, CustodialSupervisor |
| GET | `/district/work_orders` | List work orders | FacilitiesDirector, DistrictAdmin, SiteCoordinator, CustodialSupervisor |
| POST | `/district/work_orders/{wo_id}/verify` | Verify actual custodial hours; drives the FINAL staffing charge | CustodialSupervisor |
| GET | `/district/invoices/{invoice_id}` | Get an invoice | FacilitiesDirector, DistrictAdmin, SiteCoordinator, RenterOrgRep |
| GET | `/district/invoices` | List invoices, filterable | FacilitiesDirector, DistrictAdmin, SiteCoordinator |
| POST | `/district/permits/{permit_id}/damage_assessments` | Record damage intake on a COMPLETED permit; freezes deposit release | SiteCoordinator |
| GET | `/district/damage_assessments` | List damage assessments district-wide, filterable | FacilitiesDirector, DistrictAdmin, SiteCoordinator |
| GET | `/district/damage_assessments/{assessment_id}` | Get a damage assessment | FacilitiesDirector, DistrictAdmin, SiteCoordinator, RenterOrgRep |
| POST | `/district/damage_assessments/{assessment_id}/adjudicate` | Adjudicate the damage amount; cannot be the intake coordinator | FacilitiesDirector |
| POST | `/district/damage_assessments/{assessment_id}/accept` | Renter accepts the adjudication; forfeiture allocation runs | RenterOrgRep |
| POST | `/district/damage_assessments/{assessment_id}/appeal` | Appeal an adjudication within fourteen days | RenterOrgRep |
| POST | `/district/damage_assessments/{assessment_id}/resolve_appeal` | Resolve an appeal with a final amount; cannot be the intake coordinator | FacilitiesDirector |
| POST | `/district/seasonal_permits` | Create a recurring seasonal permit series; expands occurrences through the approval pipeline; renewals require the OCC field | RenterOrgRep, FacilitiesDirector |
| GET | `/district/seasonal_permits/{series_id}` | Get a seasonal permit series | FacilitiesDirector, DistrictAdmin, SiteCoordinator, RenterOrgRep |
| GET | `/district/seasonal_permits` | List seasonal permit series, filterable | FacilitiesDirector, DistrictAdmin, SiteCoordinator |
| POST | `/district/seasonal_permits/{series_id}/cancel` | Cancel a series; future permits are cancelled with a full administrative refund | RenterOrgRep, FacilitiesDirector |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this catalogue is the index.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_RENTER_NOT_IN_GOOD_STANDING` | 402 Payment Required |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 402 Payment Required |
| `ERR_OVERPAYMENT` | 402 Payment Required |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_SCHEDULE_CONFLICT` | 409 Conflict |
| `ERR_DUPLICATE` | 409 Conflict |
| `ERR_IDEMPOTENCY_CONFLICT` | 409 Conflict |
| `ERR_REVISION_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_APPEAL_WINDOW_ELAPSED` | 409 Conflict |
| `ERR_FACILITY_NOT_AVAILABLE` | 409 Conflict |
| `ERR_SITE_CLOSED` | 409 Conflict |
| `ERR_PERMIT_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_INSURANCE_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_INVALID_TIME_WINDOW` | 422 Unprocessable Entity |
| `ERR_REFERENCE_INVALID` | 422 Unprocessable Entity |
| `ERR_ADJUDICATION_EXCEEDS_CLAIM` | 422 Unprocessable Entity |
| `ERR_EMPTY_DAMAGE_CLAIM` | 422 Unprocessable Entity |
| `ERR_RENEWAL_NOT_RENEWABLE` | 422 Unprocessable Entity |
