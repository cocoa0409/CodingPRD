# Online Tutoring Marketplace API — Product Requirements Document

## 1. Introduction

The Online Tutoring Marketplace API powers a multi-sided platform in the Wyzant tradition, connecting independent tutors with learners (and the parents of underage learners) for paid one-on-one academic sessions. The platform is responsible for everything that sits between a learner's intent to book a lesson and the eventual payout to the tutor — credential checks that gate who is allowed to teach, a controlled vocabulary of subject offerings, hourly and trial pricing with multi-hour discounts, session scheduling with overlap protection, per-session settlement after a holding window, a multi-round refund arbitration workflow, and dual-admin payout batches paid out of the tutor's running balance.

Because money moves on every state change, the platform is engineered around three intertwined concerns. **Trust** is enforced through credential verification and segregation of duties: the operator who approves a credential cannot be the tutor, the arbiter who rules on a dispute cannot be a party to the session, and the admin who marks a payout paid cannot be the one who created it. **Money conservation** is enforced as a hard invariant — every cent that enters as a student charge must end the session's lifecycle accounted for as tutor payout, platform commission, or student refund, and the system computes these splits twice (a forward-looking quote at booking and a final reconciliation at completion or after refund). **Lifecycle correctness** is enforced through state machines for tutors, credentials, subject tags, sessions, refund disputes, parent-child links, and payout batches, with cascading effects when a credential expires or a tutor is suspended.

This document is the single source of truth for the API surface, the rules behind it, and the wire formats it speaks. All endpoints are mounted beneath the `/tutoring` prefix.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming their operational capacity. If either header is missing or carries an unknown role, the request is rejected with `ERR_AUTH_REQUIRED`. If the role is recognized but is not permitted for the requested endpoint, the request is rejected with `ERR_FORBIDDEN`. If the role and endpoint match but the principal does not own (or is not linked to) the target resource, the request is rejected with `ERR_NOT_AUTHORIZED_FOR_RESOURCE`.

The system recognizes six roles:

- **`Tutor`** — an individual who offers lessons, accepts session bookings, and responds to disputes. When `X-User-Role` is `Tutor`, `X-User-ID` is the `id` of the acting `Tutor` row; ownership checks on any resource that references a `Tutor` (Credentials, SubjectTags, Sessions, PayoutBatches) compare the resource's `tutor_id` to `X-User-ID`.
- **`Student`** — an individual booking lessons, either an `ADULT` self-booker or a `MINOR` row whose actions are gated through a linked `Parent`. When `X-User-Role` is `Student`, `X-User-ID` is the `id` of the acting `Student` row; ownership checks on any resource that references a `Student` (Sessions, RefundDisputes, ParentChildLinks) compare the resource's `student_id` to `X-User-ID`.
- **`Parent`** — manages one or more `MINOR` students through `ParentChildLink` approvals. When `X-User-Role` is `Parent`, `X-User-ID` is the `id` of the acting `Parent` row; ownership checks on any resource that references a `Parent` (ParentChildLinks) compare the resource's `parent_id` to `X-User-ID`, and a Parent's access to a child's Sessions or RefundDisputes is mediated by an `ACTIVE` `ParentChildLink` from `X-User-ID` to the `Student`.
- **`CredentialVerifier`** — an operations role that approves or rejects credentials and subject tags. When `X-User-Role` is `CredentialVerifier`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `reviewed_by` on a `Credential`) but does not compare it to any entity's `id`; the only rule is that it must not equal the `tutor_id` of the resource being acted on.
- **`PlatformArbiter`** — an operations role that resolves escalated refund disputes. When `X-User-Role` is `PlatformArbiter`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it (as `arbitrated_by` on a `RefundDispute`) but does not compare it to any entity's `id`; the only rule is that it must not equal the `Session`'s `tutor_id`, the `Session`'s `student_id`, or — if the student is a `MINOR` — the linked Parent's `id`.
- **`PlatformAdmin`** — the highest-privilege operations role. Suspends and reinstates tutors, initiates payouts, advances the test clock. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it (as `requested_by` on a `PayoutBatch`) but does not compare it to any entity's `id`; the only rule is that the admin marking a payout paid cannot equal the admin recorded in `requested_by`.

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

List endpoints accept two query parameters: `limit`, defaulting to 10, with a minimum of 1 and a maximum of 100, and `offset`, defaulting to 0. Unless otherwise stated, list endpoints return resources sorted by `created_at` ascending. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside `meta`. The `has_more` flag is `true` when `offset + limit < total_count`.

### 2.4. Common Resource Properties

Most top-level entities — `Tutor`, `Student`, `Parent`, `Credential`, `SubjectTag`, `Session`, `RefundDispute` — carry a common envelope of system-managed fields:

- `id` — a server-minted UUID string, with no type prefix.
- `created_at` — the ISO 8601 UTC timestamp with three fractional digits at which the row was first created.
- `updated_at` — the ISO 8601 UTC timestamp at which the row was most recently mutated. Every state transition, every recomputation of a computed money field, and every PATCH that takes effect refreshes `updated_at`.
- `version` — an integer that begins at 1 on creation and increments by exactly 1 on every mutation, including server-driven mutations such as cascade cancellations and ledger recomputations.

The `ParentChildLink` and `PayoutBatch` entities are bookkeeping records and carry only `id` and `created_at`; they have neither `updated_at` nor `version`. State transitions on a `ParentChildLink` (PENDING_PARENT_APPROVAL to ACTIVE, ACTIVE to REVOKED) and a `PayoutBatch` (REQUESTED to PAID, REQUESTED to REVERSED) are still real mutations, but they do not bump a version field.

### 2.5. Nested Resource Retrieval and Path-Parameter Validation

Many endpoints address a resource that lives inside another (for example, a credential under a tutor, a link under a parent). The server validates path identifiers strictly left-to-right and returns `ERR_NOT_FOUND` for the first missing one. A request for a credential under a non-existent tutor surfaces the missing tutor before the missing credential is ever considered. The same rule applies when a request body carries foreign-key references: if any FK in the body does not resolve to an existing row, the request is rejected with `ERR_NOT_FOUND`.

### 2.6. Validation Ordering

