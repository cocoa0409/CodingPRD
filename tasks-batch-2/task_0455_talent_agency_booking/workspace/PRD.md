# Talent Agency Booking API — Product Requirements Document

## 1. Introduction

The Talent Agency Booking API coordinates the full commercial relationship between three parties who rarely share a single source of truth: the agency that represents performers, the production-side casting offices that audition and hire them, and the performers themselves. In a traditional agency, a booking is the end of a long paper trail — a comp card mailed to a casting director, an audition penciled into a room calendar, a callback, a verbal offer, a counter, a handshake, and finally a deal memo that someone files in a drawer. Money then flows in the opposite direction: a producer remits a gross fee, the agency takes its commission out of escrow, the performer receives a net check that depends on whether they are union or not, and — for union work — residual checks trickle in for years as the spot reruns.

This system models that entire arc as an explicit, auditable state machine. It tracks talent rosters and their portfolios, casting calls and submissions, audition and callback scheduling, multi-round deal-memo negotiation, availability and conflict holds, confirmed bookings with usage-rights terms, agency commission held in escrow, union and non-union payment math, and the residual schedules that follow. The dominant design tension is **temporal windowing** — almost every meaningful operation is gated on where a logical clock sits relative to a shoot window, a slot, or a booking — layered over a **multi-party negotiation** in which a casting director and a performer trade offers and counters until one side accepts. Throughout, the agency operator must keep two financial figures reconciled: a forward-looking commission projected when a booking is confirmed, and a final commission settled chronologically when real money arrives.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the capacity in which they act. The system recognizes exactly three roles, spelled precisely: `Agent`, `CastingDirector`, and `Talent`. A request that omits either header, or carries a malformed value, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is well-formed but not permitted for the requested operation (per the authorization column of the endpoint table in §4) is rejected with `ERR_FORBIDDEN_ROLE`.

The three roles map to identity differently, and this mapping governs every ownership check. When `X-User-Role` is `CastingDirector`, `X-User-ID` is the `id` of the acting `CastingDirector` entity; any resource that references a casting director through a `casting_director_id` foreign key is owned by the director whose `id` equals that value. When `X-User-Role` is `Talent`, `X-User-ID` is the `id` of the acting `Talent` entity; ownership checks on any resource carrying a `talent_id` compare that field to `X-User-ID`. When `X-User-Role` is `Agent`, `X-User-ID` is an opaque agency-operator identifier that is not tied to any persisted entity; the agent acts on behalf of the agency and the server does not compare the agent's `X-User-ID` to any entity `id`. The `Agent` is the agency operator who runs the roster, escrow, commissions, bookings, payments, and residuals; the `CastingDirector` owns casting calls, audition and callback scheduling, and deal-memo offers; the `Talent` manages comp cards, submissions, counters, accepts, and withdrawals on their own behalf.

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items skipped before collection begins and defaults to 0. Unless an endpoint specifies otherwise, list responses are sorted by the resource's `created_at` timestamp in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the envelope's `meta` object.

### 2.4. Common Resource Properties and the Logical Clock

Every primary resource carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp recorded as an ISO 8601 UTC value with three fractional digits. Most resources additionally carry an `updated_at` timestamp (ISO 8601 UTC, three fractional digits, refreshed on every mutation) and a `version` integer that begins at its initial value and increments by one on each mutation. Across this domain every entity — `Agency`, `CastingDirector`, `Talent`, `CompCard`, `CastingCall`, `Submission`, `AuditionSlot`, `AvailabilityHold`, `DealMemo`, `Booking`, `CommissionEntry`, `Payment`, and `ResidualSchedule` — carries the full set of `id`, `created_at`, `updated_at`, and `version`.

Time in this system is never wall-clock time. A single logical clock drives every deadline, expiry, and window comparison. At server startup the clock reads exactly `2026-01-01T00:00:00Z`, and until it is explicitly moved it stays at that default and never falls back to real time. Any of the three roles may advance or rewind the clock by supplying a target instant in the `to_iso8601` field; the capability echoes the resulting `now` instant. Because all temporal preconditions (slot completion, booking completion, hold windows) read this clock, tests drive it deterministically.

### 2.5. Hierarchical Consistency, Cascades, and Reconciliation

