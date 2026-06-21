# Standardized Test Registration API — Product Requirements Document

## 1. Introduction

This document specifies the Standardized Test Registration Management platform, a back-office API that coordinates the full registration lifecycle for the major college-admission and credit-by-examination programs — the SAT, the ACT, and the AP and CLEP exams. The platform exists because a single sitting touches an unusually wide set of regulated workflows that are normally handled by disconnected systems: a test center must publish seat capacity for a given administration window, candidates must be able to reserve and pay for those seats, students with documented disabilities must be able to request and receive extended-time accommodations under their 504 plan or IEP, scoring operations must record raw scores and later release Super Score composites that draw the best section results across multiple sittings, and finance must apply a date-sensitive tiered refund whenever a seat is cancelled. Each of these concerns carries its own correctness rules, and the platform's job is to keep them mutually consistent inside every request.

The system is organized around four operational constituencies that never overlap in authority. Test center operators publish administration windows and run the on-site check-in and identity-verification process. Candidates self-register, join standby waitlists when a session is full, manage their own accommodation requests and score sends, and file CLEP credit claims. A dedicated accommodation review function adjudicates 504/IEP requests against documentation and seat availability. Scoring operations records section scores, releases sittings, and recognizes CLEP credit. Because seats are a scarce, conserved resource — a cancelled seat must be released exactly once, and a freed standard seat must be offered to the highest-ranked waiting alternate — the platform treats capacity accounting, money accounting, and the standby promotion cascade as a single atomic settlement that completes inside the triggering request, with optimistic concurrency protecting against two clients racing for the same freed seat.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply uniformly across the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. The `X-User-ID` header identifies the acting user, and the `X-User-Role` header declares the operational capacity under which they are acting. If either header is missing, or if `X-User-Role` does not name a role the system recognizes, the request is rejected with `ERR_UNAUTHENTICATED`. The system recognizes exactly four roles, spelled precisely as follows: `Candidate`, `TestCenterAdmin`, `AccommodationReviewer`, and `ScoreOps`. Once authentication succeeds, the system additionally checks that the acting role is permitted to perform the requested operation; an operation attempted by a role that does not own it is rejected with `ERR_UNAUTHORIZED`.

The four roles partition the surface into disjoint slices, and no role is a superset of any other. A `Candidate` is a test-taker who owns their own candidate record and everything that hangs off it: their registrations, confirmations, cancellations, score cancellations, accommodation requests and resubmissions, standby entries, standby claims and declines, score sends, and CLEP claims. A `TestCenterAdmin` is a center operator who owns test centers, test sessions, session close, on-site check-in, and identity verification. An `AccommodationReviewer` owns the 504/IEP review queue — beginning review, requesting more information, approving, and denying accommodation requests. A `ScoreOps` operator owns score recording, score release, and CLEP adjudication. All four roles may perform read (GET) operations across the surface and may set the simulated clock.

The headers tie to ownership differently per role. When `X-User-Role` is `Candidate`, `X-User-ID` is the `id` of the acting `Candidate`; ownership checks on any resource that references a candidate compare that resource's candidate foreign key to `X-User-ID`. When `X-User-Role` is `TestCenterAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. The same opaque treatment applies when `X-User-Role` is `AccommodationReviewer` and when `X-User-Role` is `ScoreOps`: in both cases `X-User-ID` is an opaque operator identifier that the server does not match against any stored entity identifier.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and accepted values range from a minimum of 1 to a maximum of 100. The `offset` parameter is the number of items to skip before collecting the page and defaults to 0.

Unless an endpoint explicitly states otherwise, every list endpoint returns its resources sorted by their creation timestamp in ascending order — that is, oldest first by `created_at`. Because the simulated clock (§2.11) can mint several resources at the same instant, two resources sharing an identical `created_at` are ordered by their creation sequence, oldest created first, so list ordering stays deterministic.

Each list response carries the pagination bookkeeping inside the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Identifiers

Every persisted resource carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp expressed as an ISO 8601 UTC value with three fractional digits, fixed at the moment the resource is first created. Most resources additionally carry an `updated_at` timestamp, refreshed on every mutation, and an integer `version` that begins at 1 and increments by one on each mutation. The ten core resources of this system — test centers, test sessions, candidates, registrations, accommodation requests, standby entries, score reports, score sends, CLEP claims, and identity verifications — all carry the full `id`, `created_at`, `updated_at`, and `version` set. There are no immutable-after-creation resources in this domain; every resource exposes `updated_at` and `version`.

Foreign-key relationships between resources are never exposed as schema declarations; instead they are carried as identifier fields on the referencing resource and supplied through request bodies and query strings, as described throughout Section 3.

### 2.5. Resource Existence and Left-to-Right Validation

