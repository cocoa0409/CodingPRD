# Standardized Test Registration API — Product Requirements Document

## 1. Introduction

Across the SAT, ACT, AP, and CLEP programs, registration today is fragmented between vendor portals, paper accommodation forms, and ad-hoc cancellation hotlines. Test takers cannot see whether a seat at their preferred center is actually free; they cannot tell what their refund will look like if they need to cancel a week before the test; they cannot trust that an out-of-state driver's license will be accepted at the door. Test centers, meanwhile, struggle to reconcile physical seat counts against an opaque mix of confirmed registrations, accommodation-pending requests, and standby alternates — and accommodation officers have no auditable trail showing which official reviewed which request.

This document specifies the Standardized Test Registration API: a single backend that owns the registration lifecycle for all four programs, the test-center capacity ledger that backs it, the segregation-of-duties review workflow for 504/IEP accommodation requests, and the tiered-refund and Super Score computations that sit on top. The system is deliberately designed so every state-changing transition is auditable, every seat is accounted for at every observable instant, and every dollar charged to a candidate is either retained on a defensible basis or refunded through a recorded transaction.

The API serves five distinct human actors — candidates, proctors, accommodation officers, registrars, and credits officers — whose responsibilities are intentionally separated to make collusion and accidental policy bypass difficult. The §2 specifications below define the cross-cutting contract; §3 walks the business workflows through which those actors interact with the resources defined here.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID` and `X-User-Role`. The first identifies the calling actor; the second names their role. Missing or malformed values for either header are rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. A header pair that is well-formed but whose role lacks permission for the requested endpoint — or whose `X-User-ID` does not match the resource owner where ownership applies — is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

The role enumeration is exact and case-sensitive. Five values are recognised: `Candidate`, `Proctor`, `AccommodationsOfficer`, `Registrar`, and `CreditsOfficer`. Any other value in `X-User-Role` is treated as if the header were malformed.

Identity semantics differ by role. When `X-User-Role` is `Candidate`, `X-User-ID` is the `id` of the acting `Candidate` row; ownership checks on every resource that references a `Candidate` (registrations, accommodation requests, score reports, refund transactions, CLEP credit awards) compare the resource's `candidate_id` to `X-User-ID`. When `X-User-Role` is any of `Proctor`, `AccommodationsOfficer`, `Registrar`, or `CreditsOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity row. The server may record an opaque identifier where a state-machine transition requires it — for example, an `AccommodationsOfficer`'s `X-User-ID` is written into the `reviewer_user_id` field on `AccommodationRequest` at the moment review starts, and a `CreditsOfficer`'s `X-User-ID` is written into `posted_by_user_id` on `CLEPCreditAward` — but the server never compares those identifiers to any `id` column on a persisted entity.

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

All list endpoints accept two query parameters: `limit` and `offset`. `limit` defaults to 10 when omitted, has a minimum of 1, and a maximum of 100; values outside that range are rejected as malformed input. `offset` defaults to 0 and has no upper bound other than the size of the underlying collection. List results are returned in ascending order by each row's `created_at` timestamp. The four pagination fields surfaced in the response `meta` for list endpoints are `limit`, `offset`, `total_count`, and `has_more`; `has_more` is `true` whenever `offset + limit < total_count`.

### 2.4. Common Resource Properties

Most entities in this system carry the same four common fields. The `id` is a server-minted UUID string with no type prefix — clients never supply it and must not assume any embedded structure. The `created_at` timestamp records the instant of row creation as an ISO 8601 UTC string with three fractional digits, and is immutable. The `updated_at` timestamp tracks the last mutating write to the row in the same ISO 8601 UTC format with three fractional digits. The `version` field is a non-negative integer that begins at 1 on creation and increments by 1 on every mutating write; it is the basis of the optimistic-concurrency mechanism described in §2.7.

Three entities deliberately depart from this template because their semantics are append-only and immutable. A `ScoreReport`, a `CLEPCreditAward`, and a `RefundTransaction` each carry only an `id` and a `created_at` — they have no `updated_at` and no `version`, because they are never updated in place after they are first created.

### 2.5. Hierarchical Path Resolution

Nested resource paths are validated strictly left-to-right. For a path of the shape that descends from `testEventId` through `registrationId` to `idVerificationId` or `scoreReportId` (and ultimately to a CLEP credit award), each segment must resolve before the next is checked. The same left-to-right discipline applies to paths anchored on `testCenterId`, on `accommodationRequestId`, and on `candidateId`. A missing `TestEvent` yields `ERR_TEST_EVENT_NOT_FOUND`; once a valid `TestEvent` is found, a missing `TestCenter` yields `ERR_TEST_CENTER_NOT_FOUND`; a missing `Registration` yields `ERR_REGISTRATION_NOT_FOUND`; a missing `AccommodationRequest` yields `ERR_ACCOMMODATION_REQUEST_NOT_FOUND`; a missing `IDVerification` yields `ERR_ID_VERIFICATION_NOT_FOUND`; a missing `ScoreReport` yields `ERR_SCORE_REPORT_NOT_FOUND`; a missing `Candidate` yields `ERR_CANDIDATE_NOT_FOUND`. A missing `TestCenterCapacity` row for a given `(test_event_id, test_center_id)` pair yields `ERR_TEST_CENTER_CAPACITY_NOT_FOUND`. The system never short-circuits the order — for example, an invalid `registrationId` is never reported until both the `testEventId` and the registration's relation to that event have been confirmed.

### 2.6. Monetary Precision and Rounding

