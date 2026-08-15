# Broiler Growout Settlement API — Product Requirements Document

## 1. Introduction

Contract broiler production is a tournament business. An integrator delivers day-old chicks and feed to an independent grower's houses; the grower raises the birds to market weight; and at settlement the grower's pay is set not by an absolute rate card but by how that flock ranked against every other flock harvested in the same settlement week. Small differences in feed conversion, livability, and plant condemnations translate directly into cents per pound, and the same settlement check is also the collection point for any capital-upgrade loans the integrator has advanced to the grower.

This document specifies the Broiler Growout Settlement API, which manages the full arc from grower onboarding through flock placement, feed and mortality tracking, catch scheduling and harvest, tournament scoring, settlement calculation and dispute, loan issuance and repayment, and the biosecurity and downtime rules that keep houses eligible for the next placement. The audience is the engineering team implementing the API; every behavior described here is a hard requirement, and the endpoint and error catalogs in §4 and §5 are the structural contract the tests will exercise.

The system serves five distinct operator populations — integrator operations administrators, growers acting on their own farms, field service technicians, live-haul coordinators, and settlement-office analysts — with deliberate segregation of duties so that the person who schedules a catch can never approve the settlement that pays for it.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. The API is mounted under `/api`; all paths in §4 are relative to that mount.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through two mandatory HTTP headers. Every request must include `X-User-ID` identifying the acting user and `X-User-Role` naming their operational capacity. The system recognizes five roles, spelled exactly: `IntegratorAdmin`, `Grower`, `ServiceTech`, `LivehaulScheduler`, and `SettlementAnalyst`.

A request missing either header, or carrying an `X-User-Role` value outside this declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted to invoke the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403); the same `ERR_UNAUTHORIZED` is raised when an entity-backed ownership check fails, such as a `Grower` attempting to act on a resource belonging to another grower.

Role identity is interpreted as follows. When `X-User-Role` is `Grower`, `X-User-ID` is the `id` of the acting `Grower` record; ownership checks on any resource that references a `Grower` (directly, or through the house-to-grower chain on a flock or settlement) compare that resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `IntegratorAdmin`, `ServiceTech`, `LivehaulScheduler`, or `SettlementAnalyst`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit purposes but does not compare it to any entity's `id`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order. Paginated list responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. Common Resource Properties

Every persisted resource carries a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier formatted as a bare UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp, refreshed on any change to the resource's properties.
- `version` (integer): a system-managed integer that increments on every mutation of the resource, used for optimistic concurrency control where this document names it.

All resources in this domain — growers, contracts, houses, flocks, placements, feed deliveries, mortality reports, catch schedules, catch crews, weight tickets, biosecurity audits, settlement groups, settlements, and grower loans — carry the full set of common fields including `updated_at` and `version`. Updates to derived fields (for example a flock's `feed_delivered_lbs` or a grower's `loan_outstanding_cents`) are mutations of the owning resource and therefore refresh its `updated_at` and increment its `version`.

### 2.5. Nested Resource Retrieval

The API enforces strict, hierarchical validation for any request targeting a nested resource. When an endpoint path contains a resource identifier, the system resolves path-template identifiers sequentially from left to right (grower, then contract, house, flock, placement, schedule, settlement, loan, group, crew, audit, in the order they appear in the path). The request is rejected immediately with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve to an existing resource, before any later identifier or any body field is examined. Separately, identifiers that arrive in the request body — the `contract_id`, `settlement_group_id`, or `crew_id` supplied when planning a flock or scheduling a catch, and analogous foreign keys such as `grower_id` or `house_id` on creation payloads — are validated after the path resolves; a body reference that does not resolve is rejected with `ERR_REFERENCE_NOT_FOUND` (HTTP 404).

### 2.6. Monetary Values, Ratios, and Rounding Discipline

All monetary amounts in this domain are integer counts of cents — never fractional dollars — and all ratios used for scoring are decimal numbers. Two precision regimes coexist and must not be confused.

Rate and ratio quantities that feed the tournament scoring — `adj_fcr`, `livability_pct`, `condemnation_pct`, `performance_score`, `performance_rating`, and the three group averages — are computed and stored to exactly 4 decimal places using round-half-up. Settlement money lines (`base_amount_cents`, `fcr_bonus_cents`, `condemnation_deduction_cents`, `loan_repayment_cents`, `net_amount_cents`) are whole-cent integers, each rounded half-up to whole cents individually before any summation takes place. The rounding order is pinned: per line, then sum — never sum-then-round. A settlement whose lines appear inconsistent by a cent or two with an outside recomputation is almost always a symptom of rounding at the wrong stage.

