# Giving Circle API — Product Requirements Document

## 1. Introduction

A giving circle inverts the usual grant-making hierarchy: a community of members pools charitable contributions, studies candidate nonprofits together, and votes collectively on where the money goes. This document specifies the Giving Circle API, the platform contract for operating that collective process end to end — member recruitment at tiered contribution levels, pooled-fund accounting under a host organization's administration fee, nonprofit nomination and evidence-based vetting, member voting with quorum enforcement, tranche-based grant disbursement under segregation of duties, and grantee reporting whose timeliness feeds back into each nonprofit's standing and into the next membership year.

The annual giving cycle is the organizing unit. Each cycle walks a nine-phase pipeline from `DRAFT` through `CLOSED`, and every phase gate, tally rule, budget figure, and cascade in this document is defined against that pipeline. Two implementation commitments shape everything that follows. First, all money is tracked as integer cents, and every derived ledger figure is recomputed immediately on each financial mutation, so the pooled balance and both grant budgets are never stale. Second, all time-driven behavior — the voting window, report deadlines, site-visit no-shows — is evaluated against a logical clock that administrators control, never against wall-clock time. All endpoints are mounted under `/api`. Section 2 fixes the system-wide contracts; Section 3 walks the business workflows in narrative form; Sections 4 and 5 summarize the endpoint surface and the error catalogue.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity. A request missing either header, or carrying a role value outside the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Four roles exist: `CircleAdmin`, `FinanceOfficer`, `Member`, and `GranteeContact`. Each write endpoint restricts which roles may invoke it (Section 4); a caller whose role is not listed for that endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

How `X-User-ID` binds to stored data depends on the role. When `X-User-Role` is `CircleAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `requested_by_user_id` on the payouts that an award advance creates — but it does not compare it to any entity's `id`. The same holds when `X-User-Role` is `FinanceOfficer`: the identifier is opaque, is recorded as `approved_by_user_id` when the officer approves a payout, and participates only in user-identifier comparisons such as the segregation-of-duties check described in §3.7, never in entity-ownership comparisons.

When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`; ownership checks on any resource that references a `Member` compare the resource's foreign-key field to `X-User-ID` — a membership's `member_id`, the membership reached through a contribution's `membership_id`, a nomination's `nominated_by_membership_id`, or a ballot's `membership_id`. When `X-User-Role` is `GranteeContact`, `X-User-ID` is the `id` of the acting `Nonprofit`; ownership checks compare a nomination's or an award's `nonprofit_id` to `X-User-ID`. A failed ownership check is rejected with `ERR_FORBIDDEN` (HTTP 403).

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

List endpoints paginate through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0.

Unless an endpoint states a different deterministic order, every list endpoint returns resources sorted by `created_at` in ascending order. Two collections override this default: payouts list in `tranche` ascending order, and grantee reports list in `due_at` ascending order (which places the `INTERIM` report before the `FINAL` report of the same award).

List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. The Logical Clock

All time-dependent behavior in the platform reads a logical clock, never wall-clock time. Before any administrative call sets it, the logical clock reads exactly `2026-05-01T00:00:00Z`, and it never falls back to wall-clock time on its own. A `CircleAdmin` advances the clock through a test-driving capability that takes a `to_iso8601` timestamp and returns the resulting `current_utc`.

Every clock advance evaluates the time-driven transitions of §3: a grantee report whose `due_at` has passed while the report is still `DUE` flips to `OVERDUE` and fires the standing cascade of §3.8, and a site visit whose `ends_at` has passed while the visit is still `SCHEDULED` flips to `NO_SHOW` per §3.5. The voting-window comparisons of §3.6 and the phase-advance guard of §3.7 also evaluate against this clock.

### 2.5. Common Resource Properties

Every resource in the system — circles, cycles, members, memberships, contributions, nonprofits, nominations, site visits, learning sessions, ballots, awards, payouts, reports, and rollover decisions — carries a standard set of system-managed fields:

- **`id` (string):** a unique, server-minted identifier formatted as a UUID, with no type prefix.
- **`created_at` (string):** an ISO 8601 UTC timestamp with three fractional digits (e.g., `2026-05-01T09:15:00.123Z`), set when the resource is first created.
- **`updated_at` (string):** an ISO 8601 UTC timestamp with three fractional digits, refreshed on every change to the resource.
- **`version` (integer):** a system-managed integer that increments with every modification to the resource.

A mutation is any change the server persists, including system-driven recomputation of derived fields: when a cascade recomputes a parent counter or ledger figure, the parent's `updated_at` refreshes and its `version` increments just as if a client had written it.

### 2.6. The Cycle Ledger and Derived-Field Reconciliation

Each giving cycle maintains a family of derived ledger figures that the server recomputes immediately on every financial mutation; clients never write them. Six totals accumulate activity: `received_total_cents` is the sum of `amount_cents` over the cycle's contributions in `RECEIVED` (a contribution in `REFUND_REQUESTED` still counts as received, because its funds remain in the pool until the refund is approved); `pledged_outstanding_cents` sums `amount_cents` over contributions in `PLEDGED`; `refunded_total_cents` sums contributions in `REFUNDED`; `released_total_cents` sums the cycle's payouts in `RELEASED`; `admin_fee_transferred_cents` is the host administration fee moved out of the pool in a single transfer at the award lock; and the rollover pair `rollover_in_cents` and `rollover_out_cents` records funds carried into or out of the cycle by executed `CARRY_FORWARD` rollover decisions.

