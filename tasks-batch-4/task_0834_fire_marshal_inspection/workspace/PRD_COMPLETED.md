# Fire Marshal Inspection API — Product Requirements Document

## 1. Introduction

The Fire Marshal Inspection API is the system of record for a fire jurisdiction's plan-review and inspection program. It governs the full arc of fire-code compliance for a building: registering a property and deriving its life-safety metrics, taking a construction or occupancy permit application through multi-discipline plan review, assessing and collecting permit fees, issuing and revoking permits, scheduling periodic and complaint inspections, recording violations and driving them to abatement, and posting the certificate-of-occupancy and placard status that tells the public whether a building may be used.

The domain is deliberately cross-cutting: a single field action — recording an inspection result, letting an abatement deadline lapse, revoking a permit — can ripple through several entities at once, suspending a certificate here, escalating a violation there, and adjusting a jurisdiction's collected-fee totals. The API is built for civil servants in distinct roles (applicants, plan reviewers, field inspectors, and the fire marshal) who each own a slice of the workflow, and it is expected to hold those cascades consistent at every step. This document specifies the entities, their state machines, the fee and life-safety calculations, the validation rules and their precedence, and the endpoint and error contracts that together define the system.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must be authenticated by two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is missing, or `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`. The system recognizes exactly four roles: `Applicant`, `PlanReviewer`, `Inspector`, and `FireMarshal`. When an authenticated user attempts an operation their role is not permitted to perform, the request is rejected with `ERR_UNAUTHORIZED`.

All four roles carry an **opaque** identity. When `X-User-Role` is `Applicant`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity's `id`; the server does not resolve it to a stored record. It does, however, participate in ownership enforcement: when an applicant opens a permit application they supply an `applicant_user_id`, and for the applicant-owned actions (submitting an application, paying a fee, and resubmitting corrections) the server compares the caller's `X-User-ID` against the target application's stored `applicant_user_id`. A mismatch is rejected with `ERR_NOT_OWNER`. When `X-User-Role` is `PlanReviewer`, `Inspector`, or `FireMarshal`, `X-User-ID` is likewise an opaque operator identifier not compared to any entity's `id`; the server may log it but does not treat it as a foreign key. Beyond the applicant-ownership check, authorization is purely role-based per the endpoint table in Section 4.

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

List endpoints are paginated through two query parameters. The `limit` parameter bounds the number of items returned; when omitted it defaults to 10, and it is constrained to a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Out-of-range and malformed values are coerced rather than rejected: a `limit` below 1 is raised to 1 and one above 100 is lowered to 100, a negative `offset` is treated as 0, and a non-integer `limit` or `offset` falls back to its default (10 and 0 respectively).

Unless a specific endpoint states otherwise, list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order, with ties broken by creation (insertion) order so the ordering is deterministic.

Every list response carries the pagination bookkeeping in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Logical Clock

Every entity in this system — `Property`, `PermitApplication`, `PlanReview`, `Permit`, `Inspection`, `Violation`, `AbatementOrder`, `Certificate`, `Hydrant`, and `FlowTest` — carries the standard system-managed fields:

