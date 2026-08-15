# Transcript Ordering & Credential Verification API — Product Requirements Document

## 1. Introduction

The registrar's transcript office operates at the intersection of student privacy law, financial administration, and multi-channel fulfillment. A single incoming request can bounce between identity proofing, a financial-hold adjudication, a fee calculation against a schedule with volume tiers and rush multipliers, an archive retrieval for pre-1990 paper records, and ultimately a national clearinghouse reporting obligation — each step gated by segregation-of-duties rules so that no one actor can both place and approve a sensitive action. This document specifies the Transcript Ordering & Credential Verification API, a REST service mounted under `/registrar`, that orchestrates that entire pipeline.

Two distinct product surfaces sit on the same substrate. On the student-facing surface, a records subject drafts an order, attaches recipients across four delivery channels (clearinghouse network, email-PDF, postal mail, in-person pickup), proves identity out-of-band, pays, and tracks per-copy delivery. On the third-party surface, employers and background-check firms file credential verification requests that must clear FERPA consent checks, financial-hold screens, and reviewer approval before any disclosure leaves the institution. Wrapped around both surfaces are the registrar's own administrative concerns: record snapshots that recompute a student's GPA, archived-record retrievals with a 48-hour service-level agreement, reissue workflows for damaged or misdirected credentials, fee schedules with effective windows, and tamper-evident audit logging on every mutating action.

This specification is written for engineers implementing the service. Contract-level mechanics — response envelopes, pagination, common resource fields, optimistic concurrency — appear in §2. Business logic — the dual state machines on orders, the fee-quotation pipeline, the hold and consent cascades, the clearinghouse sweep — is developed narratively in §3, where rules are deliberately distributed across the subsections they most naturally belong to rather than concentrated in a single spec block.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` identifying the calling principal and `X-User-Role` identifying the capacity in which they act. A request missing either header, or presenting one in a malformed form, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not on the endpoint's authorized list is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The eight roles are spelled exactly as follows:

- `Student` — the records subject. When `X-User-Role` is `Student`, `X-User-ID` is the `id` of the acting `Student` entity. The API enforces exactly one such ownership check: a `Student` may only revoke a `ConsentGrant` whose `student_id` equals the caller's `X-User-ID`. Everywhere else a student-initiated request names a `student_id` (order creation, identity-verification start, consent-grant creation, payment authorization), any existing `student_id` is accepted without comparison to `X-User-ID`.
- `RegistrarOperator` — day-to-day fulfillment operator. `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it against any entity's `id`.
- `RegistrarReviewer` — reviewer for identity verifications, verification requests, and reissue requests; serves as the segregation-of-duties counterparty to `Student`. `X-User-ID` is an opaque operator identifier. When a `RegistrarReviewer` approves or rejects a `ReissueRequest`, the server records that identifier in the request's `reviewed_by` field, and the same segregation check forbids the reviewer's `X-User-ID` from equalling the `id` of the `Student` who placed the original order or who is the subject of the verification.
- `RegistrarAdmin` — administrator for students, record snapshots, fee schedules, and the logical clock. `X-User-ID` is an opaque operator identifier.
- `BursarOffice` — releases `FINANCIAL` holds. `X-User-ID` is an opaque operator identifier.
- `LibraryOffice` — releases `LIBRARY` holds. `X-User-ID` is an opaque operator identifier.
- `ArchiveClerk` — pulls and digitizes archived records. `X-User-ID` is an opaque operator identifier.
- `VerificationRequester` — third-party requester (employer, background-check firm). `X-User-ID` is an opaque operator identifier not tied to any persisted entity.

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

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_` followed by twenty random alphanumeric characters.
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

All list endpoints accept `limit` and `offset` query parameters. `limit` defaults to 10, has a minimum of 1 and a maximum of 100. `offset` defaults to 0. A non-integer `limit` or `offset`, a `limit` outside the 1–100 range, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). List responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` block, with `has_more` true exactly when `offset` + `limit` is strictly less than `total_count`. Unless otherwise noted, list endpoints sort by `created_at` ascending, breaking ties by `id` ascending. List endpoints additionally honor equality filters on selected resource fields passed as query parameters (for example `status`, `ferpa_restricted`, or `archived_record_flag` on the student list; `fulfillment_status`, `payment_status`, `order_kind`, or `student_id` on the order list; `line_status` on the line-item lists), and unrecognized query parameters are ignored.

### 2.4. Common Resource Properties and the Logical Clock

Every entity carries an `id` that is a server-minted UUID with no type prefix. Most entities additionally carry `created_at` (ISO 8601 UTC with three fractional digits), `updated_at` (refreshed on every mutation), and `version` (an integer starting at 1, incremented by exactly 1 on every mutation). Two entity types deviate from this shape. `IdentityVerification` carries only `id` and `created_at`; it has neither `updated_at` nor `version`. `AuditEvent` is likewise limited to `id` and `created_at` — the audit trail is append-only and no event is ever mutated, so `updated_at` and `version` are absent. For every entity that does carry `version`, any state transition, side-effect write, or cascade-driven change increments that entity's `version` by 1. All entity timestamps — `created_at`, `updated_at`, and server-stamped fields such as `placed_at`, `released_at`, `submitted_at`, the identity-verification `expires_at`, `sla_due_at`, `transmitted_at`, and `recorded_at` — are read from the logical clock, never from wall-clock time; only the `api_request_timestamp` in the response `meta` reflects wall-clock UTC.

All time-sensitive behaviour — consent expiry, identity-verification expiry, financial-hold auto-expiry, rush-cutoff evaluation, clearinghouse period boundaries — is evaluated against a server-maintained logical clock, never against wall-clock time. At startup the logical clock reads exactly `2026-08-01T00:00:00Z`. An administrator-only capability advances the logical clock to a supplied `to_iso8601` instant (which may be earlier or later than the current reading) and returns the resulting `current_utc`; setting the clock re-evaluates every `ConsentGrant` whose `expires_at` is at or before the new instant (transitioning each such grant from `ACTIVE` to `EXPIRED`), every `IdentityVerification` whose `expires_at` has been reached (transitioning each from `PENDING` to `EXPIRED`), and every zero-amount `FINANCIAL` hold whose `placed_at` is more than 365 days in the past (transitioning each from `ACTIVE` to `EXPIRED`). Each of those transitions cascades per the rules in §3.

### 2.5. Validation Order Across All Endpoints

