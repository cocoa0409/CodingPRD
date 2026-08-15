# Community Choir & Ensemble Management API — Product Requirements Document

## 1. Introduction

Running a community chorus is a logistically demanding volunteer operation: singers audition into voice-part sections that must balance, dues must be collected alongside a confidential scholarship program, rehearsal attendance determines who may step on stage, a lending library of physical scores leaks copies to forgetful members, concerts require venue contracts and guest musicians whose fees pass through negotiation, approval, and payment by three different officers, tours split costs across a locked roster, and fundraising committees collect pledges under segregation-of-duties controls. Today most choruses run all of this out of spreadsheets and email threads, and the failure modes are familiar — an over-enrolled alto section discovered the week before rehearsals start, a scholarship reserve accidentally spent twice, a venue deposit refunded after it was already committed.

This document specifies a single REST API that runs the entire operation as one coherent system. The Season is the organizing spine: its posture (from `DRAFT` through `ARCHIVED`) gates which operations are legal at which point in the year, and a single logical clock drives every deadline, overdue sweep, and refund window. Money is tracked in exactly two places — a per-season treasury ledger and a scholarship pool ledger with a strict conservation invariant — and every workflow that moves money, fills a seat, or locks a program is described here in terms an engineer can implement without further interpretation.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The system recognizes exactly five roles, spelled as follows: `President`, `Treasurer`, `ChoirDirector`, `Librarian`, and `Member`. A request missing either header, or presenting a role outside this list, is rejected with `ERR_UNAUTHENTICATED`. An authenticated caller attempting an operation that their role is not permitted to perform is rejected with `ERR_FORBIDDEN`.

When `X-User-Role` is `President`, `Treasurer`, `ChoirDirector`, or `Librarian`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `decided_by_user_id` on a decided scholarship grant, `approved_by_user_id` and `paid_by_user_id` on a guest contract, `excused_by_user_id` on an excused attendance record, or `recorded_by_user_id` and `fulfilled_by_user_id` on a pledge — but it never compares the value against any entity's `id`.

When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting Member; ownership checks on any resource that references a Member compare the resource's `member_id` field to `X-User-ID`. A `Member` caller may touch only their own record, their own invoices and payments, their own scholarship grants, their own attendance records, their own score checkouts, and their own tour registrations; acting on a resource owned by a different member is rejected with `ERR_FORBIDDEN_OWNERSHIP`.

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

List endpoints accept two query parameters. `limit` sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets the number of items skipped and defaults to 0. Unless otherwise specified, list endpoints return resources sorted by `created_at` in ascending order. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

Every temporal rule in this document — early-bird cutoffs, dues deadlines, overdue sweeps, booking lead times, refund windows, audition expiry — is evaluated against a single server-side logical clock, never against wall-clock time. At server startup, before any call, the clock reads exactly `2026-08-01T00:00:00Z`. A `President` advances it through a test-driving capability that sets the current instant to a supplied `to_iso8601` value; the response reports the resulting `current_utc`. Once set, the clock holds the supplied instant until it is set again; it never falls back to wall-clock time. Timestamps written by the system (`issued_at`, `received_at`, `checked_out_at`, `enrolled_at`, `returned_at`) are always taken from this clock.

### 2.5. Common Resource Properties

