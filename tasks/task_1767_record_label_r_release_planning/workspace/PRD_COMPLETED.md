# Record Label Release Planning API — Product Requirements Document

## 1. Introduction

An independent record label lives and dies by a chain of interlocking commitments: a scout finds an artist, A&R structures a deal around an advance and a royalty rate, finance funds the advance and the recording budget, marketing drives the release calendar and promotion, and — quarters later — the label must explain to every artist, line by line, exactly how their royalties were earned and what was recouped. This document specifies the API that backs that entire operation, from first scouting contact through deal execution, studio delivery, distribution, promotion, tour support, and the quarterly royalty cycle.

Two concerns dominate the design. The first is money in transit: advances, milestone payments, tour floats, and promo spend all land in a per-contract recoupment ledger, and royalty earnings flow back through that ledger in a strict priority order until the artist flips from recouping to earning. The second is gated workflow: recording projects cannot start before the advance is funded, releases cannot be scheduled before assets are locked, statements cannot be paid before their run is finalized, and every one of these gates is enforced by the server rather than by convention. An artist-facing portal role rounds out the picture, letting signed artists counter deal memos, submit tour expenses, read their own statements, and dispute them.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and invariants that apply to every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity in which they act. The system recognizes exactly five roles. `LabelAdmin` is the label executive superuser — deal approval and execution, option exercise, contract termination, distributor administration, and operation of the clock and housekeeping sweeps. `AnRManager` runs A&R — scouting, deal drafting and negotiation, recording projects, milestones, tracks, release assembly and cancellation, and tour support proposals. `FinanceController` owns the money — advance disbursement, milestone payment, tour funding and expense adjudication, revenue ingestion, and the royalty runs and statements. `MarketingManager` owns the release calendar — scheduling, distributor deliveries, go-live and takedown, marketing beats, promo campaigns, and campaign spend. `ArtistPortal` is the signed artist — reading their own contract, account, and statements, countering deal memos, submitting tour expenses, and disputing statements.

A request whose headers are missing, or whose role value is not one of the five declared roles, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not in the target endpoint's authorized role list is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

The identity carried by `X-User-ID` differs by role. When `X-User-Role` is `LabelAdmin`, `AnRManager`, `FinanceController`, or `MarketingManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example as `approved_by_user_id` on a milestone or tour support, or as `funded_by_user_id` on a tour support — but it never compares that value to any entity's `id`. When `X-User-Role` is `ArtistPortal`, `X-User-ID` is the `id` of the acting Artist; ownership checks on any resource that belongs to an artist — the artist record itself, a deal memo, a contract, a recoupment account, a royalty statement, and anything reached through the artist's contract chain, namely a recording project, milestone, track, release, marketing beat, promo campaign, tour support, or tour expense — compare the resource's owning-artist chain to `X-User-ID`, and a mismatch is rejected with `ERR_ARTIST_OWNERSHIP_MISMATCH` (HTTP 403).

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

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_` — concretely, `req_` followed by 24 random alphanumeric characters.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, stamped from the server's logical clock (§2.4), never the wall clock.
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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and is capped at a maximum of 100. The `offset` parameter sets the number of items to skip and defaults to 0. Both parameters must be integer-valued — a non-integer value is rejected with `ERR_INVALID_REQUEST` — and an out-of-range integer is clamped into the allowed interval rather than rejected. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, with ties broken by creation (insertion) order. The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`. A boolean filter parameter such as `is_active` accepts the case-insensitive strings `true` and `false`; any other value is rejected with `ERR_INVALID_REQUEST`.

List endpoints also accept filter parameters natural to their resource — for example `label_id`, `artist_id`, `contract_id`, `deal_memo_id`, `project_id`, `release_id`, `distributor_id`, `run_id`, `version_of_track_id`, `status`, `distribution_status`, `genre`, `channel`, `category`, `period`, and `is_active` — alongside `limit` and `offset`. The endpoint table in §4 indicates which resources are listable; §3 narratives note the meaningful filters where they matter.

### 2.4. The Logical Clock and the Housekeeping Sweep

The server maintains a logical clock that governs every date comparison in this document; wherever the text says "today" it means the calendar date of that logical clock. At startup the logical clock reads exactly `2026-08-01T00:00:00Z` — before any explicit set call, the clock reads that default and never the wall clock. A `LabelAdmin`-only test-driving capability sets the clock by supplying a `to_iso8601` instant; the response reports the resulting `current_utc`, and no entity is mutated by the operation — only the clock changes. The supplied instant may carry any ISO 8601 offset designator (`Z` included) or none at all — an offset-less value is read as UTC — and an unparseable value is rejected with `ERR_INVALID_REQUEST`.

Alongside the clock sits a deterministic housekeeping sweep, also restricted to `LabelAdmin`, which is run against a label and performs three classes of catch-up transitions in one pass: it expires deal memos whose `valid_until_date` has passed, moves eligible contracts into their option window, and expires contracts whose term end has passed. The sweep response reports three identifier lists — `expired_deal_memo_ids`, `window_entered_contract_ids`, and `expired_contract_ids` — one per class. The precise rules behind each class live with their workflows in §3.2 and §3.3.

### 2.5. Common Resource Properties

Every primary resource carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` timestamp is an ISO 8601 UTC value with three fractional digits recording when the resource was created. The `updated_at` timestamp follows the same format and is refreshed on every mutation of the resource. The `version` is a system-managed integer that starts at 1 when the resource is created and increments by one on every mutation; it is the basis of the optimistic concurrency control described in §2.8. Any change to a resource — including system-driven changes such as cascades, computed-field recomputation, and sweep transitions — counts as a mutation and therefore refreshes `updated_at` and increments `version`. Both `created_at` and `updated_at` are stamped from the server's logical clock (§2.4), never the wall clock; since the logical clock advances only when explicitly set, several mutations of a resource occurring at the same clock instant re-stamp equal `updated_at` values, and it is the incrementing `version`, not the timestamp, that distinguishes successive mutations.

One entity is deliberately exempt. A revenue report is an append-only ingest record: once created it is never modified, so it carries only `id` and `created_at`; both `updated_at` and `version` are absent from it.

### 2.6. Money, Dates, and Rounding

All monetary values in the system are integer cents — advances, budgets, payments, spend, revenue, and balances alike — and all derived monetary values are whole cents. Where a computation produces a fraction, the result is rounded half up to the nearest whole cent. Royalty computations obey a pinned rounding order: every revenue line is rounded individually, and statement totals are sums of those already-rounded line values; the system never sums unrounded values and rounds once at the end. Per-category tour caps are the one place where truncation is used instead: the cap is computed with integer division that discards any fractional cent.

Two non-monetary quantities have their own precision rules. The scouting score is a number rounded half up to exactly one decimal place and then clamped into the range from 0 to 100 inclusive. Calendar dates use the `YYYY-MM-DD` format, and royalty periods use the `YYYY-Qn` format with the quarter number between 1 and 4; period strings are compared lexicographically, and that ordering is identical to chronological order.

### 2.7. The Recoupment Ledger

Every executed deal produces exactly one recoupment account, created together with the contract, and that account is the single source of truth for what the artist owes the label. The account keeps four independent bucket balances, all starting at zero: `recording_balance_cents` for unrecouped recording (milestone) costs, `advance_balance_cents` for the unrecouped advance, `tour_support_balance_cents` for unrecouped approved tour expenses, and `promo_balance_cents` for unrecouped recoupable promo spend. Their sum is exposed as `total_unrecouped_cents`, recomputed whenever any bucket moves. Two further counters track history: `total_recouped_cents`, the lifetime amount recovered through royalty waterfalls, and `writeoff_cents`, the amount forgiven at contract termination.

Bucket balances move only through the events described in §3: disbursing the advance debits the advance bucket, paying a milestone debits the recording bucket, approving a tour expense debits the tour bucket (and voiding one credits it back), and recording promo spend debits the promo bucket when the contract makes promo costs recoupable. The account's `payout_status` begins at `RECOUPING` and flips to `EARNING` only when a royalty waterfall drives `total_unrecouped_cents` to zero.

When royalties are applied, buckets are drained in a pinned priority order — recording first, then advance, then tour support, then promo — and which buckets are eligible at all depends on the contract's recoupment scope, as detailed in §3.8.

### 2.8. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control, each against the current `version` of a named parent resource. In each case the request must carry the named expectation field holding the version the client last observed; if that value does not equal the parent's current `version` — because another write has advanced the version since the client read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting state it has not observed.

