# Online Course Creator API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Online Course Creator Platform API, a backend in the spirit of Teachable and Kajabi that lets independent instructors turn expertise into a sellable, self-service learning product. A creator builds a course, arranges its curriculum into ordered lessons, prices it under one or more commercial models, promotes it through discount coupons and affiliate partners, and then earns revenue as students enroll and pay. The platform sits in the middle of every one of those money flows: it charges students, withholds a platform fee, pays affiliate commissions, holds creator earnings through a refund window, and finally releases settled earnings to the creator as payouts.

The hard part of this domain is that a single learner action ripples through several ledgers at once, and the same underlying quantity is reported two ways — a provisional, forward-looking figure for dashboards and a final, conserved figure for accounting. Paying an invoice both activates a student's access and moves money into the creator's earnings; refunding that same invoice must cleanly reverse every one of those effects, revoke the student's access and certificate, and claw back the affiliate's commission, all without leaving a cent of drift. Because several of these figures depend on the passage of time — coupon validity windows, drip-release of lessons, refund eligibility, and revenue recognition after the refund window closes — the platform runs on an explicit logical clock rather than wall-clock time, so that these time-dependent behaviors are deterministic and testable.

This specification defines the entities, their state machines, the pricing and ledger calculations, the validation rules and their precedence, and the full REST surface. It is written for the engineer implementing the service and is the sole authority on behavior.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contracts, envelopes, and cross-cutting principles that govern every endpoint. Domain workflows that combine these rules are described in Section 3.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. If either header is missing or malformed, the request is rejected with `ERR_MISSING_AUTH_HEADER`. The platform recognizes exactly three roles, spelled precisely as `PlatformAdmin`, `Creator`, and `Student`; a value in `X-User-Role` that is not one of these three exact spellings is treated as a malformed header and rejected with `ERR_MISSING_AUTH_HEADER`. When a syntactically valid request names a role that is not permitted to perform the requested operation, the platform responds with `ERR_UNAUTHORIZED`.

The three roles have different relationships to the identity in `X-User-ID`:

- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The platform may accept it but does not compare it to any entity's `id`; a `PlatformAdmin` is a trusted operator who onboards creators and students, advances payouts, may pay or refund any invoice, and controls the logical clock.
- When `X-User-Role` is `Creator`, `X-User-ID` is the `id` of the acting `Creator`. Ownership checks on any resource that ultimately references a creator — a `Course` (through its `creator_id`), and by extension that course's lessons, price plans, coupons, affiliates, enrollments, and invoices, plus the creator's own payouts — compare the owning creator to `X-User-ID`.
- When `X-User-Role` is `Student`, `X-User-ID` is the `id` of the acting `Student`. Ownership checks on an `Enrollment` compare its `student_id` to `X-User-ID`.

When an authenticated user acts on a resource they do not own — a creator manipulating another creator's course, or a student progressing another student's enrollment — the request is rejected with `ERR_NOT_OWNER`.

**Order of validation.** When several failures could apply to one request, the platform reports them in a fixed precedence so that behavior is deterministic. The order is: (1) authentication headers present and well-formed, else `ERR_MISSING_AUTH_HEADER`; (2) the request body and query are well-formed with required fields present and enums and types valid, else `ERR_INVALID_REQUEST`; (3) the role is permitted for the operation, else `ERR_UNAUTHORIZED`; (4) every id named in the path exists, checked left-to-right, else that entity's not-found error; (5) the acting user owns the target resource, else `ERR_NOT_OWNER`; (6) the target resource is in a state that admits the requested transition, else the relevant invalid-state error; (7) cross-referenced resources belong together; (8) cross-entity status gates hold; (9) time-window gates hold; (10) interval-overlap and uniqueness gates hold; (11) quota and fiscal gates hold; and finally (12) the optimistic-concurrency check for payout creation. Earlier checks always mask later ones.

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

List endpoints are paginated through two query parameters. The `limit` parameter bounds how many items are returned; it defaults to 10, has a minimum of 1, and a maximum of 100 — a supplied `limit` below 1 or above 100 is clamped to the nearest bound rather than rejected. The `offset` parameter is the number of leading items to skip and defaults to 0; a negative `offset` is clamped to 0. A `limit` or `offset` that is present but not integer-valued is rejected with `ERR_INVALID_REQUEST`. Unless a specific endpoint states otherwise, list results are ordered by their `created_at` timestamp in ascending order, with ties broken by ascending order of creation (the sequence in which the resources were created). Every list response reports `limit`, `offset`, `total_count`, and `has_more` in the envelope's `meta` object, where `total_count` is the size of the full filtered set and `has_more` indicates whether items remain beyond the returned page.

### 2.4. Common Resource Properties and Versioning

Every resource carries a server-minted `id`, a string in UUID form used purely for identity — it never encodes a type prefix. Every resource also carries `created_at`, an ISO 8601 UTC timestamp with three fractional digits recorded when the resource is first created.

