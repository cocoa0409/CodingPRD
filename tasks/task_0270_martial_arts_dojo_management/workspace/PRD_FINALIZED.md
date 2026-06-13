# Martial Arts Dojo Management API — Product Requirements Document

## 1. Introduction

This document specifies the back-office platform that runs a modern martial-arts academy. A single dojo simultaneously juggles several intertwined concerns: it teaches structured belt-rank progressions across multiple disciplines, schedules and takes attendance for group classes, decides who is ready to sit a promotion test, bills recurring tuition under fixed-term contracts, books one-on-one private lessons, registers competitors for tournaments, and sells gear through a small pro-shop. Today most academies stitch these together with spreadsheets and a calendar, which makes it nearly impossible to answer questions like "is this student eligible to grade?" or "what does this family actually owe this month?" without manual reconciliation.

The API described here is the system of record that removes that guesswork. Every belt is earned along an explicit progression chain; every dollar of tuition flows through a contract whose discount was pinned at signing; every safety prerequisite (a signed waiver, an account in good standing) is enforced before a student steps on the mat or onto a competition floor. The platform must be internally consistent at all times: freezing an account ripples to its enrollments, a missed payment can suspend a member and strip their tournament spots, and clearing the balance reverses those effects. Because the dojo's front desk, its instructors, its chief instructor, and the students themselves all act on the same data concurrently, the system also enforces optimistic version checks at the points where stale reads would cause real financial or eligibility errors.

The intended audience for this document is the engineering team building the service. It is organized so that Section 2 fixes the system-wide contracts (auth, response shape, pagination, consistency, money, concurrency), Section 3 narrates the domain workflows in business terms, and Sections 4 and 5 enumerate the HTTP surface and the error catalogue. All resources are mounted under the `/dojo` path prefix.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the calling principal, and `X-User-Role`, naming the role the caller is acting as. If `X-User-Role` is missing or is not one of the four recognized roles, or if `X-User-ID` is missing for a role that requires an entity identity, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the named role is not permitted to perform the requested operation — or an entity-backed caller attempts to act on a resource it does not own — the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The four roles are `FrontDesk`, `Instructor`, `ChiefInstructor`, and `Member`.

`FrontDesk` is an operator role with an **opaque** identity: when `X-User-Role` is `FrontDesk`, `X-User-ID` is an opaque staff identifier not tied to any persisted entity. The server may record it for audit but never compares it to any entity's `id`; front-desk staff act on any member's resources on the academy's behalf.

The remaining three roles are **entity-backed**. When `X-User-Role` is `Instructor`, `X-User-ID` is the `id` of the acting `Instructor`; ownership checks on any resource that references an `Instructor` compare that resource's instructor foreign key to `X-User-ID`. When `X-User-Role` is `ChiefInstructor`, `X-User-ID` is likewise the `id` of the acting `Instructor` (a chief instructor is an `Instructor` record whose `rank_level` is `CHIEF_INSTRUCTOR`); `ChiefInstructor` is a hierarchical override of `Instructor`, so it may perform every `Instructor` action and additionally sign off promotions. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`; ownership checks on any resource that references a `Member` compare the resource's member foreign key to `X-User-ID`, and a member may only read and act on their own bookings, payments, registrations, and orders.

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

All list endpoints are paginated through two query parameters. `limit` controls how many records are returned and defaults to 10 when omitted; it must be at least 1 and at most 100. `offset` is the zero-based index of the first record returned, defaults to 0, and must be at least 0. Results are always sorted by `created_at` in ascending order so that pagination is stable across pages. Every list response surfaces `limit`, `offset`, `total_count` (the total number of records matching the filter, ignoring pagination), and `has_more` (true when records remain beyond the current page) inside the `meta` object.

### 2.4. Common Resource Properties

Every persisted resource carries a server-minted `id` — a UUID with no type prefix — and a `created_at` timestamp in ISO 8601 UTC format with three fractional digits. The vast majority of resources are mutable and additionally carry an `updated_at` timestamp (same format, refreshed on every mutation) and an integer `version` that begins at 1 and increments by exactly 1 on each mutation. The `version` field is the basis for the optimistic concurrency checks described in §2.6. Clients must never set `id`, `created_at`, `updated_at`, or `version`; the server owns them.

### 2.5. Belt Progression and Derived-Field Reconciliation

Several fields in this system are **computed** and must always be reconciled to their definition rather than set directly by a client. `Family.active_member_count` is the number of members in a household whose `account_status` is either `ACTIVE` or `FROZEN` (a `SUSPENDED` or `WITHDRAWN` member is excluded); it is recomputed on every member add, removal, or status change. `Member.outstanding_balance_cents` is the sum of `amount_due_cents` over the member's invoices whose `status` is `DUE` or `OVERDUE`; it is recomputed whenever an invoice is generated, paid, waived, or voided. `Enrollment.rank_attendance_count` counts the `CONFIRMED` attendance rows for that enrollment recorded at or after `rank_acquired_at`, and resets to 0 on promotion. `ClassSession.confirmed_count` counts the `CONFIRMED` attendances for a session. `ProShopOrder.gross_cents` and `ProShopOrder.net_cents` are derived from the order's line items per §2.8. Because these are derived, any operation that disturbs an input must re-run the relevant reconciliation as part of the same operation.

