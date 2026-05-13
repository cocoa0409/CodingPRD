# Domestic Service Dispatch API — Product Requirements Document

## 1. Introduction

The Domestic Service Dispatch platform connects households with vetted in-home service personnel — cleaners, cooks, childcare workers, and elder-care attendants — and coordinates the entire lifecycle from booking to settlement. Customers browse a catalogue of service items, book single or recurring appointments, and rate the work that is delivered to their door. Service personnel build a profile, obtain certifications, accept dispatches that match their geographic radius and skills, check in on-site, and earn commissions and tier-based bonuses. Behind the scenes, a platform operations team approves credentials, runs the dispatch selector, handles refunds, and shepherds insurance claims through their lifecycle.

The system has to reconcile several tensions that are characteristic of two-sided home-service marketplaces. First, it must guarantee that every personnel record sent to a customer's home is identity-verified, currently certified, medically fit to work, and contractually qualified for the requested skill. Second, it must reconcile customer preferences (gender, age band, language) and hard geographic limits with personnel availability and workload at the moment of dispatch — a question that has no clean answer unless the eligibility rules and the tie-break ordering are written down once and applied identically every time. Third, the settlement contract has to behave correctly across two timestamps separated by a customer-acceptance window during which a low rating may demote the personnel's tier and shift the bonus.

This document specifies the REST API mounted under `/dsd` that implements those rules. All requests and responses use JSON. The remainder of the document defines the global contract (authentication, response envelope, pagination, cross-cutting concerns), the business workflows that govern every entity's lifecycle, the table of endpoints, and the error catalogue.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` (the caller's identifier) and `X-User-Role` (one of the four roles defined below). A request that omits or mis-spells either header is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted to invoke the requested endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

The four roles are spelled exactly as `Customer`, `ServicePersonnel`, `PlatformOperator`, and `system`.

- When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` compare the resource's foreign-key field (for example, `Order.customer_id`) to `X-User-ID`.
- When `X-User-Role` is `ServicePersonnel`, `X-User-ID` is the `id` of the acting `ServicePersonnel`; ownership checks on any resource that references a `ServicePersonnel` compare the resource's foreign-key field (for example, `Order.assigned_personnel_id`) to `X-User-ID`.
- When `X-User-Role` is `PlatformOperator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `actor_id` on `AuditLogEntry` when an operator-triggered transition writes an audit row) but does not compare it to any entity's `id`.
- When `X-User-Role` is `system`, `X-User-ID` is an opaque internal identifier used by test-driving endpoints and inbound webhooks. It is likewise not tied to any persisted entity.

When a `ServicePersonnel` invokes an order-action endpoint (accept, reject, check-in, complete, execution update), the server additionally verifies that `Order.assigned_personnel_id` equals `X-User-ID`; a mismatch is rejected with `ERR_NOT_ASSIGNED` (HTTP 403). The authentication checks (presence of `X-User-Role` and RBAC eligibility) are the first two gates in the validation pipeline and run before any path-parameter or business-rule evaluation. Internal sweep and clock endpoints (`/dsd/_clock/advance`, `/dsd/_sweep/*`) bypass the `X-User-Role` presence check but still enforce role restrictions when a header is supplied.

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

List endpoints accept two query parameters: `limit` and `offset`. The default `limit` is 10; the minimum is 1; the maximum is 100. The default `offset` is 0. List endpoints sort their results by `created_at` ascending. The pagination metadata exposed in the success envelope's `meta` block consists of `limit`, `offset`, `total_count` (the unfiltered total matching the query), and `has_more` (true when more rows exist past the current window).

### 2.4. Common Resource Properties

Every entity in this system carries a server-minted `id`. The `id` is a UUID with no type prefix — it is a bare UUID string, not a slug or a typed identifier. Most entities additionally carry `created_at`, `updated_at`, and `version`. The timestamps are ISO 8601 UTC values rendered to three fractional digits of precision (the same format used by `api_request_timestamp`). The `version` field is a positive integer that starts at 1 on creation and increments by exactly 1 on every mutation that changes the entity's persisted state.

Three entities — `ServiceExecution`, `AbnormalEvent`, `OrderRating`, `SettlementLedgerEntry`, and `AuditLogEntry` — are append-only in spirit and carry only `id` and `created_at`. They have no `updated_at` field and no `version` field, and they are not subject to optimistic concurrency control.

### 2.5. Optimistic Concurrency Control

Any `PATCH` endpoint that mutates an entity carrying a `version` field accepts an optional `version` in its request body. When `version` is supplied, it must equal the entity's currently persisted `version`; a mismatch is rejected with `ERR_VERSION_CONFLICT` (HTTP 409). When `version` is omitted from the request body, the server performs the mutation without a version check. A successful mutation increments the persisted `version` by one and refreshes `updated_at` to the server's current time.

### 2.6. Path Resolution

Where an endpoint includes one or more path parameters (for example, `/dsd/personnel/{id}/certifications`), the server resolves them strictly left-to-right. If a referenced entity does not exist, the request is rejected with `ERR_NOT_FOUND` (HTTP 404), and resolution stops at the first missing entity — the right-hand path segments are not consulted.

### 2.7. Validation Pipeline Ordering

