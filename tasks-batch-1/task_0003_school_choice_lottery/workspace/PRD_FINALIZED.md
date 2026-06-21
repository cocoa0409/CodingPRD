# School Choice Lottery API — Product Requirements Document

## 1. Introduction

Public school districts across the country operate centralized choice and magnet-school lotteries each spring: families list their preferred schools in ranked order, sibling priority is honored, neighborhood boundaries are respected, and a fixed seat budget per school is allocated through a weighted random draw that gives extra consideration to families from higher-poverty catchments. Today, most districts run this process through a patchwork of spreadsheets, paper forms, and ad-hoc scripts written by a single overworked enrollment coordinator. The result is brittle: a missed deadline cascades into wrong-school placements, sibling preferences are forgotten when a family moves between cycles, and the rules that drive the lottery are buried in policy memos that no two districts interpret identically.

The School Choice Lottery API is the canonical backend for this process. It models the entire flow — from a district administrator opening a registration window, to families registering and submitting ranked applications, to the deterministic weighted-lottery run, to seat acceptance, waitlist promotion, and final closeout — as a single, auditable, state-machine-driven system. Two principal user roles operate the system: `DistrictAdmin` users who configure the geographic and capacity scaffolding for the cycle and drive its lifecycle transitions, and `Guardian` users who represent a family and act on that family's students, applications, and offers. A third role, `Anonymous`, exists solely for the public family-registration entry point. Inter-district transfer is permitted but capped, and a logical system clock backs every time-gated rule so that the lottery is reproducible and testable in compressed time.

The contract specified here is the single source of truth for both the implementer and the automated test suite. Every numeric threshold, state transition, validation precedence, and concurrency guard described below is exercised by tests; vague phrasings that admit multiple readings are explicit defects in this document.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API — except the public family-registration endpoint, which is callable anonymously — must carry two HTTP headers identifying the caller: `X-User-ID` (an opaque string identifier for the acting principal) and `X-User-Role` (the string name of the role being asserted). The set of recognized role names is exactly three: `DistrictAdmin`, `Guardian`, and `Anonymous`. Any value of `X-User-Role` outside this set, or any request that omits one of the required headers when they are required, is rejected with `ERR_UNAUTHENTICATED` and HTTP 401. A request whose headers are well-formed but whose role is not permitted to perform the requested operation is rejected with `ERR_FORBIDDEN` and HTTP 403.

