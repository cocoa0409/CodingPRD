# Opera & Ballet Production Management API — Product Requirements Document

## 1. Introduction

An opera and ballet company lives or dies by its calendar. Sets, costumes, and props must be built before the rehearsal room opens; artists must be contracted under union rest rules and cast with covers ready to step in; the single stage must rotate between productions with disciplined changeover buffers; surtitles must be prepared and locked before an audience is admitted; and every seat in the house must be priced against demand, held, and sold. Alongside this artistic pipeline runs a commercial one: co-production partners share build costs and season revenue, and finished productions are rented to other companies through negotiated offers.

This document specifies the API of a production management system for such a company. It covers the full lifecycle of a production from design through build, rehearsal, repertory, and archive; the fiscal discipline of the build budget; casting with principal/cover chains; rehearsal room scheduling and call sheets; stage occupancy across the repertory; performance readiness gates, ticket inventory, and demand-based pricing; and the negotiation and settlement of co-production shares and rental offers. All business resources are served under the `/opera` prefix, with one administrative capability mounted outside it. Contractual mechanics — envelopes, pagination, headers, validation order, error codes — are pinned down in §2; business behavior is told as workflows in §3; §4 indexes the endpoints and §5 catalogs the error codes.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` and `X-User-Role`. If either header is missing, or if `X-User-Role` is not one of the declared roles, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). If the role is declared but is not permitted to invoke the endpoint, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

Eight roles are declared. `PlatformAdmin` is the platform operator: it registers partner companies, changes their standing, and drives the logical clock. `ProductionManager` is the company-side production head: it owns productions, build items, co-production shares, and rental offers, and it cancels performances. `CastingDirector` is the casting authority: it owns dramatic roles, cast assignments, and cover chains. `ContractsOfficer` owns artists, artist contracts, and call-sheet participation; rest-floor waivers require a different `ContractsOfficer` than the one who created the contract (see §2.10). `TechnicalDirector` owns technical operations: rehearsal rooms, rehearsal calls, stage slots, surtitle tracks, and performance readiness. `BoxOfficeManager` owns ticketing: performances, sales windows, and seat-inventory holds and sales. `PartnerRepresentative` represents a renter company and counters, accepts, or declines rental offers addressed to that company. `Any` is a read-only role shared by every authenticated caller: all GET endpoints accept any declared role.

Seven of the eight roles are opaque identities. When `X-User-Role` is `PlatformAdmin`, `ProductionManager`, `CastingDirector`, `ContractsOfficer`, `TechnicalDirector`, `BoxOfficeManager`, or `Any`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example as `created_by_user_id` on a `Contract` or on a `RentalOffer` — but never compares it to any entity's `id`. The remaining role is entity-backed: when `X-User-Role` is `PartnerRepresentative`, `X-User-ID` is the `id` of the acting `PartnerCompany`, and ownership checks on any resource that references a `PartnerCompany` compare the resource's foreign-key field — `renter_company_id` on a rental offer — to `X-User-ID`. A `PartnerRepresentative` whose `X-User-ID` does not equal the offer's `renter_company_id` is rejected with `ERR_RENTER_OWNERSHIP_MISMATCH` (HTTP 403).

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

List endpoints accept two query parameters, `limit` and `offset`. `limit` defaults to 10 and must be at least 1 and at most 100; `offset` defaults to 0 and must not be negative. A `limit` or `offset` that is not an integer, or that violates these bounds, is rejected with `ERR_VALIDATION` (400). Results are sorted by `created_at` ascending, with ties on identical timestamps broken by creation order. The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

All sixteen resource types share the same four system-managed properties. `id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits, assigned at creation and never modified afterwards. `updated_at` uses the same timestamp format, initially equals `created_at`, and is refreshed on every mutation. `version` is an integer that starts at 1 at creation and increments by one on every mutation of the resource. A recompute of a derived field — `build_cost_balance_cents`, `season_revenue_cents`, `casting_status`, `confirmed_headcount`, or `accrued_revenue_share_cents` — is not a mutation for this rule: when the recomputed value changes, only `updated_at` is refreshed and `version` is left unchanged, and when the recomputed value is unchanged the resource is not touched at all.

A production's `version` is additionally advanced by two workflows that primarily mutate other resources: a build item of that production reaching `BUILT` (a cascade touch, §3.2), and the creation of a rental offer against that production (§3.9). Both bumps matter for the optimistic-concurrency rule in §2.7.

### 2.5. The Logical Clock

The server maintains a **logical clock** rather than trusting wall-clock time. At startup the clock reads exactly 2026-05-01T00:00:00Z, and it never falls back to wall-clock time afterwards. A `PlatformAdmin` may set it through the capability `POST /_clock/set_current_utc`, supplying the target instant as `to_iso8601`; the response reports the new reading as `current_utc`.

The logical clock gates two business events. A performance may be marked completed only when the clock is strictly past the performance's `ends_at` (§3.8). An accepted rental offer may be settled only when the clock has reached the offer's `window_end` (§3.9).

### 2.6. Monetary Precision and Rounding

All monetary amounts are integer cents. Wherever a calculation produces a fractional cent, the result is rounded half up — a fractional part of exactly one half cent rounds up to the next cent. Three rounding disciplines coexist, and they must not be collapsed into one another:

- **Seat pricing** pins two rounding stages in a fixed order: the section-adjusted unit price is rounded half up first, and the demand-adjusted price is rounded half up second. A single-rounding shortcut produces different cent values and is non-conformant (§3.8).
- **Weekly pay and rental fees** perform no intermediate rounding; the final figure is rounded half up to whole cents exactly once (§3.4, §3.9).
- **Build-budget arithmetic** is exact integer arithmetic over cents with no rounding at all (§3.2).

Where a co-production share accrues a revenue share, that accrued amount is itself rounded half up to whole cents at the moment it is computed (§3.3).

### 2.7. Optimistic Concurrency on Rental Offer Creation

Exactly one endpoint participates in optimistic concurrency control: creating a rental offer (`POST /opera/rental-offers`). The request must carry `expected_production_version`, a non-optional field holding the client's last observed `version` of the target production. If the value does not match the production's current `version` — because another writer has advanced the production since the client last read it, for example by creating an offer for the same renter, which legitimately supersedes the prior open offer and advances the production's version — the create is rejected with `ERR_STALE_VERSION` (HTTP 412). Endpoints not named here do not take a version field.

### 2.8. Rooms, the Shared Stage, and Scheduling Conflicts

**Rehearsal rooms** use strict half-open interval semantics: a call occupies its room from `starts_at` (inclusive) to `ends_at` (exclusive). Two calls on the same room conflict when each one starts before the other ends; two calls that merely touch — one ending exactly when the other begins — do not conflict, so back-to-back occupation is allowed. Only calls in `DRAFT` or `PUBLISHED` status block a room. The check runs when a rehearsal call is created and is re-run when a call is published; a conflict is rejected with `ERR_ROOM_TIME_CONFLICT` (HTTP 409).

