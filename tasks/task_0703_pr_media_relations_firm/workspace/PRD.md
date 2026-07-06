# PR & Media-Relations Firm API — Product Requirements Document

## 1. Introduction

A public-relations agency lives and dies by two interlocking disciplines: orchestrating the long arc of earned-media work — briefing a client, building a media list, pitching journalists, distributing embargoed releases, tracking the resulting coverage, scheduling spokesperson interviews, and running crisis-comms when something goes wrong — and reconciling the money and hours behind all of it against monthly retainers. This API is the system of record for both. It models the agency as a flat collection of peer resources (clients, campaigns, journalists, outlets, media lists, pitches, press releases, distributions, coverage clips, interviews, crisis events, retainer periods, and time entries) that reference one another by identifier rather than by URL nesting, and it governs the precise lifecycle each of those resources moves through.

The central tension the system resolves is between *workflow correctness* and *ledger fidelity*. A campaign cannot be completed while pitches are still open or interviews are still pending; a press release cannot go out before its embargo lifts; an interview cannot double-book a spokesperson; a retainer period cannot be closed while time entries are still awaiting approval. At the same time, every verified coverage clip contributes a conserved media value to its campaign and client that must be reversible without drift when the clip is retracted, and every hour logged against a retainer is billed under tiered overage rules that round differently depending on whether the bill is provisional or final. Because several of these mutations are supersede-style — a new media list replaces the campaign's current one, a period close freezes its bill — the system uses optimistic concurrency control to reject writes made against a stale view of the parent resource.

This document specifies the complete contract: the global response and pagination conventions, the role-based access model, the cross-cutting principles that govern consistency and money, and the detailed business workflows for every resource lifecycle. All resources are mounted under the `/agency` path prefix.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. Most of the rules here are contract-level: they hold uniformly across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the capacity in which they act. If `X-User-Role` is missing or is not one of the four declared roles, the request is rejected with `ERR_UNAUTHENTICATED`. If the role is recognized but is not permitted to perform the requested operation under the access matrix, the request is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly four roles: `AccountManager`, `MediaSpecialist`, `SchedulingCoordinator`, and `PlatformAdmin`. An `AccountManager` owns the client-relationship surface — creating clients, running the full campaign lifecycle, opening and closing retainer periods, approving and voiding time entries, managing spokespersons, and driving crisis-comms. A `MediaSpecialist` owns the earned-media surface — journalists, media lists, pitches, press releases, distributions, and coverage. A `SchedulingCoordinator` owns interview scheduling and all interview transitions. A `PlatformAdmin` is an operator/superuser responsible for reference data (outlets, journalists), client suspension, and the logical clock.