Before any business rule runs, the system confirms that every resource the request names actually exists. This covers both identifiers embedded in the URL path and foreign-key identifiers carried in the request body. These existence checks are performed left to right, and the first identifier that does not resolve to a stored resource causes the request to be rejected with `ERR_NOT_FOUND` before any later identifier is examined. For example, a registration create that names a non-existent `test_session_id` and a non-existent `candidate_id` reports the session miss first.

After existence is confirmed, request bodies are checked for well-formedness: all required fields must be present, every enumerated field must carry a value inside its declared set, and every numeric field must fall within its accepted bounds. A malformed body — a missing required field, an out-of-range enum, or an out-of-bounds score — is rejected with `ERR_INVALID_REQUEST`.

### 2.6. Validation Ordering

When several checks could apply to one operation, they are evaluated in a fixed priority order so that the same offending request always produces the same error. The order is: authentication first (`ERR_UNAUTHENTICATED`), then authorization (`ERR_UNAUTHORIZED`), then existence of path and foreign-key resources (`ERR_NOT_FOUND`), then request-body well-formedness (`ERR_INVALID_REQUEST`), then the optimistic-concurrency version check (`ERR_STALE_SESSION_VERSION`), then the state-validity check for the requested transition (`ERR_INVALID_STATE`), and only then the domain-specific business rules that follow. Within the business tier, the more fundamental eligibility and safety checks precede the fiscal capacity checks. Concretely, where they coincide on one operation, accommodation eligibility, identity-verification gating, bindability, window-overlap, candidate schedule separation, and session-closed checks are evaluated ahead of the standard-pool and accommodated-pool capacity checks, which in turn precede the refund-window check. This ordering guarantees, for instance, that an unauthenticated caller never learns whether a resource exists, and that a state-validity failure surfaces before a capacity failure rather than being masked by it.

### 2.7. Seat Capacity Conservation

Seats are the system's scarce, conserved resource, and the platform accounts for them through two integer counters maintained on each `TestSession`: `standard_seats_reserved` and `accommodated_seats_reserved`. Each counter records, at all times, the number of registrations on that session drawing from its pool whose `lifecycle_status` is `RESERVED`, `CONFIRMED`, or `CHECKED_IN`. A standard registration draws from `standard_seats_reserved`; an accommodated registration draws from `accommodated_seats_reserved`. Both counters begin at 0 when the session is created. The two pools are sized independently by the session's host center, which publishes `room_capacity_standard` for its standard testing room and `room_capacity_accommodated` for its separate, extended-time room. Every operation that takes or releases a seat adjusts the matching counter by exactly one and increments the session's `version` by one, so that the counters and the version always move together. When an accommodation is approved for an already-reserved seat, the seat is moved between pools rather than created or destroyed: the standard counter is reduced by one and the accommodated counter raised by one in the same settlement.

### 2.8. Money Conservation and Precision

Money is also conserved, tracked per center in the integer field `net_revenue_cents` on `TestCenter`, which holds the running sum of all registration fees captured at that center's sessions minus all refunds issued. This counter starts at 0 when a center is created. Every fee capture adds to it and every refund subtracts from it, so the center ledger and the registrations beneath it never drift apart. All monetary amounts in this system are integer cent values. Wherever a calculation produces a fractional cent — the percentage products in the tiered refund, or a fee-reduction product in the AP fee settlement — the result is rounded half up to the nearest whole cent. The ACT composite, which is a mean of four section scores, is likewise rounded half up to the nearest whole integer.

### 2.9. Optimistic Concurrency on Session Version

Two write operations are guarded by optimistic concurrency against the parent `TestSession.version`, because both consume a free seat and a stale view of the session would otherwise overbook it.

The first is creating a registration. A registration create must carry `expected_test_session_version` holding the session `version` the client last observed. If the session's current `version` has advanced since then — because an intervening registration or a standby promotion already took the seat the client meant to take and bumped the version — the create is rejected with `ERR_STALE_SESSION_VERSION` (HTTP 412) rather than silently overbooking the session.

The second is claiming a standby offer. A standby claim must also carry `expected_test_session_version` matching the session's current `version`. If a cancel-or-promotion cascade has re-allocated the freed seat and advanced the version since the candidate received their offer, the claim is rejected with `ERR_STALE_SESSION_VERSION` (HTTP 412), because the seat the claimant expected to take may already have been legitimately reallocated. These are the only two endpoints that take a version field; no other operation requires or accepts `expected_test_session_version`.

### 2.10. Cascading Settlements and Immediate Consistency

