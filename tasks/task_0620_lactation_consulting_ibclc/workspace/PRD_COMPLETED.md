# Lactation Consulting & Breastfeeding Support (IBCLC) API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Lactation Consulting & Breastfeeding Support API, the operational backbone of an IBCLC (International Board Certified Lactation Consultant) practice. The system coordinates the full arc of breastfeeding care: scheduling prenatal, in-home, and telehealth consults; capturing intake feeding assessments; producing follow-up plans with weighted-feed tracking; generating superbills and reconciling insurance reimbursement (including the ACA preventive lactation benefit); qualifying clients for breast-pump durable medical equipment (DME); routing pediatrician referrals; and applying package credits and income-based sliding-scale pricing.

The practice is a busy place where four kinds of staff act on overlapping records, and the API exists to keep their work consistent. A front-desk clerk books and rearranges appointments and records no-shows; an IBCLC consultant runs the clinical visit and its downstream paperwork; a billing specialist drives the revenue cycle from draft superbill through insurer adjudication and reimbursement; and a practice administrator configures the catalog of tiers, packages, and consultants. Clients themselves get a narrow self-service read window into their own care. Because several of these actors can touch the same client, consult, or ledger at once, the system treats consistency as a first-class concern: scheduling conflicts, package-credit accounting, no-show suspensions, and reimbursement reversals must all behave deterministically regardless of who acted or in what order.

A handful of cross-cutting mechanics recur throughout the system and are worth naming up front: a per-practice logical clock that governs all time comparisons, a cascading no-show suspension that can auto-cancel a client's remaining appointments, a dual-variant fee calculation that branches on self-pay versus package redemption, an insurance reimbursement calculation that branches on ACA-preventive coverage, and an optimistic-concurrency guard protecting the client reimbursement ledger from stale reversals.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares the operational capacity under which they are acting. If either header is missing or malformed, the request is rejected with `ERR_MISSING_AUTH_CONTEXT`. A header counts as malformed when it is absent, empty, or whitespace-only, and additionally `X-User-Role` is malformed when its value is not one of the five recognized role strings; an unrecognized role therefore yields `ERR_MISSING_AUTH_CONTEXT` rather than `ERR_FORBIDDEN_ROLE`. When the headers are well-formed but the declared (recognized) role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes five roles, spelled exactly as follows: `PracticeAdmin`, `FrontDesk`, `Consultant`, `BillingSpecialist`, and `Client`.

The meaning of `X-User-ID` depends on the role:

- When `X-User-Role` is `PracticeAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it but does not compare it to any entity's `id`.
- When `X-User-Role` is `FrontDesk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it but does not compare it to any entity's `id`.
- When `X-User-Role` is `BillingSpecialist`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it but does not compare it to any entity's `id`.
- When `X-User-Role` is `Consultant`, `X-User-ID` is the `id` of the acting `Consultant`; ownership checks on any resource that references a `Consultant` compare the resource's consultant foreign-key field to `X-User-ID`.
- When `X-User-Role` is `Client`, `X-User-ID` is the `id` of the acting `Client`; ownership checks on any resource that references a `Client` compare the resource's client foreign-key field to `X-User-ID`.

Roles divide the work along clear lines. A `PracticeAdmin` configures the practice — creating practices, setting the logical clock, and defining sliding-scale tiers, service packages, and consultants — and additionally shares the scheduling-desk operations with `FrontDesk`. A `FrontDesk` clerk registers clients and books, reschedules, cancels, and records no-shows for consults. A `Consultant` owns the clinical lifecycle: starting and completing consults, recording feeding assessments, opening and closing follow-up plans, recording weighted feeds, and creating, acknowledging, and cancelling pediatrician referrals; a consultant may also request a DME qualification. A `BillingSpecialist` owns the revenue cycle: drafting, submitting, adjudicating, and voiding superbills, adjudicating DME qualifications, and (sharing with consultants) requesting DME qualifications. A `Client` has read-only access to their own practice, clients record, consults, follow-up plans, weighted feeds, superbills, DME qualifications, and pediatrician referrals. The authoritative method/path/role mapping appears in §4.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0. Out-of-range numeric values are clamped to the nearest bound rather than rejected — a `limit` below 1 becomes 1, a `limit` above 100 becomes 100, and a negative `offset` becomes 0 — while a `limit` or `offset` that is not a valid integer is rejected with `ERR_INVALID_REQUEST`.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

List-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Time Handling

Every `Practice` carries its own logical clock, exposed on the practice as `now_utc`. This clock — never the server's real wall-clock — is the single source of truth for every time comparison the system makes, including whether a consult may be started or marked a no-show and how an infant's age is computed for DME qualification. A freshly created practice begins with `now_utc` fixed at `2026-01-01T00:00:00Z`, and it stays at that default until explicitly advanced.