- `id`: a server-minted unique identifier formatted as a UUID, with no type prefix.
- `created_at`: an ISO 8601 UTC timestamp (three fractional digits) recording when the resource was created.
- `updated_at`: an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version`: an integer that starts at 1 on creation and increments by one on every mutation of the resource. It is the basis for optimistic concurrency control described in Section 2.8.

Whenever a rule in this document says a field is changed, the owning resource's `updated_at` is refreshed and its `version` is incremented as part of that same mutation, including mutations the server performs on its own (cascades and sweeps) without a direct client request on that resource.

Time in this system is a **logical clock**, not wall-clock time. On server startup the clock reads exactly `2026-03-01T00:00:00Z` and stays there until explicitly moved; it never falls back to real time. The fire marshal advances the clock by supplying a `to_iso8601` instant to the clock-setting capability, after which the clock reads that value. All server-stamped timestamps — a permit's `issued_at`, an inspection's `result_recorded_at`, an abatement order's `issued_at`, a violation's `abated_at`, and every deadline and expiry derived from them — are read from this logical clock. The record-keeping timestamps `created_at` and `updated_at` (and the envelope's `api_request_timestamp`) are the exception: they are stamped from the server's real wall-clock time, not from this logical clock.

### 2.5. Numeric Precision and Rounding Discipline

Monetary amounts are integers denominated in whole cents. Wherever a fee component is computed from a rate, the intermediate value is rounded to whole cents using the **round-half-up** convention (a value exactly at the half-cent rounds up to the next whole cent). The permit-fee calculation in Section 3.3 pins the order of operations: each rate-derived component is rounded to whole cents **first**, and only the already-rounded components are summed. Summing the raw products and rounding once at the end is not equivalent and is not permitted.

Life-safety metrics are integers. Occupant-load figures are taken to the mathematical floor (rounded down to the nearest whole person). The required fire flow is rounded **up** to the nearest 250 gpm after clamping. A flow test's projected available flow is rounded to the nearest whole gpm using round-half-up. Abatement deadlines and permit expiries are UTC datetimes derived by adding a whole number of days to a logical-clock timestamp.

### 2.6. Hierarchical Consistency and Cascading Effects

Many operations in this domain mutate more than one entity. The system applies every such secondary effect immediately and in full — there is no deferred or eventual reconciliation. When a rule states that an action both changes the acted-on resource and, for example, suspends a certificate, adjusts a property's counters, or supersedes a prior order, all of those changes take effect together, each incrementing its own resource's `version` and refreshing its own `updated_at`. The property-level counters `open_violation_count` and `fees_paid_cents` are maintained exclusively through these cascades; they are never supplied by a client. The detailed cascade chains (imminent-hazard auto-abatement, overdue escalation, and permit-revocation revocation of occupancy) are specified in Section 3.

### 2.7. Referential Resolution Order

Requests reference resources both through path identifiers and through foreign-key fields in the body. The server resolves these left-to-right and front-to-back: path identifiers are checked before body-referenced resources, and each referenced resource must exist. The first identifier that fails to resolve determines the error — for example, a missing property yields `ERR_PROPERTY_NOT_FOUND`, a missing application yields `ERR_APPLICATION_NOT_FOUND`, and likewise `ERR_PLAN_REVIEW_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, `ERR_VIOLATION_NOT_FOUND`, `ERR_ABATEMENT_ORDER_NOT_FOUND`, `ERR_CERTIFICATE_NOT_FOUND`, `ERR_HYDRANT_NOT_FOUND`, and `ERR_FLOW_TEST_NOT_FOUND`. All existence failures carry HTTP 404.

### 2.8. Optimistic Concurrency Control on Abatement-Order Issuance

Issuing a new abatement order against a violation is guarded by optimistic concurrency control. The issuance request must carry `expected_violation_version`, and it is not optional: the value is the `version` of the target violation that the client last observed. The server compares `expected_violation_version` against the violation's current `version`. If they do not match — meaning another writer has advanced the violation since the client read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). This is framed purely in stale-view terms: because a new order legitimately supersedes the prior active order and the violation itself stays `OPEN`, no state precondition would otherwise block a second issuance; the version check is precisely what distinguishes a client acting on an outdated view (whose observation predates the issuance that already superseded the order) from a client acting on the current one. A successful issuance increments the violation's `version` by one. No other endpoint takes a version field or performs an OCC check.

### 2.9. Validation Precedence

When several checks could reject a request, they are evaluated in a fixed order so that the returned `error_id` is deterministic:

1. Authentication — headers present and role recognized (`ERR_UNAUTHENTICATED`, 401).
2. Authorization — the acting role is permitted for the endpoint (`ERR_UNAUTHORIZED`, 403).
3. Existence — every path- and body-referenced resource resolves, left-to-right (the resource-specific 404 codes of Section 2.7).
4. Ownership — for the applicant-owned actions (submit, pay-fee, resubmit-corrections), the caller's `X-User-ID` equals the application's `applicant_user_id` (`ERR_NOT_OWNER`, 403).
5. Body well-formedness — required body fields are present and correctly typed (`ERR_VALIDATION`, 400).
6. Enum membership — enum-valued body fields carry a declared member (`ERR_INVALID_ENUM`, 422).
7. Conditional-field presence — a `COMPLAINT` inspection carries a `complaint_description`, and a `HAZMAT` or `TANK` application submit carries a `flow_test_id` (`ERR_MISSING_CONDITIONAL_FIELD`, 422).
8. State and business rules — the operation is legal from the resource's current state and satisfies the domain-specific constraints described in Section 3.

Within the final tier, the generic "illegal from current state" rejection is `ERR_INVALID_STATE` (409); the more specific business rejections (fee unpaid, open violations, window overlap, stale version, and the others) are named in the narratives that describe them and are listed in Section 5.

## 3. Business Logic & Workflows

### 3.1. Registering a Property and Deriving Its Life-Safety Metrics

A property is the root of everything else. An `Applicant` or a `FireMarshal` registers one by supplying its `address`, `owner_name`, an `occupancy_classification`, a `construction_type`, the `total_floor_area_sqft`, and the number of `stories`. The `occupancy_classification` must be one of `ASSEMBLY`, `BUSINESS`, `EDUCATIONAL`, `FACTORY`, `HIGH_HAZARD`, `INSTITUTIONAL`, `MERCANTILE`, `RESIDENTIAL`, `STORAGE`, or `UTILITY`, and the `construction_type` must be one of `TYPE_I`, `TYPE_II`, `TYPE_III`, `TYPE_IV`, or `TYPE_V`. The gross floor area must be greater than zero and the number of stories must be at least one. A property may later be amended — its `total_floor_area_sqft`, `occupancy_classification`, `construction_type`, and `stories` are each individually amendable — and any amendment recomputes every derived metric below from the new values.

On registration, and again on every amendment, the server computes four derived fields and stores them on the property.

The **posted occupant load** (`occupant_load`) uses the net-area method. Each occupancy classification has an occupant-load factor expressed as square feet per person: `ASSEMBLY` 7, `BUSINESS` 150, `EDUCATIONAL` 20, `FACTORY` 100, `HIGH_HAZARD` 100, `INSTITUTIONAL` 240, `MERCANTILE` 60, `RESIDENTIAL` 200, `STORAGE` 500, and `UTILITY` 300. The posted occupant load is the gross floor area multiplied by a net-area ratio of 0.85, that product divided by the occupancy factor, and the result taken to the floor (rounded down to a whole number of people).

The **design occupant load** (`design_occupant_load`) uses the gross-area method: the gross floor area divided by the same occupancy factor, taken to the floor. Because it omits the 0.85 net-area ratio, it is always at least as large as the posted occupant load.

The **required number of exits** (`required_exits`) is a step function of the posted `occupant_load`, with each boundary inclusive at its lower edge: an occupant load of 1000 or more requires 4 exits; from 500 up to but not including 1000 requires 3 exits; from 50 up to but not including 500 requires 2 exits; and anything below 50 requires 1 exit. Thus 49 occupants require one exit and 50 occupants require two.

The **required fire flow** (`required_fire_flow_gpm`) blends area, construction, and hazard. Start from a raw value equal to the gross floor area multiplied by a flow coefficient of 0.09, multiplied by a construction factor, multiplied by an occupancy hazard multiplier. The construction factor is 0.8 for `TYPE_I` and `TYPE_II`, 1.0 for `TYPE_III` and `TYPE_IV`, and 1.5 for `TYPE_V`. The occupancy hazard multiplier is 1.5 for `HIGH_HAZARD`; 1.25 for `STORAGE` and `FACTORY`; 1.0 for `ASSEMBLY`, `INSTITUTIONAL`, and `EDUCATIONAL`; and 0.75 for `BUSINESS`, `MERCANTILE`, `RESIDENTIAL`, and `UTILITY`. Clamp that raw value into the closed range from a floor of 500 gpm to a ceiling of 8000 gpm — that is, take the larger of the raw value and 500, then the smaller of that and 8000. Finally round the clamped value up to the nearest multiple of 250 gpm. The property also exposes two system counters that always begin at zero: `open_violation_count`, the number of currently-open violations tied to its inspections, and `fees_paid_cents`, the jurisdiction's net collected permit fees for the property. Both are maintained solely by the cascades described later.