Most resources additionally carry `updated_at` (an ISO 8601 UTC timestamp refreshed on every mutation) and `version` (an integer that begins at 1 and increases by one each time the resource is mutated). A resource's derived analytics (creator ledger figures, course counts and revenue, affiliate commissions, enrollment progress, and the like) are not stored but computed live at read time from current store state and the logical clock; recomputing them does not by itself refresh `updated_at` or advance `version`. Only a direct mutation of a resource's own persisted fields refreshes its `updated_at` and advances its `version` — and even then the `Creator` is a special case whose `version` advances solely on payout activity (Section 2.10). The one exception is `QuizAttempt`: a quiz attempt is an immutable event record that carries only `id` and `created_at` — it has neither `updated_at` nor `version`.

### 2.5. The Logical Clock and Time-Window Semantics

The platform reads time from a logical clock, never from wall-clock time. At startup the clock reads exactly `2026-03-01T00:00:00Z`, and it holds that value until an operator explicitly moves it; it never silently falls back to real time. A `PlatformAdmin` advances the clock by supplying a target instant, `to_iso8601`. Because so many computed fields depend on elapsed time, moving the clock recomputes every window-dependent quantity: which invoices still sit inside their refund window, which lessons have dripped open, whether coupons are currently valid, and how creator earnings split between pending and settled.

Three time windows recur throughout the domain, and each uses a specific boundary convention. A coupon is valid when the current clock time is at or after its `starts_at` and at or before its `expires_at` — both endpoints inclusive. An invoice remains refundable while the current clock time is at or before its `paid_at` plus the course's `refund_window_days` (measured in whole days) — the final instant of that window is still eligible. A lesson remains drip-locked until the current clock time reaches at least the enrollment's `activated_at` plus the lesson's `drip_offset_days`; before that moment the lesson cannot be completed.

### 2.6. Monetary Precision and Rounding

All money is stored and returned as integer cents; there are no fractional cents and no floating-point representation. Where a calculation would produce a fraction, the direction of rounding is pinned per rule and stated where that rule is described: percentage discounts and the platform fee and affiliate commission all round down (floor); payment-plan installments round up (ceil) for every installment except the last, which absorbs the exact remainder so the installments sum to the discounted total with no drift. Progress percentage is likewise an integer, floored.

### 2.7. The Creator Earnings Ledger

Each `Creator` exposes a live earnings ledger recomputed whenever an invoice is paid or refunded, whenever a payout changes status, and whenever the clock moves. It is composed of several conserved quantities, all in integer cents.

`lifetime_gross_cents` is the sum of `amount_cents` over every one of the creator's invoices currently in `PAID` status (that is, paid and not since refunded). `lifetime_refunded_cents` is the sum of `amount_cents` over every invoice that has moved to `REFUNDED`. `lifetime_creator_net_cents` is the conserved net-earnings quantity: the sum of `creator_net_cents` over invoices whose status is `PAID`; when an invoice is refunded it leaves `PAID`, so its net contribution drops out. This gives the ledger invariant the platform must preserve — `lifetime_creator_net_cents` always equals the running sum of `creator_net_cents` across the creator's `PAID` invoices, so that a payment followed by a full refund of the same invoice returns the figure exactly to its pre-payment value with zero drift.

Net earnings are further split by the refund window. `pending_net_cents` sums `creator_net_cents` over the creator's `PAID` invoices that are still inside their refund window (current clock at or before `paid_at` plus the course's `refund_window_days`). `settled_net_cents` sums `creator_net_cents` over the creator's `PAID` invoices that have passed their refund window (current clock strictly after `paid_at` plus `refund_window_days`). Only settled earnings are eligible to be paid out.

Payouts consume the settled pool in two stages. `earnings_reserved_cents` is the sum of `amount_cents` over the creator's payouts in `REQUESTED` or `PROCESSING` status; `earnings_paid_cents` is the sum of `amount_cents` over payouts in `PAID` status. From these, `available_for_payout_cents` is `settled_net_cents` minus `earnings_paid_cents` minus `earnings_reserved_cents`, floored at zero so it is never negative.

### 2.8. Cascading State Consistency and the Two Enrollment Axes

An `Enrollment` tracks two independent status axes at once. The **access axis**, `access_status`, governs what the learner can do and moves through `LOCKED`, `ACTIVE`, `COMPLETED`, and `REVOKED`. The **billing axis**, `billing_status`, governs the commercial relationship and moves through `PENDING`, `CURRENT`, `CANCELLED`, and `REFUNDED`. The two axes advance on their own triggers but are coupled at key moments — paying the initial invoice advances both, and a refund or cancellation drives both to their terminal reversal states together.

Because one operation can touch several entities, the platform performs every dependent mutation as part of the same request. When paying an initial invoice activates an enrollment, when refunding it revokes access and reverses earnings, or when a payout settles and adjusts the creator's reserved and paid pools, each affected resource independently reflects the change. Resources whose own persisted state changes — the enrollment's coupled statuses, the invoice being paid or refunded, a payout's status — have their `updated_at` refreshed and `version` advanced; resources whose only change is a live-computed figure (the creator's ledger, a course's revenue and counts, an affiliate's commissions) are recomputed on read and are not themselves re-versioned by that recomputation. The detailed cascades are described in Section 3, but the governing principle is that no derived count, ledger figure, or coupled status is ever left stale after the operation that should have changed it.