An administrator-only test-driving capability sets the clock to a supplied instant. The request names the target practice via `practice_id`, which must resolve to an existing practice (otherwise `ERR_RESOURCE_NOT_FOUND`), and supplies the new clock value as `to_iso8601`, which must be a well-formed ISO 8601 timestamp (otherwise `ERR_INVALID_REQUEST`); the practice's `now_utc` is set to that value and the updated practice is returned. Setting the clock is a mutation of the practice, so it refreshes the practice's `updated_at` and increments its `version`. All timestamps throughout the system are ISO 8601 in UTC.

### 2.5. Common Resource Properties

Most resources are "full" resources and carry a standard set of system-managed fields:

- `id` — a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits indicating when the resource was first created.
- `updated_at` — an ISO 8601 UTC timestamp indicating when the resource was last modified; refreshed on every mutation.
- `version` — a system-managed integer that starts at `1` on the resource's creation and increments by one on every mutation. It is the basis for optimistic concurrency control (§2.9).

The full resources are `Practice`, `SlidingScaleTier`, `ServicePackage`, `Consultant`, `Client`, `Consult`, `FollowUpPlan`, `Superbill`, `DMEQualification`, and `PediatricianReferral`.

Two resources are lightweight records that are immutable after creation: `FeedingAssessment` and `WeightedFeed`. These carry only `id` and `created_at`; they have neither an `updated_at` field nor a `version` field. Whenever a derived field on a full resource changes — for example a client's credit balances, a follow-up plan's rollups, or a client's reimbursement ledger — that change is itself a mutation that refreshes the resource's `updated_at` and increments its `version`.

### 2.6. Nested Identifier Resolution and Reference Integrity

The topology is flat: peer resources live at top-level collection paths, and a child is discovered through a filtered list query rather than a deeply nested URL. The filter is supplied as an optional query parameter whose name matches the foreign-key field, and each list endpoint honours exactly the foreign keys present on its resource: sliding-scale-tier, service-package, and consultant lists filter on `practice_id`; the client list filters on `practice_id` and `package_id`; the consult list filters on `practice_id`, `client_id`, and `consultant_id`; the feeding-assessment list filters on `consult_id`; the follow-up-plan, superbill, DME-qualification, and pediatrician-referral lists each filter on `consult_id` and `client_id`; and the weighted-feed list filters on `follow_up_plan_id`. An unrecognized or omitted filter parameter is simply ignored, returning the unfiltered collection. Where a path does carry a resource identifier, the system resolves it before doing any work; if that identifier does not name an existing resource the request is rejected with `ERR_RESOURCE_NOT_FOUND`. When a path carries more than one identifier, they are validated left to right, and the first one that does not resolve produces the rejection.

Foreign-key references supplied in a request body are validated separately. On client registration, consult scheduling, superbill drafting, DME-qualification requests, follow-up-plan creation, weighted-feed recording, and pediatrician-referral creation, every referenced foreign-key id in the body — among them `client_id`, `consultant_id`, `consult_id`, `package_id`, and `follow_up_plan_id` — must name an existing resource, or the request is rejected with `ERR_REFERENCED_RESOURCE_NOT_FOUND`.

### 2.7. Validation Ordering

When several checks could fail on a single request, they are evaluated in a fixed priority order so that the returned error is deterministic. The order is:

1. Authentication — `X-User-ID` and `X-User-Role` present and well-formed, else `ERR_MISSING_AUTH_CONTEXT`.
2. Authorization — the role is permitted for this operation per §2.1 and §4, else `ERR_FORBIDDEN_ROLE`.
3. Path existence — every resource id named in the path exists (validated left to right), else `ERR_RESOURCE_NOT_FOUND`.
4. Referenced-resource existence — every foreign-key id in the body exists, else `ERR_REFERENCED_RESOURCE_NOT_FOUND`.
5. Request well-formedness — required fields present, enum values valid, `scheduled_end_utc` strictly after `scheduled_start_utc`, and `post_feed_weight_grams` not below `pre_feed_weight_grams`, else `ERR_INVALID_REQUEST`.
6. Cross-practice integrity — on consult scheduling, the consultant and client share the consult's practice, else `ERR_CROSS_PRACTICE_REFERENCE`.
7. State correctness — the target resource is in a state that permits the requested transition, else `ERR_INVALID_STATE` (whose concrete per-transition specializations are described in §3).
8. Client active-status — on consult scheduling and rescheduling, the target client is `ACTIVE` rather than `SUSPENDED`, else `ERR_CLIENT_SUSPENDED`.
9. Parent-consult completion — superbill, DME-qualification, follow-up-plan, and pediatrician-referral creation each require the parent consult to be `COMPLETED`, else `ERR_CONSULT_NOT_COMPLETED`.
10. Consultant calendar conflict — on consult scheduling and rescheduling, the buffer-padded interval must not collide on the consultant, else `ERR_CONSULTANT_DOUBLE_BOOKED`.
11. Client calendar conflict — on consult scheduling and rescheduling, the bare interval must not collide for the client, else `ERR_CLIENT_DOUBLE_BOOKED`. The consultant check is evaluated before the client check.
12. ACA-preventive availability — on superbill drafting, if `is_aca_preventive` is requested true the practice must have `aca_preventive_enabled` true, else `ERR_ACA_PREVENTIVE_DISABLED`.
13. Package-credit sufficiency — on consult scheduling with package payment, the client must hold at least one remaining credit, else `ERR_NO_PACKAGE_CREDITS`.
14. Follow-up-plan open status — a weighted feed may be added only while its plan is `OPEN`, else `ERR_PLAN_CLOSED`.