### 2.7. Optimistic Concurrency Control

Two write endpoints in this API require an optimistic-concurrency token from the caller, and only those two.

First, recomputing a flock's settlement — the `SettlementAnalyst` operation that creates or refreshes the settlement row for a harvested flock — requires the request to carry `expected_flock_version`, the value of the flock's `version` the analyst last observed. If the flock's current `version` has advanced since that observation (for example because a weight ticket was just posted, changing `live_weight_lbs` and therefore the harvest-time calculations), the request is rejected with `ERR_STALE_FLOCK_VERSION` (HTTP 412) and the client must re-read the flock and retry with the fresh version.

Second, issuing a grower loan requires the request to carry `expected_grower_version`, the value of the grower's `version` the client last observed. If the grower's current `version` has advanced in the meantime (for example because a settlement approval cascade just reduced `loan_outstanding_cents`), the loan issuance is rejected with `ERR_STALE_GROWER_VERSION` (HTTP 412) and the client must re-read and retry.

Endpoints not named above do not accept a version field; the server performs no OCC check on them.

### 2.8. Validation Ordering

When multiple validation rules could reject the same request, they are evaluated in a fixed priority order so that the surfaced error is deterministic:

1. Authentication first — presence and validity of `X-User-Role` and `X-User-ID` (`ERR_UNAUTHENTICATED`).
2. Authorization — the role may invoke the endpoint and any ownership check passes (`ERR_UNAUTHORIZED`).
3. Path existence — left-to-right resolution of path identifiers (`ERR_NOT_FOUND`).
4. Body reference existence — foreign keys in the payload resolve (`ERR_REFERENCE_NOT_FOUND`).
5. Transition legality — the target entity is in a from-state of the requested transition (`ERR_INVALID_STATE`).
6. Optimistic concurrency — on the two OCC-guarded writes, the expected version matches (`ERR_STALE_FLOCK_VERSION` or `ERR_STALE_GROWER_VERSION`).
7. House placement safety — the house is not quarantined and the scheduled placement date clears any downtime (`ERR_HOUSE_IN_DOWNTIME`).
8. Condemned-loss threshold — the flock's condemnation percentage exceeds the whole-flock loss threshold (`ERR_CONDEMNATION_BELOW_THRESHOLD`).
9. Crew capacity — the crew is not already committed at its daily maximum on the catch date (`ERR_CREW_OVERBOOKED`).
10. Flock age — the flock is at least 35 days old at catch scheduling (`ERR_FLOCK_TOO_YOUNG`).
11. Quantity sanity — positive weights and head counts, capacity limits, cumulative mortality bounds (`ERR_QUANTITY_INVALID`).
12. Uniqueness — no duplicate of a unique identifier (`ERR_DUPLICATE`).
13. Renewal preconditions — upgrade cleared and house eligibility count sufficient (`ERR_RENEWAL_BLOCKED`).
14. Termination preconditions — no in-flight flocks under the contract (`ERR_FLOCKS_IN_FLIGHT`).
15. Settlement approval preconditions — group locked and settlement final (`ERR_GROUP_NOT_LOCKED`).
16. Loan terms — principal positive and recovery percentage in range (`ERR_LOAN_TERMS_INVALID`).

The ordering matters in practice: on catch-schedule creation, an overbooked crew surfaces as `ERR_CREW_OVERBOOKED` before an under-age flock surfaces as `ERR_FLOCK_TOO_YOUNG`, because priority 9 is evaluated before priority 10. Likewise, a stale grower version on loan issuance (priority 6) is reported before the loan's own term validation (priority 16), so a client holding a stale read learns to re-read before it learns its terms were wrong.

### 2.9. The Logical Clock

All time-dependent rules in this document — flock age, downtime windows, quarantine windows, contract term comparisons — are evaluated against a server-side logical clock, not the wall clock. The logical clock's startup default, before any operator intervention, is exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time. An `IntegratorAdmin` may set the logical clock by invoking the admin-only clock capability with a `to_iso8601` timestamp; the capability returns the resulting `current_utc` value. Date-only comparisons in this document treat a logical instant after midnight of a date as being "after" that date.

## 3. Business Logic & Workflows

### 3.1. Onboarding Growers, Contracts, and Houses

The integrator's roster begins with the grower. An `IntegratorAdmin` creates a `Grower` by supplying a `grower_code` — unique across all growers and immutable once created — together with the grower's legal `full_name`. A new grower's `status` starts at `ACTIVE`, with `performance_rating` null (there is no settled history yet), `loan_outstanding_cents` at zero, and `house_count` at zero. The grower `status` lifecycle has three values: `ACTIVE`, `SUSPENDED`, and `TERMINATED`. Suspension is an `IntegratorAdmin` action that moves the grower to `SUSPENDED` and increments the grower's `version`.

