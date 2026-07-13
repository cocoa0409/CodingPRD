# Film Location Permit API — Product Requirements Document

## 1. Introduction

The Municipal Film & Location Permit Office coordinates every on-location production that takes place on public streets and municipal property. A production company that wants to film in the city must apply for a permit, describe each location it intends to occupy, disclose whether it needs road closures or reserved parking, prove that it carries adequate liability insurance, and — where drones or organized still-photography are involved — attach the appropriate special-activity riders. Behind the counter, several municipal departments (police, parking enforcement, fire, and public works) review the request in parallel, on-site officers are scheduled to monitor the shoot, neighbors are notified in advance, and fees and refundable deposits are assessed. This API is the system of record for that entire lifecycle.

The domain is deliberately intricate because the real-world process is. A single application accretes locations, insurance certificates, road-closure bookings, officer assignments, riders, notifications, and a running ledger of payments, and its fee is quoted twice — once as a forward-looking estimate when the applicant submits, and again as a binding figure at issuance, after denied riders and blocked bookings have dropped away. Street segments can only be closed by one production at a time, so competing bookings must be resolved deterministically. When a shoot wraps, the office reconciles the deposit against any damage and any overrun of the permitted end time, and the production company's standing is adjusted accordingly. This document specifies the resources, the state machines that govern them, the fee and deposit arithmetic, the validation rules and their precedence, and the exact HTTP contract that clients depend on.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the principal's role. If either header is absent, or if `X-User-Role` is not one of the four roles below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well-formed but the role is not permitted to invoke the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly four roles:

- **`ProductionCompany`** — the applicant. A `ProductionCompany` owns its applications and everything hanging off them: locations, riders, insurance certificates, road-closure bookings, payments, and the wrap request. Its identity is entity-backed: when `X-User-Role` is `ProductionCompany`, `X-User-ID` is the `id` of the acting `ProductionCompany` entity; however, `ProductionCompany` write operations are authorized by role alone — the server does not compare a resource's `production_company_id` to `X-User-ID`, so ownership is not enforced as an authorization gate and any authenticated `ProductionCompany` may act on any application and its children.
- **`DepartmentReviewer`** — an official acting on behalf of one reviewing department. Its identity is entity-backed against `Department`: when `X-User-Role` is `DepartmentReviewer`, `X-User-ID` is the `id` of the acting `Department`, and a reviewer may only record a decision on a review whose `department_id` equals `X-User-ID`.
- **`FieldOfficer`** — the on-site officer who closes out a shoot. Its identity is entity-backed against `Officer`: when `X-User-Role` is `FieldOfficer`, `X-User-ID` is the `id` of the acting `Officer`.
- **`FilmOfficeCoordinator`** — the municipal film-office operator who onboards companies, officers, departments, and street segments, issues permits, verifies insurance certificates, decides riders, sends neighborhood notifications, assigns officers, and drives the logical clock. Its identity is opaque: when `X-User-Role` is `FilmOfficeCoordinator`, `X-User-ID` is an operator identifier not tied to any persisted entity. The server may accept and record it but does not compare it to any entity's `id`.

All read (GET) endpoints are available to every authenticated role. Write operations are partitioned so that no two roles share ownership of the same resource: applicants build and submit applications, reviewers decide reviews, coordinators run the office and issue permits, and field officers close wraps.

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

List endpoints accept two query parameters, `limit` and `offset`. `limit` defaults to 10, must be at least 1, and may not exceed 100; `offset` defaults to 0 and must be at least 0. Results are always returned sorted by `created_at` in ascending order (oldest first); when two records share the same `created_at`, ties are broken by ascending creation (insertion) order. The response's `meta` object carries `limit`, `offset`, `total_count` (the total number of matching records before pagination), and `has_more` (true when records beyond the current page remain). A request whose `limit` or `offset` falls outside these bounds is rejected as a malformed request with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.4. Common Resource Properties, Timestamps, and Versioning

Every resource is assigned a server-minted `id` that is a UUID with no type prefix. Two timestamp fields, `created_at` and `updated_at`, are ISO 8601 UTC values carrying three fractional digits; `created_at` is stamped once at creation, and `updated_at` is refreshed on every mutation. Each resource also carries an integer `version` that begins at 1 and increments by one on every mutation of that resource.

Not every resource is versioned. `Department`, `StreetSegment`, `LocationDetail`, `NeighborhoodNotification`, and `LedgerEntry` are immutable-by-design records: each carries only an `id` and a `created_at`, and has neither an `updated_at` nor a `version` field. All other resources — `ProductionCompany`, `Officer`, `PermitApplication`, `DepartmentReview`, `InsuranceCertificate`, `RoadClosureBooking`, `OfficerAssignment`, and `Rider` — carry the full complement of `created_at`, `updated_at`, and `version`.

A subtle but important consequence concerns the `PermitApplication`. Because an application's `version` advances not only when the application itself transitions but also whenever a child is attached to it — a location, a rider, or an insurance certificate — a client that reads an application, then attaches a rider, then tries to act on its earlier snapshot will be working from a stale version. This is the hinge on which the optimistic-concurrency rules in §2.5 turn.

### 2.5. Optimistic Concurrency Control