### 2.6. Optimistic Concurrency Control

Three classes of write are guarded against stale reads. A guarded request must include an `expected_<parent>_version` field carrying the client's last observed `version` of the parent resource; if that value does not equal the parent's current `version` at the moment the write is processed, the write is rejected with `ERR_STALE_VERSION` (HTTP 412), and no state changes. This protects a client from overwriting data it has not observed.

Two of these guards sit on creation endpoints and pin against the `Member`. Creating a contract requires `expected_member_version` to match the target member's current `version`; if another writer has advanced the member's version since the client last read it — for instance because the member was just frozen or withdrawn, which changes the family's `active_member_count` and therefore the discount a new contract would legitimately pin — the create is rejected with `ERR_STALE_VERSION` (HTTP 412). Creating an enrollment likewise requires `expected_member_version` to match the member's current `version`; if the member was advanced since the client last read it (for example, withdrawn, which drops enrollments), the create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing a new enrollment from attaching to an account that no longer accepts them.

The remaining guards sit on member, class-session, and contract transitions: freezing, unfreezing, and withdrawing a member each require `expected_member_version`; cancelling and completing a class session each require `expected_class_session_version`; terminating a contract requires `expected_contract_version`. In every case a mismatch yields `ERR_STALE_VERSION` (HTTP 412). Endpoints not named here take no version field.

### 2.7. Monetary Values, Precision, and Rounding

All money is stored and returned as integer cents — there are no fractional cents. Wherever a percentage discount or a fractional-hour rate produces a non-integer, the result is rounded **half up** to a whole cent. The *order* in which rounding is applied is deliberately specified per calculation and is not interchangeable: recurring tuition rounds the discount on the single base amount; the pro-shop rounds each line item's discount before summing; the private-lesson charge rounds exactly once at the very end after multiplying. Section 3 states each rule precisely. No computed monetary amount may ever go negative; tuition is floored at zero cents.

### 2.8. Pro-Shop Pricing Discipline

A pro-shop order's `line_items` is a non-empty array of objects, each with a `sku`, a `unit_price_cents`, and a `qty`. The order's `gross_cents` is the sum, over every line item, of `unit_price_cents` multiplied by `qty`. The member's pro-shop discount percentage is a loyalty reward keyed to belt rank: the system finds the highest `rank_order` among the `BeltRank` records currently held across the member's `ACTIVE` enrollments, treating a member with no `ACTIVE` enrollment as rank order 0. If that highest rank order is at least 5, the member's discount is 15 percent; otherwise, if it is at least 2, the discount is 10 percent; otherwise it is 0 percent. The order's `net_cents` is computed per line item: for each line, the system multiplies `unit_price_cents` by `qty`, computes the discount as that product times the discount percentage rounded half up to whole cents, subtracts the rounded discount from the line total, and then sums the discounted line totals. Rounding is applied per line item *before* summing — never sum-then-round.

### 2.9. Nested Resource Retrieval and Referential Integrity

Resources reference one another by foreign keys, and the graph is navigated through filtered list reads rather than deep nesting. Two sub-resource paths do nest one level: a program's belt ranks and (conceptually) any path that carries a resource id. Path identifiers are validated left to right: for any endpoint whose URL contains a resource id, that id must resolve to an existing resource, and when several ids appear they are checked in path order; the first that does not resolve yields `ERR_NOT_FOUND` (HTTP 404). Separately, every foreign-key id supplied in a request body — a `member_id`, `program_id`, `instructor_id`, `enrollment_id`, `class_session_id`, `examiner_instructor_id`, `contract_id`, or `family_id` — must reference an existing resource, or the request is rejected with `ERR_FK_NOT_FOUND` (HTTP 404).

### 2.10. Validation Order

When a single request could trip several checks, they are evaluated in a fixed priority order, and the first failure is the one reported. Authentication (`ERR_UNAUTHENTICATED`, 401) is checked first, then authorization (`ERR_UNAUTHORIZED`, 403), then existence of every path id (`ERR_NOT_FOUND`, 404), then existence of every foreign key in the body (`ERR_FK_NOT_FOUND`, 404), then structural validity of the body — required fields, types, enums, ranges (`ERR_INVALID_REQUEST`, 400), then uniqueness (`ERR_DUPLICATE`, 409), then the optimistic-concurrency version check (`ERR_STALE_VERSION`, 412), then the state-transition legality check (`ERR_INVALID_STATE`, 409). Only after all of those pass are the domain-specific business rules of Section 3 evaluated. In other words: who you are and whether the things you name exist are settled before the shape of your payload, which is settled before whether the target is in a legal state, which is settled before the deeper business gates.

## 3. Business Logic & Workflows

### 3.1. Programs, Belt Chains, and the Pro-Shop Catalogue

The academy's offerings are organized into **programs**, each created by the front desk with a display `name` of 1 to 120 characters that is non-empty after trimming, a `discipline` drawn from `KARATE`, `BJJ`, `TAEKWONDO`, `JUDO`, or `MUAY_THAI`, and four economic and progression parameters: the `base_monthly_tuition_cents` charged each month before discounts, the flat `test_fee_cents` charged when a member sits a promotion test, the `min_attendance_for_test` (the minimum number of qualifying attendances accumulated in the current rank before a test may be scheduled), and the `min_days_in_rank` (the minimum whole days a member must hold the current rank before testing). All four amounts and counts are non-negative integers. A program is born in `ACTIVE` `status`; archiving it transitions its `status` to `ARCHIVED`, after which it accepts no new enrollments.

