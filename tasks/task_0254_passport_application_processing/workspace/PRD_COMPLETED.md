# Passport Application Processing API — Product Requirements Document

## 1. Introduction

This document specifies the Passport Application Processing API, a back-office system that governs the end-to-end lifecycle of a travel-document application — from the moment an applicant opens a draft, through document verification at an acceptance facility, fee collection, risk adjudication, and finally issuance. The domain is deliberately branchy: an application follows a materially different path depending on whether it is a brand-new application, a renewal of an existing document, or an application filed on behalf of a minor child, and each branch pulls in its own set of required documents, fees, and execution obligations.

The system serves three operational constituencies whose duties are intentionally separated. Applicants (and the guardians who act for minors) assemble their own paperwork, pay their fees, and book appointments. Front-counter acceptance agents physically execute and verify the documents an applicant brings in. Back-office adjudicators make the approve/reject decision and issue the document. A core compliance requirement threaded throughout is **segregation of duties**: the officer who adjudicates an application must never be the same person who executed and verified its documents. Layered on top of the main lifecycle are a parallel name-change workflow, an automated photo-validation gate, a weighted document-risk score that can divert an application into manual review, two distinct kinds of appointment scheduling with different interval semantics, and a strictly conserved fee ledger in which every refund exactly reverses its original charge.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that apply across every endpoint. The entire API is mounted under the `/applications` family of paths together with the sibling resource collections described in Section 4.

### 2.1. User and Role-Based Access Control

Every request, with two explicit exceptions noted below, must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the capacity in which they are acting. If either header is missing or malformed, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The two endpoints that do not require authentication headers are applicant registration and the test-only clock-setting capability; all other endpoints require them.

The system recognizes exactly three roles, spelled precisely as follows: `Applicant`, `AcceptanceAgent`, and `Adjudicator`. Once a request is authenticated, the system checks whether the acting role is permitted to invoke the requested operation. A role attempting an operation it is not authorized for is rejected with `ERR_FORBIDDEN` (HTTP 403).

All three roles are entity-backed, meaning `X-User-ID` ties directly to a persisted record and is used for ownership and segregation checks:

- When `X-User-Role` is `Applicant`, `X-User-ID` is the `id` of the acting `Applicant`; ownership checks on any resource that references an `Applicant` (for example, an `Application` via its `applicant_id`, or downstream documents, photos, fees, and appointments reachable from that application) compare the resource's owning applicant to `X-User-ID`. A guardian acting for a minor is itself an `Applicant` record.
- When `X-User-Role` is `AcceptanceAgent`, `X-User-ID` is the `id` of the acting `AcceptanceAgent`; ownership and segregation checks compare an application's `assigned_acceptance_agent_id` to `X-User-ID`. An agent may only verify documents on an application whose verification they themselves began.
- When `X-User-Role` is `Adjudicator`, `X-User-ID` is the `id` of the acting `Adjudicator`; the segregation-of-duties check compares the acting adjudicator's identity against the application's `assigned_acceptance_agent_id` so that the same person cannot both verify and adjudicate.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. A `limit` or `offset` that is not parseable as an integer, a `limit` outside the inclusive `[1, 100]` range, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order; when two records share the same creation timestamp, ties are broken by a monotonic creation sequence so that insertion order is preserved.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Most resources in the system carry a standard set of system-managed fields. Every such resource exposes an `id` (a server-minted UUID with no type prefix), a `created_at` (an ISO 8601 UTC timestamp with three fractional digits recorded at creation), an `updated_at` (an ISO 8601 UTC timestamp refreshed on every mutation), and a `version` (an integer that begins at its initial value and increments by one on every mutation of that resource). The `version` field is what the optimistic-concurrency mechanism described in Section 2.7 reads.

Two entities are intentionally lighter-weight and carry **only** `id` and `created_at` — they have neither an `updated_at` nor a `version` field, because they are immutable append-only records once written. These are the `Photo` and the `ApplicationStatusEvent`. A `Photo`'s validation outcome is recomputed through an explicit re-validation operation that rewrites the same record's `validation_result` and `failure_reasons` in place, but the system does not maintain `updated_at`/`version` audit fields on it. Every other entity — `Applicant`, `Application`, `AcceptanceAgent`, `Adjudicator`, `SupportingDocument`, `FeeAssessment`, `Appointment`, `AcceptanceFacility`, `UrgentTravelCounter`, and `AdjudicationDecision` — carries the full `id`/`created_at`/`updated_at`/`version` set.

When a derived field is recomputed as a side effect of an operation — for example when an applicant's `verification_risk_score` is refreshed, or an application's `target_completion_date` is recomputed — that recomputation is a mutation of the owning resource: it refreshes `updated_at` and increments `version` exactly as a direct edit would.

### 2.5. Monetary Values, Precision, and Rounding

All monetary amounts in the system are expressed and stored as **integer cents**. There are no fractional cents; every fee component is a whole number of cents, and a total is the exact integer sum of its components. The fee calculation performs a single combination of its components at the very end with no intermediate rounding, which is exact because all inputs are already integers.

The one place fractional arithmetic appears is the verification risk score, which is computed with decimal weights and is rounded to exactly 2 decimal places using the round-half-up convention. The score is stored on the applicant with that 2-decimal precision.

### 2.6. Status History and Audit Trail