Incoming requests are validated against a fixed priority ladder, and a failure at any rung prevents evaluation of every later rung. Authentication of the headers comes first (`ERR_UNAUTHENTICATED`, 401), followed by role authorization on the endpoint (`ERR_UNAUTHORIZED`, 403), followed by left-to-right existence resolution of every path-templated resource (`ERR_NOT_FOUND`, 404), followed by generic shape validation of the request body — unknown fields, missing required fields, and malformed values (`ERR_INVALID_REQUEST`, 400) — followed by existence of every body-supplied foreign key such as `student_id`, `recipient_id`, `consent_grant_id`, `original_order_id`, or `digitized_record_id` (`ERR_REFERENCED_NOT_FOUND`, 404). Only after existence checks does the server evaluate whether the target resource sits in a state that admits the requested transition (`ERR_INVALID_STATE` or its specialized variants such as `ERR_ORDER_NOT_DRAFT`, 409), and only after that does it evaluate optimistic-concurrency version agreement on the endpoints that carry it (`ERR_STALE_VERSION`, 412). Business rules come after those structural gates: FERPA consent (`ERR_FERPA_CONSENT_REQUIRED`, 422), segregation of duties (`ERR_SEGREGATION_OF_DUTIES`, 403), hold-office matching (`ERR_HOLD_OFFICE_MISMATCH`, 403), holds blocking an official order or a verification request (`ERR_HOLD_BLOCKING`, 422), recipient active status (`ERR_RECIPIENT_INACTIVE`, 422), recipient routing validity (`ERR_RECIPIENT_ROUTING_INVALID`, 422), identity verification (`ERR_IDENTITY_NOT_VERIFIED`, 422), then business-temporal rules (`ERR_CONSENT_EXPIRED`, `ERR_VERIFICATION_EXPIRED`, `ERR_SCHEDULE_WINDOW_INVALID`, all 422), business-referential rules (`ERR_REISSUE_SOURCE_INVALID`, 422), fiscal rules (`ERR_CAPTURE_EXCEEDS_AUTHORIZED`, `ERR_REFUND_EXCEEDS_CAPTURED`, both 422), and idempotency (`ERR_IDEMPOTENCY_CONFLICT`, 409). Where §3 pins a more specific check order for a particular endpoint — identity confirmation (§3.4), order submission (§3.5), payment authorization (§3.6), retrieval record attachment (§3.8), verification approval (§3.9), and reissue review (§3.10) — the endpoint-specific order governs over this ladder.

### 2.6. Optimistic Concurrency Control

Two write endpoints participate in optimistic concurrency control, and both name `TranscriptOrder` as the parent entity. Submitting an order requires the caller to include `expected_order_version` carrying the order's `version` as last observed by the client; if another writer has advanced the order's version since that read — for example by adding a line item that changed the rush qualification or the provisional quote — the submission is rejected with `ERR_STALE_VERSION` (HTTP 412). Adding a line item to a DRAFT order carries the same requirement: the request must include `expected_order_version` matching the order's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). Endpoints not named in this rule do not accept any version field; attempting to send one is treated as an unknown-field shape violation under `ERR_INVALID_REQUEST`.

### 2.7. Precision, Rounding, and Money

All monetary quantities are integer cents. Every fee computation pins its rounding at explicit steps: each line's unit price is rounded to cents *before* any summing, and each subsequent multiplication step applies round-half-up before the next step consumes its result. The constants that appear across calculations are a basis-point denominator of 10000 (so a `rush_multiplier_bp` of 15000 means multiply by 1.5, and a `discount_bp` of 500 means a 5 percent reduction), a rush cutoff of 14:00 local registrar time compared at second precision, a four-hour post-cutoff grace window, an archive-retrieval SLA of 48 hours, and a financial-hold auto-expiry of 365 days. Local registrar time is the UTC reading of the logical clock (the logical clock is maintained in UTC). GPA is stored as `gpa_cents`, an integer equal to one hundred times the grade-point average rounded half-up, so that a 2.50 GPA is stored as 250.

### 2.8. Soft Deactivation and Append-Only Audit

Two entities support soft removal rather than hard deletion. A `Recipient` whose `active` flag has been flipped to false can no longer be added to new orders and can no longer receive new dispatches, but historical `OrderLineItem` rows keep their reference to it. A `FeeSchedule` whose `active` flag is false no longer participates in fee selection; only one schedule may be active at any logical instant, and registering a new active schedule atomically deactivates any other schedule whose effective window overlaps. Registration requires `effective_from` to be strictly before `effective_to` whenever `effective_to` is non-null — an inverted or zero-length window is rejected with `ERR_SCHEDULE_WINDOW_INVALID` (HTTP 422) — and the schedule `code` must be unique, a duplicate being rejected with `ERR_INVALID_REQUEST` (HTTP 400).

The audited actions are exactly the ones called out across §3: student registration and update (`STUDENT_CREATED`, `STUDENT_UPDATED`), hold release (`HOLD_RELEASED`), identity confirmation and rejection (`IDENTITY_VERIFIED`, `IDENTITY_REJECTED`), order creation, submission, student-initiated cancellation, delivery, and failure (`ORDER_CREATED`, `ORDER_SUBMIT`, `ORDER_CANCELLED`, `ORDER_DELIVERED`, `ORDER_FAILED`), every advance of an `OFFICIAL` order into `READY_TO_FULFILL` (`HOLD_CLEARED`), and reissue approval (`REISSUE_APPROVED`). Mutating operations not in that list — record publication, recipient maintenance, hold placement, line-item adds, dispatch and delivery markings, payment authorize/capture/refund/void, consent-grant creation and revocation, the verification-request lifecycle, the retrieval lifecycle, reissue opening and rejection, the batch lifecycle, fee-schedule registration, and clock advances — emit no audit event. Each `AuditEvent` carries `aggregate_type`, `aggregate_id`, `actor_role`, `actor_id` (the `X-User-ID` of the caller, or null for system-initiated actions), an `action` identifier such as `ORDER_SUBMIT` or `HOLD_RELEASED`, a `payload_hash` computed as SHA-256 over the canonical event payload for tamper evidence, and a server-stamped `recorded_at`. The audit trail is readable only by `RegistrarAdmin` and `RegistrarReviewer`.

## 3. Business Logic & Workflows

### 3.1. Registering the Student and Maintaining the Academic Record

Everything in the registrar's world anchors on a `Student`. A `RegistrarAdmin` registers a student by supplying `student_number` (unique across the tenant, six to twelve alphanumeric characters), `full_name` (the legal name on record), `date_of_birth` (an ISO 8601 date consumed by identity verification), and `email`. Three optional flags shape downstream behaviour. `status` defaults to `ACTIVE` and may be moved to `INACTIVE`, `GRADUATED`, `WITHDRAWN`, or `DECEASED` as the student's enrollment posture evolves. `ferpa_restricted` defaults to false; when true, the student has exercised a FERPA directory-information restriction and no third-party verification may be approved without an explicit consent grant. `archived_record_flag` defaults to false; when true, the student's record lives in the offline archive (typical for pre-1990 paper files), which drives both a historical-lookup surcharge on verification fees and the archive-retrieval workflow on transcript orders. A student update touches only `status`, `ferpa_restricted`, and `archived_record_flag`; each update increments the student's `version` and emits a `STUDENT_UPDATED` audit event. The registration itself emits `STUDENT_CREATED`.