Two operations on a `PermitApplication` are guarded by optimistic concurrency, and both compare against the application's own `version`. Each such request must include an `expected_application_version` field carrying the `version` the client last observed on the application. If that value does not equal the application's current `version` at the moment the server processes the request, the operation is rejected with `ERR_STALE_APPLICATION_VERSION` (HTTP 412), and no state changes. The check is enforced only when the field is present: a guarded request that omits `expected_application_version` (or sends it as null) is processed without any version comparison.

The first guarded operation is **submitting an insurance certificate**. Because submitting a new certificate supersedes the prior active one and advances the application's `version`, a submission whose `expected_application_version` is older than the application's current `version` means another certificate has already been submitted since the client last read the application; the stale submission is rejected with `ERR_STALE_APPLICATION_VERSION` so the client cannot overwrite a certificate state it never saw.

The second guarded operation is **issuing the permit**. Issuance stamps the final fee from the application's current set of approved riders and confirmed bookings; if the applicant has added a rider or a location since the coordinator last read the application, the application's `version` has advanced and issuing now would price a production different from the one the coordinator reviewed. Such an issue request is rejected with `ERR_STALE_APPLICATION_VERSION`. Operations that are not on this list do not accept and do not check a version field.

### 2.6. Monetary Amounts, Precision, and Rounding

Every monetary quantity in this system — fees, surcharges, deposits, penalties, refunds, officer billing, and ledger amounts — is expressed as an integer number of cents. There are no fractional cents. The permit-fee subtotal is a sum of integer terms and is computed with no intermediate rounding. Where a rate expressed in basis points is applied (the municipal surcharge and the deposit percentage), the product is divided by 10000 and rounded down to the nearest whole cent (floor division). Where a duration must be converted to whole billable units — officer shift hours and late-wrap overage hours — the number of hours is always rounded up to the next whole hour (ceiling). Two derived quantities are clamped: the production compliance score is held within the inclusive range 0 through 100, and the deposit refund is never allowed to fall below 0.

### 2.7. The Logical Clock and Temporal Reasoning

All deadline, lead-time, issuance, and wrap comparisons are made against a **logical clock** rather than real wall-clock time, so that behavior is fully deterministic. At server startup the clock reads exactly `2026-03-01T00:00:00Z`, and it holds that value until it is explicitly advanced; before any advance it never reflects real time. A coordinator advances the clock by supplying a target instant as `to_iso8601`. The clock's current value is what stamps `issued_at`, `decided_at`, `sent_at`, and `actual_end_at`-related comparisons, and what the neighborhood-notification lead-time is measured against.

When two temporal windows are compared for overlap, the convention depends on the domain: officer-assignment conflict detection treats windows as half-open intervals `[start, end)`, so two shifts that merely touch (one ending exactly when the next begins) do **not** conflict, whereas road-closure conflict detection first expands each window by a setup buffer (see §2.9 and §3.5) before testing for overlap.

### 2.8. Request Validation Order and Nested-Path Resolution

When several checks could reject a request, they are evaluated in a fixed precedence so that the returned `error_id` is deterministic. Authentication is checked first: a missing or unknown-role header pair yields `ERR_UNAUTHENTICATED` (401). Authorization is checked next: a role not permitted for the endpoint yields `ERR_UNAUTHORIZED` (403). Then path existence is verified left-to-right — for a nested path, each `id` segment is resolved in order, and the first that does not resolve yields `ERR_NOT_FOUND` (404). Then any foreign-key reference in the request body (`production_company_id`, `application_id`, `department_id`, `street_segment_id`, `officer_id`) is checked for existence, again yielding `ERR_NOT_FOUND` (404) if absent. Then the body is checked for well-formedness — required fields present, enum values in range, constrained integers non-negative — yielding `ERR_INVALID_REQUEST` (400). Only after all of these do endpoint-specific temporal, state, and business rules run, in the per-endpoint order described throughout §3. Time-range checks (an end timestamp that is not strictly after its start) are evaluated ahead of the deeper business rules and yield `ERR_INVALID_TIME_RANGE` (HTTP 422).

### 2.9. Cascading State Propagation and Conserved Quantities

Many operations mutate more than one resource. Whenever a state transition fires a side effect that changes another resource, that secondary resource is itself mutated: its `updated_at` is refreshed and, where it is a versioned resource, its `version` increments. The `PermitApplication` in particular increments its `version` on every transition and on every child attachment, as described in §2.4.

Two quantities on an application are **conserved ledger totals** rather than free-standing inputs. `amount_paid_cents` is the running sum of the amounts of all `PERMIT_FEE` ledger debits recorded against the application. `deposit_held_cents` is the running sum of `DEPOSIT` debit amounts minus the sum of `REFUND` credit amounts for the application — that is, the deposit money the city currently holds. These are maintained by the ledger and by the refund side effects described in §3.8; they are never set directly by a client.

Road-closure bookings introduce a further propagation chain that ripples across applications sharing a street segment, and issuance, withdrawal, and review-rejection each set portions of it in motion. Those cascades are specified in full in §3.

## 3. Business Logic & Workflows

### 3.1. Building the Operational Registry