When multiple validation rules could fire on the same request, the server evaluates them in a fixed priority order so that the most fundamental failure surfaces first. The ordering, from highest priority to lowest, is: authentication headers (`ERR_AUTH_REQUIRED`), role permission (`ERR_FORBIDDEN`), path-level existence (`ERR_NOT_FOUND` for missing path resources), foreign-key existence (`ERR_NOT_FOUND` for missing FK targets in the body), state legality (`ERR_INVALID_STATE`), optimistic concurrency (`ERR_VERSION_CONFLICT`), segregation of duties (`ERR_SEGREGATION_VIOLATION`), parental gating for minors (`ERR_MINOR_REQUIRES_PARENT`), subject-offering check (`ERR_SUBJECT_NOT_OFFERED`), tutor-verified check (`ERR_TUTOR_NOT_VERIFIED`), session-window check (`ERR_INVALID_SESSION_WINDOW`), session overlap on confirm (`ERR_SESSION_OVERLAP`), trial uniqueness (`ERR_TRIAL_ALREADY_USED`), parent capacity (`ERR_CHILD_LIMIT_EXCEEDED`), dispute window (`ERR_DISPUTE_WINDOW_CLOSED`), amount bounds (`ERR_AMOUNT_OUT_OF_RANGE`), credit application validity (`ERR_CREDIT_APPLY_INVALID`), payout staleness (`ERR_PAYOUT_STALE`), resource-level cancel authority (`ERR_NOT_AUTHORIZED_FOR_RESOURCE` on cancel), dispute escalation readiness (`ERR_ESCALATION_NOT_ALLOWED`), and finally adjusted-minutes range (`ERR_ADJUSTED_MINUTES_OUT_OF_RANGE`). Body-level parse and type errors surface as `ERR_VALIDATION` and are returned before any business rule fires.

### 2.7. Optimistic Concurrency Control

Mutating endpoints accept an optional `version` field in the request body. When supplied, the server compares it to the current `version` of the target row; mismatch is rejected with `ERR_VERSION_CONFLICT`. When omitted, the server skips the check and proceeds. Every accepted mutation increments `version` by exactly 1, refreshes `updated_at`, and persists the new row before responding. OCC applies to entities that carry a `version` field; the bookkeeping records (`ParentChildLink`, `PayoutBatch`) do not participate in OCC.

### 2.8. Monetary Precision and Rounding

All money on the wire is in **integer cents**. There are no decimal money fields anywhere in the API. The price of a session, the platform commission, the tutor's payout, the cancellation fee, the dispute refund — every cents-denominated field is an integer.

Whenever a calculation produces a fractional cents value during intermediate arithmetic, the final cents value is rounded using **round half up** (a fractional part of exactly 0.5 always rounds away from zero, toward the larger magnitude). Two ordering rules govern multi-step calculations: gross prices are rounded at the line level first, then commissions are rounded as a single round at the end; commissions are never rounded on a per-minute basis. The cancellation fee is also rounded half-up after a single multiplication of the fee rate against `charged_amount_cents`.

### 2.9. The Money Conservation Invariant

The platform treats money conservation as a hard invariant. **Per-session**, at the end of every terminal Session transition (the entry into `COMPLETED`, `SETTLED`, `REFUNDED`, `CANCELLED_BY_STUDENT`, or `CANCELLED_BY_TUTOR`), the following must hold exactly, in integer cents:

> `gross_price_cents` equals `tutor_payout_cents` plus `final_commission_cents` plus `refund_to_student_cents`.

This invariant is checked at the close of every transition that mutates a money field on the session. During mid-flight states (REQUESTED, CONFIRMED, IN_PROGRESS, DISPUTED) `tutor_payout_cents` and `final_commission_cents` are zero or provisional and the invariant is not asserted. The bookkeeping split between `credit_applied_cents` and `charged_amount_cents` is how the gross was originally paid (credit vs cash) and they sum to `gross_price_cents` by construction; they do not appear on the right-hand side of the invariant.

**Globally**, the sum of every Student's `credit_balance_cents`, every Tutor's `payout_balance_cents`, every COMPLETED-but-not-yet-settled session's `tutor_payout_cents`, and every PAID `PayoutBatch`'s `amount_cents` must equal the sum across all sessions of `charged_amount_cents` plus the sum of any initial seeded student credit balances, minus the sum across sessions of any `final_commission_cents` that has not yet been paid out (since platform-held commission is not in any of the running buckets). Equality is exact — no tolerance.

### 2.10. Cascading Side Effects and Force-Cancellation

A single operation can mutate more than one entity. When a credential is approved, the credential row's status flips and the tutor's `verification_status` is recomputed; both rows have their `updated_at` and `version` advanced. When a credential expires (a system-driven action during clock advance), the credential transitions to `EXPIRED`, the tutor's `verification_status` is recomputed and, if it drops below `VERIFIED`, the tutor moves to `SUSPENDED`, and every Session of that tutor in `CONFIRMED` whose `start_at` is in the future is force-cancelled to `CANCELLED_BY_TUTOR` with `refund_to_student_cents` set equal to `charged_amount_cents` and `cancellation_fee_cents` set to 0 — a three-level cascade from Credential to Tutor to Session. Each affected Session's `updated_at` and `version` are bumped, the cancellation cascade credits the student's `credit_balance_cents` by `refund_to_student_cents`, and the per-session money conservation invariant must hold for every cancelled session.

The same future-CONFIRMED-cancel cascade fires when a `PlatformAdmin` explicitly suspends a tutor (`VERIFIED` to `SUSPENDED`), and a structurally similar cascade fires when a `Parent` or `PlatformAdmin` revokes an `ACTIVE` `ParentChildLink`: every Session of that minor child in `REQUESTED` or `CONFIRMED` with `start_at` in the future is cascade-cancelled as `CANCELLED_BY_STUDENT` with `refund_to_student_cents` equal to `charged_amount_cents` minus the cancellation fee computed for the child's session per the cancellation-fee rule.

### 2.11. Segregation of Duties