Many operations in this system mutate more than one entity. Whenever a transition lists secondary effects, the server applies all of them as part of the same operation, and each entity that is touched has its `updated_at` refreshed and its `version` incremented. Cascades can run several links deep: closing a casting call withdraws its open submissions, and those withdrawals in turn release the submissions' scheduled audition slots — a two-link chain originating from one close. Cancelling a confirmed booking originates a four-link cascade that releases the availability hold, voids the deal memo, reverses the commission entry, and reconciles the agency's and talent's booked-day counters downward. These chains are detailed in §3 alongside the workflows they belong to.

Several fields are **derived** and must be kept reconciled rather than set by clients. An agency's `escrow_balance_cents` always equals the sum of `held_cents` across that agency's commission entries whose status is `HELD`, and it is recomputed on every commission-entry mutation. The `booked_day_count` on both `Agency` and `Talent` is the sum, over every booking for that party whose `booking_status` is either `CONFIRMED` or `COMPLETED`, of the booking's inclusive day span — that is, the number of days from the start date through the end date counting both endpoints. These counters are reconciled upward on confirm and downward on cancel, and they are conserved quantities: a cancel must subtract exactly what the matching confirm added.

### 2.6. Left-to-Right Resource Resolution

When an operation references resources — whether through a path identifier or a foreign key in the request body — the server validates their existence left to right, in the order they appear, and rejects the request with `ERR_NOT_FOUND` at the first identifier that does not resolve to an existing resource. For a creation that supplies several foreign keys, the keys are checked in declaration order before any business rule runs, so a missing parent surfaces before any state or temporal check.

### 2.7. Monetary Precision and Rounding

All monetary amounts are stored and returned as integer cents; there are no fractional cents and no floating-point representation in responses. Day-span aggregations that multiply a day rate by a whole number of days are exact and require no rounding. Where a calculation divides by the basis-point denominator of 10,000 — commission, pension and health, and residual math all do — the result is rounded to whole cents using the round-half-up method: a fractional cent of exactly one half rounds up. The §3 calculation narratives state, for each formula, exactly when in the sequence rounding is applied, because for multi-step money math the rounding order is part of the contract.

### 2.8. Optimistic Concurrency on Booking Creation

Creating a booking is the one write in this system guarded by optimistic concurrency control, because a booking reserves a talent's calendar window and the talent record may have moved underneath the client. A create-booking request must carry `expected_talent_version`, which is not optional, holding the `version` of the target `Talent` that the client last observed. If that value does not equal the talent's current `version` at the moment the request is processed, the create is rejected with `ERR_STALE_TALENT_VERSION` and HTTP status 412. This matters because confirming any other booking for the same talent bumps `Talent.version` through the booked-day reconciliation side effect; a client that read the talent before such a confirmation is holding a stale view, and the OCC check refuses to let it write a booking against data it has not seen. No other endpoint in this system accepts or requires a version field.

### 2.9. Validation Ordering

When several checks apply to one request, they are evaluated in a fixed priority order so that the returned error is deterministic. Authentication comes first: a request missing or malformed in its `X-User-ID` or `X-User-Role` headers fails with `ERR_UNAUTHENTICATED` (401) before anything else. Authorization is second — a role not permitted for the operation fails with `ERR_FORBIDDEN_ROLE` (403). Third, the existence of every path and foreign-key-referenced resource is confirmed left to right, failing with `ERR_NOT_FOUND` (404). Fourth, on every mutating endpoint, request-body shape is validated — required fields present and correctly typed, enum values within their declared sets — failing with `ERR_INVALID_REQUEST` (422). Fifth, on booking creation only, the optimistic-concurrency check on `expected_talent_version` runs, failing with `ERR_STALE_TALENT_VERSION` (412). Sixth, the target resource's own state is checked for transition legality, failing with `ERR_INVALID_STATE` (409). Seventh, cross-entity gates that require a referenced sibling to be in a particular state are evaluated, failing with `ERR_CROSS_ENTITY_GATE` (409) or a more specific cross-entity code where the workflow names one. The remaining business rules — temporal, constraint, fiscal — follow, each described with its workflow in §3. A request that violates several rules surfaces the highest-priority (lowest-numbered) failure.

## 3. Business Logic & Workflows

### 3.1. Building the Roster: Agencies, Talent, and Comp Cards

