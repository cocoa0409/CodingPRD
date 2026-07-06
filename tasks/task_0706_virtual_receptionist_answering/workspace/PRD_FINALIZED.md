# Virtual Receptionist API — Product Requirements Document

## 1. Introduction

The Virtual Receptionist & Answering Service powers a managed call-handling business in the mold of Ruby or Smith.ai: a shared pool of live human receptionists answers inbound calls on behalf of many client businesses, captures messages and qualified leads, books appointments against each client's calendar, and pushes the resulting captures into the client's CRM. This API is the operational backbone behind that service. It models the full inbound-call lifecycle — from the moment a call arrives, through spam screening, routing to an eligible agent, the live conversation, wrap-up, and billing — alongside the configuration that governs how calls are answered and the financial ledger that tracks what each client owes.

Two characteristics make this domain demanding. First, a call advances along **two independent state axes at once**: a handling axis that tracks the human-facing progress of the conversation, and a billing axis that tracks how the call is charged and whether that charge is later disputed and adjusted. The two axes evolve on their own schedules and must be reasoned about separately. Second, money flows through a per-account ledger whose totals are *provisional* while a billing period is open — recomputed on every read to preview in-flight usage — but become *authoritative and frozen* at the moment a call completes or a period closes. Crossing usage thresholds cascades into the client account's posture, suspending service and even cancelling outstanding appointments when overage runs past a hard ceiling. Because the platform operates a shared agent pool and a logical test clock, routing decisions and time-dependent classifications must be fully deterministic.

This document specifies every entity, state transition, calculation, validation, endpoint, and error the implementation must honor. Section 2 fixes the system-wide contracts; Section 3 narrates the business workflows in which the detailed rules live; Sections 4 and 5 summarize the endpoint surface and the error catalogue.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply across the entire API. Every resource is a peer collection mounted under the `/va` prefix; relationships between resources are carried as foreign-key fields in request and response bodies rather than as nested URL paths.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header is rejected with `ERR_UNAUTHENTICATED`. The system recognizes exactly three roles, spelled precisely as follows: `PlatformAdmin`, `AccountOwner`, and `Receptionist`. When an authenticated role is not permitted to perform a given operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The three roles differ in how `X-User-ID` ties back to persisted data:

- When `X-User-Role` is `AccountOwner`, `X-User-ID` is the `id` of the acting `ClientAccount`. Ownership checks on any resource that references a `ClientAccount` compare the resource's `account_id` to `X-User-ID`. An `AccountOwner` may therefore only act on its own scripts, spam rules, calendar slots, appointments, calls, billing periods, and CRM handoffs; acting on a resource belonging to another account is rejected with `ERR_NOT_RESOURCE_OWNER`.
- When `X-User-Role` is `Receptionist`, `X-User-ID` is the `id` of the acting `Receptionist`. Ownership checks on a call compare the call's `answered_by_receptionist_id` to `X-User-ID` where ownership applies — for example, the agent who answered a call is the one who may start, wrap, complete, or escalate it. A mismatch is rejected with `ERR_NOT_RESOURCE_OWNER`.
- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit but does not compare it to any entity's `id`; a `PlatformAdmin` is not ownership-scoped and operates across all accounts.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless an endpoint states otherwise, list results are sorted by `created_at` in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

Every resource carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp expressed in ISO 8601 UTC with three fractional digits. Most resources additionally carry an `updated_at` timestamp (same format, refreshed on every mutation) and an integer `version` that begins at its initial value and increments by one on every mutation that changes the resource. These two fields support optimistic concurrency control as described in §2.6.

One entity is the exception. A `ServicePlan` is an immutable price card: once created it is never modified, so it carries only `id` and `created_at`. A `ServicePlan` has no `updated_at` field and no `version` field. Every other entity in this system — `ClientAccount`, `CallScript`, `SpamRule`, `Receptionist`, `AvailabilityWindow`, `CalendarSlot`, `Call`, `Message`, `Escalation`, `CrmHandoff`, `Appointment`, and `BillingPeriod` — carries the full set of `id`, `created_at`, `updated_at`, and `version`.

### 2.5. Derived Fields and Reconciliation

Several fields are *computed* rather than supplied by clients, and the server keeps them reconciled with the facts they summarize. Whenever a computed field changes as a side effect of an operation, the owning resource is mutated: its `updated_at` is refreshed and its `version` increments. This applies to a `ClientAccount`'s `open_call_count` and `lifetime_calls_answered`, to a `CalendarSlot`'s `booked_count` and `available_count`, to a `Receptionist`'s `active_call_count`, to a `Call`'s `duration_seconds`, `spam_score`, `billed_units`, and `charge_cents`, and to a `BillingPeriod`'s `consumed_units`, `overage_units`, and `overage_charge_cents`. When one operation legitimately mutates more than one resource — for instance a call completion that both freezes the call's charge and advances its billing period and possibly its account posture — every affected resource is independently reconciled and version-bumped.

### 2.6. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control against a parent resource's `version`. In each case the client must supply, as a non-optional field, the `version` it last observed on the parent; if that value no longer matches the parent's current `version`, the write is refused because the client is acting on a stale view.

