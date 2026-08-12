# eConsult & Specialist Curbside Program API — Product Requirements Document

## 1. Introduction

Specialty care access is one of the persistent bottlenecks in a health system: routine questions that a specialist could answer in minutes instead become referral appointments scheduled weeks out, consuming visit capacity and delaying care. This program formalizes the informal "curbside consult" into an asynchronous, compensated, and auditable clinical workflow. A primary-care provider submits a structured clinical question; the platform routes it deterministically to an eligible panel specialist in the right specialty; the specialist responds within a response-time target, may ask clarifying questions, and may recommend converting the case to an in-person visit.

The API described here governs the full lifecycle of that exchange: specialty track configuration, panel enrollment and availability, consult submission and routing, clarification cycles, response submission with timeliness accounting, dual-record documentation, quality review with segregation of duties, a two-posture compensation ledger, billing claims subject to monthly track caps, and program-level measurement of avoided in-person visits. Because payment, quality standing, and routing eligibility all interact — a single rebuke can cascade from a review to a response, to the ledger, to a specialist's panel standing, and back out to every consult that specialist was holding — the specification pays particular attention to evaluation order, deterministic selection, and exact rounding behavior.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or presenting a role the system does not declare, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The system recognizes five roles, spelled exactly as follows: `ProgramCoordinator`, `ReferringProvider`, `Specialist`, `QualityReviewer`, and `BillingClerk`. Each operation restricts which roles may invoke it; a caller whose role is not listed for the endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `ReferringProvider`, `X-User-ID` is the `id` of the acting `ReferringProvider`; ownership checks on any resource that references a referring provider compare the resource's `referring_provider_id` field to `X-User-ID`. When `X-User-Role` is `Specialist`, `X-User-ID` is the `id` of the acting `Specialist`; ownership checks compare against `assigned_specialist_id` on a consult, `specialist_id` on a response or conversion, or the `specialist_id` of the membership behind an availability window. When `X-User-Role` is `QualityReviewer`, `X-User-ID` is likewise the `id` of a `Specialist` — reviewers are peer specialists — but it must never equal the responding specialist's id on the response under review, a separation-of-duties rule enforced at review creation. When `X-User-Role` is `ProgramCoordinator` or `BillingClerk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. Clinical and fiscal duties are deliberately segregated: billing operations are unavailable to every clinical role, and quality review is unavailable to the specialist who wrote the response.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, and the `meta` object of a list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Most resources in the system share a standard set of system-managed fields. The `id` is a server-minted UUID string with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created, and `updated_at` is the same kind of timestamp refreshed on every mutation. The `version` field is a system-managed integer that starts at its initial value on creation and increments by one on every modification to the resource; it is the basis for optimistic concurrency control.

Two resources are append-only audit records and deliberately carry less: a `ClarificationMessage` and a `RoutingDecision` each expose only `id` and `created_at`. Neither has `updated_at` nor `version`, because neither is ever modified after it is written.

### 2.5. The Logical Clock and the Expiry Sweep

All time-dependent behavior in the system — SLA deadlines, expiry, availability coverage, period attribution — is evaluated against a server-maintained logical clock, never against wall-clock time. At server startup the logical clock reads exactly `2026-05-01T00:00:00Z`, and the server must not fall back to wall-clock under any circumstance. A `ProgramCoordinator` may advance the logical clock through an admin-only test-driving capability that accepts a `to_iso8601` instant and sets the clock to it.

Setting the clock has a side effect beyond timekeeping: it runs the expiry sweep. Any consult still `ASSIGNED` or `CLARIFICATION_REQUESTED` whose deadline — its `sla_due_at` plus a 24-hour grace period — is strictly earlier than the new clock value transitions to `EXPIRED`, and any consult still `QUEUED` more than 72 hours after its creation — again a strictly-greater comparison — transitions to `EXPIRED` as well. Each swept consult undergoes the full cascade described in §3.3, including balance reversals and billing voiding where applicable.

### 2.6. Monetary Values and the Two-Posture Compensation Ledger

All monetary amounts in the system are integer cents; no fractional cents exist anywhere. Wherever a computation produces a non-integer cent value, the result is rounded half up to a whole cent at the step the specification names — and only at that step. This matters most where rounding order is pinned: rounding a component first and deriving a second component from the rounded value yields a different cent total than rounding once at the end, and only the pinned order is conformant.

Specialist compensation is recorded in an append-only ledger of `CompensationEntry` rows. Every entry carries a `membership_id`, the originating `consult_id`, an `entry_type` of either `RESPONSE_FEE` or `CLARIFICATION_FEE`, a signed integer `amount_cents`, a `posture`, and a `period_key` holding the calendar month of the entry's creation in `YYYY-MM` form. Posture is the ledger's central idea: entries are born `PROVISIONAL`, become `POSTED` when the associated response is finalized, and become `REVERSED` when the underlying work is undone by cancellation, expiry, or rebuke. A membership's `provisional_balance_cents` is the sum of `amount_cents` over its `PROVISIONAL` entries, and its `posted_balance_cents` is the sum over its `POSTED` entries; both are maintained eagerly as entries change posture, so a read of the membership always reflects the current ledger.

### 2.7. Optimistic Concurrency Control on Consult Writes

Two consult write operations are guarded by optimistic concurrency control, and both name the guard field identically: `expected_consult_version`. Amending a consult's structured question requires the client to present `expected_consult_version` carrying the consult's `version` it last observed; if any intervening mutation — a prior amendment, a routing event, a clarification, a response, or a cascade — has advanced the version, the amendment is stale and is rejected with `ERR_STALE_CONSULT_VERSION` (HTTP 412). Re-running the routing selector for a queued consult is guarded the same way: the request must carry `expected_consult_version` matching the consult's current `version`, and a mismatch is rejected with `ERR_STALE_CONSULT_VERSION` (HTTP 412). Re-routing is legitimate whenever the consult is queued, so the stale-view conflict is resolved purely by this version check rather than by any additional state precondition. No other endpoint accepts a version field.