Several operations mutate more than one resource, and all such cascades settle inside the triggering request — there is no deferred reconciliation. Releasing a scored sitting recomputes the candidate's Super Score across their other released sittings. Approving an accommodation rebinds a registration, moves its seat between pools, and recomputes the registration's granted minutes. Most consequentially, cancelling a registration (or sweeping it to no-show at close) frees a seat, and if that freed seat is a standard seat with a waiting alternate, the system promotes the top-ranked alternate, which itself mints a held registration — a chain that can run three levels deep. Each resource touched in a cascade has its own `updated_at` refreshed and its own `version` incremented; in particular, every seat movement bumps the session's `version`, which is what makes the optimistic-concurrency checks of §2.9 meaningful.

### 2.11. The Simulated Clock

Because refund tiers, standby recency, and session-close behavior all depend on the passage of time, the platform runs against a settable logical clock rather than wall-clock time. Any role may set the simulated current UTC instant by supplying a `to_iso8601` value; from that point forward, every day-difference and hour-difference computation in the system — refund-tier day counting, standby waited-hours, and the "test date has passed" determination at close — uses this simulated clock as "now". The server-minted `created_at` and `updated_at` timestamps of §2.4 are likewise stamped from this same simulated clock, so that a resource's `created_at` lies on the same timeline as the "now" against which its standby waited-hours and other time differences are measured. Until the clock has been set, both the simulated "now" and these minted timestamps fall back to real wall-clock UTC.

### 2.12. Reverse Reachability of Linked Resources

Because relationships are carried as identifier fields rather than nested URLs, the platform exposes filtered list capabilities so that any resource reachable by a foreign key can be found from its parent, with every list honoring the pagination and ordering rules of §2.3 through its `limit` and `offset` parameters. Registrations can be listed and filtered by their `test_session_id`, their `candidate_id`, or their `accommodation_request_id`. Score reports can be listed by `registration_id` or `candidate_id`. Score sends are listable for a given registration. Accommodation requests can be filtered by `candidate_id`, `target_registration_id`, or `status`. Standby entries can be filtered by `test_session_id`, `candidate_id`, their self-referential `promoted_from_entry_id`, their `offered_registration_id`, or `status`. CLEP claims can be listed for a candidate and filtered by `status`. Test sessions can be filtered by `test_center_id` and `exam_type`. Identity verifications can be listed for a registration.

## 3. Business Logic & Workflows

### 3.1. Centers, Sessions, and the Administration Window

The platform begins with physical infrastructure. A `TestCenterAdmin` creates a **test center** by supplying its display `name`, the two-letter US `state_code` where it physically sits (such as `CA` or `NY`), and the seat capacities of its two rooms: `room_capacity_standard` for the main room and `room_capacity_accommodated` for the separate extended-time room. A freshly created center has its `net_revenue_cents` ledger initialized to zero.

On top of a center, the same operator schedules **test sessions**. A session create names its host center through `test_center_id` and declares the `exam_type` — one of `SAT`, `ACT`, or `AP` — together with an `exam_subject` label, which carries the specific AP subject (for example `AP_CALC_BC`) for AP sessions and the literal `GENERAL` for SAT and ACT sessions. The session also fixes its `test_date` as a calendar date, the administration window as `window_start_utc` and `window_end_utc`, and the per-seat `base_fee_cents`. A new session starts with both seat counters at zero, a `version` of 1, and its `registration_status` set to `OPEN`. The administration window is treated as half-open — it includes its start instant and excludes its end instant — and the system forbids scheduling two sessions whose windows overlap at the same center on the same date; an overlapping create is rejected with `ERR_SESSION_WINDOW_OVERLAP`. Because the window is half-open, two sessions that merely touch at a shared boundary instant do not overlap and are both allowed.

A session is closed by its center operator once its `test_date` has passed the simulated clock. Closing flips `registration_status` to `CLOSED`, which blocks any further registrations. Closing also performs an end-of-day sweep: every registration on the session that is `CONFIRMED` but was never `CHECKED_IN` is moved to `NO_SHOW`, and for each such forfeiture the matching seat pool is reduced by one — with no refund, since the seat is forfeited — and the session `version` is incremented once per release. A registration already in `CHECKED_IN` that never received a score is likewise considered a no-show at close. The same close action expires the waitlist: every standby entry on the session still in `WAITING` is moved to `EXPIRED`.

### 3.2. The Candidate and Identity

A **candidate** is created by the test-taker themselves, who supplies their `legal_first_name` and `legal_last_name` exactly as printed on their government photo ID, their `date_of_birth`, their `home_state_code` of legal residence, and the `id_document_state_code` of the state that issued that photo ID. A candidate may also declare `has_active_504_iep`, a boolean that defaults to false when omitted and that gates all accommodation eligibility downstream.

