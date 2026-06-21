# Babysitter & Nanny Marketplace API — Product Requirements Document

## 1. Introduction

This document specifies the Babysitter & Nanny Marketplace API, a Care.com-style platform that connects households needing childcare with vetted babysitters and nannies. The platform's central challenge is multi-party negotiation: a family extends a booking offer to a caregiver, the caregiver may counter, and the two parties exchange counter-offers until one side accepts. Layered on top of this negotiation is rigorous temporal scheduling — caregivers work one-time and recurring sessions that must never overlap once a mandatory travel buffer is taken into account, and a family must not double-book itself with two confirmed engagements that collide in time.

Beyond matchmaking, the system behaves as a regulated employment and payments platform. Every household that hires a caregiver is a household employer, and once cumulative wages to a single caregiver cross the federal household-employment threshold within a tax year, the family incurs a W-2 obligation. Money flows through two conserved ledgers: a per-family escrow wallet that reserves funds against confirmed bookings, and a household-employer tax ledger that accumulates wages paid and FICA withheld. Both ledgers must remain internally consistent across forward actions (confirmation, clock-out, payout) and their compensating reversals (cancellation, payout reversal). The platform also governs caregiver trustworthiness through tiered background checks, mediates interviews and paid trials before a booking can proceed, dispatches last-minute backup care, and curates a moderated rating and review system.

