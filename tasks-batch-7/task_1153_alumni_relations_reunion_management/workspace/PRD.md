# Alumni Relations API — Product Requirements Document

## 1. Introduction

A university alumni association lives or dies on the quality of its relationships: records go stale as graduates move and change email addresses, reunion classes need volunteer committees and ticketed events, affinity and regional chapters run year-round programming on finite budgets, and milestone reunions anchor the giving pipeline. Today these workflows are tracked in spreadsheets and disconnected tools, which makes it impossible to answer basic operational questions — which alumni have we lost touch with, which reunion is actually ready to open registration, how much of a chapter's budget is already committed, and which alumni are most likely to give.

This document specifies the Alumni Relations API, the single system of record for the association's operations. The API manages alumni records and the research cases that bring lost alumni back into the fold; the full lifecycle of class-year reunion events from committee formation through ticketing, check-in, and financial reconciliation; affinity groups and their chapter programs with strict budget and venue discipline; milestone gift campaigns with employer-match accounting; communication preferences with a global suppression list; and the memorabilia publications that close the loop after each reunion. A computed engagement score and giving propensity per alumnus tie these streams together so that development staff can prioritize outreach on evidence rather than anecdote.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and boilerplate that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, presenting an `X-User-Role` value that is not one of the declared roles, or omitting `X-User-ID` where the role is entity-backed, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Once authenticated, the role is checked against the endpoint's authorization list; a role not permitted for the endpoint — or an actor failing an ownership check where one is required — is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes six roles. `AlumniRelationsStaff` is the operations staff role: it manages alumni records, research cases, reunion event lifecycles (except cancellation), program approvals and cancellations, refunds and check-in, gift campaign lifecycle, pledge fulfillment, suppression-list maintenance, publication drafting, and the test-driving clock. `AlumniRelationsDirector` is the head of alumni relations and holds a superset of staff capabilities plus the override-only operations: clearing a do-not-contact flag, cancelling an event, writing off a pledge, suspending, reactivating, or dissolving a group, and the publication review decisions (return-for-edits, approve, re-review, publish). For both `AlumniRelationsStaff` and `AlumniRelationsDirector`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.

The remaining four roles are entity-backed by the alumnus record. When `X-User-Role` is `ReunionChair`, `CommitteeVolunteer`, `AffinityGroupLeader`, or `Alumni`, `X-User-ID` is the `id` of the acting `AlumniRecord`; ownership checks on any resource that references an alumnus compare the resource's alumnus foreign-key field to `X-User-ID`. A `ReunionChair` is the active CHAIR of a specific reunion committee and may invite members and end memberships on that committee. A `CommitteeVolunteer` accepts or declines their own membership invitation. An `AffinityGroupLeader` drives the program lifecycle for programs they lead. An `Alumni` is a self-service alumnus who registers for events, confirms or cancels their own registrations, manages their own communication preferences, and pledges to campaigns.

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

List endpoints accept two query parameters. The `limit` parameter sets the maximum number of items returned: it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

All time-gated behavior in the system — sales windows, early-bird and late-fee boundaries, recency windows, and event-date comparisons — is evaluated against a server-side **logical clock**, never against wall-clock time. At startup, before any clock operation has been performed, the logical clock reads exactly `2026-05-01T00:00:00Z`. An administrator-facing test-driving capability (restricted to `AlumniRelationsStaff` and `AlumniRelationsDirector`) advances the logical clock to a supplied instant via a request body containing `to_iso8601`; the response echoes the new reading as `current_utc`. The clock must never fall back to wall-clock time once set, and window-gated calculations re-evaluate against the new reading on the next read or mutation that consults them.

### 2.5. Common Resource Properties

Every resource in the system — alumni records, research cases, reunion events, committees, memberships, ticket tiers, registrations, affinity groups, chapter programs, communication preferences, gift campaigns, pledges, and publications — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every modification of the resource.
- `version` (integer): a system-managed integer that increments by one on every mutation of the resource, including mutations driven by cascades and derived-field recomputation rather than by direct client writes.

### 2.6. Nested Resource Retrieval

Endpoints whose paths contain several resource identifiers validate them strictly left to right. The first identifier in the path that does not correspond to an existing resource yields `ERR_NOT_FOUND` (HTTP 404), and scoped children must actually belong to the parent named in the path — a membership fetched under the wrong committee, or a registration fetched under the wrong event, is `ERR_NOT_FOUND` rather than a cross-parent leak. Path variables such as `id` and `committeeId` are therefore resolved in path order before any business rule is evaluated. This ordering guarantee matters because it fixes which error a malformed request produces: existence is always established before state, referential, or fiscal checks run.

### 2.7. Optimistic Concurrency Control

Two write operations in the system are protected by optimistic concurrency control, and only these two accept a version field.

First, updating an alumni record's mutable fields requires the request body to carry `expected_record_version`, holding the record's `version` as the client last observed it. If the record's current `version` has advanced since then — for example because another writer updated contact details, or because a reunite cascade mutated the record — the update is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from silently overwriting a record state it has not observed.

Second, creating a ticket tier on a reunion event requires the request body to carry `expected_event_version`, holding the event's `version` as the client last observed it. A prior tier creation or any posture-affecting mutation advances the event's `version`; if it no longer matches the submitted value, the create is rejected with `ERR_STALE_VERSION` (HTTP 412), because the client's assumptions about the event's tier layout are stale.

No other endpoint takes a version field; mutations not listed here are processed without an optimistic-concurrency check.

### 2.8. Money, Scores, and Rounding

Monetary amounts are represented throughout the API as integer cents (`base_price_cents`, `final_price_cents`, `goal_cents`, `annual_budget_cents`, and their siblings); the API never returns fractional cents. Where a monetary computation produces a fraction — ticket pricing, per-pledge matching credit — the result is rounded half-up to whole cents at the point the scaffolded rule requires, and intermediate steps of the ticket-pricing pipeline are left unrounded until its final step. Engagement scores and giving propensities are decimal quantities carried at exactly two decimal places, rounded half-up: an `engagement_score` ranges from 0.00 to 100.00 and a `giving_propensity` from 0.00 to 1.00.

### 2.9. Hierarchical Consistency and Cascading Mutations

