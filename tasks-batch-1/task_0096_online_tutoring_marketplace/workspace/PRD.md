# Online Tutoring Marketplace API — Product Requirements Document

## 1. Introduction

This document specifies the backend service for an online tutoring marketplace in the style of platforms such as Wyzant, where independent tutors offer paid lessons to families and the platform mediates trust, money, and disputes between them. The system must reconcile several parties whose interests do not naturally align: tutors who want their credentials recognized and their lessons paid promptly, parents who manage one or more children and want assurance that a lesson actually happened before money changes hands, a trust-and-safety function that gates which tutors may teach which subjects, and an independent arbitrator who resolves refund disputes that the two sides cannot settle on their own.

The marketplace is built around a small number of durable workflows. Tutors submit credentials that a reviewer verifies before the tutor may be tagged to credential-gated subjects; parents fund a prepaid wallet, register their children, and book lessons that place a hold against that wallet; delivered lessons are confirmed and settled, at which point the platform takes a commission whose rate depends on the tutor's lifetime earnings; and, when a parent is dissatisfied, a structured refund negotiation runs between parent and tutor, escalating to binding arbitration when the two cannot agree. Money is tracked to the cent across parent wallets, tutor payout balances, and the platform's commission take, and every monetary movement must conserve value — no cent appears or disappears without a corresponding ledger entry.

Because lessons are scheduled against a clock and disputes have time windows, all temporal logic is evaluated against a single deterministic server clock that test harnesses advance explicitly rather than against wall-clock time. The remainder of this document defines the global contracts every endpoint shares (Section 2), the business workflows and their rules (Section 3), the endpoint surface (Section 4), and the catalogue of error identifiers (Section 5).

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers identifying the caller: `X-User-ID`, the caller's identifier, and `X-User-Role`, the caller's role. If either header is missing or malformed, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. When the headers are well-formed but the role is not permitted to invoke the requested operation (per the authorization column in Section 4), the request is rejected with `ERR_UNAUTHORIZED`.

The platform recognizes exactly five roles, spelled precisely as follows: `PlatformAdmin`, `TrustOfficer`, `Tutor`, `ParentGuardian`, and `Arbiter`.

Two of these roles are **entity-backed**, meaning their `X-User-ID` is the identity of a persisted entity:

- When `X-User-Role` is `Tutor`, `X-User-ID` is the `id` of the acting `Tutor`. Ownership checks on any resource that references a tutor (a `Credential`, a `TutorSubjectTag`, a `Session`, and the responding side of a `RefundCase`) compare that resource's `tutor_id` to `X-User-ID`.
- When `X-User-Role` is `ParentGuardian`, `X-User-ID` is the `id` of the acting `ParentAccount`. Ownership checks on any resource that references a parent (a `Student` via `parent_account_id`, a `Booking`, and the claimant side of a `RefundCase`) compare that resource's parent foreign key to `X-User-ID`.

The remaining three roles are **opaque**: their `X-User-ID` is an operator identifier not tied to any persisted entity. When `X-User-Role` is `PlatformAdmin`, `TrustOfficer`, or `Arbiter`, the server does not compare `X-User-ID` to any entity's `id`. The server may record such an identifier where a transition writes it — for example, a `TrustOfficer`'s `X-User-ID` is stored as `reviewed_by` on a `Credential` when that officer begins reviewing it — but it never treats that value as a foreign key for ownership purposes.

When an entity-backed caller acts on a resource it does not own — a tutor operating on another tutor's credential, or a parent confirming another parent's session — the request is rejected with `ERR_NOT_RESOURCE_OWNER`. This ownership check applies to tutor-owned and parent-owned mutation endpoints.

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

All list endpoints accept two query parameters, `limit` and `offset`. The `limit` parameter defaults to 10 when omitted, may be no smaller than 1, and may be no larger than 100. The `offset` parameter defaults to 0 and represents the number of leading rows to skip. List results are returned sorted by `created_at` in ascending order — oldest first. The `meta` block of a list response carries the pagination fields `limit`, `offset`, `total_count` (the total number of rows matching the filter, ignoring pagination), and `has_more` (true when rows remain beyond the current page).

### 2.4. Common Resource Properties

Every resource in the system carries a server-minted `id`: a UUID string with no type prefix, serving as identity only. Resources that are mutable additionally carry three system-managed fields:

- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, stamped once at creation.
- `updated_at` — an ISO 8601 UTC timestamp, refreshed on every mutation of the resource.
- `version` — an integer that begins at its initial value and increments by one on each mutation. It is the basis for the optimistic concurrency control described in Section 2.7.

All entities in this system — `Subject`, `CommissionPolicy`, `Tutor`, `Credential`, `TutorSubjectTag`, `ParentAccount`, `Student`, `Booking`, `Session`, `Settlement`, and `RefundCase` — are mutable and therefore carry all four fields (`id`, `created_at`, `updated_at`, `version`). Any operation that changes a resource's stored state, including changes to computed fields such as a tutor's `lifetime_net_earnings_cents` or a parent's `held_balance_cents`, is a mutation that refreshes `updated_at` and increments `version`.

### 2.5. Resource Existence and Request Validation

