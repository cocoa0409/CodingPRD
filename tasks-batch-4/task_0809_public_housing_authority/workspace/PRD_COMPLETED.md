# Public Housing Authority API — Product Requirements Document

## 1. Introduction

This document specifies the operational backbone of a Public Housing Authority (PHA): the system of record that carries a household from its first application, through the waitlist lottery, into a leased unit, and across the full arc of annual and interim recertifications, HUD-50058 reporting, grievances, and eviction. The domain is fundamentally an allocation engine layered over a pricing engine — scarce units must be rationed fairly by preference points and a lottery draw, and once a household is housed, its rent must be recomputed deterministically under federal rent rules every time its income or composition changes.

The API is designed for four operational audiences whose responsibilities never fully overlap: intake staff who register applicants and administer waitlists, housing specialists who extend offers and drive the certification and HUD workflow, property managers who own the physical unit inventory and adjudicate evictions, and the households themselves who accept or refuse offers and report changes in their circumstances. Because nearly every meaningful action cascades — accepting an offer simultaneously creates a tenancy, occupies a unit, houses a waitlist entry, and withdraws that household's competing entries — the system settles every cascade atomically within the triggering request, so a caller never observes a half-applied transition.

A deterministic logical clock underpins the entire system. Application ordering, offer expiry, make-ready turnaround, and stale-entry purge are all measured against this clock rather than wall-clock time, so that the same sequence of requests always produces the same allocation and the same rent.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that govern every endpoint. All URL paths in this document are mounted under the `/pha` prefix.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is missing, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes exactly four roles, spelled precisely as follows: `IntakeClerk`, `HousingSpecialist`, `PropertyManager`, and `Applicant`.

Once a caller is authenticated, the system checks that their role is permitted to perform the requested operation and, where ownership applies, that they own the target resource. A role attempting an operation outside its authority, or an `Applicant` acting on a resource it does not own, is rejected with `ERR_UNAUTHORIZED` (HTTP 403). Authentication is always evaluated before authorization: a request lacking valid headers fails with `ERR_UNAUTHENTICATED` before any role or ownership check runs.

The three staff roles are opaque identities. When `X-User-Role` is `IntakeClerk`, `HousingSpecialist`, or `PropertyManager`, the accompanying `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. The `Applicant` role is entity-backed: when `X-User-Role` is `Applicant`, `X-User-ID` is the `id` of the acting `Applicant`, and ownership checks on any resource that references an `Applicant` compare that resource's applicant foreign key to `X-User-ID`. Concretely, an `Applicant` may only accept or refuse an offer, report an interim change, file a grievance, or read a resource that belongs to its own household; the applicant behind an offer is reached through the offer's waitlist entry, and the applicant behind a tenancy, certification, interim change, or grievance is reached through the tenancy.

Role authority is partitioned by responsibility. An `IntakeClerk` registers applicants, adds household members, claims and verifies or revokes preference claims, and administers waitlists (creation, enrollment, the lottery draw, and the stale purge). A `HousingSpecialist` creates offers, creates and finalizes certifications, submits and records HUD-50058 results, and processes interim changes. A `PropertyManager` owns unit creation and decides grievances and evictions. An `Applicant` accepts or refuses offers, reports interim changes, and — together with staff — may claim a preference and file a grievance. All read (GET) endpoints are available to every one of the four roles. The precise authorization set per endpoint is given in the §4 table.

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

List endpoints are paginated through two query parameters. The `limit` parameter bounds the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless a specific workflow states otherwise, list endpoints return their resources sorted by creation timestamp (`created_at`) in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `total_count` reflects the full number of matching resources before the limit and offset are applied and `has_more` indicates whether further pages remain.

### 2.4. Common Resource Properties

Every persisted resource in this system — `Applicant`, `HouseholdMember`, `PreferenceClaim`, `Waitlist`, `WaitlistEntry`, `Unit`, `Offer`, `Tenancy`, `Certification`, `InterimChange`, and `Grievance` — carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, fixed at the moment the resource is first created. The `updated_at` field is an ISO 8601 UTC timestamp, refreshed on every mutation to the resource. The `version` field is an integer that begins at 1 (or 0, per the server's chosen origin) and increments by exactly one on every mutation; it is the basis for the optimistic concurrency control described in §2.6. Whenever the system mutates a resource — including a system-driven cascade the caller did not explicitly request on that resource — it refreshes that resource's `updated_at` and increments its `version`.

All datetime fields — including the domain timestamps `application_date`, `offered_at`, `expires_at`, `last_contact_at`, `last_lease_end_date`, `lease_start_date`, `lease_end_date`, `effective_date`, `reported_at`, and `filed_at` — are represented as ISO 8601 UTC instants.

### 2.5. Path Resolution and Validation Ordering

When a path names one or more resource identifiers, the system resolves them left to right and rejects the request at the first identifier that does not correspond to a live resource, returning the not-found error specific to that resource — `ERR_APPLICANT_NOT_FOUND`, `ERR_PREFERENCE_CLAIM_NOT_FOUND`, `ERR_WAITLIST_NOT_FOUND`, `ERR_WAITLIST_ENTRY_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`, `ERR_OFFER_NOT_FOUND`, `ERR_TENANCY_NOT_FOUND`, `ERR_CERTIFICATION_NOT_FOUND`, `ERR_INTERIM_CHANGE_NOT_FOUND`, or `ERR_GRIEVANCE_NOT_FOUND` (all HTTP 404). For example, enrolling an applicant on a waitlist that does not exist fails with `ERR_WAITLIST_NOT_FOUND` before the request body is examined.

The system applies its checks in a fixed precedence, and the first check that fails determines the error. Authentication (`ERR_UNAUTHENTICATED`) is evaluated first, then authorization and ownership (`ERR_UNAUTHORIZED`), then path existence (the 404 family above). Only after these guards pass does the system evaluate resource-specific concerns: the optimistic-concurrency version check (`ERR_STALE_VERSION`) where it applies, then whether the target resource is in a state that admits the requested transition (`ERR_INVALID_STATE`), then cross-entity state and business constraints, and finally — as the lowest-priority guard — request-body field validation (`ERR_VALIDATION`), which confirms that required fields are present, that types and enum members are valid, and that amounts declared as non-negative are not negative. Each workflow in §3 states the additional ordering that applies among its own business checks.

### 2.6. Optimistic Concurrency on Tenancy Certifications

Creating a certification against a tenancy is guarded by optimistic concurrency control on the parent tenancy. A request to create a new certification for a tenancy must carry `expected_tenancy_version`, a non-optional field that holds the `version` of the target `Tenancy` as the client last observed it. If `expected_tenancy_version` does not equal the tenancy's current `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412). This captures the situation where another writer has already created or finalized a certification that legitimately supersedes the prior one, advancing the tenancy's `version` since the client last read it; the current writer's view is stale, so its create must not proceed. A successful create increments the tenancy's `version` by one, so a second create replaying the same `expected_tenancy_version` will also be rejected. No other endpoint takes a version field; optimistic concurrency applies only to certification creation.