Before any permit can be processed, a coordinator populates the office's registry. A `ProductionCompany` is registered with its `legal_name`, `contact_email`, and `primary_contact`. On registration, three behavioral counters — `late_wrap_count`, `damage_incident_count`, and `missed_notification_count` — start at 0, and the company's `compliance_score` starts at 100. The counters are system-maintained tallies of prior misbehavior: `late_wrap_count` counts prior applications that wrapped after their permitted end time, `damage_incident_count` counts prior applications whose wrap-close reported damage, and `missed_notification_count` counts each time a neighborhood notification for one of the company's applications was rejected as too late at the moment it was recorded. The `compliance_score` is not stored as a fixed figure but derived from these counters, as described in §3.8.

A `Department` is created with a `code` — one of `POLICE`, `PARKING`, `FIRE`, or `PUBLIC_WORKS` — a human-readable `name`, and a `trigger_condition` that declares which applications require this department's review. The `trigger_condition` is one of `ALL_APPLICATIONS` (every submitted application), `ROAD_CLOSURE_ONLY` (only applications whose `requires_road_closure` is true), `PARKING_ONLY` (only applications whose `requires_parking` is true), or `DRONE_ONLY` (only applications that carry at least one `DRONE` rider at submit time). Departments carry only an `id` and a `created_at`.

An `Officer` is created with a `full_name`, a `badge_number`, a `rank` (`OFFICER`, `SERGEANT`, or `LIEUTENANT`), and an `hourly_rate_cents` billing rate that must be a non-negative integer. A new officer's `status` is `ACTIVE`. A coordinator may later flip an officer's `status` between `ACTIVE` and `INACTIVE`; setting an officer `INACTIVE` does not retroactively cancel that officer's existing assignments, it only prevents new ones.

A `StreetSegment` represents one physical stretch of roadway that can be closed. It is registered with a short unique `segment_code` (for example, `MAIN-100`), a human-readable `name`, and a `length_m` giving its length in meters, which must be greater than 0. Street segments carry only an `id` and a `created_at`.

### 3.2. Assembling a Permit Application

An applicant opens a new application in `DRAFT` status by supplying the owning `production_company_id`, a `title`, a `synopsis`, the requested `shoot_start_at` and `shoot_end_at` instants, the total `crew_size` (which must be at least 1), and two booleans, `requires_road_closure` and `requires_parking`, each defaulting to false. The `shoot_end_at` must be strictly after `shoot_start_at`; otherwise the creation is rejected with `ERR_INVALID_TIME_RANGE`. From the two shoot instants the system derives `shoot_days`, the inclusive calendar-day span computed as the date of `shoot_end_at` minus the date of `shoot_start_at`, plus one, where each instant's calendar date is taken in UTC. Several money fields on the application begin at 0 and are stamped later: `estimated_fee_cents`, `final_fee_cents`, `municipal_surcharge_cents`, `total_fee_cents`, `deposit_cents`, `amount_paid_cents`, `deposit_held_cents`, `late_wrap_penalty_cents`, and `deposit_refund_cents`. The timestamps `issued_at`, `permitted_end_at`, and `actual_end_at` begin null, and `damage_cost_cents` begins at 0.

While an application is still open for editing — that is, while its `status` is `DRAFT`, `UNDER_REVIEW`, or `REVISION_REQUIRED` — the applicant attaches the pieces the office will review. Attempting any of these attachments when the application is in any other status is rejected with `ERR_INVALID_STATE`. Each successful attachment increments the parent `PermitApplication.version` by one.

A `LocationDetail` records one place the production will occupy. It carries the parent `application_id`, an `address`, a `geo_zone` (the notification zone the address falls in), an `activity_type` of `FILMING`, `EQUIPMENT_STAGING`, or `BASECAMP`, a `requested_start_at` and `requested_end_at` for the occupation window, and a `uses_road_closure` flag defaulting to false. Locations carry only an `id` and a `created_at`.

Insurance is disclosed through an `InsuranceCertificate` (a "COI"). Each certificate references its `application_id` and records a `policy_number`, a `coverage_amount_cents` general-liability figure (a non-negative integer), an `aviation_coverage` boolean (true when the policy also covers drone operations, defaulting to false), and the policy's `effective_date` and `expiration_date`. The `expiration_date` must be strictly after the `effective_date`, or the submission is rejected with `ERR_INVALID_TIME_RANGE`. A newly submitted certificate begins in `SUBMITTED` status. Submitting a certificate is optimistically-concurrency-guarded: the request must carry `expected_application_version` matching the application's current `version`, and a mismatch is rejected with `ERR_STALE_APPLICATION_VERSION` (HTTP 412), as detailed in §2.5. When a certificate is submitted, every prior certificate for the same application that is still in `SUBMITTED` or `VERIFIED` status is moved to `SUPERSEDED`, and the application's `version` advances.

Special activities are requested through a `Rider`, whose `rider_type` is either `DRONE` or `STILL_PHOTO`. A still-photo rider needs no further fields. A drone rider additionally supplies an `faa_waiver_number`, a `max_altitude_ft` maximum flight altitude in feet, and a flight window given by `flight_start_at` and `flight_end_at` (all four of these default to null and are meaningful only for `DRONE`). A new rider begins in `REQUESTED` status. Two safety rules guard the creation of a drone rider and are described in §3.6. A rider may be attached only while the application is in one of the editable statuses named above.