### 2.9. Nested Resource Retrieval and Path Validation

Several endpoints address a sub-resource beneath a parent — a creator's payouts, an enrollment's invoices, an enrollment's completed lessons or quiz attempts. For any path bearing more than one identifier, the platform validates the identifiers strictly left to right and rejects the request at the first one that does not resolve, returning that entity's own not-found error (`ERR_CREATOR_NOT_FOUND`, `ERR_STUDENT_NOT_FOUND`, `ERR_COURSE_NOT_FOUND`, `ERR_LESSON_NOT_FOUND`, `ERR_PRICE_PLAN_NOT_FOUND`, `ERR_COUPON_NOT_FOUND`, `ERR_AFFILIATE_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_PAYOUT_NOT_FOUND`, or `ERR_QUIZ_ATTEMPT_NOT_FOUND` as appropriate). A request that names a payout under a nonexistent creator fails as a missing creator before the payout is ever considered.

### 2.10. Optimistic Concurrency Control for Payout Creation

Requesting a payout is the one write guarded by optimistic concurrency, because a payout draws down the creator's available balance and two independent draws must not both act on the same stale view. A payout-request must carry `expected_creator_version` holding the client's last observed `version` of the target `Creator`. If that value does not equal the creator's current `version`, the request is rejected with `ERR_STALE_CREATOR_VERSION` at HTTP 412, and no payout is created. The creator's `version` advances every time a payout is created and every time a payout changes status, so once any earlier payout activity has moved the version past what the client last read, the current request is refused as operating on a stale balance. No other endpoint takes a version field or performs this check.

## 3. Business Logic & Workflows

### 3.1. Onboarding Creators and Students

The platform operator seeds the two human actor types. A `PlatformAdmin` onboards a creator by supplying an `email` (which serves as the unique creator login) and a public `display_name`; the new `Creator` begins in `ACTIVE` status with every ledger figure at zero. The same operator registers a learner by supplying the student's `email` and `full_name`, producing a `Student` that carries only identity. A `PlatformAdmin` may later suspend or reactivate a creator, moving `status` between `ACTIVE` and `SUSPENDED`; this refreshes the creator's `updated_at` but does not advance its `version` (which tracks only payout activity, per Section 2.10). A suspended creator cannot request payouts. A creator resource, when read, exposes its `version` alongside the full earnings ledger described in Section 2.7.

### 3.2. Building the Course and the Publishing Lifecycle

A `Creator` creates a course by naming the owning `creator_id` and a `title`, and may set the refund policy and community and email touchpoints at creation: `refund_window_days` (whole days of refund eligibility measured from payment, at least zero, defaulting to 14), `community_enabled` (whether subscription members receive community access, defaulting to false), and `welcome_email_subject` (the subject line conceptually emailed to a student when their enrollment activates, defaulting to "Welcome!"). A new `Course` begins in `DRAFT`.