Every transition of an application's main lifecycle status appends an immutable `ApplicationStatusEvent` record capturing `application_id`, the `from_status` (the status before the transition), the `to_status` (the status after the transition), the `actor_role` (the role that triggered the transition), and `occurred_at` (the ISO 8601 UTC timestamp of the transition, equal to the system clock at that moment). No event is appended at application creation itself — the first event is the `DRAFT`-to-`SUBMITTED` transition recorded at submission, whose `from_status` is `DRAFT` — so in practice `from_status` is never null on any recorded event. For transitions the system performs on its own (the auto-advance out of verification into `ADJUDICATING`, and the risk-driven move into `REVIEW_HOLD`), `actor_role` is the literal string `"system"`; for the directly invoked transitions it is the acting role (`Applicant`, `AcceptanceAgent`, or `Adjudicator`). These events are retrievable in chronological order by `occurred_at` and form the application's audit trail. They are append-only and carry no `updated_at` or `version`.

The system clock that stamps `occurred_at`, `submitted_at`, `verification_completed_at`, the minor-age computation, and the SLA target dates is a single logical clock. For deterministic test driving, an administrative capability lets an authorized officer set this clock to a supplied instant, passed as `to_iso8601`; the new clock value (returned as `current_utc`) governs all subsequent time-derived computations.

### 2.7. Optimistic Concurrency Control

Two write operations defend against acting on a stale view of an application by requiring an optimistic-concurrency token. In both, the request body must carry `expected_application_version`, which is the `version` of the target `Application` that the client last observed, and it is a required (non-optional) field on those two operations. If `expected_application_version` does not equal the application's current `version` at the time the server processes the request, the operation is rejected with `ERR_STALE_VERSION` (HTTP 412) and no change is made.

The first guarded operation is **booking an appointment** for an application. If another writer has advanced the application's `version` since the client last read it — most importantly by booking the single permitted urgent-travel-counter appointment, which legitimately flips the application's `urgent_travel` flag to true and re-derives the fee — then the booking client's snapshot is stale and the booking is rejected with `ERR_STALE_VERSION`. The second guarded operation is **submitting an application**, which is the operation that creates the application's fee assessment. The application's `version` may have advanced since the client's last read because a name-change cascade or a photo re-validation mutated the application; submitting from that stale snapshot is rejected with `ERR_STALE_VERSION`. No operation other than these two takes a version field.

### 2.8. Nested Resource Retrieval and Existence Ordering

Many endpoints carry one or more resource identifiers in the path (for example, an application id followed by a sub-collection such as its documents or photos). The system validates path identifiers strictly left-to-right and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier in the path that does not correspond to an existing resource, before considering any later identifier or the request body. Separately, when a request body carries a foreign-key reference — `applicant_id`, `application_id`, `facility_id`, `counter_id`, `adjudicator_id`, and the like — and that reference points to a resource that does not exist, the request is rejected with `ERR_FK_NOT_FOUND` (HTTP 422). Path-id absence yields `ERR_NOT_FOUND`; body foreign-key absence yields `ERR_FK_NOT_FOUND`.

### 2.9. Validation Ordering and Error Precedence

When several checks could apply to one request, they are evaluated in a fixed priority order, and the first failing check determines the error returned. The ordering is:

1. **Authentication** — `X-User-Role` and `X-User-ID` present and well-formed; otherwise `ERR_UNAUTHENTICATED`. This applies to every endpoint except applicant registration and the clock-setting capability.
2. **Authorization** — the acting role is permitted for this endpoint; otherwise `ERR_FORBIDDEN`. This applies to every endpoint.
3. **Path existence** — every path-referenced resource exists, checked left-to-right; otherwise `ERR_NOT_FOUND`. Applies to all endpoints with path ids or body foreign keys.
4. **Foreign-key existence** — body foreign-key fields reference existing resources; otherwise `ERR_FK_NOT_FOUND`. Applies to create and booking endpoints.
5. **Transition definedness** — the target resource is in a state from which the requested transition is defined; otherwise `ERR_INVALID_STATE`. Applies to all transition endpoints.
6. **Terminality** — a resource already in a terminal state rejects any further transition with `ERR_ALREADY_TERMINAL`. The terminal states are: applications in `ISSUED`, `REJECTED`, or `WITHDRAWN`; a fee assessment in `REFUNDED`; and an appointment in `COMPLETED` or `CANCELLED`. Applies to transition endpoints.
7. **Segregation of duties** — `ERR_SOD_VIOLATION`, as described in Sections 2.1 and 3.
8. **Photo validity at submit** — `ERR_PHOTO_INVALID`.
9. **Guardian consent at submit** — `ERR_GUARDIAN_CONSENT_REQUIRED`.
10. **Name-change evidence** — `ERR_NAME_CHANGE_EVIDENCE_REQUIRED`.
11. **Facility slot conflict** — `ERR_FACILITY_SLOT_CONFLICT`.
12. **Counter slot conflict** — `ERR_COUNTER_SLOT_CONFLICT`.
13. **Appointment interval validity** — `ERR_INVALID_INTERVAL`.
14. **Single urgent appointment** — `ERR_DUPLICATE_URGENT_APPOINTMENT`.
15. **Exact payment amount** — `ERR_PAYMENT_AMOUNT_MISMATCH`.
16. **Fee paid before verification** — `ERR_FEE_UNPAID`.
17. **Optimistic concurrency** — `expected_application_version` matches current `version`; otherwise `ERR_STALE_VERSION`.
18. **Request well-formedness** — body field types and enum membership are valid and required fields are present; otherwise `ERR_INVALID_REQUEST`. Applies to all endpoints.

