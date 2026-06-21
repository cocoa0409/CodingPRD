# Online Course Marketplace API — Product Requirements Document

## 1. Introduction

The Online Course Marketplace API powers a two-sided learning platform in the spirit of Udemy or Coursera, where independent instructors publish courses and learners enroll, study, and earn certificates. The platform's job is to keep two very different parties honest about the same set of facts at the same time: an instructor cares about how a course is priced, how many seats a coupon or bundle has moved, and how much money has cleared into a payable balance; a learner cares about whether a lesson has unlocked, whether a quiz attempt counted toward passing, and whether a purchase can still be refunded.

Most of the system's difficulty lives at the seams between those two concerns. A single enrollment is simultaneously a pricing event (list price, optional coupon discount, or a bundle's flat price split across member courses), a revenue event (a ledger credit that starts life provisional and only becomes payable once the refund window has closed), and a progress anchor (the moment from which drip-release and the refund deadline are measured). A refund unwinds all three at once. Completion forks away from refund and expiry into divergent terminal outcomes, each with its own side effects. This document specifies the catalog and curriculum model, enrollment and progress tracking, quiz assessment and certification, the instructor revenue-share ledger and payout flow, coupon and bundle pricing, the rating-and-review surface with its moderation controls, drip content release, and the continuing-education (CEU) credit award — as one coherent contract that an implementer can build against without guessing.

Because money and serialization are at stake, the platform models time explicitly through a controllable logical clock, settles balances through an append-style revenue ledger rather than mutating running totals in place, and guards two of its most dangerous writes — payout approval and bundle enrollment — with optimistic concurrency checks against the version of the entity whose balance or membership those writes consume.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that apply across every endpoint in the API. Domain workflows that weave these principles together are detailed in Section 3.

### 2.1. User and Role-Based Access Control

Every request to a protected endpoint must carry two HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which they act. When either header is missing, or `X-User-Role` is not one of the recognized role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The two registration endpoints — creating an instructor and creating a learner — are the only exceptions; they may be called without authentication.

The system recognizes exactly four roles, spelled precisely as follows: `Anonymous`, `Instructor`, `Learner`, and `PlatformAdmin`. Once a caller is authenticated, the system additionally checks that the declared role is permitted to perform the requested operation and, where ownership applies, that the caller owns the targeted resource; a failure of either check is rejected with `ERR_FORBIDDEN` (HTTP 403).