All four roles are opaque operator identities. When `X-User-Role` is `AccountManager`, `MediaSpecialist`, `SchedulingCoordinator`, or `PlatformAdmin`, the value of `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may record it (for example, a time entry captures the logging operator as its `staff_id`) but it never compares `X-User-ID` to any entity's `id` for ownership purposes. Authorization is therefore by role alone, not by resource ownership.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Logical Clock

Most resources in this system carry a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits indicating when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp indicating when the resource was last modified. It is refreshed on any mutation to the resource.
- `version` (integer): a system-managed integer that begins at 1 and increments by one on every mutation of the resource. It underpins optimistic concurrency control (see §2.7).

One entity is deliberately leaner. The `Outlet` is immutable reference data: an outlet carries only `id` and `created_at`. It has no `updated_at` and no `version` field, because outlets are never modified after creation.

Time in this system is driven by a **logical clock**, not by wall-clock time. The server boots with its clock set to `2026-03-01T00:00:00Z`; before any explicit set, the clock reads exactly that default instant and never falls back to real time. A `PlatformAdmin` may advance or rewind the clock to a supplied instant via the `to_iso8601` field. Every timestamp the system stamps onto a resource as a side effect of a transition — a pitch's `sent_at`, a press release's `released_at`, a distribution's `delivered_at` — is read from this logical clock at the moment of the transition. All temporal preconditions (embargo windows, interview start/end checks) likewise compare against the logical clock.

### 2.5. Hierarchical Consistency and Cascading Side Effects

Although resources are flat in the URL space, they form a logical hierarchy through foreign-key references, and several operations cascade across that hierarchy. Whenever an operation transitions a resource, the system independently mutates each affected resource: it advances that resource's `status` (or whichever state field the transition targets), refreshes its `updated_at`, and increments its `version`. This holds for cascade-induced transitions just as it does for the directly requested one — a child swept into a new state by a parent's transition has its own `updated_at` and `version` updated.

Two cascades are especially deep. Archiving a campaign sweeps its media lists, then the pitches on those lists, then the interviews on those pitches (a three-level cascade described in §3.7). Deactivating a spokesperson cancels that spokesperson's pending interviews and, where an interview anchored an accepted pitch, reverts the pitch so it can be re-accepted (a two-level cascade described in §3.6). The system performs these reconciliations automatically, without requiring a separate client request against each child.

### 2.6. Nested Reference Validation Order

Many create operations carry foreign-key references in their request body, and action endpoints carry a resource identifier in the path. Validation proceeds in a fixed order so that the earliest applicable failure is the one reported. First, authentication and authorization are checked (`ERR_UNAUTHENTICATED`, then `ERR_FORBIDDEN`). Next, every resource named in the request path must exist, validated left to right; the first path identifier that does not resolve produces `ERR_NOT_FOUND`. Then, on create endpoints, every foreign-key field in the request body must reference an existing resource, or the request is rejected with `ERR_REFERENCE_NOT_FOUND`. Only after these existence checks does the system validate field shapes and enums (`ERR_INVALID_REQUEST`), then optimistic-concurrency versions, then state preconditions, and finally the domain-specific business rules. Section 2.8 states the full priority ordering.

### 2.7. Optimistic Concurrency Control

Two operations are supersede-style: they overwrite or freeze something the client believes it has already observed, and they must not proceed against a stale view of their parent resource. Both require a version field in the request body that the client sets to the parent's last-observed `version`.

Creating a media list supersedes the campaign's current list, so a media-list create request must carry `expected_campaign_version`. The server compares it against the target campaign's current `version`; if another writer has advanced the campaign's `version` since the client last read it, the create is rejected with `ERR_STALE_CAMPAIGN_VERSION` at HTTP status 412, because the client's view of which list is current is stale. On success, the create increments the campaign's `version` by one.

Closing a retainer period freezes its bill, so a close request must carry `expected_retainer_period_version` set to the period's last-observed `version`. The server compares it against the period's current `version`; if another writer has advanced it since the client last read it — for instance by approving or voiding a time entry, which changes the totals the closer expects to freeze — the close is rejected with `ERR_STALE_PERIOD_VERSION` at HTTP status 412. On success, the close increments the period's `version` by one.

No other endpoint takes a version field; mutations outside these two operations are processed without an OCC check.

### 2.8. Validation Priority Ordering

When several validations could apply to a single request, they are evaluated in a strict order and the first failure is the one returned. The ordering is: (1) authentication — `X-User-Role` present and a declared role, else `ERR_UNAUTHENTICATED`; (2) authorization — the role is permitted for the operation, else `ERR_FORBIDDEN`; (3) path existence — all path-referenced resources exist, validated left to right, else `ERR_NOT_FOUND`; (4) reference existence — all foreign-key body fields resolve, else `ERR_REFERENCE_NOT_FOUND`; (5) request well-formedness — required fields present and well-typed, enums in their allowed set, and numeric ranges satisfied (`billable_hours` strictly greater than zero, `ends_at` strictly after `starts_at`, `period_month` matching the year-month format), else `ERR_INVALID_REQUEST`; (6) optimistic concurrency — the supplied expected version equals the parent's current `version` on supersede-style creates and closes, else the relevant stale-version error at 412; (7) state validity — the target resource is in a state from which the requested transition is legal, else `ERR_INVALID_STATE`; (8) referential business rules such as media-list membership, else `ERR_JOURNALIST_NOT_IN_LIST`; (9) embargo safety; (10) interview interval-overlap checks; and (11) fiscal constraints such as the period being open for time logging. Domain-specific transition preconditions (for example, a suspended client blocking activation, or an embargo not yet lifted) are evaluated at the state/business layer, after the structural checks above have passed.

### 2.9. Monetary Precision and the Media-Value and Billing Ledgers

All monetary amounts in the system are integer **cents**; the API never returns fractional cents. Calculations that produce a final monetary value round to whole cents using the round-half-up method. The campaign return-on-investment ratio is the one non-monetary computed figure, and it rounds to four decimal places, also round-half-up.

Three computed quantities behave as conserved ledger balances and must be kept drift-free. A campaign's `earned_media_value_cents` is the sum of the verified media value of its verified coverage; a client's `lifetime_earned_media_cents` is the same sum aggregated across all of that client's campaigns; and a retainer period's `hours_consumed` is the sum of billable hours of its non-void time entries. Every event that contributes to one of these balances has an exactly equal and opposite reversal: retracting a verified clip subtracts back precisely the amount it added, and voiding a time entry subtracts back precisely the hours it added. These reversals operate by re-deriving the balance from the current set of contributing children rather than by accumulating ad-hoc deltas, so the balance can never drift away from the truth.

## 3. Business Logic & Workflows

### 3.1. Clients, Account Tiers, and Suspension

The agency's relationships begin with a **Client**. An `AccountManager` (or a `PlatformAdmin`) registers a client by supplying its company `name`, its `industry` (one of `TECH`, `HEALTH`, `FINANCE`, `CONSUMER`, or `NONPROFIT`), the `monthly_retainer_cents` flat fee, a `monthly_hours_cap` of included service hours, and the `overage_rate_cents` per-hour rate charged above that cap. The retainer fee must be zero or greater, the overage rate must be zero or greater, and the hours cap must be strictly greater than zero. The caller may also supply an `account_tier` of `STANDARD`, `PREMIUM`, or `ENTERPRISE`; if omitted it defaults to `STANDARD`. The account tier selects the media-value multiplier applied to that client's coverage, as described in §3.9. A newly created client is `ACTIVE` and its `lifetime_earned_media_cents` starts at zero.

A client's `status` is one of `ACTIVE` or `SUSPENDED`. Only a `PlatformAdmin` may suspend a client, moving its `status` to `SUSPENDED`. Suspension blocks new campaign work: while a client is `SUSPENDED`, its campaigns cannot be activated. Clients may be listed and filtered by `status`.

### 3.2. Outlets and Journalists

Outlets are immutable reference data created only by a `PlatformAdmin`. An **Outlet** is described by its `name`, its `tier` (one of `NATIONAL`, `REGIONAL`, `TRADE`, or `BLOG`, which drives the base media-value units), its `monthly_unique_visitors` reach figure (zero or greater), and a `domain_authority` score on the inclusive scale from 0 to 100. Outlets may be listed and filtered by `tier`.

A **Journalist** is created by a `MediaSpecialist` or a `PlatformAdmin` against a primary outlet, supplying the `outlet_id`, the journalist's `full_name`, a contact `email` that must be unique across all journalists, and a coverage `beat` (one of `TECH`, `HEALTH`, `FINANCE`, `CONSUMER`, or `POLITICS`). A journalist is created `ACTIVE`. A journalist's `status` is `ACTIVE` or `BLOCKLISTED`; a `MediaSpecialist` or `PlatformAdmin` may blocklist a journalist, moving the `status` to `BLOCKLISTED`. A `BLOCKLISTED` journalist cannot be pitched or scheduled. Journalists may be listed and filtered by `outlet_id`, `beat`, and `status`.

### 3.3. Campaigns and Their Lifecycle

A campaign is the central unit of PR work. An `AccountManager` creates a **Campaign** for a client by supplying the `client_id`, a `title`, an `objective` (one of `LAUNCH`, `THOUGHT_LEADERSHIP`, `CRISIS`, or `AWARENESS`), a `budget_cents` authorized media-value budget that must be strictly greater than zero, and a `target_beat` (one of `TECH`, `HEALTH`, `FINANCE`, `CONSUMER`, or `POLITICS`) used as the pitch beat-match target. A new campaign opens in `DRAFT` with `earned_media_value_cents` and `cost_basis_cents` at zero, `roi_ratio` null, and `version` 1. Campaigns may be listed and filtered by `client_id` and `status`.

A campaign's `status` moves through `DRAFT`, `ACTIVE`, `PAUSED`, `COMPLETED`, and `ARCHIVED`, all driven by the `AccountManager`. Activation moves a campaign from `DRAFT` to `ACTIVE`, and also from `PAUSED` back to `ACTIVE`. In both cases the owning client must be `ACTIVE`; if the client is suspended, activation is rejected with `ERR_CLIENT_SUSPENDED`. Pausing moves a campaign from `ACTIVE` to `PAUSED`; while a campaign is `PAUSED`, its pitches in `DRAFT` or `SENT` cannot advance to `RESPONDED` (enforced in the pitch workflow, §3.4). A campaign may pause and resume any number of times — there is no limit on the `ACTIVE`/`PAUSED` cycle, and resuming from `PAUSED` produces no ledger change.

Completing a campaign moves it from `ACTIVE` to `COMPLETED`, or from `PAUSED` to `COMPLETED`. Completion has two preconditions, evaluated together: no pitch on the campaign may be in `SENT` or `RESPONDED` status (else `ERR_CAMPAIGN_HAS_OPEN_PITCHES`), and no interview on the campaign may be in `REQUESTED` or `CONFIRMED` status (else `ERR_CAMPAIGN_HAS_OPEN_INTERVIEWS`). The count of pitches on a campaign in `SENT` or `RESPONDED` is the campaign's open-pitch count, and completion is permitted only when that count is exactly zero. As a side effect of completion, the campaign's `roi_ratio` is recomputed once more (see §3.10) so the closed campaign carries a settled ratio.

Archiving moves a campaign from `COMPLETED` to `ARCHIVED`, and also directly from `DRAFT` to `ARCHIVED`; `ARCHIVED` is terminal. Archiving triggers the deep cascade described in §3.7 (when a draft campaign has no children, the cascade is a no-op).

### 3.4. Pitching Journalists

A **Pitch** carries an angle to a single journalist drawn from a media list. A `MediaSpecialist` creates a pitch by supplying the `campaign_id` being pitched, the `media_list_id` it is drawn from, the `journalist_id` recipient, an `angle` hook, and optionally `is_exclusive` (whether the pitch offers an exclusive; defaults to false). At creation time the chosen journalist must already be one of the entries in that media list's `journalist_ids`; if the recipient is not a member of the source list, the create is rejected with `ERR_JOURNALIST_NOT_IN_LIST`. A new pitch opens in `DRAFT` with `version` 1 and a null `sent_at`. Pitches may be listed and filtered by `campaign_id`, `media_list_id`, `journalist_id`, and `status`.

A pitch's `status` runs `DRAFT`, `SENT`, `RESPONDED`, `ACCEPTED`, `REJECTED`, `DECLINED`, and `CANCELLED`. Sending a pitch advances it from `DRAFT` to `SENT`. Sending has three preconditions: the campaign must be `ACTIVE`, else `ERR_CAMPAIGN_NOT_ACTIVE`; the recipient journalist must be `ACTIVE`, else `ERR_JOURNALIST_BLOCKLISTED`; and the source media list must be `ACTIVE`, else `ERR_MEDIA_LIST_NOT_ACTIVE`. On a successful send, the pitch's `sent_at` is stamped from the logical clock.

Marking a journalist's reply advances a pitch from `SENT` to `RESPONDED`. This requires the campaign to be `ACTIVE`; because a paused campaign is not `ACTIVE`, a response attempted while the campaign is `PAUSED` is rejected with `ERR_CAMPAIGN_NOT_ACTIVE`. From `RESPONDED`, the pitch forks into two mutually exclusive branches. Accepting it advances `RESPONDED` to `ACCEPTED`; an accepted pitch becomes eligible to anchor an interview, meaning an interview create may reference it. Rejecting it advances `RESPONDED` to `REJECTED`, which is terminal. Separately, a pitch may be declined directly from `SENT`, advancing `SENT` to `DECLINED`, which is also terminal.

Both rejecting and declining a pitch can exhaust the pitch's media list. For a given media list, count the pitches on it whose `status` is `DRAFT`, `SENT`, `RESPONDED`, or `ACCEPTED` — this is the list's open count. When a reject or a decline drops that open count to exactly zero, the media list auto-transitions from `ACTIVE` to `EXHAUSTED`. The boundary is exact: an open count reaching zero triggers exhaustion, while an open count of one does not.

### 3.5. Press Releases, Distributions, and Embargoes

A **Press Release** is owned by a campaign. A `MediaSpecialist` drafts one by supplying the `campaign_id`, a `headline`, and an `embargo_until` instant (ISO 8601 UTC) before which the content may not be released. A new press release opens in `DRAFT` with `version` 1 and a null `released_at`. Press releases may be listed and filtered by `campaign_id` and `status`. Its `status` runs `DRAFT`, `SCHEDULED`, `RELEASED`, and `WITHDRAWN`.

Before a release goes out, recipients are queued as **Distributions**. A `MediaSpecialist` queues a distribution by supplying the `press_release_id` and the `journalist_id` recipient; the distribution opens in `QUEUED` with a null `delivered_at`. Two rules guard distribution creation. The recipient journalist must belong to a media list of the release's campaign, else `ERR_JOURNALIST_NOT_IN_LIST`. And the target release must still be open to new recipients — it must be in `DRAFT` or `SCHEDULED`; if the release is already `RELEASED` or `WITHDRAWN`, the create is rejected with `ERR_DISTRIBUTION_RELEASE_LOCKED`. A distribution's `status` is one of `QUEUED`, `DELIVERED`, or `BOUNCED`. Distributions may be listed and filtered by `press_release_id` and `journalist_id`.

Scheduling a press release advances it from `DRAFT` to `SCHEDULED`. Scheduling requires the campaign to be `ACTIVE`, else `ERR_CAMPAIGN_NOT_ACTIVE`, and requires the `embargo_until` instant to be strictly after the current logical clock; an embargo at or before the current clock is rejected with `ERR_EMBARGO_IN_PAST`.

Releasing advances a press release from `SCHEDULED` to `RELEASED`. Two preconditions apply: the current logical clock must be at or after `embargo_until` (an attempt before the embargo lifts is rejected with `ERR_EMBARGO_NOT_LIFTED`), and at least one distribution must exist for the release (otherwise `ERR_NO_DISTRIBUTIONS`). On release, the press release's `released_at` is stamped from the logical clock, and every distribution for that release still in `QUEUED` advances to `DELIVERED` with its `delivered_at` stamped from the same clock.

Withdrawing a press release moves it to `WITHDRAWN` from either `DRAFT` or `SCHEDULED`. Withdrawing from `DRAFT` has no further effect. Withdrawing from `SCHEDULED` advances every distribution for that release still in `QUEUED` to `BOUNCED`.

### 3.6. Spokespersons and Interview Scheduling

A **Spokesperson** represents a client. An `AccountManager` registers one by supplying the `client_id`, the spokesperson's `full_name`, their `title`, and optionally a `prep_buffer_minutes` value (zero or greater; defaults to 30) that defines the minimum gap required before and after each of this spokesperson's interviews. A spokesperson's `status` is `ACTIVE` or `INACTIVE`, starting `ACTIVE`. Spokespersons may be listed and filtered by `client_id` and `status`.

A **Interview** pairs a spokesperson with a journalist in a campaign context. A `SchedulingCoordinator` requests one by supplying the `campaign_id`, the `spokesperson_id` interviewee, the `journalist_id` interviewer, optionally a `pitch_id` (the accepted pitch this interview fulfills, nullable), a `starts_at` instant, and an `ends_at` instant that must be strictly after `starts_at`. A new interview opens in `REQUESTED` with `version` 1. Its `status` runs `REQUESTED`, `CONFIRMED`, `COMPLETED`, `CANCELLED`, and `NO_SHOW`. Interviews may be listed and filtered by `campaign_id`, `spokesperson_id`, `journalist_id`, and `pitch_id`.

Both interview creation and rescheduling enforce two non-overlap rules. The proposed half-open interval running from `starts_at` up to but not including `ends_at` must not overlap any other non-terminal interview for the same spokesperson once that spokesperson's `prep_buffer_minutes` padding is applied to both ends — a violation is rejected with `ERR_SPOKESPERSON_DOUBLE_BOOKED`. Independently, the same half-open interval must not overlap any other non-terminal interview for the same journalist, evaluated without any buffer padding — a violation is rejected with `ERR_JOURNALIST_DOUBLE_BOOKED`. A non-terminal interview is one not in `COMPLETED`, `CANCELLED`, or `NO_SHOW`.

Rescheduling re-checks both overlap rules and updates `starts_at` and `ends_at` in place while leaving the `status` at `REQUESTED`; an interview may be rescheduled any number of times. Confirming advances `REQUESTED` to `CONFIRMED` and has two preconditions: the spokesperson must be `ACTIVE`, else `ERR_SPOKESPERSON_INACTIVE`; and if the interview carries a `pitch_id`, that pitch's `status` must be `ACCEPTED`, else `ERR_PITCH_NOT_ACCEPTED`. Completing advances `CONFIRMED` to `COMPLETED` but only once the logical clock is at or after `ends_at`; an attempt before then is rejected with `ERR_INTERVIEW_NOT_ENDED`. Marking a no-show advances `CONFIRMED` to `NO_SHOW` but only once the logical clock is at or after `starts_at`; an attempt before then is rejected with `ERR_INTERVIEW_NOT_STARTED`. Cancelling moves an interview to `CANCELLED` from either `REQUESTED` or `CONFIRMED`.

Deactivating a spokesperson is consequential. An `AccountManager` moves a spokesperson from `ACTIVE` to `INACTIVE`, which triggers a two-level cascade. First, every interview for that spokesperson in `REQUESTED` or `CONFIRMED` is cancelled (advancing to `CANCELLED`), freeing the spokesperson's calendar slot. Then, for each such cancelled interview that carried a `pitch_id` whose pitch is currently `ACCEPTED`, that pitch is reverted from `ACCEPTED` back to `RESPONDED` as compensation, so the pitch can be re-accepted and re-anchored to a fresh interview later.

### 3.7. The Archive Cascade

Archiving a campaign performs a three-level cascade. At the first level, every media list belonging to the campaign whose `status` is `ACTIVE` or `EXHAUSTED` is moved to `ARCHIVED`. At the second level, each media list moving to `ARCHIVED` cascades to its pitches: every pitch on that list whose `status` is `DRAFT`, `SENT`, or `RESPONDED` is moved to `CANCELLED`. At the third level, each pitch moving to `CANCELLED` cascades to its interviews: every interview anchored to that pitch whose `status` is `REQUESTED` or `CONFIRMED` is moved to `CANCELLED`, which frees the spokesperson's slot. Each resource touched by the cascade has its `updated_at` refreshed and its `version` incremented in its own right, per §2.5.

### 3.8. Logging Coverage

A **Coverage** clip records earned media for a campaign. A `MediaSpecialist` logs one by supplying the `campaign_id` that earned it, the `journalist_id` author, optionally a `pitch_id` (the originating pitch, nullable for inbound coverage), the clip `headline`, the `published_at` instant (ISO 8601 UTC), a `sentiment` (one of `POSITIVE`, `NEUTRAL`, or `NEGATIVE`), and a `prominence` (one of `FEATURE`, `MENTION`, or `PASSING`). At logging, the clip's provisional advertising-value-equivalent is computed and stored as `estimated_media_value_cents` (the estimated variant of the media-value calculation, §3.9). A new clip opens in `DRAFT` with `media_value_cents` zero and `version` 1. Coverage may be listed and filtered by `campaign_id`, `journalist_id`, `pitch_id`, and `status`. A clip's `status` is `DRAFT`, `VERIFIED`, or `RETRACTED`.

Verifying a clip advances `DRAFT` to `VERIFIED`. Verification requires the owning campaign to be in `ACTIVE`, `PAUSED`, or `COMPLETED`; in any other state the verify is rejected with `ERR_INVALID_STATE`. On verification, the clip's `media_value_cents` is computed and frozen using the verified variant of the media-value calculation, the clip's verified value is added to the owning campaign's `earned_media_value_cents` and to the owning client's `lifetime_earned_media_cents`, and the campaign's `roi_ratio` is recomputed.

Retracting a clip moves it to `RETRACTED`. Retracting a clip that was only ever `DRAFT` (and so contributed nothing) has no ledger effect. Retracting a `VERIFIED` clip is a drift-free reversal: exactly the clip's frozen `media_value_cents` is subtracted back from the campaign's `earned_media_value_cents` and from the client's `lifetime_earned_media_cents`, the clip's `media_value_cents` is reset to zero, and the campaign's `roi_ratio` is recomputed.

### 3.9. Media-Value Calculation

The advertising-value-equivalent of a coverage clip is a weighted product over the clip's outlet, sentiment, prominence, and the owning client's account tier. Each input is a single multiplicative factor, and the factors are multiplied together in this order.

Start from the outlet base units selected by the outlet's `tier`: `NATIONAL` contributes 500000, `REGIONAL` 200000, `TRADE` 80000, and `BLOG` 20000 (these base units are already expressed in cents). Multiply by a reach factor equal to one plus the outlet's `monthly_unique_visitors` divided by one million, but cap that reach factor at 3.0 — that is, use the smaller of the computed reach factor and 3.0. Multiply by an authority factor equal to one plus the outlet's `domain_authority` divided by 100. Multiply by the sentiment weight: 1.0 for `POSITIVE`, 0.5 for `NEUTRAL`, and 0.25 for `NEGATIVE`. Multiply by the prominence weight: 1.0 for `FEATURE`, 0.6 for `MENTION`, and 0.3 for `PASSING`. Finally, multiply by the account-tier multiplier of the owning client: 1.0 for `STANDARD`, 1.25 for `PREMIUM`, and 1.5 for `ENTERPRISE`. The result of this product is the raw value.

The calculation has two variants that share that raw value. The **estimated** variant, computed at logging and stored as `estimated_media_value_cents`, applies a provisional haircut: it multiplies the raw value by 0.8 and rounds half-up to whole cents. The **verified** variant, computed at verification and stored as `media_value_cents`, applies no haircut: it rounds the full raw value half-up to whole cents. Both variants use the sentiment and prominence as logged on the clip.

### 3.10. Campaign Return on Investment

A campaign's `roi_ratio` is recomputed whenever a coverage clip is verified or retracted, and once more when the campaign is completed. Because earned value feeds the numerator and service cost feeds the denominator, and both are derived from the campaign's children, the computation follows a pinned order. First, take the campaign's earned value, which is the `earned_media_value_cents` sum of the verified `media_value_cents` of all coverage in `VERIFIED` status. Second, take the campaign's cost basis, `cost_basis_cents`, which is the sum of the `cost_cents` of all time entries on the campaign in `APPROVED` status. Third, form the denominator as the larger of that cost basis and a floor of 100000 cents, so the system never divides by zero and the ratio is defined even before any time is logged. Fourth, the ratio is the earned value minus the cost basis, divided by that denominator, rounded half-up to four decimal places. As a special case, if the earned value is zero — no coverage has yet been verified — the `roi_ratio` is null rather than a computed number. Completing a campaign runs this same computation once more so the closed campaign carries a settled ratio.

### 3.11. Retainer Periods, Time Entries, and Billing

A **RetainerPeriod** is the monthly billing container for a client. An `AccountManager` opens one by supplying the `client_id` and a `period_month` formatted as a four-digit year, a hyphen, and a two-digit month (for example `2026-03`); the month must be unique per client, and a second period for the same client and `period_month` is rejected with `ERR_DUPLICATE_PERIOD`. At open, the period snapshots the client's current hours cap into `hours_cap` and the client's current overage rate into `overage_rate_cents`, so later changes to the client do not retroactively alter the period. A new period opens in `OPEN` with `hours_consumed` zero and `version` 1; its `status` is `OPEN` or `CLOSED`, and `final_total_cents` is null until the period is closed. Periods may be listed and filtered by `client_id` and `status`.

A **TimeEntry** records work against a period. A logger — any of `AccountManager`, `MediaSpecialist`, or `SchedulingCoordinator` — submits one by supplying the `retainer_period_id`, optionally a `campaign_id` (nullable for non-campaign work), the `staff_id` operator who did the work, a `work_type` (one of `STRATEGY`, `WRITING`, `OUTREACH`, `MONITORING`, or `CRISIS`), and the `billable_hours` worked, which must be strictly greater than zero. The target period must be `OPEN`; logging time against a `CLOSED` period is rejected with `ERR_PERIOD_CLOSED`. A new time entry is `SUBMITTED`; its `status` is `SUBMITTED`, `APPROVED`, or `VOID`. At logging, its per-entry `cost_cents` is set per the provisional billing rule below, and the period's `hours_consumed` and `provisional_total_cents` are recomputed. Time entries may be listed and filtered by `retainer_period_id`, `campaign_id`, and `status`.

An `AccountManager` may approve a time entry, advancing `SUBMITTED` to `APPROVED`, which recomputes both the owning campaign's `cost_basis_cents` and the period's `provisional_total_cents`. An `AccountManager` may also void a time entry from `SUBMITTED` or `APPROVED`, advancing it to `VOID`; voiding subtracts that entry's `billable_hours` back out of the period's `hours_consumed` and recomputes the period's `provisional_total_cents` and the campaign's `cost_basis_cents`, preserving the conserved-hours invariant.

**Billing.** Hours within the cap are covered by the flat monthly retainer and contribute zero cents to the overage bill; only overage hours — those beyond the cap — are billed, at the period's snapshotted overage rate. To allocate overage across entries, the included entries are processed as a waterfall in ascending `created_at` order (the entry `id` is never used for ordering). For each entry, let the prior running total be the billable hours of the earlier included entries; the in-cap room remaining is the cap minus that prior running total, but never less than zero; the entry's overage hours are its `billable_hours` minus that remaining room, but never less than zero; and the entry's real overage amount in cents is its overage hours multiplied by the snapshotted overage rate.

The two billing totals differ only in which entries they include and in when rounding happens. The **provisional** total, recomputed live as `provisional_total_cents` whenever a time entry is logged, approved, or voided, includes entries in `SUBMITTED` or `APPROVED` status, and it rounds each entry's real overage amount half-up to whole cents and then sums those rounded per-entry amounts. At logging time, an entry's own `cost_cents` is set to that round-half-up of its real overage amount. The **final** total, computed once when the period is closed and stored as `final_total_cents`, includes only entries in `APPROVED` status, and it sums the real overage amounts across those approved entries first and rounds the single sum half-up to whole cents at the end.

Closing a period advances it from `OPEN` to `CLOSED` and freezes the bill. Closing has one workflow precondition — no time entry in the period may still be `SUBMITTED`; every entry must be `APPROVED` or `VOID`, else the close is rejected with `ERR_PERIOD_HAS_PENDING_ENTRIES` — in addition to the optimistic-concurrency check on `expected_retainer_period_version` described in §2.7. On a successful close, `final_total_cents` is computed and the period's `version` is incremented by one. A closed period freezes time-entry logging.

### 3.12. Crisis-Comms Protocol

A **CrisisEvent** tracks the agency's response to a client emergency along two independent dimensions that advance separately. An `AccountManager` opens one by supplying the `client_id`, optionally a `campaign_id` (the related campaign, nullable), a `summary`, a `severity` (one of `LOW`, `MEDIUM`, `HIGH`, or `CRITICAL`), and optionally a `holding_statement` text. A new crisis event opens with its `severity_status` at `ASSESSING`, its `response_status` at `DRAFTING`, and `version` 1. Crisis events may be listed and filtered by `client_id` and `campaign_id`.

The **severity dimension**, `severity_status`, moves among `ASSESSING`, `CONTAINED`, and `ESCALATED`. Escalating advances `ASSESSING` to `ESCALATED`, but only when the event's `severity` is `HIGH` or `CRITICAL`; an escalate on a `LOW` or `MEDIUM` crisis is rejected with `ERR_SEVERITY_TOO_LOW`. Containing advances either `ASSESSING` or `ESCALATED` to `CONTAINED`, but only once the response dimension has reached `PUBLISHED`; a contain attempted before then is rejected with `ERR_RESPONSE_NOT_PUBLISHED`. Containment is a cross-dimension guard: it reads the response dimension but changes only the severity dimension.

The **response dimension**, `response_status`, moves among `DRAFTING`, `APPROVED`, and `PUBLISHED`. Approving the response advances `DRAFTING` to `APPROVED`, but only when the event has a non-null `holding_statement`; if no holding statement is present the approve is rejected with `ERR_NO_HOLDING_STATEMENT`. The approve-response operation may itself supply a `holding_statement` to set on the event. Publishing the response advances `APPROVED` to `PUBLISHED`. Each dimension's transition affects only that dimension and leaves the other untouched.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — including all state-transition actions and the logical-clock set — return `200 OK`. Read operations return `200 OK`. For the complete request and response shape of each operation, refer to the corresponding workflow narrative in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/agency/_clock/set_current_utc` | Set the server logical clock | PlatformAdmin |
| POST | `/agency/clients` | Create a Client | AccountManager, PlatformAdmin |
| GET | `/agency/clients/{clientId}` | Get a Client | AccountManager, MediaSpecialist, SchedulingCoordinator, PlatformAdmin |
| GET | `/agency/clients` | List Clients (filterable by status) | AccountManager, MediaSpecialist, SchedulingCoordinator, PlatformAdmin |
| POST | `/agency/clients/{clientId}/suspend` | Suspend a Client | PlatformAdmin |
| POST | `/agency/outlets` | Create an Outlet | PlatformAdmin |
| GET | `/agency/outlets/{outletId}` | Get an Outlet | AccountManager, MediaSpecialist, SchedulingCoordinator, PlatformAdmin |
| GET | `/agency/outlets` | List Outlets | AccountManager, MediaSpecialist, SchedulingCoordinator, PlatformAdmin |
| POST | `/agency/journalists` | Create a Journalist | MediaSpecialist, PlatformAdmin |
| GET | `/agency/journalists/{journalistId}` | Get a Journalist | AccountManager, MediaSpecialist, SchedulingCoordinator, PlatformAdmin |
| GET | `/agency/journalists` | List/filter Journalists | AccountManager, MediaSpecialist, SchedulingCoordinator, PlatformAdmin |
| POST | `/agency/journalists/{journalistId}/blocklist` | Blocklist a Journalist | MediaSpecialist, PlatformAdmin |
| POST | `/agency/campaigns` | Create a Campaign | AccountManager |
| GET | `/agency/campaigns/{campaignId}` | Get a Campaign | AccountManager, MediaSpecialist, SchedulingCoordinator, PlatformAdmin |
| GET | `/agency/campaigns` | List/filter Campaigns | AccountManager, MediaSpecialist, SchedulingCoordinator, PlatformAdmin |
| POST | `/agency/campaigns/{campaignId}/activate` | Activate a Campaign | AccountManager |
| POST | `/agency/campaigns/{campaignId}/pause` | Pause a Campaign | AccountManager |
| POST | `/agency/campaigns/{campaignId}/complete` | Complete a Campaign | AccountManager |
| POST | `/agency/campaigns/{campaignId}/archive` | Archive a Campaign (deep cascade) | AccountManager |
| POST | `/agency/retainer-periods` | Open a RetainerPeriod | AccountManager |
| GET | `/agency/retainer-periods/{retainerPeriodId}` | Get a RetainerPeriod | AccountManager, PlatformAdmin |
| GET | `/agency/retainer-periods` | List/filter RetainerPeriods | AccountManager, PlatformAdmin |
| POST | `/agency/retainer-periods/{retainerPeriodId}/close` | Close a RetainerPeriod | AccountManager |
| POST | `/agency/time-entries` | Log a TimeEntry | AccountManager, MediaSpecialist, SchedulingCoordinator |
| GET | `/agency/time-entries/{timeEntryId}` | Get a TimeEntry | AccountManager, MediaSpecialist, SchedulingCoordinator, PlatformAdmin |
| GET | `/agency/time-entries` | List/filter TimeEntries | AccountManager, MediaSpecialist, SchedulingCoordinator, PlatformAdmin |
| POST | `/agency/time-entries/{timeEntryId}/approve` | Approve a TimeEntry | AccountManager |
| POST | `/agency/time-entries/{timeEntryId}/void` | Void a TimeEntry | AccountManager |
| POST | `/agency/spokespersons` | Create a Spokesperson | AccountManager |
| GET | `/agency/spokespersons/{spokespersonId}` | Get a Spokesperson | AccountManager, SchedulingCoordinator, PlatformAdmin |
| GET | `/agency/spokespersons` | List/filter Spokespersons | AccountManager, SchedulingCoordinator, PlatformAdmin |
| POST | `/agency/spokespersons/{spokespersonId}/deactivate` | Deactivate a Spokesperson (cascade) | AccountManager |
| POST | `/agency/media-lists` | Create a MediaList (supersedes prior; OCC-guarded) | MediaSpecialist |
| GET | `/agency/media-lists/{mediaListId}` | Get a MediaList | AccountManager, MediaSpecialist, PlatformAdmin |
| GET | `/agency/media-lists` | List/filter MediaLists | AccountManager, MediaSpecialist, PlatformAdmin |
| POST | `/agency/pitches` | Create a Pitch | MediaSpecialist |
| GET | `/agency/pitches/{pitchId}` | Get a Pitch | AccountManager, MediaSpecialist, PlatformAdmin |
| GET | `/agency/pitches` | List/filter Pitches | AccountManager, MediaSpecialist, PlatformAdmin |
| POST | `/agency/pitches/{pitchId}/send` | Send a Pitch | MediaSpecialist |
| POST | `/agency/pitches/{pitchId}/respond` | Mark a Pitch responded | MediaSpecialist |
| POST | `/agency/pitches/{pitchId}/accept` | Accept a Pitch | MediaSpecialist |
| POST | `/agency/pitches/{pitchId}/reject` | Reject a Pitch | MediaSpecialist |
| POST | `/agency/pitches/{pitchId}/decline` | Decline a Pitch | MediaSpecialist |
| POST | `/agency/press-releases` | Create a PressRelease | MediaSpecialist |
| GET | `/agency/press-releases/{pressReleaseId}` | Get a PressRelease | AccountManager, MediaSpecialist, PlatformAdmin |
| GET | `/agency/press-releases` | List/filter PressReleases | AccountManager, MediaSpecialist, PlatformAdmin |
| POST | `/agency/press-releases/{pressReleaseId}/schedule` | Schedule a PressRelease | MediaSpecialist |
| POST | `/agency/press-releases/{pressReleaseId}/release` | Release a PressRelease | MediaSpecialist |
| POST | `/agency/press-releases/{pressReleaseId}/withdraw` | Withdraw a PressRelease | MediaSpecialist |
| POST | `/agency/distributions` | Queue a Distribution | MediaSpecialist |
| GET | `/agency/distributions/{distributionId}` | Get a Distribution | AccountManager, MediaSpecialist, PlatformAdmin |
| GET | `/agency/distributions` | List/filter Distributions | AccountManager, MediaSpecialist, PlatformAdmin |
| POST | `/agency/coverage` | Log a Coverage clip | MediaSpecialist |
| GET | `/agency/coverage/{coverageId}` | Get a Coverage clip | AccountManager, MediaSpecialist, PlatformAdmin |
| GET | `/agency/coverage` | List/filter Coverage | AccountManager, MediaSpecialist, PlatformAdmin |
| POST | `/agency/coverage/{coverageId}/verify` | Verify a Coverage clip | MediaSpecialist |
| POST | `/agency/coverage/{coverageId}/retract` | Retract a Coverage clip | MediaSpecialist |
| POST | `/agency/interviews` | Create an Interview request | SchedulingCoordinator |
| GET | `/agency/interviews/{interviewId}` | Get an Interview | AccountManager, SchedulingCoordinator, MediaSpecialist, PlatformAdmin |
| GET | `/agency/interviews` | List/filter Interviews | AccountManager, SchedulingCoordinator, MediaSpecialist, PlatformAdmin |
| POST | `/agency/interviews/{interviewId}/reschedule` | Reschedule an Interview | SchedulingCoordinator |
| POST | `/agency/interviews/{interviewId}/confirm` | Confirm an Interview | SchedulingCoordinator |
| POST | `/agency/interviews/{interviewId}/complete` | Complete an Interview | SchedulingCoordinator |
| POST | `/agency/interviews/{interviewId}/no-show` | Mark an Interview no-show | SchedulingCoordinator |
| POST | `/agency/interviews/{interviewId}/cancel` | Cancel an Interview | SchedulingCoordinator |
| POST | `/agency/crisis-events` | Open a CrisisEvent | AccountManager |
| GET | `/agency/crisis-events/{crisisId}` | Get a CrisisEvent | AccountManager, PlatformAdmin |
| GET | `/agency/crisis-events` | List/filter CrisisEvents | AccountManager, PlatformAdmin |
| POST | `/agency/crisis-events/{crisisId}/escalate` | Escalate severity dimension | AccountManager |
| POST | `/agency/crisis-events/{crisisId}/contain` | Contain severity dimension | AccountManager |
| POST | `/agency/crisis-events/{crisisId}/approve-response` | Approve response dimension | AccountManager |
| POST | `/agency/crisis-events/{crisisId}/publish-response` | Publish response dimension | AccountManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCE_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_CAMPAIGN_VERSION` | 412 |
| `ERR_STALE_PERIOD_VERSION` | 412 |
| `ERR_CLIENT_SUSPENDED` | 409 |
| `ERR_CAMPAIGN_NOT_ACTIVE` | 409 |
| `ERR_CAMPAIGN_HAS_OPEN_PITCHES` | 409 |
| `ERR_CAMPAIGN_HAS_OPEN_INTERVIEWS` | 409 |
| `ERR_JOURNALIST_BLOCKLISTED` | 409 |
| `ERR_JOURNALIST_NOT_IN_LIST` | 409 |
| `ERR_MEDIA_LIST_NOT_ACTIVE` | 409 |
| `ERR_EMBARGO_IN_PAST` | 422 |
| `ERR_EMBARGO_NOT_LIFTED` | 409 |
| `ERR_NO_DISTRIBUTIONS` | 409 |
| `ERR_SPOKESPERSON_DOUBLE_BOOKED` | 409 |
| `ERR_JOURNALIST_DOUBLE_BOOKED` | 409 |
| `ERR_SPOKESPERSON_INACTIVE` | 409 |
| `ERR_PITCH_NOT_ACCEPTED` | 409 |
| `ERR_INTERVIEW_NOT_ENDED` | 409 |
| `ERR_INTERVIEW_NOT_STARTED` | 409 |
| `ERR_PERIOD_CLOSED` | 409 |
| `ERR_PERIOD_HAS_PENDING_ENTRIES` | 409 |
| `ERR_DISTRIBUTION_RELEASE_LOCKED` | 409 |
| `ERR_SEVERITY_TOO_LOW` | 409 |
| `ERR_RESPONSE_NOT_PUBLISHED` | 409 |
| `ERR_NO_HOLDING_STATEMENT` | 409 |
| `ERR_DUPLICATE_PERIOD` | 409 |