This priority order governs the structural and business checks (priorities 3 through 17) as listed. The well-formedness of the discriminating `decision` field on the two decide endpoints — `POST /applications/{id}/adjudicate` and `POST /applications/{id}/name-change/decide` — is, however, validated up front (immediately after path existence and before the transition-definedness, terminality, and segregation checks), since that field selects which branch of the operation runs; a missing or out-of-enum `decision` on those two endpoints therefore yields `ERR_INVALID_REQUEST` ahead of any state or terminality error. On the document-verify endpoint the `outcome` field is instead validated after the structural checks, in priority-18 position. Across the transition endpoints, this ordering means existence is checked before state, state is checked before segregation-of-duties, and the fiscal and concurrency checks come after the structural ones. Field-range violations distinct from malformed-request errors (for example a `declared_quality` outside the 0-through-100 range, or a `head_height_fraction` not strictly between 0 and 1) are reported as `ERR_VALIDATION` (HTTP 422).

## 3. Business Logic & Workflows

### 3.1. Registering Participants and Setting Up Facilities

Before any application can move, the participants and the physical infrastructure must exist. An applicant is registered by supplying their `full_legal_name` (a non-empty string of at most 120 characters), their `date_of_birth` (an ISO date in `YYYY-MM-DD` form, which must be a valid date in the past), and a contact `email` that doubles as the applicant's unique identity handle. The email is normalized to lowercase and must be unique across all applicants; a registration whose normalized email collides with an existing applicant is rejected with `ERR_INVALID_REQUEST` (HTTP 400). For a minor's own applicant record, a `guardian_applicant_id` may be supplied pointing to the parent or guardian's applicant record; for an adult this is null and defaults to null. When a `guardian_applicant_id` is supplied but references no existing applicant, the registration is rejected with `ERR_FK_NOT_FOUND` (HTTP 422). At registration the system computes the applicant's `is_minor` flag against the current clock: an applicant is a minor when the difference between today's date (from the clock) and their `date_of_birth` is strictly less than 16 years — that is, the applicant has not yet reached their sixteenth birthday. The `is_minor` flag is recomputed whenever it is referenced, and is pinned onto an application at the moment that application is created.

An applicant record also exposes three computed, read-only quantities maintained by the system: `verification_risk_score` (the weighted document-risk figure described in Section 3.6, stored to 2 decimals), `total_fees_paid_cents` (a conserved ledger described in Section 3.5, defaulting to 0), and `is_minor`. These are never supplied on input.

Adjudicators administer the supporting infrastructure. An acceptance facility is created with a `name` and a two-letter, uppercase `state_code` (exactly length 2). An urgent-travel counter is created with a `name` and an optional `cleanup_buffer_minutes` — a non-negative integer (at least 0) that defaults to 15 and that extends the exclusion window around each booking on that counter (see Section 3.7). An acceptance agent is registered with a `name`, a `badge_number` that is unique across all acceptance agents, and the `facility_id` of the facility they staff; a duplicate `badge_number` is rejected with `ERR_INVALID_REQUEST` (HTTP 400), and a `facility_id` that references no existing facility is rejected with `ERR_FK_NOT_FOUND` (HTTP 422). An adjudicator is registered with a `name` and a `passport_office_code` that is unique across all adjudicators; a duplicate `passport_office_code` is likewise rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 3.2. Opening an Application and Choosing a Path

