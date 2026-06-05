# Music Royalty Licensing API — Product Requirements Document

## 1. Introduction

The music industry splits the economic value of a song across two distinct layers of ownership: the underlying composition (held by writers and publishers) and the master recording (held by labels and other parties). The same play of a track therefore generates obligations in several directions at once — a performing-rights organization (PRO) such as ASCAP or BMI collects performance money for the composition, statutory mechanical rates accrue for streaming and physical reproductions, and one-off synchronization deals license a master into film, television, advertising, or video games. This API exists to model that fragmented reality as a single coherent ledger, so that every dollar of reported usage can be traced from the moment it is ingested through to the moment a payee is paid.

At the heart of the system are two reconciliation problems that recur constantly in royalty accounting. The first is **advance recoupment**: rightsholders are frequently paid a lump sum up front and must "earn it back" before they see further money, so the platform must continuously track gross earnings against an outstanding recouped balance. The second is **provisional-versus-final accounting**: a royalty figure that appears on a usage event the moment it is allocated is only an estimate until the rightsholder's statement for that period is finalized, at which point the same numbers become authoritative and flow into lifetime totals. Layered on top of these are a multi-dimensional sync pricing engine and a strict regime of territory-and-term rights windows that gate whether any exploitation is even permitted.

This document specifies the complete contract for the platform: the entities and their fields, the state machines that govern licensing and settlement, the calculation rules for performance, mechanical, and sync royalties, the validation order that protects the ledger, and the role-based permissions that separate catalog administration, royalty operations, licensees, and payees.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply across every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. The `X-User-ID` header identifies the acting user, and the `X-User-Role` header declares the operational capacity under which they are acting. If either header is missing or malformed, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are present but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly four roles, spelled precisely as follows: `Administrator`, `RoyaltyOperator`, `Licensee`, and `Rightsholder`.

An `Administrator` manages the catalog and the parties: creating rightsholders and suspending them, registering works and locking their composition shares, registering recordings and locking their master shares, adding composition and recording shares, granting and revoking rights windows, and issuing or writing off advances. A `RoyaltyOperator` runs the royalty machinery: ingesting and allocating usage, quoting and executing sync licenses, opening, finalizing, and reopening statements, and creating, settling, and reversing payouts.