Academic history is versioned through `StudentRecord` snapshots. Publishing a new snapshot for a student takes `effective_term` (for example `2026-SPR`), `earned_credits`, an optional `degree_awarded` flag defaulting to false, and a list of `courses` in the publish payload. The server computes `gpa_cents` from that course list: it sums, over every course, the product of that course's `grade_points` and `credits`; it separately sums the `credits` across the same list; if the credit total is greater than zero the GPA in cents is one hundred times the point total divided by the credit total, rounded half-up to the nearest integer; if the credit total is zero the GPA in cents is 0. Each snapshot carries a monotonically increasing `record_version` starting at 1, and exactly one snapshot per student has `is_current` set to true — the act of publishing flips every prior snapshot for that student to `is_current` false and increments the owning student's `version` by 1.

### 3.2. Holds and the Offices That Own Them

A `Hold` sits on a student and is placed by the office that owns it. The four values of `hold_type` are `FINANCIAL`, `LIBRARY`, `REGISTRAR`, and `DISCIPLINARY`. A `FINANCIAL` hold may only be placed by `BursarOffice`, a `LIBRARY` hold only by `LibraryOffice`, and `REGISTRAR` or `DISCIPLINARY` holds only by `RegistrarAdmin`. Placement supplies `student_id`, `hold_type`, `blocking_scope` (one of `OFFICIAL`, `ALL`, or `NONE`), and an optional `amount_cents` defaulting to 0 — a `FINANCIAL` hold normally carries the outstanding balance while non-financial holds carry 0. A negative `amount_cents` is rejected with `ERR_INVALID_REQUEST` (HTTP 400), and a placement attempted by a role that does not own the `hold_type` is rejected with `ERR_HOLD_OFFICE_MISMATCH` (HTTP 403), just as on release. The server stamps `placed_at` at creation and leaves `released_at` null while the hold is `ACTIVE`. The `blocking_scope` value `OFFICIAL` blocks official transcripts only; `ALL` blocks official transcripts and third-party verification requests; `NONE` is retained for legacy data and never blocks anything.

Release is segregated in the same way. Releasing a hold requires the acting role to match the office that owns the `hold_type`: `FINANCIAL` is released only by `BursarOffice`, `LIBRARY` only by `LibraryOffice`, and `REGISTRAR` or `DISCIPLINARY` only by `RegistrarAdmin`. A mismatched attempt is rejected with `ERR_HOLD_OFFICE_MISMATCH` (HTTP 403). A successful release moves the hold from `ACTIVE` to `RELEASED`, stamps `released_at`, increments the hold's `version`, emits a `HOLD_RELEASED` audit event, and then cascades: every order on the same student currently sitting in `HOLD_CHECK` is re-evaluated, and if no other active blocking hold remains, each such order advances to `READY_TO_FULFILL` (emitting a `HOLD_CLEARED` audit event), which itself fans every `PENDING` line item on that order out to `QUEUED`. The cascade therefore runs three levels deep — hold, order, line item.

Two other transitions close a hold without an explicit release. When the logical clock advances past `placed_at` plus 365 days on a `FINANCIAL` hold whose `amount_cents` is 0, the hold moves automatically from `ACTIVE` to `EXPIRED` and triggers the same cascade as a release. A hold whose `blocking_scope` is `NONE` never participates in the blocking evaluation.

### 3.3. Drafting an Order, Routing to Recipients, and the Rush Question

A `Student` opens a `TranscriptOrder` by supplying `student_id`, `order_kind` (`OFFICIAL` for a sealed, registrar-issued document or `UNOFFICIAL` for a student-view copy), and an optional `rush_requested` flag defaulting to false. The new order lands in `DRAFT` on the fulfillment dimension and `UNPAID` on the payment dimension, and the server emits an `ORDER_CREATED` audit event. The two dimensions evolve independently from this point onward.

Line items attach recipients to the order. Adding a line item requires `recipient_id`, `delivery_kind` (one of `ELECTRONIC_NETWORK`, `EMAIL_PDF`, `PAPER_MAIL`, `PICKUP`), `quantity` (between 1 and 10 copies), and — because the add is OCC-protected — `expected_order_version`. An optional `archived_retrieval_id` may be supplied to bind the new line to an `ArchivedRecordRetrieval`; a reference to a nonexistent retrieval is rejected with `ERR_REFERENCED_NOT_FOUND` (404). The referenced `Recipient` must exist and must still be `active` at add time; a reference to a deactivated recipient is rejected with `ERR_RECIPIENT_INACTIVE` (HTTP 422). Each `Recipient` carries a human-readable `display_name` naming the university, employer, or self-address the routing points at. Routing validity is checked against the recipient's `kind`: it must equal the requested `delivery_kind`, and the kind-specific routing field must be populated — `network_code` when the kind is `ELECTRONIC_NETWORK`, `email_address` when `EMAIL_PDF`, `postal_address` when `PAPER_MAIL`; for `PICKUP` none of the routing fields apply. Registering a recipient likewise requires the routing field of its `kind` to be populated — a registration missing it is rejected with `ERR_RECIPIENT_ROUTING_INVALID` (HTTP 422) — while the two routing fields not used by the kind may be set or left null. A mismatch — a `PAPER_MAIL` line pointed at an `EMAIL_PDF` recipient, a missing `network_code` on an `ELECTRONIC_NETWORK` recipient, and so on — is rejected with `ERR_RECIPIENT_ROUTING_INVALID` (HTTP 422). Line-item mutations are permitted only while the order is in `DRAFT`; attempting one against an order that has left `DRAFT` is rejected with `ERR_ORDER_NOT_DRAFT` (HTTP 409). Each successful add increments the order's `version` and recomputes both `rush_qualified` and the provisional `quoted_fee_cents`; that add-time recomputation runs the same per-line pricing pipeline described in §3.5, including storing each line's rounded `unit_price_cents` on the line. If no active `FeeSchedule` covers the current clock at add time, the add still succeeds: `rush_qualified` is recomputed, but the per-line unit prices and the provisional `quoted_fee_cents` are left unchanged.

Rush qualification is a conjunction of five conditions, evaluated at submit and again whenever a line item changes before submit; before `submitted_at` exists, the time-of-day, weekday, and holiday conditions are evaluated against the current logical clock. The order must carry `rush_requested` true. The local registrar time of `submitted_at` must be strictly earlier than 14:00 — a submission landing at exactly 14:00:00 is not rush-qualified. The submission must fall on a weekday, Monday through Friday. The submission date must not appear on the registrar's holiday calendar (the holiday calendar is empty in this deployment, so this condition never disqualifies a submission). And every line item on the order must have a `delivery_kind` drawn from `ELECTRONIC_NETWORK`, `EMAIL_PDF`, or `PICKUP` — a single `PAPER_MAIL` line disqualifies the entire order from rush regardless of the other lines. The result is stored in `rush_qualified`.