When several validations can fire on the same request, they are evaluated in a fixed order so that the most fundamental failure surfaces first. Authentication (the `X-User-Role` presence check that returns `ERR_UNAUTHENTICATED`) is evaluated before role permission (`ERR_FORBIDDEN`). Role permission is evaluated before path-parameter existence (`ERR_NOT_FOUND`). Path-parameter existence is evaluated before any state check (`ERR_INVALID_STATE`) that compares the entity's current state to the source state of the requested transition. State checks precede ownership checks such as the personnel-assignment guard returning `ERR_NOT_ASSIGNED`. Ownership checks precede business-safety checks (for example, the on-site check-in face/location validation returning `ERR_CHECKIN_LOCATION_MISMATCH`). Business-safety checks precede business-referential checks such as area service and item activity (`ERR_AREA_NOT_SERVICED`, `ERR_ITEM_INACTIVE`). Business-referential checks precede business-temporal checks (lead-time, modification window, cancellation window, complaint window, dispatch deadline). Business-temporal checks precede business-constraint checks (eligibility, checklist completeness, evidence sufficiency, rating range, certification thresholds, active-assignments guard). Business-constraint checks precede business-fiscal checks (manual reassignment eligibility, OCC version comparison). Uniqueness constraints — one rating per order, one execution per order — fire last because they detect collisions that only matter once everything else has passed.

### 2.8. Hierarchical Consistency and Cascading Side Effects

Several transitions in this system propagate mutations across multiple entities. Every cascade updates `updated_at` and increments `version` on each affected entity that carries those fields. When the recertification sweep transitions a personnel from `ACTIVE` to `SUSPENDED` because health certification has lapsed or no `ACTIVE` `SkillCertification` remains, every `Order` currently assigned to that personnel in `DISPATCHED` state is reverted to `PENDING_DISPATCH`, its `assigned_personnel_id` is cleared, and an `AuditLogEntry` with `action_type` set to `DISPATCH_EXPIRED` is appended. When a personnel record is disqualified, every linked `SkillCertification` in `ACTIVE` state transitions to `REVOKED`, and the personnel's derived `skill_tags` view is refreshed to the empty array because no `ACTIVE` certification remains. When a `SkillCertification` expires through the recertification sweep, the personnel's `skill_tags` is recomputed (the corresponding tag is removed if no other `ACTIVE` certification covers it), and if `skill_tags` becomes empty while `status` is `ACTIVE`, the same sweep transitions the personnel from `ACTIVE` to `SUSPENDED` in the same pass.

### 2.9. Geographic Distance and Service Radius

Distances in this system are great-circle distances computed via the haversine formula between two latitude/longitude pairs, expressed in kilometres to six decimal places of precision. Two distance gates appear in the workflow rules: the dispatch selector requires that the haversine distance between a personnel's home base (`service_lat`, `service_lng`) and the customer's service address (`address_lat`, `address_lng`) be less than or equal to the personnel's `service_radius_km`, and on-site check-in requires that the haversine distance between the submitted check-in coordinates (`checkin_lat`, `checkin_lng`) and the customer's address be at most 0.2 kilometres.

### 2.10. Monetary Precision and Tier Rounding

All monetary values in this system are tracked as integer cents and stored in `*_cents` fields (`base_price_cents`, `gross_price_cents`, `amount_cents`, `claimed_amount_cents`, `paid_amount_cents`, `wallet_credit_cents`). Where a calculation produces a non-integer intermediate result — provisional commission, final commission with bonus, payout tax — the final cent value is rounded half-up to zero decimal places. Composite scores and personnel rating scores are rounded half-up to four decimal places. Tier-floor comparisons are performed against the four-decimal `rating_score`, and every comparison uses the inclusive form: a `rating_score` exactly equal to a floor places the personnel at that tier.

### 2.11. Audit Trail

A subset of high-impact actions is recorded in an append-only `AuditLogEntry` stream. Each entry captures an `action_type` chosen from `DISPATCH`, `REASSIGN`, `DISPATCH_EXPIRED`, `CLAIM_REPORTED`, `CLAIM_FILED`, `CLAIM_APPROVED`, `CLAIM_REJECTED`, and `CLAIM_PAID`; a `subject_type` of either `Order` or `InsuranceClaim`; the `subject_id` of the affected entity; the `actor_role` and `actor_id` of the caller; and a `payload` JSON object snapshotting the relevant fields at the moment of the action. Audit rows are written as part of the same logical operation that causes the transition — they cannot be detached from the action they describe.

### 2.12. Event-Driven External Synchronization

The platform synchronizes with external systems via inbound webhooks for the payment processor and the insurance company. The payment webhook records that a payment was received for a given `order_id` and `amount_cents` without altering the order's lifecycle state. The insurance webhook accepts the insurer's decision payload (`claim_id`, `decision`, `amount_cents`) and drives `InsuranceClaim` from `FILED` to either `APPROVED` or `REJECTED`. When the insurance claim leaves `EVIDENCE_PENDING` for `FILED`, the platform emits an outbound event to the insurance company carrying the claim payload — this is the cue that asks the insurer to render a decision.

## 3. Business Logic & Workflows

### 3.1. Personnel Onboarding and Lifecycle

A `ServicePersonnel` record is the heart of supply in this system. An operator creates the profile with the personnel's `full_name`, `gender`, `age`, list of spoken `languages`, home-base coordinates `service_lat` and `service_lng`, the maximum reach `service_radius_km` (defaulting to 10 if not supplied), and a `health_cert_expires_at` timestamp. `age` is constrained to be at least 18 and no greater than 70. `gender` must be either `MALE` or `FEMALE`. On creation, `status` starts at `PENDING_VERIFICATION`, `identity_verified` is false, `rating_score` is 0, `rating_count` is 0, `workload_active_orders` is 0, `tier` is `BRONZE`, and `last_recert_at` is null. The personnel's `skill_tags` view is a derived projection of the `SkillCertification` table — it lists exactly those skill tags for which at least one `ACTIVE` certification exists, and it is refreshed every time a certification's state changes.