When `X-User-Role` is `Guardian`, `X-User-ID` is the `id` of the acting `Family`; ownership checks on any resource that references a `Family` compare the resource's foreign-key field to `X-User-ID`. Concretely, a `Guardian` may only create or act upon an `Application` whose `student_id` points to a `Student` whose `family_id` equals `X-User-ID`; a guardian who attempts to submit, withdraw, accept, or decline on behalf of another family's student is rejected with `ERR_FORBIDDEN_OWNERSHIP` and HTTP 403. When `X-User-Role` is `DistrictAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit purposes but does not compare it against any entity's `id`. When `X-User-Role` is `Anonymous`, `X-User-ID` is likewise opaque and is permitted to be absent: the role is accepted only on the public family-registration endpoint and on no other endpoint.

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

All list endpoints accept two query parameters that govern pagination: `limit` and `offset`. The default value of `limit` is 10, its minimum is 1, and its maximum is 100; values outside this range are rejected with `ERR_INVALID_REQUEST` and HTTP 400. The default value of `offset` is 0 and it may not be negative. List responses default to ascending order of the resource's `created_at` timestamp, so older records appear before newer ones. The `meta` block of every list response carries `limit`, `offset`, `total_count` (the total number of rows matching the query, ignoring pagination), and `has_more` (a boolean indicating whether further pages exist beyond the current one).

### 2.4. Common Resource Properties and Optimistic Concurrency

Almost every resource exposed by the API carries the same four envelope properties. The `id` is a server-minted UUID string with no type prefix and is assigned at creation; clients never supply it. The `created_at` and `updated_at` timestamps are both ISO 8601 UTC strings with three fractional digits — `created_at` is set at insert time and never changes, while `updated_at` is refreshed on every mutation, including state transitions driven by system cascades. The `version` field is an integer that begins at 1 on creation and increments by exactly one each time the row is mutated; it is the parent token consulted by optimistic concurrency control.

Two resource types are deliberately leaner. A `SiblingBond` carries only `id` and `created_at` — neither `updated_at` nor `version` is present, because sibling bonds are append-only declarations that never mutate after creation. The `SystemClock` likewise carries no `updated_at` or `version`; it exposes only its `current_utc` reading.

Two write operations are guarded by optimistic concurrency. Running the lottery — that is, transitioning an `EnrollmentWindow` from `CLOSED` to `LOTTERY_RUN` — requires the request body to carry `expected_window_version` as a non-optional field whose value must equal the target window's current `version`. If the value does not match (typically because another administrator has already advanced the window through close-or-run since the client last read it), the request is rejected with `ERR_STALE_VERSION` and HTTP 412, and no lottery is run. Accepting an offer similarly requires the request body to carry `expected_offer_version` as a non-optional field equal to the target offer's current `version`; a mismatch — which most often arises when the offer has just been expired by a clock-driven sweep that bumped its version — is rejected with `ERR_STALE_VERSION` and HTTP 412 before the acceptance takes effect. No other endpoint accepts a version field.

### 2.5. Nested Resource Path Resolution

URL paths that reference a resource by `id` are validated left to right. For an endpoint such as the one that reads an application by id, the server first confirms the application exists; if it does not, the request is rejected with `ERR_NOT_FOUND` and HTTP 404 before any deeper check. When the same endpoint requires a foreign-key payload — for example, an application-creation request body that names a `window_id`, a `student_id`, and a `school_id` — each referenced row is resolved in turn, and the first missing reference produces `ERR_NOT_FOUND`. Existence checks always precede state checks, ownership checks, and business-rule checks; an `ERR_FORBIDDEN_OWNERSHIP` rejection therefore presupposes that all referenced rows exist.

### 2.6. Validation Precedence

When multiple validation rules apply to the same request, they are evaluated in a fixed priority order. Authentication (the presence and validity of `X-User-ID` and `X-User-Role`) is checked first, then role authorization, then existence of every referenced id, then the resource state for state-transition endpoints, then temporal preconditions on enrollment-window timing, then district-archived checks against referenced districts, then ownership for guardian-initiated operations, then per-window application uniqueness, then grade-range fit, then optimistic-concurrency version checks, then request-body schema and range checks for school capacity, and finally district data-sanity checks at window-open time. The first rule that fails dictates the rejection's `error_id` and HTTP status, and no subsequent rule is evaluated for that request. This ordering matters in practice: a guardian attempting to submit an application against a non-existent window is told the window does not exist (`ERR_NOT_FOUND`), not that they lack ownership.

### 2.7. Hierarchical Consistency and Cascade Semantics

Mutations frequently cascade across more than one entity. When the `EnrollmentWindow` advances from `OPEN` to `CLOSED`, every `Application` in that window whose status is still `DRAFT` is auto-transitioned to `WITHDRAWN`, and each cascaded application's `version` increments by one and its `updated_at` is refreshed. When the window advances from `CLOSED` to `LOTTERY_RUN`, the lottery-weight calculation runs over every `SUBMITTED` application in the window, the seat-assignment calculation partitions per-school applications into accepted and waitlisted sets, each accepted application transitions from `SUBMITTED` to `ACCEPTED` with a freshly created `Offer` whose `source` is `LOTTERY`, and each overflow application transitions from `SUBMITTED` to `WAITLISTED` with a freshly created `WaitlistEntry` whose `status` is `ACTIVE`. When the window advances from `LOTTERY_RUN` to `FINALIZED`, every `ACTIVE` waitlist entry whose school belongs to this window transitions to `REMOVED`, and any application still in `WAITLISTED` linked to such a removed entry transitions to `WITHDRAWN`. Every cascaded mutation bumps the affected row's `version` by one (except `WaitlistEntry`, which has no version field) and refreshes its `updated_at`.

A second cascade fires whenever a lottery-issued offer is declined or expires (see §3.5). The cascade reuses the same versioning and timestamp rules: each entity touched is mutated atomically with the triggering operation.

### 2.8. Precision and Rounding

All numeric scores produced by the calculation engine — the lottery weight, the family risk score, and the school acceptance rate — are reported to three decimal places and rounded half-up. The lottery weight has a deliberate ordering pin: the poverty-index boost is rounded to three decimals before it is summed with the other terms, and the final rounding is then applied once to the total sum; the prohibited alternative (rounding only the final sum) yields different last-digit outcomes on boundary cases. The family risk score is rounded first to three decimals and then clamped to the range from 0.000 to 1.000 inclusive. The school acceptance rate is rounded to three decimals; its competitive flag uses a strict less-than threshold (the boundary value of 0.300 is therefore not competitive). Integer ranks — `lottery_rank` and `queue_rank` — are not subject to rounding; they are produced as exact 1-based ordinals.

### 2.9. Test-Driving System Clock

The system carries a single logical clock, exposed as a `SystemClock` resource with one field, `current_utc`. The clock backs every time-gated transition: window open, window close, lottery run, offer expiry. A `DistrictAdmin`-only test-driving capability sets the clock to a supplied `to_iso8601` instant in one shot, and a read endpoint returns the current value. Advancing the clock past an offer's `respond_by` does not by itself transition that offer to `EXPIRED`; expiry happens during the windowed batch sweep described in §3.5. Advancing the clock past a window's `closes_at` likewise does not auto-close the window — the close transition still requires an explicit close call by a `DistrictAdmin` once the clock has passed `closes_at`.

## 3. Business Logic & Workflows

### 3.1. District and School Configuration

A `DistrictAdmin` begins each cycle by declaring the district itself: a unique short `code` (uppercase alphanumeric, between 3 and 8 characters, globally unique across the system), a human-readable `name`, and the district's federal `poverty_index_pct` — the catchment-level federal poverty rate, expressed as a percent between 0 and 100 inclusive with two decimal places. A new district's `status` starts as `ACTIVE`. The admin may later patch the district to update either its `poverty_index_pct` or its `status` (for example, archiving an out-of-service district by setting `status` to `ARCHIVED`); each such patch refreshes `updated_at` and bumps `version`. References to an `ARCHIVED` district from any subsequent create-application, family-register, school-create, or student-create operation are rejected with `ERR_DISTRICT_ARCHIVED`.

Each school is registered with a `district_id` (which must point to an `ACTIVE` district), a `code` unique within that district (uppercase alphanumeric, 3 to 12 characters), a display `name`, a `school_type` of either `NEIGHBORHOOD` or `MAGNET`, an inclusive grade band given by `grade_min` and `grade_max` (where kindergarten is grade 0, `grade_min` must not exceed `grade_max`, and `grade_max` may not exceed 12), and a `total_seats` integer that is at least zero. A subsequent patch can update the school's `name` or `total_seats`; `total_seats` below zero is rejected with `ERR_INVALID_REQUEST`.

Attendance boundaries are declared as separate rows: each `BoundaryRule` ties a `school_id` to a `zone_code` (uppercase alphanumeric, 3 to 10 characters — typically a postal code or attendance-zone label) and an `is_in_boundary` boolean that defaults to true. A given family's residence zone is in-boundary for a school exactly when a `BoundaryRule` row exists with that school's id, that family's residence zone code, and `is_in_boundary` true.

### 3.2. Enrollment Window Lifecycle

A `DistrictAdmin` creates an enrollment window in `DRAFT` for a given district and cycle. The creation payload supplies `district_id`, `cycle_label` (a human-readable identifier such as "2026-27" that must be unique within the district), and three timestamps: `opens_at` (inclusive — applications are accepted at or after this instant), `closes_at` (exclusive — applications are no longer accepted at this instant), and `lottery_runs_at` (the planned lottery instant, which must be at or after `closes_at`). Window timing must satisfy two invariants: `opens_at` must be strictly before `closes_at`, and `closes_at` must be at or before `lottery_runs_at`; either violation is rejected with `ERR_WINDOW_TIMING`.

Opening the window transitions it from `DRAFT` to `OPEN`. The operation is rejected with `ERR_INVALID_STATE` if the window is not in `DRAFT`, rejected with `ERR_WINDOW_TIMING` unless the system clock has reached `opens_at` but is still strictly before `closes_at`, rejected with `ERR_DISTRICT_ARCHIVED` if the window's district is not `ACTIVE`, and rejected with `ERR_DISTRICT_DATA_INVALID` if the district's `poverty_index_pct` is outside the 0-to-100 range — a data-sanity gate intended to catch corrupted district configurations before they distort lottery weighting.

Closing the window transitions it from `OPEN` to `CLOSED`. Closure is only permitted once the system clock has reached or passed `closes_at`; an early-close attempt is rejected with `ERR_INVALID_STATE`. The clock advancing past `closes_at` does not auto-close the window — the administrator must still call the close transition. On close, every application in `DRAFT` for this window cascades to `WITHDRAWN`.

Running the lottery transitions the window from `CLOSED` to `LOTTERY_RUN`. The operation requires the clock to have reached `lottery_runs_at` and the window to be in `CLOSED`; either failure surfaces as `ERR_INVALID_STATE` or `ERR_WINDOW_TIMING` as appropriate. The request body must also carry `expected_window_version` matching the window's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` and HTTP 412, since another administrator may have advanced the window in the interim.