`Anonymous` is an opaque identity: when `X-User-Role` is `Anonymous`, `X-User-ID` is an opaque identifier not tied to any persisted entity, and the role exists only to let an unauthenticated visitor register themselves as an instructor or a learner. `Instructor` is an entity-backed identity: when `X-User-Role` is `Instructor`, `X-User-ID` is the `id` of the acting `Instructor`, and ownership checks on any resource that references an instructor (a course's `instructor_id`, a coupon's `instructor_id`, a bundle's `instructor_id`, a payout's `instructor_id`) compare that foreign key to `X-User-ID`. `Learner` is likewise entity-backed: when `X-User-Role` is `Learner`, `X-User-ID` is the `id` of the acting `Learner`, and ownership checks on any resource that references a learner (an enrollment's `learner_id`, and by extension the enrollment behind a lesson-completion, a refund, or a review) compare that foreign key to `X-User-ID`. `PlatformAdmin` is an opaque operational identity: when `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the platform admin moderates reviews, approves or rejects payouts, and drives the clock, but the server does not compare its `X-User-ID` to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it accepts a minimum of 1 and a maximum of 100. The `offset` parameter is the number of leading items to skip and defaults to 0.

Unless an endpoint states otherwise, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Every list response carries the pagination bookkeeping inside the `meta` object: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Most resources in the system share a standard set of system-managed fields. Every resource carries an `id` — a server-minted UUID with no type prefix, used for identity only — and a `created_at` timestamp, formatted as ISO 8601 UTC with three fractional digits (for example, `2025-05-24T10:30:00.123Z`), recording when the resource was first created.

Resources that are mutable additionally carry an `updated_at` timestamp and an integer `version`. The `updated_at` field is refreshed to the current instant on every mutation, including mutations caused by cascades from a related resource. The `version` field starts at 1 when the resource is created and increases by exactly 1 on every mutation. These mutable resources are: `Instructor`, `Learner`, `Course`, `Lesson`, `Coupon`, `Bundle`, `Enrollment`, `LessonCompletion`, `Review`, and `Payout`.

Two resources are immutable after creation and therefore carry only `id` and `created_at` — they have neither an `updated_at` field nor a `version` field: the `Certificate` and the `RevenueLedgerEntry`. A reconciliation that recomputes a derived field on a mutable resource (for instance, refreshing a course's rating or an instructor's balances) is itself a mutation: it refreshes that resource's `updated_at` and increments its `version`.

### 2.5. Reverse-Reach Retrieval and Path Validation

The entity model is flat: every resource is a top-level resource addressed by its own `id`, and parent-child relationships are expressed through foreign keys rather than nested URL paths. A handful of read endpoints reach back along a foreign key — listing a course's lessons, an enrollment's lesson-completions, an enrollment's certificate, and so on — by accepting the parent identifier as a filter or a leading path segment.

For any endpoint whose path or body references resources by identifier, the system validates those identifiers left to right and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve to an existing resource, before any business rule is evaluated. The left-to-right resolution order across the referenced resource families is course, lesson, enrollment, coupon, bundle, payout, review, learner, instructor.

### 2.6. Monetary Precision and Rounding

All prices, discounts, fees, balances, and ledger amounts are held as whole integer cents — there are no fractional cents anywhere in the system. Wherever a calculation produces a non-integer cent value (a percentage discount, or an instructor's revenue share of a gross price), the result is rounded to the nearest whole cent using the round-half-up convention. The score fields that are expressed as fractions — a lesson-completion's `score_pct`, an enrollment's `weighted_score_pct`, and a certificate's `final_score_pct` — are rounded to four decimal places, again half-up. A course's `average_rating` is rounded to two decimal places. An instructor's three balance fields (`payout_balance_cents`, `pending_balance_cents`, `lifetime_earned_cents`) and a learner's `wallet_credit_cents` are integer cents; `payout_balance_cents` and `wallet_credit_cents` are floored at zero and never go negative.

### 2.7. The Revenue Ledger Principle

Instructor earnings are never stored as a hand-edited running total. Instead, every money movement appends a `RevenueLedgerEntry`, and an instructor's balances are always a fresh aggregation over that instructor's ledger rows. Each entry records the `instructor_id` it belongs to, an `entry_type` of `SALE`, `REFUND`, or `PAYOUT`, an `amount_cents` value, a `status`, the `enrollment_id` that produced it (set for `SALE` and `REFUND` entries, null for `PAYOUT`), the `payout_id` it settles (set on `PAYOUT` entries, otherwise null), and the `created_at` clock instant at which it was written. A `SALE` entry carries a positive `amount_cents` equal to the enrollment's instructor share; a `REFUND` entry carries a negative `amount_cents` equal to the clawed-back share; a `PAYOUT` entry carries a negative `amount_cents` equal to the amount paid. A ledger entry's `status` is one of `PENDING`, `AVAILABLE`, `CLAWED_BACK`, or `PAID`.

Whenever a ledger row is written or has its status flipped — a new sale, a refund clawback, a window-expiry flip to available, or a payout — the owning instructor's balances are recomputed immediately. The pending balance (`pending_balance_cents`) is the sum of `amount_cents` over the instructor's `SALE` entries whose status is `PENDING`. The available credits figure is the sum of `amount_cents` over the instructor's `SALE` entries whose status is `AVAILABLE`. The payouts-taken figure is the sum of the absolute values of `amount_cents` over the instructor's `PAYOUT` entries whose status is `PAID`. The payable balance (`payout_balance_cents`) is the available credits minus the payouts-taken figure, floored at zero so it can never be negative. The lifetime earned figure (`lifetime_earned_cents`) is the sum of `amount_cents` over the instructor's entries whose `entry_type` is `SALE` or `REFUND` and whose status is anything other than `CLAWED_BACK`. Every such recomputation is a mutation of the instructor, refreshing its `updated_at` and incrementing its `version`.

### 2.8. The Logical Clock

The system reads "now" from a controllable logical clock rather than wall-clock time. An admin-only test-driving capability sets the current UTC instant to a supplied `to_iso8601` value and returns the new `current_utc`. Time-sensitive rules — coupon validity windows, bundle promotional windows, drip-release gates, refund deadlines, and the lazy expiry of enrollments — are all evaluated against this clock. Advancing the clock past an enrollment's `refund_deadline` does not eagerly mutate anything; the affected enrollment lazily transitions on the next read or write that touches it (see Section 3).

### 2.9. Cascades, Derived Fields, and Hierarchical Consistency

Many operations mutate more than one resource. When a write changes a derived figure on a related resource — a course's enrollment count, rating, or lesson counts; an instructor's balances; a coupon's redeemed count or status; a bundle's status — the system applies the cascade synchronously within the same operation, and each cascaded resource independently records the mutation by refreshing its own `updated_at` and incrementing its own `version`. The specific cascade sets are described in the workflows of Section 3; the general guarantee is that no derived field is ever left stale relative to the events that feed it, and that completion of an enrollment never moves money — a completion leaves the originating `SALE` ledger entry exactly as it was.

### 2.10. Optimistic Concurrency Control

Two write operations consume a balance or a membership that another writer may have legitimately moved, and both are guarded by optimistic concurrency control. In each case the client must send the version of the *parent* entity it last observed, and the write is rejected if that version no longer matches the parent's current `version`.

Approving a payout draws against the instructor's payable balance. The approval request must carry `expected_instructor_version`, holding the client's last observed `version` of the target payout's instructor. If a SALE-window expiry flip or an earlier payout has advanced that instructor's `version` since the client read it, the carried value will no longer equal the instructor's current `version`, and the approval is rejected with `ERR_STALE_VERSION` (HTTP 412) — preventing the approval from drawing against a balance the client can no longer see. Enrolling through a bundle consumes the bundle's membership. The bundle-enroll request must carry `expected_bundle_version`, holding the client's last observed `version` of the target bundle. The OCC check is evaluated late, after the bundle is known to exist and to be in an eligible (`ACTIVE`) state per the ordering of Section 2.11: when the bundle is still `ACTIVE` but its `version` no longer equals the carried `expected_bundle_version`, the bundle enrollment is rejected with `ERR_STALE_VERSION` (HTTP 412). A retire cascade (triggered when one of the bundle's member courses is retired) both moves the bundle to `RETIRED` and advances its `version`; because state eligibility is checked before the OCC version check, a bundle-enroll against such a retired bundle fails the state-eligibility check first and is rejected with `ERR_INVALID_STATE` (HTTP 409) rather than `ERR_STALE_VERSION`. The bundle version bump remains the event the OCC check defends against while the bundle is still eligible. No other endpoint accepts or requires a version field.

### 2.11. Validation Ordering

When several checks guard a single endpoint, they are evaluated in a fixed priority order so that the same failing request always yields the same error. Authentication comes first: a missing or unknown header pair fails with `ERR_UNAUTHENTICATED` (401). Authorization comes next: a role not permitted for the operation, or an entity-backed caller acting on a resource it does not own, fails with `ERR_FORBIDDEN` (403). Existence comes third: any referenced resource that does not resolve fails with `ERR_NOT_FOUND` (404), left to right. State eligibility comes fourth: a target resource that is not in a state permitting the requested transition fails with `ERR_INVALID_STATE` (409). Domain business rules — the publishability, completion, coupon, bundle, refund, payout, and review constraints detailed throughout Section 3 — are evaluated after those four, each carrying its own specific error. Optimistic-concurrency version checks are evaluated late, after the resource is known to exist and to be in an eligible state. Generic field-level input validation — required fields present, enum values legal, numbers within their permitted ranges — carries `ERR_INVALID_REQUEST` (HTTP 400) and is the lowest-priority family, applicable to every endpoint that accepts a body.

## 3. Business Logic & Workflows

### 3.1. Accounts: Instructors and Learners

The platform's two human-facing actors register themselves through unauthenticated endpoints. An instructor is created with a `display_name`, an `email` that must be unique across instructors, and an optional `revenue_share_pct`; when the share is omitted it defaults to 0.50, and any supplied value must lie between 0.00 and 1.00 inclusive. The new instructor's three computed money fields — `payout_balance_cents`, `pending_balance_cents`, and `lifetime_earned_cents` — all begin at zero and thereafter track the revenue ledger as described in Section 2.7. A learner is created with a `full_name` and an `email` that must be unique across learners; the learner's `wallet_credit_cents` begins at zero and accrues only from refunds.

Reading an instructor recomputes and returns its current balances. Reading a learner returns its current wallet credit. An instructor may read its own record and a platform admin may read any; a learner may read its own record and a platform admin may read any. Both account types begin life at `version` 1.

### 3.2. Building a Catalog: Courses and Lessons

An instructor authors a course by supplying the owning `instructor_id`, a `title`, and a `list_price_cents` catalog price that must be at least zero. Several pedagogical and commercial parameters are optional at creation and fall back to defaults: `passing_score_pct` (the minimum weighted quiz score needed to pass, between 0.00 and 1.00, default 0.70); `refund_window_days` (how many days after enrollment a learner may self-refund, at least zero, default 30); `drip_enabled` (whether lessons unlock on a schedule rather than all at once, default false); `ceu_credits` (continuing-education units granted on completion, at least zero and in multiples of 0.1, default 0.0); and `completion_threshold_pct` (the fraction of published lessons that must be completed to finish the course, between 0.01 and 1.00 inclusive, default 1.00). A course is born in `DRAFT` status. Its derived fields — `lesson_count`, `published_lesson_count`, `enrollment_count`, `average_rating`, and `rating_count` — are maintained by the system; `average_rating` is null while a course has no published reviews.

A lesson is added to a course by referencing the owning `course_id`; lessons may only be added while the course is in `DRAFT` or `UNPUBLISHED` status. Each lesson carries a `title` and an `order_index`, a 1-based position within the course that must be unique among that course's lessons — a colliding `order_index` on creation is rejected with `ERR_DUPLICATE_LESSON_COMPLETION` (HTTP 409). A lesson may be graded or not: `is_graded` defaults to false, and when it is true the lesson carries a quiz that contributes to the course score. A graded lesson's `quiz_weight` (default 0, at least zero) is its relative weight in the course's weighted score and is ignored entirely when the lesson is not graded; its `question_count` (default 0) is the number of quiz questions and must be at least 1 when `is_graded` is true. Each lesson also has a `drip_offset_days` (default 0, at least zero) governing how long after enrollment it unlocks when its course has drip enabled. A lesson's `is_published` flag is system-managed, defaults to false, and becomes true only when its course is published. Adding a lesson recomputes the course's `lesson_count`.

### 3.3. Publishing, Unpublishing, Retiring

Publishing is the gate between an unsellable draft and an enrollable course. An instructor may publish a course only from `DRAFT` (the `DRAFT → PUBLISHED` transition) or re-publish it from `UNPUBLISHED` (the `UNPUBLISHED → PUBLISHED` transition); attempting to publish a course in any other status is rejected with `ERR_INVALID_STATE`. A first-time publish from `DRAFT` carries three further requirements, all enforced together with `ERR_COURSE_NOT_PUBLISHABLE` (HTTP 422): the course must have at least one lesson; every graded lesson must have a `question_count` of at least 1; and, when the course has at least one graded lesson, the sum of `quiz_weight` across the graded lessons must be at least 1. A course with no graded lessons satisfies this last requirement vacuously — the `quiz_weight`-sum constraint is not applied when there are no graded lessons to sum over — so such a course is publishable on the strength of having at least one lesson alone. When publishing succeeds from `DRAFT`, the system sets `is_published` to true on every lesson of the course and recomputes both `lesson_count` and `published_lesson_count`. Re-publishing from `UNPUBLISHED` additionally requires that the course still have at least one published lesson, and it simply makes the course enrollable again.

Unpublishing takes a course from `PUBLISHED` to `UNPUBLISHED`. Its sole effect is to make the course non-enrollable — new enrollments are blocked while it is unpublished — while leaving any existing `ACTIVE` enrollments completely unaffected so that learners mid-course are not disrupted. Retiring is terminal. An instructor may retire a course from either `PUBLISHED` or `UNPUBLISHED` status, but only when the course has no enrollment still in `ACTIVE` status; if any active enrollment remains, the retire is rejected with `ERR_INVALID_STATE`. Retiring a course (both the `PUBLISHED → RETIRED` and the `UNPUBLISHED → RETIRED` transitions) cascades to bundles: every bundle currently in `ACTIVE` status whose `course_ids` includes the retired course is itself transitioned to `RETIRED`, and each such bundle independently refreshes its `updated_at` and increments its `version`. This bundle version bump is precisely the event the bundle-enrollment concurrency check defends against.

### 3.4. Pricing and Enrollment: the Single-Course Path

When a learner enrolls in a single course, the system snapshots the course's current `list_price_cents` onto the enrollment as `list_price_cents` and computes what the learner actually pays. A single-course enrollment is permitted only while the course is in `PUBLISHED` status; a target course in any other status (`DRAFT`, `UNPUBLISHED`, or `RETIRED`) is rejected at the state-eligibility stage with `ERR_INVALID_STATE` (HTTP 409). The enrollment request carries the enrolling `learner_id` and an optional `coupon_code`. With no coupon, the gross price (`gross_price_cents`) equals the snapshot list price. A supplied `coupon_code` is resolved case-insensitively among the coupons issued by the course's owning instructor; if it resolves to no such coupon, the enrollment is rejected with `ERR_COUPON_COURSE_MISMATCH` (HTTP 422). With a coupon that resolves to a coupon on this course, the discount depends on the coupon's `discount_type`: a `PERCENT` coupon discounts the base list price by its `discount_value` percent, with the discount amount computed as the list price multiplied by the discount value divided by 100 and rounded half-up to the nearest cent; a `FLAT` coupon discounts by the lesser of its `discount_value` cents and the base list price. The gross price is then the list price minus the discount, but never below zero. From the gross price the system derives the instructor's cut: `instructor_share_cents` is the gross price multiplied by the owning instructor's `revenue_share_pct`, rounded half-up to the nearest cent, and `platform_fee_cents` is the gross price minus the instructor share.

A successful single-course enrollment is born `ACTIVE` at `version` 1, stamps `enrolled_at` with the current clock instant, and computes `refund_deadline` as `enrolled_at` plus the course's `refund_window_days`, treated as an exclusive boundary (self-refund is allowed strictly before it). The enrollment records a null `bundle_id` and, if a coupon was used, the redeemed `coupon_id` (otherwise null). The enrollment writes one `SALE` `RevenueLedgerEntry` for the owning instructor with a `PENDING` status and an `amount_cents` equal to the instructor share, then increments the course's `enrollment_count`. If a coupon was redeemed, the coupon's `redeemed_count` is incremented; should that increment bring `redeemed_count` up to `max_redemptions`, the coupon transitions `ACTIVE → EXHAUSTED` so that no further redemption is allowed. The enrollment's progress fields — `completed_lesson_count`, `progress_pct`, `weighted_score_pct`, `ceu_awarded` — all start empty (zero), and `ceu_awarded` stays at 0.0 until the enrollment completes.

A learner may not hold two enrollments in the same course at once: if an enrollment in `ACTIVE`, `COMPLETED`, or `EXPIRED` status already exists for this learner-and-course pair, a new enrollment attempt is rejected with `ERR_ALREADY_ENROLLED` (HTTP 409). A prior `REFUNDED` enrollment does not block re-enrollment. This duplicate-enrollment guard applies to both the single-course path and the bundle path.

### 3.5. Coupons: Eligibility and Redemption Constraints

An instructor issues a coupon against one of its own courses by supplying the issuing `instructor_id`, the target `course_id`, a `code` (unique per instructor, compared case-insensitively), a `discount_type` of either `PERCENT` or `FLAT`, a `discount_value`, a `max_redemptions` count of at least 1, and a half-open validity window defined by `valid_from` (inclusive start) and `valid_until` (exclusive end). For a `PERCENT` coupon the `discount_value` is a whole percentage from 1 to 100; for a `FLAT` coupon it is a number of cents off, at least 1. The coupon's `redeemed_count` begins at zero and tracks the number of non-`REFUNDED` enrollments that have redeemed it; the coupon's `status` begins `ACTIVE`.

A new coupon's window must not overlap the window of any existing non-`DISABLED` coupon for the same instructor-and-course combination. The windows are half-open: two coupons whose windows merely touch at an endpoint — where one's `valid_until` equals the other's `valid_from` — do not overlap and are permitted. Two windows overlap, and the create is rejected with `ERR_COUPON_WINDOW_OVERLAP` (HTTP 409), exactly when the new window's `valid_from` is strictly before the existing window's `valid_until` and the existing window's `valid_from` is strictly before the new window's `valid_until`.

At redemption time — during a single-course enrollment — a coupon is usable only when it is currently `ACTIVE` and the clock sits within its window, meaning the current instant is at or after `valid_from` and strictly before `valid_until`; a coupon outside its window or not `ACTIVE` is rejected with `ERR_COUPON_NOT_REDEEMABLE` (HTTP 422). The resolved coupon must also belong to the course being enrolled: its `course_id` must equal the enrolled course and its issuing instructor must own that course, or the enrollment is rejected with `ERR_COUPON_COURSE_MISMATCH` (HTTP 422). Finally, a coupon whose `redeemed_count` has already reached `max_redemptions` cannot be redeemed again and is rejected with `ERR_COUPON_EXHAUSTED` (HTTP 409). An instructor may also retire a coupon ahead of schedule: disabling a coupon takes it from `ACTIVE` to `DISABLED`, after which it can never be redeemed; `DISABLED` is terminal.

### 3.6. Bundles: Multi-Course Pricing and Allocation

A bundle packages two or more of an instructor's courses at a single flat price. Creating a bundle requires the owning `instructor_id`, a `title`, an ordered `course_ids` list, a `bundle_price_cents`, and a promotional window bounded by `promo_starts_at` (inclusive) and `promo_ends_at` (exclusive), where the end must be strictly after the start. The `course_ids` list must contain at least two distinct courses, all of which are `PUBLISHED` and owned by the issuing instructor, and the `bundle_price_cents` must be strictly less than the sum of the member courses' list prices; a bundle that violates either rule is rejected with `ERR_INVALID_BUNDLE` (HTTP 422). At creation the system snapshots `sum_list_price_cents` as the sum of the members' `list_price_cents` and derives `savings_cents` as that sum minus `bundle_price_cents`. The bundle is born `ACTIVE`; its status is one of `ACTIVE` or `RETIRED`, and the retire cascade described in Section 3.3 is the only path to `RETIRED`.

A new bundle's promotional window must keep a strict one-day buffer from every existing `ACTIVE` bundle of the same instructor that shares at least one member course. The buffer is 86,400 seconds (one full day). Two such bundles collide — and the create is rejected with `ERR_BUNDLE_PROMO_OVERLAP` (HTTP 409) — when the new window's `promo_starts_at` is before the existing window's `promo_ends_at` extended forward by one day, and at the same time the existing window's `promo_starts_at` is before the new window's `promo_ends_at` extended forward by one day. Under these closed-with-buffer semantics, windows that merely touch, or that leave any gap shorter than one full day, are rejected; only a gap of at least one day between sharing bundles is allowed.

Enrolling through a bundle creates one enrollment per member course in a single operation and is guarded by the optimistic-concurrency check of Section 2.10: the request carries the enrolling `learner_id` and `expected_bundle_version`, and a mismatch against the bundle's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). Coupons are not accepted on a bundle enrollment. The flat `bundle_price_cents` is split across the member courses by list-price weight using the largest-remainder method, so that the per-course gross prices sum to exactly the bundle price with no cent lost or invented. For each member course, a raw share is the bundle price multiplied by that course's `list_price_cents` divided by `sum_list_price_cents`; each course's provisional share is the floor of its raw share. The leftover — the bundle price minus the sum of all the floored shares, always a non-negative whole number of cents — is then distributed one cent at a time to the courses with the largest fractional parts of their raw shares, with ties broken by the member course's `created_at` ascending. A course that receives a leftover cent has a gross of its floor plus one; a course that does not has a gross equal to its floor. Each resulting member enrollment computes its own `instructor_share_cents` by applying that member course's instructor's `revenue_share_pct` to the course's allocated gross, rounded half-up, with `platform_fee_cents` as the remainder. Each member enrollment carries the originating `bundle_id`, a null `coupon_id`, writes its own `SALE` ledger entry for its instructor in `PENDING` status, and increments its course's `enrollment_count`; the bundle enroll also increments the bundle's `version` by 1. The duplicate-enrollment guard of Section 3.4 applies to each member course. A successful bundle enroll returns `201 Created` with `response_type` `array`, the `data` field carrying the list of newly created member enrollments in member-course order.

### 3.7. Learning, Quizzes, and Scoring

A learner records progress by submitting a lesson-completion against an enrollment, identifying the owning `enrollment_id` and the `lesson_id` being completed, plus an optional `correct_answers` count (default 0) for graded lessons. A completion is accepted only while the enrollment is `ACTIVE`, the target lesson belongs to the enrollment's course and is published, and no completion already exists for this enrollment-and-lesson pair; a duplicate pair is rejected with `ERR_DUPLICATE_LESSON_COMPLETION` (HTTP 409). When the course has drip enabled, the lesson is additionally locked until the clock reaches `enrolled_at` plus the lesson's `drip_offset_days`; an attempt before that instant is rejected with `ERR_LESSON_LOCKED` (HTTP 409). For graded lessons, `correct_answers` must not exceed the lesson's `question_count`.

Each completion is scored. For a non-graded lesson the `score_pct` is fixed at 1.0 and the lesson is `passed`. For a graded lesson the `score_pct` is the `correct_answers` divided by the lesson's `question_count`, rounded to four decimal places, and the lesson is `passed` when that `score_pct` is at least the course's `passing_score_pct` — the comparison is inclusive, so a score exactly equal to the passing threshold passes. Recording a completion recomputes the enrollment's progress: `completed_lesson_count` is the number of the enrollment's completions whose `passed` is true; `progress_pct` is that count divided by the course's `published_lesson_count`, rounded to two decimal places.

The enrollment's `weighted_score_pct` is the authoritative figure for both the pass/fail gate and the value stored on the enrollment, and it is computed over the course's graded, published lessons. The fixed denominator is the total `quiz_weight` summed across all graded published lessons of the course, established at publish time and at least 1. The numerator is the sum, over those graded lessons that have a completion on this enrollment, of each completion's `score_pct` multiplied by its lesson's `quiz_weight`. The weighted score is the numerator divided by the fixed total weight, rounded to four decimal places. Because the denominator is fixed, graded lessons not yet completed contribute zero to the numerator while their weight still counts in the denominator. A certificate transcript may additionally display a simpler unweighted average — the mean of the completed graded lessons' `score_pct` over the count of those completed graded lessons — but that transcript average is for display only and is never the completion gate; because its denominator grows as the learner completes more lessons, it can diverge from the weighted figure for identical data.

### 3.8. Completion, Certificates, and CEU

After each lesson-completion is recorded and the enrollment's progress and weighted score are refreshed, the system checks whether the enrollment has earned completion. An `ACTIVE` enrollment auto-transitions to `COMPLETED` (the `ACTIVE → COMPLETED` transition) when two conditions hold together: its `progress_pct` is at least the course's `completion_threshold_pct`, and its `weighted_score_pct` is at least the course's `passing_score_pct`. A course with no graded lessons auto-satisfies the score condition. On completion, the system sets the enrollment's `ceu_awarded` to the course's `ceu_credits` and issues exactly one `Certificate` for the enrollment. Completion moves no money — the originating `SALE` ledger entry is left untouched.

The issued certificate is an immutable record carrying its own `id` and `created_at`, the `enrollment_id` it certifies, the `course_id` and `learner_id` copied from that enrollment, a `ceu_credits` snapshot of the course's CEU value at issuance, a `final_score_pct` snapshot of the enrollment's `weighted_score_pct` (to four decimal places) at issuance, and an `issued_at` clock instant. A completed enrollment's certificate is retrievable by reaching back from the enrollment; that reverse-reach read responds with `response_type` `array`, the `data` field carrying the matching certificates (one element once the enrollment has completed, an empty list otherwise).

### 3.9. The Refund Window and Lazy Expiry

An `ACTIVE` enrollment carries a self-refund right that lives only until its `refund_deadline`. A learner may self-refund (the `ACTIVE → REFUNDED` transition) while the enrollment is `ACTIVE` and the current clock is strictly before `refund_deadline`; a refund attempted at or after that instant is rejected with `ERR_REFUND_WINDOW_CLOSED` (HTTP 422). A successful refund unwinds the purchase across four resources at once. The learner's `wallet_credit_cents` is increased by the enrollment's `gross_price_cents`. The enrollment's originating `SALE` `RevenueLedgerEntry` flips from `PENDING` to `CLAWED_BACK`, and then a new `REFUND` entry is written with a `status` of `AVAILABLE` and an `amount_cents` equal to the negative of the enrollment's `instructor_share_cents`; both movements force a recompute of the instructor's `pending_balance_cents` and `lifetime_earned_cents`. Because the `REFUND` entry's status is not `CLAWED_BACK`, its negative amount counts toward the lifetime-earned aggregation per Section 2.7. If the enrollment had redeemed a coupon, that coupon's `redeemed_count` is decremented, and if the coupon had been `EXHAUSTED` it transitions back from `EXHAUSTED` to `ACTIVE` now that a redemption has been freed (the `EXHAUSTED → ACTIVE` transition, recomputing the coupon's `status` and `version`). Finally the course's `enrollment_count` is decremented.