The concrete state checks named in §3 (such as `ERR_CONSULT_NOT_SCHEDULED` or `ERR_SUPERBILL_NOT_SUBMITTED`) are the per-transition specializations of the generic state-correctness step.

### 2.8. Precision and Rounding

All monetary amounts are integers expressed in cents, and all weights and milk-transfer amounts are integers expressed in grams (one gram of transfer corresponds to one milliliter of milk). Wherever a calculation produces a fractional cent or a fractional gram, the result is rounded half-up — that is, a value exactly halfway between two integers rounds to the larger magnitude — and the stored field is the resulting whole number. Where a calculation specifies a floor (such as per-visit package value or infant age in days), the fractional part is discarded toward zero rather than rounded. The specific rounding obligations are stated alongside each calculation in §3.

### 2.9. Optimistic Concurrency Control on Ledger Reversal

One operation in the system requires optimistic concurrency control: voiding a paid superbill, which reverses that superbill's reimbursed amount back out of the owning client's reimbursement ledger. Because that reversal must never be computed against a stale view of the ledger, the void request must carry `expected_client_version`, a non-optional field whose value is the `version` of the owning `Client` that the caller last observed. The server compares `expected_client_version` to the client's current `version`. If another mutation — a second superbill paying out, or a no-show strike — has advanced the client's `version` since the caller last read it, the values differ and the void is rejected with `ERR_STALE_CLIENT_VERSION` (HTTP 412), so the reversal is never applied on top of an out-of-date balance. No other endpoint accepts or requires a version field; endpoints outside this rule perform no OCC check.

## 3. Business Logic & Workflows

### 3.1. Practice Configuration: Tiers, Packages, and Consultants

Everything begins with a `Practice`, created by a `PracticeAdmin` with a `name`. A practice also carries `aca_preventive_enabled`, which defaults to true; when true, superbills flagged as ACA preventive are reimbursed at the full allowed amount with zero patient responsibility, and when false such flagging is refused outright. The practice's logical clock, `now_utc`, is initialized to `2026-01-01T00:00:00Z` at creation, as described in §2.4.

Against a practice, the administrator builds the pricing catalog. A `SlidingScaleTier` is created with a `practice_id`, a human-readable `name` (such as `TIER_A`), an `income_ceiling_cents`, and a `discount_pct`. The `income_ceiling_cents` is the inclusive upper bound of annual household income, in cents, that qualifies a client for the tier — a client qualifies for the tier when their household income is at or below this ceiling. The `discount_pct` is a whole-number percent from 0 to 100 taken off the standard consult rate for clients in that tier.

A `ServicePackage` bundles prepaid visits. It is created with a `practice_id`, a `name` (such as `THREE_VISIT_BUNDLE`), an `included_visits` count of at least one, and a flat `price_cents`. On creation the system computes `per_visit_value_cents` as the package price divided by the number of included visits, with any fractional cent discarded toward zero (floor); this is the credit value redeemed per consult.

A `Consultant` — the IBCLC clinician — is created with a `practice_id`, a `full_name`, and a `standard_rate_cents`, the self-pay rate before any sliding-scale discount or package redemption. Each consultant also carries a `travel_buffer_minutes`, defaulting to 60, which is the number of minutes of travel buffer reserved before and after each in-home consult on that consultant's calendar (see §3.4).

### 3.2. Registering a Client and Granting Package Credits

A `FrontDesk` clerk or a `PracticeAdmin` registers a `Client` with a `practice_id`, a `full_name`, the infant's date of birth `infant_dob`, and the annual `household_income_cents` that drives sliding-scale selection. A client may optionally supply a `package_id` naming the purchased `ServicePackage` whose credits they will redeem; when omitted the client is self-pay only and the stored `package_id` is null. The supplied (or null) `package_id` is persisted on the client record and is filterable on the client list. Every newly registered client starts with `status` equal to `ACTIVE`.

A client's credit accounting is captured in three computed fields. `package_credits_total` is the total prepaid credits granted: when a `package_id` is supplied at registration it equals that package's `included_visits`, and otherwise it is 0. `package_credits_consumed` is the number of credits committed by completed or in-flight consults, starting at 0. `package_credits_remaining` is `package_credits_total` minus `package_credits_consumed` and is never allowed to go negative. The client also carries `reimbursement_ledger_cents` — the running sum of reimbursed amounts across that client's paid superbills, reduced again when a paid superbill is voided — and `no_show_strikes`, the count of this client's consults that have reached a no-show. Both begin at 0.

A client's `status` is `ACTIVE` or `SUSPENDED`. The status flips to `SUSPENDED` when the strike count reaches the suspension threshold, as detailed in §3.6. A `Client` (the self-service role) and practice staff can read the client record, including its live ledgers and credit balances.

