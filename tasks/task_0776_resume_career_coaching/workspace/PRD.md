# Resume Career Coaching API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Resume Career Coaching API, the transactional backbone of a professional résumé-writing and career-coaching service. The platform coordinates the full engagement between three parties: the clients who purchase writing and coaching packages, the coaches who produce the written deliverables and deliver live sessions, and the operational back office that curates the catalogue, adjudicates disputes, and controls delivery. A single engagement begins with an intake that captures the client's target role and industry, threads through the drafting and revision of résumés and supporting documents, layers in ATS-optimization scans and coaching or interview-prep sessions, and settles with a delivery, an acceptance, and — where a package offers one — a satisfaction or interview guarantee.

The business problem the API solves is that money, work product, and time-bound promises must stay consistent as the engagement moves through many hands. Pricing is quoted twice — once provisionally at intake and once finally at delivery — because add-ons and revision overages accrue in between. Credit pools for revisions and sessions must be spent, restored, and topped up without ever letting a client be double-charged or silently under-served. Guarantee windows are measured against a controllable logical clock so that turnaround deadlines and eligibility rules are deterministic. This specification defines the entities, state machines, pricing calculations, validation ordering, and access-control rules that keep all of these moving parts reconciled.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that apply across every endpoint. Business-process detail lives in Section 3; the two sections are meant to be read together.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated with two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the capacity in which they act. The system recognizes exactly three roles, spelled precisely as `Client`, `Coach`, and `CareerAdmin`. If either header is missing, or if `X-User-Role` is not one of the three known roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are valid but the acting role is not permitted to call the requested endpoint, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

