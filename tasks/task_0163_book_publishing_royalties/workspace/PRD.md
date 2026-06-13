# Book Publishing Royalties API — Product Requirements Document

## 1. Introduction

This document specifies the Book Publishing Royalties API, the system of record a publishing house uses to track contracts, manage the catalogue of titles and formats, and settle what it owes to authors and their agents. Royalty accounting in trade publishing is deceptively intricate: a single book earns at an escalating rate as cumulative sales climb through contractual tiers, a portion of every period's earnings is withheld against the very real possibility that bookstores will return unsold stock, advances must be recouped before any cash flows, foreign, audio, and film rights add income outside the unit-sales channel, and agents take a commission on whatever ultimately reaches the author. The house must be able to reconstruct every cent on any statement it has ever issued.

The API models this domain as a ledger-reconciliation engine. Publishers register authors and agents, draft contracts with their tier schedules and reserve policy, open accounting periods, post raw sales and returns, and then generate, finalize, and pay statements. Authors and agents are first-class but read-only participants: each can inspect the contracts, statements, and ledger lines that concern them, but only the publishing house performs the posting and accounting work. Because finalizing one period mutates contract-level balances that the next period's math depends upon, the system treats the contract as a concurrency-controlled aggregate root and rejects any settlement computed against a baseline another writer has already superseded.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that govern every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which they act. The system recognizes exactly three roles, spelled precisely as `Publisher`, `Author`, and `Agent`. A request that omits either header, or supplies an `X-User-Role` that is not one of these three, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not permitted to perform the requested operation — or an entity-backed principal reaching for a resource it does not own — is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The `Publisher` role is the publishing-house operator. Its identity is opaque: when `X-User-Role` is `Publisher`, `X-User-ID` is an operator identifier not tied to any persisted entity. The server does not compare it to any entity's `id`; the Publisher may act on every contract and all of its children. The Publisher exclusively performs all mutating work — registering authors and agents, creating and activating and terminating contracts, defining royalty tiers, titles, formats, sales periods, sales records, and subsidiary rights, publishing and retiring titles, closing periods, voiding rights, and generating, finalizing, and paying statements.

The `Author` and `Agent` roles are entity-backed observers with scoped read-only rights. When `X-User-Role` is `Author`, `X-User-ID` is the `id` of the acting `Author`; ownership checks compare a contract's `author_id` foreign key to `X-User-ID`, and an `Author` may read a contract, its children, and the statements and statement lines beneath it only when that contract's `author_id` equals `X-User-ID`, plus its own author record where the `Author.id` equals `X-User-ID`. When `X-User-Role` is `Agent`, `X-User-ID` is the `id` of the acting `Agent`; ownership checks compare a contract's `agent_id` foreign key to `X-User-ID`, and an `Agent` may read a contract, its children, and the statements and lines thereon only when that contract's `agent_id` equals `X-User-ID`, plus its own agent record where the `Agent.id` equals `X-User-ID`. Neither `Author` nor `Agent` may perform any posting, accounting, or lifecycle operation; such attempts are rejected with `ERR_UNAUTHORIZED`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and accepted values range from a minimum of 1 to a maximum of 100. The `offset` parameter is the number of items to skip from the front of the result set and defaults to 0.

Unless an endpoint states otherwise, every list is sorted by each resource's creation timestamp, `created_at`, in ascending order. Each list response carries `limit`, `offset`, `total_count`, and `has_more` inside the envelope's `meta` object, where `total_count` reports the size of the full unpaginated set and `has_more` indicates whether further pages remain.

### 2.4. Common Resource Properties

Every primary resource — `Author`, `Agent`, `Contract`, `Title`, `Format`, `SalesPeriod`, `SalesRecord`, `ReturnsReserve`, `SubsidiaryRight`, and `AuthorStatement` — carries a system-managed `id` formatted as a UUID with no type prefix, a `created_at` timestamp (ISO 8601 UTC with three fractional digits) fixed at creation, an `updated_at` timestamp in the same format refreshed on every mutation, and an integer `version` that begins at 1 and increments by one each time the resource is mutated.

Two entities are deliberately lighter. A `RoyaltyTier` and a `StatementLine` are immutable once created: each carries only an `id` and a `created_at`, and neither bears an `updated_at` nor a `version`. A `StatementLine` in particular is never updated after the finalize or pay event that emits it; it is a permanent ledger artifact.

### 2.5. Hierarchical Consistency and Automatic Propagation