Identity is verified on test day, not at registration. When a candidate arrives, the center operator records an **identity verification** against the registration being checked in, supplying the `presented_first_name`, the `presented_last_name`, and the `presented_id_state_code` printed on the document handed over at the desk. The system first determines `cross_state`, which is true exactly when the presented ID's issuing state differs from the host center's `state_code`, and false otherwise. The matching standard then depends on that flag: when the ID is cross-state, the verification yields an `outcome` of `MATCH` only if both the presented first name and the presented last name are exactly equal — character for character, case sensitive — to the candidate's legal first and last names, and `MISMATCH` otherwise. When the ID is same-state, the comparison is case-insensitive: the `outcome` is `MATCH` when the presented first and last names equal the candidate's legal names ignoring letter case, and `MISMATCH` otherwise. The stricter cross-state rule reflects the higher fraud risk of out-of-state identification.

### 3.3. Reserving and Confirming a Seat

A `Candidate` reserves a seat by creating a **registration** that names the `test_session_id` of the desired session and the `candidate_id` doing the registering, and that carries `expected_test_session_version` as described in §2.9. Optionally the request may carry a `fee_reduction_pct` expressing a fee waiver; when omitted, the fee reduction is zero. A successful reservation lands the registration in lifecycle status `RESERVED` and score status `PENDING`, with `seat_kind` defaulting to `STANDARD`, drawing the seat from the standard pool: `standard_seats_reserved` is increased by one and the session `version` is incremented. The fee captured is recorded in `amount_paid_cents`, and that same amount is added to the host center's `net_revenue_cents`. At reservation the registration's `allotted_minutes` is set to the standard, un-accommodated minute count for the exam, the `accommodation_request_id` binding is left empty, `amount_refunded_cents` and the `refund_tier` are untouched, and `is_standby_origin` is false.

Several conditions can defeat a reservation. A session whose `registration_status` is `CLOSED` cannot accept new registrations and is rejected with `ERR_SESSION_CLOSED`. If the standard pool is already at capacity — `standard_seats_reserved` has reached `room_capacity_standard`, leaving no room for one more — the reservation is rejected with `ERR_SESSION_FULL`, and the candidate's recourse is to join standby instead. And, as in §2.9, a `expected_test_session_version` that no longer matches the session's current `version` is rejected with `ERR_STALE_SESSION_VERSION`.

The amount captured at reservation is governed by the AP fee settlement rule, which matters most for AP orders that bundle several exams. Each AP exam in an order is a line item, and each line item carries the session's `base_fee_cents`. The settlement applies the order's fee reduction to each line item independently: for each line item, the captured amount is its `base_fee_cents` multiplied by one minus the `fee_reduction_pct`, and that per-line product is rounded half up to a whole cent. Only after every line item has been rounded individually are the per-line amounts summed to produce `amount_paid_cents`. The rounding happens per line item and then the totals are summed — never the reverse — because summing the unrounded line products and rounding once at the end yields a different total whenever a per-line product lands on a half-cent boundary. A single-seat registration that is not an AP bundle is simply one line item under the same rule.

A reserved registration is advanced to `CONFIRMED` by the candidate, provided the registration is currently `RESERVED` and the host session's `registration_status` is still `OPEN`; otherwise the transition is rejected with `ERR_INVALID_STATE`. Confirming changes no seat counts, because the seat was already counted at reservation.

On test day the center operator checks a candidate in, advancing the registration from `CONFIRMED` to `CHECKED_IN`. This requires the registration to be `CONFIRMED` to begin with — a check-in attempted from any other lifecycle state is rejected with `ERR_INVALID_STATE`. Two cross-entity gates then apply. First, there must already exist an identity verification for this registration whose `outcome` is `MATCH`; a check-in attempted without such a passing verification on file is rejected with `ERR_ID_VERIFICATION_FAILED`. Second, if the registration's `seat_kind` is `ACCOMMODATED`, its bound accommodation request must have reached status `APPROVED`. Check-in changes no seat counts.

### 3.4. Accommodations: the 504/IEP Review Queue

A candidate who needs extended time submits an **accommodation request** naming the `candidate_id`, the `target_registration_id` it will bind to once approved, the `accommodation_type`, and the documentation `basis`. The accommodation type is one of `EXTENDED_TIME_50`, `EXTENDED_TIME_100`, `SEPARATE_ROOM`, or `BREAKS_ONLY`, and the basis is either `PLAN_504` or `IEP`. A new request begins in status `SUBMITTED`.