### 3.3. Scheduling a Consult

A consult is the unit of care. A `FrontDesk` clerk or `PracticeAdmin` schedules a `Consult` by supplying a `practice_id`, the `client_id`, the `consultant_id`, a `consult_type` of `PRENATAL`, `IN_HOME`, or `TELEHEALTH`, a `scheduled_start_utc`, a `scheduled_end_utc` that must be strictly after the start, and a `pay_method` of either `SELF_PAY` or `PACKAGE`. A new consult is created in `SCHEDULED` status with a `reschedule_count` of 0.

Before the consult is accepted, several conditions are checked beyond ordinary body validation. The consultant and client must both belong to the same practice as the consult itself; a mismatch is rejected with `ERR_CROSS_PRACTICE_REFERENCE`. The target client must be `ACTIVE`; a suspended client cannot have new consults booked and the attempt is rejected with `ERR_CLIENT_SUSPENDED`. The proposed time must clear both calendar-conflict checks described in §3.4.

The `pay_method` determines the patient charge, recorded as `fee_cents`, and whether a package credit is involved, tracked by the boolean `package_credit_redeemed` (which begins false). When `pay_method` is `SELF_PAY`, the sliding-scale fee calculation runs at scheduling time and sets `fee_cents`; the package credit balance is untouched. When `pay_method` is `PACKAGE`, `fee_cents` is set to 0 because a package credit will stand in for payment, and the sliding scale is never evaluated; the credit itself is not committed at scheduling but at completion. A package-paid consult may only be scheduled when the client has at least one remaining credit — `package_credits_remaining` of one or more — and otherwise the request is rejected with `ERR_NO_PACKAGE_CREDITS`.

**Sliding-scale fee.** To price a self-pay consult, the system first selects the client's tier. It gathers every `SlidingScaleTier` belonging to the consult's practice whose `income_ceiling_cents` is greater than or equal to the client's `household_income_cents` — that is, every tier whose ceiling the client's income does not exceed. If no tier qualifies, the discount percent is 0 and the client pays the full rate. If one or more tiers qualify, the system picks the tier with the smallest `income_ceiling_cents` (the tightest matching bracket); ties on the ceiling are broken by choosing the lowest `discount_pct`, and any remaining tie is broken by the earliest `created_at`. The chosen tier's `discount_pct` is then applied: `fee_cents` is the consultant's `standard_rate_cents` multiplied by the quantity one hundred minus the discount percent, divided by one hundred, with the result rounded half-up to a whole number of cents.

### 3.4. Calendar Conflicts and the Travel Buffer

Two separate non-overlap checks guard every consult booking and rebooking, and both consider only non-terminal consults — those still in `SCHEDULED` or `IN_PROGRESS` — as occupying the calendar. The consultant check is evaluated first; the client check second.

On the consultant's calendar, an in-home visit reserves travel time on both sides. An `IN_HOME` consult occupies the half-open interval running from its start minus the consultant's `travel_buffer_minutes` up to (but not including) its end plus that same buffer; a `PRENATAL` or `TELEHEALTH` consult occupies only its bare half-open interval from start up to (but not including) end. The new consult's buffer-padded interval must not overlap any non-terminal consult already on that consultant. Two intervals overlap exactly when the first one's padded start is strictly before the second one's padded end and the second one's padded start is strictly before the first one's padded end; if such an overlap exists the booking is rejected with `ERR_CONSULTANT_DOUBLE_BOOKED`.

On the client's calendar, no buffer is ever applied. The new consult's bare half-open interval from `scheduled_start_utc` up to (but not including) `scheduled_end_utc` must not overlap any non-terminal consult for the same client, using the same strict overlap test: the first interval's start strictly before the second's end and the second's start strictly before the first's end. Because the interval is half-open, two adjacent appointments that merely touch at an instant — one ending exactly when the next begins — do not conflict. A genuine overlap is rejected with `ERR_CLIENT_DOUBLE_BOOKED`.

### 3.5. Rescheduling, Starting, and Completing a Consult

Rescheduling moves a consult to a new window. A `FrontDesk` clerk or `PracticeAdmin` supplies a fresh `scheduled_start_utc` and `scheduled_end_utc`. Rescheduling is permitted only on a consult in `SCHEDULED` status, otherwise it is rejected with `ERR_CONSULT_NOT_SCHEDULED`; the owning client must be `ACTIVE` (`ERR_CLIENT_SUSPENDED` otherwise); and the new window must clear the same consultant buffer-padded check (`ERR_CONSULTANT_DOUBLE_BOOKED`) and bare client check (`ERR_CLIENT_DOUBLE_BOOKED`) described in §3.4. A reschedule passes through a brief holding state, advancing `SCHEDULED → RESCHEDULED` and then, within the same request, automatically re-confirming `RESCHEDULED → SCHEDULED`. Its side effects replace `scheduled_start_utc` and `scheduled_end_utc` with the new values and add one to `reschedule_count`.

