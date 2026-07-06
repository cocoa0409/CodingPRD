# HOA Resident Portal API — Product Requirements Document

## 1. Introduction

This document specifies the HOA Resident Portal — a back-office API that consolidates the operational surface of a homeowners' association into a single, resident-facing platform. The system unifies homeowner account management, monthly assessment billing and autopay, architectural change requests (ARC), violation reporting and appeal, amenity reservations, board motions and voting, work-order dispatch, and the community's document library.

The portal has three intertwined obligations. First, it must deliver correct **fiscal outcomes**: proration on mid-cycle onboarding, tiered late fees that reflect a homeowner's standing, ledger-consistent cascades whenever a payment is reversed, and lien placement on chronically unpaid assessments. Second, it must enforce **compliance governance**: architectural work proceeds through a board review workflow whose outcome cascades onto the property's compliance flag; violations flow through a report-confirm-fine-appeal-adjudicate pipeline in which safety fines are non-appealable; motions carry categorical scheduling constraints that prevent the community from voting on overlapping matters. Third, it must expose **residents' day-to-day amenities and civic participation**: capacity-checked reservations, ballot casting under quorum arithmetic, and access to the CC&R library.

Because a resident's standing derives from unresolved assessments across every property they own, and a property's compliance flag is influenced by both ARC approvals and unresolved violations, this API is fundamentally a **multi-party, multi-aggregate reconciliation system**. Delinquency cascades touch three aggregate roots in a single call; the ARC pipeline can auto-spawn a work order; a payment reversal can undo a homeowner's booking privilege days after the payment posted. These reconciliations must be immediate, deterministic, and observable to every role that queries a resource.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through two mandatory HTTP headers. Every request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognises four operational roles — `Homeowner`, `BoardMember`, `ComplianceOfficer`, and `HOAManager` — plus an implicit `Anonymous` actor that has no permitted operations and exists solely so that the authentication check has a well-defined negative case.

When `X-User-Role` is missing or is not one of the four operational role names above, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the role is recognised but is not among the roles authorised for the requested endpoint, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The two headers are further tied to entity identity as follows. When `X-User-Role` is `Homeowner`, `X-User-ID` is the `id` of the acting `Homeowner`; ownership checks on any resource that references a `Homeowner` (for example, an `AmenityReservation`, an `ARCRequest` submitted by that homeowner, a `Ballot` cast by them, or an `AutopayMandate` under their name) compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `BoardMember`, `X-User-ID` is likewise the `id` of a `Homeowner` — the same natural identity backbone — but the acting homeowner's `is_board_member` flag must be `true` for board-scoped operations. When `X-User-Role` is `ComplianceOfficer` or `HOAManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record this identifier on downstream artefacts (for example on a `Payment` at reversal time or on a `WorkOrder` at assignment time), but it does not compare the identifier to any entity's `id`.

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

For endpoints that return lists of resources, pagination is controlled via two query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their `created_at` timestamp in ascending order.

Paginated and non-paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource in this system — `Homeowner`, `Property`, `Assessment`, `Payment`, `AutopayMandate`, `ARCRequest`, `ARCReview`, `Violation`, `Amenity`, `AmenityReservation`, `Motion`, `Ballot`, and `WorkOrder` — carries the same four system-managed fields:

- **`id`** (string): A server-minted UUID, formatted as a plain UUID with no type prefix.
- **`created_at`** (string): An ISO 8601 UTC timestamp with three fractional digits (for example, `2026-05-24T10:30:00.123Z`) recording when the resource was first created.
- **`updated_at`** (string): An ISO 8601 UTC timestamp with three fractional digits recording the last mutation to the resource. Any change to a resource's fields — including changes to derived fields such as `total_outstanding_cents`, `standing`, or `booking_privilege` — mutates `updated_at`.
- **`version`** (integer): A system-managed integer that starts at 1 and increments by one on every mutation. This field participates in the optimistic concurrency mechanism described in §2.10.

The `Document` resource is the sole exception: it is immutable after creation and therefore carries only `id` and `created_at`. It has no `updated_at` and no `version`.

### 2.5. Nested Resource Retrieval and Path Validation

Several endpoints in this API take a hierarchical path (for example, listing reviews under an ARC request or listing ballots under a motion). For every endpoint that carries a path parameter, path parameters are validated in **strict left-to-right order**. The first path identifier that does not resolve to an existing row causes the request to be rejected immediately with `ERR_NOT_FOUND` (HTTP 404). Only after every path identifier has been resolved does the system proceed to body-referenced foreign keys; a body-level foreign key that does not resolve to an existing row is rejected with `ERR_FK_NOT_FOUND` (HTTP 404).

### 2.6. Hierarchical Consistency and Derived-Field Reconciliation

Several fields in this system are **derived**: they are not written by clients but are recomputed by the server whenever an upstream event changes their inputs. A `Property`'s `total_outstanding_cents`, its `fine_balance_cents`, its `compliance_flag`, and every `Homeowner`'s `delinquency_score`, `standing`, and `booking_privilege` are all such fields.

Whenever a state transition, payment post, payment reversal, fine, adjudication, or ARC approval alters the inputs to a derived field, the server recomputes that field within the same request, mutates the affected resource's `updated_at`, and increments its `version`. A single payment reversal that drops a `Homeowner`'s payment status below full can therefore ripple across three aggregates in one call — the `Assessment` reverts, the `Property`'s totals recompute, and the `Homeowner`'s `delinquency_score`, `standing`, and `booking_privilege` recompute — each mutation observable to any subsequent read. The property's `total_outstanding_cents` is the sum of `amount_due_cents` minus `amount_paid_cents` across every `Assessment` on the property whose `status` is `OPEN`, `PARTIALLY_PAID`, `OVERDUE`, or `DELINQUENT`, plus the sum of `fine_balance_cents` across every `Violation` on the property whose `status` is `FINED`, `APPEALED`, or `UPHELD`. The property's `fine_balance_cents` is the sum of `Violation.fine_amount_cents` across the same three statuses on that property and drops to zero for a violation that reaches `OVERTURNED`.

Homeowner `standing` is derived from `delinquency_score` (whose recipe is given in §3.2): a score below 500 places the homeowner in `GOOD_STANDING`; a score in the range 500 through 1499 inclusive places them in `MARGINAL`; a score of 1500 or greater places them in `DELINQUENT`. The homeowner's `booking_privilege` is derived from `standing` in turn: it is `ALLOWED` while `standing` is `GOOD_STANDING` or `MARGINAL`, and `FROZEN` while `standing` is `DELINQUENT`. Both fields are recomputed whenever an assessment or payment event on any property the homeowner owns changes their score.