Within a program, the front desk lays out the belt progression as a chain of **belt ranks**. Each `BeltRank` belongs to its program through `program_id` and carries a `code` of 1 to 40 characters that is unique within the program, a `rank_order` (an integer, ascending from the entry rank, that is also unique within the program), and a `next_rank_code` that points to the `code` of the immediate successor rank in the same program. The successor pointer is null on the highest-ordered rank, which marks the terminal belt; on any other rank it must reference an existing belt rank's `code` in the same program. Exactly one rank per program is the entry rank, flagged by `is_entry_rank` (the rank whose `rank_order` is 0); a fresh enrollment always starts there. A rank may set `requires_chief_signoff` to true, which means a promotion *into* that rank cannot be finalized by an ordinary instructor's pass alone and instead waits for a chief instructor's signature. Attempting to register a member or instructor with a duplicate email, or a belt rank whose `code` or `rank_order` collides with one already in the program, is rejected with `ERR_DUPLICATE` (HTTP 409).

The pro-shop sells gear against the catalogue of `sku` codes carried on each order's line items; pricing discipline lives in §2.8.

### 3.2. Households and the Family Discount

A **family** is a billing household identified by a `surname` (1 to 80 characters) and a `billing_email` (which must contain an `@`). Its `active_member_count` is maintained by the system as described in §2.5. The family's size drives a tiered discount: a household with one or fewer counted members earns 0 percent; exactly two counted members earns 10 percent; exactly three earns 15 percent; four or more earns 20 percent, which is the cap and never rises higher. The boundary is inclusive on the low side of each tier — two members yields exactly 10 percent, not the solo rate.

This discount appears in two distinct guises. The **live** tier reflects the household's current roster and shifts as members join, freeze, or withdraw; it is what a family's record reports and what a what-if buyout quote uses. The **pinned** tier is a snapshot: at the moment a contract is signed, the then-current live discount is frozen onto the contract as `locked_family_discount_pct`, and every recurring invoice that contract ever generates uses that pinned value regardless of any later change in family size. The two can legitimately diverge, and the system must keep them separate.

### 3.3. Members, Instructors, and the Two-Dimensional Account

A **member** is registered by the front desk with a `full_name` (1 to 120 characters), a globally unique `email` (containing an `@`, unique across all members), and a `date_of_birth` used later for tournament age divisions. A member may optionally belong to a household via `family_id` (null for a solo member); when a member is created into a family, the family's counted-member tally is reconciled. A member's `waiver_signed` flag records whether the liability waiver is on file and defaults to false until the waiver is signed; signing it sets the flag to true. The crucial design point is that a member tracks two *independent* dimensions: belt progression (which lives on enrollments) and the `account_status` lifecycle, which moves among `ACTIVE`, `FROZEN`, `SUSPENDED`, and `WITHDRAWN`. A member begins `ACTIVE`. The system also maintains `outstanding_balance_cents` per §2.5.

An **instructor** is created with a `full_name`, a globally unique `email` (unique across all instructors), and a `rank_level` of either `INSTRUCTOR` or `CHIEF_INSTRUCTOR` (defaulting to `INSTRUCTOR`). The system tracks each instructor's `is_available` flag, which starts true and indicates whether they are currently accepting class assignments and private lessons.

Freezing a member is a front-desk action available only from `ACTIVE` and guarded by `expected_member_version`. It sets `account_status` to `FROZEN` and **cascades down**: every enrollment of that member whose `status` is `ACTIVE` moves to `ON_HOLD`. Because a `FROZEN` member still counts toward family size, the family's `active_member_count` is reconciled (its value is unchanged by the freeze itself), and the member's `version` increments by 1. Unfreezing is the mirror: available only from `FROZEN` and guarded by `expected_member_version`, it returns `account_status` to `ACTIVE`, moves every `ON_HOLD` enrollment of that member back to `ACTIVE`, and increments `version` by 1.

