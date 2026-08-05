# Off-Campus Student-Housing Marketplace API — Product Requirements Document

## 1. Introduction

Off-campus housing is a market with a peculiar rhythm. Demand spikes on the academic calendar, leases are signed by the bed rather than by the apartment, and a single four-bedroom unit routinely holds four strangers who must first agree to live together. This platform exists to make that rhythm legible to software: it lets landlords list buildings and floor-plans, lets students form roommate groups and match on lifestyle compatibility, underwrites guarantors for thin-credit applicants, prices academic-year and partial terms on two independent bases, and settles collected rent back to property owners under a maintenance holdback and a segregation-of-duties control.

The system is built around a handful of hard realities. A bed slot can only be occupied by one lease at a time, and a mandatory vacancy gap separates one tenant's move-out from the next tenant's move-in. Money is tracked in integer cents from the first installment to the final wire, and every derived total must reconcile to the cent. Time is modelled by an explicit logical clock rather than wall-clock time, so tests can drive leases through lateness, activation, and expiry deterministically. Because several actors — platform operators, landlords, campus housing offices, and students themselves — touch the same resources, every write is gated by role and by ownership.

This document specifies the complete REST contract: the global envelope and pagination rules, the role model, the state machines that govern each entity's lifecycle, the calculation rules that produce every derived money and score field, the validation order that decides which error a bad request receives, and the full endpoint and error catalogues. The scaffolded seed tables are the source of truth; this prose is their faithful projection.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the caller's role. Exactly four roles exist, spelled precisely as follows: `PlatformAdmin`, `PropertyManager`, `UniversityPartner`, and `Student`. If either header is absent, or if `X-User-Role` is not one of these four names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well-formed but the named role is not permitted to reach the target endpoint, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403). When the role is permitted in principle but the acting `X-User-ID` does not own the resource in scope, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

The four roles map to identity in two different ways. When `X-User-Role` is `Student`, `X-User-ID` is the `id` of the acting `Student`; ownership checks on any resource that references a student compare that resource's student foreign key to `X-User-ID`. A student may form roommate groups, apply for beds, submit guarantors, sign, pay, sublet, and reserve amenities, but always only on resources that resolve to their own `id`: a lease they hold, a membership whose `student_id` is theirs, or a group whose `lead_student_id` is theirs.

The other three roles carry opaque identifiers. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it where a transition writes it — for example as `submitted_by_user_id` or `approved_by_user_id` on a `Payout` — but never compares it to any entity's `id`. When `X-User-Role` is `PropertyManager`, `X-User-ID` is likewise opaque, but it is captured as `manager_user_id` on the `Property` at creation and thereafter every `PropertyManager` mutation on that property — and on its units, amenities, leases, guarantor applications and sublets — requires `X-User-ID` to equal that stored `manager_user_id`. When `X-User-Role` is `UniversityPartner`, `X-User-ID` is an opaque identifier recorded as `partner_admin_user_id` on the `University`; a partner may decide an enrollment verification only for students whose university names their `X-User-ID` as its `partner_admin_user_id`.

`PlatformAdmin` owns marketplace operations and finance: onboarding universities and students, suspending and reinstating properties, driving the logical clock, and running the payout pipeline. `PropertyManager` is the landlord-side operator who owns buildings, units and amenities, underwrites guarantors, places roommate groups, approves sublets, and terminates leases. `UniversityPartner` is campus housing-office staff whose sole write capability is deciding enrollment verifications. `Student` is the renter. All four roles may read the shared catalogue of GET endpoints; the payout read endpoints are visible only to `PlatformAdmin` and `PropertyManager`.

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

Every list endpoint accepts two optional query parameters, `limit` and `offset`. `limit` defaults to 10, may be no smaller than 1 and no larger than 100; `offset` defaults to 0 and may be no smaller than 0. A `limit` outside 1–100 or a negative `offset` is a schema violation rejected with `ERR_VALIDATION` (HTTP 400). List results are ordered by `created_at` ascending unless a specific endpoint states another key — the membership list orders by `sequence_number` ascending when filtered to a single `group_id`, and the lease-installments sub-resource orders by `sequence_number` ascending. Each list response reports `limit`, `offset`, `total_count` (the number of matching rows before the page window) and `has_more` (true when rows remain beyond the current window) inside `meta`.

### 2.4. Common Resource Properties and Versioning

Every entity in this system carries a common envelope of system fields. `id` is a server-minted UUID with no type prefix; clients never supply it. `created_at` is the ISO 8601 UTC instant of creation with three fractional digits. `updated_at` is the ISO 8601 UTC instant of the most recent mutation, and `version` is an integer that begins at 1 on creation and increments by exactly 1 on every mutation of the row. All thirteen entities — `University`, `Property`, `Unit`, `Student`, `RoommateGroup`, `GroupMembership`, `Lease`, `GuarantorApplication`, `Installment`, `Sublet`, `Amenity`, `AmenityAssignment`, and `Payout` — carry `updated_at` and `version`; none is version-free.

A subtlety worth stressing: `version` on `Property` and `Unit` advances on **every** mutation, including cascaded recomputation of derived fields such as bed rollups, escrow, and posture. A caller that needs a fresh optimistic-concurrency token must read it immediately before the guarded write, because an intervening reservation, payment, or auto-posture change will already have moved it.

All timestamps written into system datetime fields — `signed_at`, `terminated_at`, `paid_at`, `decided_at`, `released_at`, `reversed_at`, `verification_submitted_at`, `verification_expires_at`, `verification_decided_at` — are the value of the logical clock at the moment of the write, not wall-clock time. These fields, and the `current_utc` the clock endpoint reports, are rendered as ISO 8601 UTC instants with three fractional digits, exactly like `created_at` and `updated_at`.

### 2.5. The Logical Clock and the Operations Checkpoint

The server keeps a single logical UTC clock. Before the first time it is set, the clock reads exactly `2026-05-01T00:00:00Z`; the server never falls back to real wall-clock time. Only a `PlatformAdmin` may advance the clock, by supplying a `to_iso8601` instant. The new instant must be at or after the current one; a request to move the clock backwards is rejected with `ERR_CLOCK_BACKWARDS` (HTTP 422).

Setting the clock runs an operations checkpoint in a strictly pinned three-step order. **Step one is the lateness sweep:** every `Installment` still in `SCHEDULED` status whose owning lease is in `PENDING_SIGNATURE`, `ACTIVE`, or `TERMINATED`, and whose due date plus the five-day grace window falls strictly before the new clock date, is moved to `LATE`, and each affected lease's `funding_status` is recomputed to `DELINQUENT`. **Step two is the sublet sweep:** every `Sublet` in `APPROVED` whose `start_date` is at or before the new clock date becomes `ACTIVE`, and every `Sublet` in `ACTIVE` whose `end_date` is at or before the new clock date becomes `COMPLETED`. **Step three is the lease auto-end sweep:** every `Lease` in `ACTIVE` whose `term_end_date` is at or before the new clock date becomes `ENDED`, releasing its bed slot and re-running the unit and property rollups. The response reports the resulting `current_utc` along with `installments_marked_late_count`, `sublets_activated_count`, `sublets_completed_count`, and `leases_ended_count`.