Several operations cannot be performed by parties to the underlying resource. A `CredentialVerifier` may not approve or reject a credential whose `tutor_id` equals their `X-User-ID`, and may not approve a subject tag for a tutor whose `id` equals their `X-User-ID` — the rejection is `ERR_SEGREGATION_VIOLATION`. A `PlatformArbiter` may not arbitrate a dispute whose underlying `Session` has `tutor_id`, `student_id`, or (for MINOR students) linked Parent `id` equal to their `X-User-ID` — also `ERR_SEGREGATION_VIOLATION`. A `PlatformAdmin` may not mark a payout paid if their `X-User-ID` equals the `requested_by` recorded when the batch was created — also `ERR_SEGREGATION_VIOLATION`.

## 3. Business Logic & Workflows

### 3.1. Tutor Onboarding, Credentials, and Verification Posture

A `Tutor` registers by supplying a `display_name` (1 to 80 characters), a globally unique login `email` validated as RFC 5322 against the existing `Tutor.email` set, an `hourly_rate_cents` between 1000 and 50000 (i.e. $10/hr through $500/hr), and a `trial_rate_cents` between 0 and `hourly_rate_cents` inclusive — the trial rate cannot exceed the standard rate. The tutor's `verification_status` is computed; new tutors begin in `UNVERIFIED`. A computed `subject_tags` array (a denormalized cache of `subject_code` strings from approved tags), a computed `payout_balance_cents` (starting at 0), and a computed `lifetime_completed_sessions` (starting at 0) round out the tutor row. The tutor's standing rates may later be updated via a tutor profile patch carrying any of `display_name`, `hourly_rate_cents`, `trial_rate_cents`, or an optional `version` for optimistic locking; the patch never alters the pinned price on any existing Session, since each Session snapshots the tutor's rates at booking time.

To establish a verification posture, a tutor uploads credentials. Each `Credential` submission carries the owning `tutor_id`, a `credential_type` of `GOVERNMENT_ID`, `DEGREE`, `TEACHING_LICENSE`, or `BACKGROUND_CHECK`, an opaque `document_ref` pointing at the uploaded document, and an optional `expires_at` ISO timestamp (null means no expiry). The credential row starts in `SUBMITTED` and carries a `status` that the verifier will later set, plus a computed `reviewed_by` populated when a verifier acts. Any credential submission for a tutor currently in `UNVERIFIED` flips the tutor from `UNVERIFIED` to `PENDING_REVIEW`; subsequent submissions do not re-trigger this transition.

A `CredentialVerifier` reviews credentials by approving or rejecting them. Both operations require the credential to be in `SUBMITTED` (any other state yields `ERR_INVALID_STATE`) and require the verifier's `X-User-ID` to differ from the credential's `tutor_id` (`ERR_SEGREGATION_VIOLATION`). Approving a credential transitions it `SUBMITTED → APPROVED` and writes the acting user id to `reviewed_by`; rejecting it transitions `SUBMITTED → REJECTED` and likewise records the verifier. Both outcomes trigger a recomputation of the tutor's `verification_status` per the verification-posture rule described below.

Verification posture is recomputed deterministically from the tutor's entire credential set, with a fixed precedence order: `REJECTED` over `VERIFIED` over `PENDING_REVIEW` over `SUSPENDED` over `UNVERIFIED`. The rule walks the credentials with these tests: if any credential of type `GOVERNMENT_ID` or `BACKGROUND_CHECK` is in `REJECTED`, the tutor is `REJECTED`. Otherwise, define the set of approved-and-unexpired credential types as those whose `status` is `APPROVED` and whose `expires_at` is either null or strictly later than the current clock; if this set contains both `GOVERNMENT_ID` and `BACKGROUND_CHECK`, the tutor is `VERIFIED`. Otherwise, if any credential is still in `SUBMITTED`, the tutor is `PENDING_REVIEW`. Otherwise, if the tutor was previously `VERIFIED` and the approved-and-unexpired set no longer contains both `GOVERNMENT_ID` and `BACKGROUND_CHECK`, the tutor moves to `SUSPENDED`. Otherwise, the tutor reverts to `UNVERIFIED`. This recomputation is what drives the tutor state transitions `PENDING_REVIEW → VERIFIED` (on a posture of `VERIFIED`) and `PENDING_REVIEW → REJECTED` (when a critical-type credential is rejected). The two critical credential types for verification are `GOVERNMENT_ID` and `BACKGROUND_CHECK`; `DEGREE` and `TEACHING_LICENSE` are tracked but do not gate `VERIFIED` status.

A `VERIFIED` tutor moves to `SUSPENDED` either when a system-driven credential expiration drops the posture below `VERIFIED`, or when a `PlatformAdmin` explicitly suspends the tutor. Both paths fire the cascade described in §2.10: every future-dated `CONFIRMED` session for that tutor is force-cancelled to `CANCELLED_BY_TUTOR` with full refund. A `SUSPENDED` tutor can be returned to `VERIFIED` only by a `PlatformAdmin` reinstate action, and only if the verification posture computation again yields `VERIFIED` — typically after the tutor has uploaded fresh credentials.

### 3.2. Subject Tags

Before a tutor can teach a subject, they must declare it. A tutor proposes a `SubjectTag` by submitting a `subject_code` from the controlled vocabulary (must match the regular expression of an uppercase letter followed by 2 to 29 characters from the set of uppercase letters, digits, and underscores; total length 3 to 30 characters; the `(tutor_id, subject_code)` pair must be unique) and a `proficiency_level` of `BEGINNER`, `INTERMEDIATE`, `ADVANCED`, or `EXPERT`. The tag row carries the owning `tutor_id` and starts in `PROPOSED`.

A `CredentialVerifier` reviews subject proposals. Approving a tag transitions it `PROPOSED → APPROVED`, provided the tutor's `verification_status` is `VERIFIED` and the verifier's `X-User-ID` is different from the tutor's `id` (`ERR_SEGREGATION_VIOLATION` otherwise). On approval, the `subject_code` is appended to the tutor's denormalized `subject_tags` cache.