An applicant opens an application in `DRAFT` by supplying the `applicant_id` of the primary applicant (for a minor application this is the minor child's own applicant record), the `application_type`, the `product_type`, and optionally the `service_level`, `name_change_requested`, and `prior_name`. The `application_type` is one of `NEW`, `RENEWAL`, or `MINOR` and selects the processing path. The `product_type` is one of `BOOK`, `CARD`, or `BOOK_AND_CARD` and names the requested travel-document product. The `service_level` is either `ROUTINE` or `EXPEDITE` and defaults to `ROUTINE`. The application begins with `status` equal to `DRAFT`.

At creation the system pins two computed snapshots onto the application. First, `applicant_is_minor` captures the primary applicant's `is_minor` value as of creation; this snapshot drives both the base-fee age band and the execution requirement. Second, `requires_execution` is determined as follows: it is true whenever the `application_type` is `NEW` or `MINOR`; for a `RENEWAL` it is true only when `name_change_requested` is true and the requested name change is not eligible for handling by mail, and it is false for a plain renewal. The system carries no mail-eligibility input or signal of its own, so in practice every `RENEWAL` whose `name_change_requested` is true is treated as not mail-eligible and therefore has `requires_execution` true, while a `RENEWAL` with `name_change_requested` false has `requires_execution` false. This flag drives the execution fee described in Section 3.5.

The `name_change_requested` field (defaulting to false) records whether the applicant is requesting a legal name change on this application, and `prior_name` holds the former legal name when a name change is requested and is null otherwise (defaulting to null). The application also carries a parallel name-change sub-status, `name_change_status`, which is independent of the main `status` and which begins at `NONE`. If the application is created with `name_change_requested` set to true, the system immediately moves `name_change_status` from `NONE` to `PENDING_EVIDENCE` as a creation-time side effect, while the main status remains `DRAFT`. The complete name-change lifecycle is described in Section 3.4.

Several other application fields are computed or system-stamped over the lifecycle and never accepted as input: `status`, `applicant_is_minor`, `requires_execution`, `name_change_status`, `urgent_travel` (defaulting to false, described in Section 3.7), `submitted_at` (null while in `DRAFT`), `verification_completed_at` (null until verification finishes), and `target_completion_date` (null until submission). The `assigned_acceptance_agent_id` and `adjudicator_id` are populated by the workflow as the application passes through verification and adjudication.

### 3.3. Assembling Documents and Photos, Then Submitting

While in `DRAFT`, the applicant attaches the supporting paperwork. A supporting document is attached by providing its `doc_category` — one of `IDENTITY`, `CITIZENSHIP`, `GUARDIAN_CONSENT`, or `NAME_CHANGE_EVIDENCE` — together with a `doc_kind` describing the specific document (such as `DRIVERS_LICENSE`, `BIRTH_CERTIFICATE`, or `MARRIAGE_CERTIFICATE`) and an optional `declared_quality`, a self-declared legibility score from 0 through 100 that defaults to 100 and that feeds the risk score once the document is accepted. A `declared_quality` outside the 0-through-100 range is rejected with `ERR_VALIDATION`. A freshly attached document begins with `verification_status` equal to `PENDING` and a null `reviewed_by_agent_id`; both `application_id` (which document it supports) and these computed fields are part of the record.

A photo is attached by supplying `width_px`, `height_px`, `head_height_fraction`, and `background_is_white`. Both pixel dimensions must be greater than 0 and `head_height_fraction` must be strictly between 0 and 1 (any value not strictly inside the open interval from 0 to 1, or a non-positive dimension, is rejected — a non-positive dimension as `ERR_INVALID_REQUEST` and an out-of-(0,1) fraction as `ERR_VALIDATION`). The photo records its owning `application_id`. Photo validation runs immediately on attachment and again on demand through a re-validation capability that may override any of the four inputs; the outcome is written to `validation_result` (one of `PENDING`, `PASS`, or `FAIL`, defaulting to `PENDING`) and the list of failed-rule codes is written to `failure_reasons` (empty on a pass). The four photo rules, evaluated together, are:

- Both `width_px` and `height_px` must be at least 600 pixels; if either is below 600, the code `DIMENSION_TOO_SMALL` is added.
- The aspect ratio, computed as `width_px` divided by `height_px`, must be at least 0.98 and at most 1.02; outside that inclusive band the code `NOT_SQUARE` is added.
- The `head_height_fraction` must be at least 0.50 and at most 0.69; outside that inclusive band the code `HEAD_OUT_OF_RANGE` is added — so a fraction of exactly 0.69 passes this rule while exactly 0.70 fails it.
- The `background_is_white` flag must be true; if it is false, the code `BACKGROUND_NOT_WHITE` is added.

The validation result is `PASS` when no codes were added and `FAIL` otherwise, with `failure_reasons` holding exactly the codes that were added.

Submitting an application advances it from `DRAFT` to `SUBMITTED`. Submission is permitted only when the application is currently `DRAFT`; an attempt from any other state is rejected with `ERR_INVALID_STATE`, and a terminal application rejects it with `ERR_ALREADY_TERMINAL`. Submission carries `expected_application_version` and is subject to the stale-version rejection of Section 2.7. Three business preconditions guard submission, evaluated in the priority order of Section 2.9: there must be at least one photo on the application whose `validation_result` is `PASS` (a `FAIL` photo cannot satisfy this), failing which the submit is rejected with `ERR_PHOTO_INVALID`; for a `MINOR` application there must exist a supporting document with `doc_category` `GUARDIAN_CONSENT` and the primary applicant must have a non-null `guardian_applicant_id`, failing which the submit is rejected with `ERR_GUARDIAN_CONSENT_REQUIRED`; and if `name_change_requested` is true there must exist a supporting document with `doc_category` `NAME_CHANGE_EVIDENCE`, failing which the submit is rejected with `ERR_NAME_CHANGE_EVIDENCE_REQUIRED`.

When submission succeeds, the system performs a coordinated set of side effects: it stamps `submitted_at` to the current clock; it computes the forward-looking `target_completion_date` (Section 3.8); it creates the application's fee assessment with `payment_status` `UNPAID` (Section 3.5); it appends an `ApplicationStatusEvent` recording the move from `DRAFT` to `SUBMITTED`; it recomputes the applicant's `verification_risk_score` using the provisional inputs (Section 3.6); and it increments the application's `version` by one.

### 3.4. The Parallel Name-Change Workflow

The name-change sub-status runs alongside the main lifecycle on its own dimension and has its own terminal states, `APPROVED` and `DENIED`. As noted in Section 3.2, creating an application with `name_change_requested` true moves `name_change_status` from `NONE` to `PENDING_EVIDENCE` immediately, independently of the main status. The sub-status then advances from `PENDING_EVIDENCE` to `EVIDENCE_VERIFIED` automatically as a cascade when a supporting document of category `NAME_CHANGE_EVIDENCE` is accepted (moves from `PENDING` to `ACCEPTED`); this cascade fires only while the sub-status is `PENDING_EVIDENCE`.

Once the sub-status is `EVIDENCE_VERIFIED`, an adjudicator decides the name change. The decision endpoint accepts a `decision` field whose value is exactly one of `APPROVE` or `DENY`. Deciding to approve (`APPROVE`) advances `name_change_status` from `EVIDENCE_VERIFIED` to `APPROVED`, records the new legal name onto the applicant, and increments the application's `version` by one; because the application carries no separate "new legal name" field, the applicant's `full_legal_name` already holds the intended legal name and this step is an identity write of that same value (marking the applicant mutated) rather than a copy from an application field. Approving additionally re-evaluates the main-status auto-advance out of verification, so that if every required document is already accepted the now-`APPROVED` name-change dimension unblocks the move described in Section 3.6. Deciding to deny (`DENY`) advances `name_change_status` from `EVIDENCE_VERIFIED` to `DENIED` and increments the application's `version` by one. The decision requires the sub-status to be exactly `EVIDENCE_VERIFIED`: a decision attempted while the sub-status is `NONE` or `PENDING_EVIDENCE` is rejected with `ERR_NAME_CHANGE_EVIDENCE_REQUIRED`, while a decision attempted once the sub-status is already in one of its terminal sub-states `APPROVED` or `DENIED` is rejected with `ERR_ALREADY_TERMINAL`. Note that the main-status auto-advance out of verification additionally requires the name-change dimension to be either `NONE` or `APPROVED`, so a name change that is still pending or merely evidence-verified holds the application in verification until the adjudicator resolves it.

### 3.5. Fees, Payment, and the Conserved Ledger

Submission creates a fee assessment tied to the application via `application_id`. Its components are all computed and stored in integer cents. The **base fee** depends on the product and on whether the applicant is a minor (read from the pinned `applicant_is_minor`). For a book product, the base is 13000 cents ($130.00) for an adult and 10000 cents ($100.00) for a minor. For a card product, the base is 3000 cents ($30.00) for an adult and 1500 cents ($15.00) for a minor. For a combined book-and-card product, the base is the sum of the applicable book and card components less a bundle discount of 1000 cents ($10.00); for an adult this is 13000 plus 3000 minus 1000, that is 15000 cents, and for a minor it is 10000 plus 1500 minus 1000, that is 10500 cents — the bundle discount and the minor age band both apply. This computed base is stored as `base_fee_cents`.

Three surcharges and one delivery option round out the assessment. The `execution_fee_cents` is 3500 cents ($35.00) when the application's `requires_execution` is true, and 0 otherwise. The `expedite_fee_cents` is 6000 cents ($60.00) when `service_level` is `EXPEDITE`, and 0 otherwise. The `urgent_surcharge_cents` is 6000 cents ($60.00) when the application's `urgent_travel` is true, and 0 otherwise. The `one_day_delivery_cents` is 2136 cents ($21.36) when one-day return delivery is purchased — captured by the `one_day_delivery` boolean field stored on the assessment, which defaults to false — and 0 otherwise; no endpoint in this system accepts a `one_day_delivery` value as input, so an assessment is created with `one_day_delivery` false and the component stays 0 (and re-derivations while `UNPAID` preserve that stored false), making this component effectively 0 for every assessment. The `total_due_cents` is the exact sum of `base_fee_cents`, `execution_fee_cents`, `expedite_fee_cents`, `urgent_surcharge_cents`, and `one_day_delivery_cents`, combined once at the end with no intermediate rounding. The assessment also carries `amount_paid_cents` (a conserved ledger field defaulting to 0) and `payment_status`, which is one of `UNPAID`, `PAID`, or `REFUNDED` and starts at `UNPAID`.

Payment is performed by the applicant against an `UNPAID` assessment by tendering `amount_tendered_cents`. The tendered amount must exactly equal the assessment's `total_due_cents`; any other amount is rejected with `ERR_PAYMENT_AMOUNT_MISMATCH`. On success the assessment moves from `UNPAID` to `PAID`, `amount_paid_cents` is set to `total_due_cents`, the owning applicant's `total_fees_paid_cents` is incremented by `total_due_cents`, and the assessment's `version` increments by one. A payment attempt on an assessment not in `UNPAID` is rejected with `ERR_INVALID_STATE`, and a `REFUNDED` assessment (a terminal payment state) rejects it with `ERR_ALREADY_TERMINAL`.

The applicant's `total_fees_paid_cents` is a strictly conserved quantity: at any time it equals the sum of `amount_paid_cents` over all of that applicant's fee assessments that are currently `PAID`. A refund is a compensating action that exactly reverses its charge — when an assessment is refunded, the system decrements the applicant's `total_fees_paid_cents` by the assessment's current `amount_paid_cents` and then sets `amount_paid_cents` to 0, moving the assessment from `PAID` to `REFUNDED` and incrementing the assessment's `version`. Because the refund decrement equals the original payment increment, a pay-then-refund pair on the same assessment leaves `total_fees_paid_cents` exactly where it began, contributing a net of zero. Refunds are triggered only by the system as part of rejection or withdrawal compensation (Section 3.9), never directly.

### 3.6. Verification, the Risk Score, and the Review-Hold Gate

After the fee is paid, an acceptance agent begins verification, advancing the application from `SUBMITTED` to `IN_VERIFICATION`. This is permitted only when the application is `SUBMITTED` (otherwise `ERR_INVALID_STATE`) and the application's fee assessment has `payment_status` equal to `PAID` (otherwise `ERR_FEE_UNPAID`). The acting agent is pinned onto the application as its `assigned_acceptance_agent_id`, an `ApplicationStatusEvent` is appended for the move from `SUBMITTED` to `IN_VERIFICATION`, and the application's `version` increments by one. This pinning is the anchor of the segregation-of-duties controls.

While the application is `IN_VERIFICATION`, the assigned agent verifies each document. A document verification supplies an `outcome` and moves the document from `PENDING` to either `ACCEPTED` or `REJECTED`. Verification is permitted only when the document is `PENDING`, the parent application is `IN_VERIFICATION`, and the acting agent is the application's `assigned_acceptance_agent_id`; an agent who is not the assigned agent — including one who never began verification on this application — is rejected with `ERR_SOD_VIOLATION`. On either outcome the system sets the document's `reviewed_by_agent_id` to the acting agent, recomputes the applicant's `verification_risk_score` using the final inputs, and increments the parent application's `version` by one. Accepting a document additionally triggers two cascades: if the document's `doc_category` is `NAME_CHANGE_EVIDENCE`, the application's `name_change_status` advances from `PENDING_EVIDENCE` to `EVIDENCE_VERIFIED`; and if this acceptance was the last required document, the application auto-advances out of verification as described below.

The `verification_risk_score` is a weighted figure stored on the applicant to 2 decimal places, rounded half up. The system computes a per-factor quality for two document factors and one photo factor: the identity factor carries weight 0.40, the citizenship factor carries weight 0.35, and the photo factor carries weight 0.25. The factor pool is the applicant-wide set: it aggregates the supporting documents and photos across every `Application` owned by that applicant, not only the one currently being acted upon. For each document factor, the factor quality is the highest `declared_quality` among that applicant's accepted documents of that category (across all of the applicant's applications), or 0 if there are none accepted in that category. The photo quality is 100 if any photo on any of the applicant's applications has `validation_result` equal to `PASS`, and 0 otherwise. The combined quality is 0.40 times the identity factor quality plus 0.35 times the citizenship factor quality plus 0.25 times the photo quality. The risk is then 100 minus that combined quality, rounded half up to 2 decimal places.