Countering a deal memo requires `expected_deal_memo_version` to match the deal memo's current `version`. Because countering is legitimate from both `PROPOSED` and `COUNTERED`, a second sequential counter would otherwise succeed under the natural semantics, so a stale observation of the memo is caught purely by this version check. Amending a recording project's budget requires `expected_recording_project_version` to match the project's current `version`; budget amendment is repeatable from every non-terminal project status, so the version check is the only thing that invalidates an amendment based on a stale read. Adjusting a royalty statement requires `expected_royalty_statement_version` to match the statement's current `version`; adjustment is repeatable while the statement is `PROVISIONAL` or `DISPUTED`, so again only the version check catches a stale base. Endpoints not listed here take no version field at all.

### 2.9. Validation Order and the Error Surface

Every request is validated in a fixed pipeline order, so that when several problems exist the surfaced error is deterministic. First, the presence and validity of the two user-context headers is checked (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`). Second, the caller's role is checked against the endpoint's authorized roles (`ERR_FORBIDDEN_FOR_ROLE`). Third, for endpoints an `ArtistPortal` caller may reach, the ownership of the addressed resource is verified (`ERR_ARTIST_OWNERSHIP_MISMATCH`). Fourth, path identifiers are resolved left to right, and body foreign-key references are checked for existence and same-label membership (`ERR_NOT_FOUND`). Fifth, the request body itself is validated — required fields present, types correct, enum membership, and numeric ranges such as a base royalty rate between 1,000 and 3,000 basis points, an options count between 0 and 3, an initial term of 12, 24, or 36 months, and end dates falling after start dates (`ERR_INVALID_REQUEST`); a body that is not valid JSON, or that is not a JSON object, fails at this layer as well. Sixth, on the three OCC-guarded writes, the expectation field is compared to the parent's current version (`ERR_STALE_VERSION`). Seventh, the attempted state transition must be declared from the resource's current status — attempts from terminal states included (`ERR_INVALID_STATE`).

Only after all seven general layers pass do the domain business rules run, in this category order: safety rules first (guardian consent, sample clearance), then business constraints (uniqueness and cardinality rules), then cross-entity referential gates (funding, signability, renegotiation, release liveness, unrecouped balances), then temporal rules (expiry, windows, lead times, overlaps), and finally fiscal rules (caps, budgets, segregation of duties, non-negative payable). The requirement that every statement of a run be paid before the run itself can be marked paid is evaluated last of all. Where several business rules guard the same endpoint, §3 states their relative order next to the workflow they guard.

### 2.10. Cascading Side Effects and Hierarchical Consistency

Many operations in this system mutate more than one resource, and every such cascade is atomic within the triggering request: either all linked changes are visible or none are. The server may also transition a resource without an explicit client request on that resource — a member track being blocked can revert a release's asset state, unschedule its distribution, and cancel its in-flight deliveries; finalizing a royalty run advances every statement of the run and may flip recoupment accounts into earning. These automatic transitions follow the same rules as client-driven ones and are enumerated with their workflows in §3. Parent-child alignment is maintained in both directions: a parent becoming non-operational resolves its dependents, and a child event that satisfies or violates a parent's state criteria reconciles the parent.

### 2.11. Nested Resource Retrieval

Requests that target nested resources validate path identifiers sequentially from left to right, and the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not correspond to an existing resource. Foreign keys supplied in request bodies are likewise checked for existence, and any referenced resource must belong to the same label as the rest of the request; a cross-label reference is not found from the caller's perspective.

## 3. Business Logic & Workflows

### 3.1. The Label, Its Policy Knobs, and Scouting

Everything in the system hangs off a label. A `LabelAdmin` creates the label with a display `name` and may override any of its policy knobs at creation; every knob has a default. `advance_cap_cents` (default 5,000,000) is the maximum advance allowed on any executed deal memo. `reserve_rate_bps` (default 1,000 basis points) is the provisional-statement reserve rate. `sign_threshold_score` (default 40.0) is the minimum scouting score required to propose a deal memo. `option_window_days` (default 90) is how far before a contract's term end an option may be exercised. `release_lead_days` (default 21) is the minimum lead time between scheduling and the release date. `beat_pre_release_days` (default 42) and `beat_post_release_days` (default 30) bound how early beats may start and how late they may end relative to the release date. `campaign_gap_days` (default 7) is the minimum gap between promotion campaigns on the same release and channel. `genre_multipliers` (defaulting to 1.10 for `POP`, 1.05 for `HIPHOP`, 1.00 for `ROCK`, 0.95 for `ELECTRONIC`, and 0.90 for `OTHER`) scales scouting scores per genre. `channel_deduction_bps` (defaulting to 3,000 for `STREAMING`, 1,500 for `DOWNLOAD`, 2,500 for `PHYSICAL`, and 0 for `SYNC`) is the distribution deduction taken off gross revenue per channel. `tier_thresholds` (defaulting to three marks — 0 units carrying no delta, 500,000 units carrying a 200-basis-point delta, and 2,000,000 units carrying a 300-basis-point delta) defines marginal royalty-rate escalations by cumulative units, where a unit at a position strictly greater than a threshold earns that threshold's delta. `tour_category_caps_bps` (defaulting to 5,000 for `TRAVEL`, 3,000 for `LODGING`, 4,000 for `PRODUCTION`, and 1,000 for `MISC`) caps each tour-expense category as a share of the approved tour budget. Overrides are validated at creation: the scalar knobs are non-negative integers, except `reserve_rate_bps`, which is additionally capped at 10,000, and `sign_threshold_score`, which may be fractional; the two basis-point maps and `genre_multipliers` merge per key over the defaults rather than replacing them — their keys are not restricted to the known channels, categories, or genres — with basis-point values required to be integers between 0 and 10,000 and multiplier values non-negative numbers; and a supplied `tier_thresholds` replaces the whole list, each entry carrying non-negative integer `units` and `delta_bps`.

An `AnRManager` scouts an artist by creating the record with the owning `label_id`, the artist's `stage_name`, a `genre` of `POP`, `HIPHOP`, `ROCK`, `ELECTRONIC`, or `OTHER`, the `birth_date`, and four scouting metrics: `monthly_streams`, `social_followers`, `engagement_rate` (a number between 0 and 1 inclusive), and `live_draw_avg`; the three volumetric metrics must be non-negative integers. At creation the server computes the artist's `scouting_score`. Each capped metric is first normalized — divided by its cap, taking the lesser of that quotient and one — with `monthly_streams` capped at 1,000,000, `social_followers` at 2,000,000, and `live_draw_avg` at 2,000. The weighted sum combines 30 percent of the normalized streams, 20 percent of the normalized followers, 25 percent of the engagement rate used as-is, and 25 percent of the normalized live draw; multiplying that sum by 100 yields the raw score. The raw score is then multiplied by the label's genre multiplier for the artist's genre, the product is rounded half up to one decimal place, and the result is clamped so it never falls below 0 or above 100.

A new artist starts in `SCOUTED` status. When the first deal memo for a scouted artist is proposed, the artist moves from `SCOUTED` to `IN_NEGOTIATION`; a `SIGNED` or `ACTIVE` artist does not change state on propose. If that negotiation later collapses — the memo is rejected, or it expires — and the artist has no other memo in `DRAFT`, `PROPOSED`, `COUNTERED`, or `APPROVED` and no contract at all, the artist reverts from `IN_NEGOTIATION` back to `SCOUTED`. Executing a memo moves the artist from `IN_NEGOTIATION` to `SIGNED`, and the first time a release of the artist's contract goes live the artist moves from `SIGNED` to `ACTIVE`.

Artists also have an off-ramp and a way back. An `AnRManager` may place a `SIGNED` or `ACTIVE` artist on hiatus, moving them to `HIATUS` and recording where they came from in `pre_hiatus_status`. Reactivation returns the artist to exactly that recorded status — `HIATUS` to `SIGNED` when `pre_hiatus_status` is `SIGNED`, and `HIATUS` to `ACTIVE` when it is `ACTIVE` — and clears `pre_hiatus_status` back to null. A `LabelAdmin` may drop an artist from `SIGNED`, `ACTIVE`, or `HIATUS`, but only once every contract of the artist is `EXPIRED` or `TERMINATED`; if any contract is still live the drop is rejected with `ERR_INVALID_STATE`. `DROPPED` is terminal.

### 3.2. Deal Memos: Negotiation, Approval, and Execution

Deals begin when an `AnRManager` drafts a deal memo under an artist. The draft carries the full proposed term sheet: `advance_cents` (zero or more), `base_royalty_rate_bps` (between 1,000 and 3,000 basis points), `recoupment_scope` (`MASTER_ONLY` or `CROSS_COLLATERALIZED`, selecting which recoupment buckets royalties may recoup against), `promo_costs_recoupable` (whether promo campaign spend debits the promo bucket), `options_total` (between 0 and 3 label options), `option_term_months` (12 or 24 months added per exercised option), `option_escalation_bps` (royalty basis points added per exercised option), `term_months` (an initial term of 12, 24, or 36 months), and `valid_until_date`, after which the memo lapses. For a minor artist the draft may also carry `guardian_name` and `guardian_email`, both null by default; the two fields are accepted on any draft regardless of the artist's age and become mandatory only when a minor artist's memo is executed. The memo records the `artist_id` of the artist it was drafted under, keeps a `round_count` of negotiation rounds starting at 0, has a `contract_id` that stays null until execution, and starts in `DRAFT` status. An artist may have at most one open memo — one in `DRAFT`, `PROPOSED`, `COUNTERED`, or `APPROVED` — so drafting while another memo is open is rejected with `ERR_DEAL_MEMO_ALREADY_OPEN`. Drafting or proposing also requires the artist to be in `SCOUTED`, `IN_NEGOTIATION`, `SIGNED`, or `ACTIVE` — a `SIGNED` or `ACTIVE` artist's new memo is how renegotiation begins — and any other artist status is rejected with `ERR_ARTIST_NOT_SIGNABLE`.

Proposing moves a memo from `DRAFT` to `PROPOSED`. The checks at propose run in a fixed order: first the one-open-memo rule above, then the scouting gate — the artist's `scouting_score` must be at least the label's `sign_threshold_score`, otherwise `ERR_SCOUTING_SCORE_TOO_LOW` — then artist signability, and finally the expiry guard, which moves the memo to `EXPIRED` and rejects with `ERR_DEAL_MEMO_EXPIRED` when today is past `valid_until_date`. A successful propose moves a `SCOUTED` artist to `IN_NEGOTIATION` and increments the memo's `version`.

Countering is the negotiation loop: from `PROPOSED` a counter moves the memo to `COUNTERED`, and from `COUNTERED` a counter returns it to `PROPOSED`. Either an `AnRManager` or the artist through the `ArtistPortal` may counter, but an artist may counter only memos belonging to their own artist record (`ERR_ARTIST_OWNERSHIP_MISMATCH` otherwise). Every counter request must carry `expected_deal_memo_version` matching the memo's current `version`, per §2.8; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), and this OCC check is evaluated before the expiry guard. A counter is likewise refused once `valid_until_date` has passed, expiring the memo with `ERR_DEAL_MEMO_EXPIRED`. A successful counter increments `round_count` by one, overwrites whichever term fields were supplied — `advance_cents`, `base_royalty_rate_bps`, `recoupment_scope`, `promo_costs_recoupable`, `options_total`, `option_term_months`, `option_escalation_bps`, `term_months`, or `valid_until_date` — and increments the memo's `version`.

A `LabelAdmin` approves a memo from either `PROPOSED` or `COUNTERED`, moving it to `APPROVED`; the only guard beyond state is the expiry guard. Approval is not execution — the deal has no financial effect yet.

Execution is the moment the deal becomes real. A `LabelAdmin` executes an `APPROVED` memo, and the operation returns the newly created contract (HTTP 201). Three guards apply, in this order: first, if the artist is under 18 years old as of today, the memo must carry both `guardian_name` and `guardian_email`, otherwise `ERR_GUARDIAN_CONSENT_REQUIRED`; second, the expiry guard; third, the memo's `advance_cents` must not exceed the label's `advance_cap_cents`, otherwise `ERR_ADVANCE_CAP_EXCEEDED`. On success, five things happen atomically. A contract is created in `ACTIVE` status with `term_start_date` set to today's date and `current_term_end_date` set `term_months` calendar months later; its `artist_id`, `deal_memo_id`, `advance_cents`, `base_royalty_rate_bps`, `recoupment_scope`, `promo_costs_recoupable`, `options_total`, `option_escalation_bps`, and `option_term_months` are copied from the memo, and `options_exercised` starts at 0. A recoupment account is created one-to-one for the contract with all four bucket balances at zero and `payout_status` `RECOUPING`. The contract's `advance_status` is set to `FUNDED` immediately when the advance is zero, and to `PENDING` otherwise. The artist moves from `IN_NEGOTIATION` to `SIGNED`. And the memo's `contract_id` is set to the new contract while the memo itself becomes `EXECUTED`, which is terminal.

An `AnRManager` may reject a memo from `DRAFT`, `PROPOSED`, or `COUNTERED`, moving it to `REJECTED`; if that closes the artist's last open memo and no contract exists, the artist reverts from `IN_NEGOTIATION` to `SCOUTED`. Memos also expire: from any of `DRAFT`, `PROPOSED`, `COUNTERED`, or `APPROVED`, a memo whose `valid_until_date` has passed moves to `EXPIRED`, either during the housekeeping sweep or lazily when a guarded transition — propose, counter, approve, or execute — is attempted against it, in which case the attempt is rejected with `ERR_DEAL_MEMO_EXPIRED` as the memo expires. Expiry triggers the same artist reversion as rejection.

### 3.3. Contract Administration: Advances, Option Windows, and Termination

A contract in `ACTIVE` with a `PENDING` advance is waiting on finance. A `FinanceController` disburses the advance, which requires `advance_status` to be `PENDING` — attempting a second disbursement is rejected with `ERR_INVALID_STATE`. Disbursal adds the contract's `advance_cents` to the recoupment account's `advance_balance_cents`, flips `advance_status` to `FUNDED`, leaves the contract in `ACTIVE`, and increments the contract's `version`. A contract's recoupment account can be read back through a reverse lookup that returns an array of length zero or one, since the account exists only from execution onward.

Option windows are managed by the housekeeping sweep. When the sweep finds a contract in `ACTIVE` or `EXTENDED` whose today is on or after the date `option_window_days` before `current_term_end_date` and still on or before `current_term_end_date`, and whose `options_exercised` is still below `options_total`, it moves the contract to `OPTION_WINDOW`; these contracts appear in the sweep's `window_entered_contract_ids`. A contract whose `current_term_end_date` has passed moves to `EXPIRED` — from `ACTIVE`, `OPTION_WINDOW`, or `EXTENDED` alike — and appears in `expired_contract_ids`. `EXPIRED` is terminal.

While a contract is in `OPTION_WINDOW`, a `LabelAdmin` may exercise an option, moving it to `EXTENDED`. Exercise is allowed only while today is still on or before `current_term_end_date` — afterwards the window is shut and the attempt is rejected with `ERR_OPTION_WINDOW_CLOSED` — and only while no deal memo of the contract's artist is open in `DRAFT`, `PROPOSED`, `COUNTERED`, or `APPROVED`, because an open memo means renegotiation is in flight and the attempt is rejected with `ERR_RENEGOTIATION_IN_PROGRESS`; where both guards would fail, the renegotiation check is evaluated before the window-closed check, consistent with §2.9's referential-before-temporal ordering. Exercising increments `options_exercised` by one, pushes `current_term_end_date` out by `option_term_months` calendar months, recomputes the contract's `effective_base_rate_bps`, and increments the contract's `version`. That effective rate is the lesser of two quantities — the `base_royalty_rate_bps` plus `options_exercised` times `option_escalation_bps`, and a hard ceiling of 3,000 basis points — and the same computation runs at contract creation, where with zero options exercised it simply yields the base rate.

Termination is the hard stop, available to a `LabelAdmin` from `ACTIVE`, `OPTION_WINDOW`, or `EXTENDED`, and it takes a single explicit input, `write_off_unrecouped`. When the recoupment account's `total_unrecouped_cents` is still positive, termination requires `write_off_unrecouped` to be true; refusing to write off a live balance is rejected with `ERR_UNRECOUPED_BALANCE`. When the write-off flag is set, the account's `writeoff_cents` is recorded as the full `total_unrecouped_cents` at that moment and all four bucket balances are zeroed. `TERMINATED` is terminal.

### 3.4. Recording Projects, Milestones, and Tracks

Once a deal is executed, an `AnRManager` may open a recording project under the contract with a working `title`, a `project_type` of `SINGLE`, `EP`, or `ALBUM`, and a `budget_cents` ceiling. The contract must be in `ACTIVE`, `OPTION_WINDOW`, or `EXTENDED`, and the artist must be `SIGNED` or `ACTIVE` (`ERR_ARTIST_NOT_SIGNABLE` otherwise). The `budget_cents` ceiling may be zero at creation — the positive-budget requirement bites only when the project is started. The project starts `PLANNED` with `spent_cents` and `committed_cents` both at zero.

Budgets are living numbers until delivery. An `AnRManager` may amend `budget_cents` while the project is `PLANNED`, `RECORDING`, or `POST_PRODUCTION` — never once `DELIVERED` or `CANCELLED` — and every amendment request must carry `expected_recording_project_version` matching the project's current `version` per §2.8, with mismatches rejected as `ERR_STALE_VERSION` (HTTP 412). The new budget must be at least the amount already spent — equality is allowed — otherwise the amendment is rejected with `ERR_BUDGET_BELOW_SPEND`. Each amendment recomputes the project's budget posture and increments its `version`.

Starting a project moves it from `PLANNED` to `RECORDING` and is where the funding gate bites: the contract must be in `ACTIVE`, `OPTION_WINDOW`, or `EXTENDED`, its `advance_status` must be `FUNDED` (`ERR_CONTRACT_NOT_FUNDED` while still `PENDING`), and `budget_cents` must be greater than zero (`ERR_INVALID_REQUEST` otherwise). The artist gate applies here too — starting, like creating, requires a `SIGNED` or `ACTIVE` artist, so a `SCOUTED` or `IN_NEGOTIATION` artist is rejected with `ERR_ARTIST_NOT_SIGNABLE`, while a `HIATUS` or `DROPPED` artist violates the state precondition and is rejected with `ERR_INVALID_STATE`. From `RECORDING`, advancing the stage moves the project to `POST_PRODUCTION`, but only when no milestone of the project is still `PENDING` or `SUBMITTED` (`ERR_INVALID_STATE`). Advancing again from `POST_PRODUCTION` delivers the project, and the bar is higher: every non-`CANCELLED` milestone must be `PAID` and every track of the project must be `MASTERED` or `CLEARED` — any shortfall is `ERR_INVALID_STATE`. `DELIVERED` is terminal.

Cancellation is available from `PLANNED`, `RECORDING`, or `POST_PRODUCTION`, but never while any milestone stands `APPROVED` — an approved-but-unpaid milestone is a live commitment and blocks cancellation with `ERR_INVALID_STATE`. Cancelling cascades: every milestone in `PENDING`, `SUBMITTED`, or `REJECTED` moves to `CANCELLED`. `CANCELLED` is terminal.

Milestones structure the spend. An `AnRManager` creates a milestone under a project that is `RECORDING` or `POST_PRODUCTION` — attempts while the project is in any other status are rejected with `ERR_INVALID_STATE` — supplying a `name`, a `sequence` — any integer, with no range constraint — that orders the milestone within the project and must be unique among the project's non-`CANCELLED` milestones (`ERR_MILESTONE_SEQUENCE_CONFLICT` on a duplicate), a `due_date`, a `payment_cents` amount greater than zero, and an optional `deliverable_note`. Milestones start `PENDING`. Submission — from `PENDING`, or again from `REJECTED` as a resubmission — moves a milestone to `SUBMITTED` and may attach a `deliverable_note`; the project must be `RECORDING` or `POST_PRODUCTION` (`ERR_INVALID_STATE`). A `LabelAdmin` then approves or rejects: approval moves the milestone to `APPROVED`, adds its `payment_cents` to the project's `committed_cents`, records the caller in `approved_by_user_id`, and recomputes budget posture; rejection moves it to `REJECTED` with no financial effect.

Payment is the point where money hits the ledger. A `FinanceController` pays an `APPROVED` milestone, which requires the project to be `RECORDING` or `POST_PRODUCTION` (`ERR_INVALID_STATE`) and requires that the project's `spent_cents` plus this `payment_cents` not exceed `budget_cents` — equality is allowed — otherwise `ERR_PROJECT_BUDGET_EXCEEDED`. Paying subtracts the amount from `committed_cents`, adds it to `spent_cents`, recomputes the project's budget posture, and — the second link of the pay cascade — adds the same amount to the recoupment account's `recording_balance_cents`, recomputing `total_unrecouped_cents`. `PAID` is terminal.

Budget posture is a standing signal, recomputed on every milestone approval, every milestone payment, and every budget amendment: `spent_cents` is the sum of `payment_cents` over `PAID` milestones, `committed_cents` the sum over `APPROVED`-but-unpaid ones, and `budget_posture` is `AT_RISK` whenever the sum of spent and committed reaches at least 85 percent of `budget_cents` — the boundary is inclusive, so exactly 85 percent is already at risk — and `WITHIN_BUDGET` otherwise.

Tracks are the creative payload of a project. An `AnRManager` creates a track under a project — in any project status, since creation carries no project-state gate — with a `title`, a `duration_seconds` greater than zero, an `isrc` recording code that must be unique per label across all tracks (`ERR_ISRC_CONFLICT` on collision), a `contains_sample` flag defaulting to false, an optional `clearance_ref`, and an optional `version_of_track_id` that gives radio edits and remixes a self-referential lineage — the referenced track must belong to the same label. Tracks start in `DEMO`. Advancing a track walks it one step at a time through `TRACKED`, then `MIXED`, then `MASTERED`, then `CLEARED`, and every advance requires the project to be neither `CANCELLED` nor `DELIVERED` (`ERR_INVALID_STATE`). The final step into `CLEARED` carries a clearance gate: when `contains_sample` is true, `clearance_ref` must be non-null, otherwise `ERR_SAMPLE_CLEARANCE_MISSING`.

Blocking is the emergency brake, available to an `AnRManager` from `TRACKED`, `MIXED`, `MASTERED`, or `CLEARED`, and it detonates a three-link cascade beyond the track itself. First, every non-`CANCELLED` release — non-`CANCELLED` here refers to the distribution dimension — containing the blocked track whose `asset_status` is `ASSEMBLED` or `LOCKED` reverts its `asset_status` to `DRAFT`. Second, each release whose asset state just reverted and whose `distribution_status` is `SCHEDULED` reverts to `PLANNED`. Third, every delivery of such a release that is `QUEUED` or `TRANSMITTED` is cancelled. Rework returns a `BLOCKED` track to `TRACKED`, subject to the same project-state rule as advancing.

### 3.5. Release Assembly, Scheduling, and Distribution

A release bundles finished tracks into a commercial product. An `AnRManager` creates a release under a contract, supplying the `project_id` of the primary project the release draws from — which must reference a project of that same contract, otherwise `ERR_NOT_FOUND` — a `title`, a `release_type` of `SINGLE` or `ALBUM`, the commercial `release_date`, and the member `track_ids`, which must be a non-empty list of strings — an empty list fails body validation with `ERR_INVALID_REQUEST` before the cardinality rule runs. The cardinality rule is strict: a `SINGLE` carries exactly one track, an `ALBUM` carries between 2 and 30, every listed track must belong to a project of the same contract, and every listed track must already be `MIXED`, `MASTERED`, or `CLEARED` — any violation is rejected with `ERR_SINGLE_TRACK_COUNT`. The artist must be `SIGNED` or `ACTIVE` (`ERR_ARTIST_NOT_SIGNABLE`). A release carries two independent state dimensions from birth: `asset_status`, starting at `DRAFT`, and `distribution_status`, starting at `PLANNED`.

The asset dimension is A&R's. Assembling moves `asset_status` from `DRAFT` to `ASSEMBLED`, requires the release's `distribution_status` to still be `PLANNED` (`ERR_INVALID_STATE`), and requires every member track to be `CLEARED` — not merely mixed or mastered — otherwise `ERR_TRACKS_NOT_CLEARED`. Locking moves `ASSEMBLED` to `LOCKED` and takes one explicit input, `cover_art_confirmed`, which must be true; without confirmed cover art the lock is rejected with `ERR_COVER_ART_MISSING`. Both reverts described in §3.4 — `ASSEMBLED` back to `DRAFT`, and `LOCKED` back to `DRAFT` with the distribution unscheduling and delivery cancellation that follow — arrive only as cascades from a member track being blocked.

The distribution dimension belongs to marketing. A `MarketingManager` schedules a release, moving `distribution_status` from `PLANNED` to `SCHEDULED`; scheduling requires the assets to be `LOCKED` (`ERR_ASSETS_NOT_LOCKED` otherwise) and requires `release_date` to be at least `release_lead_days` — 21 days by default — after today, with equality allowed, otherwise `ERR_RELEASE_LEAD_TIME`.

With a release scheduled, deliveries carry the assets to partners. Creating deliveries takes a non-empty list of `distributor_ids` and creates one delivery per distributor, each starting `QUEUED` with `attempt_count` at zero; creation imposes no requirement on the release's current `distribution_status`, and the response is `201 Created` with `response_type` `array`, carrying the created deliveries in `data`. At most one non-terminal delivery — one in `QUEUED`, `TRANSMITTED`, or `REJECTED` — may exist per release-and-distributor pair, and a distributor id repeated within the request list itself violates the same rule, otherwise `ERR_DUPLICATE_DELIVERY`, and that duplicate check is evaluated before the activity check that follows: an inactive distributor rejects new deliveries with `ERR_DISTRIBUTOR_INACTIVE`. Distributors themselves are administered by a `LabelAdmin`, created with a `label_id`, a `name`, a `channel_type` of `DSP`, `PHYSICAL`, or `RADIO`, and an `is_active` flag defaulting to true; the flag can later be flipped either way by an update whose body must carry the `is_active` boolean. Transmitting moves a delivery from `QUEUED` to `TRANSMITTED`, requires the release's `distribution_status` to be `SCHEDULED` (`ERR_INVALID_STATE`), and increments `attempt_count` by one. The distributor's answer is recorded next: acknowledging moves `TRANSMITTED` to `ACKNOWLEDGED`, and rejecting moves it to `REJECTED`; a rejected delivery may be retried, returning it to `QUEUED`, again only while the release is `SCHEDULED`. Acknowledgement bubbles upward — the moment at least one non-`CANCELLED` delivery exists for a release and every non-`CANCELLED` delivery is `ACKNOWLEDGED`, the release's `distribution_status` moves from `SCHEDULED` to `DELIVERED`. Both `ACKNOWLEDGED` and `CANCELLED` are terminal for a delivery.

Going live is the commercial event. A `MarketingManager` goes live from `DELIVERED`, allowed only once today has reached `release_date` — earlier attempts are rejected with `ERR_RELEASE_DATE_NOT_REACHED`. Going live stamps `went_live_date` with today's date, moves the release to `LIVE`, and, when this is the first live release of the artist's contract, moves a `SIGNED` artist to `ACTIVE`. From `LIVE` a release may be taken down to `TAKEN_DOWN`, and a taken-down release may be relaunched back to `LIVE`.

Cancellation is available to an `AnRManager` or `LabelAdmin` from `PLANNED`, `SCHEDULED`, `DELIVERED`, or `TAKEN_DOWN` — notably not from `LIVE`, where the release must be taken down first — and it cascades: every beat of the release in `PLANNED` or `READY` moves to `CANCELLED`, every promo campaign in `DRAFT`, `ACTIVE`, or `PAUSED` moves to `KILLED`, and every delivery in `QUEUED` or `TRANSMITTED` moves to `CANCELLED`. `CANCELLED` is terminal for the distribution dimension.

### 3.6. Marketing Beats and Promo Campaigns

A `MarketingManager` plans a marketing beat against a release with a `beat_type` of `TEASER`, `SINGLE_DROP`, `VIDEO`, `PRESS`, or `TOUR_ANNOUNCE`, a `channel` of `PLAYLIST`, `RADIO`, `SOCIAL`, or `PRESS`, a `start_date`, an `end_date` that must fall after the start date, and a `budget_cents` of zero or more. Beats start `PLANNED`, with `impressions` and `engagement_score` null until measured. Two temporal guards apply at planning time, evaluated in this order. First, the beat must sit inside the release window: `start_date` no earlier than `beat_pre_release_days` before `release_date` — 42 days by default — and `end_date` no later than `beat_post_release_days` after it — 30 days by default — with both boundaries inclusive; a beat outside the window is rejected with `ERR_BEAT_OUTSIDE_WINDOW`. Second, beats on the same release and channel may not overlap: treating each beat as a half-open window that includes its start date and excludes its end date, two beats overlap when each one's start falls before the other's end, and touching windows — one ending exactly when the other begins — do not overlap. The check runs against beats in `PLANNED`, `READY`, `EXECUTED`, or `MEASURED`; `SKIPPED` and `CANCELLED` beats are ignored, and a collision is rejected with `ERR_BEAT_WINDOW_OVERLAP`.

The beat lifecycle is simple. Readying moves `PLANNED` to `READY`; executing moves `READY` to `EXECUTED`; measuring moves `EXECUTED` to `MEASURED` and records the supplied `impressions` (a non-negative integer) and `engagement_score` (any number) on the beat. A beat in `PLANNED` or `READY` may instead be skipped to `SKIPPED`, and the release-cancellation cascade moves beats in `PLANNED` or `READY` to `CANCELLED`. `MEASURED`, `SKIPPED`, and `CANCELLED` are all terminal.

Promo campaigns are the paid-push counterpart, created by a `MarketingManager` against a release with a `channel` of `PLAYLIST` or `RADIO`, a `start_date`, an `end_date` on or after the start date, and a `spend_cap_cents` greater than zero. Campaigns start in `DRAFT` with `spend_cents` at zero. Campaigns use closed intervals — both endpoints count — and a mandatory buffer: two campaigns on the same release and channel conflict unless at least `campaign_gap_days` separate them. Precisely, there is no conflict only when one campaign's end date plus the gap falls on or before the other's start date (or vice versa), so a gap of exactly `campaign_gap_days` — 7 days by default — is allowed. The check runs against all campaigns not in `KILLED`, and a conflict is rejected with `ERR_CAMPAIGN_WINDOW_CONFLICT`. Note the deliberate difference from beats: closed intervals plus a mandatory buffer, versus half-open intervals with adjacency allowed.

Activation moves a campaign from `DRAFT` to `ACTIVE` and requires the release's `distribution_status` to be `SCHEDULED`, `DELIVERED`, or `LIVE` (`ERR_INVALID_STATE`). Pausing moves `ACTIVE` to `PAUSED`; resuming moves `PAUSED` back to `ACTIVE` under the same release-state gate as activation. Completing moves a campaign from `ACTIVE` or `PAUSED` to `COMPLETED`. Killing moves a campaign from `DRAFT`, `ACTIVE`, or `PAUSED` to `KILLED`, and the release-cancellation cascade kills the same three states. `COMPLETED` and `KILLED` are terminal.

Spend is recorded against an `ACTIVE` campaign — recording spend in any other status is rejected with `ERR_INVALID_STATE` — by supplying an `amount_cents` that must be a positive integer. The campaign's `spend_cents` plus the new amount must not exceed `spend_cap_cents`, equality allowed, otherwise `ERR_CAMPAIGN_CAP_EXCEEDED`. An accepted spend adds the amount to `spend_cents`, and when the release's contract has `promo_costs_recoupable` set, the same amount is added to the recoupment account's `promo_balance_cents` with `total_unrecouped_cents` recomputed; when the flag is not set, promo spend is a pure marketing cost and never touches the ledger.

### 3.7. Tour Support and Expense Accounting

Tour support starts with the artist's ask. An `AnRManager` proposes a tour support under a contract with a `tour_name` and a `requested_amount_cents` greater than zero; the artist must be `SIGNED` or `ACTIVE` (`ERR_ARTIST_NOT_SIGNABLE`), and the proposal starts in `PROPOSED` with `approved_budget_cents`, `advanced_amount_cents`, `unspent_returned_cents`, `approved_by_user_id`, and `funded_by_user_id` all null and `approved_expense_total_cents` at zero.

A `LabelAdmin` then decides. Approval moves the proposal to `APPROVED`, setting `approved_budget_cents` from the supplied input — a positive integer that must not exceed `requested_amount_cents`, otherwise `ERR_APPROVED_EXCEEDS_REQUESTED` — and recording the caller as `approved_by_user_id`. Declining moves `PROPOSED` to `DECLINED`, which is terminal. Before any money moves, an `AnRManager` may also cancel an `APPROVED` support outright, moving it to `CANCELLED`, which is likewise terminal.

Funding is a segregated duty. A `FinanceController` advances funds against an `APPROVED` support, supplying an `amount_cents` that must be a positive integer and must not exceed `approved_budget_cents` (`ERR_INVALID_REQUEST` otherwise, and this amount check runs first), and the caller's `X-User-ID` must differ from the `approved_by_user_id` recorded at approval — the same operator may not both approve and fund, and a violation is rejected with `ERR_SEGREGATION_OF_DUTIES`. Advancing sets `advanced_amount_cents` to the supplied amount, records the caller as `funded_by_user_id`, and moves the support to `ADVANCED`. Notably, advancing funds does not touch the tour-support recoupment bucket.

Expenses are the artist's paperwork. Through the `ArtistPortal`, the owning artist submits an expense against a tour support that is `ADVANCED` — any other status is `ERR_INVALID_STATE` — giving a `category` of `TRAVEL`, `LODGING`, `PRODUCTION`, or `MISC`, an `amount_cents` greater than zero, and an `expense_date`; the expense records the `tour_support_id` of the support it was submitted under and starts `SUBMITTED`. A `FinanceController` adjudicates. Approval is the fiscally loaded step, and it first requires the tour support to still be `ADVANCED` (`ERR_INVALID_STATE` otherwise); then come two caps, evaluated in this order: first the category cap — the sum of `APPROVED` expense amounts in the same category plus this `amount_cents` must not exceed the category's cap, computed as the label's `tour_category_caps_bps` share for that category multiplied by `approved_budget_cents` and divided by 10,000 with integer division discarding any fraction (by default 50 percent for travel, 30 for lodging, 40 for production, 10 for miscellaneous), with equality allowed and violations rejected as `ERR_CATEGORY_CAP_EXCEEDED`; then the total cap — `approved_expense_total_cents` plus this `amount_cents` must not exceed `approved_budget_cents`, equality allowed, otherwise `ERR_TOUR_BUDGET_EXCEEDED`. Approval adds the amount to the recoupment account's `tour_support_balance_cents`, adds it to the support's `approved_expense_total_cents`, and recomputes `total_unrecouped_cents`. Rejection moves the expense to `REJECTED`, terminal.

Voiding is the compensating move: a `FinanceController` may void an `APPROVED` expense while the tour support is anything but `CLOSED` (`ERR_INVALID_STATE` once closed), subtracting the amount from `tour_support_balance_cents` and from `approved_expense_total_cents` and recomputing `total_unrecouped_cents`. `VOIDED` is terminal.

Reconciliation closes the loop on the cash float. A `FinanceController` reconciles an `ADVANCED` support, computing `unspent_returned_cents` as the larger of zero and `advanced_amount_cents` minus `approved_expense_total_cents`, and the support moves to `RECONCILED`. Neither advancing nor reconciling ever touches the recoupment bucket — it moves only on expense approval and void. Closing then moves `RECONCILED` to `CLOSED`, terminal, after which expenses are locked against voiding.

### 3.8. Revenue Ingestion, Royalty Runs, and Artist Statements

Royalties begin with raw distributor data. A `FinanceController` ingests a revenue report with the `label_id`, `distributor_id`, and `release_id` it belongs to, a `period` in the `YYYY-Qn` format, a `channel` of `STREAMING`, `DOWNLOAD`, `PHYSICAL`, or `SYNC`, a `units` count greater than zero, a `gross_revenue_cents` greater than zero, and an optional `note`. Two checks guard ingestion, in this order: the report must be unique per label, distributor, release, period, and channel — a duplicate is rejected with `ERR_DUPLICATE_REVENUE_REPORT` — and the release's `distribution_status` must be `DELIVERED`, `LIVE`, or `TAKEN_DOWN`, otherwise `ERR_RELEASE_NOT_LIVE`. Reports are append-only per §2.5.

A `FinanceController` opens a royalty run for a label and `period`; the period must be unique per label, otherwise `ERR_RUN_PERIOD_CONFLICT`, and the run starts `OPEN`. Closing the run moves it from `OPEN` to `CLOSED` and is the precondition for calculation. Closing does not block ingestion — a report for the run's period may still be ingested afterwards and, if present when calculation runs, is picked up by the run; the snapshot semantics come from calculation reading eligibility at the moment it runs and from each report being counted at most once across runs.

Calculation moves the run from `CLOSED` to `CALCULATED` and generates statements. One `PROVISIONAL` statement is created per contract that is in `ACTIVE`, `OPTION_WINDOW`, or `EXTENDED` and has at least one eligible revenue report in the run's period; each statement records its `run_id`, `contract_id`, and the `period` copied from the run, with `recoupment_applied_cents` and `adjustment_cents` starting at zero and `dispute_note` null until a dispute. A report is eligible for a contract's statement when its release belongs to that contract, its period is lexicographically on or before the run's period, and it has not already been counted by an earlier run's statement — each report is counted at most once across runs, and a report joins the earliest run whose period is on or after the report's period.

Each statement's money is computed line by line, in a pinned order. The current-period lines — the eligible reports whose period equals the run's period — are sorted by `created_at` ascending with ties broken by `gross_revenue_cents` ascending. The walk maintains a running cumulative unit count that starts at the prior cumulative: the sum of `units` over the contract's eligible reports whose periods are strictly earlier than the run's period. Units an earlier run's statement has already counted never re-enter the walk — the prior cumulative is summed over not-yet-counted reports only — so each statement's running cumulative covers exactly the units that statement itself counts: the contract's uncounted earlier-period backlog plus the current-period lines. Each line's own `units` are added to the running cumulative before its tier is selected, and the line's tier is the last threshold in the label's `tier_thresholds` whose unit mark is strictly less than the running cumulative. For `STREAMING`, `DOWNLOAD`, and `PHYSICAL` lines, the line's rate is the contract's `effective_base_rate_bps` plus that tier's delta in basis points; `SYNC` lines ignore tiers entirely and earn a flat half of the line's net. Each line's net is its `gross_revenue_cents` multiplied by ten thousand minus the channel's `channel_deduction_bps`, divided by ten thousand, rounded half up to whole cents; each line's royalty is that net multiplied by the line rate and divided by ten thousand, again rounded half up to whole cents. Rounding happens per line and totals are sums of rounded lines — never the reverse. The statement's `gross_revenue_cents` is the sum of the current-period lines' gross, its `net_revenue_cents` the sum of the line nets, and its `royalty_earned_cents` the sum of the line royalties.

Calculation also projects recoupment without touching it. The waterfall's distributable amount is the lesser of `royalty_earned_cents` and the sum of the eligible bucket balances, and the buckets are walked in the pinned priority order — `recording_balance_cents`, then `advance_balance_cents`, then `tour_support_balance_cents`, then `promo_balance_cents` — each bucket taking the lesser of its balance and the remaining distributable amount, which in whole cents is exact and leaves no remainder. Which buckets are eligible depends on the contract's `recoupment_scope`: under `MASTER_ONLY` only the recording and advance buckets are visible to the waterfall, so the applied amount can be zero even while tour and promo balances stand positive; under `CROSS_COLLATERALIZED` all four buckets are eligible, so identical earnings recoup strictly more whenever tour or promo balances are positive and the upstream buckets have been exhausted. At calculate time the waterfall is a projection only — the would-be applied total is stored as `projected_recoupment_cents` and no bucket is mutated.

The provisional statement's payable figure then comes together in a pinned order: the remainder is `royalty_earned_cents` minus `projected_recoupment_cents`; the reserve is that remainder multiplied by the label's `reserve_rate_bps` and divided by 10,000, rounded half up to whole cents, and stored as `reserve_held_cents`; and `net_payable_cents` is the remainder minus the reserve plus `adjustment_cents`, which starts at zero. Adjustments always enter after the reserve is computed — an adjustment never changes `reserve_held_cents` — so with a positive reserve rate and a positive remainder, a provisional statement always shows a lower payable than its final counterpart.

Finalization moves the run from `CALCULATED` to `FINALIZED` in a three-link cascade. First, every statement of the run moves from `PROVISIONAL` to `FINAL`: its `reserve_held_cents` is released to zero, its recoupment switches from projection to actual with `recoupment_applied_cents` set from the waterfall result, and its `net_payable_cents` is recomputed under the final variant — `royalty_earned_cents` minus `recoupment_applied_cents` plus `adjustment_cents`. Second, each finalized statement applies the waterfall to its contract's recoupment account: the eligible bucket balances are reduced in the pinned priority order, and the account's `total_recouped_cents` grows by the applied amount. Third, any account whose `total_unrecouped_cents` has reached zero flips its `payout_status` from `RECOUPING` to `EARNING`.

Between final and payment, two human loops remain. The owning artist, through the `ArtistPortal`, may dispute a `FINAL` statement, moving it to `DISPUTED` and recording the supplied `dispute_note`; a portal caller whose identity does not own the statement's contract's artist is rejected with `ERR_ARTIST_OWNERSHIP_MISMATCH`. A `FinanceController` resolves a dispute, returning the statement from `DISPUTED` to `FINAL`. While a statement is `PROVISIONAL` or `DISPUTED`, a `FinanceController` may also post a signed manual adjustment by supplying `adjustment_delta_cents` together with `expected_royalty_statement_version` matching the statement's current `version` per §2.8 — a mismatch is `ERR_STALE_VERSION` (HTTP 412). The delta is added into `adjustment_cents`, `net_payable_cents` is recomputed within the statement's current variant, and the statement's `version` increments. On the statement list endpoint, an `ArtistPortal` caller is not rejected; the list is silently scoped to the caller's own statements before any filters are applied.

Payment is per statement: a `FinanceController` pays a `FINAL` statement, which requires the run to be `FINALIZED` (`ERR_INVALID_STATE` otherwise) and requires `net_payable_cents` to be zero or positive — a negative payable is rejected with `ERR_NEGATIVE_PAYABLE`. Paying moves the statement to `PAID`, terminal. Finally, marking the run paid moves it from `FINALIZED` to `PAID` and is allowed only when every statement of the run is already `PAID`; any holdout is rejected with `ERR_RUN_HAS_UNPAID_STATEMENTS`. `PAID` is terminal for the run.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — including every state-transition action — return `200 OK`. Executing a deal memo returns `201 Created` because it creates the contract. All endpoints are mounted under the `/api` prefix shown in the paths below, and all enforce the authentication, validation-order, and envelope rules of §2. A request whose path matches no endpoint — or matches only under a different method — is answered with the standard error envelope carrying `ERR_NOT_FOUND` (HTTP 404).

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/_clock/set_current_utc` | Set the server's logical clock (test-driving) | LabelAdmin |
| POST | `/api/labels` | Create a label with optional config overrides | LabelAdmin |
| GET | `/api/labels/{id}` | Get a label | All roles |
| POST | `/api/labels/{id}/ops/sweep` | Housekeeping sweep: memo expiry, option-window entry, contract expiry | LabelAdmin |
| POST | `/api/artists` | Create a scouted artist; scouting score computed | AnRManager |
| GET | `/api/artists/{id}` | Get an artist | All roles |
| GET | `/api/artists` | List artists with filters | LabelAdmin, AnRManager, FinanceController, MarketingManager |
| POST | `/api/artists/{id}/hiatus` | Place a SIGNED/ACTIVE artist on hiatus | AnRManager |
| POST | `/api/artists/{id}/reactivate` | Return a HIATUS artist to their pre-hiatus status | AnRManager |
| POST | `/api/artists/{id}/drop` | Drop an artist whose contracts are all terminal | LabelAdmin |
| POST | `/api/artists/{id}/deal-memos` | Draft a deal memo for the artist | AnRManager |
| GET | `/api/deal-memos/{id}` | Get a deal memo | LabelAdmin, AnRManager, ArtistPortal |
| GET | `/api/artists/{id}/deal-memos` | List an artist's deal memos | LabelAdmin, AnRManager, FinanceController, ArtistPortal |
| GET | `/api/deal-memos` | List deal memos with filters | LabelAdmin, AnRManager, FinanceController |
| POST | `/api/deal-memos/{id}/propose` | Propose a drafted memo; scouting-score gate | AnRManager |
| POST | `/api/deal-memos/{id}/counter` | Counter a memo (OCC-guarded) | AnRManager, ArtistPortal |
| POST | `/api/deal-memos/{id}/approve` | Approve a proposed or countered memo | LabelAdmin |
| POST | `/api/deal-memos/{id}/execute` | Execute an approved memo; creates contract and recoupment account | LabelAdmin |
| POST | `/api/deal-memos/{id}/reject` | Reject a memo | AnRManager |
| GET | `/api/contracts/{id}` | Get a contract | All roles |
| GET | `/api/contracts` | List contracts with filters | LabelAdmin, AnRManager, FinanceController, MarketingManager |
| POST | `/api/contracts/{id}/disburse-advance` | Fund the advance; debit the advance bucket | FinanceController |
| POST | `/api/contracts/{id}/exercise-option` | Exercise an option; extend term and escalate royalty rate | LabelAdmin |
| POST | `/api/contracts/{id}/terminate` | Terminate a contract with optional unrecouped write-off | LabelAdmin |
| GET | `/api/contracts/{id}/recoupment-accounts` | Look up a contract's recoupment account (array of 0 or 1) | LabelAdmin, AnRManager, FinanceController, ArtistPortal |
| GET | `/api/recoupment-accounts/{id}` | Get a recoupment account | LabelAdmin, AnRManager, FinanceController, ArtistPortal |
| POST | `/api/contracts/{id}/recording-projects` | Create a recording project | AnRManager |
| GET | `/api/recording-projects/{id}` | Get a recording project | All roles |
| GET | `/api/contracts/{id}/recording-projects` | List a contract's recording projects | LabelAdmin, AnRManager, FinanceController, ArtistPortal |
| POST | `/api/recording-projects/{id}/amend-budget` | Amend the project budget (OCC-guarded) | AnRManager |
| POST | `/api/recording-projects/{id}/start` | Start recording (funding gate) | AnRManager |
| POST | `/api/recording-projects/{id}/advance-stage` | Advance the project stage with milestone/track gates | AnRManager |
| POST | `/api/recording-projects/{id}/cancel` | Cancel a project; cascade non-approved milestones | AnRManager |
| POST | `/api/recording-projects/{id}/milestones` | Create a milestone | AnRManager |
| GET | `/api/milestones/{id}` | Get a milestone | LabelAdmin, AnRManager, FinanceController, ArtistPortal |
| GET | `/api/recording-projects/{id}/milestones` | List a project's milestones | LabelAdmin, AnRManager, FinanceController, ArtistPortal |
| POST | `/api/milestones/{id}/submit` | Submit (or resubmit) a milestone | AnRManager |
| POST | `/api/milestones/{id}/approve` | Approve a milestone; commits budget | LabelAdmin |
| POST | `/api/milestones/{id}/reject` | Reject a milestone | LabelAdmin |
| POST | `/api/milestones/{id}/pay` | Pay a milestone; debits budget and recording bucket | FinanceController |
| POST | `/api/recording-projects/{id}/tracks` | Create a track; ISRC unique per label | AnRManager |
| GET | `/api/tracks/{id}` | Get a track | All roles |
| GET | `/api/recording-projects/{id}/tracks` | List a project's tracks | All roles |
| GET | `/api/tracks` | List tracks with filters | LabelAdmin, AnRManager, FinanceController, MarketingManager |
| POST | `/api/tracks/{id}/advance-stage` | Advance a track one stage (clearance gate into CLEARED) | AnRManager |
| POST | `/api/tracks/{id}/block` | Block a track; cascades to releases and deliveries | AnRManager |
| POST | `/api/tracks/{id}/rework` | Return a blocked track to TRACKED | AnRManager |
| POST | `/api/contracts/{id}/releases` | Create a release bundling tracks of the contract's projects | AnRManager |
| GET | `/api/releases/{id}` | Get a release | All roles |
| GET | `/api/contracts/{id}/releases` | List a contract's releases | All roles |
| GET | `/api/recording-projects/{id}/releases` | List releases by primary project | All roles |
| POST | `/api/releases/{id}/assemble` | Assemble assets; all member tracks must be CLEARED | AnRManager |
| POST | `/api/releases/{id}/lock-assets` | Lock assets with confirmed cover art | AnRManager |
| POST | `/api/releases/{id}/schedule` | Schedule distribution; requires LOCKED assets and lead time | MarketingManager |
| POST | `/api/releases/{id}/deliveries` | Create QUEUED deliveries for the given distributors | MarketingManager |
| POST | `/api/releases/{id}/go-live` | Go live on or after the release date | MarketingManager |
| POST | `/api/releases/{id}/takedown` | Take a live release down | MarketingManager |
| POST | `/api/releases/{id}/relaunch` | Relaunch a taken-down release | MarketingManager |
| POST | `/api/releases/{id}/cancel` | Cancel a release; cascades beats, campaigns, deliveries | AnRManager, LabelAdmin |
| GET | `/api/asset-deliveries/{id}` | Get a delivery | LabelAdmin, AnRManager, MarketingManager |
| GET | `/api/releases/{id}/deliveries` | List a release's deliveries | LabelAdmin, AnRManager, MarketingManager |
| GET | `/api/asset-deliveries` | List deliveries with filters | LabelAdmin, AnRManager, MarketingManager |
| POST | `/api/asset-deliveries/{id}/transmit` | Transmit a queued delivery | MarketingManager |
| POST | `/api/asset-deliveries/{id}/acknowledge` | Acknowledge a delivery; may bubble release to DELIVERED | MarketingManager |
| POST | `/api/asset-deliveries/{id}/reject` | Reject a transmitted delivery | MarketingManager |
| POST | `/api/asset-deliveries/{id}/retry` | Retry a rejected delivery | MarketingManager |
| POST | `/api/distributors` | Create a distributor | LabelAdmin |
| GET | `/api/distributors/{id}` | Get a distributor | LabelAdmin, AnRManager, FinanceController, MarketingManager |
| GET | `/api/distributors` | List distributors | LabelAdmin, AnRManager, FinanceController, MarketingManager |
| PATCH | `/api/distributors/{id}` | Update a distributor's is_active flag | LabelAdmin |
| POST | `/api/releases/{id}/beats` | Plan a marketing beat; window bounds plus half-open overlap | MarketingManager |
| GET | `/api/beats/{id}` | Get a beat | LabelAdmin, AnRManager, MarketingManager |
| GET | `/api/releases/{id}/beats` | List a release's beats | LabelAdmin, AnRManager, MarketingManager, ArtistPortal |
| POST | `/api/beats/{id}/ready` | Mark a beat ready | MarketingManager |
| POST | `/api/beats/{id}/execute` | Execute a ready beat | MarketingManager |
| POST | `/api/beats/{id}/measure` | Measure an executed beat with outcome metrics | MarketingManager |
| POST | `/api/beats/{id}/skip` | Skip a planned or ready beat | MarketingManager |
| POST | `/api/releases/{id}/promo-campaigns` | Create a promo campaign; closed-interval gap rule | MarketingManager |
| GET | `/api/promo-campaigns/{id}` | Get a campaign | LabelAdmin, AnRManager, MarketingManager |
| GET | `/api/releases/{id}/promo-campaigns` | List a release's campaigns | LabelAdmin, AnRManager, MarketingManager, ArtistPortal |
| POST | `/api/promo-campaigns/{id}/activate` | Activate a campaign; release must be scheduled or beyond | MarketingManager |
| POST | `/api/promo-campaigns/{id}/pause` | Pause an active campaign | MarketingManager |
| POST | `/api/promo-campaigns/{id}/resume` | Resume a paused campaign | MarketingManager |
| POST | `/api/promo-campaigns/{id}/complete` | Complete a campaign | MarketingManager |
| POST | `/api/promo-campaigns/{id}/kill` | Kill a campaign | MarketingManager |
| POST | `/api/promo-campaigns/{id}/spend` | Record spend against an ACTIVE campaign | MarketingManager |
| POST | `/api/contracts/{id}/tour-supports` | Propose tour support | AnRManager |
| GET | `/api/tour-supports/{id}` | Get a tour support | LabelAdmin, AnRManager, FinanceController, ArtistPortal |
| GET | `/api/contracts/{id}/tour-supports` | List a contract's tour supports | LabelAdmin, AnRManager, FinanceController, ArtistPortal |
| POST | `/api/tour-supports/{id}/approve` | Approve a tour support with a budget | LabelAdmin |
| POST | `/api/tour-supports/{id}/decline` | Decline a tour support | LabelAdmin |
| POST | `/api/tour-supports/{id}/advance-funds` | Advance funds; segregation of duties vs approver | FinanceController |
| POST | `/api/tour-supports/{id}/reconcile` | Reconcile; computes unspent returned amount | FinanceController |
| POST | `/api/tour-supports/{id}/close` | Close a reconciled tour support; locks expenses | FinanceController |
| POST | `/api/tour-supports/{id}/cancel` | Cancel an approved tour support before funding | AnRManager |
| POST | `/api/tour-supports/{id}/expenses` | Submit a tour expense (artist portal, own tours) | ArtistPortal |
| GET | `/api/tour-expenses/{id}` | Get a tour expense | LabelAdmin, AnRManager, FinanceController, ArtistPortal |
| GET | `/api/tour-supports/{id}/expenses` | List a tour's expenses | LabelAdmin, AnRManager, FinanceController, ArtistPortal |
| POST | `/api/tour-expenses/{id}/approve` | Approve an expense; category and total caps; debits tour bucket | FinanceController |
| POST | `/api/tour-expenses/{id}/reject` | Reject an expense | FinanceController |
| POST | `/api/tour-expenses/{id}/void` | Void an approved expense; compensating credit | FinanceController |
| POST | `/api/revenue-reports` | Ingest an append-only distributor revenue line | FinanceController |
| GET | `/api/revenue-reports/{id}` | Get a revenue report | LabelAdmin, AnRManager, FinanceController |
| GET | `/api/revenue-reports` | List revenue reports with filters | LabelAdmin, AnRManager, FinanceController |
| POST | `/api/royalty-runs` | Open a royalty run for a period (unique per label) | FinanceController |
| GET | `/api/royalty-runs/{id}` | Get a royalty run | LabelAdmin, FinanceController |
| GET | `/api/royalty-runs` | List royalty runs | LabelAdmin, FinanceController |
| POST | `/api/royalty-runs/{id}/close` | Close a run; freezes revenue intake | FinanceController |
| POST | `/api/royalty-runs/{id}/calculate` | Calculate; generates PROVISIONAL statements (projection only) | FinanceController |
| POST | `/api/royalty-runs/{id}/finalize` | Finalize; statements to FINAL, waterfall applied, payout flips | FinanceController |
| POST | `/api/royalty-runs/{id}/mark-paid` | Mark the run paid; every statement must be PAID | FinanceController |
| GET | `/api/royalty-runs/{id}/statements` | List a run's statements | LabelAdmin, FinanceController |
| GET | `/api/royalty-statements/{id}` | Get a statement (artist portal reads own) | LabelAdmin, FinanceController, ArtistPortal |
| GET | `/api/royalty-statements` | List statements with filters | LabelAdmin, FinanceController, ArtistPortal |
| POST | `/api/royalty-statements/{id}/dispute` | Dispute a FINAL statement (owning artist) | ArtistPortal |
| POST | `/api/royalty-statements/{id}/adjust` | Post a signed adjustment (OCC-guarded) | FinanceController |
| POST | `/api/royalty-statements/{id}/resolve-dispute` | Resolve a disputed statement back to FINAL | FinanceController |
| POST | `/api/royalty-statements/{id}/pay` | Pay a FINAL statement | FinanceController |

## 5. Error Code Catalogue

The following table enumerates every error identifier the API can return together with its HTTP status code. The conditions that trigger each error are described in the narrative of §2 and §3 rather than repeated here.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_ARTIST_OWNERSHIP_MISMATCH` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_GUARDIAN_CONSENT_REQUIRED` | 422 Unprocessable Entity |
| `ERR_SAMPLE_CLEARANCE_MISSING` | 422 Unprocessable Entity |
| `ERR_DEAL_MEMO_ALREADY_OPEN` | 409 Conflict |
| `ERR_SCOUTING_SCORE_TOO_LOW` | 422 Unprocessable Entity |
| `ERR_DEAL_MEMO_EXPIRED` | 422 Unprocessable Entity |
| `ERR_ADVANCE_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_RENEGOTIATION_IN_PROGRESS` | 409 Conflict |
| `ERR_OPTION_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_UNRECOUPED_BALANCE` | 422 Unprocessable Entity |
| `ERR_CONTRACT_NOT_FUNDED` | 409 Conflict |
| `ERR_ARTIST_NOT_SIGNABLE` | 409 Conflict |
| `ERR_PROJECT_BUDGET_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_BUDGET_BELOW_SPEND` | 422 Unprocessable Entity |
| `ERR_MILESTONE_SEQUENCE_CONFLICT` | 409 Conflict |
| `ERR_ISRC_CONFLICT` | 409 Conflict |
| `ERR_SINGLE_TRACK_COUNT` | 422 Unprocessable Entity |
| `ERR_TRACKS_NOT_CLEARED` | 422 Unprocessable Entity |
| `ERR_COVER_ART_MISSING` | 422 Unprocessable Entity |
| `ERR_ASSETS_NOT_LOCKED` | 409 Conflict |
| `ERR_RELEASE_LEAD_TIME` | 422 Unprocessable Entity |
| `ERR_DISTRIBUTOR_INACTIVE` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_DELIVERY` | 409 Conflict |
| `ERR_RELEASE_DATE_NOT_REACHED` | 422 Unprocessable Entity |
| `ERR_BEAT_OUTSIDE_WINDOW` | 422 Unprocessable Entity |
| `ERR_BEAT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_CAMPAIGN_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_CAMPAIGN_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_APPROVED_EXCEEDS_REQUESTED` | 422 Unprocessable Entity |
| `ERR_CATEGORY_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_TOUR_BUDGET_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_SEGREGATION_OF_DUTIES` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_REVENUE_REPORT` | 409 Conflict |
| `ERR_RELEASE_NOT_LIVE` | 422 Unprocessable Entity |
| `ERR_RUN_PERIOD_CONFLICT` | 409 Conflict |
| `ERR_RUN_HAS_UNPAID_STATEMENTS` | 409 Conflict |
| `ERR_NEGATIVE_PAYABLE` | 422 Unprocessable Entity |