State changes on a parent resource propagate to its dependents immediately and atomically with the triggering operation, and every resource touched by a cascade is itself mutated: its `updated_at` refreshes and its `version` increments, exactly as if the client had written to it directly. Three cascades are load-bearing in this domain. Marking an alumnus deceased ends their committee memberships, cancels their outstanding registrations, lapses their open pledges, and suppresses every communication channel in a single act. Cancelling a reunion event that has opened registration cancels registrations, abandons the linked gift campaign and lapses its pledges, ends committee memberships, and leaves publications untouched for the archive. Completing or cancelling a chapter program releases or converts its committed budget on the parent affinity group. Conversely, child mutations roll upward: each registration confirmation increments a tier's `sold_count` and the event's `total_revenue_cents`, and each membership acceptance or ending adjusts the event's `committee_count`, after which the event's derived posture is recomputed.

### 2.10. Validation Order

When several rules could reject the same request, the system evaluates them in a fixed priority order, and the first failing rule determines the error returned. The order is:

1. **Authentication** — `X-User-Role` present and a declared role, `X-User-ID` present for entity-backed roles (`ERR_UNAUTHENTICATED`, applies to every endpoint).
2. **Authorization** — the role is permitted for the endpoint and any required ownership check passes (`ERR_UNAUTHORIZED`, every endpoint).
3. **Existence** — path identifiers exist, validated left to right, with scoped children belonging to the named parent (`ERR_NOT_FOUND`, all resource endpoints).
4. **Optimistic concurrency** — where required, the `expected_*_version` field is present and matches the parent's current `version` (`ERR_STALE_VERSION`, on record update and ticket-tier creation only).
5. **State** — the target resource is in a valid from-state for the requested transition (`ERR_INVALID_STATE`, all action endpoints).
6. **Referential integrity** — referenced entities exist and are linkable: the tier belongs to the event, the alumnus is not `DECEASED`, a program leader is an `ACTIVE` alumnus (`ERR_REFERENTIAL_INTEGRITY`, creation endpoints with foreign-key payloads).
7. **Temporal rules** — tier sales windows are half-open and non-overlapping per event, program venue intervals do not conflict, registration occurs inside the sales window (`ERR_WINDOW_OVERLAP`, `ERR_VENUE_CONFLICT`, `ERR_SALES_WINDOW_CLOSED`).
8. **Structural constraints** — one `ACTIVE` CHAIR per committee, one committee per event, one campaign per event, pledge amounts of at least 100 cents (`ERR_CHAIR_EXISTS`, `ERR_DUPLICATE_CHILD`, `ERR_AMOUNT_TOO_SMALL`).
9. **Suppression and compliance** — no communication-targeting operation may address a suppressed channel, and deceased records are read-only except for status corrections (`ERR_CHANNEL_SUPPRESSED`).
10. **Fiscal checks** — quorum before registration opens, tier not sold out at confirmation, budget remaining sufficient at approval, spend within allocation at completion (`ERR_QUORUM_NOT_MET`, `ERR_TIER_SOLD_OUT`, `ERR_BUDGET_EXCEEDED`, `ERR_SPEND_OVERRUN`).

Independently of this ordering, any request with a malformed body, a missing required field, or an invalid enum value is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

## 3. Business Logic & Workflows

### 3.1. Alumni Records and the Contact Lifecycle

An alumnus enters the system when an `AlumniRelationsStaff` member creates a record carrying `full_name`, `primary_email`, the four-digit `class_year` of the primary degree, and a `degree_code` such as BA, BS, or MBA. The `primary_email` must be unique across all records that are not `DECEASED`. A new record starts with `status` set to `ACTIVE`, an `engagement_score` of 0.00, an `engagement_tier` of `LOW`, a `giving_propensity` of 0.00, `lifetime_giving_cents` of 0, and `lost_since` unset. Records can be listed with optional filters on `status`, `class_year`, and `engagement_tier`.

Contact details drift, and staff correct them through the record update operation, which accepts any of `full_name`, `primary_email`, and `degree_code` alongside the mandatory `expected_record_version` guard described in §2.7; a successful update increments the record's `version` by one. Note that `class_year` is not updatable through this operation.

When the association loses track of a graduate, staff mark the record, transitioning `status` from `ACTIVE` to `LOST` and stamping `lost_since` with the current logical clock. This is refused while the alumnus holds a registration with `payment_status` of `CONFIRMED` on a reunion event whose `status` is `OPEN_FOR_REGISTRATION` — a confirmed attendee of an open event is, by definition, not lost. Marking lost also recomputes the `suppressed` flag on every `CommunicationPreference` row the alumnus holds.

Each alumnus carries one `CommunicationPreference` per outreach `channel` — `EMAIL`, `MAIL`, or `PHONE` — recording an `opt_in` flag (default true at creation). Creating a preference for a channel the alumnus already has upserts that row rather than adding a second one, and the structural guard `ERR_DUPLICATE_CHILD` protects the (alumnus, channel) pair from ever existing as two rows. Updating a preference accepts a new `opt_in` value. Independently of per-record preferences, staff maintain a **global suppression list** of (alumnus, channel) pairs; adding a pair triggers recomputation of the matching preference row with suppression reason `GLOBAL_LIST`, and removing the pair recomputes it again.

The effective `suppressed` flag on a preference row is derived, never set directly: a row is suppressed when the owning record's `status` is `DO_NOT_CONTACT`, when the record is `DECEASED`, when the (alumnus, channel) pair appears on the global suppression list, or when the channel is `EMAIL` and the record's `hard_bounce_flag` is set. The `suppression_reason` is the first matching cause in the fixed precedence order `DO_NOT_CONTACT_RECORD`, then `GLOBAL_LIST`, then `HARD_BOUNCE`, and is `NONE` when none applies. Any operation that would target a suppressed (alumnus, channel) pair for outreach is rejected with `ERR_CHANNEL_SUPPRESSED`.

Setting the do-not-contact flag moves a record from `ACTIVE` to `DO_NOT_CONTACT` and immediately suppresses every preference row with reason `DO_NOT_CONTACT_RECORD`. Clearing it — a director-only decision — returns the record to `ACTIVE` and recomputes every row, since the global list may still suppress some channels. Marking a record deceased is the heaviest transition in the system: `status` becomes `DECEASED` (terminal, and thereafter read-only except for status corrections), every committee membership in `INVITED` or `ACTIVE` moves to `ENDED` with `ended_reason` of `ALUMNUS_DECEASED` (each such ending itself decrementing the event's `committee_count` and potentially flipping its posture to `GATED`), every registration with `payment_status` of `PENDING_PAYMENT` or `CONFIRMED` moves to `CANCELLED` with `cancelled_reason` of `ALUMNUS_DECEASED` (each cancellation itself decrementing the tier's `sold_count` and the event's `total_revenue_cents`), every pledge still `PLEDGED` moves to `LAPSED` (each lapse itself decrementing its campaign's `pledged_total_cents`), and all preference rows are suppressed with reason `DO_NOT_CONTACT_RECORD`.

