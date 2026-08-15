# Real Estate Team & Lead Routing Operations API — Product Requirements Document

## 1. Introduction

A high-producing real estate team lives or dies on two disciplines: how quickly a new lead hears back from an agent, and how deliberately the team distributes those leads. A mega-team may run half a dozen intake channels at once — portal subscriptions, an IDX website, paid advertising, sign calls, sphere contacts, and external referral partners — each with its own acquisition cost and monthly budget. Behind the intake funnel sit the economics that keep the team aligned: referral fees owed to partners, the house's share of every commission, and bilateral split agreements between agents who work deals together. When routing is slow or arbitrary, conversion suffers; when fees and splits are computed inconsistently, trust in the operation erodes.

This document specifies the API that operates such a team end to end. It covers the roster lifecycle (onboarding, capacity ceilings, time off, pauses, and offboarding with pipeline drain), versioned routing policies that drive a deterministic agent selector, a claim-window regime with automatic reassignment when an offered agent does not respond, engagement-derived lead temperature that stages nurture campaigns, and a deal pipeline whose commission waterfall — referral fee, house share, agent pool — is computed under a pinned rounding order so that every cent is conserved. All business resources are mounted under `/crm`. A discrete logical clock, settable only by administrators, drives every deadline sweep, so behavior is reproducible and every mutation's cascades and recomputations are visible in the same response.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and boilerplate that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their operational capacity. A request missing either header, or carrying a malformed one, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not among those permitted on the target endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

Four request roles are recognized. `TeamAdmin` is the operations administrator — a superset role covering clock control, the roster lifecycle, policies, sources, campaigns, partners, disputes, and payouts. `TeamLeader` is a lead agent who manages routing, splits, enrollments, and deal approvals. `Agent` is a roster agent who claims offered leads, works them, and manages their own time off. `ReferralPartner` is an external partner who submits referral leads. Two further names complete the model: `System` is the automation identity behind clock-sweep and cascade transitions and is never used as a request role, and `Any` expresses that every authenticated role may perform GET reads.

Identity semantics differ by role. When `X-User-Role` is `TeamAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`. When `X-User-Role` is `TeamLeader`, `X-User-ID` is the `id` of the acting agent — specifically an agent whose `role_on_team` is `LEADER` on the relevant team — and a caller who does not resolve to such an agent fails identity-scoped operations with `ERR_AGENT_IDENTITY_MISMATCH`. When `X-User-Role` is `Agent`, `X-User-ID` is likewise the `id` of the acting agent, and ownership checks compare a resource's foreign keys — a lead's `assigned_agent_id`, an assignment's `agent_id` — against `X-User-ID`. When `X-User-Role` is `ReferralPartner`, `X-User-ID` is the `id` of the acting referral partner, and lead intake compares the payload's `referral_partner_id` against `X-User-ID`.

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

List endpoints paginate through the `limit` and `offset` query parameters. `limit` specifies the maximum number of items to return; it defaults to 10 and accepts values from a minimum of 1 to a maximum of 100. `offset` specifies the number of items to skip and defaults to 0. Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and the Deadline Sweep

All deadlines in the system read from a single logical clock rather than wall-clock time. Before the clock has ever been set it reads exactly `2026-08-01T00:00:00Z`; it advances only when set, and it never falls back to wall-clock time. A `TeamAdmin`-only capability sets the clock to a supplied `to_iso8601` instant, and setting it runs the system sweep: `OFFERED` assignments whose claim deadline has passed are expired (driving the missed-claim counter, auto-pause at three misses, and the re-route cascades described in §3.4), split agreements whose `effective_until` has been reached are expired, and due nurture enrollment steps are advanced or completed. Sweep ordering is pinned: expired `OFFERED` assignments are processed in ascending `claim_deadline_at` order with ties broken by ascending assignment `created_at`, and when one expiry pushes an agent to three consecutive misses, that agent's auto-pause cascade executes immediately inside the triggering expiry's processing, before the next expired assignment is handled. The response reports the new logical time `now_utc` together with `expired_assignment_count`, `auto_paused_agent_count`, `expired_agreement_count`, and `advanced_enrollment_count`.

Calendar boundaries also follow the logical clock. A lead source's monthly counters accumulate over the current calendar month as delimited by the team's `timezone`, and a referral partner's volume tier is evaluated over the current calendar year.

### 2.5. Resource Identity, Timestamps, and Versioning

Every persisted resource carries a server-minted `id` — a bare UUID with no type prefix — and a `created_at` timestamp in ISO 8601 UTC format with three fractional digits. Mutable resources additionally carry `updated_at`, refreshed on every mutation, and an integer `version` that starts at 1 at creation and increments by 1 on every mutation. Engagement events are the single exception: they form an append-only log and carry only `id` and `created_at`; both `updated_at` and `version` are absent from them. Consistency is immediate: every mutation's side effects, cascades, and recomputed fields are reflected in that mutation's own response and in every subsequent read.

### 2.6. Monetary Units, Basis Points, and Rounding

All money amounts are integer cents; fractional cents never appear anywhere in the system. All rates are expressed in basis points, where 10000 basis points equal one hundred percent. Wherever a derivation produces a fractional cent — the referral fee, the house share, an agent A split share, or a pipeline contribution to projected source ROI — the value is rounded half up to a whole cent at that step. Where a ratio is defined with floor semantics — decayed engagement points, the claim and conversion rates on a scorecard, and the ROI figure itself — the result is truncated toward zero, and this document says so at each site. Selector scoring uses integer arithmetic with no rounding.

### 2.7. Optimistic Concurrency on Policy Activation

Activating a routing policy supersedes whichever policy is currently active for the team, so activation is guarded by optimistic concurrency control on the team's `version`. The activation request must carry `expected_team_version`, a non-optional field holding the team `version` the client last observed. If that value does not equal the team's current `version` — because another activation has advanced it since the client read the team — the request is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than superseding a policy the client never saw. A second activation attempt carrying a version observed before the first activation is therefore deterministically rejected. No other endpoint accepts a version field.

### 2.8. Validation Order and the Error Surface