A request body that is malformed, carries a field of the wrong type, or omits a required field is rejected with `ERR_VALIDATION`. When a request passes header and authorization checks, the system next confirms that every resource it references actually exists, checking path identifiers before request-body foreign keys. Each missing identifier produces a typed not-found error matched to the kind of resource: a missing tutor yields `ERR_TUTOR_NOT_FOUND`, a missing subject `ERR_SUBJECT_NOT_FOUND`, a missing credential `ERR_CREDENTIAL_NOT_FOUND`, a missing subject tag `ERR_SUBJECT_TAG_NOT_FOUND`, a missing parent account `ERR_PARENT_NOT_FOUND`, a missing student `ERR_STUDENT_NOT_FOUND`, a missing booking `ERR_BOOKING_NOT_FOUND`, a missing session `ERR_SESSION_NOT_FOUND`, a missing settlement `ERR_SETTLEMENT_NOT_FOUND`, and a missing refund case `ERR_REFUND_CASE_NOT_FOUND`. The same typed not-found errors apply to foreign keys supplied in a create payload — for example a booking whose `tutor_id`, `student_id`, `subject_id`, or `parent_account_id` names a row that does not exist, or a refund case whose `session_id` does not exist. Where a few endpoints additionally require the named tutor to already be verified, an operation that needs a `VERIFIED` tutor but finds one that is not is rejected with `ERR_TUTOR_NOT_VERIFIED`.

### 2.6. Cross-Entity Consistency and Cascades

Many operations in this marketplace mutate more than one entity. When a tutor's verification status changes, when a credential expires, or when a session settles, the effects ripple across several resources in a single logical step, and every touched resource has its `updated_at` refreshed and its `version` incremented. The system is immediately consistent: by the time a mutating request returns, every cascade it triggered has already been applied. The precise cascade rules — which parent transition a child transition forces, which tags get revoked when a tutor is suspended, how a settlement reversal moves money — are described inline with the workflows that own them in Section 3, because each cascade belongs to a specific business event.

### 2.7. Optimistic Concurrency Control

The refund negotiation is the one workflow where two parties write to the same resource in alternation, so it is guarded by optimistic concurrency control. A tutor's counter-offer and a parent's re-proposal both carry a mandatory `expected_refund_case_version` field holding the client's last observed `version` of the target `RefundCase`. Before applying the write, the server compares `expected_refund_case_version` against the case's current `version`. If they differ — because the other party has advanced the case since the client last read it — the write is rejected with `ERR_STALE_REFUND_CASE_VERSION` and HTTP status 412, and the client must re-read the case and re-derive its move against the current standing offers. The accept-counter and accept-offer operations likewise carry `expected_refund_case_version` and are rejected with the same error and status on a mismatch. No other endpoint in the system takes a version field; only these four refund-case operations are version-guarded.

### 2.8. Monetary Values, Rates, and Rounding