### 3.2. Lost-Alumni Research and Reunion

For a record in `LOST`, staff open a `LostAlumniResearchCase` naming the `alumni_id` under research together with a `lead_source` (`SOCIAL_MEDIA`, `PUBLIC_RECORDS`, `PEER_TIP`, or `PROFESSIONAL_DATABASE`), a free-text `lead_detail`, and a `lead_confidence` score from 1 to 100. The case starts in `OPEN`; cases can be listed filtered by `alumni_id` or `status`.

Logging a lead moves the case `OPEN → LEAD_LOGGED` and refreshes the `lead_source`, `lead_detail`, and `lead_confidence` values from the submission; it is permitted only while the linked record is still `LOST`, otherwise the request fails with `ERR_ALUMNUS_NOT_LOST`. Verifying a lead moves the case `LEAD_LOGGED → VERIFIED` and demands a `lead_confidence` of at least 60 — a lower confidence fails with `ERR_LEAD_CONFIDENCE_TOO_LOW`. A verified lead that turns out bad can be reopened, cycling the case `VERIFIED → OPEN` and incrementing `reopened_count` by one; this cycle is capped, and reopening a case whose `reopened_count` has already reached 3 is rejected with `ERR_CASE_REOPEN_LIMIT`. Two terminal outcomes exist: reuniting the case moves it `VERIFIED → REUNITED`, requiring the linked record to still be `LOST`, stamps `resolved_at` with the current logical clock, and — crucially — flips the linked `AlumniRecord` from `LOST` back to `ACTIVE`, which clears its `lost_since` to null and recomputes its `engagement_score`; declaring the trail cold moves the case `LEAD_LOGGED → DEAD_END` and likewise stamps `resolved_at`. As with all transitions, invoking any of these actions against a case in the wrong from-state fails with `ERR_INVALID_STATE`.

### 3.3. Reunion Events and Committee Formation

A reunion event is born in `PLANNING` when staff create it with a `class_year`, a `title` such as "Class of 2001 25th Reunion", an `event_date`, and optionally a `committee_quorum_required` that defaults to 3 when omitted. At scheduling time the server computes `milestone_year` as the current year minus the `class_year`; the value matters later because milestone gift campaigns may activate only when it is positive and divisible by five. A fresh event has `committee_count` of 0, `total_revenue_cents` of 0, and a derived `posture` of `GATED`. Events are listable with filters on `status`, `posture`, and `class_year`.

Exactly one `ReunionCommittee` may exist per event; staff create it with a display `name`, and a second attempt fails with `ERR_DUPLICATE_CHILD`. The committee starts unlocked, with `chair_membership_id` null. Fetching an event's committee returns an array of zero or one rows. Volunteers join through invitations: an invitation names the `alumni_id` and a `role` of `CHAIR`, `TREASURER`, `LOGISTICS`, `OUTREACH`, or `MEMBER`, producing a membership in `INVITED` with `invited_at` stamped from the logical clock. Memberships can be listed per committee (with `status` and `role` filters) or across the system filtered by `alumni_id` or `committee_id`.

Acceptance is personal: a `CommitteeVolunteer` accepts their own invitation, meaning the acting user's `AlumniRecord` `id` must equal the membership's `alumni_id` or the request fails as `ERR_UNAUTHORIZED`. Acceptance also requires the parent committee's `locked` flag to be false (`ERR_COMMITTEE_LOCKED`) and the volunteer's record to be `ACTIVE` (`ERR_ALUMNUS_NOT_ACTIVE`). On acceptance the membership moves `INVITED → ACTIVE`, the event's `committee_count` increases by one, and the event's posture is re-derived; if the accepted `role` is `CHAIR`, the committee's `chair_membership_id` is set to this membership, and only one `ACTIVE` CHAIR may exist per committee — a second acceptance as CHAIR while another CHAIR is active fails with `ERR_CHAIR_EXISTS`. Declining is likewise personal and moves the membership `INVITED → DECLINED`. An active membership ends `ACTIVE → ENDED` at the hands of the committee's own active CHAIR or of staff acting as override; the committee must not be locked (`ERR_COMMITTEE_LOCKED`), the event's `committee_count` decreases by one with posture re-derived, and if the ended membership was the CHAIR, `chair_membership_id` returns to null. Where a cascade ends a membership it records why: `ended_reason` is one of `RESIGNED`, `REMOVED`, `EVENT_CANCELLED`, or `ALUMNUS_DECEASED`.

Forming the committee moves the event `PLANNING → COMMITTEE_FORMED`, requiring that the committee exist and that `committee_count` already be at least one. Opening registration moves it `COMMITTEE_FORMED → OPEN_FOR_REGISTRATION` under two checks: `committee_count` must be at least `committee_quorum_required` (else `ERR_QUORUM_NOT_MET`), and at least one ticket tier's sales window must cover the current logical clock (else `ERR_NO_ACTIVE_TIER`). Opening locks the committee — `locked` becomes true and all membership mutations are thereafter rejected — and re-derives posture. Once the logical clock reaches the `event_date`, staff may mark the event `OPEN_FOR_REGISTRATION → HELD`, which flips posture to `CLOSED`. Reconciliation moves `HELD → RECONCILED` and is blocked while any registration remains in `PENDING_PAYMENT`; pledges on the linked gift campaign survive reconciliation, and the campaign itself may still be `ACTIVE`.

Cancellation is a director-only act with three distinct scopes. From `PLANNING` or `COMMITTEE_FORMED`, cancellation ends every `ACTIVE` or `INVITED` membership with `ended_reason` of `EVENT_CANCELLED`. From `OPEN_FOR_REGISTRATION` it does far more: every registration in `PENDING_PAYMENT` or `CONFIRMED` is cancelled with `cancelled_reason` of `EVENT_CANCELLED` (each such cancellation itself decrementing the tier's `sold_count` and the event's `total_revenue_cents`); a linked campaign in `ACTIVE` is abandoned and each of its `PLEDGED` pledges lapses (each lapse itself decrementing the campaign's `pledged_total_cents` and triggering a `giving_propensity` recompute on the pledgor's record); every active or invited membership ends with reason `EVENT_CANCELLED` (each ending itself decrementing `committee_count`); and publications in `DRAFT`, `IN_REVIEW`, or `APPROVED` are deliberately left untouched, retained for the archive. `CANCELLED` and `RECONCILED` are terminal.