Withdrawing a member is permanent and is available from `ACTIVE`, `FROZEN`, or `SUSPENDED`, guarded by `expected_member_version`. It sets `account_status` to `WITHDRAWN` and cascades broadly: every non-terminal enrollment (one whose `status` is `ACTIVE` or `ON_HOLD`) is dropped to `DROPPED`; every `ACTIVE` or `PAST_DUE` contract is terminated to `TERMINATED`, and for each such contract whose `months_billed` is still below its `term_months`, one `BUYOUT` invoice is generated (which raises the member's outstanding balance). Because a withdrawn member no longer counts toward the household, the family's `active_member_count` is reconciled downward, which may lower the discount tier applied to that household's *future* contracts. The member's `version` increments by 1. The transitions out of `ACTIVE`, `FROZEN`, and `SUSPENDED` into `WITHDRAWN` all carry these same effects; `WITHDRAWN` is terminal.

Two of the member's status changes are driven by the system rather than the front desk, and they hinge on a balance threshold of 100 dollars — that is, 10000 cents. When invoice generation or an overdue sweep pushes an `ACTIVE` member's `outstanding_balance_cents` strictly above that 10000-cent threshold, the member auto-transitions from `ACTIVE` to `SUSPENDED`. Suspension cascades to billing: every `ACTIVE` contract of that member moves to `PAST_DUE`, and that contract change in turn strips the member's future tournament spots (see §3.7). Conversely, when a payment brings a `SUSPENDED` member's `outstanding_balance_cents` to at most that same 10000-cent threshold, the member auto-transitions from `SUSPENDED` back to `ACTIVE`, and each of that member's `PAST_DUE` contracts whose balance is now clear returns to `ACTIVE`.

### 3.4. Enrollment, Class Scheduling, and Attendance

Enrolling a member into a program is a front-desk action carrying `member_id`, `program_id`, and `expected_member_version` (the optimistic guard of §2.6). A new enrollment is born `ACTIVE`; its `current_rank_code` is initialized to the program's entry rank, its `rank_acquired_at` is set to the current time, and its `rank_attendance_count` starts at 0. Initializing `current_rank_code` requires the program to have an entry rank on file; if the named program has no belt rank flagged as its entry rank, the enrollment cannot be initialized and the request is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Enrollment creates a new `Enrollment` resource only and does not mutate the target member, so the member's `version` is unchanged by an enrollment. A member may hold several enrollments across different programs, and the same enrollment carries the belt progression for that program.

Classes are scheduled as **class sessions**, each naming the `program_id` it teaches and the lead `instructor_id`, with a `starts_at` and an `ends_at` (both ISO 8601 UTC; `ends_at` must be strictly after `starts_at`, or the request fails with `ERR_VALIDATION`, 422) and a `capacity` of at least 1 — the maximum number of confirmed attendances allowed on the mat. A session opens in `SCHEDULED` `status` with `confirmed_count` at 0. The same instructor cannot be in two places at once: a new class session's interval must not overlap any other booking on that instructor, where overlap is judged on the half-open interval from `starts_at` (inclusive) to `ends_at` (exclusive), so back-to-back bookings that merely touch — one's `ends_at` equal to the next's `starts_at` — are allowed; a true overlap is rejected with `ERR_INSTRUCTOR_DOUBLE_BOOKED` (HTTP 409). An instructor may complete a `SCHEDULED` session (guarded by `expected_class_session_version`), moving it to `COMPLETED` and incrementing the session's `version`.

Cancelling a class session is available from `SCHEDULED`, guarded by `expected_class_session_version`. It sets the session's `status` to `CANCELLED` and performs a compensation sweep: every `CONFIRMED` attendance of that session is set to `CANCELLED`, and for each such attendance that had been credited toward rank (its `counts_toward_rank` was true) the owning enrollment's `rank_attendance_count` is decremented by 1, returning the attendance pool to its pre-check-in value; the session's `confirmed_count` is reset to 0; and the session's `version` increments by 1.

Checking a member into a class creates an **attendance** carrying the `enrollment_id` and the `class_session_id`. The attendance is born `CONFIRMED`, and the session's `confirmed_count` is incremented. Whether the check-in actually advances belt progress depends on the member's standing at check-in time: `counts_toward_rank` is set to true — and the enrollment's `rank_attendance_count` is incremented by 1 — only when the member is `ACTIVE` and `waiver_signed` is true at that moment; otherwise the attendance is recorded but does not count toward rank. Several gates protect check-in, and they fail with their own codes: a member whose `waiver_signed` is false is blocked with `ERR_WAIVER_NOT_SIGNED` (HTTP 422); a member whose `account_status` is not `ACTIVE` is blocked with `ERR_MEMBER_NOT_ACTIVE` (HTTP 422); a check-in whose enrollment's `program_id` does not equal the session's `program_id` is rejected with `ERR_PROGRAM_MISMATCH` (HTTP 422); a check-in that would push `confirmed_count` past `capacity` — that is, where the new confirmed count would exceed the session's capacity — is rejected with `ERR_CLASS_FULL` (HTTP 409); and a member who already holds a `CONFIRMED` attendance for that session cannot check in twice, which is rejected with `ERR_ALREADY_CHECKED_IN` (HTTP 409).

Cancelling a single attendance is a front-desk action available while the attendance is `CONFIRMED` and its owning session is still `SCHEDULED`. It sets the attendance `status` to `CANCELLED`, decrements the owning session's `confirmed_count` by 1, and, if the attendance had counted toward rank, decrements the owning enrollment's `rank_attendance_count` by 1 — the exact compensation that undoes the increment the original check-in made.

### 3.5. Testing Eligibility and the Promotion Lifecycle

A member's readiness to grade is summarized by a computed eligibility read over an enrollment, which returns whether the candidate is `eligible`, an integer `readiness` score, and the list of `failed_gates`. Eligibility is an AND of six gates, all of which must hold. First, the enrollment's `rank_attendance_count` must be at least the program's `min_attendance_for_test`. Second, the number of whole days between the enrollment's `rank_acquired_at` and the current time must be at least the program's `min_days_in_rank`. Third, the owning member's `account_status` must be `ACTIVE`. Fourth, the member's `waiver_signed` must be true. Fifth, the member's `outstanding_balance_cents` must be at most 100 dollars — the 10000-cent test-balance ceiling. Sixth, the enrollment's current belt must not be terminal — its `next_rank_code` must be non-null.

The `readiness` score orders eligible candidates and is computed even when a candidate is not eligible. It weights attendance at 40 and time-in-rank at 60. The attendance ratio is `rank_attendance_count` divided by the program's `min_attendance_for_test` (using 1 as the divisor if that minimum is 0), and the days ratio is the whole days in rank divided by `min_days_in_rank` (again using 1 if that minimum is 0); each ratio is clamped to a maximum of 1.0 before weighting. The score is 40 times the clamped attendance ratio plus 60 times the clamped days ratio, rounded half up, and then capped so it never exceeds 100. It is an integer between 0 and 100.

Scheduling a **promotion test** is performed by the front desk or an instructor and carries the `enrollment_id`, the `examiner_instructor_id` who will administer it, and the `scheduled_for` date-time of the sitting. At scheduling the system sets the test's `target_rank_code` to the enrollment's current rank's `next_rank_code`, opens the test in `SCHEDULED` `status`, and generates a `TEST_FEE` invoice for the program's `test_fee_cents`, which raises the member's outstanding balance. Scheduling is heavily gated, and the gates report distinct codes: the member must have signed the waiver, else `ERR_WAIVER_NOT_SIGNED` (HTTP 422); the member's `account_status` must be `ACTIVE`, else `ERR_MEMBER_NOT_ACTIVE` (HTTP 422); the enrollment must be `ACTIVE` and its current belt must have a non-null `next_rank_code` — an enrollment already at a terminal rank, or one that is not `ACTIVE`, is rejected with `ERR_RANK_TERMINAL` (HTTP 422); the member's `outstanding_balance_cents` must not exceed the 10000-cent ceiling, else `ERR_TEST_BALANCE_TOO_HIGH` (HTTP 422); and the attendance-and-time eligibility must hold — specifically, `rank_attendance_count` at least `min_attendance_for_test` and whole days in rank at least `min_days_in_rank` — else `ERR_NOT_ELIGIBLE_FOR_TEST` (HTTP 422). The supplied `scheduled_for` must be a well-formed timestamp. When several of these could fail at once, they are evaluated in the order just given: waiver, then member-active, then rank-terminal, then balance ceiling, then attendance-and-days eligibility.

Grading a `SCHEDULED` test is performed by an instructor (or chief instructor) and records a `score` between 0 and 100 (a score outside that range, or a missing one, fails with `ERR_VALIDATION`, 422). The pass boundary is a score of at least 70 — meeting it exactly passes. The branch then forks on whether the target belt `requires_chief_signoff`. When the score reaches the pass mark and the target rank does **not** require chief signoff, the test moves to `PASSED`, its `score` is recorded, and the promotion is applied immediately. When the score reaches the pass mark and the target rank **does** require chief signoff, the test moves to `PASSED_PENDING_SIGNOFF` with its `score` recorded but **no rank change yet** — the promotion is deferred. When the score is below the pass mark, the test moves to `FAILED` with its `score` recorded, no rank change occurs, and `rank_attendance_count` is left untouched (no compensation is needed).

A test in `PASSED_PENDING_SIGNOFF` waits for a chief instructor to sign off. Signoff is exclusive to a `ChiefInstructor`: the acting instructor's `rank_level` must be `CHIEF_INSTRUCTOR`. Signoff moves the test from `PASSED_PENDING_SIGNOFF` to `PASSED`, records the signing instructor as `chief_signoff_instructor_id`, and applies the promotion at that point. Cancelling a `SCHEDULED` test moves it to `CANCELLED` and runs the fee compensation: the `TEST_FEE` invoice generated at scheduling is voided (its `status` set to `VOID`) and the member's outstanding balance is recomputed, so the ledger returns to its pre-scheduling total.

Applying a promotion — whether immediately on a pass or later on signoff — advances the belt on the enrollment. The enrollment's `current_rank_code` is set to the test's `target_rank_code`, the `rank_acquired_at` is reset to the current time, and `rank_attendance_count` is reset to 0 (the conserved attendance pool is cleared for the new rank). The enrollment normally stays `ACTIVE` through this self-advancing step. The one exception is when the newly acquired belt is itself terminal — that is, the just-acquired rank's `next_rank_code` is null: in that case the enrollment's `current_rank_code` is still set to `target_rank_code`, but the enrollment's `status` also moves to `COMPLETED`, marking the progression finished. A promotion only applies when the enrollment is `ACTIVE` and the test's `target_rank_code` equals the current rank's `next_rank_code`.

### 3.6. Contracts, Recurring Billing, and Buyouts

A **contract** binds a member to recurring tuition for a program. Signing one is a front-desk action carrying `member_id`, `program_id`, a `term_months` chosen from 3, 6, 12, or 24, a `billing_anchor_day` from 1 to 28 (the day of the month the recurring invoice is generated), and the optimistic guard `expected_member_version`. A `term_months` outside the allowed set or a `billing_anchor_day` outside 1 to 28 fails with `ERR_VALIDATION` (HTTP 422). At signing the contract opens `ACTIVE` with `months_billed` at 0 and pins `locked_family_discount_pct` from the *live* family discount tier computed at that instant (§3.2).

Running billing is the contract's cyclic heartbeat. Each run is available while the contract is `ACTIVE`, requires `months_billed` to still be below `term_months`, and requires the owning member to not be `WITHDRAWN`. A run generates one `TUITION` invoice and increments `months_billed` by 1. The tuition amount is computed from the program's `base_monthly_tuition_cents` and the contract's *pinned* `locked_family_discount_pct` (not the live tier): the discount in cents is the base amount times the pinned percentage, rounded half up to whole cents, and the invoice's `amount_due_cents` is the base minus that rounded discount, floored at 0. After the invoice is generated the member's outstanding balance is recomputed; if that pushes the balance past the 10000-cent suspension threshold, the member auto-suspends, which cascades the contract to `PAST_DUE` as described in §3.3. The contract stays `ACTIVE` across runs until the term is met; on the run that bills the final term month — the one where `months_billed` plus 1 equals `term_months` — the final `TUITION` invoice is generated, `months_billed` reaches `term_months`, and the contract transitions to `FULFILLED`.

A contract that has gone `PAST_DUE` because its member was suspended returns to `ACTIVE` automatically once the member's balance is cleared and the member is back to `ACTIVE`.

Terminating a contract early is a front-desk action available from `ACTIVE` or `PAST_DUE`, guarded by `expected_contract_version`. It sets the contract `status` to `TERMINATED`, and, when `months_billed` is still below `term_months`, generates one `BUYOUT` invoice and recomputes the member's balance; the contract's `version` increments by 1. The buyout charge is computed in a pinned evaluation order: first determine the remaining whole months as `term_months` minus `months_billed`; then compute the monthly tuition value exactly as the recurring tuition charge would (which itself uses the contract's pinned `locked_family_discount_pct`); then multiply the remaining months by that monthly value and by the buyout rate of 50 percent, rounding half up; then cap the result so the buyout never exceeds 50000 cents. The **final** buyout — the amount actually charged at terminate or withdraw — uses the contract's pinned discount and is authoritative.

A what-if **buyout quote** lets a member or the front desk preview the cost of leaving without committing. It returns `provisional_buyout_cents`, the `remaining_months`, and the `live_discount_pct`. The provisional figure follows the same evaluation order as the final buyout, but projects the monthly tuition using the *live* family discount tier (the current roster) rather than the pinned percentage, so a provisional quote can legitimately differ from the eventual authoritative charge.

### 3.7. Private Lessons, Tournaments, and the Pro-Shop

A **private lesson** is a one-on-one booking carrying the `member_id`, the `instructor_id`, a `starts_at`, an `ends_at` (strictly after `starts_at`), and an agreed `hourly_rate_cents`. It is requested into `REQUESTED` `status`. Booking is gated on the member being `ACTIVE` (else `ERR_MEMBER_NOT_ACTIVE`, 422), and an `ends_at` not strictly after `starts_at` fails with `ERR_VALIDATION` (422). An instructor confirms a `REQUESTED` lesson only when their `is_available` is true and the lesson's interval does not overlap any of that instructor's other `CONFIRMED` private lessons or `SCHEDULED` class sessions — the same half-open `[starts_at, ends_at)` overlap test used for class scheduling, so adjacency is allowed and a true overlap is rejected with `ERR_INSTRUCTOR_DOUBLE_BOOKED` (HTTP 409); confirmation moves the lesson to `CONFIRMED`. Completing a `CONFIRMED` lesson moves it to `COMPLETED` and generates one `PRIVATE_LESSON` invoice, then recomputes the member's balance. The private-lesson charge is computed by taking the duration in minutes between `starts_at` and `ends_at` (with `ends_at` exclusive), multiplying `hourly_rate_cents` by that duration divided by 60 to get a raw fractional-hour charge, and rounding that raw figure half up exactly once at the end — sum-then-round, the opposite order to the pro-shop. A lesson may be cancelled from `REQUESTED` or `CONFIRMED` (by the member or front desk), moving it to `CANCELLED` and freeing the instructor's interval.

A **tournament registration** enters a member into a competition carrying the `member_id`, the `enrollment_id` under which they compete (which determines the competing rank and division), the `tournament_name` (1 to 120 characters), and the `event_date`. It is created in `REGISTERED` `status`, and the system computes the `division` from the member's `date_of_birth` relative to the `event_date`: the age in whole completed years is taken, and a competitor under 13 is `YOUTH`, one who is 13 to 17 is `TEEN`, one who is 18 to 39 is `ADULT`, and one who is 40 or older is `MASTERS`. The boundaries are inclusive at the lower edge: a competitor who turns exactly 18 on the event date is `ADULT`, not `TEEN`, and one who turns exactly 13 is `TEEN`, not `YOUTH`. Registration is gated: the member must have a signed waiver (else `ERR_WAIVER_NOT_SIGNED`, 422), must be `ACTIVE` (else `ERR_MEMBER_NOT_ACTIVE`, 422), and the `event_date` must be strictly in the future relative to the current clock (else `ERR_EVENT_IN_PAST`, 422). A registration may be withdrawn by the member or front desk, moving it to `WITHDRAWN`. Withdrawal also happens automatically as a cascade: when a member is suspended and their contracts go `PAST_DUE`, every still-`REGISTERED` registration of that member whose `event_date` is in the future is withdrawn to `WITHDRAWN`, stripping the suspended member's competition eligibility.

A **pro-shop order** is placed by a member or the front desk carrying the `member_id` and the `line_items` array; an empty `line_items`, or a line with a `qty` below 1 or a negative `unit_price_cents`, fails with `ERR_VALIDATION` (422). On creation the system computes `gross_cents` and `net_cents` per the pro-shop pricing discipline of §2.8 and opens the order in `PLACED` `status`. Fulfilling a `PLACED` order is a front-desk action that moves it to `FULFILLED`, generates one `PRO_SHOP` invoice for the order's `net_cents`, and recomputes the member's balance. A `PLACED` order may instead be cancelled (by the member or front desk) to `CANCELLED`.

### 3.8. Invoices, Payment, and the Overdue Sweep

Every charge in the system materializes as an **invoice** carrying the `member_id` responsible, an optional `contract_id` (set on recurring tuition, null on ad-hoc charges such as a test fee, pro-shop sale, or buyout), a `kind` drawn from `TUITION`, `TEST_FEE`, `PRO_SHOP`, `BUYOUT`, or `PRIVATE_LESSON`, the computed `amount_due_cents` (immutable once generated and never negative), and a `due_at` after which it becomes overdue. An invoice opens `DUE`.

Paying an invoice is available while it is `DUE` or `OVERDUE` and moves it to `PAID`, then recomputes the member's outstanding balance; if that recomputation brings the balance to at most the 10000-cent threshold, the member auto-unsuspends and the cascade described in §3.3 returns their `PAST_DUE` contracts to `ACTIVE`. Waiving an invoice (front-desk only) is available while it is `DUE` or `OVERDUE`, moves it to `WAIVED`, and recomputes the balance, removing that invoice from the unpaid sum. Marking an invoice overdue moves a `DUE` invoice to `OVERDUE` when the current clock time has passed its `due_at`; this does not by itself change `amount_due_cents`. An invoice may also reach `VOID` through the test-cancellation compensation described in §3.5.

Because several rules depend on the passage of time — invoices going overdue, tournament dates falling into the past — the system exposes a test-driving capability that sets the server's logical clock to a supplied instant. It accepts a `to_iso8601` timestamp and reports back the new `current_utc`. After the clock advances, the overdue sweep can move past-due invoices to `OVERDUE`, which in turn can raise balances and trigger the suspension cascade.

## 4. Endpoint Definitions

All endpoints are mounted under `/dojo`. Creation endpoints return HTTP 201 with the newly created resource; reads and state-changing actions on existing resources return HTTP 200 with the affected resource (or the computed payload for the read-only eligibility, quote, and clock endpoints). Request and response payloads are not repeated here — reconstruct them from the workflow narratives in Section 3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/dojo/programs` | Create a martial-arts program | FrontDesk |
| GET | `/dojo/programs/{id}` | Fetch a program | FrontDesk, Instructor, ChiefInstructor, Member |
| GET | `/dojo/programs` | List programs (paginated) | FrontDesk, Instructor, ChiefInstructor, Member |
| POST | `/dojo/programs/{id}/archive` | Archive a program | FrontDesk |
| POST | `/dojo/programs/{id}/belt-ranks` | Add a belt rank to a program's progression chain | FrontDesk |
| GET | `/dojo/programs/{id}/belt-ranks` | List the belt ranks of a program | FrontDesk, Instructor, ChiefInstructor, Member |
| POST | `/dojo/families` | Create a family household | FrontDesk |
| GET | `/dojo/families/{id}` | Fetch a family with computed active member count | FrontDesk, Member |
| POST | `/dojo/members` | Register a member | FrontDesk |
| GET | `/dojo/members/{id}` | Fetch a member with computed balance | FrontDesk, Instructor, ChiefInstructor, Member |
| GET | `/dojo/members` | List members | FrontDesk |
| POST | `/dojo/members/{id}/sign-waiver` | Record the member's signed waiver | FrontDesk, Member |
| POST | `/dojo/members/{id}/freeze` | Freeze a member account | FrontDesk |
| POST | `/dojo/members/{id}/unfreeze` | Reactivate a frozen member | FrontDesk |
| POST | `/dojo/members/{id}/withdraw` | Withdraw a member | FrontDesk |
| POST | `/dojo/instructors` | Create an instructor | FrontDesk |
| GET | `/dojo/instructors/{id}` | Fetch an instructor | FrontDesk, Instructor, ChiefInstructor, Member |
| GET | `/dojo/instructors` | List instructors | FrontDesk, Member |
| POST | `/dojo/enrollments` | Enroll a member into a program at its entry rank | FrontDesk |
| GET | `/dojo/enrollments/{id}` | Fetch an enrollment | FrontDesk, Instructor, ChiefInstructor, Member |
| GET | `/dojo/enrollments` | List enrollments | FrontDesk, Instructor, ChiefInstructor, Member |
| GET | `/dojo/enrollments/{id}/test-eligibility` | Computed testing eligibility and readiness | FrontDesk, Instructor, ChiefInstructor, Member |
| POST | `/dojo/class-sessions` | Schedule a class session | FrontDesk, Instructor |
| GET | `/dojo/class-sessions/{id}` | Fetch a class session | FrontDesk, Instructor, ChiefInstructor, Member |
| GET | `/dojo/class-sessions` | List class sessions | FrontDesk, Instructor, ChiefInstructor, Member |
| POST | `/dojo/class-sessions/{id}/cancel` | Cancel a scheduled class | FrontDesk, Instructor |
| POST | `/dojo/class-sessions/{id}/complete` | Mark a class completed | Instructor |
| POST | `/dojo/attendances` | Check a member into a class | FrontDesk, Member |
| GET | `/dojo/attendances/{id}` | Fetch an attendance | FrontDesk, Instructor, ChiefInstructor, Member |
| GET | `/dojo/attendances` | List attendances | FrontDesk, Instructor, ChiefInstructor, Member |
| POST | `/dojo/attendances/{id}/cancel` | Cancel a single attendance | FrontDesk |
| POST | `/dojo/promotion-tests` | Schedule a promotion test | FrontDesk, Instructor |
| GET | `/dojo/promotion-tests/{id}` | Fetch a promotion test | FrontDesk, Instructor, ChiefInstructor, Member |
| GET | `/dojo/promotion-tests` | List promotion tests | FrontDesk, Instructor, ChiefInstructor, Member |
| POST | `/dojo/promotion-tests/{id}/grade` | Grade a test | Instructor, ChiefInstructor |
| POST | `/dojo/promotion-tests/{id}/signoff` | Chief instructor signs off a pending pass | ChiefInstructor |
| POST | `/dojo/promotion-tests/{id}/cancel` | Cancel a scheduled test | FrontDesk, Instructor |
| POST | `/dojo/contracts` | Sign a recurring-tuition contract | FrontDesk |
| GET | `/dojo/contracts/{id}` | Fetch a contract | FrontDesk, Member |
| GET | `/dojo/contracts` | List contracts | FrontDesk, Member |
| GET | `/dojo/contracts/{id}/buyout-quote` | What-if provisional buyout quote | FrontDesk, Member |
| POST | `/dojo/contracts/{id}/run-billing` | Generate the next recurring tuition invoice | FrontDesk |
| POST | `/dojo/contracts/{id}/terminate` | Terminate a contract early | FrontDesk |
| GET | `/dojo/invoices/{id}` | Fetch an invoice | FrontDesk, Member |
| GET | `/dojo/invoices` | List invoices | FrontDesk, Member |
| POST | `/dojo/invoices/{id}/pay` | Pay an invoice | FrontDesk, Member |
| POST | `/dojo/invoices/{id}/waive` | Waive an invoice | FrontDesk |
| POST | `/dojo/invoices/{id}/mark-overdue` | Mark a due invoice overdue | FrontDesk |
| POST | `/dojo/private-lessons` | Request a private lesson | FrontDesk, Member |
| GET | `/dojo/private-lessons/{id}` | Fetch a private lesson | FrontDesk, Instructor, ChiefInstructor, Member |
| GET | `/dojo/private-lessons` | List private lessons | FrontDesk, Instructor, ChiefInstructor, Member |
| POST | `/dojo/private-lessons/{id}/confirm` | Confirm a requested lesson | Instructor |
| POST | `/dojo/private-lessons/{id}/complete` | Complete a confirmed lesson | Instructor |
| POST | `/dojo/private-lessons/{id}/cancel` | Cancel a requested/confirmed lesson | Member, FrontDesk |
| POST | `/dojo/tournament-registrations` | Register a member for a tournament | FrontDesk, Member |
| GET | `/dojo/tournament-registrations/{id}` | Fetch a tournament registration | FrontDesk, Member |
| GET | `/dojo/tournament-registrations` | List tournament registrations | FrontDesk, Member |
| POST | `/dojo/tournament-registrations/{id}/withdraw` | Withdraw from a tournament | Member, FrontDesk |
| POST | `/dojo/pro-shop-orders` | Place a pro-shop gear order | FrontDesk, Member |
| GET | `/dojo/pro-shop-orders/{id}` | Fetch a pro-shop order | FrontDesk, Member |
| GET | `/dojo/pro-shop-orders` | List pro-shop orders | FrontDesk, Member |
| POST | `/dojo/pro-shop-orders/{id}/fulfill` | Fulfill a pro-shop order | FrontDesk |
| POST | `/dojo/pro-shop-orders/{id}/cancel` | Cancel a placed pro-shop order | Member, FrontDesk |
| POST | `/dojo/_clock/advance` | Test-driving: set the server's UTC clock | FrontDesk |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_FK_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_DUPLICATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_STATE | 409 |
| ERR_WAIVER_NOT_SIGNED | 422 |
| ERR_MEMBER_NOT_ACTIVE | 422 |
| ERR_RANK_TERMINAL | 422 |
| ERR_NOT_ELIGIBLE_FOR_TEST | 422 |
| ERR_INSTRUCTOR_DOUBLE_BOOKED | 409 |
| ERR_PROGRAM_MISMATCH | 422 |
| ERR_CLASS_FULL | 409 |
| ERR_ALREADY_CHECKED_IN | 409 |
| ERR_EVENT_IN_PAST | 422 |
| ERR_TEST_BALANCE_TOO_HIGH | 422 |
| ERR_VALIDATION | 422 |