An operator marks identity by verifying a submitted document and flipping `identity_verified` to true. Once `identity_verified` is true, the health certificate is still in date (the current time is strictly before `health_cert_expires_at`), and at least one `ACTIVE` `SkillCertification` exists for this personnel, the operator can activate the record, transitioning it from `PENDING_VERIFICATION` to `ACTIVE`; activation also recomputes the personnel's `tier`. If any of these three preconditions is unmet, the transition is rejected with `ERR_INVALID_STATE`.

An active personnel record can be paused or terminated. Suspension drives `ACTIVE` to `SUSPENDED`, but only if no `Order` assigned to this personnel is currently in `DISPATCHED`, `ACCEPTED`, or `IN_PROGRESS`; a suspend attempt against a personnel with active assignments is rejected with `ERR_HAS_ACTIVE_ASSIGNMENTS`. Disqualification drives `ACTIVE` to `DISQUALIFIED` under the same active-assignments precondition and additionally revokes every linked `SkillCertification` that was in `ACTIVE` status, transitioning each one to `REVOKED` and recomputing `skill_tags` to the empty array — `DISQUALIFIED` is a terminal state. A suspended personnel can be reinstated to `ACTIVE` provided the health certificate is still in date and at least one `ACTIVE` `SkillCertification` still exists; reinstatement also recomputes `tier`.

### 3.2. Certifications and the Recertification Sweep

A `SkillCertification` couples a personnel to one of four `skill_tag` values — `CLEANING`, `COOKING`, `CHILDCARE`, or `ELDERCARE` — and is the only artifact that grants a personnel the right to be matched against service items requiring that skill. Each certification carries the foreign-key `personnel_id`, the `skill_tag` being certified, an integer-or-decimal `training_hours` count, an `expires_at` timestamp, and a `status` that begins at `PENDING`. The `certified_at` timestamp is filled in by the server when the certification is approved.

Approval drives a certification from `PENDING` to `ACTIVE`. Approval requires `training_hours` to be at least 8 and `expires_at` to be strictly in the future; if either precondition fails, the approval is rejected with `ERR_CERT_REQUIREMENTS_NOT_MET`. On approval, the server stamps `certified_at` to the current time and recomputes the personnel's `skill_tags` view to include this newly active skill tag. Revocation drives a certification from `ACTIVE` to `REVOKED` and likewise refreshes `skill_tags` on the personnel. A certification can also leave `ACTIVE` via the recertification sweep, which expires any cert whose `expires_at` has passed and refreshes the affected personnel's `skill_tags`. Expiration and revocation are both terminal states for a certification.

The recertification sweep is a system-driven pass that walks every personnel and every certification. For each personnel, if the current time is at or beyond `health_cert_expires_at` — that is, the inclusive comparison `current_time >= health_cert_expires_at` holds — or if no `ACTIVE` certification remains, the personnel is moved from `ACTIVE` to `SUSPENDED`. Any `Order` that was `DISPATCHED` to that personnel reverts to `PENDING_DISPATCH`, its `assigned_personnel_id` is cleared, and an `AuditLogEntry` with `action_type` of `DISPATCH_EXPIRED` is appended for each reverted order. For each `ACTIVE` certification whose `expires_at` has been reached or passed (`current_time >= expires_at`), the certification moves to `EXPIRED`, the personnel's `skill_tags` is recomputed, and — if `skill_tags` becomes empty while the personnel is still in `ACTIVE` — the same sweep continues the cascade by suspending the personnel and reverting any dispatched orders as above. `last_recert_at` is updated to the current time at the end of the pass.

### 3.3. Service Catalogue and Customer Profiles

Every booking begins with two ingredients: a `Customer` profile and a `ServiceItem` from the catalogue. An operator creates a service item with a display `name`, the `required_skill_tag` a personnel must hold to serve it, a `base_price_cents` per hour expressed in integer cents, a `min_duration_hours` (default 1), an array of permitted `service_areas` codes such as `CN-11-001`, and an `active` flag (default true). Operators can later patch `base_price_cents`, `service_areas`, or `active` on an existing item; an inactive item rejects new orders but does not affect existing ones. The catalogue listing accepts `area_code` and `active` filters in addition to pagination.

A `Customer` profile records `full_name`, `area_code`, the customer's service location coordinates `address_lat` and `address_lng`, and four optional preference fields: `pref_gender` (one of `MALE`, `FEMALE`, or null), `pref_min_age` and `pref_max_age` (integer or null), and `pref_language` (a language code string or null). A null preference is treated as "no preference" and is silently skipped during eligibility filtering. The `wallet_credit_cents` balance tracks the customer's refundable credit in integer cents; it is incremented when a cancellation or refund posts a credit and decremented only when redeemed against a future order. Wallet credit is an invariant under settlement reversal — the same refund that reverses a personnel's commission also adds back to `wallet_credit_cents`.

### 3.4. Order Submission, Modification, and the Lead-Time Rule

An `Order` is the work unit that flows through the dispatch and execution pipeline. A customer (or an operator acting on their behalf) creates an order with a `customer_id`, a `service_item_id`, a `mode` of either `SINGLE` or `RECURRING`, a `scheduled_start_at` timestamp, and a `duration_hours` value. The duration is always a multiple of 0.5 hours. The order begins in `DRAFT`. The `gross_price_cents` field starts at zero and is computed on submission.

