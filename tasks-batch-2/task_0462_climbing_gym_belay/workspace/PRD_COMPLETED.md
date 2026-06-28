# Climbing Gym Belay API — Product Requirements Document

## 1. Introduction

A modern climbing gym is, at its core, a safety operation wrapped around a hospitality business. Before anyone touches a wall, the gym must know that the climber has signed a liability waiver, that the waiver has not lapsed, and — on walls that demand it — that the climber holds a current belay or lead certification earned through a graded practical test. At the same time the front desk is selling day passes, opening recurring memberships, renting harnesses and ropes against refundable deposits, scheduling youth-team clinics, and tracking exactly how many bodies are on each bouldering floor at any given second. This system is the back-office API that ties all of that together: it is the single source of truth for membership billing, certification badges, route grading, live floor capacity, gear deposits, and the incident reports that occasionally force the gym to revoke a badge and pull a member off the floor.

The platform serves five distinct operator surfaces — front-desk staff, certification examiners, route setters, gym administrators, and the members themselves — each with a narrow slice of authority. The hardest problems it solves are concurrency and cascade. Two front-desk terminals can try to check the last climber onto a full floor at the same moment, and the API must let exactly one of them win without overselling the finite capacity. A single serious injury report can, in one atomic action, revoke a belay badge, suspend the injured member's membership, and clear them off every floor they are standing on. Money must be conserved to the cent across freezes, refunds, and renewals: a dollar of unused membership time becomes exactly a dollar of wallet credit, and a deposit always splits cleanly into a late fee plus a refund. This document specifies every entity, every state transition, every price calculation, and every guard rail the implementation must honor.

The server runs on a **logical clock** rather than wall-clock time. All expiry checks, billing windows, age derivations, and grace-period measurements read this clock, and an administrative endpoint moves it to any absolute instant so that time-dependent behavior can be exercised deterministically.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers identifying the caller: `X-User-ID` and `X-User-Role`. If either header is missing, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing. If both headers are present but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

There are exactly five roles, spelled precisely as follows: `Member`, `FrontDesk`, `Examiner`, `RouteSetter`, and `GymAdmin`.

- When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member` entity; this role is entity-backed. Ownership checks on any resource that references a member compare the resource's `member_id` foreign-key field to `X-User-ID`. A `Member` may only act on resources they own; when a `Member` attempts a mutation on a membership or enrollment whose `member_id` does not equal their `X-User-ID`, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).
- When `X-User-Role` is `FrontDesk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it but never compares it to any entity's `id`.
- When `X-User-Role` is `Examiner`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it as `examiner_user_id` on a `Certification` when an examiner grades a test, but otherwise does not compare it to any entity's `id`.
- When `X-User-Role` is `RouteSetter`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it as `setter_user_id` on a `Route` when a setter logs a route, but otherwise does not compare it to any entity's `id`.
- When `X-User-Role` is `GymAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it but does not compare it to any entity's `id`.

The precise menu of which role may invoke which operation is given by the authorization column of the endpoint table in Section 4. Roles are peers: front desk, examiner, route setter, and admin each own a distinct operational surface, and the member owns only their personal resources.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, read from the logical clock (Section 2.5) at response time rather than from wall-clock time.
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

All list endpoints accept two query parameters, `limit` and `offset`. The `limit` parameter defaults to 10, has a minimum of 1, and a maximum of 100. The `offset` parameter defaults to 0 and has a minimum of 0. A `limit` or `offset` that is present but non-integer, or out of its allowed range, is rejected with `ERR_INVALID_REQUEST` (HTTP 400). List results are always sorted by `created_at` in ascending order, with ties broken by ascending `id`. Beyond the filters named in each endpoint's description, list endpoints additionally honor optional exact-match filters on the resource's own scalar fields where applicable — including `status` and, where the resource carries them, foreign keys (`member_id`, `facility_id`, `clinic_id`, `setter_user_id`) and other scalars (e.g. `email` on members, `discipline` on certifications); an unrecognized query parameter is ignored. The `meta` block of a list response includes `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the number of records matching the filter before pagination and `has_more` is true when records remain beyond the current page.

### 2.4. Common Resource Properties and Identity

Every resource carries a server-minted `id`, which is a UUID with no type prefix and is used for identity only. Every resource also carries a `created_at` timestamp, expressed as an ISO 8601 UTC instant with three fractional digits and stamped from the logical clock at the moment of creation.

Most resources additionally carry an `updated_at` timestamp (same format, refreshed on every mutation) and an integer `version` field (described under concurrency below). Two resources are exceptions and carry **only** `id` and `created_at` — they have no `updated_at` and no `version`: the `Waiver` and the `Enrollment`. For these two, do not emit an `updated_at` or a `version`; their lifecycle is captured entirely by their own status fields and timestamps. Every other resource — `Member`, `Membership`, `Certification`, `Facility`, `Route`, `CheckIn`, `Clinic`, `Rental`, and `Incident` — carries the full set of common fields.

### 2.5. The Logical Clock