A grower's productive capacity is expressed in houses. Each `House` is created by an `IntegratorAdmin` under a grower via a payload carrying the owner `grower_id`, a grower-scoped `house_no` (unique within that grower, such as H1), and a positive `capacity_birds`. A house's `house_status` starts at `ACTIVE`. The set of `house_status` values is `ACTIVE`, `PLACED`, `DOWNTIME`, `QUARANTINED`, and `DECOMMISSIONED`. A house's `downtime_until` field — an ISO date until which the house is barred from placement — starts null and is set by harvest completion and biosecurity failures, as later subsections describe. The grower's `house_count` is a derived field: it counts exactly the grower's houses whose status is `ACTIVE` or `PLACED`, and it is recomputed whenever a house is created or changes status.

The commercial relationship is the `GrowerContract`. An `IntegratorAdmin` creates one with a payload containing the `grower_id`, a unique `contract_no`, the contracted `base_pay_cents_per_lb` (a positive integer count of cents per live pound, tier-adjusted at settlement by tournament rank), the `committed_house_count` the grower must keep eligible, and the `term_start_date` and `term_end_date` bounding the term. A contract's `status` begins at `DRAFT`, and the contract carries an `upgrade_required` flag that starts false. The contract lifecycle's terminal outcomes are `RENEWED`, `EXPIRED`, and `TERMINATED`.

### 3.2. The Contract Lifecycle: Activation, Renewal, Termination

Activation moves a contract `DRAFT` → `ACTIVE` and is performed by an `IntegratorAdmin`. Two preconditions guard it: the grower must be in `ACTIVE` status, and the grower's count of houses in `ACTIVE`, `PLACED`, or `DOWNTIME` status must be at least the contract's `committed_house_count`. A contract whose grower lacks the eligible houses cannot activate.

Renewal is a two-party handshake. The `Grower` initiates it by requesting renewal on their own contract, moving it `ACTIVE` → `RENEWAL_PENDING`; this is permitted only while the current logical date is on or before `term_end_date`, and only when the acting grower is the contract's grower. The `IntegratorAdmin` then either rejects the renewal — returning the contract `RENEWAL_PENDING` → `ACTIVE` with no other change — or completes it, moving the contract `RENEWAL_PENDING` → `RENEWED`. Completing a renewal supplies `new_term_end_date` and `new_committed_house_count` in the payload; on success the contract's `term_end_date` and `committed_house_count` are replaced with those values, and the grower's `house_count` is recomputed. Any of the grower's houses that sit in `QUARANTINED` at renewal remain `QUARANTINED` — renewal never launders a quarantine.

Two preconditions guard renewal completion, and their violation is reported as `ERR_RENEWAL_BLOCKED` (HTTP 422). First, if the contract's `upgrade_required` flag is true, the grower must hold a `GrowerLoan` whose `purpose` is `CAPITAL_UPGRADE` and whose status is `ISSUED` or `REPAID` — the integrator's capital-upgrade requirement is satisfied by financing it, not by promising to. Second, the grower's count of houses in `ACTIVE`, `PLACED`, or `DOWNTIME` must be at least the proposed `new_committed_house_count`. The integrator imposes the upgrade requirement through a dedicated action that sets `upgrade_required` to true on the contract.

Termination moves a contract `ACTIVE` → `TERMINATED` and is an `IntegratorAdmin` action. It is blocked — with `ERR_FLOCKS_IN_FLIGHT` (HTTP 409) — while any flock grown under the contract is still in a non-terminal state, meaning `PLANNED`, `PLACED`, `GROWING`, `CATCH_SCHEDULED`, or `HARVESTED`. Only once every flock under the contract has reached `SETTLED` or `CONDEMNED_LOSS` may the contract terminate.

### 3.3. Flock Planning, Placement, and the Grow-Out

A flock begins as a plan. An `IntegratorAdmin` plans a `Flock` with a payload naming the `house_id` it will occupy, the `contract_id` it grows under (a cross-aggregate link — the contract belongs to the grower, not the house), the `settlement_group_id` of the tournament group it will compete in, and a unique integrator-issued `flock_no`. A planned flock starts in `PLANNED` status with `placed_head` zero, all derived counters at zero, `adj_fcr`, `livability_pct`, and `performance_score` null, and `condemnation_pct` at zero. The full flock lifecycle is `PLANNED` → `PLACED` → `GROWING` → `CATCH_SCHEDULED` → `HARVESTED` → `SETTLED`, with a branch from `GROWING` to the terminal `CONDEMNED_LOSS` for catastrophic condemnation events.