Finalization transitions the window from `LOTTERY_RUN` to `FINALIZED` and may proceed only when no application in this window is still in `OFFERED` status — that is, every offer has either been accepted, declined, or expired. The transition cascades active waitlist entries on this window's schools to `REMOVED`, and any still-`WAITLISTED` application linked to one of those removed entries cascades to `WITHDRAWN`.

### 3.3. Family Registration, Students, and Sibling Bonds

A family registers through the public anonymous endpoint by supplying `guardian_email` (which is lowercased and is globally unique across all families), `residence_zone_code` (the zone identifier that the family lives in), `residence_district_id` (the `id` of an `ACTIVE` district where they reside), and `poverty_flag` (a boolean, default false, that records whether the family is below the federal poverty line for the cycle — a self-declared per-family marker that is independent of the catchment-level `poverty_index_pct`). Successful registration immediately recomputes the family's provisional risk score (see §3.7). A reference to an `ARCHIVED` district at registration is rejected with `ERR_DISTRICT_ARCHIVED`.

After registration, the family adds one or more students by providing `family_id` (which must match `X-User-ID` when the caller is a `Guardian`), `full_name`, and `grade_for_cycle` (the grade the student will enter during the cycle, with kindergarten encoded as 0 and an upper bound of 12). District admins may also create students on behalf of a family.