**The stage** is a single resource shared by all productions, and it uses deliberately different, buffered-adjacency semantics because repertory changeovers take time. A new stage slot is checked against every existing stage slot in `PLANNED`, `LOCKED`, or `DONE` status. The required gap is two hours when the existing slot belongs to the same production as the new one (a reset buffer) and six hours when it belongs to a different production (a changeover buffer). A conflict exists when the existing slot starts before the new slot's end plus the required gap, and the new slot starts before the existing slot's end plus the required gap; overlap is therefore always a conflict, while adjacency is allowed only when the gap between the slots is at least the buffer. A gap of exactly the buffer passes. Violations are rejected with `ERR_STAGE_CHANGEOVER_CONFLICT` (HTTP 409).

### 2.9. Request Processing and Validation Order

Every request passes through a fixed validation pipeline. Earlier failures mask later ones: a request that fails step 1 never reaches step 2, a request that fails shape validation never reaches the fiscal check, and so on. The order is:

1. **Authentication headers.** `X-User-ID` and `X-User-Role` must be present and the role must be declared, on every endpoint — else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (400).
2. **Role permission.** The role must be permitted for the endpoint, on every endpoint — else `ERR_INSUFFICIENT_PERMISSIONS` (403).
3. **Entity-backed ownership.** For a `PartnerRepresentative` calling `POST /opera/rental-offers/{id}/counter`, `POST /opera/rental-offers/{id}/accept`, or `POST /opera/rental-offers/{id}/decline`, `X-User-ID` must equal the offer's `renter_company_id` — else `ERR_RENTER_OWNERSHIP_MISMATCH` (403). Because ownership cannot be evaluated without the offer, the offer id is resolved first, and a missing offer yields `ERR_NOT_FOUND` (404) before the ownership comparison.
4. **Request shape.** Required fields must be present, enums must be in range, integers that must be positive must be positive, and a share percentage must be greater than zero and at most one hundred — else `ERR_VALIDATION` (400). This applies to all mutating endpoints. The request body, when present, must be a JSON object — an unparseable or non-object body is `ERR_VALIDATION`, while an absent body is treated as an empty object. Datetime values must be ISO 8601 strings: an explicit offset is honored and the value normalized to UTC, an offset-less value is read as UTC, and any other value is `ERR_VALIDATION`; in responses, datetime business fields are rendered in UTC at second precision, with three fractional digits only when sub-second precision was supplied. On transition endpoints, `to_state` must be one of the target states of the transitions §3 declares for that endpoint — any other value, including a state of the machine that no transition of the endpoint leads to, is `ERR_VALIDATION`, while a declared target not reachable from the resource's current state falls to step 8.
5. **Time ranges.** `ends_at` must be strictly after `starts_at`, and `window_end` strictly after `window_start` — else `ERR_INVALID_TIME_RANGE` (400). This applies to exactly four creation endpoints: `POST /opera/rehearsal-calls`, `POST /opera/stage-slots`, `POST /opera/performances`, and `POST /opera/rental-offers`.
6. **Existence.** Path identifiers are validated left to right, then body foreign-key identifiers in their declared input order — else `ERR_NOT_FOUND` (404). This applies to every endpoint that carries path or body identifiers, including nested retrievals such as listing a performance's seat inventories, where the performance id is resolved before the query is served.
7. **Optimistic concurrency.** On `POST /opera/rental-offers`, `expected_production_version` must equal the production's current `version` — else `ERR_STALE_VERSION` (412).
8. **State legality.** The target entity's current state must permit the requested transition or action. Where the state machine declares a specific code, that code is used — `ERR_CALL_NOT_OPEN`, `ERR_CONTRACT_NOT_ACTIVE`, `ERR_OFFER_NOT_ACTIONABLE`, `ERR_SALES_NOT_OPEN`, `ERR_PRODUCTION_NOT_IN_REHEARSAL`, `ERR_PRODUCTION_NOT_IN_REPERTORY_PHASE`, `ERR_PERFORMANCE_NOT_ENDED`, `ERR_OFFER_WINDOW_NOT_ENDED`, `ERR_BUILD_ITEMS_NOT_DELIVERED`, `ERR_NO_PERFORMANCES_SCHEDULED`, `ERR_PRODUCTION_HAS_OPEN_COMMITMENTS`, `ERR_READINESS_GATE_BLOCKED` (all 409) — otherwise the generic `ERR_INVALID_STATE_TRANSITION` (409) is used.
9. **Segregation of duties.** The waiver approver must differ from the contract's creator, and the settle caller must differ from the offer's creator — else `ERR_SOD_SAME_USER_FORBIDDEN` (403). This applies to exactly two endpoints: `POST /opera/call-participants/{id}/approve-waiver` and `POST /opera/rental-offers/{id}/settle`.
10. **Referential integrity.** Cover assignments must reference a principal assignment on the same role (`ERR_COVER_LINK_INVALID`, 422); a cast assignment's contract must belong to the same production as its role (`ERR_CROSS_PRODUCTION_REFERENCE`, 422); at most one non-terminal participant may exist per call and contract pair (`ERR_DUPLICATE_PARTICIPANT`, 409); a co-production share requires a `CO_PRODUCER` partner and a rental offer requires a `RENTER` partner (`ERR_PARTNER_KIND_MISMATCH`, 422). This family applies to `POST /opera/cast-assignments`, `POST /opera/call-participants`, `POST /opera/co-production-shares`, and `POST /opera/rental-offers`.
11. **Resource scheduling conflicts.** The room-overlap check governs `POST /opera/rehearsal-calls` and the publish transition (`ERR_ROOM_TIME_CONFLICT`, 409); the stage-changeover check governs `POST /opera/stage-slots` (`ERR_STAGE_CHANGEOVER_CONFLICT`, 409). See §2.8.
12. **Union rest floor.** Adding a participant to a call runs the rest-floor check of §3.6 against the contract's committed calls — else `ERR_REST_FLOOR_VIOLATION` (422), unless the request waives the floor, in which case the participant is parked in `WAIVER_PENDING` instead.
13. **Capacity and quota.** Seat holds, releases, and purchases require sufficient seats (`ERR_INSUFFICIENT_SEATS`, 409); confirming a principal requires that no other confirmed principal exist on the role (`ERR_ROLE_PRINCIPAL_TAKEN`, 409); ratifying a share requires the ratified percentages to stay within one hundred (`ERR_SHARE_PERCENT_OVERFLOW`, 422); accepting a rental offer requires the renter's standing to be `GOOD` (`ERR_RENTER_STANDING_NOT_GOOD`, 409); countering requires the negotiation-round cap to be unreached (`ERR_NEGOTIATION_ROUND_LIMIT`, 422).
14. **Fiscal discipline.** A build item's quoted cost must fit within the production's remaining build balance at order time, and the excess of actual over quoted cost must fit at completion time — else `ERR_BUILD_BUDGET_EXCEEDED` (402). This applies to `POST /opera/build-items` and to `POST /opera/build-items/{id}/transition` when the target state is `BUILT`.

### 2.10. Segregation of Duties