### 3.3. Submission and Multi-Department Review

When the applicant submits the application, it moves from `DRAFT` to `UNDER_REVIEW` (or, on a later resubmission, from `REVISION_REQUIRED` back to `UNDER_REVIEW`). Submission is refused with `ERR_INVALID_STATE` if the application is not in one of those two states. Two preconditions gate a first submission: the application must have at least one `LocationDetail` — a submission against an application with zero locations is rejected with `ERR_NO_LOCATIONS` (HTTP 422) — and its shoot window must be valid, with `shoot_end_at` after `shoot_start_at`. On a resubmission out of `REVISION_REQUIRED`, the at-least-one-location requirement still holds.

Submission triggers a **department fan-out**. For each `Department` whose `trigger_condition` matches this application, the system creates a `DepartmentReview` in `PENDING` status linking the application to that department. A department with `trigger_condition` `ALL_APPLICATIONS` always matches; `ROAD_CLOSURE_ONLY` matches only when the application's `requires_road_closure` is true; `PARKING_ONLY` matches only when `requires_parking` is true; and `DRONE_ONLY` matches only when the application carries at least one `DRONE` rider. This fan-out is a parallel creation of the review surface, not a chained cascade. Submission also stamps `estimated_fee_cents` with the ESTIMATE permit fee (see §3.4) and increments the application's `version`.

Each `DepartmentReview` carries its `application_id`, its `department_id`, a `status`, an optional `decision_notes` string recorded with the last decision, and a `decided_at` timestamp. A reviewer records a decision that is one of APPROVE, REJECT, or REQUEST_REVISION, optionally attaching `decision_notes`. Three preconditions apply to every decision, evaluated in this order: first, the acting reviewer's `X-User-ID` must equal the review's `department_id`, otherwise it is rejected with `ERR_UNAUTHORIZED` (HTTP 403) — a reviewer may decide only its own department's reviews; then the review itself must still be `PENDING`, otherwise (a decision on an already-decided review) the decision is rejected with `ERR_INVALID_STATE`; and then the parent application must be `UNDER_REVIEW`, otherwise the decision is likewise rejected with `ERR_INVALID_STATE`. Every decision stamps `decided_at` with the current clock value.

An APPROVE moves the review from `PENDING` to `APPROVED`, which is terminal for that review. A REQUEST_REVISION moves it from `PENDING` to `REVISION_REQUESTED`; this is a soft, non-terminal signal that by itself does **not** move the application — only an outright rejection does. A REJECT moves the review from `PENDING` to `REJECTED` and kicks off **Cascade A**: the parent application transitions from `UNDER_REVIEW` to `REVISION_REQUIRED`. As the second link of Cascade A, every `RoadClosureBooking` for that application whose status is `PENDING` or `CONFIRMED` is transitioned to `RELEASED`, and the application's `version` increments.

The review loop is cyclic. When the applicant addresses the feedback and resubmits, the application moves `REVISION_REQUIRED → UNDER_REVIEW`; as part of that transition, every `DepartmentReview` for the application whose status is `REJECTED` or `REVISION_REQUESTED` is reset to `PENDING`, `estimated_fee_cents` is recomputed from the ESTIMATE permit fee, and the application's `version` increments. Reviews that were already `APPROVED` stay approved.

### 3.4. Fees, the Municipal Surcharge, and Payments

The permit fee is computed twice over an application's life, from the same formula but with two different input sets, yielding an ESTIMATE variant at submit and a FINAL variant at issue. Both variants first compute a **subtotal** in integer cents as the sum of six terms:

1. a base application fee of 25,000 cents;
2. a per-day charge of 15,000 cents multiplied by `shoot_days`;
3. a **crew surcharge** keyed on `crew_size`: 0 cents when the crew is 15 or fewer, 20,000 cents when the crew is between 16 and 50 inclusive, 50,000 cents when the crew is between 51 and 150 inclusive, and 100,000 cents when the crew exceeds 150;
4. a road-closure charge that is 0 when the application's `requires_road_closure` is false, and otherwise 40,000 cents multiplied by the number of included road-closure bookings;
5. a parking charge that is 0 when `requires_parking` is false, and otherwise 10,000 cents multiplied by `shoot_days`;
6. a rider charge equal to 30,000 cents for each included `DRONE` rider plus 5,000 cents for each included `STILL_PHOTO` rider.

The two variants differ only in which bookings and riders count as "included." In the **ESTIMATE** variant, computed at submit and stamped into `estimated_fee_cents`, the included booking count is every `RoadClosureBooking` for the application whose status is `PENDING` or `CONFIRMED`, and the included rider counts are every rider of each type whose status is `REQUESTED` or `APPROVED` — a forward-looking figure covering everything the applicant has asked for. Because all subtotal terms are integers, the subtotal is computed with no rounding.