A tag may be deleted by the owning tutor or by a `PlatformAdmin`. Deletion of a `PROPOSED` tag is unconditional and transitions it directly to `REMOVED`. Deletion of an `APPROVED` tag transitions it `APPROVED → REMOVED` and removes the `subject_code` from the tutor's `subject_tags` cache, but only if there is no Session for that `(tutor_id, subject_code)` pair in any of `REQUESTED`, `CONFIRMED`, or `IN_PROGRESS` — otherwise the delete is rejected with `ERR_INVALID_STATE`. The `REMOVED` state is terminal.

### 3.3. Students, Parents, and the Child-Link Workflow

A `Student` registers with a `display_name` (1 to 80 characters), a globally unique `email` (RFC 5322, unique among `Student.email`), an `account_type` of either `ADULT` or `MINOR`, and an optional `parent_id`. For an `ADULT` student the `parent_id` must be null; for a `MINOR` student the `parent_id` must be set to an existing `Parent.id`. The student row also carries a computed `credit_balance_cents` (starting at 0), which accrues refunds from cancellations and dispute resolutions and which can be spent on future bookings via the booking-time `apply_credits` flag.

A `Parent` registers with a `display_name` (1 to 80 characters) and a globally unique `email` (RFC 5322, unique among `Parent.email`). The parent row carries a computed `managed_child_count` (starting at 0) reflecting the number of `Student` rows whose `parent_id` equals the parent's `id`, whose `account_type` is `MINOR`, and which have not been soft-deleted. A parent may manage at most 10 children; an approval that would push `managed_child_count` past 10 is rejected with `ERR_CHILD_LIMIT_EXCEEDED`.

When a `MINOR` student is created with a `parent_id`, the server automatically creates a `ParentChildLink` carrying `parent_id`, `student_id`, a `link_status` of `PENDING_PARENT_APPROVAL`, and a null `approved_at`. The link is the gating object between parent and child: until it reaches `ACTIVE`, no parent action can be taken on behalf of the child. The owning parent approves the link, which moves it `PENDING_PARENT_APPROVAL → ACTIVE`, sets `approved_at` to the current clock, and increments the parent's `managed_child_count` by 1. The approve action requires the acting parent's `X-User-ID` to equal the link's `parent_id` and requires the linked student's `account_type` to be `MINOR`.

Either the owning parent or a `PlatformAdmin` may revoke an `ACTIVE` link, which transitions it `ACTIVE → REVOKED`, decrements the parent's `managed_child_count` by 1, and triggers the future-session cascade described in §2.10 — every Session of the linked child in `REQUESTED` or `CONFIRMED` with `start_at` later than the current clock is cancelled as `CANCELLED_BY_STUDENT` with `refund_to_student_cents` set to `charged_amount_cents` minus the cancellation fee computed for that child's session per the cancellation-fee rule. The `REVOKED` state is terminal.

Bookings on behalf of a `MINOR` are always initiated by the linked `Parent` through an `ACTIVE` `ParentChildLink`. An attempt to book on behalf of a minor without an `ACTIVE` link, or any `MINOR`-targeting operation where the acting `Parent` is not the linked one, is rejected with `ERR_MINOR_REQUIRES_PARENT` — this gate applies to session booking, dispute opening, and session cancellation. An `ADULT` student carrying a non-null `parent_id` is also rejected with `ERR_MINOR_REQUIRES_PARENT` at registration time.

### 3.4. Booking a Session

A `Student` (for `ADULT` self-booking) or a `Parent` (acting through an `ACTIVE` link for a `MINOR` child) books a Session by submitting the target `tutor_id`, the booking `student_id`, the `subject_code` to be taught, the scheduled `start_at` and `end_at` ISO 8601 UTC timestamps with three fractional digits, an optional `is_trial` boolean (default false), and an optional `apply_credits` boolean (default false).

Several gates fire at booking time, in the priority order of §2.6. The tutor must be `VERIFIED` — bookings against any other `verification_status` are rejected with `ERR_TUTOR_NOT_VERIFIED`. The `subject_code` must match an `APPROVED` `SubjectTag` for the tutor; otherwise `ERR_SUBJECT_NOT_OFFERED`. The session window must satisfy three properties: `start_at` must be at least 60 minutes ahead of the current clock (the minimum-lead-time rule), `end_at` must be strictly after `start_at`, and the scheduled duration must be a positive whole number of minutes no greater than 240 (a four-hour cap); any violation produces `ERR_INVALID_SESSION_WINDOW`. When `is_trial` is true, the `(tutor_id, student_id)` pair must have **no** prior Session anywhere in history (active or terminal) with `is_trial` true, and the student must have a count of zero `COMPLETED` sessions with that tutor; otherwise `ERR_TRIAL_ALREADY_USED`. When two trial bookings are submitted concurrently for the same `(tutor_id, student_id)` pair, exactly one wins and the other receives `ERR_TRIAL_ALREADY_USED`.

When `apply_credits` is true on a non-trial booking, the server consumes from the student's `credit_balance_cents` up to the gross price; the amount consumed is the minimum of `gross_price_cents` and the student's `credit_balance_cents` at the moment of booking. The remaining `charged_amount_cents` (gross minus credit applied) must be 0 or greater. Trial bookings always pin `credit_applied_cents` to 0 and ignore the `apply_credits` flag. Any violation — for example, an `apply_credits=true` request that would over-spend the student's balance — is rejected with `ERR_CREDIT_APPLY_INVALID`.

If all gates pass, the server creates the Session in `REQUESTED` and pins the following at REQUESTED: `gross_price_cents` per the gross-pricing rule, `credit_applied_cents` per the credits rule above, `charged_amount_cents` (equal to `gross_price_cents` minus `credit_applied_cents`), and `provisional_commission_cents` per the commission rule (PROVISIONAL variant). The student's `credit_balance_cents` is decremented by the `credit_applied_cents` actually consumed.

The gross price is computed as a tiered hourly figure. First, the scheduled duration is computed as the number of seconds between `end_at` and `start_at` divided by 60.0 and then rounded up to the next whole minute (so 90 minutes 10 seconds becomes 91 scheduled minutes). The base per-minute rate is the tutor's `trial_rate_cents` divided by 60.0 when `is_trial` is true, and the tutor's `hourly_rate_cents` divided by 60.0 otherwise. The raw amount is the base per-minute rate multiplied by the scheduled minutes. A multi-hour discount then applies **only to non-trial bookings**: if scheduled minutes is at least 180, the raw amount is multiplied by 0.90 (a 10% discount); else if scheduled minutes is at least 120, the raw amount is multiplied by 0.95 (a 5% discount); otherwise no discount applies. Trial bookings receive no discount even if they meet the duration thresholds. The final `gross_price_cents` is the raw amount rounded half-up to whole cents — a single rounding at the end.