- Booking a new appointment must carry `expected_slot_version` matching the target `CalendarSlot`'s current `version`. The slot's `version` advances whenever a booking consumes one of its capacity units, so a booking carrying an earlier value has a stale picture of remaining capacity and is rejected with `ERR_STALE_SLOT_VERSION` (HTTP 412).
- Adjusting a disputed call must carry `expected_call_version` matching the target `Call`'s current `version`. A call's `version` advances whenever its billing or handling fields are mutated, so an adjust carrying an earlier value is operating on a stale call and is rejected with `ERR_STALE_CALL_VERSION` (HTTP 412).
- Beginning the close-out of a billing period must carry `expected_period_version` matching the target `BillingPeriod`'s current `version`; a mismatch is rejected with `ERR_STALE_PERIOD_VERSION` (HTTP 412).

No other endpoint accepts or requires a version field.

### 2.7. Validation Order

When more than one rule could reject a request, the checks are applied in a fixed priority order, and the first failing check determines the error returned. The order is: (1) presence of the authentication headers (`ERR_UNAUTHENTICATED`); (2) whether the role is permitted for the operation (`ERR_FORBIDDEN_ROLE`); (3) existence of every referenced resource id, both path identifiers and foreign-key body fields, validated left-to-right (`ERR_NOT_FOUND`); (4) ownership of the targeted resource by the acting entity-backed user (`ERR_NOT_RESOURCE_OWNER`); (5) the optimistic-concurrency version match where one applies (the stale-version errors of §2.6); (6) that the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`); (7) that the acting account is not suspended for answer, booking, and confirm operations (`ERR_ACCOUNT_SUSPENDED`); and then the domain-specific business checks described throughout §3. Required-field presence and enum/range validity (`ERR_INVALID_REQUEST`) is the lowest-priority check, applied last. This ordering guarantees, for example, that a request from an unauthenticated client is never first rejected for a missing body field.

### 2.8. Nested and Referenced Resource Validation

Every identifier a request references — whether it appears in the URL path or as a foreign-key field in the body — must resolve to an existing resource. These are validated left-to-right in the order they appear, and the first identifier that does not resolve produces `ERR_NOT_FOUND` immediately, before any later identifier or business rule is consulted. For instance, booking an appointment names both a `ClientAccount` (via `account_id`) and a `CalendarSlot` (via `slot_id`); if the account does not exist the booking fails on the account before the slot is ever examined.

### 2.9. Monetary Precision and Minute Rounding

All money in this system is expressed in whole integer cents — there are no fractional cents anywhere, and every charge field holds an integer. Per-minute call billing rounds each individual call's duration **up** to whole minutes before it is added to the period's usage: a call's billable minutes are its duration in seconds divided by sixty and rounded up to the next whole number, where sixty seconds make one minute. This per-call rounding happens first, on each call in isolation; the system never sums raw seconds across multiple calls and rounds the total once. A call with zero duration rounds up to zero minutes and therefore bills nothing. Tier boundaries in overage pricing are evaluated on the integer unit index using an at-or-above comparison, never on fractional quantities.

### 2.10. The Logical Clock

Time in this system is driven by a logical clock rather than wall-clock time. At server startup the clock reads exactly `2026-03-01T00:00:00Z`, and until it is explicitly set it remains at that default and never falls back to real time. A `PlatformAdmin` may advance the clock to any absolute UTC instant by supplying a `to_iso8601` value; the response reports the new `current_utc`, its `epoch_seconds`, and its `minute_of_day`. This clock is the single source of truth for the minute-of-day at which a call is received (driving after-hours classification), the epoch-seconds stamped when a call begins and ends its live segment, and the instant against which appointment completion eligibility is judged.

## 3. Business Logic & Workflows

### 3.1. Plans, Accounts, and the Opening of a Billing Period

The commercial relationship begins with a **ServicePlan**, an immutable price card created by a `PlatformAdmin`. A plan is created with a `name` and a `billing_model`, which is either `PER_MINUTE` or `PER_CALL`. A `PER_MINUTE` plan bills the rounded duration of each answered call and carries a monthly `included_minutes` allowance; a `PER_CALL` plan bills a flat unit per answered call and carries a monthly `included_calls` allowance. The allowance not relevant to the model defaults to zero — `included_minutes` defaults to 0 and `included_calls` defaults to 0, each constrained to be zero or greater. A plan that mixes the two — a `PER_MINUTE` plan declaring a positive `included_calls`, or a `PER_CALL` plan declaring a positive `included_minutes` — is misconfigured and rejected with `ERR_PLAN_MISCONFIGURED`. Every plan carries a flat monthly `base_fee_cents` (zero or greater) and overage pricing inputs: `overage_rate_cents` is the cents charged per overage unit within the first tier (zero or greater), `overage_tier2_threshold` is the overage-unit count at or above which the second-tier marginal rate applies (defaulting to 100, at least 1), and `overage_tier2_rate_cents` is the cents per overage unit at or beyond that threshold (zero or greater). A plan also declares `hard_cap_overage_cents`, the overage ceiling at or above which the account is suspended (at least 1; a value below 1 is itself an `ERR_PLAN_MISCONFIGURED`). Finally, `minute_rounding` declares how per-call seconds are rounded for `PER_MINUTE` billing; in this version it may only be `CEIL_MINUTE`, which rounds each call's seconds up to whole minutes, and it defaults to `CEIL_MINUTE`.

A `PlatformAdmin` then creates a **ClientAccount** for a client business, supplying a `business_name`, the `plan_id` of the subscribed plan (pinned at creation), and an optional `default_language` that is either `EN` or `ES` and defaults to `EN`. A newly created account starts with `status` of `ACTIVE`. Creating an account also opens the account's first **BillingPeriod**: a period whose `period_index` is 0, whose `plan_id` snapshots the account's plan, and whose `included_units` is pinned from that plan — `included_minutes` for a `PER_MINUTE` plan, `included_calls` for a `PER_CALL` plan. The new period's `status` is `OPEN`, and the account's `current_period_id` is set to point at it. An account exposes two computed counters: `open_call_count`, the number of the account's own calls whose handling is not yet terminal (that is, not in `COMPLETED`, `ABANDONED`, or `SCREENED_OUT`), and `lifetime_calls_answered`, the cumulative count of the account's calls that ever reached the `IN_PROGRESS` handling stage. The account's `status` may be `ACTIVE`, `DELINQUENT`, or `SUSPENDED`, and is driven entirely by billing posture as described in §3.9.

### 3.2. Call Scripts and Screening Configuration

Before any call can be answered an account must publish a **CallScript**, which an `AccountOwner` authors against its own account via `account_id`. A script supplies an English greeting in `greeting_en` and an optional Spanish greeting in `greeting_es` (defaulting to the empty string). It declares the business day with two minute-of-day integers: `business_open_minute`, the minute after UTC midnight at which business hours open (inclusive, in the range 0 through 1439), and `business_close_minute`, the minute at which they close (exclusive, in the range 1 through 1440 and strictly greater than `business_open_minute`). A call received at or after the close minute, or before the open minute, is after-hours. The script also declares `after_hours_action`, either `VOICEMAIL` or `OVERFLOW` (defaulting to `VOICEMAIL`), governing what happens to after-hours inbound; `overflow_action`, either `QUEUE` or `VOICEMAIL` (defaulting to `QUEUE`), governing what happens during business hours when no receptionist is available; and `escalation_threshold_seconds`, the running duration at or beyond which an in-progress call becomes eligible for escalation (defaulting to 600, at least 1). A script's `status` begins at `DRAFT`; only a `PUBLISHED` script routes live calls, and a `RETIRED` script no longer does.

Publishing is performed by an `AccountOwner` and moves a script from `DRAFT` to `PUBLISHED`. Because an account may have at most one live script, publishing a draft also retires the account's previously `PUBLISHED` script, moving that prior script to `RETIRED`. This is the bridge that makes call intake possible: at intake the system resolves the account's single `PUBLISHED` script, and if the account has none, intake fails with `ERR_NO_PUBLISHED_SCRIPT`.

Screening is configured by a **SpamRule**, which an `AccountOwner` or `PlatformAdmin` creates against an account via `account_id`. A rule carries `blocked_area_codes`, an array of three-character area-code strings auto-screened on inbound (defaulting to an empty array); `spam_score_threshold`, the provisional spam score at or above which a call is screened out before it is ever answered (defaulting to 70, in the range 0 through 100); and `anonymous_penalty`, the points added to a call's spam score when the caller's number is withheld (defaulting to 40, in the range 0 through 100). A rule's `status` is `ACTIVE` or `DISABLED`, defaulting to `ACTIVE`; only an `ACTIVE` rule screens.

### 3.3. The Live Agent Pool, Availability, and Status

Receptionists form a **shared pool** that is not scoped to any single account — any eligible agent may answer any account's call. A `PlatformAdmin` creates a **Receptionist** with a `display_name`, a non-empty `languages` array whose values are drawn from `EN` and `ES`, and an optional `max_concurrent_calls` capacity ceiling on simultaneous in-progress calls (defaulting to 1, at least 1). A receptionist's `status` begins at `OFFLINE` and may move among `OFFLINE`, `AVAILABLE`, and `BUSY`; the computed `active_call_count` tracks how many of the agent's calls are currently `IN_PROGRESS`.

Coverage is declared through **AvailabilityWindow** records, each owned by its agent via `receptionist_id`. A receptionist (or a `PlatformAdmin`) adds a window with a `start_minute` (minutes after UTC midnight, inclusive, 0 through 1439) and an `end_minute` (the inclusive endpoint, 1 through 1440 and strictly greater than `start_minute`); a window is the closed interval from `start_minute` to `end_minute`. Windows may be listed filtered by their `receptionist_id`. A new window must not overlap an existing `ACTIVE` window for the same receptionist, where touching endpoints are permitted — one window may end at exactly the minute another begins — but any genuine overlap is rejected with `ERR_WINDOW_OVERLAP`. A window's `status` is `ACTIVE` or `CANCELLED`, defaulting to `ACTIVE`.

A receptionist becomes reachable by going online, which transitions `status` from `OFFLINE` to `AVAILABLE`; this requires the agent to have at least one `ACTIVE` `AvailabilityWindow`, and an attempt without one is rejected with `ERR_NO_AVAILABILITY_WINDOW`. Going offline transitions `status` from `AVAILABLE` to `OFFLINE`, but only when the agent has no calls in progress (`active_call_count` equal to 0); otherwise the request is rejected with `ERR_RECEPTIONIST_BUSY`. The other two status changes are system-driven: when a call enters the live stage and the agent's `active_call_count` reaches `max_concurrent_calls`, the agent moves from `AVAILABLE` to `BUSY`; when a call leaves the live stage and `active_call_count` falls below `max_concurrent_calls`, the agent moves from `BUSY` back to `AVAILABLE`.

### 3.4. Intake: Receiving and Screening an Inbound Call

A **Call** enters the system when a `PlatformAdmin` or `Receptionist` submits intake for a given `account_id`, optionally supplying the `caller_id` (the caller's phone number, defaulting to the empty string when withheld or anonymous) and the `requested_language`, either `EN` or `ES` (defaulting to `EN`). Intake performs several actions atomically. It resolves the account's single `PUBLISHED` `CallScript` into the call's `script_id`; if no published script exists, intake fails with `ERR_NO_PUBLISHED_SCRIPT`. It stamps `received_minute` from the logical clock's minute-of-day. It computes `is_after_hours`, which is true exactly when `received_minute` falls outside the half-open business window — that is, when it is below the script's `business_open_minute` or at or above its `business_close_minute`.

Intake also runs **provisional spam screening** to compute the call's `spam_score`. Starting from zero, the score adds the matched `ACTIVE` rule's `anonymous_penalty` when the `caller_id` is the empty string, and adds 50 points when the caller's area code appears in the rule's `blocked_area_codes`; the result is then capped at a ceiling of 100. If an `ACTIVE` `SpamRule` exists for the account and either the caller's area code is among the blocked codes or the provisional score is at or above the rule's `spam_score_threshold`, the call is screened out: its `handling_status` is set directly to `SCREENED_OUT`, a terminal state, no receptionist is consumed, and its `billing_status` stays `UNBILLED` so the call is never charged. A screened-out call does not increment the account's `open_call_count`.

When the call survives screening, its initial handling is decided next. A call that is after-hours under a script whose `after_hours_action` is `OVERFLOW` is placed directly into `OVERFLOW`; otherwise the call begins life in `RINGING`. In either of these non-screened cases the account's `open_call_count` increments. The `requested_language` recorded here is the language the routing step must match an agent against. A call's `handling_status` is one of `RINGING`, `ANSWERED`, `IN_PROGRESS`, `WRAP_UP`, `COMPLETED`, `OVERFLOW`, `SCREENED_OUT`, or `ABANDONED`; its terminal handling states are `COMPLETED`, `SCREENED_OUT`, and `ABANDONED`.

### 3.5. Answering and Routing

Answering a call is a `Receptionist` action that runs the **answer-routing selector** to pick which agent takes it. The candidate set is every receptionist in the shared pool whose `status` is `AVAILABLE`, whose `active_call_count` is strictly below their `max_concurrent_calls`, and whose `languages` include the call's `requested_language`. Candidates are ranked deterministically: primarily by `active_call_count` ascending (the least-loaded agent first); ties broken by `max_concurrent_calls` descending (more headroom first); and any remaining ties broken by `created_at` ascending (the oldest receptionist first). The first candidate in that ordering is selected; the ordering never falls back to comparing `id`.

A successful answer requires that the account is `ACTIVE`, the call is currently `RINGING` (and was not screened out), the selected agent is `AVAILABLE` with capacity, and that agent's `languages` include the call's `requested_language`. On success the call moves from `RINGING` to `ANSWERED` and its `answered_by_receptionist_id` is set to the selected agent; the agent's `active_call_count` is not yet changed, since that increment happens when the live conversation begins. An attempt to answer when the account is `SUSPENDED` is rejected with `ERR_ACCOUNT_SUSPENDED`. An attempt to answer an after-hours call that the script does not make routable is rejected with `ERR_AFTER_HOURS_BLOCKED`. If a candidate is found but no eligible agent speaks the requested language with capacity, the answer is rejected with `ERR_NO_LANGUAGE_MATCH`.

Routing has a deliberate non-error fallback. During business hours, if the candidate set is empty, the call is not rejected; instead it transitions to `OVERFLOW`, leaving `answered_by_receptionist_id` null and the call still open (its account's `open_call_count` is unchanged because the call remains open). The script's `overflow_action` — `QUEUE` or `VOICEMAIL` — describes the disposition of such an overflowed call. Only when an answer is attempted during business hours, the candidate pool is empty, and that overflow disposition is unavailable is the answer rejected with `ERR_NO_RECEPTIONIST_AVAILABLE`. A call already sitting in `OVERFLOW` can still be answered later: answering an `OVERFLOW` call runs the same eligibility requirements (account `ACTIVE`, a selected agent that is `AVAILABLE` with capacity and speaks the `requested_language`) and, on success, moves it from `OVERFLOW` to `ANSWERED` with `answered_by_receptionist_id` set. A `RINGING` call that the caller drops can be marked abandoned by a `Receptionist` or `PlatformAdmin`, moving it from `RINGING` to `ABANDONED` and decrementing the account's `open_call_count`.

### 3.6. The Live Conversation: Start, Wrap, and Complete

Once a call is `ANSWERED`, the answering agent starts the live conversation, moving it from `ANSWERED` to `IN_PROGRESS`. Starting requires that `answered_by_receptionist_id` is set. On start, `start_second` is stamped from the logical clock's epoch-seconds, the answering receptionist's `active_call_count` increments by one (and the agent moves to `BUSY` if that brings `active_call_count` up to `max_concurrent_calls`), and the account's `lifetime_calls_answered` increments by one.

Ending the conversation moves the call from `IN_PROGRESS` to `WRAP_UP`. On wrap, `end_second` is stamped from the logical clock and `duration_seconds` is recomputed as the larger of zero and `end_second` minus `start_second`. The spam score is now **finalized**: the final score is computed exactly like the provisional score (zero, plus `anonymous_penalty` if `caller_id` is empty, plus 50 if the area code is blocked, capped at 100) but, if the call ever reached `IN_PROGRESS` — evidence that a human engaged and the call was legitimate — 30 points are subtracted with a floor of zero. Wrapping also decrements the answering receptionist's `active_call_count` by one and returns the agent from `BUSY` to `AVAILABLE` if it had been `BUSY`.

Completing the call moves it from `WRAP_UP` to `COMPLETED` and is the moment billing occurs; it requires the call to be in `WRAP_UP` with `billing_status` still `UNBILLED`. On completion the per-call charge is computed (see §3.7) against the account's `OPEN` `BillingPeriod`, producing the call's `billed_units` and `charge_cents`; the call's `billing_status` flips from `UNBILLED` to `BILLED`, freezing `charge_cents` and `billed_units` onto the call; the period's `consumed_units` increases by the call's `billed_units` and its `overage_units` and `overage_charge_cents` are recomputed under the final overage variant; and the account's `open_call_count` decrements. Completion then evaluates the billing cascade on the account posture as described in §3.9.

A `Receptionist` may escalate a call that is in progress. Escalation creates an **Escalation** event against the call's `call_id` with a `reason` that is one of `LONG_RUNNING`, `CALLER_REQUEST`, or `LANGUAGE`. The escalation routing selector chooses a *senior* agent — the same eligibility and ranking as ordinary answer-routing, but additionally requiring the candidate's `max_concurrent_calls` to be at least 2 — and records it in `escalated_to_receptionist_id`. If a senior agent is selected the escalation's `status` is `ASSIGNED`; if the senior candidate set is empty the escalation stays `QUEUED` with `escalated_to_receptionist_id` null. An escalation's `status` is `QUEUED`, `ASSIGNED`, or `RESOLVED`. A call becomes escalation-eligible once its running duration reaches the script's `escalation_threshold_seconds`. Resolving an escalation moves it to `RESOLVED` from either `QUEUED` or `ASSIGNED`.

### 3.7. Charging a Call

When a call completes, its charge is computed in two parts. First, the **billable units** for this single call depend on the plan's `billing_model`. Under `PER_CALL`, `billed_units` is exactly 1 regardless of duration, and the plan's `included_calls` allowance applies. Under `PER_MINUTE`, `billed_units` is this call's `duration_seconds` divided by sixty and rounded up to the next whole minute; a zero-second call yields zero units and bills nothing. This per-call rounding is performed before the units are added to the period — the system never sums raw seconds across calls.

Second, the **cents charged for this call** are the *marginal* contribution of these units to the period's tiered overage charge. The system evaluates the period's tiered overage charge twice: once on the period's `consumed_units` as they stand immediately before this call is billed, and once on `consumed_units` plus this call's `billed_units`. The call's `charge_cents` is the larger of zero and the second figure minus the first. In other words, a call whose units fall entirely within the included allowance contributes nothing, while a call whose units push the period into (or further into) overage contributes exactly the overage cents that its units add.

### 3.8. Tiered Overage and Provisional-versus-Final Accounting

A **BillingPeriod** accumulates an account's usage and computes its overage charge from two-tier marginal pricing. The period's `overage_units` are the larger of zero and `consumed_units` minus `included_units`. Those overage units are split across two tiers using the plan's `overage_tier2_threshold` as the dividing line: the first-tier units are the smaller of the total overage units and one less than the threshold (the units strictly below the threshold index), and the second-tier units are the larger of zero and the overage units minus that same quantity of one less than the threshold (the units at or above the threshold index). The `overage_charge_cents` is then the first-tier units multiplied by the plan's `overage_rate_cents` plus the second-tier units multiplied by the plan's `overage_tier2_rate_cents`. All figures are whole cents, and the default tier-2 threshold is 100 overage units when a plan does not specify otherwise.

This overage figure is computed in two variants that differ only in which calls feed `consumed_units`:

- The **provisional** variant is what a reader sees on an `OPEN` period — both when fetching the period directly and through its overage summary. It counts the `billed_units` of all `BILLED` and `ADJUSTED` calls *and additionally adds a forward-looking estimate for every one of the account's calls currently `IN_PROGRESS` or `WRAP_UP`*. The estimate for an in-flight call is the same per-call rule applied to its elapsed time: under `PER_MINUTE`, its elapsed seconds divided by sixty and rounded up to a whole minute; under `PER_CALL`, exactly 1. Because it anticipates in-flight calls, the provisional figure is an upper-bound preview that may exceed the eventual final charge.
- The **final** variant is the authoritative figure persisted on the period. It counts `billed_units` *only* from calls whose `billing_status` is `BILLED` or `ADJUSTED`, excluding all in-flight calls. The final variant is what is computed as a side effect of a call completing, as a side effect of a call adjustment, and when a billing period is closed.

The overage summary read returns, for an `OPEN` period, the provisional breakdown: `consumed_units`, `overage_units`, the first-tier unit count as `tier1_units`, the second-tier unit count as `tier2_units`, the `overage_charge_cents`, and a `variant` label identifying which variant produced the figures.

### 3.9. Account Posture: Delinquency, Suspension, and Reinstatement

An account's `status` is a compound posture bubbled up automatically from its `OPEN` billing period's overage; clients never set it directly. The relevant ceiling is the plan's `hard_cap_overage_cents`. When a call completion (or any final recompute) leaves the open period with overage, the cascade is evaluated: if the period's `overage_charge_cents` is at or above `hard_cap_overage_cents`, the account is suspended; otherwise, if `overage_units` is greater than zero, the account is made delinquent.

Concretely, the transitions are these. From `ACTIVE`, the account moves to `DELINQUENT` when the open period's `overage_units` is greater than zero while its `overage_charge_cents` is still below the hard cap — delinquency is a soft posture, so new bookings are still allowed and live answering continues. From either `ACTIVE` or `DELINQUENT`, the account moves to `SUSPENDED` when the open period's `overage_charge_cents` reaches or exceeds the hard cap. Suspension is the protective posture: it cascades to **cancel every one of the account's appointments that is in `REQUESTED`, `CONFIRMED`, or `RESCHEDULE_REQUESTED`**, and each such cancellation decrements its `CalendarSlot`'s `booked_count` and recomputes that slot's `available_count`. While suspended, new answer and booking operations are rejected with `ERR_ACCOUNT_SUSPENDED`.

Suspension can be undone only by a downward revision of overage, which arises from a call adjustment (see §3.10) or a period close-out. If a recompute drops the open period's `overage_charge_cents` back below the hard cap while `overage_units` is still greater than zero, the account is reinstated from `SUSPENDED` to `DELINQUENT` and live answering resumes — but appointments cancelled during suspension are **not** restored. If a recompute clears overage entirely (`overage_units` equal to zero), a `DELINQUENT` account returns to `ACTIVE`. The same clear-to-`ACTIVE` rule is applied when a period finalizes: if the period that just closed had `overage_units` of zero, the account's `status` is set to `ACTIVE`.

### 3.10. Disputes and Adjustments: The Billing Axis

The billing axis of a call evolves independently of its handling axis. A completed call's `billing_status` is `BILLED`. An `AccountOwner` may dispute a billed call, moving its `billing_status` from `BILLED` to `DISPUTED`; this is permitted only while the call's `BillingPeriod` is `OPEN`, and it makes no ledger change yet — it merely flags the call for adjustment review. A dispute or other usage operation targeting a non-`OPEN` period is rejected with `ERR_PERIOD_NOT_OPEN`.

A `PlatformAdmin` then adjusts a disputed call, moving its `billing_status` from `DISPUTED` to `ADJUSTED` (a terminal billing state). The adjust supplies the new `adjusted_units` and, as the optimistic-concurrency guard of §2.6, `expected_call_version` matching the call's current `version`. On adjust, the call's `billed_units` is set to `adjusted_units` and its `charge_cents` is recomputed at the adjusted unit count; the call's `version` increments by one. The period's ledger is then compensated so its minutes-ledger invariant holds: `consumed_units` is reduced by the difference between the old `billed_units` and the `adjusted_units`, and `overage_units` and `overage_charge_cents` are recomputed under the final variant. The adjust then re-evaluates the account posture cascade in the reverse direction: if the recomputed `overage_charge_cents` is below the hard cap while `overage_units` remains greater than zero, a suspended account is reinstated to `DELINQUENT`; if `overage_units` reaches zero, the account returns to `ACTIVE`.

### 3.11. Closing and Rolling Over a Billing Period

A `PlatformAdmin` closes out a billing period in two steps. The first step begins the close: it moves the period from `OPEN` to `PENDING_CLOSE`, finalizes `overage_charge_cents` under the final variant, and accepts no further usage. Beginning the close requires the period to be `OPEN`, carries the `expected_period_version` optimistic-concurrency guard of §2.6, and is blocked if any of the period's calls is still in `DISPUTED` billing status — an open dispute prevents close-out and the attempt is rejected with `ERR_OPEN_DISPUTE`. Beginning the close increments the period's `version` by one.

The second step finalizes the period: it moves it from `PENDING_CLOSE` to `CLOSED` (a terminal state). Finalizing opens a fresh `OPEN` `BillingPeriod` for the account with `period_index` one greater than the closed period, and repoints the account's `current_period_id` to that new period. As noted in §3.9, if the period that just closed had `overage_units` of zero, the account's `status` is set to `ACTIVE` as part of finalization.

### 3.12. Calendar Slots and the Appointment Lifecycle

An `AccountOwner` opens bookable capacity by creating a **CalendarSlot** against its own account via `account_id`. A slot defines a bookable day-window with `window_start` (ISO 8601 UTC, inclusive) and `window_end` (ISO 8601 UTC, exclusive, strictly after `window_start`). It carries a `buffer_minutes` value, the mandatory clear gap required between two appointments in the slot (defaulting to 0, zero or greater), and a `capacity`, the maximum number of non-cancelled appointments the slot may hold (defaulting to 1, at least 1). The slot exposes a computed `booked_count` — the number of its appointments in `REQUESTED`, `CONFIRMED`, `RESCHEDULE_REQUESTED`, or `COMPLETED` status — and a computed `available_count` equal to `capacity` minus `booked_count`, never falling below zero. A slot's `status` is `OPEN` or `CLOSED`, defaulting to `OPEN`; a `CLOSED` slot rejects new bookings. An `AccountOwner` may close a slot, moving its `status` from `OPEN` to `CLOSED`.

Booking creates an **Appointment**. The booking is made by an `AccountOwner` or `Receptionist` and names the `account_id`, the `slot_id` to book into, the appointment's `start_at` and `end_at` (ISO 8601 UTC, with `end_at` strictly after `start_at`; the appointment occupies the half-open interval from `start_at` up to but not including `end_at`), the `expected_slot_version` optimistic-concurrency guard, and an optional `origin_call_id` linking the booking back to the call that produced it (defaulting to the empty string for direct bookings). A new appointment starts in `REQUESTED`. Booking is subject to several checks, applied in the order listed and the first failing check determining the error returned: the account must not be `SUSPENDED` (else `ERR_ACCOUNT_SUSPENDED`); the slot's `version` must match `expected_slot_version` (else `ERR_STALE_SLOT_VERSION`); the slot must be `OPEN` with `available_count` greater than zero (else `ERR_SLOT_FULL`); and then the new interval must not overlap any other non-cancelled appointment in the slot once `buffer_minutes` of clear gap is honored (else `ERR_SLOT_OVERLAP`). The slot-capacity check thus precedes the overlap check, so a booking that is both into a full slot and overlapping yields `ERR_SLOT_FULL`. On a successful booking the slot's `booked_count` increments, its `available_count` is recomputed, and the slot's `version` increments by one.

The appointment then follows a cyclic lifecycle. An `AccountOwner` confirms a `REQUESTED` appointment, moving it to `CONFIRMED`; confirmation requires the account to be `ACTIVE` or `DELINQUENT` and the slot to be `OPEN`. A confirmed appointment may be rescheduled by an `AccountOwner` to a new `start_at` and `end_at`, moving it from `CONFIRMED` to `RESCHEDULE_REQUESTED`; rescheduling requires that `reschedule_count` is below 3 (else `ERR_RESCHEDULE_LIMIT`) and that the new interval does not overlap any other non-cancelled appointment in the slot honoring `buffer_minutes` (else `ERR_SLOT_OVERLAP`). On reschedule, `start_at` and `end_at` are updated to the new interval and `reschedule_count` increments by one. Re-confirming moves the appointment from `RESCHEDULE_REQUESTED` back to `CONFIRMED` (requiring the account to be `ACTIVE` or `DELINQUENT`), closing the loop; the cycle between `CONFIRMED` and `RESCHEDULE_REQUESTED` is bounded by the rule that `reschedule_count` stays below 3.

A confirmed appointment is completed by an `AccountOwner` only once the logical clock has reached its `end_at` (the clock's epoch is at or beyond `end_at`), moving it from `CONFIRMED` to `COMPLETED`; completion does not change the slot's `booked_count` or `available_count`, since a completed appointment still counts as booked. A confirmed appointment may instead be marked a no-show by an `AccountOwner`, again only once the clock has reached `end_at`, moving it from `CONFIRMED` to `NO_SHOW` and decrementing the slot's `booked_count` with `available_count` recomputed, freeing the capacity. An appointment may be cancelled by an `AccountOwner` from `REQUESTED`, `CONFIRMED`, or `RESCHEDULE_REQUESTED`, moving it to `CANCELLED`; each cancellation decrements the slot's `booked_count` and recomputes its `available_count` as `capacity` minus `booked_count`. An appointment's `status` is one of `REQUESTED`, `CONFIRMED`, `RESCHEDULE_REQUESTED`, `COMPLETED`, `CANCELLED`, or `NO_SHOW`, with `COMPLETED`, `CANCELLED`, and `NO_SHOW` terminal.

### 3.13. Message Capture and CRM Handoff

During or after a call, a `Receptionist` captures a **Message** against the call's `call_id`, recording the `caller_name`, a `callback_number`, the `body` of the message or lead detail, and an `is_lead` flag marking whether it is a qualified sales lead (defaulting to false). A message's `status` is `NEW` or `HANDED_OFF`, defaulting to `NEW`.

When the captures are ready to push, an `AccountOwner` creates a **CrmHandoff** against the call's `call_id` with a `crm_target` that is one of `SALESFORCE`, `HUBSPOT`, or `ZOHO`. The handoff flips every `NEW` `Message` on that call to `HANDED_OFF` and records how many it flipped in `messages_pushed`; the handoff's `status` is `PUSHED` on success or `FAILED`. Each transition to terminal handling on a call, and the transitions described throughout this section, independently mutate the resources they touch, refreshing `updated_at` and incrementing `version`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`. Operations that modify an existing resource — including state transitions and computed reads — return `200 OK`. All list and get reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/va/_clock/set_current_utc` | Set the logical clock to an absolute UTC instant | PlatformAdmin |
| POST | `/va/service-plans` | Create an immutable service plan | PlatformAdmin |
| GET | `/va/service-plans/{planId}` | Get a service plan | PlatformAdmin, AccountOwner |
| GET | `/va/service-plans` | List service plans | PlatformAdmin, AccountOwner |
| POST | `/va/accounts` | Create a client account; opens its first billing period | PlatformAdmin |
| GET | `/va/accounts/{accountId}` | Get a client account with computed posture and counts | PlatformAdmin, AccountOwner |
| GET | `/va/accounts` | List client accounts | PlatformAdmin |
| POST | `/va/call-scripts` | Create a DRAFT call script for an account | AccountOwner |
| GET | `/va/call-scripts/{scriptId}` | Get a call script | PlatformAdmin, AccountOwner |
| GET | `/va/call-scripts` | List call scripts | PlatformAdmin, AccountOwner |
| POST | `/va/call-scripts/{scriptId}/publish` | Publish a DRAFT script; retires the prior PUBLISHED script | AccountOwner |
| POST | `/va/spam-rules` | Create a screening rule for an account | AccountOwner, PlatformAdmin |
| GET | `/va/spam-rules/{spamRuleId}` | Get a spam rule | PlatformAdmin, AccountOwner |
| GET | `/va/spam-rules` | List spam rules | PlatformAdmin, AccountOwner |
| POST | `/va/receptionists` | Create a receptionist (shared pool) | PlatformAdmin |
| GET | `/va/receptionists/{receptionistId}` | Get a receptionist | PlatformAdmin, Receptionist, AccountOwner |
| GET | `/va/receptionists` | List receptionists | PlatformAdmin, Receptionist |
| POST | `/va/receptionists/{receptionistId}/go-online` | Bring a receptionist online | Receptionist |
| POST | `/va/receptionists/{receptionistId}/go-offline` | Take a receptionist offline | Receptionist |
| POST | `/va/receptionists/{receptionistId}/availability-windows` | Add a coverage window for a receptionist | Receptionist, PlatformAdmin |
| GET | `/va/availability-windows/{windowId}` | Get an availability window | PlatformAdmin, Receptionist |
| GET | `/va/availability-windows` | List availability windows | PlatformAdmin, Receptionist |
| POST | `/va/calendar-slots` | Create a bookable calendar slot for an account | AccountOwner |
| GET | `/va/calendar-slots/{slotId}` | Get a calendar slot with computed counts | PlatformAdmin, AccountOwner |
| GET | `/va/calendar-slots` | List calendar slots | PlatformAdmin, AccountOwner |
| POST | `/va/calendar-slots/{slotId}/close` | Close a slot to new bookings | AccountOwner |
| POST | `/va/calls` | Receive an inbound call; screen and classify | PlatformAdmin, Receptionist |
| GET | `/va/calls/{callId}` | Get a call with computed fields | PlatformAdmin, AccountOwner, Receptionist |
| GET | `/va/calls` | List calls | PlatformAdmin, AccountOwner, Receptionist |
| POST | `/va/calls/{callId}/answer` | Answer a RINGING/OVERFLOW call; route to an agent | Receptionist |
| POST | `/va/calls/{callId}/start` | Begin the live conversation | Receptionist |
| POST | `/va/calls/{callId}/wrap` | End the conversation | Receptionist |
| POST | `/va/calls/{callId}/complete` | Finalize and bill the call | Receptionist |
| POST | `/va/calls/{callId}/abandon` | Mark a RINGING call abandoned | Receptionist, PlatformAdmin |
| POST | `/va/calls/{callId}/dispute` | Dispute a billed call | AccountOwner |
| POST | `/va/calls/{callId}/adjust` | Adjust a disputed call's billable units | PlatformAdmin |
| POST | `/va/calls/{callId}/escalate` | Escalate an in-progress call; select a senior agent | Receptionist |
| POST | `/va/messages` | Capture a message / lead for a call | Receptionist |
| GET | `/va/messages/{messageId}` | Get a captured message | PlatformAdmin, AccountOwner, Receptionist |
| GET | `/va/messages` | List captured messages | PlatformAdmin, AccountOwner, Receptionist |
| GET | `/va/escalations/{escalationId}` | Get an escalation event | PlatformAdmin, Receptionist, AccountOwner |
| GET | `/va/escalations` | List escalations | PlatformAdmin, Receptionist, AccountOwner |
| POST | `/va/escalations/{escalationId}/resolve` | Resolve an escalation | Receptionist |
| POST | `/va/crm-handoffs` | Push a call's captured messages to a CRM | AccountOwner |
| GET | `/va/crm-handoffs/{handoffId}` | Get a CRM handoff record | PlatformAdmin, AccountOwner |
| GET | `/va/crm-handoffs` | List CRM handoffs | PlatformAdmin, AccountOwner |
| POST | `/va/appointments` | Book an appointment into a slot (OCC-guarded on the slot) | AccountOwner, Receptionist |
| GET | `/va/appointments/{appointmentId}` | Get an appointment | PlatformAdmin, AccountOwner |
| GET | `/va/appointments` | List appointments | PlatformAdmin, AccountOwner |
| POST | `/va/appointments/{appointmentId}/confirm` | Confirm a requested or reschedule-requested appointment | AccountOwner |
| POST | `/va/appointments/{appointmentId}/reschedule` | Move a confirmed appointment to a new interval | AccountOwner |
| POST | `/va/appointments/{appointmentId}/complete` | Mark a confirmed appointment completed | AccountOwner |
| POST | `/va/appointments/{appointmentId}/no-show` | Mark a confirmed appointment a no-show | AccountOwner |
| POST | `/va/appointments/{appointmentId}/cancel` | Cancel an appointment; free the slot | AccountOwner |
| GET | `/va/billing-periods/{periodId}` | Get a billing period (provisional overage on OPEN) | PlatformAdmin, AccountOwner |
| GET | `/va/billing-periods` | List billing periods | PlatformAdmin, AccountOwner |
| GET | `/va/billing-periods/{periodId}/overage-summary` | Computed provisional overage breakdown for an OPEN period | PlatformAdmin, AccountOwner |
| POST | `/va/billing-periods/{periodId}/close` | Begin closing a period; finalize overage | PlatformAdmin |
| POST | `/va/billing-periods/{periodId}/finalize` | Finalize a closing period; open the next | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_SLOT_VERSION` | 412 |
| `ERR_STALE_CALL_VERSION` | 412 |
| `ERR_STALE_PERIOD_VERSION` | 412 |
| `ERR_ACCOUNT_SUSPENDED` | 409 |
| `ERR_AFTER_HOURS_BLOCKED` | 409 |
| `ERR_NO_LANGUAGE_MATCH` | 409 |
| `ERR_NO_RECEPTIONIST_AVAILABLE` | 409 |
| `ERR_SLOT_OVERLAP` | 409 |
| `ERR_WINDOW_OVERLAP` | 409 |
| `ERR_SLOT_FULL` | 409 |
| `ERR_RESCHEDULE_LIMIT` | 409 |
| `ERR_OPEN_DISPUTE` | 409 |
| `ERR_NO_PUBLISHED_SCRIPT` | 409 |
| `ERR_NO_AVAILABILITY_WINDOW` | 409 |
| `ERR_RECEPTIONIST_BUSY` | 409 |
| `ERR_PLAN_MISCONFIGURED` | 422 |
| `ERR_PERIOD_NOT_OPEN` | 409 |