### 2.8. Validation Priority Order

When several rules could reject the same request, the server evaluates them in a fixed order so the surfaced error is deterministic. Authentication context comes first: missing or malformed identity headers yield `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, and a caller whose role is not authorized for the endpoint yields `ERR_INSUFFICIENT_PERMISSIONS`. Request-body schema validation follows — missing required fields, wrong types, invalid enum members, and string-length violations such as a too-short question or an out-of-range score all yield `ERR_INVALID_REQUEST`. Existence of every path- and body-referenced resource id comes next, validated left to right, with the first missing resource producing `ERR_NOT_FOUND`. After existence, the optimistic-concurrency check is applied where the endpoint declares one, producing `ERR_STALE_CONSULT_VERSION`. Ownership checks follow, surfacing the role-appropriate ownership error. Only then are state-machine preconditions evaluated, then the standing and segregation-of-duties gates, then uniqueness and cap rules, then interval and overlap rules, then the usability of referenced actors, and finally — last, so that every cheaper rejection is detected before it — the aggregate fiscal gate on claim submission.

### 2.9. Nested and Referenced Resource Retrieval

Several endpoints address a child resource beneath its parent — for example a response, clarification thread, conversion, or claim beneath a consult. For any such path, the server validates the existence of each identifier sequentially from left to right and rejects the request with `ERR_NOT_FOUND` at the first identifier that does not correspond to an existing resource, before any business rule is evaluated. The same left-to-right discipline applies to resource ids referenced in the request body.

## 3. Business Logic & Workflows

### 3.1. Program Configuration: Tracks, Providers, Specialists, and the Panel

A `ProgramCoordinator` prepares the program before any consult can flow. The foundation is the **specialty track**, which couples a clinical specialty to its service targets and fee schedule. Creating a track takes a `specialty_code` — one of `CARDIOLOGY`, `ENDOCRINOLOGY`, `NEUROLOGY`, `DERMATOLOGY`, or `RHEUMATOLOGY`, unique across all tracks — together with `response_time_target_hours` for routine consults and `urgent_target_hours` for urgent ones. Both targets must be positive, and the urgent target must be strictly smaller than the routine target. The fee schedule comprises `base_response_fee_cents` paid for an answered response that does not convert, `conversion_response_fee_cents` paid when the disposition recommends an in-person visit, `clarification_fee_cents` paid per answered clarification round, and `late_penalty_cents` subtracted at finalization when the response was late; all four fees are non-negative integers. Finally, `monthly_billing_cap_cents` — a positive integer — caps the aggregate claims a track may carry per calendar month, a rule exercised in §3.9.

People are registered next. A referring provider is created with a `full_name` and an `npi` — a 10-digit national provider identifier, unique across referring providers — and a `status` that is `ACTIVE` by default and may later be `DEACTIVATED`. Specialists are registered the same way, with their own `full_name`, unique 10-digit `npi`, and the same `ACTIVE`-by-default `status` lifecycle.

Panel enrollment binds a specialist to a track. A `ProgramCoordinator` creates a **panel membership** by supplying `specialist_id` and `specialty_track_id`, optionally with `is_accepting` (which defaults to `true`). The specialist must be `ACTIVE` at enrollment; enrolling a `DEACTIVATED` specialist is rejected with `ERR_SPECIALIST_INACTIVE`. The pairing must be unique — the system records a `unique_membership` marker over the specialist-and-track pair, and a duplicate enrollment is rejected with `ERR_DUPLICATE_MEMBERSHIP`. A new membership starts in `GOOD_STANDING` with a `quality_score_bps` of 8500 and every counter zeroed: `reviews_count`, `reviews_score_sum`, `responded_count`, `on_time_count`, `rebuke_count`, `expired_count`, and `open_consult_count` all begin at zero, and `provisional_balance_cents` and `posted_balance_cents` begin at zero as well. The membership collection can be listed and filtered by `specialist_id`, `specialty_track_id`, or `standing`, and an individual membership read exposes the same counters and balances.

### 3.2. Availability Windows and the Routing Selector

A specialist declares when they are on call by creating **availability windows** against one of their own memberships, supplying `membership_id`, `window_start`, and `window_end`. Windows use half-open semantics: the window covers instants from `window_start` up to but not including `window_end`. The end must be strictly later than the start, or creation fails with `ERR_WINDOW_INVALID_RANGE`. Two windows belonging to the same membership may not overlap while both are `ACTIVE`: a new window conflicts with an existing `ACTIVE` window whenever the new window starts before the existing one ends and the existing one starts before the new one ends. Adjacency is not a conflict — a new window starting exactly when an existing one ends is allowed. A genuine overlap is rejected with `ERR_AVAILABILITY_WINDOW_OVERLAP`. A window is born `ACTIVE`; the specialist who owns the underlying membership may cancel it, moving it to `CANCELLED` — cancelling requires the window to still be `ACTIVE` (otherwise `ERR_WINDOW_NOT_ACTIVE`) and the caller to be the membership's specialist (otherwise `ERR_NOT_MEMBERSHIP_OWNER`). A membership whose standing is `SUSPENDED` may not create new windows at all; the attempt is rejected with `ERR_MEMBERSHIP_SUSPENDED`. The windows of a membership can be listed with an optional `status` filter.

Routing is deterministic and runs at two moments: immediately inside consult creation, and again when a coordinator re-routes a queued consult. The eligible pool for a consult is the set of panel memberships that satisfy all five of the following: the membership's track equals the consult's `specialty_track_id`; the membership's `standing` is `GOOD_STANDING`; the membership's `is_accepting` is true; the membership's `open_consult_count` is below the program-wide ceiling of 5 open consults; and the membership has at least one `ACTIVE` availability window covering the current logical instant under half-open semantics — the window's start is at or before now, and now is strictly before its end.

When the pool is non-empty, the selector ranks candidates by `open_consult_count` ascending, then by `quality_score_bps` descending, then by the membership's `created_at` ascending as the final deterministic tie-break; the membership `id` must never be consulted for ranking. The winning membership is recorded on the consult through `assigned_specialist_id` and `assigned_membership_id`, its `open_consult_count` increases by one (which refreshes the membership's `updated_at` and increments its `version`), and the consult lands in `ASSIGNED`. Every routing pass — successful or not — appends an immutable `RoutingDecision` audit row recording the `consult_id`, an `outcome` of `ASSIGNED` or `QUEUED`, the `candidate_count` (the size of the eligible pool at decision time), the `selected_membership_id` (null when queued), and a human-readable `ranking_basis` such as "open_consult_count ASC, quality_score_bps DESC, created_at ASC" — or, for cascade-driven re-queues, "SPECIALIST_SUSPENDED". When the pool is empty at creation, the consult instead lands in `QUEUED` with a decision row whose `candidate_count` is zero and whose `selected_membership_id` is null. A consult's routing history is readable through its decision listing.

### 3.3. Consult Submission, Amendment, Rerouting, and Cancellation

A `ReferringProvider` submits a consult by providing a `patient_ref` (a non-empty, de-identified patient reference), the target `specialty_track_id`, a `question_text` of at least 20 characters holding the structured clinical question, and a non-empty `icd10_primary` code. Optional `comorbidity_flags` default to an empty list, and `urgency` defaults to `ROUTINE` but may be set to `URGENT`. The submitting provider must be `ACTIVE`; a submission from a `DEACTIVATED` provider is rejected with `ERR_PROVIDER_INACTIVE`. At most one non-terminal consult may exist for a given patient within a given track: if a consult for the same `patient_ref` and `specialty_track_id` pair exists in any status other than `CLOSED`, `EXPIRED`, or `CANCELLED`, creation is rejected with `ERR_DUPLICATE_OPEN_CONSULT`. The new consult's `referring_provider_id` is taken from the caller's `X-User-ID`, its `billing_status` begins at `UNBILLABLE`, its `sla_breached` flag begins false, and the routing selector from §3.2 runs inline, landing the consult in `ASSIGNED` or `QUEUED` and incrementing its `version`. Consults can be listed with filters on `referring_provider_id`, `specialty_track_id`, `assigned_specialist_id`, `assigned_membership_id`, or `status`.

While a consult is still awaiting an answer, the owning provider may amend its structured question — `question_text`, `icd10_primary`, `comorbidity_flags`, and `urgency` may each be changed. The amendment is the first of the two OCC-guarded writes from §2.7: the request must carry `expected_consult_version`, and a version the client no longer holds is rejected with `ERR_STALE_CONSULT_VERSION`. Only the owning provider may amend; anyone else is rejected with `ERR_NOT_CONSULT_OWNER`. A successful amendment increments the consult's `version` and refreshes `updated_at`.

A consult stuck in `QUEUED` can be re-routed by a `ProgramCoordinator`. The re-route is the second OCC-guarded write: it requires `expected_consult_version` matching the consult's current `version`, with mismatch rejected as `ERR_STALE_CONSULT_VERSION`. The consult must actually be `QUEUED` — re-routing any other status is rejected with `ERR_CONSULT_NOT_QUEUED` — and the selector must find a non-empty pool, or the attempt fails with `ERR_NO_ELIGIBLE_SPECIALIST`. A successful re-route applies the full assignment side effects of §3.2: selection, assignment fields, the decision row, and the winner's `open_consult_count` increasing by one, with the consult's `version` incremented.

Cancellation is the owning provider's escape hatch before an answer exists, and its effects depend on where the consult sits. Cancelling a consult in `ASSIGNED` or `CLARIFICATION_REQUESTED` decrements the holding membership's `open_consult_count` by one and reverses every `PROVISIONAL` compensation entry for the consult — from `CLARIFICATION_REQUESTED` this includes any `CLARIFICATION_FEE` rows — reducing `provisional_balance_cents` accordingly. Cancelling from `SUBMITTED` or `QUEUED` touches no membership and no ledger rows. In all four cases the consult becomes `CANCELLED`, its `billing_status` moves from `UNBILLABLE` to `VOID`, and its `version` increments. Cancellation is not available once a consult is `ANSWERED` or in any terminal state; such attempts are rejected with `ERR_CONSULT_ALREADY_TERMINAL`, as is any cancellation by a non-owner with `ERR_NOT_CONSULT_OWNER`.

The expiry sweep of §2.5 produces the same kind of teardown without any client action. When the logical clock passes a consult's `sla_due_at` by more than the 24-hour grace period while the consult is `ASSIGNED` or `CLARIFICATION_REQUESTED`, the consult transitions to `EXPIRED`, its `sla_breached` flag is set to true, the membership's `expired_count` increases by one and its `open_consult_count` decreases by one, and the `billing_status` moves from `UNBILLABLE` to `VOID`. Expiry from `CLARIFICATION_REQUESTED` additionally reverses every `PROVISIONAL` entry for the consult. A consult that sits in `QUEUED` until the logical clock is strictly more than 72 hours past its creation expires the same way, voiding billing, though no membership counters move because none was ever assigned. Each expiry increments the consult's `version`.

### 3.4. The Clarification Cycle

An assigned specialist who needs more information asks for it by posting a clarification message with a non-empty `body`. The consult must be `ASSIGNED` — otherwise `ERR_CONSULT_NOT_ASSIGNED` — and the caller must be the specialist named in `assigned_specialist_id`, or the attempt is rejected with `ERR_NOT_ASSIGNED_SPECIALIST`. The program allows at most 2 specialist-initiated clarification rounds per consult; when `clarification_rounds` has already reached that ceiling, the request is rejected with `ERR_MAX_CLARIFICATION_ROUNDS_REACHED`. A successful request appends a `ClarificationMessage` whose `author_role` is `SPECIALIST` and whose `sequence_no` is one greater than the count of prior messages on the consult, increments `clarification_rounds`, moves the consult from `ASSIGNED` to `CLARIFICATION_REQUESTED`, and increments the consult's `version`.

The owning provider answers by posting a clarification message of their own, again with a non-empty `body`. This reply requires the consult to be `CLARIFICATION_REQUESTED` (otherwise `ERR_CONSULT_NOT_AWAITING_CLARIFICATION`) and the caller to be the consult's owner (otherwise `ERR_NOT_CONSULT_OWNER`). The reply appends a message with `author_role` set to `REFERRING_PROVIDER` and the next `sequence_no`, moves the consult back from `CLARIFICATION_REQUESTED` to `ASSIGNED`, and — because answering a clarification is compensable work — appends a `CLARIFICATION_FEE` compensation entry at the track's `clarification_fee_cents` with posture `PROVISIONAL`, adding the same amount to the membership's `provisional_balance_cents`. The consult's `version` increments. A clarification fee entry's amount never changes; at response finalization its posture simply flips from `PROVISIONAL` to `POSTED`. The full thread of a consult's clarification messages is listable in `created_at` order.

### 3.5. Response Submission and SLA Accounting

The central deliverable is the specialist's response, submitted with a `disposition` — one of `MANAGE_IN_PRIMARY_CARE`, `MANAGE_WITH_PLAN`, or `CONVERT_TO_VISIT` — and a `recommendation_text` of at least 20 characters. Submission requires the consult to be `ASSIGNED`: a consult in any other non-terminal state yields `ERR_CONSULT_NOT_ASSIGNED`, and a terminal consult yields `ERR_CONSULT_ALREADY_TERMINAL`. The caller must be the assigned specialist (`ERR_NOT_ASSIGNED_SPECIALIST`), and the assigned membership must not be `SUSPENDED` — a suspended specialist cannot submit responses and is turned away with `ERR_MEMBERSHIP_SUSPENDED`. Because submission requires `ASSIGNED` and the consult leaves `ASSIGNED` the moment the response is created, a consult accepts exactly one response.

The response's timeliness is judged against the consult's `sla_due_at`, which the routing pass computed at assignment time as the consult's `created_at` plus the track's `urgent_target_hours` when the consult's `urgency` is `URGENT`, or plus the track's `response_time_target_hours` when it is `ROUTINE`. A response created at or before `sla_due_at` — the boundary is inclusive — is recorded with `on_time` true; anything later is late. The response also records `response_minutes`, the whole minutes elapsed from the consult's creation to the response's creation. When a late response arrives, the consult's `sla_breached` flag is set true at that moment.

Three snapshots are frozen onto the response at submission and never recomputed afterward: `on_time`, `response_minutes`, and `review_required`. The last of these flags the response for mandatory quality review when, at submission time, the membership's `standing` is `PROBATION`, or the `disposition` is `CONVERT_TO_VISIT`, or the response was not on time. The response is born in `SUBMITTED` status with `revision_count` zero, `last_submitted_at` marking the submission instant, and both documentation flags — `pcp_note_documented` and `specialist_note_documented`, and therefore `documentation_complete` — initially false.

Submission moves money and counters. A `RESPONSE_FEE` compensation entry is appended at the provisional base: the track's `conversion_response_fee_cents` when the disposition is `CONVERT_TO_VISIT`, otherwise the track's `base_response_fee_cents` — no quality multiplier and no late penalty apply at this stage. The membership's `provisional_balance_cents` grows by that provisional amount, `responded_count` increases by one, `on_time_count` increases by one when the response was on time, and `open_consult_count` decreases by one. The consult itself moves from `ASSIGNED` to `ANSWERED`, its `billing_status` moves from `UNBILLABLE` to `PENDING_DOCUMENTATION`, and its `version` increments. Finally, the membership's blended quality score is recomputed as described in §3.7, which may immediately drive a standing transition. A consult's responses are listable beneath the consult, and a specialist's authored responses are listable beneath the specialist.

### 3.6. Dual-Record Documentation, Finalization, and Compensation Posting

An answered consult is not billable until its response is finalized, and finalization is gated on documentation written into both clinical records. Each side of the documentation is marked through a single capability that takes a `record_type`: marking the `PCP_NOTE` side is the owning referring provider's act and sets `pcp_note_documented`, while marking the `SPECIALIST_NOTE` side is the responding specialist's act and sets `specialist_note_documented`. The response must still be `SUBMITTED` for either marking, otherwise `ERR_RESPONSE_NOT_SUBMITTED`; the wrong actor for a side is rejected with the matching ownership error. Whenever either flag changes, `documentation_complete` is recomputed as the conjunction of the two flags — both notes written, and only then, make it true.

Finalization is the responding specialist's act and carries four preconditions, evaluated in the order of §2.8. The response must be `SUBMITTED` (`ERR_RESPONSE_NOT_SUBMITTED`); the caller must be the responder (`ERR_NOT_ASSIGNED_SPECIALIST`); `documentation_complete` must be true (`ERR_DOCUMENTATION_INCOMPLETE`); and when `review_required` was snapshotted true, there must exist a `COMPLETED` quality review with verdict `PASS` whose `created_at` is at or after the response's `last_submitted_at` — a review predating the latest submission does not count — with failure rejected as `ERR_REVIEW_REQUIRED_NOT_PASSED`.

Finalizing posts the money. The consult's `RESPONSE_FEE` entry flips from `PROVISIONAL` to `POSTED`, and its `amount_cents` is recomputed at the final variant: start from the same disposition base used provisionally, apply the quality band read from the membership's `quality_score_bps` **at finalize time** — a score of 9000 or above multiplies the base by 1.20; 7500 through 8999 multiplies it by 1.00; 5000 through 7499 by 0.80; below 5000 by 0.50 — and round the product half up to whole cents. From that gross, subtract the track's `late_penalty_cents` when the response's `on_time` is false (nothing otherwise), and floor the result at zero so a penalty can never make a payment negative. Every `CLARIFICATION_FEE` entry for the consult flips from `PROVISIONAL` to `POSTED` with its amount unchanged. On the membership, `provisional_balance_cents` is reduced by the prior provisional amounts and `posted_balance_cents` grows by the freshly posted amounts. Because the posted response fee reflects the quality band and lateness, identical response data can legitimately yield a posted amount different from the provisional one. The consult's `billing_status` moves from `PENDING_DOCUMENTATION` to `CHARGEABLE`.

Only after finalization may the owning provider close the consult, moving it from `ANSWERED` to `CLOSED`. Closing requires the consult to be `ANSWERED` (`ERR_CONSULT_NOT_ANSWERED`), the caller to be the owner (`ERR_NOT_CONSULT_OWNER`), and — a cross-entity dependency — the consult's response to be `FINALIZED` (`ERR_RESPONSE_NOT_FINALIZED`). A successful close increments the consult's `version`.

The ledger itself is readable: compensation entries can be listed with filters on `membership_id`, `consult_id`, or `posture`, and fetched individually. A computed summary read on any membership returns its `provisional_balance_cents`, `posted_balance_cents`, the `reversed_total_cents` accumulated across reversed entries, and its current `open_consult_count`.

### 3.7. Quality Review, Rebuke, and Panel Standing

Quality oversight begins when a `QualityReviewer` opens a review on a response by its `response_id`. The response must be `SUBMITTED` (`ERR_RESPONSE_NOT_SUBMITTED`), and the reviewer — whose `reviewer_specialist_id` is set from the caller's `X-User-ID` — must not be the specialist who wrote the response; that segregation-of-duties violation is rejected with `ERR_REVIEWER_IS_RESPONDER` (HTTP 403). The review is born `PENDING`. Reviews can be listed with filters on `response_id` or `reviewer_specialist_id`.

Completing a review is the assigned reviewer's act and requires the review to be `PENDING` (`ERR_REVIEW_NOT_PENDING`) and the caller to be that reviewer (`ERR_NOT_REVIEW_OWNER`). The reviewer supplies three scores — `timeliness_score`, `appropriateness_score`, and `clarity_score`, each an integer from 1 to 5 (anything outside that range is `ERR_INVALID_REQUEST`) — and a `verdict` of `PASS` or `REBUKE`. The system computes `composite_score_bps` as fifty times the appropriateness score plus twenty-five times the timeliness score plus twenty-five times the clarity score, the total divided by five, rounded half up, then multiplied by one hundred, yielding a basis-point score between 1000 and 10000. The verdict must agree with the computed band: a composite of 6000 or more requires `PASS`, and below 6000 requires `REBUKE`; a verdict that contradicts its band is rejected with `ERR_VERDICT_SCORE_MISMATCH` (HTTP 422).

A completed review feeds the membership's quality record: `reviews_count` increases by one and `reviews_score_sum` grows by the composite. When the verdict is `REBUKE`, the consequences cascade. The response itself moves from `SUBMITTED` to `REBUKED`; every `PROVISIONAL` compensation entry for the consult — the response fee and any clarification fees — is `REVERSED`, shrinking `provisional_balance_cents`; and the membership's `rebuke_count` increases by one.

A rebuke is not the end of the response. The responding specialist may revise a `REBUKED` response — attempting it in any other status yields `ERR_RESPONSE_NOT_REBUKED`, and a non-responder yields `ERR_NOT_ASSIGNED_SPECIALIST`. Revision replaces `recommendation_text` and, when provided, `disposition`; it increments `revision_count`, stamps `last_submitted_at` with the current instant, and resets both documentation flags — `pcp_note_documented`, `specialist_note_documented`, and therefore `documentation_complete` — to false, so both records must be documented again. A fresh `PROVISIONAL` `RESPONSE_FEE` entry is appended at the provisional disposition base, adding to `provisional_balance_cents`, and the response returns to `SUBMITTED`. The consult remains `ANSWERED` and its `billing_status` remains `PENDING_DOCUMENTATION` throughout. Because `review_required` was frozen at the original submission and the finalize gate compares review timestamps against `last_submitted_at`, a response that required review before revision requires a fresh passing review after it.

After every response submission and every completed review, the membership's blended `quality_score_bps` is recomputed from its persisted counters, applied after the triggering mutation has landed, in a pinned order. First the triggering mutation's counter updates are applied. Then the timeliness component is computed: when `responded_count` is zero it defaults to 10000, otherwise it is 10000 times `on_time_count` divided by `responded_count`, rounded half up. The review component follows: when `reviews_count` is zero it defaults to 8500, otherwise it is `reviews_score_sum` divided by `reviews_count`, rounded half up. The blended score is six times the review component plus four times the timeliness component, the sum divided by ten, rounded half up. Standing thresholds are then evaluated exactly once, in this order, against the membership's current standing. A membership in `GOOD_STANDING` drops to `SUSPENDED` when its score falls below 5000, and otherwise drops to `PROBATION` when its score falls below 7000. A membership in `PROBATION` drops to `SUSPENDED` when its score falls below 5000 or its `rebuke_count` reaches 2, and otherwise recovers to `GOOD_STANDING` when its score reaches 7500 or higher. A `SUSPENDED` membership never transitions automatically.

Suspension is operationally severe by design. The moment a membership enters `SUSPENDED`, its `is_accepting` flips to false, and every consult currently `ASSIGNED` or `CLARIFICATION_REQUESTED` to that membership is re-queued: each such consult's `assigned_specialist_id` and `assigned_membership_id` are cleared to null, its `open_consult_count` contribution is decremented, and a `RoutingDecision` with outcome `QUEUED` and `ranking_basis` "SPECIALIST_SUSPENDED" is appended per consult. There is no automatic path back: only a `ProgramCoordinator` may reinstate a membership, moving it from `SUSPENDED` to `PROBATION` and restoring `is_accepting` to true; reinstatement attempted on a membership that is not `SUSPENDED` is rejected with `ERR_MEMBERSHIP_NOT_SUSPENDED`. A reinstated membership starts climbing again from `PROBATION`, where a score of 7500 or higher at the next recompute restores `GOOD_STANDING`.

### 3.8. In-Person Conversion and Scheduling

When a specialist concludes the question cannot be answered asynchronously, the response's `CONVERT_TO_VISIT` disposition opens the path to a scheduled appointment. The responding specialist creates the conversion against the consult by supplying `appointment_start` and `appointment_end`; the start is inclusive and the end exclusive. The consult must be `ANSWERED` (`ERR_CONSULT_NOT_ANSWERED`), the response's disposition must be `CONVERT_TO_VISIT` (`ERR_DISPOSITION_NOT_CONVERSION`), and the consult must not already have a conversion — at most one conversion exists per consult, and a duplicate is rejected with `ERR_CONVERSION_ALREADY_EXISTS`. The end must be strictly later than the start, or creation fails with `ERR_WINDOW_INVALID_RANGE`. The converting specialist is recorded from the caller's identity, and the conversion is born `SCHEDULED`.

Scheduling respects the specialist's existing appointment book with a buffer rule. Each scheduled appointment effectively occupies its interval plus a 30-minute buffer on each side, and a new conversion conflicts with an existing `SCHEDULED` conversion of the same specialist whenever the new appointment starts before the existing appointment's buffered end — its end plus 30 minutes — and the existing appointment starts before the new appointment's buffered end. Because both comparisons are strict, a gap of exactly 30 minutes between one appointment's end and the next one's start does not conflict. A conflicting proposal is rejected with `ERR_APPOINTMENT_WINDOW_OVERLAP`.

The conversion's lifecycle is simple. The specialist who created it marks it completed, moving `SCHEDULED` to `COMPLETED`; either that specialist or the owning referring provider may instead cancel it, moving `SCHEDULED` to `CANCELLED`. Both acts require the conversion to still be `SCHEDULED` (`ERR_CONVERSION_NOT_SCHEDULED`) and enforce the matching ownership — a specialist who is not the converter is rejected with `ERR_NOT_ASSIGNED_SPECIALIST`, a provider who does not own the consult with `ERR_NOT_CONSULT_OWNER`. Conversions can be listed with filters on `consult_id`, `specialist_id`, or `status`.

### 3.9. Billing Claims and Program Measurement

Billing is a world apart from the clinical roles: every claim operation belongs to the `BillingClerk`. A claim is drafted against an answered consult — the consult must be `ANSWERED` (`ERR_CONSULT_NOT_ANSWERED`) and must not already have a claim, since at most one claim exists per consult (`ERR_CLAIM_ALREADY_EXISTS`). Creation computes the claim's two derived fields and leaves it in `DRAFT`. The `period_key` is the calendar month of the claim's creation in `YYYY-MM` form and is the accounting period for the track cap. The `claim_code` is the string "ECONSULT-" followed by "URG" when the consult's `urgency` is `URGENT` (otherwise "RUT"), a hyphen, and "CONV" when the response's disposition is `CONVERT_TO_VISIT` (otherwise "ANSW").

The claim's `amount_cents` is computed in a pinned rounding order that implementers must follow exactly. First the professional component: the track's `base_response_fee_cents` multiplied by an urgency factor — 1.5 when the consult is `URGENT`, 1.0 when `ROUTINE` — rounded half up to whole cents. Only then is the documentation add-on computed, and it is derived from the **rounded** professional component: ten percent of it when a conversion in `SCHEDULED` or `COMPLETED` status exists for the consult, five percent otherwise, itself rounded half up to whole cents. The claim amount is the sum of the rounded component and the rounded add-on. Deriving the add-on from the unrounded component and rounding once at the end yields a different cent value and is non-conformant.

Submitting a draft claim is where the program's fiscal gate bites, and it is evaluated last per §2.8. The claim must be `DRAFT` (`ERR_CLAIM_INVALID_STATE`), and the consult's `billing_status` must be `CHARGEABLE` (`ERR_CONSULT_NOT_CHARGEABLE`) — which, per §3.6, means the response is finalized. The monthly cap check then sums the `amount_cents` of every claim belonging to the same track — claims are attributed to a track through their consult — whose `status` is `SUBMITTED` or `PAID` and whose `period_key` matches the new claim's, and rejects the submission with `ERR_TRACK_BILLING_CAP_EXCEEDED` (HTTP 402) when that consumed total plus the new claim's amount would exceed the track's `monthly_billing_cap_cents`. Reaching the cap exactly is allowed; only a strictly greater total is rejected. A successful submission moves the claim to `SUBMITTED` and advances the consult's `billing_status` from `CHARGEABLE` to `CLAIMED`. From `SUBMITTED`, the clerk either marks the claim `PAID` or denies it; denial moves it to `DENIED`. Writing off a denied claim moves it to `VOID` and drops the consult's `billing_status` from `CLAIMED` to `VOID`. Every transition attempted from the wrong claim status is rejected with `ERR_CLAIM_INVALID_STATE`. A consult's claims are listable beneath the consult, and claims are individually readable.

The program closes the loop with **avoided-visit measurement**, the metric that justifies the service. A `ProgramCoordinator` creates a measurement by naming a `specialty_track_id` and a `period_key` in `YYYY-MM` form; only one measurement may exist per track and period, with duplicates rejected as `ERR_MEASUREMENT_ALREADY_EXISTS`. At creation the system computes two variants over the consults of that track whose `created_at` falls within the calendar month — the half-open interval from the first instant of the month up to but not including the first instant of the next. Within that population, `responded_count` counts consults whose `status` is `ANSWERED` or `CLOSED`, and `conversions_count` counts those among them that have a conversion in `SCHEDULED` or `COMPLETED` status. The attributed variant, `avoided_attributed_count`, is simply `responded_count` minus `conversions_count` — every responded consult counts as avoided unless a live conversion exists. The conservative variant, `avoided_conservative_count`, counts only consults that are `CLOSED`, whose response's disposition is `MANAGE_IN_PRIMARY_CARE`, and for which no conversion exists in any status; identical data always yields a conservative number no larger than the attributed one. The measurement is born `OPEN` and both variants are recomputed and frozen when the coordinator finalizes it, moving it to `FINALIZED`; finalizing an already-final measurement is rejected with `ERR_MEASUREMENT_ALREADY_FINALIZED`. Measurements can be listed with filters on `specialty_track_id` or `period_key`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource return `200 OK`. The table below summarizes the HTTP contract only — request payloads, response bodies, and side effects are defined by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/econsult/_clock/set_current_utc` | Set the logical clock; runs the expiry sweep | ProgramCoordinator |
| POST | `/econsult/specialty-tracks` | Create a specialty track (routing & fee configuration) | ProgramCoordinator |
| GET | `/econsult/specialty-tracks/{id}` | Get a specialty track | Any declared role |
| POST | `/econsult/referring-providers` | Register a referring provider | ProgramCoordinator |
| GET | `/econsult/referring-providers/{id}` | Get a referring provider | Any declared role |
| POST | `/econsult/specialists` | Register a specialist | ProgramCoordinator |
| GET | `/econsult/specialists/{id}` | Get a specialist | Any declared role |
| GET | `/econsult/specialists/{id}/consult-responses` | List responses authored by a specialist | Any declared role |
| POST | `/econsult/panel-memberships` | Enroll a specialist on a specialty track panel | ProgramCoordinator |
| GET | `/econsult/panel-memberships` | List panel memberships with filters | Any declared role |
| GET | `/econsult/panel-memberships/{id}` | Get a panel membership | Any declared role |
| POST | `/econsult/panel-memberships/{id}/reinstate` | Reinstate a SUSPENDED membership to PROBATION | ProgramCoordinator |
| GET | `/econsult/panel-memberships/{id}/compensation-summary` | Computed read of provisional vs posted compensation totals | ProgramCoordinator, Specialist, BillingClerk |
| GET | `/econsult/panel-memberships/{id}/availability-windows` | List availability windows of a membership | Any declared role |
| POST | `/econsult/specialist-availability-windows` | Create an on-call availability window | Specialist |
| POST | `/econsult/specialist-availability-windows/{id}/cancel` | Cancel an ACTIVE availability window | Specialist |
| POST | `/econsult/consult-requests` | Submit a structured asynchronous consult; routing runs inline | ReferringProvider |
| GET | `/econsult/consult-requests` | List consult requests with filters | Any declared role |
| GET | `/econsult/consult-requests/{id}` | Get a consult request | Any declared role |
| PATCH | `/econsult/consult-requests/{id}` | Amend the structured question pre-answer (OCC-guarded) | ReferringProvider |
| POST | `/econsult/consult-requests/{id}/reroute` | Re-run the routing selector for a QUEUED consult (OCC-guarded) | ProgramCoordinator |
| POST | `/econsult/consult-requests/{id}/cancel` | Cancel a pre-answer consult | ReferringProvider |
| POST | `/econsult/consult-requests/{id}/close` | Close an answered consult (requires FINALIZED response) | ReferringProvider |
| POST | `/econsult/consult-requests/{id}/clarifications` | Post a clarification message (specialist request or provider reply) | ReferringProvider, Specialist |
| GET | `/econsult/consult-requests/{id}/clarifications` | List clarification messages of a consult | Any declared role |
| GET | `/econsult/consult-requests/{id}/routing-decisions` | List routing decisions of a consult | Any declared role |
| POST | `/econsult/consult-requests/{id}/responses` | Submit the specialist response (drives ASSIGNED to ANSWERED) | Specialist |
| GET | `/econsult/consult-requests/{id}/responses` | List responses of a consult | Any declared role |
| GET | `/econsult/consult-responses/{id}` | Get a consult response | Any declared role |
| POST | `/econsult/consult-responses/{id}/documentation` | Mark one side of the dual-record documentation complete | ReferringProvider, Specialist |
| POST | `/econsult/consult-responses/{id}/finalize` | Finalize a fully documented response (posts compensation) | Specialist |
| POST | `/econsult/consult-responses/{id}/revise` | Revise a REBUKED response (documentation flags reset) | Specialist |
| POST | `/econsult/quality-reviews` | Open a quality review on a SUBMITTED response | QualityReviewer |
| POST | `/econsult/quality-reviews/{id}/complete` | Complete a review with scores and band-consistent verdict | QualityReviewer |
| GET | `/econsult/quality-reviews` | List quality reviews with filters | Any declared role |
| GET | `/econsult/quality-reviews/{id}` | Get a quality review | Any declared role |
| POST | `/econsult/consult-requests/{id}/conversions` | Convert an answered consult to an in-person visit | Specialist |
| POST | `/econsult/in-person-conversions/{id}/complete` | Mark a scheduled conversion completed | Specialist |
| POST | `/econsult/in-person-conversions/{id}/cancel` | Cancel a scheduled conversion | Specialist, ReferringProvider |
| GET | `/econsult/in-person-conversions` | List conversions with filters | Any declared role |
| GET | `/econsult/in-person-conversions/{id}` | Get a conversion | Any declared role |
| POST | `/econsult/consult-requests/{id}/billing-claims` | Create a DRAFT billing claim for an answered consult | BillingClerk |
| GET | `/econsult/consult-requests/{id}/billing-claims` | List claims of a consult | Any declared role |
| GET | `/econsult/billing-claims/{id}` | Get a billing claim | Any declared role |
| POST | `/econsult/billing-claims/{id}/submit` | Submit a DRAFT claim (monthly cap enforced) | BillingClerk |
| POST | `/econsult/billing-claims/{id}/mark-paid` | Mark a submitted claim paid | BillingClerk |
| POST | `/econsult/billing-claims/{id}/deny` | Deny a submitted claim | BillingClerk |
| POST | `/econsult/billing-claims/{id}/write-off` | Write off a denied claim (voids consult billing) | BillingClerk |
| GET | `/econsult/compensation-entries` | List compensation ledger entries with filters | ProgramCoordinator, Specialist, BillingClerk |
| GET | `/econsult/compensation-entries/{id}` | Get a compensation entry | ProgramCoordinator, Specialist, BillingClerk |
| POST | `/econsult/avoided-visit-measurements` | Create an OPEN measurement for a track and period | ProgramCoordinator |
| POST | `/econsult/avoided-visit-measurements/{id}/finalize` | Finalize a measurement (recompute and freeze both variants) | ProgramCoordinator |
| GET | `/econsult/avoided-visit-measurements` | List measurements with filters | Any declared role |
| GET | `/econsult/avoided-visit-measurements/{id}` | Get a measurement | Any declared role |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_CONSULT_VERSION` | 412 Precondition Failed |
| `ERR_NOT_CONSULT_OWNER` | 403 Forbidden |
| `ERR_NOT_ASSIGNED_SPECIALIST` | 403 Forbidden |
| `ERR_NOT_MEMBERSHIP_OWNER` | 403 Forbidden |
| `ERR_NOT_REVIEW_OWNER` | 403 Forbidden |
| `ERR_CONSULT_NOT_QUEUED` | 409 Conflict |
| `ERR_NO_ELIGIBLE_SPECIALIST` | 409 Conflict |
| `ERR_CONSULT_NOT_ASSIGNED` | 409 Conflict |
| `ERR_CONSULT_NOT_AWAITING_CLARIFICATION` | 409 Conflict |
| `ERR_CONSULT_NOT_ANSWERED` | 409 Conflict |
| `ERR_CONSULT_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_RESPONSE_NOT_SUBMITTED` | 409 Conflict |
| `ERR_RESPONSE_NOT_REBUKED` | 409 Conflict |
| `ERR_RESPONSE_NOT_FINALIZED` | 409 Conflict |
| `ERR_REVIEW_NOT_PENDING` | 409 Conflict |
| `ERR_CONVERSION_NOT_SCHEDULED` | 409 Conflict |
| `ERR_CLAIM_INVALID_STATE` | 409 Conflict |
| `ERR_MEASUREMENT_ALREADY_FINALIZED` | 409 Conflict |
| `ERR_WINDOW_NOT_ACTIVE` | 409 Conflict |
| `ERR_MEMBERSHIP_NOT_SUSPENDED` | 409 Conflict |
| `ERR_CONSULT_NOT_CHARGEABLE` | 409 Conflict |
| `ERR_DOCUMENTATION_INCOMPLETE` | 409 Conflict |
| `ERR_REVIEW_REQUIRED_NOT_PASSED` | 409 Conflict |
| `ERR_MEMBERSHIP_SUSPENDED` | 403 Forbidden |
| `ERR_REVIEWER_IS_RESPONDER` | 403 Forbidden |
| `ERR_DUPLICATE_OPEN_CONSULT` | 409 Conflict |
| `ERR_DUPLICATE_MEMBERSHIP` | 409 Conflict |
| `ERR_CONVERSION_ALREADY_EXISTS` | 409 Conflict |
| `ERR_CLAIM_ALREADY_EXISTS` | 409 Conflict |
| `ERR_MEASUREMENT_ALREADY_EXISTS` | 409 Conflict |
| `ERR_MAX_CLARIFICATION_ROUNDS_REACHED` | 409 Conflict |
| `ERR_VERDICT_SCORE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_DISPOSITION_NOT_CONVERSION` | 409 Conflict |
| `ERR_WINDOW_INVALID_RANGE` | 422 Unprocessable Entity |
| `ERR_AVAILABILITY_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_APPOINTMENT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_PROVIDER_INACTIVE` | 409 Conflict |
| `ERR_SPECIALIST_INACTIVE` | 409 Conflict |
| `ERR_TRACK_BILLING_CAP_EXCEEDED` | 402 Payment Required |