### 2.6. Money, Scores, Precision and Rounding

All monetary quantities are integer cents; all match scores are integer points. Wherever a rule divides or applies a basis-point rate, the result is rounded once with **round half up** — ties are resolved away from zero — and no intermediate rounding is chained. Basis points are hundredths of a percent divided again by one hundred, so a rate expressed in basis points is applied by multiplying the base by the basis-point figure and dividing by 10000. Two rules use `floor` (truncation toward negative infinity) rather than round-half-up, and they are called out explicitly where they apply: the guarantor income-multiple computation and the per-installment base-share allocation. Whole-day date arithmetic treats a half-open interval `[start, end)` as `end` minus `start` days, and a closed interval `[start, end]` as `end` minus `start` plus one day.

### 2.7. Optimistic Concurrency Control

Two write endpoints are guarded by optimistic concurrency on a parent entity's `version`, and only those two. Placing a locked roommate group into a unit requires `expected_unit_version` in the request body, carrying the client's last observed `version` of the target `Unit`; if that value does not match the unit's current `version`, the placement is rejected with `ERR_STALE_VERSION` (HTTP 412). Creating a payout requires `expected_property_version`, carrying the client's last observed `version` of the target `Property`; if it does not match the property's current `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412). Both guards exist because the parent row legitimately hosts several successful writes — a four-bed unit can host two two-person groups, and disjoint settlement windows produce several payouts on one property — so a request carrying an up-to-date token succeeds even after an earlier write consumed part of the parent; only a stale token is refused. No other endpoint takes a version field.

### 2.8. Bed Rollups, Property Posture, and Cascading Consistency

Occupancy is tracked at three levels that must always agree. A `Unit` holds `leased_bed_count` — the number of leases on that unit whose `lease_status` is `PENDING_GUARANTOR`, `PENDING_SIGNATURE`, or `ACTIVE` — and `available_bed_count`, which is the length of the unit's `bed_labels` array minus `leased_bed_count`. The partition holds as a conserved invariant: the number of bed labels always equals `leased_bed_count` plus `available_bed_count`. The unit's `occupancy_status` is `FULLY_LEASED` when `available_bed_count` is 0, `AVAILABLE` when `leased_bed_count` is 0, and `PARTIALLY_LEASED` otherwise. `DRAFT`, `ENDED`, `CANCELLED`, and `TERMINATED` leases never consume a bed.

A `Property` rolls these up: `unit_count` is the number of its units, `total_bed_count` is the sum over its units of the bed-label count, and `available_bed_count` is the sum over its units of unit `available_bed_count`. Whenever any unit rollup changes, the property `available_bed_count` is recomputed and the property posture is re-evaluated. A `LISTED` property whose `available_bed_count` reaches 0 auto-transitions to `FULLY_COMMITTED`; a `FULLY_COMMITTED` property whose `available_bed_count` rises above 0 auto-transitions back to `LISTED`. This auto-posture is applied inside the same request that changed the bed rollup, and each such change increments the property's `version`.

Because a single write can ripple across several rows, the system applies cascades depth-first within one request: a lease reservation recomputes the unit rollup, which recomputes the property rollup, which may fire the property posture auto-transition — and a group placement extends this same chain across every minted lease. Every touched row's `updated_at` and `version` advance.

### 2.9. Validation Order and Error Precedence

When more than one rule could reject a request, the rules are evaluated in a fixed ascending priority and the first failure determines the response; no later rule is consulted. The order is: (1) authentication — both headers present and the role recognised, else `ERR_UNAUTHENTICATED`; (2) authorization — the role appears in the endpoint's permitted list, else `ERR_UNAUTHORIZED`; (3) path existence — every resource named by a path segment exists, validated left to right, else the matching not-found error; (4) body foreign-key existence — every entity referenced by a foreign key in the request body exists, else the matching not-found error; (5) ownership — the acting `X-User-ID` owns the resource in scope, else `ERR_NOT_RESOURCE_OWNER`; (6) request schema — required fields present, types correct, enum members legal, integers in range, dates well-formed and correctly ordered, else `ERR_VALIDATION`; (7) optimistic concurrency — the supplied version token matches, else `ERR_STALE_VERSION`; (8) state admissibility — the target resource is in a state from which the requested transition is declared, else the matching invalid-state error; (9) property posture — the property in scope is `LISTED` or `FULLY_COMMITTED`, else `ERR_PROPERTY_NOT_ACTIVE`; (10) host-lease posture — the host lease is `ACTIVE`, else `ERR_LEASE_NOT_ACTIVE`; (11) student verification, else `ERR_STUDENT_NOT_VERIFIED`; and thereafter the domain-specific business rules described in §3, in the order laid out there. The per-rule numeric ranges enforced at priority six are: `bedroom_count` 1–8, `cleanliness_level` and `noise_tolerance` 1–5, `required_size` 2–8, `installment_count` 1–12, `capacity` at least 1, `distance_to_campus_m` at least 0, `base_rent_cents_per_bed_monthly` greater than 0, `sublet_rent_cents` greater than 0, `monthly_fee_cents` at least 0, `period_end_date` at or after `period_start_date`, `academic_year_end_date` strictly after `academic_year_start_date`, `term_end_date` strictly after `term_start_date`, `bed_labels` non-empty with distinct entries, `limit` within 1–100, and `offset` at least 0.

### 2.10. Nested Resource Retrieval

Where a path names more than one resource — the single sub-resource route that lists a lease's installments — the segments are validated left to right, so a missing lease yields `ERR_LEASE_NOT_FOUND` before any installment filter is applied. All other collections are top-level; foreign keys are supplied in request bodies and query filters rather than in nested paths.

Each entity type has its own not-found error, returned (HTTP 404) both when a path segment names a missing row and when a foreign key in a request body references one that does not exist: a missing university is `ERR_UNIVERSITY_NOT_FOUND`, a missing property `ERR_PROPERTY_NOT_FOUND`, a missing unit `ERR_UNIT_NOT_FOUND`, a missing student `ERR_STUDENT_NOT_FOUND`, a missing roommate group `ERR_GROUP_NOT_FOUND`, a missing membership `ERR_MEMBERSHIP_NOT_FOUND`, a missing lease `ERR_LEASE_NOT_FOUND`, a missing guarantor application `ERR_GUARANTOR_APPLICATION_NOT_FOUND`, a missing installment `ERR_INSTALLMENT_NOT_FOUND`, a missing sublet `ERR_SUBLET_NOT_FOUND`, a missing amenity `ERR_AMENITY_NOT_FOUND`, a missing amenity assignment `ERR_AMENITY_ASSIGNMENT_NOT_FOUND`, and a missing payout `ERR_PAYOUT_NOT_FOUND`.

## 3. Business Logic & Workflows

### 3.1. Universities and Enrollment Verification