### 2.7. Monetary Amounts, Cents, and Rounding

All money in this system is stored and returned as whole integer cents — incomes, deductions, allowances, income limits, tenant rent, reimbursements, and the Total Tenant Payment are all integers, never fractional dollars. Household income aggregation is an exact integer sum of whole-cent inputs and needs no rounding. Where a calculation multiplies a monetary figure by a percentage rate — the medical-expense threshold and the two percentage components of the Total Tenant Payment — the result is rounded to a whole number of cents using the round-half-up method (a value exactly halfway between two whole cents rounds up). The precise points at which rounding is applied, and the pinned order of operations around each rounding step, are specified with the rent calculations in §3.5; the rule that must never be violated is that no percentage figure is pre-rounded before the rounding step the formula prescribes.

### 2.8. Cascading Occupancy and State Propagation

Many operations mutate more than one resource, and every such cascade settles atomically inside the triggering request. The clearest example is offer acceptance, which in a single transaction accepts the offer, creates a tenancy and its initial draft certification, occupies the unit, houses the accepting waitlist entry, houses the applicant, and withdraws that applicant's other still-in-play waitlist entries. Each resource touched by a cascade independently has its `updated_at` refreshed and its `version` incremented, exactly as a direct mutation would. The individual propagation rules — which state a parent moves to when a child changes, and vice versa — are described in the §3 workflow where each transition originates. The governing principle is that the stored state of units, waitlist entries, applicants, tenancies, and certifications must always be mutually consistent at the end of any request, with no client action required to reconcile them afterward.

### 2.9. The Logical Clock and Temporal Rules

The server maintains a single logical clock that supplies "now" for every time-dependent rule: the `application_date` stamped on a new applicant, the `offered_at` stamped on a new offer, the `last_contact_at` refreshed by waitlist activity, the `reported_at` and `filed_at` stamps, and the lease dates. On startup the clock reads exactly `2026-03-01T00:00:00Z`, and until it is explicitly set it never advances to real wall-clock time. An administrative capability lets any staff role set the clock to a supplied ISO-8601 UTC instant via the `to_iso8601` field, after which all subsequent reads of "now" use that instant. This endpoint responds `200 OK` with a `data` object of the shape `{ "current_utc": <the newly set instant, ISO-8601 UTC> }` rather than a persisted resource. Offer expiry, the make-ready turnaround buffer, and the stale-entry purge are all measured against this logical clock, so a test can advance time deterministically and observe the resulting allocation.