### 3.4. Ticket Tiers, Pricing, and Registration

Ticket tiers are created against an event by staff, and creation is one of the two optimistic-concurrency checkpoints in the system: the request must carry `expected_event_version` matching the event's current `version`, or it fails with `ERR_STALE_VERSION` as described in §2.7. Each tier names a `name` (such as Early Bird, Standard, or Patron), a `base_price_cents` list price, a `capacity`, and a sales window from `sales_start` to `sales_end`; an optional `early_bird_discount_pct` (a whole percent from 0 to 90, defaulting to 0) rewards early buyers. A `capacity` of exactly 0 means the tier is unlimited and can never sell out; any positive capacity sells out when `sold_count` reaches it. The sales window is a half-open interval — a purchase at `sales_start` is inside the window, a purchase at `sales_end` is outside it — and the windows of an event's tiers may not overlap, though windows that merely touch at an endpoint are allowed; an overlapping create is rejected with `ERR_WINDOW_OVERLAP`. A successful tier create starts `sold_count` at 0, increments the parent event's `version` by one, and re-derives posture.

The price a registrant pays is computed by a four-step pipeline whose evaluation order is pinned: early-bird discount first, committee discount second, late fee third, rounding last. Starting from the tier's `base_price_cents`, step one applies the early-bird discount when the current logical clock is before the early-bird cutoff — sixty days before the `event_date` — by scaling the price by the complement of `early_bird_discount_pct` (a 20 percent discount multiplies the price by 0.80). Step two grants committee members a 25 percent discount, scaling the running price by 0.75, whenever the registrant holds a committee membership with `status` `ACTIVE` on this event's committee. Step three adds a flat late fee of $15.00 (1500 cents) when the current logical clock has advanced into the final seven days before the event — that is, when it reads strictly later than `event_date` minus seven days. Step four rounds half-up to whole cents; intermediate steps are not rounded.

This pipeline runs in two variants. At registration creation the ESTIMATE variant produces `quoted_price_cents`: it is forward-looking, applying the early-bird discount whenever the clock is currently before the cutoff, and ignoring the late fee entirely since a registration is never late at the moment it is created. At payment confirmation the FINAL variant produces `final_price_cents`: it is chronological, evaluating all four steps against the logical clock at confirm time, including the late fee. For identical tier data, a registration created early but confirmed within seven days of the event therefore yields a FINAL price strictly greater than its ESTIMATE.

Registration itself is a self-service act: an `Alumni` creates a registration on an event by naming the `tier_id` and themselves as `alumni_id` — the acting user's record `id` must match the payload's `alumni_id`, else `ERR_UNAUTHORIZED`. The chosen tier must belong to the event in the path and the alumnus must not be `DECEASED`, on pain of `ERR_REFERENTIAL_INTEGRITY`; the logical clock must fall inside the tier's half-open sales window, on pain of `ERR_SALES_WINDOW_CLOSED`. A new registration starts with `payment_status` of `PENDING_PAYMENT` and `attendance_status` of `NOT_CHECKED_IN`, with `quoted_price_cents` set by the ESTIMATE variant. The registration's two status dimensions then evolve in parallel. On the payment dimension, confirmation — again personal to the registrant — moves `PENDING_PAYMENT → CONFIRMED` but only while the parent event's `status` is `OPEN_FOR_REGISTRATION` (`ERR_EVENT_NOT_OPEN`) and the tier is not sold out at confirm time, meaning its `capacity` is 0 or its `sold_count` is still below `capacity` (`ERR_TIER_SOLD_OUT`). Confirmation computes `final_price_cents` via the FINAL variant, increments the tier's `sold_count` by one, adds `final_price_cents` to the event's `total_revenue_cents`, re-derives posture, and recomputes the registrant's `engagement_score`. Staff may refund a `CONFIRMED` registration so long as the event has not been marked `HELD` (`ERR_EVENT_ALREADY_HELD`); refunding moves it to `REFUNDED`, decrements `sold_count` by one, subtracts `final_price_cents` from `total_revenue_cents`, leaves `attendance_status` at `NOT_CHECKED_IN`, and re-derives posture. The registrant may cancel a registration that is still in `PENDING_PAYMENT`, moving it to `CANCELLED` with `cancelled_reason` of `REGISTRANT`; the full set of cancellation reasons in the system is `REGISTRANT`, `EVENT_CANCELLED`, `ALUMNUS_DECEASED`, and `PAYMENT_TIMEOUT`. On the attendance dimension, staff check in a registration — `NOT_CHECKED_IN → CHECKED_IN` — when the parent event's `status` is `OPEN_FOR_REGISTRATION` or `HELD` and the payment dimension sits at `CONFIRMED`; once `CHECKED_IN`, the registration row is terminal, as are `REFUNDED` and `CANCELLED`.

The event's `posture` is a continuously derived read model of these moving parts. When the event's `status` is anything other than `OPEN_FOR_REGISTRATION`, posture is `CLOSED` if the status is `HELD`, `RECONCILED`, or `CANCELLED`, and `GATED` otherwise. While the event is `OPEN_FOR_REGISTRATION`, posture is `GATED` when `committee_count` has fallen below `committee_quorum_required`; otherwise it is `SOLD_OUT` when no tier remains bookable — every tier having a positive `capacity` fully reached by its `sold_count` — and `OPEN` when at least one tier is bookable. Posture recomputes on any change to `committee_count`, to any tier's `sold_count`, or to the event's `status`.

Registrations can be listed per event with a `payment_status` filter, or across the system filtered by `alumni_id`, `tier_id`, `event_id`, or `payment_status`.

### 3.5. Affinity Groups and Chapter Programming

Affinity groups and regional chapters are created by staff with a `name`, a `kind` of `AFFINITY` or `REGIONAL_CHAPTER`, and an `annual_budget_cents`. A new group is `ACTIVE` with `budget_committed_cents` and `budget_spent_cents` at 0 and `budget_remaining_cents` equal to the annual budget. The remaining budget is always derived — the annual budget minus committed minus spent — and must never go negative. Groups are listable by `status` and `kind`.