Several operations mutate more than one resource at once, and the system performs these cascades atomically so that no client ever observes a half-applied settlement. When a parent's state change forces a child's state — retiring a title drives its formats out of service, finalizing a statement liquidates eligible reserves, statements its subsidiary rights, and advances its sales period — the dependent resources are transitioned by the server itself, without a separate client request against each one. Any resource the server mutates as part of such a cascade has its `updated_at` refreshed and, where it carries a `version`, its `version` incremented. The contract specifically is the aggregate whose `version` advances on activate, terminate, statement finalize, and statement pay; downstream subsections describe each of these in its business context.

### 2.6. Nested Resource Retrieval and Referential Validation

Many paths address a resource through one or more ancestor identifiers. The system validates every identifier in a path strictly left to right, and the first one that does not resolve to an existing resource fails the request with `ERR_NOT_FOUND` (HTTP 404) before any deeper check runs. After path identifiers, the same not-found rule applies to foreign keys named in the request body, again checked in order. Beyond mere existence, the system enforces referential coherence across the contract boundary: a sales record's `format_id` must name a format whose owning title belongs to the same contract as the sales record's period, since cross-contract sales are nonsensical; a violation is rejected with `ERR_CROSS_CONTRACT_REFERENCE` (HTTP 422).

### 2.7. Monetary Precision, Rounding, and the Cents Convention

All money in the system is expressed as an integer number of cents — `advance_cents`, `list_price_cents`, `proceeds_cents`, and every computed monetary field — so that no floating-point drift can creep into a ledger. Where a calculation multiplies a cents amount by a fractional rate or splits a value, the result is rounded to a whole number of cents using the round-half-up method (a value exactly halfway between two integers rounds to the larger magnitude toward positive infinity for the positive amounts at play here). Fractional rate inputs such as `agent_commission_pct`, `reserve_pct`, `author_share_pct`, `tax_withholding_pct`, and a tier's `rate` are stored at the precision supplied. One field is intentionally exempt from per-step rounding: a reserve's `reserve_unit_value_cents` is retained at full precision and is only rounded when it is multiplied out at consumption time, as the reserve-liquidation rules below detail.

### 2.8. Numeric Range Constraints

Inputs that carry a declared range are validated on write, and a value outside its range is rejected with `ERR_VALIDATION_RANGE` (HTTP 422). Every percentage field must lie within the closed interval from 0 to 1 inclusive: `tax_withholding_pct`, `agent_commission_pct`, `reserve_pct`, and `author_share_pct` — although a tier's `rate` is stricter, requiring a value greater than 0 and at most 1, and a subsidiary right's `author_share_pct` likewise must be greater than 0 and at most 1. A contract's `advance_cents` must be zero or greater. A format's `list_price_cents` must be strictly greater than 0. A subsidiary right's `proceeds_cents` must be strictly greater than 0. A title's `edition` must be at least 1. A tier's `lower_unit` must be at least 1, and its `upper_unit`, when present, must be greater than or equal to its `lower_unit`. A contract's `reserve_hold_periods` must be at least 1, and a sales period's `sequence` must be at least 1. Units posted on a sales record — `units_sold` and `units_returned` — must each be zero or greater.

### 2.9. Optimistic Concurrency Control on the Contract Aggregate

Two settlement operations are guarded by optimistic concurrency control against the contract, because both read and then mutate contract-level balances that another writer may have moved in between. When a statement is finalized, the request must carry an `expected_contract_version` field equal to the owning contract's current `version`; if a different statement for an earlier period was finalized after this client last read the contract — legitimately changing `unrecouped_advance_cents` and `lifetime_net_units` — the contract's `version` will have advanced, and the finalize is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412) because its recoupment and tier math were computed against a superseded baseline. Likewise, when a statement is paid, the request must carry an `expected_contract_version` equal to the contract's current `version`; a pay request whose supplied version is older than the live one — capturing the case where another statement finalized against the same contract after this client read it — is rejected with the same `ERR_STALE_CONTRACT_VERSION` (HTTP 412). The `expected_contract_version` field is mandatory on both of these operations and is not accepted on any other endpoint.

### 2.10. Validation Ordering and Priority