To declare sibling priority — the boost given when an applying student has a sibling already enrolled at the target school — the family or a district admin creates a `SiblingBond` row tying the applying `student_id` to the already-enrolled `sibling_student_id` and the `school_id` where the sibling is currently enrolled. The bond is an append-only declaration: it is read by the weighting calculation, but the system independently verifies the linked sibling's actual enrollment status at the moment the calculation runs.

### 3.4. Application Submission and the Five-Choice Limit

A `Guardian` creates an application by supplying `window_id`, `student_id`, `school_id`, and `choice_rank`. The `student_id` must belong to a `Student` whose `family_id` equals the caller's `X-User-ID`; otherwise the request is rejected with `ERR_FORBIDDEN_OWNERSHIP`. The `choice_rank` is an integer from 1 to 5 inclusive, where 1 designates the family's top preference. A student may submit at most five applications per window, and within a given window each of that student's applications must carry a distinct `choice_rank`; either a duplicate rank for the same student in the same window, a rank outside 1-to-5, or a sixth application for the same student in the same window is rejected with `ERR_DUPLICATE_CHOICE`. The student's `grade_for_cycle` must be within the school's `[grade_min, grade_max]` band inclusive on both ends; an out-of-band grade is rejected with `ERR_GRADE_OUT_OF_RANGE`. References to an `ARCHIVED` district (either the family's residence district or the school's operating district) are rejected with `ERR_DISTRICT_ARCHIVED`. A new application is created in `DRAFT` with `lottery_weight` defaulting to 0.0, `lottery_rank` defaulting to null, and `inter_district_transfer` defaulting to false; the family's provisional risk score is recomputed in the same operation.