All monetary quantities in this system are integer USD cents. There is no fractional cent representation anywhere in the API surface or in storage. Wherever a calculation multiplies a cents amount by a rate, the resulting product is rounded half-up (standard banker-independent commercial rounding) to the nearest whole cent before being used downstream. Where the refund computation produces multiple per-line products, each line is rounded half-up to whole cents individually and only then summed — the order is fixed as round-then-sum rather than sum-then-round, and this ordering is observable in the recorded `RefundTransaction.amount_cents`.

### 2.7. Optimistic Concurrency Control

Endpoints that modify an existing resource accept an optional `version` field in the request body. When the client supplies it, the server compares the value to the row's current `version`; if they differ, the request is rejected with `ERR_VERSION_CONFLICT` and no side effects fire. When the client omits the field, the server proceeds without the check — clients that want last-writer-wins semantics can opt out by leaving `version` out of the payload. Every successful mutating write increments `version` by 1 and refreshes `updated_at`, regardless of which fields changed.

### 2.8. Test Center Capacity as a Materialised Ledger

The seat counters on every `TestCenterCapacity` row — `confirmed_seats_used`, `accommodation_seats_used`, `standby_seats_pending`, and `available_seats` — are computed, not client-supplied. After every `Registration` insert or status change tied to a given `(test_event_id, test_center_id)`, the ledger is reconciled in full: `confirmed_seats_used` is set to the count of `Registration` rows for that pair whose `status` is `CONFIRMED`, `CHECKED_IN`, or `COMPLETED`; `accommodation_seats_used` is set to the count of those rows that additionally have `accommodation_required` equal to true; `standby_seats_pending` is set to the count of rows on the pair whose `status` is `STANDBY`; and `available_seats` is set to `total_capacity` minus `confirmed_seats_used`. The compensating invariant — that `available_seats` plus `confirmed_seats_used` equals `total_capacity` at every observable instant — is the integrity contract this materialised view exists to enforce. `available_seats` must never be negative; an operation that would drive it below zero is rejected before it commits.

### 2.9. Segregation of Duties and Anti-Collusion

Several workflows in this system require that the human who initiates a privileged action is *not* the human who completes it. An `AccommodationsOfficer` who calls start-review on an `AccommodationRequest` is pinned into the row's `reviewer_user_id`, and from that moment forward every subsequent action on that request — requesting more information, approving, denying — must come from the same `X-User-ID`. Another officer attempting to act on the same request is rejected with `ERR_NOT_PINNED_REVIEWER`. The role system enforces a complementary structural separation: a `Proctor` cannot cancel a registration, a `Registrar` cannot post a CLEP credit award, a `CreditsOfficer` cannot clear an ID, and so on; these segregations are enforced through the role-permission check that yields `ERR_INSUFFICIENT_PERMISSIONS` when violated.

### 2.10. Time, Deadlines, and the Logical Clock

This system is deeply time-aware. Registration deadlines, late-registration cutoffs, score-release moments, accommodation submission deadlines, and check-in windows are all expressed as ISO 8601 UTC instants on `TestEvent` rows or derived from them. Because automated tests need deterministic time, the server exposes an admin-only logical clock that can be advanced to any supplied future instant via a `to` field in the request body. Advancing the clock across a `TestEvent`'s late-registration cutoff, test-session end, or score-release moment automatically fires the corresponding state transition on that event; advancing the clock alone does not, however, run the no-show or standby-promotion sweep — that is a separate operational capability invoked explicitly.

## 3. Business Logic & Workflows

### 3.1. The Test Event Lifecycle

A `TestEvent` is the central scheduling object — one row per administered sitting of one test form. A `Registrar` creates it with the test program (`test_type` is one of `SAT`, `ACT`, `AP`, or `CLEP`), a unique `form_code`, an optional `subject` (required for AP and CLEP — for example `AP_CALC_BC` or `CLEP_COLLEGE_ALGEBRA` — and null for SAT and ACT), the scheduled `test_date`, the `registration_deadline` (the last instant a registration may be created without the late-fee surcharge), the `late_registration_deadline` (the last instant late registrations are accepted at all), the `score_release_date`, the `base_fee_cents`, and the `late_fee_cents` surcharge applied to registrations created in the late window. The `test_type` value is immutable once the event is created. The event starts life in `REGISTRATION_OPEN`.

When the logical clock crosses `late_registration_deadline`, the system advances the event from `REGISTRATION_OPEN` to `REGISTRATION_CLOSED`. From that moment, no new `Registration` row may be created on the event — attempts return `ERR_REGISTRATION_CLOSED` — but existing `STANDBY` rows remain promotable until test day through the no-show-and-promote sweep. A `Registrar` may, exactly once per event, override this closure by supplying a new late-registration deadline that lies in the future; this transitions the event back from `REGISTRATION_CLOSED` to `REGISTRATION_OPEN`, updates the `late_registration_deadline` on the row, and bumps the event's `version` by one. A second extension on the same event is rejected with `ERR_DEADLINE_EXTENSION_EXHAUSTED`. The new-deadline value travels in the request as `new_late_registration_deadline`, alongside an optional `version` for the optimistic-concurrency check. Existing `CANCELLED` registrations on the event remain cancelled — they are not auto-reinstated by the extension.

The second automatic transition fires when the logical clock crosses `test_date` plus the test-session duration (a fixed four hours), at which point a `REGISTRATION_CLOSED` event moves to `SCORES_PENDING`. This transition has a precondition that the no-show-and-promote sweep has been called for the event at least once after `test_date`, ensuring no still-promotable standby slots are forgotten. When the move to `SCORES_PENDING` lands, every remaining `STANDBY` row on the event is automatically cancelled with `registration_channel` set to `SELF_INITIATED` and a full refund posted equal to the original `amount_charged_cents` — those candidates never sat, so the system returns all money. Every `CHECKED_IN` row on the event simultaneously moves to `COMPLETED`. Finally, when the clock crosses `score_release_date`, the event moves from `SCORES_PENDING` to `COMPLETED`, at which point `ScoreReport` posting becomes legal for the event's completed registrations.