Submitting an order drives it from `DRAFT` to `PENDING_DISPATCH`. Submission performs four preconditions: the customer's `area_code` must appear in the service item's `service_areas` list; the service item's `active` flag must be true; `scheduled_start_at` must be at least one hour in the future (the inclusive comparison is `scheduled_start_at >= current_time + 1 hour`); and `duration_hours` must be at least the service item's `min_duration_hours`. The same area and active-item checks apply when creating an order or recurring order in the first place. The lead-time violation surfaces as `ERR_LEAD_TIME_TOO_SHORT`, the area violation as `ERR_AREA_NOT_SERVICED`, and an inactive-item attempt as `ERR_ITEM_INACTIVE`. On successful submission, the server computes `gross_price_cents` as the service item's `base_price_cents` multiplied by `duration_hours` — because the base price is an integer cent value and `duration_hours` is always a multiple of 0.5, the product is always an integer cent value and no rounding step is needed.

Modification is allowed while the order is still in `PENDING_DISPATCH` and only outside the modification window. Specifically, modification is permitted exactly when the current time is more than 12 hours before `scheduled_start_at` — that is, `current_time < scheduled_start_at - 12 hours`. A modification attempt that falls inside the 12-hour window or against an order not in `PENDING_DISPATCH` is rejected with `ERR_MODIFY_WINDOW_CLOSED`. Modification can change `scheduled_start_at` and/or `duration_hours` and accepts an optional `version` in the request body for optimistic concurrency. When `duration_hours` is updated, `gross_price_cents` is recomputed accordingly.

A `RecurringOrder` is a parent template for repeated bookings under the same customer and service item with a cadence of 1, 7, 14, or 30 days. It carries `cadence_days`, a `first_start_at` timestamp for the first occurrence, the per-occurrence `duration_hours`, an `occurrences_generated` counter tracking how many `Order` rows have been materialized, and a `status` of `ACTIVE`, `PAUSED`, or `TERMINATED`. Each materialized occurrence carries `recurring_order_id` pointing back to the parent; for `SINGLE` orders, `recurring_order_id` is null. A recurring order can be paused and resumed during its life; termination is final.

### 3.5. Dispatch Selection and the Re-dispatch Loop

Dispatching transitions an order from `PENDING_DISPATCH` to `DISPATCHED`. The selection algorithm is a deterministic two-step procedure run against the `ServicePersonnel` set. Step one applies an eligibility filter that retains only personnel for whom every one of the following conditions holds: the personnel's `status` is `ACTIVE`; the personnel's `id` is not in the order's in-memory exclusion set built up by prior rejections; the service item's `required_skill_tag` appears in the personnel's `skill_tags` (active skills only); the personnel's `health_cert_expires_at` is strictly in the future; the haversine distance between the personnel's home base (`service_lat`, `service_lng`) and the customer's address (`address_lat`, `address_lng`) is at most the personnel's `service_radius_km`; the personnel's `workload_active_orders` is strictly fewer than 5; if the customer expressed a `pref_gender`, the personnel's `gender` matches; if the customer expressed a `pref_min_age`, the personnel's `age` is at least that minimum; if the customer expressed a `pref_max_age`, the personnel's `age` is at most that maximum; and if the customer expressed a `pref_language`, that language code appears in the personnel's `languages` array. Null preferences are skipped — they do not exclude anyone.

Step two sorts the surviving pool by a composite rank key with three components, applied in this order from most significant to least: first by a tier priority where `PLATINUM` is 4, `GOLD` is 3, `SILVER` is 2, and `BRONZE` is 1, sorted descending so higher tiers rank earlier; then by `rating_score` sorted descending so higher-rated personnel rank earlier; then by the distance from personnel home base to the customer address sorted ascending so closer personnel rank earlier. Any remaining ties are broken by the personnel's `id` sorted in ascending ASCII order to guarantee a stable outcome. The first element of the sorted survivor list is the assignment.

When the eligibility filter empties, the dispatch is rejected with `ERR_NO_ELIGIBLE_PERSONNEL`. Otherwise the order's `assigned_personnel_id` is set to the chosen personnel; `dispatch_round` is incremented by one (it starts at zero on submission, so the first dispatch reads `1`, the second `2`, and so on); `dispatch_deadline_at` is set to the current time plus 15 minutes; the chosen personnel's `workload_active_orders` is incremented by one; and an `AuditLogEntry` with `action_type` of `DISPATCH` is appended.

The assigned personnel must respond before the deadline. Accepting drives the order from `DISPATCHED` to `ACCEPTED` and requires both that `X-User-ID` equal `Order.assigned_personnel_id` (otherwise `ERR_NOT_ASSIGNED`) and that the current time be strictly less than `Order.dispatch_deadline_at`. An accept attempt past the deadline is rejected with `ERR_DISPATCH_DEADLINE_PASSED`. Rejecting also requires that `X-User-ID` equal `Order.assigned_personnel_id`; on rejection, the order reverts from `DISPATCHED` to `PENDING_DISPATCH`, the assignee's `workload_active_orders` is decremented by one, `assigned_personnel_id` is cleared, the previous personnel is added to the order's in-memory exclusion set so the next dispatch will not pick them, and an `AuditLogEntry` with `action_type` of `DISPATCH_EXPIRED` is appended. If the deadline passes with no response and the test-driving clock advance fires, the same transition occurs system-driven: the order returns to `PENDING_DISPATCH`, `workload_active_orders` is decremented for the previous assignee, `assigned_personnel_id` is cleared, and a `DISPATCH_EXPIRED` audit row is appended.

An operator can override the selector by manually reassigning a `PENDING_DISPATCH` order. The reassignment endpoint accepts a `personnel_id` in its body and re-runs the eligibility predicate against just that candidate; if the candidate fails the filter, the request is rejected with `ERR_PERSONNEL_NOT_ELIGIBLE`. On success, `assigned_personnel_id` is set to the body's `personnel_id`, `dispatch_round` is incremented by one, `dispatch_deadline_at` is set to the current time plus 15 minutes, the chosen personnel's `workload_active_orders` is incremented, and an `AuditLogEntry` with `action_type` of `REASSIGN` is appended.