The marketplace begins with institutions. A `PlatformAdmin` registers a `University` by supplying its display `name`, a short institution `code` of 2–8 uppercase alphanumeric characters that must be unique across all universities, and a covered academic year given as `academic_year_start_date` and `academic_year_end_date` (ISO calendar dates, the end strictly after the start). A second `PlatformAdmin` attempting to reuse a `code` is refused with `ERR_UNIVERSITY_CODE_TAKEN`. The institution's `partner_tier` is optional and defaults to `STANDARD`; the only other legal value is `PREFERRED`. From the tier the system computes `partner_discount_bps`: 500 basis points when the tier is `PREFERRED`, and 0 when it is `STANDARD`, recomputed whenever the tier is set. The registrant also names the `partner_admin_user_id` — the opaque operator authorised to decide this university's verifications — and sets `verification_required`, which defaults to true and, when true, forces every student of the university to reach a `VERIFIED` posture before any of their leases may leave `DRAFT`. A newly created university reports `verified_student_count` of 0; that counter tracks students of this university whose `verification_status` is `VERIFIED`.

Students self-attest enrollment and let the campus office confirm it. A `Student` is registered by a `PlatformAdmin` with a `university_id`, a `full_name`, and an `email` unique across all students (a collision is `ERR_EMAIL_TAKEN`), plus the four lifestyle attributes described in §3.3. The optional `credit_score_band` defaults to `FAIR` and is one of `THIN`, `LOW`, `FAIR`, `GOOD`, `EXCELLENT`; the optional `smoker` flag defaults to false. Every student is born `UNVERIFIED`, with `verification_submitted_at`, `verification_expires_at`, and `verification_decided_at` all null.

The verification state machine is branching with a revert. From `UNVERIFIED` — or from `REJECTED`, which is the revert loop that lets a rejected student try again any number of times — a student may request verification on their own behalf, moving to `PENDING`. That request stamps `verification_submitted_at` to the current clock and sets `verification_expires_at` to fourteen (14) days later; it leaves any prior `verification_decided_at` unchanged, so a student re-requesting after a `REJECTED` decision keeps that decision's timestamp until a subsequent decision overwrites it. Only the owning student may make the request; requesting from `PENDING` or `VERIFIED` is refused with `ERR_STUDENT_INVALID_STATE`. A `UniversityPartner` whose `X-User-ID` matches the student's university `partner_admin_user_id` then decides the pending request with a `decision` of `APPROVE` or `REJECT` and an optional `note`. `APPROVE` moves a `PENDING` student to `VERIFIED`, stamps `verification_decided_at`, and increments the university's `verified_student_count` by 1; `REJECT` moves them to `REJECTED` and stamps `verification_decided_at`. A decision on a student who is not `PENDING` is `ERR_STUDENT_INVALID_STATE`. Crucially, the decision must be issued while the current clock is at or before `verification_expires_at`; a decision after that instant is refused with `ERR_VERIFICATION_EXPIRED`.

### 3.2. Buildings, Units, and Listing Posture

A `PropertyManager` creates a `Property` against a `university_id`, giving the building's `name`, `address_line`, and `distance_to_campus_m` (walking metres from campus centre, at least 0). The creating manager's `X-User-ID` is recorded as `manager_user_id`, the posture is `DRAFT`, and all rollup counters — `unit_count`, `total_bed_count`, `available_bed_count`, `escrow_balance_cents`, `maintenance_reserve_cents` — start at 0 with `payout_eligible` false.

Units are the floor-plan instances that actually hold beds. Adding a `Unit` supplies its `property_id`, a `unit_number` unique within the owning property (a duplicate is `ERR_DUPLICATE_UNIT_NUMBER`), a `floorplan_code` such as `4x2`, a `bedroom_count` between 1 and 8, a `bathroom_count` of at least 1, an ordered `bed_labels` array of distinct slot labels, and a `base_rent_cents_per_bed_monthly` greater than 0. The length of `bed_labels` must equal `bedroom_count`, or the request is `ERR_BED_LABELS_MISMATCH`. A fresh unit reports `leased_bed_count` 0, `available_bed_count` equal to the number of bed labels, and `occupancy_status` `AVAILABLE`; creating it recomputes the parent property's rollups and bumps the property `version`.

Publishing is a posture change. A `PropertyManager` lists a `DRAFT` property, advancing it `DRAFT → LISTED`, provided it has at least one unit — a property with `unit_count` of 0 is refused with `ERR_PROPERTY_HAS_NO_UNITS` — and provided the acting `X-User-ID` owns it; listing recomputes the bed rollups and bumps `version`. Listing a property that is not `DRAFT` is `ERR_PROPERTY_INVALID_STATE`. A `PlatformAdmin` may suspend a `LISTED` or `FULLY_COMMITTED` property with an optional `reason`, driving it to `SUSPENDED` and blocking new leasing, signing, placement, subletting, and payout approval; suspending a `DRAFT` or already-`SUSPENDED` property is `ERR_PROPERTY_INVALID_STATE`. Reinstating a `SUSPENDED` property returns it to `LISTED` when it has available beds, or to `FULLY_COMMITTED` when `available_bed_count` is 0; reinstating a property that is not `SUSPENDED` is `ERR_PROPERTY_INVALID_STATE`.

### 3.3. Roommate Matching, Groups, and Placement

Every student carries four lifestyle attributes that feed compatibility scoring: `cleanliness_level` and `noise_tolerance`, each a self-reported 1–5 integer; `sleep_schedule`, a chronotype that is either `EARLY` or `LATE`; and the boolean `smoker`. The pair-compatibility kernel between two students starts at a perfect 100 and subtracts penalties: 12 points for each point of difference in `cleanliness_level`, 8 points for each point of difference in `noise_tolerance`, a flat 25 points when the two students' `sleep_schedule` values differ, and a flat 30 points when their `smoker` flags differ. The result is clamped to lie between 0 and 100. All arithmetic in the kernel is exact integers.

A `Student` opens a `RoommateGroup` for a `property_id`, giving the group a `name` and a `required_size` between 2 and 8 — the exact number of accepted members it must hold before it can lock. The creator becomes the `lead_student_id`, taken from `X-User-ID`, and is auto-enrolled as an `ACCEPTED` `GroupMembership` with `sequence_number` 1 and `match_score` 100; the group is born `FORMING` with `accepted_member_count` 1. The lead — and only the lead — invites another student by `student_id`. Each invitation mints a `GroupMembership` in `INVITED` status whose `sequence_number` is one greater than the current maximum in the group, and stamps its `match_score` as the lead-anchored pair score between the invitee and the lead. Inviting a student who already holds an `INVITED`, `ACCEPTED`, or `PLACED` membership on the group is refused with `ERR_DUPLICATE_MEMBERSHIP`; inviting into a group that is not `FORMING` is `ERR_GROUP_INVALID_STATE`.

An invited student responds on their own membership with a `decision` of `ACCEPT` or `DECLINE`, moving it `INVITED → ACCEPTED` or `INVITED → DECLINED` and recomputing the group's `accepted_member_count` (which counts memberships in `ACCEPTED` or `PLACED`). Responding while the group is not `FORMING`, or on a membership no longer `INVITED`, is refused — the latter with `ERR_MEMBERSHIP_INVALID_STATE`. A student may hold at most one non-`DECLINED` membership per group.