### 3.2. Hydrants and Flow Testing

Water supply is tracked through hydrants and their flow tests. An `Inspector` or a `FireMarshal` registers a hydrant against a property by supplying the `property_id`, a `location_desc`, and the supplying main's diameter in inches as `main_size_inches`.

An `Inspector` records a flow test against a hydrant by supplying the `hydrant_id`, the `test_date`, the `static_psi`, the `residual_psi`, and the `measured_flow_gpm`. Two guards run before the test is accepted. First, the readings must be physically coherent: the residual pressure must be greater than 20 and strictly less than the static pressure, and the measured flow must be greater than zero; otherwise the test is rejected with `ERR_INVALID_FLOW_READINGS`. Second, each test establishes a one-year validity window running from its `test_date` and lasting 365 days — the window is the half-open interval that includes the `test_date` and excludes the instant 365 days later. A new test's window may not overlap the window of any existing flow test on the same hydrant; if it does, the test is rejected with `ERR_FLOW_TEST_WINDOW_OVERLAP`. Adjacency at the boundary is explicitly allowed: an existing window that ends exactly at the new test's `test_date` does not count as an overlap.

When a test is accepted, the server computes its `available_flow_at_20psi`, the fire flow projected to a 20 psi residual. Form the pressure ratio as the static pressure minus 20, divided by the static pressure minus the residual pressure. Raise that ratio to the power 0.54, multiply by the `measured_flow_gpm`, and round the result to the nearest whole gpm using round-half-up. The server also stamps the test's `valid_until` as the `test_date` plus 365 days, the exclusive end of its validity window.

### 3.3. Opening a Permit Application and Estimating Its Fee

An `Applicant` opens a permit application in the `DRAFT` state by supplying the `property_id`, the `applicant_user_id` that will own the application, the `permit_type`, the declared `project_valuation_cents`, and the `scope_area_sqft`; a `flow_test_id` may also be supplied and is required later for certain permit types. The `permit_type` must be one of `CONSTRUCTION`, `TENANT_IMPROVEMENT`, `HAZMAT`, or `TANK`. The declared valuation must be zero or greater and the scope area must be greater than zero.