The commercial backbone is the **agency**. An `Agent` opens one by supplying its legal `name` and a `commission_rate_bps`, the agency's commission expressed in basis points where 1000 means ten percent; this rate must be an integer from 0 through 5000 inclusive. A new agency starts with `escrow_balance_cents` and `booked_day_count` both at zero — these are the derived fields reconciled later as bookings and commissions move. Reading an agency returns these computed figures alongside the input fields. Separately, a casting director registers themselves (or is registered by an agent) with a `display_name` and a `studio`; the resulting `CastingDirector` `id` becomes the `X-User-ID` a casting director presents.

Performers enter as **talent**. An agent creates a talent by naming the representing agency through `agency_id`, the performer's `full_name`, their `union_status` — exactly one of `SAG` or `NON_UNION`, which later selects the entire payment and residual variant — and a `scale_rate_cents` floor (at least zero) used in rate math. A freshly created talent begins life in `status` `PROSPECT` with `booked_day_count` at zero. Talent can be listed and filtered by `agency_id` or by `status`.

Before a talent can be activated, they need a portfolio. A **comp card** is created against a talent through `talent_id`, carrying a `headshot_url`, a `height_cm` in whole centimeters (at least 1), and a `skills` array of free-text tags. The first comp card created for a given talent is automatically marked with `is_primary` set to true; every later card for that talent has `is_primary` false. Comp cards are listable and filterable by `talent_id`.

The talent lifecycle is a small state machine an agent drives. Moving a talent from `PROSPECT` to `ROSTERED` requires that the talent have at least one comp card on file; with none, the activation is refused with `ERR_NO_COMP_CARD`. A rostered talent may be suspended, moving `ROSTERED → SUSPENDED`, and a suspended talent may be reinstated back to `ROSTERED` (the same activation action serves both `PROSPECT → ROSTERED` and `SUSPENDED → ROSTERED`). From either `ROSTERED` or `SUSPENDED`, an agent may archive the talent, moving them to the terminal `ARCHIVED` state — but only if the talent has no booking in `booking_status` `PENDING` or `CONFIRMED`; an open booking blocks the archive with `ERR_TALENT_HAS_OPEN_BOOKINGS`. Archiving carries a side effect: every availability hold for that talent still in `ACTIVE` status is released to `RELEASED`.

### 3.2. Casting Calls and Submissions

A `CastingDirector` opens a **casting call** to advertise a role. Creation requires `casting_director_id` (the owner), a `title`, a `media_type` drawn from `BROADCAST_TV`, `CABLE`, `STREAMING`, `PRINT`, or `DIGITAL` (this key later selects the residual media multiplier), a `usage_term_months` of at least one month describing how long the production may use the performance, a `shoot_start_date` and a `shoot_end_date` (the latter must be on or after the former, else `ERR_INVALID_DATE_RANGE`), and an `offered_day_rate_cents` of at least zero. A new call opens in `status` `OPEN`. Casting calls are filterable by `casting_director_id` and `status`.

A director may close an `OPEN` call, moving it to `CLOSED`. Closing originates a cascade: every submission for that call still in `SUBMITTED`, `AUDITION_SCHEDULED`, or `CALLBACK_SCHEDULED` is withdrawn to `WITHDRAWN` (the first cascade link), and each such withdrawn submission then has its audition slots that are still `SCHEDULED` released to `RELEASED` (the second link, caused by the first). A `CLOSED` call may be reopened to `OPEN`, but reopening does not resurrect the submissions withdrawn during the close — they stay `WITHDRAWN`. Independently, a call moves from `OPEN` to the terminal `FILLED` state automatically when a booking that references it via `casting_call_id` reaches `CONFIRMED`.

A **submission** pairs a talent with a casting call. It is created — by an agent or by the talent — with the `casting_call_id` it targets, the `talent_id` being submitted, and the `comp_card_id` attached to represent the performer. A new submission begins in `SUBMITTED`. Submissions are listable and filterable by `casting_call_id`, `talent_id`, `comp_card_id`, and `status`. A casting director may decline a submission, and the talent who owns it may withdraw it. Declining moves a submission to the terminal `DECLINED` state, and withdrawing moves it to `WITHDRAWN`; both actions, when the submission was past the initial state, release that submission's `SCHEDULED` audition slots to `RELEASED`. A submission in `SUBMITTED` can be declined or withdrawn with no slots to release; a submission in `AUDITION_SCHEDULED` or `CALLBACK_SCHEDULED` carries the slot-release side effect.