The system operates on a logical clock instead of wall-clock time. At server startup the clock reads exactly `2026-01-01T00:00:00Z`, and until it is explicitly set it stays at that default — it never falls back to real wall-clock time. An administrative test-driving capability advances the clock to a supplied absolute UTC instant carried in the `to_iso8601` field. Every time-sensitive rule in this document — waiver expiry, certification expiry, billing-cycle due dates, the grace-period sweep, clinic enrollment windows, rental due dates, and the youth-age derivation — reads its "now" from this logical clock.

### 2.6. Versioning, Mutation Semantics, and Optimistic Concurrency Control

Each versioned resource begins life with `version` equal to 1. Every successful mutation of that resource increments its `version` by exactly 1 and refreshes its `updated_at`. The `version` is the basis for optimistic concurrency control on the two endpoints that race against finite capacity.

Two write operations require an optimistic-concurrency token because they consume a finite shared resource:

- **Checking a member onto a floor** must carry an `expected_facility_version` field holding the client's last observed `version` of the target `Facility`. The new check-in legitimately supersedes the prior occupancy snapshot — it consumes one unit of the finite `floor_capacity` — so if another writer has advanced the facility's `version` since the client last read it, the client is operating on a stale view of remaining capacity. When `expected_facility_version` does not equal the facility's current `version`, the create is rejected with `ERR_STALE_FACILITY_VERSION` (HTTP 412).
- **Enrolling a member into a clinic** must carry an `expected_clinic_version` field holding the client's last observed `version` of the target `Clinic`. Each new enrollment supersedes the prior seat snapshot by consuming one unit of finite `seat_capacity`, so if the clinic's `version` has advanced since the client read it, the enrollment is rejected with `ERR_STALE_CLINIC_VERSION` (HTTP 412).

Several other mutating endpoints also take an expected-version token to guard against acting on a stale resource. Freezing, resuming, and cancelling a membership each require `expected_membership_version`; a mismatch with the membership's current `version` is rejected with `ERR_STALE_MEMBERSHIP_VERSION` (HTTP 412). Returning or reporting-lost a rental each require `expected_rental_version`; a mismatch is rejected with `ERR_STALE_RENTAL_VERSION` (HTTP 412). Stripping a route requires `expected_route_version`; a mismatch is rejected with `ERR_STALE_ROUTE_VERSION` (HTTP 412). Endpoints not described here as taking an expected-version field do not require one.

### 2.7. Monetary Precision and Conserved-Quantity Invariants

All money in the system is held in integer cents; there are no fractional cents anywhere. Where a calculation specifies rounding, "round half up" means round to the nearest whole cent with halves going up, and "floor" means truncate toward zero to a whole cent. The system upholds two conservation invariants to the cent. First, when a rental is settled, the original `deposit_cents` always splits exactly into a late fee plus a refund — the late fee and refund sum back to the deposit with nothing lost. Second, when a membership is frozen, the fee owed for the unused days of the current cycle converts one-for-one into wallet credit. A member's `wallet_credit_cents` is never negative and is always spent before a card is charged on the next renewal.

### 2.8. Nested Path Resolution and Existence

Referenced resources are validated left to right: a path identifier is resolved before any foreign key in the request body, and path identifiers are resolved in the order they appear in the URL. Any referenced resource that does not exist — whether it is a path id or a body foreign key — yields `ERR_NOT_FOUND` (HTTP 404). For the facility-scoped list endpoints (routes, check-ins, incidents, enrollments, and setter reports nested under a facility or clinic), the parent must exist before its child collection is filtered and returned.

### 2.9. Validation Ordering

When several checks could fail on one request, they are evaluated in a fixed priority order so that the first applicable failure is the one reported. The order is: (1) authentication of the headers, yielding `ERR_UNAUTHENTICATED`; (2) role authorization, yielding `ERR_FORBIDDEN_ROLE`; (3) existence of referenced resources, yielding `ERR_NOT_FOUND`; (4) resource ownership for member-role mutations on owned memberships and enrollments, yielding `ERR_NOT_RESOURCE_OWNER`; (5) the target resource being in a valid state for the requested transition, yielding `ERR_INVALID_STATE`; (6) well-formedness of the request body — required fields present, enum values valid, and numeric ranges respected — yielding `ERR_INVALID_REQUEST`; and then the domain-specific business gates that follow. The business gates, in order, are: (7) the check-in waiver gate, yielding `ERR_WAIVER_INVALID`; (8) the belay-certification gate, yielding `ERR_BELAY_CERT_REQUIRED`; (9) the lead-prerequisite gate, yielding `ERR_BELAY_PREREQUISITE_MISSING`; (10) the active-membership gate, yielding `ERR_MEMBERSHIP_NOT_ACTIVE`; (11) the clinic enrollment-window gate, yielding `ERR_ENROLLMENT_WINDOW_CLOSED`; (12) the optimistic-concurrency version match, yielding `ERR_STALE_FACILITY_VERSION` or `ERR_STALE_CLINIC_VERSION`; and (13) the capacity gate, yielding `ERR_CAPACITY_FULL`. In words: authentication precedes authorization, which precedes existence, which precedes ownership, which precedes state validity, which precedes body well-formedness, which precedes the safety and capacity gates — and within the safety gates the waiver is checked before the belay certification, which is checked before the membership-active rule, which is checked before the enrollment window, which is checked before the version match, which is checked before capacity. This ordering means a request that fails several rules surfaces the earliest one; for example, a check-in for a non-existent member returns `ERR_NOT_FOUND` rather than a later capacity or version error.