Chicks arrive through a `ChickPlacement`. An `IntegratorAdmin` schedules a placement against a planned flock with a `scheduled_date` and a `head_count` — the number of chicks to be delivered, which must be greater than zero and no more than the target house's `capacity_birds`. Placement creation is guarded by house safety: if the flock's house is `QUARANTINED`, or its `downtime_until` covers the scheduled date, the request is rejected with `ERR_HOUSE_IN_DOWNTIME` (HTTP 409). A placement starts `SCHEDULED` and may be cancelled (`SCHEDULED` → `CANCELLED`) or confirmed by an `IntegratorAdmin`.

Confirmation is the pivot of the placement workflow. Confirming a placement moves it `SCHEDULED` → `CONFIRMED`, stamps its `confirmed_date` with the current logical date, and applies the same house-safety guard as scheduling — a house that has entered quarantine or whose downtime still covers the date rejects the confirmation with `ERR_HOUSE_IN_DOWNTIME`. On confirmation, three cascades fire together: the flock transitions `PLANNED` → `PLACED` with `placed_head` set from the placement's `head_count` and `placed_date` set from the placement's `confirmed_date`, and the flock's `livability_pct` is computed for the first time; the house transitions `ACTIVE` → `PLACED`, which recomputes the grower's `house_count`; and all of these mutations refresh `updated_at` and increment `version` on their respective records.

Feed follows placement. An `IntegratorAdmin` records each `FeedDelivery` against a flock with its `delivered_date`, the `feed_lbs` delivered (must be positive), the ration phase `feed_type` — one of `STARTER`, `GROWER`, `FINISHER`, or `WITHDRAWAL` — and a unique feed-mill `ticket_no`. Every accepted delivery adds its `feed_lbs` into the flock's `feed_delivered_lbs`. The very first delivery for a flock also flips it `PLACED` → `GROWING`; subsequent deliveries accumulate without further status change.

Mortality reporting belongs to the grower. A `Grower` files a `MortalityReport` for their own flock with a `report_date`, a `dead_head` count of birds found dead (zero or more), and a `condemned_head` count of birds condemned at the plant or in field condemnation (also zero or more). Each report adds its `dead_head` into the flock's `mortality_head` and its `condemned_head` into the flock's `condemnation_head`, then recomputes the flock's `livability_pct` — placed head minus mortality head, divided by placed head — and its `condemnation_pct` — condemnation head divided by the larger of one and (placed head minus mortality head). Quantity sanity is enforced at intake with `ERR_QUANTITY_INVALID` (HTTP 422): the cumulative mortality plus condemnation across all of a flock's reports must never exceed its `placed_head`.

### 3.4. Biosecurity, Downtime, and House Release

Houses breathe between flocks. When a flock's catch completes, its house moves `PLACED` → `DOWNTIME` and `downtime_until` is set to the catch date plus fourteen days — a mandatory two-week resting and clean-out window. When a whole-flock condemnation loss is declared (§3.6), the house instead receives a longer rest: `downtime_until` is set to the current logical date plus twenty-one days.

Biosecurity is policed by the `ServiceTech`. A `ServiceTech` records a `BiosecurityAudit` against a house with an `audit_date`, a `result` of `PASS` or `FAIL`, and — when the result is `FAIL` — a `quarantine_days` value that must be at least 7 (it defaults to 0 and is ignored when the result is `PASS`). A failing audit cascades immediately: the house moves `DOWNTIME` → `QUARANTINED` or `ACTIVE` → `QUARANTINED` depending on where it stood, and its `downtime_until` becomes the later of its current value and the audit date plus the quarantine days. For a house that was `ACTIVE` — with no downtime in force — the failure sets `downtime_until` to the audit date plus quarantine days outright.

Release from these states is also the `ServiceTech`'s job, with two distinct actions. Releasing downtime moves a house `DOWNTIME` → `ACTIVE`; it requires the current logical date to be after `downtime_until`, and additionally requires that no `FAIL` audit exists for the house whose quarantine window — its `audit_date` plus `quarantine_days` — still covers the current logical date; on release, `downtime_until` is cleared to null. Releasing quarantine moves a house `QUARANTINED` → `ACTIVE`; it requires the existence of a `PASS` audit for the house dated on or after the `FAIL` audit that triggered the quarantine, and likewise clears `downtime_until` to null. Both guards exist so that a house cannot be talked back into service while a live quarantine window still covers it.

### 3.5. Catch Scheduling, Weighing, and Harvest