Every request is screened against eleven tiers of checks in a fixed priority order, and a request that violates several tiers surfaces only the earliest failure. First come the identity headers of §2.1, then role authorization. Third, body well-formedness — required fields present, no undeclared fields (a strict schema under which computed or system-maintained fields sent by the client are rejected), enum values valid, datetimes parseable, and integer ranges respected — all failing as `ERR_INVALID_REQUEST` (HTTP 400). Fourth, existence: every id referenced in the path and in the body must exist, validated left-to-right, else `ERR_NOT_FOUND` (HTTP 404). Fifth, entity-backed identity per §2.1, surfacing `ERR_AGENT_IDENTITY_MISMATCH`, `ERR_NOT_OFFERED_TO_AGENT`, or `ERR_PARTNER_IDENTITY_MISMATCH` (HTTP 403). Sixth, state preconditions on the target resource — the generic `ERR_INVALID_STATE` and its specialized siblings `ERR_SOURCE_NOT_ACTIVE`, `ERR_NO_ACTIVE_POLICY`, `ERR_POLICY_NOT_ACTIVATABLE`, `ERR_DEAL_NOT_APPROVABLE`, `ERR_ENROLLMENT_NOT_ACTIVE`, and `ERR_CAMPAIGN_NOT_ACTIVE` (HTTP 409). Seventh, the temporal overlap rules of §3.1 and §3.6 (`ERR_TIME_OFF_OVERLAP`, `ERR_SPLIT_WINDOW_OVERLAP`). Eighth, structural cross-field rules — split shares summing to exactly 10000 basis points, split agent pair validity, and referral partner presence — surfacing the HTTP 422 codes. Ninth, uniqueness conflicts such as `ERR_DUPLICATE_LICENSE_NUMBER` and `ERR_DUPLICATE_OPEN_LEAD` (HTTP 409). Tenth, the source monthly budget of §3.3. Eleventh, selector pool emptiness. Because the order is fixed, an intake request against a paused source that is also over budget reports `ERR_SOURCE_NOT_ACTIVE`, and a manual route attempted on a team with no active policy reports `ERR_NO_ACTIVE_POLICY` rather than `ERR_NO_ELIGIBLE_AGENT`.

## 3. Business Logic & Workflows

### 3.1. Team Setup and the Roster Lifecycle

Everything belongs to a team. Creating a team records its `name`, the `market` or metro label it serves, and the IANA `timezone` that anchors its calendar-month budget boundaries. Two service-level defaults are configured here and may be overridden per routing policy: `speed_to_lead_window_seconds`, the maximum seconds from lead intake to first agent response, defaulting to 900 seconds (fifteen minutes); and `claim_window_seconds`, the seconds an offered agent has to claim before reassignment, defaulting to 7200 seconds (two hours). A new team's `version` starts at 1.

**Roster creation.** A `TeamAdmin` adds an agent with `team_id`, `display_name`, a `license_number` that must be unique within the team (a duplicate is rejected with `ERR_DUPLICATE_LICENSE_NUMBER`), a `role_on_team` of `MEMBER` or `LEADER` (defaulting to `MEMBER`; the `LEADER` value is what backs the `TeamLeader` request role), and a `max_active_leads` capacity ceiling of at least 1. New agents are born `ONBOARDING` with `performance_tier` `BRONZE` and every counter zeroed, and they are invisible to the routing selector until activation. Activation by a `TeamAdmin` flips the agent to `ACTIVE`, stamps `onboarded_at`, and makes the agent selectable. Activating from any other status is `ERR_INVALID_STATE`. Real-world hires arrive with history, so an administrator may backfill an agent's production record — any subset of `trailing_90d_conversions`, `trailing_90d_claimed`, `trailing_90d_offered`, `avg_first_response_seconds`, and `consecutive_missed_claims` — after which the performance tier is recomputed from the imported figures per §3.7. The roster list accepts `team_id`, `status`, and `role_on_team` filters.

**Capacity accounting.** An agent's `active_lead_count` is the number of assigned leads in `OFFERED`, `CLAIMED`, `WORKING`, or `UNDER_CONTRACT` status, reconciled on every assignment-affecting mutation — incremented when an assignment is created for the agent, decremented when one of those leads is released, closed lost, or won. The trailing-90-day counters feed tiering and scorecards: `trailing_90d_offered` counts assignments offered to the agent within the window (the claim-rate denominator), `trailing_90d_claimed` counts assignments the agent claimed within the window, and `trailing_90d_conversions` counts the agent's deals reaching `APPROVED` or `PAID_OUT` with `approved_at` within the window. The `avg_first_response_seconds` is the mean gap between a lead's `created_at` and its `first_response_at` across the agent's leads answered in the trailing ninety days, and stays null until the agent has answered at least one lead. The `last_assigned_at` timestamp records the most recent assignment created for the agent and serves as the round-robin sort key. Finally, `consecutive_missed_claims` tracks the deadline-expiry streak: it increments when one of the agent's offers expires unclaimed, resets to zero on any successful claim and on resume, and reaching three pauses the agent automatically.

**Time off.** An agent (acting on their own `agent_id`, else `ERR_AGENT_IDENTITY_MISMATCH`) or an administrator records a time-off block with `starts_at`, an `ends_at` that must fall strictly after `starts_at`, and a free-text `reason`. Both bounds are inclusive — the block is a closed interval — and blocks are approved on creation. Creation is rejected with `ERR_TIME_OFF_OVERLAP` (HTTP 409) when the new block intersects any existing block of the same agent under closed-interval semantics: blocks that merely touch at an endpoint still conflict. A block whose interval covers the current instant excludes the agent from the routing selector (§3.2). An agent's blocks can be listed through the roster's time-off collection.