From these totals, `pooled_balance_cents` is what remains of received funds after subtracting the refunded total, the released total, and the transferred administration fee, then adding rollover funds carried in and subtracting rollover funds carried out. Here "received funds" means the gross inflow — everything ever received, including funds later refunded — so the refunded terms cancel and the pooled balance equals `received_total_cents` minus the released total and the transferred administration fee, plus rollover in, minus rollover out; the refund is never subtracted twice. Two grant-budget variants share one shape: from a base, subtract the administration fee on that base, then subtract the cycle's snapshotted `operating_reserve_cents`. The fee on a base is the base multiplied by the cycle's `admin_fee_percent` and divided by one hundred, rounded half up to whole cents. The provisional variant, `grant_budget_provisional_cents`, builds its base from received funds plus outstanding pledges, so it reads at least as high as the final variant whenever pledges remain outstanding; it is the planning figure and is recomputed on every financial mutation in any phase. The final variant, `grant_budget_final_cents`, builds its base from received funds only; it is the authoritative figure at award time, and once `budget_locked` becomes `true` at the award lock the final figure is frozen and never moves again, while the provisional figure continues to track mutations. A separate derived counter, `ballots_cast_count`, counts the cycle's ballots. A dedicated ledger read on the cycle returns exactly these ten figures — the six totals, the pooled balance, and both budget variants.

Derived counters elsewhere obey the same recompute-on-mutation discipline: a circle's `active_member_count` and `renewed_member_count`, and a session's `seats_taken`, move only through server-side recomputation when the underlying memberships or reservations change, and each such recomputation bumps the owning resource's `version` and `updated_at` per §2.5.

### 2.7. Monetary Precision and Rounding

All monetary amounts are integer cents; fractional cents never occur anywhere in the system. Round-half-up appears in exactly the places that name it: the administration fee in both budget variants, the single administration-fee transfer at the award lock, the weighted `vetting_score` (rounded half up to a whole number), and the raw award amount (rounded half up to whole cents before clamping). Rounding down appears in exactly two places: the first payout tranche is floored to whole cents, and each member credit in a pro-rata residual distribution is floored to whole cents. Everything else — pooled-balance arithmetic, tally points, quorum counts — is exact integer arithmetic with no rounding at all.

### 2.8. Optimistic Concurrency Control

Two write paths are guarded by optimistic concurrency control, and no other endpoint takes a version field.

Advancing a cycle requires the request to carry `expected_cycle_version`, holding the cycle `version` the caller last observed. If that value does not match the cycle's current `version` — because an earlier advance, a contribution receipt, a payout release, or any cascaded ledger recompute has moved the version since the caller read it — the advance is rejected with `ERR_STALE_VERSION` (HTTP 412), so a caller never advances a cycle it has not observed.

Recasting a ballot works the same way with `expected_ballot_version` against the ballot's current `version`. When the ballot's version has advanced since the caller last read it, the recast is rejected with `ERR_STALE_VERSION` (HTTP 412), so an older view never silently overwrites a superseding allocation.

### 2.9. Validation Discipline and Resource Existence

Every request passes through a fixed evaluation order, and an earlier failure masks every later check. Authentication comes first (§2.1, `ERR_UNAUTHENTICATED`), then role authorization for the endpoint (`ERR_FORBIDDEN`), then the ownership check on member- and grantee-scoped resources (`ERR_FORBIDDEN`). Next, every identifier the request names — path identifiers and body foreign keys alike — is resolved left to right, and the first identifier that does not correspond to an existing resource fails the request with `ERR_NOT_FOUND` (HTTP 404). Every collection addresses its resources by an identifier path parameter named after the resource: `circle_id`, `cycle_id`, `member_id`, `membership_id`, `contribution_id`, `nonprofit_id`, `nomination_id`, `visit_id`, `session_id`, `ballot_id`, `award_id`, `payout_id`, `report_id`, and `decision_id`.

Only then do state checks run, in this order: the target entity's from-state validity (`ERR_INVALID_STATE`), the cycle-phase gate (`ERR_CYCLE_PHASE`), and the membership-active gate (`ERR_MEMBERSHIP_NOT_ACTIVE`). The cycle advance evaluates its own guard sequence — on that operation the stale-version precondition of §2.8 is checked first, ahead of the per-hop guards of §3, which carry their specific error ids. Business rules come last, in this relative order: segregation of duties on payout approval; the temporal windows (voting window, refund window); uniqueness constraints; calendar overlap rules; capacity and counter limits; referenced-entity state (nonprofit standing, completed site visits, interim-report acceptance); ballot reference and points-budget rules; and finally the fiscal thresholds (tier minimums, the vetting score gate, and the refund underfunding guard).

### 2.10. Calendar Integrity: Windows, Overlaps, and Buffers

On any site visit or learning session, `starts_at` must be strictly earlier than `ends_at`; a window that violates this is rejected as a malformed request with `ERR_INVALID_REQUEST` (HTTP 400).

Site visits for the same nonprofit follow a half-open overlap rule: a new or rescheduled visit conflicts only with visits in `SCHEDULED` or `COMPLETED` whose intervals truly overlap it, and back-to-back adjacency — one visit's `ends_at` equal to another's `starts_at` — is allowed because the intervals are half-open. A conflict is rejected with `ERR_SITE_VISIT_OVERLAP` (HTTP 409), and the rule applies both when a visit is first scheduled and when it is rescheduled.

Learning sessions within one cycle's calendar require a fifteen-minute buffer: a new session must leave at least fifteen minutes between its window and the window of every other `SCHEDULED` session in the same cycle, in either direction. A violation is rejected with `ERR_SESSION_OVERLAP_BUFFER` (HTTP 409).

## 3. Business Logic & Workflows

### 3.1. Founding a Circle and Opening a Giving Cycle