The score has two variants distinguished by when it is taken. Both variants apply the same applicant-wide aggregation described above and use the identical formula; the only difference is the set of accepted documents in play at the moment of the recompute. The **provisional** variant is computed at submission, before any document has been verified: documents still `PENDING` contribute a factor quality of 0 (the worst case), so an applicant whose documents are all still pending but who has a passing photo scores exactly 75.00 (the photo factor alone contributes 25 of quality, leaving a risk of 75). The **final** variant is computed on every change to a supporting document's or photo's verification status: only `ACCEPTED` documents contribute their `declared_quality`, so once identity and citizenship documents are accepted at high quality the risk drops toward 0.00. The final variant drives the review-hold gate.

The review-hold gate is a strict threshold. When a final recompute of the applicant's `verification_risk_score` yields a score strictly greater than 50, the application, while `IN_VERIFICATION`, transitions to `REVIEW_HOLD`; a score of exactly 50.00 does not trigger the hold. This transition appends an `ApplicationStatusEvent` from `IN_VERIFICATION` to `REVIEW_HOLD` and increments the application's `version`. An adjudicator can clear the hold, which reverts the application from `REVIEW_HOLD` back to `IN_VERIFICATION` (permitted only from `REVIEW_HOLD`, otherwise `ERR_INVALID_STATE`), appends the corresponding status event, and increments `version`.