The guardian later moves the application from `DRAFT` to `SUBMITTED` by submitting it; submission requires the parent enrollment window to be in `OPEN` and the student's `grade_for_cycle` to fit the school's grade band. The guardian may withdraw an application from either `DRAFT` or `SUBMITTED` to `WITHDRAWN` so long as the parent window is in `OPEN` or `CLOSED`. A `DistrictAdmin` may reject a `SUBMITTED` application — for example, on fraud or eligibility grounds — moving it to `REJECTED`; the same `OPEN`-or-`CLOSED` window-state precondition applies. Withdrawing, submitting, or rejecting all recompute the family's provisional risk score.

While the window is `OPEN`, a family may request a provisional preview of their lottery weight; the preview uses the provisional variant of the weighting calculation described in §3.6 and returns a `lottery_weight` and a `variant` label without persisting either to the application.

### 3.5. The Weighted Lottery, Offers, and Waitlist Promotion

When the lottery runs (the `CLOSED → LOTTERY_RUN` transition), the system computes a final `lottery_weight` for every `SUBMITTED` application in the window using the formula in §3.6, then partitions the applications school-by-school using the seat-assignment procedure in §3.6. Each school's applications are sorted by descending `lottery_weight`, then by descending `poverty_flag` of the applying family (true ranking before false), then by ascending `created_at` of the application; the resulting ordinals are written to `lottery_rank` starting at 1. The top `total_seats` applications by `lottery_rank`, after the inter-district-transfer cap is applied, become `ACCEPTED`; the remainder become `WAITLISTED` with `queue_rank` equal to `lottery_rank − total_seats`, so that the first overflow application carries `queue_rank` 1.

Every accepted application is paired with a freshly minted `Offer` row whose `application_id` points back to the application, whose `status` begins as `OFFERED`, whose `source` is `LOTTERY`, whose `offered_at` equals the clock at the lottery-run instant, and whose `respond_by` is exactly seven days after `offered_at`. Each waitlisted application is paired with a `WaitlistEntry` row whose `application_id`, `school_id`, and `queue_rank` are set as above and whose `status` begins as `ACTIVE`. At the moment each application becomes `ACCEPTED`, the `inter_district_transfer` flag on the application is recorded as true exactly when the school's `district_id` differs from the family's `residence_district_id`.

Families respond to offers by accepting or declining. Acceptance moves an `OFFERED` offer to `ACCEPTED` and, in the same atomic mutation, advances the linked application from `ACCEPTED` to `ENROLLED`; the request must carry `expected_offer_version` matching the offer's current `version` (rejected with `ERR_STALE_VERSION` if not) and may not proceed once the clock has reached `respond_by` (rejected with `ERR_INVALID_STATE`). Declination moves an `OFFERED` offer to `DECLINED`, advances the linked application from `ACCEPTED` to `DECLINED`, and triggers the waitlist-promotion cascade: the `ACTIVE` waitlist entry on the same school with the lowest `queue_rank` is selected, its linked application transitions from `WAITLISTED` to `ACCEPTED`, that waitlist entry's `status` becomes `PROMOTED`, a new offer is minted with `source` set to `WAITLIST_PROMOTION` and `respond_by` set to seven days after the cascade instant, and every remaining `ACTIVE` waitlist entry on the same school has its `queue_rank` decremented by one. Waitlist promotion is permitted only while the parent window is in `LOTTERY_RUN`.