## 3. Business Logic & Workflows

### 3.1. Members, Waivers, and the Youth Distinction

Everything begins with a **member**. Front-desk staff register a member by supplying a `full_name`, an `email`, and a `date_of_birth`. The email must be unique across all members; an attempt to register a second member with an email already on file is rejected with `ERR_DUPLICATE_EMAIL` (HTTP 409). On creation the member's `status` is set to `ACTIVE` (the only other value being `DEACTIVATED`), the `wallet_credit_cents` balance starts at 0, and the system derives `is_youth` from the supplied `date_of_birth` measured against the logical clock at creation time: a member is a youth when their age in completed years as of the `created_at` date is under 18. The member's `id` is server-minted.

Before a climber can be checked onto any floor, they must have a **waiver** on file. Signing a waiver records the `member_id` of the signer, stamps `signed_at` from the logical clock, and computes `expires_at` as the signing instant plus 365 days. A waiver's `status` is derived, not stored as a free choice: it reads `VALID` while the clock is strictly before `expires_at`, and `EXPIRED` once the clock reaches or passes `expires_at`. When a waiver is retrieved or listed its status is recomputed against the current clock, so a waiver that was valid yesterday but whose expiry has since passed reads `EXPIRED` on the next read. If the signer is a youth, a `minor_guardian_name` must be supplied; if the signer is not a youth, `minor_guardian_name` must be omitted or null. Violating that guardian rule is a malformed body and is rejected with `ERR_INVALID_REQUEST`. A member may hold only one valid waiver at a time: signing a second waiver while an existing one is still `VALID` is rejected with `ERR_DUPLICATE_WAIVER` (HTTP 409). Waivers carry only an `id` and a `created_at` and no version. Either the front desk or the member themselves may sign a waiver; both may also retrieve waivers, and the waiver list may be narrowed to a single member.

### 3.2. Memberships: Two Independent Axes

A **membership** is opened by the front desk for a given member with a chosen `plan_tier`. The tier is either `BASIC` or `YOUTH_TEAM`, and it fixes the `monthly_fee_cents`: a `BASIC` plan costs 9000 cents per cycle and a `YOUTH_TEAM` plan costs 6000 cents per cycle. At creation the membership records `member_id`, sets `cycle_start` to the current clock instant, computes `cycle_end` as `cycle_start` plus 30 days, and starts its two status axes at their defaults with `version` equal to 1.

A membership tracks two **independent** status dimensions on the same row. The `billing_status` axis moves among `CURRENT`, `PAST_DUE`, and `CANCELLED`, with `CANCELLED` being terminal. The `access_status` axis moves among `ACTIVE`, `FROZEN`, `SUSPENDED`, and `TERMINATED`, with `TERMINATED` being terminal. These two axes evolve on their own timelines except where a transition explicitly reaches across to the other axis. The `past_due_since` timestamp records the clock instant the membership entered `PAST_DUE` and is null whenever billing is `CURRENT`; the `frozen_at` timestamp records the clock instant the membership was frozen and is null whenever access is not `FROZEN`.

**Freezing.** A member may freeze their own active membership. The freeze is permitted only when `access_status` is `ACTIVE` and `billing_status` is not `CANCELLED`; otherwise the transition is rejected with `ERR_INVALID_STATE`. A successful freeze moves `access_status` from `ACTIVE` to `FROZEN`, sets `frozen_at` to the current clock, credits the unused-days proration described in Section 3.7 to the member's `wallet_credit_cents`, and increments the membership's `version`. The freeze request must carry `expected_membership_version`.

**Resuming.** A member resumes their own frozen membership; this is allowed only when `access_status` is `FROZEN`, else `ERR_INVALID_STATE`. Resuming moves `access_status` from `FROZEN` back to `ACTIVE`, clears `frozen_at` to null, and rebases the billing cycle — it advances `cycle_start` to the current clock and recomputes `cycle_end` — because frozen days do not consume the cycle. The membership's `version` is incremented. The resume request carries `expected_membership_version`.

**Cancelling.** A member may cancel their own membership while `billing_status` is either `CURRENT` or `PAST_DUE`; from any other billing state the cancel is rejected with `ERR_INVALID_STATE`. Cancelling moves `billing_status` to `CANCELLED` and, crossing axes, moves `access_status` to `TERMINATED`. As a cascade, every still-active enrollment belonging to this member is withdrawn (each affected enrollment moves to `WITHDRAWN`, and each affected clinic has its `enrolled_count` recomputed and its `version` bumped). The membership's `version` is incremented. The cancel request carries `expected_membership_version`.

### 3.3. Recurring Billing, the Grace Window, and Suspension

Billing is driven by a single front-desk operation that supplies an `outcome` of `SUCCEEDED`, `FAILED`, or `SWEEP`. The three outcomes drive three different transitions.