As a flock approaches market age, the `LivehaulScheduler` takes over. Catch crews are registered with a unique `crew_code` and a positive `max_catches_per_day` daily capacity. Scheduling a catch for a flock creates a `CatchSchedule` naming the `crew_id` and the `catch_date`, moves the flock `GROWING` → `CATCH_SCHEDULED`, and starts the schedule in `SCHEDULED` status. Two temporal guards protect the schedule, evaluated in the fixed priority order of §2.8: the crew must not already be committed to `max_catches_per_day` catches in `SCHEDULED` or `COMPLETED` status on that `catch_date` — a violation is `ERR_CREW_OVERBOOKED` (HTTP 409) — and the flock's age, computed as the current logical date minus its `placed_date`, must be at least 35 days — a violation is `ERR_FLOCK_TOO_YOUNG` (HTTP 422).

Weighing happens at the plant. The `LivehaulScheduler` records each `WeightTicket` against the flock with a unique scale `ticket_no`, the `weighed_at` datetime, and the positive `live_weight_lbs` net weight. Every ticket adds its `live_weight_lbs` into the flock's aggregate `live_weight_lbs` and increments the flock's `version` — which is exactly why settlement recomputation carries an optimistic-concurrency token (§2.7).

Completing the catch is the harvest event, performed by the `LivehaulScheduler` once at least one weight ticket exists for the flock. Completion moves the schedule `SCHEDULED` → `COMPLETED` and fires a four-way cascade: the flock transitions `CATCH_SCHEDULED` → `HARVESTED`, its `adj_fcr` is computed, and its `livability_pct` and `condemnation_pct` are finalized; the house transitions `PLACED` → `DOWNTIME` with `downtime_until` set to the catch date plus fourteen days; the grower's `house_count` is recomputed; and the settlement group's averages are recomputed to include this flock. A catch schedule may instead be cancelled while `SCHEDULED`, which returns the flock `CATCH_SCHEDULED` → `GROWING` and moves the schedule to `CANCELLED`.

The harvest-time feed conversion calculation deserves precision. The flock's raw feed conversion ratio is its total `feed_delivered_lbs` divided by its total `live_weight_lbs`. The adjusted ratio — the one that actually feeds the tournament — subtracts a standard feed-waste credit of 2,000 pounds from the delivered total before dividing by `live_weight_lbs`, recognizing that some feed is always lost to spillage and cleanout rather than consumed by birds. Both the raw and adjusted values are rounded half-up to 4 decimal places; the raw value exists for diagnostic reporting only and is strictly greater than the adjusted value whenever any delivery exists.

### 3.6. Condemned-Loss Declaration

When disease or plant condemnation guts a flock, the integrator may write it off rather than settle it. An `IntegratorAdmin` declares condemned loss on a `GROWING` flock. The declaration requires the flock's `condemnation_pct` to exceed the whole-flock loss threshold of 0.30 — that is, more than 30 percent of the surviving placed birds condemned; a flock at or below the threshold is rejected with `ERR_CONDEMNATION_BELOW_THRESHOLD` (HTTP 422). On declaration the flock moves `GROWING` → `CONDEMNED_LOSS`, no settlement row is ever created for it, and its house is pushed into `DOWNTIME` with `downtime_until` set to the current logical date plus 21 days — three weeks of rest after a catastrophic health event.

### 3.7. Tournament Groups, Provisional Settlements, and Locking

Settlement is a tournament. A `SettlementAnalyst` creates a `SettlementGroup` with a unique `group_code` and a `week_ending_date` naming the settlement week; the group starts `OPEN`. Every flock planned into the group competes against the group's other members, and the group maintains three running averages over its member flocks that have reached `HARVESTED` or `SETTLED`: `group_avg_fcr` (the mean of member `adj_fcr`), `group_avg_livability_pct`, and `group_avg_condemnation_pct`. These averages are recomputed on each member's harvest and start null while no member has harvested.

While the group is `OPEN`, a `SettlementAnalyst` may compute a provisional settlement for a harvested flock. This operation creates the flock's `Settlement` row in `PENDING` status with `variant` `PROVISIONAL` if none exists, or recomputes the amounts on the existing row. The operation requires `expected_flock_version` per §2.7, and increments the flock's `version` as it runs. Each flock has at most one settlement — the `flock_id` on a settlement is unique — and a second settlement creation for the same flock violates uniqueness with `ERR_DUPLICATE` (HTTP 409).