**Pausing and resuming.** A `TeamAdmin` or `TeamLeader` pauses an `ACTIVE` agent; pausing from any other status, or resuming from any status other than `PAUSED`, is `ERR_INVALID_STATE`. When a pause takes effect — manual or automatic — every `OFFERED` assignment of that agent expires with `outcome_reason` `AUTO_PAUSE`, and these cascade expirations do not increment `consecutive_missed_claims`. Each lead whose assignment was cascade-expired returns to `NEW` and is immediately re-routed through the selector with the paused agent excluded; if no eligible agent remains, the lead stays pooled in `NEW` with `assigned_agent_id` null. A `PAUSED` agent is excluded from the selector until resumed. Resuming returns the agent to `ACTIVE` and resets `consecutive_missed_claims` to zero.

**Offboarding.** Only a `TeamAdmin` offboards, and only from `ACTIVE` or `PAUSED` — an `ONBOARDING` or `OFFBOARDED` agent rejects with `ERR_INVALID_STATE`. The agent enters the transient `OFFBOARDING` state while the drain runs inside the same call: every `OFFERED` assignment of the agent expires with `outcome_reason` `OFFBOARD`; every lead in `CLAIMED`, `WORKING`, or `UNDER_CONTRACT` has its assignment released with `outcome_reason` `OFFBOARD` and returns to `NEW` with `assigned_agent_id` cleared; and each returned lead is immediately re-routed through the selector with the departing agent excluded, remaining pooled in `NEW` if it cannot be routed. The moment the agent's `active_lead_count` reaches zero, the agent transitions to terminal `OFFBOARDED` and is permanently excluded from the selector and from claim, release, and log-response operations.

### 3.2. Routing Policies and the Agent Selector

Routing behavior is governed by versioned policies. Creating a policy — a `TeamAdmin` operation — takes `team_id`, a `mode` of `ROUND_ROBIN` or `PERFORMANCE_WEIGHTED`, and optional tuning: `tier_weight_bps`, the per-tier multipliers in basis points used by performance weighting, defaulting to 10000 for `BRONZE`, 11000 for `SILVER`, 12500 for `GOLD`, and 15000 for `PLATINUM`; `source_mode_overrides`, a map from lead-source `type` to mode that overrides the policy's default mode for leads arriving from those source types, defaulting to empty; and optional `claim_window_seconds` and `speed_to_lead_window_seconds` overrides that replace the team defaults for leads routed under this policy. Each policy receives a per-team sequential `version_no` starting at 1 and is born `DRAFT`. Policies may be listed filtered by `team_id` and `status`.

Activation, also `TeamAdmin`-only, is the optimistic-concurrency-guarded transition of §2.7: the policy must be `DRAFT` (activation attempted from `ACTIVE` or `SUPERSEDED` is rejected with `ERR_POLICY_NOT_ACTIVATABLE`), and the request's `expected_team_version` must match the team's current `version`. On success the policy becomes `ACTIVE` with `activated_at` stamped, the team's previously `ACTIVE` policy — if any — becomes `SUPERSEDED`, and the team's `version` increments by 1. At most one policy is `ACTIVE` per team at any moment.

**Eligibility.** The selector considers only the lead's team roster, and an agent is eligible only when all of the following hold: the agent's `status` is `ACTIVE`; the agent's `active_lead_count` is strictly below `max_active_leads`; no time-off block covers the current instant under closed-interval semantics (a block whose `starts_at` equals now, or whose `ends_at` equals now, still excludes the agent); and the agent is not in the retry-exclusion set — the agent whose assignment for this lead just expired or was released is excluded from that lead's immediate re-route.

**Mode resolution and selection.** The effective mode is the policy's `source_mode_overrides` entry for the lead's source `type` when such an override exists, otherwise the policy's `mode`. Under `ROUND_ROBIN`, eligible agents are ordered by `last_assigned_at` ascending with never-assigned agents first, ties broken by the agent's `created_at` ascending, and the first agent wins. Under `PERFORMANCE_WEIGHTED`, each eligible agent's score is the `tier_weight_bps` multiplier for the agent's current `performance_tier` multiplied by the agent's remaining capacity (`max_active_leads` minus `active_lead_count`); when the lead's `temperature` is `HOT` and the agent's `trailing_90d_conversions` is at least 5, the score is doubled. Weighted ordering is by score descending, then `last_assigned_at` ascending with never-assigned first, then `created_at` ascending.

**Empty pools.** When no agent survives the eligibility filters, behavior depends on how routing was triggered: a manual route or reassignment is rejected with `ERR_NO_ELIGIBLE_AGENT` (HTTP 409), while intake auto-route fails silently and the lead simply remains pooled in `NEW`.