While the order is still in `DRAFT`, a caller may request a fee quote preview. The preview runs the same tiered-pricing pipeline as submit-time quoting but against the current logical clock and the currently active `FeeSchedule`; the result is advisory only, is not persisted, and may diverge from the eventual `quoted_fee_cents` if the clock crosses a schedule boundary between preview and submit. The preview response exposes `quoted_fee_cents`, `rush_qualified`, and the `schedule_code` that was used. The preview is available only while the order is in `DRAFT` — any other state is rejected with `ERR_INVALID_STATE` (HTTP 409) — and if no active `FeeSchedule` covers the current clock the preview is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 3.4. Identity Verification as a Gate to Submission

Before a draft order can be submitted, the student must prove identity through a bound `IdentityVerification`. Starting one takes `student_id`, `order_id`, and `method` — one of `SSN_DOB`, `GOVERNMENT_ID`, `IN_PERSON`, or `NOTARIZED`. The server mints a one-time `verification_token` and stamps `expires_at` at exactly 72 hours after creation. If the bound order happened to be sitting in `SUBMITTED` when the verification starts, the order moves into `IDENTITY_PENDING`. Confirming the verification requires the caller to present the `verification_token`; confirmation succeeds only while the record is `PENDING`, the token matches, and the logical clock is still earlier than `expires_at`. A confirm attempted after expiry is rejected with `ERR_VERIFICATION_EXPIRED` (HTTP 422), and this expiry rejection takes precedence over the generic not-`PENDING` state rejection: once the logical clock has reached `expires_at`, a confirm is rejected with `ERR_VERIFICATION_EXPIRED` even when the record has already left `PENDING`, including one already sitting in `EXPIRED`. The not-`PENDING` state rejection (`ERR_INVALID_STATE`, 409) in turn precedes the token comparison, and a token that does not match is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Successful confirmation moves the record to `VERIFIED`, emits an `IDENTITY_VERIFIED` audit event, and cascades any bound order out of `IDENTITY_PENDING` — into `HOLD_CHECK` if the §3.5 blocking-hold evaluation applies (an `OFFICIAL` order whose student carries an `ACTIVE` hold of scope `ALL` or `OFFICIAL`), or directly to `READY_TO_FULFILL` otherwise.

A `RegistrarReviewer` may reject a `PENDING` verification, moving it to `REJECTED` and emitting `IDENTITY_REJECTED`; any bound order in `IDENTITY_PENDING` is cancelled in the same breath. The same cancellation cascade fires if the logical clock reaches `expires_at` while the record is still `PENDING`, moving it to `EXPIRED`. A single order may accumulate several verification records over its life; listing them is supported both per-student and per-order.

### 3.5. Submission, the Hold Check, and the Fee-Quote Pipeline

Submitting a DRAFT order requires `expected_order_version` for OCC and triggers the densest sequence of side effects in the system. The preconditions are evaluated in this order: the order is in `DRAFT` (else `ERR_INVALID_STATE`, 409); `expected_order_version` equals the order's current `version` (else `ERR_STALE_VERSION`, 412); the order carries at least one `OrderLineItem` (else `ERR_INVALID_REQUEST`, 400); and an `IdentityVerification` bound to this order exists with `status` equal to `VERIFIED` (else `ERR_IDENTITY_NOT_VERIFIED`, 422). If no active `FeeSchedule` window covers the submit-time clock, the submit is rejected with `ERR_INVALID_REQUEST` (HTTP 400); such a rejected attempt leaves the order in `DRAFT`, but the `submitted_at` stamp and `rush_qualified` recomputation from the failed attempt remain visible on the order. On success the server stamps `submitted_at`, recomputes `rush_qualified` per §3.3, computes the provisional `quoted_fee_cents` per the pipeline below, initializes `final_fee_cents` equal to `quoted_fee_cents`, increments the order's `version`, emits `ORDER_SUBMIT`, and advances `fulfillment_status` from `DRAFT` to `SUBMITTED`. From `SUBMITTED` the order immediately routes onward: if the order is `OFFICIAL` and any `Hold` on the student is `ACTIVE` with a `blocking_scope` of `ALL` or `OFFICIAL`, the order moves into `HOLD_CHECK`; otherwise it advances directly to `READY_TO_FULFILL`. There is no manual push or advance operation on orders: an order in `HOLD_CHECK` leaves only through the §3.2 release or auto-expiry cascade once no active blocking hold remains.

The provisional fee quote walks a pinned sequence. First the server locates the `FeeSchedule` active at `submitted_at` — the one whose `effective_from` is at or before `submitted_at` and whose `effective_to` is strictly after it, with a null `effective_to` meaning open-ended. Each schedule is registered under a unique `code` (for example `STD-2026`) that identifies it on the quote preview response. From that schedule the base per copy is `official_base_cents` when the order's `order_kind` is `OFFICIAL`, otherwise `unofficial_base_cents`. Then, for each line item, the server computes that line's unit price by starting from the base per copy, adding `paper_surcharge_cents` if the line's `delivery_kind` is `PAPER_MAIL`, adding `pickup_surcharge_cents` if the kind is `PICKUP`, and rounding the result half-up to integer cents; that per-line rounded figure is stored on the line as `unit_price_cents`. The order subtotal is the sum, over all line items, of each line's `unit_price_cents` multiplied by its `quantity`. Volume discounting looks at the total copy count across all lines and picks the highest-`min_copies` tier in `volume_tiers` whose threshold the total meets or exceeds; if two tiers tie on `min_copies`, the one listed first wins. The chosen tier's `discount_bp` is applied to the whole subtotal by multiplying the subtotal by the difference between 10000 and `discount_bp` and dividing by 10000, rounding half-up to integer cents. Finally, if the order is rush-qualified, the discounted subtotal is multiplied by `rush_multiplier_bp` and divided by 10000 with round-half-up, and `rush_flat_cents` is added on top — multiplicative first, additive second, in that order. The result becomes `quoted_fee_cents` and never changes after submit.

### 3.6. Payment: Authorize, Capture, Refund, Void