**An on-time renewal** is a `SUCCEEDED` outcome on a membership whose billing is `CURRENT`. This is only meaningful once the cycle is due — that is, once the clock has reached or passed `cycle_end`; a `SUCCEEDED` outcome on a `CURRENT` membership whose cycle is not yet due is rejected with `ERR_INVALID_STATE` (HTTP 409), and a `SUCCEEDED` outcome on a membership whose billing is neither `CURRENT` nor `PAST_DUE` (i.e. `CANCELLED`) is likewise rejected with `ERR_INVALID_STATE`. The on-time renewal is refused on a frozen membership: a `SUCCEEDED` renewal attempted while `access_status` is `FROZEN` is rejected with `ERR_MEMBERSHIP_FROZEN` (HTTP 409), because a frozen membership is not billed. A successful renewal advances `cycle_start` to the current clock, recomputes `cycle_end`, applies the renewal charge (wallet first, then card, as detailed in Section 3.7), and increments the membership's `version`. The billing axis stays at `CURRENT` — this is the `CURRENT → CURRENT` self-loop of the billing cycle.

**A failed charge** is a `FAILED` outcome on a `CURRENT` membership whose cycle is due (the clock has reached or passed `cycle_end`); a `FAILED` outcome whose membership is not `CURRENT`, or whose cycle is not yet due, is rejected with `ERR_INVALID_STATE` (HTTP 409). It moves `billing_status` from `CURRENT` to `PAST_DUE`, stamps `past_due_since` with the current clock, and increments the `version`. Crucially, it does **not** change `access_status`: the member keeps `ACTIVE` access during the grace window. A back-payment is a `SUCCEEDED` outcome on a `PAST_DUE` membership, which clears `past_due_since` to null, advances `cycle_start` to the current clock and recomputes `cycle_end`, and increments the `version`; this is the `PAST_DUE → CURRENT` recovery hop. If at the moment of that back-payment the `access_status` had been driven to `SUSPENDED`, the recovery also restores `access_status` to `ACTIVE` — a cross-axis side effect that brings a suspended member back onto the floor.

**The grace sweep** is a `SWEEP` outcome. It applies only to a `PAST_DUE` membership — a `SWEEP` on a membership whose billing is not `PAST_DUE` is rejected with `ERR_INVALID_STATE` (HTTP 409) — and measures how long the membership has been overdue: the whole-day count is the number of complete days from `past_due_since` to the current clock, computed by taking the elapsed time and flooring it to whole days (each day being 86400 seconds). When that whole-day count is at least 7, the sweep moves `access_status` from `ACTIVE` to `SUSPENDED`. The boundary is exact: at 6 whole days overdue the sweep is a no-op, and at 7 whole days it suspends. A no-op sweep — fewer than 7 whole days overdue, or a membership whose `access_status` is not `ACTIVE` — still returns HTTP 200 with the membership unchanged and does not increment the `version` or refresh `updated_at`. Suspension blocks membership-based check-ins, and as a cascade every check-in this member currently has on the floor is automatically checked out (each such check-in moves to `CHECKED_OUT`, and each affected facility has its `occupancy` recomputed and its `version` bumped). The membership's `version` is incremented only when the sweep actually suspends. The terminal `TERMINATED` access state is reached only by cancellation (via the billing axis) or by a serious incident cascade, and once terminal there are no further access transitions.

### 3.4. Certifications: Registration, Grading, Expiry, and Revocation

A **certification** is a candidate's badge in a `discipline` that is either `BELAY` or `LEAD`. Registration — performed by the front desk or an examiner — records the `member_id` and the requested `discipline`, sets `status` to `REGISTERED`, and starts `version` at 1. The graded fields (`weighted_score`, `min_station_score`, `passed_at`, `expires_at`, and `examiner_user_id`) are all null until the test is graded.

**Grading** is performed by an examiner against a registered certification and supplies four station scores in the request body: `knot`, `commands`, `catch`, and `lower`, each an integer from 0 to 100. The grading computes a `weighted_score` and a `min_station_score` as detailed in Section 3.7 and then branches. A certification can only be graded while it is `REGISTERED`; grading any other status is rejected with `ERR_INVALID_STATE`.

- If the weighted score is at least 80 **and** the lowest single station score is at least 60 — and, for a `LEAD` test, the lead prerequisite below is satisfied — the certification moves from `REGISTERED` to `PASSED`. The grading persists `weighted_score`, `min_station_score`, and `examiner_user_id` (the opaque `X-User-ID` of the grading examiner), stamps `passed_at` with the current clock, and computes `expires_at` as `passed_at` plus 365 days. The `version` is incremented.
- If the weighted score is below 80 **or** the lowest single station score is below 60, the certification moves from `REGISTERED` to `FAILED`. The grading persists `weighted_score`, `min_station_score`, and `examiner_user_id`, but `passed_at` and `expires_at` remain null. The `version` is incremented.

**The lead prerequisite.** Grading a `LEAD` certification to a pass requires that the same member already holds a `BELAY` certification that is in status `PASSED` and not expired. If that prerequisite belay badge is missing, the lead grading is rejected with `ERR_BELAY_PREREQUISITE_MISSING` (HTTP 422).