A `CircleAdmin` founds a circle by supplying its `name` and the five numbers that govern its economics: `admin_fee_percent`, the host organization's percentage share of received funds, an integer from 0 to 20; `quorum_percent`, the percentage of active memberships that must cast ballots for a valid vote, an integer from 1 to 100; `standard_minimum_cents`, the minimum contribution for the `STANDARD` tier, strictly greater than zero; `leader_minimum_cents`, the minimum for the `LEADER` tier, strictly greater than `standard_minimum_cents`; and `operating_reserve_cents`, the reserve subtracted from pooled funds before grant budgeting, zero or greater. The founder also selects the `vetting_profile` — `BALANCED` or `EQUITY_FIRST` — which selects the vetting-score weight variant of §3.4. A request whose values fall outside these ranges or whose enum value is unrecognized is malformed and fails with `ERR_INVALID_REQUEST`. A new circle's `active_member_count` and `renewed_member_count` both start at zero.

Opening a giving cycle takes a `circle_id` and a human `year_label` such as `2026`. The cycle is created in `DRAFT` and snapshots three circle settings at creation: `quorum_percent`, `admin_fee_percent`, and `operating_reserve_cents` are copied onto the cycle, so later edits to the circle never retroactively change a cycle in flight.

From there the cycle walks nine phases — `DRAFT`, `RECRUITMENT`, `POOLING`, `NOMINATION`, `VETTING`, `VOTING`, `AWARD`, `REPORTING`, `CLOSED` — through a single advance operation that moves the `phase` exactly one hop forward. Only a `CircleAdmin` may advance a cycle. Every advance must carry `expected_cycle_version` under the optimistic-concurrency rule of §2.8, and every successful advance increments the cycle's `version` by one. The first hop, `DRAFT` → `RECRUITMENT`, carries no guard beyond the version check. Moving `RECRUITMENT` → `POOLING` requires at least one membership of the circle to be `ACTIVE`; with zero active memberships the advance fails with `ERR_NO_ACTIVE_MEMBERS`. Moving `POOLING` → `NOMINATION` requires money actually received: if `received_total_cents` is zero the advance fails with `ERR_EMPTY_POOL`. The remaining hops are guarded in their own sections below.

### 3.2. Memberships and the Annual Retention Cycle

Member records are registered by a `CircleAdmin` with a `full_name` and an `email`. Email uniqueness is case-insensitive: registering a second member whose address differs only in letter case is a duplicate and fails with `ERR_INVALID_REQUEST`.

A `CircleAdmin` then invites a member into a circle at a contribution `tier` — `STANDARD` or `LEADER` — by supplying `member_id` and `circle_id`. The new membership starts in `INVITED`. Only the invited member may accept: the acting member's `X-User-ID` must equal the membership's `member_id`, or the accept fails with `ERR_FORBIDDEN`. Acceptance moves the membership `INVITED` → `ACTIVE` and recomputes the circle's `active_member_count`.

When a cycle closes (§3.8), every membership of the circle still in `ACTIVE` flips automatically to `RENEWAL_DUE`, opening the retention window. The member renews their own membership — again an ownership check against `member_id`, and only from `RENEWAL_DUE` (otherwise `ERR_INVALID_STATE`) — which returns it to `ACTIVE`, adds one to its `renewal_count`, and recomputes both `active_member_count` and the circle's `renewed_member_count`, the running sum of `renewal_count` across the circle's memberships. A `CircleAdmin` may instead lapse a membership that sits in `RENEWAL_DUE`, moving it to `LAPSED` (any other from-state fails with `ERR_INVALID_STATE`) and recomputing `active_member_count`.

A member may withdraw their own membership from either `ACTIVE` or `RENEWAL_DUE`; the membership ends in `WITHDRAWN`, and the withdrawal cascades: every contribution of that membership still in `PLEDGED` is voided to `VOIDED`, each voided contribution's `amount_cents` is subtracted from the cycle's `pledged_outstanding_cents`, the provisional grant budget is recomputed, and the circle's `active_member_count` is recomputed. `LAPSED` and `WITHDRAWN` are terminal. Separately, a membership's `credit_balance_cents` accumulates residual credits granted by pro-rata rollover executions (§3.8); it starts at zero.

### 3.3. Pooling Contributions and the Refund Protocol

While a cycle is in `POOLING`, a member pledges a contribution by naming the `cycle_id`, their `membership_id`, and an `amount_cents`. Three gates apply, after the ownership check against the membership: the cycle must be in `POOLING` (otherwise `ERR_CYCLE_PHASE`), the membership must be `ACTIVE` (otherwise `ERR_MEMBERSHIP_NOT_ACTIVE`), and the amount must meet the tier minimum — `STANDARD` memberships pledge at least the circle's `standard_minimum_cents`, `LEADER` memberships at least `leader_minimum_cents`, and a shortfall fails with `ERR_BELOW_TIER_MINIMUM`. A pledge is created in `PLEDGED`; its amount is added to the cycle's `pledged_outstanding_cents` and the provisional budget is recomputed immediately.

Recording receipt is a `CircleAdmin` action and likewise requires the cycle to still be in `POOLING` (`ERR_CYCLE_PHASE`) and the contribution to be in `PLEDGED` (`ERR_INVALID_STATE`). Receipt moves the contribution `PLEDGED` → `RECEIVED`, stamps `received_at` from the logical clock, adds the amount to `received_total_cents`, subtracts it from `pledged_outstanding_cents`, and recomputes `pooled_balance_cents` together with both grant-budget variants (the final variant freezes only once `budget_locked` is set at the award lock).

A member who has second thoughts requests a refund on their own contribution. The request is valid only from `RECEIVED` (`ERR_INVALID_STATE`) and only while the cycle's phase is one of `POOLING`, `NOMINATION`, `VETTING`, `VOTING`, or `AWARD`; once the cycle has moved past `AWARD`, or before pooling has begun, the request fails with `ERR_REFUND_WINDOW_CLOSED`. A successful request moves the contribution `RECEIVED` → `REFUND_REQUESTED`; per §2.6 the funds still count as received in both budget bases while the request is pending.

