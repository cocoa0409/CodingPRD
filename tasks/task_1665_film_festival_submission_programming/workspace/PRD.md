# Film Festival Programming API — Product Requirements Document

## 1. Introduction

Running an annual film festival in the Sundance mold means orchestrating thousands of film submissions against fixed deadlines, a small army of volunteer and staff programmers, a finite grid of venues and time slots, a finite pool of hotel room-nights and travel stipend money, and a prize fund that must be accounted for to the cent. Each of those resources is scarce, and each stage of the season — intake, eligibility review, screening, deliberation, notification, scheduling, the festival itself, and awards night — imposes its own rules on what may happen when. This document specifies the API that runs that operation end to end: submission intake with tiered entry fees and deadline-driven pricing, eligibility rulings with a revision loop, screener assignment and seniority-weighted scoring, committee deliberation and slate locking, filmmaker invitations with RSVP expiry and waitlist promotion, screening-slot allocation on venue grids, travel and accommodation administration, exhibition-rights agreements, and jury balloting with an instant-runoff tally.

Three design pillars hold the system together. First, all time-dependent behavior is driven by a single logical clock rather than the wall clock, so that deadline crossings, invitation expiries, and assignment expiries are deterministic and testable. Second, a festival edition carries a posture — its lifecycle phase — that gates nearly every child operation; nothing is scored, invited, scheduled, or awarded outside its proper phase. Third, the edition maintains a live ledger of collected fees, committed travel funds, allocated hotel nights, and committed prize money, so that every approval and cancellation is immediately reflected in the resources that remain. Actor responsibilities are deliberately segregated: the chair who builds a slate may not be the director who locks it, and a juror may not vote on a film whose production company is on their conflict list.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope formats, and cross-cutting principles that apply to every endpoint of the API, which is served under the `/festival` mount.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The declared role must be one of the roles recognized by the system: `PUBLIC`, `FESTIVAL_ADMIN`, `FILMMAKER`, `PROGRAMMER`, `PROGRAM_CHAIR`, `FESTIVAL_DIRECTOR`, `SCHEDULING_OPS`, `TRAVEL_COORDINATOR`, `JUROR`, and `AWARDS_ADMIN`. A request missing either header, or presenting a role outside this list, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not in the target endpoint's authorized role list is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

The role `PUBLIC` represents unauthenticated public intake and is honored only for submitter registration; its `X-User-ID` is an opaque caller identifier not tied to any persisted entity. The roles `FESTIVAL_ADMIN`, `PROGRAM_CHAIR`, `FESTIVAL_DIRECTOR`, `SCHEDULING_OPS`, `TRAVEL_COORDINATOR`, and `AWARDS_ADMIN` are likewise opaque: their `X-User-ID` values are not tied to any persisted entity, though the server may record them for audit — for example, as `last_entry_added_by` on a slate — without ever comparing them to an entity's `id`.

Three roles are entity-backed. When `X-User-Role` is `FILMMAKER`, `X-User-ID` is the `id` of the acting Submitter; ownership checks compare a submission's `submitter_id` — or the submitter reached through a fee payment, slate entry, travel package, or exhibition agreement linked to that submission — against `X-User-ID`. When `X-User-Role` is `PROGRAMMER`, `X-User-ID` is the `id` of the acting Programmer; ownership checks on a screener assignment compare the assignment's `programmer_id` against `X-User-ID`, and a programmer sees and edits only their own assignments and scores. When `X-User-Role` is `JUROR`, `X-User-ID` is the `id` of the acting Juror, and a ballot's `juror_id` is set from it. An entity-backed actor operating on a resource they do not own is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403); a juror casting a ballot for an award whose panel does not include them is rejected with `ERR_JUROR_NOT_ON_PANEL` (HTTP 403).

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned: it defaults to 10, and accepts values from a minimum of 1 to a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0. The `meta` object of every list response carries `limit`, `offset`, `total_count`, and `has_more`.

Unless otherwise specified, list endpoints return resources sorted by `created_at` in ascending order. One exception exists: the entries of a slate are returned ordered by `rank_position` ascending, as described in §3.5.

### 2.4. The Logical Clock and Deferred Sweeps