**Expiry.** A passed certification expires once the clock reaches or passes its `expires_at`. Expiry is not automatic on read; it is realized by an explicit refresh operation available to the front desk or an examiner, which moves a `PASSED` certification to `EXPIRED` when the clock is at or beyond `expires_at` (and increments the `version`). If the certification is not `PASSED`, or the clock has not yet reached `expires_at`, the refresh leaves the badge untouched or is rejected as an invalid state transition with `ERR_INVALID_STATE` as appropriate.

**Revocation.** A passed or expired certification can be revoked by the system as part of a serious-incident cascade. Revocation moves the badge to `REVOKED` and increments its `version`. A revoked badge is terminal for that badge; to recertify, the member must register a fresh certification, which begins a new `REGISTERED` lifecycle.

### 3.5. Facilities, Routes, and the Setter Report

A **facility** is a wall or bouldering area created by a gym administrator with a `name`, a `floor_capacity` (which must be at least 1), and an optional `requires_belay_cert` flag that defaults to false. On creation `occupancy` starts at 0 and `version` at 1. The `occupancy` is always the live count of check-ins on that facility whose status is `ON_FLOOR`. When `requires_belay_cert` is true, climbers must present a current belay or lead badge to enter, as Section 3.6 describes.

A **route** is logged on a facility by a route setter. The setter supplies the `facility_id`, the `grade`, and the `style`. The `grade` is a V-scale integer from 0 to 10 inclusive, and the `style` is one of `SLAB`, `OVERHANG`, or `ROOF`. The route's `setter_user_id` is captured from the setting examiner's — that is, the route setter's — opaque `X-User-ID`, its `set_on` instant is stamped from the clock, its `status` starts at `OPEN`, and its `version` at 1. At creation the route's `difficulty_points` is computed from the grade and style as described in Section 3.7. A setter may **strip** an open route, retiring it: stripping moves `status` from `OPEN` to `STRIPPED` (only valid from `OPEN`, else `ERR_INVALID_STATE`) and increments the `version`. The strip request carries `expected_route_version`. A stripped route stops counting toward open-route listings but keeps its `difficulty_points` so that historical setter aggregation remains accurate. The route-list endpoints (`/facilities/{id}/routes` and `/routes`) accept an optional `status` query parameter that, when supplied, restricts the listing to routes in that exact status (e.g. `status=OPEN`); `/routes` additionally accepts optional `setter_user_id` and `facility_id` filters, and `/facilities/{id}/routes` is implicitly scoped to its path facility.

The **setter report** is a computed read available to a route setter or an administrator. It takes a `setter_user_id` and a `month`, and returns that setter's total difficulty points and route count on the facility for the month. The aggregation is detailed in Section 3.7; both open and stripped routes within the window are included.

### 3.6. Check-Ins: Gates, Pricing, and Floor Capacity

Checking a member onto a facility floor is the most heavily guarded operation in the system, performed by front-desk staff. The request supplies a `member_id`, a `facility_id`, an `entry_kind`, and the `expected_facility_version` token; a day-pass entry may also set the `gear_bundle` flag. The `entry_kind` is either `MEMBERSHIP`, which draws on an active membership at no per-visit charge, or `DAY_PASS`, which pays a one-off fee. A successful check-in sets `status` to `ON_FLOOR`, computes `price_cents` (0 for a membership entry, or the day-pass price for a day-pass entry), stamps `checked_in_at` from the clock, leaves `checked_out_at` null, increments the facility's `occupancy` by one, and bumps the facility's `version`.

A check-in must clear a sequence of gates. First, the climber must hold a currently valid waiver — a waiver whose status is `VALID` because the clock is before its `expires_at`; absent that, the check-in is rejected with `ERR_WAIVER_INVALID` (HTTP 422). Next, if the target facility's `requires_belay_cert` is true, the member must hold a certification — in either the `BELAY` or `LEAD` discipline — whose status is `PASSED` and which is not expired; absent that, the check-in is rejected with `ERR_BELAY_CERT_REQUIRED` (HTTP 422). For a `MEMBERSHIP` entry, the member must additionally hold a membership whose `access_status` is `ACTIVE` (not `FROZEN`, `SUSPENDED`, or `TERMINATED`); if no active membership exists the check-in is rejected with `ERR_MEMBERSHIP_NOT_ACTIVE` (HTTP 422). The optimistic-concurrency check then compares `expected_facility_version` to the facility's current `version`, rejecting a stale token with `ERR_STALE_FACILITY_VERSION` as described in Section 2.6. Finally, capacity is checked: a check-in is admitted only while the facility's `occupancy` is strictly below its `floor_capacity`; when occupancy has reached or exceeded floor capacity the check-in is rejected with `ERR_CAPACITY_FULL` (HTTP 422). These gates are evaluated in the order just given, consistent with the global validation ordering of Section 2.9.

**Checking out** is a front-desk operation that moves a check-in from `ON_FLOOR` to `CHECKED_OUT`, stamps `checked_out_at` from the clock, recomputes the facility's `occupancy`, and bumps the facility's `version`. A check-in may also be checked out automatically by the system — when a membership is suspended by the grace sweep, or when a serious incident clears a member off the floor — with the same occupancy and version effects.

### 3.7. Money: Day-Pass Pricing, Freeze Credit, Renewal, Rental Settlement, and Scoring

This subsection collects the system's quantitative rules; the workflows above reference each by name.