Starting a consult is a `Consultant` action that advances `SCHEDULED → IN_PROGRESS`. It requires the consult to be `SCHEDULED` (`ERR_CONSULT_NOT_SCHEDULED` otherwise) and requires the practice clock `now_utc` to have reached the appointment start — that is, `now_utc` is at or after `scheduled_start_utc`; if the clock is still before the start the request is rejected with `ERR_CONSULT_NOT_STARTABLE`.

Completing a consult is a `Consultant` action that advances `IN_PROGRESS → COMPLETED`. It requires the consult to be `IN_PROGRESS` (`ERR_CONSULT_NOT_IN_PROGRESS` otherwise) and requires that a feeding assessment already exists for this consult; completing a consult with no recorded assessment is rejected with `ERR_NO_FEEDING_ASSESSMENT`. On completion, if the consult's `pay_method` is `PACKAGE`, the package credit is committed: `package_credit_redeemed` is set true, the client's `package_credits_consumed` is increased by one, and `package_credits_remaining` is recomputed accordingly. Completion is also the gate that makes the consult eligible to spawn its downstream records — a superbill, a DME qualification, a follow-up plan, and a pediatrician referral.

### 3.6. No-Shows, Strikes, and the Suspension Cascade

When a scheduled client fails to appear, a `FrontDesk` clerk or `PracticeAdmin` marks the consult a no-show, advancing `SCHEDULED → NO_SHOW`. This requires the consult to be `SCHEDULED` (`ERR_CONSULT_NOT_SCHEDULED` otherwise) and, like starting, requires the clock `now_utc` to be at or after `scheduled_start_utc`, otherwise `ERR_CONSULT_NOT_STARTABLE`. `NO_SHOW` is terminal.

A no-show sets off an ordered cascade of mutations across the client. First, the client's `no_show_strikes` is increased by one — a mutation on the client caused by this transition. If the consult being no-showed had a committed package credit, that credit is returned at the same time by decreasing the client's `package_credits_consumed` by one, never letting it fall below zero. Second, the system evaluates the suspension threshold: when the freshly incremented strike count reaches three or more, the client's `status` is set to `SUSPENDED`. The boundary is inclusive — the third strike suspends, while two strikes do not. This suspension is understood as caused by the strike increment, not by the no-show directly. Third, the suspension itself fans out: every other consult of that client still in `SCHEDULED` status is automatically cancelled to `CANCELLED`, and each such auto-cancelled consult that held a committed package credit returns it, again decreasing `package_credits_consumed` by one per credited consult and never below zero. This auto-cancel tail hop is the consequence of the suspension, which is in turn the consequence of the strike increment. The entire cascade of client-field changes — the strike increment, any returned credits, and a possible suspension — collapses into a single mutation of the client, refreshing its `updated_at` and incrementing its `version` exactly once for the whole no-show; each auto-cancelled consult is separately mutated and so bumps its own `version` once.

Separately from no-shows, a `FrontDesk` clerk or `PracticeAdmin` may directly cancel an appointment, advancing `SCHEDULED → CANCELLED`. Cancellation is permitted only on a consult that is `SCHEDULED`; an attempt to cancel a consult in any other state is rejected with `ERR_CONSULT_NOT_CANCELLABLE`. When the cancelled consult was package-paid and had a committed package credit (its `package_credit_redeemed` is true), that credit is returned by decreasing the client's `package_credits_consumed` by one, never below zero, and `package_credits_remaining` is recomputed. `CANCELLED` is terminal.

### 3.7. Feeding Assessments

During a visit, a `Consultant` records a `FeedingAssessment` for a consult. Recording an assessment is not gated on the parent consult's state — the consult need only exist (its `consult_id` must resolve, else `ERR_REFERENCED_RESOURCE_NOT_FOUND`); no particular consult status is required. The assessment names its `consult_id`, a `latch_score` from 0 to 10 (the LATCH assessment), a `pre_feed_weight_grams` that must be greater than zero, a `post_feed_weight_grams` that must be at least the pre-feed weight, and optional free-text `notes`. A request where the post-feed weight is below the pre-feed weight is rejected as malformed with `ERR_INVALID_REQUEST`. The presence of at least one feeding assessment on a consult is precisely what unlocks completion, as covered in §3.5.

### 3.8. Follow-Up Plans and Weighted Feeds

After a consult is `COMPLETED`, a `Consultant` may open a `FollowUpPlan` against it by naming the `consult_id` and a `target_daily_transfer_grams` goal greater than zero; the plan's `client_id` is copied from the parent consult, and the plan opens in `OPEN` status. Because creating a follow-up plan requires a completed parent, an attempt against a consult that is not `COMPLETED` is rejected with `ERR_CONSULT_NOT_COMPLETED`.

Under an open plan, the consultant records `WeightedFeed` entries, each naming its `follow_up_plan_id`, a `pre_feed_weight_grams` greater than zero, and a `post_feed_weight_grams` at least equal to the pre-feed weight (a smaller post-feed weight is an `ERR_INVALID_REQUEST`). Each feed's `transfer_grams` is computed as its post-feed weight minus its pre-feed weight — the milk transferred that feed. A weighted feed may be recorded only while its plan is `OPEN`; once the plan is closed, further feed entry is rejected with `ERR_PLAN_CLOSED`.