Two actions enforce a four-eyes rule. Approving a rest-floor waiver on a call participant must be performed by a `ContractsOfficer` whose `X-User-ID` differs from the `created_by_user_id` recorded on the underlying contract. Settling an accepted rental offer must be performed by a `ProductionManager` whose `X-User-ID` differs from the `created_by_user_id` recorded on the offer. Either violation is rejected with `ERR_SOD_SAME_USER_FORBIDDEN` (HTTP 403).

## 3. Business Logic & Workflows

### 3.1. Partner Companies and Their Standing

A `PlatformAdmin` registers each external company the house does business with, supplying its legal `name` and a `partner_kind` of either `CO_PRODUCER` or `RENTER`. A company may not act as both kinds, and the kind is enforced at the point of use: proposing a co-production share with a company that is not a `CO_PRODUCER`, or creating a rental offer addressed to a company that is not a `RENTER`, is rejected with `ERR_PARTNER_KIND_MISMATCH` (§3.3, §3.9).

Every company begins life with `standing` set to `GOOD`. Standing is a simple administrative flag that a `PlatformAdmin` moves among `GOOD`, `WATCH`, and `BARRED` by submitting a `to_state` to the standing-change action; all three values are reachable from any other, and re-submitting the current standing is accepted — the recorded standing is unchanged, though `updated_at` and `version` still advance. Standing has exactly one business consequence: a renter whose standing is not `GOOD` cannot accept a rental offer (§3.9).

The partner-company list can be filtered by `partner_kind` and by `standing`, with the standard `limit` and `offset` pagination.

### 3.2. Productions and the Build Pipeline

A `ProductionManager` opens a new production with its `title`, a `work_type` of `OPERA` or `BALLET`, a `build_budget_cents` that must be greater than zero, and a `default_surtitle_language` — the ISO language code of the house surtitle track that will later gate technical readiness (§3.8). The new production starts in `DESIGN`, its `build_cost_balance_cents` is initialized to the full `build_budget_cents`, and its `season_revenue_cents` starts at zero.

From `DESIGN` the production advances `DESIGN` → `BUILD` with no further conditions. Moving `BUILD` → `REHEARSAL` requires that every build item of the production that is not `CANCELLED` has reached `DELIVERED` or `IN_USE` — a requirement vacuously satisfied when the production has no build items at all — and is otherwise rejected with `ERR_BUILD_ITEMS_NOT_DELIVERED`. Rehearsal may expose problems in the physical production, so `REHEARSAL` → `BUILD` is a legitimate rework loop back, again without preconditions. When the company is ready to perform, `REHEARSAL` → `IN_REPERTORY` requires that at least one performance exist for the production, failing with `ERR_NO_PERFORMANCES_SCHEDULED` otherwise. Finally, `IN_REPERTORY` → `ARCHIVED` — the terminal state — is permitted only when no rental offer of the production sits in `DRAFT`, `SENT`, `COUNTERED`, or `ACCEPTED` and no performance of it remains `SCHEDULED`; open commitments block the archive with `ERR_PRODUCTION_HAS_OPEN_COMMITMENTS`. Every successful production transition increments the production's `version` by one. The production list can be filtered by `status`.

**Build items** are the sets, costumes, and props ordered against the budget. Ordering one takes the owning `production_id`, an `item_kind` of `SET`, `COSTUME`, or `PROP`, a `name`, and a `quoted_cost_cents` that must be greater than zero. The quoted cost must fit within the production's current `build_cost_balance_cents`; an order that would overdraw the budget is rejected with `ERR_BUILD_BUDGET_EXCEEDED` (HTTP 402). A new item starts `ORDERED`, and its creation already commits money: the balance is recomputed on every order.

The item then walks `ORDERED` → `BUILT` → `DELIVERED` → `IN_USE`, with two terminal states, `IN_USE` and `CANCELLED`. Marking an item `BUILT` requires the request to carry `actual_cost_cents`, provided and greater than zero — a missing or non-positive actual is `ERR_VALIDATION`, and the field is read only on the `BUILT` transition and ignored on every other — and the production's current balance must be at least the amount by which the actual cost exceeds the quoted cost, else the completion is rejected with `ERR_BUILD_BUDGET_EXCEEDED`. A successful completion recomputes the production's balance and, as a cascade touch, increments the production's `version` by one. When a built item proves defective, `BUILT` → `ORDERED` is a rework loop that releases the actual-cost basis back to the quoted basis by recomputing the balance. Cancelling from `ORDERED` releases the committed quoted cost entirely, again via recompute, so an item that is ordered and then cancelled leaves the balance exactly where it started.

The balance itself obeys a conservation invariant. The committed amount is the sum, over the production's build items in `ORDERED`, `BUILT`, `DELIVERED`, or `IN_USE` (`CANCELLED` items are excluded), of each item's effective cost — its `actual_cost_cents` when the item has reached `BUILT`, `DELIVERED`, or `IN_USE` and an actual cost is recorded, otherwise its `quoted_cost_cents`. The production's `build_cost_balance_cents` is always the budget minus the committed amount, so balance plus committed equals `build_budget_cents` at all times; all arithmetic is exact integer cents. The build-item list can be filtered by `production_id` and `status`.

### 3.3. Co-Production Shares: Ratification, Dispute, and Settlement

A co-production share proposes that a partner company participate in a production's costs and, depending on the variant, its revenue. Creating one takes the `production_id`, the partner's `company_id`, a `share_percentage` — a JSON number, fractional values allowed — greater than zero and at most one hundred, and a `cost_split_method` of `GROSS_COST` or `NET_REVENUE_SHARE` which selects the settlement variant computed later. The company must be a `CO_PRODUCER`, failing which the create is rejected with `ERR_PARTNER_KIND_MISMATCH`. A new share is `PROPOSED`; its `settlement_cents` stays null until the share is `SETTLED`, and its `accrued_revenue_share_cents` is zero unless and until a ratified net-revenue share begins accruing.

Ratifying — `PROPOSED` → `RATIFIED` — enforces the house's one-hundred-percent cap: the sum of `share_percentage` over the production's already-`RATIFIED` shares plus the candidate's percentage must not exceed one hundred, else the ratification is rejected with `ERR_SHARE_PERCENT_OVERFLOW` (HTTP 422). When a `NET_REVENUE_SHARE` share is ratified, its `accrued_revenue_share_cents` is computed as the share's percentage of the production's current `season_revenue_cents`, rounded half up to whole cents; from then on the accrual is recomputed, with the same formula, on every change to the production's season revenue — every ticket purchase (§3.8) and every performance cancellation moves it.

Disputes are a normal part of co-production: `RATIFIED` → `DISPUTED` freezes the share while partners argue, and `DISPUTED` → `RATIFIED` resolves the dispute by re-running the same one-hundred-percent capacity check as an initial ratification and recomputing the accrual with the same formula. Settlement — `RATIFIED` → `SETTLED`, the terminal state — prices the share. The total build cost is the sum of effective costs over the production's build items in `DELIVERED` or `IN_USE`, where an item's effective cost is its `actual_cost_cents` when recorded, otherwise its `quoted_cost_cents`. The partner's cost share is its `share_percentage` of that total build cost, rounded half up to whole cents. Under `GROSS_COST` the partner simply pays its share of the build cost with no revenue offset, so `settlement_cents` is the cost share. Under `NET_REVENUE_SHARE` the build-cost share is offset by the partner's accrued share of season revenue: `settlement_cents` is the cost share minus the `accrued_revenue_share_cents`, with the accrual evaluated at settle time as the share's percentage of the production's `season_revenue_cents`, rounded half up. The net variant therefore never settles above the gross variant on identical inputs — it is strictly smaller whenever the accrued revenue share is positive — and it may legitimately go negative when the partner's revenue share exceeds its cost share. The share list can be filtered by `production_id`, `company_id`, and `status`.