All time-dependent behavior in the system — deadline selection, expiry sweeps, festival windows — reads a single logical clock, never the wall clock. At server startup the logical clock reads exactly `2026-08-01T00:00:00Z`; until it is explicitly set, every clock read returns that value. A `FESTIVAL_ADMIN`-only, test-driving capability sets the clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`.

Advancing the clock is not a passive act: each advance triggers deferred sweeps across the edition. When the clock moves past an edition's `late_deadline_at`, intake for that edition closes automatically. When the clock moves past a screener assignment's `due_at`, a non-terminal assignment expires and the replacement selector runs. When the clock moves past a slate entry's `rsvp_deadline_at`, the unanswered invitation expires and the waitlist-promotion cascade runs. These sweeps and their cascades are specified where their workflows live, in §3.4 and §3.6.

### 2.5. Edition Posture: The Festival's Master Gate

A festival edition advances through eleven phases in strict order: `SETUP`, `INTAKE_OPEN`, `INTAKE_CLOSED`, `SCREENING`, `DELIBERATION`, `SLATE_LOCKED`, `NOTIFICATION`, `SCHEDULING`, `FESTIVAL_LIVE`, `AWARDS_NIGHT`, and finally `CLOSED`, which is terminal. All advancement flows through a single advance capability invoked by a `FESTIVAL_ADMIN` with an explicit target phase carried in the `to_status` field; the sole exception is the automatic intake close performed by the clock sweep described in §2.4. A request to advance to a phase that is not the declared next phase is rejected with `ERR_INVALID_STATE` (HTTP 409). Each per-transition gate — scoring completeness, slate locking, outstanding invitations, festival start, award disbursement — is specified with its phase pair in §3. Every advance increments the edition's `version` and refreshes its `updated_at`.

Posture is not advisory. Nearly every child operation in the system is permitted only while the edition sits in a declared phase set: submissions and checkouts only during `INTAKE_OPEN`, scoring only during `SCREENING`, slate editing only during `DELIBERATION`, invitations only during `NOTIFICATION`, slot holds only during `SCHEDULING`, and so on. An operation attempted outside its declared phase set is rejected with `ERR_EDITION_PHASE_FORBIDDEN` (HTTP 409).

### 2.6. Common Resource Properties

Every primary resource carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created, and `updated_at` is the same kind of timestamp refreshed on every modification. The `version` field is an integer that starts at its initial value on creation and increments on every mutation of the resource — including mutations caused by derived-field reconciliation, so a recomputed edition ledger field bumps the edition's `version` and `updated_at` just as a direct edit would.

One resource is deliberately lighter. A jury vote carries only `id` and `created_at`: both `updated_at` and `version` are absent from it, because a ballot is immutable once cast.

### 2.7. Optimistic Concurrency Control

Four write endpoints guard against stale views of a parent aggregate through optimistic concurrency control; each requires a non-optional expected-version field in the request body, and rejects the request with `ERR_STALE_VERSION` (HTTP 412) when the supplied value does not match the parent entity's current `version`.

- Adding an entry to a slate — `POST /festival/slates/{id}/entries` — requires `expected_slate_version` carrying the slate's last observed `version`. If another chair has added or removed an entry since the client last read the slate, the slate's version has advanced and the add is rejected, because rank assignments the client saw are no longer valid.
- Creating a screening slot — `POST /festival/screening-slots` — requires `expected_venue_version` carrying the venue's last observed `version`; a venue whose grid has gained a slot since the client last read it has an advanced version, and the create is rejected.
- Approving a travel package — `POST /festival/travel-packages/{id}/approve` — requires `expected_edition_version` carrying the edition's last observed `version`; an edition whose budget or hotel pools have been committed by another approval since the client last read it has an advanced version, and the approval is rejected.
- Amending an exhibition agreement — `POST /festival/exhibition-agreements/{id}/amend` — requires `expected_agreement_version` carrying the agreement's last observed `version`; an agreement amended since the client last read it has an advanced version, and the amend is rejected.

No other endpoint accepts a version field. On all other mutations the server applies the change without an optimistic-concurrency check, incrementing the target's own `version` in the ordinary way.

### 2.8. Money, Scores, and the Edition Ledger

All monetary amounts in the system are integer cents. Where a calculation produces a fractional cent — a percentage discount, a partial refund, a cancellation penalty — the result is rounded half up to whole cents, and where discounts stack, each discount is computed and rounded individually before any subtraction takes place. Score aggregates are held to three decimal places, with round-half-up applied once to the final quotient.

Each edition maintains a derived ledger that is recomputed immediately whenever any child row changes. `total_fees_collected_cents` is the sum of `amount_cents` over the edition's fee payments in `SUCCEEDED` or `PARTIALLY_REFUNDED` status — the full collected amount, with refunds tracked separately in `total_refunded_cents`, the sum of `refunded_amount_cents` over all of the edition's payments. `travel_committed_cents` sums `stipend_cents` over travel packages in `APPROVED`, `BOOKED`, or `RECONCILED` status; `travel_penalty_sink_cents` sums `penalty_cents` over packages in `CANCELLED` status; and `travel_budget_remaining` equals `travel_budget_cents` minus the committed and penalty figures. These three figures obey a standing invariant, INV-TRAVEL: the remaining budget plus the committed amount plus the penalty sink always equals the edition's `travel_budget_cents`. On the lodging side, `hotel_nights_allocated` sums `hotel_nights_allocated` over travel packages in `APPROVED`, `BOOKED`, or `RECONCILED` status, and `hotel_nights_remaining` equals `hotel_nights_pool` minus that allocation; the invariant INV-HOTEL holds at all times — allocated nights plus remaining nights always equal the pool. Finally, `prize_committed_cents` sums `prize_cents` over awards in `SETUP`, `VOTING_OPEN`, `TALLIED`, `ANNOUNCED`, or `DISBURSED` status, and `prize_disbursed_cents` sums `disbursed_amount_cents` over awards in `DISBURSED` status. Each recomputation is a mutation of the edition and therefore refreshes `updated_at` and increments `version` per §2.6.

### 2.9. Validation Order and Error Precedence

When a request violates several rules at once, the error it receives is deterministic, because validation runs in a fixed sequence. First, the request shape is checked — required fields present, enum values valid, integer ranges sane — and any failure yields `ERR_VALIDATION` (HTTP 400); this covers, among other things, a `delegate_count` below 1, a `hotel_nights_requested` below 1, rubric scores outside the 1-to-10 range, a `capacity_slots` below 1, a negative `prize_cents`, or an `end_at` that is not later than its `start_at`. Second, authentication headers are verified (`ERR_UNAUTHENTICATED`). Third, the role is checked against the endpoint's authorized list (`ERR_UNAUTHORIZED_ROLE`). Fourth, path-templated resources are resolved left to right (`ERR_NOT_FOUND`). Fifth, entity-backed ownership is enforced (`ERR_FORBIDDEN_OWNERSHIP`). Sixth, the target resource's own state machine must permit the transition — invalid-from states and terminal lockdowns yield `ERR_INVALID_STATE` (HTTP 409), and domain-specific state errors declared on a transition, such as `ERR_SCORE_EXISTS`, `ERR_ENTRY_NOT_CONFIRMED`, `ERR_AGREEMENT_NOT_SIGNED`, or `ERR_SCORES_LOCKED`, fire at this same step in place of the generic code. Seventh, the edition posture gate is applied (`ERR_EDITION_PHASE_FORBIDDEN`). Eighth, clock-based window rules run: intake timing, the slot's festival window, premiere-before-public ordering, the refund cooling window, and the festival-start gate. Ninth, conflict-of-interest and segregation rules run (`ERR_COI_RECUSAL_REQUIRED`, `ERR_SEGREGATION_OF_DUTIES`, `ERR_JUROR_CONFLICT`). Tenth, body-referenced entities are checked for existence and same-edition membership (`ERR_REFERENTIAL_INTEGRITY`, HTTP 422). Eleventh, uniqueness, eligibility, and structural constraints run — duplicate emails, titles, configs, slates, assignments, scores, ballots and entries, premiere-slot uniqueness, runtime and completion-date eligibility, section-category mapping, venue overlap and slot fit, slate underfill and threshold, scoring and decision completeness, ballot validity, licensed screening counts, format support, and the assignment cap. Twelfth, fiscal guards run (`ERR_TRAVEL_BUDGET_EXHAUSTED`, `ERR_HOTEL_NIGHTS_EXHAUSTED`, `ERR_PRIZE_POOL_EXHAUSTED`, `ERR_PAYMENT_NOT_REFUNDABLE`, `ERR_REFUND_NOT_ALLOWED`). Last, the optimistic-concurrency version check fires (`ERR_STALE_VERSION`).

### 2.10. Nested Path Validation

Where an endpoint path contains more than one resource identifier, identifiers are validated strictly left to right, and the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve to an existing resource. A request targeting an entry under a slate — for example `/festival/slates/{id}/entries/{entry_id}` — therefore reports the slate's absence before the entry's, and never surfaces a later identifier's failure ahead of an earlier one. The same left-to-right rule applies to body references during creation: a referenced parent that does not exist fails before any rule that depends on it.

## 3. Business Logic & Workflows

This section walks the festival season in the order the work actually happens: standing up the edition, taking films in, ruling on eligibility, screening and scoring, deliberating and locking slates, inviting filmmakers, papering agreements and travel, building the screening grid, and finishing with the juries and the prizes. Each subsection owns its own rules, and rules that reach across stages — the ledger, the sweeps, the promotion cascade — are restated where they bite.

### 3.1. Standing Up an Edition: Deadlines, Categories, and People

A `FESTIVAL_ADMIN` founds a festival edition by supplying its `year` — unique across editions — together with the full calendar skeleton: `intake_open_at`, when submissions begin to be accepted; `early_deadline_at`, `regular_deadline_at`, and `late_deadline_at`, which bound the three fee tiers; and `festival_start_at` and `festival_end_at`, which bound the screening grid. The same creation call fixes the season's scarce pools: `hotel_nights_pool`, `travel_budget_cents`, and `prize_pool_cents`. Two fields are optional at creation: `host_country_code`, the ISO country code of the festival's host, which defaults to `US` and later drives the international determination on travel packages; and `rsvp_window_days`, the number of days an invitation stays open before the expiry sweep, which defaults to 7. A new edition is born in `SETUP` with every aggregate ledger field — fees collected, refunds, travel committed, penalty sink, hotel nights allocated, prize money committed and disbursed — at zero.

Intake cannot open until the edition has pricing and eligibility policy. Advancing from `SETUP` to `INTAKE_OPEN` requires that at least one category configuration exist for the edition; otherwise the advance is rejected with `ERR_NO_CATEGORY_CONFIG`. A category configuration is created per edition and per `category` — one of `NARRATIVE_FEATURE`, `DOCUMENTARY_FEATURE`, `SHORT_FILM`, or `EPISODIC` — and a second configuration for the same edition and category is rejected with `ERR_DUPLICATE_CATEGORY_CONFIG`. The configuration carries the inclusive runtime window `min_runtime_minutes` to `max_runtime_minutes`, the `premiere_requirement` (one of `WORLD_REQUIRED`, `NORTH_AMERICA_REQUIRED`, `US_REQUIRED`, or `NONE`), the `completion_cutoff` date a film must have been completed on or after, and the three tier prices `early_fee_cents`, `regular_fee_cents`, and `late_fee_cents`. It also declares `screener_count_required`, the number of scored assignments a film must accumulate before its official composite score is computed, defaulting to 3. An administrator can read back the configurations of an edition at any time; the listing accepts `limit` and `offset`.

Intake closes in one of two ways: a `FESTIVAL_ADMIN` may advance the edition `INTAKE_OPEN` → `INTAKE_CLOSED` directly, or the clock sweep of §2.4 performs the same close automatically once the logical clock passes `late_deadline_at`. Either way, no new submissions or checkouts are accepted for the edition from that moment on — the posture gate rejects them.

Filmmakers enter the system through open registration: a caller using the `PUBLIC` role registers a submitter with a `legal_name`, a contact `email`, and a `country_of_residence` ISO code. Two flags shape pricing later: `is_student`, which entitles the submitter to a 25 percent discount, and `is_member`, which entitles them to 10 percent; both default to false. An `email` already registered is rejected with `ERR_DUPLICATE_EMAIL`. A `FILMMAKER` may read back only their own submitter record.

Programmers are onboarded by a `FESTIVAL_ADMIN` with a `display_name`, a unique `email`, and a `seniority` of `STAFF`, `SENIOR`, or `LEAD` — the seniority later determines how heavily each programmer's score weighs in the composite. The profile also records `categories_covered`, the set of categories the programmer may be assigned to screen; `coi_production_companies`, the production companies the programmer is conflicted with, defaulting to empty; `max_active_assignments`, the cap on assignments the programmer may hold open at once, defaulting to 12; and `active`, defaulting to true, since only active programmers may receive assignments. The system maintains `active_assignment_count`, the number of assignments the programmer currently holds in `ASSIGNED` status. An administrator may later patch a programmer's `active`, `categories_covered`, `max_active_assignments`, or `coi_production_companies`; flipping `active` from true to false recuses every assignment the programmer currently holds and runs the replacement selector of §3.4 for each.

### 3.2. Intake: Submissions, Fees, and Payment

A `FILMMAKER` creates a submission with a payload containing the `edition_id`, the `category`, the film's `title`, its `runtime_minutes`, the `completion_date` as an ISO date, the declared `premiere_status` — one of `WORLD`, `INTERNATIONAL`, `NORTH_AMERICA`, `US`, `REGIONAL`, or `NONE` — the `production_company` used later for conflict-of-interest matching, and the exhibition `format`, one of `DCP_2K`, `DCP_4K`, `FILM_35MM`, or `PRORES_4444`. The server stamps `submitter_id` from the caller's `X-User-ID`, and the film is born in `DRAFT` with `payment_status` `UNPAID`, `needs_info_resolved` false, and an empty `award_names` list. Creation is gated: the edition must be in `INTAKE_OPEN` posture, or the create is rejected with `ERR_EDITION_PHASE_FORBIDDEN`; and the logical clock must read at or after the edition's `intake_open_at`, or the create fails with `ERR_INTAKE_NOT_YET_OPEN`. The referenced edition must exist and the referenced category must be configured for that edition — a category with no configuration yields `ERR_NO_CATEGORY_CONFIG`, and a body reference that resolves to nothing yields `ERR_REFERENTIAL_INTEGRITY` (HTTP 422). Eligibility fields are checked at the door: a `runtime_minutes` outside the category's inclusive minimum-to-maximum window is rejected with `ERR_INELIGIBLE_RUNTIME`, a `completion_date` earlier than the category's `completion_cutoff` is rejected with `ERR_INELIGIBLE_COMPLETION_DATE`, and a `title` the same submitter has already used for a submission in this edition is rejected with `ERR_DUPLICATE_SUBMISSION`. A filmmaker browsing the submission listing — filterable by `edition_id`, `submitter_id`, `status`, `category`, `limit`, and `offset` — sees only their own submissions regardless of the filters supplied, and may read only their own submission by id.

While a submission is in `DRAFT` or `NEEDS_INFO`, its filmmaker may amend it, passing any of `title`, `runtime_minutes`, `completion_date`, `premiere_status`, `production_company`, or `format`; the amendment re-validates the runtime, completion, and premiere fields against the category configuration, increments the submission's `version`, and — when the film is in `NEEDS_INFO` — sets `needs_info_resolved` to true. Amending a submission in any other status is rejected with `ERR_INVALID_STATE`.

Payment begins at checkout, which creates a fee payment for a `DRAFT` submission — or, if an `INITIATED` payment already exists for it, returns that same payment unchanged. Checkout honors the same intake gates as creation: outside `INTAKE_OPEN` the request fails with `ERR_EDITION_PHASE_FORBIDDEN`, and before `intake_open_at` it fails with `ERR_INTAKE_NOT_YET_OPEN`. The fee is priced by tier against the logical clock: when the clock reads at or before `early_deadline_at` the `EARLY` tier applies, when it reads after `early_deadline_at` and at or before `regular_deadline_at` the `REGULAR` tier applies, and when it reads after `regular_deadline_at` and at or before `late_deadline_at` the `LATE` tier applies. A clock past `late_deadline_at` is unreachable at checkout, because the sweep has already closed intake and the posture gate rejects the request. The chosen tier is recorded in `tier_applied`, and the category's matching price becomes `base_fee_cents`.

Discounts then apply in a pinned order. The student discount is computed first: when the submitter's `is_student` flag is true at checkout — snapshotted onto the payment as `student_discount_applied` — `student_discount_cents` is one quarter of `base_fee_cents`, rounded half up to whole cents; otherwise it is zero. The member discount is computed second: when `is_member` is true at checkout — snapshotted as `member_discount_applied` — `member_discount_cents` is one tenth of the base minus the student discount, again rounded half up to whole cents; otherwise zero. The charged `amount_cents` is the base minus both discounts. Consider a base of 5500 cents with both flags set: the student discount is one quarter of 5500, exactly 1375; the member discount is one tenth of the remaining 4125, which is 412.50 and rounds half up to 413; the amount due is 5500 minus 1375 minus 413, which is 3712 cents. Computing the member discount as a single combined rate against the student-discounted base would yield 3713 cents and is forbidden — each discount is rounded individually before subtraction. When neither flag is set, the amount equals the base. The new payment carries status `INITIATED` with `paid_at` null and `refunded_amount_cents` zero.

A payment leaves `INITIATED` only through the admin-driven payment simulator, which takes a `fee_payment_id` and an `outcome` of `SUCCEEDED` or `FAILED`. On success the payment's `paid_at` is stamped with the logical clock, the submission moves `DRAFT` → `SUBMITTED`, its `payment_status` moves `UNPAID` → `PAID`, and the edition's fee aggregates are recomputed. On failure the payment becomes `FAILED` and the submission remains `DRAFT`; the filmmaker may simply check out again, which creates a fresh payment since none is `INITIATED`.

Withdrawal is the filmmaker's own act, available from every non-terminal program status — `DRAFT`, `SUBMITTED`, `NEEDS_INFO`, `ELIGIBLE`, `IN_SCREENING`, `ADVANCED`, `INVITED`, `WAITLISTED`, `CONFIRMED`, or `PROGRAMMED` — and lands the submission in `WITHDRAWN`. The unwind depends on how far the film travelled. When a `SUCCEEDED` payment exists and no screening slot ever reached `HELD`, `CONFIRMED`, or `PLAYED` for the film's slate entry, the system auto-refunds half of `amount_cents`, rounded half up to whole cents — an amount of 6075 cents refunds 3038 — setting `refunded_amount_cents`, moving the payment to `PARTIALLY_REFUNDED`, the `payment_status` to `PARTIALLY_REFUNDED`, and recomputing the edition's `total_refunded_cents`. If the film holds a slate entry in `NOMINATED`, `INVITED`, `CONFIRMED`, or `PROGRAMMED` status, that entry is dropped to `DROPPED` and the waitlist-promotion cascade of §3.6 fires. Every slot held for the entry returns to `OPEN` with its `slate_entry_id` cleared, and every confirmed slot is cancelled with the agreement's `used_screening_count` decremented once per cancelled slot. A `DRAFT` film whose only payment is still `INITIATED` has that payment voided to `FAILED`.

An administrator may instead grant a full cooling-window refund on a payment, supplying a `reason`. The payment must be `SUCCEEDED` — any other status yields `ERR_PAYMENT_NOT_REFUNDABLE` — the logical clock must read no later than 48 hours after `paid_at`, beyond which the request fails with `ERR_REFUND_WINDOW_CLOSED`, and the submission must still be `SUBMITTED`, failing with `ERR_REFUND_NOT_ALLOWED` in any other status. A granted refund moves the payment to `REFUNDED`, sets `refunded_amount_cents` to the full `amount_cents`, moves the submission's `payment_status` to `REFUNDED`, and recomputes the edition totals. Administrators and owning filmmakers can list payments filtered by `submission_id` and `status`, and a filmmaker reads only payments belonging to their own submissions.

### 3.3. Eligibility Rulings and the Information-Request Loop

Once a film is `SUBMITTED`, eligibility rests with a `FESTIVAL_ADMIN`, who records a ruling by supplying a `decision` of `ELIGIBLE`, `INELIGIBLE`, or `NEEDS_INFO`; the latter two require a `reason`. Rulings are accepted only while the edition is in `INTAKE_OPEN`, `INTAKE_CLOSED`, or `SCREENING`; at any other phase the decision is rejected with `ERR_EDITION_PHASE_FORBIDDEN`.

A ruling of `ELIGIBLE` certifies that the film's `premiere_status` satisfies the category's `premiere_requirement`, and a film that does not satisfy it is rejected with `ERR_INELIGIBLE_PREMIERE`. Satisfaction follows the premiere hierarchy: a category requiring `WORLD_REQUIRED` accepts only a `WORLD` premiere; `NORTH_AMERICA_REQUIRED` accepts `WORLD`, `INTERNATIONAL`, or `NORTH_AMERICA`; `US_REQUIRED` accepts `WORLD`, `INTERNATIONAL`, `NORTH_AMERICA`, or `US`; and `NONE` accepts any declared premiere status. When the edition is already in `SCREENING`, an eligible ruling moves the film `SUBMITTED` → `IN_SCREENING` directly; at earlier phases it moves `SUBMITTED` → `ELIGIBLE`, and the film waits for the posture cascade. A ruling of `INELIGIBLE` is terminal for the film. A ruling of `NEEDS_INFO` returns the film to the filmmaker with `needs_info_resolved` cleared to false; after amending the record — which sets the flag true — the filmmaker resubmits, and a resubmission attempted while the flag is still false is rejected with `ERR_UNRESOLVED_INFO_REQUEST`. The `SUBMITTED` → `NEEDS_INFO` → `SUBMITTED` revision cycle may repeat as often as needed.

When the administrator advances the edition `INTAKE_CLOSED` → `SCREENING`, every film sitting in `ELIGIBLE` moves to `IN_SCREENING` in one bulk cascade — the screening room opens only for films that have cleared eligibility. Advancing onward from `SCREENING` to `DELIBERATION` is gated twice: no submission may remain in `SUBMITTED` or `NEEDS_INFO`, failing with `ERR_ELIGIBILITY_DECISIONS_PENDING`, and every film in `IN_SCREENING` must hold at least its category's `screener_count_required` assignments in `SCORED` status, failing with `ERR_SCORING_INCOMPLETE`. The same advance locks the scoring record: every score of the edition has its `locked` flag set true, pinning the deliberation record.

### 3.4. Screening: Assignments, Recusal, and Scores

During `SCREENING`, the `PROGRAM_CHAIR` distributes films to programmers by creating screener assignments carrying `submission_id`, `programmer_id`, and a `due_at` deadline. Assignment is gated on both the film and the programmer. The edition must be in `SCREENING` posture, failing with `ERR_EDITION_PHASE_FORBIDDEN`, and the film must be `IN_SCREENING`, failing with `ERR_INVALID_STATE`. The programmer must be active and must list the film's category in `categories_covered`. A conflict of interest is disqualifying: when the film's `production_company` appears in the programmer's `coi_production_companies`, the assignment is rejected with `ERR_COI_RECUSAL_REQUIRED`. A programmer already holding `max_active_assignments` open assignments cannot take another, rejected with `ERR_ASSIGNMENT_CAP`, and a duplicate open assignment for the same submission–programmer pair is rejected with `ERR_DUPLICATE_ASSIGNMENT`. A successful creation lands the assignment in `ASSIGNED` and increments the programmer's `active_assignment_count`. Assignments can be listed with `submission_id`, `programmer_id`, and `status` filters — a `PROGRAMMER` sees only their own — and read back individually.

Scoring is the assigned programmer's own act: the caller's `X-User-ID` must equal the assignment's `programmer_id`, failing with `ERR_FORBIDDEN_OWNERSHIP`, and the edition must still be in `SCREENING`, failing with `ERR_EDITION_PHASE_FORBIDDEN`. The score payload carries the four rubric axes `originality`, `craft`, `story`, and `overall` — each an integer from 1 to 10, with out-of-range values rejected as `ERR_VALIDATION` — plus a `recommendation` of `STRONG_ADVOCATE`, `ADVOCATE`, `NEUTRAL`, `PASS`, or `STRONG_PASS`. Each assignment accepts exactly one score, its `assignment_id` unique; a second score against the same assignment is rejected with `ERR_SCORE_EXISTS`. Filing the score moves the assignment `ASSIGNED` → `SCORED`, decrements the programmer's `active_assignment_count`, and recomputes the film's two score aggregates.

The aggregates differ in weighting and availability. The `provisional_score` is the simple mean of `overall` across the film's `SCORED` assignments, rounded half up to three decimal places, and is null while no score exists. The `composite_score` is the seniority-weighted mean of the same inputs — `STAFF` scores weigh 1.0, `SENIOR` 1.5, and `LEAD` 2.0 — computed as the sum of each `overall` multiplied by its programmer's weight, divided by the sum of the weights, rounded half up once to three decimal places; it remains null until the count of `SCORED` assignments reaches the category's `screener_count_required`. Only `SCORED` assignments feed either figure — `ASSIGNED`, `RECUSED`, and `EXPIRED` assignments are excluded. A worked example: scores of 8 from a `LEAD`, 7 from a `SENIOR`, and 9 from a `STAFF` give a weighted sum of 35.5 against a total weight of 4.5, a quotient of 7.8888… that rounds to 7.889, while the provisional mean is 8.000. While the edition remains in `SCREENING`, the scoring programmer may revise a score's `originality`, `craft`, `story`, `overall`, or `recommendation`, and the film's aggregates recompute on each edit; once the edition advances to `DELIBERATION` the score's `locked` flag is true and edits are rejected with `ERR_SCORES_LOCKED`.

Two paths retire an open assignment without a score, and both run the same replacement selector. A programmer may recuse themself, moving the assignment `ASSIGNED` → `RECUSED`, and the clock sweep expires any non-terminal assignment once it passes `due_at`, moving it `ASSIGNED` → `EXPIRED`; either way the programmer's `active_assignment_count` is decremented. The selector then builds the replacement pool for the same submission: programmers who are active, who cover the film's category, whose `coi_production_companies` do not contain the film's `production_company`, who are under their assignment cap, and who have never held an assignment for this submission in any status. The pool is ranked by `active_assignment_count` ascending, ties broken by the programmer's `created_at` ascending, and the first-ranked programmer receives a fresh `ASSIGNED` assignment; the retired assignment's `replaced_by_assignment_id` points at that new row. When the pool is empty no replacement is created and `replaced_by_assignment_id` stays null.

### 3.5. Deliberation: Building and Locking the Slates

Programming takes shape on slates. A `PROGRAM_CHAIR` creates a slate for an edition by naming its `edition_id`, its `section` — one of `US_DRAMATIC`, `US_DOCUMENTARY`, `WORLD_CINEMA_DRAMATIC`, `NEXT`, `PREMIERES`, `MIDNIGHT`, or `SHORTS` — and its `capacity_slots`, the number of main-lane berths the slate offers, which must be at least 1. One slate per section per edition: a duplicate section for the same edition is rejected with `ERR_DUPLICATE_SLATE`. A new slate is `OPEN` with an `entry_count` of zero and `locked_at` null. When the edition reaches `DELIBERATION`, the chair opens the slate for editing, moving it `OPEN` → `DELIBERATING`; attempting that move in any other edition phase fails with `ERR_EDITION_PHASE_FORBIDDEN`.

Entries are added to a slate only while the edition is in `DELIBERATION` posture — at any other phase the add is rejected with `ERR_EDITION_PHASE_FORBIDDEN` — and only while the slate itself is `DELIBERATING`; the slate's version guard applies, so the add carries `submission_id` and the `expected_slate_version` of §2.7. Two structural rules shape what may be nominated. Section–category mapping confines `SHORT_FILM` submissions to `SHORTS` slates and confines `NARRATIVE_FEATURE`, `DOCUMENTARY_FEATURE`, and `EPISODIC` submissions to the non-`SHORTS` sections, with mismatches rejected as `ERR_SECTION_CATEGORY_MISMATCH`; and a submission that already holds a non-`DROPPED` entry on the same slate is rejected with `ERR_DUPLICATE_ENTRY`. A film must be `IN_SCREENING` to be nominated; the add moves it `IN_SCREENING` → `ADVANCED`. The new entry is born `NOMINATED` in lane `UNASSIGNED`, takes a `rank_position` one above the slate's current maximum, and stamps the slate's `last_entry_added_by` with the caller's `X-User-ID`; the slate's `version` increments on every add. The slate's entries are listed in `rank_position` ascending order — filterable by `status` — and the slate listing itself accepts `edition_id`, `status`, `limit`, and `offset`.

Removing an entry is the compensating mirror of the add, available only while the slate is `DELIBERATING` and otherwise rejected with `ERR_INVALID_STATE`. The entry moves to `DROPPED`, its film returns `ADVANCED` → `IN_SCREENING`, the surviving entries' `rank_position` values are compacted upward preserving their relative order, and the slate's `version` increments again. `entry_count` always reflects the count of entries that are not `DROPPED`.

Locking a slate belongs to the `FESTIVAL_DIRECTOR`, never to the chair who built it, and three gates stand in front of the lock, evaluated in the precedence order of §2.9 — segregation first, then underfill, then the score threshold. The segregation-of-duties gate fires when the slate holds at least one entry and the director's `X-User-ID` equals the slate's `last_entry_added_by`, rejected with `ERR_SEGREGATION_OF_DUTIES`; the person who placed the last entry may not also certify the slate. The underfill gate requires `entry_count` to be at least `capacity_slots`, failing with `ERR_SLATE_UNDERFILLED`. The threshold gate requires every entry whose `rank_position` is at or below `capacity_slots` — the future main lane — to have a non-null `composite_score` of at least 7.500, compared at its stored three-decimal precision so that exactly 7.500 passes; any shortfall is rejected with `ERR_BELOW_SLATE_THRESHOLD`. A successful lock assigns lanes — entries at or below `capacity_slots` become `MAIN`, the rest `WAITLIST` — snapshots each entry's `composite_score` into `locked_composite_score`, and stamps `locked_at` with the logical clock.

A lock is not irreversible: before any invitation has been issued, the director may reopen a slate, but only while every entry is still `NOMINATED` — any entry that has progressed further fails the reopen with `ERR_INVALID_STATE`. Reopening returns the slate to `DELIBERATING`, resets every entry's lane to `UNASSIGNED`, and clears every `locked_composite_score`. The edition itself cannot advance `DELIBERATION` → `SLATE_LOCKED` until at least one slate exists and every slate of the edition is `LOCKED`, failing with `ERR_SLATES_UNLOCKED`; from there the administrator advances the edition to `NOTIFICATION`.

### 3.6. Notification: Invitations, RSVP, and the Waitlist

Invitations go out in one bulk act by the `FESTIVAL_DIRECTOR`, permitted only while the edition is in `NOTIFICATION` and only while every slate of the edition is `LOCKED` — a reopened slate blocks the issuance with `ERR_SLATES_UNLOCKED`, and any other phase yields `ERR_EDITION_PHASE_FORBIDDEN`. For each locked slate, every `NOMINATED` entry in the `MAIN` lane becomes `INVITED`, its `rsvp_deadline_at` set to the issue instant plus the edition's `rsvp_window_days`, and its film moves `ADVANCED` → `INVITED`. Entries in the `WAITLIST` lane remain `NOMINATED`, but their films move `ADVANCED` → `WAITLISTED`. Films still `IN_SCREENING` that sit on no locked slate are declined in the same sweep, moving to `DECLINED`. The issuance response enumerates what happened through `invited_entry_ids`, `declined_submission_ids`, and `waitlisted_submission_ids`. Individual entries can be read back by id, and the entry listing — filterable by `submission_id`, `slate_id`, `status`, and `lane` — shows a `FILMMAKER` only entries attached to their own submissions.

The invited filmmaker answers through the entry's respond action with an `accept` flag. Acceptance moves the entry `INVITED` → `CONFIRMED` and the film `INVITED` → `CONFIRMED`, and the system immediately creates two `DRAFT` artifacts linked to the film: a travel package — one per confirmed submission — and an exhibition agreement keyed to the accepting entry. Declining moves the entry `INVITED` → `DECLINED` and the film `INVITED` → `DECLINED_BY_FILMMAKER`, and fires the waitlist-promotion cascade. Should the filmmaker simply let the deadline lapse, the clock sweep moves the entry `INVITED` → `EXPIRED` and the film `INVITED` → `EXPIRED` once it passes `rsvp_deadline_at`, firing the same promotion cascade.

The promotion cascade always works the same way. Within the same slate, the selector takes the entries still in `NOMINATED` status with lane `WAITLIST`, picks the one with the smallest `rank_position`, promotes it to lane `MAIN` and status `INVITED`, sets its `rsvp_deadline_at` to the current instant plus `rsvp_window_days`, and moves its film `WAITLISTED` → `INVITED`. When no waitlisted `NOMINATED` entry exists, the cascade does nothing — the berth simply goes unfilled.

The edition leaves `NOTIFICATION` for `SCHEDULING` only when every invitation has been answered or swept: any entry still `INVITED` blocks the advance with `ERR_INVITATIONS_PENDING`.

### 3.7. Exhibition Agreements and Travel Packages

Acceptance of an invitation creates the exhibition agreement in `DRAFT`, one per submission, pinned to the slate entry whose acceptance created it. The `FESTIVAL_DIRECTOR` issues it by supplying the license terms: `rights_scope` — one of `FESTIVAL_WORLD`, `FESTIVAL_NORTH_AMERICA`, or `FESTIVAL_US` — `licensed_screening_count`, the maximum number of confirmed screenings the license covers, the `exclusivity_until` instant marking the end of the exclusivity window, which is informational, and `revenue_share_pct`, the box-office share owed to the filmmaker. Issuance moves the agreement `DRAFT` → `ISSUED`; the filmmaker's signature moves it `ISSUED` → `SIGNED` and pins `submission_version_at_signing` to the submission's current `version`. Agreements can be listed with `submission_id`, `slate_entry_id`, and `status` filters, with filmmakers seeing only their own submissions' agreements.

Terms may be amended while the agreement is `SIGNED` or `ACTIVE`; the amend carries the agreement's OCC field `expected_agreement_version` per §2.7 and may change any of `rights_scope`, `licensed_screening_count`, `exclusivity_until`, or `revenue_share_pct`. The license may never be cut beneath usage already consumed — a `licensed_screening_count` below the agreement's `used_screening_count` is rejected with `ERR_LICENSED_BELOW_USED`. A successful amend leaves the agreement in `ACTIVE`, refreshes `submission_version_at_signing` to the submission's current version, and increments the agreement's own `version`. Termination is likewise the director's act, moving a `SIGNED` or `ACTIVE` agreement to terminal `TERMINATED`, but it is forbidden while any slot in `HELD` or `CONFIRMED` references the entry, failing with `ERR_ACTIVE_SLOTS_EXIST`. The `used_screening_count` itself starts at zero and is driven entirely by the scheduling cascade of §3.8.

The travel package, also born `DRAFT` on acceptance and linked to both the submission and — denormalized for budget checks — the edition, is the filmmaker's to complete. The filmmaker submits `delegate_count` (at least 1 traveler), `origin_country_code`, and `hotel_nights_requested` (at least 1 room-night); submission moves the package `DRAFT` → `SUBMITTED` — or `CHANGES_REQUESTED` → `SUBMITTED` on the revision loop — and computes two fields. The `is_international` flag is true when `origin_country_code` differs from the edition's `host_country_code`. The `raw_stipend_cents` is the uncapped-by-budget figure: a base of 50000 cents domestic or 150000 cents international, plus 20000 cents for each covered delegate beyond the first, with at most 2 delegates covered — so at most one extra-delegate allowance — and the whole figure capped at 200000 cents per film. Worked examples: an international production sending 3 delegates computes 150000 plus a single 20000 allowance, 170000 cents, below the cap; a domestic solo delegate computes 50000.

Approval belongs to the `TRAVEL_COORDINATOR` and is where the raw figure meets the edition's pools; the call carries the edition's OCC field `expected_edition_version` per §2.7. Two resource gates guard approval: an edition whose `travel_budget_remaining` has reached zero rejects with `ERR_TRAVEL_BUDGET_EXHAUSTED`, and an edition whose `hotel_nights_remaining` has reached zero rejects with `ERR_HOTEL_NIGHTS_EXHAUSTED`. On approval the package's `stipend_cents` is set to the smaller of `raw_stipend_cents` and the edition's `travel_budget_remaining` computed without this package — so a raw figure of 170000 against 100000 remaining commits exactly 100000 — and `hotel_nights_allocated` is set to the smaller of `hotel_nights_requested` and the edition's `hotel_nights_remaining`; until approval both fields read zero. Approval recomputes the edition's travel and hotel aggregates and increments the edition's `version`. When the package needs work, the coordinator requests changes, moving it `SUBMITTED` → `CHANGES_REQUESTED`, and the filmmaker resubmits through the same submit action; the revision cycle may repeat.

Once approved, the coordinator marks the package `APPROVED` → `BOOKED` when travel is ticketed. Cancellation — available to the coordinator and to the filmmaker who owns the package — moves an `APPROVED` or `BOOKED` package to terminal `CANCELLED`: the allocated hotel nights and committed stipend are released back to the edition's pools by zeroing `hotel_nights_allocated` and `stipend_cents`, and a package cancelled from `BOOKED` additionally forfeits a cancellation penalty — `penalty_cents` is one quarter of the package's original stipend, rounded half up, and flows into the edition's `travel_penalty_sink_cents`, while cancelling a merely `APPROVED` package carries no penalty. Either way the edition aggregates recompute, restoring the INV-HOTEL and INV-TRAVEL invariants of §2.8. After the festival has gone live, the coordinator reconciles a booked package — `BOOKED` → `RECONCILED` — an act permitted only in `FESTIVAL_LIVE` or `AWARDS_NIGHT` and otherwise rejected with `ERR_EDITION_PHASE_FORBIDDEN`. Packages are listed with `submission_id`, `edition_id`, and `status` filters; a filmmaker sees only packages for their own submissions.

### 3.8. The Screening Grid: Venues, Slots, and Screenings

With invitations answered, `SCHEDULING_OPS` builds the grid. Venues come first, created by a `FESTIVAL_ADMIN` with `edition_id`, a `name`, an informational `seat_capacity`, the `formats_supported` — a subset of `DCP_2K`, `DCP_4K`, `FILM_35MM`, and `PRORES_4444` — and a `turnover_minutes` buffer required between consecutive slots on the venue, defaulting to 30. Venue creation is forbidden once the edition is `FESTIVAL_LIVE` or beyond, rejected with `ERR_EDITION_PHASE_FORBIDDEN`; the venue listing accepts an `edition_id` filter.

Screening slots are created on a venue's grid by `SCHEDULING_OPS`, each carrying `venue_id`, a `slot_type` of `PREMIERE`, `PUBLIC`, `PRESS_INDUSTRY`, or `AWARDS_ENCORE`, and a `start_at` and `end_at`; creation takes the venue's OCC field `expected_venue_version` per §2.7, and each created slot increments the venue's `version`. Every slot must sit inside the festival window — `start_at` at or after `festival_start_at` and `end_at` at or before `festival_end_at` — with violations rejected as `ERR_SLOT_OUTSIDE_FESTIVAL_WINDOW`, and `end_at` must be later than `start_at`, with violations rejected as `ERR_VALIDATION`. Slots on the same venue may not collide: every existing slot of that venue in `OPEN`, `HELD`, `CONFIRMED`, or `PLAYED` status — `CANCELLED` slots drop out of the occupation set — conflicts with a candidate unless the candidate's end plus the venue's `turnover_minutes` is at or before the existing slot's start, or the existing slot's end plus the turnover buffer is at or before the candidate's start. Two slots separated by exactly the turnover buffer therefore do not conflict, and a genuine collision is rejected with `ERR_VENUE_OVERLAP`. A new slot is `OPEN` with its `slate_entry_id` null; slots are listed with `venue_id`, `slate_entry_id`, `slot_type`, and `status` filters.

Holding a slot for a film is the most heavily gated act on the grid, available only while the edition is in `SCHEDULING`, otherwise `ERR_EDITION_PHASE_FORBIDDEN`. The hold names a `slate_entry_id`, and that entry must be `CONFIRMED`, failing with `ERR_ENTRY_NOT_CONFIRMED`; the exhibition agreement for the entry's submission must be `SIGNED` or `ACTIVE`, failing with `ERR_AGREEMENT_NOT_SIGNED`. Premiere discipline is enforced per entry: a `PREMIERE` hold is rejected with `ERR_PREMIERE_SLOT_EXISTS` when the entry already has a `PREMIERE` slot in `HELD`, `CONFIRMED`, or `PLAYED`, and a `PUBLIC` or `PRESS_INDUSTRY` hold is rejected with `ERR_PREMIERE_WINDOW_VIOLATION` unless a `PREMIERE` slot for the same entry exists in one of those three statuses starting earlier than the slot being held; `AWARDS_ENCORE` slots carry no premiere-window constraint. The film's `format` must appear in the venue's `formats_supported`, failing with `ERR_FORMAT_UNSUPPORTED`, and the slot's duration must cover the film's `runtime_minutes` plus 15 minutes of audience Q&A, failing with `ERR_SLOT_TOO_SHORT`. A successful hold sets `slate_entry_id` on the slot and moves it `OPEN` → `HELD`.

A hold can be released, returning the slot `HELD` → `OPEN` and clearing its `slate_entry_id`; the hold–release cycle may repeat. Confirming a hold moves the slot `HELD` → `CONFIRMED` and draws against the license: confirmation is rejected with `ERR_LICENSED_COUNT_EXCEEDED` when the agreement's `used_screening_count` plus one would exceed `licensed_screening_count`. Each confirmation increments `used_screening_count`, flips a `SIGNED` agreement to `ACTIVE` on the first confirmation, and — on the first confirmed slot for the entry — moves the slate entry `CONFIRMED` → `PROGRAMMED` and its submission `CONFIRMED` → `PROGRAMMED`. Cancelling a confirmed slot moves it `CONFIRMED` → `CANCELLED`, decrements `used_screening_count`, and, when the cancellation leaves the entry with zero `CONFIRMED` or `PLAYED` slots, reverses both the entry and the submission from `PROGRAMMED` back to `CONFIRMED` — the `CONFIRMED` ↔ `PROGRAMMED` pair is a genuine cycle driven by slot occupancy. Finally, during `FESTIVAL_LIVE` a confirmed slot is marked played, moving `CONFIRMED` → `PLAYED`; marking at any other phase is rejected with `ERR_EDITION_PHASE_FORBIDDEN`.

The festival itself opens when the administrator advances the edition `SCHEDULING` → `FESTIVAL_LIVE`, which requires the logical clock to read at or after `festival_start_at`, failing with `ERR_FESTIVAL_NOT_STARTED`. The advance closes out the waitlist: every film still `WAITLISTED` moves to `DECLINED`, and its waitlist-lane entry — still `NOMINATED` — moves to `RELEASED`.

### 3.9. Awards: Jury Panels, Ballots, and the Instant-Runoff Tally

Awards administration runs in parallel with the festival. An `AWARDS_ADMIN` empanels jurors per edition with `edition_id`, a `display_name`, and `coi_production_companies` defaulting to empty; juror listings accept an `edition_id` filter, and the ballots cast by a juror can be listed with an `award_id` filter. The administrator creates awards with `edition_id`, a `name` such as a grand jury prize, a `section` scoping the candidate films, a `prize_cents` amount, and `assigned_juror_ids`, the jurors of the same edition empaneled on the award — at least one, and a juror from another edition fails creation with `ERR_REFERENTIAL_INTEGRITY`. The prize must fit the purse: `prize_cents` may not exceed `prize_pool_cents` minus the prizes of every award already created for the edition — awards are never cancelled, so each existing award, even a disbursed one, remains charged against the pool — and an overdraw is rejected with `ERR_PRIZE_POOL_EXHAUSTED`. A new award is born in `SETUP` with `winner_submission_id` null, an empty `rounds_log`, and `disbursed_amount_cents` zero; the award listing accepts `edition_id`, `status`, and `winner_submission_id` filters.

Voting opens only once the festival is live: opening moves the award `SETUP` → `VOTING_OPEN` and is rejected at any other phase with `ERR_EDITION_PHASE_FORBIDDEN`. Each empaneled juror casts exactly one ballot per award — a second ballot is rejected with `ERR_BALLOT_EXISTS`, and a juror not listed in the award's `assigned_juror_ids` is rejected with `ERR_JUROR_NOT_ON_PANEL`. The ballot carries `ranked_submission_ids`, the juror's candidate ordering most-preferred first, which must be non-empty and free of duplicates. Candidates are exactly the submissions in `PROGRAMMED` status whose slate's `section` equals the award's section; a ballot ranking anything else, an empty ballot, or a ballot with duplicates is rejected with `ERR_BALLOT_INVALID`. Conflict-of-interest discipline follows the juror: a ballot ranking a film whose `production_company` appears in the juror's `coi_production_companies` is rejected with `ERR_JUROR_CONFLICT`. The ballot's `juror_id` is stamped from the caller's `X-User-ID` and its `submitted_at` from the logical clock; per §2.6 a ballot is immutable, carrying only `id` and `created_at`.

While voting is open, observers may consult the provisional standings, which report raw first-preference counts per candidate in `first_preference_counts` and the current leaders in `provisional_leaders`. These standings are deliberately provisional — a film can lead on first preferences and still lose the runoff, as the tally below shows.

Closing the vote runs the official instant-runoff tally, which requires quorum: the number of ballots submitted must be at least half the panel size rounded up — that is, the count of `assigned_juror_ids` divided by two, rounded up — failing with `ERR_QUORUM_NOT_MET`. The tally then iterates. The candidates are the `PROGRAMMED` submissions of the award's section; the active ballots begin as every ballot cast. Each round counts current first preferences among active candidates across the active ballots. A candidate holding strictly more than half of the active ballots wins immediately. Otherwise the candidate with the fewest current first preferences is eliminated; when several candidates tie for fewest, the eliminated one is the tied candidate whose earliest current first-preference ballot — ordered by the ballot's `submitted_at`, then by its `created_at` — is the latest; still tied, the candidate with the fewest total mentions anywhere across all ballots is eliminated; and the final fallback eliminates the candidate whose submission was created earliest. A ballot whose ranked candidates have all been eliminated becomes exhausted and leaves the active set, shrinking the denominator for later rounds. Every round's elimination is recorded in `rounds_log`, the winner is stored in `winner_submission_id`, and the award moves `VOTING_OPEN` → `TALLIED`. A worked example with five ballots — two ranking A over C, two ranking B over A, one ranking C over B — counts first preferences at two for A, two for B, and one for C; C is eliminated, its ballot transfers to B, and B wins three to two even though A had tied B on first preferences.

Announcement belongs to the `FESTIVAL_DIRECTOR` and waits for `AWARDS_NIGHT` — at any other phase it is rejected with `ERR_EDITION_PHASE_FORBIDDEN`. Announcing moves the award `TALLIED` → `ANNOUNCED` and appends the award's name to the winning submission's `award_names`. Disbursement by the `AWARDS_ADMIN` moves the award `ANNOUNCED` → `DISBURSED`, pays the prize in full — `disbursed_amount_cents` equals `prize_cents` with no withholding — and recomputes the edition's `prize_disbursed_cents`.

When the festival's public screenings have played out, the administrator advances the edition `FESTIVAL_LIVE` → `AWARDS_NIGHT`; that transition carries no gate. The season ends when the administrator advances the edition `AWARDS_NIGHT` → `CLOSED`, permitted only when every award of the edition has been disbursed — any award short of `DISBURSED` blocks the close with `ERR_AWARDS_PENDING`. `CLOSED` is terminal for the edition.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify or act on an existing resource return `200 OK`; the single removal operation returns `204 No Content` with an empty `data` object. "All authenticated roles" below means every role in §2.1 except `PUBLIC`. Request payloads, preconditions, and side effects are specified in §2 and §3; this table is only the HTTP contract index.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/festival/_clock/set_current_utc` | Set the logical clock; triggers deferred sweeps | FESTIVAL_ADMIN |
| POST | `/festival/_payments/simulate` | Drive a fee payment to a deterministic outcome | FESTIVAL_ADMIN |
| POST | `/festival/editions` | Create a festival edition in SETUP | FESTIVAL_ADMIN |
| GET | `/festival/editions/{id}` | Read an edition including ledger aggregates | All authenticated roles |
| POST | `/festival/editions/{id}/advance` | Advance the edition posture | FESTIVAL_ADMIN |
| POST | `/festival/category-configs` | Create per-category fee and eligibility policy | FESTIVAL_ADMIN |
| GET | `/festival/editions/{id}/category-configs` | List category configs of an edition | All authenticated roles |
| POST | `/festival/submitters` | Register a submitter account | PUBLIC |
| GET | `/festival/submitters/{id}` | Read a submitter (filmmaker: own record only) | FESTIVAL_ADMIN, FILMMAKER |
| POST | `/festival/programmers` | Onboard a programmer | FESTIVAL_ADMIN |
| GET | `/festival/programmers/{id}` | Read a programmer | FESTIVAL_ADMIN, PROGRAM_CHAIR, PROGRAMMER |
| PATCH | `/festival/programmers/{id}` | Update programmer flags and capacity | FESTIVAL_ADMIN |
| POST | `/festival/submissions` | Create a submission in DRAFT | FILMMAKER |
| GET | `/festival/submissions/{id}` | Read a submission (filmmaker: own only) | All authenticated roles |
| GET | `/festival/submissions` | List submissions with filters | All authenticated roles |
| PATCH | `/festival/submissions/{id}` | Amend a DRAFT or NEEDS_INFO submission | FILMMAKER |
| POST | `/festival/submissions/{id}/checkout` | Create or return the open fee payment | FILMMAKER |
| POST | `/festival/submissions/{id}/withdraw` | Withdraw a submission | FILMMAKER |
| POST | `/festival/submissions/{id}/eligibility-decision` | Record an eligibility ruling | FESTIVAL_ADMIN |
| POST | `/festival/submissions/{id}/resubmit` | Return a NEEDS_INFO film to SUBMITTED | FILMMAKER |
| GET | `/festival/fee-payments/{id}` | Read a payment (filmmaker: own only) | FESTIVAL_ADMIN, FILMMAKER |
| GET | `/festival/fee-payments` | List payments with filters | FESTIVAL_ADMIN, FILMMAKER |
| POST | `/festival/fee-payments/{id}/refund` | Full cooling-window refund | FESTIVAL_ADMIN |
| POST | `/festival/screener-assignments` | Assign a film to a programmer | PROGRAM_CHAIR |
| GET | `/festival/screener-assignments/{id}` | Read an assignment | FESTIVAL_ADMIN, PROGRAM_CHAIR, PROGRAMMER |
| GET | `/festival/screener-assignments` | List assignments with filters | FESTIVAL_ADMIN, PROGRAM_CHAIR, PROGRAMMER |
| POST | `/festival/screener-assignments/{id}/recuse` | Recuse the owning programmer | PROGRAMMER |
| POST | `/festival/screener-assignments/{id}/scores` | File the score for an assignment | PROGRAMMER |
| GET | `/festival/screener-assignments/{id}/scores` | List the score of an assignment | FESTIVAL_ADMIN, FESTIVAL_DIRECTOR, PROGRAM_CHAIR, PROGRAMMER |
| GET | `/festival/scores/{id}` | Read a score | FESTIVAL_ADMIN, FESTIVAL_DIRECTOR, PROGRAM_CHAIR, PROGRAMMER |
| PATCH | `/festival/scores/{id}` | Edit a score while still unlocked | PROGRAMMER |
| POST | `/festival/slates` | Create a slate for an edition section | PROGRAM_CHAIR |
| GET | `/festival/slates/{id}` | Read a slate | FESTIVAL_ADMIN, FESTIVAL_DIRECTOR, PROGRAM_CHAIR |
| GET | `/festival/slates` | List slates with filters | FESTIVAL_ADMIN, FESTIVAL_DIRECTOR, PROGRAM_CHAIR |
| POST | `/festival/slates/{id}/deliberate` | Open a slate for entry editing | PROGRAM_CHAIR |
| POST | `/festival/slates/{id}/entries` | Add an entry to a slate (OCC) | PROGRAM_CHAIR |
| GET | `/festival/slates/{id}/entries` | List a slate's entries by rank | FESTIVAL_ADMIN, FESTIVAL_DIRECTOR, PROGRAM_CHAIR, FILMMAKER |
| DELETE | `/festival/slates/{id}/entries/{entry_id}` | Remove an entry while deliberating | PROGRAM_CHAIR |
| POST | `/festival/slates/{id}/lock` | Lock a slate with lanes and snapshots | FESTIVAL_DIRECTOR |
| POST | `/festival/slates/{id}/reopen` | Reopen a locked slate before invitations | FESTIVAL_DIRECTOR |
| GET | `/festival/slate-entries/{entry_id}` | Read a slate entry | FESTIVAL_ADMIN, FESTIVAL_DIRECTOR, PROGRAM_CHAIR, SCHEDULING_OPS, FILMMAKER |
| GET | `/festival/slate-entries` | List slate entries with filters | FESTIVAL_ADMIN, FESTIVAL_DIRECTOR, PROGRAM_CHAIR, SCHEDULING_OPS, FILMMAKER |
| POST | `/festival/slate-entries/{entry_id}/respond` | Accept or decline an invitation | FILMMAKER |
| POST | `/festival/editions/{id}/issue-invitations` | Issue invitations for all locked slates | FESTIVAL_DIRECTOR |
| POST | `/festival/venues` | Create a venue for an edition | FESTIVAL_ADMIN |
| GET | `/festival/venues/{id}` | Read a venue | FESTIVAL_ADMIN, FESTIVAL_DIRECTOR, PROGRAM_CHAIR, SCHEDULING_OPS |
| GET | `/festival/venues` | List venues | FESTIVAL_ADMIN, FESTIVAL_DIRECTOR, PROGRAM_CHAIR, SCHEDULING_OPS |
| POST | `/festival/screening-slots` | Create an open slot on a venue grid (OCC) | SCHEDULING_OPS |
| GET | `/festival/screening-slots/{id}` | Read a slot | FESTIVAL_ADMIN, FESTIVAL_DIRECTOR, PROGRAM_CHAIR, SCHEDULING_OPS, FILMMAKER |
| GET | `/festival/screening-slots` | List slots with filters | FESTIVAL_ADMIN, FESTIVAL_DIRECTOR, PROGRAM_CHAIR, SCHEDULING_OPS, FILMMAKER |
| POST | `/festival/screening-slots/{id}/hold` | Hold an open slot for a confirmed entry | SCHEDULING_OPS |
| POST | `/festival/screening-slots/{id}/confirm` | Confirm a held slot against the license | SCHEDULING_OPS |
| POST | `/festival/screening-slots/{id}/release` | Release a held slot back to open | SCHEDULING_OPS |
| POST | `/festival/screening-slots/{id}/cancel` | Cancel a confirmed slot | SCHEDULING_OPS |
| POST | `/festival/screening-slots/{id}/mark-played` | Mark a confirmed slot as played | SCHEDULING_OPS |
| GET | `/festival/travel-packages/{id}` | Read a travel package | FESTIVAL_ADMIN, TRAVEL_COORDINATOR, FILMMAKER |
| GET | `/festival/travel-packages` | List travel packages with filters | FESTIVAL_ADMIN, TRAVEL_COORDINATOR, FILMMAKER |
| POST | `/festival/travel-packages/{id}/submit` | Submit travel details and compute raw stipend | FILMMAKER |
| POST | `/festival/travel-packages/{id}/approve` | Approve with budget and hotel clamps (OCC) | TRAVEL_COORDINATOR |
| POST | `/festival/travel-packages/{id}/request-changes` | Send a package back for changes | TRAVEL_COORDINATOR |
| POST | `/festival/travel-packages/{id}/mark-booked` | Mark an approved package as booked | TRAVEL_COORDINATOR |
| POST | `/festival/travel-packages/{id}/cancel` | Cancel an approved or booked package | TRAVEL_COORDINATOR, FILMMAKER |
| POST | `/festival/travel-packages/{id}/reconcile` | Reconcile a booked package after go-live | TRAVEL_COORDINATOR |
| GET | `/festival/exhibition-agreements/{id}` | Read an agreement | FESTIVAL_ADMIN, FESTIVAL_DIRECTOR, SCHEDULING_OPS, FILMMAKER |
| GET | `/festival/exhibition-agreements` | List agreements with filters | FESTIVAL_ADMIN, FESTIVAL_DIRECTOR, SCHEDULING_OPS, FILMMAKER |
| POST | `/festival/exhibition-agreements/{id}/issue` | Issue an agreement with license terms | FESTIVAL_DIRECTOR |
| POST | `/festival/exhibition-agreements/{id}/sign` | Sign an agreement, pinning the submission version | FILMMAKER |
| POST | `/festival/exhibition-agreements/{id}/amend` | Amend a signed or active agreement (OCC) | FESTIVAL_DIRECTOR |
| POST | `/festival/exhibition-agreements/{id}/terminate` | Terminate an agreement with no live slots | FESTIVAL_DIRECTOR |
| POST | `/festival/jurors` | Empanel a juror for an edition | AWARDS_ADMIN |
| GET | `/festival/jurors/{id}` | Read a juror | AWARDS_ADMIN, FESTIVAL_ADMIN, FESTIVAL_DIRECTOR, JUROR |
| GET | `/festival/jurors` | List jurors | AWARDS_ADMIN, FESTIVAL_ADMIN, FESTIVAL_DIRECTOR, JUROR |
| GET | `/festival/jurors/{id}/ballots` | List ballots cast by a juror | AWARDS_ADMIN, FESTIVAL_ADMIN, FESTIVAL_DIRECTOR, JUROR |
| POST | `/festival/awards` | Create an award within the prize pool | AWARDS_ADMIN |
| GET | `/festival/awards/{id}` | Read an award | AWARDS_ADMIN, FESTIVAL_ADMIN, FESTIVAL_DIRECTOR, JUROR |
| GET | `/festival/awards` | List awards with filters | AWARDS_ADMIN, FESTIVAL_ADMIN, FESTIVAL_DIRECTOR, JUROR |
| POST | `/festival/awards/{id}/open-voting` | Open jury voting during the festival | AWARDS_ADMIN |
| POST | `/festival/awards/{id}/ballots` | Cast a ranked ballot | JUROR |
| GET | `/festival/awards/{id}/ballots` | List ballots of an award | AWARDS_ADMIN, FESTIVAL_ADMIN, FESTIVAL_DIRECTOR |
| GET | `/festival/awards/{id}/standings` | Provisional first-preference standings | AWARDS_ADMIN, FESTIVAL_ADMIN, FESTIVAL_DIRECTOR, JUROR |
| POST | `/festival/awards/{id}/tally` | Close voting and run the IRV tally | AWARDS_ADMIN |
| POST | `/festival/awards/{id}/announce` | Announce the winner on awards night | FESTIVAL_DIRECTOR |
| POST | `/festival/awards/{id}/disburse` | Disburse the prize | AWARDS_ADMIN |