A group can be suspended by a director, moving `ACTIVE → SUSPENDED`; programs of the group sitting in `DRAFT` or `PROPOSED` survive the suspension but cannot be proposed or approved while it lasts. Reactivation returns `SUSPENDED → ACTIVE`. Dissolution moves `ACTIVE → DISSOLVED` and is blocked while any of the group's programs stands in `APPROVED` or `PUBLISHED` (`ERR_PROGRAMS_OUTSTANDING`); because committed budget exists only on programs in exactly those two states, `budget_committed_cents` is necessarily zero at dissolve time.

Programs are the group's spending vehicle. One is created in `DRAFT` under a group with a `title`, a `venue_slot_start`, a `venue_slot_end`, a `budget_allocated_cents` reservation, and a `leader_id` that must reference an `ACTIVE` alumnus, else `ERR_REFERENTIAL_INTEGRITY`. Programs list per group with a `status` filter, or across the system by `leader_id` or `group_id`. The leader — the acting user's record `id` must equal the program's `leader_id`, else `ERR_UNAUTHORIZED` — proposes the program, moving `DRAFT → PROPOSED` while the parent group is `ACTIVE` (`ERR_GROUP_NOT_ACTIVE`), and may withdraw a proposal back to `DRAFT`. Approval is staff work: moving `PROPOSED → APPROVED` requires the group to be `ACTIVE` (`ERR_GROUP_NOT_ACTIVE`), requires `budget_allocated_cents` to fit within the group's `budget_remaining_cents` (`ERR_BUDGET_EXCEEDED`), and requires a clear venue calendar — no other program of the same group in `APPROVED`, `PUBLISHED`, or `COMPLETED` may occupy an overlapping venue interval, where each program occupies the closed interval from its `venue_slot_start` to sixty minutes after its `venue_slot_end`; a conflict fails with `ERR_VENUE_CONFLICT`. Approval commits the budget: the group's `budget_committed_cents` increases by `budget_allocated_cents` and `budget_remaining_cents` is re-derived. The leader then publishes, `APPROVED → PUBLISHED`, and after the event completes the program, `PUBLISHED → COMPLETED`, supplying `actual_spend_cents`, which must be provided, non-negative, and no greater than `budget_allocated_cents` (`ERR_SPEND_OVERRUN`). Completion moves money between buckets: `budget_committed_cents` decreases by `budget_allocated_cents`, `budget_spent_cents` increases by `actual_spend_cents`, and the remainder is re-derived. Staff may instead cancel a program from `APPROVED` or `PUBLISHED`, a compensating release that decrements `budget_committed_cents` by `budget_allocated_cents` and re-derives the remainder.

### 3.6. Milestone Gift Campaigns and Pledges

A reunion event may host exactly one gift campaign — a second create fails with `ERR_DUPLICATE_CHILD` — established by staff with a `name`, a `goal_cents` fundraising target, and an optional `matching_multiplier_bps` that defaults to 0 and expresses an employer-match credit in basis points, where 10000 means a 1.0x match. The campaign starts in `DRAFT` with all totals at zero; fetching an event's campaign returns an array of zero or one rows.

Activation, `DRAFT → ACTIVE`, is the milestone gate: the linked event's `milestone_year` must be positive and divisible by five (else `ERR_NOT_MILESTONE_YEAR`), and `goal_cents` must be greater than zero. Pledges flow only into an `ACTIVE` campaign. Creating one names the `alumni_id` and an `amount_cents` of at least 100 (else `ERR_AMOUNT_TOO_SMALL`); an `Alumni` pledges for themselves, and the campaign must be `ACTIVE` (else `ERR_CAMPAIGN_NOT_ACTIVE`). A new pledge is `PLEDGED` with `pledge_date` stamped from the logical clock, and the campaign's `pledged_total_cents` increases by `amount_cents`. Pledges list per campaign or across the system filtered by `alumni_id`, `campaign_id`, or `status`.

Fulfillment is staff work and is the campaign's richest mutation: it requires the parent campaign to still be `ACTIVE` (`ERR_CAMPAIGN_NOT_ACTIVE`) and the pledgor's record to not be `DECEASED`. On the `PLEDGED → FULFILLED` transition the pledge's own `matched_credit_cents` is computed as `amount_cents` scaled by `matching_multiplier_bps` divided by 10000, rounded half-up to whole cents — rounding happens per pledge, and the campaign's `matched_credit_cents` is the sum of these per-pledge rounded credits over fulfilled pledges; summing first and rounding once is explicitly not how the campaign total is built. Fulfillment then adds `amount_cents` to the campaign's `fulfilled_total_cents`, adds the pledge's credit to the campaign's `matched_credit_cents`, adds `amount_cents` to the pledgor's `lifetime_giving_cents`, and finally recomputes the pledgor's `engagement_score` and then their `giving_propensity`, in that pinned order so the propensity reads the newly persisted score. A pledge may instead lapse, `PLEDGED → LAPSED`, at staff hands or automatically when its event is cancelled or its pledgor is marked deceased; lapsing subtracts `amount_cents` from the campaign's `pledged_total_cents` and recomputes the pledgor's `giving_propensity`. Finally, a director may write off a pledge — `PLEDGED → WRITTEN_OFF` — but only once the parent campaign is `CLOSED` (`ERR_CAMPAIGN_NOT_CLOSED`); writing off also subtracts `amount_cents` from `pledged_total_cents`. `FULFILLED`, `LAPSED`, and `WRITTEN_OFF` are all terminal.

Closing a campaign, `ACTIVE → CLOSED`, requires that no pledge remain in `PLEDGED` (`ERR_PLEDGES_OUTSTANDING`). A campaign is abandoned only by the system, when its linked reunion event is cancelled: `ACTIVE → ABANDONED` lapses every `PLEDGED` pledge with the per-pledge total-decrement and propensity-recompute side effects described above.

### 3.7. Engagement Scoring and Giving Propensity

Every record carries three computed development indicators, all expressed at two-decimal precision rounded half-up, and they reconcile against the operational streams rather than being edited directly.