The refund window closing does not in itself end the enrollment's usefulness. When the clock has reached or passed an `ACTIVE` enrollment's `refund_deadline`, the enrollment lazily transitions to `EXPIRED` (the `ACTIVE → EXPIRED` transition) on the next read or write that touches it. Expiry means only that the refund right is gone: an `EXPIRED` enrollment is still usable for learning and can still auto-complete. Its single side effect is fiscal — the enrollment's originating `SALE` ledger entry flips from `PENDING` to `AVAILABLE`, which recomputes the instructor's `pending_balance_cents` and `payout_balance_cents`, moving that sale's share out of the provisional bucket and into the payable balance. This is the moment an instructor's earnings on a sale become withdrawable.

### 3.10. Ratings, Reviews, and Moderation

A learner may review a course only after experiencing it. A review references the reviewer's own `enrollment_id` and supplies a `stars` rating from 1 to 5 inclusive and a free-text `body`; the system copies the `course_id` and `learner_id` from the referenced enrollment onto the review. A review is eligible only when the referenced enrollment is owned by the acting learner and is in `COMPLETED` or `EXPIRED` status, and the enrollment does not already back a non-`RETRACTED` review (at most one live review per enrollment); a request failing either condition is rejected with `ERR_REVIEW_NOT_ELIGIBLE` (HTTP 422). A review is born `PUBLISHED`. Creating a published review recomputes the target course's `average_rating` (the mean of the stars over the course's published reviews, to two decimal places, null when there are none) and `rating_count` (the number of published reviews).

Reviews are subject to moderation and learner control. A platform admin may hide a published review (the `PUBLISHED → HIDDEN` transition) and later unhide it (the `HIDDEN → PUBLISHED` transition); a learner may retract their own review (the `PUBLISHED → RETRACTED` transition), permitted only while the review is `PUBLISHED` and the acting learner owns the enrollment the review references — `RETRACTED` is terminal. Each of these three transitions cascades to the course's rating: hiding and retracting recompute `average_rating` and `rating_count` with the affected review excluded, while unhiding recomputes them with the review included again; every such recompute is a mutation of the course, refreshing its `updated_at` and incrementing its `version`.

### 3.11. Payouts and Settlement

An instructor draws earnings down by requesting a payout, supplying its own `instructor_id` and a `requested_amount_cents` of at least 1. A payout request requires the instructor's `payout_balance_cents` to be at least 1, or it is rejected with `ERR_INSUFFICIENT_BALANCE` (HTTP 422). A new payout is born `REQUESTED` at `version` 1, with `paid_amount_cents` at zero until it is paid.

A platform admin settles a requested payout. Approving a payout (the `REQUESTED → PAID` transition) is allowed only while the payout is `REQUESTED`, requires the instructor's `payout_balance_cents` to still be at least 1 (otherwise `ERR_INSUFFICIENT_BALANCE`, HTTP 422), and is guarded by the optimistic-concurrency check of Section 2.10: the approval request carries `expected_instructor_version`, which must equal the instructor's current `version` or the approval is rejected with `ERR_STALE_VERSION` (HTTP 412). On approval the system sets `paid_amount_cents` to the lesser of the `requested_amount_cents` and the instructor's current `payout_balance_cents`, writes a `PAYOUT` `RevenueLedgerEntry` referencing the payout with an `amount_cents` equal to the negative of that paid amount and a `status` of `PAID`, recomputes the instructor's `payout_balance_cents` (debited by the paid amount), and increments the instructor's `version` by 1. Alternatively the admin may reject a requested payout (the `REQUESTED → REJECTED` transition), which moves no money and simply closes the payout; both `PAID` and `REJECTED` are terminal.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`. Operations that modify an existing resource — including state transitions and read operations — return `200 OK`. Reconstruct each endpoint's request body, response body, and side effects from the workflow narratives in Section 3; the table below lists only the surface contract.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/instructors` | Register an instructor | Anonymous |
| GET | `/instructors/{instructor_id}` | Get an instructor with balances | Instructor, PlatformAdmin |
| POST | `/learners` | Register a learner | Anonymous |
| GET | `/learners/{learner_id}` | Get a learner with wallet | Learner, PlatformAdmin |
| POST | `/courses` | Create a course (DRAFT) | Instructor |
| GET | `/courses/{course_id}` | Get a course | Instructor, Learner, PlatformAdmin |
| GET | `/courses` | List courses (filter by instructor_id, status) | Instructor, Learner, PlatformAdmin |
| POST | `/courses/{course_id}/publish` | Publish or re-publish a course | Instructor |
| POST | `/courses/{course_id}/unpublish` | Unpublish a course | Instructor |
| POST | `/courses/{course_id}/retire` | Retire a course | Instructor |
| POST | `/lessons` | Add a lesson to a DRAFT/UNPUBLISHED course | Instructor |
| GET | `/lessons/{lesson_id}` | Get a lesson | Instructor, Learner, PlatformAdmin |
| GET | `/lessons` | List lessons (filter by course_id) | Instructor, Learner, PlatformAdmin |
| POST | `/coupons` | Create a coupon | Instructor |
| GET | `/coupons/{coupon_id}` | Get a coupon | Instructor, PlatformAdmin |
| GET | `/coupons` | List coupons (filter by instructor_id, course_id, status) | Instructor, PlatformAdmin |
| POST | `/coupons/{coupon_id}/disable` | Disable a coupon | Instructor |
| POST | `/bundles` | Create a bundle | Instructor |
| GET | `/bundles/{bundle_id}` | Get a bundle | Instructor, Learner, PlatformAdmin |
| GET | `/bundles` | List bundles (filter by instructor_id, status) | Instructor, Learner, PlatformAdmin |
| POST | `/bundles/{bundle_id}/enroll` | Enroll a learner in all member courses (OCC on bundle) | Learner |
| POST | `/courses/{course_id}/enroll` | Enroll a learner in a single course | Learner |
| GET | `/enrollments/{enrollment_id}` | Get an enrollment (lazy auto-expire) | Learner, Instructor, PlatformAdmin |
| GET | `/enrollments` | List enrollments (filter by course_id, learner_id, coupon_id, bundle_id, status) | Learner, Instructor, PlatformAdmin |
| POST | `/enrollments/{enrollment_id}/refund` | Self-refund within the refund window | Learner |
| GET | `/enrollments/{enrollment_id}/lesson-completions` | List completions for an enrollment | Learner, Instructor, PlatformAdmin |
| GET | `/enrollments/{enrollment_id}/certificate` | Get the certificate for a completed enrollment | Learner, Instructor, PlatformAdmin |
| POST | `/lesson-completions` | Record a lesson completion / quiz attempt | Learner |
| GET | `/lesson-completions/{completion_id}` | Get a lesson completion | Learner, Instructor, PlatformAdmin |
| GET | `/lesson-completions` | List completions (filter by enrollment_id, lesson_id) | Learner, Instructor, PlatformAdmin |
| GET | `/certificates/{certificate_id}` | Get a certificate | Learner, Instructor, PlatformAdmin |
| GET | `/certificates` | List certificates (filter by course_id, learner_id, enrollment_id) | Learner, Instructor, PlatformAdmin |
| POST | `/reviews` | Create a review | Learner |
| GET | `/reviews/{review_id}` | Get a review | Learner, Instructor, PlatformAdmin |
| GET | `/reviews` | List reviews (filter by course_id, enrollment_id, learner_id, status) | Learner, Instructor, PlatformAdmin |
| POST | `/reviews/{review_id}/hide` | Hide a review (moderation) | PlatformAdmin |
| POST | `/reviews/{review_id}/unhide` | Unhide a review | PlatformAdmin |
| POST | `/reviews/{review_id}/retract` | Retract one's own review | Learner |
| POST | `/payouts` | Request a payout | Instructor |
| GET | `/payouts/{payout_id}` | Get a payout | Instructor, PlatformAdmin |
| GET | `/payouts` | List payouts (filter by instructor_id, status) | Instructor, PlatformAdmin |
| POST | `/payouts/{payout_id}/approve` | Approve and pay a payout (OCC on instructor) | PlatformAdmin |
| POST | `/payouts/{payout_id}/reject` | Reject a payout | PlatformAdmin |
| GET | `/ledger-entries/{entry_id}` | Get a revenue ledger entry | Instructor, PlatformAdmin |
| GET | `/ledger-entries` | List ledger entries (filter by instructor_id, enrollment_id, payout_id, entry_type, status) | Instructor, PlatformAdmin |
| POST | `/_clock/set_current_utc` | Set the system clock (test-driving) | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_COURSE_NOT_PUBLISHABLE` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_LESSON_COMPLETION` | 409 Conflict |
| `ERR_LESSON_LOCKED` | 409 Conflict |
| `ERR_COUPON_NOT_REDEEMABLE` | 422 Unprocessable Entity |
| `ERR_COUPON_COURSE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_COUPON_EXHAUSTED` | 409 Conflict |
| `ERR_ALREADY_ENROLLED` | 409 Conflict |
| `ERR_REVIEW_NOT_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_INVALID_BUNDLE` | 422 Unprocessable Entity |
| `ERR_COUPON_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_BUNDLE_PROMO_OVERLAP` | 409 Conflict |
| `ERR_INSUFFICIENT_BALANCE` | 422 Unprocessable Entity |
| `ERR_REFUND_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