### 3.4. Artists, Contracts, and Weekly Pay

A `ContractsOfficer` registers each artist with a `full_name`, a `discipline` of `PRINCIPAL_DANCER`, `CORPS_DANCER`, `SOPRANO`, `TENOR`, `CHORUS`, or `ORCHESTRA`, and a `union_code` of `AGMA`, `AFM`, or `EQUITY` that determines which rest and overtime rule family applies. Artists can be listed with a `discipline` filter.

Engaging an artist for a production creates a contract with the `production_id`, the `artist_id`, an `engagement_type` of `PRINCIPAL`, `COVER`, `CHORUS`, or `ORCHESTRA`, an `hourly_rate_cents` greater than zero, a `weekly_hours_cap` greater than zero marking the regular hours before overtime tiers apply, and an optional `rest_floor_hours` — the minimum rest between committed calls — a non-negative integer that defaults to 12 hours when omitted. The creating officer's `X-User-ID` is recorded as `created_by_user_id`; the segregation-of-duties check of §2.10 reads it later. Contracts begin in `DRAFT`.

The contract lifecycle is a negotiation followed by an engagement. `DRAFT` → `OFFERED` sends the offer; `OFFERED` → `DRAFT` recalls it for revision; `OFFERED` → `SIGNED` closes the deal and `OFFERED` → `DECLINED` records a refusal. Activation — `SIGNED` → `ACTIVE` — is permitted only while the production is in `BUILD`, `REHEARSAL`, or `IN_REPERTORY`, failing which it is rejected with `ERR_INVALID_STATE_TRANSITION`. Termination is possible from either `SIGNED` or `ACTIVE` and carries a cascade: every call participant of the contract in `INVITED`, `WAIVER_PENDING`, `CONFIRMED`, or `CHECKED_IN` status is moved to `REMOVED`, and each removal recomputes the affected call's `confirmed_headcount` (§3.6). Closing — `ACTIVE` → `CLOSED` — is the clean end of an engagement and requires that the contract hold no participant in `INVITED`, `WAIVER_PENDING`, or `CONFIRMED` status on any call still in `DRAFT` or `PUBLISHED`; a checked-in artist does not block closing, but open commitments do, and the transition is otherwise rejected with `ERR_INVALID_STATE_TRANSITION`. `CLOSED`, `DECLINED`, and `TERMINATED` are terminal. The contract list can be filtered by `production_id`, `artist_id`, and `status`.

**Weekly pay** is quoted per contract and per week. The quote takes a `week_start` and an optional `mode` of `PROJECTED` or `FINAL`, and always reports both variants side by side — `projected_hours` and `projected_pay_cents` against `final_hours` and `final_pay_cents` — so scheduled-but-unplayed work can be compared against actuals. The week window is the seven-day half-open window beginning at `week_start` 00:00:00 UTC — any time-of-day supplied in `week_start` is discarded, so the window always opens at midnight UTC on the named date — and it includes the start instant and excludes the instant seven days later. A missing or unparseable `week_start`, or a `mode` outside the two declared values, is `ERR_VALIDATION`. A call contributes to a contract's week when the contract holds a participant on it in `CONFIRMED` or `CHECKED_IN` status and the call's `starts_at` falls inside the window. The two variants differ only in which calls are included: `PROJECTED` counts calls in `PUBLISHED` or `COMPLETED`, so scheduled-but-unplayed hours count; `FINAL` counts only `COMPLETED` calls, so identical week data yields strictly lower final pay whenever any included call is still `PUBLISHED` rather than `COMPLETED`.

Total payable hours are the sum of each included call's duration — end minus start — measured in whole and fractional hours. Pay then applies the overtime tiers: the regular hours, being the smaller of the total hours and the contract's `weekly_hours_cap`, are paid at the base `hourly_rate_cents`; the first overtime tier, comprising the hours beyond the cap up to a span of ten hours, is paid at one and a half times the base rate; the second overtime tier, comprising any hours beyond the cap plus that ten-hour first tier, is paid at double the base rate. On top of the tiered pay, each night call — an included call whose `ends_at` time-of-day, taken in UTC, falls at or after 23:00 and before midnight — adds a flat premium of 1,500 cents. No intermediate rounding occurs anywhere in the computation; the final figure is rounded half up to integer cents exactly once.

### 3.5. Casting and the Cover Chain

A `CastingDirector` creates each dramatic role of a production with the `production_id`, a `role_name` such as Odette/Odile, a `voice_type` of `SOPRANO`, `MEZZO`, `TENOR`, `BARITONE`, `BASS`, `DANCER_M`, `DANCER_F`, or `NON_SINGING`, and an optional `is_title_role` flag that defaults to false. A role's `casting_status` is derived, never set directly: it is `FULLY_CAST` when a `CONFIRMED` principal assignment and at least one `CONFIRMED` cover assignment exist on the role, `PRINCIPAL_SET` when a `CONFIRMED` principal exists but no confirmed cover does, and `UNFILLED` otherwise. A freshly created role starts `UNFILLED`. Roles can be listed with a `production_id` filter.

Casting proposes an assignment of a contract to a role: the request carries the `role_id`, the `contract_id`, a `slot` of `PRINCIPAL`, `COVER_1`, or `COVER_2`, and — required exactly when the slot is not `PRINCIPAL` — a `covers_assignment_id` pointing at the principal assignment this cover understudies. The cover link must reference a `PRINCIPAL`-slot assignment on the same role; a missing or invalid link is rejected with `ERR_COVER_LINK_INVALID` (HTTP 422). The contract must belong to the same production as the role, else `ERR_CROSS_PRODUCTION_REFERENCE` (HTTP 422). The assignment's own `production_id` is not taken from the request at all — it is copied from the role at creation. New assignments are `PROPOSED`.

Confirming an assignment runs three guards in the pipeline order of §2.9: the contract must be `ACTIVE`, else `ERR_CONTRACT_NOT_ACTIVE`; for a cover slot, the assignment referenced by `covers_assignment_id` must itself be `CONFIRMED`, else `ERR_COVER_LINK_INVALID`; and for a principal slot, no other `CONFIRMED` principal may exist on the same role, else `ERR_ROLE_PRINCIPAL_TAKEN` (HTTP 409). A successful confirm recomputes the role's `casting_status`.