A `DistrictAdmin` may trigger a batch sweep against a window to expire any `OFFERED` offer whose `respond_by` has been passed by the clock. The sweep returns a small object reporting `expired_count` (how many offers transitioned to `EXPIRED`) and `promoted_count` (how many waitlist entries were promoted as a consequence). Each expired offer cascades exactly like a declination: the linked application moves to `DECLINED`, the top `ACTIVE` waitlist entry on that school is promoted, a new offer is minted with `source` set to `WAITLIST_PROMOTION`, and queue ranks below the promoted entry shift down by one. The expiry sweep increments the window's `version` once for the batch.

### 3.6. The Lottery Weighting Formula and Seat Assignment

The lottery weight for an application is the sum of five terms, computed in a fixed order. The starting base term is 1.000 for every application. A sibling boost of 0.500 is added when a `SiblingBond` exists tying this application's `student_id` to a sibling at this application's `school_id`, provided the sibling's enrollment status passes the variant-specific check described below; otherwise the sibling boost is zero. An in-boundary boost of 0.300 is added when a `BoundaryRule` row exists tying this application's school to the family's `residence_zone_code` with `is_in_boundary` true; otherwise the in-boundary boost is zero. A poverty-index boost is then computed as the family's residence-district `poverty_index_pct` divided by 100 and multiplied by 0.400, then independently rounded half-up to three decimal places before being summed — this rounding pin matters: the poverty term is rounded once on its own to three decimals, the final sum is rounded once to three decimals, and no other intermediate rounding occurs. A family-poverty-flag boost of 0.200 is added when the family's `poverty_flag` is true and zero otherwise. The final `lottery_weight` is the half-up rounding of the sum of these five terms to three decimal places. The maximum achievable poverty-index boost is 0.400 (reached at a 100% catchment poverty rate).

The weighting calculation has two variants that share every term except the sibling check. In the provisional variant — invoked during the open window to give families a forward-looking preview — the sibling boost fires when a sibling bond exists and the linked sibling has at least one application against this school whose status is `SUBMITTED`, `ACCEPTED`, or `ENROLLED`. In the final variant — invoked once at the lottery instant, with the system clock at `lottery_runs_at` as the cutoff — the sibling boost fires only when the linked sibling has at least one application against this school whose status is `ENROLLED`. The two variants will therefore disagree when a sibling is mid-flight; the final variant is what is persisted to `lottery_weight`.

Seat assignment is a top-down waterfall. Within each school, applications are sorted by descending lottery weight, descending family `poverty_flag` (true ranks above false), and ascending application `created_at`, and the assigned `lottery_rank` is the 1-based position in that order. The first `total_seats` applications by rank are tentatively accepted, with one further constraint: the count of accepted applications whose `inter_district_transfer` would be true (because the application's school district differs from the family's residence district) may not exceed the inter-district-transfer cap, computed as the floor of 0.10 multiplied by the school's `total_seats`. Cap evaluation is strict and traverses the sorted list top-down: an inter-district application whose admission would push the running count of inter-district admits above the cap is skipped and demoted to the waitlist (retaining its place in the global sort order for `queue_rank` purposes), and the next in-district application by rank is promoted into the freed seat. The cap is floor-based, so a school with `total_seats` of nine has an inter-district-transfer cap of zero — at that capacity, no inter-district application can be accepted by the lottery, only by waitlist promotion that is in turn constrained by future cap evaluations. Applications below the accepted set become waitlisted with `queue_rank` equal to their `lottery_rank` minus `total_seats`.

### 3.7. The Family Risk Score

For internal monitoring of placement outcomes, the system maintains a per-family risk score in the range 0.000 to 1.000 inclusive. The score is recomputed at family-creation time and on every subsequent change to a member application's status. It exists in two variants. The provisional variant, available while at least one of the family's applications is still `SUBMITTED`, is computed as 0.15 multiplied by the count of the family's applications whose status is `WAITLISTED`, minus 0.20 multiplied by the count of the family's applications whose status is `ENROLLED`; declined applications are deliberately excluded, on the theory that a family with declined offers may still resubmit in the next cycle. The final variant, available post-finalization for audit, is 0.35 multiplied by the count of `DECLINED` applications plus 0.15 multiplied by the count of `WAITLISTED` applications minus 0.20 multiplied by the count of `ENROLLED` applications; this counts all terminal-state applications chronologically. Both variants are rounded half-up to three decimal places and then clamped to the interval from 0.000 to 1.000 inclusive — values that would otherwise be negative are clipped to 0.000 and values exceeding 1.000 are clipped to 1.000. The response returns the `risk_score` and a `variant` label indicating which formula produced it.