Locking freezes the roster. The lead locks a `FORMING` group, which requires that `accepted_member_count` equals `required_size` (otherwise `ERR_GROUP_SIZE_MISMATCH`) and that the group is compatible enough. At lock the system stamps two scores over the accepted member set — which always includes the lead. The `average_match_score` is the pairwise-mean reading: take every unordered pair of distinct accepted members, score each pair with the kernel, sum, divide by the number of pairs (which is the member count times one less than the member count, divided by two), and round half up. The `lead_anchored_mean_score` is the lead-anchored reading: score each accepted member against the lead only, sum those, divide by the member count, and round half up. These two readings of the same member set diverge, because the pairwise mean sees friction between two non-lead roommates that the lead-anchored mean cannot. The lock gate is on the pairwise mean: `average_match_score` must be at least 55, or the lock is refused with `ERR_GROUP_MATCH_SCORE_TOO_LOW`. Both `average_match_score` and `lead_anchored_mean_score` are null until the group is locked. A successful lock moves the group `FORMING → LOCKED`; locking a group that is not `FORMING` is `ERR_GROUP_INVALID_STATE`.

Placement is where a locked group becomes a set of by-bed leases. A `PropertyManager` who owns the property places a `LOCKED` group into a `unit_id`, and this write is guarded by optimistic concurrency: the request must carry `expected_unit_version` matching the unit's current `version`, else `ERR_STALE_VERSION` (HTTP 412), because an intervening reservation on the same unit will have advanced that token. The request also carries the shared lease-term fields `term_start_date`, `term_end_date`, and `installment_count`. Placement requires that the unit's `property_id` equals the group's `property_id` (else `ERR_UNIT_PROPERTY_MISMATCH`), that the property is `LISTED` or `FULLY_COMMITTED` (else `ERR_PROPERTY_NOT_ACTIVE`), that the unit's `available_bed_count` is at least the group's `required_size` (else `ERR_UNIT_CAPACITY_INSUFFICIENT`), that every placed member's verification passes when their university demands it (else `ERR_STUDENT_NOT_VERIFIED`), that the term length is legal and not in the past, and that no allocated bed slot has a turnover conflict. A successful placement cascades: the group moves `LOCKED → PLACED` and records `placed_unit_id`; then each `ACCEPTED` membership — walked in ascending `sequence_number` order and zipped against the unit's vacant bed labels in lexicographic ascending order — becomes `PLACED` and mints a `Lease` in `DRAFT` that is immediately driven into its bed-holding state — `PENDING_GUARANTOR` when that minted lease's `guarantor_required` is true, otherwise `PENDING_SIGNATURE`, routed exactly as a solo submission routes by its own `guarantor_required` flag; then, because each new lease holds a bed, the unit's `leased_bed_count`, `available_bed_count`, and `occupancy_status` are recomputed; then the property's `available_bed_count` is recomputed; then, if it reached 0, the property auto-transitions `LISTED → FULLY_COMMITTED`. Placement increments the unit `version` by 1. Each minted lease records its `roommate_group_id`. Placing a group that is not `LOCKED` is `ERR_GROUP_INVALID_STATE`.

### 3.4. Leasing: Application, Pricing, and the Guarantor Gate

A `Student` applies for a single bed by creating a `Lease` with a `student_id`, a `unit_id`, a `bed_label`, the occupancy dates `term_start_date` and `term_end_date`, and an `installment_count` between 1 and 12. The `bed_label` must be a member of the target unit's `bed_labels` array, or the application is refused with `ERR_BED_LABEL_UNKNOWN`. The lease's `property_id` is denormalised from the unit, and `monthly_rent_cents` is snapshotted from the unit's `base_rent_cents_per_bed_monthly` — any client-supplied rent is ignored. `term_days` is the number of whole days from `term_start_date` to `term_end_date`, treating the occupancy interval as half-open, and must lie between 90 and 400 inclusive, or the request is `ERR_TERM_LENGTH_INVALID`; the start may not be earlier than the current clock date, or it is `ERR_TERM_START_IN_PAST`. Creation must not collide with an existing bed-holding lease on the same slot (see the turnover rule in §3.10), or it is `ERR_BED_TURNOVER_CONFLICT`.

At creation the lease is stamped with the **quoted** total. The quoted reading bills the term as whole months: divide `term_days` by 30 and round up to the next whole month, then multiply by the list `monthly_rent_cents`. No university partner discount is ever applied to the quoted figure. This value lands in `quoted_total_cents`. The lease is born with `lease_status` `DRAFT` and `funding_status` `UNFUNDED`, and no bed is reserved yet. Creation also stamps `guarantor_required`: it is true when the leaseholder's `credit_score_band` is `THIN` or `LOW`, or when the snapshotted `monthly_rent_cents` is strictly greater than 120000 cents — a bed renting for exactly 120000 does not on its own demand a guarantor.

Submitting a `DRAFT` lease reserves the bed. The owning student submits, and the lease routes by its `guarantor_required` flag: to `PENDING_GUARANTOR` when a guarantor is required, or straight to `PENDING_SIGNATURE` when it is not. Submission requires that the property is `LISTED` or `FULLY_COMMITTED` (else `ERR_PROPERTY_NOT_ACTIVE`), that the student is `VERIFIED` whenever their university's `verification_required` is true (else `ERR_STUDENT_NOT_VERIFIED`), and that the bed slot has no turnover conflict. It reserves the slot — recomputing the unit rollups, bumping the unit `version`, recomputing the property `available_bed_count`, and re-evaluating the property posture. Submitting a lease that is not `DRAFT` is `ERR_LEASE_INVALID_STATE`.

Signing turns a `PENDING_SIGNATURE` lease `ACTIVE` and locks in the money. Only the owning student signs, and only while the property is `LISTED` or `FULLY_COMMITTED`. Signing computes the **contracted** total on a daily-proration basis, which diverges deliberately from the quoted figure. First the system fixes `term_type`: it is `ACADEMIC_YEAR` when the lease's `term_start_date` is at or before the student's university `academic_year_start_date` **and** its `term_end_date` is at or after that university's `academic_year_end_date`, and `PARTIAL_TERM` otherwise. It converts monthly rent to a daily rate by multiplying `monthly_rent_cents` by 12, dividing by 365, and rounding half up — this is `daily_rate_cents`. The gross is `daily_rate_cents` times the exact `term_days`. The `partner_discount_bps` is the university's `partner_discount_bps` when `term_type` is `ACADEMIC_YEAR`, and 0 otherwise; `partner_discount_cents` is the gross times that basis-point figure, divided by 10000 and rounded half up. `total_contract_cents` is the gross minus the discount. Signing stamps `term_type`, `daily_rate_cents`, `partner_discount_bps`, `partner_discount_cents`, and `total_contract_cents`, sets `signed_at` to the clock, mints the installment schedule described in §3.6, and recomputes `billed_total_cents` and `funding_status`. Signing a lease that is not `PENDING_SIGNATURE` is `ERR_LEASE_INVALID_STATE`.

A student may cancel a lease that has not yet been signed — one in `DRAFT`, `PENDING_GUARANTOR`, or `PENDING_SIGNATURE` — with an optional `reason`, moving it to `CANCELLED` and stamping `terminated_at`. If the cancelled lease held a bed, the slot is released and the unit and property rollups and posture are re-evaluated; any guarantor application on the lease still in `SUBMITTED`, `UNDER_REVIEW`, or `INFO_REQUESTED` is moved to `DECLINED`. Cancelling a signed or terminal lease is `ERR_LEASE_INVALID_STATE`.