**Day-pass price.** When a check-in is created with `entry_kind` of `DAY_PASS`, its `price_cents` is computed as follows. Start with a subtotal equal to the base day-pass fee of 2500 cents, plus an additional 1200 cents when the `gear_bundle` flag is set (bundling a harness and shoes), and nothing extra otherwise. If the member is a youth, a discount is taken: the youth discount is 20 percent of the subtotal, floored to a whole cent (truncated toward zero). The final `price_cents` is the subtotal minus that youth discount; for a non-youth member the discount is zero and the price equals the subtotal. A membership entry has a `price_cents` of 0 and never invokes this calculation.

**Freeze credit.** When a membership is frozen, the unused-days proration credited to the member's wallet is computed against the current clock. The number of unused days is the count of whole days remaining from the freeze instant to `cycle_end`, never less than zero. The credit is the `monthly_fee_cents` multiplied by the unused days, divided by the 30-day cycle length, with the result rounded half up to whole cents. That credit is added to the member's `wallet_credit_cents`. A what-if quote of this credit is available without mutation: the freeze-quote read runs the identical formula against the current clock and returns the prospective `freeze_credit_cents` and `unused_days`, but persists nothing — and because it reads the clock at quote time, the quoted figure can diverge from the committed credit if the clock advances between the quote and the actual freeze. The committed freeze is the authoritative value, evaluated and persisted at the freeze instant.

**Renewal charge.** When a due membership is renewed on a `SUCCEEDED` billing run, the charge is settled wallet-first. The evaluation order is pinned: the gross amount is the `monthly_fee_cents`; the amount drawn from the wallet is the smaller of the member's current `wallet_credit_cents` and that gross amount; the amount charged to the card is the gross minus the wallet draw; and the member's `wallet_credit_cents` is then reduced by the amount drawn. Because the wallet is applied before the card amount is derived, the card charge is exactly whatever remains after the wallet is spent. All quantities are integer cents with no rounding. The wallet never goes below zero by construction.

**Rental settlement.** A gear rental is checked out by the front desk against a refundable `deposit_cents` (which must be at least 0). On checkout the rental records the `member_id`, an `item_kind` of `HARNESS`, `SHOES`, or `ROPE` (informational), stamps `rented_at` from the clock, computes `due_at` as `rented_at` plus 24 hours, sets `status` to `OUT`, and starts `version` at 1; `returned_at` is null, and `late_fee_cents` and `refund_cents` are 0 until settlement. A rental settles down one of two branches, each carrying `expected_rental_version`:

- **Return.** Returning an out rental computes the late fee from how late it is. The hours late are the hours between `due_at` and the current return clock, never less than zero (a rental returned by its due date is not late). The whole days late are those hours divided by 24 and rounded up to the next whole day (so 0 hours is 0 days late, 1 to 24 hours is 1 day, 25 to 48 hours is 2 days, and so on). The raw fee is 800 cents per day late, and the `late_fee_cents` is that raw fee capped at `deposit_cents` — it never exceeds the deposit. The `refund_cents` is `deposit_cents` minus `late_fee_cents`, and that refund is credited to the member's `wallet_credit_cents`. The rental moves from `OUT` to `RETURNED`, stamps `returned_at` from the clock, and increments its `version`.
- **Report lost.** Reporting an out rental lost forfeits the whole deposit: `late_fee_cents` is set to the full `deposit_cents` regardless of timing, and `refund_cents` is 0 with no wallet credit. The rental moves from `OUT` to `LOST` and increments its `version`.

A rental may only be returned or reported lost while it is `OUT`; from any other status the transition is rejected with `ERR_INVALID_STATE`.

**Belay weighted score.** Grading computes the `weighted_score` from the four station scores with fixed weights: the knot station carries weight 0.30, the commands station 0.20, the catch station 0.30, and the lower station 0.20. The rounding order is pinned: first sum the four weighted contributions — 0.30 times `knot`, plus 0.20 times `commands`, plus 0.30 times `catch`, plus 0.20 times `lower` — in full precision, and only then round that single total half up to a whole integer to obtain `weighted_score`; do not round each weighted term before summing. The `min_station_score` is the smallest of the four raw integer station scores. A pass requires the `weighted_score` to be at least 80 and the `min_station_score` to be at least 60, as Section 3.4 applies.

**Setter monthly points.** Each route's `difficulty_points` is computed at creation as the base points times the style multiplier, rounded half up to a whole integer. The base points are 100 plus the grade times 50. The style multiplier is 1.0 for `SLAB`, 1.25 for `OVERHANG`, and 1.50 for `ROOF`. The setter report then sums the `difficulty_points` of every route on the requested facility that was set by the requested `setter_user_id` and whose `set_on` instant falls in the requested month — within the half-open window running from the first instant of that month up to, but not including, the first instant of the next month — including routes whose status is `OPEN` as well as those that have been `STRIPPED`. The report returns that integer `total_points` together with a `route_count` of the routes summed, and echoes back the requested `setter_user_id` and `month`; the response is a bare object carrying exactly these four fields and is not wrapped with the common `id`/`created_at` resource fields. The sum is order-independent. The `month` query parameter must be a `YYYY-MM` string with a month in `[1,12]`, and both `setter_user_id` and `month` are required query parameters; a missing or malformed value is rejected with `ERR_INVALID_REQUEST`.