The tournament score is computed when a flock moves from `HARVESTED` to `SETTLED`, and is previewed whenever a provisional settlement is computed. The score starts from 100 and applies three adjustments: it adds 50 times the relative amount by which the group's average feed conversion exceeds this flock's `adj_fcr` — better-than-average conversion raises the score; it adds 20 times the amount by which the flock's `livability_pct` exceeds the group's average livability; and it subtracts 100 times the amount by which the flock's `condemnation_pct` exceeds the group's average condemnation. The result is rounded half-up to 4 decimal places. The evaluation order is pinned: the flock's `adj_fcr` and all three group averages are computed from their source rows first, and only then is the score evaluated. The apparent circularity — the score depends on group averages that include this flock — is resolved by computing the group averages over the `HARVESTED` and `SETTLED` members before scoring any member. A provisional score computed while the group is `OPEN` uses the averages over the currently-harvested members only, so it can and usually does drift from the final score as later members harvest.

Locking is the settlement week's point of no return. The `SettlementAnalyst` locks an `OPEN` group, moving it `OPEN` → `LOCKED`; on lock, every `PENDING` settlement in the group is recomputed per the full settlement-amount calculation and its `variant` is flipped from `PROVISIONAL` to `FINAL`. A group that has completed settlement reaches `SETTLED`.

### 3.8. Settlement Amounts: Rank, Tiers, Bonus, Deduction, Repayment

The money calculation runs at provisional settlement creation, at every settlement recomputation, at dispute resolution, and finally at group lock. Its inputs are the flock, the flock's contract, the group's members, and the grower's outstanding loans.

Ranking comes first. The flock's `rank_position` is its position when the group's members are ordered by `performance_score` from best to worst — position 1 is best. Ties break in favor of the higher `live_weight_lbs`, then the earlier `placed_date`. From rank comes a percentile: the group's member count minus the rank position, divided by the member count. The base pay rate is the contract's `base_pay_cents_per_lb` plus a tier uplift in cents per pound: 1.5 cents when the percentile is at least 0.75, otherwise 0.8 cents when it is at least 0.50, otherwise 0.2 cents when it is at least 0.25, otherwise nothing. The `base_amount_cents` is the flock's `live_weight_lbs` multiplied by that tier-adjusted rate, rounded half-up to whole cents.

The feed-conversion bonus rewards efficiency: `fcr_bonus_cents` is the flock's `live_weight_lbs` multiplied by a per-pound bonus of 0.5 cents when the flock's `adj_fcr` is at or below 98 percent of the group average, or 0.25 cents when it is merely at or below the group average, or zero otherwise — again rounded half-up to whole cents.

The condemnation deduction claws back excess plant loss: the flock's `condemnation_pct` is compared against a 0.005 allowance (half a percent); any excess above the allowance is multiplied by the flock's `live_weight_lbs` and by a rate of 40 cents per pound to produce `condemnation_deduction_cents`, rounded half-up to whole cents. A flock at or under the allowance has no excess and no deduction.

The positive subtotal is `base_amount_cents` plus `fcr_bonus_cents` minus `condemnation_deduction_cents`. When that subtotal is positive, the settlement diverts a share to loan repayment: `loan_repayment_cents` is the smaller of the subtotal multiplied by the loan's `recovery_pct` divided by 100 (rounded half-up to whole cents) and the sum of `outstanding_cents` across the grower's loans still in `ISSUED` status. When the subtotal is zero or negative, no repayment is diverted. The `net_amount_cents` is the positive subtotal minus the repayment. Every line is rounded to whole cents before the lines are combined — per-line rounding, then summation, never the reverse. A provisional computation ranks the flock over the currently-harvested members only, so provisional and final amounts differ whenever another member harvests after the preview.

### 3.9. Grower Loans and the Repayment Waterfall

Capital upgrades are financed by the integrator. An `IntegratorAdmin` issues a `GrowerLoan` to a grower with a `principal_cents` (must be positive), a `recovery_pct` — the percentage of each settlement's positive subtotal diverted to repayment, which must lie between 1 and 50 inclusive — and a `purpose` of `CAPITAL_UPGRADE` or `OPERATING`. A loan whose terms break these bounds is rejected with `ERR_LOAN_TERMS_INVALID` (HTTP 422). Issuance is OCC-guarded by `expected_grower_version` per §2.7. A new loan starts in `ISSUED` status with `outstanding_cents` equal to its `principal_cents`; its creation recomputes the grower's `loan_outstanding_cents` — the sum of `outstanding_cents` over the grower's loans in `ISSUED` status — and increments the grower's `version`. A `CAPITAL_UPGRADE`-purpose loan is what satisfies a contract's `upgrade_required` flag for renewal (§3.2).