### 3.2. Test Centers and the Capacity Ledger

A `TestCenter` is the physical venue at which one or more `TestEvent`s are administered. A `Registrar` creates a `TestCenter` with a display `name`, a street `address`, the two-letter US `state_code` (used downstream by the cross-state ID rule), and an IANA `timezone`. The center begins in `ACTIVE` status (it may also be `SUSPENDED`).

A `TestCenterCapacity` row binds a `TestCenter` to a specific `TestEvent` and declares the seat budget for that combination. A `Registrar` allocates capacity by supplying the `test_center_id`, the `total_capacity` (the physical seat count at this venue for this event), and the `accommodation_capacity` (the subset of those seats reserved for candidates with `APPROVED` accommodation requests, which must not exceed `total_capacity` and cannot be filled by non-accommodation registrations). The pair `(test_event_id, test_center_id)` is unique — a venue can host a given event at most once. At creation the four computed counters are initialised: `confirmed_seats_used` is 0, `accommodation_seats_used` is 0, `standby_seats_pending` is 0, and `available_seats` equals `total_capacity`.

A `TestCenter` cannot host two different `TestEvent`s whose scheduled sessions overlap in the same four-hour test-session window. When a `Registrar` allocates capacity, the system checks whether the candidate `TestEvent`'s window from `test_date` through `test_date + 4 hours` (closed interval, no buffer) overlaps any other event's window already bound to the same `TestCenter`; if it does, the allocation is rejected with `ERR_TEST_CENTER_TIME_CONFLICT`.

### 3.3. Candidate Onboarding and Identity

A `Candidate` row represents an individual test-taker. It may be created by the candidate themselves or by a `Registrar` operating on their behalf, supplying the `legal_name` exactly as it appears on the candidate's government ID, a unique `email` (used for `X-User-ID` resolution and treated as the candidate's identity handle), the `date_of_birth` as an ISO 8601 date, the two-letter US `home_state_code` (compared against ID documents at clearance time), and an optional `has_iep_or_504` boolean (defaulting to false). Setting `has_iep_or_504` to true is the gating condition that makes the candidate eligible to file an `AccommodationRequest`; a candidate whose record has this flag at false who attempts to submit an accommodation request is rejected with `ERR_ACCOMMODATION_NOT_ELIGIBLE`.

Candidates may look up their own data, their own registrations, their own accommodation requests, their own score reports, their own refunds, and their own CLEP credit awards. Attempting to read another candidate's resources yields `ERR_INSUFFICIENT_PERMISSIONS`.

### 3.4. Registering for a Test: Standby, Confirmation, and Auto-Promotion