Refund decisions belong to the `CircleAdmin`. Approval moves `REFUND_REQUESTED` → `REFUNDED`, but only if the pool remains funded afterward: the pooled balance minus the refunded `amount_cents` must still be at least the sum of `amount_cents` over the cycle's payouts in `SCHEDULED` or `APPROVED`, or the approval fails with `ERR_REFUND_UNDERFUNDS_AWARDS`. An approved refund subtracts the amount from `received_total_cents`, adds it to `refunded_total_cents`, and recomputes the pooled balance and the provisional budget; the final budget does not move once `budget_locked` is set. Denial moves the contribution `REFUND_REQUESTED` → `RECEIVED` with no ledger movement. `REFUNDED` and `VOIDED` are the terminal states, and `VOIDED` is reachable only through the withdrawal cascade of §3.2.

### 3.4. Nominating Nonprofits and the Vetting Gauntlet

The nonprofit registry is maintained by a `CircleAdmin`, who registers each organization with its `ein`, `legal_name`, and free-form `mission_category`. The EIN is unique across the registry; a duplicate registration fails with `ERR_EIN_CONFLICT`. Every nonprofit's `standing` begins at `GOOD`.

During the `NOMINATION` phase, an active member nominates a nonprofit by supplying `cycle_id`, `nonprofit_id`, and a rationale `statement`. The server resolves `nominated_by_membership_id` from the acting member's `X-User-ID` — the nomination is attributed to that member's active membership in the cycle's circle. Nomination requires the cycle to be in `NOMINATION` (`ERR_CYCLE_PHASE`), the membership to be `ACTIVE` (`ERR_MEMBERSHIP_NOT_ACTIVE`), and the nonprofit's `standing` to be `GOOD` (`ERR_NONPROFIT_SUSPENDED`). Each membership may nominate once per cycle: a second nomination by the same membership in the same cycle fails with `ERR_DUPLICATE_NOMINATION`. A nomination is born in `SUBMITTED`.

Both the nominating member and the administration retain exit ramps before finalist selection. The nominating member may withdraw the nomination from `SUBMITTED`, `VETTING`, or `NEEDS_INFO`, ending it in `WITHDRAWN`; the ownership check runs against `nominated_by_membership_id`, and any other from-state fails with `ERR_INVALID_STATE`. A `CircleAdmin` may reject from the same three states, ending the nomination in `REJECTED`. Closing the nomination slate is itself a cycle advance: `NOMINATION` → `VETTING` requires at least one nomination of the cycle in `SUBMITTED`, failing with `ERR_NO_NOMINATIONS` otherwise.

Vetting begins per nomination when a `CircleAdmin` starts vetting, moving `SUBMITTED` → `VETTING`; this requires the cycle to be in `VETTING` (`ERR_CYCLE_PHASE`) and the nomination in `SUBMITTED` (`ERR_INVALID_STATE`). Scoring is recorded by a `CircleAdmin` updating the nomination's three inputs — `financial_health`, `mission_alignment`, and `org_capacity`, each an integer from 0 to 100. The computed `vetting_score` stays null until all three inputs are set; once they are, each update recomputes it as a weighted sum rounded half up to a whole number, with weights selected by the circle's `vetting_profile`. Under `BALANCED`, the score is forty percent of `financial_health`, thirty percent of `mission_alignment`, and thirty percent of `org_capacity`. Under `EQUITY_FIRST`, the score is twenty-five percent of `financial_health`, fifty percent of `mission_alignment`, and twenty-five percent of `org_capacity` — the same inputs can therefore pass under one profile and fail under the other.

When the administration needs more from the grantee, requesting information moves `VETTING` → `NEEDS_INFO` and increments `info_rounds_used`, which starts at zero. At most two information rounds exist per nomination: once `info_rounds_used` reaches two, a further request fails with `ERR_INFO_ROUND_EXHAUSTED`. The grantee answers through a `GranteeContact` whose `X-User-ID` must equal the nomination's `nonprofit_id` (`ERR_FORBIDDEN` otherwise); submitting the requested information returns the nomination `NEEDS_INFO` → `VETTING`.

Promotion to finalist is the gauntlet's exit gate, and it enforces four checks beyond the from-state and phase guards: the cycle must be in `VETTING` and the nomination in `VETTING` (`ERR_INVALID_STATE` otherwise); the nonprofit's `standing` must be `GOOD` (`ERR_NONPROFIT_SUSPENDED`); the `vetting_score` must be at least 70, so a 69 fails with `ERR_VETTING_SCORE_BELOW_THRESHOLD`; and at least one site visit of the nomination must have reached `COMPLETED`, failing with `ERR_SITE_VISIT_REQUIRED` otherwise. Success moves the nomination `VETTING` → `FINALIST`. Note that a nomination can also be rejected without any administrative action: the standing cascade of §3.8 rejects in-flight nominations automatically when their nonprofit falls out of good standing.

### 3.5. Site Visits and Learning Sessions

Site visits are scheduled by a `CircleAdmin` against a nomination under vetting, supplying the `nomination_id` and a `starts_at`/`ends_at` window; the visit is created in `SCHEDULED`. Scheduling enforces the calendar rules of §2.10: the window must start strictly before it ends (`ERR_INVALID_REQUEST`), and it must not truly overlap another `SCHEDULED` or `COMPLETED` visit for the same nonprofit, with adjacency allowed (`ERR_SITE_VISIT_OVERLAP`).

A visit is completed only after it has run its course: completion requires the visit still in `SCHEDULED` and the logical clock at or past `ends_at` (either failure is `ERR_INVALID_STATE`), and it records the visiting team's `findings_note`. If the clock instead moves strictly past `ends_at` while the visit is still `SCHEDULED`, the visit flips automatically to `NO_SHOW`. A `CircleAdmin` may also cancel a `SCHEDULED` visit outright to `CANCELLED`. Both dead-end states are recoverable: rescheduling a visit in `CANCELLED` or `NO_SHOW` returns it to `SCHEDULED` with a replacement `starts_at`/`ends_at` window, re-applying the same overlap rule, and failing any other from-state with `ERR_INVALID_STATE`. `COMPLETED` and `CANCELLED` are terminal.