The required document set for an application is defined by category: `IDENTITY` and `CITIZENSHIP` are required for every application type; an application of type `MINOR` additionally requires `GUARDIAN_CONSENT`; and any application whose `name_change_requested` is true additionally requires `NAME_CHANGE_EVIDENCE`. A required category counts as accepted once at least one of its documents reaches `ACCEPTED`. When the last required supporting document is accepted, and provided the application is `IN_VERIFICATION`, every required category for the application's type has at least one `ACCEPTED` document, and the name-change dimension is `NONE` or `APPROVED`, the application auto-advances from `IN_VERIFICATION` to `ADJUDICATING` as the tail of that acceptance. This auto-advance stamps `verification_completed_at` to the current clock, recomputes the applicant's `verification_risk_score` using the final inputs, appends an `ApplicationStatusEvent` from `IN_VERIFICATION` to `ADJUDICATING`, and increments `version`. If, however, that final recompute yields a score strictly above 50, the application instead lands in `REVIEW_HOLD` rather than `ADJUDICATING`.

### 3.7. Booking Appointments: Two Resources, Two Interval Rules

An applicant books an appointment for an application by supplying the `application_id`, the `resource_kind` (either `ACCEPTANCE_FACILITY` or `URGENT_TRAVEL_COUNTER`), the appropriate resource reference, the `start_utc` and `end_utc` (both ISO 8601 UTC instants), and the `expected_application_version` token of Section 2.7. When `resource_kind` is `ACCEPTANCE_FACILITY`, the `facility_id` is set and `counter_id` is null; when it is `URGENT_TRAVEL_COUNTER`, the `counter_id` is set and `facility_id` is null. An appointment begins with `status` equal to `BOOKED`. The `end_utc` must be strictly after `start_utc`; otherwise the booking is rejected with `ERR_INVALID_INTERVAL`.

The two resource kinds use different conflict semantics. A facility appointment must not overlap any existing `BOOKED` facility appointment on the same facility, where overlap is judged on a half-open interval basis: each booking occupies the time from its `start_utc` up to but not including its `end_utc`, so two bookings that merely touch end-to-start (one ending exactly when the next begins) do not conflict, but any actual overlap is rejected with `ERR_FACILITY_SLOT_CONFLICT`. An urgent-travel-counter appointment is subject to a buffer-extended exclusion window: each existing `BOOKED` counter appointment occupies the time from its `start_utc` up to but not including its `end_utc` plus that counter's `cleanup_buffer_minutes`, and a new booking that falls anywhere inside that buffer-extended window is rejected with `ERR_COUNTER_SLOT_CONFLICT`; a new booking whose `start_utc` is exactly equal to an existing booking's `end_utc` plus the buffer is allowed, since the window is closed at its start and open at its extended end.