Layered on the subtotal is the **municipal surcharge**, whose rate in basis points is selected from the subtotal's tier — not from the post-surcharge total. The evaluation order is pinned: first compute the subtotal, then choose the rate, then compute the surcharge, then add it to the subtotal. The rate is 300 basis points when the subtotal is below 100,000 cents, 500 basis points when the subtotal is at least 100,000 cents but below 300,000 cents, and 700 basis points when the subtotal is 300,000 cents or more; these tier boundaries are half-open, so a subtotal of exactly 100,000 cents takes the 500-basis-point rate and exactly 300,000 cents takes the 700-basis-point rate. The surcharge itself is the subtotal multiplied by the chosen basis points, divided by 10000, rounded down to a whole cent. The ESTIMATE stamped into `estimated_fee_cents` is the subtotal plus this surcharge.

Payments are recorded as ledger entries. A payment carries an `entry_type` of `PERMIT_FEE` or `DEPOSIT` and an `amount_cents` that must be greater than 0; the system creates a `LedgerEntry` with `direction` set to `DEBIT`, a system `memo`, and the given `application_id`. The timing of each payment type is constrained: a `PERMIT_FEE` payment is allowed only while the application's status is `UNDER_REVIEW` or `REVISION_REQUIRED`, and a `DEPOSIT` payment is allowed only while the status is `ISSUED`. A payment whose type is not allowed for the current status is rejected with `ERR_PAYMENT_NOT_ALLOWED` (HTTP 409). Recording a `PERMIT_FEE` debit adds its amount to the application's `amount_paid_cents`; recording a `DEPOSIT` debit adds its amount to `deposit_held_cents`. The third entry type, `REFUND`, is never created by a client — it is a system-generated `CREDIT` produced at wrap-close or on withdrawal, as described in §3.8 and §3.9. Every ledger entry carries only an `id` and a `created_at`.

### 3.5. Road-Closure Bookings and Permit Issuance

A `RoadClosureBooking` reserves one street segment for one production over a window. It is created with an `application_id`, a `street_segment_id`, and a `closure_start_at` and `closure_end_at`; the closure end must be strictly after the closure start, or the booking is rejected with `ERR_INVALID_TIME_RANGE`. A booking may only be created while the referenced application is in one of its editable statuses (`DRAFT`, `UNDER_REVIEW`, or `REVISION_REQUIRED`); otherwise it is rejected with `ERR_INVALID_STATE`. A new booking begins in `PENDING` status.

At creation, a booking is checked against existing bookings on the same `street_segment_id`. The candidate window is expanded by a **setup buffer of 60 minutes** on each side, and if that buffer-expanded window overlaps any booking on the same segment that is already `CONFIRMED`, the new booking is rejected with `ERR_SEGMENT_DOUBLE_BOOKED` (HTTP 409). Competing `PENDING` requests on the same segment are deliberately allowed to coexist at creation time; they are not resolved against one another until a permit is issued.

Permit issuance is the office's most consequential operation, and its side effects fire in a pinned order. Issuance is available only from `UNDER_REVIEW`; from any other state it is rejected with `ERR_INVALID_STATE` (HTTP 409), which is checked ahead of the four preconditions below. Before anything else changes, four preconditions are checked in this order:

1. **Reviews complete.** Every `DepartmentReview` for the application must be `APPROVED` (vacuously satisfied when the application has no reviews); otherwise issuance is rejected with `ERR_REVIEWS_INCOMPLETE` (HTTP 409).
2. **Version fresh.** The request's `expected_application_version` must equal the application's current `version`; a mismatch is rejected with `ERR_STALE_APPLICATION_VERSION` (HTTP 412), as described in §2.5.
3. **Insurance verified.** At least one `InsuranceCertificate` for the application must be in `VERIFIED` status; otherwise issuance is rejected with `ERR_COI_NOT_VERIFIED` (HTTP 422).
4. **Permit fee paid.** The application's `amount_paid_cents` must be at least its `estimated_fee_cents`; otherwise issuance is rejected with `ERR_FEE_UNPAID` (HTTP 402).

Once the preconditions pass, the application transitions `UNDER_REVIEW → ISSUED` and the side effects run in this exact sequence. **First, bookings are confirmed (Cascade B):** every `RoadClosureBooking` for the application whose status is `PENDING` transitions to `CONFIRMED`. Each newly confirmed booking then blocks its competitors — the second hop of Cascade B: every other `RoadClosureBooking` on the same `street_segment_id` that is still `PENDING` and whose buffer-expanded window (again, 60 minutes on each side) overlaps the just-confirmed booking transitions to `BLOCKED`. Being blocked triggers the third hop: for each booking newly moved to `BLOCKED`, every `OfficerAssignment` belonging to that blocked booking's application whose status is `PROPOSED` transitions to `CANCELLED`, since the losing applicant no longer needs those officers. **Second**, every `OfficerAssignment` for the application being issued whose status is `PROPOSED` transitions to `CONFIRMED`. **Third**, now that the confirmed-booking set is settled, the FINAL permit fee is computed and stamped.

The FINAL permit fee uses the same six-term subtotal formula from §3.4 but with the FINAL input set: the included booking count is only those `RoadClosureBooking` rows for the application now in `CONFIRMED` status, and the included rider counts use only riders in `APPROVED` status. Denied riders and blocked bookings therefore drop out, and the FINAL subtotal generally differs from the ESTIMATE. `final_fee_cents` is stamped with this FINAL subtotal. The municipal surcharge is recomputed over the FINAL subtotal using the §3.4 tier rule and stamped into `municipal_surcharge_cents`, and `total_fee_cents` is stamped as `final_fee_cents` plus `municipal_surcharge_cents`.