## 3. Business Logic & Workflows

### 3.1. Applicant Intake and Household Composition

An `IntakeClerk` opens the pipeline by registering an applicant household, supplying only the `household_name`. The new `Applicant` begins in the `APPLIED` state, and the system stamps its `application_date` from the logical clock at creation time. That `application_date` is load-bearing well beyond intake: it is the deterministic tie-order source that decides preliminary waitlist rank and the order in which lottery numbers are assigned, so two applicants registered at different clock instants have a stable, reproducible ordering. An applicant's lifecycle `status` is one of `APPLIED`, `WAITLISTED`, `HOUSED`, or `WITHDRAWN`; it moves off `APPLIED` automatically the first time the household is enrolled on a waitlist, and `HOUSED` and `WITHDRAWN` are terminal.

The same clerk builds out the household by adding members. Each `HouseholdMember` belongs to one applicant and is created with a `full_name` and a `relationship` — one of `HEAD`, `SPOUSE`, `DEPENDENT`, or `OTHER_ADULT`. A member also carries several optional attributes that drive later rent math: `annual_income_cents` is the member's recurring annual income in whole cents (defaulting to 0 and never negative); `nonrecurring_income_cents` is one-time or non-recurring annual income such as a bonus or lump sum, again in whole cents, defaulting to 0 and never negative; `is_dependent` marks a member who counts toward the dependent deduction (default false); `is_elderly` marks a member aged at least 62 (default false); and `is_disabled` marks a disabled member (default false). Household members are reference data, not lifecycle entities — they have no status and are always counted in full when a certification is finalized.

Two applicant fields are kept denormalized and are recomputed whenever the household roster changes: `household_size` is the count of the applicant's household members, and `annual_gross_income_cents` is the sum of `annual_income_cents` across all of the applicant's members (the recurring figure only, matching the actual-income variant, excluding non-recurring amounts). Adding a member therefore refreshes both figures on the parent applicant.

### 3.2. Admission Preferences and Verified Points

Admission preferences let a household earn ranking points. Either an `IntakeClerk` or the `Applicant` itself may claim a preference on an applicant by supplying a `preference_type`, one of `VETERAN`, `ELDERLY`, `DISABLED`, `INVOLUNTARY_DISPLACEMENT`, `LOCAL_RESIDENT`, or `WORKING_FAMILY`. A new `PreferenceClaim` starts in `CLAIMED` with `points_awarded` of 0. `CLAIMED` is not terminal; `DENIED` is.

Verification is an `IntakeClerk` responsibility, expressed by supplying a `decision` of `VERIFY` or `DENY`. A decision to verify moves a `CLAIMED` claim to `VERIFIED` and sets its `points_awarded` from the preference schedule: a `VETERAN` preference is worth 50 points, `INVOLUNTARY_DISPLACEMENT` 40, `ELDERLY` and `DISABLED` 30 each, `LOCAL_RESIDENT` 20, and `WORKING_FAMILY` 10. A decision to deny moves a `CLAIMED` claim to `DENIED` and leaves `points_awarded` at 0. Only a claim currently in `CLAIMED` may be verified or denied; acting on a claim in any other state is rejected with `ERR_INVALID_STATE`.

Verifying a claim immediately recomputes the applicant's standing. The `total_points` on every one of that applicant's waitlist entries is the sum of `points_awarded` over the applicant's `VERIFIED` claims — claims in `CLAIMED` or `DENIED` contribute nothing — and this figure is recomputed on the applicant's waitlist entries at the moment the claim is verified. A clerk may also revoke a previously verified claim as a compensating action: revoking returns a `VERIFIED` claim to `CLAIMED`, resets its `points_awarded` back to 0, and recomputes `total_points` on each of the applicant's waitlist entries so the removed points are subtracted. Only a `VERIFIED` claim may be revoked; otherwise `ERR_INVALID_STATE` is returned.

### 3.3. Waitlist Enrollment, the Lottery, Ranking, and Purge

A waitlist is created by an `IntakeClerk` for a given `site_name` and `bedroom_size`, where `bedroom_size` is a bedroom count between 0 and 6 inclusive. Its `status` defaults to `OPEN` but may be created `CLOSED` by passing the optional `status`; only `OPEN` and `CLOSED` are valid. A new waitlist has `lottery_drawn` set to false, indicating no draw has yet assigned lottery numbers.