When several checks could fail a single request, the system evaluates them in a fixed priority so that the returned error is deterministic. Authentication comes first: missing or unknown headers yield `ERR_UNAUTHENTICATED`. Authorization is next: a recognized but unpermitted role, or an entity-backed principal reaching past its ownership, yields `ERR_UNAUTHORIZED`. Resource existence follows: any unresolved path identifier or body foreign key yields `ERR_NOT_FOUND`. Request well-formedness comes after that: a missing or malformed body, an absent required field, a wrong type, or an enum value outside its allowed set yields `ERR_INVALID_REQUEST` (HTTP 422), and a numeric input outside its declared range yields `ERR_VALIDATION_RANGE` (HTTP 422). Only once a request is authenticated, authorized, resolved, and well-formed does the system apply domain rules — uniqueness, commission-without-agent, tier coverage, sequence uniqueness, state legality, cross-contract referential checks, period-open and sequence-ordering rules, statement-existence, settled-right immutability, open-liability, and finally the contract-version OCC check — each described in the workflow it guards. Where a domain conflict and the OCC check could both apply, the state and business conflicts are surfaced ahead of the stale-version rejection.

## 3. Business Logic & Workflows

### 3.1. Parties, Contracts, and the Tier Escalator

Everything begins with the parties. A `Publisher` registers an `Author` by supplying a `full_name`, a contact `email`, and optionally a `tax_withholding_pct`; the withholding fraction defaults to 0 when omitted and represents the share of an author's net payable that is held back for taxes at payment time. An `Agent` is registered with an `agency_name` and an `email`. Author and agent emails must each be unique within their own population; registering a second author or agent with an `email` already on file is rejected with `ERR_DUPLICATE_EMAIL` (HTTP 409).

With the parties on file, the Publisher drafts a `Contract`. The create payload names the authoring party through `author_id`, optionally a representing `agent_id` (which defaults to absent for unagented deals), the `advance_cents` paid against future earnings, and the contract's policy knobs: `agent_commission_pct` (the fraction of net payable the agent takes, defaulting to 0), `reserve_pct` (the fraction of each period's gross royalty withheld against returns, defaulting to 0.25), and `reserve_hold_periods` (how many finalized periods a reserve sits before it may be liquidated, defaulting to 2). A contract is born in `DRAFT` status. Its `unrecouped_advance_cents` and `lifetime_net_units` are computed, house-managed balances: at creation `unrecouped_advance_cents` mirrors the supplied `advance_cents` and `lifetime_net_units` is 0. If a contract names no agent yet carries a non-zero `agent_commission_pct`, the create is rejected with `ERR_COMMISSION_WITHOUT_AGENT` (HTTP 422); the same coupling is re-checked at activation.

A contract's earning schedule lives in its `RoyaltyTier` children, each added to a still-`DRAFT` contract with a `lower_unit`, an optional `upper_unit`, and a `rate`. Tiers describe the escalator over cumulative net units across the life of the contract: the `lower_unit` is the inclusive 1-based cumulative-unit index at which a tier begins, the `upper_unit` is the inclusive index at which it ends (absent meaning the open-ended top tier), and the `rate` is the royalty fraction of list price earned by units that fall in that band. Tiers belong to the contract and apply across all of its titles.

Activation is the gate that turns a draft into a live accounting entity. When the Publisher activates a contract, transitioning its `status` from `DRAFT` to `ACTIVE`, the system requires that the contract carry at least one royalty tier, that those tiers form a contiguous cover beginning at `lower_unit` equal to 1 with exactly one open-ended top tier (the one whose `upper_unit` is absent) and no gaps or overlaps between consecutive tiers, that the contract have at least one title bearing at least one format, and — once more — that `agent_commission_pct` be 0 whenever no `agent_id` is set. Two tiers overlap when their inclusive `[lower_unit, upper_unit]` ranges intersect; adjacency is required, meaning each tier's `upper_unit` plus one must equal the next tier's `lower_unit`, which is correct coverage rather than overlap. A tier schedule that is not a gapless, non-overlapping cover from 1 with exactly one open top tier is rejected with `ERR_TIER_COVERAGE_INVALID` (HTTP 422); a missing-agent-but-nonzero-commission contract is rejected at activation with `ERR_COMMISSION_WITHOUT_AGENT`; and a contract lacking tiers, a title, or a format is rejected with `ERR_CONTRACT_NOT_READY` (HTTP 409). On success, activation sets `status` to `ACTIVE`, re-establishes `unrecouped_advance_cents` as `advance_cents`, and advances the contract's `version` by one.