Releasing an assignment covers two exits with one action. A `PROPOSED` assignment becomes `WITHDRAWN` with no further ceremony. Releasing a `CONFIRMED` assignment moves it to `RELEASED` — and when the released assignment was the role's principal, the cover-promotion cascade fires: among the assignments whose `covers_assignment_id` pointed at the released principal and whose status is `CONFIRMED`, the one with the lowest slot rank (`COVER_1` before `COVER_2`) is chosen, ties broken by earliest `created_at` (and, for identical timestamps, by creation order); the promoted assignment's `slot` becomes `PRINCIPAL` and its `covers_assignment_id` is cleared while its status stays `CONFIRMED`; every other `CONFIRMED` cover of the released principal is re-pointed so its `covers_assignment_id` references the promoted assignment. Whether a cover was promoted or none existed, the role's `casting_status` is then recomputed. Casting changes never touch rehearsal calls — there is no headcount cascade out of casting. Both `RELEASED` and `WITHDRAWN` are terminal. The assignment list can be filtered by `production_id`, `role_id`, `contract_id`, `covers_assignment_id`, `slot`, and `status`.

### 3.6. Rehearsal Rooms, Calls, and Call Sheets

A `TechnicalDirector` registers rehearsal rooms with a `name`, a `kind` of `STUDIO`, `STAGE`, or `ORCHESTRA_PIT`, a `capacity` greater than zero, and an `hourly_rate_cents` that must be a non-negative integer. Rooms can be listed with a `kind` filter.

Scheduling a call takes the `production_id`, the `room_id`, a `call_type` of `BLOCKING`, `STAGING`, `ORCHESTRA_READ`, `DANCE_CALL`, `TECH`, or `DRESS`, a `starts_at` and an `ends_at` that must be strictly later (else `ERR_INVALID_TIME_RANGE`), and an optional `required_headcount` — the minimum confirmed participants for the call to be viable — a non-negative integer that defaults to 1. Creation runs the room-overlap check of §2.8 against the room's blocking calls, rejecting conflicts with `ERR_ROOM_TIME_CONFLICT`. A new call is a `DRAFT` with `confirmed_headcount` zero.

Publishing — `DRAFT` → `PUBLISHED` — is gated twice: the production must be in `REHEARSAL`, else `ERR_PRODUCTION_NOT_IN_REHEARSAL`, and the room-overlap check is re-run against the room's current `DRAFT` and `PUBLISHED` calls — the call being published is excluded from the re-check — since the calendar may have moved since the draft was made. `PUBLISHED` → `DRAFT` is the unpublish-for-reschedule loop. `PUBLISHED` → `COMPLETED` marks the call played — completed calls are the ones that count toward the `FINAL` pay variant of §3.4. Cancellation is possible from `DRAFT` and from `PUBLISHED`; either way, every participant of the call in `INVITED`, `WAIVER_PENDING`, `CONFIRMED`, or `CHECKED_IN` status is moved to `REMOVED`, each removal recomputing the call's `confirmed_headcount` so it ends at zero. `COMPLETED` and `CANCELLED` are terminal. The call list can be filtered by `production_id`, `room_id`, and `status`.

**Call sheets** are built one participant at a time by a `ContractsOfficer`, submitting the `call_id`, the `contract_id`, and an optional `waive_rest_floor` flag that defaults to false. Four guards protect the sheet, in pipeline order. The call must still be open — `DRAFT` or `PUBLISHED` — since participant operations on a `COMPLETED` or `CANCELLED` call are rejected with `ERR_CALL_NOT_OPEN`. The contract must be `ACTIVE`, else `ERR_CONTRACT_NOT_ACTIVE`. At most one non-terminal participant may exist for the same call and contract pair — a prior participant in `INVITED`, `WAIVER_PENDING`, `CONFIRMED`, or `CHECKED_IN` blocks the add with `ERR_DUPLICATE_PARTICIPANT` (HTTP 409), while a `DECLINED` or `REMOVED` one does not. Finally the union rest floor runs, in the following precise form.

Let the floor F be the contract's `rest_floor_hours` converted to seconds. For the new participant's call, consider every other call on which the same contract already holds a participant in `CONFIRMED` or `CHECKED_IN` status and which is itself `PUBLISHED` or `COMPLETED`. A pair is rest-compliant when the new call starts at least F seconds after the other call ends, or the other call starts at least F seconds after the new call ends. If any committed pair is not compliant — including any pair whose calls overlap — the rest floor is violated. A gap of exactly F seconds passes. A participant that passes the rest floor is created in `INVITED`. A violation is handled according to `waive_rest_floor`: when the flag is true, the participant is created in `WAIVER_PENDING` instead of being rejected; when the flag is false or absent, the creation is rejected with `ERR_REST_FLOOR_VIOLATION` (HTTP 422).

Participants then move through their own lifecycle. An `INVITED` participant is confirmed — `INVITED` → `CONFIRMED` — or declines — `INVITED` → `DECLINED`. A confirmed participant checks in — `CONFIRMED` → `CHECKED_IN` — or is removed — `CONFIRMED` → `REMOVED`. A `WAIVER_PENDING` participant can only escape forward through the waiver-approval action: a `ContractsOfficer` whose `X-User-ID` differs from the contract's `created_by_user_id` approves the waiver under the segregation-of-duties rule of §2.10 — a same-user approval is rejected with `ERR_SOD_SAME_USER_FORBIDDEN` — moving the participant `WAIVER_PENDING` → `CONFIRMED`. `DECLINED` and `REMOVED` are terminal. A call's `confirmed_headcount` is a derived count of its participants in `CONFIRMED` or `CHECKED_IN` status, recomputed on every participant mutation: gaining a confirmed participant raises it by one, and a confirmed participant's removal lowers it by one. The participant list can be filtered by `call_id`, `contract_id`, and `status`.

### 3.7. Stage Occupancy and Surtitle Preparation

The stage is the house's scarcest resource: a single stage shared by every production in the repertory. A `TechnicalDirector` books occupation of it as stage slots, each carrying a `production_id`, a `slot_type` of `LOAD_IN`, `LOAD_OUT`, `TECH`, `PERFORMANCE_SLOT`, or `DRESS_ON_STAGE`, and a `starts_at` with an `ends_at` strictly later (else `ERR_INVALID_TIME_RANGE`). Creation runs the changeover check of §2.8 — the two-hour reset buffer between slots of the same production, the six-hour changeover buffer between slots of different productions, with a gap exactly equal to the buffer allowed — rejecting conflicts with `ERR_STAGE_CHANGEOVER_CONFLICT`. A slot is born `PLANNED`, firms to `LOCKED`, and completes as `DONE`; cancellation is allowed from `PLANNED` and from `LOCKED`, with `DONE` and `CANCELLED` terminal. Slots can be listed with `production_id`, `slot_type`, and `status` filters.

Surtitle tracks proceed in parallel. Creating one takes the `production_id`, the track's `language` as an ISO code, and a `cue_count` greater than zero. The track's life runs `DRAFT` → `TRANSLATED` → `CUES_LOCKED` → `LIVE`, with a revision loop `CUES_LOCKED` → `TRANSLATED` for late corrections; the machine has no terminal state. Tracks can be listed with `production_id`, `language`, and `status` filters. Both stage slots and surtitle tracks feed the readiness gate of §3.8: a `DONE` slot of type `TECH` proves the technical rehearsal happened, and a `LIVE` track in the production's `default_surtitle_language` proves the house can show titles.