Enrolling an applicant onto a waitlist creates a `WaitlistEntry` for the supplied `applicant_id`, linked to the enrolling waitlist through its `waitlist_id` (the waitlist is named in the path). The entry begins in `PENDING`, its `last_contact_at` is stamped from the logical clock, and — if this is the first waitlist entry for that applicant — the applicant transitions from `APPLIED` to `WAITLISTED`. Enrollment is only permitted while the waitlist is `OPEN`; enrolling onto a `CLOSED` waitlist is rejected with `ERR_WAITLIST_CLOSED`. An entry's `status` progresses through `PENDING`, `ACTIVE`, `OFFERED`, and terminates in `HOUSED`, `PURGED`, or `WITHDRAWN`. Each entry also tracks a `lottery_number` (null until the draw), the denormalized `total_points` described in §3.2, an `effective_rank`, and a `refusal_count` that starts at 0.

An entry's `effective_rank` is a 1-based position within its waitlist, and it is computed one of two ways depending on whether the draw has happened. Before the draw — while the waitlist's `lottery_drawn` is false — the ranking is preliminary: the pool is the waitlist's `PENDING` entries, ordered solely by their applicant's `application_date` earliest-first, with preference points deliberately ignored because they are not yet locked in. Enrolling a new entry therefore recomputes the preliminary `effective_rank` across the waitlist's `PENDING` entries in `application_date` order. After the draw — when `lottery_drawn` is true — the ranking is final: the pool is the waitlist's `ACTIVE` entries, ordered by `total_points` highest-first and, for equal points, by `lottery_number` lowest-first. Entries in `OFFERED`, `HOUSED`, `PURGED`, or `WITHDRAWN` are never part of either ranking pool.

The lottery draw, run by an `IntakeClerk`, is the pivot between the two regimes. Drawing is only permitted while the waitlist is `OPEN`, and a draw on a `CLOSED` waitlist is rejected with `ERR_WAITLIST_CLOSED`. The draw walks the `PENDING` entries in `application_date` earliest-first order and assigns each a `lottery_number` starting at 1 and increasing by one, moves each such entry from `PENDING` to `ACTIVE`, sets each entry's `total_points` from its applicant's verified claims, refreshes each entry's `last_contact_at`, sets the waitlist's `lottery_drawn` to true, and recomputes the final `effective_rank` across the now-`ACTIVE` pool. The draw responds with the updated `Waitlist` resource.

Over time, active entries can go stale. When an `IntakeClerk` runs the purge on a waitlist, every `ACTIVE` entry whose `last_contact_at` is at least 90 days before the current logical time — that is, the whole-day difference between now and `last_contact_at` is 90 or more — transitions from `ACTIVE` to `PURGED` and is removed from the ranking; the `effective_rank` is then recomputed across the entries that remain `ACTIVE`. The purge responds with the updated `Waitlist` resource. A purged entry is terminal. Separately, whenever an applicant becomes housed on one entry, that applicant's other entries still in `PENDING`, `ACTIVE`, or `OFFERED` are withdrawn (moved to `WITHDRAWN`); and if at any point none of an applicant's entries remain in `PENDING`, `ACTIVE`, `OFFERED`, or `HOUSED` — all are `PURGED` or `WITHDRAWN` — the applicant itself transitions from `WAITLISTED` to `WITHDRAWN`.

### 3.4. The Offer Cycle: Units, Offers, Acceptance, and Refusal

A `PropertyManager` maintains the physical inventory by creating a `Unit` with an `address_label`, a `bedroom_size` (0 to 6 inclusive), and an `income_limit_cents` (a strictly positive annual gross income admission ceiling in whole cents). A unit may optionally declare a `utility_allowance_cents` (a non-negative monthly utility allowance in whole cents, default 0) that later offsets tenant rent. A unit's `status` is `AVAILABLE`, `OFFERED`, or `OCCUPIED`, beginning at `AVAILABLE`, and the unit records a `last_lease_end_date` — the lease-end date of the most recent terminated tenancy on it, null if it has never been occupied — which governs its make-ready turnaround.

Extending an offer is a `HousingSpecialist` action that ties a waitlist entry to a unit: the request carries the `waitlist_entry_id`, the `unit_id`, and an `expires_at` deadline after which the offer can no longer be accepted. A new `Offer` begins in `PENDING` with its `offered_at` stamped from the logical clock; creating it moves the unit from `AVAILABLE` to `OFFERED` and the waitlist entry from `ACTIVE` to `OFFERED`, refreshing that entry's `last_contact_at`. Existence is resolved on the `waitlist_entry_id` (`ERR_WAITLIST_ENTRY_NOT_FOUND`) before the `unit_id` (`ERR_UNIT_NOT_FOUND`). Several guards apply, evaluated in this order after existence and role checks: the waitlist entry must currently be `ACTIVE`, or the offer is rejected with `ERR_INVALID_STATE`; the unit must currently be `AVAILABLE`, or the offer is rejected with `ERR_UNIT_NOT_AVAILABLE`; the unit's `bedroom_size` must equal the bedroom size of the waitlist behind the entry, or the offer is rejected with `ERR_BEDROOM_MISMATCH`; and if the unit carries a `last_lease_end_date`, the current logical time must be on or after 14 days past that date (the make-ready buffer), otherwise the offer is rejected with `ERR_UNIT_TURNOVER_CONFLICT`. An offer's `status` is one of `PENDING`, `ACCEPTED`, or `REFUSED`, with `ACCEPTED` and `REFUSED` terminal.