Payment runs on the order's second state dimension. Authorizing a payment takes `order_id` and a client-supplied `idempotency_key`; the server tracks seen keys in a single registry spanning all orders. Authorization is permitted only while the order's `fulfillment_status` is `SUBMITTED`, `HOLD_CHECK`, or `READY_TO_FULFILL`, and only when no existing `Payment` for the order is in `AUTHORIZED` or `CAPTURED`. On success the server creates a `Payment` whose `amount_cents` equals the order's `quoted_fee_cents`, stamps `gateway_ref`, moves `Payment.status` to `AUTHORIZED`, mirrors the order's `payment_status` to `AUTHORIZED`, and increments the order's `version`. If a second authorize arrives carrying an `idempotency_key` already seen with a different payload — which, the authorize payload being only `order_id` and the key itself, is exactly the case of a key first used on one order being presented against another order — the request is rejected with `ERR_IDEMPOTENCY_CONFLICT` (HTTP 409); the same key with the same payload (that is, the same `order_id`) returns the original `Payment` unchanged. The registry is consulted before the fulfillment-state and existing-payment checks, so a replayed key with the same `order_id` returns the original `Payment` (HTTP 201) even when the order has since left the authorizable states, and a key reused on a different order is rejected with `ERR_IDEMPOTENCY_CONFLICT` regardless of that order's state.

Capture reconciles the provisional authorization against a final fee recomputed at the capture-time clock. A `RegistrarOperator` captures only while the `Payment` is `AUTHORIZED` and the order's `fulfillment_status` is not `CANCELLED`; a capture attempted on a `Payment` that is not `AUTHORIZED`, or against a `CANCELLED` order, is rejected with `ERR_INVALID_STATE` (HTTP 409). Capture recomputes `final_fee_cents` using the same shape as the provisional pipeline but against the `FeeSchedule` effective at capture time, with two adjustments: a reissue order whose `ReissueRequest` carried `fee_waived` true short-circuits the final fee to 0, and if the order was rush-qualified at submit but the capture clock has moved past the same-day rush cutoff plus a four-hour grace window, the rush multiplier and flat fee are dropped and only the base-plus-discount portion is kept. If no active `FeeSchedule` window covers the capture-time clock, the recomputation falls back to the order's existing `quoted_fee_cents` as the final fee. The capture target is then the greater of zero and the difference between `final_fee_cents` and the payment's already-`refunded_cents`. The captured amount is the smaller of the authorized `amount_cents` and that target — a capture can never exceed the authorization; the capture request carries no amount parameter, so an over-target authorization simply caps the capture at the authorized amount and `ERR_CAPTURE_EXCEEDS_AUTHORIZED` is never raised by it. If the target exceeds the authorized amount the shortfall is visible in the reconciled `amount_cents` but is not auto-charged, and capture does not itself move the order's `fulfillment_status`. A successful capture writes the captured amount into `captured_cents`, reconciles `amount_cents` to the recomputed `final_fee_cents`, moves `Payment.status` to `CAPTURED`, mirrors the order's `payment_status` to `CAPTURED`, and increments the order's `version`.

Refunds follow a waterfall. Refunding takes `refund_amount_cents`; the amount must be a positive integer, otherwise the request is rejected with `ERR_INVALID_REQUEST` (HTTP 400), and the `Payment` must be `CAPTURED` or `PARTIALLY_REFUNDED`, otherwise it is rejected with `ERR_INVALID_STATE` (HTTP 409). While the `Payment` is `CAPTURED`, a refund whose amount is strictly less than the difference between `captured_cents` and the already-accumulated `refunded_cents` adds to `refunded_cents` and moves the payment to `PARTIALLY_REFUNDED`; when the cumulative refunded total reaches `captured_cents`, the payment moves to `REFUNDED`. A refund from `PARTIALLY_REFUNDED` likewise moves the payment to `REFUNDED` once the cumulative total equals `captured_cents`. Any refund request whose cumulative total would exceed `captured_cents` is rejected with `ERR_REFUND_EXCEEDS_CAPTURED` (HTTP 422). The order's `payment_status` mirrors the `Payment.status` after every refund. Void is available only while the `Payment` is `AUTHORIZED` and has not yet been captured — a void against a `Payment` in any other status is rejected with `ERR_INVALID_STATE` (HTTP 409); voiding moves the payment to `VOIDED` and flips the order's `payment_status` back to `UNPAID`.

### 3.7. Dispatch, Delivery, and the Order-Level Bubble-Up

Once an order reaches `READY_TO_FULFILL`, every `PENDING` line item on it fans out to `QUEUED`. Dispatching a queued line item — the act that moves it from `QUEUED` to `SENT` — is performed by a `RegistrarOperator` and is gated on three conditions: the line is currently `QUEUED`; the order's `payment_status` is `CAPTURED` or `WAIVED`; and, when the line's `delivery_kind` is `ELECTRONIC_NETWORK`, the recipient's `active` flag is still true. A dispatch against a deactivated recipient is rejected with `ERR_RECIPIENT_INACTIVE`; routing fields are not re-validated at dispatch time. A successful dispatch stamps `tracking_ref`, increments the line's `version`, and — if this is the first line on the order to reach `SENT` — flips the order's `fulfillment_status` from `READY_TO_FULFILL` to `IN_TRANSIT`.

Each `SENT` line resolves in one of two directions. Marking it delivered moves `line_status` from `SENT` to `DELIVERED`; marking it bounced moves it to `BOUNCED`. Either way the server evaluates the order-level bubble-up after every such marking. When every line item on the order has reached a terminal delivery state — `DELIVERED`, `BOUNCED`, or `CANCELLED` — and at least one line is `DELIVERED`, the order advances from `IN_TRANSIT` to `DELIVERED` and emits `ORDER_DELIVERED`. When every line is terminal but none is `DELIVERED`, the order moves instead from `IN_TRANSIT` to `FAILED`, emits `ORDER_FAILED`, and auto-refunds the payment: the full `captured_cents` is returned, `refunded_cents` rises to equal `captured_cents`, and the payment's status becomes `REFUNDED`. The refund never exceeds the captured total.

Cancellation by the student is available while `fulfillment_status` is `HOLD_CHECK`, `READY_TO_FULFILL`, or `IDENTITY_PENDING`, and while `payment_status` is `UNPAID` or `AUTHORIZED`. The caller may supply a free-text `cancelled_reason`, which is stored as null when omitted. Cancelling moves every non-terminal line item to `CANCELLED`, voids the `AUTHORIZED` payment if one exists, increments the order's `version`, and emits `ORDER_CANCELLED`. An attempt to cancel from any other state is rejected with `ERR_INVALID_STATE`.

### 3.8. Archived Records and the Retrieval SLA

When a student's `archived_record_flag` is true, fulfilling a transcript order requires pulling the record from the offline archive. A `RegistrarOperator` or `ArchiveClerk` opens an `ArchivedRecordRetrieval` by supplying `student_id` and `requested_by_order_id`; the server stamps `sla_due_at` at 48 hours after creation. Any `OrderLineItem` that could only be fulfilled via the archive carries `archived_retrieval_id` pointing at the retrieval; like every other line item it fans out from `PENDING` to `QUEUED` when its order reaches `READY_TO_FULFILL` (§3.7).