A further constraint applies to urgent-travel bookings: an application may hold at most one `BOOKED` urgent-travel-counter appointment at any time, and an attempt to book a second while one is still `BOOKED` is rejected with `ERR_DUPLICATE_URGENT_APPOINTMENT`. Booking a counter appointment has fiscal consequences: it sets the application's `urgent_travel` flag to true and, if the application's fee assessment is still `UNPAID`, re-derives that assessment so the urgent surcharge is reflected. Every booking increments the application's `version` by one.

Appointments can be completed or cancelled. An acceptance agent can complete a `BOOKED` appointment, moving it to `COMPLETED` (permitted only from `BOOKED`) and incrementing the appointment's `version`; the system also completes a `BOOKED` appointment automatically when the application is issued. An applicant can cancel a `BOOKED` appointment, moving it to `CANCELLED` and incrementing the appointment's `version`; cancellation also occurs automatically as part of rejection or withdrawal. When a cancelled appointment is an urgent-travel-counter appointment and no other `BOOKED` urgent appointment remains for that application, the system flips the application's `urgent_travel` back to false and re-derives the fee assessment if it is still `UNPAID`. A complete or cancel attempt on an appointment that is not `BOOKED` is rejected with `ERR_INVALID_STATE`, and on a `COMPLETED` or `CANCELLED` appointment with `ERR_ALREADY_TERMINAL`.

### 3.8. Processing Targets and the Computed Summary

At submission the system computes a forward-looking processing target and stores it on `target_completion_date` as an ISO date. The target is calendar-day arithmetic: a routine application is given 42 calendar days and an expedite application 21 calendar days, the chosen number depending on `service_level`. The forward-looking variant adds that span to the date portion of `submitted_at` — it assumes verification clears instantly, so the effective start is the submission date. The stored `target_completion_date` is recomputed at submission and whenever `service_level` changes.

A separate chronological variant of the same target uses the date portion of `verification_completed_at` as its effective start instead, adding the same 42-or-21 day span; this variant is null until verification has completed. The two variants are exposed together on the application summary, a computed read that recomputes the chronological variant on access and returns `forward_looking_target_date`, `chronological_target_date`, the current `total_due_cents`, the count of required documents `required_docs_total`, and the count of those accepted `required_docs_accepted`. The document progress is counted over the required document *categories* for the application's type (the same required-category set used by the verification auto-advance): `required_docs_total` is the number of those required categories and `required_docs_accepted` is the number of them having at least one `ACCEPTED` document. The summary's `total_due_cents` reads from the application's fee assessment if one exists; before submission (when no fee assessment has yet been created) it is reported as 0. For example, a seven-day delay between submission and verification completion makes the chronological target fall exactly seven calendar days after the forward-looking one.

### 3.9. Adjudication, Issuance, Withdrawal, and Compensation

Once an application reaches `ADJUDICATING`, an adjudicator decides it by supplying a `decision` (one of `APPROVE`, `REJECT`, or `RETURN_FOR_REVIEW`) and an optional `reason_code`. Every decision is permitted only from `ADJUDICATING` (otherwise `ERR_INVALID_STATE`) and creates an `AdjudicationDecision` record carrying the `application_id`, the deciding `adjudicator_id`, the `decision`, and the `reason_code`.

Approving and rejecting are both guarded by the segregation-of-duties rule: the acting adjudicator's underlying person must differ from the application's `assigned_acceptance_agent_id`; a violation is rejected with `ERR_SOD_VIOLATION`. Approving additionally requires the fee assessment to be `PAID`, checked after the segregation-of-duties guard; if it is not `PAID` the approve is rejected with `ERR_FEE_UNPAID`. On success the application moves from `ADJUDICATING` to `APPROVED`, the application's `adjudicator_id` is set to the acting adjudicator, a status event from `ADJUDICATING` to `APPROVED` is appended, and `version` increments. Rejecting moves the application from `ADJUDICATING` to `REJECTED` and triggers the full compensation cascade: the fee assessment, if `PAID`, is refunded (moved from `PAID` to `REFUNDED`, `amount_paid_cents` reset to 0, and the applicant's `total_fees_paid_cents` decremented by the refunded amount), any `BOOKED` appointment for the application is cancelled (moved to `CANCELLED`), a status event from `ADJUDICATING` to `REJECTED` is appended, and `version` increments. Returning for review moves the application from `ADJUDICATING` back to `REVIEW_HOLD` — a cyclic revert that places the application back in the hold queue — appends the corresponding status event, and increments `version`; this branch carries no segregation-of-duties precondition and no fiscal precondition beyond being in `ADJUDICATING`.

Issuing is the final step. An adjudicator issues an `APPROVED` application, moving it from `APPROVED` to `ISSUED` (permitted only from `APPROVED`). Issuance marks any `BOOKED` appointment for the application as `COMPLETED`, appends a status event from `APPROVED` to `ISSUED`, and increments `version`. `ISSUED` is terminal.