Termination is the contract's only other lifecycle move and is terminal. The Publisher may terminate an `ACTIVE` contract — transitioning `status` from `ACTIVE` to `TERMINATED` and advancing the contract's `version` by one — but only when the contract has no open financial liabilities: no `SalesPeriod` may sit in `CLOSED` status (every period must be `OPEN` or `STATEMENTED`), no `AuthorStatement` may be in `DRAFT` or `FINALIZED` status (all must be `PAID`, or none exist), and no `ReturnsReserve` may still be `HELD`. A termination attempt against a contract with held reserves or unpaid statements is rejected with `ERR_OPEN_LIABILITIES` (HTTP 409). Once `TERMINATED`, the contract blocks all further posting. Any lifecycle transition requested against a resource not in the permitting state — finalizing a non-`DRAFT` statement, paying a non-`FINALIZED` statement, voiding a non-`REGISTERED` right, and the like — is rejected with `ERR_INVALID_STATE` (HTTP 409) where a more specific code does not govern.

### 3.2. The Catalogue: Titles and Formats

Inside an active contract the Publisher builds the catalogue. A `Title` is created under a contract with a `name` and an optional `edition` number that defaults to 1, and it enters the world in `DRAFT` `status`. Each title in turn holds one or more `Format` children, every format created under its owning title (recorded as `title_id`) with a `format_type` — one of `HARDCOVER`, `PAPERBACK`, `EBOOK`, or `AUDIO` — and a `list_price_cents` against which its royalty rate is applied. A new format is `active` by default, meaning it may receive sales records.

Publishing a title moves it from `DRAFT` to `PUBLISHED`. The Publisher may publish a title only while its owning contract is `ACTIVE` and only when the title already has at least one format; a title with zero formats cannot be published and the attempt is rejected with `ERR_TITLE_HAS_NO_FORMAT` (HTTP 409). Retiring a title moves it from `PUBLISHED` to the terminal `OUT_OF_PRINT` state, again permitted only while the owning contract is `ACTIVE`. Retirement cascades downward: every `Format` of the retired title has its `active` flag set to false, so no further sales records may be posted against those formats. `OUT_OF_PRINT` is terminal for a title.

### 3.3. Accounting Periods and Posting Sales

Sales are accumulated inside accounting periods. The Publisher opens a `SalesPeriod` on a contract with a human `label` such as a half-year tag and a `sequence`, the monotonic ordering index within the contract; periods are processed and statemented in ascending `sequence`. A period opens in `OPEN` `status`. The `sequence` must be unique within the owning contract: opening a period whose `sequence` already occupies a point on the contract's timeline is a zero-width collision rejected with `ERR_DUPLICATE_PERIOD_SEQUENCE` (HTTP 409) — distinct from the range-overlap semantics that govern tiers.

Into an open period the Publisher posts `SalesRecord` rows. Each record names the `format_id` whose units it reports and carries `units_sold` and `units_returned`, both defaulting to 0. A record may be posted only into a period that is `OPEN` and whose owning contract is `ACTIVE`, and only against a format that is still `active`; a record aimed at a non-open period, an inactive format, or a non-active contract is rejected with `ERR_PERIOD_NOT_OPEN` (HTTP 409). As noted in the referential rules, the named `format_id` must resolve under the same contract as the period, or the post is rejected with `ERR_CROSS_CONTRACT_REFERENCE`.

A period's net units are the heart of every downstream figure: summed across all of the period's sales records, the net is each record's `units_sold` minus its `units_returned`, totalled. Returns count regardless of whether the underlying format is still active. A period's net is used as-is and may even be negative when returns exceed sales — a credit-reversal period that legitimately reduces gross royalty rather than being floored at zero.

Closing a period is the precondition for statementing it. The Publisher closes an `OPEN` period — transitioning its `status` from `OPEN` to `CLOSED` — only while the owning contract is `ACTIVE` and only when every lower-`sequence` period of the same contract is already `STATEMENTED`; closing a period while an earlier-`sequence` sibling has not yet been statemented violates the ascending-sequence rule and is rejected with `ERR_PERIOD_SEQUENCE_VIOLATION` (HTTP 409). Once a period is `CLOSED`, no further sales records may be posted into it. A period's final transition, from `CLOSED` to the terminal `STATEMENTED`, is not a direct operation but a consequence of finalizing the statement that reports on it, described below.

### 3.4. Subsidiary Rights

Apart from unit sales, a book earns through subsidiary rights — the sale of foreign-language, audio, or film rights. The Publisher registers a `SubsidiaryRight` on a contract with a `right_type` of `FOREIGN`, `AUDIO`, or `FILM`, the gross `proceeds_cents` received, and the `author_share_pct` — the fraction of those proceeds credited to the author, with the publisher keeping the remainder. At registration the system computes the author's credit, `author_income_cents`, as the gross `proceeds_cents` multiplied by `author_share_pct`, rounded half up to whole cents. A right is born `REGISTERED`, with its `statement_id` link absent until it is credited.