### 3.5. Confirming, Running, and Completing a Session

A booked session sits in `REQUESTED` awaiting tutor acceptance. The owning tutor confirms the session, which advances `REQUESTED → CONFIRMED`. Confirmation requires the acting tutor's `X-User-ID` to equal the session's `tutor_id`, requires the tutor's current `verification_status` to be `VERIFIED` (a tutor whose posture has slipped to `SUSPENDED` or `UNVERIFIED` between booking and confirmation cannot confirm — `ERR_TUTOR_NOT_VERIFIED`), and requires the session to have no temporal overlap with any other Session of the same tutor in `CONFIRMED` or `IN_PROGRESS`. Temporal overlap uses a closed-open interval `[start_at, end_at)` with a 0-minute buffer: two sessions overlap if the open interval of one contains any instant of the closed-open interval of the other. An overlap is rejected with `ERR_SESSION_OVERLAP`. When two overlapping confirms race, exactly one wins on the per-`tutor_id` overlap reservation and the other receives `ERR_SESSION_OVERLAP`. When a tutor's confirm races a student's cancel on the same session, exactly one transition succeeds and the loser observes `ERR_INVALID_STATE` because the source state has already shifted.

As the wall clock advances and the system is told the new clock instant via a clock-advance call carrying a `to_iso8601` timestamp, several sweeps run together. Every Session in `CONFIRMED` whose `start_at` is at or before the new clock and whose `end_at` is strictly later transitions `CONFIRMED → IN_PROGRESS`. (There is no client-callable "start" endpoint; entry into `IN_PROGRESS` is purely a server-side function of the clock.) Every credential whose `status` is `APPROVED` and whose `expires_at` is at or before the new clock transitions `APPROVED → EXPIRED` with the cascade of §2.10. Every COMPLETED session whose elapsed time since `end_at` is at least 72 hours and which has no active dispute transitions `COMPLETED → SETTLED` (see §3.6). Every non-terminal `RefundDispute` whose age since `created_at` is at least 14 days transitions to `ARBITRATION` (see §3.7). Sweeps run as a single logical step per clock advance.

The tutor marks the session complete, which advances `IN_PROGRESS → COMPLETED`. The complete action requires the acting tutor's `X-User-ID` to equal the session's `tutor_id` and requires either that the current clock has reached `end_at` or that the reported `adjusted_minutes` is at least the scheduled minutes minus 10 (allowing a tutor to wrap up to 10 minutes early). The request optionally carries `adjusted_minutes`, the actual minutes delivered; if omitted, it defaults to the scheduled minutes. The supplied value must lie in the range 0 through scheduled minutes inclusive, where scheduled minutes is the same ceiling computation used at booking; otherwise `ERR_ADJUSTED_MINUTES_OUT_OF_RANGE`.

Completion triggers a recomputation of the actual delivered gross. The `actual_gross_cents` is recomputed using `adjusted_minutes` (clamped to the range 0 through scheduled minutes inclusive) and the same tiered formula as gross pricing — base per-minute rate is the trial rate (when `is_trial` is true) or the hourly rate (otherwise), multiplied by the clamped actual minutes, then multiplied by 0.90 if scheduled minutes is at least 180 for non-trial bookings, or 0.95 if scheduled minutes is at least 120 for non-trial bookings, then rounded half-up. Note that the discount tier is keyed on **scheduled** minutes (not actual), so a tutor cannot shed the multi-hour discount by reporting fewer actual minutes. The unused-minute portion is then refunded: a short-delivery refund equal to the maximum of zero and `gross_price_cents` minus `actual_gross_cents` is computed; if this short-delivery refund is positive, `refund_to_student_cents` is increased by it and the student's `credit_balance_cents` is increased by the same amount.

The final commission is then pinned. The `final_commission_cents` is computed per the commission rule using the FINAL variant, which keys the commission tier on the tutor's `lifetime_completed_sessions` **at the moment of completion** (after the increment described next) and bills commission on `actual_gross_cents`. Specifically: if the tutor's `lifetime_completed_sessions` is at least 100, the commission rate is 0.10 (10%); else if it is at least 20, the commission rate is 0.15 (15%); otherwise 0.20 (20%). The commission is the rate multiplied by `actual_gross_cents`, rounded half-up as a single rounding at the end. The `tutor_payout_cents` is then pinned to `actual_gross_cents` minus `final_commission_cents`, clamped to zero or greater. The tutor's `lifetime_completed_sessions` is incremented by 1. The per-session conservation invariant of §2.9 must hold at the close of this transition; note that `tutor_payout_cents` is not credited to the tutor's `payout_balance_cents` at COMPLETED — that crediting happens only on entry to `SETTLED`.

### 3.6. Settlement and the Hold Window

A `COMPLETED` session enters its hold window: it cannot pay out to the tutor until 72 hours of wall-clock time have elapsed since `end_at` and no `RefundDispute` is in any non-terminal state for that session. Both conditions are evaluated by the clock-advance sweep. When both are met, the session transitions `COMPLETED → SETTLED`, and the tutor's `payout_balance_cents` is increased by the session's pinned `tutor_payout_cents`. The `SETTLED` state is terminal. If a dispute is opened during the hold window, settlement is deferred until the dispute reaches a terminal state.

A `PlatformAdmin` creates a `PayoutBatch` from a tutor's running balance by submitting the target `tutor_id`. At creation, the server snapshots the tutor's current `payout_balance_cents` into the batch's `amount_cents` and snapshots into `session_ids` the ids of every `SETTLED` Session for that tutor whose `tutor_payout_cents` contributes to the snapshot — specifically, all SETTLED sessions for the tutor that are not yet attached to any `PayoutBatch` in either `REQUESTED` or `PAID` status — sorted by Session `id` ascending. The batch records the requesting admin's `X-User-ID` as `requested_by` and starts in `REQUESTED`. Listing payout batches accepts optional `tutor_id` and `status` query filters in addition to pagination.

