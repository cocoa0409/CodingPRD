# Microschool Pod Management API — Product Requirements Document

## 1. Introduction

Microschools and learning pods occupy an awkward regulatory and operational middle ground: they are too small to run a district's back office, yet too structured to survive on a shared spreadsheet. A pod operator must form a family cohort and price tuition per seat, staff certified guides against student-ratio rules, maintain a multi-age curriculum and hold progress conferences, secure a facility and navigate zoning-based licensing exemptions, publish health and safety policies with an emergency plan, accept mid-year enrollments with prorated tuition, honor state ESA voucher funding, and — when a pod fails — dissolve it with a defensible refund waterfall. Each of these obligations interacts with the others: a guide's resignation can flip a pod's compliance posture overnight, and a single enrollment can push an invoice's administration fee into a different tier.

This document specifies a REST API that operationalizes that entire lifecycle. The API is built around a **Pod** aggregate whose derived **posture** gates what its child records (seats, assignments, conferences) may do at any moment, and whose compliance flag is continuously reconciled from staffing and enrollment data. Around the pod sit family and student records, voucher accounts with dual verification-and-funding lifecycles, a tiered invoicing and payment ledger, licensing determinations with a resubmission loop, and a refund-claim pipeline guarded by segregation of duties. A server-side logical clock, settable by platform administrators, makes every date-dependent transition deterministic and testable. The intended readers are the engineers who will implement the service; every rule below is normative.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contract: authentication, response envelopes, pagination, resource conventions, the logical clock, monetary precision, pod posture gating, optimistic concurrency, cascade semantics, and the order in which requests are validated.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The recognized role values are exactly `PlatformAdmin`, `PodOperator`, `ComplianceOfficer`, `Registrar`, `Guide`, and `Family`. A request whose `X-User-Role` header is missing or holds a value outside this set — or whose `X-User-ID` header is missing for any of these roles — is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not permitted to invoke the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

The meaning of `X-User-ID` differs by role. When `X-User-Role` is `PlatformAdmin`, `PodOperator`, `ComplianceOfficer`, or `Registrar`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example, as `filed_by_user_id` when a `Registrar` files a refund claim, or as `reviewed_by_user_id` when one decides it — but it is never compared to any entity's `id`. When `X-User-Role` is `Guide`, `X-User-ID` is the `id` of the acting `Guide`; ownership checks on any resource that references a `Guide` compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `Family`, `X-User-ID` is the `id` of the acting `Family`; ownership checks on any resource that references a `Family` compare the resource's foreign-key field to `X-User-ID`.

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

List endpoints accept two query parameters. `limit` sets the maximum number of items returned: it defaults to 10 when omitted, and any value below 1 or above 100 is rejected. `offset` sets the number of items skipped and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

Most list endpoints additionally accept filter parameters specific to their resource — for example the pod directory can be filtered by `status`, `posture`, or `facility_site_id`; the cross-pod student listing by `family_id`, `esa_account_id`, or `student_status`. Filter parameters are always optional and always named exactly as the resource field they match; the per-resource filters are identified in the workflow narratives of §3 alongside each resource.

### 2.4. Common Resource Properties

Every primary resource carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, fixed at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on any mutation.
- `version` (integer): starts at 1 and increments by exactly 1 on every mutation of the resource, including mutations the server performs as cascade side effects.

One resource deviates from this convention: a `Payment` is an immutable ledger entry and carries only `id` and `created_at` — both `updated_at` and `version` are absent from it.

Any request body that is missing a required field, supplies a value of the wrong type, or fails basic format validation — a malformed enum value or a negative amount, for instance — is rejected with `ERR_INVALID_REQUEST` (HTTP 400) before any deeper rule is evaluated.

### 2.5. The Logical Clock

Date-dependent behavior never reads the wall clock; it reads a server-side logical clock. At startup, before any administrative intervention, the logical clock reads `2026-05-01T00:00:00Z`. A `PlatformAdmin` may advance it through an admin-only clock-setting capability whose request body carries `to_iso8601` and whose response echoes the new value as `current_utc`. Advancing the clock may fire system-side transitions whose preconditions depend on the current date — a scheduled guide assignment coming into force on its `window_start_date`, an assignment ending once the clock passes its `window_end_date`, an issued invoice lapsing to `OVERDUE` past its `due_date`, or a scheduled conference becoming eligible to be marked `NO_SHOW` once its `scheduled_end` has passed. Withdrawal requests also validate their `withdrawn_on` against this clock rather than against real time.

### 2.6. Nested Resource Retrieval

Requests that address nested resources are validated left to right along the URL path. Each path-templated identifier must resolve to an existing resource, and the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not — a request aimed at a seat beneath a non-existent pod fails on the pod before the seat is ever consulted. The same error, at the same precedence tier, applies to foreign keys carried in request bodies: identifiers such as `pod_id`, `student_id`, `facility_site_id`, `guide_id`, `curriculum_plan_id`, `esa_account_id`, or `seat_id` must resolve to existing entities, or the request fails with `ERR_NOT_FOUND`.

### 2.7. Monetary Values, Ratios, and Rounding

All money in the system is represented as integer cents; no fractional cents exist at rest or in transit. Whenever a division or percentage multiplication would produce a fractional cent — prorated tuition, refund amounts, administration fees, pro-rata waterfall shares — the result is rounded half up to the nearest whole cent. The one non-monetary computed quantity is the guide-to-student ratio, which is evaluated to four decimal places with exact comparisons at its classification boundaries.

### 2.8. Pod Posture and the Compliance Flag

Beyond its lifecycle `status`, every pod carries two derived attributes. `posture` — one of `OPEN`, `RESTRICTED`, `FROZEN`, or `CLOSED` — is the operational gate through which child mutations must pass, and `compliance_flag` — one of `COMPLIANT`, `AT_RISK`, or `VIOLATION` — is the latest evaluation of the pod's staffing ratio and licensing posture.

A pod whose `posture` is `FROZEN` refuses five categories of child mutation with `ERR_POD_FROZEN` (HTTP 409): reserving a seat, enrolling a reserved seat, withdrawing an enrolled seat, requesting a progress conference, and scheduling a guide assignment. A pod whose `posture` is `CLOSED` refuses every child mutation. Posture is never set directly by clients; it is recomputed by the server as lifecycle transitions and compliance evaluations unfold, as detailed throughout §3.

### 2.9. Optimistic Concurrency Control

Two write operations guard against stale reads with optimistic concurrency control on the parent pod.

Enrolling a reserved seat requires the request body to carry `expected_pod_version`, holding the pod `version` the client last observed. Because every enrollment advances the pod's `version` as it recomputes `enrolled_count`, a client whose view of remaining capacity predates another enrollment holds a stale version; if `expected_pod_version` does not equal the pod's current `version`, the enrollment is rejected with `ERR_STALE_VERSION` (HTTP 412).