The review machine is a branching workflow with a cycle, owned by the `AccommodationReviewer`. The reviewer first opens a `SUBMITTED` request for review, moving it to `UNDER_REVIEW`; this is permitted only when the request is `SUBMITTED` and only when the owning candidate's `has_active_504_iep` flag is true. A candidate without an active 504 plan or IEP cannot have a request opened, and the attempt is rejected with `ERR_NOT_504_IEP_ELIGIBLE`. From `UNDER_REVIEW` the reviewer may request more documentation, supplying a `reviewer_note` and moving the request to `MORE_INFO_NEEDED`; from `MORE_INFO_NEEDED` the candidate resubmits to send the request back to `UNDER_REVIEW`, and this `MORE_INFO_NEEDED → UNDER_REVIEW` cycle may repeat. Each of these transitions is allowed only from its stated source status; an attempt from any other status is rejected with `ERR_INVALID_STATE`.

From `UNDER_REVIEW` the request reaches one of two terminal outcomes. The reviewer denies it — recording a `reviewer_note`, moving it to `DENIED`, and leaving the target registration `STANDARD` and otherwise untouched. Or the reviewer approves it, moving it to `APPROVED`, which is the most consequential transition in this workflow and is described in §3.5. Both deny and approve are permitted only from `UNDER_REVIEW`.

### 3.5. Approval: Binding, Pool Movement, and Minutes

Approving an accommodation request is only possible from `UNDER_REVIEW` and only when several binding conditions hold together. The target registration must still be bindable — not yet `CHECKED_IN`, with its lifecycle status being `RESERVED` or `CONFIRMED`, and owned by the requesting candidate; a target that is already checked in or that belongs to a different candidate is rejected with `ERR_ACCOMMODATION_NOT_BINDABLE`. The accommodated pool must have room: the session's `accommodated_seats_reserved` must be below the center's `room_capacity_accommodated`, otherwise the approval cannot move the seat and is rejected with `ERR_ACCOMMODATED_FULL`. And the candidate's accommodated sittings must respect a rest separation, described below, or the approval is rejected with `ERR_CANDIDATE_SCHEDULE_CONFLICT`.

When approval succeeds it performs a single atomic settlement. It binds the registration to this request by setting the registration's `accommodation_request_id` to this request's `id` and flipping `seat_kind` to `ACCOMMODATED`. It moves the seat between pools on the host session — reducing `standard_seats_reserved` by one and raising `accommodated_seats_reserved` by one — and increments the session `version`. And it recomputes the registration's `allotted_minutes` from the approved accommodation, a depth-two cascade onto the bound registration.

The granted-minutes computation starts from a base minute count fixed by the session's `exam_type`: 134 minutes for `SAT`, 175 minutes for `ACT`, and 180 minutes for `AP`. The base is then scaled by a multiplier chosen by `accommodation_type`: `EXTENDED_TIME_50` multiplies the base by 1.5, `EXTENDED_TIME_100` multiplies it by 2.0, while `SEPARATE_ROOM` and `BREAKS_ONLY` leave the base unchanged at a multiplier of 1.0. The scaled value is then taken down to a whole number of minutes by discarding any fractional part (floor), producing `allotted_minutes`. A registration with no approved accommodation simply carries the exam's base minute count, equivalent to a multiplier of 1.0.

The rest-separation rule protects a candidate from being booked into two accommodated sittings too close together. Consider a candidate's two accommodated sittings and order them in time. The required gap is measured from the earlier sitting's `window_end_utc` to the later sitting's `window_start_utc`, and that gap must be at least 3 hours. A gap of less than 3 hours — including windows that overlap or that sit exactly back to back — is rejected with `ERR_CANDIDATE_SCHEDULE_CONFLICT` at the moment the approval would make the second sitting accommodated. This 3-hour buffer is distinct from the center-slot overlap rule of §3.1: that rule is half-open and permits exact adjacency between any two sessions at a center, whereas this buffer additionally forbids back-to-back accommodated sittings for one candidate.

### 3.6. Standby: Waitlist, Promotion, Claim, and Decline

When a session's standard pool is full, a candidate joins the waitlist by creating a **standby entry** naming the `test_session_id` and the `candidate_id`, and declaring a `priority_tier` of `FEE_WAIVER`, `SCHOOL_DAY`, or `GENERAL`. A new entry starts in status `WAITING`, with its `promotion_score` computed on creation, its `promoted_from_entry_id` and `offered_registration_id` empty, and its self-referential chain pointer reserved for re-queued offers.

Promotion is automatic and is the second link of the cancellation cascade. Whenever a standard seat frees on a session — through a cancellation, a no-show sweep at close, or a declined offer — the system reconsiders the session's waiting alternates and promotes the single top-ranked one, provided a standard seat is genuinely free, meaning `standard_seats_reserved` is below `room_capacity_standard`. Promotion moves the chosen entry from `WAITING` to `OFFERED` and mints an offer-hold registration for it: a new registration with lifecycle status `RESERVED`, `seat_kind` of `STANDARD`, and `is_standby_origin` set to true, whose id is recorded on the entry as `offered_registration_id`. Minting the hold re-takes the freed seat — `standard_seats_reserved` is raised by one — and increments the session `version`. If no alternate is waiting, no promotion fires and the freed seat simply remains open.