Repayment flows through settlement approval. When a settlement is approved, its `loan_repayment_cents` is applied to the grower's loans oldest-first: the `ISSUED` loan with the earliest `created_at` absorbs the repayment first, and when its `outstanding_cents` reaches zero its status becomes `REPAID` and any remainder flows to the next-oldest `ISSUED` loan. The grower's `loan_outstanding_cents` is then recomputed. A fully-cleared loan can also be moved to `CLOSED`.

### 3.10. Settlement Approval, Dispute, and Payment

Approval is the settlement's commitment point, performed by a `SettlementAnalyst`. Two preconditions guard it, and their violation surfaces as `ERR_GROUP_NOT_LOCKED` (HTTP 409): the parent group must be in `LOCKED` status, and the settlement's `variant` must be `FINAL`. Approving a settlement moves it `PENDING` → `APPROVED` and fires the domain's largest cascade: the flock transitions `HARVESTED` → `SETTLED` and its `performance_score` is computed; the loan repayment waterfall of §3.9 runs against the grower's `ISSUED` loans and the grower's `loan_outstanding_cents` is recomputed; and the grower's `performance_rating` is recomputed.

The performance rating is a rolling form guide: the mean of `performance_score` across the grower's flocks in `SETTLED` status, taking the three most recent by `placed_date` — with ties broken by the later settled date, then by creation order — rounded half-up to 4 decimal places. A grower with no settled flocks has a null rating.

The grower's remedy is the dispute. A `Grower` may dispute a `PENDING` settlement on their own flock — the acting grower's identity must match the grower who owns the flock's house — moving it `PENDING` → `DISPUTED`. A `SettlementAnalyst` resolves the dispute, returning it `DISPUTED` → `PENDING` and recomputing the amounts per the full settlement calculation; this revision loop can run as often as needed before approval. Finally, an `APPROVED` settlement is paid by a `SettlementAnalyst`, moving it `APPROVED` → `PAID`; payment freezes `net_amount_cents`, and `PAID` is terminal.

## 4. Endpoint Definitions