### 3.3. Auditions, Callbacks, and the Casting Director's Calendar

Scheduling drives the submission forward. When a director schedules an **audition slot** for a submission, the slot advances the submission's status as a side effect. A slot is created with the `submission_id` it serves, the `casting_director_id` whose room calendar holds it, a `slot_kind` of either `AUDITION` or `CALLBACK`, a `start_at`, and an `end_at` that must be strictly after `start_at` (otherwise `ERR_INVALID_DATE_RANGE`). A new slot is `SCHEDULED`.

Creating an `AUDITION`-kind slot advances its submission `SUBMITTED → AUDITION_SCHEDULED`, but only while the submission's casting call is still `OPEN`; if the call is not open, the scheduling is refused with `ERR_CASTING_CALL_NOT_OPEN`. Creating a `CALLBACK`-kind slot advances the submission `AUDITION_SCHEDULED → CALLBACK_SCHEDULED`, but this is permitted only when an `AUDITION`-kind slot for that same submission has already reached `COMPLETED`; without a completed audition, the callback is refused with `ERR_AUDITION_NOT_COMPLETED`. Both scheduling paths also share the cross-entity gate that surfaces as a general cross-entity-gate rejection when the referenced sibling is in the wrong state.

A director's calendar must not double-book. A new audition slot may not overlap another `SCHEDULED` slot belonging to the same `casting_director_id`, where overlap is measured as a closed interval extended by a buffer gap of `SLOT_BUFFER_MINUTES` minutes — fifteen minutes of turnaround between adjacent slots on one director's calendar. A slot that violates this buffered-overlap rule is rejected with `ERR_SLOT_OVERLAP`. Audition slots are listable and filterable by `submission_id` and `casting_director_id`.

A `SCHEDULED` slot can be completed only once the logical clock has reached or passed its `end_at`; an attempt before the slot has ended is refused with `ERR_SLOT_NOT_ENDED`. Completion moves the slot to `COMPLETED`. A `SCHEDULED` slot may instead be released to the terminal `RELEASED` state, either explicitly by the director or automatically through the cascades described above (submission withdrawal or decline, or casting-call close).

### 3.4. Availability and Conflict Holds

An agent protects a talent's calendar with an **availability hold**. A hold is placed with the `talent_id` whose calendar it blocks, a `start_date` and an `end_date` (inclusive days; the end must be on or after the start, else `ERR_INVALID_DATE_RANGE`), and a `hold_kind` of either `FIRST_REFUSAL` or `CONFIRMED_BOOKING`. A new hold is `ACTIVE`. Holds are filterable by `talent_id` and `status`.

Two holds of the **same** kind on the **same** talent may not overlap. Overlap here is measured on the half-open interval running from the start date up to but not including the day after the end date, which means two same-kind holds that sit exactly back-to-back — one ending the day before the next begins — are allowed. A same-kind overlap is rejected with `ERR_HOLD_OVERLAP`. Holds of different kinds, however, interact rather than collide: when a `CONFIRMED_BOOKING` hold is created and it overlaps an existing `ACTIVE` `FIRST_REFUSAL` hold on the same talent, that first-refusal hold is bumped from `ACTIVE` to `CONFLICTED` as a side effect — a confirmed booking beats a speculative first refusal. An `ACTIVE` hold may be released to `RELEASED` by an agent, or automatically when the talent is archived or a booking is cancelled.

Two availability figures can be read back for a talent through a computed availability summary. The first, the forward-looking **projected blocked days** (`projected_blocked_days`), counts every `ACTIVE` hold regardless of kind — both first-refusal and confirmed — treating each speculative first-refusal hold as though it will convert. It is the sum, over every `ACTIVE` hold for the talent, of that hold's inclusive day span (end date minus start date, plus one). The second, the chronological **committed days** (`committed_days`), counts only days actually committed: it considers only `ACTIVE` holds whose `hold_kind` is `CONFIRMED_BOOKING`, processes them in ascending `created_at` order, merges overlapping confirmed windows so that any calendar day is counted exactly once, and reports the resulting merged inclusive day count. The projected figure includes first-refusal holds; the committed figure excludes them and de-duplicates overlapping confirmed days.

### 3.5. Deal-Memo Negotiation