### 3.8. Performances, Readiness, Sales, and Seat Pricing

A `BoxOfficeManager` schedules a performance once its production has reached `REHEARSAL` or `IN_REPERTORY` — scheduling against a production in any other status is rejected with `ERR_PRODUCTION_NOT_IN_REPERTORY_PHASE`. The request carries the `production_id`, the curtain time `starts_at`, the curtain-down `ends_at` strictly later (else `ERR_INVALID_TIME_RANGE`), and a creation-only `sections` array that must be non-empty, whose elements each name a `section` — one of `STALLS`, `BALCONY`, `BOX`, or `GALLERY` — a `total_seats` count that must be a positive integer, and a `base_price_cents` that must be a non-negative integer; any malformed element is rejected with `ERR_VALIDATION`, and naming the same section twice within one request is rejected as invalid shape with `ERR_VALIDATION`. One seat-inventory row is created per array element: its `performance_id` is set from the parent performance, its `section`, `total_seats`, and `base_price_cents` come from the element, its `seats_held` and `seats_sold` start at zero, and its `current_price_cents` is computed at a sold ratio of zero. A new performance starts with `lifecycle_status` `SCHEDULED`, `sales_status` `NOT_ON_SALE`, `readiness_status` `AWAITING_TECH`, and `realized_revenue_cents` zero.

Those three statuses are **parallel dimensions** evolving independently on the same row; no transition on one dimension implies a transition on another. On the sales dimension, opening sales — `NOT_ON_SALE` → `ON_SALE` — requires the performance still to be `SCHEDULED`, else `ERR_INVALID_STATE_TRANSITION`; suspending sales moves `ON_SALE` back to `NOT_ON_SALE`; closing sales moves `ON_SALE` → `SALES_CLOSED`. On the readiness dimension, marking tech-ready — `AWAITING_TECH` → `TECH_READY` — first requires the performance still `SCHEDULED`, else `ERR_INVALID_STATE_TRANSITION`, and then enforces three gate conditions, any failure surfacing as `ERR_READINESS_GATE_BLOCKED`: a stage slot of the same production with `slot_type` `TECH` and status `DONE` whose `ends_at` is no later than the performance's `starts_at`; a surtitle track of the same production whose `language` equals the production's `default_surtitle_language` and whose status is `LIVE`; and the production itself in `REHEARSAL` or `IN_REPERTORY`. Clearing for audience — `TECH_READY` → `CLEARED_FOR_AUDIENCE` — has no further conditions.

On the lifecycle dimension, marking the performance completed requires the logical clock to be strictly past `ends_at` — an early complete is rejected with `ERR_PERFORMANCE_NOT_ENDED` — and the readiness dimension to have reached `CLEARED_FOR_AUDIENCE`, else `ERR_READINESS_GATE_BLOCKED`. Only a `SCHEDULED` performance can be cancelled — cancelling from any other lifecycle state is rejected with `ERR_INVALID_STATE_TRANSITION`. Cancellation, executed by a `ProductionManager`, triggers a three-level cascade: every seat inventory of the performance is zeroed — `seats_held` and `seats_sold` to zero and `current_price_cents` recomputed at a sold ratio of zero — and the performance's `realized_revenue_cents` is reset to zero; the production's `season_revenue_cents` is recomputed because a cancelled performance no longer contributes; and every `RATIFIED` `NET_REVENUE_SHARE` co-production share of the production has its `accrued_revenue_share_cents` recomputed from the new season revenue. The production's season revenue is, at all times, the sum of `realized_revenue_cents` over its performances whose lifecycle is not `CANCELLED`. Performances can be listed with `production_id` and `lifecycle_status` filters, and a performance's seat inventories can be listed under the performance itself.

**Seat pricing** follows a pinned two-stage rounding that must not be collapsed. First, the section-adjusted unit price is computed as `base_price_cents` multiplied by the section multiplier — 1.0 for `STALLS`, 1.25 for `BALCONY`, 1.6 for `BOX`, 0.8 for `GALLERY` — and rounded half up to whole cents. Second, the sold ratio — `seats_sold` divided by `total_seats`, measured before the seats of the purchase currently being charged are counted — selects a demand multiplier: 1.0 while the ratio is below 0.5, 1.2 once the ratio reaches 0.5 but stays below 0.8, and 1.5 once the ratio reaches 0.8. The `current_price_cents` is then the section-adjusted unit price times the demand multiplier, rounded half up to whole cents. The two roundings are pinned: computing the price with a single rounding over the combined product yields a different cent value for odd bases — a base of 10050 cents in `BALCONY` at a ratio of 0.6 prices at 15076 cents under the pinned order, but 15075 under the naive single rounding — and only the pinned result is conformant. The price is recomputed when the inventory is created and after every purchase; holds and releases do not move the ratio and do not recompute the price.

A price quote is available for any inventory: given an optional `quantity` — a positive integer that defaults to 1, anything else being `ERR_VALIDATION` — it reports the `unit_price_cents`, the `demand_multiplier` currently in force, whether the group discount applied as `group_discount_applied`, and the `total_price_cents`, all evaluated at the current sold ratio without counting the quoted seats. A purchase charges the `current_price_cents` times the quantity, multiplied by 0.9 as a group discount when the quantity is at least 10 and by 1.0 otherwise, with the total rounded half up to whole cents.

The box office moves seats between three buckets, where availability is always `total_seats` minus `seats_held` minus `seats_sold`. Each of the three seat operations takes a `quantity` that must be a positive integer, else `ERR_VALIDATION`. Holding seats moves them from available to held and requires the performance's sales dimension to be `ON_SALE` — else `ERR_SALES_NOT_OPEN` — and the requested `quantity` not to exceed availability, else `ERR_INSUFFICIENT_SEATS`. Releasing seats moves them from held back to available and requires only that the `quantity` not exceed `seats_held`, else `ERR_INSUFFICIENT_SEATS`; a release is not gated on the sales dimension. Purchasing requires `ON_SALE` and sufficient availability under the same two errors; it charges the total at the pre-purchase demand ratio, then increases `seats_sold` by the `quantity`, adds the charged total to the performance's `realized_revenue_cents`, recomputes the inventory's `current_price_cents` at the new ratio, and propagates upward — the production's `season_revenue_cents` is recomputed, and with it the `accrued_revenue_share_cents` of every `RATIFIED` net-revenue share of the production. Inventories can be listed with `performance_id` and `section` filters.

### 3.9. Rental Offers and Negotiation

Renting a production out begins when a `ProductionManager` creates a rental offer with the `production_id`, the `renter_company_id` of the prospective renter — which must be a `RENTER`-kind partner company, else `ERR_PARTNER_KIND_MISMATCH` — a rental `window_start` and `window_end` strictly later (else `ERR_INVALID_TIME_RANGE`), a `performances_count` greater than zero, a `per_performance_fee_cents` greater than zero, and the optimistic-concurrency field `expected_production_version` of §2.7, a stale value being rejected with `ERR_STALE_VERSION` (HTTP 412). Creation has three side effects beyond the offer row itself: the production's `version` increments by one; any prior offer for the same production and the same renter still sitting in `SENT` or `COUNTERED` is automatically moved to `SUPERSEDED` by the system; and the offer's `negotiation_rounds` starts at zero while `created_by_user_id` records the creating manager's `X-User-ID`. The computed fee fields stay null until the action that computes them: `fee_base_cents`, `surcharge_pct`, and `total_fee_cents` until the offer is first sent, `countered_fee_cents` until the first counter, and `final_settlement_cents` until settlement. A new offer is a `DRAFT`.