The retrieval lifecycle runs `retrieval_status` from `REQUESTED` → `PULLED` → `DIGITIZED` → `ATTACHED`, with a failure exit from `REQUESTED` to `FAILED`. An `ArchiveClerk` marks a `REQUESTED` retrieval pulled. Attaching the digitized record moves it from `PULLED` to `DIGITIZED`; the supplied `digitized_record_id` must reference an existing `StudentRecord` belonging to the same student, otherwise the request is rejected with `ERR_REFERENCED_NOT_FOUND` (the `PULLED` state check is evaluated before that reference check). Attaching the digitized record to the order moves the retrieval from `DIGITIZED` to `ATTACHED`; the order referenced by `requested_by_order_id` must currently be in `READY_TO_FULFILL`. That final step cascades: every `OrderLineItem` on that order whose `archived_retrieval_id` equals this retrieval's `id` and whose `line_status` is still `PENDING` flips to `QUEUED`. A retrieval that cannot be completed is marked failed from `REQUESTED`; the failure has no cascade, and dependent line items are left untouched. Advancing a retrieval — marking it pulled, attaching the digitized record, or attaching it to the order — once the logical clock has moved strictly past its `sla_due_at` is rejected with `ERR_RETRIEVAL_SLA_BREACHED` (HTTP 422); there is no escalation mechanism, and marking a retrieval failed is not SLA-gated.

### 3.9. Third-Party Verification, FERPA Consent, and Reviewer Approval

A `VerificationRequester` — an employer, a background-check firm — opens a `VerificationRequest` by supplying `requester_name`, `subject_student_id`, and `scope` (`ENROLLMENT_ONLY`, `DEGREE_ONLY`, or `FULL_RECORD`), plus an optional `consent_grant_id`. The request lands in `RECEIVED` with `fee_cents` 0 and `denial_reason` null. A `RegistrarReviewer` begins review, moving it from `RECEIVED` to `CONSENT_CHECK`.

The student-facing counterpart is the `ConsentGrant`. A `Student` creates one by supplying `student_id`, `grantee_name`, `scope`, and `expires_at`; the expiry must lie strictly in the future at creation, otherwise the request is rejected with `ERR_CONSENT_EXPIRED` (HTTP 422). The grant's `scope` may be `ENROLLMENT_ONLY`, `DEGREE_ONLY`, or `FULL_RECORD`. A student may revoke only their own grant: revocation first requires the grant to be `ACTIVE` (any other status is rejected with `ERR_INVALID_STATE`, 409), after which a caller whose `X-User-ID` differs from the grant's `student_id` is rejected with `ERR_UNAUTHORIZED` (403). Revocation moves the grant from `ACTIVE` to `REVOKED` and cascades: every `VerificationRequest` referencing that grant and currently sitting in `CONSENT_CHECK` is denied with `denial_reason` set to `CONSENT_REVOKED`. When the logical clock reaches a grant's `expires_at`, the grant moves from `ACTIVE` to `EXPIRED` and the same cascade fires, this time with `denial_reason` set to `CONSENT_EXPIRED`.

Approval of a verification request enforces four checks, evaluated in this order so that an early failure is not masked by a later one. First, FERPA consent: if the subject student's `ferpa_restricted` flag is true, or the requested `scope` is anything other than `ENROLLMENT_ONLY`, then an `ACTIVE` `ConsentGrant` recorded against the subject student (its `student_id` equals the subject's `id`) must exist whose `grantee_name` equals the request's `requester_name`, whose `scope` covers the requested scope under the ordering `ENROLLMENT_ONLY` < `DEGREE_ONLY` < `FULL_RECORD` (a grant covers its own scope and every narrower one), and whose `expires_at` is strictly later than the current logical clock; failing this yields `ERR_FERPA_CONSENT_REQUIRED` (HTTP 422). Second, the hold screen: no `Hold` on the subject may be `ACTIVE` with a `blocking_scope` of `ALL`; a blocking hold yields `ERR_HOLD_BLOCKING`. Third, segregation of duties: the reviewer's `X-User-ID` must differ from the `id` of the `Student` who is the subject; a self-review is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Fourth, the request must currently sit in `CONSENT_CHECK`; any other state yields `ERR_INVALID_STATE`. On success the server computes `fee_cents` and moves the request from `CONSENT_CHECK` to `APPROVED`. The verification fee is a flat 500-cent base, plus 300 cents when the scope is `DEGREE_ONLY` or 700 cents when it is `FULL_RECORD` (no scope surcharge for `ENROLLMENT_ONLY`), plus a 1500-cent historical-lookup surcharge when the subject student's `archived_record_flag` is true. Denial from `CONSENT_CHECK` moves the request to `DENIED` and records the supplied `denial_reason`. An approved request waits in `APPROVED` until the clearinghouse sweep carries it onward.

### 3.10. Reissue: Correcting a Delivered Credential

A `Student` opens a `ReissueRequest` against a delivered order by supplying a `reason` — one of `NAME_CORRECTION`, `RECORD_CORRECTION`, `DAMAGED_IN_MAIL`, `NEVER_RECEIVED`, or `WRONG_RECIPIENT` — and an optional `fee_waived` flag defaulting to false. The target order must currently be in `DELIVERED`, otherwise the request is rejected with `ERR_REISSUE_SOURCE_INVALID` (HTTP 422); the replacement must also reference the same student as the original. Opening the request moves the original order's `fulfillment_status` from `DELIVERED` to `REISSUE_PENDING` and increments its `version`.

Review is segregated: the `RegistrarReviewer` who approves or rejects must have an `X-User-ID` different from the `id` of the `Student` who placed the original order, otherwise the action is rejected with `ERR_SEGREGATION_OF_DUTIES`; on both approve and reject this segregation check runs before any state check. Approval requires the `ReissueRequest` to be in `REQUESTED` and the original order to be in `REISSUE_PENDING`. On approval the request moves to `APPROVED`, `reviewed_by` is set to the reviewer's `X-User-ID`, and a replacement `TranscriptOrder` is created with `reissue_of_order_id` pointing at the original and `fulfillment_status` initialized to `READY_TO_FULFILL`; the `ReissueRequest`'s `replacement_order_id` is populated with the new order's `id`. The replacement inherits the original's `student_id`, `order_kind`, `rush_requested`, and `submitted_at`, and starts with `rush_qualified` false and both `quoted_fee_cents` and `final_fee_cents` at 0. The replacement's line items are copied from the original — `recipient_id`, `delivery_kind`, `quantity`, `unit_price_cents`, and `archived_retrieval_id` carried over, `tracking_ref` null — with `line_status` set to `QUEUED`. When `fee_waived` is true the replacement's `payment_status` is initialized to `WAIVED`; otherwise the replacement runs through normal authorization. The original order's `fulfillment_status` advances from `REISSUE_PENDING` back into `IN_TRANSIT` — the original remains recorded as delivered historically while the replacement proceeds. Both orders have their `version` incremented, and a `REISSUE_APPROVED` audit event is emitted. Rejection requires the same segregation check, moves the `ReissueRequest` from `REQUESTED` to `REJECTED`, and reverts the original order from `REISSUE_PENDING` to `DELIVERED`. Once the replacement order itself reaches `DELIVERED`, the `ReissueRequest` moves automatically from `APPROVED` to `FULFILLED`.