**Weighted-feed rollup.** Every time a new feed is recorded, the plan's aggregates are recomputed over all of the plan's weighted feeds (feeds are immutable, so no status filter applies). The `total_transfer_grams` is the sum of the per-feed transfers — each transfer being the feed's post-feed weight minus its pre-feed weight. The `avg_transfer_grams` is the mean per-feed transfer: when the plan has no feeds it is 0, and otherwise it is the total transfer divided by the number of feeds, rounded half-up exactly once after summing. The rounding order is fixed — sum the integer per-feed transfers first, then round the single mean — rather than rounding each feed and then averaging. The boolean `meets_target` is true when `total_transfer_grams` is greater than or equal to the plan's `target_daily_transfer_grams`.

Closing a follow-up plan is a `Consultant` action that advances `OPEN → CLOSED`; it requires the plan to be `OPEN`, otherwise `ERR_PLAN_NOT_OPEN`. Closing locks weighted-feed entry, so any subsequent attempt to record a feed against the now-closed plan is the `ERR_PLAN_CLOSED` case noted above.

### 3.9. Superbills and Insurance Reimbursement

The revenue cycle is owned by a `BillingSpecialist`. Against a `COMPLETED` consult, the specialist drafts a `Superbill` by naming the `consult_id`, the provider's `billed_amount_cents` submitted to the insurer, and the insurer's `allowed_amount_cents` for the CPT code — reimbursement is always computed against the allowed amount, never the billed amount. The draft may also carry `is_aca_preventive` (default false), `deductible_remaining_cents` (default 0, the client's remaining deductible at submission), and `coinsurance_pct` (default 0, the client coinsurance percent from 0 to 100 applied after the deductible). The superbill's `client_id` is copied from the consult, and it opens in `DRAFT` status with `reimbursed_amount_cents` and `patient_responsibility_cents` both at 0. Drafting requires the parent consult to be `COMPLETED`, otherwise `ERR_CONSULT_NOT_COMPLETED`. If `is_aca_preventive` is requested true, the practice must have `aca_preventive_enabled` true, otherwise the draft is rejected with `ERR_ACA_PREVENTIVE_DISABLED`.

Submitting moves the superbill `DRAFT → SUBMITTED`; it requires the superbill to be in `DRAFT` (the not-submittable state error is `ERR_SUPERBILL_NOT_SUBMITTABLE`) and again requires the parent consult to be `COMPLETED` (`ERR_CONSULT_NOT_COMPLETED`).

Adjudication is the decisive step and is driven by an `outcome` supplied in the request. The superbill must be `SUBMITTED`, otherwise `ERR_SUPERBILL_NOT_SUBMITTED`. When `outcome` is `PAID`, the superbill advances `SUBMITTED → PAID`, the reimbursement figures are computed (below), and the client's reimbursement ledger is increased: `reimbursement_ledger_cents` grows by the just-computed `reimbursed_amount_cents`, and as a ledger mutation the client's `version` advances by one. When `outcome` is `DENIED`, the superbill advances `SUBMITTED → DENIED`, `reimbursed_amount_cents` is set to 0, and `patient_responsibility_cents` is set to the full `allowed_amount_cents`. A denied superbill may be resubmitted, advancing `DENIED → SUBMITTED` under the same preconditions as a first submit (the superbill must be in `DENIED`, surfaced as `ERR_SUPERBILL_NOT_SUBMITTABLE` when it is not, and the parent consult must still be `COMPLETED`).

**Reimbursement amount.** At a paid adjudication the figures branch on coverage. If the superbill is ACA-preventive — `is_aca_preventive` is true and the practice's `aca_preventive_enabled` is true — the full allowed amount is reimbursed: `reimbursed_amount_cents` equals `allowed_amount_cents` and `patient_responsibility_cents` is 0 regardless of any deductible or coinsurance. Otherwise the standard cost-share applies. The deductible actually applied is the smaller of the allowed amount and `deductible_remaining_cents`. The amount remaining after the deductible is the allowed amount minus that applied deductible. The coinsurance is that after-deductible amount multiplied by `coinsurance_pct`, divided by one hundred, rounded half-up to whole cents. The patient responsibility is the applied deductible plus the coinsurance, and `reimbursed_amount_cents` is the allowed amount minus that patient responsibility. In both branches `patient_responsibility_cents` equals `allowed_amount_cents` minus `reimbursed_amount_cents`.

**Voiding a paid superbill.** A paid superbill can be voided, advancing `PAID → VOID`, which reverses its contribution to the client ledger: `reimbursement_ledger_cents` is decreased by the superbill's `reimbursed_amount_cents` so the ledger returns to its pre-payment value, and the client's `version` advances by one. The superbill must be `PAID`, otherwise `ERR_SUPERBILL_NOT_VOIDABLE`. Because this reversal must not run against a stale ledger, the void carries `expected_client_version` and is guarded by the optimistic-concurrency rule of §2.9: if `expected_client_version` does not match the client's current `version`, the void is rejected with `ERR_STALE_CLIENT_VERSION`.

### 3.10. Breast-Pump DME Qualification

A breast-pump durable-medical-equipment qualification establishes a client's eligibility for a pump. Against a `COMPLETED` consult (which establishes medical necessity — otherwise `ERR_CONSULT_NOT_COMPLETED`), a `Consultant` or `BillingSpecialist` requests a `DMEQualification` by naming the `consult_id` and a `pump_type` of either `STANDARD_ELECTRIC` or `HOSPITAL_GRADE`. The qualification's `client_id` is copied from the consult, its `requested_utc` is stamped from the practice clock `now_utc` at request time, it opens in `PENDING` status, and its `qualified` flag is computed immediately.

**Qualification window.** The `qualified` flag follows the window rule. If the parent consult is not `COMPLETED`, the flag is false. Otherwise, if `pump_type` is `HOSPITAL_GRADE`, the flag is true — a hospital-grade pump always qualifies off a completed consult. If `pump_type` is `STANDARD_ELECTRIC`, the system computes the infant's age in days as the difference between the qualification's `requested_utc` and the client's `infant_dob`, taken in whole days by flooring (the elapsed seconds divided by eighty-six thousand four hundred, fractional part discarded); the flag is true when that age in days is at or below the thirty-day window, and false beyond it. The boundary is inclusive: an age of exactly thirty days qualifies, while thirty-one days does not.

Adjudicating a DME qualification is a `BillingSpecialist` action on a `PENDING` qualification (otherwise `ERR_DME_NOT_PENDING`). When the `qualified` flag is true the qualification advances `PENDING → QUALIFIED`; when the flag is false it advances `PENDING → DENIED`. Adjudication cannot force a qualification through against a false flag: an attempt to land on `QUALIFIED` while `qualified` is false is rejected with `ERR_DME_WINDOW_NOT_MET`.

### 3.11. Pediatrician Referrals

When a visit surfaces a concern that belongs with the infant's pediatrician, a `Consultant` creates a `PediatricianReferral` against a `COMPLETED` consult (else `ERR_CONSULT_NOT_COMPLETED`). The referral names the prompting `consult_id`, a `reason` of `WEIGHT_CONCERN`, `TONGUE_TIE`, `JAUNDICE`, or `OTHER`, and the receiving `pediatrician_name`; its `client_id` is copied from the consult and it opens in `OPEN` status.

A referral has two terminal resolutions, both `Consultant` actions on an `OPEN` referral (otherwise `ERR_REFERRAL_NOT_OPEN` in either case). Acknowledging it advances `OPEN → ACKNOWLEDGED`, recording that the pediatrician received it. Cancelling it advances `OPEN → CANCELLED`. Neither resolution carries further side effects.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — including all state-transition actions and the clock-setting capability — return `200 OK`. Read operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/practices` | Create a practice | PracticeAdmin |
| GET | `/practices/{id}` | Get a practice | PracticeAdmin, BillingSpecialist, Consultant, FrontDesk, Client |
| POST | `/_clock/set_current_utc` | Set the practice logical clock (test-driving) | PracticeAdmin |
| POST | `/sliding-scale-tiers` | Create a sliding-scale tier | PracticeAdmin |
| GET | `/sliding-scale-tiers/{id}` | Get a sliding-scale tier | PracticeAdmin, BillingSpecialist, Consultant, FrontDesk |
| GET | `/sliding-scale-tiers` | List sliding-scale tiers | PracticeAdmin, BillingSpecialist, Consultant, FrontDesk |
| POST | `/service-packages` | Create a service package | PracticeAdmin |
| GET | `/service-packages/{id}` | Get a service package | PracticeAdmin, BillingSpecialist, Consultant, FrontDesk |
| GET | `/service-packages` | List service packages | PracticeAdmin, BillingSpecialist, Consultant, FrontDesk |
| POST | `/consultants` | Create an IBCLC consultant | PracticeAdmin |
| GET | `/consultants/{id}` | Get a consultant | PracticeAdmin, BillingSpecialist, Consultant, FrontDesk |
| GET | `/consultants` | List consultants | PracticeAdmin, BillingSpecialist, Consultant, FrontDesk |
| POST | `/clients` | Register a client | FrontDesk, PracticeAdmin |
| GET | `/clients/{id}` | Get a client | PracticeAdmin, BillingSpecialist, Consultant, FrontDesk, Client |
| GET | `/clients` | List clients | PracticeAdmin, BillingSpecialist, Consultant, FrontDesk |
| POST | `/consults` | Schedule a consult | FrontDesk, PracticeAdmin |
| GET | `/consults/{id}` | Get a consult | PracticeAdmin, BillingSpecialist, Consultant, FrontDesk, Client |
| GET | `/consults` | List consults | PracticeAdmin, BillingSpecialist, Consultant, FrontDesk, Client |
| POST | `/consults/{id}/reschedule` | Reschedule a scheduled consult | FrontDesk, PracticeAdmin |
| POST | `/consults/{id}/start` | Begin a consult | Consultant |
| POST | `/consults/{id}/complete` | Complete a consult | Consultant |
| POST | `/consults/{id}/no-show` | Mark a consult as a no-show | FrontDesk, PracticeAdmin |
| POST | `/consults/{id}/cancel` | Cancel a scheduled consult | FrontDesk, PracticeAdmin |
| POST | `/feeding-assessments` | Record an intake feeding assessment | Consultant |
| GET | `/feeding-assessments/{id}` | Get a feeding assessment | PracticeAdmin, BillingSpecialist, Consultant, FrontDesk |
| GET | `/feeding-assessments` | List feeding assessments | PracticeAdmin, BillingSpecialist, Consultant, FrontDesk |
| POST | `/follow-up-plans` | Open a follow-up plan | Consultant |
| GET | `/follow-up-plans/{id}` | Get a follow-up plan | PracticeAdmin, BillingSpecialist, Consultant, FrontDesk, Client |
| GET | `/follow-up-plans` | List follow-up plans | PracticeAdmin, BillingSpecialist, Consultant, FrontDesk, Client |
| POST | `/follow-up-plans/{id}/close` | Close a follow-up plan | Consultant |
| POST | `/weighted-feeds` | Record a weighted feed | Consultant |
| GET | `/weighted-feeds/{id}` | Get a weighted feed | PracticeAdmin, BillingSpecialist, Consultant, FrontDesk, Client |
| GET | `/weighted-feeds` | List weighted feeds | PracticeAdmin, BillingSpecialist, Consultant, FrontDesk, Client |
| POST | `/superbills` | Draft a superbill | BillingSpecialist |
| GET | `/superbills/{id}` | Get a superbill | PracticeAdmin, BillingSpecialist, Consultant, Client |
| GET | `/superbills` | List superbills | PracticeAdmin, BillingSpecialist, Consultant, Client |
| POST | `/superbills/{id}/submit` | Submit or resubmit a superbill | BillingSpecialist |
| POST | `/superbills/{id}/adjudicate` | Adjudicate a submitted superbill | BillingSpecialist |
| POST | `/superbills/{id}/void` | Void a paid superbill | BillingSpecialist |
| POST | `/dme-qualifications` | Request a DME qualification | BillingSpecialist, Consultant |
| GET | `/dme-qualifications/{id}` | Get a DME qualification | PracticeAdmin, BillingSpecialist, Consultant, Client |
| GET | `/dme-qualifications` | List DME qualifications | PracticeAdmin, BillingSpecialist, Consultant, Client |
| POST | `/dme-qualifications/{id}/adjudicate` | Adjudicate a DME qualification | BillingSpecialist |
| POST | `/pediatrician-referrals` | Create a pediatrician referral | Consultant |
| GET | `/pediatrician-referrals/{id}` | Get a pediatrician referral | PracticeAdmin, BillingSpecialist, Consultant, Client |
| GET | `/pediatrician-referrals` | List pediatrician referrals | PracticeAdmin, BillingSpecialist, Consultant, Client |
| POST | `/pediatrician-referrals/{id}/acknowledge` | Acknowledge a referral | Consultant |
| POST | `/pediatrician-referrals/{id}/cancel` | Cancel an open referral | Consultant |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH_CONTEXT` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_RESOURCE_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCED_RESOURCE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_CROSS_PRACTICE_REFERENCE` | 409 Conflict |
| `ERR_ACA_PREVENTIVE_DISABLED` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_CONSULT_NOT_SCHEDULED` | 409 Conflict |
| `ERR_CONSULT_NOT_IN_PROGRESS` | 409 Conflict |
| `ERR_CONSULT_NOT_STARTABLE` | 409 Conflict |
| `ERR_CONSULT_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_CONSULT_NOT_COMPLETED` | 409 Conflict |
| `ERR_NO_FEEDING_ASSESSMENT` | 409 Conflict |
| `ERR_CLIENT_SUSPENDED` | 409 Conflict |
| `ERR_SUPERBILL_NOT_SUBMITTABLE` | 409 Conflict |
| `ERR_SUPERBILL_NOT_SUBMITTED` | 409 Conflict |
| `ERR_SUPERBILL_NOT_VOIDABLE` | 409 Conflict |
| `ERR_DME_NOT_PENDING` | 409 Conflict |
| `ERR_DME_WINDOW_NOT_MET` | 409 Conflict |
| `ERR_PLAN_NOT_OPEN` | 409 Conflict |
| `ERR_PLAN_CLOSED` | 409 Conflict |
| `ERR_REFERRAL_NOT_OPEN` | 409 Conflict |
| `ERR_CONSULTANT_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_CLIENT_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_NO_PACKAGE_CREDITS` | 402 Payment Required |
| `ERR_STALE_CLIENT_VERSION` | 412 Precondition Failed |