Learning sessions are the circle's education track. A `CircleAdmin` schedules one with the `cycle_id`, a `title`, a `starts_at`/`ends_at` window, and a `capacity` of at least one seat; the session starts in `SCHEDULED` with `seats_taken` at zero and an empty `rsvp_membership_ids`. Session scheduling enforces the fifteen-minute buffer of §2.10 against the cycle's other `SCHEDULED` sessions (`ERR_SESSION_OVERLAP_BUFFER`).

An active member reserves a seat by presenting their `membership_id`; the membership must belong to the acting member and be `ACTIVE` (`ERR_MEMBERSHIP_NOT_ACTIVE`). Two failures guard the seat count: a membership already present in `rsvp_membership_ids` fails with `ERR_ALREADY_RSVPED`, and a session whose `seats_taken` has reached its `capacity` is full — the boundary is a strict less-than, so the reservation that would equalize the two fails with `ERR_SESSION_FULL`. A successful reservation increments `seats_taken` by one and appends the membership to `rsvp_membership_ids`. Completion and cancellation by a `CircleAdmin` move a `SCHEDULED` session to `COMPLETED` or `CANCELLED` respectively, both terminal; any other from-state is `ERR_INVALID_STATE`.

### 3.6. The Voting Window and Ballot Casting

Moving `VETTING` → `VOTING` requires at least one nomination of the cycle in `FINALIST` (`ERR_NO_FINALISTS` otherwise) and opens the voting window: the advance stamps `voting_opens_at` from the logical clock, sets `voting_closes_at` exactly seven days later, and freezes `active_member_snapshot` as the count of the circle's memberships in `ACTIVE` at that instant. The snapshot never changes afterward — a member who withdraws mid-vote does not lower the quorum bar.

While the window is open, a member casts a ballot by naming the `cycle_id`, their `membership_id`, and an `allocations` array whose entries each pair a `nomination_id` with a `points` value. Casting requires the membership to belong to the acting member and be `ACTIVE` (`ERR_MEMBERSHIP_NOT_ACTIVE`), and the logical clock to sit inside the inclusive window from `voting_opens_at` through `voting_closes_at` — a ballot attempted before the opening instant or after the closing instant fails with `ERR_VOTING_WINDOW_CLOSED`. Each membership votes once per cycle (`ERR_DUPLICATE_BALLOT`). The points budget is exact: `allocations` holds from one to five entries, every entry carries at least 10 points, and the entries sum to exactly 100; any other shape fails with `ERR_POINTS_BUDGET`. Every allocation must target a nomination that is a `FINALIST` of this cycle; naming anything else fails with `ERR_NOT_FINALIST`. A ballot is created directly in `CAST` — its only state — and its arrival increments the cycle's `ballots_cast_count` and is reflected in the tally immediately.

A ballot is not set in stone while the window remains open: recasting replaces its `allocations` wholesale in a self-loop on `CAST`. The recast carries `expected_ballot_version` under §2.8 — a version that no longer matches the ballot's current `version` fails with `ERR_STALE_VERSION` — and it re-enforces the voting window (`ERR_VOTING_WINDOW_CLOSED`), the membership's continued `ACTIVE` status (`ERR_MEMBERSHIP_NOT_ACTIVE`), and the same points-budget and finalist-reference rules as the original cast. A successful recast increments the ballot's `version` by one, and the cycle's tally reflects the replacement immediately.

The tally itself is deterministic. For each `FINALIST` nomination, its `total_points` is the sum of the `points` of every ballot allocation naming it, and its `first_choice_count` counts the ballots on which it holds the strictly greatest `points` value — a tie for greatest on a ballot gives first choice to no one on that ballot. The winner is the finalist with the highest `total_points`; ties break toward the higher `first_choice_count`, and further ties toward the finalist whose nomination has the earliest `created_at`. The `total_points_cast` across all finalists always equals one hundred times `ballots_cast_count`, because every ballot distributes exactly one hundred points. A read-only tally view on the cycle exposes `ballots_cast_count`, the computed `quorum_required`, whether `quorum_met` is currently true, the per-finalist `finalist_points` array, and `total_points_cast`.

Quorum is measured against the frozen snapshot, not the living membership: `quorum_required` is the `active_member_snapshot` multiplied by the cycle's `quorum_percent`, divided by one hundred, and rounded up to the next whole ballot. Quorum is met when `ballots_cast_count` is at least that requirement — exact equality passes.

### 3.7. Award Allocation and the Payout Pipeline

Closing the vote is the heaviest operation in the system. The advance from `VOTING` to `AWARD` carries the usual `expected_cycle_version` guard, and then two gatekeepers: the logical clock must have moved strictly past `voting_closes_at` — an attempt at or before the closing instant fails with `ERR_VOTING_STILL_OPEN` — and quorum must be met per §3.6, failing with `ERR_QUORUM_NOT_MET` when too few ballots were cast.

When the gates pass, the advance runs the tally and commits a chain of side effects in one motion. The winning finalist's nomination moves `FINALIST` → `AWARDED`; every other finalist moves `FINALIST` → `NOT_SELECTED`. A single `GrantAward` is created — awards are never created directly — carrying the `cycle_id`, the winning `nomination_id`, the `nonprofit_id` denormalized from that nomination, the winner's `winner_points`, and an `amount_cents` computed from the locked budget: the winner's share is its `winner_points` divided by the `total_points_cast`, treated as an exact ratio; the raw amount is that share of `grant_budget_final_cents`, rounded half up to whole cents; and the awarded amount is the raw figure raised to a floor of 50000 cents (five hundred dollars) when it falls short, capped at the final budget itself if the floor would exceed it. The award begins life with `payout_status` `UNPAID` and `reporting_status` `AWAITING_REPORTS`.