### 2.7. Monetary Precision and Rounding

All monetary values are expressed as integer cents (`amount_due_cents`, `amount_paid_cents`, `late_fee_cents`, `fine_amount_cents`, `fine_balance_cents`, `total_outstanding_cents`, `monthly_dues_cents`, `max_charge_cents`, `cost_estimate_cents`, `fee_cents`, `amount_cents`). Internal calculations that produce fractional cents (proration, tiered late-fee scaling by standing, per-review ARC-fee contributions, delinquency-score division by 100) are rounded **half-up** at the boundary the individual calculation specifies (see §3 for the exact point per calculation). No value stored on a resource ever carries a fractional cent.

The homeowner delinquency score, uniquely, is expressed in **dollars** (integer), not cents; §3.2 gives the divide-by-100 step at which the conversion happens.

### 2.8. Priority-Ordered Validation

Every incoming request is evaluated against a fixed sequence of checks. Whichever check fails first determines the rejection code returned to the client — later checks are skipped. The sequence is:

1. **Authentication** — `X-User-Role` must be present and match one of the four operational roles from §2.1; otherwise `ERR_UNAUTHENTICATED` (HTTP 401).
2. **Authorisation** — the role must be permitted for the endpoint per the RBAC assignments in §4; otherwise `ERR_UNAUTHORIZED` (HTTP 403).
3. **Path-parameter existence** — every path-templated `id` must resolve, left-to-right; otherwise `ERR_NOT_FOUND` (HTTP 404).
4. **Body foreign-key existence** — every body-referenced foreign key must resolve; otherwise `ERR_FK_NOT_FOUND` (HTTP 404).
5. **State precondition** — the target resource must be in a state that permits the requested transition (see §3 for per-entity state machines); otherwise `ERR_INVALID_STATE` (HTTP 409).
6. **Optimistic concurrency** — where the endpoint takes a version pin (see §2.10), the pin must equal the parent's current `version`; otherwise `ERR_STALE_VERSION` (HTTP 412).
7. **Business safety gates** — including `Property.compliance_flag` not being `SUSPENDED` on ARC submit and `Homeowner.booking_privilege` not being `FROZEN` on amenity-reservation creation; otherwise `ERR_PROPERTY_SUSPENDED` (HTTP 422).
8. **Business referential** — for example, an `ARCReview` must reference a homeowner whose `is_board_member` is `true`; otherwise `ERR_REVIEWER_NOT_BOARD` (HTTP 422).
9. **Business temporal (amenity window)** — reservation times must satisfy `Amenity.reservation_window_start_hour`/`reservation_window_end_hour`, avoid `blackout_dates`, and fit within an 8-hour ceiling; otherwise `ERR_AMENITY_WINDOW_VIOLATION` (HTTP 422).
10. **Business temporal (motion window)** — the motion's window must be internally well-ordered, and no other `OPEN` motion of the same category may lie within a 24-hour buffer on either side; otherwise `ERR_MOTION_WINDOW_CONFLICT` (HTTP 422).
11. **Business constraint (amenity capacity)** — the interval-merge capacity check (see §3.6) must accept the proposed reservation; otherwise `ERR_AMENITY_CAPACITY_EXCEEDED` (HTTP 422).
12. **Business constraint (ballot uniqueness)** — at most one `Ballot` may exist per `motion_id`/`homeowner_id` pair; a second cast is rejected with `ERR_BALLOT_DUPLICATE` (HTTP 409).
13. **Business constraint (appeal category)** — a `Violation` with `category` equal to `SAFETY` may not be appealed; otherwise `ERR_APPEAL_NON_APPEALABLE` (HTTP 422).
14. **Business fiscal (overpayment)** — a payment's `amount_cents` may not push cumulative paid above the current outstanding; otherwise `ERR_OVERPAYMENT` (HTTP 422).
15. **Business fiscal (delinquent submitter)** — an ARC request may not be submitted while the submitter's `standing` is `DELINQUENT`; otherwise `ERR_HOMEOWNER_DELINQUENT` (HTTP 422).
16. **Business constraint (revision limit)** — an ARC request may not be resubmitted from `REVISION_REQUESTED` once its `revision_count` has reached 3; otherwise `ERR_REVISION_LIMIT` (HTTP 422).
17. **Business temporal (appeal window)** — a violation appeal is accepted only while the current server time is at or before `fined_at` plus 14 days; otherwise `ERR_APPEAL_WINDOW_EXPIRED` (HTTP 422).

The ordering is significant: a request that would trip checks 5 and 14 surfaces the state error (`ERR_INVALID_STATE`), not the fiscal one. Malformed payloads — a missing required field, a wrong type, an enum outside its declared set — are rejected with `ERR_INVALID_REQUEST` (HTTP 400) before the sequence begins; uniqueness collisions on `Homeowner.email` or `Property.address` are rejected with `ERR_UNIQUE_VIOLATION` (HTTP 409).

### 2.9. Time-Gated Transitions and the Logical Server Clock

Several transitions in this system depend on the passage of time: an assessment tips to `OVERDUE` at its `due_date`, then to `DELINQUENT` at 60 days past `due_date`, then becomes eligible for lien placement at 90 days past; a `FINED` violation auto-transitions to `UPHELD` more than 14 days after `fined_at` if no appeal has been lodged; a booked reservation transitions to `NO_SHOW` or `COMPLETED` once its end has been reached without or with a check-in.

To keep these transitions deterministic under test, the server maintains a **logical clock** whose value is exposed as `current_utc`. Every time-gated transition compares `current_utc` (never wall-clock time) against the relevant field on the resource. The logical clock starts at a fixed value of `2026-03-01T00:00:00Z` on server boot and is advanced only through the test-driving capability described in §3.9, which accepts a supplied `to_iso8601` value. Wall-clock fallback is explicitly not used; the server never consults the operating system clock in place of `current_utc`.

### 2.10. Optimistic Concurrency Control

A single endpoint in this API uses optimistic concurrency: creating (or superseding) a homeowner's autopay mandate. The autopay-mandate creation endpoint (see §3.3) requires the payload to include `expected_homeowner_version`, carrying the client's last observed `version` of the target `Homeowner`. If `expected_homeowner_version` does not equal the target homeowner's current `version` at the moment the create is processed, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). A successful create supersedes any active mandate and increments the homeowner's `version` by one — so the very next such request from any client using the previously-observed version will fail this check. This mechanism is framed strictly in stale-version terms: the client's request is rejected because it is based on a `Homeowner` snapshot that another writer has already advanced past, not because two requests arrived at the same instant. No other endpoint in this API takes a version pin.