Curriculum is assembled from lessons. A creator adds a `Lesson` to one of their courses by naming the owning `course_id`, a `title`, and a 1-based `position` in the curriculum (at least 1). A lesson may set `is_published` (whether it counts toward the curriculum and toward progress, defaulting to true), `drip_offset_days` (whole days after enrollment activation before the lesson unlocks, defaulting to 0 and never negative), `is_quiz_required` (whether a passing quiz attempt is needed for mastery, defaulting to false), and `quiz_passing_score` (the inclusive 0-to-100 score threshold to pass this lesson's quiz, defaulting to 70). Adding a lesson recomputes the parent course's `published_lesson_count` — the number of its lessons with `is_published` true — and its `required_quiz_lesson_count` — the number of its published lessons whose `is_quiz_required` is true.

The course status field, `status`, is cyclic. From `DRAFT` a creator publishes to `PUBLISHED`, but only when the course has at least one published lesson (`published_lesson_count` is one or more) and at least one price plan in `ACTIVE` status; if either condition fails the transition is rejected with `ERR_COURSE_INVALID_STATUS_TRANSITION`. A published course may be moved to `UNPUBLISHED`, which blocks new enrollments while leaving existing enrollments untouched, and an unpublished course may be republished back to `PUBLISHED` under the same two preconditions as the first publish. From `DRAFT`, `PUBLISHED`, or `UNPUBLISHED` a creator may move the course to `ARCHIVED`, after which the course is immutable and accepts no new enrollments; `ARCHIVED` is terminal, and any attempt to transition out of it is likewise `ERR_COURSE_INVALID_STATUS_TRANSITION`. When a set-status request names a value outside the course's status enum, it is rejected with `ERR_INVALID_STATUS_VALUE`. Reading a course also returns its live analytics: `enrollment_count`, `completion_count`, `gross_revenue_cents`, and `net_settled_revenue_cents`, described below.

### 3.3. Pricing, Coupons, and Affiliates

A course is sold through one or more price plans. A creator creates a `PricePlan` against a `course_id` by choosing a `plan_type` — `ONE_TIME`, `SUBSCRIPTION`, or `PAYMENT_PLAN` — and an `amount_cents` (at least 1). For `ONE_TIME` and `PAYMENT_PLAN`, `amount_cents` is the full list price total; for `SUBSCRIPTION` it is the per-cycle amount. A subscription plan sets `billing_interval_days` (the cycle length in days; null for other types), and a payment plan sets `num_installments` (the installment count, which must be at least 2 for a payment plan; null otherwise). A plan may set `grants_community` (whether purchasing it grants community access, defaulting to false). A price plan opens in `ACTIVE` status and can be archived to `ARCHIVED`; an archived plan cannot be used for new enrollments.

A creator issues discounts through coupons. A `Coupon` is scoped to a `course_id` and carries a redemption `code`, a `discount_type` of `PERCENT` or `FIXED`, a `discount_value` (at least 1; for `PERCENT` this is a 1-to-100 percentage, for `FIXED` it is cents off), an optional `min_purchase_cents` (the coupon applies only when the list price is at least this figure; defaults to 0 and never negative), a `max_redemptions` cap (at least 1), and an inclusive validity window bounded by `starts_at` and `expires_at`. A coupon opens in `ACTIVE` status and may be disabled to `DISABLED`. Two active coupons that share the same `code` on the same course may not have overlapping validity windows — the windows are treated as closed intervals, and a create whose window overlaps an existing active same-code coupon is rejected with `ERR_COUPON_WINDOW_OVERLAP`. The coupon reports a conserved `redeemed_count`: the number of enrollments that used it whose `billing_status` is neither `CANCELLED` nor `REFUNDED`.

A creator recruits partners through affiliates. An `Affiliate` is scoped to a `creator_id` and carries a referral `code` (unique per creator) and a `commission_pct` (a 0-to-100 percentage of each paid invoice attributed to it). An affiliate opens in `ACTIVE` status and can be suspended or reactivated between `ACTIVE` and `SUSPENDED`. Reading an affiliate exposes its running commission analytics: `commission_pending_cents`, `commission_clawed_back_cents`, and `referred_revenue_cents`, defined in Section 3.5 and 3.7.

### 3.4. Checkout: Enrollment Creation and the Charge Calculation

A `Student` enrolls by checking out. The request names the enrolling `student_id`, the `course_id`, the chosen `price_plan_id`, and optionally a `coupon_code` and an `affiliate_code`. Checkout resolves the codes: `coupon_code` resolves to `coupon_id` and `affiliate_code` resolves to `affiliate_id`, each stored on the enrollment and left null when not supplied; an unresolvable coupon code is `ERR_COUPON_NOT_FOUND` and an unresolvable affiliate code is `ERR_AFFILIATE_NOT_FOUND`.

Checkout is gated by a sequence of cross-entity checks. The chosen plan must belong to the course (`ERR_PRICE_PLAN_COURSE_MISMATCH`), any coupon must belong to the course (`ERR_COUPON_COURSE_MISMATCH`), and any affiliate must belong to the course's creator, comparing the affiliate's `creator_id` to the course's `creator_id` (`ERR_AFFILIATE_CREATOR_MISMATCH`). The course must be in `PUBLISHED` status, else `ERR_COURSE_NOT_PUBLISHED`; the price plan must be `ACTIVE`, else `ERR_PRICE_PLAN_INACTIVE`; a coupon in `DISABLED` status is rejected with `ERR_COUPON_INACTIVE`; and an affiliate in `SUSPENDED` status cannot be attributed, giving `ERR_AFFILIATE_INACTIVE`. A student may hold only one non-terminal enrollment per course — if the student already has an enrollment in this course whose billing is not `CANCELLED` or `REFUNDED`, checkout is rejected with `ERR_DUPLICATE_ENROLLMENT`.

The charge is computed at the current clock. First the list price, stored as `list_price_cents`, is taken from the plan's `amount_cents`: for `ONE_TIME` it is the amount, for `PAYMENT_PLAN` it is the amount as the total across all installments, and for `SUBSCRIPTION` it is the amount of the first cycle. A coupon reduces the charge only if every one of the following holds: a coupon was supplied, its status is `ACTIVE`, the current clock time falls within its inclusive `starts_at`-to-`expires_at` window, its `redeemed_count` is strictly less than its `max_redemptions`, and the list price is at least its `min_purchase_cents`. Two of these, when violated at checkout, surface as their own errors: a current clock outside the coupon window is `ERR_COUPON_WINDOW_EXPIRED`, a list price below the minimum is `ERR_COUPON_MIN_PURCHASE_NOT_MET`, and an already-exhausted coupon (redeemed count at or above the maximum) is `ERR_COUPON_REDEMPTION_LIMIT`.

When the coupon is eligible, the `discount_cents` is computed by type: for a `PERCENT` coupon it is the list price multiplied by the discount value divided by 100, rounded down; for a `FIXED` coupon it is the smaller of the discount value and the list price (so a discount can never exceed the price). When no coupon applies, `discount_cents` is zero. The discounted total is the list price minus the discount.

From the discounted total the platform derives `initial_charge_cents`, the amount of the first invoice, and `scheduled_total_cents`, the amount the plan is scheduled to collect. For `ONE_TIME`, both the initial charge and the scheduled total equal the discounted total. For `SUBSCRIPTION`, the initial charge equals the discounted total (the first cycle), and the scheduled total is provisionally that same first-cycle discounted total, since the plan is open-ended; later cycles bill the full per-cycle `amount_cents` without the coupon. For `PAYMENT_PLAN`, the scheduled total equals the discounted total, and the initial charge equals the first installment.

Payment-plan installments split the discounted total across `num_installments` with the order pinned so the sum matches exactly. Each installment except the last is the discounted total divided by the installment count, rounded up; the last installment is the discounted total minus that rounded-up per-installment amount multiplied by one less than the installment count. The rounded-up installments therefore front-load any rounding, and the final installment absorbs the remainder so the installments add up to the discounted total precisely.

Checkout then creates the enrollment in `access_status` `LOCKED` and `billing_status` `PENDING` and lays down its invoices. For `ONE_TIME` and `SUBSCRIPTION`, a single invoice is created with `kind` `INITIAL`, status `PENDING`, and `amount_cents` equal to the initial charge. For `PAYMENT_PLAN`, all installment invoices are created at once: the invoice at `sequence_index` 1 has `kind` `INITIAL` with the first installment amount, and the invoices at sequence indices 2 through the installment count have `kind` `INSTALLMENT` with their respective installment amounts, all in `PENDING`. If a coupon was applied, the coupon's `redeemed_count` immediately counts this enrollment.

### 3.5. Paying Invoices, Fees, Commissions, and Subscription Cycles

An invoice is settled by paying it, an action available to the owning `Student` or to a `PlatformAdmin`. Payment is only possible while the invoice is `PENDING`, else `ERR_INVOICE_NOT_PAYABLE`, and the parent enrollment's course must not be `ARCHIVED`. On payment the invoice moves to `PAID`, its `paid_at` is stamped with the current clock, and three money figures are computed on the spot. The `platform_fee_cents` is the invoice's `amount_cents` multiplied by the platform fee percentage of 10 and divided by 100, rounded down. The `affiliate_commission_cents` is, when the enrollment has an attributed affiliate whose status is `ACTIVE`, the invoice's `amount_cents` multiplied by that affiliate's `commission_pct` divided by 100 and rounded down, and is zero otherwise. Commission is deliberately computed and floored per invoice and then summed across invoices — the affiliate's `commission_pending_cents` is the sum of those per-invoice floored commissions over the affiliate's attributed `PAID` invoices, which is not the same as flooring one commission on the summed amount. The affiliate's `referred_revenue_cents` is the sum of `amount_cents` over its attributed `PAID` (non-refunded) invoices. Finally the invoice's `creator_net_cents` is its `amount_cents` minus its platform fee minus its affiliate commission.

Paying the `INITIAL` invoice is the moment an enrollment comes alive: `access_status` moves `LOCKED → ACTIVE`, `billing_status` moves `PENDING → CURRENT`, and the enrollment's `activated_at` is set to the current clock so that drip offsets are measured from this instant. Paying any invoice recomputes the creator's earnings ledger (Section 2.7) and the affected course's revenue figures. A course reports `gross_revenue_cents` as the provisional variant — the sum of `amount_cents` over all `PAID` invoices belonging to its enrollments, counting every paid invoice including those still inside their refund window — and `net_settled_revenue_cents` as the final variant — the sum of `creator_net_cents` over its `PAID` invoices that have passed their refund window (current clock strictly after `paid_at` plus `refund_window_days`). The provisional figure uses pre-fee amounts and ignores the window; the final figure uses net-of-fee amounts and recognizes revenue only once the window has closed.

An enrollment also reports its two billing totals. The `scheduled_total_cents` is the forward-looking figure fixed at checkout, while `collected_total_cents` is the actuals — the sum of `amount_cents` over this enrollment's `PAID` invoices — which diverges from the scheduled figure whenever a payment plan is only partly paid.

Subscription courses bill again each cycle. A `Creator` or `PlatformAdmin` generates the next cycle invoice for an enrollment by supplying the cycle's `cycle_start` (inclusive coverage start) and `cycle_end` (exclusive coverage end). This creates a `CYCLE` invoice in `PENDING` status whose `amount_cents` is the plan's full per-cycle `amount_cents` (later cycles do not carry the initial coupon discount). The platform does not gate this operation on the plan's `plan_type`; it creates the `CYCLE` invoice for any enrollment regardless of plan type, always priced at that plan's `amount_cents`. Cycle invoices for one enrollment may not cover overlapping time: the coverage intervals are half-open, so back-to-back cycles that merely touch at an endpoint are allowed, but a genuine overlap with an existing non-refunded cycle invoice is rejected with `ERR_CYCLE_OVERLAP`. Cycle invoices carry `cycle_start` and `cycle_end`; initial and installment invoices leave both null. When an invoice is paid, its `sequence_index` and `kind` and the computed `platform_fee_cents`, `affiliate_commission_cents`, and `creator_net_cents` are all visible on the invoice, along with `refunded_at` once it is refunded.

### 3.6. Progress, Quizzes, Mastery, and Certification

Once an enrollment is `ACTIVE`, the learner works through the curriculum. A `Student` marks a lesson complete by naming its `lesson_id`. The lesson must belong to the enrollment's course, comparing the lesson's `course_id` to the enrollment's `course_id`, else `ERR_LESSON_COURSE_MISMATCH`; it must be published, else `ERR_LESSON_NOT_PUBLISHED`; the enrollment must be in a state that permits progress (an enrollment that is `LOCKED` or `REVOKED`, rather than `ACTIVE`, cannot progress and yields `ERR_ENROLLMENT_INVALID_STATE`); and the lesson must have dripped open — if the current clock is earlier than `activated_at` plus the lesson's `drip_offset_days`, it is still locked and the request is rejected with `ERR_LESSON_LOCKED`. Completing a lesson recomputes the enrollment's `completed_lesson_count` and its `raw_progress_pct`, the provisional progress variant, which is the completed published-lesson count divided by the course's `published_lesson_count`, multiplied by 100 and rounded down, and defined as zero when the course has no published lessons.

For required-quiz lessons the learner submits attempts. A `Student` submits a quiz attempt against a `lesson_id` with a `score` in the 0-to-100 range; the attempt records `passed` as true exactly when the score is at or above that lesson's `quiz_passing_score` (the boundary is inclusive). A quiz attempt may only be submitted for a lesson whose `is_quiz_required` is true, else `ERR_QUIZ_NOT_REQUIRED`, and the same course-match and published-lesson rules apply as for completion; the enrollment must also be `ACTIVE`, and any other access state (`LOCKED`, `COMPLETED`, or `REVOKED`) yields `ERR_ENROLLMENT_INVALID_STATE`. A quiz attempt is an immutable record carrying its `id`, `enrollment_id`, `lesson_id`, `score`, and computed `passed`.

Mastery is the final completion variant and the gate for the certificate. An enrollment's `is_mastery_complete` becomes true only when its completed lesson count equals the course's `published_lesson_count` and, in addition, every published lesson whose `is_quiz_required` is true has at least one quiz attempt for this enrollment with `passed` true. A learner can therefore reach 100 percent `raw_progress_pct` yet remain short of mastery if a required quiz is still unpassed. When completing a lesson makes mastery newly true, the enrollment's `access_status` moves `ACTIVE → COMPLETED`, a certificate is minted by setting `certificate_serial` and stamping `certificate_issued_at` with the current clock, and the course's `completion_count` is incremented. This mastery-driven transition — the `access_status` change, the certificate minting, and the `completion_count` increment — is evaluated only within the complete-lesson operation. Submitting a quiz attempt records the attempt (and `is_mastery_complete`, being a live-computed figure, may consequently read true) but never on its own advances `access_status`, mints a certificate, or increments `completion_count`, even when the passing attempt is what makes mastery newly true. The course's `completion_count` counts enrollments in `access_status` `COMPLETED`; its `enrollment_count` counts enrollments whose billing is neither `CANCELLED` nor `REFUNDED`.

An enrollment also reports `community_access`, which is true exactly when its access is `ACTIVE` or `COMPLETED` and the purchased price plan's `grants_community` is set and the course's `community_enabled` is set.

### 3.7. Cancellation, Refunds, and Cascading Reversal

Before any money changes hands, a `Student` may cancel an enrollment. Cancellation is permitted only while no invoice for the enrollment is in `PAID` status — it is a pre-payment escape hatch — and a cancel attempted after payment is rejected with `ERR_ENROLLMENT_INVALID_STATE`. Cancelling drives `billing_status` from `PENDING` or `CURRENT` to `CANCELLED`, drives `access_status` to `REVOKED`, voids every `PENDING` invoice on the enrollment to `VOID`, and — because the enrollment is now terminal — removes it from any coupon's `redeemed_count` as a compensating decrement.

After payment, reversal happens through refunds. A `Creator` (for their own invoices) or a `PlatformAdmin` refunds a `PAID` invoice. The invoice must actually be in `PAID` status, else `ERR_INVOICE_NOT_REFUNDABLE`, and the refund must fall inside the window — the current clock must be at or before `paid_at` plus the course's `refund_window_days`; a later refund is rejected with `ERR_REFUND_WINDOW_EXPIRED`. On refund the invoice moves `PAID → REFUNDED` and its `refunded_at` is stamped. The creator ledger reverses: because the invoice is no longer `PAID`, its `creator_net_cents` drops out of `lifetime_creator_net_cents`, and its `amount_cents` is added to `lifetime_refunded_cents`. The affiliate commission is clawed back: the invoice's `affiliate_commission_cents` moves out of the affiliate's `commission_pending_cents` and into its `commission_clawed_back_cents` (the running sum of commission on the affiliate's attributed `REFUNDED` invoices).