Ranking is by a promotion score that blends tier and waiting time. Each entry's tier contributes a base weight: 300 for `FEE_WAIVER`, 200 for `SCHOOL_DAY`, and 100 for `GENERAL`. To that the system adds a recency bonus equal to the whole number of hours the entry has waited since its `created_at` measured against the simulated clock, but capped at 48 — so the recency contribution is the lesser of the elapsed whole hours and 48, and is never negative. The `promotion_score` is the tier weight plus that capped recency bonus. The entry with the highest `promotion_score` is promoted; ties are broken by `created_at` ascending, so the oldest entry wins a tie, and a further tie between two entries sharing an identical `created_at` is broken by creation sequence, oldest created first, matching the deterministic list ordering of §2.3. The score is recomputed whenever a standard seat frees, so a long-waiting `GENERAL` alternate can climb relative to newcomers.

A candidate acts on an offer in one of two ways. Claiming the offer carries `expected_test_session_version` and requires the entry to be `OFFERED` and its offer-hold registration to still be `RESERVED`; an offer-hold that has already been cancelled out from under the claimant is rejected with `ERR_OFFER_NO_LONGER_VALID`, and a stale session version is rejected with `ERR_STALE_SESSION_VERSION` as in §2.9. A successful claim moves the entry from `OFFERED` to `CLAIMED`, advances the offer-hold registration from `RESERVED` to `CONFIRMED`, captures the fee by setting that registration's `amount_paid_cents` to the session's `base_fee_cents`, adds that `base_fee_cents` to the center's `net_revenue_cents`, and increments the session `version` once more — which settles the concurrency token so that a second, stale claim against the same offer fails.

Declining is the revert path. From `OFFERED` the candidate may decline, which cancels the offer-hold registration (moving it to `CANCELLED` with no refund, since it was never paid), releases the held seat by reducing `standard_seats_reserved` by one, and increments the session `version`. Declining then re-runs promotion for the next-best waiting alternate; when that next alternate is promoted, its `promoted_from_entry_id` is set to the declining entry's id, recording the chain of re-queued offers for audit. A waiting entry that is never offered is moved to `EXPIRED` when its session closes, as noted in §3.1.

### 3.7. Cancellation and the Tiered Refund

A candidate may cancel a registration while it is `RESERVED` or `CONFIRMED`; a cancel attempted from any other lifecycle state is rejected with `ERR_INVALID_STATE`. Cancellation moves the registration to `CANCELLED` and triggers a four-part settlement. First, the system computes the tiered refund (below) and records it: the refund amount is added to `amount_refunded_cents` and the applied tier is written to `refund_tier`. Second, the same refund amount is subtracted from the host center's `net_revenue_cents`, preserving money conservation. Third, the seat is released — the matching pool counter, `standard_seats_reserved` or `accommodated_seats_reserved` depending on the registration's `seat_kind`, is reduced by one — and the session `version` is incremented. Fourth, if the freed seat was a standard seat and a waiting alternate exists, the standby promotion cascade of §3.6 runs, which itself mints an offer-hold registration and bumps the version again — a settlement that can run three levels deep within the single cancel request.

The refund tier is keyed on how far ahead of the test date the cancellation occurs, measured against the simulated clock. Let the days-before count be the whole number of whole days between the simulated current instant and midnight UTC at the start of the session's `test_date`, taking the floor of the elapsed-seconds difference divided by the number of seconds in a day. The tier boundaries are inclusive on their lower edge. If the days-before count is at least 60, the tier is `FULL` and the refund equals the full `amount_paid_cents`. Otherwise, if it is at least 14, the tier is `PARTIAL_75` and the refund is 75 percent of `amount_paid_cents`, rounded half up to whole cents. Otherwise, if it is at least 1, the tier is `PARTIAL_50` and the refund is 50 percent of `amount_paid_cents`, rounded half up to whole cents. Otherwise — when the days-before count is zero or negative, meaning the cancellation falls on the test day itself or after it — the tier is `NONE` and the refund is zero. The tier is keyed strictly on days before the session's `test_date`, never on days since the registration was created. The cancel itself always succeeds even in the `NONE` tier; only when a caller asserts that a refund should have been issued does a `NONE`-tier cancel surface as `ERR_REFUND_WINDOW_CLOSED`.

### 3.8. Scoring: Recording, Releasing, Super Score, and Score Sends