## 3. Business Logic & Workflows

### 3.1. Homeowners, Properties, and the Compliance Flag

A community's roll begins with the manager registering each resident. Registering a homeowner accepts an `email` (unique across the roll, matched case-insensitively), a `full_name` for the audit trail, and an optional `is_board_member` boolean that indicates whether the acting homeowner is currently seated on the board. When `is_board_member` is not supplied, it defaults to `false`. A new homeowner is created with `standing` initialised to `GOOD_STANDING`, `delinquency_score` initialised to `0`, `booking_privilege` initialised to `ALLOWED`, and `version` initialised to `1`.

Property registration is likewise a manager-facing action: the payload provides a `homeowner_id` naming the owner of record, an `address` unique across the community, and a baseline `monthly_dues_cents` (a non-negative integer of cents). A newly registered property is initialised with `compliance_flag` set to `OPEN`, `total_outstanding_cents` set to `0`, and `fine_balance_cents` set to `0`.

The `compliance_flag` gates a homeowner's ability to submit architectural work on that property. It moves off `OPEN` in two circumstances. First, whenever an ARC request against the property is finalised as approved, the flag transitions to `APPROVED_MOD` as part of the ARC approval cascade (see §3.4). Second, once an unresolved violation on the property reaches `FINED` and has remained without an appeal or resolution for at least 60 days, the flag transitions to `SUSPENDED`. A `SUSPENDED` property may not be the target of a new ARC submission (see §3.4 for the exact rejection code).

Retrieving a homeowner returns the current derived `standing`, `delinquency_score`, and `booking_privilege`. Retrieving a property returns the current derived `total_outstanding_cents`, `fine_balance_cents`, and `compliance_flag`. Reverse-reachability listings — the properties owned by a homeowner, and the assessments, ARC requests, violations, and work orders scoped to a property — are available to the owning homeowner, board members, and the manager, with the property-scoped violation list additionally available to compliance officers.

### 3.2. Assessment Billing, Payments, Delinquency, and the Cascade

An assessment is a monthly bill against a property. The manager creates one by supplying the target `property_id`, an inclusive `billing_period_start`, an exclusive `billing_period_end` (the first instant of the following month), a `due_date` after which the bill tips into arrears (typically the billing period end plus 15 days), and an optional `prorate_from` for mid-cycle onboarding. `amount_paid_cents` and `late_fee_cents` start at `0`; the assessment's initial `status` is `OPEN`.

**Proration.** The value stamped into `amount_due_cents` at create time depends on `prorate_from`. When `prorate_from` is absent or is less than or equal to `billing_period_start`, the full-month variant applies and `amount_due_cents` equals the property's `monthly_dues_cents`. When `prorate_from` is strictly after `billing_period_start` and strictly before `billing_period_end`, the daily-prorate variant applies: the number of included days is the whole-day count from `prorate_from` (inclusive) to `billing_period_end` (exclusive), and the number of days in the period is the whole-day count from `billing_period_start` to `billing_period_end`. The raw prorated amount is `monthly_dues_cents` multiplied by included days, then divided by days in period; the value written to `amount_due_cents` is that raw amount rounded half-up to a whole cent. Once stamped, `amount_due_cents` is immutable for the life of the assessment.

**Paying an assessment.** A homeowner (or the manager acting on their behalf) records a payment against an assessment by supplying `amount_cents` (which must be strictly greater than zero) and a `method` of either `MANUAL` or `AUTOPAY`. On success the server creates a `Payment` row whose `assessment_id` links back to the target assessment (populated from the path parameter, not from the payload), with `status` set to `POSTED`, stamps `posted_at` from the server clock, increments the assessment's `amount_paid_cents` by the payment amount, and recomputes the property's `total_outstanding_cents`. If the payment leaves the assessment short of the full outstanding (that is, the sum of the new payment plus prior `amount_paid_cents` is strictly less than `amount_due_cents` plus `late_fee_cents`), the assessment transitions from `OPEN` to `PARTIALLY_PAID`; if the payment closes the remainder exactly (the sum equals `amount_due_cents` plus `late_fee_cents`), the assessment transitions to `PAID` — from either `OPEN` or `PARTIALLY_PAID`. Payment where the sum would exceed the full outstanding is rejected with `ERR_OVERPAYMENT`. When a payment closes the assessment to `PAID`, the server also recomputes the paying homeowner's `delinquency_score`, `standing`, and `booking_privilege`.

**Late fees on overdue assessments.** When the logical clock advances such that `current_utc` reaches or passes `due_date` and the assessment is still `OPEN` or `PARTIALLY_PAID`, the assessment auto-transitions to `OVERDUE` and `late_fee_cents` is stamped from the late-fee calculation described below. The property's `total_outstanding_cents` is recomputed to include the fee. When `current_utc` advances 60 days or more past `due_date` and the assessment is still `OVERDUE`, it further auto-transitions to `DELINQUENT`; this triggers a recomputation of the owning homeowner's `delinquency_score`, and — if the recomputed `standing` reaches `DELINQUENT` — sets that homeowner's `booking_privilege` to `FROZEN`. Once an assessment has sat 90 days or more past `due_date` in `DELINQUENT`, the manager may place it on lien: the assessment moves to the terminal `ON_LIEN` state. The other terminal state, `PAID`, is reached only by a completing payment.

The late-fee amount stamped at the transition to `OVERDUE` is computed as follows. The system first counts whole days overdue as the floor of the number of seconds from `due_date` to the current server clock divided by 86400, clamped at zero if the assessment is not yet past due. The outstanding amount is `amount_due_cents` minus `amount_paid_cents`. A standing multiplier is chosen from the owning homeowner's current `standing`: 1.0 when `standing` is `GOOD_STANDING`, 1.5 when `standing` is `MARGINAL`, and 2.0 when `standing` is `DELINQUENT`. A tier is chosen from days overdue against the boundaries 14, 30, and 60 days: days overdue at least 1 and strictly less than 14 selects tier 1, at least 14 and strictly less than 30 selects tier 2, at least 30 and strictly less than 60 selects tier 3, and 60 or greater selects tier 4. The tier's base fee is computed by multiplying the outstanding amount by that tier's rate (0.02 for tier 1, 0.05 for tier 2, 0.10 for tier 3, 0.15 for tier 4) and rounding half-up to a whole cent. The base fee is then multiplied by the standing multiplier and again rounded half-up to a whole cent, giving a scaled fee. The scaled fee is finally clamped: it is raised, if necessary, to the tier's floor and reduced, if necessary, to the tier's cap. The tier floors are 1000, 1000, 2500, and 5000 cents for tiers 1 through 4 respectively; the tier caps are 2500, 5000, 10000, and 25000 cents. The clamped value is written to `late_fee_cents`.