A `REGISTERED` right that never closed — a deal that fell through — may be voided by the Publisher, moving its `status` to `VOID`. Once a right is `VOID`, its `author_income_cents` is excluded from every future statement, so the would-be credit simply never posts. A right that has already been carried onto a statement, however, is settled income and immutable: attempting to void a `STATEMENTED` (or already `VOID`) right is rejected with `ERR_RIGHT_ALREADY_SETTLED` (HTTP 409). The other path a right can take — from `REGISTERED` to the terminal `STATEMENTED` — happens automatically when a statement finalize credits it, as the reconciliation workflow describes.

### 3.5. Generating a Provisional Statement

When a period is closed, the Publisher generates its `AuthorStatement`, which is created in `DRAFT` against that period. Generation is allowed only when the `SalesPeriod` is `CLOSED` and no statement already exists for that period; a second generate against a period that already has a statement is rejected with `ERR_STATEMENT_EXISTS` (HTTP 409). The statement records the `contract_id` it settles and the `period_id` it primarily reports on.

A draft statement is a forward-looking estimate, computed but not committed. At generation the system computes a provisional `gross_royalty_cents` by running the tier escalator (detailed in §3.7) using the contract's current `lifetime_net_units` as the cumulative baseline, derives the provisional `reserve_held_cents` and `royalty_credited_cents`, identifies the `HELD` reserves whose hold has matured and sums their candidate release into a provisional `reserve_released_cents`, identifies the `REGISTERED` subsidiary rights on the contract and sums their candidate `subsidiary_income_cents`, and rolls those into provisional `period_earnings_cents`, `advance_recouped_cents`, `payable_before_commission_cents`, `agent_commission_cents`, and `net_to_author_cents`. These draft figures are explicitly provisional: nothing is committed, no reserve flips, no right is stamped, and the numbers are recomputed against live state when the statement is finalized. Should returns be posted or another statement finalize between generate and finalize, the committed figures may differ from this provisional snapshot.

### 3.6. Finalizing and Paying a Statement — the Reconciliation Heart

Finalization is where provisional becomes committed and where the bulk of the system's cascades fire. The Publisher finalizes a `DRAFT` statement, transitioning its `status` from `DRAFT` to `FINALIZED`, and the request must carry an `expected_contract_version` matching the contract's live `version` (the stale-version rejection of §2.9 applies). Finalization is permitted only when the statement is `DRAFT` and its owning `SalesPeriod` is `CLOSED`.

On finalize, the system recomputes every monetary field against live state — this committed variant is canonical and supersedes the draft snapshot — and then performs an ordered set of cascades, atomically:

- It debits the contract's `unrecouped_advance_cents` by this statement's `advance_recouped_cents`, keeping the recoupment ledger in sync.
- It increments the contract's `lifetime_net_units` by this period's net units, which resets the tier baseline for the next period.
- It liquidates every `HELD` `ReturnsReserve` whose hold has matured — those whose `eligible_sequence` is less than or equal to this finalizing period's `sequence` — transitioning each from `HELD` to `LIQUIDATED`, setting its `released_cents` and `consumed_cents`, and adding the released portion into this statement's `reserve_released_cents` (the cascade: statement finalize drives reserve liquidation, which credits the author).
- It transitions each credited `SubsidiaryRight` from `REGISTERED` to `STATEMENTED` and stamps its `statement_id` with this statement's `id`.
- It creates a new `ReturnsReserve` in `HELD`, sized at this period's withheld `reserve_held_cents`.
- It transitions the owning `SalesPeriod` from `CLOSED` to `STATEMENTED`, bubbling up from the statement's finalize.
- It emits the immutable `StatementLine` rows, one per non-zero ledger component.
- It advances the contract's `version` by one.

Each of those reserve, right, and period mutations refreshes its own `updated_at` and, where applicable, `version`, per §2.5. Because finalizing this statement bumps the contract's `version`, any sibling statement whose finalize or pay was prepared against the older contract version will be caught by the OCC check and must be re-read — this is the intended serialization point across a contract's periods.