Sending — `DRAFT` → `SENT` — computes the fee schedule in a pinned order. The `fee_base_cents` is the `performances_count` times the `per_performance_fee_cents`. The `surcharge_pct` keys on the fee base only, never on the total: it is 0 when the fee base is below 5,000,000 cents and 8 once the fee base reaches 5,000,000 cents. The `total_fee_cents` is the fee base plus the fee base times the surcharge percentage divided by one hundred, rounded half up to whole cents at this final step. Keying the tier on the total would make the fee self-referential; the pinned order keeps it well-defined.

The renter answers through a `PartnerRepresentative` acting under the ownership rule of §2.1. Countering — `SENT` → `COUNTERED` — submits a `countered_fee_cents` total, which must be a positive integer, and is allowed only while `negotiation_rounds` is below the hard cap of five; a counter at the cap is rejected with `ERR_NEGOTIATION_ROUND_LIMIT` (HTTP 422). The manager answers a counter by revising: submitting a new `per_performance_fee_cents` moves `COUNTERED` back to `SENT`, increments `negotiation_rounds` by one, and recomputes the whole fee schedule from the revised per-performance fee. The renter may instead accept — `SENT` → `ACCEPTED` — which additionally requires the renter company's `standing` to be `GOOD`, else `ERR_RENTER_STANDING_NOT_GOOD` (HTTP 409), or decline — `SENT` → `DECLINED`, or from a countered offer `COUNTERED` → `DECLINED`. The manager may withdraw a non-terminal offer — `DRAFT`, `SENT`, or `COUNTERED` → `WITHDRAWN`. Every one of these renter actions enforces ownership, rejecting a mismatched caller with `ERR_RENTER_OWNERSHIP_MISMATCH`; and any offer action attempted from a status that does not support it — sending a non-`DRAFT`, countering or accepting or declining a non-`SENT`, settling a non-`ACCEPTED` — is rejected with `ERR_OFFER_NOT_ACTIONABLE` (HTTP 409).

Settlement closes the loop: from `ACCEPTED`, a `ProductionManager` settles once the logical clock has reached the offer's `window_end` — earlier attempts fail with `ERR_OFFER_WINDOW_NOT_ENDED` — and only when the settling manager's `X-User-ID` differs from the offer's `created_by_user_id`, the segregation-of-duties rule of §2.10, else `ERR_SOD_SAME_USER_FORBIDDEN`. The `final_settlement_cents` is the `countered_fee_cents` when at least one negotiation round occurred — that is, whenever `negotiation_rounds` is above zero — and the `total_fee_cents` when none did; the offer lands in its `SETTLED` terminal state. `DECLINED`, `WITHDRAWN`, and `SUPERSEDED` are likewise terminal. Offers can be listed with `production_id`, `renter_company_id`, and `status` filters.

## 4. Endpoint Definitions