### 3.5. Guarantor Underwriting

When a lease needs a cosigner, the student submits a `GuarantorApplication` naming the `lease_id`, the `guarantor_full_name`, the guarantor's declared `guarantor_annual_income_cents` (at least 0), and the `relationship`, one of `PARENT`, `GUARDIAN`, `RELATIVE`, `EMPLOYER`, or `OTHER`. The application may only be filed against a lease whose `guarantor_required` is true and which does not already hold an application in `SUBMITTED`, `UNDER_REVIEW`, `INFO_REQUESTED`, or `APPROVED`; otherwise it is refused with `ERR_GUARANTOR_NOT_REQUIRED`. A new application is `SUBMITTED` with `round_count` 1. Its `income_multiple_bps` is computed as the guarantor's annual income times 10000, divided by the lease's annual rent (its `monthly_rent_cents` times 12), taking the floor — this basis-point multiple is never rounded up. It is recomputed on every submit and resubmit.

The underwriting posture is cyclic. A `PropertyManager` who owns the property advances the application via a review `decision` — `START_REVIEW`, `REQUEST_INFO`, `APPROVE`, or `DECLINE` — with an optional `note`. `START_REVIEW` moves a `SUBMITTED` application to `UNDER_REVIEW`, provided the lease is still `PENDING_GUARANTOR`, and records the acting `reviewer_user_id`. From `UNDER_REVIEW`, `REQUEST_INFO` moves it to `INFO_REQUESTED`, recording `reviewer_user_id` and the supplied `decision_note`. The student answers an `INFO_REQUESTED` round by resubmitting revised `guarantor_full_name` and `guarantor_annual_income_cents`; this replaces those values, recomputes `income_multiple_bps`, increments `round_count` by 1, and returns the application to `SUBMITTED`, reopening the cycle. A resubmit is refused with `ERR_GUARANTOR_MAX_ROUNDS_EXCEEDED` once `round_count` has already reached 3. Resubmitting an application that is not `INFO_REQUESTED`, or issuing a review decision that does not match the current status, is `ERR_GUARANTOR_INVALID_STATE`.

Two terminal decisions close the cycle. From `UNDER_REVIEW`, `APPROVE` requires the lease still `PENDING_GUARANTOR` and requires the application's `income_multiple_bps` to be at least 30000 — an exact 3.0000x multiple passes, one basis point short is refused with `ERR_GUARANTOR_INCOME_INSUFFICIENT`. Approval sets the application `APPROVED`, stamps `decided_at` and `reviewer_user_id`, and cascades the lease `PENDING_GUARANTOR → PENDING_SIGNATURE`. From `UNDER_REVIEW`, `DECLINE` sets the application `DECLINED`, stamps `decided_at` and `reviewer_user_id`, and cascades the lease `PENDING_GUARANTOR → CANCELLED`, stamping the lease's `terminated_at` to the current clock, which releases the bed slot and re-runs the unit and property rollups. Both `APPROVE` and `DECLINE` require the lease to be `PENDING_GUARANTOR`.

### 3.6. Installments, Payment, Lateness, and Funding Status

Signing mints the lease's `RENT` installments. The schedule splits `total_contract_cents` across `installment_count` charges by a pinned rounding order: floor the per-installment base share first — the contract total divided by the count, truncated — assign that base to installments 1 through the second-to-last, and push the entire residual onto the last installment, so the last charge is the contract total minus the base times one less than the count. This reconciles exactly: the sum of the schedule equals `total_contract_cents` to the cent, whereas rounding each line independently would not. Each `RENT` `Installment` gets a `sequence_number` from 1 to `installment_count` in due-date order, a `kind` of `RENT`, a `status` of `SCHEDULED`, an `amount_cents` from the split, and a `due_date` that is the lease's `term_start_date` advanced by 30 days for each step past the first. `AMENITY` and `SUBLET_FEE` charges, minted later, never join this allocation and never renumber the `RENT` rows; each takes a `sequence_number` one greater than the current maximum on the lease. A charge carries `late_fee_cents` (0 unless it was `LATE` when paid), `paid_cents` (its `amount_cents` plus `late_fee_cents` once `PAID`, else 0), and `paid_at` (the clock instant of payment, null unless `PAID`). A lease's charges of every kind are readable as a sub-resource ordered by `sequence_number`, filterable by `kind` and `status`.

Lateness is decided strictly by the clock. During the lateness sweep an installment becomes `LATE` only when the new clock date is strictly greater than its `due_date` plus a five-day grace — a payment made exactly on the due date plus five days carries no fee. The owning student pays a charge by supplying `amount_cents`, which must equal the installment's `amount_cents` exactly; a mismatch is `ERR_PAYMENT_AMOUNT_MISMATCH`, and partial payment is not supported. Payment is allowed only while the lease is `ACTIVE` or `TERMINATED`; a charge that is already `PAID` or `VOID`, or whose lease is in neither state, is `ERR_INSTALLMENT_NOT_PAYABLE`. When the charge was not `LATE`, its `late_fee_cents` is 0. When it was `LATE`, the late fee is the `amount_cents` times 500 basis points, divided by 10000 and rounded half up, then capped at 7500 cents — whichever is smaller. Paying sets the charge `PAID`, stamps `paid_at`, sets `paid_cents` to `amount_cents` plus the late fee, then cascades: the lease's `paid_cents` is recomputed and `funding_status` re-derived, the property's `escrow_balance_cents` is recomputed, and `payout_eligible` is re-derived, bumping the property `version`.

The `funding_status` axis evolves independently of `lease_status` and is recomputed in full after any installment mutation — payment, the lateness sweep, the termination void cascade, an amenity charge mint or void, and a sublet-fee mint. Over the lease's non-`VOID` installments, the status is decided by the first matching clause in this order: if there are none, `UNFUNDED`; else if every one is `PAID`, `SETTLED`; else if any is `LATE`, `DELINQUENT`; else if none is `PAID`, `UNFUNDED`; else if every non-`VOID` charge whose `due_date` is at or before the clock date is `PAID`, `CURRENT`; otherwise `PARTIAL`. The lease's `paid_cents` is the sum of `amount_cents` plus `late_fee_cents` over its `PAID` charges; its `amenity_fee_total_cents` is the sum of `amount_cents` over its non-`VOID` `AMENITY` and `SUBLET_FEE` charges; and `billed_total_cents` is `total_contract_cents` (treated as 0 before signing) plus `amenity_fee_total_cents`. `VOID` rows are excluded from every clause and every rollup.

### 3.7. Subletting