All money in the system is represented as an integer number of cents — there are no fractional-cent values and no floating-point money. Rates are expressed either as integer cents per hour (a tutor's hourly rate) or as **basis points** (one basis point is one hundredth of one percent, so 10000 basis points is 100%) for commission. Whenever a monetary amount is derived by multiplying a rate by a duration or a basis-point fraction, the result is rounded to a whole number of cents using the **round half up** convention: a fractional result of exactly one half rounds up to the next cent. Rounding is applied at each named step of a calculation, never deferred to the end of a multi-step computation. The reliability score is the sole non-cent quantity and is carried to one decimal place, also rounded half up.

### 2.9. Ledger Conservation

Three balances track money for each party, and they must remain internally consistent at all times. For each `ParentAccount`, the prepaid `wallet_balance_cents` is always the sum of `available_balance_cents` and `held_balance_cents`; `available_balance_cents` is `wallet_balance_cents` minus `held_balance_cents` and is never negative; and `held_balance_cents` is the sum of `hold_amount_cents` across that parent's bookings in `SCHEDULED`, `RESCHEDULE_REQUESTED`, or `DELIVERED` status. For each `Tutor`, `payout_balance_cents` is the withdrawable balance and is never negative; when a refund reversal exceeds the available balance, the shortfall is recorded as `clawback_owed_cents` rather than driving the balance below zero. The platform's commission is retained by the platform and is never refunded back to the tutor. Every booking hold, settlement debit, payout credit, and refund reversal moves money between these balances such that no cent is created or destroyed.

## 3. Business Logic & Workflows

### 3.1. Platform Configuration: Subjects and Commission Policy

Before any tutoring can happen, a `PlatformAdmin` establishes the platform's catalogue and economics. A subject is created with a unique `code` (such as `MATH_ALGEBRA_2`), a human-readable `display_name`, and a `category` drawn from `STEM`, `LANGUAGE`, `HUMANITIES`, `TEST_PREP`, or `MUSIC`. A subject may be flagged with `requires_credential`; when this flag is true, a tutor must hold a verified credential for that subject before being tagged to it, and when omitted the flag defaults to false. Subjects are immutable configuration: once created, a subject's `status` is `ACTIVE` and stays `ACTIVE` for the life of the system.

The platform's economics live in a commission policy. A policy is created in `DRAFT` with a `name`, two parallel arrays, and several caps. The first array, `tier_breakpoints_cents`, lists lifetime-earnings breakpoints in ascending order of cents — for example a list beginning at zero followed by higher thresholds. The second array, `tier_rates_bps`, lists the commission rate in basis points for each corresponding tier; the two arrays run parallel, so the rate at a given index applies to the tier opened by the breakpoint at that same index. A separate `trial_commission_bps` overrides the tiered rate for trial sessions. The policy also sets `trial_max_billed_minutes`, the hard ceiling on billed minutes for any trial session (defaulting to 30), and `refund_window_hours`, the number of hours after a session ends during which a refund case may still be opened (defaulting to 168). A newly created policy has a null `activated_at` and a `status` of `DRAFT`. Activating a policy stamps `activated_at`, moves its `status` to `ACTIVE`, and supersedes whichever policy was previously `ACTIVE` by moving that prior policy's `status` to `SUPERSEDED`. At most one policy is `ACTIVE` at a time, and the active policy supplies the commission tiers, trial rate, trial cap, and refund window used throughout the rest of this document.

### 3.2. Tutor Onboarding and Credential Verification

A tutor registers with an `email`, a `full_name`, and a `base_hourly_rate_cents`, which is the tutor's default hourly rate in cents and must be at least 1000 and at most 50000. A freshly registered tutor begins life with a `verification_status` of `UNVERIFIED`. Several balances start empty and are maintained by the system thereafter: `lifetime_net_earnings_cents` (the running sum of the tutor's net earnings across settled settlements, which drives commission-tier selection), `payout_balance_cents`, `clawback_owed_cents`, the `reliability_score`, and `active_subject_count` (the number of the tutor's subject tags currently in `APPROVED` status). A derived flag, `is_payable`, is true exactly when the tutor's `verification_status` is `VERIFIED` and `clawback_owed_cents` is zero.

To become eligible to teach, a tutor submits credentials. Each `Credential` names the owning `tutor_id`, the `subject_id` it attests competence in, a `kind` drawn from `DEGREE`, `CERTIFICATION`, `TEACHING_LICENSE`, or `TRANSCRIPT`, and an opaque `document_ref` pointing at the uploaded document. A submitted credential begins in `SUBMITTED` status. A `TrustOfficer` then drives it through review. Beginning review on a credential that is in `SUBMITTED` advances it to `UNDER_REVIEW`, records the reviewing officer's identifier in `reviewed_by`, and — when the owning tutor is still `UNVERIFIED` — advances that tutor from `UNVERIFIED` to `PENDING_REVIEW`. A credential in any state other than the one its transition requires is rejected with `ERR_INVALID_STATE`.

From `UNDER_REVIEW`, the officer may verify or reject. Verifying advances the credential from `UNDER_REVIEW` to `VERIFIED`; the system then recomputes the owning tutor's eligibility, and if the tutor now holds at least one `VERIFIED` credential the tutor bubbles up from `PENDING_REVIEW` to `VERIFIED` (with `is_payable` recomputed), and any `PROPOSED` subject tag for that subject whose approval was waiting on a missing credential becomes eligible for approval. Rejecting advances the credential from `UNDER_REVIEW` to `REJECTED`, stores the supplied `rejection_reason`, and — if the tutor then holds zero `VERIFIED` credentials and has no other credential still `UNDER_REVIEW` — drops the tutor from `PENDING_REVIEW` to `REJECTED`. A verified credential may later be expired by the officer, advancing it from `VERIFIED` to `EXPIRED`; if the tutor is left with zero `VERIFIED` credentials as a result, the tutor falls from `VERIFIED` to `SUSPENDED` and every `APPROVED` subject tag whose subject requires a credential is revoked as a cascade. The states `VERIFIED`, `REJECTED`, and `EXPIRED` are terminal for a credential.

A `TrustOfficer` may also suspend or reinstate a tutor directly. Suspending a tutor whose `verification_status` is `VERIFIED` moves it to `SUSPENDED` and revokes every `APPROVED` subject tag the tutor holds as a cascade, blocking future bookings. Reinstating moves a tutor from `SUSPENDED` back to `VERIFIED`, but only when the tutor currently holds at least one `VERIFIED` credential; an attempt to reinstate a tutor that is not `SUSPENDED`, or that has no `VERIFIED` credential, is rejected with `ERR_TUTOR_NOT_REINSTATABLE`. Reinstatement recomputes `is_payable`. The tutor's machine also has system-driven transitions noted above: it enters `PENDING_REVIEW` when the first credential reaches `UNDER_REVIEW`, rises to `VERIFIED` once a credential is verified, falls to `REJECTED` when the last credential under review is rejected with none verified, and may reach `SUSPENDED` either by officer suspension or by the expiry of the last verified credential.

### 3.3. Subject Tagging and Effective Pricing

A tutor advertises which subjects they teach by proposing a subject tag. Proposing a tag names the owning `tutor_id`, the `subject_id`, and an optional `subject_rate_cents` — a per-subject hourly rate override in cents; when this override is left null, the tutor's `base_hourly_rate_cents` applies instead. A new tag begins in `PROPOSED` status. A `TrustOfficer` approves the tag, which requires three conditions to hold: the tag must currently be `PROPOSED`, the owning tutor's `verification_status` must be `VERIFIED`, and — if the subject carries `requires_credential` set to true — the tutor must hold a `VERIFIED` credential for that same subject. The first two failures surface as `ERR_INVALID_STATE` and the verification gap respectively; the credential gap, specifically, is rejected with `ERR_SUBJECT_REQUIRES_CREDENTIAL`. On approval the tag advances from `PROPOSED` to `APPROVED`, the system snapshots `effective_hourly_rate_cents` (taking `subject_rate_cents` when it is non-null and otherwise the tutor's `base_hourly_rate_cents` at approval time), and the tutor's `active_subject_count` is incremented.

A tag may be revoked from either active state. Revoking an `APPROVED` tag moves it to `REVOKED`, decrements the tutor's `active_subject_count`, and blocks future bookings on that tutor-and-subject pair while leaving any existing `SCHEDULED` bookings untouched. Revoking a tag that is still `PROPOSED` simply moves it to `REVOKED` with no count change. `REVOKED` is terminal. Revocation also occurs automatically as the cascade from a tutor suspension or, for credential-gated subjects, from the expiry of the tutor's last verifying credential.

### 3.4. Parent Accounts, Wallets, and Students

A parent registers a `ParentAccount` with an `email` and a `full_name`. The account opens `ACTIVE` (parent accounts have no freeze lifecycle in this version) with a `wallet_balance_cents` of zero. The wallet is funded by deposits, each of which adds the supplied `amount_cents` to `wallet_balance_cents`. The system maintains three derived balances on the account at all times per the ledger rules in Section 2.9: `wallet_balance_cents`, `held_balance_cents`, and `available_balance_cents`. A fourth derived field, `child_count`, counts the account's students whose `status` is not `ARCHIVED`.

Under an account, a parent registers one or more students. A `Student` carries the managing `parent_account_id`, a `display_name`, and a `grade_level` between 1 and 13, where 13 denotes an adult learner. A new student is `ACTIVE`, and registering one increments the parent's `child_count`. Archiving a student moves its `status` to `ARCHIVED` and decrements `child_count`; the states `ACTIVE` and `ARCHIVED` are the only two a student can hold.

### 3.5. Booking a Lesson

A parent books a lesson by supplying the `parent_account_id`, the `student_id` attending, the chosen `tutor_id`, the `subject_id`, a `scheduled_start` instant in UTC, and the `planned_minutes` of the lesson. Several conditions are checked when a booking is created, and several values are computed for it.

The subject must be one the tutor actually teaches: there must be an `APPROVED` subject tag for the chosen tutor and subject, and the tutor must be `VERIFIED`; otherwise the booking is rejected with `ERR_TUTOR_SUBJECT_NOT_APPROVED`. The `scheduled_start` must be strictly later than the current deterministic clock, and `planned_minutes` must be at least 15 and at most 240; a start that is not in the future or a duration outside that range is rejected with `ERR_BOOKING_TIME_INVALID`. The tutor's calendar must be free: the new booking's half-open interval, running from `scheduled_start` up to but not including `scheduled_start` plus `planned_minutes`, must not overlap the interval of any of that tutor's other non-cancelled bookings — this overlap test uses a zero-minute buffer, so two bookings that merely touch end-to-start do not conflict, and a true overlap is rejected with `ERR_TUTOR_TIME_CONFLICT`. The attending student's calendar is checked more conservatively with a fifteen-minute buffer: for an existing non-cancelled booking running over its own interval and the new booking running over its interval, the two conflict when the new booking starts before the existing booking's end plus fifteen minutes and the existing booking starts before the new booking's end plus fifteen minutes; such a clash is rejected with `ERR_STUDENT_TIME_CONFLICT`. Both calendar checks treat cancelled bookings as absent.

When these checks pass the booking is created in `SCHEDULED` status, and three computed fields are set. The `is_trial` flag is true exactly when this is the first non-cancelled booking for that student-and-tutor pair. The `quoted_rate_cents` captures the tutor's `effective_hourly_rate_cents` for the chosen subject at the moment of booking. The `hold_amount_cents` is the estimated charge placed against the parent's wallet: for a standard booking it is the `quoted_rate_cents` multiplied by `planned_minutes`, divided by 60, rounded half up to whole cents; for a trial booking it is the `quoted_rate_cents` multiplied by the smaller of `planned_minutes` and the policy's `trial_max_billed_minutes`, divided by 60, rounded half up. Before the booking is accepted, the parent's `available_balance_cents` must be at least the computed `hold_amount_cents`; if available funds cannot cover the hold, the booking is rejected with `ERR_INSUFFICIENT_WALLET_BALANCE`. On success the parent's `held_balance_cents` rises by the hold amount. The booking also carries a `reschedule_count`, beginning at zero.

### 3.6. Reschedules, Cancellations, and No-Shows

Before a lesson begins, a parent may request a reschedule. Requesting one is allowed only when the booking is `SCHEDULED`, when its `reschedule_count` is strictly less than 3, and when the current clock is still earlier than the booking's `scheduled_start`; the request supplies a `proposed_start` and moves the booking from `SCHEDULED` to `RESCHEDULE_REQUESTED`, incrementing `reschedule_count`. Once `reschedule_count` has reached 3, a further request is rejected with `ERR_RESCHEDULE_LIMIT_REACHED`. The tutor then confirms the reschedule, which supplies the `proposed_start`, moves the booking from `RESCHEDULE_REQUESTED` back to `SCHEDULED`, updates `scheduled_start` to the proposed instant, recomputes `hold_amount_cents`, and synchronizes the parent's wallet hold to the new amount. Because confirming a reschedule changes the lesson's time, the tutor-calendar and student-calendar conflict checks of Section 3.5 are re-applied at confirmation, and a clash is rejected with `ERR_TUTOR_TIME_CONFLICT` or `ERR_STUDENT_TIME_CONFLICT` respectively.

A parent may cancel a future booking. Cancellation is permitted while the booking is `SCHEDULED` or `RESCHEDULE_REQUESTED` and while the current clock is still earlier than `scheduled_start`; it moves the booking to `CANCELLED` and releases the full wallet hold as compensation, so the parent's `held_balance_cents` falls by `hold_amount_cents` with no debit to the wallet. The terminal states for a booking are `SETTLED`, `CANCELLED`, and `NO_SHOW`.

When the lesson time has arrived and the student fails to appear, the tutor marks the booking a no-show. Marking a no-show is allowed only when the booking is `SCHEDULED` and the current clock is at or past `scheduled_start`; it moves the booking to `NO_SHOW`, releases the parent's wallet hold, and applies an acute reliability penalty to the tutor (see Section 3.10).

### 3.7. Delivering and Confirming a Lesson

When the lesson time has arrived, the tutor reports delivery. Delivering is allowed only when the booking is `SCHEDULED`, when the current clock is at or past `scheduled_start`, and when the tutor's `verification_status` is `VERIFIED`. Delivery supplies the `actual_minutes` the lesson actually ran (at least 1 and at most 480), moves the booking from `SCHEDULED` to `DELIVERED`, and creates a `Session` that records its `booking_id`, copies the `tutor_id` from the booking, opens in `delivery_status` of `REPORTED` and `settlement_status` of `DELIVERED`, and computes its `billed_minutes`.

The billed minutes are derived as follows. Take the reported `actual_minutes`. Cap it at `planned_minutes` plus a fifteen-minute overtime grace — that is, billed minutes may not exceed the planned duration by more than fifteen minutes. If the booking is a trial, apply a second cap so that billed minutes additionally may not exceed the policy's `trial_max_billed_minutes`; the active cap is whichever of these limits is the smaller. Finally, floor the result at 1, so any delivered session bills at least one minute. For a non-trial booking only the overtime cap and the floor apply.

A reported session is then resolved by the parent in one of two ways. Confirming the delivery moves the session's `delivery_status` from `REPORTED` to `CONFIRMED` and triggers settlement: a `Settlement` is created, the booking advances from `DELIVERED` to `SETTLED`, the session's `settlement_status` becomes `SETTLED`, and the tutor's `lifetime_net_earnings_cents` and `reliability_score` are updated. As part of settlement the parent's wallet hold is released and the wallet is debited by the settlement's `gross_amount_cents`, and the tutor's `payout_balance_cents` is credited by the settlement's `tutor_net_cents`. Disputing the delivery instead moves the session's `delivery_status` from `REPORTED` to `DISPUTED` while leaving `settlement_status` at `DELIVERED`; this opens a refund-eligible window without auto-settling the session. Both confirm and dispute require the session to currently be in `REPORTED`, and any other starting state is rejected with `ERR_INVALID_STATE`. The terminal delivery states for a session are `CONFIRMED` and `DISPUTED`.

### 3.8. Settlement and Commission

A settlement records the financial outcome of a confirmed session. It references the settling `session_id` one-to-one, copies the earning `tutor_id`, and computes four amounts in a fixed order. First the **gross**: `gross_amount_cents` is the session's `effective_hourly_rate_cents` — which is the booking's captured `quoted_rate_cents` — multiplied by the session's `billed_minutes`, divided by 60, rounded half up to whole cents. Second the **commission rate**, expressed in `commission_bps` and chosen by variant: for a standard (non-trial) settlement the rate is the tier rate selected from the active commission policy by the tutor's `lifetime_net_earnings_cents` as observed before this settlement's net is added; for a trial settlement the rate is the policy's `trial_commission_bps`, which overrides the tiered rate. Selecting the standard tier means choosing the largest index for which the breakpoint at that index in `tier_breakpoints_cents` is less than or equal to the tutor's pre-settlement `lifetime_net_earnings_cents`, and taking the parallel rate at that index in `tier_rates_bps`. It is essential that the tier read uses the lifetime earnings value from before this settlement's `tutor_net_cents` is added; reading it afterward would charge a tutor straddling a breakpoint the wrong rate. Third the **commission amount**: `commission_cents` is the `gross_amount_cents` multiplied by `commission_bps`, divided by 10000, rounded half up. Fourth the **net**: `tutor_net_cents` is `gross_amount_cents` minus `commission_cents`. Rounding is applied per settlement at each named step, never per minute.

A trial settlement therefore differs from a standard one in two compounding ways: its billed minutes were already capped at the trial ceiling, and its commission rate is the trial rate (typically higher than the tier rate), so for an identical billed duration the tutor's net on a trial is strictly lower than on a standard session. The settlement carries a `refunded_cents` field that accumulates amounts refunded against it and a `status` that begins at `SETTLED` and becomes `REVERSED` or `PARTIALLY_REVERSED` as refunds are applied (see Section 3.9).

### 3.9. Refund Negotiation and Arbitration

A parent who is dissatisfied with a session opens a refund case. Opening a case names the disputed `session_id`, the `claimed_amount_cents` the parent wants back, and an optional `supersedes_case_id` pointing at a prior rejected case this re-opening replaces. A case may be opened only while the current clock is at or before the session's end plus the policy's `refund_window_hours`, and only while the session's `settlement_status` is `SETTLED` or `DISPUTED`; opening it after the window has closed, or against a session in any other settlement state, is rejected with `ERR_REFUND_WINDOW_CLOSED`. The `claimed_amount_cents` must be greater than zero and no greater than the linked settlement's `gross_amount_cents`; a claim outside that range is rejected with `ERR_AMOUNT_OUT_OF_RANGE`. A new case opens in `PARENT_PROPOSED` status, copies the claimant `parent_account_id` from the session's booking and the responding `tutor_id` from the session, sets `parent_offer_cents` to the claimed amount, and moves the session's `settlement_status` to `REFUND_OPEN`. The case also tracks `tutor_offer_cents` (null until the first counter), `round_count` (the number of completed negotiation rounds, where a parent proposal followed by a tutor counter is one round), and `granted_amount_cents` (the final amount refunded, zero when denied).

The negotiation then loops. From `PARENT_PROPOSED`, the tutor may counter: a counter supplies `counter_amount_cents`, which must be less than or equal to the current `parent_offer_cents`, advances the case to `TUTOR_COUNTERED`, sets `tutor_offer_cents`, and — being one of the version-guarded operations — requires `expected_refund_case_version` to match and increments the case `version`. From `TUTOR_COUNTERED`, the parent may re-propose, accept the counter, or escalate. Re-proposing supplies `new_offer_cents`, which must be at least the current `tutor_offer_cents` and at most the current `parent_offer_cents` — the offers narrow monotonically toward each other — advances the case back to `PARENT_PROPOSED`, sets `parent_offer_cents` to the new offer, and increments `round_count`; it requires `expected_refund_case_version` to match and bumps the version, and it is blocked once `round_count` has reached 3. An offer that violates these monotone-narrowing bounds (a tutor counter above the parent offer, or a re-proposal outside the band between the tutor offer and the parent offer, or an arbitration award above the parent offer) is rejected with `ERR_OFFER_OUT_OF_BOUNDS`; a re-proposal attempted once the round cap is reached, or an escalation attempted before at least one round has completed, is rejected with `ERR_NEGOTIATION_ROUNDS_EXHAUSTED`.

The negotiation can settle by agreement in two symmetric ways. When the case is `TUTOR_COUNTERED`, the parent accepting the counter advances it to `AGREED` and sets `granted_amount_cents` to `tutor_offer_cents`. When the case is `PARENT_PROPOSED`, the tutor accepting the parent's standing offer advances it to `AGREED` and sets `granted_amount_cents` to `parent_offer_cents`. Both accept operations carry `expected_refund_case_version` and are version-guarded. From `AGREED`, the system automatically applies the settlement reversal (Section 3.9.1) and the case reaches the terminal `RESOLVED_REFUND`.

When the two sides cannot agree, the parent may escalate to arbitration. Escalation is allowed from either `PARENT_PROPOSED` or `TUTOR_COUNTERED` provided `round_count` is at least 1, and moves the case to `ARBITRATION`. An `Arbiter` then rules, supplying a `ruling` of either `REFUND` or `DENY`. A `ruling` of `REFUND` requires an `awarded_amount_cents` strictly greater than zero and no greater than the current `parent_offer_cents`; it sets `granted_amount_cents` to the awarded amount, applies the settlement reversal, advances the case to the terminal `RESOLVED_REFUND`, and applies an acute reliability penalty to the tutor that the negotiated path does not impose. A `ruling` of `DENY` sets `granted_amount_cents` to zero, returns the session's `settlement_status` to `SETTLED`, moves no money, and advances the case to the terminal `RESOLVED_DENY`. At any point while a case is `PARENT_PROPOSED` or `TUTOR_COUNTERED`, the parent may withdraw it, which returns the session's `settlement_status` to `SETTLED`, moves no money, and advances the case to the terminal `WITHDRAWN`. The terminal states for a refund case are `RESOLVED_REFUND`, `RESOLVED_DENY`, and `WITHDRAWN`.

The granted amount that a resolved-refund case carries depends on its path: when resolved by agreement it equals whichever standing offer the accepting party clicked and is bounded between `tutor_offer_cents` and `parent_offer_cents`; when resolved by arbitration it equals the Arbiter's `awarded_amount_cents`, independent of the standing offers except for the `parent_offer_cents` ceiling, and additionally carries the acute tutor penalty.

#### 3.9.1. Settlement Reversal

Whenever a refund case resolves with a refund — whether reached by agreement or by arbitration — the system reverses money against the linked settlement in a strictly pinned order, because the tutor's clawback depends on a payout balance that prior reversals may have already drawn down. Let the granted amount be the case's `granted_amount_cents`. First, the parent credit equals the full granted amount: the parent's wallet is always made whole by the granted amount. Second, the amount debited from the tutor's balance is the smaller of the granted amount and the tutor's current `payout_balance_cents`, read before any mutation in this reversal. Third, the clawback is the granted amount minus that debited amount — the remainder owed when the balance was short. The reversal then applies these results: the parent's `wallet_balance_cents` increases by the parent credit, the tutor's `payout_balance_cents` decreases by the debited amount, and the tutor's `clawback_owed_cents` increases by the clawback. Finally, the settlement's `refunded_cents` increases by the granted amount, and the settlement's `status` becomes `REVERSED` when `refunded_cents` has reached the full `gross_amount_cents` and `PARTIALLY_REVERSED` otherwise. In parallel, the linked session's `settlement_status` is moved to `REFUNDED` when the settlement has been fully reversed and to `PARTIALLY_REFUNDED` when only part of the gross has been refunded. Commission is never refunded to the tutor and the platform retains it; the platform funds the gap between the granted amount and the tutor debit only through the clawback, never by crediting commission back. The balance must be read before it is mutated and the clawback derived from that read; reversing the order would double-count.

### 3.10. Tutor Reliability Scoring

A tutor's `reliability_score` is a single number between 0 and 100 that blends chronic completion history against acute penalties, and it is recomputed in full on every trigger so that no incremental drift accumulates. It is recomputed when a session is confirmed (chronic), when a booking is marked a no-show (acute), and when a refund case is resolved in the parent's favor by an arbitrator (acute). The chronic component is 100 multiplied by the count of the tutor's confirmed sessions, divided by the greater of 1 and the sum of confirmed sessions plus no-show count — using the greater-of-1 divisor so a brand-new tutor with no history is not divided by zero. From that chronic figure the system subtracts an acute penalty equal to 8 times the tutor's no-show count plus 12 times the count of refund cases against the tutor that resolved as a refund through arbitration. The result is then clamped to lie between a floor of 0 and a ceiling of 100, and the final score is carried to one decimal place, rounded half up. Here the confirmed-session count is the number of the tutor's sessions whose `delivery_status` is `CONFIRMED`, the no-show count is the number of the tutor's bookings in `NO_SHOW`, and the arbitrated-refund count is the number of refund cases against the tutor that reached `RESOLVED_REFUND` by way of arbitration.

### 3.11. The Deterministic Clock

Every temporal check in the system — whether a booking's start is in the future, whether a cancellation is still permitted, whether a lesson time has arrived, whether a refund window is still open — is evaluated against a single server-held UTC clock rather than wall-clock time. A `PlatformAdmin` advances this clock by supplying a `to_iso8601` instant, which the server adopts as its current time and echoes back. This capability exists so that test harnesses can drive time-dependent workflows deterministically.

## 4. Endpoint Definitions

Operations that create a new, standalone resource return a `201 Created` status code; this includes registering a tutor or parent, creating a subject or commission policy, submitting a credential, proposing a subject tag, adding a student, creating a booking, opening a refund case, and reporting a lesson delivered (which creates a session). All other state-changing operations — activations, transitions, deposits, confirmations, negotiation moves, and the clock set — return `200 OK`, as do read operations. Validation across an endpoint is evaluated in a fixed priority order: header presence first, then role authorization, then resource ownership, then existence of path ids, then existence of body foreign keys, then state-machine applicability, then optimistic-concurrency version match, then the domain-specific business rules in their listed order.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set` | Set the deterministic UTC clock | PlatformAdmin |
| POST | `/subjects` | Create a subject | PlatformAdmin |
| GET | `/subjects/{id}` | Get a subject | PlatformAdmin, TrustOfficer, Tutor, ParentGuardian, Arbiter |
| POST | `/commission-policies` | Create a commission policy (DRAFT) | PlatformAdmin |
| POST | `/commission-policies/{id}/activate` | Activate a policy; supersedes the active one | PlatformAdmin |
| GET | `/commission-policies/{id}` | Get a commission policy | PlatformAdmin, TrustOfficer, Arbiter |
| POST | `/tutors` | Register a tutor | PlatformAdmin, Tutor |
| GET | `/tutors/{id}` | Get a tutor | PlatformAdmin, TrustOfficer, Tutor, ParentGuardian, Arbiter |
| POST | `/tutors/{id}/suspend` | Suspend a verified tutor | TrustOfficer |
| POST | `/tutors/{id}/reinstate` | Reinstate a suspended tutor | TrustOfficer |
| POST | `/credentials` | Submit a credential for a tutor and subject | Tutor |
| GET | `/credentials` | List/filter credentials | PlatformAdmin, TrustOfficer, Tutor |
| GET | `/credentials/{id}` | Get a credential | PlatformAdmin, TrustOfficer, Tutor |
| POST | `/credentials/{id}/start-review` | Begin reviewing a submitted credential | TrustOfficer |
| POST | `/credentials/{id}/verify` | Verify a credential under review | TrustOfficer |
| POST | `/credentials/{id}/reject` | Reject a credential under review | TrustOfficer |
| POST | `/credentials/{id}/expire` | Expire a verified credential | TrustOfficer |
| POST | `/subject-tags` | Propose a subject tag | Tutor |
| GET | `/subject-tags` | List/filter subject tags | PlatformAdmin, TrustOfficer, Tutor, ParentGuardian |
| GET | `/subject-tags/{id}` | Get a subject tag | PlatformAdmin, TrustOfficer, Tutor, ParentGuardian |
| POST | `/subject-tags/{id}/approve` | Approve a proposed subject tag | TrustOfficer |
| POST | `/subject-tags/{id}/revoke` | Revoke a subject tag | TrustOfficer |
| POST | `/parent-accounts` | Register a parent account | PlatformAdmin, ParentGuardian |
| GET | `/parent-accounts/{id}` | Get a parent account | PlatformAdmin, ParentGuardian, Arbiter |
| POST | `/parent-accounts/{id}/deposit` | Add prepaid funds to a parent wallet | PlatformAdmin, ParentGuardian |
| POST | `/parent-accounts/{id}/students` | Add a student under a parent account | ParentGuardian |
| GET | `/parent-accounts/{id}/students` | List a parent's students | PlatformAdmin, ParentGuardian |
| POST | `/students/{id}/archive` | Archive a student | ParentGuardian |
| POST | `/bookings` | Create a booking; holds estimated charge | ParentGuardian |
| GET | `/bookings` | List/filter bookings | PlatformAdmin, TrustOfficer, Tutor, ParentGuardian, Arbiter |
| GET | `/bookings/{id}` | Get a booking | PlatformAdmin, TrustOfficer, Tutor, ParentGuardian, Arbiter |
| POST | `/bookings/{id}/request-reschedule` | Parent requests a reschedule | ParentGuardian |
| POST | `/bookings/{id}/confirm-reschedule` | Tutor confirms reschedule; re-holds | Tutor |
| POST | `/bookings/{id}/cancel` | Parent cancels a future booking | ParentGuardian |
| POST | `/bookings/{id}/deliver` | Tutor reports the lesson delivered; creates Session | Tutor |
| POST | `/bookings/{id}/mark-no-show` | Tutor marks the student a no-show | Tutor |
| GET | `/sessions` | List/filter sessions | PlatformAdmin, TrustOfficer, Tutor, ParentGuardian, Arbiter |
| GET | `/sessions/{id}` | Get a session | PlatformAdmin, TrustOfficer, Tutor, ParentGuardian, Arbiter |
| POST | `/sessions/{id}/confirm` | Parent confirms delivery; settles the session | ParentGuardian |
| POST | `/sessions/{id}/dispute` | Parent disputes the reported session | ParentGuardian |
| GET | `/settlements` | List/filter settlements | PlatformAdmin, TrustOfficer, Tutor, Arbiter |
| GET | `/settlements/{id}` | Get a settlement | PlatformAdmin, TrustOfficer, Tutor, Arbiter |
| POST | `/refund-cases` | Open a refund case against a session | ParentGuardian |
| GET | `/refund-cases` | List/filter refund cases | PlatformAdmin, TrustOfficer, Tutor, ParentGuardian, Arbiter |
| GET | `/refund-cases/{id}` | Get a refund case | PlatformAdmin, TrustOfficer, Tutor, ParentGuardian, Arbiter |
| POST | `/refund-cases/{id}/counter` | Tutor counters the standing offer (OCC-guarded) | Tutor |
| POST | `/refund-cases/{id}/repropose` | Parent re-proposes a narrower offer (OCC-guarded) | ParentGuardian |
| POST | `/refund-cases/{id}/accept-counter` | Parent accepts the tutor's counter (OCC-guarded) | ParentGuardian |
| POST | `/refund-cases/{id}/accept-offer` | Tutor accepts the parent's offer (OCC-guarded) | Tutor |
| POST | `/refund-cases/{id}/escalate` | Parent escalates the case to arbitration | ParentGuardian |
| POST | `/refund-cases/{id}/arbitrate` | Arbiter rules on a case in arbitration | Arbiter |
| POST | `/refund-cases/{id}/withdraw` | Parent withdraws the refund case | ParentGuardian |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_VALIDATION | 400 |
| ERR_UNAUTHORIZED | 403 |
| ERR_NOT_RESOURCE_OWNER | 403 |
| ERR_TUTOR_NOT_FOUND | 404 |
| ERR_SUBJECT_NOT_FOUND | 404 |
| ERR_CREDENTIAL_NOT_FOUND | 404 |
| ERR_SUBJECT_TAG_NOT_FOUND | 404 |
| ERR_PARENT_NOT_FOUND | 404 |
| ERR_STUDENT_NOT_FOUND | 404 |
| ERR_BOOKING_NOT_FOUND | 404 |
| ERR_SESSION_NOT_FOUND | 404 |
| ERR_SETTLEMENT_NOT_FOUND | 404 |
| ERR_REFUND_CASE_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_TUTOR_NOT_REINSTATABLE | 409 |
| ERR_STALE_REFUND_CASE_VERSION | 412 |
| ERR_SUBJECT_REQUIRES_CREDENTIAL | 409 |
| ERR_TUTOR_NOT_VERIFIED | 409 |
| ERR_TUTOR_SUBJECT_NOT_APPROVED | 409 |
| ERR_BOOKING_TIME_INVALID | 422 |
| ERR_TUTOR_TIME_CONFLICT | 409 |
| ERR_STUDENT_TIME_CONFLICT | 409 |
| ERR_REFUND_WINDOW_CLOSED | 409 |
| ERR_OFFER_OUT_OF_BOUNDS | 422 |
| ERR_NEGOTIATION_ROUNDS_EXHAUSTED | 409 |
| ERR_AMOUNT_OUT_OF_RANGE | 422 |
| ERR_RESCHEDULE_LIMIT_REACHED | 409 |
| ERR_INSUFFICIENT_WALLET_BALANCE | 402 |