Two concurrency situations are pinned by these rules. When two personnel attempt to accept the same `DISPATCHED` order at the same time, the first writer wins; the loser sees the order is no longer `DISPATCHED` and is rejected with `ERR_INVALID_STATE`. When an operator reassignment fires against the same order that the assignee is accepting, first-writer-wins on `Order.assigned_personnel_id` likewise serializes the operations — if the accept lands first, the reassign loses with `ERR_INVALID_STATE` (the state is already `ACCEPTED`); if the reassign lands first, the accept loses with `ERR_INVALID_STATE` (the assignee has changed). The third concurrency scenario, customer cancellation racing with personnel check-in, also serializes first-writer-wins on `Order.status`; whichever lands first wins, and the loser sees `ERR_INVALID_STATE`.

### 3.6. On-Site Execution and Completion

Once an order is `ACCEPTED`, the assigned personnel must check in on-site to begin service. Check-in drives the order from `ACCEPTED` to `IN_PROGRESS` and creates exactly one `ServiceExecution` row keyed by the order's `id`. The request body carries `checkin_lat`, `checkin_lng`, and `checkin_face_passed`. The transition's preconditions are that `X-User-ID` equal `Order.assigned_personnel_id`, that `checkin_face_passed` be true, that the haversine distance between the submitted coordinates and the customer's `address_lat`/`address_lng` be at most 0.2 kilometres, and that the current time be at or beyond `scheduled_start_at − 15 minutes` (in inclusive form, `current_time >= scheduled_start_at - 15 minutes`). Failures in the face/location checks surface as `ERR_CHECKIN_LOCATION_MISMATCH`. On success, the `ServiceExecution` row is created with `checkin_at` set to the current time, and any subsequent check-in attempt for the same order is rejected with `ERR_EXECUTION_ALREADY_EXISTS` because at most one execution exists per order.

The execution row also carries a `procedure_checklist` array (an ordered list of step-completion flags whose size and content are fixed per service item), a `before_photo_url`, an `after_photo_url`, an `abnormal_reported` flag that flips to true the first time an `AbnormalEvent` is filed against the order, and a `completion_submitted_at` timestamp that is filled in at completion time. Between check-in and completion, the personnel patches the execution row to flip checklist flags and to attach the before and after photo URLs.

Completion drives the order from `IN_PROGRESS` to `COMPLETED`. The preconditions are that `X-User-ID` equal `Order.assigned_personnel_id`, that a `ServiceExecution` exist with every entry in `procedure_checklist` set to true, and that both `before_photo_url` and `after_photo_url` be non-null. A checklist with any false entry or a missing photo is rejected with `ERR_CHECKLIST_INCOMPLETE`. On success, `Order.completed_at` and the execution's `completion_submitted_at` are stamped to the current time, and a provisional `SettlementLedgerEntry` is posted with kind `COMMISSION` and `withheld_until` set to 72 hours past `completed_at` — see the settlement section for the formula.

Customer acceptance drives the order from `COMPLETED` to `ACCEPTED_BY_CUSTOMER` and is the moment commission is finalized. The acceptance endpoint requires `X-User-ID` equal `Order.customer_id`. On success, `Order.accepted_at` is set to the current time, the assigned personnel's `workload_active_orders` is decremented by one, and the final commission is reconciled against the provisional posting (see settlement). `ACCEPTED_BY_CUSTOMER` is a terminal state.

### 3.7. Abnormal Events and Insurance Claims

Either party — customer or personnel — or an operator can file an abnormal-event report against an order. The report carries a `reporter_role` from the set `PERSONNEL`, `CUSTOMER`, or `OPERATOR`; a `category` of one of `INJURY`, `PROPERTY_DAMAGE`, `NO_SHOW`, or `OTHER`; and a free-text `description`. When the category is `INJURY` or `PROPERTY_DAMAGE`, a derived `triggers_claim` flag is set to true and an `InsuranceClaim` is opened automatically as a side effect, with its `claim_type` set to `ON_JOB_INJURY` (for injuries to personnel) or `PROPERTY_DAMAGE` (for damage to customer property). For `NO_SHOW` or `OTHER` categories, `triggers_claim` is false and no claim is opened. The execution row's `abnormal_reported` flag also flips to true.

An `InsuranceClaim` carries `order_id`, `abnormal_event_id`, `claim_type`, `claimed_amount_cents`, `paid_amount_cents` (initially 0), and `evidence_count` (initially 0). Its lifecycle begins at `REPORTED` and proceeds through `EVIDENCE_PENDING`, `FILED`, then either `APPROVED` or `REJECTED`, then `PAID` (from `APPROVED`), and finally `ARCHIVED`. The operator requests evidence to move from `REPORTED` to `EVIDENCE_PENDING` and appends an `AuditLogEntry` with `action_type` of `CLAIM_REPORTED`. Attaching evidence to the claim increments `evidence_count` and accepts an `evidence_url` and a `description`. Filing the claim moves it from `EVIDENCE_PENDING` to `FILED` and requires `evidence_count` to be at least 2; a filing attempt with fewer evidence items is rejected with `ERR_INSUFFICIENT_EVIDENCE`. On successful filing, an `AuditLogEntry` with `action_type` of `CLAIM_FILED` is appended and an external event is emitted to the insurance company.