Initiating pod dissolution carries the same guard: the request must carry `expected_pod_version` matching the pod's current `version`. A pod whose version has advanced since the client last read it — through a fresh enrollment or any other versioned mutation — no longer matches the dissolution-refund baseline the client computed against, and the dissolution request is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint accepts a version field.

### 2.10. Hierarchical Consistency and Cascading Mutations

The server keeps parent and child aggregates consistent without waiting for clients to repair them. When a parent's transition renders children non-operational — a pod dissolving beneath its seats, assignments, and plans — the server cascades state changes through every affected child in the same request. When a child mutation changes the inputs to a parent's derived attributes — a seat enrolling beneath a pod's capacity and ratio arithmetic — the server recomputes those attributes immediately. Every such cascade step is itself a mutation: it refreshes the affected resource's `updated_at` and increments its `version` by 1. Consistency is immediate, not eventual; a response is returned only after every cascade and recomputation the transition triggers has been applied.

### 2.11. Request Validation Order

Incoming requests are checked against a fixed priority ladder, and the first failing check determines the error returned. Authentication comes first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_FORBIDDEN`), then existence of path-templated resources (`ERR_NOT_FOUND`), then existence of body-referenced foreign keys (`ERR_NOT_FOUND`), then state-machine validity of the requested transition (`ERR_INVALID_STATE`, HTTP 409), then the pod posture gate (`ERR_POD_FROZEN`), and finally the business rules of §3 in their stated order.

Where several business rules guard one operation, their relative order is part of the contract. Seat enrollment evaluates the posture gate first, then capacity, then the term window. Creating a guide assignment evaluates the posture gate first, then window overlap against the guide's existing commitments, then window validity, then the guide's active standing. Requesting a progress conference evaluates the posture gate, then conference overlap, then window validity, then curriculum-plan approval. Posting or clearing a payment evaluates voucher-funds sufficiency before the overpayment ceiling. Deciding a refund claim evaluates segregation of duties before the approved-amount bounds. Reserving a seat evaluates the posture gate, then duplicate-seat uniqueness, then the term window.

## 3. Business Logic & Workflows

### 3.1. Sites, Pods, and the Road to Opening Day

A pod's physical home is a **FacilitySite**, registered by a `PlatformAdmin` with a `site_name`, a street `address_line1`, a `jurisdiction_code` such as `AZ-MARICOPA` or `TX-HARRIS` that determines the applicable zoning regime, a `zoning_class` drawn from `RESIDENTIAL_SINGLE`, `RESIDENTIAL_MULTI`, `COMMERCIAL`, `MIXED_USE`, `RELIGIOUS`, or `AGRICULTURAL`, a fire-marshal `max_occupancy`, and the net instructional `indoor_sqft` — both of the latter strictly positive integers. A site's `site_status` begins at `AVAILABLE`, moves to `LEASED` the moment a pod referencing it opens enrollment, and may be soft-deleted to `ARCHIVED` by a `PlatformAdmin` provided no pod in any status other than `DISSOLVED` references it; archived sites cannot host new pods but remain queryable. A leased site returns to `AVAILABLE` through a `PlatformAdmin` release, which is permitted only when no pod in `DRAFT`, `FORMING`, `LICENSING_REVIEW`, `ACTIVE`, `SUSPENDED`, or `DISSOLVING` references it. The site directory can be filtered by `site_status` or `jurisdiction_code`.

With a site in place, a `PodOperator` founds a pod by supplying a human-readable `name`; a `pod_code` that is unique across all pods under case-insensitive comparison and runs four to twenty-four alphanumeric characters; an `academic_year` label such as `2026-2027`, which becomes immutable once the first enrollment occurs; the year's `term_start_date` and `term_end_date`; a `seat_capacity` between 5 and 30 inclusive, as zoning rules require; the published `tuition_full_year_cents` per seat, a strictly positive integer; the `min_guides_required` compliance floor, an integer of at least 1 derived from the seat capacity at creation time; and the `facility_site_id` of the host site. A new pod's `status` is `DRAFT`, its `enrolled_count` is a derived count of seats currently `ENROLLED`, and its `dissolved_at` remains null until dissolution finalizes. The pod directory can be filtered by `status`, `posture`, or `facility_site_id`.

Opening enrollment — moving a pod from `DRAFT` to `FORMING` — is a `PodOperator` action gated on three preconditions: the referenced site must be `AVAILABLE` or `LEASED`; the pod must hold at least one `APPROVED` safety policy; and it must hold at least one `APPROVED` curriculum plan. A missing or inadequate safety policy is rejected with `ERR_SAFETY_POLICY_MISSING` (HTTP 422). On success the pod's `posture` is recomputed (typically landing on `OPEN`), an `AVAILABLE` host site flips to `LEASED`, and the pod's `version` increments. A pod that has not yet attracted a seat reservation can retreat: reverting from `FORMING` to `DRAFT` is permitted only while no seat in `RESERVED` or `ENROLLED` exists for the pod, and it recomputes posture and increments the pod's `version`.

### 3.2. Safety Policy and Curriculum Governance

Every pod publishes a **SafetyPolicy** capturing its health and emergency posture. A `PodOperator` drafts one with a `policy_version` — an integer of at least 1, monotonically increasing within the pod, each new version superseding its predecessor — the full `emergency_plan_text` preparedness plan, an `immunization_policy` of `REQUIRED`, `EXEMPTION_ALLOWED`, or `NOT_REQUIRED`, a `background_check_required` flag indicating whether every guide must clear a background check, and a `drill_cadence_days` emergency-drill interval between 7 and 90 days inclusive. The policy's `policy_status` begins at `DRAFT`. Approval is a `PlatformAdmin` act that requires the emergency plan text to run at least 200 characters and the drill cadence to sit inside the 7-to-90-day window; a policy failing either requirement is rejected with `ERR_SAFETY_POLICY_MISSING`. Approval stamps `approved_at`, increments the policy's `version`, and cascades any previously `APPROVED` policy of the same pod to `SUPERSEDED` — only one approved policy is ever in force per pod. Policy listings can be filtered by `policy_status`, and the cross-pod listing additionally by `pod_id`.

The academic counterpart is the **CurriculumPlan**, created in `DRAFT` by a `PodOperator` with a `plan_name`, the `grade_bands_covered` it serves — a subset of the four grade bands `LOWER_EL`, `UPPER_EL`, `MIDDLE`, and `HIGH` — a `multi_age_grouping` flag declaring whether the plan deliberately mixes bands in shared blocks, and `total_instructional_minutes_per_week`, which must be at least 1200 minutes (twenty instructional hours) across all bands. Submission moves a plan from `DRAFT` to `SUBMITTED` and requires the plan to cover every grade band present among the pod's currently `ENROLLED` seats — a pod with no enrolled seats may submit any plan. A `PodOperator` may also pull a `SUBMITTED` plan back to `DRAFT` for revision.

Plan approval is reserved for a `PlatformAdmin` and enforces two checks, rejected jointly as `ERR_CURRICULUM_INADEQUATE` (HTTP 422): the pod must hold at least one `APPROVED` safety policy, and the plan must clear the 1200-minute weekly floor while covering every grade band present among enrolled seats. Approval stamps `approved_at` and pins `approved_safety_policy_id` to whichever of the pod's `APPROVED` safety policies carries the highest `policy_version` at that moment — a version-locked reference that survives later policy supersession. Approving one plan cascades any previously `APPROVED` plan of the same pod to `SUPERSEDED`, and dissolution does the same; supersession in turn cancels every progress conference still referencing the retired plan in `REQUESTED`, `SCHEDULED`, or `RESCHEDULED` status, moving each to `CANCELLED`. Plan listings can be filtered by `plan_status`, and the cross-pod listing additionally by `pod_id` or `approved_safety_policy_id`. Only `APPROVED` plans may anchor a progress conference.

### 3.3. Licensing Determinations and Zoning Exemption

Before a forming pod may activate, it must clear its jurisdiction's licensing question. A `PodOperator` submits a **LicensingDetermination** naming the `jurisdiction_code` it applies to — mirrored from the host facility site at submission time — and a `submission_kind` of `EXEMPTION_CLAIM` or `FULL_LICENSE`. Submission is allowed only while no other determination for the pod sits in `SUBMITTED` or `UNDER_REVIEW`; it creates the determination in `SUBMITTED` status with a `revision_number` of 0, moves the pod from `FORMING` to `LICENSING_REVIEW`, sets the pod's `posture` to `RESTRICTED` while licensing is in flight, and increments the pod's `version`. Determination listings can be filtered by `determination_status`, and the cross-pod listing additionally by `pod_id`.

A `ComplianceOfficer` begins review, moving the determination from `SUBMITTED` — or, on a resubmitted case, from `RESUBMITTED` — to `UNDER_REVIEW`. The decision call then branches four ways, each driven by the payload's `decision` value. Deciding `EXEMPT_GRANTED` requires the pod's `seat_capacity` to be no more than 10 seats — the exemption eligibility threshold, beyond which full licensure is mandatory — and the host site's `zoning_class` to be one of `RESIDENTIAL_SINGLE`, `RELIGIOUS`, or `AGRICULTURAL`; a pod or site failing either test is rejected with `ERR_EXEMPTION_NOT_ELIGIBLE` (HTTP 422). Deciding `LICENSE_GRANTED` requires the determination's `submission_kind` to be `FULL_LICENSE`. Either grant stamps `decided_at` and cascades the pod from `LICENSING_REVIEW` to `ACTIVE` provided the remaining activation precondition holds: at least one guide assignment in `SCHEDULED` or `ACTIVE` status covering `term_start_date`. Activation recomputes the pod's posture, sets its `compliance_flag` to `COMPLIANT`, and increments its `version`.

The two adverse outcomes both return the pod from `LICENSING_REVIEW` to `FORMING` and increment its `version`. Deciding `LICENSE_REQUIRED` — the exemption denied, a full license now needed — performs that cascade directly. Deciding `DENIED` requires a non-empty `denial_reason` in the payload, performs the same cascade, and additionally marks the pod's `compliance_flag` `AT_RISK`.

Neither adverse outcome is terminal. A `PodOperator` may resubmit a `DENIED` determination by supplying a `revision_number` exactly one greater than the current one, moving it to `RESUBMITTED` with the counter incremented. A `LICENSE_REQUIRED` determination resubmits the same way but must additionally switch `submission_kind` to `FULL_LICENSE`, abandoning the exemption path. A resubmitted determination re-enters review through the same begin-review step. The grant states `EXEMPT_GRANTED` and `LICENSE_GRANTED` are terminal.

### 3.4. Guide Staffing, Assignment Windows, and Ratio Compliance

Guides are the pod's instructional workforce. A `PlatformAdmin` registers a **Guide** with a `full_name`, a contact `email` unique across guides, and a `certification_tier` of `APPRENTICE`, `CERTIFIED`, or `LEAD`. The tier determines a derived `fte_weight`: an apprentice counts as 0.5 full-time-equivalent, while certified and lead guides each count as 1.0. A guide's `guide_status` begins at `CANDIDATE`; a `PlatformAdmin` activates the guide — any background-check clearance required by an assignee pod's safety policy is assumed satisfied for this system's purposes — and may later deactivate the guide to `INACTIVE`, but only while no assignment in `SCHEDULED` or `ACTIVE` status references them.

A `PodOperator` staffs a pod by creating a **GuideAssignment** naming the `guide_id`, an inclusive `window_start_date` and `window_end_date`, the scheduled `weekly_hours` on site — an integer between 4 and 40 inclusive — and an optional `is_primary` flag, defaulting to false, of which exactly one `ACTIVE` assignment per pod may hold the primary designation at any time. Creation enforces, after the posture gate, three checks in order: the window must not overlap any of the same guide's existing windows in `SCHEDULED` or `ACTIVE` status, with overlap measured inclusively at both ends (`ERR_GUIDE_WINDOW_OVERLAP`, HTTP 422); the start date must not fall after the end date and the window must intersect the pod's academic term (`ERR_INVALID_WINDOW`, HTTP 422); and the referenced guide must be `ACTIVE` (`ERR_GUIDE_INACTIVE`, HTTP 422). Assignment listings can be filtered by `assignment_status` or `guide_id`, and the cross-pod listing additionally by `pod_id`.

Assignments age through the logical clock. When the clock reaches a `SCHEDULED` assignment's `window_start_date` while its pod is `ACTIVE`, the assignment becomes `ACTIVE`; when the clock passes an `ACTIVE` assignment's `window_end_date`, it becomes `ENDED`. Both system transitions recompute the pod's compliance flag and increment the assignment's `version`. A `PodOperator` may also terminate an assignment early. Terminating a `SCHEDULED` assignment is permitted whenever the pod is in `DRAFT`, `FORMING`, `LICENSING_REVIEW`, `ACTIVE`, or `SUSPENDED`. Terminating an `ACTIVE` assignment is permitted only from an `ACTIVE` or `SUSPENDED` pod and carries a staffing-floor guard: after the termination, the projected ratio over the pod's remaining `ACTIVE` and `SCHEDULED` assignments must still satisfy `min_guides_required`, unless a replacement assignment is already `SCHEDULED` to start within 7 calendar days. The termination recomputes the pod's compliance flag, and if the ratio is found in violation the pod is automatically suspended — its `status` moves to `SUSPENDED` and its `posture` to `FROZEN` without any separate officer action.

The ratio itself is recomputed whenever a seat enters or leaves `ENROLLED`, whenever an assignment starts, ends, or terminates, and whenever a guide's certification tier changes. Each `ACTIVE` assignment whose window covers the current date contributes its guide's `fte_weight` multiplied by the lesser of 1.0 and the assignment's `weekly_hours` divided by 30 — weekly hours are capped at thirty for ratio purposes. Those contributions sum to a total FTE, which is divided by the pod's `enrolled_count`, with an empty pod treated as a single seat to keep the divisor defined. A ratio of at least one tenth — one FTE per ten students — is `COMPLIANT`; a ratio of at least one fifteenth but below one tenth is `AT_RISK`; anything strictly below one fifteenth is `VIOLATION` and automatically suspends the pod. Boundaries are exact at four decimal places: a ratio of precisely 0.1 is `COMPLIANT`, while a hair below it is `AT_RISK`; a ratio of precisely one fifteenth is `AT_RISK`, and only a value strictly beneath it is `VIOLATION`. Some jurisdictions evaluate on an alternate headcount convention in which every guide counts as 1.0 regardless of tier, producing a different flag whenever apprentices are present.

Beyond the automatic suspension on ratio violation, a `ComplianceOfficer` may suspend an `ACTIVE` pod whenever its `compliance_flag` reads `AT_RISK` or `VIOLATION`; suspension sets `posture` to `FROZEN`, leaves every seat record intact, and blocks enrollment actions while frozen. Reinstatement by a `ComplianceOfficer` returns a `SUSPENDED` pod to `ACTIVE` once re-evaluation finds the flag `COMPLIANT`, recomputing posture and incrementing the pod's `version`.

### 3.5. Families, Students, and ESA Voucher Accounts

A `Registrar` onboards a household as a **Family** with a `family_name`, a `primary_contact_email` unique across families and well-formed per RFC 5322, and a two-letter `billing_address_state` that determines ESA eligibility. The family's `family_status` begins at `PROSPECT`, advances to `ACTIVE` automatically the moment any of its students' seats first reaches `ENROLLED`, and falls to `INACTIVE` when a dissolution finalization leaves the family with zero enrolled students.

Each **Student** is registered under a family by a `Registrar` with a `legal_first_name`, a `legal_last_name`, a `date_of_birth`, and an optional `esa_account_id` linking a voucher account. The student's `grade_band` — one of `LOWER_EL`, `UPPER_EL`, `MIDDLE`, or `HIGH` — is derived from the date of birth against the pod's academic year and recomputed on enrollment. The `student_status` lifecycle begins at `APPLICANT` and proceeds through `ENROLLED`, `WITHDRAWN`, and `GRADUATED`. If `esa_account_id` is supplied — at registration or in a later student update — it must reference a voucher account owned by that same student; a cross-student reference is rejected with `ERR_VOUCHER_STUDENT_MISMATCH` (HTTP 422). The student directory can be filtered by `family_id`, `esa_account_id`, or `student_status`.

A `Registrar` opens a **VoucherAccount** for a student with a state `program_code` such as `AZ-ESA` or `FL-FES` and an `awarded_annual_cents` total award, a strictly positive integer. The account lives on two independent state dimensions. Its `verification_status` begins at `PENDING_VERIFICATION` and is settled by a `ComplianceOfficer`: verification requires the student's `date_of_birth` to yield an eligible grade band for the program's jurisdiction and moves the account to `VERIFIED`, recomputing `accepted_by_pod`; rejection moves it to `REJECTED`. Its `funding_status` begins at `FUNDED` and tracks the `disbursable_balance_cents` that remains available for disbursement, as detailed in §3.7. The derived `accepted_by_pod` flag reads true only when the account is `VERIFIED`, its funding is `FUNDED` or `PARTIALLY_DEPLETED`, and the pod in question is `ACTIVE` — it starts false. Voucher listings can be filtered by `student_id`, `verification_status`, or `funding_status`. After a dissolution, a `PlatformAdmin` releases a `FROZEN` account once the owning pod stands `DISSOLVED` and every refund claim for the seat has been decided; the release returns the account to `FUNDED` and immediately recomputes the funding status from the balance thresholds.

### 3.6. Seats, Enrollment, and Mid-Year Proration

A seat is the join between a student and a pod. A `Registrar` reserves one by naming the `student_id` and the intended `enrolled_on` first instructional date, creating the **Seat** in `RESERVED` status with `reserved_at` stamped. Reservation enforces, after the posture gate, seat uniqueness — at most one seat in `RESERVED` or `ENROLLED` may exist per student per pod, violations rejected with `ERR_DUPLICATE_SEAT` (HTTP 422) — and the term window: `enrolled_on` must fall within the pod's `term_start_date` and `term_end_date`, inclusive of both, with out-of-term dates rejected as `ERR_ENROLLMENT_OUT_OF_TERM` (HTTP 422). Mid-year enrollment is expressly permitted; proration applies. Seat listings can be filtered by `seat_status` or `student_id`, and the cross-pod listing additionally by `pod_id`.

Enrollment — the family's act of moving a seat from `RESERVED` to `ENROLLED` — is the most heavily gated transition in the system. The pod must be `ACTIVE`; its `posture` must be `OPEN` or `RESTRICTED`; capacity must remain, with any enrollment that would push `enrolled_count` past `seat_capacity` rejected as `ERR_CAPACITY_FULL` (HTTP 422); the student must still be an `APPLICANT`; the seat's `enrolled_on` is re-validated against the term window at this step exactly as at reservation, with out-of-term dates again rejected as `ERR_ENROLLMENT_OUT_OF_TERM`; if the student carries an `esa_account_id`, the voucher account's `accepted_by_pod` must read true; and the pod must hold at least one guide assignment in `SCHEDULED` or `ACTIVE` covering the seat's `enrolled_on` date. The request must also carry `expected_pod_version` under the optimistic-concurrency rule of §2.9. On success the pod's `enrolled_count` increments, the student becomes `ENROLLED`, the family becomes `ACTIVE`, the seat pins `tuition_basis_cents` as a snapshot of the pod's `tuition_full_year_cents` at that instant, the seat's `prorated_due_cents` is computed as below, and the pod's posture, compliance flag, and version are all recomputed alongside the seat's own `version`.

Proration honors whichever convention the pod is configured for. Under the daily convention, the amount owed for a mid-year start is the pod's full-year tuition multiplied by the seat's enrolled days — the calendar-day count from `enrolled_on` through `term_end_date`, inclusive of both — divided by the academic year's total instructional days, counted from `term_start_date` through `term_end_date` and likewise inclusive of both, with the quotient rounded half up to a whole cent. Under the weekly convention, enrolled days are divided by seven and rounded up to a whole week count, total days are divided by seven and rounded up the same way, and the amount owed is the full-year tuition multiplied by enrolled weeks and divided by total weeks, again rounded half up to a whole cent; the two conventions can differ by up to six days' worth of tuition on the same mid-year start. Each pod is bound to exactly one convention for enrollment proration.

Withdrawal — a family moving a seat from `ENROLLED` to `WITHDRAWN` — is permitted while the pod is `ACTIVE` or `SUSPENDED`, and the payload's `withdrawn_on` date must not precede the current logical-clock date. The transition stamps `withdrawn_on`, moves the student to `WITHDRAWN`, decrements the pod's `enrolled_count`, recomputes the compliance flag, creates a refund claim of kind `WITHDRAWAL` priced by the sliding-scale rule of §3.9, and reconciles the seat's open invoices: every invoice still in `DRAFT` or `ISSUED` for the seat moves to `WRITTEN_OFF` when its total exceeds the recomputed prorated amount due, and otherwise has its `PARTIALLY_PAID` or `PAID` standing recomputed. A withdrawn seat whose pod later finalizes dissolution is released by the system from `WITHDRAWN` to `RELEASED`.

### 3.7. Invoicing, Payments, and Voucher Disbursement

Billing runs through the **TuitionInvoice**. A `PodOperator` drafts an invoice for a seat with a `billing_period_start`, a `billing_period_end` that must not precede it, a `due_date` that must not precede the period end — violations rejected as `ERR_INVALID_INVOICE_PERIOD` (HTTP 422) — and a `line_items` array whose entries each carry a `description`, a `quantity`, a `unit_amount_cents`, and a `kind` of `TUITION`, `FEE`, or `CREDIT`. The invoice begins in `DRAFT` with `paid_cents` at zero. Invoice listings can be filtered by `invoice_status`, and the cross-seat listing additionally by `seat_id`.

Issuance is a `PodOperator` action requiring the seat to be `ENROLLED`, and it fixes the invoice's money fields in a pinned evaluation order. First, `subtotal_cents` is computed per line: each line's extended amount is its `quantity` multiplied by its `unit_amount_cents`, rounded half up to a whole cent, and the subtotal is the sum of those rounded line amounts. Second, `admin_fee_cents` is computed as a percentage of that subtotal, tiered by the pod's `enrolled_count` at the moment of issuance — not by the student's own seat count: four percent when the pod has at most eight enrolled seats, three percent from nine through sixteen, two percent from seventeen through twenty-four, and one and a half percent at twenty-five or more, with the fee itself rounded half up to a whole cent. Boundary counts belong to the higher-fee tier: exactly eight seats bills four percent, exactly sixteen bills three, exactly twenty-four bills two. Finally, `total_cents` is the subtotal plus the fee. This per-line-then-sum order is contractual: summing raw extended amounts and rounding once at the end produces different cents for fractional quantities and is not permitted. Editing the line items of a `DRAFT` invoice re-runs the same computation.

Families and registrars post a **Payment** against an invoice by naming a `source_kind` of `FAMILY`, `VOUCHER`, `SCHOLARSHIP`, or `REFUND_REVERSAL`, a strictly positive `amount_cents`, and — required exactly when the source is `VOUCHER` — a `voucher_account_id`; the payment also denormalizes its `seat_id` for reporting. A payment starts `PENDING` with `paid_at` stamped when recorded. Two fiscal guards apply both when the payment is posted and when it is later cleared, evaluated in this order: first the voucher-funds check — a voucher-funded payment requires its account to be `VERIFIED`, the `disbursable_balance_cents` to cover the full `amount_cents`, and the funding status to be anything but `FROZEN`, with any failure rejected as `ERR_INSUFFICIENT_VOUCHER_FUNDS` (HTTP 422) — and then the overpayment ceiling: for family- and scholarship-funded payments, cumulative cleared payments against the invoice may not exceed its `total_cents`, violations rejected as `ERR_OVERPAYMENT` (HTTP 422). A `PodOperator` settles a pending payment by clearing it. A cleared payment recomputes the invoice's `paid_cents` — the sum of `CLEARED` payments' amounts — and moves an `ISSUED` invoice to `PARTIALLY_PAID` when some but not all of the total is covered, directly to `PAID` when a single payment covers the full balance in one shot, and a `PARTIALLY_PAID` invoice to `PAID` once cumulative cleared payments reach the total; the seat's own `paid_cents` is recomputed alongside. A `PENDING` payment may instead be failed, ending at `FAILED`. Only `CLEARED` payments count toward any `paid_cents` figure.

Voucher disbursement rebalances the account the moment a voucher payment clears. The payment amount is subtracted from `disbursable_balance_cents`, and the funding status is reclassified against the full `awarded_annual_cents`: a remaining balance of at least half the annual award keeps the account `FUNDED` — the half-award boundary is inclusive; a positive balance below half moves it to `PARTIALLY_DEPLETED`; a balance of exactly zero marks it `DEPLETED`. Programs on a monthly-release schedule instead cap the disbursable balance at one tenth of the annual award per month and apply the same thresholds against that monthly cap, which shifts the `FUNDED` boundary for identical balances. A disbursement that would overdraw the balance is rejected outright with `ERR_INSUFFICIENT_VOUCHER_FUNDS`.

Two terminal adjustments close the loop. An invoice in `ISSUED` or `OVERDUE` may be written off to `WRITTEN_OFF` by a `PodOperator` only when its seat is `WITHDRAWN` and its `paid_cents` is exactly zero — an invoice carrying any cleared payment must be refunded rather than written off, and the attempt is rejected with `ERR_INVOICE_HAS_PAYMENTS` (HTTP 422). And a `PlatformAdmin` may reverse a `CLEARED` payment when the linked seat is `WITHDRAWN` or a refund claim in `APPROVED` or `PAID` exists for it; reversal moves the payment to `REVERSED`, decrements the invoice's and seat's `paid_cents`, and — for voucher-sourced payments — restores the amount to the account's `disbursable_balance_cents`. Separately, when the logical clock passes an invoice's `due_date` with `paid_cents` still short of `total_cents`, the invoice lapses from `ISSUED` or `PARTIALLY_PAID` to `OVERDUE`; a later payment covering the full balance still settles an `OVERDUE` invoice to `PAID`. Payment listings can be filtered by `invoice_id`, `seat_id`, `voucher_account_id`, `payment_status`, or `source_kind`.

### 3.8. Progress Conferencing

Each enrolled seat conferences against an approved curriculum plan. A family member or a guide requests a **ProgressConference** by naming the `seat_id`, the `curriculum_plan_id`, and a `scheduled_start` and `scheduled_end` window. The referenced plan must be `APPROVED` and belong to the same pod — otherwise `ERR_PLAN_NOT_APPROVED` (HTTP 422). The window must open strictly before it closes and both endpoints must lie in the future relative to the logical clock — otherwise `ERR_INVALID_CONFERENCE_WINDOW` (HTTP 422). And the guide's calendar must be clear: no other conference in `REQUESTED`, `SCHEDULED`, or `RESCHEDULED` status for the same guide may overlap the half-open window from `scheduled_start` up to but not including `scheduled_end` — otherwise `ERR_CONFERENCE_OVERLAP` (HTTP 422). A new conference begins in `REQUESTED` with `cycle_count` at zero. Conference listings can be filtered by `conference_status` or `seat_id`, and the cross-pod listing additionally by `pod_id` or `curriculum_plan_id`.

Scheduling is the guide's act and moves a conference from `REQUESTED` — or from `RESCHEDULED`, under identical preconditions — to `SCHEDULED`: the pod must be `ACTIVE`, the seat `ENROLLED`, the plan `APPROVED`, and the overlap rule above must hold. From `SCHEDULED` the guide either completes the conference, which requires a non-empty `notes_summary` and lands at `COMPLETED`, or marks a no-show once the logical clock has reached `scheduled_end`, landing at `NO_SHOW`.

A no-show is recoverable by the family: rescheduling moves the conference from `NO_SHOW` to `RESCHEDULED` and increments `cycle_count`, but only while fewer than three reschedule cycles have been consumed — a third rescheduling attempt is rejected with `ERR_CONFERENCE_CYCLE_LIMIT` (HTTP 422). The family may also cancel outright from `REQUESTED`, `SCHEDULED`, or `RESCHEDULED`, ending at `CANCELLED`. `COMPLETED` and `CANCELLED` are terminal. Recall from §3.2 that superseding a curriculum plan cascades cancellation into every conference still referencing it in `REQUESTED`, `SCHEDULED`, or `RESCHEDULED`.

### 3.9. Withdrawal Refunds, Claims Adjudication, and Dissolution

Withdrawal pricing follows a sliding scale over the unearned portion of what a seat has paid. The seat's enrolled days are counted from `enrolled_on` through `withdrawn_on`, inclusive of both. The earned tuition is the prorated amount measured over exactly that span — always under the daily convention, whatever the pod's enrollment-proration setting — that is, the full-year tuition multiplied by those enrolled days and divided by the academic year's total instructional days, rounded half up to a whole cent. The unearned portion is the amount by which the seat's cleared payments exceed that earned figure, floored at zero. The refund percentage then tiers on enrolled days: no more than fourteen days enrolled refunds the unearned portion in full; more than fourteen and no more than forty-five refunds three quarters; more than forty-five and no more than ninety refunds one half; beyond ninety days nothing is refundable. Boundary days resolve to the more favorable tier — exactly fourteen days refunds in full, exactly forty-five refunds three quarters, exactly ninety refunds one half, and the ninety-first day onward refunds nothing. The claimed refund is the unearned portion multiplied by the tier percentage, rounded half up to a whole cent. Pods configured with a flat-fee withdrawal policy ignore the day tiers entirely and refund the cleared payments minus a fixed administrative fee, floored at zero.

Every refund runs through a **RefundClaim**. Claims of kind `WITHDRAWAL` are created automatically by the withdrawal transition and claims of kind `DISSOLUTION` by the dissolution cascade; a family member or `Registrar` may additionally file an ad-hoc claim — an `OVERPAYMENT` claim, for instance — by naming the `seat_id` and `claim_kind`, provided no non-terminal claim already exists for the same seat and kind, with duplicates rejected as `ERR_CLAIM_ALREADY_EXISTS` (HTTP 422). The claim records its computed `claimed_amount_cents`, the filer's identity as `filed_by_user_id` taken from `X-User-ID`, and begins in `FILED`. Claim listings can be filtered by `claim_status`, `claim_kind`, or `seat_id`, and the cross-pod listing additionally by `pod_id`.

Adjudication is a `Registrar` workflow guarded by segregation of duties. Beginning review moves a claim from `FILED` to `UNDER_REVIEW`. The decision then enforces, in order, the reviewer-versus-filer separation — the reviewer's `X-User-ID` must differ from `filed_by_user_id`, or the decision is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 422) — and the amount bounds. A decision of `APPROVED` requires the payload's `approved_amount_cents` to be no greater than `claimed_amount_cents` and no less than zero, violations rejected as `ERR_REFUND_EXCEEDS_CLAIM` (HTTP 422); it records `approved_amount_cents` on the claim, stamps `reviewed_by_user_id` with the reviewer's identity, and sets the seat's `refund_due_cents` to the approved amount. A decision of `DENIED` applies the same segregation check, stamps `reviewed_by_user_id`, and zeroes the seat's `refund_due_cents`.

Disbursement of an `APPROVED` claim is a `PlatformAdmin` act that moves it to `PAID`. The disbursement posts a `Payment` of `source_kind` `REFUND_REVERSAL` for the approved amount against a synthesized zero-balance invoice scoped to the seat, closing the loop on the original tuition invoices. Where the seat's student holds a voucher account and the claim is a `DISSOLUTION` claim, the disbursement routes through the voucher release: the account's funding must not be `FROZEN` at the moment of disbursement, or the disbursement triggers the release first and then posts.

Dissolution itself begins with a `PodOperator` calling for dissolution of an `ACTIVE` or `SUSPENDED` pod, supplying the `dissolution_reason` rationale and the `expected_pod_version` guard of §2.9. From `ACTIVE`, the pod must hold at least one `ENROLLED` seat; a pod with no enrolled seats instead follows the zero-seat branch, in which the operator moves a `DRAFT` pod directly to `DISSOLVED` through the same dissolution capability. A dissolution request against a pod whose current status permits neither the cascade nor that zero-seat branch is rejected with `ERR_NO_ENROLLED_SEATS_FOR_DISSOLUTION` (HTTP 422). From `SUSPENDED`, the same cascade runs with the same version guard.

Entering `DISSOLVING` records the `dissolution_reason`, sets the pod's `posture` to `CLOSED`, and fires a five-fold cascade in a single request: every `ENROLLED` seat moves to `WITHDRAWN` with `withdrawn_on` set to the current date; every guide assignment in `SCHEDULED` or `ACTIVE` moves to `TERMINATED_EARLY`; every `APPROVED` curriculum plan moves to `SUPERSEDED` — carrying the conference cancellations of §3.8 with it; a refund claim of kind `DISSOLUTION` is created for each withdrawn seat; and every voucher account linked to a withdrawn student is frozen to `FROZEN`, held pending refund reconciliation. The pod's `version` increments.

Each dissolution claim's `claimed_amount_cents` is priced from a refund pool. The gross collected is the sum of `paid_cents` across the seats the cascade withdrew. The earned-through-dissolution figure is the sum, over those same seats, of each seat's prorated tuition measured from its `enrolled_on` through the pod's `dissolved_at` date under the daily convention. The pool is the excess of gross collected over earned, floored at zero. Distribution follows a fixed waterfall, each bucket filling before overflow reaches the next: first, voucher-program reimbursements, shared pro-rata by voucher-paid cents and capped at the total voucher-paid amount; then family direct-paid refunds, shared pro-rata by family-paid cents; finally scholarship fund returns. Within a bucket, each claimant's share is the remaining pool multiplied by the claimant's paid fraction of the bucket's total, rounded half up to a whole cent; whatever rounding remainder is left in the pool goes to the claimant whose seat carries the earliest `created_at` — ties break on creation time, never on identifier.

Finalizing dissolution is the `PlatformAdmin`'s last act and is permitted only once every dissolution claim for the pod stands `APPROVED`, `PAID`, or `DENIED`, and every voucher account the cascade froze has been released from `FROZEN`. Finalization stamps `dissolved_at` with the current UTC instant, keeps the pod's `posture` at `CLOSED`, moves every `WITHDRAWN` seat to `RELEASED`, moves every family left with zero enrolled students to `INACTIVE`, increments the pod's `version`, and lands the pod in the terminal `DISSOLVED` state.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify, transition, or act upon an existing resource return `200 OK`. Request payloads, derived-field behavior, cascades, and failure modes are defined by the workflow narratives of §3 rather than restated per endpoint here.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | PlatformAdmin |
| POST | `/facility-sites` | Create a facility site | PlatformAdmin |
| GET | `/facility-sites/{id}` | Fetch a site | PlatformAdmin, PodOperator, ComplianceOfficer |
| GET | `/facility-sites` | List sites | PlatformAdmin, PodOperator, ComplianceOfficer |
| POST | `/facility-sites/{id}/archive` | Archive a site (soft delete) | PlatformAdmin |
| POST | `/facility-sites/{id}/release` | Release a leased site back to available | PlatformAdmin |
| POST | `/pods` | Create a new pod in `DRAFT` status | PodOperator |
| GET | `/pods/{id}` | Fetch a pod | PlatformAdmin, PodOperator, ComplianceOfficer, Guide, Family, Registrar |
| GET | `/pods` | List pods | PlatformAdmin, PodOperator, ComplianceOfficer, Guide, Family, Registrar |
| POST | `/pods/{id}/open-enrollment` | Transition pod `DRAFT → FORMING` | PodOperator |
| POST | `/pods/{id}/revert-to-draft` | Transition pod `FORMING → DRAFT` | PodOperator |
| POST | `/pods/{id}/suspend` | Suspend a pod (`ACTIVE → SUSPENDED`) | ComplianceOfficer |
| POST | `/pods/{id}/reinstate` | Reinstate a suspended pod (`SUSPENDED → ACTIVE`) | ComplianceOfficer |
| POST | `/pods/{id}/dissolve` | Initiate pod dissolution with full cascade | PodOperator |
| POST | `/pods/{id}/finalize-dissolution` | Finalize dissolution once all refund claims are decided | PlatformAdmin |
| POST | `/pods/{id}/safety-policies` | Create a safety policy for a pod (`DRAFT`) | PodOperator |
| GET | `/pods/{id}/safety-policies` | List safety policies for a pod | PlatformAdmin, PodOperator, ComplianceOfficer |
| GET | `/safety-policies/{id}` | Fetch a single safety policy | PlatformAdmin, PodOperator, ComplianceOfficer |
| GET | `/safety-policies` | List safety policies across pods | PlatformAdmin, PodOperator, ComplianceOfficer |
| POST | `/pods/{id}/safety-policies/{policy_id}/approve` | Approve a safety policy, superseding the prior approved one | PlatformAdmin |
| POST | `/pods/{id}/curriculum-plans` | Create a curriculum plan (`DRAFT`) | PodOperator |
| GET | `/pods/{id}/curriculum-plans` | List curriculum plans for a pod | PlatformAdmin, PodOperator, ComplianceOfficer, Guide |
| GET | `/curriculum-plans/{id}` | Fetch a single curriculum plan | PlatformAdmin, PodOperator, ComplianceOfficer, Guide |
| GET | `/curriculum-plans` | List curriculum plans across pods | PlatformAdmin, PodOperator, ComplianceOfficer |
| POST | `/pods/{id}/curriculum-plans/{plan_id}/submit` | Submit a plan for approval | PodOperator |
| POST | `/pods/{id}/curriculum-plans/{plan_id}/approve` | Approve a plan, pinning the current approved safety policy | PlatformAdmin |
| POST | `/pods/{id}/curriculum-plans/{plan_id}/revise` | Send a `SUBMITTED` plan back to `DRAFT` | PodOperator |
| POST | `/pods/{id}/licensing-determinations` | Submit a licensing determination; pod `FORMING → LICENSING_REVIEW` | PodOperator |
| GET | `/pods/{id}/licensing-determinations` | List determinations for a pod | PlatformAdmin, PodOperator, ComplianceOfficer |
| GET | `/licensing-determinations/{id}` | Fetch a single licensing determination | PlatformAdmin, PodOperator, ComplianceOfficer |
| GET | `/licensing-determinations` | List determinations across pods | PlatformAdmin, PodOperator, ComplianceOfficer |
| POST | `/pods/{id}/licensing-determinations/{det_id}/begin-review` | Begin review (`SUBMITTED` or `RESUBMITTED → UNDER_REVIEW`) | ComplianceOfficer |
| POST | `/pods/{id}/licensing-determinations/{det_id}/decide` | Issue a decision (`EXEMPT_GRANTED` / `LICENSE_GRANTED` / `LICENSE_REQUIRED` / `DENIED`) | ComplianceOfficer |
| POST | `/pods/{id}/licensing-determinations/{det_id}/resubmit` | Resubmit a `DENIED` or `LICENSE_REQUIRED` determination | PodOperator |
| POST | `/guides` | Register a guide (`CANDIDATE`) | PlatformAdmin |
| GET | `/guides/{id}` | Fetch a guide | PlatformAdmin, PodOperator, ComplianceOfficer |
| POST | `/guides/{id}/activate` | Activate a guide | PlatformAdmin |
| POST | `/guides/{id}/deactivate` | Deactivate a guide | PlatformAdmin |
| POST | `/pods/{id}/guide-assignments` | Schedule a guide assignment window | PodOperator |
| GET | `/pods/{id}/guide-assignments` | List assignments for a pod | PlatformAdmin, PodOperator, ComplianceOfficer, Guide |
| GET | `/guide-assignments/{id}` | Fetch a single guide assignment | PlatformAdmin, PodOperator, ComplianceOfficer, Guide |
| GET | `/guide-assignments` | List assignments across pods | PlatformAdmin, PodOperator, ComplianceOfficer |
| POST | `/pods/{id}/guide-assignments/{asg_id}/terminate` | Terminate an assignment early | PodOperator |
| POST | `/families` | Register a family (`PROSPECT`) | Registrar |
| GET | `/families/{id}` | Fetch a family | PlatformAdmin, Registrar, Family |
| GET | `/families/{id}/students` | List students of a family | PlatformAdmin, Registrar, Family |
| POST | `/families/{id}/students` | Register a student under a family (`APPLICANT`) | Registrar |
| GET | `/students/{id}` | Fetch a student | PlatformAdmin, Registrar, Family |
| GET | `/students` | List students across families | PlatformAdmin, Registrar, ComplianceOfficer |
| POST | `/students/{id}/voucher-accounts` | Open a voucher account for a student | Registrar |
| GET | `/voucher-accounts/{id}` | Fetch a voucher account | PlatformAdmin, Registrar, ComplianceOfficer |
| GET | `/voucher-accounts` | List voucher accounts | PlatformAdmin, Registrar, ComplianceOfficer |
| POST | `/voucher-accounts/{id}/verify` | Verify a voucher account | ComplianceOfficer |
| POST | `/voucher-accounts/{id}/reject` | Reject a voucher account | ComplianceOfficer |
| POST | `/voucher-accounts/{id}/release` | Release a `FROZEN` voucher account after dissolution reconciliation | PlatformAdmin |
| POST | `/pods/{id}/seats` | Reserve a seat for a student in a pod | Registrar |
| GET | `/pods/{id}/seats` | List seats of a pod | PlatformAdmin, PodOperator, ComplianceOfficer, Registrar, Guide, Family |
| GET | `/seats/{id}` | Fetch a seat | PlatformAdmin, PodOperator, ComplianceOfficer, Registrar, Family |
| GET | `/seats` | List seats across pods | PlatformAdmin, PodOperator, ComplianceOfficer, Registrar |
| POST | `/pods/{id}/seats/{seat_id}/enroll` | Enroll a reserved seat; OCC-guarded on the pod's version | Family |
| POST | `/pods/{id}/seats/{seat_id}/withdraw` | Withdraw an enrolled seat, creating a refund claim | Family |
| POST | `/pods/{id}/seats/{seat_id}/invoices` | Create a draft invoice for a seat | PodOperator |
| GET | `/pods/{id}/seats/{seat_id}/invoices` | List invoices for a seat | PlatformAdmin, PodOperator, Registrar, Family |
| GET | `/invoices/{id}` | Fetch an invoice | PlatformAdmin, PodOperator, Registrar, Family |
| GET | `/invoices` | List invoices across seats | PlatformAdmin, PodOperator, Registrar |
| POST | `/pods/{id}/seats/{seat_id}/invoices/{invoice_id}/issue` | Issue a draft invoice, computing subtotal, admin fee, and total | PodOperator |
| POST | `/pods/{id}/seats/{seat_id}/invoices/{invoice_id}/write-off` | Write off an unpaid invoice on a withdrawn seat | PodOperator |
| POST | `/pods/{id}/seats/{seat_id}/invoices/{invoice_id}/payments` | Post a payment against an invoice (`PENDING`) | Family, Registrar |
| GET | `/payments/{id}` | Fetch a payment | PlatformAdmin, PodOperator, Registrar, Family |
| GET | `/payments` | List payments | PlatformAdmin, PodOperator, Registrar |
| GET | `/pods/{id}/seats/{seat_id}/invoices/{invoice_id}/payments` | List payments on an invoice | PlatformAdmin, PodOperator, Registrar, Family |
| POST | `/payments/{id}/clear` | Clear a `PENDING` payment | PodOperator |
| POST | `/payments/{id}/fail` | Fail a `PENDING` payment | PodOperator |
| POST | `/payments/{id}/reverse` | Reverse a `CLEARED` payment | PlatformAdmin |
| POST | `/pods/{id}/progress-conferences` | Request a progress conference | Family, Guide |
| GET | `/pods/{id}/progress-conferences` | List conferences for a pod | PlatformAdmin, PodOperator, ComplianceOfficer, Guide, Family |
| GET | `/progress-conferences/{id}` | Fetch a single progress conference | PlatformAdmin, PodOperator, ComplianceOfficer, Guide, Family |
| GET | `/progress-conferences` | List conferences across pods | PlatformAdmin, PodOperator, ComplianceOfficer |
| POST | `/pods/{id}/progress-conferences/{conf_id}/schedule` | Guide schedules a conference (`REQUESTED` or `RESCHEDULED → SCHEDULED`) | Guide |
| POST | `/pods/{id}/progress-conferences/{conf_id}/complete` | Complete a conference with notes | Guide |
| POST | `/pods/{id}/progress-conferences/{conf_id}/mark-no-show` | Mark a scheduled conference as `NO_SHOW` | Guide |
| POST | `/pods/{id}/progress-conferences/{conf_id}/reschedule` | Family requests reschedule from `NO_SHOW` | Family |
| POST | `/pods/{id}/progress-conferences/{conf_id}/cancel` | Cancel a conference | Family |
| POST | `/pods/{id}/refund-claims` | File an ad-hoc refund claim (e.g., `OVERPAYMENT`) | Family, Registrar |
| GET | `/pods/{id}/refund-claims` | List refund claims for a pod | PlatformAdmin, PodOperator, Registrar, Family |
| GET | `/refund-claims/{id}` | Fetch a refund claim | PlatformAdmin, PodOperator, Registrar, Family |
| GET | `/refund-claims` | List refund claims across pods | PlatformAdmin, PodOperator, Registrar, ComplianceOfficer |
| POST | `/pods/{id}/refund-claims/{claim_id}/begin-review` | Begin review of a claim | Registrar |
| POST | `/pods/{id}/refund-claims/{claim_id}/decide` | Approve or deny a claim, with segregation of duties enforced | Registrar |
| POST | `/pods/{id}/refund-claims/{claim_id}/disburse` | Disburse an approved claim | PlatformAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in §2 and §3 where the guarded workflow is described.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_POD_FROZEN` | 409 Conflict |
| `ERR_SAFETY_POLICY_MISSING` | 422 Unprocessable Entity |
| `ERR_EXEMPTION_NOT_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_SEGREGATION_OF_DUTIES` | 422 Unprocessable Entity |
| `ERR_GUIDE_WINDOW_OVERLAP` | 422 Unprocessable Entity |
| `ERR_CONFERENCE_OVERLAP` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_SEAT` | 422 Unprocessable Entity |
| `ERR_CAPACITY_FULL` | 422 Unprocessable Entity |
| `ERR_CURRICULUM_INADEQUATE` | 422 Unprocessable Entity |
| `ERR_ENROLLMENT_OUT_OF_TERM` | 422 Unprocessable Entity |
| `ERR_INVALID_WINDOW` | 422 Unprocessable Entity |
| `ERR_INVALID_CONFERENCE_WINDOW` | 422 Unprocessable Entity |
| `ERR_INVALID_INVOICE_PERIOD` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_VOUCHER_FUNDS` | 422 Unprocessable Entity |
| `ERR_OVERPAYMENT` | 422 Unprocessable Entity |
| `ERR_REFUND_EXCEEDS_CLAIM` | 422 Unprocessable Entity |
| `ERR_INVOICE_HAS_PAYMENTS` | 422 Unprocessable Entity |
| `ERR_VOUCHER_STUDENT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_PLAN_NOT_APPROVED` | 422 Unprocessable Entity |
| `ERR_GUIDE_INACTIVE` | 422 Unprocessable Entity |
| `ERR_CONFERENCE_CYCLE_LIMIT` | 422 Unprocessable Entity |
| `ERR_CLAIM_ALREADY_EXISTS` | 422 Unprocessable Entity |
| `ERR_NO_ENROLLED_SEATS_FOR_DISSOLUTION` | 422 Unprocessable Entity |