## 5. Error Code Catalogue

Trigger conditions for each error live with their workflows in §2 and §3; this catalogue is only the identifier-to-status index.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 Forbidden |
| `ERR_JUROR_NOT_ON_PANEL` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_EDITION_PHASE_FORBIDDEN` | 409 Conflict |
| `ERR_SCORES_LOCKED` | 409 Conflict |
| `ERR_ENTRY_NOT_CONFIRMED` | 409 Conflict |
| `ERR_AGREEMENT_NOT_SIGNED` | 409 Conflict |
| `ERR_QUORUM_NOT_MET` | 409 Conflict |
| `ERR_INTAKE_NOT_YET_OPEN` | 409 Conflict |
| `ERR_SLOT_OUTSIDE_FESTIVAL_WINDOW` | 409 Conflict |
| `ERR_PREMIERE_WINDOW_VIOLATION` | 409 Conflict |
| `ERR_REFUND_WINDOW_CLOSED` | 409 Conflict |
| `ERR_FESTIVAL_NOT_STARTED` | 409 Conflict |
| `ERR_COI_RECUSAL_REQUIRED` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 409 Conflict |
| `ERR_JUROR_CONFLICT` | 409 Conflict |
| `ERR_REFERENTIAL_INTEGRITY` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_EMAIL` | 409 Conflict |
| `ERR_DUPLICATE_SUBMISSION` | 409 Conflict |
| `ERR_DUPLICATE_CATEGORY_CONFIG` | 409 Conflict |
| `ERR_DUPLICATE_SLATE` | 409 Conflict |
| `ERR_DUPLICATE_ASSIGNMENT` | 409 Conflict |
| `ERR_SCORE_EXISTS` | 409 Conflict |
| `ERR_BALLOT_EXISTS` | 409 Conflict |
| `ERR_DUPLICATE_ENTRY` | 409 Conflict |
| `ERR_PREMIERE_SLOT_EXISTS` | 409 Conflict |
| `ERR_INELIGIBLE_RUNTIME` | 409 Conflict |
| `ERR_INELIGIBLE_COMPLETION_DATE` | 409 Conflict |
| `ERR_INELIGIBLE_PREMIERE` | 409 Conflict |
| `ERR_SECTION_CATEGORY_MISMATCH` | 409 Conflict |
| `ERR_VENUE_OVERLAP` | 409 Conflict |
| `ERR_SLOT_TOO_SHORT` | 409 Conflict |
| `ERR_SLATE_UNDERFILLED` | 409 Conflict |
| `ERR_BELOW_SLATE_THRESHOLD` | 409 Conflict |
| `ERR_SCORING_INCOMPLETE` | 409 Conflict |
| `ERR_ELIGIBILITY_DECISIONS_PENDING` | 409 Conflict |
| `ERR_BALLOT_INVALID` | 409 Conflict |
| `ERR_LICENSED_COUNT_EXCEEDED` | 409 Conflict |
| `ERR_LICENSED_BELOW_USED` | 409 Conflict |
| `ERR_FORMAT_UNSUPPORTED` | 409 Conflict |
| `ERR_NO_CATEGORY_CONFIG` | 409 Conflict |
| `ERR_SLATES_UNLOCKED` | 409 Conflict |
| `ERR_INVITATIONS_PENDING` | 409 Conflict |
| `ERR_AWARDS_PENDING` | 409 Conflict |
| `ERR_UNRESOLVED_INFO_REQUEST` | 409 Conflict |
| `ERR_ACTIVE_SLOTS_EXIST` | 409 Conflict |
| `ERR_ASSIGNMENT_CAP` | 409 Conflict |
| `ERR_TRAVEL_BUDGET_EXHAUSTED` | 409 Conflict |
| `ERR_HOTEL_NIGHTS_EXHAUSTED` | 409 Conflict |
| `ERR_PRIZE_POOL_EXHAUSTED` | 409 Conflict |
| `ERR_PAYMENT_NOT_REFUNDABLE` | 409 Conflict |
| `ERR_REFUND_NOT_ALLOWED` | 409 Conflict |