**Payment reversal and the three-aggregate cascade.** The manager may reverse a `POSTED` payment by supplying a `reversal_reason`. Reversal flips the payment's `status` to `REVERSED`, stamps `reversal_reason`, and reduces the target assessment's `amount_paid_cents` by the payment's `amount_cents`. If the assessment had been `PAID` and the reversal drops it below full, the assessment reverts: to `OVERDUE` when the logical clock has already reached or passed `due_date` (at which point `late_fee_cents` is re-stamped from the late-fee calculation above), or to `PARTIALLY_PAID` when the logical clock is still strictly before `due_date`. The property's `total_outstanding_cents` is recomputed. When the reversal moves the assessment back to `OVERDUE`, the homeowner's `delinquency_score` is recomputed and their `standing` and `booking_privilege` are re-derived; a homeowner who was previously booking amenities may find their privilege downgraded to `FROZEN` as a direct consequence of a payment reversal on a single assessment.

**The delinquency score.** A homeowner's `delinquency_score` reflects unresolved obligations across every property they own. The score has two variants, selected community-wide by the grace policy exposed in §3.9. Under the **strict** variant (in effect whenever `grace_policy` is `STRICT`), the server considers every `Assessment` on every property owned by the homeowner whose `status` is `OPEN`, `PARTIALLY_PAID`, `OVERDUE`, or `DELINQUENT`. For each such assessment, the age in whole days is the floor of the seconds between `due_date` and the current server clock divided by 86400, clamped at zero if not yet past due. A weight is chosen as one plus the integer-division of age-days by 30, multiplied by 0.5 — that is, an assessment aged less than 30 days carries weight 1.0, an assessment aged at least 30 and strictly less than 60 days carries weight 1.5, aged at least 60 and strictly less than 90 days carries weight 2.0, and so on with a step of 0.5 per additional 30-day tranche. Each assessment's contribution in cents is the outstanding plus late fee — that is, `amount_due_cents` minus `amount_paid_cents` plus `late_fee_cents` — multiplied by that weight. The contributions are summed, then that sum is divided by 100 and rounded half-up to give an integer dollar score. Under the **lenient** variant (in effect whenever `grace_policy` is `LENIENT`), the calculation is identical except that any assessment whose age is strictly less than 30 days is excluded entirely from the summation — its contribution is zero rather than weight 1.0. The two variants therefore diverge whenever a homeowner's portfolio contains at least one assessment aged between zero and 29 days inclusive. The 30-day grace window, the 500-dollar `MARGINAL` boundary, and the 1500-dollar `DELINQUENT` boundary are all fixed community constants.

### 3.3. Autopay Mandates and Concurrent Supersede Semantics

A homeowner may authorise the community to auto-charge their dues by creating an `AutopayMandate`. The create call takes an `expected_homeowner_version` and a `max_charge_cents` upper bound (a strictly positive integer of cents). On success the server flips any prior `ACTIVE` mandate for this homeowner to `SUPERSEDED`, creates the new mandate with `status` set to `ACTIVE`, and increments the homeowner's `version` by one. The mandate belongs to the acting `homeowner_id`; a homeowner may act on their own behalf, or the manager may act on theirs.

Because a fresh mandate supersedes any active one, natural semantics would permit any sequential create to succeed. The stale-version check exists to catch the case where the client has been holding a snapshot of the homeowner across a supersede they did not observe. Under the OCC rule described in §2.10, the create endpoint carries `expected_homeowner_version` as a non-optional input and rejects any mismatch with `ERR_STALE_VERSION` (HTTP 412). Two sequential creates by a client that re-reads the homeowner between calls will both succeed — the second observes the incremented `version` from the first and supplies it fresh. Only a create issued against a homeowner whose `version` has been advanced by an unobserved writer is rejected. Framed strictly in stale-version terms: the client is refused because it is acting on an out-of-date view of the homeowner, not because its request arrived contemporaneously with another.

A homeowner (or the manager) may cancel the current active mandate; the cancel operation flips its `status` to `CANCELLED` and returns no body. Listing a homeowner's mandates returns the current mandate together with any prior superseded or cancelled rows, ordered by `created_at`.

### 3.4. Architectural Review Requests (ARC): Draft, Review, Cyclic Revision, Finalise