The same advance settles the host organization: `admin_fee_transferred_cents` is set to the cycle's `received_total_cents` multiplied by its snapshotted `admin_fee_percent`, divided by one hundred, and rounded half up to whole cents, and the pooled balance is recomputed with that fee moved out. `budget_locked` becomes `true` and `grant_budget_final_cents` freezes permanently. Two payouts are created in `SCHEDULED` with `requested_by_user_id` recording the acting `CircleAdmin`'s `X-User-ID`: tranche 1 (the upfront tranche, `tranche` value 1) is the largest whole number of cents not exceeding seventy percent of the award amount, and tranche 2 is the remainder, so the two always sum exactly to `amount_cents` — the tranches are never rounded independently, and the second tranche absorbs any cent the floor leaves behind. Two grantee reports are created in `DUE`: the `INTERIM` report due exactly ninety days after the advance, the `FINAL` report due exactly three hundred sixty-five days after, each `due_at` stamped accordingly. Finally the cycle's `version` increments by one.

Payouts then flow under segregation of duties: the officer who approves money is never the administrator who requested it. Approving a payout requires it in `SCHEDULED` (`ERR_INVALID_STATE`) and requires the acting `FinanceOfficer`'s `X-User-ID` to differ from the payout's `requested_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`, HTTP 403); approval moves the payout `SCHEDULED` → `APPROVED` and records the officer in `approved_by_user_id`. Release requires the payout in `APPROVED` and the cycle in `AWARD` or `REPORTING` (`ERR_CYCLE_PHASE`); releasing tranche 2 additionally requires the award's `INTERIM` report to have reached `ACCEPTED`, failing with `ERR_INTERIM_REPORT_NOT_ACCEPTED` otherwise. A release moves the payout `APPROVED` → `RELEASED`, adds its `amount_cents` to the cycle's `released_total_cents`, recomputes the pooled balance, and recomputes the award's `payout_status` — the first release moves `UNPAID` → `PARTIALLY_PAID`, and when every payout of the award has been released the award becomes `PAID`. When a transfer goes wrong, marking an `APPROVED` payout failed moves it to `FAILED`, and retrying a `FAILED` payout returns it to `SCHEDULED` with `approved_by_user_id` reset to null — the retry must win a fresh approval, and the segregation-of-duties check applies again.

### 3.8. Grantee Reporting, Standing, and Cycle Closeout

Every award carries two reports, created in `DUE` at the award advance with `report_type` `INTERIM` or `FINAL` and the `due_at` deadlines of §3.7. The logical clock enforces the deadlines: when a clock advance — supplied through `to_iso8601` per §2.4 — moves time past a report's `due_at` while the report is still `DUE`, the report flips to `OVERDUE` and the cascade fires in two hops. First, the nonprofit behind the award has its `standing` set to `SUSPENDED`. Second, every nomination of that nonprofit still in `SUBMITTED`, `VETTING`, or `NEEDS_INFO` whose cycle is in the `NOMINATION` or `VETTING` phase is rejected automatically to `REJECTED`. A suspension therefore propagates into other circles' live pipelines, and it blocks the two standing-gated operations of §3.4 — creating a nomination and advancing to finalist — with `ERR_NONPROFIT_SUSPENDED` until the nonprofit recovers.

The grantee answers through a `GranteeContact` whose `X-User-ID` equals the award's `nonprofit_id` (`ERR_FORBIDDEN` otherwise). Submission is allowed from `DUE`, `OVERDUE`, or `REJECTED` — any other state is `ERR_INVALID_STATE` — and carries the `narrative` and the reported `expenditure_cents`; each submission moves the report to `SUBMITTED` and stamps `submitted_at` from the logical clock, and a resubmission after rejection also clears the prior `reject_reason`.

Review belongs to the `CircleAdmin`. Accepting a `SUBMITTED` report moves it to `ACCEPTED`, the terminal state; if no `OVERDUE` reports remain for that nonprofit anywhere in the system, the nonprofit's `standing` is restored to `GOOD`, and when every report of the award has reached `ACCEPTED` the award's `reporting_status` recomputes from `AWAITING_REPORTS` to `REPORTS_COMPLETE`. Rejecting a `SUBMITTED` report moves it to `REJECTED` and requires a `reject_reason`, which is recorded for the grantee to answer on resubmission.

Two final advances close the loop. Moving `AWARD` → `REPORTING` requires at least one payout of the cycle's award in `RELEASED`, failing with `ERR_NO_PAYOUT_RELEASED` before the first dollar has moved. Moving `REPORTING` → `CLOSED` is the strictest gate in the system: every payout of the cycle's award must be `RELEASED` and every report `ACCEPTED` — either shortfall fails with `ERR_INVALID_STATE` — and the pool must be empty, meaning `pooled_balance_cents` is exactly zero or an `EXECUTED` rollover decision sourced from this cycle exists, failing with `ERR_ROLLOVER_REQUIRED` otherwise. Closing fires the retention cascade of §3.2: every membership of the circle still `ACTIVE` flips to `RENEWAL_DUE`, and the cycle's `version` increments.

Residual money is handled deliberately, through a rollover decision. A `CircleAdmin` proposes one with a `source_cycle_id` — the source must be in `REPORTING` (`ERR_CYCLE_PHASE`) — a `mode` of `CARRY_FORWARD` or `RETURN_PRO_RATA`, and, for `CARRY_FORWARD`, a `target_cycle_id`; the target must be a cycle of the same circle in `DRAFT` or `RECRUITMENT`, and a missing or ineligible target fails as an invalid request (`ERR_INVALID_REQUEST`). The decision is created in `PROPOSED`, moves `PROPOSED` → `APPROVED` on approval, and `APPROVED` → `EXECUTED` on execution, which re-verifies the source cycle is still in `REPORTING` (`ERR_CYCLE_PHASE`).