Issuance then stamps the **deposit**. The deposit percentage is 2,500 basis points (25%) when `total_fee_cents` is at least 500,000 cents, and 2,000 basis points (20%) otherwise; note the boundary is inclusive, so exactly 500,000 cents takes the higher rate. `deposit_cents` is stamped as `total_fee_cents` multiplied by that basis-point rate, divided by 10000 and rounded down to a whole cent, plus a road-closure bond of 50,000 cents for each `RoadClosureBooking` that is `CONFIRMED` at issue. Finally, issuance stamps `issued_at` to the current clock value and `permitted_end_at` to a snapshot of the application's `shoot_end_at`, and the application's `version` increments. The `permitted_end_at` snapshot is what the late-wrap penalty is later measured against.

### 3.6. Riders, Insurance Verification, and Officer Assignments

Two safety rules guard drone riders at the moment a rider is attached. If the rider's `rider_type` is `DRONE`, the application must already have a `VERIFIED` `InsuranceCertificate` whose `aviation_coverage` is true; if none exists, the rider is rejected with `ERR_AVIATION_COVERAGE_MISSING` (HTTP 422). Additionally, a drone rider's flight window — from `flight_start_at` to `flight_end_at` — must lie entirely within the application's shoot window from `shoot_start_at` to `shoot_end_at`; a flight window that starts before the shoot begins or ends after the shoot ends is rejected with `ERR_FLIGHT_WINDOW_OUTSIDE_SHOOT` (HTTP 422). This containment check is applied only when both `flight_start_at` and `flight_end_at` are provided; if either is null the check is skipped. When both apply, aviation coverage is checked before the flight-window containment.

A coordinator decides each rider with an APPROVE or DENY, provided the rider is still in `REQUESTED` status and the parent application's status is `UNDER_REVIEW` or `REVISION_REQUIRED`; a decision on a rider that has already been decided, or from an application in any other state, is rejected with `ERR_INVALID_STATE`, and the rider-status check is applied before the application-status check. APPROVE moves the rider `REQUESTED → APPROVED`; DENY moves it `REQUESTED → DENIED`. Both are terminal.

A coordinator verifies insurance certificates. A verification decision is either VERIFY, moving the certificate `SUBMITTED → VERIFIED`, or REJECT, moving it `SUBMITTED → REJECTED`; both require the certificate to currently be `SUBMITTED`, else the decision is rejected with `ERR_INVALID_STATE`.

Officers are scheduled through an `OfficerAssignment`, which carries an `application_id`, an `officer_id`, and a shift window of `shift_start_at` to `shift_end_at`; the shift end must be strictly after the shift start, or the assignment is rejected with `ERR_INVALID_TIME_RANGE`. An assignment may be created only when the referenced application's status is `UNDER_REVIEW` or `ISSUED`; from any other status it is rejected with `ERR_INVALID_STATE`. The referenced officer must be `ACTIVE`; an assignment against an `INACTIVE` officer is rejected with `ERR_OFFICER_INACTIVE` (HTTP 409). The shift window is then checked against the officer's existing schedule: it must not overlap any other assignment for the same `officer_id` that is still in a non-terminal status (`PROPOSED` or `CONFIRMED`); a conflict is rejected with `ERR_OFFICER_DOUBLE_BOOKED` (HTTP 409). These windows are half-open intervals `[start, end)`, so two shifts that merely touch — one ending exactly when the next begins — do not conflict, and no setup buffer is applied. For an assignment, the order of these checks is time-range, then application-state, then officer-active, then officer-overlap.

A new assignment begins in `PROPOSED` status, and its `billed_cost_cents` is computed at creation as the officer's `hourly_rate_cents` multiplied by the shift length in whole hours, where the shift length is the difference between `shift_end_at` and `shift_start_at` converted to hours and rounded up to the next whole hour. An assignment reaches `CONFIRMED` only as a side effect of its application being issued (see §3.5). A coordinator may cancel an assignment that is `PROPOSED` or `CONFIRMED`, moving it to `CANCELLED`; a cancel from any other state is rejected with `ERR_INVALID_STATE`. An assignment reaches `COMPLETED` only as a side effect of its application wrapping.

### 3.7. Neighborhood Notifications

Before a shoot, residents in the affected zones are notified. A coordinator records a `NeighborhoodNotification` for an application by supplying the `geo_zone` that was notified and the `notice_method` used, which is one of `MAILED`, `POSTED`, or `DOOR_HANGER`. The system stamps `sent_at` with the current clock value and derives `lead_days` as the whole number of days between the notice and the shoot start — specifically, the difference between the application's `shoot_start_at` and the current clock value, divided into whole 86,400-second days and rounded down. That lead time must be at least 7 days; if `lead_days` is fewer than 7, the notification is rejected with `ERR_NOTICE_TOO_LATE` (HTTP 422). At that same moment — before the request fails and while the notification is being recorded — the owning `ProductionCompany`'s `missed_notification_count` is incremented by one and no notification record is created; the increment happens when the too-late notification is recorded, not deferred to permit issuance. Notifications carry only an `id` and a `created_at`.