Registration is the central many-to-many junction between candidates and events. A `Candidate` (acting for themselves) or a `Registrar` (acting on a candidate's behalf) creates a `Registration` by supplying the `candidate_id`, the `test_center_id`, and an optional `force_confirmed` boolean (default false). The path identifies the target `TestEvent` through `testEventId`. The event must be in `REGISTRATION_OPEN`; if it is anything else, the request is rejected with `ERR_REGISTRATION_CLOSED`.

Each new row is initially placed in `STANDBY`. If the `TestCenterCapacity` row for the chosen center has `available_seats` greater than zero — and, when the candidate already has an `APPROVED` `AccommodationRequest` on this event, the accommodation pool also has free capacity — the row is then auto-promoted to `CONFIRMED` in the same operation. When `force_confirmed` is true and capacity is insufficient (either the general pool, or the accommodation pool when accommodation is required), the request is rejected with `ERR_CAPACITY_EXHAUSTED`; with `force_confirmed` left at false, the row simply remains in `STANDBY` and the candidate joins the alternate queue with no error. Two candidates who simultaneously target the last seat at the same `(test_event_id, test_center_id)` are serialised first-writer-wins on the increment to `confirmed_seats_used`: at most one becomes `CONFIRMED`, and the loser either lands in `STANDBY` silently (if `force_confirmed` was false) or receives `ERR_CAPACITY_EXHAUSTED` (if `force_confirmed` was true).

The newly created row records the calling channel in `registration_channel` (initially `SELF_INITIATED` from the candidate path, set to `OFFICIAL_CANCELLATION` only later if a `Registrar` cancels — at creation time the value is `SELF_INITIATED`), and pins `registered_at` to the creation instant. `standby_promotion_eligibility_at` is set to `registered_at` plus the standby visibility delay (a value the system pins at zero seconds so promotion eligibility is effectively immediate; the field exists to give the priority selector an explicit gate). The `accommodation_required` field is computed: it is true if and only if there exists an `AccommodationRequest` for `(candidate_id, test_event_id)` whose `status` is `APPROVED`, and false otherwise. The fee snapshot captures three values: `base_fee_cents_charged` mirrors the event's `base_fee_cents`; `late_fee_cents_charged` equals the event's `late_fee_cents` when `registered_at` is strictly after `registration_deadline` (the late window) and is zero otherwise; `accommodation_fee_cents_charged` is 2500 cents when `accommodation_required` is true at creation and zero otherwise. The total `amount_charged_cents` is the sum of all three line items, and `amount_refunded_cents` begins at zero, leaving `amount_retained_cents` equal to `amount_charged_cents`.

Two duplication checks apply at creation. The pair `(candidate_id, test_event_id)` must be unique across all `Registration` rows that are not `CANCELLED`; a second non-cancelled registration on the same event by the same candidate is rejected with `ERR_DUPLICATE_REGISTRATION`. Additionally, a candidate cannot register for two events whose test windows overlap when extended by a four-hour cooldown buffer on either side: the system computes the closed interval from `test_date - 4 hours` through `test_date + 4 hours + 4 hours` (that is, the test-session window padded by the cooldown on either side) for the candidate's existing non-`CANCELLED`, non-`NO_SHOW` registrations and rejects the new one with `ERR_CANDIDATE_SESSION_OVERLAP` if it falls within any such interval.

When existing `CONFIRMED` capacity later frees — because a sibling row cancels, no-shows, or is demoted by a retroactive accommodation approval — the standby promotion selector fires on the same `(test_event_id, test_center_id)`. The selector first identifies the candidate pool of `STANDBY` registrations on that pair whose `standby_promotion_eligibility_at` is at or before now. It then partitions the pool into accommodation-required candidates and general candidates. With the inputs (test event identifier, test center identifier, total seats freed, and accommodation seats freed where the accommodation count cannot exceed the total), the selector first fills the accommodation slots: for up to the number of accommodation seats freed, it picks the highest-priority accommodation-required candidate and promotes them to `CONFIRMED`. Any accommodation slots left unfilled spill into the general pool — their count is added to the remaining general seats freed. Then the selector fills the general seats from the remaining candidates by the same priority key. The priority key sorts ascending: first by priority class (class 0 is an accommodation-required candidate filling an accommodation seat in the first phase, class 1 is an accommodation-required candidate consuming a spilled accommodation slot in the general phase, and class 2 is a general candidate without accommodation), then by `registered_at` ascending so earlier registrations win, and finally by `Candidate.id` ascending as a lexicographic deterministic tie-break. An empty pool produces no error and no promotions.

Each promotion increments `confirmed_seats_used` by one (and `accommodation_seats_used` by one when applicable), decrements `standby_seats_pending` by one, recomputes the fee snapshot on the promoted row (with no late fee added on promotion), and refreshes `updated_at` and `version` on the affected `TestCenterCapacity` and `Registration` rows.

### 3.5. Identity Verification on Registration

Every confirmed registration must clear an identity check before its candidate can be checked in on test day. The `Candidate` submits documents by providing the `id_document_type` (one of `DRIVERS_LICENSE`, `STATE_ID`, `PASSPORT`, or `SCHOOL_ID_WITH_PHOTO`), an optional `issuing_state_code` (ignored when `id_document_type` is `PASSPORT`), and the `id_expires_on` date. The `IDVerification` row is created with `status` of `NOT_STARTED` and immediately transitions to `DOCS_SUBMITTED` on the first submission; subsequent submissions after a rejection — which the candidate uses to correct previously failed documents — also land in `DOCS_SUBMITTED`. The candidate's `Registration` must be in either `STANDBY` or `CONFIRMED` for either submission to be accepted; otherwise the rejection code is `ERR_INVALID_REGISTRATION_STATE`.

A `Registrar` reviews the submitted documents and either clears or rejects them. Clearance requires two checks. First, the `id_expires_on` date must be strictly later than the event's `test_date`; a document that expires on or before the test day is rejected with `ERR_ID_EXPIRED_BEFORE_TEST`. Second, unless the document type is `PASSPORT`, the document's `issuing_state_code` must equal the candidate's `home_state_code`; if it does not, clearance is refused with `ERR_CROSS_STATE_ID_MISMATCH` unless the `Registrar` supplies `allow_cross_state_override` set to true on the clearance call. When the override is used, the row's `cross_state_override_granted` flag is set to true as an audit trace. On successful clearance the row advances to `CLEARED`. A rejection — invoked with a free-text `rejection_reason` — moves the row to `REJECTED` and writes the supplied reason into the `rejection_reason` field. From `REJECTED`, the candidate may resubmit by calling the submit operation again, which advances the row back to `DOCS_SUBMITTED` (the cycle through rejection and resubmission is by design).

### 3.6. Accommodation Requests: The Review Workflow

A `Candidate` whose record has `has_iep_or_504` set to true may file an `AccommodationRequest` for a specific `TestEvent` by supplying the `candidate_id`, the `test_event_id`, the `requested_accommodations` array (each entry drawn from the enumeration `EXTENDED_TIME_50`, `EXTENDED_TIME_100`, `BREAKS_EXTENDED`, `READER`, `SCRIBE`, `LARGE_PRINT`), and the `supporting_documents` array (a list of document URIs or identifiers, at least one of which is required before review can start). The request is created in `SUBMITTED` with two computed deadlines: `submission_deadline_at` is fourteen days before the event's `registration_deadline`, and `review_deadline_at` is `submission_deadline_at` plus seven days (the officer review SLA window). A submission filed after `submission_deadline_at` is rejected with `ERR_ACCOMMODATION_DEADLINE_PASSED`. A candidate whose record has `has_iep_or_504` at false is rejected with `ERR_ACCOMMODATION_NOT_ELIGIBLE`. Only one non-`EXPIRED` accommodation request may exist per `(candidate_id, test_event_id)` pair at a time — a second such submission is rejected with `ERR_DUPLICATE_ACCOMMODATION`.

An `AccommodationsOfficer` pulls a `SUBMITTED` request into review, advancing it to `UNDER_REVIEW`. This action is rejected with `ERR_INVALID_ACCOMMODATION_STATE` if the row is not currently in `SUBMITTED`, and requires that `supporting_documents` is non-empty and that now is at or before `review_deadline_at`. On success, the caller's `X-User-ID` is written into `reviewer_user_id` and pinned for the remainder of the row's life. From `UNDER_REVIEW`, the same pinned officer (any other officer is rejected with `ERR_NOT_PINNED_REVIEWER`) may take three branches:

The officer may request additional information, transitioning the row to `NEEDS_MORE_INFO`. From `NEEDS_MORE_INFO`, the candidate who owns the request may re-submit by appending new entries to `supporting_documents` (the length must strictly increase) and providing the updated array; this transition is accepted only if now is at or before `review_deadline_at`, and on success the row returns to `SUBMITTED`, from which the pinned officer pulls it back into `UNDER_REVIEW` again. The cycle through `SUBMITTED → UNDER_REVIEW → NEEDS_MORE_INFO → SUBMITTED → UNDER_REVIEW` may repeat any number of times until the deadline passes or the officer commits to an approve or deny decision.

The officer may approve, advancing the row to `APPROVED`. Approval is the most cascading transition in the system. Every `Registration` for the same `(candidate_id, test_event_id)` has its `accommodation_required` flipped to true, the new accommodation fee added to `accommodation_fee_cents_charged`, `amount_charged_cents` recomputed, and the approving `AccommodationRequest`'s `version` pinned into `locked_accommodation_request_version`. On every `TestCenter` for which the affected candidate holds a `CONFIRMED` registration, the system then checks whether the accommodation pool has free capacity: if `accommodation_capacity` minus `accommodation_seats_used` equals zero, the `CONFIRMED` registration is demoted back to `STANDBY` and the seat counters are reconciled (`confirmed_seats_used` decreases by one, `standby_seats_pending` increases by one). After all demotions land, the capacity ledger on each affected `(test_event_id, test_center_id)` is reconciled in full. The `version` and `updated_at` on every touched row — accommodation request, registrations, and capacity rows — refresh.

The officer may deny, advancing the row to `DENIED`. A denial does not change any registration's `accommodation_required` flag, and the candidate may still be checked in on the day of the test using the standard seating.

Two AccommodationOfficer actors who both successfully called start-review on the same request would not be possible — the first start-review pins `reviewer_user_id` and serialises the pinning first-writer-wins. If a second officer races against the first on `approve` or `deny` after the pinning has occurred, that second officer's call is rejected with `ERR_NOT_PINNED_REVIEWER`.

If the deadline passes while the request is still in any of `SUBMITTED`, `UNDER_REVIEW`, or `NEEDS_MORE_INFO`, the next no-show-and-promote sweep transitions the row to `EXPIRED`. For the purpose of the check-in rules in §3.7, an `EXPIRED` row counts the same as `DENIED`.

### 3.7. Test Day: Check-In, Sweeps, and No-Shows

Check-in is the act by which a `Proctor` at the test center confirms a candidate's physical arrival, advancing their `Registration` from `CONFIRMED` to `CHECKED_IN`. Four checks gate the transition. The current logical time must be within the window from `test_date - 2 hours` to `test_date + 1 hour` (check-in opens two hours before the scheduled start and closes one hour after); if it is not, the proctor's call is rejected with `ERR_CHECK_IN_WINDOW_CLOSED`. The registration must currently be in `CONFIRMED`; any other state — including `STANDBY`, `CHECKED_IN`, `NO_SHOW`, `COMPLETED`, or `CANCELLED` — yields `ERR_INVALID_REGISTRATION_STATE`. The associated `IDVerification` must be in `CLEARED`; a missing or non-cleared verification yields `ERR_ID_NOT_CLEARED`. Finally, if any `AccommodationRequest` exists on the same `(candidate_id, test_event_id)`, that request must already be in one of the terminal review states — `APPROVED`, `DENIED`, or `EXPIRED` — and not in `SUBMITTED`, `UNDER_REVIEW`, or `NEEDS_MORE_INFO`; otherwise the proctor receives `ERR_ACCOMMODATION_PENDING`.

The no-show-and-promote sweep is the operational workhorse of test day and accommodation expiry. It is invoked by either a `Registrar` or a `Proctor` against a single `TestEvent`, and accomplishes three things in one call. First, it moves any `Registration` still in `CONFIRMED` whose check-in window has passed (now is strictly after `test_date + 1 hour`) to `NO_SHOW`, decrementing the corresponding `confirmed_seats_used` (and `accommodation_seats_used` where applicable) on the relevant `TestCenterCapacity` row. Second, on each affected `(test_event_id, test_center_id)`, the seats freed by those no-shows immediately trigger the standby priority selector described in §3.4; promoted rows move from `STANDBY` to `CONFIRMED` and the seat counters are reconciled. Third, any `AccommodationRequest` whose `review_deadline_at` has passed and which is still in any of `SUBMITTED`, `UNDER_REVIEW`, or `NEEDS_MORE_INFO` is moved to `EXPIRED`. The sweep's response reports three integer counters: `no_show_count`, `promotions`, and `expired_accommodations`. The sweep is also a precondition for the event itself moving from `REGISTRATION_CLOSED` to `SCORES_PENDING`.

A `Proctor`'s check-in racing against a `Registrar`'s admin cancellation on the same row is serialised first-writer-wins on the registration's `status`; the loser receives `ERR_INVALID_REGISTRATION_STATE`. A `Candidate`'s self-cancellation racing against a concurrent sweep that is about to mark the same row `NO_SHOW` is likewise serialised — whichever transition lands first is final, and the loser receives `ERR_INVALID_REGISTRATION_STATE`.

### 3.8. Cancellations and the Tiered Refund

A `Registration` in `STANDBY` or `CONFIRMED` may be cancelled by two distinct paths. The candidate may self-cancel their own row, and a `Registrar` may admin-cancel any candidate's row. Both paths move the row to `CANCELLED`, but they differ in the resulting refund. The candidate self-serve cancellation writes `registration_channel` as `SELF_INITIATED`; the admin path writes it as `OFFICIAL_CANCELLATION`. Either operation accepts the optional `version` field for the concurrency check. Cancellation is forbidden once the parent `TestEvent` has reached `COMPLETED`; an attempt is rejected with `ERR_INVALID_REGISTRATION_STATE`.

The refund amount is computed at the cancellation instant. The system first computes `days_before_test` as the floor of the number of seconds between the current instant and the event's `test_date` divided by 86400. It then selects a refund tier from the threshold table: when `days_before_test` is at least 30 the tier is `FULL` with a rate of 1.00; when `days_before_test` is at least 15 and less than 30 the tier is `PARTIAL_75` with a rate of 0.75; when `days_before_test` is at least 7 and less than 15 the tier is `PARTIAL_50` with a rate of 0.50; and when `days_before_test` is less than 7 the tier is `NONE` with a rate of 0.00. The system then computes two per-line refund amounts independently, rounding each half-up to whole cents before any further arithmetic: the refund on the base fee is `base_fee_cents_charged` multiplied by the rate (rounded half-up); the refund on the late fee is `late_fee_cents_charged` multiplied by the rate (rounded half-up); the refund on the accommodation fee is always zero, because the accommodation processing fee is non-refundable regardless of tier or channel. The candidate refund is the sum of those three rounded line amounts.

For self-initiated cancellations the per-tier rate above applies verbatim. For official cancellations — a `Registrar` cancelling for reasons such as event mis-scheduling, force majeure, or a downstream ID rejection cascade — the rate is forced to 1.00 on both the base fee and the late fee regardless of `days_before_test`; the accommodation fee remains non-refundable. The tier label that gets written into the resulting `RefundTransaction.tier_label` is, in both variants, the actual time-tier (`FULL`, `PARTIAL_75`, `PARTIAL_50`, or `NONE`) that would have applied at the cancellation instant — not a synthetic value reflecting the forced rate — so the audit trail preserves the temporal context even when the official path overrides the financial outcome. The final refund amount is the maximum of zero and the computed total; it can be zero but is never negative.

A `RefundTransaction` row is then appended to the registration. The transaction records the parent `registration_id`, the computed `amount_cents`, the `tier_label` from the threshold table, and the `refund_channel` mirroring the cancellation channel (`SELF_INITIATED` or `OFFICIAL_CANCELLATION`). The parent `Registration` is updated: `amount_refunded_cents` is set to the sum of all its `RefundTransaction.amount_cents` (in practice one row per cancellation), and `amount_retained_cents` is recomputed as `amount_charged_cents` minus `amount_refunded_cents`. If the cancelled row had been `CONFIRMED`, the relevant `TestCenterCapacity` has `confirmed_seats_used` decreased by one (and `accommodation_seats_used` decreased by one when applicable); if it had been `STANDBY`, `standby_seats_pending` decreases by one instead. Either way, the standby promotion selector then fires on `(test_event_id, test_center_id)`, and a top-priority `STANDBY` row — if any exists with `standby_promotion_eligibility_at` satisfied — is promoted from `STANDBY` to `CONFIRMED`, its `confirmed_seats_used` increment lands on the ledger, and its fee snapshot is recomputed (with no additional late fee for the promotion).

### 3.9. Score Reports and Super Scoring

Once a `Registration` reaches `COMPLETED` (which only happens after the parent `TestEvent` has moved through `SCORES_PENDING` to `COMPLETED`), a `Registrar` may post a `ScoreReport`. The post supplies the `section_scores` object (a map from section name to integer score, where the section names depend on `test_type` — SAT uses `reading_writing` and `math`, ACT uses `english`, `math`, `reading`, and `science`, AP and CLEP use the single key `composite`), the `total_score` integer (whose valid range varies by program: SAT 400 to 1600, ACT 1 to 36, AP 1 to 5, CLEP 20 to 80), and an optional `report_type` defaulting to `OFFICIAL`. A second post of `report_type` `RESCORED` logically supersedes the prior `OFFICIAL` row for the same registration in subsequent calculations — the latest row by `created_at` wins inside Super Score selection. Score report rows are immutable once written.

The Super Score endpoint computes the candidate's best aggregated score across a window of past sittings. It is read-only and produces no side effects. The caller supplies the candidate identifier via `candidateId` in the path, the `test_type` query parameter selecting which program to score, the optional `reporting_mode` query parameter (default `COLLEGE_BOARD_OFFICIAL`, alternative `INSTITUTIONAL_SUBMISSION`), and the optional `as_of_date` query parameter (defaulting to the current logical instant).

The candidate's ScoreReport pool is built as follows. The system selects every `Registration` belonging to the candidate whose parent `TestEvent.test_type` matches the requested `test_type`. For each such registration, the system keeps the single contributing `ScoreReport` row: the most recent by `created_at` between the `OFFICIAL` row and any `RESCORED` row (so a later `RESCORED` row overrides the original `OFFICIAL`, but if no `RESCORED` exists the `OFFICIAL` is used). Sittings whose `TestEvent.test_date` is more than 730 days (24 months) before `as_of_date` are excluded from the pool.

The composite is computed in one of two ways depending on `reporting_mode`. In `COLLEGE_BOARD_OFFICIAL` mode (the default), each section's contribution is the maximum of that section's `section_scores` value across all sittings in the pool — so `reading_writing`'s maximum and `math`'s maximum may come from different sittings. In `INSTITUTIONAL_SUBMISSION` mode, the system instead identifies the single sitting whose `total_score` is highest within the pool and uses that sitting's `section_scores` verbatim — so all sections of the returned composite come from the same sitting, even if a candidate's per-section maximum in isolation is higher elsewhere. After the per-section values are chosen, the composite is computed by program: for SAT the composite is the sum of `reading_writing` and `math` and falls in the 400 to 1600 range; for ACT the composite is the arithmetic mean of `english`, `math`, `reading`, and `science` rounded half-up to an integer; for AP and CLEP there is no super-score concept and the endpoint returns the latest sitting's composite value verbatim. When the candidate pool after filtering is empty, the endpoint returns a composite value of null, an empty sections object, and a `sittings_used` count of zero.

### 3.10. CLEP Credit Award Posting

A `CreditsOfficer` posts a CLEP credit decision against a specific `ScoreReport`. The parent `TestEvent`'s `test_type` must be `CLEP`; otherwise the post is rejected with `ERR_CLEP_INVALID_CONTEXT`. The subject on the parent event must appear in the recognised subject map (`CLEP_COLLEGE_ALGEBRA`, `CLEP_AMERICAN_GOVERNMENT`, `CLEP_BIOLOGY`, `CLEP_CHEMISTRY`, `CLEP_COLLEGE_COMPOSITION`); an unrecognised subject yields `ERR_CLEP_SUBJECT_UNRECOGNIZED`. The award row is keyed uniquely by `score_report_id`; a second post for the same score report is rejected with `ERR_CLEP_AWARD_ALREADY_POSTED`, and two officers racing to post the first award on the same score report are serialised first-writer-wins on that uniqueness — the loser receives the same code.

The award computation is a simple threshold lookup. The recommended-score table assigns 50 to each of the five recognised subjects above; the credit-units table assigns 3 units to `CLEP_COLLEGE_ALGEBRA` and `CLEP_AMERICAN_GOVERNMENT`, and 6 units to `CLEP_BIOLOGY`, `CLEP_CHEMISTRY`, and `CLEP_COLLEGE_COMPOSITION`. If the parent `ScoreReport.total_score` is at least the recommended score for the subject (the boundary at exact equality is awarded, not denied), the award's `credit_status` is `AWARDED` and `credit_units` is set from the credit-units table; otherwise `credit_status` is `DENIED` and `credit_units` is zero. The award row also records `score_report_id`, the mirrored `candidate_id` (from the registration that owns the score report, for query convenience), and `posted_by_user_id` set from the officer's `X-User-ID` — the field is recorded on both `AWARDED` and `DENIED` outcomes. The award is immutable once posted.

### 3.11. Validation Order and Error Precedence

When more than one validation could fire on the same request, the system evaluates them in a strict order so the returned `error_id` is deterministic. Header well-formedness comes first (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`), then role-and-ownership permission (`ERR_INSUFFICIENT_PERMISSIONS`), then path existence checks left-to-right (yielding the appropriate not-found error per §2.5), then current-state legality for the target resource (`ERR_INVALID_REGISTRATION_STATE`, `ERR_INVALID_ACCOMMODATION_STATE`, `ERR_INVALID_ID_VERIFICATION_STATE`, or `ERR_REGISTRATION_CLOSED` at registration creation). Only after those gates have all passed do the cross-entity and business-specific checks apply. For check-in specifically, the order after state is: ID-cleared (`ERR_ID_NOT_CLEARED`), then accommodation-pending (`ERR_ACCOMMODATION_PENDING`), then the check-in window check (`ERR_CHECK_IN_WINDOW_CLOSED`). For ID clearance, the cross-state mismatch is checked (`ERR_CROSS_STATE_ID_MISMATCH`) before the expiry check (`ERR_ID_EXPIRED_BEFORE_TEST`). For registration creation under the `force_confirmed` flag, the order after state is: accommodation deadline if relevant (`ERR_ACCOMMODATION_DEADLINE_PASSED` applies only to accommodation requests), then session-overlap on the candidate (`ERR_CANDIDATE_SESSION_OVERLAP`), then duplicate registration (`ERR_DUPLICATE_REGISTRATION`), then capacity (`ERR_CAPACITY_EXHAUSTED`). For accommodation request creation, the order after state is: deadline-passed check (`ERR_ACCOMMODATION_DEADLINE_PASSED`), then eligibility (`ERR_ACCOMMODATION_NOT_ELIGIBLE`), then duplicate (`ERR_DUPLICATE_ACCOMMODATION`). Generic schema and type problems on a request body that cannot even be parsed yield `ERR_INVALID_REQUEST` and are evaluated together with header well-formedness at the top of the chain.

## 4. Endpoint Definitions

The endpoints below mount under the API prefix and exchange JSON bodies in the envelope described in §2.2. New resources are returned with HTTP 201; modifications to existing resources are returned with HTTP 200; read endpoints return 200. The request body, response body, side effects, and authorization-ownership rules for each endpoint are detailed in §3 and §2.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /_clock/advance | Advance the server's logical clock to a supplied instant; fires any time-gated TestEvent transitions whose deadline is crossed | Registrar |
| POST | /_sweep/no-show-and-promote | Run the no-show, standby-promotion, and accommodation-expiry sweep for one TestEvent | Registrar, Proctor |
| POST | /test-events | Create a TestEvent | Registrar |
| GET | /test-events | List TestEvents | Candidate, Proctor, Registrar, AccommodationsOfficer, CreditsOfficer |
| GET | /test-events/{testEventId} | Get a TestEvent | Candidate, Proctor, Registrar, AccommodationsOfficer, CreditsOfficer |
| POST | /test-events/{testEventId}/extend-deadline | Reopen a closed TestEvent registration window once | Registrar |
| POST | /test-centers | Create a TestCenter | Registrar |
| GET | /test-centers | List TestCenters | Candidate, Proctor, Registrar, AccommodationsOfficer, CreditsOfficer |
| GET | /test-centers/{testCenterId} | Get a TestCenter | Candidate, Proctor, Registrar, AccommodationsOfficer, CreditsOfficer |
| POST | /test-events/{testEventId}/test-center-capacities | Allocate seats at a TestCenter for a TestEvent | Registrar |
| GET | /test-events/{testEventId}/test-center-capacities | List TestCenterCapacity rows for a TestEvent | Candidate, Proctor, Registrar, AccommodationsOfficer, CreditsOfficer |
| POST | /candidates | Create a Candidate | Candidate, Registrar |
| GET | /candidates/{candidateId} | Get a Candidate | Candidate, Registrar, AccommodationsOfficer |
| GET | /candidates/{candidateId}/super-score | Compute and return the Super Score for the Candidate | Candidate, Registrar |
| POST | /test-events/{testEventId}/registrations | Create a Registration | Candidate, Registrar |
| GET | /test-events/{testEventId}/registrations/{registrationId} | Get a Registration | Candidate, Proctor, Registrar |
| GET | /test-events/{testEventId}/registrations | List Registrations for a TestEvent | Proctor, Registrar |
| DELETE | /test-events/{testEventId}/registrations/{registrationId} | Candidate self-cancellation | Candidate |
| POST | /test-events/{testEventId}/registrations/{registrationId}/admin-cancel | Registrar cancellation (forces full refund variant) | Registrar |
| POST | /test-events/{testEventId}/registrations/{registrationId}/check-in | Proctor checks in a Candidate on test day | Proctor |
| POST | /test-events/{testEventId}/registrations/{registrationId}/id-verification/submit | Candidate submits ID documents | Candidate |
| POST | /test-events/{testEventId}/registrations/{registrationId}/id-verification/clear | Registrar clears the ID | Registrar |
| POST | /test-events/{testEventId}/registrations/{registrationId}/id-verification/reject | Registrar rejects the ID submission | Registrar |
| GET | /test-events/{testEventId}/registrations/{registrationId}/id-verification | Get IDVerification for a Registration | Candidate, Proctor, Registrar |
| POST | /accommodation-requests | Candidate submits a 504/IEP accommodation request | Candidate |
| POST | /accommodation-requests/{accommodationRequestId}/start-review | AccommodationsOfficer pulls a request into review | AccommodationsOfficer |
| POST | /accommodation-requests/{accommodationRequestId}/request-info | AccommodationsOfficer demands more documents | AccommodationsOfficer |
| PATCH | /accommodation-requests/{accommodationRequestId}/resubmit | Candidate appends new supporting documents and re-submits | Candidate |
| POST | /accommodation-requests/{accommodationRequestId}/approve | AccommodationsOfficer approves | AccommodationsOfficer |
| POST | /accommodation-requests/{accommodationRequestId}/deny | AccommodationsOfficer denies | AccommodationsOfficer |
| GET | /accommodation-requests/{accommodationRequestId} | Get an AccommodationRequest | Candidate, Registrar, AccommodationsOfficer |
| GET | /accommodation-requests | List AccommodationRequests | Registrar, AccommodationsOfficer |
| POST | /test-events/{testEventId}/registrations/{registrationId}/score-reports | Post a ScoreReport to a COMPLETED Registration | Registrar |
| GET | /test-events/{testEventId}/registrations/{registrationId}/score-reports | List ScoreReports for a Registration | Candidate, Registrar, CreditsOfficer |
| POST | /test-events/{testEventId}/registrations/{registrationId}/score-reports/{scoreReportId}/clep-credit | Post a CLEP credit decision | CreditsOfficer |
| GET | /candidates/{candidateId}/clep-credit-awards | List CLEPCreditAwards for a Candidate | Candidate, Registrar, CreditsOfficer |
| GET | /test-events/{testEventId}/registrations/{registrationId}/refunds | List RefundTransactions for a Registration | Candidate, Registrar |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_INSUFFICIENT_PERMISSIONS | 403 |
| ERR_TEST_EVENT_NOT_FOUND | 404 |
| ERR_TEST_CENTER_NOT_FOUND | 404 |
| ERR_TEST_CENTER_CAPACITY_NOT_FOUND | 404 |
| ERR_CANDIDATE_NOT_FOUND | 404 |
| ERR_REGISTRATION_NOT_FOUND | 404 |
| ERR_ACCOMMODATION_REQUEST_NOT_FOUND | 404 |
| ERR_ID_VERIFICATION_NOT_FOUND | 404 |
| ERR_SCORE_REPORT_NOT_FOUND | 404 |
| ERR_REGISTRATION_CLOSED | 409 |
| ERR_INVALID_REGISTRATION_STATE | 409 |
| ERR_INVALID_ACCOMMODATION_STATE | 409 |
| ERR_INVALID_ID_VERIFICATION_STATE | 409 |
| ERR_DEADLINE_EXTENSION_EXHAUSTED | 409 |
| ERR_NOT_PINNED_REVIEWER | 403 |
| ERR_CLEP_AWARD_ALREADY_POSTED | 409 |
| ERR_ID_NOT_CLEARED | 409 |
| ERR_ACCOMMODATION_PENDING | 409 |
| ERR_CROSS_STATE_ID_MISMATCH | 422 |
| ERR_ID_EXPIRED_BEFORE_TEST | 422 |
| ERR_CHECK_IN_WINDOW_CLOSED | 409 |
| ERR_ACCOMMODATION_DEADLINE_PASSED | 422 |
| ERR_TEST_CENTER_TIME_CONFLICT | 409 |
| ERR_CANDIDATE_SESSION_OVERLAP | 409 |
| ERR_DUPLICATE_REGISTRATION | 409 |
| ERR_ACCOMMODATION_NOT_ELIGIBLE | 422 |
| ERR_DUPLICATE_ACCOMMODATION | 409 |
| ERR_CAPACITY_EXHAUSTED | 409 |
| ERR_CLEP_INVALID_CONTEXT | 422 |
| ERR_CLEP_SUBJECT_UNRECOGNIZED | 422 |
| ERR_INVALID_REQUEST | 400 |
| ERR_VERSION_CONFLICT | 409 |