The scoring lifecycle runs on a status axis, `score_status`, that is independent of the seat lifecycle axis, `lifecycle_status`. A registration's `score_status` begins at `PENDING` and is advanced by `ScoreOps`. Recording scores creates a **score report** for the sitting: the operator supplies the `exam_type` (only the sectioned exams, `SAT` and `ACT`, carry a score report) and the `section_scores`, a map from section label to that section's integer raw score for this sitting — for example a reading-writing and a math score for the SAT. Recording is permitted only when the registration's score status is `PENDING` and, crucially, only when its lifecycle status is `CHECKED_IN`; this cross-axis dependency means a candidate must have actually sat the exam before a score can be recorded. Recording moves the score status to `SCORED` and computes the report's `sitting_composite`.

The sitting composite is the composite for this one sitting in isolation, computed only from the section scores supplied on this report with no reference to any other sitting. For the SAT, it is the sum of the reading-writing section score and the math section score. For the ACT, it is the arithmetic mean of the four section scores — English, math, reading, and science — rounded half up to a whole integer.

Releasing a scored sitting moves its score status from `SCORED` to `RELEASED` and makes the sitting eligible to contribute to the candidate's Super Score. Releasing recomputes `super_composite` across every released sitting of the same candidate and the same exam type. A candidate may also cancel a sitting's score: from `SCORED` the score status moves to `CANCELLED_SCORE` and the sitting is excluded from all future Super Score sweeps; from `RELEASED` it likewise moves to `CANCELLED_SCORE` with the same exclusion and recompute. Each of these transitions is allowed only from its stated source status, and a transition from any other source is rejected with `ERR_INVALID_STATE`.

The Super Score is computed per section across the candidate's qualifying sittings and only then composited — and this is deliberately different from the naive "best single sitting" reading. The qualifying set is exactly those score reports whose registration has score status `RELEASED`, the same `candidate_id`, and the same `exam_type`; sittings that are `PENDING`, `SCORED`, or `CANCELLED_SCORE` are excluded. For each section in the exam's section set, the system takes the maximum value of that section across all qualifying sittings. For the SAT the `super_composite` is the best reading-writing section plus the best math section; for the ACT it is the mean of the four best sections — English, math, reading, science — rounded half up to a whole integer. Because the best of each section may come from different sittings, the resulting `super_composite` can exceed any single sitting's composite. When exactly one sitting qualifies, the super composite equals that sitting's composite.

Once a sitting has been released, the candidate may queue a **score send** to a college. The send names the `registration_id` of the sitting, the destination `recipient_code` (the College Board or ACT recipient code), and an optional `use_super_score` flag that defaults to false. A send may only be queued when the named registration's score status is `RELEASED`. The send begins in status `QUEUED`, and at the moment it is queued the composite to be transmitted is frozen onto the send as `sent_composite`: when `use_super_score` is true the frozen value is the candidate's `super_composite`, and when it is false it is that sitting's `sitting_composite`. Freezing the value at send time means a later score change does not retroactively alter an already-queued send. A send subsequently moves from `QUEUED` to `SENT` as its transmission lifecycle.

### 3.9. CLEP Credit Recognition

Separately from the sectioned exams, a candidate may file a **CLEP claim** to have credit-by-examination recognized. The claim names the `candidate_id`, the `clep_subject` label (such as `COLLEGE_ALGEBRA`), and the reported `clep_scaled_score`, which lies on the 20-to-80 CLEP scale. A new claim begins in status `PENDING` with `recommended_credit_hours` at zero.

A `ScoreOps` operator adjudicates a pending claim, and the outcome turns on a single passing threshold of 50. If the `clep_scaled_score` is below 50, the claim is rejected — its status becomes `REJECTED` and `recommended_credit_hours` stays at zero. If the score is 50 or above, the claim is recognized — its status becomes `RECOGNIZED` — and the recommended credit hours follow a step schedule keyed on the score: a score of at least 50 but below 60 grants 3 credit hours; a score of at least 60 but below 70 grants 6 credit hours; and a score of 70 or above grants 9 credit hours. Adjudication is permitted only from `PENDING`; a second adjudication of an already-decided claim is rejected with `ERR_INVALID_STATE`.

## 4. Endpoint Definitions