### 3.11. Clearinghouse Reporting

Regulatory reporting runs through `ClearinghouseReportBatch`. A `RegistrarOperator` opens a batch by supplying `report_period_start` (inclusive) and `report_period_end` (exclusive). Opening the batch runs the sweep, which pins its inclusion set: a `TranscriptOrder` is swept in when its `fulfillment_status` is `DELIVERED`, its `submitted_at` falls within the reporting period (at or after the start and strictly before the end), and it is not already a member of any batch in `OPEN`, `LOCKED`, `TRANSMITTED`, or `ACKED`; a `VerificationRequest` is swept in when its status is `APPROVED`, its `updated_at` falls within the same period, and it has not already been swept into a non-failed batch. When two items share the same `submitted_at`, sweep order is broken by `created_at` ascending — never by `id`. The batch's `order_count` and `verification_count` record how many of each were swept in.

Locking an `OPEN` batch first re-runs the sweep against the current state and then freezes the resulting membership so no further items may be swept in; a lock whose re-swept `order_count` plus `verification_count` is 0 is rejected with `ERR_BATCH_EMPTY` (HTTP 422), and a lock against a batch no longer in `OPEN` is rejected with `ERR_INVALID_STATE` (HTTP 409). Transmitting a `LOCKED` batch stamps `transmitted_at`, moves the batch from `LOCKED` to `TRANSMITTED`, and cascades: every swept `APPROVED` `VerificationRequest` transitions to `REPORTED`. The transmitted batch then awaits acknowledgement, which moves it from `TRANSMITTED` to `ACKED`. If transmission failed, marking the batch failed moves it from `TRANSMITTED` to `FAILED` and unlocks membership — the swept verification requests the transmission had moved to `REPORTED` revert to `APPROVED` — so the next sweep re-includes the same items: the compensating action that keeps reporting eventual.

## 4. Endpoint Definitions