A leaseholder may sublet their bed for a summer or in-term window to another student. Creating a `Sublet` names the `lease_id`, the `subtenant_student_id`, the window dates `start_date` and `end_date`, and the `sublet_rent_cents` (greater than 0) the subtenant will pay. The host lease must be `ACTIVE` (else `ERR_LEASE_NOT_ACTIVE`) and its property `LISTED` or `FULLY_COMMITTED` (else `ERR_PROPERTY_NOT_ACTIVE`). The subtenant must differ from the host `student_id` (else `ERR_SUBTENANT_IS_LEASEHOLDER`) and, when their university demands it, must be `VERIFIED` (else `ERR_STUDENT_NOT_VERIFIED`). The window is half-open `[start_date, end_date)`; its `window_days` is the whole-day difference, which must be at least 21 days (else `ERR_WINDOW_TOO_SHORT`), and the window must lie inside the host lease term — its `start_date` at or after the lease `term_start_date` and its `end_date` at or before the lease `term_end_date` — or it is `ERR_WINDOW_OUTSIDE_LEASE_TERM`. The requested window may not overlap another sublet on the same host lease that is `REQUESTED`, `APPROVED`, or `ACTIVE`; two windows that merely touch at a shared endpoint are permitted, but any real overlap is `ERR_SUBLET_OVERLAP`. Finally the rent is capped: `sublet_rent_cents` may not exceed the host lease's `monthly_rent_cents` times 11000 basis points divided by 10000 and rounded half up — that is, 110.00% of the lease's monthly rent — or it is `ERR_SUBLET_RENT_ABOVE_CAP`. At creation the sublet stamps `window_days` and `sublet_total_cents` (the `sublet_rent_cents` times the whole-month count, where the month count divides `window_days` by 30 and rounds up) and is born `REQUESTED`.

The owning `PropertyManager` decides the request with a `decision` of `APPROVE` or `DECLINE` and an optional `note`. `APPROVE` stamps `platform_fee_cents` as the larger of 2500 cents and the `sublet_total_cents` times 800 basis points divided by 10000 and rounded half up — an 8.00% fee with a 2500-cent floor — moves the sublet `REQUESTED → APPROVED`, records `decided_by_user_id` and `decided_at`, and mints a `SUBLET_FEE` `Installment` on the host lease whose `amount_cents` equals `platform_fee_cents`, whose `due_date` is the sublet's `start_date`, and whose `sequence_number` is one past the current maximum; the new charge's `id` is stored on the sublet's `installment_id`, and the lease's `amenity_fee_total_cents` and `billed_total_cents` are recomputed. `DECLINE` moves the sublet `REQUESTED → DECLINED` and records `decided_by_user_id` and `decided_at`. A decision on a sublet that is not `REQUESTED` is `ERR_SUBLET_INVALID_STATE`.

Sublets reach their live states only by the clock checkpoint. In the sublet sweep an `APPROVED` sublet whose `start_date` has arrived becomes `ACTIVE`, and an `ACTIVE` sublet whose `end_date` has arrived becomes `COMPLETED`.

### 3.8. Amenities

A `PropertyManager` publishes an `Amenity` on a `property_id` with a `name`, an `amenity_type` (one of `PARKING`, `STORAGE`, `GYM`, `STUDY_ROOM`, `LAUNDRY`), a `capacity` of at least 1, and a `monthly_fee_cents` of at least 0. The `capacity` is the maximum number of concurrently active reservations whose closed windows may contain any single calendar day. A new amenity reports `active_assignment_count` 0.

A leaseholder reserves an amenity by creating an `AmenityAssignment` with the `amenity_id`, the `lease_id` to be billed, and the closed window `start_date` and `end_date`. The amenity's `property_id` must equal the billed lease's `property_id` (else `ERR_AMENITY_PROPERTY_MISMATCH`), and the host lease must be `ACTIVE` (else `ERR_LEASE_NOT_ACTIVE`). The window is closed `[start_date, end_date]`, so its `window_days` is the whole-day difference plus one; it must be at least 30 days (else `ERR_WINDOW_TOO_SHORT`) and must lie inside the lease term (else `ERR_WINDOW_OUTSIDE_LEASE_TERM`). Capacity is an aggregate, not exclusive, constraint: the assignment is admitted only if, for every calendar day in its closed window, the count of currently `ACTIVE` assignments whose closed windows contain that day plus this one does not exceed the amenity's `capacity`; because the windows are closed, two that merely touch at a single day do collide. Exceeding capacity on any day is `ERR_AMENITY_CAPACITY_EXCEEDED`. On success the assignment stamps `window_days`, `billed_months` (the `window_days` divided by 30 and rounded up), and `total_fee_cents` (the amenity's `monthly_fee_cents` times `billed_months`), and mints an `AMENITY` `Installment` on the lease with `amount_cents` equal to `total_fee_cents`, `due_date` equal to the assignment `start_date`, `status` `SCHEDULED`, and `sequence_number` one past the current maximum; the charge `id` is stored on `installment_id`. Creating the assignment increments the amenity's `active_assignment_count` by 1 and recomputes the lease's `amenity_fee_total_cents`, `billed_total_cents`, and `funding_status`. The assignment is born `ACTIVE`.

The leaseholder may release an `ACTIVE` assignment, moving it `ACTIVE → RELEASED`, stamping `released_at`, voiding the linked `AMENITY` charge when it is still `SCHEDULED` or `LATE`, decrementing the amenity's `active_assignment_count` by 1, and recomputing the lease's money rollups and `funding_status`. A `RELEASED` assignment no longer consumes capacity. Releasing an already-`RELEASED` assignment is `ERR_ASSIGNMENT_INVALID_STATE`.

### 3.9. Payout Settlement and the Escrow Ledger

Collected rent accumulates in each property's escrow. The `escrow_balance_cents` is the sum of `amount_cents` plus `late_fee_cents` over all `PAID` installments on the property's leases, minus the sum of `gross_collected_cents` over the property's `PAID` payouts; the `maintenance_reserve_cents` is the sum of `holdback_cents` over the property's `PAID` payouts. `payout_eligible` is true exactly when `escrow_balance_cents` is at least 50000 cents. A conserved invariant holds across the pipeline: at every moment the property's `escrow_balance_cents` plus the total `gross_collected_cents` of its `PAID` payouts equals the total collected from its `PAID` installments.

A finance `PlatformAdmin` opens a settlement by creating a `Payout` for a `property_id` over a closed window `[period_start_date, period_end_date]`, where `period_end_date` is at or after `period_start_date`. The create is guarded by optimistic concurrency on the property: it must carry `expected_property_version` matching the property's current `version`, else `ERR_STALE_VERSION` (HTTP 412). The requested window may not overlap the closed window of another payout on the same property that is `SUBMITTED`, `APPROVED`, or `PAID`, else `ERR_PAYOUT_PERIOD_OVERLAP`. At creation the system computes every money field in a fixed order. First `gross_collected_cents`: the sum of `amount_cents` plus `late_fee_cents` over `PAID` installments on the property's leases whose `paid_at` calendar date lies within the closed window — this must be strictly greater than 0, or the create is refused with `ERR_PAYOUT_EMPTY_PERIOD`. Second the fee tier, keyed on that pre-fee gross alone: `platform_fee_bps` is 900 when the gross is below 500000 cents, 700 when it is below 2000000 cents, and 500 otherwise. Third, the fee and holdback, each rounded once off the gross: `platform_fee_cents` is the gross times `platform_fee_bps` divided by 10000 rounded half up, and `holdback_cents` is the gross times 200 basis points divided by 10000 rounded half up. Fourth, `subtotal_cents` is the gross minus the fee minus the holdback. Fifth, the loyalty rebate: when `subtotal_cents` is at least 150000 cents, `rebate_cents` is the `platform_fee_cents` times 1000 basis points divided by 10000 rounded half up — 10.00% of the fee — and otherwise 0. Sixth, `net_amount_cents` is `subtotal_cents` plus `rebate_cents`. The payout is born `SUBMITTED`, records the creator's `X-User-ID` as `submitted_by_user_id`, and bumps the property `version`.