An architectural change flows through six statuses: `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, `REVISION_REQUESTED`, and the terminal outcomes `APPROVED` and `REJECTED`. Creating an ARC request is a `Homeowner`-only action; the payload names the target `property_id`, the acting `submitter_homeowner_id` (which must equal the property's `homeowner_id` at create time), a `category` chosen from `SIMPLE`, `MEDIUM`, or `COMPLEX`, and a free-text `description` of the modification. The request is created in `DRAFT` with `revision_count` set to `0` and `fee_cents` set to `0`.

**Submission gates.** Moving a request from `DRAFT` to `SUBMITTED` succeeds only when the target property's `compliance_flag` is not `SUSPENDED` and the submitter's `standing` is not `DELINQUENT`. A submission against a suspended property is rejected with `ERR_PROPERTY_SUSPENDED`; a submission by a delinquent homeowner is rejected with `ERR_HOMEOWNER_DELINQUENT`. From `REVISION_REQUESTED` back to `SUBMITTED`, the same two cross-entity gates apply, plus the additional constraint that `revision_count` must be strictly less than 3; a resubmit past that limit is rejected with `ERR_REVISION_LIMIT`. When a resubmit succeeds from `REVISION_REQUESTED`, the prior `ARCReview` rows on this request are archived — excluded from the review sum computed at the next finalisation.

**Board review.** A `BoardMember` submits a review on a request by supplying the `reviewer_homeowner_id` (which must reference a homeowner whose `is_board_member` is `true`; otherwise `ERR_REVIEWER_NOT_BOARD`), a `weight` in the inclusive range 1 through 5 reflecting reviewer seniority, a `verdict` chosen from `APPROVE`, `REJECT`, or `REVISE`, and an optional `comment` supplying free-text rationale. The review record links back to the target request via `arc_request_id`, populated from the path parameter — clients do not supply it in the payload. The first review on a request in `SUBMITTED` auto-transitions the request to `UNDER_REVIEW`. Additional reviews accumulate against the current revision.

**Finalisation and the arc-fee calculation.** A `BoardMember` finalises an `UNDER_REVIEW` request. The outcome is determined by the current-revision review verdicts (that is, reviews created since the last resubmit, since prior reviews were archived on resubmit): if at least one current-revision verdict is `REJECT`, the request transitions to `REJECTED`; otherwise, if at least one current-revision verdict is `REVISE` and none is `REJECT`, the request transitions to `REVISION_REQUESTED` and `revision_count` is incremented by one; otherwise (every current-revision verdict is `APPROVE`), the request transitions to `APPROVED`. On both `APPROVED` and `REJECTED` — but not on `REVISION_REQUESTED` — the server stamps `fee_cents` from the arc-finalisation calculation described below.

The arc-finalisation fee is computed as follows. A base fee in cents is selected from the request's `category`: 2500 for `SIMPLE`, 10000 for `MEDIUM`, and 25000 for `COMPLEX`. For every current-revision `ARCReview` row, an unrounded per-review contribution is computed as the review's `weight` multiplied by the base fee multiplied by the fixed review rate of 0.10725. The final fee is the sum of the base fee and all unrounded per-review contributions, rounded half-up to a whole cent at the end of the summation. This evaluation order — **sum first, then round** — is pinned; the alternative of rounding each per-review contribution before summing is not used, since it produces a different total whenever any per-review contribution has a non-integer cents value.

**The approval cascade.** When a finalise transitions the request to `APPROVED`, two secondary effects fire in addition to the fee stamp. First, the target property's `compliance_flag` is set to `APPROVED_MOD` — recording that a modification has been sanctioned on that property. Second, a `WorkOrder` is auto-created against the same property with `source` set to `AUTO_ARC`, `related_property_id` set to the property's `id`, `title` set to `Post-approval inspection`, and `cost_estimate_cents` set to `0`. A `REJECTED` finalise does not trigger these cascades; only the fee stamp fires.

Reverse-reachability lists — the ARC requests filed against a property, the ARC requests submitted by a homeowner, the reviews cast by a homeowner, and the reviews on a given request — are available to the manager and to board members, with property-scoped and homeowner-scoped filings additionally available to the owning homeowner.

### 3.5. Violation Reporting, Fining, Appeal, and Adjudication

A `Violation` documents an infraction against a property and flows through seven statuses: the initial `REPORTED`, then `CONFIRMED`, then one of the terminal outcomes `CURED`, `UPHELD`, or `OVERTURNED`, with intermediate `FINED` and `APPEALED` states between confirmation and adjudication. Reporting is a shared action: compliance officers, the manager, and board members may all file a report. The payload carries `property_id` and a `category` chosen from `NUISANCE`, `LANDSCAPE`, `STRUCTURAL`, or `SAFETY`. A newly reported violation carries `status` `REPORTED` and a server-stamped `reported_at`; `fine_amount_cents`, `fine_balance_cents`, and `fined_at` start at `0`, `0`, and null respectively.

A compliance officer confirms a `REPORTED` violation, moving it to `CONFIRMED`. From `CONFIRMED`, the officer may either resolve the violation via cure (supplying an `outcome` of `CURED`), taking it to the terminal `CURED` state without a fine; or fine the violation by supplying `fine_amount_cents` in the inclusive range 2500 through 500000 cents. Fining moves the violation to `FINED`, stamps `fine_amount_cents`, sets `fine_balance_cents` to the same value, stamps `fined_at` from the server clock, and recomputes the property's `fine_balance_cents` and `total_outstanding_cents`.

**Appeal window and the safety exception.** A homeowner may appeal a `FINED` violation, moving it to `APPEALED`, only within a 14-day window: the appeal succeeds only while the current server clock is at or before `fined_at` plus 14 days; an appeal after that expiry is rejected with `ERR_APPEAL_WINDOW_EXPIRED`. In addition, a violation with `category` equal to `SAFETY` is non-appealable at any point — safety fines never enter the appeal branch, and any attempt to appeal one is rejected with `ERR_APPEAL_NON_APPEALABLE`. When the logical clock advances strictly past `fined_at` plus 14 days on a violation still in `FINED`, the server auto-transitions it to the terminal `UPHELD` state — the fine is now final without an appeal ever having been lodged.

**Adjudication.** A compliance officer adjudicates an `APPEALED` violation by supplying an `outcome` of either `UPHOLD` (transitioning to the terminal `UPHELD` state) or `OVERTURN` (transitioning to the terminal `OVERTURNED` state). An `OVERTURNED` adjudication additionally sets `fine_balance_cents` to `0` and triggers a recomputation of the property's `fine_balance_cents` and `total_outstanding_cents`; the invariant is that after an overturn the property's outstanding balance is exactly what it would have been had the fine never been assessed. An `UPHELD` adjudication leaves `fine_balance_cents` at the fined amount.

The property-scoped violation list is available to residents of that property, board members, the manager, and compliance officers.

### 3.6. Amenity Reservations: Windowing, Blackouts, and the Interval-Merge Capacity Check

Amenities such as pools and clubhouses are configured by the manager. The registration payload provides the amenity's display `name`, its total `capacity` (a strictly positive integer of simultaneous guests permitted across all overlapping reservations), a `reservation_window_start_hour` (an integer in the inclusive range 0 through 23 giving the first reservable hour of the amenity's local day), a `reservation_window_end_hour` (an integer in the inclusive range 1 through 24 giving the exclusive last hour, and required to be strictly greater than the start hour), and an optional sorted array `blackout_dates` of ISO 8601 date strings on which no reservation may start or extend into (defaulting to an empty array).

A homeowner books an amenity by supplying the target `amenity_id`, their own `homeowner_id`, the inclusive `start_ts` and exclusive `end_ts` (both ISO 8601 UTC), and the intended `guest_count` (an integer of at least 1). A newly created reservation has `status` `BOOKED`. Ownership listings — reservations filtered by `homeowner_id`, and reservations under an amenity — are available to that homeowner, board members, and the manager; the query parameter `homeowner_id` narrows the community-wide reservation listing.

**Window and blackout validation.** A candidate reservation is rejected with `ERR_AMENITY_WINDOW_VIOLATION` when `start_ts` is not strictly less than `end_ts`, or when its span exceeds 8 hours (that is, `end_ts` is strictly greater than `start_ts` plus 8 hours), or when its start hour or its end hour lies outside the amenity's `reservation_window_start_hour` through `reservation_window_end_hour` band, or when its span begins on or extends into any date listed in `blackout_dates`.

**The booking-privilege gate.** A reservation may not be created while the acting homeowner's `booking_privilege` is `FROZEN`. This is the same gate that couples amenity access to delinquency: whenever a homeowner's `standing` reaches `DELINQUENT`, their `booking_privilege` is set to `FROZEN` and subsequent reservation attempts are rejected with `ERR_PROPERTY_SUSPENDED`.

**The capacity check.** Reservation intervals are half-open on the right: a reservation ending at 12:00 and a reservation starting at 12:00 do not overlap. The server first assembles an overlap set of reservations on the same `amenity_id` whose `status` is `BOOKED` or `CHECKED_IN`, filtered to those whose `start_ts` is strictly before the candidate's `end_ts` and whose `end_ts` is strictly after the candidate's `start_ts`. It then computes the peak concurrent guest count: for each candidate boundary `t` — a value drawn from the set consisting of the candidate's own `start_ts` together with every overlapping reservation's `start_ts` — the server sums `guest_count` across every overlapping reservation whose `start_ts` is at or before `t` and whose `end_ts` is strictly after `t`, and adds the candidate's own `guest_count`. The peak across all boundary points is the concurrent guests at peak. The candidate is accepted when concurrent guests at peak is at most the amenity's `capacity`; equality is accepted; strictly greater is rejected with `ERR_AMENITY_CAPACITY_EXCEEDED`.

**Reservation lifecycle.** A homeowner (or the manager) may cancel a `BOOKED` reservation while the logical clock is strictly before `start_ts`; the reservation moves to the terminal `CANCELLED` state and the previously-consumed capacity is restored for future overlap checks — this is the compensating invariant that keeps two sequential cancel-and-rebook cycles idempotent. The manager may check a homeowner in against a `BOOKED` reservation once the logical clock has reached or passed `start_ts` and is still strictly before `end_ts`, moving it to `CHECKED_IN`. Once the logical clock reaches or passes `end_ts`, a `CHECKED_IN` reservation auto-transitions to `COMPLETED` and a `BOOKED` reservation for which no check-in occurred auto-transitions to `NO_SHOW`. Both are terminal.

### 3.7. Motions, Ballots, and the Quorum Close

A board member proposes a `Motion` by supplying a `title`, a `description`, a `category` chosen from `BUDGET`, `POLICY`, or `ELECTION`, an inclusive `voting_window_start` and inclusive `voting_window_end` (both ISO 8601 UTC, with the end strictly after the start), an `eligible_voter_count` snapshotted at motion-creation time (an integer of at least 1), and a `quorum_pct` in the inclusive range 1 through 100 giving the participation threshold in percent. A newly created motion carries `status` `OPEN`, `yes_count` and `no_count` initialised to `0`, and is subject to the category-overlap rule: within any single category, no two `OPEN` motions may have voting windows within 24 hours of one another (that is, a new motion is rejected with `ERR_MOTION_WINDOW_CONFLICT` if any existing `OPEN` motion of the same category has its own voting window overlapping the interval that extends the new motion's voting window by 24 hours on each side).

**Casting ballots.** A homeowner (or a board member acting as themselves) casts a ballot on an `OPEN` motion by supplying the acting `homeowner_id` and a `choice` of `YES`, `NO`, or `ABSTAIN`. A `YES` choice increments the motion's `yes_count`; a `NO` choice increments the motion's `no_count`; an `ABSTAIN` choice contributes to the ballots-cast count for quorum arithmetic but neither `yes_count` nor `no_count`. Any second ballot from the same homeowner on the same motion is rejected with `ERR_BALLOT_DUPLICATE`. Reverse-reachability lists — the ballots cast on a motion, the ballots cast by a homeowner (filterable by `homeowner_id` or `motion_id`), and the retrieval of a single ballot — are available to the acting homeowner, board members, and the manager.

**Closing the motion.** A board member closes an `OPEN` motion once the logical clock has reached or passed `voting_window_end`; a close attempt before that instant is rejected as an invalid state transition. The outcome is determined by ballots cast and the quorum ceiling, which is the ceiling of `eligible_voter_count` multiplied by `quorum_pct` divided by 100. When ballots cast is strictly less than the quorum ceiling, the motion transitions to the terminal `QUORUM_FAILED` state — the vote is disregarded regardless of the yes/no split. When ballots cast is at least the quorum ceiling and `yes_count` is strictly greater than `no_count`, the motion transitions to the terminal `CLOSED_PASSED` state. When ballots cast is at least the quorum ceiling and `yes_count` is at most `no_count` (that is, ties count as failures), the motion transitions to the terminal `CLOSED_FAILED` state.

### 3.8. Work Orders: Parallel Work and Payment Dimensions

A `WorkOrder` describes a piece of maintenance or improvement work. The manager may create one manually by supplying a `title`, a non-negative `cost_estimate_cents`, and an optional `related_property_id` (null denotes a community-wide work order). A manually created work order carries `source` set to `MANUAL`. Additionally, the ARC approval cascade auto-creates a work order with `source` set to `AUTO_ARC` on each approved request (see §3.4).

Work orders evolve along **two parallel dimensions** whose transitions are independent of one another once the invoice branch begins. The work dimension, `work_status`, begins at `NEW` on create. The manager assigns a vendor by supplying `assigned_vendor_id` (an opaque external identifier); this stamps the vendor and moves `work_status` to `ASSIGNED`. Starting an assigned order moves it to `IN_PROGRESS`; completing an in-progress order moves it to the terminal `COMPLETED` state. From either `NEW` or `ASSIGNED`, the manager may cancel the order — but only while the payment dimension is still `UNBILLED`; a cancel attempt with `payment_status` already `INVOICED` or `PAID` is rejected as an invalid state transition. Cancellation is terminal.

The payment dimension, `payment_status`, begins at `UNBILLED`. The manager may transition it to `INVOICED` only while `work_status` is `IN_PROGRESS` or `COMPLETED`; once `INVOICED`, the payment side may proceed to `PAID` independently — even if the work dimension is still `IN_PROGRESS`. The two dimensions may therefore terminate at different times: a work order may reach `COMPLETED` on the work axis while still `INVOICED` on the payment axis, or reach `PAID` on the payment axis while still `IN_PROGRESS` on the work axis.

Retrieval and listing of work orders is available to board members and the manager, with property-scoped listings also visible to the property's homeowner; the community-wide list accepts an optional `related_property_id` query filter.

### 3.9. Documents and Test-Driving Capabilities

The CC&R library holds reference material. A document is uploaded by the manager or by a board member with a `title`, a `category` chosen from `CCR`, `POLICY`, `MINUTES`, or `BUDGET`, and a `content_url` pointing at the stored blob. Documents are immutable after creation and therefore, per §2.4, carry only `id` and `created_at` — they do not have `updated_at` or `version`. All four operational roles may read the document library; the community-wide list accepts an optional `category` query filter.

Two administrative capabilities support deterministic time-based testing. A manager-only clock-advancement capability accepts a `to_iso8601` value and sets `current_utc` to that timestamp; advancing the logical clock past assessment `due_date` thresholds, past a `FINED` violation's 14-day appeal window, past a motion's `voting_window_end`, or past a reservation's `end_ts` fires the auto-transitions catalogued in §3.2, §3.5, §3.7, and §3.6 respectively as part of the same request. A second manager-only capability accepts a `grace_policy` scalar of either `STRICT` or `LENIENT` and switches the community-wide grace policy that selects between the two delinquency-score variants; changing the policy triggers a full recomputation of `delinquency_score`, `standing`, and `booking_privilege` for every homeowner with the newly selected variant.

## 4. Endpoint Definitions

Operations that create a new resource (a homeowner, a property, an assessment, a payment, an autopay mandate, an ARC request, an ARC review, a violation, an amenity, a reservation, a motion, a ballot, a work order, or a document) return `201 Created`. The `DELETE` operation on an autopay mandate returns `204 No Content` with an empty body. Every state-transition operation and every retrieval or list operation returns `200 OK`.

| Method | Path                                                | Description                                                                                                                | Authorized Role(s)                                     |
| ------ | --------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------ |
| POST   | `/homeowners`                                       | Register a new homeowner                                                                                                   | HOAManager                                             |
| GET    | `/homeowners/{id}`                                  | Fetch a homeowner                                                                                                          | Homeowner, BoardMember, HOAManager, ComplianceOfficer  |
| GET    | `/homeowners/{id}/properties`                       | List properties owned by this homeowner                                                                                    | Homeowner, BoardMember, HOAManager                     |
| POST   | `/homeowners/{id}/autopay-mandate`                  | Create or supersede a homeowner's autopay mandate (requires `expected_homeowner_version`)                                  | Homeowner, HOAManager                                  |
| DELETE | `/homeowners/{id}/autopay-mandate`                  | Cancel the current active mandate                                                                                          | Homeowner, HOAManager                                  |
| GET    | `/homeowners/{id}/autopay-mandate`                  | List a homeowner's autopay mandates (current plus historical)                                                              | Homeowner, HOAManager                                  |
| GET    | `/homeowners/{id}/arc-requests`                     | List ARC requests submitted by this homeowner                                                                              | Homeowner, BoardMember, HOAManager                     |
| GET    | `/homeowners/{id}/arc-reviews`                      | List ARC reviews cast by this homeowner                                                                                    | BoardMember, HOAManager                                |
| POST   | `/properties`                                       | Register a new property under an existing homeowner                                                                        | HOAManager                                             |
| GET    | `/properties/{id}`                                  | Fetch a property with computed fields                                                                                      | Homeowner, BoardMember, HOAManager, ComplianceOfficer  |
| GET    | `/properties/{id}/assessments`                      | List assessments for this property                                                                                         | Homeowner, BoardMember, HOAManager                     |
| GET    | `/properties/{id}/arc-requests`                     | List ARC requests filed against this property                                                                              | Homeowner, BoardMember, HOAManager                     |
| GET    | `/properties/{id}/violations`                       | List violations filed against this property                                                                                | Homeowner, BoardMember, HOAManager, ComplianceOfficer  |
| GET    | `/properties/{id}/work-orders`                      | List work orders scoped to this property                                                                                   | Homeowner, BoardMember, HOAManager                     |
| POST   | `/assessments`                                      | Create a new assessment for a property (runs proration to stamp `amount_due_cents`)                                        | HOAManager                                             |
| GET    | `/assessments/{id}`                                 | Fetch an assessment                                                                                                        | Homeowner, BoardMember, HOAManager                     |
| POST   | `/assessments/{id}/pay`                             | Record a payment against an assessment (triggers state transitions and delinquency cascade)                                | Homeowner, HOAManager                                  |
| POST   | `/assessments/{id}/place-lien`                      | Move a `DELINQUENT` assessment (>= 90 days past `due_date`) to `ON_LIEN`                                                   | HOAManager                                             |
| GET    | `/assessments/{id}/payments`                        | List payments against this assessment                                                                                      | Homeowner, BoardMember, HOAManager                     |
| GET    | `/payments/{id}`                                    | Fetch a payment                                                                                                            | Homeowner, BoardMember, HOAManager                     |
| POST   | `/payments/{id}/reverse`                            | Reverse a `POSTED` payment (cascades to assessment, property, and homeowner)                                               | HOAManager                                             |
| POST   | `/arc-requests`                                     | Create a `DRAFT` ARC request                                                                                               | Homeowner                                              |
| GET    | `/arc-requests/{id}`                                | Fetch an ARC request                                                                                                       | Homeowner, BoardMember, HOAManager                     |
| POST   | `/arc-requests/{id}/submit`                         | Submit or resubmit an ARC request (cyclic from `REVISION_REQUESTED`)                                                       | Homeowner                                              |
| POST   | `/arc-requests/{id}/reviews`                        | Board member submits a review on an ARC request                                                                            | BoardMember                                            |
| GET    | `/arc-requests/{id}/reviews`                        | List reviews on this ARC request                                                                                           | Homeowner, BoardMember, HOAManager                     |
| POST   | `/arc-requests/{id}/finalize`                       | Finalise an `UNDER_REVIEW` request (stamps `fee_cents` and cascades on approve)                                            | BoardMember                                            |
| POST   | `/violations`                                       | Report a new violation on a property                                                                                       | ComplianceOfficer, HOAManager, BoardMember             |
| GET    | `/violations/{id}`                                  | Fetch a violation                                                                                                          | Homeowner, BoardMember, HOAManager, ComplianceOfficer  |
| POST   | `/violations/{id}/confirm`                          | Confirm a `REPORTED` violation                                                                                             | ComplianceOfficer                                      |
| POST   | `/violations/{id}/fine`                             | Assess a fine on a `CONFIRMED` violation                                                                                   | ComplianceOfficer                                      |
| POST   | `/violations/{id}/appeal`                           | Homeowner appeals a `FINED` violation within 14 days (non-appealable if `SAFETY`)                                          | Homeowner                                              |
| POST   | `/violations/{id}/adjudicate`                       | Compliance officer decides an `APPEALED` violation (`outcome` = `UPHOLD` or `OVERTURN`)                                    | ComplianceOfficer                                      |
| POST   | `/violations/{id}/resolve`                          | Resolve a `CONFIRMED` violation via cure (no fine; `outcome` = `CURED`)                                                    | ComplianceOfficer                                      |
| POST   | `/amenities`                                        | Register a bookable amenity                                                                                                | HOAManager                                             |
| GET    | `/amenities/{id}`                                   | Fetch an amenity                                                                                                           | Homeowner, BoardMember, HOAManager                     |
| POST   | `/amenity-reservations`                             | Reserve a slot on an amenity (runs interval-overlap capacity check)                                                        | Homeowner                                              |
| GET    | `/amenities/{id}/reservations`                      | List reservations on this amenity                                                                                          | Homeowner, BoardMember, HOAManager                     |
| GET    | `/amenity-reservations`                             | List reservations, filterable by `homeowner_id`                                                                            | Homeowner, BoardMember, HOAManager                     |
| GET    | `/amenity-reservations/{id}`                        | Fetch an amenity reservation                                                                                               | Homeowner, BoardMember, HOAManager                     |
| POST   | `/amenity-reservations/{id}/cancel`                 | Cancel a `BOOKED` reservation before `start_ts`                                                                            | Homeowner, HOAManager                                  |
| POST   | `/amenity-reservations/{id}/check-in`               | Check in a homeowner at the amenity                                                                                        | HOAManager                                             |
| POST   | `/motions`                                          | Create a motion for voting (validates window and category overlap)                                                         | BoardMember                                            |
| GET    | `/motions/{id}`                                     | Fetch a motion                                                                                                             | Homeowner, BoardMember, HOAManager                     |
| POST   | `/motions/{id}/ballots`                             | Cast a ballot on an `OPEN` motion (unique per motion + homeowner)                                                          | Homeowner, BoardMember                                 |
| GET    | `/motions/{id}/ballots`                             | List ballots on this motion                                                                                                | Homeowner, BoardMember, HOAManager                     |
| GET    | `/ballots`                                          | List ballots filterable by `homeowner_id` or `motion_id`                                                                   | Homeowner, BoardMember, HOAManager                     |
| GET    | `/ballots/{id}`                                     | Fetch a ballot                                                                                                             | Homeowner, BoardMember, HOAManager                     |
| POST   | `/motions/{id}/close`                               | Close a motion after `voting_window_end` (chooses `CLOSED_PASSED`, `CLOSED_FAILED`, or `QUORUM_FAILED`)                    | BoardMember                                            |
| POST   | `/work-orders`                                      | Create a new work order (community-wide if `related_property_id` null)                                                     | HOAManager                                             |
| GET    | `/work-orders/{id}`                                 | Fetch a work order                                                                                                         | Homeowner, BoardMember, HOAManager                     |
| GET    | `/work-orders`                                      | List work orders, filterable by `related_property_id`                                                                      | BoardMember, HOAManager                                |
| POST   | `/work-orders/{id}/assign`                          | Assign a vendor to a `NEW` work order                                                                                      | HOAManager                                             |
| POST   | `/work-orders/{id}/start`                           | Start work on an `ASSIGNED` work order                                                                                     | HOAManager                                             |
| POST   | `/work-orders/{id}/complete`                        | Mark an `IN_PROGRESS` work order `COMPLETED`                                                                               | HOAManager                                             |
| POST   | `/work-orders/{id}/cancel`                          | Cancel a `NEW` or `ASSIGNED` work order (`payment_status` must be `UNBILLED`)                                              | HOAManager                                             |
| POST   | `/work-orders/{id}/invoice`                         | Move `payment_status` `UNBILLED` to `INVOICED`                                                                             | HOAManager                                             |
| POST   | `/work-orders/{id}/mark-paid`                       | Move `payment_status` `INVOICED` to `PAID`                                                                                 | HOAManager                                             |
| POST   | `/documents`                                        | Upload a document to the CC&R library                                                                                      | HOAManager, BoardMember                                |
| GET    | `/documents`                                        | List documents, filterable by `category`                                                                                   | Homeowner, BoardMember, HOAManager, ComplianceOfficer  |
| GET    | `/documents/{id}`                                   | Fetch a document                                                                                                           | Homeowner, BoardMember, HOAManager, ComplianceOfficer  |
| POST   | `/_clock/set_current_utc`                           | Advance the logical clock to a supplied ISO 8601 UTC timestamp (`to_iso8601`)                                              | HOAManager                                             |
| POST   | `/_config/grace-policy`                             | Set community-wide `grace_policy` (`STRICT` or `LENIENT`)                                                                  | HOAManager                                             |

## 5. Error Code Catalogue

| Error ID                              | HTTP Status Code       |
| ------------------------------------- | ---------------------- |
| `ERR_UNAUTHENTICATED`                 | 401 Unauthorized       |
| `ERR_UNAUTHORIZED`                    | 403 Forbidden          |
| `ERR_NOT_FOUND`                       | 404 Not Found          |
| `ERR_FK_NOT_FOUND`                    | 404 Not Found          |
| `ERR_INVALID_STATE`                   | 409 Conflict           |
| `ERR_STALE_VERSION`                   | 412 Precondition Failed |
| `ERR_PROPERTY_SUSPENDED`              | 422 Unprocessable Entity |
| `ERR_REVIEWER_NOT_BOARD`              | 422 Unprocessable Entity |
| `ERR_AMENITY_WINDOW_VIOLATION`        | 422 Unprocessable Entity |
| `ERR_AMENITY_CAPACITY_EXCEEDED`       | 422 Unprocessable Entity |
| `ERR_MOTION_WINDOW_CONFLICT`          | 422 Unprocessable Entity |
| `ERR_BALLOT_DUPLICATE`                | 409 Conflict           |
| `ERR_APPEAL_NON_APPEALABLE`           | 422 Unprocessable Entity |
| `ERR_APPEAL_WINDOW_EXPIRED`           | 422 Unprocessable Entity |
| `ERR_OVERPAYMENT`                     | 422 Unprocessable Entity |
| `ERR_HOMEOWNER_DELINQUENT`            | 422 Unprocessable Entity |
| `ERR_REVISION_LIMIT`                  | 422 Unprocessable Entity |
| `ERR_INVALID_REQUEST`                 | 400 Bad Request        |
| `ERR_UNIQUE_VIOLATION`                | 409 Conflict           |