Acceptance is the household's decision and is reserved to the owning `Applicant`. It is permitted only when the offer is still `PENDING`, and three conditions are checked in order after existence and ownership: the offer must be `PENDING` (else `ERR_INVALID_STATE`), the offered unit must still be in `OFFERED` (else `ERR_UNIT_NOT_AVAILABLE`), and the current logical time must be at or before the offer's `expires_at` (else `ERR_OFFER_EXPIRED`). A successful accept is a single atomic cascade: the offer becomes `ACCEPTED`; a new `Tenancy` is created in `ACTIVE` for the entry's applicant and the offered unit, with `lease_start_date` set from the logical clock; an `INITIAL` `Certification` is created in `DRAFT` for that tenancy with its `effective_date` equal to the lease start; the unit moves from `OFFERED` to `OCCUPIED`; the accepting waitlist entry moves from `OFFERED` to `HOUSED`; the applicant moves from `WAITLISTED` to `HOUSED`; and that applicant's other still-in-play entries are withdrawn as described in §3.3. The accept endpoint returns the newly created `Tenancy` resource (HTTP 201), not the offer.

Refusal is likewise the owning `Applicant`'s decision and is permitted only on a `PENDING` offer. Refusing sets the offer to `REFUSED`, releases the reserved unit from `OFFERED` back to `AVAILABLE`, and resolves the waitlist entry by the refusal-limit rule: the entry's `refusal_count` is incremented by one, and if the incremented count reaches 3 or more the entry is `PURGED` and removed from ranking, otherwise the entry returns to `ACTIVE` (with `last_contact_at` refreshed). In other words the third refusal purges the entry while the second does not. The offer's `expires_at` deadline governs acceptance only; a refusal may be recorded regardless of expiry.

### 3.5. Tenancy Rent: Certifications and the Total Tenant Payment

A `Tenancy` records the housed household — its `applicant_id` and `unit_id` — and carries a `status` of `ACTIVE` or `TERMINATED`, a `lease_start_date`, a `lease_end_date` (null while `ACTIVE`), and two derived rent fields, `monthly_tenant_rent_cents` and `utility_reimbursement_cents`, both 0 until the first certification becomes effective. Rent is set exclusively through certifications. The first (`INITIAL`) certification is created automatically at offer acceptance, but a `HousingSpecialist` also creates further certifications against a tenancy directly, supplying `cert_type`, `effective_date`, the `expected_tenancy_version` for the concurrency check of §2.6, and optionally `childcare_expenses_annual_cents` and `medical_expenses_annual_cents` (each a non-negative whole-cent deduction input, default 0). A directly created certification's `cert_type` is `INITIAL` or `ANNUAL`; the `INTERIM` type is reserved for certifications the system creates while processing an interim change (see §3.7), which set `source_interim_change_id` to the originating change while a directly created certification leaves it null. A new certification begins with `status` `DRAFT` and `hud_status` `NOT_SUBMITTED`, and creating one increments the parent tenancy's `version` by one.

Finalizing a draft certification is what actually computes and locks in rent, and it is a `HousingSpecialist` action. Its guards are evaluated in this order once existence and role pass: the certification must be in `DRAFT` (else `ERR_INVALID_STATE`); the tenancy must be `ACTIVE` (else `ERR_TENANCY_NOT_ACTIVE`); the certification's `effective_date` must be strictly after the `effective_date` of the tenancy's current effective certification, so equal or earlier dates are rejected with `ERR_CERT_PERIOD_OVERLAP`; and, for an `INITIAL` certification only, the household's anticipated annual gross income must not exceed the unit's `income_limit_cents` — an equal figure passes, a strictly greater one is rejected with `ERR_OVER_INCOME`. When finalize succeeds, the system runs the three rent calculations described below, snapshots their results onto the certification's `annual_gross_income_cents`, `annual_adjusted_income_cents`, and `ttp_cents`, moves the certification's `status` from `DRAFT` to `EFFECTIVE`, moves any prior effective certification on the same tenancy from `EFFECTIVE` to `SUPERSEDED`, and recomputes the tenancy's two rent fields.