Payment is the terminal step and the only point at which tax is applied. The Publisher pays a `FINALIZED` statement, transitioning its `status` from `FINALIZED` to `PAID`, with the request again carrying an `expected_contract_version` matching the contract's live `version`. On payment the system computes `tax_withheld_cents` as the author-facing amount — `payable_before_commission_cents` minus `agent_commission_cents` — multiplied by the author's `tax_withholding_pct`, rounded half up to whole cents, then recomputes `net_to_author_cents` as `payable_before_commission_cents` minus `agent_commission_cents` minus `tax_withheld_cents`. It emits the `TAX_WITHHELD` and final `NET_PAYABLE` `StatementLine` rows and advances the contract's `version` by one. Before payment, `tax_withheld_cents` carries its default of 0.

The immutable ledger lines a statement emits are `StatementLine` rows, each bearing the `statement_id` it belongs to, a `line_type`, a signed `amount_cents` (credits positive, deductions negative), and a `memo` snapshotted at the moment it is written. The `line_type` is one of `ROYALTY`, `RESERVE_WITHHELD`, `RESERVE_RELEASED`, `SUBSIDIARY`, `ADVANCE_RECOUP`, `AGENT_COMMISSION`, `TAX_WITHHELD`, or `NET_PAYABLE`; the first six categories are emitted at finalize for every non-zero component, while `TAX_WITHHELD` and the final `NET_PAYABLE` are emitted at pay.

### 3.7. The Tiered Royalty Escalator

A period's gross royalty is earned by walking its net units through the contract's tier escalator, beginning from where the contract's cumulative sales already stand. The cumulative baseline, the count of units already earned across prior finalized periods, is the contract's `lifetime_net_units`; it reflects finalized periods only, so draft or closed siblings never contribute to it. Tiers are processed in ascending `lower_unit` order. Starting at a running position equal to the cumulative baseline and a remaining quantity equal to the period's net units, the escalator considers each tier in turn: it skips to the next tier once the remaining quantity has been exhausted; for the current tier it determines the segment available between the running position (or the tier's start, whichever is further along) and the tier's inclusive top (or, for the open-ended top tier, as far as the remaining quantity reaches); it takes from that tier the smaller of the remaining quantity and the segment's width; it values those taken units at the per-unit royalty for that tier — the tier's `rate` times the relevant list price — and accumulates that segment's value rounded half up to whole cents into `gross_royalty_cents`; then it reduces the remaining quantity and advances the running position by the units taken. Rounding happens once per tier segment and the rounded segment subtotals are summed; this segment-level rounding order is the pinned, canonical order.

When a period carries units across multiple formats with different `list_price_cents`, the gross royalty is computed per format and then summed: each format's units run the escalator against the same shared cumulative-baseline window, formats taken in ascending order of their `created_at`, each format's subtotal rounded to whole cents, and only then are the per-format subtotals added together. This per-format-then-sum order is canonical and can legitimately differ by a cent from the alternative of summing raw values and rounding once; the summing-then-rounding-once interpretation is the wrong one.

### 3.8. Returns Reserve Sizing and Liquidation

The reserve mechanism protects the house against paying royalties on books that later come back. At the finalize of each statement, alongside crediting the period's royalty, the system withholds a reserve and creates a fresh `ReturnsReserve` in `HELD` against the contract, linking it to the originating statement through `origin_statement_id`. That reserve's sizing is computed from the finalizing period: its `reserve_units` is the period's net units multiplied by the contract's `reserve_pct`, rounded half up to a whole number (and may be 0); its `reserve_held_cents` is the period's `gross_royalty_cents` multiplied by the contract's `reserve_pct`, rounded half up to whole cents; and its per-unit liquidation value, `reserve_unit_value_cents`, is `reserve_held_cents` divided by `reserve_units` when `reserve_units` is greater than 0 and otherwise 0, kept at full precision and not rounded at this stage. The reserve also records the `eligible_sequence` at or after which it may be liquidated, computed as the origin period's `sequence` plus the contract's `reserve_hold_periods`.

A held reserve is liquidated automatically during a later statement's finalize, specifically when that finalizing period's `sequence` is greater than or equal to the reserve's `eligible_sequence` and the reserve is still `HELD`, transitioning it from `HELD` to `LIQUIDATED`. Liquidation reconciles the withheld money against the returns that actually materialized. The actual returns charged against a reserve's cohort are the sum of `units_returned` over every sales record across the same contract whose period `sequence` is strictly greater than the reserve's origin period `sequence` and less than or equal to the finalizing period's `sequence` — a half-open window opening just after origin and closing at the finalizing period — with records ordered by period `sequence` ascending and then `created_at` ascending for determinism. The system charges the smaller of those actual return units and the reserve's `reserve_units`, sets `consumed_cents` to that charged count multiplied by the reserve's full-precision `reserve_unit_value_cents` rounded half up to whole cents, and sets `released_cents` to `reserve_held_cents` minus `consumed_cents`. Because released equals held minus consumed exactly, the reserve is conserved to the cent. The released portion flows up as a credit into the finalizing statement's `reserve_released_cents`.