### 3.8. Clinics and Enrollments

A **clinic** is a youth-team or skills session scheduled by a gym administrator with a `title`, a `starts_at` instant, an `ends_at` instant, and a `seat_capacity` (which must be at least 1). The `ends_at` must be strictly after `starts_at`; otherwise the request is malformed and rejected with `ERR_INVALID_REQUEST`. On creation `status` is `SCHEDULED`, `enrolled_count` is 0, and `version` is 1. The `enrolled_count` is always the live count of enrollments on the clinic whose status is `ENROLLED`.

An **enrollment** places a member into a clinic and may be created by the front desk or by the member themselves (a member may only enroll themselves). The request supplies the `clinic_id`, the `member_id`, and the `expected_clinic_version` token. Enrollment is gated by a time window: the clock must be strictly before the clinic's `starts_at`, so a session that has already started or been cancelled cannot be enrolled into — a violation is rejected with `ERR_ENROLLMENT_WINDOW_CLOSED` (HTTP 422). The optimistic-concurrency check then compares `expected_clinic_version` to the clinic's current `version`, rejecting a stale token with `ERR_STALE_CLINIC_VERSION`. Capacity is then enforced: an enrollment is admitted only while `enrolled_count` is strictly below `seat_capacity`; once the count has reached or exceeded the capacity the enrollment is rejected with `ERR_CAPACITY_FULL`. A successful enrollment sets `status` to `ENROLLED`, increments the clinic's `enrolled_count` by one, and bumps the clinic's `version`. An enrollment carries only an `id` and a `created_at` and has no version of its own.

A member may **withdraw** from a clinic, which moves their enrollment from `ENROLLED` to `WITHDRAWN`, recomputes the clinic's `enrolled_count`, and bumps the clinic's `version`. Withdrawal is valid only from `ENROLLED`, else `ERR_INVALID_STATE`. An enrollment may also be withdrawn by the system as a cascade — when the clinic itself is cancelled, or when the member cancels their membership.

**Cancelling a clinic** is a gym-administrator action valid only while the clinic is `SCHEDULED` (else `ERR_INVALID_STATE`). It carries `expected_clinic_version`, moves `status` from `SCHEDULED` to `CANCELLED`, withdraws every enrollment that is still `ENROLLED` (each moving to `WITHDRAWN`), recomputes `enrolled_count` down to 0, and increments the clinic's `version`.

### 3.9. Incidents and the Serious-Injury Cascade

An **incident** is an injury or safety report filed by the front desk or a gym administrator. It records the `member_id` of the involved party, the `facility_id` where it occurred, an optional `certification_id` naming a belay badge implicated in the event (null when none applies), a `severity` of either `MINOR` or `SERIOUS`, and a free-text `description`. On creation `status` is `OPEN`, `reported_at` is stamped from the clock, and `version` starts at 1.

When the severity is `SERIOUS`, filing the incident fires a three-hop cascade atomically at creation. First, if a `certification_id` was supplied, the referenced certification — when it is in status `PASSED` or `EXPIRED` — is revoked, moving to `REVOKED` and bumping that certification's `version`. Second, the involved member's membership, if its `access_status` is `ACTIVE` or `FROZEN`, is suspended, moving `access_status` to `SUSPENDED` and bumping that membership's `version`. Third, every check-in the member currently has `ON_FLOOR` is automatically checked out, each moving to `CHECKED_OUT` and prompting a recompute of the affected facility's `occupancy` and a bump of its `version`. A `MINOR` incident fires no cascade. Whatever the severity, an open incident is later closed by a gym administrator, moving `status` from `OPEN` to `RESOLVED` and incrementing the incident's `version`; resolving is valid only from `OPEN`, else `ERR_INVALID_STATE`.

## 4. Endpoint Definitions

All endpoints are mounted at the server root. A request that creates a new resource returns HTTP 201; a request that retrieves or modifies an existing resource returns HTTP 200. Request bodies, the resources returned, and side effects are described in the narratives of Section 3; the table below lists only the method, path, purpose, and the roles permitted to call each operation.