The `engagement_score` is a weighted blend capped at 100.00: event participation contributes at a weight of 0.50, giving at 0.30, and service at 0.20. Event points come from the count of the alumnus's registrations with `payment_status` of `CONFIRMED` or `CHECKED_IN` — cancelled and refunded registrations never count — at 25 points each, capped at 100 points. Giving points come from `lifetime_giving_cents` at the rate of one point per ten dollars of fulfilled giving — a lifetime total of $1,000.00 yields the full 100 points — capped at 100. Service points come from the count of the alumnus's committee memberships with `status` `ACTIVE` or `ENDED`, excluding any membership whose `ended_reason` is `ALUMNUS_DECEASED`, at 20 points each, capped at 100. The weighted sum is capped at 100.00 and rounded half-up to two decimals. The score recomputes and persists whenever a registration is confirmed for the alumnus, whenever one of their pledges is fulfilled, whenever a lost record is reunited, and for every registrant of an event when one of that event's publications is published. A provisional variant exists for display at registration-creation and pledge-creation time: it additionally counts the amounts of pledges still in `PLEDGED` at half their value within the giving component, so for identical underlying data the provisional score is greater than or equal to the persisted one; the persisted variant counts only fulfilled pledges and non-cancelled registrations.

Immediately after a new score persists, the `engagement_tier` is re-derived from inclusive thresholds: a score of at least 70.00 is `HIGH`, a score of at least 30.00 but below 70.00 is `MEDIUM`, and anything below 30.00 is `LOW`. Exactly 70.00 is therefore `HIGH` and exactly 30.00 is `MEDIUM`.

The `giving_propensity` recompute is pinned to run after the engagement score persists, and it reads that newly persisted score. The base factor is the score divided by 100. A recency bonus of 0.15 is added when the alumnus has any pledge in `FULFILLED` whose fulfillment falls within the 365 days preceding the current logical clock, and 0 otherwise. A capacity factor is added equal to `lifetime_giving_cents` divided by one million cents and multiplied by 0.25, capped at 0.25 — so $10,000.00 of lifetime giving saturates the capacity factor. The propensity is the base factor weighted at 0.7, plus the recency bonus, plus the capacity factor, capped at 1.00 and rounded half-up to two decimals. A pledge lapse also triggers a propensity recompute on its own.

### 3.8. Memorabilia Publications