Every resource type in the system — Season, Section, Member, Audition, DuesInvoice, DuesPayment, ScholarshipGrant, Rehearsal, AttendanceRecord, MusicScore, ScoreCheckout, Venue, Concert, VenueBooking, ProgramPiece, GuestContract, TourTrip, TourRegistration, Committee, and FundraiserPledge — carries the same four system-managed fields. `id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created. `updated_at` is an ISO 8601 UTC timestamp, again with three fractional digits, refreshed on every mutation. `version` is a system-managed integer that increments by one on every modification of the resource. A mutation is any change to the resource's fields, whether client-initiated or system-driven — a posture advance on a Season, a counter-offer on a GuestContract, a recomputed `active_count` on a Section all refresh `updated_at` and increment `version` on the affected resource.

### 2.6. Monetary Precision, Rates, and Rounding

All monetary values in the system are represented as integer cents. Where a calculation produces a fractional cent — an early-bird discount, a tour share, a cancellation fee, a refund — the result is rounded half up to the nearest integer cent. Two non-monetary computed fields have their own precision contracts: an audition's `composite_score` is rounded to 2 decimal places, round half up, and a member's `attendance_rate` is rounded to 4 decimal places, round half up. Fractional configuration inputs such as `early_bird_pct` and `attendance_threshold` are stored exactly as supplied (for example, 0.10 for a ten-percent discount, 0.75 for a seventy-five-percent attendance bar).

### 2.7. Optimistic Concurrency Control

Three write endpoints are guarded by optimistic concurrency control, and each takes a mandatory version-witness field; no other endpoint accepts a version field.

Updating a Season's configuration requires `expected_season_version`, carrying the caller's last observed `version` of that Season. If the Season's current `version` has advanced since the caller read it — another writer may have legitimately changed dues policy or checkpointed the season in between — the update is rejected with `ERR_STALE_VERSION` (HTTP 412) and the caller must re-read before writing.

Running the ops checkpoint likewise requires `expected_season_version`. Each successful checkpoint legitimately advances `ops_week_index` and the Season's `version`, so a request carrying an older observed `version` is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than double-applying epoch side effects.

Recording a counter-offer on a guest contract requires `expected_guest_contract_version`. A counter-offer legitimately supersedes the terms of the current offer, so when the GuestContract's `version` has advanced beyond the value the caller observed, the counter is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than silently overwriting newer terms.

### 2.8. Validation Order and Error Precedence

When a request violates several rules at once, the error it receives is determined by a fixed pipeline of validation tiers, evaluated in the following order. First, authentication: the headers are present and the role is declared, else `ERR_UNAUTHENTICATED`. Second, role authorization, else `ERR_FORBIDDEN`. Third, member-ownership scoping, else `ERR_FORBIDDEN_OWNERSHIP`. Fourth, existence: resource ids appearing in the path and in the body are validated left to right, and the first id that does not resolve to an existing resource yields `ERR_NOT_FOUND`. Fifth, request shape: missing required fields, wrong types, and unknown fields are rejected with `ERR_INVALID_REQUEST`, and an enum field carrying an undeclared value is rejected with `ERR_INVALID_ENUM`. Sixth, the optimistic-concurrency check, else `ERR_STALE_VERSION`. Seventh, season posture gating: `ERR_SEASON_POSTURE` when the posture does not permit the operation and `ERR_SEASON_TERMINAL` when the season is archived. Eighth, target-state validity — the resource must be in a legal from-state for the requested transition or action, else `ERR_INVALID_STATE` or the more specific state-tier error named for that operation. Ninth, business safety rules (eligibility, score thresholds, segregation of duties). Tenth, referential gates on linked resources. Eleventh, business constraints (uniqueness, capacity, overlap). Twelfth, temporal rules (lead times and clock comparisons). Thirteenth and last, fiscal rules (treasury coverage, pool sufficiency, overpayment). A failure in an earlier tier masks every later check, so a caller always sees the highest-priority applicable error.

### 2.9. Season Posture as a Global Gate

Every Season carries a `posture` field cycling through `DRAFT`, `OPEN`, `REHEARSING`, `CONCERT_LOCK`, and `ARCHIVED`, and posture gates every season-scoped write in the system. Membership, audition, and dues writes require the season to be `OPEN` or `REHEARSING` unless a more specific rule in §3 says otherwise. Rehearsal and attendance writes require `REHEARSING` or later. Library checkouts and tour writes require `OPEN` or later. A season-scoped write that the current posture does not permit is rejected with `ERR_SEASON_POSTURE`. Once a season reaches `ARCHIVED`, every write against it is rejected with `ERR_SEASON_TERMINAL`.

### 2.10. Treasury Conservation and Segregation of Duties

Each Season owns a cash ledger, exposed as the computed `treasury_balance_cents`, which starts at zero when the season is created. The balance is defined, scoped to a single season, as: the sum of `amount_cents` over dues payments in `POSTED` status, minus the sum of `amount_cents` over dues payments in `REFUNDED` status, plus the sum of `amount_cents` over pledges in `FULFILLED` status, minus the sum of `amount_cents` over pledges in `REFUNDED` status, minus the `deposit_cents` of venue bookings in `CONFIRMED` status, plus the `deposit_cents` of bookings that have moved from `CONFIRMED` to `RELEASED`, minus the `quoted_fee_cents` of guest contracts in `PAID` status, minus the `cancellation_fee_cents` of contracts cancelled after acceptance, plus the `deposit_paid_cents` of tour registrations in `CONFIRMED` status, minus the `refund_cents` of registrations in `CANCELLED` or `REFUNDED` status. Every fiscal event is reflected in this ledger immediately.

Two integrity rules govern every debit and every two-person workflow. Any operation that would debit more than the season's current `treasury_balance_cents` — confirming a booking deposit, paying a contract, posting a cancellation fee, refunding a payment, pledge, or registration — is rejected with `ERR_INSUFFICIENT_TREASURY`. And on the two segregated workflows, the two hands must differ: the Treasurer who pays a guest contract may not be the user recorded as its `approved_by_user_id`, and the Treasurer who fulfills a pledge may not be the user recorded as its `recorded_by_user_id`; either violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

### 2.11. Derived State, Bubble-Ups, and Cascades

Many state changes in this system are produced by the server rather than requested by a client. When a child resource crosses a threshold that satisfies or violates its parent's conditions, the parent moves: a concert rises from `PLANNING` to `VENUE_BOOKED` when its booking is confirmed, and a member rises from `ENROLLED` to `ACTIVE` when their dues balance reaches zero. When a parent is torn down, the change cascades downward: cancelling a concert releases its booking, voids its program pieces, and cancels the contracts attached to those pieces. Each bubble-up or cascade step is a real mutation of the affected resource — `updated_at` refreshes and `version` increments on every resource the cascade touches — and computed fields downstream (section `active_count`, member `performance_eligible`, concert `program_duration_seconds`, committee `raised_cents`) are recomputed as part of the same operation.

## 3. Business Logic & Workflows

### 3.1. Season Configuration, Posture, and the Ops Checkpoint

A `President` opens the year by creating a Season with a display `name` and the season's full fiscal and policy configuration: `base_dues_cents` (the dues amount before any discount), `early_bird_pct` (the early-bird discount as a fraction, such as 0.10), `early_bird_cutoff` (payments received at or before this instant keep the discount), `dues_due_date` (after which an invoice with a positive balance becomes overdue), `late_fee_weekly_cents` and `late_fee_cap_cents` (the weekly late fee and its ceiling), and `scholarship_pool_cents` (the season's initial scholarship fund). Two policy knobs are optional: `audition_slot_minutes`, the fixed audition slot length defaulting to 30, and `attendance_threshold`, the minimum attendance rate for performance eligibility defaulting to 0.75. A new season is born in `DRAFT` posture with `ops_week_index` at 0, `pool_available_cents` equal to `scholarship_pool_cents`, `pool_reserved_cents` and `pool_spent_cents` at zero, and an empty treasury.

Season configuration can later be revised through an OCC-guarded update carrying `expected_season_version` plus any subset of the same fields (`name`, `base_dues_cents`, `early_bird_pct`, `early_bird_cutoff`, `dues_due_date`, `late_fee_weekly_cents`, `late_fee_cap_cents`, `scholarship_pool_cents`, `audition_slot_minutes`, `attendance_threshold`); each successful update increments the Season's `version` by one.

Posture advances under the President's hand, each successful transition incrementing the Season's `version` by one. From `DRAFT`, the season may move to `OPEN` unconditionally, or directly to `ARCHIVED`. Moving from `OPEN` to `REHEARSING` is gated on the voice-part balance: every Section of the season whose `status` is `OPEN` must satisfy the balance gate — its `active_count` must be at least `target_min` and at most `target_max` — or the advance is rejected with `ERR_SECTION_UNBALANCED`; separately, if any audition of the season is still `SCHEDULED`, the advance is rejected with `ERR_AUDITIONS_PENDING`. Sections in `CLOSED` status are skipped by this gate entirely. From `REHEARSING` the season moves to `CONCERT_LOCK` without preconditions, and from `CONCERT_LOCK` to `ARCHIVED` only when every concert of the season has reached `PERFORMED` or `CANCELLED` — otherwise `ERR_CONCERTS_OPEN`.

The President also runs the season's ops checkpoint, an OCC-guarded sweep that bumps `ops_week_index` by one, increments the Season's `version`, and applies every epoch rule in one pass: expiring stale auditions to `NO_SHOW`, sweeping unpaid invoices to `OVERDUE` with late-fee accrual and member suspension, running the attendance probation sweep, promoting from the member and tour waitlists, and sweeping library checkouts to `OVERDUE` with fine accrual. Each sweep is specified in the subsection that owns it.

Sections themselves are managed by the `ChoirDirector`, who creates one per voice part with a `season_id`, a `voice_part` of `SOPRANO`, `ALTO`, `TENOR`, or `BASS`, and the staffing targets `target_min` and `target_max`. The same voice part may not be created twice within a season — the duplicate is rejected with `ERR_DUPLICATE_SECTION`. A section starts in `OPEN` status with an `active_count` of zero; the director can later update `target_min` or `target_max`, or flip the section between `OPEN` and `CLOSED`. Closing a section both exempts it from the `OPEN` → `REHEARSING` balance gate and bars new audition acceptances into it. A section's `active_count` counts its members whose status is `ENROLLED`, `ACTIVE`, or `PROBATION`, and is recomputed whenever membership changes.

### 3.2. Auditions, Enrollment, and the Member Lifecycle

A singer enters the system when the `ChoirDirector` registers them with a `season_id`, `full_name`, and `email`. The email must be unique among members of that season; a duplicate registration is rejected with `ERR_DUPLICATE_MEMBERSHIP`. A new member starts as an `APPLICANT` with `attendance_rate` at 1.0, `performance_eligible` false, and no `section_id`.

Booking an audition requires the member to be an `APPLICANT` and the season to be `OPEN`; the director supplies the `member_id` and a `scheduled_at` instant in the logical-clock domain. Audition slots are buffered: any two non-cancelled auditions of the same season must start at least `audition_slot_minutes` apart, so a new slot landing closer than that to an existing non-cancelled audition — in either direction — is rejected with `ERR_AUDITION_OVERLAP`. A booked audition starts in `SCHEDULED` status and the member moves from `APPLICANT` to `AUDITION_SCHEDULED`. If the singer cancels, the audition moves to `CANCELLED` and the member falls back to `APPLICANT`. If the slot passes unheld — at a checkpoint, an audition whose `scheduled_at` is earlier than the clock and which is still `SCHEDULED` — the audition becomes `NO_SHOW` and the member likewise returns to `APPLICANT`. Both `CANCELLED` and `NO_SHOW` are terminal for the audition.

After the audition, the director records three integer scores — `tone_score`, `pitch_score`, and `sight_score`, each from 0 to 10. The system computes `composite_score` as forty percent of the tone score, plus thirty-five percent of the pitch score, plus twenty-five percent of the sight score, rounded half up to two decimal places. Scoring moves the audition from `SCHEDULED` to `COMPLETED` and the member from `AUDITION_SCHEDULED` to `AUDITIONED`.

The decision step takes a `decision` of `ACCEPT`, `WAITLIST`, or `REJECT` and writes the audition's `decision` field (which starts as `NONE` and becomes `ACCEPTED`, `WAITLISTED`, or `REJECTED`); the audition's own status stays `COMPLETED`. The checks surface in validation-tier order: the audition must be `COMPLETED` before any decision, else `ERR_AUDITION_NOT_SCORED`; for `ACCEPT` or `WAITLIST` the composite must be at least 7.0, else `ERR_SCORE_BELOW_THRESHOLD`; for `ACCEPT` the caller names a target `section_id` whose status must be `OPEN`, else `ERR_SECTION_CLOSED`; and only then is the section's headroom checked, with a section whose `active_count` has reached `target_max` rejected as `ERR_SECTION_FULL`. An acceptance moves the member to `ENROLLED`, sets the member's `section_id`, stamps `enrolled_at` from the clock, and recomputes the section's `active_count`. A waitlist decision moves the member to `WAITLISTED`; a rejection moves them to `REJECTED`, which is terminal.

Waitlisted singers are promoted automatically at each checkpoint, provided an `OPEN` section exists with `active_count` below `target_max`. Candidates are ranked by the `composite_score` of their completed audition, highest first, with ties broken by the audition's `created_at`, earliest first. Each candidate in rank order is assigned to the `OPEN` section with the largest gap between `target_max` and `active_count` among sections with a positive gap, ties broken by the section's `created_at`, earliest first; promotion stops when no positive-gap `OPEN` section remains. An empty candidate set or a season with no gap is a silent no-op, not an error. A promoted member moves from `WAITLISTED` to `ENROLLED` with `section_id` set and `enrolled_at` stamped. The director can also drop a `WAITLISTED` member outright, moving them to `REJECTED`.

### 3.3. Rehearsals, Attendance, and Member Standing

Once the season is `REHEARSING` or later, the `ChoirDirector` schedules rehearsals with a `season_id`, a `scheduled_at` instant, and an optional free-form `location`; a new rehearsal is `SCHEDULED`. Cancelling a rehearsal moves it to `CANCELLED` and removes it from every attendance calculation. Attendance is recorded in bulk: the director submits `records`, a list pairing each `member_id` with a `status` of `PRESENT`, `LATE`, `ABSENT_UNEXCUSED`, or `ABSENT_EXCUSED`. The rehearsal must already have taken place — its `scheduled_at` at or before the clock — or the recording is rejected with `ERR_REHEARSAL_NOT_HELD`, and a member may appear only once per rehearsal, else `ERR_DUPLICATE_ATTENDANCE`. Recording moves the rehearsal from `SCHEDULED` to `COMPLETED` and creates one AttendanceRecord per entry, after which each recorded member's `attendance_rate` is recomputed.

The `attendance_rate` is a weighted fraction over the member's counted rehearsals: the season's `COMPLETED` rehearsals scheduled at or after the member's `enrolled_at` (cancelled rehearsals excluded). If that set is empty, the rate is 1.0. Otherwise the numerator weights each record — full credit for `PRESENT`, half credit (0.5) for `LATE`, three-quarter credit (0.75) for `ABSENT_EXCUSED`, and zero for `ABSENT_UNEXCUSED` — and the denominator is the number of counted rehearsals, where a counted rehearsal in which the member has no record contributes zero, exactly as an unexcused absence does. The result is rounded half up to four decimal places. The only permitted edit to a recorded mark is excusing it: the director converts `ABSENT_UNEXCUSED` to `ABSENT_EXCUSED`, the record captures who excused it in `excused_by_user_id`, and the member's rate is recomputed; every other record value is final once the rehearsal is `COMPLETED`.

Performance eligibility is a three-way conjunction recomputed whenever any input changes: `performance_eligible` is true exactly when the member's status is `ACTIVE`, their `attendance_rate` is at least the season's `attendance_threshold`, and their `dues_balance_cents` is zero. The rate boundary is inclusive — a member exactly at the threshold qualifies.

Standing moves on its own as evidence arrives. When a member's first dues invoice reaches `PAID` or `WAIVED` and their `dues_balance_cents` is zero, an `ENROLLED` member bubbles up to `ACTIVE`. At each checkpoint's attendance sweep, an `ACTIVE` member whose `attendance_rate` has fallen below the threshold drops to `PROBATION`, and a `PROBATION` member whose rate is back at or above the threshold with a zero dues balance returns to `ACTIVE`. The checkpoint's overdue sweep suspends: an `ACTIVE` or `PROBATION` member carrying an `OVERDUE` invoice moves to `SUSPENDED`. Independently of any invoice state, the director can also suspend an `ACTIVE` or `PROBATION` member manually. Reinstatement — whether by the system once every overdue invoice has been cured, or by the director's reinstate action — requires `dues_balance_cents` of zero and an `attendance_rate` at or above the threshold, and moves the member from `SUSPENDED` back to `ACTIVE`. The director's member-status action accepts an `action` of `DROP`, `SUSPEND`, or `REINSTATE`.

Departure cascades. A director's drop moves a member from `ENROLLED`, `ACTIVE`, `PROBATION`, or `SUSPENDED` to `DROPPED`; resignation, available to the member themselves or to the director, moves the same four states to `RESIGNED`. Both run the same member-drop cascade: any score checkout still `CHECKED_OUT` or `OVERDUE` is marked `LOST` with the charges described in §3.5 posted to the member's ledger; the member's non-terminal tour registrations are cancelled and the freed seats trigger waitlist promotion; and the section's `active_count` is recomputed. Every standing change — probation, suspension, reinstatement, activation, departure — recomputes `performance_eligible`. `REJECTED`, `DROPPED`, and `RESIGNED` are terminal.

### 3.4. Dues, Payments, Scholarships, and the Treasury

The `Treasurer` issues a dues invoice for a member who is `ENROLLED` or later, supplying just the `member_id`; the invoice copies the member's `season_id`, stamps `issued_at` from the clock, computes its `provisional_amount_cents`, and opens in `ISSUED` status with `scholarship_applied_cents`, `paid_cents`, and `late_fee_cents` all at zero. Dues pricing has two variants. The provisional amount, fixed at issuance, keys the early-bird discount on the invoice itself: when `issued_at` falls at or before the season's `early_bird_cutoff`, the provisional amount is the `base_dues_cents` discounted by `early_bird_pct` and rounded half up to integer cents; after the cutoff it is simply `base_dues_cents`. The final amount is revealed later, at the first payment or first scholarship application against the invoice, and keys the discount on money actually received: the discount is earned only when the payment's `received_at` falls at or before `early_bird_cutoff`, yielding the same discounted formula when earned and `base_dues_cents` when not. The variants diverge exactly when an invoice issued before the cutoff is first paid after it — the provisional assumes the discount and the final removes it, so `final_amount_cents` can exceed `provisional_amount_cents`. An invoice's `balance_cents` is its `final_amount_cents`, minus `scholarship_applied_cents`, minus `paid_cents`, plus `late_fee_cents`, and a member's `dues_balance_cents` is the sum of `balance_cents` over their invoices that have not reached a terminal state.

Payments run a waterfall. The Treasurer records a payment with `member_id`, `amount_cents`, and a `method` of `CASH`, `CHECK`, or `CARD`; the payment's `received_at` is stamped from the clock and drives the early-bird determination. On creation, the system first reveals `final_amount_cents` on any of the member's invoices that have not yet revealed it. It then walks the member's open invoices — those in `ISSUED`, `PARTIAL`, or `OVERDUE` — ordered by `issued_at` ascending with ties broken by `created_at` ascending, taking from each the lesser of the remaining payment and that invoice's `balance_cents`, and appending each take to the payment's `allocations` as an `invoice_id` / `amount_cents` pair. If anything remains after every open invoice is satisfied, the entire payment is rejected with `ERR_OVERPAYMENT` and nothing is written — no partial allocation survives. On success the payment is `POSTED`, the treasury is credited, and each allocated invoice moves: an allocation covering only part of the balance moves `ISSUED` to `PARTIAL`, while one that zeroes the balance moves the invoice to `PAID`. `PAID` and `WAIVED` are terminal. Whenever an invoice reaches `PAID` or `WAIVED`, the member's `ENROLLED` → `ACTIVE` bubble-up and `dues_balance_cents` recomputation run.

Refunds unwind symmetrically. Refunding a `POSTED` payment requires the treasury to cover the payment's `amount_cents`, else `ERR_INSUFFICIENT_TREASURY`; the treasury is debited, every allocated invoice's `paid_cents` is reduced, and any invoice that was `PAID` reopens to `ISSUED`. If a refunded invoice reopens, a member who had risen to `ACTIVE` is demoted back to `ENROLLED` as compensation, and `performance_eligible` is recomputed.

At each checkpoint, invoices in `ISSUED` or `PARTIAL` whose season's `dues_due_date` is earlier than the clock and whose `balance_cents` is still positive move to `OVERDUE`, and the late fee accrues: the number of full weeks overdue is the count of whole seven-day periods between `dues_due_date` and now, never below zero — exactly seven days overdue counts as one full week — and `late_fee_cents` is the lesser of the season's `late_fee_cap_cents` and the weeks overdue multiplied by `late_fee_weekly_cents`. An invoice moving to `OVERDUE` suspends an `ACTIVE` or `PROBATION` member. Payment can still cure it: zeroing an `OVERDUE` invoice's balance, late fee included, moves it to `PAID`, and once a suspended member's last overdue invoice is cured, they return to `ACTIVE` if their attendance also meets the threshold.

Scholarships run against the season's pool, which obeys a strict conservation invariant: at every instant, `scholarship_pool_cents` equals `pool_available_cents` plus `pool_reserved_cents` plus `pool_spent_cents`. A member may request a grant for themselves, or the Treasurer may file on their behalf, supplying `member_id`, `requested_cents`, and an optional free-form `need_note`; the grant copies the member's `season_id` and opens in `REQUESTED` status. The Treasurer then decides. Approval takes an optional explicit `approved_cents` that defaults to the lesser of `requested_cents` and the season's `pool_available_cents`; the approved amount must be positive and no greater than `pool_available_cents`, else `ERR_SCHOLARSHIP_POOL_EXHAUSTED`. Approval reserves the funds — `pool_reserved_cents` grows by `approved_cents` and `pool_available_cents` shrinks by the same — records `decided_by_user_id`, and moves the grant to `APPROVED`. Rejection simply records `decided_by_user_id` and moves the grant to `REJECTED`, which is terminal.

Applying a grant is the state tier's most carefully ordered operation: the grant's own status is checked first — it must be `APPROVED`, else `ERR_GRANT_NOT_APPROVED` — and only then is the target invoice examined, which must be in `ISSUED`, `PARTIAL`, or `OVERDUE` with a positive `balance_cents`, else `ERR_INVOICE_NOT_OPEN`. The applied amount is the lesser of `approved_cents` and the invoice's `balance_cents`; a caller may name a smaller explicit `amount_cents`, but one above that bound is rejected with `ERR_GRANT_EXCEEDS_INVOICE_BALANCE`. Application unreserves the full approval (`pool_reserved_cents` falls by `approved_cents`), spends the applied portion (`pool_spent_cents` grows by the applied amount), returns the unspent difference to availability (`pool_available_cents` grows by `approved_cents` minus the applied amount), raises the invoice's `scholarship_applied_cents` by the applied amount, and recomputes its balance. A scholarship application that zeroes the invoice moves it to `WAIVED` rather than `PAID`, with the same member bubble-up, and the grant becomes `APPLIED` — terminal — with `invoice_id` recorded. An approved-but-unapplied grant can instead be revoked, moving it to `REVOKED` (also terminal) and returning the reservation to the pool: `pool_reserved_cents` falls by `approved_cents` and `pool_available_cents` rises by the same.

### 3.5. The Music Library

The `Librarian` catalogs each score with a `title`, the total `copy_count` of physical copies owned, the `replacement_cost_cents` charged when a copy is lost, and an optional `composer`. A new score is `ACTIVE` with `copies_available` equal to `copy_count` and `copies_lost` at zero; thereafter `copies_available` is computed as `copy_count` minus open checkouts minus `copies_lost`.

Checking out a copy requires the `score_id`, `member_id`, and a `due_date`. The score must be `ACTIVE`, else `ERR_SCORE_RETIRED`; at least one copy must be available, else `ERR_NO_COPIES_AVAILABLE`; and the member must not already carry an `OVERDUE` checkout — the library hold — else `ERR_LIBRARY_HOLD`. A checkout opens in `CHECKED_OUT` status with `checked_out_at` stamped from the clock and `fine_cents` and `charge_cents` at zero.

At each checkpoint, a checkout whose `due_date` has passed moves from `CHECKED_OUT` to `OVERDUE`, and the fine clock starts: `fine_cents` is set to a weekly fine of 200 cents on the transition, and each subsequent checkpoint at which the checkout is still `OVERDUE` adds another 200 cents, capped at the score's `replacement_cost_cents`. While any checkout of theirs is `OVERDUE`, the member is on library hold and cannot take out new scores.

Returns and losses close the loop, and both require the checkout to be `CHECKED_OUT` or `OVERDUE` — anything else is rejected with `ERR_CHECKOUT_NOT_ACTIVE`. Returning sets `returned_at`, moves the checkout to `RETURNED`, recomputes the score's `copies_available`, posts any accrued `fine_cents` to the member's `ledger_balance_cents` when the return came from `OVERDUE`, and re-evaluates the member's library hold. Marking a copy lost moves the checkout to `LOST`, sets `charge_cents` to the score's `replacement_cost_cents` and posts it to `ledger_balance_cents` — together with the accrued fine when the checkout was `OVERDUE` — and increments `copies_lost`. A member's `ledger_balance_cents` accumulates exactly these library charges; a positive value means the member owes. The member-drop cascade from §3.3 marks any still-open checkouts `LOST` under these same charging rules. Finally, the Librarian may retire a score: `ACTIVE` to `RETIRED` is terminal, blocks new checkouts, and leaves existing checkouts untouched.

### 3.6. Concerts, Venues, and Programs

Venues belong to the `President`, who registers each with a `name` and audience `capacity`; a venue starts `ACTIVE` and can later be archived. Archiving is terminal, makes the venue reject all new bookings with `ERR_VENUE_ARCHIVED`, and leaves existing `CONFIRMED` bookings unaffected.

A `ChoirDirector` creates a concert once the season is `REHEARSING` or later, supplying `season_id`, `title`, and `expected_attendance`; the concert opens in `PLANNING` with `program_duration_seconds` at zero. To book the hall, the director requests a venue booking with `concert_id`, `venue_id`, a `start_at` and `end_at` defining a half-open interval — the start is inclusive, the end exclusive, so back-to-back bookings that merely touch are permitted — and a `deposit_cents`. The interval must not intersect any existing non-terminal booking of the same venue, else `ERR_VENUE_OVERLAP`; the `start_at` must be at least 72 hours — three full days — in the future, else `ERR_BOOKING_LEAD_TIME`; and the concert's `expected_attendance` must not exceed the venue's `capacity`, else `ERR_VENUE_CAPACITY_EXCEEDED` (HTTP 422). A new booking is `REQUESTED`.

Confirming a booking is the Treasurer's job and requires the treasury to cover the deposit, else `ERR_INSUFFICIENT_TREASURY`; confirmation debits `deposit_cents` from the treasury, moves the booking to `CONFIRMED`, and bubbles the concert from `PLANNING` to `VENUE_BOOKED`. The director may instead decline a `REQUESTED` booking, moving it to `DECLINED`, or release it: releasing a `REQUESTED` booking moves it to `CANCELLED` with no treasury movement since no deposit was ever posted, while releasing a `CONFIRMED` booking — allowed only while its concert is not yet `PERFORMED` — moves it to `RELEASED`, credits the deposit back to the treasury, and, when done manually rather than by cascade, drops the concert from `VENUE_BOOKED` back to `PLANNING`.

Programs are built from pieces. The director adds each piece with `concert_id`, `title`, `duration_seconds`, a running-order `sequence_no`, an optional `featured_member_ids` list of singers featured on the piece, and an optional `guest_contract_id` linking a hired musician. A piece opens in `DRAFT`, and while `DRAFT` its fields may be revised. The `sequence_no` must be unique within its concert among pieces that are not `VOID`, a constraint enforced both at creation and on update, else `ERR_PROGRAM_SEQUENCE_CONFLICT`.

Confirming a piece is gated three ways: the concert must still be in `PLANNING` or `VENUE_BOOKED`, else `ERR_INVALID_STATE`; every member named in `featured_member_ids` must be `performance_eligible` at that moment, else `ERR_MEMBER_NOT_ELIGIBLE`; and if a `guest_contract_id` is linked, that contract must be `ACCEPTED`, `APPROVED`, or `PAID`, else `ERR_CONTRACT_NOT_ACCEPTED`. Each confirmation or void recomputes the concert's `program_duration_seconds`, the sum of `duration_seconds` over its `CONFIRMED` pieces. Voiding a `DRAFT` piece is always allowed; voiding a `CONFIRMED` piece manually is allowed only while the concert has not yet reached `PROGRAM_LOCKED`, else `ERR_INVALID_STATE`. Either way, voiding also cancels any linked guest contract under the cascade rule below.

The concert's own transitions are director actions named by an `action` field. Locking the program — `VENUE_BOOKED` to `PROGRAM_LOCKED` — requires the booking to be `CONFIRMED`, else `ERR_BOOKING_NOT_CONFIRMED`; requires at least one non-`VOID` piece with every non-`VOID` piece in `CONFIRMED` status, else `ERR_NO_CONFIRMED_PIECES`; and requires the total program duration to fit the booking window with a 900-second — fifteen-minute — buffer to spare: `program_duration_seconds` must not exceed the gap between the booking's `end_at` and `start_at` minus 900 seconds, else `ERR_PROGRAM_TOO_LONG` (HTTP 422). Marking ready — `PROGRAM_LOCKED` to `READY` — requires every `CONFIRMED` piece carrying a `guest_contract_id` to have that contract in `PAID`, else `ERR_CONTRACT_UNPAID`. Performing — `READY` to `PERFORMED` — requires the clock to have reached the booking's `start_at`, else `ERR_CONCERT_TOO_EARLY`.

Cancelling a concert runs the concert-cancel cascade, available from `PLANNING`, `VENUE_BOOKED`, `PROGRAM_LOCKED`, or `READY`. The cascade releases the concert's booking: a booking in `REQUESTED` or `CONFIRMED` moves to `RELEASED`, and where a deposit was actually posted — a `CONFIRMED` booking — `deposit_cents` is refunded to the season treasury. It then voids every non-`VOID` program piece, and each voided piece cancels its linked guest contract when that contract stands in `OFFERED`, `COUNTERED`, `ACCEPTED`, or `APPROVED`; a contract cancelled after acceptance posts its cancellation fee as a treasury debit, as §3.7 specifies. Contracts already `PAID` are never cancelled by the cascade, and a `READY` concert with a linked `PAID` contract cannot be cancelled at all — the attempt is rejected with `ERR_INVALID_STATE` until the contract is settled first. `PERFORMED` and `CANCELLED` are the concert's terminal states, and, per §3.1, every concert must reach one of them before the season can archive.

### 3.7. Guest Musician Contracts

Hiring a guest musician starts with the `ChoirDirector` drafting a contract: `season_id`, `musician_name`, a list of `service_lines` where each line carries a `kind` of `REHEARSAL`, `CONCERT`, or `MASTERCLASS` together with a number of `units` and a `rate_cents`, an optional flat `travel_stipend_cents` defaulting to zero, and an optional `concert_id`. The contract opens in `DRAFT` with `counter_count` and `cancellation_fee_cents` at zero and its `quoted_fee_cents` computed. The quote's rounding order is pinned: each service line is rounded first — the line's `rate_cents` multiplied by its `units`, rounded half up to integer cents — and only then are the rounded line totals summed, with `travel_stipend_cents` added last. Summing the raw products and rounding once at the end is a different, non-conforming result.

Negotiation proceeds as a state dance. Offering moves `DRAFT` to `OFFERED`, and later also `COUNTERED` back to `OFFERED` with revised terms; either way the caller may supply fresh `service_lines` or `travel_stipend_cents`, the quote is recomputed, and the contract's `version` increments. Recording the musician's counter-offer moves `OFFERED` to `COUNTERED` and is the OCC-guarded step from §2.7: it requires `expected_guest_contract_version`, increments `counter_count` by one, replaces the `service_lines` and travel stipend with the countered terms, recomputes `quoted_fee_cents`, and increments `version`. The musician's answer is recorded as acceptance — `OFFERED` to `ACCEPTED` — or as a decline, which moves `OFFERED` or `COUNTERED` to the terminal `DECLINED`.

Execution splits duties across three officers. Presidential approval moves `ACCEPTED` to `APPROVED` and records `approved_by_user_id`. Treasurer payment moves `APPROVED` to the terminal `PAID`, but only under two guards: the paying user must differ from the `approved_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`, and the treasury must cover `quoted_fee_cents`, else `ERR_INSUFFICIENT_TREASURY`; payment debits the quoted fee from the treasury and records `paid_by_user_id`.

Cancellation is priced by how far the contract had progressed. Cancelling a contract in `DRAFT`, `OFFERED`, or `COUNTERED` — whether by the director directly or by the concert cascade — costs nothing: no cancellation fee exists before acceptance. Cancelling from `ACCEPTED` or `APPROVED` posts a `cancellation_fee_cents` of twenty percent of `quoted_fee_cents`, rounded half up to integer cents, debited from the treasury; the treasury must cover the fee, else `ERR_INSUFFICIENT_TREASURY`. `CANCELLED` is terminal alongside `DECLINED` and `PAID`.

### 3.8. Tours and Festival Travel

A `President` plans a tour or festival trip with `season_id`, `name`, `destination`, `departure_at` and `return_at` instants, a `seat_count` of total travel seats, a `min_seats` floor used for provisional pricing, and the `transport_lodging_cost_cents` to be split across confirmed seats. The trip opens in `PLANNING` with `confirmed_count` at zero and `final_share_cents` not yet set. Opening registration — `PLANNING` to `REGISTRATION_OPEN` — requires `departure_at` to lie in the future, else `ERR_TOUR_IN_PAST`, and requires `seat_count` to be at least `min_seats` with `min_seats` at least one, else `ERR_INVALID_REQUEST`. Opening computes `provisional_share_cents`: the total cost divided by `min_seats`, rounded half up to integer cents.

Members self-register by supplying just the `tour_id`; the registration's `member_id` is taken from the caller's `X-User-ID`. Registration requires the tour to be `REGISTRATION_OPEN`, else `ERR_TOUR_NOT_OPEN`; requires the member's `dues_balance_cents` to be zero and the member to be `performance_eligible`, else `ERR_DUES_NOT_CURRENT`; and forbids a second non-terminal registration on the same tour — a member already `REGISTERED`, `CONFIRMED`, or `WAITLISTED` is rejected with `ERR_ALREADY_REGISTERED`. If a seat is free the registration opens as `REGISTERED`, otherwise as `WAITLISTED`.

The Treasurer confirms a `REGISTERED` registration by recording the deposit: `deposit_paid_cents`, zero until now, is set to the tour's `provisional_share_cents`, the treasury is credited, the registration moves to `CONFIRMED`, and the tour's `confirmed_count` is recomputed. Cancellation — by the member themselves or the Treasurer — is only possible while the tour remains `REGISTRATION_OPEN`; after the roster locks, the attempt is rejected with `ERR_ROSTER_LOCKED`. Cancelling a `REGISTERED` registration posts no charge, frees the seat, and runs waitlist promotion. Cancelling a `CONFIRMED` one refunds by schedule: the number of whole days between now and the tour's `departure_at` determines the percentage — sixty days or more returns the full deposit, thirty to fifty-nine days returns half, and fewer than thirty days returns nothing — and `refund_cents` is the deposit multiplied by that percentage, rounded half up to integer cents. The boundaries are exact: exactly sixty days before departure yields 100 percent, exactly thirty days yields 50 percent, and twenty-nine days yields nothing. The treasury must cover the refund, else `ERR_INSUFFICIENT_TREASURY`; then the treasury is debited, the seat freed, and promotion runs. Promotion itself is deterministic: the oldest `WAITLISTED` registration by `created_at` ascending moves to `REGISTERED` whenever a freed seat exists while the tour is `REGISTRATION_OPEN`, a sweep also run at each checkpoint.

Locking the roster — `REGISTRATION_OPEN` to `ROSTER_LOCKED` — requires `confirmed_count` to be at least `min_seats`, else `ERR_BELOW_MIN_SEATS`. At lock, `final_share_cents` is computed as the total cost divided by `confirmed_count`, rounded half up to integer cents — the provisional and final shares diverge whenever the confirmed roster differs from `min_seats` — and each `CONFIRMED` registration settles: its `share_charge_cents` is set to `final_share_cents`, its `refund_cents` to `deposit_paid_cents` minus `final_share_cents`, and the treasury is debited each refund, returning the difference to the member. Registrations still `WAITLISTED` at lock move to `CANCELLED` with no charge and no refund. Before the lock, both `final_share_cents` and per-registration `share_charge_cents` are null.

After the trip, completion — `ROSTER_LOCKED` to `COMPLETED` — requires the clock to have reached `return_at`, else `ERR_TOUR_NOT_RETURNED`. Cancelling the tour itself is always possible from `PLANNING` or `REGISTRATION_OPEN`. From `PLANNING`, every non-terminal registration simply moves to `CANCELLED` and no charges post. From `REGISTRATION_OPEN`, `CONFIRMED` registrations move to `REFUNDED` with `refund_cents` equal to their full `deposit_paid_cents`, debited from the treasury, while `REGISTERED` and `WAITLISTED` registrations move to `CANCELLED`. `COMPLETED` and `CANCELLED` are the tour's terminal states, and `CANCELLED` and `REFUNDED` are a registration's.

### 3.9. Committees and Fundraising

Volunteer committees are created by the `President` with a `season_id`, a `name`, the `chair_member_id` of the member who will chair, and a `fundraising_goal_cents`. A committee starts `FORMING` with `raised_cents` at zero, and activation — `FORMING` to `ACTIVE` — requires the chair to be an `ACTIVE` member at that moment, else `ERR_CHAIR_NOT_ACTIVE`.

Pledges are the Treasurer's ledger. Recording one takes `committee_id`, `donor_name`, and `amount_cents`; the committee must be `ACTIVE`, else `ERR_COMMITTEE_NOT_ACTIVE`. The pledge opens in `PLEDGED` with the recording officer captured in `recorded_by_user_id`. Fulfilment converts the promise to cash: a Treasurer fulfills a `PLEDGED` pledge, but the fulfilling officer — recorded as `fulfilled_by_user_id` — must differ from the `recorded_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`. Fulfilment credits the treasury with `amount_cents`, recomputes the committee's `raised_cents` (the sum of its `FULFILLED` pledge amounts), and computes the donor's `recognition_tier`: `GOLD` for a pledge of at least 50000 cents, `SILVER` for at least 10000 cents, and `BRONZE` below that, with the boundaries inclusive — exactly 10000 cents earns `SILVER` and exactly 50000 earns `GOLD`.

The remaining pledge paths are unwind operations. Cancelling a `PLEDGED` pledge moves it to the terminal `CANCELLED`, and the same happens automatically to every still-`PLEDGED` pledge when its committee is dissolved; `FULFILLED` pledges survive dissolution untouched, and dissolution — `ACTIVE` to `DISSOLVED`, terminal — is the President's call. Refunding a `FULFILLED` pledge requires the treasury to cover `amount_cents`, else `ERR_INSUFFICIENT_TREASURY`, then debits the treasury, moves the pledge to the terminal `REFUNDED`, and recomputes `raised_cents` as compensation.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`. Operations that modify an existing resource — state transitions, actions, and updates — return `200 OK`, as do all reads. Resources are addressed by a single `id` path parameter. List endpoints accept the pagination parameters `limit` and `offset` plus the optional filters natural to each collection: `posture` on seasons; `season_id`, `voice_part`, and `status` on sections; `section_id` and `status` on members; `member_id` and `status` on auditions, payments, and attendance records; `season_id` and `status` on invoices, rehearsals, concerts, contracts, and tours; `invoice_id` on grants; `rehearsal_id` on attendance records; `score_id` on checkouts; `concert_id` on bookings, pieces, and contracts; `venue_id` on bookings; `guest_contract_id` on pieces; `tour_id` on registrations; and `committee_id` and `chair_member_id` on their respective collections.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/v1/_clock/set_current_utc` | Set the logical clock | President |
| POST | `/v1/seasons` | Create a season in `DRAFT` posture | President |
| GET | `/v1/seasons/{id}` | Get a season | President, Treasurer, ChoirDirector, Librarian, Member |
| GET | `/v1/seasons` | List seasons | President, Treasurer, ChoirDirector, Librarian, Member |
| PATCH | `/v1/seasons/{id}` | Update season configuration (OCC-guarded) | President |
| POST | `/v1/seasons/{id}/posture` | Advance season posture | President |
| POST | `/v1/seasons/{id}/checkpoint` | Run the ops checkpoint (OCC-guarded) | President |
| POST | `/v1/sections` | Create a voice-part section | ChoirDirector |
| GET | `/v1/sections/{id}` | Get a section | President, Treasurer, ChoirDirector, Librarian, Member |
| GET | `/v1/sections` | List sections | President, Treasurer, ChoirDirector, Librarian, Member |
| PATCH | `/v1/sections/{id}` | Update section targets or `OPEN`/`CLOSED` status | ChoirDirector |
| POST | `/v1/members` | Register an applicant member | ChoirDirector |
| GET | `/v1/members/{id}` | Get a member (Member role: self only) | President, Treasurer, ChoirDirector, Librarian, Member |
| GET | `/v1/members` | List members | President, Treasurer, ChoirDirector, Librarian, Member |
| POST | `/v1/members/{id}/status` | Director actions: `DROP`, `SUSPEND`, `REINSTATE` | ChoirDirector |
| POST | `/v1/members/{id}/resign` | Member resigns (self or director) | Member, ChoirDirector |
| POST | `/v1/auditions` | Book an audition slot for an `APPLICANT` | ChoirDirector |
| GET | `/v1/auditions/{id}` | Get an audition | President, Treasurer, ChoirDirector, Librarian, Member |
| GET | `/v1/auditions` | List auditions | President, Treasurer, ChoirDirector, Librarian, Member |
| POST | `/v1/auditions/{id}/score` | Record scores; audition becomes `COMPLETED` | ChoirDirector |
| POST | `/v1/auditions/{id}/cancel` | Cancel a `SCHEDULED` audition | ChoirDirector |
| POST | `/v1/auditions/{id}/decision` | `ACCEPT`, `WAITLIST`, or `REJECT` a completed audition | ChoirDirector |
| POST | `/v1/dues-invoices` | Issue a dues invoice for a member | Treasurer |
| GET | `/v1/dues-invoices/{id}` | Get an invoice (Member role: own only) | President, Treasurer, ChoirDirector, Member |
| GET | `/v1/dues-invoices` | List invoices | President, Treasurer, ChoirDirector, Member |
| POST | `/v1/dues-payments` | Record a dues payment with waterfall allocation | Treasurer |
| GET | `/v1/dues-payments/{id}` | Get a payment | President, Treasurer, Member |
| GET | `/v1/dues-payments` | List payments | President, Treasurer, Member |
| POST | `/v1/dues-payments/{id}/refund` | Refund a `POSTED` payment, reopening invoices | Treasurer |
| POST | `/v1/scholarship-grants` | Request a scholarship (self or on behalf) | Member, Treasurer |
| GET | `/v1/scholarship-grants/{id}` | Get a grant (Member role: own only) | President, Treasurer, Member |
| GET | `/v1/scholarship-grants` | List grants | President, Treasurer, Member |
| POST | `/v1/scholarship-grants/{id}/decision` | `APPROVE` or `REJECT` a requested grant | Treasurer |
| POST | `/v1/scholarship-grants/{id}/apply` | Apply an approved grant to an open invoice | Treasurer |
| POST | `/v1/scholarship-grants/{id}/revoke` | Revoke an approved, unapplied grant | Treasurer |
| POST | `/v1/rehearsals` | Schedule a rehearsal | ChoirDirector |
| GET | `/v1/rehearsals/{id}` | Get a rehearsal | President, Treasurer, ChoirDirector, Librarian, Member |
| GET | `/v1/rehearsals` | List rehearsals | President, Treasurer, ChoirDirector, Librarian, Member |
| POST | `/v1/rehearsals/{id}/cancel` | Cancel a `SCHEDULED` rehearsal | ChoirDirector |
| POST | `/v1/rehearsals/{id}/attendance` | Bulk-record attendance; rehearsal becomes `COMPLETED` | ChoirDirector |
| GET | `/v1/attendance-records/{id}` | Get an attendance record | President, Treasurer, ChoirDirector, Member |
| GET | `/v1/attendance-records` | List attendance records | President, Treasurer, ChoirDirector, Member |
| POST | `/v1/attendance-records/{id}/excuse` | Excuse an unexcused absence | ChoirDirector |
| POST | `/v1/music-scores` | Catalog a score | Librarian |
| GET | `/v1/music-scores/{id}` | Get a score | President, Treasurer, ChoirDirector, Librarian, Member |
| GET | `/v1/music-scores` | List scores | President, Treasurer, ChoirDirector, Librarian, Member |
| POST | `/v1/music-scores/{id}/retire` | Retire a score from circulation | Librarian |
| POST | `/v1/score-checkouts` | Check out a score copy to a member | Librarian |
| GET | `/v1/score-checkouts/{id}` | Get a checkout (Member role: own only) | President, Treasurer, ChoirDirector, Librarian, Member |
| GET | `/v1/score-checkouts` | List checkouts | President, Treasurer, ChoirDirector, Librarian, Member |
| POST | `/v1/score-checkouts/{id}/return` | Return a checkout, posting any accrued fine | Librarian |
| POST | `/v1/score-checkouts/{id}/mark-lost` | Mark a checkout lost, charging replacement cost | Librarian |
| POST | `/v1/venues` | Register a venue | President |
| GET | `/v1/venues/{id}` | Get a venue | President, Treasurer, ChoirDirector, Librarian, Member |
| GET | `/v1/venues` | List venues | President, Treasurer, ChoirDirector, Librarian, Member |
| POST | `/v1/venues/{id}/archive` | Archive a venue | President |
| POST | `/v1/concerts` | Create a concert | ChoirDirector |
| GET | `/v1/concerts/{id}` | Get a concert | President, Treasurer, ChoirDirector, Librarian, Member |
| GET | `/v1/concerts` | List concerts | President, Treasurer, ChoirDirector, Librarian, Member |
| POST | `/v1/concerts/{id}/transition` | `LOCK_PROGRAM`, `MARK_READY`, `PERFORM`, or `CANCEL` | ChoirDirector |
| POST | `/v1/venue-bookings` | Request a venue booking (half-open interval) | ChoirDirector |
| GET | `/v1/venue-bookings/{id}` | Get a booking | President, Treasurer, ChoirDirector, Librarian, Member |
| GET | `/v1/venue-bookings` | List bookings | President, Treasurer, ChoirDirector, Librarian, Member |
| POST | `/v1/venue-bookings/{id}/confirm` | Confirm a booking, debiting the deposit | Treasurer |
| POST | `/v1/venue-bookings/{id}/decline` | Decline a `REQUESTED` booking | ChoirDirector |
| POST | `/v1/venue-bookings/{id}/release` | Release a `CONFIRMED` booking or cancel a `REQUESTED` one | ChoirDirector |
| POST | `/v1/program-pieces` | Add a program piece to a concert | ChoirDirector |
| GET | `/v1/program-pieces/{id}` | Get a piece | President, Treasurer, ChoirDirector, Librarian, Member |
| GET | `/v1/program-pieces` | List pieces | President, Treasurer, ChoirDirector, Librarian, Member |
| PATCH | `/v1/program-pieces/{id}` | Update a piece while `DRAFT` | ChoirDirector |
| POST | `/v1/program-pieces/{id}/confirm` | Confirm a piece (eligibility and contract gates) | ChoirDirector |
| POST | `/v1/program-pieces/{id}/void` | Void a piece | ChoirDirector |
| POST | `/v1/guest-contracts` | Draft a guest musician contract | ChoirDirector |
| GET | `/v1/guest-contracts/{id}` | Get a contract | President, Treasurer, ChoirDirector, Librarian, Member |
| GET | `/v1/guest-contracts` | List contracts | President, Treasurer, ChoirDirector, Librarian, Member |
| POST | `/v1/guest-contracts/{id}/offer` | Offer the contract, or re-offer with revised terms | ChoirDirector |
| POST | `/v1/guest-contracts/{id}/counter` | Record a musician counter-offer (OCC-guarded) | ChoirDirector |
| POST | `/v1/guest-contracts/{id}/accept` | Record musician acceptance | ChoirDirector |
| POST | `/v1/guest-contracts/{id}/decline` | Record musician decline | ChoirDirector |
| POST | `/v1/guest-contracts/{id}/approve` | Presidential approval | President |
| POST | `/v1/guest-contracts/{id}/pay` | Treasurer payment (segregation of duties enforced) | Treasurer |
| POST | `/v1/guest-contracts/{id}/cancel` | Cancel a non-terminal contract; 20% fee after acceptance | ChoirDirector |
| POST | `/v1/tours` | Create a tour or festival trip | President |
| GET | `/v1/tours/{id}` | Get a tour | President, Treasurer, ChoirDirector, Librarian, Member |
| GET | `/v1/tours` | List tours | President, Treasurer, ChoirDirector, Librarian, Member |
| POST | `/v1/tours/{id}/transition` | `OPEN_REGISTRATION`, `LOCK_ROSTER`, `COMPLETE`, or `CANCEL` | President |
| POST | `/v1/tour-registrations` | Member self-registers for a tour | Member |
| GET | `/v1/tour-registrations/{id}` | Get a registration (Member role: own only) | President, Treasurer, ChoirDirector, Member |
| GET | `/v1/tour-registrations` | List registrations | President, Treasurer, ChoirDirector, Member |
| POST | `/v1/tour-registrations/{id}/confirm` | Record the deposit, confirming the seat | Treasurer |
| POST | `/v1/tour-registrations/{id}/cancel` | Cancel a registration; refund per schedule | Member, Treasurer |
| POST | `/v1/committees` | Create a volunteer committee | President |
| GET | `/v1/committees/{id}` | Get a committee | President, Treasurer, ChoirDirector, Librarian, Member |
| GET | `/v1/committees` | List committees | President, Treasurer, ChoirDirector, Librarian, Member |
| POST | `/v1/committees/{id}/transition` | `ACTIVATE` or `DISSOLVE` | President |
| POST | `/v1/pledges` | Record a fundraising pledge | Treasurer |
| GET | `/v1/pledges/{id}` | Get a pledge | President, Treasurer, ChoirDirector, Member |
| GET | `/v1/pledges` | List pledges | President, Treasurer, ChoirDirector, Member |
| POST | `/v1/pledges/{id}/fulfill` | Fulfill a pledge, crediting the treasury | Treasurer |
| POST | `/v1/pledges/{id}/cancel` | Cancel a `PLEDGED` pledge | Treasurer |
| POST | `/v1/pledges/{id}/refund` | Refund a `FULFILLED` pledge | Treasurer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_ENUM` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_SEASON_POSTURE` | 409 |
| `ERR_SEASON_TERMINAL` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_AUDITION_NOT_SCORED` | 409 |
| `ERR_AUDITIONS_PENDING` | 409 |
| `ERR_AUDITION_OVERLAP` | 409 |
| `ERR_SCORE_BELOW_THRESHOLD` | 409 |
| `ERR_SECTION_FULL` | 409 |
| `ERR_SECTION_CLOSED` | 409 |
| `ERR_SECTION_UNBALANCED` | 409 |
| `ERR_DUPLICATE_MEMBERSHIP` | 409 |
| `ERR_DUPLICATE_SECTION` | 409 |
| `ERR_DUPLICATE_ATTENDANCE` | 409 |
| `ERR_MEMBER_NOT_ELIGIBLE` | 409 |
| `ERR_DUES_NOT_CURRENT` | 409 |
| `ERR_INVOICE_NOT_OPEN` | 409 |
| `ERR_OVERPAYMENT` | 409 |
| `ERR_GRANT_NOT_APPROVED` | 409 |
| `ERR_GRANT_EXCEEDS_INVOICE_BALANCE` | 409 |
| `ERR_SCHOLARSHIP_POOL_EXHAUSTED` | 409 |
| `ERR_LIBRARY_HOLD` | 409 |
| `ERR_NO_COPIES_AVAILABLE` | 409 |
| `ERR_CHECKOUT_NOT_ACTIVE` | 409 |
| `ERR_SCORE_RETIRED` | 409 |
| `ERR_VENUE_ARCHIVED` | 409 |
| `ERR_VENUE_OVERLAP` | 409 |
| `ERR_VENUE_CAPACITY_EXCEEDED` | 422 |
| `ERR_BOOKING_LEAD_TIME` | 409 |
| `ERR_BOOKING_NOT_CONFIRMED` | 409 |
| `ERR_PROGRAM_TOO_LONG` | 422 |
| `ERR_PROGRAM_SEQUENCE_CONFLICT` | 409 |
| `ERR_NO_CONFIRMED_PIECES` | 409 |
| `ERR_CONTRACT_NOT_ACCEPTED` | 409 |
| `ERR_CONTRACT_UNPAID` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_INSUFFICIENT_TREASURY` | 409 |
| `ERR_TOUR_NOT_OPEN` | 409 |
| `ERR_TOUR_IN_PAST` | 409 |
| `ERR_ROSTER_LOCKED` | 409 |
| `ERR_ALREADY_REGISTERED` | 409 |
| `ERR_BELOW_MIN_SEATS` | 409 |
| `ERR_TOUR_NOT_RETURNED` | 409 |
| `ERR_REHEARSAL_NOT_HELD` | 409 |
| `ERR_COMMITTEE_NOT_ACTIVE` | 409 |
| `ERR_CHAIR_NOT_ACTIVE` | 409 |
| `ERR_CONCERTS_OPEN` | 409 |
| `ERR_CONCERT_TOO_EARLY` | 409 |