All endpoints are mounted under `/registrar`. Endpoints that create a new resource return HTTP 201; endpoints that modify an existing resource, run an action, or retrieve data return HTTP 200. Error responses use the standard error envelope from §2.2.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /registrar/students | Register a student record subject | RegistrarAdmin |
| GET | /registrar/students | List students | RegistrarAdmin, RegistrarOperator, RegistrarReviewer, BursarOffice, LibraryOffice, ArchiveClerk |
| GET | /registrar/students/{id} | Fetch one student | RegistrarAdmin, RegistrarOperator, RegistrarReviewer, BursarOffice, LibraryOffice, ArchiveClerk, Student |
| PATCH | /registrar/students/{id} | Update student status / FERPA / archive flags | RegistrarAdmin |
| GET | /registrar/students/{id}/records | List record snapshots for a student | RegistrarAdmin, RegistrarOperator, RegistrarReviewer, Student |
| POST | /registrar/students/{id}/records | Publish a new record snapshot | RegistrarAdmin |
| POST | /registrar/recipients | Register a recipient | RegistrarAdmin, RegistrarOperator |
| GET | /registrar/recipients | List recipients | RegistrarAdmin, RegistrarOperator, RegistrarReviewer, Student |
| GET | /registrar/recipients/{id} | Fetch one recipient | RegistrarAdmin, RegistrarOperator, RegistrarReviewer, Student |
| PATCH | /registrar/recipients/{id} | Update recipient display name / routing fields / active flag | RegistrarAdmin, RegistrarOperator |
| POST | /registrar/holds | Place a hold on a student | BursarOffice, LibraryOffice, RegistrarAdmin |
| GET | /registrar/holds | List holds (filtered) | RegistrarAdmin, RegistrarOperator, RegistrarReviewer, BursarOffice, LibraryOffice, Student |
| GET | /registrar/students/{id}/holds | List holds for a student | RegistrarAdmin, RegistrarOperator, RegistrarReviewer, BursarOffice, LibraryOffice, Student |
| GET | /registrar/holds/{id} | Fetch one hold | RegistrarAdmin, RegistrarOperator, RegistrarReviewer, BursarOffice, LibraryOffice, Student |
| POST | /registrar/holds/{id}/release | Release an ACTIVE hold (segregated by office) | BursarOffice, LibraryOffice, RegistrarAdmin |
| POST | /registrar/identity-verifications | Start identity verification for a (student, order) pair | Student |
| GET | /registrar/identity-verifications/{id} | Fetch one identity verification | RegistrarAdmin, RegistrarOperator, RegistrarReviewer, Student |
| GET | /registrar/students/{id}/identity-verifications | List identity verifications for a student | RegistrarAdmin, RegistrarOperator, RegistrarReviewer, Student |
| GET | /registrar/orders/{id}/identity-verifications | List identity verifications bound to an order | RegistrarAdmin, RegistrarOperator, RegistrarReviewer, Student |
| POST | /registrar/identity-verifications/{id}/confirm | Confirm identity with the one-time token | Student |
| POST | /registrar/identity-verifications/{id}/reject | Reject a PENDING identity verification | RegistrarReviewer |
| POST | /registrar/orders | Create a DRAFT transcript order | Student |
| GET | /registrar/orders | List orders | RegistrarAdmin, RegistrarOperator, RegistrarReviewer, Student |
| GET | /registrar/orders/{id} | Fetch one order | RegistrarAdmin, RegistrarOperator, RegistrarReviewer, Student |
| GET | /registrar/orders/{id}/quote-preview | Provisional fee quote (DRAFT only) | RegistrarAdmin, RegistrarOperator, Student |
| POST | /registrar/orders/{id}/line-items | Add a line item to a DRAFT order (OCC) | Student |
| GET | /registrar/orders/{id}/line-items | List line items for an order | RegistrarAdmin, RegistrarOperator, RegistrarReviewer, Student |
| POST | /registrar/orders/{id}/submit | Submit a DRAFT order (OCC) | Student |
| POST | /registrar/orders/{id}/cancel | Cancel an order | Student |
| GET | /registrar/line-items | List line items (FK reverse-lookup) | RegistrarAdmin, RegistrarOperator, RegistrarReviewer, Student |
| GET | /registrar/line-items/{id} | Fetch one line item | RegistrarAdmin, RegistrarOperator, RegistrarReviewer, Student |
| POST | /registrar/line-items/{id}/dispatch | Mark a QUEUED line item as SENT | RegistrarOperator |
| POST | /registrar/line-items/{id}/mark-delivered | Mark a SENT line item as DELIVERED | RegistrarOperator |
| POST | /registrar/line-items/{id}/mark-bounced | Mark a SENT line item as BOUNCED | RegistrarOperator |
| POST | /registrar/payments | Authorize a payment for an order | Student |
| GET | /registrar/payments/{id} | Fetch one payment | RegistrarAdmin, RegistrarOperator, RegistrarReviewer, Student |
| GET | /registrar/orders/{id}/payments | List payments for an order | RegistrarAdmin, RegistrarOperator, RegistrarReviewer, Student |
| POST | /registrar/payments/{id}/capture | Capture an authorized payment | RegistrarOperator |
| POST | /registrar/payments/{id}/refund | Refund a captured payment | RegistrarOperator |
| POST | /registrar/payments/{id}/void | Void an authorized payment | RegistrarOperator |
| POST | /registrar/consent-grants | Student grants a third party consent | Student |
| GET | /registrar/consent-grants | List consent grants | RegistrarAdmin, RegistrarOperator, RegistrarReviewer, Student |
| GET | /registrar/students/{id}/consent-grants | List a student's consent grants | RegistrarAdmin, RegistrarOperator, RegistrarReviewer, Student |
| GET | /registrar/consent-grants/{id} | Fetch one consent grant | RegistrarAdmin, RegistrarOperator, RegistrarReviewer, Student |
| POST | /registrar/consent-grants/{id}/revoke | Student revokes an ACTIVE grant | Student |
| POST | /registrar/verification-requests | Third party initiates a verification request | VerificationRequester |
| GET | /registrar/verification-requests | List verification requests | RegistrarAdmin, RegistrarOperator, RegistrarReviewer, VerificationRequester |
| GET | /registrar/verification-requests/{id} | Fetch one verification request | RegistrarAdmin, RegistrarOperator, RegistrarReviewer, VerificationRequester |
| GET | /registrar/students/{id}/verification-requests | List verification requests against a student | RegistrarAdmin, RegistrarOperator, RegistrarReviewer, Student |
| POST | /registrar/verification-requests/{id}/begin-review | Move request RECEIVED to CONSENT_CHECK | RegistrarReviewer |
| POST | /registrar/verification-requests/{id}/approve | Approve a request | RegistrarReviewer |
| POST | /registrar/verification-requests/{id}/deny | Deny a request in CONSENT_CHECK | RegistrarReviewer |
| POST | /registrar/archived-retrievals | Request an archived record retrieval | RegistrarOperator, ArchiveClerk |
| GET | /registrar/archived-retrievals | List archived retrievals | RegistrarAdmin, RegistrarOperator, ArchiveClerk |
| GET | /registrar/archived-retrievals/{id} | Fetch one archived retrieval | RegistrarAdmin, RegistrarOperator, ArchiveClerk |
| GET | /registrar/students/{id}/archived-retrievals | List archived retrievals for a student | RegistrarAdmin, RegistrarOperator, ArchiveClerk, Student |
| POST | /registrar/archived-retrievals/{id}/mark-pulled | Mark retrieval REQUESTED to PULLED | ArchiveClerk |
| POST | /registrar/archived-retrievals/{id}/attach-record | Mark retrieval PULLED to DIGITIZED | ArchiveClerk |
| POST | /registrar/archived-retrievals/{id}/attach-to-order | Mark retrieval DIGITIZED to ATTACHED | ArchiveClerk |
| POST | /registrar/archived-retrievals/{id}/mark-failed | Mark retrieval REQUESTED to FAILED | ArchiveClerk |
| POST | /registrar/orders/{id}/reissue-requests | Open a reissue request against a DELIVERED order | Student |
| GET | /registrar/reissue-requests | List reissue requests | RegistrarAdmin, RegistrarOperator, RegistrarReviewer, Student |
| GET | /registrar/reissue-requests/{id} | Fetch one reissue request | RegistrarAdmin, RegistrarOperator, RegistrarReviewer, Student |
| POST | /registrar/reissue-requests/{id}/approve | Approve a reissue (creates replacement) | RegistrarReviewer |
| POST | /registrar/reissue-requests/{id}/reject | Reject a reissue | RegistrarReviewer |
| POST | /registrar/clearinghouse-batches | Open a new report batch and sweep | RegistrarOperator |
| GET | /registrar/clearinghouse-batches | List batches | RegistrarAdmin, RegistrarOperator, RegistrarReviewer |
| GET | /registrar/clearinghouse-batches/{id} | Fetch one batch | RegistrarAdmin, RegistrarOperator, RegistrarReviewer |
| POST | /registrar/clearinghouse-batches/{id}/lock | Lock an OPEN batch | RegistrarOperator |
| POST | /registrar/clearinghouse-batches/{id}/transmit | Transmit a LOCKED batch | RegistrarOperator |
| POST | /registrar/clearinghouse-batches/{id}/ack | Acknowledge a TRANSMITTED batch | RegistrarOperator |
| POST | /registrar/clearinghouse-batches/{id}/mark-failed | Mark a TRANSMITTED batch FAILED | RegistrarOperator |
| POST | /registrar/fee-schedules | Register a fee schedule with effective window | RegistrarAdmin |
| GET | /registrar/fee-schedules | List fee schedules | RegistrarAdmin, RegistrarOperator, RegistrarReviewer |
| GET | /registrar/fee-schedules/{id} | Fetch one fee schedule | RegistrarAdmin, RegistrarOperator, RegistrarReviewer |
| GET | /registrar/audit-events | List audit events (append-only) | RegistrarAdmin, RegistrarReviewer |
| POST | /registrar/_clock/set_current_utc | Set the server's logical clock | RegistrarAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_REFERENCED_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_REQUEST | 400 |
| ERR_FERPA_CONSENT_REQUIRED | 422 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_HOLD_OFFICE_MISMATCH | 403 |
| ERR_HOLD_BLOCKING | 422 |
| ERR_RECIPIENT_ROUTING_INVALID | 422 |
| ERR_IDENTITY_NOT_VERIFIED | 422 |
| ERR_CONSENT_EXPIRED | 422 |
| ERR_VERIFICATION_EXPIRED | 422 |
| ERR_SCHEDULE_WINDOW_INVALID | 422 |
| ERR_REISSUE_SOURCE_INVALID | 422 |
| ERR_CAPTURE_EXCEEDS_AUTHORIZED | 422 |
| ERR_REFUND_EXCEEDS_CAPTURED | 422 |
| ERR_IDEMPOTENCY_CONFLICT | 409 |
| ERR_ORDER_NOT_DRAFT | 409 |
| ERR_RECIPIENT_INACTIVE | 422 |
| ERR_NO_BLOCKING_HOLD | 422 |
| ERR_RETRIEVAL_SLA_BREACHED | 422 |
| ERR_BATCH_EMPTY | 422 |
| ERR_BATCH_ALREADY_LOCKED | 409 |