### 3.8. School Acceptance Rate and Competitive Flag

For each school, the system exposes a computed acceptance-rate signal in a response field named `acceptance_rate`. The rate is the count of `ACCEPTED` applications for the school in its district's most recent runnable enrollment window, divided by the count of `SUBMITTED`, `ACCEPTED`, and `WAITLISTED` applications for that school in the same window; the numerator counts `ACCEPTED` only and does not include applications that have progressed to `ENROLLED`. The "most recent runnable window" is the district's window with the greatest `lottery_runs_at` value whose `status` is either `LOTTERY_RUN` or `FINALIZED`; ties on `lottery_runs_at` (rare, since two windows would have to share an exact instant) break by ascending `created_at`. When the denominator is zero — either because no qualifying window exists at all, or because qualifying windows exist but the school has no applications in the most recent one — `acceptance_rate` is returned as 0.000. The response also includes a boolean `is_competitive` flag, which is true exactly when `acceptance_rate` is strictly less than 0.300; the boundary value 0.300 itself is not competitive. Because 0.000 is strictly less than 0.300, a school with a zero denominator (including the no-qualifying-window case) is reported with `is_competitive` true. The `source_window_id` of the contributing window is included in the response for traceability; when no qualifying window exists, `source_window_id` is returned as `null`.

## 4. Endpoint Definitions