The requirements below define the global contracts every endpoint honors (Section 2), the business workflows that span the negotiation, scheduling, payment, and compliance lifecycles (Section 3), the full endpoint surface (Section 4), and the catalogue of machine-readable error codes (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. All resources are mounted under the `/marketplace` namespace.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. The `X-User-ID` header identifies the acting principal, and the `X-User-Role` header declares the operational capacity under which the request is made. The system recognizes exactly three roles, spelled precisely as `PlatformAdmin`, `Family`, and `Caregiver`. A request that omits either header, or supplies a malformed value, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is syntactically valid but is not permitted to perform the targeted operation — or whose identity does not own the resource it targets — is rejected with `ERR_FORBIDDEN`.

When `X-User-Role` is `Family`, the `X-User-ID` is the `id` of the acting `Family`; ownership checks on any resource that references a `Family` compare that resource's `family_id` foreign key to `X-User-ID`. A family may act only on its own job postings, bookings, interviews, backup requests, reviews, sessions, and wallet. When `X-User-Role` is `Caregiver`, the `X-User-ID` is the `id` of the acting `Caregiver`; ownership checks on any resource that references a `Caregiver` compare that resource's `caregiver_id` foreign key to `X-User-ID`. A caregiver may act only on its own profile, availability, background checks, offered bookings, sessions, and payouts. When `X-User-Role` is `PlatformAdmin`, the `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`, and a `PlatformAdmin` may act on any resource as an override, in addition to performing the platform-exclusive operations (background-check adjudication, backup-care matching, payout settlement, review moderation, W-2 issuance, and advancing the test clock).

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and accepted values range from a minimum of 1 to a maximum of 100. The `offset` parameter specifies how many items to skip from the start of the result set and defaults to 0.

Unless a specific workflow states otherwise, list endpoints return resources sorted by their `created_at` timestamp in ascending order (ties broken by `id` ascending). Every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope. List endpoints additionally accept optional equality-filter query parameters that each match a scalar field of the listed resource (for example `status`, `family_id`, `caregiver_id`, `job_posting_id`, `booking_id`, `care_type`, `availability_status`, `background_check_tier`, `matched_caregiver_id`, or `tax_year`, as applicable); supplying one narrows the result set to records whose field equals the supplied value, and an unrecognized query parameter is ignored. When the caller is a `Family` or `Caregiver`, the list is first scoped to the records that principal owns before any supplied filter is applied. `total_count` and `has_more` reflect the filtered, scoped set, and pagination is applied after sorting.

### 2.4. Common Resource Properties and Identifiers

Nearly every resource in the system carries a system-managed core. The `id` is a server-minted UUID with no type prefix, used for identity only. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created. The `updated_at` field is an ISO 8601 UTC timestamp recording the last time the resource was modified; it is refreshed on every mutation. The `version` field is an integer that begins at its initial value and increments by one with each modification to the resource, and it underpins the optimistic concurrency protocol described in Section 2.8.

One entity is deliberately leaner. A `TaxStatement` is an immutable, frozen snapshot: it carries only an `id` and a `created_at` timestamp, and it has neither an `updated_at` field nor a `version` field, because it is never mutated after issuance. Every other entity — `Family`, `Caregiver`, `BackgroundCheck`, `JobPosting`, `Interview`, `Booking`, `BookingSession`, `BackupCareRequest`, `Payout`, and `Review` — carries the full `id`, `created_at`, `updated_at`, and `version` quartet.

### 2.5. Tier Ordering and Verification Vocabulary

Background-check tiers form a strict total order. From lowest to highest, the order is `NONE`, then `BASIC`, then `STANDARD`, then `PREMIUM`. Whenever the system compares "at least" a tier — for example checking whether a caregiver's `background_check_tier` reaches a family's `required_tier` — it compares positions in this order, where `PREMIUM` outranks `STANDARD`, `STANDARD` outranks `BASIC`, and `BASIC` outranks `NONE`. A caregiver's `verification_status` is a separate enumeration that mirrors the latest background-check outcome and takes one of the values `NONE`, `PENDING`, `CLEAR`, `CONSIDER`, or `FLAGGED`. A caregiver's `availability_status` is one of `AVAILABLE` (open to new sessions and backup matches), `BUSY` (currently at session capacity), `OFFLINE` (manually paused), or `SUSPENDED` (paused by the platform). A `Family` carries a `status` of either `ACTIVE` or `SUSPENDED`.

### 2.6. Escrow Wallet and Ledger Conservation

Each `Family` operates a prepaid wallet. The `wallet_balance_cents` records the total funds the family has deposited. At all times, `escrow_reserved_cents` (funds held against confirmed bookings' estimated pay) plus `escrow_available_cents` (funds free to commit) equals `wallet_balance_cents` exactly. Neither `escrow_reserved_cents` nor `escrow_available_cents` may ever go negative. When a family deposits funds, the deposited amount is added to `wallet_balance_cents` and `escrow_available_cents` is recomputed as `wallet_balance_cents` minus `escrow_reserved_cents`. Every reservation made at confirmation and every release made at cancellation or settlement keeps this identity true, so the wallet is conserved across the full booking lifecycle.

The household-employer tax ledger is the second conserved account. As caregivers complete sessions, the family's `cash_wages_ytd_cents` accumulates the gross session pay it owes, and as payouts settle, the family's `tax_withheld_ytd_cents` accumulates the employee-share FICA withheld. The caregiver side mirrors this: `pending_earnings_cents` accrues net pay from completed-but-unpaid sessions, and `lifetime_paid_cents` accumulates net pay across settled payouts. Every forward posting to these ledgers has an exact compensating reversal, so reversing a payout returns each ledger to the precise value it held beforehand.

### 2.7. Precision and Rounding

All monetary amounts are stored and transmitted as integer cents. Wherever a calculation produces a fractional cent — pay computations, FICA withholding, platform fees, surcharges — the result is rounded to whole cents using the round-half-up method (a value of exactly one-half cent rounds upward). Durations expressed in hours, such as a session's `actual_hours`, are rounded to two decimal places, again round-half-up. A caregiver's `rating_avg` is likewise expressed to two decimal places. Where a calculation prescribes a particular order of rounding versus summation, that order is binding and is spelled out in the relevant workflow.

### 2.8. Optimistic Concurrency Control

Two specific write operations are guarded by optimistic concurrency control to prevent a client from acting on a stale view of a negotiation or a backup match.

When a counter-offer is posted against a booking, the request must carry `expected_booking_version` holding the `version` of the target `Booking` that the client last observed. If another writer has advanced the booking's `version` since the client read it, the counter is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than overwriting the latest round — each counter legitimately supersedes the prior `agreed_rate_cents`, so a counter built on a stale view of the negotiation must not silently clobber the newest offer.

When the platform matches a caregiver to a backup care request, the request must carry `expected_backuprequest_version` holding the `version` of the target `BackupCareRequest` that the client last observed. A backup request may be matched at most once. No transition ever returns a request to `OPEN`, so a request that is currently `OPEN` always still carries its initial creation `version`. The stale-version check follows the eligibility-state check in the fixed precedence of Section 2.10 (`ERR_INVALID_STATE` at priority 4 before `ERR_STALE_VERSION` at priority 5), and matching requires the request to be `OPEN`. Consequently, when a client re-matches a request whose `version` has advanced because it was already matched — so that the request has left `OPEN` — the request is no longer matchable, so the match is rejected with `ERR_INVALID_STATE` and the prior match is not overwritten; `ERR_STALE_VERSION` (HTTP 412) is surfaced only when the supplied `expected_backuprequest_version` does not match the `version` of a request that is still `OPEN`. Endpoints other than these two do not accept a version field and perform no concurrency check.

### 2.9. Cascading Consistency and Nested Retrieval

Several operations mutate more than one entity in a single atomic action; these cascades are described in full within the workflows of Section 3, and in every case the secondary entities also have their `updated_at` refreshed and their `version` incremented as part of the same operation. When a parent's state changes in a way that forces a child's state — a booking cancellation cascading to its scheduled sessions, a caregiver being flagged cascading to its open bookings — the system performs the child mutations without a separate client request.

For any request whose path or body references resources, existence is validated left to right: path identifiers are resolved first in the order they appear, then foreign-key fields named in the body. The first missing reference yields `ERR_NOT_FOUND` before any business rule is evaluated.

### 2.10. Validation Ordering

When several checks could apply to a single request, they are evaluated in a fixed precedence so that the returned error is deterministic. Authentication of the headers comes first (`ERR_UNAUTHENTICATED`). Authorization of the role and ownership comes second (`ERR_FORBIDDEN`). Existence of every referenced resource comes third (`ERR_NOT_FOUND`). For a state-changing endpoint, the target's eligibility for the requested transition comes fourth (`ERR_INVALID_STATE`). On the two concurrency-guarded writes, the stale-version check comes fifth (`ERR_STALE_VERSION`). Domain-specific business rules — tier sufficiency, suspension, posting consistency, rate floors, recurrence shape, scheduling overlaps, interval ordering, review eligibility, escrow sufficiency, and payout session validity — follow. Body well-formedness (`ERR_VALIDATION`) is the final catch-all when a required field is missing or ill-typed, an enum value falls outside its domain, or a number falls outside its permitted range.

## 3. Business Logic & Workflows

### 3.1. Onboarding Families and Caregivers

A household joins the platform as a `Family`, supplying a `display_name`, a contact `email` (unique across families), and `num_children` — the number of children needing care, which must be between 1 and 8 inclusive. A family may declare a `required_tier`, the minimum background-check tier a caregiver must hold to be bookable by this household; when omitted it defaults to `BASIC`. A family may also open its wallet with an initial `wallet_balance_cents` (defaulting to 0 and never negative). On registration the family's `status` is `ACTIVE`, its `escrow_reserved_cents` is 0, and its `escrow_available_cents` equals its `wallet_balance_cents`. The family's `tax_withheld_ytd_cents`, `cash_wages_ytd_cents`, and the `is_w2_obligated` flag all begin empty and are maintained by later workflows. To add money later, a family deposits an `amount_cents` (which must be at least 1) into its wallet, raising `wallet_balance_cents` and recomputing `escrow_available_cents` accordingly.

A caregiver joins as a `Caregiver`, supplying a `full_name`, a contact `email` (unique across caregivers), and an `hourly_rate_floor_cents` — the lowest rate they will accept, which must be at least 1. A newly registered caregiver starts with `background_check_tier` of `NONE`, `verification_status` of `NONE`, and `availability_status` of `OFFLINE`. Their computed earnings fields — `pending_earnings_cents`, `lifetime_paid_cents` — and their reputation fields `rating_avg` (0 when there are no published reviews) and `rating_count` begin empty. A caregiver may set their own `availability_status` to a new value, but a caregiver who is currently `SUSPENDED` may not move themselves out of suspension (such a self-attempt is rejected with `ERR_FORBIDDEN`); only the platform governs the suspended state, and a `PlatformAdmin` may move a caregiver out of `SUSPENDED`.

### 3.2. Background Checks and the Trust Tier

Trust on the platform is earned through background checks, which only the platform operates. A check is initiated for a caregiver by supplying the `caregiver_id` and the `requested_tier` being screened for (`BASIC`, `STANDARD`, or `PREMIUM`); it is born in `INITIATED` status with `cleared_at` unset. Starting a check that is currently `INITIATED` advances it to `IN_PROGRESS` and sets the subject caregiver's `verification_status` to `PENDING`.

From `IN_PROGRESS`, the platform records an adjudication carrying a `decision` and an optional `adjudication_note`. A decision of CLEAR moves the check to `CLEAR` (a terminal outcome): it stamps `cleared_at` with the current clock, sets the caregiver's `verification_status` to `CLEAR`, and raises the caregiver's `background_check_tier` to the greater of its current value and the check's `requested_tier` under the tier order — so a caregiver who already holds `STANDARD` and clears a `BASIC` check keeps `STANDARD`, while one who clears a `PREMIUM` check is promoted to `PREMIUM`. A decision of CONSIDER moves the check to the non-terminal `CONSIDER` state and sets `verification_status` to `CONSIDER`; from there the platform may re-run the check by invoking the same start operation that advances an `INITIATED` check, which transitions `CONSIDER` back to `IN_PROGRESS` and resets `verification_status` to `PENDING`, forming a review-and-rerun loop. (Accordingly, the start operation is permitted whenever the check is in either `INITIATED` or `CONSIDER`, and is rejected with `ERR_INVALID_STATE` otherwise.) A decision of FLAGGED — permitted from either `IN_PROGRESS` or `CONSIDER` — moves the check to the terminal `FLAGGED` state and triggers the platform's hardest cascade: the caregiver's `verification_status` becomes `FLAGGED`, the caregiver's `availability_status` is forced to `SUSPENDED`, and every booking of that caregiver currently in `OFFERED`, `COUNTERED`, or `CONFIRMED` is moved to `CANCELLED`, with each cancelled confirmed booking releasing the family escrow it had reserved. Each adjudication transition is rejected with `ERR_INVALID_STATE` if the check is not in the state the decision requires. `EXPIRED` is reserved in the background-check status vocabulary as a terminal state, but no endpoint in this API transitions a check into it.

### 3.3. Postings, Interviews, and Paid Trials

A family advertises a need by creating a `JobPosting`, providing the owning `family_id`, a `title`, a `care_type` of either `ONE_TIME` or `RECURRING`, and a `family_pay_rate_cents` — the family's offered hourly rate, which must be at least 1. The posting may carry its own `required_tier`; when omitted it inherits the family's `required_tier`. A posting opens in `OPEN` status and later moves to `FILLED` when a booking against it confirms, or to `CLOSED`.

Before committing to a booking, a family may vet a caregiver through an `Interview`. The interview references the `job_posting_id`, the interviewing `family_id`, the interviewee `caregiver_id`, a `scheduled_start` and a `scheduled_end` window (the end must be strictly after the start, else `ERR_INVALID_INTERVAL`), and a `kind` of `PHONE`, `VIDEO`, or `TRIAL` (a paid in-home trial shift). It opens in `SCHEDULED`. The family then decides the interview by supplying an `outcome` and an optional `outcome_note`. From `SCHEDULED`, a decision can fork three ways: to `PASSED`, to `FAILED`, or — only when the interview's `kind` is `TRIAL` — to `TRIAL_BOOKED`. An interview already in `TRIAL_BOOKED` can subsequently be decided to either `PASSED` or `FAILED`. A family may cancel an interview while it is in `SCHEDULED` or `TRIAL_BOOKED`, moving it to `CANCELLED`. Deciding or cancelling an interview that is not in a permitting state is rejected with `ERR_INVALID_STATE`.

### 3.4. Extending and Negotiating a Booking

The heart of the platform is the `Booking`, a multi-round negotiation between a family and a caregiver over a specific posting. A family extends an offer by referencing the `family_id`, the offered `caregiver_id`, and the `job_posting_id` it fills, together with an `agreed_rate_cents` (the hourly rate proposed in this round), a `scheduled_start` and `scheduled_end` for the first session window, an optional `recurrence_count`, and an optional `is_holiday` flag marking whether the first session falls on a holiday. The booking's `care_type` is inherited from the posting rather than supplied. On creation the booking enters `OFFERED` with `offer_round` of 1.

Several guards apply when the offer is created. The posting and the parties must be consistent — the posting's `family_id` must equal the booking's `family_id` and the posting must currently be `OPEN`, else `ERR_POSTING_MISMATCH`. The proposed `agreed_rate_cents` must be at least the caregiver's `hourly_rate_floor_cents`, else `ERR_RATE_BELOW_FLOOR`. The `recurrence_count` must match the posting's care type: it must equal 1 for a `ONE_TIME` posting and must be at least 2 for a `RECURRING` posting (defaulting to 1), else `ERR_RECURRENCE_INVALID`. The `scheduled_end` must be strictly after the `scheduled_start`, else `ERR_INVALID_INTERVAL`.

The negotiation then proceeds as a counter-offer loop. From `OFFERED`, the caregiver may counter, moving the booking to `COUNTERED`; from `COUNTERED`, the family may counter back, returning it to `OFFERED`, and the two sides may volley indefinitely. Each counter carries a new proposed `agreed_rate_cents`, which must still be at least the caregiver's `hourly_rate_floor_cents` (otherwise `ERR_RATE_BELOW_FLOOR`), and the request must carry `expected_booking_version` matching the booking's current `version` — a mismatch is rejected with `ERR_STALE_VERSION`, as described in Section 2.8. A successful counter overwrites `agreed_rate_cents` with the countered rate, increases `offer_round` by 1, and increments the booking's `version` by 1. A counter attempted against a booking not in the appropriate originating state is rejected with `ERR_INVALID_STATE`. At any point while the booking is in `OFFERED` or `COUNTERED`, the caregiver may decline it outright, moving it to the terminal `DECLINED` state.

### 3.5. Confirmation, Escrow Reservation, and Session Generation

A caregiver accepts the standing offer to confirm a booking, which may be done from either `OFFERED` or `COUNTERED`. Confirmation is the most heavily gated transition in the system, and its checks are evaluated in this order. First, the booking must be in a confirmable state, else `ERR_INVALID_STATE`. The caregiver's `verification_status` must be `CLEAR` and their `background_check_tier` must reach the family's `required_tier` under the tier order; a tier shortfall is rejected with `ERR_TIER_INSUFFICIENT`. The caregiver must not be `SUSPENDED`, else `ERR_CAREGIVER_SUSPENDED`. The family must not already hold another `CONFIRMED` or `IN_PROGRESS` booking whose first-session window overlaps this booking's first-session window — overlap here is closed-adjacency with no buffer, meaning two windows conflict whenever they share any instant — else `ERR_FAMILY_WINDOW_CONFLICT`. Finally, the family's `escrow_available_cents` must be at least the booking's `estimated_pay_cents`, else `ERR_INSUFFICIENT_ESCROW`.

When confirmation succeeds, the system performs an atomic cascade. It computes whether the booking is last-minute by setting `is_last_minute` true when the gap between the `scheduled_start` and the confirmation moment is under the last-minute window of 24 hours. It computes `estimated_pay_cents` as the forward estimate of the first session's gross pay (Section 3.6). It reserves that amount by adding it to the family's `escrow_reserved_cents` and recomputing `escrow_available_cents`. It generates the booking's sessions: for a `ONE_TIME` booking exactly one `BookingSession`, and for a `RECURRING` booking one session per the `recurrence_count`, spaced at a weekly cadence starting from the first window — each generated session spans the same duration as the first scheduled window (its `window_start` offset by a whole number of weeks, its `window_end` that start plus the first window's duration). And it marks the underlying posting `FILLED`. The booking itself moves to `CONFIRMED`.

Each generated `BookingSession` carries its parent `booking_id`, a denormalized `caregiver_id` for overlap checks, a 0-based `sequence_index` recording its position within a recurring booking, a `window_start` and `window_end` (end strictly after start), an `is_holiday` flag for whether that individual session is a holiday session — only the first session (`sequence_index` 0) inherits the booking's `is_holiday`; every later weekly session is generated with `is_holiday` false — and a `status` that opens at `SCHEDULED`. Its `clock_in_at` and `clock_out_at` are unset, its `actual_hours` is 0, and its `gross_pay_cents` is 0 until the session completes.

A family may cancel a booking while it is `CONFIRMED`, provided no child session has yet started or completed (none is `IN_PROGRESS` or `COMPLETED`). Cancellation moves the booking to `CANCELLED`, releases the reservation by subtracting `estimated_pay_cents` from the family's `escrow_reserved_cents` and recomputing `escrow_available_cents` (an exact reversal of the reservation), cascades every still-`SCHEDULED` child session to `CANCELLED`, and reopens the posting to `OPEN`. A cancellation attempted when the booking is not `CONFIRMED`, or when a child session has already started, is rejected with `ERR_INVALID_STATE`.

### 3.6. Estimating and Finalizing Session Pay

Two pay calculations sit at the core of the money flow, and they are deliberately symmetric — one forward-looking, one from actuals.

The **estimated pay** is computed at confirmation from the first session's scheduled window alone; later recurring sessions are not pre-reserved. First, the scheduled hours are the span from `scheduled_start` to `scheduled_end` expressed in hours, rounded to two decimal places. A multi-child surcharge multiplier is formed as 1 plus a per-extra-child surcharge of 10 percent for each child beyond the first — that is, 1 plus 0.10 times the quantity (`num_children` minus 1). The effective rate is the `agreed_rate_cents` multiplied by that multiplier. The base pay then depends on the holiday flag: when the booking's first session is a holiday, every scheduled hour is billed at the effective rate multiplied by the holiday multiplier of 2.0, and overtime does not additionally stack. When it is not a holiday, hours are split at the daily overtime threshold of 8.0 hours — the regular hours are the lesser of the scheduled hours and 8.0, and the overtime hours are the scheduled hours beyond 8.0 (zero if the session is shorter) — so the base is the regular hours at the effective rate plus the overtime hours at the effective rate multiplied by the overtime multiplier of 1.5. Starting from that base as the gross, if the booking is last-minute the gross is increased by the last-minute surcharge of 15 percent (the gross is multiplied by 1.15). The resulting `estimated_pay_cents` is the gross rounded to whole cents, round-half-up. This estimate drives the escrow reservation.

The **final pay** is computed at clock-out from the session's actual clocked hours, and it is the dual counterpart of the estimate, differing only in using actuals in place of the schedule. The `actual_hours` are the span from `clock_in_at` to `clock_out_at` in hours, rounded to two decimal places round-half-up. The same multi-child multiplier (1 plus 0.10 per extra child) forms the effective rate from the booking's `agreed_rate_cents`. When the session's own `is_holiday` flag is set, every actual hour is billed at the effective rate times the 2.0 holiday multiplier with no overtime stacking; otherwise the actual hours are split at the 8.0-hour daily threshold, with regular hours at the effective rate and overtime hours at the effective rate times the 1.5 overtime multiplier. If the booking is last-minute, the gross is multiplied by 1.15. The resulting `gross_pay_cents` for the session is that gross rounded to whole cents, round-half-up. Because actual hours can diverge from the schedule — a caregiver working longer, shorter, or crossing the overtime boundary — the final pay can legitimately differ from the estimate.

### 3.7. Working a Session: Clock-In, Clock-Out, and Bubble-Up

A caregiver starts work by clocking in a `SCHEDULED` session whose parent booking is `CONFIRMED` or `IN_PROGRESS`. Before clock-in is allowed, the system checks that the session's window does not collide with any of the caregiver's other non-terminal sessions: treating each window as the half-open interval from `window_start` up to but not including `window_end`, two of the caregiver's sessions conflict if they come within the travel buffer of 30 minutes of one another, so a gap of at least 30 minutes must separate them. A collision is rejected with `ERR_CAREGIVER_DOUBLE_BOOKED`. On a successful clock-in the session moves to `IN_PROGRESS`, its `clock_in_at` is stamped with the current clock, the caregiver's `availability_status` becomes `BUSY`, and — if the parent booking was still `CONFIRMED` — the booking bubbles up to `IN_PROGRESS`.

The caregiver later clocks out an `IN_PROGRESS` session, which moves it to `COMPLETED`. Clock-out stamps `clock_out_at`, computes `actual_hours` and the session's `gross_pay_cents` per Section 3.6, and then posts to the ledgers: the net of this session accrues to the caregiver's `pending_earnings_cents`, where this session net is the session's `gross_pay_cents` minus the session's employee-share FICA (`gross_pay_cents` times 0.0765, rounded to whole cents round-half-up) minus the session's platform fee (`gross_pay_cents` times 0.10, rounded to whole cents round-half-up); the session's `gross_pay_cents` is added to the family's `cash_wages_ytd_cents` with the family's `is_w2_obligated` flag recomputed, and the caregiver's `availability_status` returns to `AVAILABLE`. If clocking out leaves every sibling session of the booking in a terminal state, the booking bubbles up to `COMPLETED`. Clock-out additionally requires that the implied clock-out instant be strictly after the clock-in instant, else `ERR_INVALID_INTERVAL`.

A family may mark a `SCHEDULED` session a no-show, but only once the current clock has reached or passed the session's `window_end` (a no-show attempted before `window_end`, or against a session that is not `SCHEDULED`, is rejected with `ERR_INVALID_STATE`); the session moves to `NO_SHOW`, and if all sibling sessions are then terminal the booking bubbles up to `COMPLETED`. When a booking reaches `COMPLETED` — having every child session terminal with at least one `COMPLETED` — the system sets the booking's `final_pay_cents` to the sum of the `gross_pay_cents` of its `COMPLETED` sessions (it stays unset until the first completion) and settles the escrow by releasing the booking's entire reserved `estimated_pay_cents` out of the family's `escrow_reserved_cents` and re-deriving `escrow_available_cents` as `wallet_balance_cents` minus `escrow_reserved_cents`, so the drift between the reserved estimate and what the sessions actually consumed flows back to the family's available balance. Sessions move to `CANCELLED` only as a cascade from their parent booking's cancellation.

### 3.8. Backup Care Dispatch

When a family faces a sudden gap, it opens a `BackupCareRequest` carrying the `family_id`, a `needed_start` and `needed_end` window (end strictly after start, else `ERR_INVALID_INTERVAL`), a `required_tier` (the minimum caregiver tier acceptable for the match), and a `max_rate_cents` (the highest hourly rate the family will pay). The `matched_caregiver_id` is unset until a match is made. The request opens in `OPEN`.

The platform runs the selector to match a caregiver, an OCC-guarded write that requires `expected_backuprequest_version` matching the request's current `version` (mismatch → `ERR_STALE_VERSION`). The selector first filters the caregiver pool to those who are eligible: a caregiver qualifies only if their `availability_status` is `AVAILABLE`, their `verification_status` is `CLEAR`, their `background_check_tier` reaches the request's `required_tier` under the tier order, their `hourly_rate_floor_cents` is no greater than the request's `max_rate_cents`, and they have no scheduling overlap with the request window — the same half-open-interval-plus-30-minute-travel-buffer test used at clock-in, applied against the caregiver's non-terminal sessions. Among the eligible caregivers, the selector ranks by, in descending priority: highest `rating_avg` first (compared at two decimal places); then, breaking ties, the lowest `hourly_rate_floor_cents` (cheaper preferred); then, breaking remaining ties, the earliest `created_at` — never the `id`. The first caregiver under that ranking becomes the `matched_caregiver_id`, the request moves to `MATCHED`, and its `version` increments by 1. If no caregiver is eligible, the match is rejected with `ERR_NO_ELIGIBLE_CAREGIVER` and no match is recorded. Tier shortfall and suspension are absorbed into the eligibility filter rather than surfaced as distinct errors: a tier-short or suspended caregiver simply fails to qualify, so when no other caregiver qualifies the match still returns `ERR_NO_ELIGIBLE_CAREGIVER` (the match operation never raises `ERR_TIER_INSUFFICIENT` or `ERR_CAREGIVER_SUSPENDED`).

A family confirms that the matched caregiver served by fulfilling a `MATCHED` request, moving it to `FULFILLED`. The platform may expire an `OPEN` request once the current clock has reached or passed its `needed_start`, moving it to `EXPIRED`; an expire attempted before `needed_start`, or against a request not in `OPEN`, is rejected with `ERR_INVALID_STATE`. A family may cancel a request while it is `OPEN` or `MATCHED`, moving it to `CANCELLED`. Transitions attempted from a non-permitting state are rejected with `ERR_INVALID_STATE`.

### 3.9. Payouts, Withholding, and Household-Employer Tax

Once sessions complete, the platform sweeps them into a `Payout`. Creation references the `caregiver_id` of the payee, the `family_id` of the household employer whose W-2 ledger absorbs the tax, and a list of `session_ids` to include. Every referenced session must be `COMPLETED`, must belong to the same caregiver and family pairing, and must not already sit in a non-reversed payout; any violation is rejected with `ERR_PAYOUT_SESSION_INVALID`. The sweep considers eligible sessions ordered by `window_start` ascending, then by `created_at` ascending.

The withholding computation pins its rounding order. The payout's `gross_pay_cents` is the exact integer sum of the included sessions' `gross_pay_cents`. The `fica_withheld_cents` is computed per session — each session's `gross_pay_cents` multiplied by the employee FICA rate of 0.0765 and rounded to whole cents round-half-up — and only then summed across sessions; the binding order is round-each-session-then-sum, which differs from summing first and rounding once by the accumulated rounding remainder. The `platform_fee_cents` is the payout's gross multiplied by the platform fee of 10 percent (0.10), rounded to whole cents round-half-up. The `net_pay_cents` is the gross minus the FICA withheld minus the platform fee. The payout is born in `PENDING`.

Settling a `PENDING` payout marks it `PAID` and posts the cross-entity ledger effects: the `net_pay_cents` is subtracted from the caregiver's `pending_earnings_cents` and added to the caregiver's `lifetime_paid_cents`, and the `fica_withheld_cents` is added to the family's `tax_withheld_ytd_cents`. Reversing a `PAID` payout marks it `REVERSED` and performs the exact compensating reversal: the `net_pay_cents` is subtracted back out of the caregiver's `lifetime_paid_cents`, the `fica_withheld_cents` is subtracted back out of the family's `tax_withheld_ytd_cents`, and the `gross_pay_cents` is subtracted back out of the family's `cash_wages_ytd_cents` with the family's `is_w2_obligated` flag recomputed. A pay or reverse attempted from the wrong status is rejected with `ERR_INVALID_STATE`.

The household-employer W-2 obligation is a per-caregiver, per-tax-year threshold test. The platform groups a family's wages by caregiver and tax year — summing the `gross_pay_cents` of `COMPLETED` sessions paid from that family to that caregiver within the year, with reversed payouts decrementing the group — and sets `is_w2_obligated` to true when, for any single caregiver, that grouped wage total is strictly greater than the federal annual wage threshold of 270000 cents. The comparison is an exact integer compare and is strictly greater-than: a grouped total of exactly 270000 cents does not obligate the family, while 270001 cents does.

When the platform issues a W-2, it creates a `TaxStatement` for a `family_id`, `caregiver_id`, and `tax_year`, freezing a snapshot of `cash_wages_cents` and `fica_withheld_cents` at issuance. The `tax_year` of a session is the calendar year of its `window_start`. `cash_wages_cents` is the sum of `gross_pay_cents` over that family's and caregiver's `COMPLETED` sessions whose `window_start` falls in `tax_year`, decremented by the `gross_pay_cents` of any `REVERSED` payout in that pairing that swept such a session. `fica_withheld_cents` is the sum of `fica_withheld_cents` over `PAID` payouts of that pairing that include at least one session whose `window_start` falls in `tax_year`. The statement is immutable thereafter.

### 3.10. Ratings, Reviews, and Reputation

After a booking completes, the authoring family may submit a `Review` of the caregiver, referencing the `booking_id` of the completed booking, the author `family_id`, the subject `caregiver_id`, a `rating_value` star rating between 1 and 5 inclusive, and an optional free-text `comment`. A review may be created only when its booking's status is `COMPLETED` and the authoring family owns that booking; a review against a booking that is not completed is rejected with `ERR_BOOKING_NOT_COMPLETED`. New reviews enter `PENDING_MODERATION`.

The platform moderates each review with a `decision` of either `PUBLISH` or `HIDE`. Publishing (decision `PUBLISH`) a `PENDING_MODERATION` review moves it to `PUBLISHED` and triggers a reconciliation of the subject caregiver's reputation: `rating_avg` is recomputed as the mean of `rating_value` across that caregiver's `PUBLISHED` reviews (to two decimal places, 0 when there are none) and `rating_count` is recomputed as the count of those `PUBLISHED` reviews. Hiding (decision `HIDE`) a `PENDING_MODERATION` review moves it to `HIDDEN` with no reputation effect. A `PUBLISHED` review may later be hidden, moving it to `HIDDEN` and likewise recomputing the caregiver's `rating_avg` and `rating_count` over the remaining published reviews. A moderation decision against a review not in a permitting state is rejected with `ERR_INVALID_STATE`.

### 3.11. The Test Clock

Because nearly every temporal rule — last-minute determination, no-show eligibility, backup expiry, session overlap — depends on the current moment, the platform exposes an administrator-only test-driving capability that sets the deterministic system clock to a supplied `to_iso8601` instant. The clock-set response's `data` is an object carrying the single field `now` (the newly set instant as an ISO 8601 UTC timestamp). All "current clock" references throughout the workflows above read from this clock.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource, drive a state transition, or otherwise act on a resource by its identifier return a `200 OK` status code.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/marketplace/_clock/set` | Set the deterministic system clock | PlatformAdmin |
| POST | `/marketplace/families` | Register a family (household employer) | PlatformAdmin, Family |
| GET | `/marketplace/families/{id}` | Get a family | PlatformAdmin, Family, Caregiver |
| GET | `/marketplace/families` | List families | PlatformAdmin |
| POST | `/marketplace/families/{id}/deposit` | Add funds to a family's wallet | PlatformAdmin, Family |
| POST | `/marketplace/caregivers` | Register a caregiver | PlatformAdmin, Caregiver |
| GET | `/marketplace/caregivers/{id}` | Get a caregiver | PlatformAdmin, Family, Caregiver |
| GET | `/marketplace/caregivers` | List caregivers | PlatformAdmin, Family |
| POST | `/marketplace/caregivers/{id}/availability` | Caregiver sets availability (cannot leave SUSPENDED) | PlatformAdmin, Caregiver |
| POST | `/marketplace/background-checks` | Initiate a background check at a tier | PlatformAdmin |
| GET | `/marketplace/background-checks/{id}` | Get a background check | PlatformAdmin, Caregiver |
| GET | `/marketplace/background-checks` | List background checks | PlatformAdmin, Caregiver |
| POST | `/marketplace/background-checks/{id}/start` | Advance a check to IN_PROGRESS | PlatformAdmin |
| POST | `/marketplace/background-checks/{id}/adjudicate` | Record an adjudication outcome | PlatformAdmin |
| POST | `/marketplace/job-postings` | Create a job posting | PlatformAdmin, Family |
| GET | `/marketplace/job-postings/{id}` | Get a job posting | PlatformAdmin, Family, Caregiver |
| GET | `/marketplace/job-postings` | List job postings | PlatformAdmin, Family, Caregiver |
| POST | `/marketplace/interviews` | Schedule an interview/trial | PlatformAdmin, Family |
| GET | `/marketplace/interviews/{id}` | Get an interview | PlatformAdmin, Family, Caregiver |
| GET | `/marketplace/interviews` | List interviews | PlatformAdmin, Family, Caregiver |
| POST | `/marketplace/interviews/{id}/decide` | Record an interview outcome | PlatformAdmin, Family |
| POST | `/marketplace/interviews/{id}/cancel` | Cancel an interview | PlatformAdmin, Family |
| POST | `/marketplace/bookings` | Extend a booking offer to a caregiver | PlatformAdmin, Family |
| GET | `/marketplace/bookings/{id}` | Get a booking | PlatformAdmin, Family, Caregiver |
| GET | `/marketplace/bookings` | List bookings | PlatformAdmin, Family, Caregiver |
| POST | `/marketplace/bookings/{id}/counter` | Counter-offer a new rate (OCC-guarded) | PlatformAdmin, Family, Caregiver |
| POST | `/marketplace/bookings/{id}/confirm` | Accept an offer; reserve escrow; generate sessions | PlatformAdmin, Caregiver |
| POST | `/marketplace/bookings/{id}/decline` | Decline an offer | PlatformAdmin, Caregiver |
| POST | `/marketplace/bookings/{id}/cancel` | Cancel a confirmed booking | PlatformAdmin, Family |
| GET | `/marketplace/sessions/{id}` | Get a booking session | PlatformAdmin, Family, Caregiver |
| GET | `/marketplace/sessions` | List sessions | PlatformAdmin, Family, Caregiver |
| POST | `/marketplace/sessions/{id}/clock-in` | Caregiver clocks in (overlap-checked) | PlatformAdmin, Caregiver |
| POST | `/marketplace/sessions/{id}/clock-out` | Caregiver clocks out; compute final pay | PlatformAdmin, Caregiver |
| POST | `/marketplace/sessions/{id}/no-show` | Mark a session a no-show | PlatformAdmin, Family |
| POST | `/marketplace/backup-requests` | Open a backup care request | PlatformAdmin, Family |
| GET | `/marketplace/backup-requests/{id}` | Get a backup care request | PlatformAdmin, Family, Caregiver |
| GET | `/marketplace/backup-requests` | List backup care requests | PlatformAdmin, Family, Caregiver |
| POST | `/marketplace/backup-requests/{id}/match` | Run the selector to match a caregiver (OCC-guarded) | PlatformAdmin |
| POST | `/marketplace/backup-requests/{id}/fulfill` | Confirm the matched caregiver served | PlatformAdmin, Family |
| POST | `/marketplace/backup-requests/{id}/expire` | Expire an unmatched request past needed_start | PlatformAdmin |
| POST | `/marketplace/backup-requests/{id}/cancel` | Cancel a backup request | PlatformAdmin, Family |
| POST | `/marketplace/payouts` | Sweep COMPLETED sessions into a payout | PlatformAdmin |
| GET | `/marketplace/payouts/{id}` | Get a payout | PlatformAdmin, Caregiver |
| GET | `/marketplace/payouts` | List payouts | PlatformAdmin, Caregiver |
| POST | `/marketplace/payouts/{id}/pay` | Settle a payout to the ledgers | PlatformAdmin |
| POST | `/marketplace/payouts/{id}/reverse` | Reverse a paid payout | PlatformAdmin |
| POST | `/marketplace/reviews` | Submit a review for a completed booking | PlatformAdmin, Family |
| GET | `/marketplace/reviews/{id}` | Get a review | PlatformAdmin, Family, Caregiver |
| GET | `/marketplace/reviews` | List reviews | PlatformAdmin, Family, Caregiver |
| POST | `/marketplace/reviews/{id}/moderate` | Publish or hide a review | PlatformAdmin |
| POST | `/marketplace/tax-statements` | Issue a W-2 tax statement snapshot | PlatformAdmin |
| GET | `/marketplace/tax-statements/{id}` | Get a tax statement | PlatformAdmin, Family, Caregiver |
| GET | `/marketplace/tax-statements` | List tax statements | PlatformAdmin, Family, Caregiver |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_TIER_INSUFFICIENT` | 422 |
| `ERR_CAREGIVER_SUSPENDED` | 422 |
| `ERR_POSTING_MISMATCH` | 422 |
| `ERR_RATE_BELOW_FLOOR` | 422 |
| `ERR_RECURRENCE_INVALID` | 422 |
| `ERR_CAREGIVER_DOUBLE_BOOKED` | 409 |
| `ERR_FAMILY_WINDOW_CONFLICT` | 409 |
| `ERR_INVALID_INTERVAL` | 422 |
| `ERR_BOOKING_NOT_COMPLETED` | 422 |
| `ERR_INSUFFICIENT_ESCROW` | 422 |
| `ERR_PAYOUT_SESSION_INVALID` | 422 |
| `ERR_NO_ELIGIBLE_CAREGIVER` | 422 |