**Annual gross income.** The household's gross is an exact integer sum over all of the applicant's household members — members carry no status filter and are always counted in full. The variant is keyed on `cert_type`. For the anticipated variant, used by `INITIAL` and `ANNUAL` certifications, each member contributes its `annual_income_cents` plus its `nonrecurring_income_cents`, projecting the full forward year including one-time amounts. For the actual variant, used by `INTERIM` certifications, each member contributes only its `annual_income_cents`, so the non-recurring lines are excluded and the same roster yields a lower gross than the anticipated variant. The result is whole cents and needs no rounding. This figure is snapshotted as the certification's `annual_gross_income_cents`.

**Annual adjusted income.** Starting from that gross, the system subtracts four deductions. The dependent deduction is 48,000 cents (that is, $480) for each household member whose `is_dependent` is true. The elderly-or-disabled deduction is a flat 40,000 cents ($400) granted once if the household contains any member whose `is_elderly` or `is_disabled` is true, and zero otherwise. The childcare deduction is exactly the certification's `childcare_expenses_annual_cents`. The medical deduction applies only to households that qualify as elderly or disabled (any member elderly or disabled) and covers only the portion of medical expenses above a threshold: the threshold is 3% of the gross, and the order of operations is pinned — first compute 3% of the gross and round it half-up to whole cents, then subtract that rounded threshold from the certification's `medical_expenses_annual_cents`, taking the greater of that difference and zero; for a household that is not elderly or disabled, the medical deduction is zero. The adjusted income is the gross minus the sum of the dependent, elderly-or-disabled, childcare, and medical deductions, floored at zero (never negative). It is snapshotted as `annual_adjusted_income_cents`.

**Total Tenant Payment.** The monthly Total Tenant Payment is the greatest of three components. The first component is 30% of the annual adjusted income divided by 12, with that whole expression rounded half-up to whole cents in a single step (the annual figure is divided by 12 inside the rounding step and is never pre-rounded to a monthly amount first). The second component is 10% of the annual gross income divided by 12, again rounded half-up to whole cents in a single step. The third component is a minimum rent floor of 5,000 cents ($50). The Total Tenant Payment is the integer maximum of these three components and is snapshotted as `ttp_cents`.

**Tenant rent and utility reimbursement.** Whenever a certification becomes effective, the tenancy's rent fields are recomputed from the single latest effective certification on that tenancy — selected by `effective_date` most-recent-first, breaking ties by `created_at` most-recent-first — and the unit's `utility_allowance_cents`. Taking that certification's `ttp_cents` and the unit's allowance, the `monthly_tenant_rent_cents` is the Total Tenant Payment minus the utility allowance, floored at zero, and the `utility_reimbursement_cents` is the utility allowance minus the Total Tenant Payment, floored at zero. At most one of the two is positive.

### 3.6. HUD-50058 Submission and Adjudication

Each certification carries an independent HUD reporting axis, `hud_status`, evolving separately from the rent-status axis and taking the values `NOT_SUBMITTED`, `SUBMITTED`, `ACCEPTED`, and `REJECTED`. A `HousingSpecialist` submits a certification's HUD-50058 form, which moves `hud_status` to `SUBMITTED`. Submission is only allowed when the certification's rent `status` is `EFFECTIVE` and its `hud_status` is either `NOT_SUBMITTED` or `REJECTED` (the latter case being a resubmission after correction); attempting it from any other `hud_status` is rejected with `ERR_INVALID_STATE`. Because the axes are independent, submitting or resubmitting the HUD form never changes the rent `status`.

Once submitted, the specialist records HUD's adjudication by supplying a `result` of `ACCEPTED` or `REJECTED`. A `result` of `ACCEPTED` moves a `SUBMITTED` certification's `hud_status` to `ACCEPTED`; a `result` of `REJECTED` moves it to `REJECTED`. Only a certification whose `hud_status` is `SUBMITTED` may receive a result; otherwise `ERR_INVALID_STATE` is returned. A `REJECTED` form may be resubmitted, returning `hud_status` to `SUBMITTED`, provided the rent `status` is still `EFFECTIVE`.

### 3.7. Interim Changes and Recertification

Between annual certifications, a housed household may report a change in circumstances. The owning `Applicant` files an `InterimChange` against its tenancy, supplying a `change_type` — one of `INCOME_DECREASE`, `INCOME_INCREASE`, or `COMPOSITION` — and an `effective_date` on which the resulting recertification should take effect (conventionally the first of the month following the change). The change begins in `REPORTED`, its `reported_at` is stamped from the logical clock, and reporting is only permitted while the tenancy is `ACTIVE` (else `ERR_TENANCY_NOT_ACTIVE`). An interim change's `status` is `REPORTED`, `PROCESSED`, or `DENIED`, with the latter two terminal.