Once a submission has reached the point of an offer, a **deal memo** carries the back-and-forth. A director opens one with the `casting_call_id`, the `talent_id`, and the `submission_id` it advances from; the memo starts in `DRAFT` with `round_count` at zero, and opening it advances the originating submission to `OFFER_EXTENDED` (a submission in `AUDITION_SCHEDULED` or `CALLBACK_SCHEDULED` is moved to `OFFER_EXTENDED` by this action). Deal memos are filterable by `casting_call_id`, `talent_id`, `submission_id`, and `status`. The memo tracks `current_day_rate_cents` and `usage_term_months` as the latest terms on the table, both system-maintained.

The director extends the first offer, moving the memo `DRAFT → OFFERED`. This first offer is permitted only when the memo's submission is in `OFFER_EXTENDED`; otherwise it is refused with `ERR_SUBMISSION_NOT_OFFERABLE`. An offer supplies `offer_day_rate_cents` and `offer_usage_term_months`, which become the memo's `current_day_rate_cents` and `usage_term_months`, and it increments `round_count` by one. From `OFFERED`, the talent may counter, moving `OFFERED → COUNTERED`; a counter supplies `counter_day_rate_cents` and `counter_usage_term_months`, which overwrite the standing terms, and likewise increments `round_count` by one. From `COUNTERED`, the director may re-offer, moving `COUNTERED → OFFERED` again with a fresh `offer_day_rate_cents` and `offer_usage_term_months` and another `round_count` increment — this is the negotiation loop, and it can cycle.

The loop is bounded. Both a re-offer out of `COUNTERED` and a counter out of `OFFERED` are permitted only while `round_count` is strictly less than `MAX_ROUNDS`, a ceiling of eight exchanges; an attempt to push past that ceiling is refused with `ERR_MAX_NEGOTIATION_ROUNDS`. Either side can end the negotiation by accepting or rejecting the standing terms: from `OFFERED`, the talent may accept (to `ACCEPTED`) or reject (to the terminal `REJECTED`); from `COUNTERED`, the director may accept or reject. Whichever party faces the standing terms is the one entitled to accept or reject them. A deal that has reached `ACCEPTED` is later voided to the terminal `VOIDED` state automatically if the booking realizing it is cancelled.

### 3.6. Confirming and Completing Bookings

A **booking** realizes an accepted deal. An agent creates one with the `deal_memo_id` of the accepted deal, the `talent_id` and `casting_call_id` it concerns, the `availability_hold_id` of the `CONFIRMED_BOOKING` hold reserving the calendar, a `start_date` and `end_date` for the work (inclusive; end on or after start, else `ERR_INVALID_DATE_RANGE`), and the `expected_talent_version` required by the optimistic-concurrency rule in §2.8. A new booking is created in `booking_status` `PENDING` and `payment_status` `UNPAID` — two independent dimensions that evolve separately. Bookings are filterable by `talent_id`, `casting_call_id`, `deal_memo_id`, `availability_hold_id`, and `booking_status`.

Confirming a pending booking is the system's busiest operation. It is permitted only when three cross-entity gates all hold: the booking's deal memo is in `ACCEPTED` (otherwise `ERR_DEAL_NOT_ACCEPTED`), the referenced availability hold is of kind `CONFIRMED_BOOKING` and in `ACTIVE` status (otherwise `ERR_HOLD_NOT_ACTIVE`), and the talent is `ROSTERED` (otherwise `ERR_TALENT_NOT_ROSTERED`). When those gates pass, the booking moves `PENDING → CONFIRMED` and a chain of side effects fires together: `agreed_day_rate_cents` and `usage_term_months` are copied from the deal memo's `current_day_rate_cents` and `usage_term_months`; `gross_fee_cents` is computed; `provisional_commission_cents` is computed; a commission entry is created in `HELD` status with its `held_cents` set to the provisional commission; the agency's `escrow_balance_cents` is reconciled upward by that held amount; both the talent's and the agency's `booked_day_count` are reconciled upward by the booking's inclusive day span; and the casting call referenced by the booking auto-transitions `OPEN → FILLED`. The confirm also bumps `Talent.version` (this is the version movement that the create-booking OCC check in §2.8 guards against).