The insurance company replies asynchronously via the inbound webhook. A `decision` of `APPROVED` drives the claim from `FILED` to `APPROVED`, sets `paid_amount_cents` to the body's `amount_cents`, and appends an `AuditLogEntry` with `action_type` of `CLAIM_APPROVED`. A `decision` of `REJECTED` drives the claim from `FILED` to `REJECTED`, leaves `paid_amount_cents` at zero, and appends a `CLAIM_REJECTED` audit row. An approved claim moves to `PAID` once the operator marks it paid (which requires `paid_amount_cents` greater than zero) and appends a `CLAIM_PAID` audit row. A `PAID` claim or a `REJECTED` claim can be archived; `ARCHIVED` is terminal and admits no further mutations.

Lifetime per-personnel and per-customer claim totals roll up the `paid_amount_cents` of claims whose status is `APPROVED`, `PAID`, or `ARCHIVED`. The personnel injury total sums claims with `claim_type` of `ON_JOB_INJURY` linked through the order's `assigned_personnel_id`; the customer property total sums claims with `claim_type` of `PROPERTY_DAMAGE` linked through the order's `customer_id`. Both totals are expressed in integer cents.

### 3.8. Cancellation, Refund, and the Complaint Window

A customer or an operator can cancel an order from `PENDING_DISPATCH`, `DISPATCHED`, or `ACCEPTED` provided the current time is strictly more than 2 hours before `scheduled_start_at` — that is, `current_time < scheduled_start_at - 2 hours`. A cancellation attempt inside the 2-hour window is rejected with `ERR_CANCEL_WINDOW_CLOSED`. On cancellation, the order's `gross_price_cents` is added back as a positive credit to the customer's `wallet_credit_cents`. If the order was already past `PENDING_DISPATCH` and had an assigned personnel, that personnel's `workload_active_orders` is decremented by one. Cancellation from `PENDING_DISPATCH` involves no commission reversal because no commission was ever posted in `PENDING_DISPATCH`; cancellation from `DISPATCHED` or `ACCEPTED` is structurally the same — no commission posting has yet occurred. `CANCELLED` is terminal.

After completion but before the customer accepts, the operator retains a corrective lever: refund. Refund drives the order from `COMPLETED` to `REFUNDED` and is permitted only inside the 72-hour complaint window — that is, `current_time < Order.completed_at + 72 hours`. A refund attempt past that window, or against an order already in `ACCEPTED_BY_CUSTOMER`, is rejected with `ERR_COMPLAINT_PERIOD_EXPIRED`. Refund posts a compensating `SettlementLedgerEntry` with kind `REVERSAL`, whose amount is exactly the negative of the prior `COMMISSION` posting so that the sum of the order's `COMMISSION` plus `REVERSAL` ledger entries is exactly zero cents after the refund. Refund also adds `gross_price_cents` back into `wallet_credit_cents`, decrements the assigned personnel's `workload_active_orders` by one, and stamps `Order.refunded_at` to the current time. `REFUNDED` is terminal.

### 3.9. Ratings, the Low-Score Investigation, and Tier Recomputation

Once an order has reached `ACCEPTED_BY_CUSTOMER`, the customer may submit a rating. The rating endpoint accepts three integer dimension scores — `quality_score`, `punctuality_score`, and `attitude_score` — each in the inclusive range 1 to 5, plus a free-text `text_review` and an `anonymous` flag (default false). A rating against an order whose status is not `ACCEPTED_BY_CUSTOMER` is rejected with `ERR_RATING_NOT_ALLOWED`. A dimension score outside the 1-to-5 range is rejected with `ERR_RATING_OUT_OF_RANGE`. Only one rating exists per order: a second attempt is rejected with `ERR_RATING_ALREADY_EXISTS`, and concurrent rating attempts against the same order serialize first-writer-wins on the order-id uniqueness, with the loser receiving `ERR_RATING_ALREADY_EXISTS`.

On successful submission, a composite score is computed as the weighted sum of the three dimensions: 0.5 times `quality_score`, plus 0.3 times `punctuality_score`, plus 0.2 times `attitude_score`. The result is rounded half-up to four decimal places. The `composite_score` is stored on the rating row. The order's `rated` flag is set to true.

The composite then feeds two effects. First, the personnel's rolling `rating_score` is updated using an incremental running average: the new `rating_count` is the previous `rating_count` incremented by one; the new `rating_score` is computed as the previous `rating_score` multiplied by the previous `rating_count`, plus the new composite, then divided by the new `rating_count`, then rounded half-up to four decimal places. Second, the personnel's `tier` is recomputed: when `rating_count` is fewer than 5 the tier is `BRONZE` because the sample is insufficient; otherwise the tier is `PLATINUM` when `rating_score` is at least 4.8, `GOLD` when at least 4.5 but below 4.8, `SILVER` when at least 4.0 but below 4.5, and `BRONZE` otherwise. The floor comparisons are inclusive — a score exactly at 4.8 places the personnel at `PLATINUM`, not at `GOLD`.

When the composite is strictly less than 3.0, the rating row's `investigation_status` is set to `OPEN` automatically; otherwise it is left at `NONE`. An open investigation is closed by a `PlatformOperator` through the close-investigation endpoint, which moves `investigation_status` from `OPEN` to `CLOSED` without further preconditions or side effects.

### 3.10. Settlement: Provisional, Final, and the Periodic Sweep