Settlement runs under segregation of duties. A second `PlatformAdmin` decides the payout with a `decision` of `APPROVE` or `REJECT` and an optional `note`; the acting `X-User-ID` must differ from `submitted_by_user_id`, or the decision is refused with `ERR_SEGREGATION_OF_DUTIES`. `APPROVE` additionally requires the property not to be `SUSPENDED` and moves the payout `SUBMITTED → APPROVED`, recording `approved_by_user_id`; `REJECT` moves it `SUBMITTED → REJECTED`, also recording `approved_by_user_id`. Deciding a payout that is not `SUBMITTED` is `ERR_PAYOUT_INVALID_STATE`. Paying an `APPROVED` payout moves it `APPROVED → PAID`, stamps `paid_at`, decreases the property's `escrow_balance_cents` by `gross_collected_cents`, increases `maintenance_reserve_cents` by `holdback_cents`, re-derives `payout_eligible`, and bumps the property `version`. Reversing a `PAID` payout is the compensating action: it moves it `PAID → REVERSED`, stamps `reversed_at`, returns the exact `gross_collected_cents` to escrow, removes the `holdback_cents` from the maintenance reserve, re-derives `payout_eligible`, and bumps the property `version` — leaving the conserved escrow quantity identical before the pay and after the reverse. Paying a payout that is not `APPROVED`, or reversing one that is not `PAID`, is `ERR_PAYOUT_INVALID_STATE`.

### 3.10. Turnover, Renewal, and Early Termination

Bed slots enforce a turnover gap. A candidate lease conflicts with an existing bed-holding lease on the same unit-and-bed-label slot — one whose `lease_status` is `PENDING_GUARANTOR`, `PENDING_SIGNATURE`, or `ACTIVE` — when the candidate's `term_start_date` falls before the existing lease's `term_end_date` advanced by fourteen (14) days, and the existing lease's `term_start_date` falls before the candidate's `term_end_date` advanced by fourteen days. In other words, each existing occupancy interval is inflated by a fourteen-day (14-day) vacancy buffer on its right edge, and a candidate that would begin before that buffer clears is rejected with `ERR_BED_TURNOVER_CONFLICT`; a candidate starting exactly on the existing end date plus 14 days is accepted. `DRAFT`, `ENDED`, `CANCELLED`, and `TERMINATED` leases never block. This conflict check runs on lease creation, submission, renewal, and group placement.

Renewal mints a successor lease on the same bed for a later term. The leaseholder renews an `ACTIVE` lease (else `ERR_LEASE_NOT_ACTIVE`) by supplying a new `term_start_date`, `term_end_date`, and `installment_count`. A new `Lease` is minted in `DRAFT` carrying the same `student_id`, `unit_id`, and `bed_label`, with `replaces_lease_id` pointing at the predecessor, whose row is left untouched. The successor's `term_days` must be legal (90 to 400), its start must not be in the past, and its window must clear the fourteen-day turnover gap after the predecessor's `term_end_date`; its `quoted_total_cents` and `guarantor_required` are stamped exactly as for a fresh application. The self-referential `replaces_lease_id` chain records the turnover history.

Early termination is the manager's escape hatch. The owning `PropertyManager` terminates an `ACTIVE` lease with an optional `reason` (terminating a lease that is not `ACTIVE` is `ERR_LEASE_INVALID_STATE`), which cascades widely: the lease moves `ACTIVE → TERMINATED` and stamps `terminated_at`; every installment still `SCHEDULED` or `LATE` whose `due_date` is after the clock date becomes `VOID`; because those charges voided, the lease's `amenity_fee_total_cents`, `billed_total_cents`, and `funding_status` are recomputed; the bed slot is released and the unit and property rollups plus the property posture are re-evaluated; every `ACTIVE` `AmenityAssignment` on the lease becomes `RELEASED`; and every `Sublet` on the lease that is `REQUESTED`, `APPROVED`, or `ACTIVE` becomes `COMPLETED`. Separately, a lease reaches `ENDED` only through the clock's auto-end sweep, when an `ACTIVE` lease's `term_end_date` arrives; that too releases the bed and re-runs the rollups.

## 4. Endpoint Definitions