The same liquidation arithmetic is run provisionally at generate time, but using only returns observed up to the closed period and without committing anything — reserves stay `HELD` and no money moves. At finalize the computation is redone against live sales records and actually flips the eligible reserves to `LIQUIDATED`, crediting their `released_cents` to the statement; the committed result diverges from the provisional one whenever returns were posted between generate and finalize.

### 3.9. Statement Reconciliation: the Settlement Waterfall

Bringing the pieces together, a statement settles in a fixed waterfall whose evaluation order is pinned. First, `royalty_credited_cents` is `gross_royalty_cents` minus the period's `reserve_held_cents` — the royalty earned this period less the fresh reserve withheld from it. Second, `reserve_released_cents` is the sum of `released_cents` over the reserves liquidated into this statement. Third, `subsidiary_income_cents` is the sum of `author_income_cents` over the subsidiary rights credited on this statement, where each right's `author_income_cents` is its `proceeds_cents` times `author_share_pct` rounded half up; voided rights contribute nothing. Fourth, the period's earnings, `period_earnings_cents`, is the sum of `royalty_credited_cents`, `reserve_released_cents`, and `subsidiary_income_cents`.

The waterfall then allocates those earnings. The first bucket recoups the advance: `advance_recouped_cents` is the smaller of `period_earnings_cents` and the contract's `unrecouped_advance_cents` read at finalize time, never negative. What remains after recoupment, `payable_before_commission_cents`, is `period_earnings_cents` minus `advance_recouped_cents`. The second bucket takes the agent's commission: `agent_commission_cents` is `payable_before_commission_cents` multiplied by the contract's `agent_commission_pct`, rounded half up to whole cents. The commission base is deliberately the post-recoupment `payable_before_commission_cents`, not the pre-recoupment `period_earnings_cents` — commissioning the gross earnings would overpay the agent whenever an advance is being recouped, and the canonical base is the net-payable figure. Tax is not taken here; it is applied only at payment, where `tax_withheld_cents` is `payable_before_commission_cents` minus `agent_commission_cents`, multiplied by the author's `tax_withholding_pct`, rounded half up. Finally, `net_to_author_cents` is `payable_before_commission_cents` minus `agent_commission_cents` minus `tax_withheld_cents`. Every figure is in integer cents, and the evaluation order — royalty, then reserve released, then subsidiary, then earnings, then recoupment, then commission, then (at pay) tax, then net — is fixed.

### 3.10. Read Access and Reverse Lookups