Refunding the `INITIAL` invoice cascades to the whole enrollment. The enrollment's `access_status` moves to `REVOKED` and its `billing_status` moves to `REFUNDED`. On revocation the certificate is cleared — both `certificate_serial` and `certificate_issued_at` are reset to null — and `completed_lesson_count` is reset to zero. Because the billing axis is now terminal, the enrollment also drops out of its coupon's `redeemed_count`. The net effect is that a payment followed by a full refund of the initial invoice returns every touched ledger figure to its pre-payment value, preserving the conservation invariant of Section 2.7.

### 3.8. Payouts and Settlement

A creator draws down settled earnings by requesting a payout. A `Creator` requests a payout against their own account by supplying the `amount_cents` to withdraw (at least 1) and `expected_creator_version` for the optimistic-concurrency check of Section 2.10. The creator must be `ACTIVE` — a request from a `SUSPENDED` creator is rejected with `ERR_CREATOR_SUSPENDED` — and the amount may not exceed the creator's `available_for_payout_cents`, else `ERR_INSUFFICIENT_BALANCE` at HTTP 402. A successful request creates a `Payout` in `REQUESTED` status, reserves its amount (so it now counts toward `earnings_reserved_cents` and reduces the available balance), and increments the creator's `version` by one.

A `PlatformAdmin` advances a payout through its lifecycle. From `REQUESTED` it moves to `PROCESSING`, where the amount stays reserved. From `PROCESSING` it may reach `PAID`, at which point the amount moves out of `earnings_reserved_cents` and into `earnings_paid_cents`. From `PROCESSING` it may instead move to `FAILED`, and from either `REQUESTED` or `PROCESSING` it may be `CANCELLED`; in both of those cases the reservation is released and the amount returns to `available_for_payout_cents`. `PAID`, `FAILED`, and `CANCELLED` are terminal. Each of these four status transitions — reaching `PAID`, `FAILED`, or `CANCELLED`, as well as the initial creation — increments the creator's `version` by one, which is precisely what makes a concurrent stale payout request fail the version check. A requested transition that is not legal from the payout's current status is rejected with `ERR_PAYOUT_INVALID_STATUS_TRANSITION`, and a set-status value outside the payout status enum is `ERR_INVALID_STATUS_VALUE`.