### 3.8. Wrapping the Shoot: Refund and Compliance

After a shoot, the applicant asks to wrap. Requesting a wrap moves the application `ISSUED → WRAP_REQUESTED` and is refused with `ERR_INVALID_STATE` from any other state. It carries one fiscal precondition: the deposit must have been paid, meaning the application's `deposit_held_cents` is at least its `deposit_cents`; if not, the wrap request is rejected with `ERR_DEPOSIT_UNPAID` (HTTP 402). A successful wrap request increments the application's `version`.

The field officer then closes the wrap, moving the application `WRAP_REQUESTED → WRAPPED`. The officer reports the `actual_end_at` (the real production end), a `damages_reported` boolean, and, when damage occurred, a `damage_cost_cents` amount; the reported `actual_end_at` is expected to be at or after the application's `issued_at`, though the server does not validate this. Wrap-close stamps `actual_end_at` from the request and stamps `damage_cost_cents` as the reported amount only when `damages_reported` is true and an amount was supplied — otherwise (damage not reported, or reported with no amount) `damage_cost_cents` is stamped as 0 — and then reconciles the deposit.

The reconciliation first computes the late-wrap penalty. The overage is the time by which `actual_end_at` exceeds `permitted_end_at`, floored at zero seconds — if the shoot ended at or before its permitted end there is no overage. That overage is converted to whole hours by rounding up to the next hour, and `late_wrap_penalty_cents` is stamped as 20,000 cents per overage hour. The refund is then the deposit currently held minus what is owed: a gross refund equal to `deposit_held_cents` minus `damage_cost_cents` minus `late_wrap_penalty_cents`. `deposit_refund_cents` is stamped as that gross refund, but never below zero — if damage plus penalty meets or exceeds the held deposit, the refund is zero. The system creates a `REFUND` `LedgerEntry` with `direction` `CREDIT` and `amount_cents` equal to `deposit_refund_cents`, and decrements `deposit_held_cents` by that same refund amount.

Wrap-close also settles the schedule and updates the company's standing. Every `OfficerAssignment` for the application that is `CONFIRMED` transitions to `COMPLETED`. If the `actual_end_at` is later than `permitted_end_at`, the owning `ProductionCompany`'s `late_wrap_count` is incremented by one. If `damage_cost_cents` is greater than zero, the company's `damage_incident_count` is incremented by one. The application's `version` increments.

A production company's `compliance_score` is a weighted standing figure derived from its three counters: starting at 100, subtract 10 points for each unit of `late_wrap_count`, 15 points for each unit of `damage_incident_count`, and 20 points for each unit of `missed_notification_count`, then clamp the result to the inclusive range from 0 to 100. This score is computed in two variants. The **PROVISIONAL** variant is derived at read time whenever a production company is fetched, using only the counters currently persisted — that is, reflecting only applications that have already closed, and excluding any open application that has not yet wrapped. The **FINAL** variant is recomputed and stored at wrap-close, immediately after that wrap's counter increments have been applied, so it already reflects the just-closed application's late-wrap and/or damage incident and is therefore no higher than the PROVISIONAL figure read before the wrap.

### 3.9. Withdrawal and the Release Cascade

An applicant may withdraw an application, driving it to the terminal `WITHDRAWN` state. Withdrawal is reachable from four states, and its side effects depend on where the application was.

From `DRAFT` or from `REVISION_REQUIRED`, withdrawal has no cascade beyond incrementing the application's `version`. From `UNDER_REVIEW`, withdrawal additionally releases every `RoadClosureBooking` for the application whose status is `PENDING` or `CONFIRMED` (moving each to `RELEASED`) and cancels every `OfficerAssignment` whose status is `PROPOSED` or `CONFIRMED`. From `ISSUED` — a surrender of a live permit — withdrawal releases every `CONFIRMED` `RoadClosureBooking` for the application, cancels every `CONFIRMED` `OfficerAssignment`, and refunds any remaining deposit: if `deposit_held_cents` is greater than zero, the system creates a `REFUND` `LedgerEntry` with `direction` `CREDIT` and `amount_cents` equal to the held amount, then sets `deposit_held_cents` to zero. Every withdrawal increments the application's `version`.

Releasing a `CONFIRMED` booking is what makes blocked competitors reachable again. When a booking that had been holding a segment is `RELEASED`, any `RoadClosureBooking` on the same `street_segment_id` that is `BLOCKED` and that no longer overlaps any remaining `CONFIRMED` booking on that segment (using the same 60-minute buffer-expanded comparison) is restored from `BLOCKED` to `PENDING`. When several blocked bookings become eligible for restoration at once, they are restored in ascending `created_at` order. Separately, whenever an application leaves the review stage into `REVISION_REQUIRED` or `WITHDRAWN`, its own still-`PENDING` bookings are moved to `RELEASED` as described in §3.3 and above.

## 4. Endpoint Definitions