The batch is then resolved in one of two ways. A **different** `PlatformAdmin` (whose `X-User-ID` differs from `requested_by` — `ERR_SEGREGATION_VIOLATION` otherwise) marks the batch paid, which transitions it `REQUESTED → PAID` and decrements the tutor's `payout_balance_cents` by `amount_cents`. The marked-paid step is rejected with `ERR_PAYOUT_STALE` if the tutor's current `payout_balance_cents` no longer equals what the batch was sized against (this happens when a refund landed between request and mark-paid, changing the balance). Alternatively, any `PlatformAdmin` may reverse a `REQUESTED` batch, which transitions it `REQUESTED → REVERSED` with no balance change (the balance was never decremented at REQUESTED in the first place). Both `PAID` and `REVERSED` are terminal. Two simultaneous mark-paid attempts on the same batch serialize so that exactly one wins and the loser receives `ERR_INVALID_STATE` because the batch has already left `REQUESTED`.

The payout-balance computation at the moment a batch is requested has a closed form: `amount_cents` equals the tutor's current `payout_balance_cents`, which itself equals the running sum of `tutor_payout_cents` across all SETTLED sessions of that tutor whose ids are not already attached to any `PayoutBatch` in `REQUESTED` or `PAID`. All arithmetic is integer cents — no rounding.

### 3.7. The Refund Dispute Lifecycle