An applicant may withdraw an application from any of `DRAFT`, `SUBMITTED`, `IN_VERIFICATION`, or `REVIEW_HOLD`, moving it to `WITHDRAWN` (an attempt from any other state is rejected with `ERR_INVALID_STATE`, and a terminal application with `ERR_ALREADY_TERMINAL`). Withdrawal runs the same compensation as rejection: if the fee assessment is `PAID` it is refunded (to `REFUNDED`, `amount_paid_cents` to 0, applicant's `total_fees_paid_cents` decremented), any `BOOKED` appointment is cancelled, a status event recording the move to `WITHDRAWN` is appended, and `version` increments. `WITHDRAWN` is terminal.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return a `201 Created` status code. Operations that read a resource or that drive a state transition or other modification of an existing resource return a `200 OK` status code. Request bodies, response bodies, and side effects are not restated in this table; reconstruct them from the workflow narratives in Section 3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/applicants` | Register an applicant (adult or minor) | Applicant, Adjudicator |
| GET | `/applicants/{id}` | Read an applicant including risk score and total fees paid | Applicant, Adjudicator, AcceptanceAgent |
| GET | `/applicants` | List applicants; filter by `guardian_applicant_id` | Adjudicator, AcceptanceAgent |
| POST | `/applications` | Create a DRAFT application | Applicant |
| GET | `/applications/{id}` | Read an application | Applicant, AcceptanceAgent, Adjudicator |
| GET | `/applications` | List applications; filter by `applicant_id`, `status` | Applicant, AcceptanceAgent, Adjudicator |
| GET | `/applications/{id}/summary` | Computed read — both SLA variants, current fee, verification progress | Applicant, AcceptanceAgent, Adjudicator |
| POST | `/applications/{id}/submit` | Submit an application; creates its fee assessment | Applicant |
| POST | `/applications/{id}/begin-verification` | Begin verification; pins the acting agent | AcceptanceAgent |
| POST | `/applications/{id}/clear-hold` | Revert a review hold back to verification | Adjudicator |
| POST | `/applications/{id}/adjudicate` | Decide an application: approve, reject, or return for review | Adjudicator |
| POST | `/applications/{id}/issue` | Issue an approved application | Adjudicator |
| POST | `/applications/{id}/withdraw` | Withdraw an application | Applicant |
| POST | `/applications/{id}/name-change/decide` | Decide a name change: approve or deny | Adjudicator |
| GET | `/applications/{id}/status-events` | List status events ordered by `occurred_at` | Applicant, AcceptanceAgent, Adjudicator |
| POST | `/applications/{id}/documents` | Attach a supporting document | Applicant |
| GET | `/applications/{id}/documents` | List supporting documents for an application | Applicant, AcceptanceAgent, Adjudicator |
| GET | `/documents/{id}` | Read a supporting document | Applicant, AcceptanceAgent, Adjudicator |
| POST | `/documents/{id}/verify` | Verify a document: accept or reject | AcceptanceAgent |
| POST | `/applications/{id}/photos` | Attach a photo; runs photo validation immediately | Applicant |
| GET | `/applications/{id}/photos` | List photos for an application | Applicant, AcceptanceAgent, Adjudicator |
| POST | `/photos/{id}/revalidate` | Re-run photo validation | Applicant, AcceptanceAgent |
| GET | `/fee-assessments/{id}` | Read a fee assessment | Applicant, Adjudicator |
| GET | `/fee-assessments` | List fee assessments; filter by `application_id` | Applicant, Adjudicator, AcceptanceAgent |
| POST | `/fee-assessments/{id}/pay` | Pay a fee assessment; exact amount required | Applicant |
| POST | `/acceptance-facilities` | Create an acceptance facility | Adjudicator |
| GET | `/acceptance-facilities/{id}` | Read a facility | Applicant, AcceptanceAgent, Adjudicator |
| POST | `/urgent-travel-counters` | Create an urgent-travel counter | Adjudicator |
| GET | `/urgent-travel-counters/{id}` | Read an urgent-travel counter | Applicant, AcceptanceAgent, Adjudicator |
| POST | `/acceptance-agents` | Register an acceptance agent | Adjudicator |
| GET | `/acceptance-agents/{id}` | Read an acceptance agent | Adjudicator, AcceptanceAgent |
| GET | `/acceptance-agents` | List acceptance agents; filter by `facility_id` | Adjudicator, AcceptanceAgent |
| POST | `/adjudicators` | Register an adjudicator | Adjudicator |
| GET | `/adjudicators/{id}` | Read an adjudicator | Adjudicator, AcceptanceAgent |
| POST | `/appointments` | Book a facility or urgent-travel appointment | Applicant |
| GET | `/appointments/{id}` | Read an appointment | Applicant, AcceptanceAgent, Adjudicator |
| GET | `/appointments` | List appointments; filter by `application_id`, `facility_id`, or `counter_id` | Applicant, AcceptanceAgent, Adjudicator |
| POST | `/appointments/{id}/cancel` | Cancel a booked appointment | Applicant |
| POST | `/appointments/{id}/complete` | Complete a booked appointment | AcceptanceAgent |
| GET | `/applications/{id}/adjudication-decisions` | List adjudication decisions for an application | Applicant, AcceptanceAgent, Adjudicator |
| GET | `/adjudication-decisions` | List adjudication decisions; filter by `adjudicator_id`, `application_id` | Adjudicator |
| POST | `/_clock/set_current_utc` | Test-driving — set the system clock | (none — anonymous, per §2.1) |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_FK_NOT_FOUND` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ALREADY_TERMINAL` | 409 |
| `ERR_SOD_VIOLATION` | 403 |
| `ERR_PHOTO_INVALID` | 422 |
| `ERR_GUARDIAN_CONSENT_REQUIRED` | 422 |
| `ERR_NAME_CHANGE_EVIDENCE_REQUIRED` | 422 |
| `ERR_FACILITY_SLOT_CONFLICT` | 409 |
| `ERR_COUNTER_SLOT_CONFLICT` | 409 |
| `ERR_INVALID_INTERVAL` | 422 |
| `ERR_DUPLICATE_URGENT_APPOINTMENT` | 409 |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 422 |
| `ERR_FEE_UNPAID` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_VALIDATION` | 422 |