All endpoints are mounted at the service root. Endpoints that create a brand-new resource respond with HTTP 201; endpoints that read a resource or modify or transition an existing one respond with HTTP 200. The request and response payloads for each endpoint are those reconstructed from the narratives in §3; the table below lists only the method, path, purpose, and the roles authorized to invoke it. "All roles" denotes the four authenticated roles `FilmOfficeCoordinator`, `ProductionCompany`, `DepartmentReviewer`, and `FieldOfficer`.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/production-companies` | Register a production company | `FilmOfficeCoordinator` |
| GET | `/production-companies/{id}` | Read a production company (compliance_score is PROVISIONAL) | All roles |
| POST | `/departments` | Create a reviewing department | `FilmOfficeCoordinator` |
| GET | `/departments/{id}` | Read a department | All roles |
| POST | `/officers` | Create an officer | `FilmOfficeCoordinator` |
| GET | `/officers/{id}` | Read an officer | All roles |
| PATCH | `/officers/{id}` | Update an officer's status (ACTIVE/INACTIVE) | `FilmOfficeCoordinator` |
| POST | `/street-segments` | Register a street segment | `FilmOfficeCoordinator` |
| GET | `/street-segments/{id}` | Read a street segment | All roles |
| POST | `/applications` | Create a draft permit application | `ProductionCompany` |
| GET | `/applications/{id}` | Read a permit application | All roles |
| GET | `/applications` | List applications, filterable by `production_company_id` and `status` | All roles |
| POST | `/applications/{id}/location-details` | Add a location to a draft/revision application | `ProductionCompany` |
| GET | `/applications/{id}/location-details` | List locations for an application | All roles |
| POST | `/applications/{id}/submit` | Submit an application for multi-department review | `ProductionCompany` |
| POST | `/applications/{id}/withdraw` | Withdraw an application (terminal) | `ProductionCompany` |
| POST | `/applications/{id}/issue` | Issue the permit; confirm bookings, stamp FINAL fee/deposit | `FilmOfficeCoordinator` |
| POST | `/applications/{id}/wrap-request` | Request wrap after the shoot | `ProductionCompany` |
| POST | `/applications/{id}/wrap-close` | Close the wrap; compute refund and update compliance | `FieldOfficer` |
| POST | `/applications/{id}/insurance-certificates` | Submit a COI (supersedes prior active COI; OCC-guarded) | `ProductionCompany` |
| GET | `/applications/{id}/insurance-certificates` | List COIs for an application | All roles |
| POST | `/insurance-certificates/{id}/verify` | Verify or reject a COI | `FilmOfficeCoordinator` |
| POST | `/applications/{id}/riders` | Add a still-photo or drone rider | `ProductionCompany` |
| GET | `/applications/{id}/riders` | List riders for an application | All roles |
| POST | `/riders/{id}/decision` | Approve or deny a rider | `FilmOfficeCoordinator` |
| POST | `/applications/{id}/notifications` | Record a neighborhood notification (lead-time enforced) | `FilmOfficeCoordinator` |
| GET | `/applications/{id}/notifications` | List notifications for an application | All roles |
| POST | `/applications/{id}/payments` | Record a permit-fee or deposit payment | `ProductionCompany` |
| GET | `/applications/{id}/payments` | List ledger entries (including system REFUND credits) | All roles |
| GET | `/department-reviews/{id}` | Read a department review | All roles |
| GET | `/department-reviews` | List reviews, filterable by `application_id`, `department_id`, `status` | All roles |
| POST | `/department-reviews/{id}/decision` | Approve, reject, or request revision on a review | `DepartmentReviewer` |
| POST | `/road-closure-bookings` | Book a street closure for an application | `ProductionCompany` |
| GET | `/road-closure-bookings/{id}` | Read a road-closure booking | All roles |
| GET | `/road-closure-bookings` | List bookings, filterable by `application_id`, `street_segment_id`, `status` | All roles |
| POST | `/officer-assignments` | Assign an officer to an application shift | `FilmOfficeCoordinator` |
| GET | `/officer-assignments/{id}` | Read an officer assignment | All roles |
| GET | `/officer-assignments` | List assignments, filterable by `application_id`, `officer_id`, `status` | All roles |
| POST | `/officer-assignments/{id}/cancel` | Cancel an officer assignment | `FilmOfficeCoordinator` |
| POST | `/_clock/set_current_utc` | Set the logical clock used for all deadline comparisons | `FilmOfficeCoordinator` |

## 5. Error Code Catalogue

The trigger conditions for each error are specified in the narratives of §2 and §3; the table below lists only the error identifier and its HTTP status code.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_TIME_RANGE` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PAYMENT_NOT_ALLOWED` | 409 |
| `ERR_NO_LOCATIONS` | 422 |
| `ERR_REVIEWS_INCOMPLETE` | 409 |
| `ERR_DEPOSIT_UNPAID` | 402 |
| `ERR_STALE_APPLICATION_VERSION` | 412 |
| `ERR_COI_NOT_VERIFIED` | 422 |
| `ERR_OFFICER_INACTIVE` | 409 |
| `ERR_AVIATION_COVERAGE_MISSING` | 422 |
| `ERR_SEGMENT_DOUBLE_BOOKED` | 409 |
| `ERR_OFFICER_DOUBLE_BOOKED` | 409 |
| `ERR_FLIGHT_WINDOW_OUTSIDE_SHOOT` | 422 |
| `ERR_NOTICE_TOO_LATE` | 422 |
| `ERR_FEE_UNPAID` | 402 |