## 4. Endpoint Definitions

Endpoints that create a new, distinct resource return `201 Created`; endpoints that read a resource or drive a state transition or other modification return `200 OK`. All paths live at the root of the API.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/creators` | Onboard a creator | PlatformAdmin |
| GET | `/creators/{id}` | Get a creator with version and full earnings ledger | PlatformAdmin, Creator |
| POST | `/creators/{id}/set-status` | Suspend or reactivate a creator | PlatformAdmin |
| POST | `/students` | Register a student | PlatformAdmin |
| POST | `/courses` | Create a course (opens in DRAFT) | Creator |
| GET | `/courses/{id}` | Get a course with computed analytics and revenue | PlatformAdmin, Creator, Student |
| GET | `/courses` | List courses; filter by creator_id and status | PlatformAdmin, Creator, Student |
| POST | `/courses/{id}/set-status` | Publish, unpublish, republish, or archive a course | Creator |
| POST | `/lessons` | Add a curriculum lesson to a course | Creator |
| GET | `/lessons/{id}` | Get a lesson | PlatformAdmin, Creator, Student |
| GET | `/lessons` | List lessons; filter by course_id | PlatformAdmin, Creator, Student |
| POST | `/price-plans` | Create a pricing plan for a course | Creator |
| GET | `/price-plans/{id}` | Get a price plan | PlatformAdmin, Creator, Student |
| GET | `/price-plans` | List price plans; filter by course_id | PlatformAdmin, Creator, Student |
| POST | `/price-plans/{id}/set-status` | Archive a price plan | Creator |
| POST | `/coupons` | Create a coupon for a course | Creator |
| GET | `/coupons/{id}` | Get a coupon | PlatformAdmin, Creator |
| GET | `/coupons` | List coupons; filter by course_id | PlatformAdmin, Creator |
| POST | `/coupons/{id}/set-status` | Disable a coupon | Creator |
| POST | `/affiliates` | Create an affiliate under a creator | Creator |
| GET | `/affiliates/{id}` | Get an affiliate with commission analytics | PlatformAdmin, Creator |
| GET | `/affiliates` | List affiliates; filter by creator_id | PlatformAdmin, Creator |
| POST | `/affiliates/{id}/set-status` | Suspend or reactivate an affiliate | Creator |
| POST | `/enrollments` | Checkout: enroll a student via a price plan, with optional coupon and affiliate codes | Student |
| GET | `/enrollments/{id}` | Get an enrollment with progress, billing totals, and certificate | PlatformAdmin, Creator, Student |
| GET | `/enrollments` | List enrollments; filter by student_id, course_id, price_plan_id, coupon_id, affiliate_id, status (matching either the access or billing axis) | PlatformAdmin, Creator, Student |
| POST | `/enrollments/{id}/complete-lesson` | Mark a drip-unlocked published lesson complete | Student |
| POST | `/enrollments/{id}/cancel` | Cancel an enrollment before any payment | Student |
| POST | `/enrollments/{id}/quiz-attempts` | Submit a quiz attempt for a required-quiz lesson | Student |
| POST | `/enrollments/{id}/invoices` | Generate the next subscription cycle invoice | Creator, PlatformAdmin |
| GET | `/quiz-attempts/{id}` | Get a quiz attempt | PlatformAdmin, Creator, Student |
| GET | `/quiz-attempts` | List quiz attempts; filter by enrollment_id, lesson_id | PlatformAdmin, Creator, Student |
| GET | `/invoices/{id}` | Get an invoice with fee, commission, and net breakdown | PlatformAdmin, Creator, Student |
| GET | `/invoices` | List invoices; filter by enrollment_id | PlatformAdmin, Creator, Student |
| POST | `/invoices/{id}/pay` | Pay an invoice (simulated settlement) | Student, PlatformAdmin |
| POST | `/invoices/{id}/refund` | Refund a paid invoice within the refund window | Creator, PlatformAdmin |
| POST | `/creators/{id}/payouts` | Request a payout against available balance (OCC) | Creator |
| GET | `/payouts/{id}` | Get a payout | PlatformAdmin, Creator |
| GET | `/payouts` | List payouts; filter by creator_id | PlatformAdmin, Creator |
| POST | `/payouts/{id}/set-status` | Advance a payout to PROCESSING, PAID, FAILED, or CANCELLED | PlatformAdmin |
| POST | `/_clock/set_current_utc` | Set the server logical clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH_HEADER` | 400 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_OWNER` | 403 |
| `ERR_CREATOR_NOT_FOUND` | 404 |
| `ERR_STUDENT_NOT_FOUND` | 404 |
| `ERR_COURSE_NOT_FOUND` | 404 |
| `ERR_LESSON_NOT_FOUND` | 404 |
| `ERR_PRICE_PLAN_NOT_FOUND` | 404 |
| `ERR_COUPON_NOT_FOUND` | 404 |
| `ERR_AFFILIATE_NOT_FOUND` | 404 |
| `ERR_ENROLLMENT_NOT_FOUND` | 404 |
| `ERR_INVOICE_NOT_FOUND` | 404 |
| `ERR_PAYOUT_NOT_FOUND` | 404 |
| `ERR_QUIZ_ATTEMPT_NOT_FOUND` | 404 |
| `ERR_COURSE_INVALID_STATUS_TRANSITION` | 409 |
| `ERR_COURSE_NOT_PUBLISHED` | 409 |
| `ERR_PRICE_PLAN_INACTIVE` | 409 |
| `ERR_PRICE_PLAN_COURSE_MISMATCH` | 422 |
| `ERR_COUPON_COURSE_MISMATCH` | 422 |
| `ERR_COUPON_INACTIVE` | 409 |
| `ERR_COUPON_WINDOW_EXPIRED` | 422 |
| `ERR_COUPON_MIN_PURCHASE_NOT_MET` | 422 |
| `ERR_COUPON_REDEMPTION_LIMIT` | 409 |
| `ERR_COUPON_WINDOW_OVERLAP` | 409 |
| `ERR_AFFILIATE_CREATOR_MISMATCH` | 422 |
| `ERR_AFFILIATE_INACTIVE` | 409 |
| `ERR_ENROLLMENT_INVALID_STATE` | 409 |
| `ERR_DUPLICATE_ENROLLMENT` | 409 |
| `ERR_LESSON_COURSE_MISMATCH` | 422 |
| `ERR_LESSON_NOT_PUBLISHED` | 409 |
| `ERR_LESSON_LOCKED` | 409 |
| `ERR_QUIZ_NOT_REQUIRED` | 422 |
| `ERR_INVOICE_NOT_PAYABLE` | 409 |
| `ERR_INVOICE_NOT_REFUNDABLE` | 409 |
| `ERR_REFUND_WINDOW_EXPIRED` | 409 |
| `ERR_CYCLE_OVERLAP` | 409 |
| `ERR_CREATOR_SUSPENDED` | 403 |
| `ERR_INSUFFICIENT_BALANCE` | 402 |
| `ERR_PAYOUT_INVALID_STATUS_TRANSITION` | 409 |
| `ERR_INVALID_STATUS_VALUE` | 422 |
| `ERR_STALE_CREATOR_VERSION` | 412 |