| Method | Path | Description | Authorized Role(s) |
|--------|------|-------------|--------------------|
| POST | `/_clock/set_current_utc` | Set the server logical clock to an absolute UTC instant | GymAdmin |
| POST | `/members` | Register a member | FrontDesk |
| GET | `/members/{id}` | Get a member | FrontDesk, Member, GymAdmin |
| GET | `/members` | List members (paginated) | FrontDesk, GymAdmin |
| POST | `/waivers` | Sign a waiver for a member | FrontDesk, Member |
| GET | `/waivers/{id}` | Get a waiver (status recomputed against clock) | FrontDesk, Member, GymAdmin |
| GET | `/waivers` | List waivers, filterable by member | FrontDesk, Member, GymAdmin |
| POST | `/memberships` | Open a membership for a member | FrontDesk |
| GET | `/memberships/{id}` | Get a membership | FrontDesk, Member, GymAdmin |
| GET | `/memberships` | List memberships, filterable by member | FrontDesk, Member, GymAdmin |
| GET | `/memberships/{id}/freeze-quote` | What-if freeze-credit quote (no mutation) | FrontDesk, Member |
| POST | `/memberships/{id}/freeze` | Freeze a membership; credit unused-days proration to wallet | Member |
| POST | `/memberships/{id}/resume` | Resume a frozen membership; rebase cycle to clock | Member |
| POST | `/memberships/{id}/run-billing` | Run a billing event (renew / fail to past-due / grace sweep) | FrontDesk |
| POST | `/memberships/{id}/cancel` | Cancel a membership; terminate access, withdraw enrollments | Member |
| POST | `/certifications` | Register a member for a certification test | FrontDesk, Examiner |
| GET | `/certifications/{id}` | Get a certification | FrontDesk, Member, Examiner, GymAdmin |
| GET | `/certifications` | List certifications, filterable by member | FrontDesk, Member, Examiner, GymAdmin |
| POST | `/certifications/{id}/grade` | Grade a registered certification (pass or fail) | Examiner |
| POST | `/certifications/{id}/refresh-status` | Refresh a passed certification to expired when due | FrontDesk, Examiner |
| POST | `/facilities` | Create a climbing facility / wall | GymAdmin |
| GET | `/facilities/{id}` | Get a facility | FrontDesk, Member, RouteSetter, GymAdmin |
| GET | `/facilities` | List facilities | FrontDesk, Member, RouteSetter, GymAdmin |
| GET | `/facilities/{id}/routes` | List routes on a facility | FrontDesk, Member, RouteSetter, GymAdmin |
| GET | `/facilities/{id}/check-ins` | List check-ins on a facility | FrontDesk, GymAdmin |
| GET | `/facilities/{id}/incidents` | List incidents on a facility | GymAdmin |
| GET | `/facilities/{id}/setter-report` | Monthly difficulty-points total for a setter on this facility | RouteSetter, GymAdmin |
| POST | `/routes` | Log a newly-set route | RouteSetter |
| POST | `/routes/{id}/strip` | Strip (retire) a route | RouteSetter |
| GET | `/routes` | List routes, filterable by setter | FrontDesk, RouteSetter, GymAdmin |
| POST | `/check-ins` | Check a member onto a facility floor | FrontDesk |
| GET | `/check-ins/{id}` | Get a check-in | FrontDesk, GymAdmin |
| GET | `/check-ins` | List check-ins, filterable by member | FrontDesk, GymAdmin |
| POST | `/check-ins/{id}/check-out` | Check a member off the floor | FrontDesk |
| POST | `/clinics` | Schedule a youth/skills clinic | GymAdmin |
| GET | `/clinics/{id}` | Get a clinic | FrontDesk, Member, GymAdmin |
| GET | `/clinics` | List clinics | FrontDesk, Member, GymAdmin |
| POST | `/clinics/{id}/cancel` | Cancel a clinic; withdraw all enrollments | GymAdmin |
| GET | `/clinics/{id}/enrollments` | List enrollments on a clinic | FrontDesk, GymAdmin |
| POST | `/enrollments` | Enroll a member into a clinic | FrontDesk, Member |
| GET | `/enrollments/{id}` | Get an enrollment | FrontDesk, Member, GymAdmin |
| GET | `/enrollments` | List enrollments, filterable by member | FrontDesk, Member, GymAdmin |
| POST | `/enrollments/{id}/withdraw` | Withdraw a member from a clinic | Member |
| POST | `/rentals` | Check out a gear rental against a deposit | FrontDesk |
| GET | `/rentals/{id}` | Get a rental | FrontDesk, Member, GymAdmin |
| GET | `/rentals` | List rentals, filterable by member | FrontDesk, Member, GymAdmin |
| POST | `/rentals/{id}/return` | Return a rental; compute late fee, refund remaining deposit | FrontDesk |
| POST | `/rentals/{id}/report-lost` | Mark a rental lost; forfeit the full deposit | FrontDesk |
| POST | `/incidents` | File an incident/injury report | FrontDesk, GymAdmin |
| GET | `/incidents/{id}` | Get an incident | FrontDesk, GymAdmin |
| GET | `/incidents` | List incidents, filterable by member | GymAdmin |
| POST | `/incidents/{id}/resolve` | Resolve an open incident | GymAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|----------|------------------|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_NOT_RESOURCE_OWNER | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_WAIVER_INVALID | 422 |
| ERR_BELAY_CERT_REQUIRED | 422 |
| ERR_BELAY_PREREQUISITE_MISSING | 422 |
| ERR_MEMBERSHIP_NOT_ACTIVE | 422 |
| ERR_MEMBERSHIP_FROZEN | 409 |
| ERR_ENROLLMENT_WINDOW_CLOSED | 422 |
| ERR_CAPACITY_FULL | 422 |
| ERR_STALE_FACILITY_VERSION | 412 |
| ERR_STALE_CLINIC_VERSION | 412 |
| ERR_STALE_MEMBERSHIP_VERSION | 412 |
| ERR_STALE_RENTAL_VERSION | 412 |
| ERR_STALE_ROUTE_VERSION | 412 |
| ERR_DUPLICATE_EMAIL | 409 |
| ERR_DUPLICATE_WAIVER | 409 |