Operations that create new resources return `201 Created`. Operations that modify an existing resource — including state transitions and actions — return `200 OK`. All endpoints are mounted under `/api`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/growers` | Create grower | IntegratorAdmin |
| GET | `/api/growers/{id}` | Get grower | IntegratorAdmin, Grower, SettlementAnalyst, ServiceTech, LivehaulScheduler |
| GET | `/api/growers` | List growers | IntegratorAdmin, SettlementAnalyst |
| POST | `/api/growers/{id}/loans` | Issue grower loan (OCC on Grower.version) | IntegratorAdmin |
| GET | `/api/growers/{id}/loans` | List a grower's loans | IntegratorAdmin, Grower, SettlementAnalyst |
| GET | `/api/growers/{id}/houses` | List a grower's houses | IntegratorAdmin, Grower, ServiceTech |
| GET | `/api/growers/{id}/contracts` | List a grower's contracts | IntegratorAdmin, Grower, SettlementAnalyst |
| POST | `/api/growers/{id}/suspend` | Suspend grower | IntegratorAdmin |
| POST | `/api/contracts` | Create contract | IntegratorAdmin |
| GET | `/api/contracts/{id}` | Get contract | IntegratorAdmin, Grower, SettlementAnalyst |
| POST | `/api/contracts/{id}/activate` | Activate contract | IntegratorAdmin |
| POST | `/api/contracts/{id}/impose-upgrade` | Impose capital upgrade requirement | IntegratorAdmin |
| POST | `/api/contracts/{id}/request-renewal` | Grower requests renewal | Grower |
| POST | `/api/contracts/{id}/renew` | Renew contract (new term, new house count) | IntegratorAdmin |
| POST | `/api/contracts/{id}/reject-renewal` | Reject renewal request | IntegratorAdmin |
| POST | `/api/contracts/{id}/terminate` | Terminate contract | IntegratorAdmin |
| POST | `/api/houses` | Create house | IntegratorAdmin |
| GET | `/api/houses/{id}` | Get house | IntegratorAdmin, Grower, ServiceTech, LivehaulScheduler |
| POST | `/api/houses/{id}/release-downtime` | Release house from downtime | ServiceTech |
| POST | `/api/houses/{id}/release-quarantine` | Release house from quarantine after PASS audit | ServiceTech |
| POST | `/api/houses/{id}/audits` | Record biosecurity audit | ServiceTech |
| GET | `/api/houses/{id}/audits` | List audits for house | IntegratorAdmin, ServiceTech, Grower |
| GET | `/api/houses/{id}/flocks` | List flocks in house | IntegratorAdmin, Grower, ServiceTech, LivehaulScheduler, SettlementAnalyst |
| POST | `/api/flocks` | Plan flock | IntegratorAdmin |
| GET | `/api/flocks/{id}` | Get flock | IntegratorAdmin, Grower, ServiceTech, LivehaulScheduler, SettlementAnalyst |
| GET | `/api/flocks` | List flocks with filters | IntegratorAdmin, SettlementAnalyst, LivehaulScheduler |
| POST | `/api/flocks/{id}/placements` | Schedule chick placement | IntegratorAdmin |
| GET | `/api/flocks/{id}/placements` | List placements for flock | IntegratorAdmin, Grower, ServiceTech |
| POST | `/api/flocks/{id}/feed-deliveries` | Record feed delivery | IntegratorAdmin |
| GET | `/api/flocks/{id}/feed-deliveries` | List feed deliveries | IntegratorAdmin, Grower, SettlementAnalyst |
| POST | `/api/flocks/{id}/mortality-reports` | Record mortality report | Grower |
| GET | `/api/flocks/{id}/mortality-reports` | List mortality reports | IntegratorAdmin, Grower, SettlementAnalyst |
| POST | `/api/flocks/{id}/weight-tickets` | Record weight ticket | LivehaulScheduler |
| GET | `/api/flocks/{id}/weight-tickets` | List weight tickets | IntegratorAdmin, Grower, LivehaulScheduler, SettlementAnalyst |
| POST | `/api/flocks/{id}/catch-schedules` | Schedule catch crew | LivehaulScheduler |
| GET | `/api/flocks/{id}/catch-schedules` | List catch schedules for a flock | IntegratorAdmin, Grower, LivehaulScheduler |
| POST | `/api/flocks/{id}/declare-condemned-loss` | Declare whole-flock condemnation loss | IntegratorAdmin |
| POST | `/api/placements/{id}/confirm` | Confirm chick placement | IntegratorAdmin |
| POST | `/api/placements/{id}/cancel` | Cancel a scheduled placement | IntegratorAdmin |
| POST | `/api/catch-schedules/{id}/complete` | Complete catch (requires weight tickets) | LivehaulScheduler |
| POST | `/api/catch-schedules/{id}/cancel` | Cancel catch schedule | LivehaulScheduler |
| POST | `/api/settlement-groups` | Create settlement group | SettlementAnalyst |
| GET | `/api/settlement-groups/{id}` | Get settlement group | IntegratorAdmin, SettlementAnalyst, Grower |
| GET | `/api/settlement-groups/{id}/flocks` | List flocks in a settlement group | IntegratorAdmin, SettlementAnalyst, Grower |
| POST | `/api/settlement-groups/{id}/lock` | Lock group; finalize all PROVISIONAL settlements in group | SettlementAnalyst |
| POST | `/api/flocks/{id}/recompute-settlement` | Create/recompute the flock's settlement (OCC on Flock.version) | SettlementAnalyst |
| GET | `/api/flocks/{id}/settlement` | Get the settlement for a flock (array of 0 or 1) | IntegratorAdmin, Grower, SettlementAnalyst |
| POST | `/api/settlements/{id}/approve` | Approve settlement (requires group LOCKED, FINAL variant) | SettlementAnalyst |
| POST | `/api/settlements/{id}/dispute` | Grower disputes settlement | Grower |
| POST | `/api/settlements/{id}/resolve-dispute` | Resolve dispute; recompute amounts | SettlementAnalyst |
| POST | `/api/settlements/{id}/pay` | Pay approved settlement | SettlementAnalyst |
| POST | `/api/catch-crews` | Create catch crew | LivehaulScheduler |
| GET | `/api/catch-crews/{id}` | Get catch crew | IntegratorAdmin, LivehaulScheduler |
| GET | `/api/catch-crews/{id}/schedules` | List schedules for a crew | IntegratorAdmin, LivehaulScheduler |
| POST | `/api/_clock/set_current_utc` | Set the server logical clock | IntegratorAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCE_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_FLOCK_VERSION` | 412 |
| `ERR_STALE_GROWER_VERSION` | 412 |
| `ERR_HOUSE_IN_DOWNTIME` | 409 |
| `ERR_CONDEMNATION_BELOW_THRESHOLD` | 422 |
| `ERR_CREW_OVERBOOKED` | 409 |
| `ERR_FLOCK_TOO_YOUNG` | 422 |
| `ERR_QUANTITY_INVALID` | 422 |
| `ERR_DUPLICATE` | 409 |
| `ERR_RENEWAL_BLOCKED` | 422 |
| `ERR_FLOCKS_IN_FLIGHT` | 409 |
| `ERR_GROUP_NOT_LOCKED` | 409 |
| `ERR_LOAN_TERMS_INVALID` | 422 |