After — and during — a reunion, staff compile its memory book. A publication is created under an event with a `title` such as "Class of 2001 Memory Book" and the compiled `class_notes_body` text, starting in `DRAFT` with a `review_round` of 0. Publications list per event with a `status` filter. Submitting for review moves `DRAFT → IN_REVIEW` and requires the `class_notes_body` to be at least one character long. Review is director territory: returning the draft for edits moves `IN_REVIEW → DRAFT` and increments `review_round` by one each time; approving moves `IN_REVIEW → APPROVED`; and if a material change surfaces after approval, requesting re-review loops the publication back `APPROVED → IN_REVIEW`. Publishing is the terminal act, `APPROVED → PUBLISHED`, permitted only while the linked event's `status` is `OPEN_FOR_REGISTRATION`, `HELD`, or `RECONCILED` — never on an event still in planning or one already cancelled, which fails with `ERR_EVENT_NOT_PUBLISHABLE`. Publication has one outward ripple: an `engagement_score` recompute is scheduled for every registrant of the linked event.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify, transition, or delete-something-existing return `200 OK`. All resources are served under the `/alumni` mount. The table below is a summary only — request payloads, computed fields, side effects, and preconditions are specified in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/alumni/records` | Create an AlumniRecord | AlumniRelationsStaff, AlumniRelationsDirector |
| GET | `/alumni/records/{id}` | Get an AlumniRecord | AlumniRelationsStaff, AlumniRelationsDirector, ReunionChair, CommitteeVolunteer, AffinityGroupLeader, Alumni |
| GET | `/alumni/records` | List AlumniRecords with optional filters | AlumniRelationsStaff, AlumniRelationsDirector |
| PUT | `/alumni/records/{id}` | Update mutable record fields; OCC via `expected_record_version` | AlumniRelationsStaff, AlumniRelationsDirector |
| POST | `/alumni/records/{id}/mark-lost` | Transition record ACTIVE → LOST | AlumniRelationsStaff, AlumniRelationsDirector |
| POST | `/alumni/records/{id}/set-do-not-contact` | Transition record to DO_NOT_CONTACT | AlumniRelationsStaff, AlumniRelationsDirector |
| POST | `/alumni/records/{id}/clear-do-not-contact` | Transition record DO_NOT_CONTACT → ACTIVE | AlumniRelationsDirector |
| POST | `/alumni/records/{id}/mark-deceased` | Transition record to DECEASED with full cascade | AlumniRelationsStaff, AlumniRelationsDirector |
| POST | `/alumni/research-cases` | Open a research case for a LOST alumnus | AlumniRelationsStaff, AlumniRelationsDirector |
| GET | `/alumni/research-cases/{id}` | Get a research case | AlumniRelationsStaff, AlumniRelationsDirector |
| GET | `/alumni/research-cases` | List research cases; `alumni_id` filter supported | AlumniRelationsStaff, AlumniRelationsDirector |
| POST | `/alumni/research-cases/{id}/log-lead` | Case OPEN → LEAD_LOGGED | AlumniRelationsStaff, AlumniRelationsDirector |
| POST | `/alumni/research-cases/{id}/verify` | Case LEAD_LOGGED → VERIFIED | AlumniRelationsStaff, AlumniRelationsDirector |
| POST | `/alumni/research-cases/{id}/reopen` | Case VERIFIED → OPEN; `reopened_count` increments | AlumniRelationsStaff, AlumniRelationsDirector |
| POST | `/alumni/research-cases/{id}/reunite` | Case VERIFIED → REUNITED; record LOST → ACTIVE | AlumniRelationsStaff, AlumniRelationsDirector |
| POST | `/alumni/research-cases/{id}/dead-end` | Case LEAD_LOGGED → DEAD_END | AlumniRelationsStaff, AlumniRelationsDirector |
| POST | `/alumni/events` | Create a ReunionEvent | AlumniRelationsStaff, AlumniRelationsDirector |
| GET | `/alumni/events/{id}` | Get a ReunionEvent | AlumniRelationsStaff, AlumniRelationsDirector, ReunionChair, CommitteeVolunteer, AffinityGroupLeader, Alumni |
| GET | `/alumni/events` | List ReunionEvents | AlumniRelationsStaff, AlumniRelationsDirector, ReunionChair, CommitteeVolunteer, AffinityGroupLeader, Alumni |
| POST | `/alumni/events/{id}/form-committee` | Event PLANNING → COMMITTEE_FORMED | AlumniRelationsStaff, AlumniRelationsDirector |
| POST | `/alumni/events/{id}/open-registration` | Event COMMITTEE_FORMED → OPEN_FOR_REGISTRATION; locks committee | AlumniRelationsStaff, AlumniRelationsDirector |
| POST | `/alumni/events/{id}/mark-held` | Event OPEN_FOR_REGISTRATION → HELD | AlumniRelationsStaff, AlumniRelationsDirector |
| POST | `/alumni/events/{id}/reconcile` | Event HELD → RECONCILED | AlumniRelationsStaff, AlumniRelationsDirector |
| POST | `/alumni/events/{id}/cancel` | Event PLANNING/COMMITTEE_FORMED/OPEN_FOR_REGISTRATION → CANCELLED with cascade | AlumniRelationsDirector |
| POST | `/alumni/events/{id}/committee` | Create the (single) ReunionCommittee for an event | AlumniRelationsStaff, AlumniRelationsDirector |
| GET | `/alumni/events/{id}/committee` | Get the committee of an event (array of 0 or 1) | AlumniRelationsStaff, AlumniRelationsDirector, ReunionChair, CommitteeVolunteer |
| POST | `/alumni/committees/{committeeId}/memberships` | Invite an alumnus to a committee | AlumniRelationsStaff, AlumniRelationsDirector, ReunionChair |
| GET | `/alumni/committees/{committeeId}/memberships` | List memberships of a committee | AlumniRelationsStaff, AlumniRelationsDirector, ReunionChair, CommitteeVolunteer |
| GET | `/alumni/memberships` | Filtered membership list; `alumni_id` filter supported | AlumniRelationsStaff, AlumniRelationsDirector, ReunionChair, CommitteeVolunteer, Alumni |
| GET | `/alumni/memberships/{id}` | Get a single CommitteeMembership | AlumniRelationsStaff, AlumniRelationsDirector, ReunionChair, CommitteeVolunteer, Alumni |
| POST | `/alumni/memberships/{id}/accept` | Membership INVITED → ACTIVE; `committee_count` increments | CommitteeVolunteer, AlumniRelationsStaff, AlumniRelationsDirector |
| POST | `/alumni/memberships/{id}/decline` | Membership INVITED → DECLINED | CommitteeVolunteer |
| POST | `/alumni/memberships/{id}/end` | Membership ACTIVE → ENDED; `committee_count` decrements | ReunionChair, AlumniRelationsStaff, AlumniRelationsDirector |
| POST | `/alumni/events/{id}/ticket-tiers` | Create a TicketTier; OCC via `expected_event_version`; windows half-open non-overlapping | AlumniRelationsStaff, AlumniRelationsDirector |
| GET | `/alumni/events/{id}/ticket-tiers` | List ticket tiers of an event | AlumniRelationsStaff, AlumniRelationsDirector, ReunionChair, CommitteeVolunteer, Alumni |
| GET | `/alumni/ticket-tiers/{id}` | Get a ticket tier | AlumniRelationsStaff, AlumniRelationsDirector, ReunionChair, CommitteeVolunteer, Alumni |
| POST | `/alumni/events/{id}/registrations` | Create an EventRegistration; sets `quoted_price_cents` via ESTIMATE | Alumni |
| GET | `/alumni/events/{id}/registrations` | List registrations of an event | AlumniRelationsStaff, AlumniRelationsDirector, ReunionChair |
| GET | `/alumni/registrations` | Filtered registration list; `alumni_id` and `tier_id` filters | AlumniRelationsStaff, AlumniRelationsDirector, Alumni |
| GET | `/alumni/registrations/{id}` | Get a registration | AlumniRelationsStaff, AlumniRelationsDirector, Alumni |
| POST | `/alumni/registrations/{id}/confirm-payment` | Registration PENDING_PAYMENT → CONFIRMED; computes `final_price_cents` via FINAL | Alumni |
| POST | `/alumni/registrations/{id}/refund` | Registration CONFIRMED → REFUNDED | AlumniRelationsStaff, AlumniRelationsDirector |
| POST | `/alumni/registrations/{id}/check-in` | Registration CONFIRMED → CHECKED_IN (attendance dimension) | AlumniRelationsStaff, AlumniRelationsDirector |
| POST | `/alumni/registrations/{id}/cancel` | Registration PENDING_PAYMENT → CANCELLED by registrant | Alumni |
| POST | `/alumni/groups` | Create an AffinityGroup | AlumniRelationsStaff, AlumniRelationsDirector |
| GET | `/alumni/groups/{id}` | Get an AffinityGroup | AlumniRelationsStaff, AlumniRelationsDirector, AffinityGroupLeader |
| GET | `/alumni/groups` | List AffinityGroups | AlumniRelationsStaff, AlumniRelationsDirector, AffinityGroupLeader |
| POST | `/alumni/groups/{id}/suspend` | Group ACTIVE → SUSPENDED | AlumniRelationsDirector |
| POST | `/alumni/groups/{id}/reactivate` | Group SUSPENDED → ACTIVE | AlumniRelationsDirector |
| POST | `/alumni/groups/{id}/dissolve` | Group ACTIVE → DISSOLVED | AlumniRelationsDirector |
| POST | `/alumni/groups/{id}/programs` | Create a ChapterProgram in DRAFT | AffinityGroupLeader, AlumniRelationsStaff, AlumniRelationsDirector |
| GET | `/alumni/groups/{id}/programs` | List programs of a group | AlumniRelationsStaff, AlumniRelationsDirector, AffinityGroupLeader |
| GET | `/alumni/programs/{id}` | Get a program | AlumniRelationsStaff, AlumniRelationsDirector, AffinityGroupLeader |
| GET | `/alumni/programs` | Filtered program list; `leader_id` and `group_id` filters | AlumniRelationsStaff, AlumniRelationsDirector, AffinityGroupLeader |
| POST | `/alumni/programs/{id}/propose` | Program DRAFT → PROPOSED | AffinityGroupLeader |
| POST | `/alumni/programs/{id}/withdraw` | Program PROPOSED → DRAFT (revert) | AffinityGroupLeader |
| POST | `/alumni/programs/{id}/approve` | Program PROPOSED → APPROVED; commits budget; venue conflict check | AlumniRelationsStaff, AlumniRelationsDirector |
| POST | `/alumni/programs/{id}/publish` | Program APPROVED → PUBLISHED | AffinityGroupLeader |
| POST | `/alumni/programs/{id}/complete` | Program PUBLISHED → COMPLETED; moves committed budget to spent | AffinityGroupLeader |
| POST | `/alumni/programs/{id}/cancel` | Program APPROVED/PUBLISHED → CANCELLED; releases committed budget | AlumniRelationsStaff, AlumniRelationsDirector |
| POST | `/alumni/records/{id}/preferences` | Create/upsert a CommunicationPreference for a channel | AlumniRelationsStaff, AlumniRelationsDirector, Alumni |
| GET | `/alumni/records/{id}/preferences` | List preferences of an alumnus | AlumniRelationsStaff, AlumniRelationsDirector, Alumni |
| PUT | `/alumni/preferences/{id}` | Update `opt_in` on a preference; re-derives `suppressed` | AlumniRelationsStaff, AlumniRelationsDirector, Alumni |
| POST | `/alumni/suppression-list` | Add (alumnus, channel) to the global suppression list | AlumniRelationsStaff, AlumniRelationsDirector |
| DELETE | `/alumni/suppression-list` | Remove (alumnus, channel) from the global suppression list | AlumniRelationsStaff, AlumniRelationsDirector |
| POST | `/alumni/events/{id}/campaigns` | Create the (single) GiftCampaign for a milestone event | AlumniRelationsStaff, AlumniRelationsDirector |
| GET | `/alumni/events/{id}/campaigns` | Get the campaign of an event (array of 0 or 1) | AlumniRelationsStaff, AlumniRelationsDirector, ReunionChair |
| GET | `/alumni/campaigns/{id}` | Get a campaign | AlumniRelationsStaff, AlumniRelationsDirector, ReunionChair |
| POST | `/alumni/campaigns/{id}/activate` | Campaign DRAFT → ACTIVE (milestone check) | AlumniRelationsStaff, AlumniRelationsDirector |
| POST | `/alumni/campaigns/{id}/close` | Campaign ACTIVE → CLOSED (requires no PLEDGED pledges) | AlumniRelationsStaff, AlumniRelationsDirector |
| POST | `/alumni/campaigns/{id}/pledges` | Create a pledge on an ACTIVE campaign | AlumniRelationsStaff, AlumniRelationsDirector, Alumni |
| GET | `/alumni/campaigns/{id}/pledges` | List pledges of a campaign | AlumniRelationsStaff, AlumniRelationsDirector, ReunionChair |
| GET | `/alumni/pledges` | Filtered pledge list; `alumni_id` filter | AlumniRelationsStaff, AlumniRelationsDirector, Alumni |
| GET | `/alumni/pledges/{id}` | Get a single GiftPledge | AlumniRelationsStaff, AlumniRelationsDirector, Alumni |
| POST | `/alumni/pledges/{id}/fulfill` | Pledge PLEDGED → FULFILLED; matching credit and giving fields update | AlumniRelationsStaff, AlumniRelationsDirector |
| POST | `/alumni/pledges/{id}/lapse` | Pledge PLEDGED → LAPSED | AlumniRelationsStaff, AlumniRelationsDirector |
| POST | `/alumni/pledges/{id}/write-off` | Pledge PLEDGED → WRITTEN_OFF (only on CLOSED campaign) | AlumniRelationsDirector |
| POST | `/alumni/events/{id}/publications` | Create a MemorabiliaPublication in DRAFT | AlumniRelationsStaff, AlumniRelationsDirector |
| GET | `/alumni/events/{id}/publications` | List publications of an event | AlumniRelationsStaff, AlumniRelationsDirector, ReunionChair |
| GET | `/alumni/publications/{id}` | Get a publication | AlumniRelationsStaff, AlumniRelationsDirector, ReunionChair |
| POST | `/alumni/publications/{id}/submit-review` | Publication DRAFT → IN_REVIEW | AlumniRelationsStaff, AlumniRelationsDirector |
| POST | `/alumni/publications/{id}/return-for-edits` | Publication IN_REVIEW → DRAFT; `review_round` increments | AlumniRelationsDirector |
| POST | `/alumni/publications/{id}/approve` | Publication IN_REVIEW → APPROVED | AlumniRelationsDirector |
| POST | `/alumni/publications/{id}/request-re-review` | Publication APPROVED → IN_REVIEW (re-review loop) | AlumniRelationsDirector |
| POST | `/alumni/publications/{id}/publish` | Publication APPROVED → PUBLISHED | AlumniRelationsDirector |
| POST | `/alumni/_clock/set_current_utc` | Set the server logical clock (startup default exactly 2026-05-01T00:00:00Z; never falls back to wall-clock) | AlumniRelationsStaff, AlumniRelationsDirector |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in §2 and §3 where the guarded workflow is described.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_REFERENTIAL_INTEGRITY` | 422 |
| `ERR_DUPLICATE_CHILD` | 422 |
| `ERR_ALUMNUS_NOT_LOST` | 422 |
| `ERR_ALUMNUS_NOT_ACTIVE` | 422 |
| `ERR_LEAD_CONFIDENCE_TOO_LOW` | 422 |
| `ERR_CASE_REOPEN_LIMIT` | 422 |
| `ERR_QUORUM_NOT_MET` | 422 |
| `ERR_NO_ACTIVE_TIER` | 422 |
| `ERR_COMMITTEE_LOCKED` | 422 |
| `ERR_CHAIR_EXISTS` | 422 |
| `ERR_EVENT_NOT_OPEN` | 422 |
| `ERR_EVENT_ALREADY_HELD` | 422 |
| `ERR_TIER_SOLD_OUT` | 422 |
| `ERR_SALES_WINDOW_CLOSED` | 422 |
| `ERR_WINDOW_OVERLAP` | 422 |
| `ERR_VENUE_CONFLICT` | 422 |
| `ERR_GROUP_NOT_ACTIVE` | 422 |
| `ERR_BUDGET_EXCEEDED` | 422 |
| `ERR_SPEND_OVERRUN` | 422 |
| `ERR_PROGRAMS_OUTSTANDING` | 422 |
| `ERR_CHANNEL_SUPPRESSED` | 422 |
| `ERR_NOT_MILESTONE_YEAR` | 422 |
| `ERR_CAMPAIGN_NOT_ACTIVE` | 422 |
| `ERR_CAMPAIGN_NOT_CLOSED` | 422 |
| `ERR_PLEDGES_OUTSTANDING` | 422 |
| `ERR_AMOUNT_TOO_SMALL` | 422 |
| `ERR_EVENT_NOT_PUBLISHABLE` | 422 |