Roles are tied to resource ownership as follows. When `X-User-Role` is `Client`, `X-User-ID` is the `id` of the acting `Client`; ownership checks on any resource that references a client compare the resource's `client_id` to `X-User-ID`. Because an order records the acting client's identity in `client_id`, a client may act only on orders — and on the deliverables, revisions, sessions, add-ons, and claims beneath those orders — that carry their own `id`. When `X-User-Role` is `Coach`, `X-User-ID` is the `id` of the acting `Coach`; a coach acting on a coaching session is verified to be that session's coach, meaning the session's `coach_id` must equal `X-User-ID`. When `X-User-Role` is `CareerAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server accepts it for auditing but never compares it to any entity's `id`. A `Client` or `Coach` acting on a resource they do not own is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless a specific endpoint states otherwise, all list endpoints return their resources sorted by creation timestamp (`created_at`) in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties

Most resources in the system are full, versioned entities. `Client`, `Coach`, `Order`, `Deliverable`, `RevisionRequest`, `CoachingSession`, `AddOn`, and `GuaranteeClaim` each carry four system-managed fields: an `id` formatted as a UUID with no type prefix; a `created_at` ISO 8601 UTC timestamp with three fractional digits; an `updated_at` ISO 8601 UTC timestamp refreshed on every mutation; and a `version` integer that starts at its initial value and increments by one on every mutation of the resource.

Two resource kinds are deliberately lighter. A `PackagePlan` and a `Payment` are effectively immutable records: each carries only an `id` and a `created_at`, and neither carries an `updated_at` nor a `version`. An `AtsScan` is likewise a write-once record carrying only `id` and `created_at`. Read endpoints for these resources therefore never expose `updated_at` or `version`.

### 2.5. Monetary Amounts, Precision, and Rounding

All monetary amounts in the system are stored and returned as integer cents; there are no fractional cents. Wherever a calculation multiplies by a percentage or fraction — an add-on volume discount, a coupon percentage, a rush surcharge, or an ATS coverage percentage — the intermediate result is rounded to the nearest whole unit using the round-half-up convention (a value of exactly one-half always rounds away from zero, upward). Rounding is applied at each intermediate step that the pricing and scoring calculations of Section 3 call out, not merely once at the end. Configuration percentages such as a plan's `rush_surcharge_pct` are stored as supplied.

### 2.6. The Order Ledger and Net Collection

Every financial event on an order is recorded as an immutable `Payment` ledger entry, and the order maintains running totals derived from that ledger. Each `Payment` records the owning `order_id`, a `type` that is either `CHARGE` or `REFUND`, a positive `amount_cents` magnitude, and a `reason` drawn from `CONFIRM`, `REVISION_OVERAGE`, `SESSION_OVERAGE`, `MANUAL_ADDON`, `SESSION_REFUND`, and `GUARANTEE_REFUND`. Whenever a `CHARGE` entry is written, the order's `amount_charged_cents` increases by that entry's amount; whenever a `REFUND` entry is written, the order's `amount_refunded_cents` increases by that entry's amount. Both running totals begin at zero. The order's `net_collected_cents` is always the `amount_charged_cents` minus the `amount_refunded_cents`. These three fields are the single source of truth for how much money the engagement has actually collected, and downstream refund calculations read from them.

### 2.7. Credit Pools for Revisions and Sessions

An order carries two credit pools that govern how much work is included versus billed as overage. The revision pool has three inputs and two derived readings. Its included allotment `revision_credits_included` is copied from the plan's `included_revision_rounds` at order creation; its `revision_credits_purchased` counts the manually bought extra-revision add-ons and starts at zero; its `revision_credits_used` counts the currently active revision rounds and starts at zero. The order's `revision_credits_remaining` is the larger of zero and the quantity `revision_credits_included` plus `revision_credits_purchased` minus `revision_credits_used`.

The session pool works in parallel. Its included allotment `sessions_included` is the plan's `included_coaching_sessions` plus one additional credit when the plan's `includes_interview_prep` flag is true, and zero additional credits otherwise. Its `sessions_purchased` counts manually bought extra-coaching and interview-prep add-ons and starts at zero; its `sessions_used` counts the non-cancelled sessions booked against the order and starts at zero. A booking or a revision that finds its pool already exhausted is billed as an overage, as detailed in Section 3; a cancellation or withdrawal restores the consumed credit, also as detailed there.

### 2.8. Optimistic Concurrency on Session Booking

Booking a coaching or interview-prep session against an order is guarded by optimistic concurrency control on the order's `version`. A booking request must carry `expected_order_version` as a required field, holding the `version` of the order that the client last observed. The server compares that value to the order's current `version`; if another writer has advanced the order's version since the client last read it — every successful booking mutates the order's session and ledger fields and increments `version` by one — the stale request is rejected with `ERR_STALE_VERSION` (HTTP 412). This prevents a client from booking against an outdated view of the order's remaining session credits. No other endpoint takes a version field; only session booking is concurrency-guarded.

### 2.9. Hierarchical Consistency and Cascades

Orders sit at the top of an aggregate that includes deliverables, revision requests, coaching sessions, add-ons, guarantee claims, and payments; deliverables in turn own revision requests and ATS scans. State changes propagate through this hierarchy automatically. When the last outstanding deliverable on an order is approved, the order advances on its own from `IN_PRODUCTION` to `READY` without any separate request against the order — this is a bubble-up from the child to the parent. In the opposite direction, when a guarantee approval drives the order into `REFUNDED`, that refund cascades downward: every still-scheduled coaching session on the order is cancelled, and every deliverable that has not reached a terminal state is cancelled. Each such automatic transition is a genuine mutation of the affected resource, refreshing its `updated_at` and incrementing its `version` just as an explicit request would.

### 2.10. Nested Resource Retrieval and Path Validation

Several endpoints address a resource through a path that names a parent and then a child, and several list endpoints hang beneath an order or a deliverable. For any such path, the system validates the named identifiers left to right and rejects the request at the first identifier that does not resolve, returning that resource's specific not-found error. A reference to a missing client yields `ERR_CLIENT_NOT_FOUND`; a missing coach yields `ERR_COACH_NOT_FOUND`; a missing package plan yields `ERR_PLAN_NOT_FOUND`; a missing order yields `ERR_ORDER_NOT_FOUND`; a missing deliverable yields `ERR_DELIVERABLE_NOT_FOUND`; a missing revision request yields `ERR_REVISION_NOT_FOUND`; a missing session yields `ERR_SESSION_NOT_FOUND`; and a missing guarantee claim yields `ERR_CLAIM_NOT_FOUND`. All of these are HTTP 404.

### 2.11. The Logical Clock, Deadlines, and Guarantee Windows

All time-based rules are evaluated against a logical clock rather than wall-clock time, so that deadlines and guarantee windows are deterministic and test-drivable. At server startup the clock reads exactly `2026-03-01T00:00:00Z`, and before any clock-setting call it remains at that default and never falls back to real time. An administrative capability advances the clock to a supplied instant, provided as `to_iso8601`. When an order is confirmed, its `deadline_at` is set to the current logical-clock instant plus `requested_delivery_days` days. When an order is delivered, its `delivered_at` is stamped with the current logical-clock instant. Guarantee eligibility, described in Section 3, is measured as an elapsed interval from `delivered_at` against this same clock.

### 2.12. Validation Ordering

When a single request could fail several checks, the checks are evaluated in a fixed priority order and the first failure determines the response. The order is: (1) authentication — both headers present and `X-User-Role` a known role, else `ERR_UNAUTHENTICATED`; (2) authorization — the acting role may call this endpoint, else `ERR_UNAUTHORIZED`; (3) body well-formedness — required fields present, enum values in range, types correct, a session's `scheduled_end` strictly after its `scheduled_start`, and ATS sections non-empty with every section's `keywords_total` greater than zero, else `ERR_VALIDATION` (HTTP 422); (4) existence of every path resource, validated left to right per Section 2.10, else the matching not-found error; (5) ownership — the acting client or coach owns the target resource, else `ERR_NOT_RESOURCE_OWNER`; (6) state — the target resource is in a state that permits the requested transition, else the applicable state error (Section 3 names the specific code for each transition); (7) cross-entity referential preconditions — such as the coach being active for a new booking or the plan offering the invoked guarantee; (8) coach buffer-expanded slot conflict; (9) client overlap slot conflict; (10) guarantee eligibility window; and (11) the optimistic-concurrency version check for session booking. Because the version check sits last, a booking that is otherwise invalid surfaces its business error before any stale-version rejection.

## 3. Business Logic & Workflows

### 3.1. Catalogue Setup: Plans, Clients, and Coaches

The back office seeds the catalogue before any engagement can begin. A `CareerAdmin` defines a `PackagePlan` by supplying its `tier`, one of `BASIC`, `PRO`, or `EXECUTIVE`; a `base_price_cents` base price of at least zero; and a non-empty `included_deliverables` list drawn from `RESUME`, `LINKEDIN`, and `COVER_LETTER`. The plan also declares `included_revision_rounds` and `included_coaching_sessions` (each a count of at least zero); an `includes_interview_prep` flag that defaults to false and, when true, grants one extra session credit for interview prep; an `includes_ats` flag defaulting to false that indicates whether ATS-optimization scans are part of the package; a `guarantee_type` of `NONE`, `SATISFACTION`, or `INTERVIEW`, defaulting to `NONE`; and a `rush_surcharge_pct` fractional surcharge that defaults to 0.30 and must be at least zero.

A `CareerAdmin` also registers the people. A `Client` is created with a `name`, an `email`, and an optional account `status` that defaults to `ACTIVE` and is otherwise `INACTIVE`; only an `ACTIVE` client may create orders. A `Coach` is created with a `name`, an `email`, a `specialty` of `TECH`, `FINANCE`, `GENERAL`, or `EXECUTIVE`, an optional `buffer_minutes` that defaults to 15 and must be at least zero, and an optional availability `status` that defaults to `ACTIVE` and is otherwise `INACTIVE`. The `buffer_minutes` value is the minimum gap the coach requires after each of their sessions before starting another, and it drives the buffer-expanded overlap check at booking time. Only an `ACTIVE` coach may take new session bookings. Package plans, clients, and coaches are all individually fetchable and listable; plans may be filtered by `tier`, and orders may be filtered by `client_id`, `plan_id`, and `status`.

### 3.2. Order Intake and the Provisional Quote

A `Client` opens an engagement by creating an order, which starts in the `INTAKE` state. The creation payload names the purchased plan through `plan_id`, the `target_role` and `target_industry` the engagement optimizes for, and a `requested_delivery_days` turnaround of at least one day. It may also set the `rush` flag (default false), a `coupon_code` that is either `WELCOME10`, `SAVE50`, or absent (null), and an `addon_types` list of add-ons purchased up front at intake. On creation the system sets `client_id` from the acting client's `X-User-ID`; copies `base_price_cents`, `revision_credits_included`, `sessions_included`, and `guarantee_type` from the plan; creates one `Deliverable` in `PENDING` state for each entry of the plan's `included_deliverables`; and records `deliverables_total` as the number of deliverables created — one per included deliverable type plus one for each `EXTRA_DELIVERABLE` among the intake add-ons. Add-ons named in `addon_types` are recorded as manual add-ons that participate in the provisional quote; they are not charged individually at intake, because the single confirmation charge described in Section 3.3 covers them.

At intake the system computes the **provisional quote** and stores it in `provisional_total_cents`, alongside the component fields `addons_subtotal_cents`, `discount_cents`, and `rush_surcharge_cents`. The provisional quote is the order-price calculation evaluated over only the intake-time add-ons. The calculation proceeds in a pinned order. First, `addons_subtotal_cents` is the sum of `price_cents` over the add-ons in scope, and the add-on count is how many such add-ons there are. The subtotal before discount is `base_price_cents` plus `addons_subtotal_cents`. Next, an add-on volume discount applies only when the add-on count is at least three: in that case the discount is the add-on subtotal multiplied by ten percent, rounded half up; otherwise it is zero. Then a coupon discount is computed: for `WELCOME10` it is the base price multiplied by ten percent, rounded half up; for `SAVE50` it is the smaller of 5000 cents and the subtotal before discount; with no coupon it is zero. The total `discount_cents` is the add-on volume discount plus the coupon discount. The discounted subtotal is the subtotal before discount minus `discount_cents`, floored at zero so it never goes negative. Finally the rush surcharge is applied last, to the discounted subtotal: when the order is a rush, `rush_surcharge_cents` is the discounted subtotal multiplied by the plan's `rush_surcharge_pct`, rounded half up; otherwise it is zero. The provisional total is the discounted subtotal plus the rush surcharge.

The add-on prices used throughout are fixed: an `EXTRA_REVISION` costs 4000 cents, an `EXTRA_COACHING` costs 12000 cents, an `EXTRA_DELIVERABLE` costs 9000 cents, an `INTERVIEW_PREP` costs 15000 cents, and a `RUSH` add-on costs 0 cents.

### 3.3. Confirmation, Production, Delivery, and Acceptance

Confirmation moves the order from `INTAKE` to `IN_PRODUCTION` and may be performed only by the owning client while the order is still in `INTAKE`. Confirming writes a single `CHARGE` payment for the provisional total with reason `CONFIRM`, so `amount_charged_cents` rises by `provisional_total_cents`, and it sets `deadline_at` to the current logical-clock instant plus `requested_delivery_days` days. The note that governs this step is that the provisional quote is charged up front, and any overages incurred later during production are charged as they occur.

Production continues until every deliverable is approved. When the count of approved deliverables, `deliverables_approved`, reaches `deliverables_total`, the order bubbles up from `IN_PRODUCTION` to `READY` on its own as a side effect of that final approval. A `CareerAdmin` then delivers the `READY` order, transitioning it from `READY` to `DELIVERED`; delivering computes the **final quote** into `final_total_cents` and stamps `delivered_at` with the current logical-clock instant. The final quote is the very same order-price calculation as the provisional one, differing only in which add-ons are in scope: the final variant includes every add-on on the order whose `status` is not `CANCELLED` at delivery time, which is to say it also captures the overage `EXTRA_REVISION` and `EXTRA_COACHING` add-ons generated during production, whereas the provisional variant saw only the intake-time add-ons. Until an order is delivered, `final_total_cents` remains null. Attempting to deliver an order that is not `READY` is rejected with `ERR_INVALID_STATE` (HTTP 409). After delivery, the owning client may accept the order, transitioning it from `DELIVERED` to `CLOSED`; accepting a non-`DELIVERED` order is likewise rejected with `ERR_INVALID_STATE`.

### 3.4. Drafting, the Revision Loop, and ATS Scans

Each `Deliverable` carries a `type` seeded from the plan (`RESUME`, `LINKEDIN`, or `COVER_LETTER`), a `status`, a `revision_round_count`, and a `draft_count`, all beginning at their initial values. A deliverable starts in `PENDING`. A `Coach` uploads the first draft, transitioning the deliverable from `PENDING` to `DRAFTED` and incrementing `draft_count` by one; this first draft may be uploaded only while the parent order is `IN_PRODUCTION`, and an attempt while the order is not in production is rejected with `ERR_ORDER_NOT_IN_PRODUCTION` (HTTP 409). Draft uploads accept an optional `notes` field.

From `DRAFTED`, the owning client may open a revision round, moving the deliverable from `DRAFTED` to `IN_REVISION`. Opening a revision creates a `RevisionRequest` in `OPEN` status whose `deliverable_id` points at the deliverable under revision, whose `round_no` is the deliverable's `revision_round_count` plus one, and whose `reason` carries the client's instructions; it increments the deliverable's `revision_round_count` by one; it runs the revision-billing rule; and it increments the order's `revision_credits_used` by one. The revision-billing rule reads the pool as `revision_credits_included` plus `revision_credits_purchased`: if `revision_credits_used` is still below that pool the round is free and its `billable` flag is false; otherwise the round is an overage, `billable` is true, and the system auto-creates an `EXTRA_REVISION` add-on priced at 4000 cents with `auto_generated` true and `source_ref` set to the revision request's `id`, which is immediately charged as described in Section 3.7 with payment reason `REVISION_OVERAGE`. A revision may be opened only on a `DRAFTED` deliverable; attempting it otherwise is rejected with `ERR_DELIVERABLE_NOT_DRAFTED` (HTTP 409).

The coach closes a revision round by re-drafting: uploading a draft on an `IN_REVISION` deliverable transitions it back from `IN_REVISION` to `DRAFTED`, increments `draft_count` by one, and moves the open revision request with the highest `round_no` from `OPEN` to `ADDRESSED`. This re-draft, like the first, requires the parent order to be `IN_PRODUCTION`. Alternatively, the owning client may withdraw a revision that has not yet been addressed: withdrawing is permitted only when the revision request is `OPEN` and its `billable` flag is false, and it moves the deliverable from `IN_REVISION` back to `DRAFTED`, sets the revision request from `OPEN` to `WITHDRAWN`, decrements the deliverable's `revision_round_count` by one, and restores the consumed credit by decrementing the order's `revision_credits_used` by one. A withdraw attempted on a revision that is not `OPEN`, or on one that is billable, is rejected with `ERR_REVISION_NOT_WITHDRAWABLE` (HTTP 409).

Once a deliverable is `DRAFTED`, the owning client may approve it, transitioning it from `DRAFTED` to `APPROVED`. Approval increments the order's `deliverables_approved` by one, and when that count reaches `deliverables_total` it triggers the bubble-up that moves the order to `READY`. Approving a deliverable that is not `DRAFTED` is rejected with `ERR_DELIVERABLE_NOT_DRAFTED`.

A `Coach` may run an ATS keyword scan on a deliverable, producing an `AtsScan`. The scan request supplies `sections`, a non-empty list in which each section provides a `name`, a `weight`, a `keywords_total` that must be greater than zero, a count of `matched_strict` exact hits, and a count of `matched_semantic` synonym-inclusive hits. The scan computes two scores under a pinned rounding order. First, for each section, a strict coverage percent is the section's `matched_strict` divided by its `keywords_total`, multiplied by 100 and rounded half up to a whole percent, and a semantic coverage percent is computed the same way from `matched_semantic`. These per-section percents are rounded first, before any aggregation. Then the total weight is the sum of all section weights, the `strict_score` is the weighted sum of the per-section strict percents divided by the total weight and rounded half up to a whole number, and the `semantic_score` is the weighted sum of the per-section semantic percents divided by the total weight and rounded half up. Because `matched_semantic` is never less than `matched_strict`, the semantic score is never less than the strict score for the same résumé. The scan also records `coverage_by_section`, a map from each section's `name` to its whole-number strict coverage percent. After a scan, the deliverable's `current_strict_ats_score` and `current_semantic_ats_score` are refreshed to the strict and semantic scores of the most recent scan by creation time, and remain null while no scan exists.

### 3.5. Coaching and Interview-Prep Sessions

The owning client books a `CoachingSession` against an order. Booking is guarded by the version check of Section 2.8, so the request must include `expected_order_version`. The booking payload also names the `coach_id`, a `session_type` of `COACHING` or `INTERVIEW_PREP`, and a `scheduled_start` and `scheduled_end` in ISO 8601 UTC where the end must be strictly after the start. The system denormalizes the order's `client_id` onto the session for calendar checks, sets the session to `SCHEDULED`, runs the session-billing rule, increments the order's `sessions_used` by one, and increments the order's `version` by one.

Several preconditions guard a booking, in the priority order of Section 2.12. The target coach must be `ACTIVE`; a booking against an inactive coach is rejected with `ERR_COACH_INACTIVE` (HTTP 409). The coach's calendar is protected by a buffer-expanded overlap check: the new session must not fall within `buffer_minutes` of any existing `SCHEDULED` session on the same coach, and a violation is rejected with `ERR_COACH_SLOT_CONFLICT` (HTTP 409). The client's own calendar is protected by a half-open overlap check: the new session must not strictly overlap the interval from the start up to but not including the end of any existing `SCHEDULED` session for the same client, though back-to-back sessions whose endpoints merely touch are allowed; a violation is rejected with `ERR_CLIENT_SLOT_CONFLICT` (HTTP 409). Only after these business checks does the stale-version rejection of `ERR_STALE_VERSION` apply.

The session-billing rule reads the pool as `sessions_included` plus `sessions_purchased`. If `sessions_used` is still below that pool the session is covered, its `billable` flag is false, and its `fee_cents` is zero. Otherwise the session is an overage: `billable` is true and `fee_cents` is the session price for its type — 12000 cents for a `COACHING` session and 15000 cents for an `INTERVIEW_PREP` session. When a session is billable, the system auto-creates an add-on of type `EXTRA_COACHING` for a coaching session or `INTERVIEW_PREP` for an interview-prep session, priced at that `fee_cents`, with `auto_generated` true and `source_ref` set to the session's `id`; the add-on is charged immediately with payment reason `SESSION_OVERAGE`.

A scheduled session can end in three divergent ways. The assigned coach may complete it, transitioning it from `SCHEDULED` to `COMPLETED` with no financial effect. The owning client, or a `CareerAdmin`, may cancel it, transitioning it from `SCHEDULED` to `CANCELLED`; cancellation restores the credit by decrementing the order's `sessions_used` by one, and if the session was billable it additionally writes a `REFUND` payment for `fee_cents` with reason `SESSION_REFUND` (raising `amount_refunded_cents` by that fee) and moves the auto-generated add-on whose `source_ref` is that session from `CHARGED` to `CANCELLED`. The assigned coach may instead mark a no-show, transitioning the session from `SCHEDULED` to `NO_SHOW`; a no-show consumes the session with no credit restoration and no refund. Any of complete, cancel, or no-show attempted on a session that is not `SCHEDULED` is rejected with `ERR_SESSION_NOT_SCHEDULED` (HTTP 409).

### 3.6. Add-ons and Overage Billing

Beyond the add-ons generated automatically as overages, the owning client may purchase a manual add-on on an order by supplying its `type`, one of `EXTRA_REVISION`, `EXTRA_COACHING`, `EXTRA_DELIVERABLE`, `INTERVIEW_PREP`, or `RUSH`. Every add-on carries a `price_cents` taken from the fixed price list, a `status` beginning at `PENDING`, an `auto_generated` flag that is false for manual purchases, and a `source_ref` that is null for manual purchases. A manual add-on is charged synchronously within the purchase request, moving from `PENDING` to `CHARGED`: this writes a `CHARGE` payment for the add-on's `price_cents` with reason `MANUAL_ADDON`, raising `amount_charged_cents` accordingly, and then applies the add-on's grant. An `EXTRA_REVISION` purchase increments the order's `revision_credits_purchased` by one. An `EXTRA_COACHING` or `INTERVIEW_PREP` purchase increments the order's `sessions_purchased` by one. An `EXTRA_DELIVERABLE` purchase creates a new `PENDING` deliverable and increments `deliverables_total` by one.

Auto-generated add-ons follow the same `PENDING` to `CHARGED` charge on creation, but with the overage reasons `REVISION_OVERAGE` or `SESSION_OVERAGE` rather than `MANUAL_ADDON`, and they do not grant credits — the overage they represent has already been consumed. An auto-generated add-on that is `CHARGED` is moved to `CANCELLED` only by the system, when the session or revision that generated it is itself cancelled or withdrawn; this compensating cancellation applies only to add-ons whose `auto_generated` flag is true.

### 3.7. Guarantee Claims and the Refund Cascade

After an order is delivered, the owning client may submit a `GuaranteeClaim` by supplying a `claim_type` of `SATISFACTION` or `INTERVIEW` and an `evidence` justification. A claim begins in `SUBMITTED`. Submission is gated by a sequence of checks. The order must be in `DELIVERED` or `CLOSED`; a claim against an order in any other state is rejected with `ERR_ORDER_NOT_DELIVERED` (HTTP 409). The order's plan must actually offer the invoked guarantee — the order's `guarantee_type`, copied from the plan, must equal the `claim_type` and must not be `NONE` — otherwise the claim is rejected with `ERR_GUARANTEE_NOT_OFFERED` (HTTP 409). No claim may be filed when an open claim, meaning one that is `SUBMITTED` or already `APPROVED`, exists for the order; a duplicate is rejected with `ERR_CLAIM_ALREADY_EXISTS` (HTTP 409). Finally the eligibility window is checked: a `SATISFACTION` claim is eligible only when no more than 14 days have elapsed since `delivered_at`, while an `INTERVIEW` claim is eligible only when at least 90 days have elapsed since `delivered_at` and the order has zero completed interview-prep sessions. A claim outside its window is rejected with `ERR_CLAIM_NOT_ELIGIBLE` (HTTP 409).

A `CareerAdmin` adjudicates a submitted claim. Rejecting it moves the claim from `SUBMITTED` to `REJECTED` and leaves the order untouched. Approving it moves the claim from `SUBMITTED` to `APPROVED` and sets its `refund_amount_cents`: for a `SATISFACTION` claim this is the order's full `net_collected_cents`, and for an `INTERVIEW` claim it is the order's `base_price_cents`. Approval then drives the order into `REFUNDED` — the root of the guarantee refund cascade. As the order enters `REFUNDED`, the system writes a `REFUND` payment for the claim's `refund_amount_cents` with reason `GUARANTEE_REFUND`, raising `amount_refunded_cents` by that amount; it cancels every coaching session on the order still in `SCHEDULED` (the guarantee refund settles the order as a whole, so no separate per-session refund is issued for these); and it cancels every deliverable not yet in a terminal state, that is every deliverable in `PENDING`, `DRAFTED`, or `IN_REVISION`, moving it to `CANCELLED`. Approving or rejecting a claim that is not `SUBMITTED` is rejected with `ERR_INVALID_STATE` (HTTP 409). `REFUNDED` is terminal for an order.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify or transition an existing resource, and read operations, return `200 OK`. Request and response bodies are not restated here — reconstruct them from the workflow narratives in Section 3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/package-plans` | Create a package plan | CareerAdmin |
| GET | `/package-plans/{id}` | Fetch a package plan | Client, Coach, CareerAdmin |
| GET | `/package-plans` | List package plans | Client, Coach, CareerAdmin |
| POST | `/clients` | Register a client | CareerAdmin |
| GET | `/clients/{id}` | Fetch a client | Client, Coach, CareerAdmin |
| POST | `/coaches` | Register a coach | CareerAdmin |
| GET | `/coaches/{id}` | Fetch a coach | Client, Coach, CareerAdmin |
| POST | `/_clock/set_current_utc` | Set the logical clock | CareerAdmin |
| POST | `/orders` | Create an order (intake) | Client |
| GET | `/orders/{id}` | Fetch an order | Client, Coach, CareerAdmin |
| GET | `/orders` | List/filter orders | Client, Coach, CareerAdmin |
| POST | `/orders/{id}/confirm` | Confirm intake and enter production | Client |
| POST | `/orders/{id}/deliver` | Deliver a ready order | CareerAdmin |
| POST | `/orders/{id}/accept` | Accept delivery and close the order | Client |
| GET | `/orders/{id}/deliverables` | List an order's deliverables | Client, Coach, CareerAdmin |
| GET | `/orders/{id}/addons` | List an order's add-ons | Client, Coach, CareerAdmin |
| GET | `/orders/{id}/payments` | List an order's ledger entries | Client, Coach, CareerAdmin |
| GET | `/orders/{id}/guarantee-claims` | List an order's guarantee claims | Client, Coach, CareerAdmin |
| POST | `/orders/{id}/addons` | Purchase a manual add-on | Client |
| POST | `/orders/{id}/sessions` | Book a coaching or interview-prep session | Client |
| POST | `/orders/{id}/guarantee-claims` | Submit a guarantee claim | Client |
| GET | `/deliverables/{id}` | Fetch a deliverable | Client, Coach, CareerAdmin |
| GET | `/deliverables/{id}/revisions` | List a deliverable's revision requests | Client, Coach, CareerAdmin |
| GET | `/deliverables/{id}/ats-scans` | List a deliverable's ATS scans | Client, Coach, CareerAdmin |
| POST | `/deliverables/{id}/drafts` | Upload a draft | Coach |
| POST | `/deliverables/{id}/revisions` | Open a revision round | Client |
| POST | `/deliverables/{id}/approve` | Approve a drafted deliverable | Client |
| POST | `/deliverables/{id}/ats-scans` | Run an ATS keyword scan | Coach |
| POST | `/revisions/{id}/withdraw` | Withdraw an open, non-billable revision | Client |
| GET | `/sessions/{id}` | Fetch a coaching session | Client, Coach, CareerAdmin |
| GET | `/sessions` | List/filter coaching sessions | Client, Coach, CareerAdmin |
| POST | `/sessions/{id}/complete` | Mark a session completed | Coach |
| POST | `/sessions/{id}/cancel` | Cancel a scheduled session | Client, CareerAdmin |
| POST | `/sessions/{id}/no-show` | Mark a session no-show | Coach |
| GET | `/guarantee-claims/{id}` | Fetch a guarantee claim | Client, Coach, CareerAdmin |
| POST | `/guarantee-claims/{id}/approve` | Approve a guarantee claim | CareerAdmin |
| POST | `/guarantee-claims/{id}/reject` | Reject a guarantee claim | CareerAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_VALIDATION` | 422 |
| `ERR_CLIENT_NOT_FOUND` | 404 |
| `ERR_COACH_NOT_FOUND` | 404 |
| `ERR_PLAN_NOT_FOUND` | 404 |
| `ERR_ORDER_NOT_FOUND` | 404 |
| `ERR_DELIVERABLE_NOT_FOUND` | 404 |
| `ERR_REVISION_NOT_FOUND` | 404 |
| `ERR_SESSION_NOT_FOUND` | 404 |
| `ERR_CLAIM_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ORDER_NOT_IN_PRODUCTION` | 409 |
| `ERR_DELIVERABLE_NOT_DRAFTED` | 409 |
| `ERR_REVISION_NOT_WITHDRAWABLE` | 409 |
| `ERR_SESSION_NOT_SCHEDULED` | 409 |
| `ERR_COACH_INACTIVE` | 409 |
| `ERR_COACH_SLOT_CONFLICT` | 409 |
| `ERR_CLIENT_SLOT_CONFLICT` | 409 |
| `ERR_ORDER_NOT_DELIVERED` | 409 |
| `ERR_GUARANTEE_NOT_OFFERED` | 409 |
| `ERR_CLAIM_NOT_ELIGIBLE` | 409 |
| `ERR_CLAIM_ALREADY_EXISTS` | 409 |
| `ERR_STALE_VERSION` | 412 |