The gross fee is a straightforward aggregation computed at confirmation: the inclusive day span of the booking — the end date minus the start date, plus one, counted in whole days — multiplied by `agreed_day_rate_cents`, kept as exact integer cents with no rounding. The provisional commission is the forward-looking variant, projected from that quoted gross fee before any money has moved: it is `gross_fee_cents` multiplied by the owning agency's `commission_rate_bps`, divided by the basis-point denominator of 10,000, with the result rounded half-up to whole cents. It is stored on the booking as `provisional_commission_cents`.

A confirmed booking is completed by an agent, moving `CONFIRMED → COMPLETED`, but only once the logical clock has reached or passed the booking's `end_date`; an early completion is refused with `ERR_BOOKING_NOT_ENDED`. The `final_commission_cents` field stays null until the booking is `COMPLETED` and then settled at payment.

### 3.7. Cancellation and the Commission Reversal Cascade

A booking can be cancelled by an agent. A `PENDING` booking cancels freely to the terminal `CANCELLED` state. A `CONFIRMED` booking can also be cancelled, but only while its `payment_status` is still `UNPAID`; once payment has been posted, the cancel is refused with `ERR_BOOKING_ALREADY_PAID`. Cancelling a confirmed booking originates a four-link cascade. The first link sets `booking_status` to `CANCELLED`. Caused by that, the second link releases the booking's availability hold from `ACTIVE` to `RELEASED`; the third link voids the booking's deal memo from `ACCEPTED` to `VOIDED`; and the fourth link reverses the booking's commission entry from `HELD` to `REVERSED`, setting that entry's `held_cents` to zero and reconciling the agency's `escrow_balance_cents` downward by the previously held amount. Alongside the cascade, the talent's and the agency's `booked_day_count` are reconciled downward by the same inclusive day span the confirmation had added, conserving those counters exactly.

Commission entries are read-only ledger records an agent can list (filterable by `agency_id` and `booking_id`) and read individually. Each entry carries the `agency_id` that earns it, the `booking_id` that generated it, an `held_cents` amount that is non-zero only while the entry is `HELD`, and an `earned_cents` amount that is non-zero only once the entry is `RELEASED`. An entry begins `HELD` when its booking is confirmed, becomes `RELEASED` when payment settles, or becomes `REVERSED` when the booking is cancelled.

### 3.8. Payment, Net-to-Talent, and Escrow Settlement

Payment is where real money arrives and the final commission is settled. An agent posts a **payment** with the `booking_id` being paid, the `talent_id` of the payee, and the `gross_amount_cents` the producer actually remitted (at least zero). A payment is permitted only when the booking is in `COMPLETED`; against a booking that has not completed, the post is refused with `ERR_BOOKING_NOT_COMPLETED`. The payment's `talent_id` must equal the booking's `talent_id`; a mismatch is refused with `ERR_TALENT_MISMATCH`. The agency's escrow must also be sufficient to release the booking's held commission entry — the agency's `escrow_balance_cents` must be at least the `held_cents` being released, with equality allowed — otherwise the post is refused with `ERR_ESCROW_INSUFFICIENT`. A payment is append-only: once created it is `POSTED` and never changes. Payments are filterable by `booking_id` and `talent_id`.