Execution captures the source cycle's `pooled_balance_cents` at that instant as the decision's `amount_cents` and runs the waterfall for the chosen mode. Under `CARRY_FORWARD`, the residual is added to the target cycle's `rollover_in_cents` and to the source cycle's `rollover_out_cents`. Under `RETURN_PRO_RATA`, the residual is distributed to the memberships of the source circle in `ACTIVE` or `RENEWAL_DUE`, taken in `created_at` ascending order — ties break on creation time only, never on `id` — where each membership's weight is its own total of `RECEIVED` contributions in the source cycle; each membership's credit is the residual multiplied by its weight and divided by the combined weights, rounded down to whole cents, and the cents left over after every membership is floored go to the host organization rather than to any member. Each eligible membership's `credit_balance_cents` grows by its credit, and the source's `rollover_out_cents` grows by the residual. Either way, the source cycle's pooled balance is recomputed to zero, clearing the way for closeout.

## 4. Endpoint Definitions

Operations that create new, stand-alone resources — a circle, a cycle, a member, a membership invitation, a contribution pledge, a nonprofit, a nomination, a site visit, a learning session, a ballot, or a rollover decision — return `201 Created`. Operations that modify an existing resource, including every state transition, score update, RSVP, clock advance, and payout action, return `200 OK`. The table below is a summary only; request payloads, response shapes, and side effects are defined by the workflows of Section 3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/_clock/set_current_utc` | Advance the logical clock and evaluate time-driven transitions | CircleAdmin |
| POST | `/api/circles` | Create a circle (host organization configuration) | CircleAdmin |
| GET | `/api/circles/{circle_id}` | Get a circle | All four roles |
| GET | `/api/circles` | List circles | All four roles |
| POST | `/api/cycles` | Create a giving cycle in `DRAFT`, snapshotting circle configuration | CircleAdmin |
| GET | `/api/cycles/{cycle_id}` | Get a cycle | All four roles |
| GET | `/api/cycles` | List cycles, filterable by `circle_id` and `phase` | All four roles |
| POST | `/api/cycles/{cycle_id}/advance` | Advance the cycle one phase (OCC-guarded) | CircleAdmin |
| GET | `/api/cycles/{cycle_id}/ledger` | Read the computed pooled-fund ledger | All four roles |
| GET | `/api/cycles/{cycle_id}/tally` | Read the computed voting tally | All four roles |
| POST | `/api/members` | Register a member record | CircleAdmin |
| GET | `/api/members/{member_id}` | Get a member | All four roles |
| GET | `/api/members` | List members, filterable by `email` | All four roles |
| POST | `/api/memberships` | Invite a member to a circle at a contribution tier | CircleAdmin |
| GET | `/api/memberships/{membership_id}` | Get a membership | All four roles |
| GET | `/api/memberships` | List memberships, filterable by `circle_id`, `member_id`, and `status` | All four roles |
| POST | `/api/memberships/{membership_id}/accept` | Member accepts an invitation | Member |
| POST | `/api/memberships/{membership_id}/renew` | Member renews after cycle close | Member |
| POST | `/api/memberships/{membership_id}/lapse` | Lapse a non-renewing membership | CircleAdmin |
| POST | `/api/memberships/{membership_id}/withdraw` | Member withdraws, voiding pledged contributions | Member |
| POST | `/api/contributions` | Pledge a contribution into a cycle | Member |
| GET | `/api/contributions/{contribution_id}` | Get a contribution | All four roles |
| GET | `/api/contributions` | List contributions, filterable by `cycle_id`, `membership_id`, and `status` | All four roles |
| POST | `/api/contributions/{contribution_id}/receive` | Record receipt of a pledge | CircleAdmin |
| POST | `/api/contributions/{contribution_id}/request-refund` | Request a refund within the refund window | Member |
| POST | `/api/contributions/{contribution_id}/approve-refund` | Approve a refund (underfunding-guarded) | CircleAdmin |
| POST | `/api/contributions/{contribution_id}/deny-refund` | Deny a refund request | CircleAdmin |
| POST | `/api/nonprofits` | Register a nonprofit | CircleAdmin |
| GET | `/api/nonprofits/{nonprofit_id}` | Get a nonprofit | All four roles |
| GET | `/api/nonprofits` | List nonprofits, filterable by `ein` and `standing` | All four roles |
| POST | `/api/nominations` | Nominate a nonprofit (one per membership per cycle) | Member |
| GET | `/api/nominations/{nomination_id}` | Get a nomination | All four roles |
| GET | `/api/nominations` | List nominations, filterable by `cycle_id`, `nonprofit_id`, `nominated_by_membership_id`, and `status` | All four roles |
| PATCH | `/api/nominations/{nomination_id}` | Set vetting scores; recomputes the weighted score | CircleAdmin |
| POST | `/api/nominations/{nomination_id}/start-vetting` | Move a submitted nomination into vetting | CircleAdmin |
| POST | `/api/nominations/{nomination_id}/request-info` | Request information from the grantee (at most two rounds) | CircleAdmin |
| POST | `/api/nominations/{nomination_id}/submit-info` | Grantee returns requested information | GranteeContact |
| POST | `/api/nominations/{nomination_id}/advance-to-finalist` | Promote a vetted nomination to finalist | CircleAdmin |
| POST | `/api/nominations/{nomination_id}/reject` | Reject a non-finalist nomination | CircleAdmin |
| POST | `/api/nominations/{nomination_id}/withdraw` | Nominating member withdraws a non-finalist nomination | Member |
| POST | `/api/site-visits` | Schedule a site visit (half-open overlap rule per nonprofit) | CircleAdmin |
| GET | `/api/site-visits/{visit_id}` | Get a site visit | All four roles |
| GET | `/api/site-visits` | List site visits, filterable by `nomination_id` and `status` | All four roles |
| POST | `/api/site-visits/{visit_id}/complete` | Complete a finished visit | CircleAdmin |
| POST | `/api/site-visits/{visit_id}/cancel` | Cancel a scheduled visit | CircleAdmin |
| POST | `/api/site-visits/{visit_id}/reschedule` | Reschedule a cancelled or no-show visit | CircleAdmin |
| POST | `/api/learning-sessions` | Schedule a learning session (fifteen-minute buffer rule per cycle) | CircleAdmin |
| GET | `/api/learning-sessions/{session_id}` | Get a session | All four roles |
| GET | `/api/learning-sessions` | List sessions, filterable by `cycle_id` and `status` | All four roles |
| POST | `/api/learning-sessions/{session_id}/rsvp` | Active member reserves a seat (strict capacity boundary) | Member |
| POST | `/api/learning-sessions/{session_id}/complete` | Complete a session | CircleAdmin |
| POST | `/api/learning-sessions/{session_id}/cancel` | Cancel a session | CircleAdmin |
| POST | `/api/ballots` | Cast a ballot (created directly in `CAST`) | Member |
| GET | `/api/ballots/{ballot_id}` | Get a ballot | All four roles |
| GET | `/api/ballots` | List ballots, filterable by `cycle_id`, `membership_id`, and `status` | All four roles |
| POST | `/api/ballots/{ballot_id}/recast` | Replace a ballot's allocations while the window is open (OCC-guarded) | Member |
| GET | `/api/awards/{award_id}` | Get an award | All four roles |
| GET | `/api/awards` | List awards, filterable by `cycle_id`, `nomination_id`, and `nonprofit_id` | All four roles |
| GET | `/api/payouts/{payout_id}` | Get a payout | All four roles |
| GET | `/api/payouts` | List payouts in `tranche` ascending order, filterable by `award_id` and `status` | All four roles |
| POST | `/api/payouts/{payout_id}/approve` | Approve a scheduled payout (segregation of duties) | FinanceOfficer |
| POST | `/api/payouts/{payout_id}/release` | Release an approved payout; tranche 2 gated on interim-report acceptance | FinanceOfficer |
| POST | `/api/payouts/{payout_id}/mark-failed` | Mark an approved payout failed | FinanceOfficer |
| POST | `/api/payouts/{payout_id}/retry` | Return a failed payout to scheduled | FinanceOfficer |
| GET | `/api/reports/{report_id}` | Get a report | All four roles |
| GET | `/api/reports` | List reports in `due_at` ascending order, filterable by `award_id` and `status` | All four roles |
| POST | `/api/reports/{report_id}/submit` | Grantee submits or resubmits a report | GranteeContact |
| POST | `/api/reports/{report_id}/accept` | Accept a submitted report | CircleAdmin |
| POST | `/api/reports/{report_id}/reject` | Reject a submitted report with reason | CircleAdmin |
| POST | `/api/rollover-decisions` | Propose handling of a reporting-phase cycle's residual pool | CircleAdmin |
| GET | `/api/rollover-decisions/{decision_id}` | Get a rollover decision | All four roles |
| GET | `/api/rollover-decisions` | List rollover decisions, filterable by `source_cycle_id`, `target_cycle_id`, and `status` | All four roles |
| POST | `/api/rollover-decisions/{decision_id}/approve` | Approve a proposed rollover decision | CircleAdmin |
| POST | `/api/rollover-decisions/{decision_id}/execute` | Execute an approved decision, running the residual waterfall | CircleAdmin |

## 5. Error Code Catalogue

The table below lists every error identifier and its HTTP status. The conditions that trigger each error are defined in the narratives of Sections 2 and 3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_CYCLE_PHASE` | 409 Conflict |
| `ERR_MEMBERSHIP_NOT_ACTIVE` | 409 Conflict |
| `ERR_NONPROFIT_SUSPENDED` | 409 Conflict |
| `ERR_EIN_CONFLICT` | 409 Conflict |
| `ERR_DUPLICATE_NOMINATION` | 409 Conflict |
| `ERR_DUPLICATE_BALLOT` | 409 Conflict |
| `ERR_ALREADY_RSVPED` | 409 Conflict |
| `ERR_SESSION_FULL` | 409 Conflict |
| `ERR_SESSION_OVERLAP_BUFFER` | 409 Conflict |
| `ERR_SITE_VISIT_OVERLAP` | 409 Conflict |
| `ERR_INFO_ROUND_EXHAUSTED` | 409 Conflict |
| `ERR_VETTING_SCORE_BELOW_THRESHOLD` | 409 Conflict |
| `ERR_SITE_VISIT_REQUIRED` | 409 Conflict |
| `ERR_NOT_FINALIST` | 409 Conflict |
| `ERR_POINTS_BUDGET` | 409 Conflict |
| `ERR_BELOW_TIER_MINIMUM` | 409 Conflict |
| `ERR_REFUND_WINDOW_CLOSED` | 409 Conflict |
| `ERR_REFUND_UNDERFUNDS_AWARDS` | 409 Conflict |
| `ERR_VOTING_WINDOW_CLOSED` | 409 Conflict |
| `ERR_VOTING_STILL_OPEN` | 409 Conflict |
| `ERR_QUORUM_NOT_MET` | 409 Conflict |
| `ERR_NO_ACTIVE_MEMBERS` | 409 Conflict |
| `ERR_EMPTY_POOL` | 409 Conflict |
| `ERR_NO_NOMINATIONS` | 409 Conflict |
| `ERR_NO_FINALISTS` | 409 Conflict |
| `ERR_NO_PAYOUT_RELEASED` | 409 Conflict |
| `ERR_ROLLOVER_REQUIRED` | 409 Conflict |
| `ERR_INTERIM_REPORT_NOT_ACCEPTED` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