Every assignment the selector produces snapshots its routing context: the `policy_id` of the policy revision that produced it, a `policy_mode_snapshot` recording the effective mode after source overrides, a per-team monotonically increasing `rotation_seq`, and a `supersedes_assignment_id` pointing at the assignment it replaces on a re-route (null for a lead's first routing). The effective windows are resolved at offer time from the policy's overrides when set, falling back to the team defaults.

**Manual routing.** A `TeamAdmin` or `TeamLeader` may route a lead pooled in `NEW` through the active policy's selector. Routing from any other lead status is `ERR_INVALID_STATE`; routing when the team has no `ACTIVE` policy is `ERR_NO_ACTIVE_POLICY`; and an empty eligibility pool is `ERR_NO_ELIGIBLE_AGENT`.

### 3.3. Lead Sources, Intake, and Monthly Budgets

**Source setup.** A `TeamAdmin` registers a lead source with `team_id`, a display `name` (for example, "Zillow Premier"), a `type` of `PORTAL`, `IDX_WEBSITE`, `PAID_AD`, `REFERRAL_PARTNER`, `SPHERE`, or `SIGN_CALL`, the `cost_per_lead_cents` attributed to each intake (zero or more), and the `monthly_budget_cents` spend ceiling (zero or more). Optional fields are `priority_weight`, an intake priority label from 1 to 100 defaulting to 50 that reporting uses and the selector never reads, and `auto_route`, defaulting to true. Sources are born `ACTIVE`; pausing flips a source to `PAUSED`, resuming returns it to `ACTIVE`, and attempting either transition from the wrong state is `ERR_INVALID_STATE`. Sources list with `team_id`, `status`, and `type` filters. Two counters track the current calendar month (per the team's `timezone`): `leads_this_month_count` counts leads created from the source this month, and `spent_this_month_cents` is that count multiplied by `cost_per_lead_cents`, recomputed on every intake.

**Intake.** A `TeamAdmin`, a `TeamLeader`, or a `ReferralPartner` creates a lead with `team_id`, `source_id`, `contact_name`, `contact_phone`, `contact_email`, and a strictly positive `expected_close_price_cents` that feeds projected source ROI. The `referral_partner_id` field is required exactly when the source's `type` is `REFERRAL_PARTNER` and forbidden for every other source type; either violation is `ERR_REFERRAL_PARTNER_REQUIRED` (HTTP 422). A `ReferralPartner` caller must pass their own id as `referral_partner_id` (a mismatch is `ERR_PARTNER_IDENTITY_MISMATCH`), which confines partner intake to referral-type sources. The `contact_phone` must be unique per team among leads whose status is neither `CLOSED_WON` nor `CLOSED_LOST`; a duplicate open phone is `ERR_DUPLICATE_OPEN_LEAD`.

**State and budget gates.** Per the fixed order of §2.8, intake from a `PAUSED` source is rejected with `ERR_SOURCE_NOT_ACTIVE` before any budget arithmetic runs, and intake that would push the source over budget — `spent_this_month_cents` plus `cost_per_lead_cents` strictly greater than `monthly_budget_cents`, with exact equality allowed — is rejected with `ERR_SOURCE_BUDGET_EXHAUSTED`. A successful intake creates the lead in `NEW` with `temperature` `COLD`, `engagement_score` zero, and null `assigned_agent_id`, `first_response_at`, `within_speed_sla`, `speed_deadline_at`, `claim_deadline_at`, `current_assignment_id`, and `close_reason`. When the source's `auto_route` is true, an `ACTIVE` policy exists, and the eligibility pool is non-empty, the lead is routed immediately — its first `OFFERED` assignment created and the lead flipped to `OFFERED` — otherwise it pools in `NEW` until routed manually. Leads list with `team_id`, `source_id`, `assigned_agent_id`, `referral_partner_id`, `status`, and `temperature` filters.

### 3.4. The Assignment Lifecycle: Offers, Claims, and Reassignment

**Offers.** Routing — automatic at intake or manual — creates an `OFFERED` assignment with `offered_at` stamped and `claim_deadline_at` set to `offered_at` plus the effective claim window. The lead flips `NEW → OFFERED`, its `assigned_agent_id` and `current_assignment_id` are set to the chosen agent and the new assignment, and the lead's `claim_deadline_at` mirrors the assignment's. On the lead's first routing only, `speed_deadline_at` is snapshotted as the lead's `created_at` plus the effective speed window. The chosen agent's `active_lead_count` increments and `last_assigned_at` moves to the offer instant. The `current_assignment_id` is a server-maintained pointer to the lead's current non-terminal assignment — null while the lead is pooled or terminal.

**Claiming.** Only the offered agent may claim: the caller's identity must equal the current `OFFERED` assignment's `agent_id`, and an `ACTIVE` agent who is not the offered agent is rejected with `ERR_NOT_OFFERED_TO_AGENT`. The deadline is inclusive — a claim landing exactly at `claim_deadline_at` succeeds — but the sweep expires any assignment whose deadline is strictly before now, so a claim after the deadline always observes an already-`EXPIRED` assignment and fails the state precondition with `ERR_INVALID_STATE`. A successful claim moves the lead `OFFERED → CLAIMED` and the assignment to `CLAIMED`, resets the claimant's `consecutive_missed_claims` to zero, and recomputes `trailing_90d_claimed`.

**Deadline expiry.** When the sweep finds an assignment still `OFFERED` with `claim_deadline_at` strictly in the past, the assignment expires with `outcome_reason` `DEADLINE`, the lead returns to `NEW` with `current_assignment_id` cleared, and the missed agent's `consecutive_missed_claims` increments by one. The lead is then immediately re-routed through the selector with the missed agent excluded, remaining pooled in `NEW` if the pool is empty. A streak reaching three triggers the auto-pause cascade of §3.1.

**First response.** The assigned agent — and only that agent, else `ERR_AGENT_IDENTITY_MISMATCH` — logs the first response on a `CLAIMED` lead, moving it to `WORKING`. The lead's `first_response_at` is stamped exactly once (a second log-response is `ERR_INVALID_STATE`), `within_speed_sla` is computed as whether `first_response_at` fell at or before `speed_deadline_at`, the current assignment's `responded_at` is set, and the agent's `avg_first_response_seconds` is recomputed and `performance_tier` re-evaluated.

**Release.** The assigned agent, a `TeamLeader`, or a `TeamAdmin` may release a `CLAIMED` or `WORKING` lead back to the pool, optionally recording a `reason`; agent callers may release only their own leads, and release from any other status is `ERR_INVALID_STATE`. The assignment transitions to `RELEASED` with `outcome_reason` `RELEASED`, `assigned_agent_id` and `current_assignment_id` are cleared, and the agent's `active_lead_count` decrements. The lead then waits in `NEW` until explicitly re-routed.

**Manual reassignment.** While an assignment is still `OFFERED`, a `TeamLeader` or `TeamAdmin` may reassign it: the current assignment becomes `REASSIGNED` with `outcome_reason` `MANUAL`, and a successor `OFFERED` assignment is created for the same lead with `supersedes_assignment_id` pointing at its predecessor and a fresh `claim_deadline_at`, leaving the lead `OFFERED` under the new agent. The request may name the replacement `agent_id` explicitly — a leader override that may exceed the target's capacity but still requires the target to be `ACTIVE` and not on time off — or omit it, in which case the selector runs with the current agent excluded and an empty pool yields `ERR_NO_ELIGIBLE_AGENT`. Reassigning from any assignment status other than `OFFERED` is `ERR_INVALID_STATE`. Assignments list with `lead_id`, `agent_id`, `policy_id`, `supersedes_assignment_id`, and `status` filters, so a reassignment chain can be walked link by link.

**Closing lost and recycling.** The assigned agent, a `TeamLeader`, or a `TeamAdmin` may close a `CLAIMED` or `WORKING` lead as lost with a required `reason`, which is recorded into `close_reason`; any other status is `ERR_INVALID_STATE`, and agent callers must be the assigned agent. The assignment is retained in `CLAIMED` as the historical record while `current_assignment_id` and `assigned_agent_id` clear and the agent's `active_lead_count` decrements. A `CLOSED_LOST` lead may later be recycled by a `TeamLeader` or `TeamAdmin` back to `NEW` — from any other status, `ERR_INVALID_STATE` — preserving its `engagement_score` and `temperature` so that history survives recycling.

**Under contract.** Creating a deal against a `WORKING` lead (§3.6) moves the lead to `UNDER_CONTRACT`, and approving that deal eventually moves it to terminal `CLOSED_WON`.

### 3.5. Engagement Scoring, Lead Temperature, and Nurture Automation

**Engagement events.** An agent (for one of their own leads) or an administrator appends an engagement event carrying a `type` and an `occurred_at` timestamp. Each type earns fixed base `points`: `EMAIL_OPEN` earns 5, `LINK_CLICK` 10, `CALL_ANSWERED` 20, `FORM_SUBMIT` 25, `REPLIED` 30, and `SHOWING_ATTENDED` 40. The log is append-only — events carry `id` and `created_at` only, per §2.5 — and a lead's events can be listed through the lead's engagement collection.

**Decay and score.** An event's `effective_points` decay in steps against the logical clock: full points while the event is younger than 30 days old; half, floored to a whole point, once the event is at least 30 days but younger than 60 days old; and zero at 60 days or older. Age is the whole number of days elapsed between `occurred_at` and now. A lead's `engagement_score` is the sum of `effective_points` over all of its events — no status filter applies — recomputed whenever an event is appended and whenever the score is read.

**Temperature.** The `temperature` dimension is independent of lifecycle status: a lead is `HOT` when its `engagement_score` is at least 75, `WARM` when the score is at least 40 but below 75, and `COLD` below 40 — a score of exactly 40 is `WARM` and exactly 75 is `HOT`. Temperature changes never alter status, and status changes never alter temperature. Whenever a lead's temperature does change, every `ENROLLED` or `PAUSED` nurture enrollment whose campaign's `temperature_target` no longer equals the new temperature exits automatically with `exit_reason` `TEMPERATURE_SHIFT`.

**Campaigns.** A `TeamAdmin` creates a nurture campaign with `team_id`, `name`, a `temperature_target` of `COLD`, `WARM`, or `HOT`, and an ordered `steps` program in which each step pairs an `offset_days` with a `channel`; the program must be non-empty with strictly increasing offsets measured from the enrollment instant, and violations are `ERR_INVALID_REQUEST`. Campaigns are born `DRAFT`. Activation — from `DRAFT` or from `PAUSED` — makes the campaign `ACTIVE`; activating an already `ACTIVE` campaign is `ERR_INVALID_STATE`. Pausing an `ACTIVE` campaign (from any other state, `ERR_INVALID_STATE`) cascades every `ENROLLED` enrollment of the campaign to `PAUSED`, and re-activation cascades those `PAUSED` enrollments back to `ENROLLED`. Campaigns list by `team_id` and `status`.

**Enrollment.** A `TeamLeader` or `TeamAdmin` enrolls a lead by `campaign_id` and `lead_id`. The lead must be `CLAIMED` or `WORKING` (any other status is `ERR_INVALID_STATE`), the campaign must be `ACTIVE` (enrolling against a `DRAFT` or `PAUSED` campaign is `ERR_CAMPAIGN_NOT_ACTIVE`), the lead's current temperature must equal the campaign's `temperature_target` (else `ERR_TEMPERATURE_MISMATCH`), and the lead must not already hold an `ENROLLED` or `PAUSED` enrollment (else `ERR_LEAD_ALREADY_ENROLLED`). A new enrollment snapshots the lead's temperature into `entered_temperature`, starts at `current_step_index` zero, and schedules `next_send_at` at the enrollment instant plus the first step's `offset_days`. During the sweep, any `ENROLLED` enrollment whose `next_send_at` has been reached advances `current_step_index` and re-schedules from the next step's offset; completing the final step transitions the enrollment to `COMPLETED`. A leader or admin may exit an `ENROLLED` or `PAUSED` enrollment manually, recording `exit_reason` `MANUAL`; attempting a manual exit on a `COMPLETED` or `EXITED` enrollment is `ERR_ENROLLMENT_NOT_ACTIVE`. A lead whose deal is approved exits all open enrollments with `exit_reason` `CONVERTED` (§3.6). Enrollments list by `campaign_id`, `lead_id`, and `status`.

### 3.6. Deal Economics: Referral Fees, House Share, and Split Agreements

**Deal creation.** When a `WORKING` lead goes under contract, the assigned agent or a `TeamLeader` creates the deal with the `lead_id` and the estimated `gross_commission_cents` (strictly positive); an agent caller must be the lead's assigned agent, else `ERR_AGENT_IDENTITY_MISMATCH`, and a lead in any status other than `WORKING` is `ERR_INVALID_STATE`. The deal is born `PENDING`; its `team_id` is copied from the lead, its `agent_id` is fixed as the lead's `assigned_agent_id` at creation (the closing agent), and `referral_partner_id` is snapshotted from the lead — frozen thereafter, never a live reference. The lead transitions `WORKING → UNDER_CONTRACT`, and the full commission waterfall below is computed immediately on the estimated basis, marked by `split_basis_type` `ESTIMATED`.

**The waterfall.** The split basis, `split_basis_cents`, is `gross_commission_cents` while the deal is `PENDING`. The derivation order is pinned and must not be reordered, because each step rounds and a different order yields different cents for the same inputs. First the referral fee: `referral_fee_cents` is the basis multiplied by `effective_fee_bps` and divided by 10000, rounded half up to a whole cent — zero when the deal has no referral partner. Second the house share: `house_share_cents` is 3000 basis points (thirty percent) of the post-referral remainder, rounded half up. Third, `agent_pool_cents` is whatever remains of the basis. Finally the pool is distributed into `agent_shares`: when an `ACTIVE` split agreement covers the closing agent at the computation instant, agent A receives the pool multiplied by `a_share_bps` and divided by 10000, rounded half up, and agent B receives the unrounded remainder; otherwise the closing agent receives the entire pool as a single entry. Each share is an object pairing an `agent_id` with its `amount_cents`. This pinned order — basis, then referral fee, then house share, then pool, then A, then B — guarantees money conservation: the referral fee plus the house share plus the sum of the agent shares always equals the basis exactly.

**Referral fee tiers.** A partner's base `fee_bps` — between 0 and 5000 at partner creation, alongside `team_id` and `name` — may earn a volume premium. When the partner's calendar-year approved volume, measured as the sum of `split_basis_cents` over that partner's other deals in `APPROVED` or `PAID_OUT` status with `approved_at` inside the current calendar year of the logical clock, reaches at least 10000000 cents, the `effective_fee_bps` applied is the base fee plus 500 basis points; below the threshold the base fee applies. Volume exactly at the threshold qualifies for the premium, and the deal being computed never counts toward the volume that sets its own tier. Partner records are always `ACTIVE` and carry no lifecycle transitions; partners list by `team_id` and `status`.

**Split agreements.** A `TeamLeader` or `TeamAdmin` records a bilateral split between `agent_a_id` and `agent_b_id` with shares `a_share_bps` and `b_share_bps` over an effectiveness window from `effective_from` (inclusive) to `effective_until` (exclusive), a null `effective_until` meaning open-ended. The two shares must sum to exactly 10000 basis points, else `ERR_SPLIT_SHARE_SUM_INVALID` (HTTP 422), and the pair must be two distinct `ACTIVE` agents of the same team, else `ERR_SPLIT_AGENT_PAIR_INVALID` (HTTP 422). A new agreement whose window overlaps an `ACTIVE` agreement for the same unordered agent pair is rejected with `ERR_SPLIT_WINDOW_OVERLAP` (HTTP 409) under half-open semantics: adjacency is allowed, so a new agreement whose `effective_from` equals the existing agreement's `effective_until` does not conflict. Agreements are born `ACTIVE`. Termination by a leader or admin moves an `ACTIVE` agreement to `TERMINATED` (from any other state, `ERR_INVALID_STATE`), and the sweep moves an agreement whose `effective_until` has been reached or passed to `EXPIRED`; in both cases already-approved deals keep their snapshots. An agreement covers a deal when the closing agent is one of its two sides, it is `ACTIVE`, and the computation instant falls inside its window — the deal-creation instant for the estimated variant and the approval instant for the actual variant. The deal's `split_agreement_id` snapshots the agreement applied at approval and is null when none applied. Agreements list by `team_id`, `agent_a_id`, `agent_b_id`, `status`, and an `agent_id` filter that matches either side of the pair.

**Approval.** Only a `TeamLeader` approves deals, and that caller must resolve to an agent with `role_on_team` `LEADER` on the deal's team, else `ERR_AGENT_IDENTITY_MISMATCH`. Approval is allowed from `PENDING` or `DISPUTED`; from `APPROVED` or `PAID_OUT` the attempt is `ERR_DEAL_NOT_APPROVABLE`. The request may carry `actual_gross_commission_cents` (strictly positive when provided); when provided, the basis switches to the actual figure, `split_basis_type` becomes `ACTUAL`, and every derived split field is recomputed — including the referral tier snapshot and any split-agreement coverage, both re-evaluated at the approval instant. When no actual figure is provided, the basis remains the estimated `gross_commission_cents`. The `approved_at` timestamp is stamped at each approval, so a re-approval after a dispute moves it to the latest approval. Approval cascades to the lead: it becomes `CLOSED_WON`, the closing agent's `active_lead_count` decrements, `trailing_90d_conversions` is recomputed and the agent's tier re-evaluated, and any `ENROLLED` or `PAUSED` nurture enrollment for the lead exits with `exit_reason` `CONVERTED`.

**Disputes and payout.** A `TeamAdmin` may dispute an `APPROVED` deal, recording a `dispute_reason`; disputing from any other status is `ERR_INVALID_STATE`. The lead remains `CLOSED_WON`, and the split fields are retained until a corrected re-approval replaces the basis with the corrected actual figure and recomputes every derived field. A `TeamAdmin` may also mark an `APPROVED` deal paid, moving it to terminal `PAID_OUT` (from any other status, `ERR_INVALID_STATE`). Deals list by `team_id`, `lead_id`, `agent_id`, and `status`.

### 3.7. Performance Tiers, Accountability, and Source ROI

**Performance tiers.** An agent's `performance_tier` derives from the trailing record: `PLATINUM` requires at least 8 trailing-90-day conversions together with an average first response of at most 300 seconds (five minutes); `GOLD` requires at least 4 conversions together with an average of at most 900 seconds (fifteen minutes); `SILVER` requires at least 1 conversion; anything else is `BRONZE`. Both boundary comparisons are inclusive — exactly 4 conversions with an average of exactly 900 seconds earns `GOLD`, and exactly 8 conversions with exactly 300 seconds earns `PLATINUM` — and an agent with no recorded responses, whose `avg_first_response_seconds` is null, cannot reach `GOLD` or `PLATINUM` regardless of conversions. The tier is recomputed after every conversion, claim, first response, and production-stats import.

**Accountability scorecard.** The scorecard is computed on read from the agent's current counters. The claim rate `claim_rate_bps` is `trailing_90d_claimed` multiplied by 10000 and divided by `trailing_90d_offered` using floor division, with a zero offered count treated as one. The speed score `speed_score_bps` is 10000 when `avg_first_response_seconds` is set and is at most the effective speed window — the active policy's `speed_to_lead_window_seconds` override when set, otherwise the team default; it is 0 when the agent has no recorded responses; otherwise it is the effective window multiplied by 10000 and divided by the average response time, using floor division. The conversion rate `conversion_rate_bps` is `trailing_90d_conversions` multiplied by 10000 and divided by `trailing_90d_claimed` using floor division, again with a zero denominator treated as one. The composite `accountability_score_bps` is the weighted mean — five parts claim rate, three parts speed score, two parts conversion rate — divided by ten and rounded half up. The response bundles these four figures with `agent_id`, `performance_tier`, `active_lead_count`, `trailing_90d_conversions`, `trailing_90d_claimed`, `trailing_90d_offered`, and `avg_first_response_seconds`.

**Source ROI.** Source ROI is computed on read over a rolling window that ends at the logical now and spans `window_days` days (default 90), under a `basis` of `REALIZED` (the default) or `PROJECTED`. The cohort is every lead whose `source_id` matches and whose `created_at` falls inside the window; `leads_count` is its size, and `spend_cents` is the cohort size multiplied by `cost_per_lead_cents`. Under `REALIZED`, `attributed_commission_cents` sums `split_basis_cents` over the cohort's deals in `APPROVED` or `PAID_OUT` status, and `conversions_count` counts those deals. Under `PROJECTED`, the realized sum is augmented by the open pipeline: each cohort lead in `OFFERED`, `CLAIMED`, `WORKING`, or `UNDER_CONTRACT` contributes its `expected_close_price_cents` scaled by an estimated commission rate of 300 basis points (three percent) and then by its temperature's closing probability — 500 basis points for `COLD`, 2000 for `WARM`, 4500 for `HOT` — with each lead's contribution rounded half up to a whole cent. The return `roi_bps` is the attributed commission minus the spend, the difference multiplied by 10000 and divided by the spend using floor division; when the spend is zero, `roi_bps` is null. The response carries `source_id`, `window_days`, `basis`, `leads_count`, `conversions_count`, `spend_cents`, `attributed_commission_cents`, and `roi_bps`.

## 4. Endpoint Definitions

Endpoints that create a new resource return HTTP 201; endpoints that modify or transition an existing resource return HTTP 200. All responses use the envelope of §2.2, and list endpoints paginate per §2.3. The table below is a summary only — request payloads, response fields, and side effects are specified by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/_clock/set_current_utc` | Set the logical clock and run the deadline sweep | TeamAdmin |
| POST | `/crm/teams` | Create a team | TeamAdmin |
| GET | `/crm/teams/{teamId}` | Get a team | TeamAdmin, TeamLeader, Agent, ReferralPartner |
| POST | `/crm/agents` | Create an agent in `ONBOARDING` | TeamAdmin |
| GET | `/crm/agents/{agentId}` | Get an agent | TeamAdmin, TeamLeader, Agent, ReferralPartner |
| GET | `/crm/agents` | List agents with filters and pagination | TeamAdmin, TeamLeader, Agent, ReferralPartner |
| POST | `/crm/agents/{agentId}/activate` | Activate an `ONBOARDING` agent | TeamAdmin |
| POST | `/crm/agents/{agentId}/pause` | Pause an `ACTIVE` agent, cascade-expire its offers, re-route affected leads | TeamAdmin, TeamLeader |
| POST | `/crm/agents/{agentId}/resume` | Resume a `PAUSED` agent and reset its miss streak | TeamAdmin, TeamLeader |
| POST | `/crm/agents/{agentId}/offboard` | Drain and offboard an `ACTIVE` or `PAUSED` agent | TeamAdmin |
| GET | `/crm/agents/{agentId}/scorecard` | Computed accountability scorecard | TeamAdmin, TeamLeader, Agent, ReferralPartner |
| POST | `/crm/agents/{agentId}/import-production-stats` | Backfill trailing-90-day production counters and recompute the tier | TeamAdmin |
| POST | `/crm/agents/{agentId}/time-offs` | Create an approved time-off block | Agent, TeamAdmin |
| GET | `/crm/agents/{id}/time-offs` | List an agent's time-off blocks | TeamAdmin, TeamLeader, Agent, ReferralPartner |
| POST | `/crm/routing-policies` | Create a `DRAFT` routing policy | TeamAdmin |
| GET | `/crm/routing-policies/{policyId}` | Get a routing policy | TeamAdmin, TeamLeader, Agent, ReferralPartner |
| GET | `/crm/routing-policies` | List routing policies | TeamAdmin, TeamLeader, Agent, ReferralPartner |
| POST | `/crm/routing-policies/{policyId}/activate` | Activate a `DRAFT` policy under optimistic concurrency, superseding the current one | TeamAdmin |
| POST | `/crm/lead-sources` | Create a lead source | TeamAdmin |
| GET | `/crm/lead-sources/{sourceId}` | Get a lead source | TeamAdmin, TeamLeader, Agent, ReferralPartner |
| GET | `/crm/lead-sources` | List lead sources | TeamAdmin, TeamLeader, Agent, ReferralPartner |
| POST | `/crm/lead-sources/{sourceId}/pause` | Pause a source; intake from it is rejected while paused | TeamAdmin |
| POST | `/crm/lead-sources/{sourceId}/resume` | Resume a `PAUSED` source | TeamAdmin |
| GET | `/crm/lead-sources/{sourceId}/roi` | Computed source ROI, `REALIZED` or `PROJECTED` | TeamAdmin, TeamLeader, Agent, ReferralPartner |
| POST | `/crm/leads` | Lead intake with budget enforcement and optional auto-route | TeamAdmin, TeamLeader, ReferralPartner |
| GET | `/crm/leads/{leadId}` | Get a lead | TeamAdmin, TeamLeader, Agent, ReferralPartner |
| GET | `/crm/leads` | List leads with filters and pagination | TeamAdmin, TeamLeader, Agent, ReferralPartner |
| POST | `/crm/leads/{leadId}/route` | Manually route a `NEW` lead through the active policy's selector | TeamAdmin, TeamLeader |
| POST | `/crm/leads/{leadId}/claim` | The offered agent claims the lead at or before its claim deadline | Agent |
| POST | `/crm/leads/{leadId}/release` | Release a `CLAIMED` or `WORKING` lead back to the pool | Agent, TeamLeader, TeamAdmin |
| POST | `/crm/leads/{leadId}/log-response` | Record the assigned agent's first response | Agent |
| POST | `/crm/leads/{leadId}/engagement-events` | Append an engagement event and recompute score and temperature | Agent, TeamAdmin |
| GET | `/crm/leads/{id}/engagement-events` | List a lead's engagement events | TeamAdmin, TeamLeader, Agent, ReferralPartner |
| POST | `/crm/leads/{leadId}/close-lost` | Close a `CLAIMED` or `WORKING` lead as lost | Agent, TeamLeader, TeamAdmin |
| POST | `/crm/leads/{leadId}/recycle` | Recycle a `CLOSED_LOST` lead back to `NEW` | TeamLeader, TeamAdmin |
| GET | `/crm/assignments/{assignmentId}` | Get an assignment | TeamAdmin, TeamLeader, Agent, ReferralPartner |
| GET | `/crm/assignments` | List assignments with filters, including chain traversal | TeamAdmin, TeamLeader, Agent, ReferralPartner |
| POST | `/crm/assignments/{assignmentId}/reassign` | Reassign an `OFFERED` assignment to a new agent | TeamLeader, TeamAdmin |
| POST | `/crm/nurture-campaigns` | Create a nurture campaign | TeamAdmin |
| GET | `/crm/nurture-campaigns/{campaignId}` | Get a nurture campaign | TeamAdmin, TeamLeader, Agent, ReferralPartner |
| GET | `/crm/nurture-campaigns` | List nurture campaigns | TeamAdmin, TeamLeader, Agent, ReferralPartner |
| POST | `/crm/nurture-campaigns/{campaignId}/activate` | Activate a `DRAFT` campaign or resume a `PAUSED` one | TeamAdmin |
| POST | `/crm/nurture-campaigns/{campaignId}/pause` | Pause an `ACTIVE` campaign and its enrollments | TeamAdmin |
| POST | `/crm/nurture-enrollments` | Enroll a temperature-matching `CLAIMED` or `WORKING` lead | TeamLeader, TeamAdmin |
| GET | `/crm/nurture-enrollments/{enrollmentId}` | Get an enrollment | TeamAdmin, TeamLeader, Agent, ReferralPartner |
| GET | `/crm/nurture-enrollments` | List enrollments | TeamAdmin, TeamLeader, Agent, ReferralPartner |
| POST | `/crm/nurture-enrollments/{enrollmentId}/exit` | Manually exit an `ENROLLED` or `PAUSED` enrollment | TeamLeader, TeamAdmin |
| POST | `/crm/referral-partners` | Create a referral partner | TeamAdmin |
| GET | `/crm/referral-partners/{partnerId}` | Get a referral partner | TeamAdmin, TeamLeader, Agent, ReferralPartner |
| GET | `/crm/referral-partners` | List referral partners | TeamAdmin, TeamLeader, Agent, ReferralPartner |
| POST | `/crm/split-agreements` | Create an `ACTIVE` split agreement for an agent pair | TeamLeader, TeamAdmin |
| GET | `/crm/split-agreements/{agreementId}` | Get a split agreement | TeamAdmin, TeamLeader, Agent, ReferralPartner |
| GET | `/crm/split-agreements` | List split agreements | TeamAdmin, TeamLeader, Agent, ReferralPartner |
| POST | `/crm/split-agreements/{agreementId}/terminate` | Terminate an `ACTIVE` agreement; approved deals keep their snapshots | TeamLeader, TeamAdmin |
| POST | `/crm/deals` | Create a `PENDING` deal for a `WORKING` lead, moving it `UNDER_CONTRACT` | Agent, TeamLeader |
| GET | `/crm/deals/{dealId}` | Get a deal | TeamAdmin, TeamLeader, Agent, ReferralPartner |
| GET | `/crm/deals` | List deals with filters | TeamAdmin, TeamLeader, Agent, ReferralPartner |
| POST | `/crm/deals/{dealId}/approve` | Approve a `PENDING` or `DISPUTED` deal, cascading the lead to `CLOSED_WON` | TeamLeader |
| POST | `/crm/deals/{dealId}/dispute` | Move an `APPROVED` deal to `DISPUTED` pending correction | TeamAdmin |
| POST | `/crm/deals/{dealId}/mark-paid` | Mark an `APPROVED` deal `PAID_OUT` | TeamAdmin |

## 5. Error Code Catalogue

The catalogue below lists every error identifier with its HTTP status. Trigger conditions are specified in the narratives of §2 and §3, not here.

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_FORBIDDEN_FOR_ROLE | 403 |
| ERR_INVALID_REQUEST | 400 |
| ERR_NOT_FOUND | 404 |
| ERR_AGENT_IDENTITY_MISMATCH | 403 |
| ERR_NOT_OFFERED_TO_AGENT | 403 |
| ERR_PARTNER_IDENTITY_MISMATCH | 403 |
| ERR_INVALID_STATE | 409 |
| ERR_SOURCE_NOT_ACTIVE | 409 |
| ERR_NO_ACTIVE_POLICY | 409 |
| ERR_POLICY_NOT_ACTIVATABLE | 409 |
| ERR_DEAL_NOT_APPROVABLE | 409 |
| ERR_ENROLLMENT_NOT_ACTIVE | 409 |
| ERR_CAMPAIGN_NOT_ACTIVE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_TIME_OFF_OVERLAP | 409 |
| ERR_SPLIT_WINDOW_OVERLAP | 409 |
| ERR_SPLIT_SHARE_SUM_INVALID | 422 |
| ERR_SPLIT_AGENT_PAIR_INVALID | 422 |
| ERR_DUPLICATE_LICENSE_NUMBER | 409 |
| ERR_DUPLICATE_OPEN_LEAD | 409 |
| ERR_REFERRAL_PARTNER_REQUIRED | 422 |
| ERR_TEMPERATURE_MISMATCH | 409 |
| ERR_LEAD_ALREADY_ENROLLED | 409 |
| ERR_SOURCE_BUDGET_EXHAUSTED | 409 |
| ERR_NO_ELIGIBLE_AGENT | 409 |