All endpoints follow the envelope of §2.2. Creating a new resource returns HTTP 201; reading a resource, performing a transition or action, and invoking any capability return HTTP 200. The table is a summary only: request bodies, response payloads, and side effects are specified by the workflow narratives of §3 and the cross-cutting rules of §2.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/_clock/set_current_utc` | Set the server's logical clock (startup default 2026-05-01T00:00:00Z) | PlatformAdmin |
| POST | `/opera/partner-companies` | Register a partner company (co-producer or renter) | PlatformAdmin |
| GET | `/opera/partner-companies` | List partner companies | Any |
| GET | `/opera/partner-companies/{id}` | Get one partner company | Any |
| POST | `/opera/partner-companies/{id}/transition` | Change partner standing (`GOOD`, `WATCH`, `BARRED`) | PlatformAdmin |
| POST | `/opera/productions` | Create a production (initial status `DESIGN`) | ProductionManager |
| GET | `/opera/productions` | List productions | Any |
| GET | `/opera/productions/{id}` | Get one production | Any |
| POST | `/opera/productions/{id}/transition` | Advance or revert the production lifecycle | ProductionManager |
| POST | `/opera/build-items` | Order a build item (set, costume, or prop) | ProductionManager |
| GET | `/opera/build-items` | List build items | Any |
| GET | `/opera/build-items/{id}` | Get one build item | Any |
| POST | `/opera/build-items/{id}/transition` | Transition a build item; `BUILT` requires `actual_cost_cents` | ProductionManager |
| POST | `/opera/co-production-shares` | Propose a co-production share | ProductionManager |
| GET | `/opera/co-production-shares` | List co-production shares | Any |
| GET | `/opera/co-production-shares/{id}` | Get one co-production share | Any |
| POST | `/opera/co-production-shares/{id}/transition` | Ratify, dispute, or settle a share | ProductionManager |
| POST | `/opera/artists` | Register an artist | ContractsOfficer |
| GET | `/opera/artists` | List artists | Any |
| GET | `/opera/artists/{id}` | Get one artist | Any |
| POST | `/opera/contracts` | Create an artist contract (initial `DRAFT`) | ContractsOfficer |
| GET | `/opera/contracts` | List contracts | Any |
| GET | `/opera/contracts/{id}` | Get one contract | Any |
| POST | `/opera/contracts/{id}/transition` | Transition a contract through its lifecycle | ContractsOfficer |
| GET | `/opera/contracts/{id}/pay-quote` | Weekly pay quote; optional `mode` (`PROJECTED` or `FINAL`) is validated, and the response always reports both variants | Any |
| POST | `/opera/roles` | Create a dramatic role for a production | CastingDirector |
| GET | `/opera/roles` | List roles | Any |
| GET | `/opera/roles/{id}` | Get one role | Any |
| POST | `/opera/cast-assignments` | Propose a casting (principal or cover) for a role | CastingDirector |
| GET | `/opera/cast-assignments` | List cast assignments | Any |
| GET | `/opera/cast-assignments/{id}` | Get one cast assignment | Any |
| POST | `/opera/cast-assignments/{id}/confirm` | Confirm a proposed assignment | CastingDirector |
| POST | `/opera/cast-assignments/{id}/release` | Release or withdraw; releasing a confirmed principal promotes its best confirmed cover | CastingDirector |
| POST | `/opera/rehearsal-rooms` | Register a rehearsal room | TechnicalDirector |
| GET | `/opera/rehearsal-rooms` | List rehearsal rooms | Any |
| GET | `/opera/rehearsal-rooms/{id}` | Get one rehearsal room | Any |
| POST | `/opera/rehearsal-calls` | Create a rehearsal call (room-overlap check, half-open intervals) | TechnicalDirector |
| GET | `/opera/rehearsal-calls` | List rehearsal calls | Any |
| GET | `/opera/rehearsal-calls/{id}` | Get one rehearsal call | Any |
| POST | `/opera/rehearsal-calls/{id}/transition` | Publish, unpublish, complete, or cancel a call | TechnicalDirector |
| POST | `/opera/call-participants` | Add a contract to a call sheet (rest-floor check; waiver path) | ContractsOfficer |
| GET | `/opera/call-participants` | List call participants | Any |
| GET | `/opera/call-participants/{id}` | Get one call participant | Any |
| POST | `/opera/call-participants/{id}/transition` | Confirm, decline, check in, or remove a participant | ContractsOfficer |
| POST | `/opera/call-participants/{id}/approve-waiver` | Approve a rest-floor waiver (segregation of duties) | ContractsOfficer |
| POST | `/opera/stage-slots` | Book a stage slot (changeover-buffer check on the single shared stage) | TechnicalDirector |
| GET | `/opera/stage-slots` | List stage slots | Any |
| GET | `/opera/stage-slots/{id}` | Get one stage slot | Any |
| POST | `/opera/stage-slots/{id}/transition` | Lock, complete, or cancel a stage slot | TechnicalDirector |
| POST | `/opera/performances` | Schedule a performance; creates one seat inventory per `sections` element | BoxOfficeManager |
| GET | `/opera/performances` | List performances | Any |
| GET | `/opera/performances/{id}` | Get one performance | Any |
| GET | `/opera/performances/{id}/seat-inventories` | List the seat inventories of a performance | Any |
| POST | `/opera/performances/{id}/open-sales` | Open ticket sales (sales dimension) | BoxOfficeManager |
| POST | `/opera/performances/{id}/suspend-sales` | Suspend sales back to `NOT_ON_SALE` | BoxOfficeManager |
| POST | `/opera/performances/{id}/close-sales` | Close ticket sales (sales dimension) | BoxOfficeManager |
| POST | `/opera/performances/{id}/tech-ready` | Mark `TECH_READY` (gated on done tech slot and live default-language surtitles) | TechnicalDirector |
| POST | `/opera/performances/{id}/clear` | Clear for audience (`TECH_READY` → `CLEARED_FOR_AUDIENCE`) | TechnicalDirector |
| POST | `/opera/performances/{id}/complete` | Mark performed (requires clock past curtain-down and clearance) | BoxOfficeManager |
| POST | `/opera/performances/{id}/cancel` | Cancel a scheduled performance (refund cascade) | ProductionManager |
| GET | `/opera/seat-inventories` | List seat inventories | Any |
| GET | `/opera/seat-inventories/{id}` | Get one seat inventory | Any |
| GET | `/opera/seat-inventories/{id}/price-quote` | Price quote for a quantity at the current demand ratio | Any |
| POST | `/opera/seat-inventories/{id}/hold` | Move seats from available to held (requires `ON_SALE`) | BoxOfficeManager |
| POST | `/opera/seat-inventories/{id}/release` | Move seats from held back to available | BoxOfficeManager |
| POST | `/opera/seat-inventories/{id}/purchase` | Sell seats (requires `ON_SALE`; charged at the pre-purchase demand ratio) | BoxOfficeManager |
| POST | `/opera/surtitle-tracks` | Create a surtitle track for a production and language | TechnicalDirector |
| GET | `/opera/surtitle-tracks` | List surtitle tracks | Any |
| GET | `/opera/surtitle-tracks/{id}` | Get one surtitle track | Any |
| POST | `/opera/surtitle-tracks/{id}/transition` | Advance a track (`TRANSLATED`, `CUES_LOCKED`, `LIVE`; revision loop back to `TRANSLATED`) | TechnicalDirector |
| POST | `/opera/rental-offers` | Create a rental offer (OCC on the production; supersedes a prior open offer to the same renter) | ProductionManager |
| GET | `/opera/rental-offers` | List rental offers | Any |
| GET | `/opera/rental-offers/{id}` | Get one rental offer | Any |
| POST | `/opera/rental-offers/{id}/send` | Send the offer to the renter (computes the fee schedule) | ProductionManager |
| POST | `/opera/rental-offers/{id}/revise` | Revise a countered offer and re-send (increments the round counter) | ProductionManager |
| POST | `/opera/rental-offers/{id}/withdraw` | Withdraw a non-terminal offer | ProductionManager |
| POST | `/opera/rental-offers/{id}/settle` | Settle an accepted offer after the rental window (segregation of duties) | ProductionManager |
| POST | `/opera/rental-offers/{id}/counter` | Renter counters the offer (round cap of five) | PartnerRepresentative |
| POST | `/opera/rental-offers/{id}/accept` | Renter accepts the offer (requires standing `GOOD`) | PartnerRepresentative |
| POST | `/opera/rental-offers/{id}/decline` | Renter declines the offer | PartnerRepresentative |

## 5. Error Code Catalogue

The table lists every error code with its HTTP status. The conditions that trigger each code are specified in the narratives of §2 and §3, next to the workflow they guard.

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_INSUFFICIENT_PERMISSIONS | 403 |
| ERR_RENTER_OWNERSHIP_MISMATCH | 403 |
| ERR_SOD_SAME_USER_FORBIDDEN | 403 |
| ERR_VALIDATION | 400 |
| ERR_INVALID_TIME_RANGE | 400 |
| ERR_NOT_FOUND | 404 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_STATE_TRANSITION | 409 |
| ERR_CALL_NOT_OPEN | 409 |
| ERR_CONTRACT_NOT_ACTIVE | 409 |
| ERR_OFFER_NOT_ACTIONABLE | 409 |
| ERR_SALES_NOT_OPEN | 409 |
| ERR_PRODUCTION_NOT_IN_REHEARSAL | 409 |
| ERR_PRODUCTION_NOT_IN_REPERTORY_PHASE | 409 |
| ERR_PERFORMANCE_NOT_ENDED | 409 |
| ERR_OFFER_WINDOW_NOT_ENDED | 409 |
| ERR_BUILD_ITEMS_NOT_DELIVERED | 409 |
| ERR_NO_PERFORMANCES_SCHEDULED | 409 |
| ERR_PRODUCTION_HAS_OPEN_COMMITMENTS | 409 |
| ERR_READINESS_GATE_BLOCKED | 409 |
| ERR_ROOM_TIME_CONFLICT | 409 |
| ERR_STAGE_CHANGEOVER_CONFLICT | 409 |
| ERR_REST_FLOOR_VIOLATION | 422 |
| ERR_DUPLICATE_PARTICIPANT | 409 |
| ERR_ROLE_PRINCIPAL_TAKEN | 409 |
| ERR_COVER_LINK_INVALID | 422 |
| ERR_CROSS_PRODUCTION_REFERENCE | 422 |
| ERR_PARTNER_KIND_MISMATCH | 422 |
| ERR_SHARE_PERCENT_OVERFLOW | 422 |
| ERR_INSUFFICIENT_SEATS | 409 |
| ERR_BUILD_BUDGET_EXCEEDED | 402 |
| ERR_RENTER_STANDING_NOT_GOOD | 409 |
| ERR_NEGOTIATION_ROUND_LIMIT | 422 |