A `HousingSpecialist` adjudicates a reported change by supplying a `decision` of `PROCESS` or `DENY`, and only a change in `REPORTED` may be adjudicated (else `ERR_INVALID_STATE`); processing additionally requires the tenancy to still be `ACTIVE`. A decision to process moves the change to `PROCESSED` and, in the same atomic step, creates an `INTERIM` certification for the tenancy whose `source_interim_change_id` points back to this change and whose `effective_date` is the change's `effective_date`, then finalizes that interim certification to `EFFECTIVE` on the actual-income variant (recurring income only), supersedes the prior effective certification, and recomputes the tenancy's rent fields. This system-created `INTERIM` certification takes no deduction inputs from the request, so its `childcare_expenses_annual_cents` and `medical_expenses_annual_cents` are both 0. A decision to deny moves the change to `DENIED` and creates no certification, leaving rent untouched. Either decision returns the adjudicated `InterimChange` resource, never the certification it may create.

### 3.8. Grievances and Eviction

The grievance channel handles both tenant-initiated disputes and authority-initiated evictions against a tenancy, and the two directions share one resource distinguished by `grievance_type`: `GRIEVANCE` for a tenant filing and `EVICTION` for an authority filing. A grievance is filed with a `grievance_type` and a free-text `reason` (required but permitted to be an empty string); a tenant grievance may be filed by the owning `Applicant`, while an eviction is filed by a `PropertyManager`. The `grievance_type` is not cross-checked against the caller's role — the endpoint authorizes both the `Applicant` and `PropertyManager` roles and accepts either `grievance_type` from either, with only the `Applicant`'s ownership of the tenancy enforced. A new `Grievance` begins in `FILED`, its `filed_at` is stamped from the logical clock, and filing is permitted only while the tenancy is `ACTIVE` (else `ERR_TENANCY_NOT_ACTIVE`). Its `status` is `FILED`, `SUSTAINED`, or `OVERRULED`, the latter two terminal.