Once a session is in `COMPLETED` or `SETTLED`, the booking student or, for minors, the linked parent may open a `RefundDispute` against it. The dispute submission carries the target `session_id`, the `opened_by_role` (either `Student` or `Parent`), the `opened_by_user_id` (the X-User-ID of the opener; for a MINOR this must equal the linked Parent's `id`), a `reason_code` of `TUTOR_NO_SHOW`, `QUALITY_ISSUE`, `TECHNICAL_FAILURE`, or `OTHER`, and the `requested_amount_cents`. The requested amount must be strictly greater than zero and no greater than the session's `charged_amount_cents`; otherwise `ERR_AMOUNT_OUT_OF_RANGE`. The dispute must be opened within 7 days of the session's `end_at` and against a session in `COMPLETED` or `SETTLED`; otherwise `ERR_DISPUTE_WINDOW_CLOSED`. At most one non-terminal dispute may exist per session at any time; a second attempt is rejected with `ERR_DISPUTE_ALREADY_OPEN`. When the underlying session is currently `COMPLETED`, opening the dispute cascades it `COMPLETED → DISPUTED`; when the session is already `SETTLED`, the session remains in `SETTLED` and the dispute is simply attached.

The dispute row starts in `OPEN` with `round_count` 0, a null `arbitrated_by`, and a null `resolved_refund_cents`. The lifecycle is cyclic between `OPEN`, `TUTOR_RESPONDED`, and `COUNTER_PROPOSED`. The owning tutor responds via the respond action, which moves the dispute `OPEN → TUTOR_RESPONDED`; the action requires the tutor's `X-User-ID` to equal the session's `tutor_id`. From `TUTOR_RESPONDED`, the tutor may submit a counter offer carrying `counter_amount_cents` (the offer must lie in the range 0 through `requested_amount_cents` inclusive — `ERR_AMOUNT_OUT_OF_RANGE` otherwise), which moves the dispute `TUTOR_RESPONDED → COUNTER_PROPOSED` and increments `round_count` by 1. The counter step is rejected with `ERR_INVALID_STATE` once `round_count` has already reached 3.

From `COUNTER_PROPOSED`, the opener (student or linked parent) chooses to accept or reopen. Accepting transitions the dispute `COUNTER_PROPOSED → RESOLVED_REFUND`, pins `resolved_refund_cents` to the latest counter offer (which has already been bounded into the range 0 through `requested_amount_cents`), and cascades the underlying session `DISPUTED → REFUNDED`. Reopening (the opener rejects the counter) transitions the dispute `COUNTER_PROPOSED → OPEN`, leaving the tutor to respond again; reopen requires `round_count < 3`.

Escalation produces an `ARBITRATION` state. An escalate action transitions the dispute from `OPEN` or from `TUTOR_RESPONDED` to `ARBITRATION`; the action is only permitted when `round_count` is at least 3 **or** the elapsed time since the dispute's `created_at` is at least 14 days. Any earlier escalation is rejected with `ERR_ESCALATION_NOT_ALLOWED`. The 14-day timer is also enforced automatically: any non-terminal dispute in `OPEN` or `TUTOR_RESPONDED` whose age reaches 14 days is auto-escalated to `ARBITRATION` by the clock-advance sweep.

A `PlatformArbiter` resolves an `ARBITRATION` dispute by submitting a `decision` of either `REFUND` or `DENY` and, when refunding, an optional `refund_amount_cents`. The arbiter's `X-User-ID` must not equal the session's `tutor_id`, must not equal the session's `student_id`, and must not equal the linked Parent's `id` for MINOR students — any of these violations yields `ERR_SEGREGATION_VIOLATION`. A `REFUND` decision transitions the dispute `ARBITRATION → RESOLVED_REFUND`, writes the acting user id to `arbitrated_by`, pins `resolved_refund_cents` to the arbiter-selected `refund_amount_cents` (bounded into the range 0 through `requested_amount_cents`), and cascades the underlying session `DISPUTED → REFUNDED`. A `DENY` decision transitions the dispute `ARBITRATION → RESOLVED_DENY`, writes `arbitrated_by`, pins `resolved_refund_cents` to 0, and cascades the underlying session `DISPUTED → SETTLED`. The opener may also withdraw the dispute from `OPEN` or from `COUNTER_PROPOSED`, transitioning it to `WITHDRAWN`; on withdraw, the cascaded session goes `DISPUTED → SETTLED` if the 72-hour hold window has already elapsed since `end_at`, or `DISPUTED → COMPLETED` if the session is still inside the hold window. `RESOLVED_REFUND`, `RESOLVED_DENY`, and `WITHDRAWN` are terminal.

Two simultaneous attempts to open a dispute against the same session serialize so that exactly one wins; the loser receives `ERR_DISPUTE_ALREADY_OPEN` because the per-session uniqueness constraint excludes any non-terminal dispute. Cancel-vs-confirm races on a session (see §3.5) and approve-vs-reject races on a credential (one side has already left `SUBMITTED`) likewise yield `ERR_INVALID_STATE` on the loser.

When a session transitions `DISPUTED → REFUNDED` from the cascade of a `RESOLVED_REFUND` dispute, several money fields are pinned: `arbitration_refund_cents` is set to the dispute's `resolved_refund_cents` (this is distinct from any short-delivery refund booked at COMPLETED); `refund_to_student_cents` is increased by `arbitration_refund_cents` (adding to any short-delivery refund already present); the student's `credit_balance_cents` is increased by `arbitration_refund_cents`. The platform charges commission only on the portion of the delivered service the tutor still keeps: a service-revenue-retained quantity equal to the maximum of zero and `actual_gross_cents` minus `arbitration_refund_cents` is computed; `final_commission_cents` is recomputed using the commission rule with the FINAL_AFTER_REFUND variant, billing commission only on this retained portion at the tutor's tier as of that moment (10% at 100 or more lifetime completed sessions, 15% at 20 or more, 20% otherwise, single round half-up); `tutor_payout_cents` is re-pinned to service-revenue-retained minus this new `final_commission_cents`, clamped to zero or greater. The per-session conservation invariant of §2.9 must hold at the close of this transition.

When a session transitions `DISPUTED → SETTLED` from a `RESOLVED_DENY` arbitration, no money fields are recomputed and the tutor's `payout_balance_cents` is increased by the session's pinned `tutor_payout_cents`.

### 3.8. Cancellation and the Fee Ladder

Either the booking student (or their linked parent for a `MINOR`) or the assigned tutor may cancel a session before completion. The cancel action accepts a session in `REQUESTED` or `CONFIRMED`. When the actor is the student or the linked parent, the cancellation transitions the session to `CANCELLED_BY_STUDENT`; when the actor is the tutor, the transition is to `CANCELLED_BY_TUTOR`. Parent cancellation requires an `ACTIVE` `ParentChildLink` to the student; tutor cancellation requires the acting tutor's `X-User-ID` to equal the session's `tutor_id`; student cancellation requires the acting student's `X-User-ID` to equal the session's `student_id` — any mismatch is rejected with `ERR_NOT_AUTHORIZED_FOR_RESOURCE`.

A cancellation fee is then computed and pinned to `cancellation_fee_cents`. The fee depends on hours of notice between the current clock and the session's `start_at`. Tutor-initiated cancellations and any system-driven cascade cancellations carry a fee of 0. For a manual student-initiated cancellation, define hours-of-notice as the seconds from the current clock to `start_at` divided by 3600.0. If hours-of-notice is at least 24, the fee is 0 (a free cancel). If hours-of-notice is less than 24 but at least 2, the fee is 25% of `charged_amount_cents`, rounded half-up. If hours-of-notice is less than 2, the fee is 50% of `charged_amount_cents`, rounded half-up. The upper-side boundary inclusivity is strict: a hours-of-notice equal to exactly 24.0 is free; a value equal to exactly 2.0 is the 25% tier; the 50% tier only fires for strictly less than 2.0.

After the fee is pinned, the refund is pinned: `refund_to_student_cents` is set to `charged_amount_cents` minus `cancellation_fee_cents` for a student cancel, or to `charged_amount_cents` (full refund, fee 0) for a tutor cancel or any system cascade. The student's `credit_balance_cents` is then increased by `refund_to_student_cents`. The per-session conservation invariant of §2.9 must hold at the close of this transition.

### 3.9. The Test Clock and Read Endpoints

The platform operates against a virtual clock that is advanced exclusively by a `PlatformAdmin` test-driving capability carrying a `to_iso8601` target instant. Each advance fires all four sweeps as a single logical step: future-dated `CONFIRMED` sessions whose `start_at` has been reached enter `IN_PROGRESS`; `COMPLETED` sessions whose hold window has elapsed and which have no active dispute enter `SETTLED` and credit the tutor's `payout_balance_cents`; `APPROVED` credentials whose `expires_at` has been reached enter `EXPIRED` with the cascade of §2.10; and non-terminal disputes whose age reaches 14 days auto-escalate to `ARBITRATION`. A read of the current virtual clock is available to every role.

Read endpoints round out the API. Tutors, students, parents, the verifier, and the arbiter may read tutor profiles (including the computed `verification_status`, the denormalized `subject_tags` array, `payout_balance_cents`, and `lifetime_completed_sessions`); a tutor list-and-search endpoint accepts optional `subject_code`, `verification_status`, and `max_hourly_rate_cents` filters in addition to pagination. A student is readable by the student themselves, the linked parent, and a `PlatformAdmin`. A parent is readable by the parent themselves and a `PlatformAdmin`, and a parent may list their own `ParentChildLink` rows filtered by `link_status`. A session is readable by the booking student, the linked parent (via active link), the assigned tutor, a `PlatformAdmin`, and the `PlatformArbiter` (the last for arbitration context); a session list endpoint accepts optional `status`, `from`, and `to` filters in addition to pagination, scoped to the calling role's accessible sessions. A dispute is readable by the opener, the assigned tutor, the `PlatformArbiter`, and a `PlatformAdmin`.

## 4. Endpoint Definitions

Operations that create a new top-level resource — a tutor, a credential, a subject tag, a student, a parent, a session, a refund dispute, a payout batch — return `201 Created`. Operations that modify an existing resource (including all state-transition actions and tutor profile patches) return `200 OK`. Successful deletions return `204 No Content`. All endpoints are mounted beneath the `/tutoring` prefix.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/tutoring/tutors` | Create a tutor profile | PlatformAdmin, Tutor |
| GET    | `/tutoring/tutors/{tutor_id}` | Read a tutor with derived fields | PlatformAdmin, Tutor, Student, Parent, CredentialVerifier, PlatformArbiter |
| PATCH  | `/tutoring/tutors/{tutor_id}` | Update tutor display name or rates (OCC) | Tutor, PlatformAdmin |
| GET    | `/tutoring/tutors` | List/search tutors with filters | PlatformAdmin, Student, Parent |
| POST   | `/tutoring/tutors/{tutor_id}/suspend` | Admin suspend (VERIFIED to SUSPENDED) | PlatformAdmin |
| POST   | `/tutoring/tutors/{tutor_id}/reinstate` | Admin restore (SUSPENDED to VERIFIED) | PlatformAdmin |
| POST   | `/tutoring/tutors/{tutor_id}/credentials` | Submit a credential document | Tutor |
| POST   | `/tutoring/tutors/{tutor_id}/credentials/{credential_id}/approve` | Verifier approves a credential | CredentialVerifier |
| POST   | `/tutoring/tutors/{tutor_id}/credentials/{credential_id}/reject` | Verifier rejects a credential | CredentialVerifier |
| POST   | `/tutoring/tutors/{tutor_id}/subjects` | Propose a subject tag | Tutor |
| POST   | `/tutoring/tutors/{tutor_id}/subjects/{subject_id}/approve` | Verifier approves a subject tag | CredentialVerifier |
| DELETE | `/tutoring/tutors/{tutor_id}/subjects/{subject_id}` | Remove a subject tag | Tutor, PlatformAdmin |
| POST   | `/tutoring/students` | Create a student (ADULT or MINOR) | Student, Parent, PlatformAdmin |
| GET    | `/tutoring/students/{student_id}` | Read a student | Student, Parent, PlatformAdmin |
| POST   | `/tutoring/parents` | Create a parent | Parent, PlatformAdmin |
| GET    | `/tutoring/parents/{parent_id}` | Read a parent including managed_child_count | Parent, PlatformAdmin |
| GET    | `/tutoring/parents/{parent_id}/links` | List child links | Parent, PlatformAdmin |
| POST   | `/tutoring/parents/{parent_id}/links/{link_id}/approve` | Parent approves a pending child link | Parent |
| DELETE | `/tutoring/parents/{parent_id}/links/{link_id}` | Revoke a child link with cancellation cascade | Parent, PlatformAdmin |
| POST   | `/tutoring/sessions` | Book a session | Student, Parent |
| GET    | `/tutoring/sessions/{session_id}` | Read a session | Tutor, Student, Parent, PlatformAdmin, PlatformArbiter |
| GET    | `/tutoring/sessions` | List accessible sessions with filters | Tutor, Student, Parent, PlatformAdmin |
| POST   | `/tutoring/sessions/{session_id}/confirm` | Tutor confirms a REQUESTED session | Tutor |
| POST   | `/tutoring/sessions/{session_id}/cancel` | Cancel a session (by student, parent, or tutor) | Student, Parent, Tutor |
| POST   | `/tutoring/sessions/{session_id}/complete` | Tutor marks a session complete | Tutor |
| POST   | `/tutoring/disputes` | Open a refund dispute | Student, Parent |
| GET    | `/tutoring/disputes/{dispute_id}` | Read a dispute | Student, Parent, Tutor, PlatformArbiter, PlatformAdmin |
| POST   | `/tutoring/disputes/{dispute_id}/respond` | Tutor responds (OPEN to TUTOR_RESPONDED) | Tutor |
| POST   | `/tutoring/disputes/{dispute_id}/counter` | Tutor proposes a counter (carries counter_amount_cents) | Tutor |
| POST   | `/tutoring/disputes/{dispute_id}/accept` | Opener accepts the latest counter | Student, Parent |
| POST   | `/tutoring/disputes/{dispute_id}/reopen` | Opener rejects the counter | Student, Parent |
| POST   | `/tutoring/disputes/{dispute_id}/escalate` | Escalate to ARBITRATION | Student, Parent, PlatformAdmin |
| POST   | `/tutoring/disputes/{dispute_id}/arbitrate` | Arbiter resolves (decision REFUND or DENY) | PlatformArbiter |
| POST   | `/tutoring/disputes/{dispute_id}/withdraw` | Opener withdraws the dispute | Student, Parent |
| POST   | `/tutoring/payouts` | Admin creates a payout batch | PlatformAdmin |
| POST   | `/tutoring/payouts/{payout_id}/mark-paid` | A different admin marks the batch paid | PlatformAdmin |
| POST   | `/tutoring/payouts/{payout_id}/reverse` | Reverse a REQUESTED batch | PlatformAdmin |
| GET    | `/tutoring/payouts` | List payout batches with filters | PlatformAdmin, Tutor |
| POST   | `/tutoring/_clock/advance` | Advance the virtual clock (test-driving) | PlatformAdmin |
| GET    | `/tutoring/_clock` | Read the current virtual clock | PlatformAdmin, Tutor, Student, Parent, CredentialVerifier, PlatformArbiter |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_AUTH_REQUIRED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_AUTHORIZED_FOR_RESOURCE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_VERSION_CONFLICT` | 409 Conflict |
| `ERR_SESSION_OVERLAP` | 409 Conflict |
| `ERR_TRIAL_ALREADY_USED` | 422 Unprocessable Entity |
| `ERR_DISPUTE_ALREADY_OPEN` | 409 Conflict |
| `ERR_DISPUTE_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_AMOUNT_OUT_OF_RANGE` | 422 Unprocessable Entity |
| `ERR_TUTOR_NOT_VERIFIED` | 422 Unprocessable Entity |
| `ERR_SUBJECT_NOT_OFFERED` | 422 Unprocessable Entity |
| `ERR_SEGREGATION_VIOLATION` | 403 Forbidden |
| `ERR_MINOR_REQUIRES_PARENT` | 403 Forbidden |
| `ERR_INVALID_SESSION_WINDOW` | 422 Unprocessable Entity |
| `ERR_CHILD_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_PAYOUT_STALE` | 409 Conflict |
| `ERR_CREDIT_APPLY_INVALID` | 422 Unprocessable Entity |
| `ERR_ESCALATION_NOT_ALLOWED` | 422 Unprocessable Entity |
| `ERR_ADJUSTED_MINUTES_OUT_OF_RANGE` | 422 Unprocessable Entity |
| `ERR_VALIDATION` | 400 Bad Request |