The `Administrator` and `RoyaltyOperator` roles are operator identities. When `X-User-Role` is `Administrator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. When `X-User-Role` is `RoyaltyOperator`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity and is never compared to an entity `id`.

The `Licensee` and `Rightsholder` roles are entity-backed. When `X-User-Role` is `Licensee`, `X-User-ID` is the `id` of the acting `Rightsholder` (a party of `party_type` `LABEL` acting as the requesting licensee); ownership checks on any sync license compare that license's `licensee_id` field to `X-User-ID`. When `X-User-Role` is `Rightsholder`, `X-User-ID` is the `id` of the acting `Rightsholder`; ownership checks on any resource that references a `Rightsholder` — the rightsholder record itself, its statements, its ledger reads, its advances, and its payouts — compare the resource's `rightsholder_id` to `X-User-ID`. When an entity-backed actor targets a resource they do not own, the request is rejected with `ERR_NOT_RESOURCE_OWNER`.

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, may be no smaller than 1, and may be no larger than 100. The `offset` parameter sets the number of items to skip and defaults to 0.

Unless an endpoint states otherwise, every list response is sorted by the resource creation timestamp in ascending order.

List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

Most resources in the system carry a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, set when the resource is first created. The `updated_at` field is an ISO 8601 UTC timestamp, refreshed on every modification to the resource. The `version` field is an integer that begins at its initial value and increments by one with every mutation; it is the basis for optimistic concurrency control described in §2.7.

The `Rightsholder`, `Work`, `CompositionShare`, `Recording`, `RecordingShare`, `RightsWindow`, `UsageEvent`, `SyncLicense`, `Advance`, `Statement`, and `Payout` entities all carry the full set: `id`, `created_at`, `updated_at`, and `version`. The `LedgerEntry` entity is the lone exception: it is an append-only audit row that carries only `id` and `created_at`. A `LedgerEntry` has no `updated_at` and no `version`, because once written it is never modified in place — corrections happen by appending or removing rows, never by editing them.

### 2.5. Cascading Reconciliation and Derived Fields

Several operations in this system touch more than one entity in a single atomic action, and the downstream effects must be applied consistently. Whenever a usage allocation or a sync execution writes earning rows, every affected statement has its gross recomputed and its version advanced as part of the same action. Whenever a statement is finalized or reopened, the affected advances and the owning rightsholder's derived totals are recomputed in lockstep. Each entity that is mutated as part of such a cascade has its own `updated_at` refreshed and its own `version` incremented; a cascade is never silent.

A number of fields are **derived** and are never supplied by the client. On a `Work`, the `split_total_bps` is the sum of all `split_bps` across that work's composition shares, expressed in basis points where 10000 equals 100 percent. On a `Recording`, `split_total_bps` is the analogous sum across that recording's master shares. On a `Rightsholder`, `lifetime_earned_cents` is the sum of all `EARNING` ledger amounts across that rightsholder's finalized statements, and `unrecouped_balance_cents` is the sum, over that rightsholder's `ACTIVE` advances, of each advance's `principal_cents` minus its `recouped_cents`, with the total floored at 0. On a `UsageEvent`, `royalty_cents` and `allocated_holder_count` are computed at allocation time. On an `Advance`, `recouped_cents` accumulates as statements finalize. On a `Statement`, `gross_earnings_cents`, `recoupment_applied_cents`, `withholding_cents`, `net_payable_cents`, and `carried_forward_cents` are all computed by the system. On a `Payout`, `amount_cents` is captured at creation. None of these may be set directly by a request body.

### 2.6. Monetary Precision and Rounding

All monetary amounts are stored and returned as integer cents. Wherever a calculation produces a fractional cent, the result is rounded using the round-half-up method to a whole number of cents. The calculation rules in §3 specify exactly where each rounding boundary falls — most notably, that a royalty pool total is rounded once before it is split among holders, and that each per-holder allocation is then rounded once more. Implementers must respect these rounding boundaries precisely, because rounding a sum and summing rounded parts can diverge by a cent.

### 2.7. Optimistic Concurrency Control on Statements

Two statement operations are guarded by optimistic concurrency control, and both use the same input field, `expected_statement_version`, which is a required (non-optional) field on those requests.

When finalizing a statement, the request must carry `expected_statement_version` equal to the target statement's current `version`. A prior writer may have allocated additional usage into the same `DRAFT` statement — bumping its `version` through the gross recompute — after the client last read it, so the finalizing client's view of the statement total can be stale. If `expected_statement_version` does not match the statement's current `version`, the finalize is rejected with `ERR_STALE_VERSION` and an HTTP status of 412, rather than locking in an out-of-date gross.

When reopening a statement, the request must likewise carry `expected_statement_version` equal to the statement's current `version`. A statement that was just paid moves from `FINALIZED` to `PAID` and bumps its `version`; a client that read the statement before that move holds a stale version. If `expected_statement_version` does not match the statement's current `version`, the reopen is rejected with `ERR_STALE_VERSION` and HTTP 412, so that a stale actor cannot unwind a statement whose downstream state has already moved on. No other endpoint accepts or requires a version field.

### 2.8. Existence, Foreign Keys, and Validation Ordering

The system evaluates requests through a fixed, priority-ordered chain of checks, and the order matters because an earlier failure masks a later one. The chain is as follows.

Authentication comes first: the `X-User-Role` and `X-User-ID` headers must be present and well-formed, or the request fails with `ERR_UNAUTHENTICATED`. Authorization is second: the acting role must be permitted for the operation per the access-control rules, or the request fails with `ERR_UNAUTHORIZED`. Third, every resource named in the URL path must exist; identifiers are checked left to right, and the first one that does not resolve yields `ERR_NOT_FOUND`. Fourth, every foreign key in the request body — `recording_id`, `work_id`, `rightsholder_id`, `licensee_id`, and `statement_id` — must resolve to an existing entity, or the request fails with `ERR_FK_NOT_FOUND`. Fifth, the body must be well-formed: required fields present, enum values in range, and integers within their declared bounds (composition and recording `split_bps` between 1 and 10000 inclusive, `quantity` at least 1, `term_months` at least 1, and `withholding_pct` between 0 and 0.30 inclusive); a violation yields `ERR_INVALID_REQUEST`. Sixth, for an action endpoint, the target resource must currently be in a state from which the requested transition is defined, or the request fails with `ERR_INVALID_STATE`. Seventh, where ownership is required, the entity-backed actor must own the targeted resource (a `Licensee` must match the sync license's `licensee_id`; a `Rightsholder` must match the rightsholder on their own ledger or statement), or the request fails with `ERR_NOT_RESOURCE_OWNER`.

Beyond this generic prefix, each operation layers on its own business checks in the priority order given throughout §3 — uniqueness of codes, share-total constraints, share-lock state, rights availability, open-statement requirements, interval overlaps, unallocated-usage guards, concurrency, payout existence, suspension, and payability. Where multiple of these apply to one endpoint, they are evaluated in ascending priority so that the structurally earliest violation is the one reported.

## 3. Business Logic & Workflows

### 3.1. Parties, Catalog Registration, and Share Locking

Everything begins with the **rightsholder** — the party who ultimately gets paid. An `Administrator` creates a rightsholder by supplying a `legal_name`, a `party_type` of `WRITER`, `PUBLISHER`, or `LABEL`, and a `payee_country` given as an ISO 3166-1 alpha-2 code such as US, GB, or DE. Two optional inputs tune payout behavior: `minimum_payout_cents`, which defaults to 5000 and must be at least 0, sets the threshold below which a period's net is carried forward rather than paid; and `withholding_pct`, which defaults to 0 and must lie between 0 and 0.30 inclusive, sets the foreign-tax rate applied at finalize. A newly created rightsholder starts with `status` of `ACTIVE`, `lifetime_earned_cents` of 0, and `unrecouped_balance_cents` of 0. An `Administrator` may later suspend a rightsholder, moving its `status` to `SUSPENDED`; a suspended rightsholder cannot be paid. Reading a rightsholder returns its computed ledger fields alongside its inputs.

A **work** is the underlying composition. An `Administrator` registers one with a `title`, an `iswc` (the International Standard Musical Work Code, which must be unique across all works), a `pro_affiliation` of `ASCAP`, `BMI`, or `NONE` identifying the PRO that collects its performance money, and a `duration_seconds` running time that must be greater than 0. On creation the work has `shares_locked` of false and `split_total_bps` of 0. Attempting to register a work whose `iswc` already exists is rejected with `ERR_DUPLICATE_CODE`.

Composition ownership is expressed through **composition shares**. An `Administrator` adds one by naming the `work_id` it belongs to, the `rightsholder_id` of the writer or publisher who holds it, a `role` of `WRITER` or `PUBLISHER`, and a `split_bps` ownership stake in basis points between 1 and 10000 inclusive. Each addition recomputes the parent work's `split_total_bps`. If the new share would push that total above 10000 basis points, it is rejected with `ERR_SPLIT_TOTAL_INVALID`. Once a work's shares are locked, no further composition share may be added; such an attempt is rejected with `ERR_SHARES_LOCKED`. Locking happens through registration: an `Administrator` registers a work to lock its splits, which is permitted only when `split_total_bps` equals exactly 10000 (and otherwise rejected with `ERR_SPLIT_TOTAL_INVALID`). Registration sets `shares_locked` to true and increments the work's version.

A **recording** is the master embodiment of a work. An `Administrator` registers one by naming the `work_id` it embodies, an `isrc` (the International Standard Recording Code, unique across all recordings), a `title`, a `release_type` of `STREAMING` or `PHYSICAL` that drives the mechanical rate basis, and a `duration_seconds` running time greater than 0 that drives the mechanical penny-rate for long recordings. A new recording has `shares_locked` of false. A duplicate `isrc` is rejected with `ERR_DUPLICATE_CODE`, and a missing `work_id` with `ERR_FK_NOT_FOUND`. Master ownership is expressed through **recording shares**, each naming a `recording_id`, a `rightsholder_id` (the label or party holding the master stake), and a `split_bps` between 1 and 10000 inclusive. As with compositions, each share recomputes the recording's `split_total_bps`, an addition exceeding 10000 basis points is rejected with `ERR_SPLIT_TOTAL_INVALID`, and an addition after locking is rejected with `ERR_SHARES_LOCKED`. The recording's shares are locked by an `Administrator` only when `split_total_bps` equals exactly 10000 (otherwise `ERR_SPLIT_TOTAL_INVALID`), which sets `shares_locked` to true and increments the recording's version. The four share-and-lock operations — adding a composition share, adding a recording share, registering a work, and locking a recording's shares — all enforce the share-total constraint, and the two add operations additionally enforce the locked-parent constraint.

### 3.2. Territory and Term Rights Windows

Before any exploitation can be allocated, the platform must know that the relevant rights are held. An `Administrator` grants a **rights window** on a recording by naming the `recording_id`, a `territory` (an ISO 3166-1 alpha-2 code, or `WW` for worldwide), a `rights_type` of `SYNC`, `MECHANICAL`, or `PERFORMANCE` identifying which exploitation it authorizes, and the term boundaries `term_start` and `term_end`. The term is a half-open interval: `term_start` is the inclusive UTC start and `term_end` is the exclusive UTC end, so an instant exactly at `term_end` falls outside the window. A new window begins with `status` of `ACTIVE`, and an `Administrator` may later revoke it, moving `status` to `REVOKED` and incrementing its version.

Windows of the same `rights_type` on the same recording-and-territory may not overlap an existing `ACTIVE` window, but the overlap arithmetic differs by type. For `SYNC` windows, a strict one-day cooldown buffer of 86400 seconds is required between windows: the new window's `term_start` must be at or after the existing window's `term_end` plus 86400 seconds, or else the new window's `term_end` plus 86400 seconds must be at or before the existing window's `term_start`. For `MECHANICAL` and `PERFORMANCE` windows, plain half-open non-overlap applies with no buffer, so two windows that merely touch at a boundary — where the new window's `term_start` equals the existing window's `term_end` — are allowed, while any interior overlap is rejected. A colliding window is rejected with `ERR_WINDOW_OVERLAP`, and a missing `recording_id` with `ERR_FK_NOT_FOUND`.

### 3.3. Ingesting and Allocating Usage

Reported plays and reproductions enter the system as **usage events**. A `RoyaltyOperator` ingests one by naming the `recording_id` that was exploited, a `usage_type` of `PERFORMANCE` or `MECHANICAL`, the `territory` where the usage occurred, the `occurred_at` UTC instant, a `quantity` stream/spin/unit count of at least 1, and — for performance usage — a `gross_revenue_cents` figure of at least 0 reported by the source. The `gross_revenue_cents` value is ignored for mechanical usage, where the statutory rate is used instead. A freshly ingested event has `status` of `INGESTED`, `royalty_cents` of 0, and `allocated_holder_count` of 0. A missing `recording_id` is rejected with `ERR_FK_NOT_FOUND`. An operator may **void** a usage event that is still `INGESTED`, moving its `status` to `VOIDED`; once an event has been allocated onto a statement it can no longer be voided, and a void attempt on a non-`INGESTED` event is rejected with `ERR_INVALID_STATE`.

The pivotal operation is **allocation**, which advances a usage event from `INGESTED` to `ALLOCATED` and distributes its money. Allocation is permitted only when the event is `INGESTED` (otherwise `ERR_INVALID_STATE`). It further requires that both the recording's parent `Work` has `shares_locked` true and the `Recording` itself has `shares_locked` true; if either is unlocked the allocation is rejected with `ERR_SHARES_NOT_LOCKED`. It requires an `ACTIVE` rights window on that recording whose `rights_type` matches the usage's licensing class — performance usage requires a `PERFORMANCE` window, mechanical usage a `MECHANICAL` window — whose territory covers the event's `territory`, and whose term covers `occurred_at`; absent such a window the allocation is rejected with `ERR_RIGHTS_NOT_AVAILABLE`. Finally, every holder who is to receive money must have a `DRAFT` statement whose half-open `[period_start, period_end)` period contains `occurred_at`; if any target holder lacks such a statement the allocation fails with `ERR_NO_OPEN_STATEMENT` and nothing at all is written.

When those conditions hold, the system computes `royalty_cents` for the event — through the performance pool rule for `PERFORMANCE` usage and the mechanical statutory rule for `MECHANICAL` usage, both detailed in §3.7. It then distributes that money. For performance usage, the pool is split across the work's composition share holders by their `split_bps`; for mechanical usage, it is split across the recording's master share holders by their `split_bps`. One `EARNING` ledger entry is created per holder, with `entry_type` of `EARNING`, `source_type` of `USAGE_EVENT`, and `source_id` set to this usage event's `id`, and is attached to that holder's open `DRAFT` statement for the period. Each affected statement then has its `gross_earnings_cents` recomputed from its `EARNING` entries and its `version` incremented. The event's `allocated_holder_count` is set to the number of distinct holders that received an entry, and its `status` becomes `ALLOCATED`.

### 3.4. Sync Licensing and the Negotiation Loop

A **sync license** is a one-off deal to synchronize a master into visual media. A `RoyaltyOperator` opens one by naming the `recording_id` to be synchronized, the `licensee_id` of the requesting party (a `LABEL`-typed rightsholder acting as licensee), a `media_type` of `FILM`, `TV`, `AD`, or `GAME`, a requested `territory` (alpha-2 or `WW`), a requested `term_months` term length of at least 1, and an operator-proposed `base_fee_cents` of at least 0. On creation the system computes the `quoted_fee_cents` via the sync pricing rule in §3.7, sets `status` to `DRAFT`, and leaves `counter_fee_cents` at its default of 0. A missing `recording_id` or `licensee_id` is rejected with `ERR_FK_NOT_FOUND`.

The negotiation can loop. From `DRAFT`, the owning `Licensee` may **counter** the quote by supplying a `counter_fee_cents` of at least 1, which is recorded on the license and moves it from `DRAFT` to `COUNTERED`; the version increments. Countering requires the license be in `DRAFT` (else `ERR_INVALID_STATE`), the acting licensee to own it (else `ERR_NOT_RESOURCE_OWNER`), and a counter fee of at least 1 (else `ERR_INVALID_REQUEST`). From `COUNTERED`, a `RoyaltyOperator` may **requote** by supplying a fresh `base_fee_cents`, which resets the base fee, recomputes `quoted_fee_cents` through the same sync pricing rule, and returns the license from `COUNTERED` to `DRAFT`, incrementing the version — this is the negotiation loop. Requoting requires the license be `COUNTERED` (else `ERR_INVALID_STATE`).

Acceptance has two parallel branches that must be treated with equal care. The owning `Licensee` may **accept** a license that is in `DRAFT`; this requires `DRAFT` status (else `ERR_INVALID_STATE`), licensee ownership (else `ERR_NOT_RESOURCE_OWNER`), and an `ACTIVE` `SYNC` rights window on the recording whose territory covers the license's `territory` (else `ERR_RIGHTS_NOT_AVAILABLE`). It moves the license from `DRAFT` to `ACCEPTED` and increments the version. Symmetrically, a `RoyaltyOperator` may **accept** a license that is in `COUNTERED`; this requires `COUNTERED` status (else `ERR_INVALID_STATE`) and an `ACTIVE` `SYNC` window covering the territory (else `ERR_RIGHTS_NOT_AVAILABLE`). On this branch the operator is accepting the licensee's counter, so `quoted_fee_cents` is set to the recorded `counter_fee_cents`, the license moves from `COUNTERED` to `ACCEPTED`, and the version increments.

A `RoyaltyOperator` may **decline** a license that is in either `DRAFT` or `COUNTERED` status, moving it to `DECLINED` (a terminal state) and incrementing the version; a decline from any other state is rejected with `ERR_INVALID_STATE`.

The final step is **execution**, performed by a `RoyaltyOperator` on an `ACCEPTED` license, moving it from `ACCEPTED` to `EXECUTED` (terminal). Execution requires `ACCEPTED` status (else `ERR_INVALID_STATE`); it requires that the recording's parent `Work` has `shares_locked` true and the `Recording` has `shares_locked` true (else `ERR_SHARES_NOT_LOCKED`); and it requires that every master share holder has a `DRAFT` statement whose half-open `[period_start, period_end)` contains the server clock's current UTC instant (else `ERR_NO_OPEN_STATEMENT`). On execution, the agreed `quoted_fee_cents` is distributed to the recording's master share holders: one `EARNING` ledger entry per holder, with `entry_type` `EARNING`, `source_type` `SYNC_LICENSE`, and `source_id` set to this license's `id`, each holder's amount being the pool times that holder's `split_bps` divided by 10000 and rounded half up. The pool total `quoted_fee_cents` was rounded once at quote time, and each per-holder allocation is rounded once here. Each holder's entry attaches to that holder's open `DRAFT` statement; each affected statement has its `gross_earnings_cents` recomputed and its `version` incremented. The license's own version also increments.

### 3.5. Advances and Recoupment

An **advance** is money paid to a rightsholder up front, to be earned back out of future royalties. An `Administrator` issues one by naming the `rightsholder_id` recipient and a `principal_cents` of at least 1, with an optional `recoupment_pct` — the fraction of each period's gross withheld toward recoupment — that defaults to 1.0 and must be greater than 0 and at most 1.0. A new advance has `status` of `ACTIVE` and `recouped_cents` of 0, and issuing it recomputes the recipient's `unrecouped_balance_cents`. A missing `rightsholder_id` is rejected with `ERR_FK_NOT_FOUND`.

An advance is recouped automatically as the rightsholder's statements finalize (see §3.6); when an advance's `recouped_cents` reaches its `principal_cents` after a finalize cascade, the system transitions it from `ACTIVE` to `RECOUPED`. An `Administrator` may instead **write off** an `ACTIVE` advance, forgiving the remaining unrecouped principal: this moves it from `ACTIVE` to `WRITTEN_OFF` and recomputes the recipient's `unrecouped_balance_cents`, which excludes written-off advances. A write-off is permitted only from `ACTIVE` (else `ERR_INVALID_STATE`). A `RECOUPED` advance can return to `ACTIVE` automatically when a statement reopen reverses recoupment and drops its `recouped_cents` below its `principal_cents`.

### 3.6. The Statement Settlement Cycle

A **statement** settles a single rightsholder over a single period. A `RoyaltyOperator` opens one by naming the `rightsholder_id` it settles together with the `period_start` (inclusive UTC) and `period_end` (exclusive UTC) of the half-open royalty period. A new statement has `status` of `DRAFT` and all computed totals at 0. A missing rightsholder is rejected with `ERR_FK_NOT_FOUND`. A new statement's `[period_start, period_end)` must not overlap any existing non-`PAID` statement (one whose status is `DRAFT` or `FINALIZED`) for the same rightsholder; this uses plain half-open overlap with no buffer, so two periods that merely touch at a boundary — where the new `period_start` equals an existing `period_end` — are allowed, while any interior overlap is rejected with `ERR_STATEMENT_PERIOD_OVERLAP`. (This boundary-touching rule deliberately differs from the buffered arithmetic that governs `SYNC` rights windows.)

**Finalizing** a statement is the central settlement action, performed by a `RoyaltyOperator`, moving it from `DRAFT` to `FINALIZED`. It requires `DRAFT` status (else `ERR_INVALID_STATE`); it requires `expected_statement_version` to match the statement's current `version` per §2.7 (else `ERR_STALE_VERSION`, HTTP 412); and it requires that the rightsholder have no `INGESTED` (unallocated) usage event whose `occurred_at` falls inside `[period_start, period_end)` and whose distribution targets this rightsholder (else `ERR_UNALLOCATED_USAGE_IN_PERIOD`). When these hold, the finalize runs a chained cascade. First it computes `recoupment_applied_cents` by recouping this period's gross against the rightsholder's `ACTIVE` advances (the recoupment rule of §3.7). Each touched advance has its `recouped_cents` increased, and any advance whose `recouped_cents` reaches its `principal_cents` transitions to `RECOUPED`. A `RECOUPMENT` ledger entry (with `source_type` `ADVANCE`) is appended for each advance touched, and `recoupment_applied_cents` is recomputed. The system then computes `withholding_cents` as the gross earnings minus the recoupment applied, multiplied by the rightsholder's `withholding_pct`, rounded half up, and appends a `WITHHOLDING` ledger entry (with `source_type` `STATEMENT`). It computes `net_payable_cents` as the gross earnings minus recoupment applied minus withholding, floored at 0. As the deeper cascade, the rightsholder's `lifetime_earned_cents` is recomputed (the sum of `EARNING` entries over `FINALIZED` statements) and `unrecouped_balance_cents` is recomputed from `ACTIVE` advances. Finally, if `net_payable_cents` is below the rightsholder's `minimum_payout_cents`, that amount is moved into `carried_forward_cents` and `net_payable_cents` is set to 0; the statement's `status` becomes `FINALIZED` and its `version` increments. This is the moment at which provisional earnings become final: the same `EARNING` entries that were merely estimates while the statement was `DRAFT` now count toward `lifetime_earned_cents`.

**Reopening** a `FINALIZED` statement, performed by a `RoyaltyOperator`, returns it from `FINALIZED` to `DRAFT` and compensates every finalize side effect. It requires `FINALIZED` status (else `ERR_INVALID_STATE`); it requires that no `SETTLED` payout reference the statement (else `ERR_PAYOUT_EXISTS`); and it requires `expected_statement_version` to match the statement's current `version` per §2.7 (else `ERR_STALE_VERSION`, HTTP 412). On reopen, each `RECOUPMENT` ledger entry for this statement is reversed: the corresponding advance's `recouped_cents` is decreased by the reversed amount, and a `RECOUPED` advance whose `recouped_cents` drops below its `principal_cents` reverts to `ACTIVE`. The `WITHHOLDING` ledger entry is removed, and `recoupment_applied_cents`, `withholding_cents`, `net_payable_cents`, and `carried_forward_cents` are all reset to 0. The rightsholder's `lifetime_earned_cents` and `unrecouped_balance_cents` are recomputed. The statement's `status` becomes `DRAFT` and its `version` increments — closing the reopen cycle.

Every earning, recoupment, and withholding movement is recorded as a **ledger entry**, an append-only audit row. Each entry carries a `statement_id` linking it to the statement it rolls up into (the authoritative link; the payee is reached through that statement's `rightsholder_id`), a denormalized `rightsholder_id` copied from the parent statement for fast reads (equal to the statement's `rightsholder_id`, not an independent foreign key), an `entry_type` of `EARNING`, `RECOUPMENT`, or `WITHHOLDING` that fixes the sign and meaning of the amount, a `source_type` of `USAGE_EVENT`, `SYNC_LICENSE`, `ADVANCE`, or `STATEMENT` identifying the polymorphic source kind, a `source_id` holding the id of that source row, and an `amount_cents` carried as signed cents — positive for `EARNING`, negative for `RECOUPMENT` and `WITHHOLDING`. The ledger for a statement can be listed and filtered by `entry_type`.

### 3.7. Royalty and Pricing Calculations

**Performance pool royalty.** When a `PERFORMANCE` usage event is allocated, its royalty is computed from a PRO pool keyed on the composition's affiliation and weighted by its duration. The per-PRO rate, expressed in cents per stream-minute, is 12 for `ASCAP`, 11 for `BMI`, and 0 for `NONE`; a work whose `pro_affiliation` is `NONE` therefore earns no performance royalty at all. A duration weight is taken as the work's `duration_seconds` divided by a 180-second (three-minute) baseline, but capped at a maximum of 3.0 so that very long works do not run away. The raw pool is then the event's `gross_revenue_cents` multiplied by a pool share of 0.50, plus the event's `quantity` multiplied by the per-PRO rate multiplied by the duration weight. That raw pool is rounded half up exactly once to produce the event's `royalty_cents`. Only after the pool total is rounded is it distributed: each composition share holder receives the pool total multiplied by that holder's `split_bps` divided by 10000, rounded half up once more per holder. The rounding order is fixed — round the pool first, then round each per-holder allocation — and must not be collapsed into a single rounding.

**Mechanical statutory royalty.** When a `MECHANICAL` usage event is allocated, its royalty is computed from a per-unit penny rate that depends on the recording's length. If the recording's `duration_seconds` is at most 300 (five minutes), the rate is the baseline of 12 cents per unit. If `duration_seconds` is greater than 300, the recording enters the long-song tier: the rate is the larger of the 12-cent baseline and 2 cents multiplied by the number of started minutes, where started minutes is the `duration_seconds` divided by 60 and rounded up to the next whole minute. The basis then depends on the recording's `release_type`: for a `PHYSICAL` release the `royalty_cents` is the rate multiplied by `quantity`, rounded half up; for a `STREAMING` release it is the rate multiplied by `quantity` multiplied by a stream factor of 0.01 (streams pay one percent of the physical penny rate per stream), rounded half up. As with performance, this pool total is rounded once, and only then distributed to the recording's master share holders, each receiving the pool total multiplied by that holder's `split_bps` divided by 10000, rounded half up once per holder.

**Sync quote fee.** When a sync license is created or requoted, its `quoted_fee_cents` is computed from the operator's `base_fee_cents` scaled by three multipliers in a pinned evaluation order, because the territory multiplier depends on a subtotal that media scaling produces. First, the media multiplier is selected from the `media_type`: 2.0 for `FILM`, 1.5 for `TV`, 3.0 for `AD`, and 1.25 for `GAME`. The subtotal is `base_fee_cents` multiplied by that media multiplier, with no rounding yet. Second, the territory multiplier is selected: if the `territory` is `WW` it is a flat 2.5 regardless of the subtotal; otherwise, for a single territory, it is 1.0 when the subtotal is at least 500000 cents (large deals carry no surcharge) and 1.2 when the subtotal is below 500000 cents (small deals carry a surcharge). Third, the term multiplier is selected from `term_months`: 1.6 when the term is at least 36 months, 1.3 when it is at least 12 but fewer than 36 months, and 1.0 when it is fewer than 12 months. The `quoted_fee_cents` is the subtotal multiplied by the territory multiplier multiplied by the term multiplier, rounded half up exactly once over the full product.

**Advance recoupment.** When a statement is finalized, this period's gross is recouped against the rightsholder's `ACTIVE` advances, oldest first — that is, in ascending order of each advance's `created_at`, never by id. A running remaining-gross figure starts at the statement's `gross_earnings_cents`, and a running recoupment-applied figure starts at 0. Each advance is processed in turn: its outstanding amount is its `principal_cents` minus its `recouped_cents`, and an advance with nothing outstanding is skipped. The eligible share that this advance may take is the current remaining gross multiplied by that advance's `recoupment_pct`, rounded down (floored) to whole cents, which guarantees total recoupment never exceeds gross. The amount actually taken is the smaller of the outstanding amount and the eligible share; that amount is added to the advance's `recouped_cents` and to the running recoupment applied, and is subtracted from the remaining gross so that later advances see a reduced gross. When the remaining gross fully absorbs all outstanding principal, every touched advance reaches `RECOUPED`; when outstanding principal exceeds the eligible gross, advances stay `ACTIVE` with `recouped_cents` below `principal_cents` and the remainder rolls into future periods. The statement's `recoupment_applied_cents` is the final running total.

### 3.8. Payouts and Settlement

A **payout** disburses a finalized statement's net to the payee. A `RoyaltyOperator` creates one by naming the `statement_id` of the `FINALIZED` statement being paid (the authoritative link; the payee is reached through that statement's `rightsholder_id`). Creating the payout requires that the referenced statement be `FINALIZED` (else `ERR_INVALID_STATE`), that the rightsholder's `status` be `ACTIVE` (else `ERR_RIGHTSHOLDER_SUSPENDED`), and that the statement's `net_payable_cents` be at least 1 (else `ERR_NOTHING_PAYABLE`). The payout is created with `amount_cents` equal to the statement's `net_payable_cents` at the moment of payout and a `status` of `PENDING`, and it carries a denormalized `rightsholder_id` copied from the paid statement (equal to the statement's `rightsholder_id`, not an independent foreign key). Creating the payout moves the statement from `FINALIZED` to `PAID` and bumps the statement's version.

A `RoyaltyOperator` may **settle** a `PENDING` payout, moving its `status` to `SETTLED`; settling requires `PENDING` status (else `ERR_INVALID_STATE`). Alternatively, an operator may **reverse** a `PENDING` payout, moving its `status` to `REVERSED`; a `SETTLED` payout cannot be reversed, so a reverse from any non-`PENDING` state is rejected with `ERR_INVALID_STATE`. Reversing a payout also reverts the referenced statement from `PAID` back to `FINALIZED`, so that the statement can be re-paid or reopened.

### 3.9. The Deterministic Test Clock

Because period membership and rights-term coverage both depend on "now," the server maintains a logical current UTC instant rather than reading the wall clock. An `Administrator`-only test-driving capability sets that instant to a supplied `to_iso8601` value, pinning the server clock so that period and term checks behave deterministically. This is the instant used when a sync execution checks for an open `DRAFT` statement covering the present moment.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including the action endpoints that drive state transitions — return a `200 OK` status code. The test-clock capability also returns `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/rightsholders` | Create a payee party | Administrator |
| GET | `/rightsholders/{id}` | Read a rightsholder (computed ledger fields included) | Administrator, RoyaltyOperator, Rightsholder |
| POST | `/rightsholders/{id}/suspend` | Suspend a rightsholder (blocks payouts) | Administrator |
| POST | `/works` | Register a composition (shares not yet locked) | Administrator |
| GET | `/works/{id}` | Read a work | Administrator, RoyaltyOperator, Rightsholder, Licensee |
| POST | `/works/{id}/register` | Lock composition shares once they sum to exactly 100% | Administrator |
| POST | `/composition-shares` | Add a writer/publisher share to a composition | Administrator |
| GET | `/composition-shares/{id}` | Read a single composition share | Administrator, RoyaltyOperator |
| GET | `/composition-shares` | List composition shares; filter by work_id or rightsholder_id | Administrator, RoyaltyOperator |
| POST | `/recordings` | Register a master recording embodying a work | Administrator |
| GET | `/recordings/{id}` | Read a recording | Administrator, RoyaltyOperator, Licensee |
| GET | `/recordings` | List recordings; filter by work_id | Administrator, RoyaltyOperator, Licensee |
| POST | `/recordings/{id}/lock-shares` | Lock recording shares once they sum to exactly 100% | Administrator |
| POST | `/recording-shares` | Add a master share to a recording | Administrator |
| GET | `/recording-shares/{id}` | Read a single recording share | Administrator, RoyaltyOperator |
| GET | `/recording-shares` | List recording shares; filter by recording_id or rightsholder_id | Administrator, RoyaltyOperator |
| POST | `/rights-windows` | Grant a territory/term rights window on a recording | Administrator |
| GET | `/rights-windows/{id}` | Read a single rights window | Administrator, RoyaltyOperator, Licensee |
| GET | `/rights-windows` | List rights windows; filter by recording_id | Administrator, RoyaltyOperator, Licensee |
| POST | `/rights-windows/{id}/revoke` | Revoke a rights window | Administrator |
| POST | `/usage-events` | Ingest a raw usage event (PERFORMANCE or MECHANICAL) | RoyaltyOperator |
| GET | `/usage-events/{id}` | Read a usage event | Administrator, RoyaltyOperator |
| GET | `/usage-events` | List usage events; filter by recording_id | Administrator, RoyaltyOperator |
| POST | `/usage-events/{id}/allocate` | Compute royalty and distribute EARNING entries to holders' DRAFT statements | RoyaltyOperator |
| POST | `/usage-events/{id}/void` | Void an unallocated usage event | RoyaltyOperator |
| POST | `/sync-licenses` | Create a sync license quote | RoyaltyOperator |
| GET | `/sync-licenses/{id}` | Read a sync license | Administrator, RoyaltyOperator, Licensee |
| GET | `/sync-licenses` | List sync licenses; filter by licensee_id or recording_id | Administrator, RoyaltyOperator, Licensee |
| POST | `/sync-licenses/{id}/counter` | Licensee counters the quote | Licensee |
| POST | `/sync-licenses/{id}/requote` | Operator re-quotes with a new base fee | RoyaltyOperator |
| POST | `/sync-licenses/{id}/accept` | Accept the quote (Licensee from DRAFT, Operator from COUNTERED) | Licensee, RoyaltyOperator |
| POST | `/sync-licenses/{id}/execute` | Execute the license: distribute quoted fee to master holders | RoyaltyOperator |
| POST | `/sync-licenses/{id}/decline` | Decline the quote (DRAFT or COUNTERED) | RoyaltyOperator |
| POST | `/advances` | Issue a recoupable advance to a rightsholder | Administrator |
| GET | `/advances/{id}` | Read an advance | Administrator, RoyaltyOperator, Rightsholder |
| GET | `/advances` | List advances; filter by rightsholder_id | Administrator, RoyaltyOperator, Rightsholder |
| POST | `/advances/{id}/write-off` | Write off the remaining unrecouped principal | Administrator |
| POST | `/statements` | Open a DRAFT statement for a rightsholder + period | RoyaltyOperator |
| GET | `/statements/{id}` | Read a statement (computed totals included) | Administrator, RoyaltyOperator, Rightsholder |
| GET | `/statements` | List statements; filter by rightsholder_id | Administrator, RoyaltyOperator, Rightsholder |
| GET | `/statements/{id}/ledger` | List ledger entries attached to a statement; filter by entry_type | Administrator, RoyaltyOperator, Rightsholder |
| POST | `/statements/{id}/finalize` | Finalize: recoup advances, withhold tax, compute net payable | RoyaltyOperator |
| POST | `/statements/{id}/reopen` | Reopen a finalized statement (reverses recoupment + withholding) | RoyaltyOperator |
| POST | `/payouts` | Create a payout against a FINALIZED statement | RoyaltyOperator |
| GET | `/payouts/{id}` | Read a payout | Administrator, RoyaltyOperator, Rightsholder |
| GET | `/statements/{id}/payouts` | List payouts for a statement | Administrator, RoyaltyOperator, Rightsholder |
| POST | `/payouts/{id}/settle` | Mark a payout settled | RoyaltyOperator |
| POST | `/payouts/{id}/reverse` | Reverse a pending payout | RoyaltyOperator |
| POST | `/_clock/set_current_utc` | Set the server's current UTC instant for deterministic tests | Administrator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_FK_NOT_FOUND` | 422 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_DUPLICATE_CODE` | 409 |
| `ERR_SPLIT_TOTAL_INVALID` | 422 |
| `ERR_SHARES_LOCKED` | 409 |
| `ERR_SHARES_NOT_LOCKED` | 409 |
| `ERR_RIGHTS_NOT_AVAILABLE` | 422 |
| `ERR_NO_OPEN_STATEMENT` | 409 |
| `ERR_WINDOW_OVERLAP` | 409 |
| `ERR_STATEMENT_PERIOD_OVERLAP` | 409 |
| `ERR_UNALLOCATED_USAGE_IN_PERIOD` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_PAYOUT_EXISTS` | 409 |
| `ERR_RIGHTSHOLDER_SUSPENDED` | 409 |
| `ERR_NOTHING_PAYABLE` | 409 |