A `PropertyManager` decides a filed grievance by supplying an `outcome`, and only a grievance in `FILED` may be decided (else `ERR_INVALID_STATE`). A `SUSTAINED` outcome upholds the tenant's position and never terminates the tenancy, regardless of `grievance_type`. An `OVERRULED` outcome depends on the type: overruling an `EVICTION` terminates the tenancy — the tenancy moves from `ACTIVE` to `TERMINATED`, its `lease_end_date` is set from the logical clock, and this cascades to the unit, which moves from `OCCUPIED` back to `AVAILABLE` and records the freed lease's end date into its `last_lease_end_date` (which in turn arms the make-ready buffer for that unit's next offer). Overruling a `GRIEVANCE`, by contrast, leaves the tenancy unchanged.

Read access across all of these resources is uniform: any of the four roles may list or fetch applicants, members, preference claims, waitlists and their entries, an applicant's waitlist entries, units (optionally filtered by `status` or `bedroom_size`), offers (optionally filtered by `waitlist_entry_id` or `unit_id`), tenancies (optionally filtered by `applicant_id` or `unit_id`), certifications (optionally filtered by `tenancy_id` or `source_interim_change_id`), interim changes, and grievances.

## 4. Endpoint Definitions

Operations that create a new, distinct resource return `201 Created`; operations that modify an existing resource, drive a state transition, or run a batch action over existing resources return `200 OK`. Request and response bodies are not repeated here — the fields each operation consumes and the side effects it produces are described in the §3 workflows, and every resource is returned inside the standard envelope of §2.2.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/pha/applicants` | Register a new applicant household | IntakeClerk |
| GET | `/pha/applicants/{id}` | Fetch one applicant | IntakeClerk, HousingSpecialist, PropertyManager, Applicant |
| POST | `/pha/applicants/{id}/members` | Add a household member | IntakeClerk |
| GET | `/pha/applicants/{id}/members` | List an applicant's household members | IntakeClerk, HousingSpecialist, PropertyManager, Applicant |
| POST | `/pha/applicants/{id}/preference-claims` | Claim an admission preference | IntakeClerk, Applicant |
| GET | `/pha/applicants/{id}/preference-claims` | List an applicant's preference claims | IntakeClerk, HousingSpecialist, PropertyManager, Applicant |
| POST | `/pha/preference-claims/{id}/verify` | Verify or deny a preference claim | IntakeClerk |
| POST | `/pha/preference-claims/{id}/revoke` | Revert a verified claim and remove its points | IntakeClerk |
| GET | `/pha/applicants/{id}/waitlist-entries` | List an applicant's waitlist entries | IntakeClerk, HousingSpecialist, PropertyManager, Applicant |
| POST | `/pha/waitlists` | Create a waitlist for a site and bedroom size | IntakeClerk |
| GET | `/pha/waitlists/{id}` | Fetch one waitlist | IntakeClerk, HousingSpecialist, PropertyManager, Applicant |
| POST | `/pha/waitlists/{id}/entries` | Enroll an applicant onto a waitlist | IntakeClerk |
| GET | `/pha/waitlists/{id}/entries` | List entries on a waitlist | IntakeClerk, HousingSpecialist, PropertyManager, Applicant |
| POST | `/pha/waitlists/{id}/lottery-draw` | Run the lottery draw | IntakeClerk |
| POST | `/pha/waitlists/{id}/purge` | Purge stale active entries | IntakeClerk |
| POST | `/pha/units` | Create a housing unit | PropertyManager |
| GET | `/pha/units/{id}` | Fetch one unit | IntakeClerk, HousingSpecialist, PropertyManager, Applicant |
| GET | `/pha/units` | List units, optionally filtered by status or bedroom size | IntakeClerk, HousingSpecialist, PropertyManager, Applicant |
| POST | `/pha/offers` | Offer a unit to a waitlist entry | HousingSpecialist |
| GET | `/pha/offers/{id}` | Fetch one offer | IntakeClerk, HousingSpecialist, PropertyManager, Applicant |
| GET | `/pha/offers` | List offers, optionally filtered by waitlist entry or unit | IntakeClerk, HousingSpecialist, PropertyManager, Applicant |
| POST | `/pha/offers/{id}/accept` | Accept an offer; create tenancy and initial certification | Applicant |
| POST | `/pha/offers/{id}/refuse` | Refuse an offer; release the unit and increment refusals | Applicant |
| GET | `/pha/tenancies/{id}` | Fetch one tenancy | IntakeClerk, HousingSpecialist, PropertyManager, Applicant |
| GET | `/pha/tenancies` | List tenancies, optionally filtered by applicant or unit | IntakeClerk, HousingSpecialist, PropertyManager, Applicant |
| POST | `/pha/tenancies/{id}/certifications` | Create an INITIAL or ANNUAL certification (requires OCC version) | HousingSpecialist |
| GET | `/pha/certifications/{id}` | Fetch one certification | IntakeClerk, HousingSpecialist, PropertyManager, Applicant |
| GET | `/pha/certifications` | List certifications, optionally filtered by tenancy or source interim change | IntakeClerk, HousingSpecialist, PropertyManager, Applicant |
| POST | `/pha/certifications/{id}/finalize` | Finalize a draft certification and recompute rent | HousingSpecialist |
| POST | `/pha/certifications/{id}/hud-submit` | Submit or resubmit the HUD-50058 form | HousingSpecialist |
| POST | `/pha/certifications/{id}/hud-result` | Record the HUD-50058 adjudication result | HousingSpecialist |
| POST | `/pha/tenancies/{id}/interim-changes` | Report an interim change | Applicant |
| GET | `/pha/tenancies/{id}/interim-changes` | List interim changes on a tenancy | IntakeClerk, HousingSpecialist, PropertyManager, Applicant |
| POST | `/pha/interim-changes/{id}/process` | Process or deny a reported interim change | HousingSpecialist |
| POST | `/pha/tenancies/{id}/grievances` | File a grievance or eviction against a tenancy | Applicant, PropertyManager |
| GET | `/pha/tenancies/{id}/grievances` | List grievances on a tenancy | IntakeClerk, HousingSpecialist, PropertyManager, Applicant |
| POST | `/pha/grievances/{id}/decide` | Decide a grievance or eviction | PropertyManager |
| POST | `/pha/_clock/set_current_utc` | Set the server logical clock | IntakeClerk, HousingSpecialist, PropertyManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 422 |
| `ERR_APPLICANT_NOT_FOUND` | 404 |
| `ERR_PREFERENCE_CLAIM_NOT_FOUND` | 404 |
| `ERR_WAITLIST_NOT_FOUND` | 404 |
| `ERR_WAITLIST_ENTRY_NOT_FOUND` | 404 |
| `ERR_UNIT_NOT_FOUND` | 404 |
| `ERR_OFFER_NOT_FOUND` | 404 |
| `ERR_TENANCY_NOT_FOUND` | 404 |
| `ERR_CERTIFICATION_NOT_FOUND` | 404 |
| `ERR_INTERIM_CHANGE_NOT_FOUND` | 404 |
| `ERR_GRIEVANCE_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_UNIT_NOT_AVAILABLE` | 409 |
| `ERR_TENANCY_NOT_ACTIVE` | 409 |
| `ERR_WAITLIST_CLOSED` | 409 |
| `ERR_BEDROOM_MISMATCH` | 422 |
| `ERR_OFFER_EXPIRED` | 409 |
| `ERR_UNIT_TURNOVER_CONFLICT` | 409 |
| `ERR_CERT_PERIOD_OVERLAP` | 409 |
| `ERR_OVER_INCOME` | 422 |