The table below is a routing summary only; the request payloads, response shapes, and side effects for each route are specified in the §3 narratives. Creating a new resource returns HTTP 201; every state transition, modification, and read returns HTTP 200. The request/response envelope is always the §2.2 structure.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | /_clock/set_current_utc | Advance the logical clock and run the three-step ops checkpoint | PlatformAdmin |
| POST | /universities | Register a partner or non-partner institution | PlatformAdmin |
| GET | /universities/{id} | Read one university | PlatformAdmin, PropertyManager, UniversityPartner, Student |
| POST | /properties | Create a building in DRAFT | PropertyManager |
| GET | /properties/{id} | Read one property with escrow, rollups and version | PlatformAdmin, PropertyManager, UniversityPartner, Student |
| GET | /properties | List properties | PlatformAdmin, PropertyManager, UniversityPartner, Student |
| POST | /properties/{id}/list | Publish a DRAFT property | PropertyManager |
| POST | /properties/{id}/suspend | Suspend a LISTED or FULLY_COMMITTED property | PlatformAdmin |
| POST | /properties/{id}/reinstate | Return a SUSPENDED property to LISTED or FULLY_COMMITTED | PlatformAdmin |
| POST | /units | Add a unit with its bed-slot labels | PropertyManager |
| GET | /units/{id} | Read one unit with bed rollups and version | PlatformAdmin, PropertyManager, UniversityPartner, Student |
| GET | /units | List units | PlatformAdmin, PropertyManager, UniversityPartner, Student |
| POST | /students | Register a student profile | PlatformAdmin |
| GET | /students/{id} | Read one student | PlatformAdmin, PropertyManager, UniversityPartner, Student |
| GET | /students | List students | PlatformAdmin, PropertyManager, UniversityPartner, Student |
| POST | /students/{id}/verification-requests | Request enrollment verification | Student |
| POST | /students/{id}/verification-decision | Approve or reject a pending verification | UniversityPartner |
| POST | /roommate-groups | Open a roommate group | Student |
| GET | /roommate-groups/{id} | Read one roommate group | PlatformAdmin, PropertyManager, UniversityPartner, Student |
| GET | /roommate-groups | List roommate groups | PlatformAdmin, PropertyManager, UniversityPartner, Student |
| POST | /roommate-groups/{id}/invitations | Invite another student to the group | Student |
| POST | /roommate-groups/{id}/lock | Freeze the roster and stamp both match scores | Student |
| POST | /roommate-groups/{id}/place | Place a LOCKED group into a unit (OCC on unit version) | PropertyManager |
| GET | /group-memberships/{id} | Read one membership | PlatformAdmin, PropertyManager, UniversityPartner, Student |
| GET | /group-memberships | List memberships | PlatformAdmin, PropertyManager, UniversityPartner, Student |
| POST | /group-memberships/{id}/respond | Accept or decline an invitation | Student |
| POST | /leases | Apply for one bed slot | Student |
| GET | /leases/{id} | Read one lease | PlatformAdmin, PropertyManager, UniversityPartner, Student |
| GET | /leases | List leases | PlatformAdmin, PropertyManager, UniversityPartner, Student |
| POST | /leases/{id}/submit | Submit a DRAFT lease, reserving the bed | Student |
| POST | /leases/{id}/sign | Sign, stamping the contracted total and installments | Student |
| POST | /leases/{id}/cancel | Withdraw an unsigned lease | Student |
| POST | /leases/{id}/terminate | End an ACTIVE lease early | PropertyManager |
| POST | /leases/{id}/renew | Mint a successor lease on the same bed slot | Student |
| GET | /leases/{id}/installments | List a lease's charges | PlatformAdmin, PropertyManager, UniversityPartner, Student |
| POST | /installments/{id}/pay | Pay one charge in full | Student |
| POST | /guarantor-applications | Submit a guarantor for a lease | Student |
| GET | /guarantor-applications/{id} | Read one guarantor application | PlatformAdmin, PropertyManager, UniversityPartner, Student |
| GET | /guarantor-applications | List guarantor applications | PlatformAdmin, PropertyManager, UniversityPartner, Student |
| POST | /guarantor-applications/{id}/review | Advance underwriting (START_REVIEW/REQUEST_INFO/APPROVE/DECLINE) | PropertyManager |
| POST | /guarantor-applications/{id}/resubmit | Resubmit revised guarantor details | Student |
| POST | /sublets | Request a sublet of a bed | Student |
| GET | /sublets/{id} | Read one sublet | PlatformAdmin, PropertyManager, UniversityPartner, Student |
| GET | /sublets | List sublets | PlatformAdmin, PropertyManager, UniversityPartner, Student |
| POST | /sublets/{id}/decision | Approve or decline a sublet request | PropertyManager |
| POST | /amenities | Publish a shared amenity | PropertyManager |
| GET | /amenities/{id} | Read one amenity | PlatformAdmin, PropertyManager, UniversityPartner, Student |
| GET | /amenities | List amenities | PlatformAdmin, PropertyManager, UniversityPartner, Student |
| POST | /amenity-assignments | Reserve an amenity for a closed window | Student |
| GET | /amenity-assignments/{id} | Read one amenity assignment | PlatformAdmin, PropertyManager, UniversityPartner, Student |
| GET | /amenity-assignments | List amenity assignments | PlatformAdmin, PropertyManager, UniversityPartner, Student |
| POST | /amenity-assignments/{id}/release | Release an amenity reservation | Student |
| POST | /payouts | Open a settlement (OCC on property version) | PlatformAdmin |
| GET | /payouts/{id} | Read one payout | PlatformAdmin, PropertyManager |
| GET | /payouts | List payouts | PlatformAdmin, PropertyManager |
| POST | /payouts/{id}/decision | Approve or reject a settlement (segregation of duties) | PlatformAdmin |
| POST | /payouts/{id}/pay | Disburse an APPROVED settlement | PlatformAdmin |
| POST | /payouts/{id}/reverse | Reverse a PAID settlement | PlatformAdmin |

## 5. Error Code Catalogue

The trigger condition for each error is stated in the §2 and §3 narratives where the rule it enforces is described; this catalogue lists only the identifier and its HTTP status.

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_NOT_RESOURCE_OWNER | 403 |
| ERR_VALIDATION | 400 |
| ERR_UNIVERSITY_NOT_FOUND | 404 |
| ERR_PROPERTY_NOT_FOUND | 404 |
| ERR_UNIT_NOT_FOUND | 404 |
| ERR_STUDENT_NOT_FOUND | 404 |
| ERR_GROUP_NOT_FOUND | 404 |
| ERR_MEMBERSHIP_NOT_FOUND | 404 |
| ERR_LEASE_NOT_FOUND | 404 |
| ERR_GUARANTOR_APPLICATION_NOT_FOUND | 404 |
| ERR_INSTALLMENT_NOT_FOUND | 404 |
| ERR_SUBLET_NOT_FOUND | 404 |
| ERR_AMENITY_NOT_FOUND | 404 |
| ERR_AMENITY_ASSIGNMENT_NOT_FOUND | 404 |
| ERR_PAYOUT_NOT_FOUND | 404 |
| ERR_STALE_VERSION | 412 |
| ERR_PROPERTY_INVALID_STATE | 409 |
| ERR_STUDENT_INVALID_STATE | 409 |
| ERR_GROUP_INVALID_STATE | 409 |
| ERR_MEMBERSHIP_INVALID_STATE | 409 |
| ERR_LEASE_INVALID_STATE | 409 |
| ERR_GUARANTOR_INVALID_STATE | 409 |
| ERR_INSTALLMENT_NOT_PAYABLE | 409 |
| ERR_SUBLET_INVALID_STATE | 409 |
| ERR_ASSIGNMENT_INVALID_STATE | 409 |
| ERR_PAYOUT_INVALID_STATE | 409 |
| ERR_PROPERTY_NOT_ACTIVE | 409 |
| ERR_LEASE_NOT_ACTIVE | 409 |
| ERR_STUDENT_NOT_VERIFIED | 422 |
| ERR_BED_LABEL_UNKNOWN | 422 |
| ERR_AMENITY_PROPERTY_MISMATCH | 409 |
| ERR_UNIT_PROPERTY_MISMATCH | 409 |
| ERR_DUPLICATE_MEMBERSHIP | 409 |
| ERR_SUBTENANT_IS_LEASEHOLDER | 422 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_VERIFICATION_EXPIRED | 422 |
| ERR_GUARANTOR_MAX_ROUNDS_EXCEEDED | 409 |
| ERR_GUARANTOR_NOT_REQUIRED | 409 |
| ERR_CLOCK_BACKWARDS | 422 |
| ERR_TERM_LENGTH_INVALID | 422 |
| ERR_TERM_START_IN_PAST | 422 |
| ERR_WINDOW_OUTSIDE_LEASE_TERM | 422 |
| ERR_WINDOW_TOO_SHORT | 422 |
| ERR_BED_TURNOVER_CONFLICT | 409 |
| ERR_SUBLET_OVERLAP | 409 |
| ERR_AMENITY_CAPACITY_EXCEEDED | 409 |
| ERR_PAYOUT_PERIOD_OVERLAP | 409 |
| ERR_UNIVERSITY_CODE_TAKEN | 409 |
| ERR_EMAIL_TAKEN | 409 |
| ERR_DUPLICATE_UNIT_NUMBER | 409 |
| ERR_BED_LABELS_MISMATCH | 422 |
| ERR_PROPERTY_HAS_NO_UNITS | 409 |
| ERR_GROUP_SIZE_MISMATCH | 409 |
| ERR_GROUP_MATCH_SCORE_TOO_LOW | 422 |
| ERR_UNIT_CAPACITY_INSUFFICIENT | 409 |
| ERR_GUARANTOR_INCOME_INSUFFICIENT | 422 |
| ERR_SUBLET_RENT_ABOVE_CAP | 422 |
| ERR_PAYMENT_AMOUNT_MISMATCH | 422 |
| ERR_PAYOUT_EMPTY_PERIOD | 422 |