Posting a payment records `union_status_snapshot` by copying the talent's `union_status` at payment time, which selects the SAG-versus-non-union net math, and it drives the booking's `payment_status` from `UNPAID` to `PAID`. As side effects it computes the booking's `final_commission_cents`, transitions the booking's commission entry from `HELD` to `RELEASED` (setting that entry's `earned_cents` to the final commission and its `held_cents` to zero), and reconciles the agency's `escrow_balance_cents` downward by the previously held amount.

The final commission is the chronological variant, settled on the actual remitted gross rather than the projected one: it is `gross_amount_cents` multiplied by the agency's `commission_rate_bps`, divided by 10,000, rounded half-up to whole cents, and recorded on the booking as `final_commission_cents`. It differs from the provisional commission whenever the actual remitted gross differs from the quoted gross fee; the difference between the final commission and the booking's earlier `provisional_commission_cents` is the commission delta that the settlement absorbs.

The take-home figure follows a pinned, multi-step rounding order — the components are rounded separately before being subtracted, never summed-then-rounded. First, the `commission_withheld_cents` is computed as `gross_amount_cents` times the agency's `commission_rate_bps` divided by 10,000, rounded half-up to whole cents. Second, a pension-and-health contribution is computed but only for a `SAG` talent: it is `gross_amount_cents` times the SAG pension-and-health rate of `SAG_PH_BPS`, which is 1850 basis points (eighteen and one-half percent), divided by 10,000, rounded half-up to whole cents; for a `NON_UNION` talent this contribution is zero. Third, the `net_to_talent_cents` is the `gross_amount_cents` minus the already-rounded commission and minus the already-rounded pension-and-health contribution. Both rounded components are subtracted from gross in that order; the two figures are never added together and rounded as a single sum.

### 3.9. Residual Schedules

For union work, residuals follow the initial payment. An agent accrues a **residual schedule** for a run period by supplying the `payment_id` the residual derives from, the originating `booking_id`, and a one-based `period_index` (at least 1) marking which rerun period this is. A new schedule is `DUE` with its `residual_amount_cents` computed at creation. Residual schedules are filterable by `payment_id` and `booking_id`.

The residual amount depends on union status, media type, and how late the run period is. For a `NON_UNION` talent the residual amount is zero — non-union work pays no residuals. For a `SAG` talent the amount starts from the originating booking's `gross_fee_cents` as the base, scales it by the media multiplier keyed to the casting call's `media_type`, and then scales it again by a period-tier multiplier that decays as reruns accumulate. The media multipliers, in basis points, are: `BROADCAST_TV` at 3000, `CABLE` at 2000, `STREAMING` at 1500, `PRINT` at 1000, and `DIGITAL` at 1200. The period-tier multiplier, in basis points, is 10000 (full) when `period_index` is 1, 7500 when it is 2, 5000 when it is 3, and a flat 2500 for any period of 4 or higher. The residual amount is the base multiplied by the media multiplier divided by 10,000, then multiplied by the period multiplier divided by 10,000, with rounding to whole cents applied half-up only once, at the final step — the intermediate base-times-media product is not rounded before the period multiplier is applied.

A `DUE` residual can be paid, moving it to the terminal `PAID` state, but only when its `residual_amount_cents` is greater than zero; a residual with nothing due is refused with `ERR_NO_RESIDUAL_DUE`. A `DUE` residual can instead be voided to the terminal `VOID` state at any time. Each residual carries its own `status`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including every state-transition action and the logical-clock capability — return a `200 OK` status code. All list and read endpoints return `200 OK`. Request and response bodies are not repeated here; reconstruct them from the workflow narratives in §3 and the field semantics in §2.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock to a UTC instant | Agent, CastingDirector, Talent |
| POST | `/agencies` | Create an agency | Agent |
| GET | `/agencies/{id}` | Read an agency | Agent, CastingDirector, Talent |
| POST | `/casting-directors` | Register a casting director | Agent, CastingDirector |
| GET | `/casting-directors/{id}` | Read a casting director | Agent, CastingDirector, Talent |
| POST | `/talents` | Create a talent (PROSPECT) | Agent |
| GET | `/talents` | List talents | Agent, CastingDirector, Talent |
| GET | `/talents/{id}` | Read a talent | Agent, CastingDirector, Talent |
| GET | `/talents/{id}/availability-summary` | Read projected and committed availability days | Agent, CastingDirector, Talent |
| POST | `/talents/{id}/roster` | Roster a talent (PROSPECT/SUSPENDED → ROSTERED) | Agent |
| POST | `/talents/{id}/suspend` | Suspend a talent (ROSTERED → SUSPENDED) | Agent |
| POST | `/talents/{id}/archive` | Archive a talent (ROSTERED/SUSPENDED → ARCHIVED) | Agent |
| POST | `/comp-cards` | Create a comp card | Agent, Talent |
| GET | `/comp-cards` | List comp cards | Agent, CastingDirector, Talent |
| GET | `/comp-cards/{id}` | Read a comp card | Agent, CastingDirector, Talent |
| POST | `/casting-calls` | Create a casting call (OPEN) | CastingDirector |
| GET | `/casting-calls` | List casting calls | Agent, CastingDirector, Talent |
| GET | `/casting-calls/{id}` | Read a casting call | Agent, CastingDirector, Talent |
| POST | `/casting-calls/{id}/close` | Close a casting call (cascades) | CastingDirector |
| POST | `/casting-calls/{id}/reopen` | Reopen a closed casting call | CastingDirector |
| POST | `/submissions` | Submit a talent to a casting call | Agent, Talent |
| GET | `/submissions` | List submissions | Agent, CastingDirector, Talent |
| GET | `/submissions/{id}` | Read a submission | Agent, CastingDirector, Talent |
| POST | `/submissions/{id}/decline` | Decline a submission | CastingDirector |
| POST | `/submissions/{id}/withdraw` | Withdraw a submission | Talent |
| POST | `/audition-slots` | Schedule an audition/callback slot | CastingDirector |
| GET | `/audition-slots` | List audition slots | Agent, CastingDirector, Talent |
| GET | `/audition-slots/{id}` | Read an audition slot | Agent, CastingDirector, Talent |
| POST | `/audition-slots/{id}/complete` | Complete a slot | CastingDirector |
| POST | `/audition-slots/{id}/release` | Release a slot | CastingDirector |
| POST | `/availability-holds` | Place an availability hold | Agent |
| GET | `/availability-holds` | List availability holds | Agent, CastingDirector, Talent |
| GET | `/availability-holds/{id}` | Read an availability hold | Agent, CastingDirector, Talent |
| POST | `/availability-holds/{id}/release` | Release an availability hold | Agent |
| POST | `/deal-memos` | Open a deal memo | CastingDirector |
| GET | `/deal-memos` | List deal memos | Agent, CastingDirector, Talent |
| GET | `/deal-memos/{id}` | Read a deal memo | Agent, CastingDirector, Talent |
| POST | `/deal-memos/{id}/offer` | Extend or re-extend an offer | CastingDirector |
| POST | `/deal-memos/{id}/counter` | Counter an offer | Talent |
| POST | `/deal-memos/{id}/accept` | Accept the standing terms | Talent, CastingDirector |
| POST | `/deal-memos/{id}/reject` | Reject the standing terms | Talent, CastingDirector |
| POST | `/bookings` | Create a booking (OCC-guarded) | Agent |
| GET | `/bookings` | List bookings | Agent, CastingDirector, Talent |
| GET | `/bookings/{id}` | Read a booking | Agent, CastingDirector, Talent |
| POST | `/bookings/{id}/confirm` | Confirm a booking | Agent |
| POST | `/bookings/{id}/complete` | Complete a booking | Agent |
| POST | `/bookings/{id}/cancel` | Cancel a booking (cascades) | Agent |
| GET | `/commission-entries` | List commission entries | Agent |
| GET | `/commission-entries/{id}` | Read a commission entry | Agent |
| POST | `/payments` | Post a payment | Agent |
| GET | `/payments` | List payments | Agent, Talent |
| GET | `/payments/{id}` | Read a payment | Agent, Talent |
| POST | `/residual-schedules` | Accrue a residual schedule | Agent |
| GET | `/residual-schedules` | List residual schedules | Agent, Talent |
| GET | `/residual-schedules/{id}` | Read a residual schedule | Agent, Talent |
| POST | `/residual-schedules/{id}/pay` | Pay a due residual | Agent |
| POST | `/residual-schedules/{id}/void` | Void a due residual | Agent |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_DATE_RANGE` | 422 |
| `ERR_STALE_TALENT_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CROSS_ENTITY_GATE` | 409 |
| `ERR_DEAL_NOT_ACCEPTED` | 409 |
| `ERR_SUBMISSION_NOT_OFFERABLE` | 409 |
| `ERR_AUDITION_NOT_COMPLETED` | 409 |
| `ERR_BOOKING_NOT_COMPLETED` | 409 |
| `ERR_CASTING_CALL_NOT_OPEN` | 409 |
| `ERR_TALENT_NOT_ROSTERED` | 409 |
| `ERR_HOLD_NOT_ACTIVE` | 409 |
| `ERR_TALENT_MISMATCH` | 409 |
| `ERR_SLOT_NOT_ENDED` | 409 |
| `ERR_BOOKING_NOT_ENDED` | 409 |
| `ERR_BOOKING_ALREADY_PAID` | 409 |
| `ERR_TALENT_HAS_OPEN_BOOKINGS` | 409 |
| `ERR_NO_COMP_CARD` | 409 |
| `ERR_SLOT_OVERLAP` | 409 |
| `ERR_HOLD_OVERLAP` | 409 |
| `ERR_MAX_NEGOTIATION_ROUNDS` | 409 |
| `ERR_ESCROW_INSUFFICIENT` | 409 |
| `ERR_NO_RESIDUAL_DUE` | 409 |