Operations that create a new, standalone resource return a `201 Created` status code. Operations that modify an existing resource — including all state-transition actions and the session close — return a `200 OK` status code. Read operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/test-centers` | Create a test center | TestCenterAdmin |
| GET | `/test-centers/{id}` | Get a test center | TestCenterAdmin, Candidate, ScoreOps, AccommodationReviewer |
| POST | `/test-sessions` | Create a test session at a center | TestCenterAdmin |
| GET | `/test-sessions/{id}` | Get a test session | TestCenterAdmin, Candidate, ScoreOps, AccommodationReviewer |
| GET | `/test-sessions` | List/filter test sessions | TestCenterAdmin, Candidate, ScoreOps, AccommodationReviewer |
| POST | `/test-sessions/{id}/close` | Close a session: sweep no-shows, expire waiting standby | TestCenterAdmin |
| POST | `/candidates` | Create a candidate | Candidate |
| GET | `/candidates/{id}` | Get a candidate | Candidate, TestCenterAdmin, ScoreOps, AccommodationReviewer |
| GET | `/candidates/{id}/clep-claims` | List a candidate's CLEP claims | Candidate, ScoreOps |
| POST | `/registrations` | Reserve a seat for a candidate on a session | Candidate |
| GET | `/registrations/{id}` | Get a registration | Candidate, TestCenterAdmin, ScoreOps, AccommodationReviewer |
| GET | `/registrations` | List/filter registrations by session or candidate | Candidate, TestCenterAdmin, ScoreOps, AccommodationReviewer |
| POST | `/registrations/{id}/confirm` | Confirm a reserved registration | Candidate |
| POST | `/registrations/{id}/cancel` | Cancel a registration; refund; release seat; cascade standby | Candidate |
| POST | `/registrations/{id}/check-in` | Check a candidate in on test day | TestCenterAdmin |
| POST | `/registrations/{id}/score-reports` | Record raw section scores for a checked-in sitting | ScoreOps |
| POST | `/registrations/{id}/release-score` | Release a scored sitting; recompute super score | ScoreOps |
| POST | `/registrations/{id}/cancel-score` | Cancel a sitting's score; recompute super score | Candidate |
| GET | `/registrations/{id}/id-verifications` | List ID verifications for a registration | TestCenterAdmin, Candidate |
| GET | `/registrations/{id}/score-sends` | List score sends for a registration | Candidate, ScoreOps |
| POST | `/registrations/{id}/id-verifications` | Record an ID verification attempt for a registration | TestCenterAdmin |
| POST | `/accommodation-requests` | Submit a 504/IEP accommodation request | Candidate |
| GET | `/accommodation-requests/{id}` | Get an accommodation request | Candidate, AccommodationReviewer, TestCenterAdmin |
| GET | `/accommodation-requests` | List/filter accommodation requests | Candidate, AccommodationReviewer, TestCenterAdmin |
| POST | `/accommodation-requests/{id}/begin-review` | Open an accommodation request for review | AccommodationReviewer |
| POST | `/accommodation-requests/{id}/request-info` | Request more documentation | AccommodationReviewer |
| POST | `/accommodation-requests/{id}/resubmit` | Resubmit after providing more info | Candidate |
| POST | `/accommodation-requests/{id}/approve` | Approve; bind to registration; move seat; recompute minutes | AccommodationReviewer |
| POST | `/accommodation-requests/{id}/deny` | Deny the accommodation request | AccommodationReviewer |
| POST | `/standby-entries` | Join the standby waitlist for a full session | Candidate |
| GET | `/standby-entries/{id}` | Get a standby entry | Candidate, TestCenterAdmin |
| GET | `/standby-entries` | List/filter standby entries | Candidate, TestCenterAdmin |
| POST | `/standby-entries/{id}/claim` | Claim a standby offer (OCC against session version) | Candidate |
| POST | `/standby-entries/{id}/decline` | Decline a standby offer; release seat; promote next | Candidate |
| GET | `/score-reports/{id}` | Get a score report | Candidate, ScoreOps |
| GET | `/score-reports` | List/filter score reports by registration or candidate | Candidate, ScoreOps |
| POST | `/score-sends` | Queue a score send to a college | Candidate |
| POST | `/clep-claims` | File a CLEP credit recognition claim | Candidate |
| GET | `/clep-claims/{id}` | Get a CLEP claim | Candidate, ScoreOps |
| POST | `/clep-claims/{id}/adjudicate` | Adjudicate a CLEP claim: RECOGNIZED or REJECTED | ScoreOps |
| POST | `/_clock/set_current_utc` | Set the simulated current UTC clock (test-driving) | TestCenterAdmin, ScoreOps, Candidate, AccommodationReviewer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_SESSION_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_NOT_504_IEP_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_ID_VERIFICATION_FAILED` | 422 Unprocessable Entity |
| `ERR_ACCOMMODATION_NOT_BINDABLE` | 409 Conflict |
| `ERR_SESSION_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_CANDIDATE_SCHEDULE_CONFLICT` | 409 Conflict |
| `ERR_SESSION_CLOSED` | 409 Conflict |
| `ERR_SESSION_FULL` | 409 Conflict |
| `ERR_ACCOMMODATED_FULL` | 409 Conflict |
| `ERR_REFUND_WINDOW_CLOSED` | 409 Conflict |
| `ERR_OFFER_NO_LONGER_VALID` | 409 Conflict |