Submitting an application for review advances it from `DRAFT` to `UNDER_REVIEW`, and only the owning applicant (whose `X-User-ID` matches the application's `applicant_user_id`) may do so. For a `HAZMAT` or `TANK` application, submission additionally requires a `flow_test_id`; if it is absent the submit is rejected with `ERR_MISSING_CONDITIONAL_FIELD`. When a `flow_test_id` is present for such an application, the referenced flow test's `available_flow_at_20psi` must be at least the property's `required_fire_flow_gpm`; if the available flow falls short, the submit is rejected with `ERR_INSUFFICIENT_FIRE_FLOW`. Submission has two side effects: it freezes the application's `estimated_fee_cents`, and it creates the application's `PlanReview` with all three discipline axes set to `UNDER_REVIEW` and `overall_status` set to `OPEN`.

The permit fee is tiered. Its base depends on the `permit_type`: 20000 cents for `CONSTRUCTION`, 10000 for `TENANT_IMPROVEMENT`, 30000 for `HAZMAT`, and 25000 for `TANK`. Three rate components are derived from the `project_valuation_cents`: a valuation component at a rate of 0.005, a state-surcharge component at a rate of 0.001, and a technology-fee component at a rate of 0.0004. Each of these three components is rounded to whole cents with round-half-up individually, before any summation. A resubmission surcharge adds 5000 cents for each counted resubmission. The total fee is the base plus the three rounded rate components plus the surcharge. The fee has two variants distinguished only by the resubmission count they use. The **estimated** variant, computed at submission and stored frozen in `estimated_fee_cents`, treats the effective resubmission count as zero, so its surcharge is zero. The **final** variant, computed at permit issuance and stored in `final_fee_cents`, uses the application's actual `resubmit_count`. Both variants are otherwise identical and both round each rate component before summing.

Separately from review, the owning applicant records payments toward the application. Each payment supplies an `amount_cents` (a non-negative integer), which is added to the application's cumulative `amount_paid_cents`. Only the owning applicant may pay.

### 3.4. Plan Review Across Three Disciplines

A `PlanReview` tracks three independent discipline axes — `sprinkler_status`, `alarm_status`, and `egress_status` — each of which is one of `UNDER_REVIEW`, `APPROVED`, or `CORRECTIONS_REQUIRED`, all starting at `UNDER_REVIEW`. A derived `overall_status` summarizes them: it is `OPEN` until all three axes are `APPROVED`, at which point it becomes `APPROVED`. The review also carries a `correction_cycles` counter starting at zero.

A `PlanReviewer` records a decision on one axis at a time, naming the `discipline` to act on and the `decision` to apply. The named axis must currently be `UNDER_REVIEW`; a decision aimed at an axis that is not `UNDER_REVIEW` is rejected with `ERR_REVIEW_INCOMPLETE`. A decision either sets the named axis to `APPROVED` or sets it to `CORRECTIONS_REQUIRED`. If the decision drives the named axis to `CORRECTIONS_REQUIRED`, the parent application moves from `UNDER_REVIEW` to `CORRECTIONS_REQUIRED`. If the decision is the one that brings all three axes to `APPROVED` — that is, after applying it, zero axes remain outside `APPROVED` — then the review's `overall_status` bubbles up to `APPROVED` and the parent application advances from `UNDER_REVIEW` to `APPROVED`. A decision that approves an axis while others are still under review leaves the review `OPEN` and the application `UNDER_REVIEW`.

When corrections have been requested, the owning applicant resubmits corrected plans. Resubmission requires that at least one discipline axis is currently `CORRECTIONS_REQUIRED`; each axis that is `CORRECTIONS_REQUIRED` returns to `UNDER_REVIEW`, the review's `correction_cycles` increments by one, and the application's `resubmit_count` increments by one (which is what later inflates the final fee's surcharge). The application itself returns from `CORRECTIONS_REQUIRED` to `UNDER_REVIEW`. Only the owning applicant may resubmit.

### 3.5. Issuing and Revoking Permits

Once an application reaches `APPROVED`, a `FireMarshal` issues the permit. Two conditions gate issuance. The application's `status` must be `APPROVED`; issuance against an application in any other status is rejected with `ERR_APPLICATION_NOT_APPROVED`. And the application must be paid in full: the final fee is computed at this moment using the final fee variant (with the actual `resubmit_count`), and the application's `amount_paid_cents` must be at least that `final_fee_cents`, otherwise issuance is rejected with `ERR_FEE_UNPAID`. On success the server computes `final_fee_cents`, creates a `Permit` in the `ISSUED` state carrying its own `application_id`, a server-minted `permit_number`, a copy of `final_fee_cents`, an `issued_at` stamped from the logical clock, and an `expires_at` set to `issued_at` plus 365 days; it advances the application from `APPROVED` to `ISSUED`; and it adds the `final_fee_cents` to the property's `fees_paid_cents`.

A `FireMarshal` may revoke an issued permit. Revocation is legal only while the permit is `ISSUED` and moves it to `REVOKED`. It also reverses the money and the occupancy: the application's `refunded_cents` increases by the permit's `final_fee_cents`, the property's `fees_paid_cents` decreases by the same `final_fee_cents`, and, as a cascade, the certificate for that property has its `occupancy_status` set to `REVOKED` and its `placard_status` set to `RED`.

### 3.6. Scheduling Inspections and Recording Results

An `Inspector` schedules an inspection against a property by supplying the `property_id`, the `inspection_type` — one of `PERIODIC`, `COMPLAINT`, `RE_INSPECTION`, or `FINAL` — and the `scheduled_date`; a `COMPLAINT` inspection must also carry a `complaint_description`, and its absence is rejected with `ERR_MISSING_CONDITIONAL_FIELD` (for any other type the description is left null). To avoid clustering, a new inspection's `scheduled_date` must be at least 14 days away from that of any other non-terminal inspection on the same property; the buffer is symmetric, so a proposed date fewer than 14 days before or after an existing scheduled inspection is rejected with `ERR_INSPECTION_TOO_CLOSE`. A newly scheduled inspection begins in the `SCHEDULED` state with a null `result_recorded_at`.

An `Inspector` records the outcome by supplying a `result` of either `PASSED` or `FAILED`, together with a `findings` array when the outcome warrants it. Recording is legal only while the inspection is `SCHEDULED`. Either outcome stamps `result_recorded_at` from the logical clock and moves the inspection to `PASSED` or `FAILED` accordingly.

A `FAILED` result normally requires `findings` to be a non-empty array; the one exception is a `RE_INSPECTION`, which may fail with no new findings (its purpose there is to reopen previously abated violations). Each finding becomes a new `Violation` in the `OPEN` state, carrying the `inspection_id`, the cited `code_section`, and a `severity` of `MINOR`, `MAJOR`, or `IMMINENT_HAZARD`; for each violation created, the property's `open_violation_count` increments by one. If any newly created violation has severity `IMMINENT_HAZARD`, cascade C1 fires for it (an abatement order is auto-issued and the certificate is suspended, as described in Section 3.7). If a `RE_INSPECTION` fails, every violation on the property currently in `ABATED` reopens to `OPEN`, and the property's `open_violation_count` increments by one for each reopened violation. Finally, if the failed inspection produced or reopened no `IMMINENT_HAZARD` violation and a certificate exists for the property, that certificate's `placard_status` is set to `YELLOW`.

A `PASSED` result carries no findings. If a `PASSED` inspection is a `RE_INSPECTION`, every violation on that property currently in `ABATED` is promoted to `VERIFIED`, closing out the abatement cycle.

### 3.7. Violations, Abatement Orders, and Escalation

A `Violation` moves through `OPEN`, `ABATED`, `VERIFIED`, and `ESCALATED`. It enters at `OPEN` when an inspection fails, and `VERIFIED` is its terminal, satisfied state. An `IMMINENT_HAZARD` violation is special at birth: its creation triggers cascade C1, which auto-creates an `AbatementOrder` in the `ISSUED` state with `is_active` true for that violation, and (as the certificate side of the same cascade) suspends the property's certificate — setting `occupancy_status` to `SUSPENDED` and `placard_status` to `RED`.

An `Inspector` issues abatement orders against a violation, whether the first one or a replacement. Each issuance supplies `expected_violation_version` and is subject to the optimistic-concurrency check of Section 2.8 (`ERR_STALE_VERSION`, 412, on a mismatch). A fresh issuance while an order already controls the violation supersedes the prior one: the previously `is_active` order, if `ISSUED`, transitions to `SUPERSEDED` and its `is_active` becomes false, while the new `AbatementOrder` is created `ISSUED` with `is_active` true, carrying its `violation_id` and an `issued_at` from the logical clock. Issuance also increments the violation's `version` by one. Every order's `deadline` is its `issued_at` plus a grace period keyed to the parent violation's `severity`: 3 days for `IMMINENT_HAZARD`, 30 days for `MAJOR`, and 90 days for `MINOR`.

An `Inspector` marks the controlling order complied. Compliance is legal only when the order is `is_active` and `ISSUED` and its violation is `OPEN`; the order moves from `ISSUED` to `COMPLIED`, the violation moves from `OPEN` to `ABATED`, its `abated_at` is stamped from the logical clock, and the property's `open_violation_count` decrements by one. An `ABATED` violation is later resolved by a re-inspection: a passing re-inspection promotes it to `VERIFIED`, while a failing re-inspection returns it to `OPEN` and increments the property's `open_violation_count` by one.

Overdue orders are handled by a fire-marshal-only sweep that processes every `ISSUED`, `is_active` order whose `deadline` has passed relative to the current logical clock. The sweep processes eligible orders in ascending order of their creation and returns a `processed_count` together with the list of `escalated_violation_ids` in that same processing order. For each such order, cascade C2 runs: the order moves `ISSUED` to `OVERDUE` and, in the same sweep, on to `ESCALATED`; its violation moves from `OPEN` to `ESCALATED` (cascade C2 hop 1), and because the violation leaves `OPEN` the property's `open_violation_count` decrements by one; and the certificate for that property (reached through the violation's inspection's `property_id`) has its `occupancy_status` set to `SUSPENDED` and `placard_status` set to `RED` (cascade C2 hop 2).

### 3.8. Certificates of Occupancy and Placards

A `Certificate` tracks two independent axes for a property. The `occupancy_status` — the compliance axis — is one of `VALID`, `SUSPENDED`, or `REVOKED`, and the `placard_status` — the public posting axis — is one of `GREEN`, `YELLOW`, or `RED`. A `FireMarshal` issues a certificate against a property (supplying the `property_id`), and it starts `VALID` and `GREEN`. Issuance is blocked while any violation on that property is `OPEN` or `ESCALATED`, in which case it is rejected with `ERR_OPEN_VIOLATIONS`.

The two axes move on different triggers. The compliance axis is driven to `SUSPENDED` (and the placard to `RED`) by the safety cascades — either the auto-issue of an `IMMINENT_HAZARD` abatement order (cascade C1) or the escalation of a violation (cascade C2). In either suspend cascade, a certificate already in `REVOKED` takes precedence and is left `REVOKED` (its placard stays `RED`); only a non-`REVOKED` certificate is moved to `SUSPENDED`. It is driven to `REVOKED` (placard `RED`) when a permit whose application shares this certificate's property is revoked, whether the certificate was `VALID` or already `SUSPENDED` at the time. Independently, a failed inspection that produces no imminent hazard drops any existing certificate's placard to `YELLOW` regardless of its current `occupancy_status`, as described in Section 3.6.

A `FireMarshal` reinstates a suspended certificate, moving `occupancy_status` from `SUSPENDED` back to `VALID` and setting `placard_status` to `GREEN`. Reinstatement is permitted only when no violation on the property (reached through its inspections) is in `OPEN` or `ESCALATED`; otherwise it is rejected with `ERR_OPEN_VIOLATIONS`.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`; operations that modify an existing resource, including state transitions and the operational sweeps, return `200 OK`. All list and fetch operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/properties` | Register a property/building | Applicant, FireMarshal |
| GET | `/api/properties/{id}` | Fetch a property | Applicant, PlanReviewer, Inspector, FireMarshal |
| PATCH | `/api/properties/{id}` | Amend property attributes; recompute derived fields | Applicant, FireMarshal |
| POST | `/api/permit-applications` | Open a permit application (DRAFT) | Applicant |
| GET | `/api/permit-applications/{id}` | Fetch an application | Applicant, PlanReviewer, Inspector, FireMarshal |
| GET | `/api/permit-applications` | List applications | Applicant, PlanReviewer, Inspector, FireMarshal |
| POST | `/api/permit-applications/{id}/submit` | Submit for plan review; freeze estimated fee, open plan review | Applicant |
| POST | `/api/permit-applications/{id}/pay-fee` | Record a fee payment toward the application | Applicant |
| GET | `/api/plan-reviews/{id}` | Fetch a plan review | Applicant, PlanReviewer, Inspector, FireMarshal |
| GET | `/api/plan-reviews` | List plan reviews | Applicant, PlanReviewer, Inspector, FireMarshal |
| POST | `/api/plan-reviews/{id}/discipline-decision` | Record a discipline decision on one axis | PlanReviewer |
| POST | `/api/plan-reviews/{id}/resubmit-corrections` | Applicant resubmits corrected plans | Applicant |
| POST | `/api/permits` | Issue a permit for an approved, paid application | FireMarshal |
| GET | `/api/permits/{id}` | Fetch a permit | Applicant, PlanReviewer, Inspector, FireMarshal |
| GET | `/api/permits` | List permits | Applicant, PlanReviewer, Inspector, FireMarshal |
| POST | `/api/permits/{id}/revoke` | Revoke a permit and refund its fee | FireMarshal |
| POST | `/api/certificates` | Issue a certificate of occupancy | FireMarshal |
| GET | `/api/certificates/{id}` | Fetch a certificate | Applicant, PlanReviewer, Inspector, FireMarshal |
| GET | `/api/certificates` | List certificates | Applicant, PlanReviewer, Inspector, FireMarshal |
| POST | `/api/certificates/{id}/reinstate` | Reinstate a suspended certificate | FireMarshal |
| POST | `/api/inspections` | Schedule a periodic/complaint/re/final inspection | Inspector |
| GET | `/api/inspections/{id}` | Fetch an inspection | Applicant, PlanReviewer, Inspector, FireMarshal |
| GET | `/api/inspections` | List inspections | Applicant, PlanReviewer, Inspector, FireMarshal |
| POST | `/api/inspections/{id}/record-result` | Record inspection outcome; on FAILED create violations and cascade | Inspector |
| GET | `/api/violations/{id}` | Fetch a violation | Applicant, PlanReviewer, Inspector, FireMarshal |
| GET | `/api/violations` | List violations | Applicant, PlanReviewer, Inspector, FireMarshal |
| POST | `/api/violations/{id}/abatement-orders` | Issue (or re-issue/supersede) an abatement order | Inspector |
| GET | `/api/abatement-orders/{id}` | Fetch an abatement order | Applicant, PlanReviewer, Inspector, FireMarshal |
| GET | `/api/abatement-orders` | List abatement orders | Applicant, PlanReviewer, Inspector, FireMarshal |
| POST | `/api/abatement-orders/{id}/comply` | Mark an abatement order complied | Inspector |
| POST | `/api/hydrants` | Register a hydrant | Inspector, FireMarshal |
| GET | `/api/hydrants/{id}` | Fetch a hydrant | Applicant, PlanReviewer, Inspector, FireMarshal |
| GET | `/api/hydrants` | List hydrants | Applicant, PlanReviewer, Inspector, FireMarshal |
| POST | `/api/flow-tests` | Record a hydrant flow test | Inspector |
| GET | `/api/flow-tests/{id}` | Fetch a flow test | Applicant, PlanReviewer, Inspector, FireMarshal |
| GET | `/api/flow-tests` | List flow tests | Applicant, PlanReviewer, Inspector, FireMarshal |
| POST | `/api/_ops/process-overdue-orders` | Sweep overdue abatement orders and cascade escalations | FireMarshal |
| POST | `/api/_clock/set_current_utc` | Set the server logical clock | FireMarshal |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_OWNER` | 403 |
| `ERR_PROPERTY_NOT_FOUND` | 404 |
| `ERR_APPLICATION_NOT_FOUND` | 404 |
| `ERR_PLAN_REVIEW_NOT_FOUND` | 404 |
| `ERR_PERMIT_NOT_FOUND` | 404 |
| `ERR_INSPECTION_NOT_FOUND` | 404 |
| `ERR_VIOLATION_NOT_FOUND` | 404 |
| `ERR_ABATEMENT_ORDER_NOT_FOUND` | 404 |
| `ERR_CERTIFICATE_NOT_FOUND` | 404 |
| `ERR_HYDRANT_NOT_FOUND` | 404 |
| `ERR_FLOW_TEST_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_ENUM` | 422 |
| `ERR_MISSING_CONDITIONAL_FIELD` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_APPLICATION_NOT_APPROVED` | 409 |
| `ERR_REVIEW_INCOMPLETE` | 409 |
| `ERR_OPEN_VIOLATIONS` | 409 |
| `ERR_FLOW_TEST_WINDOW_OVERLAP` | 409 |
| `ERR_INSPECTION_TOO_CLOSE` | 409 |
| `ERR_INVALID_FLOW_READINGS` | 422 |
| `ERR_INSUFFICIENT_FIRE_FLOW` | 409 |
| `ERR_FEE_UNPAID` | 402 |
| `ERR_STALE_VERSION` | 412 |