Beyond the posting workflows, the system exposes broad read access scoped by the ownership rules of §2.1. A `Publisher`, `Author`, or `Agent` (each within their own scope) can fetch any individual resource and can traverse a contract's children — its royalty tiers, titles, formats, sales periods, subsidiary rights, statements, and reserves — as well as walk from a statement to its reserves, its credited subsidiary rights, and its immutable lines. Sales records can be listed within their period or fetched individually, and can also be filtered by `format_id` across the catalogue. Subsidiary-right and statement and reserve listings accept an optional `status` filter, statement-line listings accept an optional `line_type` filter, and sales-record listings accept an optional `format_id` filter; the author- and agent-list endpoints accept an optional `email` filter and the contract list an optional pair of `author_id` and `agent_id` filters. All such lists honor the pagination and sort rules of §2.3.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — including all lifecycle transitions such as activate, terminate, publish, retire, close, void, finalize, and pay — return `200 OK`. Request and response bodies, side effects, and validation rules are not repeated here; reconstruct them from the §3 narratives and the global rules of §2.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/authors` | Register an author | Publisher |
| GET | `/authors/{id}` | Fetch an author | Publisher, Author |
| GET | `/authors` | List authors (paginated) | Publisher |
| POST | `/agents` | Register an agent | Publisher |
| GET | `/agents/{id}` | Fetch an agent | Publisher, Agent |
| GET | `/agents` | List agents (paginated) | Publisher |
| POST | `/contracts` | Create a contract in DRAFT | Publisher |
| GET | `/contracts/{id}` | Fetch a contract incl. computed balances and version | Publisher, Author, Agent |
| GET | `/contracts` | List contracts (filterable by author_id / agent_id) | Publisher, Author, Agent |
| POST | `/contracts/{id}/activate` | Activate a DRAFT contract | Publisher |
| POST | `/contracts/{id}/terminate` | Terminate an ACTIVE contract | Publisher |
| POST | `/contracts/{id}/royalty-tiers` | Add a royalty escalator tier to a DRAFT contract | Publisher |
| GET | `/contracts/{id}/royalty-tiers` | List a contract's royalty tiers | Publisher, Author, Agent |
| POST | `/contracts/{id}/titles` | Create a Title under a contract | Publisher |
| GET | `/contracts/{id}/titles` | List a contract's titles | Publisher, Author, Agent |
| GET | `/titles/{id}` | Fetch a title | Publisher, Author, Agent |
| POST | `/titles/{id}/publish` | Publish a DRAFT title | Publisher |
| POST | `/titles/{id}/retire` | Retire a PUBLISHED title to OUT_OF_PRINT | Publisher |
| POST | `/titles/{id}/formats` | Add a Format to a Title | Publisher |
| GET | `/titles/{id}/formats` | List a title's formats | Publisher, Author, Agent |
| POST | `/contracts/{id}/sales-periods` | Open a new sales period on a contract | Publisher |
| GET | `/contracts/{id}/sales-periods` | List a contract's sales periods | Publisher, Author, Agent |
| GET | `/sales-periods/{id}` | Fetch a sales period | Publisher, Author, Agent |
| POST | `/sales-periods/{id}/close` | Close an OPEN sales period | Publisher |
| POST | `/sales-periods/{id}/sales-records` | Post a sales record into an OPEN period | Publisher |
| GET | `/sales-periods/{id}/sales-records` | List sales records in a period | Publisher, Author, Agent |
| GET | `/sales-records` | Filtered list of sales records by format_id | Publisher, Author, Agent |
| GET | `/sales-records/{id}` | Fetch a single sales record | Publisher, Author, Agent |
| POST | `/contracts/{id}/subsidiary-rights` | Register a subsidiary right sale | Publisher |
| GET | `/contracts/{id}/subsidiary-rights` | List a contract's subsidiary rights | Publisher, Author, Agent |
| GET | `/subsidiary-rights/{id}` | Fetch a subsidiary right | Publisher, Author, Agent |
| POST | `/subsidiary-rights/{id}/void` | Void a REGISTERED subsidiary right | Publisher |
| POST | `/sales-periods/{id}/generate-statement` | Generate a provisional DRAFT statement for a CLOSED period | Publisher |
| GET | `/statements/{id}` | Fetch a statement with all computed monetary fields | Publisher, Author, Agent |
| GET | `/sales-periods/{id}/statement` | The statement for a period (array of 0–1) | Publisher, Author, Agent |
| GET | `/contracts/{id}/statements` | List a contract's statements | Publisher, Author, Agent |
| POST | `/statements/{id}/finalize` | Finalize a DRAFT statement | Publisher |
| POST | `/statements/{id}/pay` | Pay a FINALIZED statement | Publisher |
| GET | `/statements/{id}/lines` | List immutable StatementLines for a statement | Publisher, Author, Agent |
| GET | `/contracts/{id}/reserves` | List a contract's returns reserves | Publisher, Author, Agent |
| GET | `/reserves/{id}` | Fetch a returns reserve | Publisher, Author, Agent |
| GET | `/statements/{id}/reserves` | List reserves originating from a statement | Publisher, Author, Agent |
| GET | `/statements/{id}/subsidiary-rights` | List subsidiary rights credited on a statement | Publisher, Author, Agent |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_DUPLICATE_EMAIL` | 409 |
| `ERR_COMMISSION_WITHOUT_AGENT` | 422 |
| `ERR_TIER_COVERAGE_INVALID` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CROSS_CONTRACT_REFERENCE` | 422 |
| `ERR_PERIOD_NOT_OPEN` | 409 |
| `ERR_PERIOD_SEQUENCE_VIOLATION` | 409 |
| `ERR_STATEMENT_EXISTS` | 409 |
| `ERR_RIGHT_ALREADY_SETTLED` | 409 |
| `ERR_OPEN_LIABILITIES` | 409 |
| `ERR_STALE_CONTRACT_VERSION` | 412 |
| `ERR_DUPLICATE_PERIOD_SEQUENCE` | 409 |
| `ERR_VALIDATION_RANGE` | 422 |
| `ERR_TITLE_HAS_NO_FORMAT` | 409 |
| `ERR_CONTRACT_NOT_READY` | 409 |