Settlement is recorded in the `SettlementLedgerEntry` ledger. Each entry carries `personnel_id`, `order_id`, a `kind` of `COMMISSION`, `BONUS`, `REVERSAL`, `TAX`, or `PAYOUT`, an `amount_cents` value (positive for `COMMISSION` and `BONUS`, negative for `REVERSAL`, `TAX`, and `PAYOUT`), a `posted_at` timestamp, the `cycle_id` to which the entry belongs (for example, `2026-05`), and a `withheld_until` timestamp on `COMMISSION` and `BONUS` rows that pins the entry inside the complaint window. The `withheld_until` field is null for `REVERSAL`, `TAX`, and `PAYOUT` entries.

At completion time, a provisional commission is posted. The provisional amount is computed as `gross_price_cents` multiplied by 0.70 and then rounded half-up to integer cents. The entry's `kind` is `COMMISSION`, its `withheld_until` is set to 72 hours after `Order.completed_at`, and it represents the personnel's earnings before any tier bonus. The 0.70 base commission rate is fixed.

At customer-acceptance time, the final commission is reconciled. The final amount is computed as `gross_price_cents` multiplied by 0.70 multiplied by the quantity (one plus the personnel's tier bonus rate at the moment of acceptance), then rounded half-up to integer cents. The tier bonus rate is 0.20 for `PLATINUM`, 0.10 for `GOLD`, 0.05 for `SILVER`, and 0.00 for `BRONZE`. The provisional commission was computed using the personnel's tier as observed at `completed_at`; if a low rating filed between completion and customer acceptance dropped the tier, the two figures differ. The delta — the final amount minus the provisional amount — is posted to the ledger: if the delta is positive it is recorded as a `BONUS` entry, and if it is negative it is recorded as a `REVERSAL` entry. In every case, the invariant `provisional + delta == final` holds.

A periodic settlement sweep processes ready entries for a given personnel and `cycle_id`. The sweep walks the ledger entries in chronological order — ascending by `posted_at`, with ties broken by ascending `id`. An entry is eligible for the current sweep when its `kind` is `COMMISSION`, `BONUS`, or `REVERSAL` and either its `withheld_until` is null or its `withheld_until` is at or before the current time. The pre-tax sum is the sum of `amount_cents` across all eligible entries, which may be negative if reversals dominate. The payout base is the larger of zero and the pre-tax sum — a negative pre-tax sum yields a zero payout for this sweep. The tax for the sweep is the payout base multiplied by 0.10, rounded half-up to integer cents; the rule is sum-then-round, meaning the sum is computed across the eligible entries first and the tax rate is applied to that sum once, not entry-by-entry. The payout for the sweep is the payout base minus the tax. The sweep posts one `TAX` entry with the negative tax amount and one `PAYOUT` entry with the negative payout amount, both stamped with the supplied `cycle_id`. `COMMISSION` entries that are still inside their 72-hour complaint window are not eligible for the current sweep and roll into the next one; a sweep where every eligible entry has been released is a standard payout, and a sweep where some entries remain held is a held-back payout that pays only the released subset.

### 3.11. Test-Driving Endpoints

Two administrative levers exist for testing time-gated behaviour. An admin-only clock-advance capability accepts a `seconds` value and shifts the logical clock forward by that many seconds; the side effect is that any dispatch whose `dispatch_deadline_at` has now passed is evaluated and the corresponding orders are reverted to `PENDING_DISPATCH` with a `DISPATCH_EXPIRED` audit row. The recertification sweep is similarly callable as an administrative pass that expires lapsed certifications, suspends personnel whose health or skill coverage has gone, and reverts their dispatched orders. The settlement sweep accepts a `cycle_id` and posts the `TAX` and `PAYOUT` entries described above.

## 4. Endpoint Definitions

New resources return HTTP 201; all other successful mutations and reads return HTTP 200. Every endpoint adheres to the response envelope in §2.2 and the error envelope when a validation fails. The table below lists the API surface; for the request and response bodies, refer back to the workflows in §3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | /dsd/personnel | Create a new personnel profile (status starts PENDING_VERIFICATION) | PlatformOperator |
| GET | /dsd/personnel/{id} | Read a personnel record | PlatformOperator, ServicePersonnel, Customer |
| GET | /dsd/personnel | List personnel; supports filter by status, skill_tag, tier and pagination | PlatformOperator |
| POST | /dsd/personnel/{id}/verify-identity | Mark identity_verified=true for a personnel | PlatformOperator |
| POST | /dsd/personnel/{id}/activate | PENDING_VERIFICATION → ACTIVE | PlatformOperator |
| POST | /dsd/personnel/{id}/suspend | ACTIVE → SUSPENDED | PlatformOperator |
| POST | /dsd/personnel/{id}/reinstate | SUSPENDED → ACTIVE | PlatformOperator |
| POST | /dsd/personnel/{id}/disqualify | ACTIVE → DISQUALIFIED; revokes all certifications | PlatformOperator |
| POST | /dsd/certifications | Create a SkillCertification (PENDING) | PlatformOperator |
| POST | /dsd/certifications/{id}/approve | PENDING → ACTIVE | PlatformOperator |
| POST | /dsd/certifications/{id}/revoke | ACTIVE → REVOKED | PlatformOperator |
| GET | /dsd/personnel/{id}/certifications | List certifications for a personnel | PlatformOperator, ServicePersonnel |
| POST | /dsd/service-items | Create a service item | PlatformOperator |
| GET | /dsd/service-items | List service items; supports filter by area_code, active | PlatformOperator, Customer |
| PATCH | /dsd/service-items/{id} | Update mutable fields (price, areas, active) | PlatformOperator |
| POST | /dsd/customers | Create a customer profile | PlatformOperator |
| GET | /dsd/customers/{id} | Read a customer profile | PlatformOperator, Customer |
| POST | /dsd/orders | Create an order in DRAFT state | Customer, PlatformOperator |
| PATCH | /dsd/orders/{id} | Modify a PENDING_DISPATCH order within the modification window | Customer, PlatformOperator |
| POST | /dsd/orders/{id}/submit | DRAFT → PENDING_DISPATCH | Customer, PlatformOperator |
| POST | /dsd/orders/{id}/dispatch | PENDING_DISPATCH → DISPATCHED via dispatch_selection | PlatformOperator |
| POST | /dsd/orders/{id}/reassign | Manual reassignment; body must specify personnel_id | PlatformOperator |
| POST | /dsd/orders/{id}/accept | Assigned personnel accepts; DISPATCHED → ACCEPTED | ServicePersonnel |
| POST | /dsd/orders/{id}/reject | Assigned personnel rejects; DISPATCHED → PENDING_DISPATCH (with exclusion) | ServicePersonnel |
| POST | /dsd/orders/{id}/checkin | ACCEPTED → IN_PROGRESS; creates ServiceExecution | ServicePersonnel |
| PATCH | /dsd/orders/{id}/execution | Update procedure_checklist, before/after photo URLs on the ServiceExecution | ServicePersonnel |
| POST | /dsd/orders/{id}/complete | IN_PROGRESS → COMPLETED; posts provisional commission | ServicePersonnel |
| POST | /dsd/orders/{id}/customer-accept | COMPLETED → ACCEPTED_BY_CUSTOMER; finalizes commission | Customer |
| POST | /dsd/orders/{id}/cancel | Cancel before scheduled_start_at − 2h | Customer, PlatformOperator |
| POST | /dsd/orders/{id}/refund | Operator refund after completion within complaint window | PlatformOperator |
| GET | /dsd/orders/{id} | Read an order | Customer, ServicePersonnel, PlatformOperator |
| GET | /dsd/orders | List orders; supports filter by customer_id, assigned_personnel_id, status, pagination | Customer, ServicePersonnel, PlatformOperator |
| POST | /dsd/recurring-orders | Create a recurring order (status ACTIVE); generates first Order child | Customer, PlatformOperator |
| POST | /dsd/recurring-orders/{id}/pause | ACTIVE → PAUSED | Customer, PlatformOperator |
| POST | /dsd/recurring-orders/{id}/resume | PAUSED → ACTIVE | Customer, PlatformOperator |
| POST | /dsd/recurring-orders/{id}/terminate | * → TERMINATED | Customer, PlatformOperator |
| POST | /dsd/orders/{id}/abnormal-events | Report an abnormal event for an order | Customer, ServicePersonnel, PlatformOperator |
| POST | /dsd/orders/{id}/rate | Submit a multi-dimensional rating after customer-accept | Customer |
| POST | /dsd/ratings/{id}/close-investigation | Close a low-rating investigation | PlatformOperator |
| GET | /dsd/claims/{id} | Read a claim | PlatformOperator |
| POST | /dsd/claims/{id}/evidence | Attach evidence to a claim; increments evidence_count | PlatformOperator |
| POST | /dsd/claims/{id}/request-evidence | REPORTED → EVIDENCE_PENDING | PlatformOperator |
| POST | /dsd/claims/{id}/file | EVIDENCE_PENDING → FILED (emits external sync event) | PlatformOperator |
| POST | /dsd/claims/{id}/mark-paid | APPROVED → PAID | PlatformOperator |
| POST | /dsd/claims/{id}/archive | PAID or REJECTED → ARCHIVED | PlatformOperator |
| GET | /dsd/audit-logs | List audit log entries; filter by subject_type, subject_id, action_type, pagination | PlatformOperator |
| GET | /dsd/personnel/{id}/settlement | List SettlementLedgerEntry rows for a personnel; filter by cycle_id | PlatformOperator, ServicePersonnel |
| POST | /dsd/_clock/advance | Test-driving endpoint to advance current_time by N seconds | system |
| POST | /dsd/_sweep/recertification | Run recertification sweep | system, PlatformOperator |
| POST | /dsd/_sweep/settlement | Run settlement sweep | system, PlatformOperator |
| POST | /dsd/_events/insurance-decision | Inbound webhook from insurance company: FILED → APPROVED or REJECTED | system |
| POST | /dsd/_events/payment-received | Inbound webhook from payment system; records payment timestamp | system |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_VERSION_CONFLICT | 409 |
| ERR_NOT_ASSIGNED | 403 |
| ERR_CHECKIN_LOCATION_MISMATCH | 422 |
| ERR_AREA_NOT_SERVICED | 422 |
| ERR_ITEM_INACTIVE | 422 |
| ERR_LEAD_TIME_TOO_SHORT | 422 |
| ERR_CANCEL_WINDOW_CLOSED | 422 |
| ERR_MODIFY_WINDOW_CLOSED | 422 |
| ERR_COMPLAINT_PERIOD_EXPIRED | 422 |
| ERR_DISPATCH_DEADLINE_PASSED | 422 |
| ERR_NO_ELIGIBLE_PERSONNEL | 422 |
| ERR_HAS_ACTIVE_ASSIGNMENTS | 422 |
| ERR_CHECKLIST_INCOMPLETE | 422 |
| ERR_RATING_NOT_ALLOWED | 422 |
| ERR_RATING_OUT_OF_RANGE | 422 |
| ERR_RATING_ALREADY_EXISTS | 409 |
| ERR_EXECUTION_ALREADY_EXISTS | 409 |
| ERR_CERT_REQUIREMENTS_NOT_MET | 422 |
| ERR_INSUFFICIENT_EVIDENCE | 422 |
| ERR_PERSONNEL_NOT_ELIGIBLE | 422 |
| ERR_VALIDATION_ERROR | 422 |