Successful resource creation returns HTTP 201; successful mutations, state transitions, and reads return HTTP 200. All endpoints below adhere to the response envelope defined in §2.2. Request bodies, response payloads, and side effects are described in the workflow narratives in §3; this table summarizes only the wire-level contract.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/lottery/districts` | Create a new district configuration. | `DistrictAdmin` |
| GET | `/lottery/districts/{id}` | Get a district by id. | `DistrictAdmin`, `Guardian` |
| GET | `/lottery/districts` | List districts; supports filtering by status. | `DistrictAdmin`, `Guardian` |
| PATCH | `/lottery/districts/{id}` | Update district poverty index or status. | `DistrictAdmin` |
| POST | `/lottery/schools` | Create a school within an `ACTIVE` district. | `DistrictAdmin` |
| GET | `/lottery/schools/{id}` | Get a school by id. | `DistrictAdmin`, `Guardian` |
| GET | `/lottery/schools` | List schools; filterable by district and school type. | `DistrictAdmin`, `Guardian` |
| PATCH | `/lottery/schools/{id}` | Update school capacity or name. | `DistrictAdmin` |
| GET | `/lottery/schools/{id}/acceptance-rate` | Computed acceptance rate and competitive flag. | `DistrictAdmin`, `Guardian` |
| POST | `/lottery/boundary-rules` | Declare an attendance-boundary rule for a school. | `DistrictAdmin` |
| GET | `/lottery/boundary-rules/{id}` | Get a single boundary rule by id. | `DistrictAdmin`, `Guardian` |
| GET | `/lottery/boundary-rules` | List boundary rules; filterable by school. | `DistrictAdmin`, `Guardian` |
| POST | `/lottery/windows` | Create a new enrollment window in `DRAFT`. | `DistrictAdmin` |
| GET | `/lottery/windows/{id}` | Get an enrollment window. | `DistrictAdmin`, `Guardian` |
| GET | `/lottery/windows` | List enrollment windows; filterable by district and status. | `DistrictAdmin`, `Guardian` |
| POST | `/lottery/windows/{id}/open` | Transition window from `DRAFT` to `OPEN`. | `DistrictAdmin` |
| POST | `/lottery/windows/{id}/close` | Transition window from `OPEN` to `CLOSED`. | `DistrictAdmin` |
| POST | `/lottery/windows/{id}/run-lottery` | Transition window from `CLOSED` to `LOTTERY_RUN`. | `DistrictAdmin` |
| POST | `/lottery/windows/{id}/expire-offers` | Batch sweep: expire offers past respond-by with cascades. | `DistrictAdmin` |
| POST | `/lottery/windows/{id}/finalize` | Transition window from `LOTTERY_RUN` to `FINALIZED`. | `DistrictAdmin` |
| POST | `/lottery/families/register` | Register a new family and primary guardian. | `Anonymous` |
| GET | `/lottery/families/{id}` | Get a family by id. | `DistrictAdmin`, `Guardian` |
| GET | `/lottery/families` | List families; filterable by residence district. | `DistrictAdmin` |
| GET | `/lottery/families/{id}/risk-preview` | Provisional family risk score. | `DistrictAdmin`, `Guardian` |
| GET | `/lottery/families/{id}/risk-final` | Final family risk score. | `DistrictAdmin`, `Guardian` |
| POST | `/lottery/students` | Register a new student under a family. | `DistrictAdmin`, `Guardian` |
| GET | `/lottery/students/{id}` | Get a student. | `DistrictAdmin`, `Guardian` |
| GET | `/lottery/students` | List students; filterable by family. | `DistrictAdmin`, `Guardian` |
| POST | `/lottery/sibling-bonds` | Declare a sibling bond. | `DistrictAdmin`, `Guardian` |
| GET | `/lottery/sibling-bonds/{id}` | Get a single sibling bond by id. | `DistrictAdmin`, `Guardian` |
| GET | `/lottery/sibling-bonds` | List sibling bonds; filterable by student, sibling, or school. | `DistrictAdmin`, `Guardian` |
| POST | `/lottery/applications` | Create an application in `DRAFT`. | `Guardian` |
| GET | `/lottery/applications/{id}` | Get an application. | `DistrictAdmin`, `Guardian` |
| GET | `/lottery/applications` | List applications; filterable by window, student, school, status. | `DistrictAdmin`, `Guardian` |
| POST | `/lottery/applications/{id}/submit` | Transition application from `DRAFT` to `SUBMITTED`. | `Guardian` |
| POST | `/lottery/applications/{id}/withdraw` | Transition application (`DRAFT` or `SUBMITTED`) to `WITHDRAWN`. | `Guardian` |
| POST | `/lottery/applications/{id}/reject` | Transition `SUBMITTED` application to `REJECTED`. | `DistrictAdmin` |
| GET | `/lottery/applications/{id}/weight-preview` | Provisional lottery weight preview. | `DistrictAdmin`, `Guardian` |
| GET | `/lottery/offers/{id}` | Get an offer. | `DistrictAdmin`, `Guardian` |
| GET | `/lottery/offers` | List offers; filterable by application, status, source. | `DistrictAdmin`, `Guardian` |
| POST | `/lottery/offers/{id}/accept` | Accept an `OFFERED` offer; application becomes `ENROLLED`. | `Guardian` |
| POST | `/lottery/offers/{id}/decline` | Decline an `OFFERED` offer; triggers waitlist promotion. | `Guardian` |
| GET | `/lottery/waitlist-entries/{id}` | Get a waitlist entry. | `DistrictAdmin`, `Guardian` |
| GET | `/lottery/waitlist-entries` | List waitlist entries; filterable by school, application, status. | `DistrictAdmin`, `Guardian` |
| POST | `/_clock/set_current_utc` | Test-driving: set the system clock to a supplied UTC instant. | `DistrictAdmin` |
| GET | `/_clock/current` | Read the current system clock. | `DistrictAdmin`, `Guardian` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_WINDOW_TIMING` | 422 |
| `ERR_DISTRICT_ARCHIVED` | 422 |
| `ERR_DUPLICATE_CHOICE` | 409 |
| `ERR_GRADE_OUT_OF_RANGE` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_DISTRICT_DATA_INVALID` | 422 |
| `ERR_ZONE_UNKNOWN` | 422 |
