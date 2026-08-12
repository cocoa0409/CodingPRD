# Snow Removal Contracts API — Product Requirements Document

## 1. Introduction

A commercial snow contractor sells certainty in bad weather. Property managers sign before the first flake falls — some pay per push, some prepay the whole season, some buy crew time by the hour — and every one of them expects the pavement clear by a contractual deadline, with photographs to prove it and a paper trail sturdy enough to survive a slip-and-fall lawsuit. Between the handshake and the final settlement lies a chain of judgment calls: Did it snow enough to trigger service? Which weather sources verified the accumulation? Did the crew finish inside its window? How much salt was actually spread, and was it within the normative allowance for a lot that size? The API specified here exists to make every one of those calls deterministic, auditable, and billable.

The system governs the full commercial lifecycle of a snow removal operation. Property-manager clients and their sites are onboarded; seasonal agreements are structured with per-site trigger depths, route priorities, and completion targets; storm events are reported and then verified against a quorum of independent weather observations; in-house crews and approved subcontractors are dispatched along priority-sequenced routes; salt, ice-melt blend, and liquid brine applications are logged against frozen rate snapshots; and verified work is converted into credit-gated invoices, dispute resolutions, liability documentation packages, and season-closing true-up settlements that feed renewal. Billing is trigger-based and evidence-driven throughout: no visit becomes billable until weather data verifies that accumulation met the applicable trigger depth, and money moves only through state-checked operations that respect client credit limits, segregation of duties, and optimistic concurrency control.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes six distinct roles: `PlatformAdmin`, `OpsDispatcher`, `CrewLead`, `Subcontractor`, `ClientContact`, and `ClaimsAdjuster`. A request missing either header, or carrying a role name outside this set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Beyond authentication, every operation is restricted to a designated list of roles (see §4); a caller whose role is not on that list is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

Four roles carry opaque operator identities. When `X-User-Role` is `PlatformAdmin`, `OpsDispatcher`, `CrewLead`, or `ClaimsAdjuster`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for accountability — for example as `issued_by_user_id` on an Invoice, `resolved_by_user_id` on a Dispute, `reviewed_by_user_id` on a ServicePhoto, `completed_by_user_id` on a ServiceVisit, or `logged_by_user_id` on a MaterialApplication — but it never compares such an identifier to any entity's `id`.

The remaining two roles are entity-backed. When `X-User-Role` is `Subcontractor`, `X-User-ID` is the `id` of the acting Subcontractor; ownership checks on any resource that references a Subcontractor compare the resource's foreign-key field — `subcontractor_id` on a coverage assignment, `assigned_subcontractor_id` on a visit — to `X-User-ID`. When `X-User-Role` is `ClientContact`, `X-User-ID` is the `id` of the acting Client; ownership checks on any resource that references a Client compare the resource's `client_id`, or the client reachable through the resource's own site, contract, invoice, or claim chain, to `X-User-ID`. An entity-backed caller that touches a resource outside its ownership is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403).

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

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

All server-stamped timestamps — `created_at`, `updated_at`, `verified_at`, `challenged_at`, `closed_at`, `actual_start_at`, `completed_at`, `issued_at`, `settled_at`, and every other system-written instant — are read from a single logical clock, never from wall-clock time. Before any call is made, the clock reads exactly `2026-05-01T00:00:00Z` as a fixed startup default. A PlatformAdmin-only test-driving capability advances the clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`; every subsequent server-stamped timestamp uses this logical time. Every deadline, eligibility window, grace period, and time gate in this document is evaluated against the logical clock.

### 2.5. Common Resource Properties

Every resource carries an `id` — a server-minted UUID with no type prefix — assigned at creation. Resources additionally carry `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits (for example `2026-01-15T04:30:00.000Z`), and a `version` integer that starts at 1 and increments by one on every modification, including lifecycle transitions and system-driven recomputation of derived fields. The WeatherObservation feed record is the sole exception: it is immutable and append-only, and carries only `id` and `created_at` — `updated_at` and `version` are absent from it entirely.

### 2.6. Monetary Values, Measurement Precision, and Rounding

All monetary amounts in the system are integer cents; no fractional cents are ever stored or returned. Wherever a multiplication produces a fractional cent, the result is rounded half-up to a whole cent, at precisely the stage the governing rule specifies: material application lines are rounded per line before any summation; hourly tier amounts are rounded per tier before the two tiers are summed, and the night premium, when it applies, rounds last on the summed base; the area-normative cap and the salt allowance at true-up are rounded half-up per application and per site respectively. Where a rule calls for a floor — the performance-credit cap and the subcontractor reliability score — the value is rounded down to a whole unit.

Inch-denominated quantities — `trigger_depth_inches`, `reported_accumulation_inches`, `accumulation_inches`, `quantity_lbs`, and the derived `effective_trigger_depth_inches` and `applied_trigger_depth_inches` — carry exactly two decimal places. Datetimes compared against SLA deadlines and eligibility windows are evaluated at second precision.

### 2.7. Optimistic Concurrency Control on Contract-Scoped Writes

Two creation endpoints guard against stale writes on the parent Contract. A request to create a ContractAmendment must carry `expected_contract_version`, holding the contract `version` the client last observed; if that value does not equal the contract's current `version`, the request is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412). This guard matters because a successful amendment creation supersedes the previously PENDING amendment — a stale writer would otherwise discard an amendment it never observed. The same rule governs SeasonalTrueUp creation: the request must carry `expected_contract_version` matching the contract's current `version`, and a mismatch is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412), because a successful true-up creation supersedes the previously DRAFT true-up. Endpoints other than these two creation operations do not take a version field.

### 2.8. Order of Validation

Every request is checked against the following tiers in the order listed, and when several checks would fail at once, the earliest tier in this order produces the returned error. First, authentication: the presence of `X-User-Role` and `X-User-ID` and membership of the role in the known role set, failing as `ERR_UNAUTHENTICATED`. Second, authorization: the caller's role must appear in the endpoint's authorized list, failing as `ERR_UNAUTHORIZED_ROLE`. Third, existence: every identifier in the path and body must resolve to an existing resource, validated left to right, failing as `ERR_NOT_FOUND`. Fourth, entity-backed ownership: a `ClientContact` may act only on its own client's sites, contracts, invoices, and claims, and a `Subcontractor` only on its own coverage assignments and assigned visits, failing as `ERR_FORBIDDEN_OWNERSHIP`. Fifth, state legality: the target resource's state machine must allow the requested transition, failing as `ERR_INVALID_STATE`, and a resource already in a terminal state rejects every transition with `ERR_ALREADY_TERMINAL`. Sixth, optimistic concurrency: `expected_contract_version` must equal the contract's current `version` on amendment and true-up creation, failing as `ERR_STALE_CONTRACT_VERSION`. Seventh, segregation of duties on dispute resolution: the resolver must differ from both the invoice issuer and the visit completer, failing as `ERR_DISPUTE_SEGREGATION`. Eighth, the documentation gate: a claim's completeness score must reach its floor before it can be documented, failing as `ERR_DOCUMENTATION_INCOMPLETE`. Ninth, schema sanity: required fields for the contract type, enum membership, well-formed windows with end after start, and rejection of unknown fields, all failing as `ERR_INVALID_REQUEST`. Tenth, material quantity must be positive, failing as `ERR_INVALID_QUANTITY`. Eleventh, subcontractor capability must cover the equipment the work requires, failing as `ERR_CAPABILITY_MISMATCH`. Twelfth, uniqueness: route priority per contract, one live invoice per event or period, and one live coverage per subcontractor-event-contract triple, failing as `ERR_PRIORITY_SEQUENCE_CONFLICT`, `ERR_DUPLICATE_INVOICE`, or `ERR_DUPLICATE_COVERAGE`. Thirteenth, contract-type conditional operations: event invoices, period invoices, and true-ups each belong to exactly one contract type, failing as `ERR_CONTRACT_TYPE_FORBIDS`. Fourteenth, aggregate content rules: an invoice needs at least one line, an evidence submission needs a note or photos, a disputed visit must be a line of the invoice, activation needs at least one linked site, and an amendment needs at least one change field, failing as `ERR_INVOICE_EMPTY`, `ERR_EVIDENCE_REQUIRED`, `ERR_DISPUTE_LINE_NOT_FOUND`, `ERR_CONTRACT_HAS_NO_SITES`, or `ERR_INVALID_REQUEST`. Fifteenth through nineteenth are the temporal rules in order: season-window overlap per site (`ERR_SEASON_WINDOW_OVERLAP`), coverage-window overlap per subcontractor (`ERR_COVERAGE_OVERLAP`), the same-site re-service buffer (`ERR_VISIT_GAP_CONFLICT`), the post-completion photo acceptance window (`ERR_PHOTO_WINDOW_EXPIRED`), and the remaining temporal windows — challenge, amendment effectivity, claim coverage, and observation eligibility — failing as `ERR_CHALLENGE_WINDOW_EXPIRED`, `ERR_AMENDMENT_WINDOW_INVALID`, `ERR_CLAIM_WINDOW_EXPIRED`, or `ERR_OBSERVATION_OUT_OF_WINDOW`. Twentieth, the cross-entity state gates, failing as `ERR_EVENT_NOT_VERIFIED`, `ERR_SUBCONTRACTOR_NOT_APPROVED`, `ERR_CONTRACT_NOT_ACTIVE`, `ERR_RENEWAL_BLOCKED`, `ERR_EVENT_LOCKED_BY_INVOICE`, `ERR_NO_BACKUP_AVAILABLE`, `ERR_PHOTO_REQUIRED`, `ERR_NO_NEW_EVIDENCE`, `ERR_CONTRACT_HAS_OPEN_WORK`, or `ERR_INVALID_STATE` as each gate specifies. Twenty-first and last, the fiscal gates, failing as `ERR_CLIENT_CREDIT_EXCEEDED`, `ERR_OVERPAYMENT`, `ERR_INVOICE_HAS_PAYMENTS`, or `ERR_SETTLEMENT_MISMATCH`.

### 2.9. Cross-Entity Cascades and Accumulator Recomputation

State changes in this system rarely stay local. Storm verification re-evaluates the billing of every completed visit under the event and then recomputes the owning contracts' season accumulators; a coverage failure cascades affected visits into backup-seeking; invoice issue and void move money through the client's credit exposure and the contract's billed totals; dispute resolution credits invoices and settles or writes off visits. The contract's derived accumulator fields — `season_billable_push_count`, `season_billable_minutes`, `season_billed_cents`, `unbilled_billable_cents`, `season_sla_miss_count`, and `overage_active` — together with the client's `credit_exposure_cents`, are recomputed immediately whenever an underlying fact changes; consistency is immediate, never deferred. Snapshots, once frozen, are never rewritten by later amendments or recomputations: a visit's `applied_trigger_depth_inches` and `applied_per_push_rate_cents` freeze at completion, a material row's `rate_per_lb_cents_snapshot` freezes at log time, an invoice's `lines` freeze at issue, and a true-up's computed components freeze at issue. Mutations driven by these cascades refresh `updated_at` and increment `version` on every entity they touch, exactly like client-initiated mutations.

### 2.10. Resource Addressing and Identifier Resolution

The API is flat: every resource is created against a top-level collection with its relationships carried as foreign keys in the request body — a visit creation payload, for instance, carries `storm_event_id` and `contract_site_id` rather than nesting under either parent. Whether identifiers arrive in the URL path or the request body, they are resolved left to right, and the first identifier that does not resolve to an existing resource is rejected with `ERR_NOT_FOUND` (HTTP 404) before any later identifier or business rule is evaluated. Collection endpoints nested under a parent resource — for example listing the sites of a client or the site links of a contract — validate the parent's existence first.

## 3. Business Logic & Workflows

### 3.1. Onboarding the Portfolio: Clients, Sites, and Seasonal Agreements

An `OpsDispatcher` onboards a property manager by creating a Client with the organization's `name` and a `credit_limit_cents` ceiling on outstanding billed exposure. The client's `credit_exposure_cents` starts at zero and is thereafter computed as the sum, over the client's invoices in `ISSUED`, `PARTIALLY_CREDITED`, or `PARTIALLY_PAID` status, of each invoice's `total_cents` minus its `paid_cents`; the issue-time fiscal gate in §3.7 compares against this figure with a less-than-or-equal test, so exposure may equal the limit but never exceed it.

Sites are the unit of service. A site is created with its owning `client_id`, a display `name`, a street `address`, a `region_code` that must match a storm event's `region_code` for the event to cover the site, a `pavement_area_sqft` plowable area that drives the area-normative material cap at true-up, and a `requires_loader` flag — defaulting to false — that marks the site as needing loader-class equipment and therefore gates subcontractor capability. An `OpsDispatcher` may create any site; a `ClientContact` may create sites only under its own client.

Contracts come in three kinds, selected by `contract_type`: `PER_PUSH`, `SEASONAL`, or `HOURLY`. Creation requires the `client_id`, the type, and a closed coverage interval from `season_start` through `season_end` (the start must not be later than the end, and both endpoints are included in the covered season). Each type demands its own rate fields: a `PER_PUSH` contract must carry `per_push_rate_cents`; a `HOURLY` contract must carry both `hourly_rate_cents` and `hourly_tier2_rate_cents`; a `SEASONAL` contract must carry `seasonal_fee_cents`, `seasonal_push_cap`, and `seasonal_overage_rate_cents`. A creation that omits a type-required field fails schema sanity with `ERR_INVALID_REQUEST`. The remaining commercial terms take defaults when omitted: `trigger_depth_inches` defaults to 2.00 inches (verified accumulation of at least this depth makes pushes billable), `hourly_tier_threshold_minutes` defaults to 2,400 minutes — forty hours of cumulative season billable time billed at tier 1 before tier 2 pricing takes over — `night_premium_pct` defaults to 0.25, `sla_miss_penalty_cents` defaults to 15000, `require_photo_verification` defaults to true, and the three material rate fields `salt_rate_per_lb_cents`, `blend_rate_per_lb_cents`, and `brine_rate_per_lb_cents` default to 25, 60, and 35 cents per pound respectively. A contract may also record a `prior_contract_id` when it is a renewal copy; the system sets `renewed_to_contract_id` on the expired source at renewal time, and both fields are nullable. A new contract is born in `DRAFT` with `version` 1 and every season accumulator at zero: `season_billable_push_count`, `season_billable_minutes`, `season_billed_cents`, `unbilled_billable_cents`, and `season_sla_miss_count` all start at 0, and `overage_active` starts false.

A site joins a contract through a ContractSite link carrying `contract_id`, `site_id`, a `priority_sequence` route-ordering key, and a `completion_target_minutes` SLA target that must be greater than zero. The `priority_sequence` is unique within a contract — a duplicate is rejected with `ERR_PRIORITY_SEQUENCE_CONFLICT` — and lower values are serviced first. Two optional per-site overrides are available: `trigger_depth_inches` and `per_push_rate_cents`, both nullable. The link resolves `effective_trigger_depth_inches` to the site override when set and to the contract's `trigger_depth_inches` otherwise, and `effective_per_push_rate_cents` likewise from the override or the contract rate. A `salt_included_lbs` allowance, defaulting to zero, records how many pounds of salt the seasonal fee already covers; it is converted to cents at true-up. Linking is guarded by the season-overlap rule, which is enforced both when a link is created and again when the contract is activated: two contracts in `ACTIVE` or `SUSPENDED` status may not cover the same site over intersecting closed season intervals, and because the intervals are closed, seasons that merely touch at an endpoint still conflict — a violation is rejected with `ERR_SEASON_WINDOW_OVERLAP`.

### 3.2. The Contract Lifecycle: Activation, Suspension, Amendment, Expiry, Renewal

A contract's `status` walks `DRAFT` to `ACTIVE`, optionally back and forth through `SUSPENDED`, and finally to terminal `EXPIRED`. Activation — performed by an `OpsDispatcher` — requires at least one ContractSite linked to the contract, failing as `ERR_CONTRACT_HAS_NO_SITES` when none exists, and re-runs the per-site season-overlap check of §3.1 against every linked site. Suspension takes `ACTIVE` to `SUSPENDED` and blocks new visit creation for the contract while it lasts (rejected with `ERR_CONTRACT_NOT_ACTIVE`); resumption takes `SUSPENDED` back to `ACTIVE`. Each of these transitions increments the contract's `version` by one.

Expiry is available from either `ACTIVE` or `SUSPENDED`, by explicit dispatcher action and also automatically during the storm close-sweep described in §3.3. It requires the logical clock to be strictly later than `season_end` — expiring at or before season end fails as `ERR_INVALID_STATE` — and no visit of the contract may remain in `SCHEDULED`, `IN_PROGRESS`, or `AWAITING_BACKUP`, failing as `ERR_CONTRACT_HAS_OPEN_WORK`. `EXPIRED` is terminal: the contract never leaves it.

Renewal is create-with-copy. Renewing an expired contract spawns a brand-new contract in `DRAFT` carrying the same `client_id`, `contract_type`, and rate terms unless the renewal payload overrides them (the payload may carry a new `season_start` and `season_end` plus optional replacements for `trigger_depth_inches`, `per_push_rate_cents`, `hourly_rate_cents`, `hourly_tier2_rate_cents`, `seasonal_fee_cents`, `seasonal_push_cap`, `seasonal_overage_rate_cents`, and `sla_miss_penalty_cents`). The new contract's `prior_contract_id` points at the source; the source's `renewed_to_contract_id` is set to the new id and its `version` increments by one, while the source itself remains `EXPIRED` forever. Renewal is refused while any true-up of the contract is still `DRAFT` or `ISSUED` — rejected with `ERR_RENEWAL_BLOCKED` — and the new `season_start` must be strictly later than the source contract's `season_end`.

Mid-season commercial changes travel through ContractAmendment. Creating one names the `contract_id`, carries the OCC guard `expected_contract_version` per §2.7, and records an `effective_from` marker that must fall strictly after `season_start` and no later than `season_end`, failing as `ERR_AMENDMENT_WINDOW_INVALID` otherwise. At least one of the four change fields — `trigger_depth_inches`, `per_push_rate_cents`, `sla_miss_penalty_cents`, `require_photo_verification` — must be present and non-null, failing as `ERR_INVALID_REQUEST` when all are absent. Exactly one amendment per contract may be `PENDING` at any time: a successful creation moves any previously `PENDING` amendment of the same contract to `SUPERSEDED`, and the creation itself increments the contract's `version` by one. Approving a pending amendment requires the parent contract to be `ACTIVE` — otherwise `ERR_CONTRACT_NOT_ACTIVE` — applies each non-null change field onto the contract, increments the contract's `version` again, and deliberately leaves completed visits untouched: their frozen `applied_trigger_depth_inches` and `applied_per_push_rate_cents` snapshots mean there is no retroactive repricing. Rejection moves `PENDING` to `REJECTED` with no side effects. `APPROVED`, `REJECTED`, and `SUPERSEDED` are all terminal.

### 3.3. Storm Events and Weather Verification

When snow threatens a region, an `OpsDispatcher` reports a StormEvent with its `region_code`, a snowfall window from `window_start` to `window_end` (the end must be strictly later than the start), an initial `reported_accumulation_inches` at two decimal places, and the `reported_source_name` behind that initial figure. The event is born `REPORTED`; SLA deadlines across the region anchor to its `window_end`.

Weather data arrives as an append-only feed of WeatherObservation rows ingested by `PlatformAdmin`. Each observation names its `storm_event_id` and `source_name` (NOAA, DTN, ON_SITE_SENSOR, and similar labels), carries an `observed_at` reading timestamp and an `accumulation_inches` storm-total reading at two decimal places that must be greater than zero, and may carry an optional `note`. The reading must fall inside the closed eligibility window — from `window_start` through six hours after `window_end`, both ends inclusive — or it is rejected with `ERR_OBSERVATION_OUT_OF_WINDOW`.

Verification is the pivot on which billing turns. Verifying a `REPORTED` event requires at least two distinct `source_name` values among the observations eligible inside that window, failing as `ERR_VERIFICATION_QUORUM`. On success the event becomes `VERIFIED`; `verified_accumulation_inches` is set to the accumulation of the eligible observation with the latest `observed_at`, with ties broken in favor of the most recently created observation; `verified_at` is stamped from the logical clock; and the ids of the eligible observations are recorded in `verifying_observation_ids`. Verification then cascades in three levels. At the first level, every completed visit under the event re-evaluates its billing, moving from `PENDING` to `BILLABLE_CONFIRMED` or `NON_BILLABLE` per the trigger rule of §3.7. At the second level, each flipped visit's owning contract recomputes `season_billable_push_count`, `unbilled_billable_cents`, and `season_billable_minutes`. At the third level, `SEASONAL` contracts recompute `overage_active`, and `DRAFT` invoices covering the event recompute their `lines`, `subtotal_cents`, and `total_cents`.

A client who disagrees with a verified reading may challenge it. Challenging — a `ClientContact` action carrying a `reason` — requires the challenging client to hold at least one contract-site whose site's `region_code` matches the event's, failing as `ERR_FORBIDDEN_OWNERSHIP`, and the logical clock must be no later than forty-eight hours after `verified_at`, inclusive, failing as `ERR_CHALLENGE_WINDOW_EXPIRED`. A successful challenge moves the event from `VERIFIED` to `CHALLENGED`, records `challenged_at`, `challenged_by_client_id`, and `challenge_reason`, and reverts every visit in `BILLABLE_CONFIRMED` under the event back to `PENDING` — visits already `INVOICED` or further along are untouched, because their money has moved and must be corrected through the dispute flow of §3.8 instead. Contract accumulators recompute for the flipped visits.

Re-verification closes the loop: a `CHALLENGED` event returns to `VERIFIED` once the quorum is met again and at least one eligible observation was created strictly later than `challenged_at` — without such fresh evidence the attempt fails as `ERR_NO_NEW_EVIDENCE`. A successful re-verification runs the same three-level cascade using the recomputed latest-observation value, which can carry a visit from `NON_BILLABLE` back to `BILLABLE_CONFIRMED` when the new verified accumulation meets the trigger.

The close-sweep is the operations checkpoint that ends an event. Sweeping a `VERIFIED` event stamps `closed_at`, moves it to `CLOSED`, and marks every visit still `SCHEDULED` or `AWAITING_BACKUP` whose `sla_deadline_at` has already passed as `MISSED` — each such visit gets `sla_miss` set true, its billing forced to `NON_BILLABLE`, and one added to its contract's `season_sla_miss_count`. Visits still `IN_PROGRESS` are never sweep-marked; they may complete later, and a late completion sets `sla_miss` then. The same sweep expires every contract whose `season_end` has passed and which has no open work. The sweep response reports `visits_marked_missed` and `contracts_expired`.

Finally, a `PlatformAdmin` may void an event entirely. Voiding a `REPORTED` or `CHALLENGED` event cancels its visits in `SCHEDULED` or `AWAITING_BACKUP` (they become `CANCELLED`) while completed visits keep their execution record but drop to `NON_BILLABLE`. Voiding a `VERIFIED` event additionally requires that no `ISSUED`-or-later invoice references it, failing as `ERR_EVENT_LOCKED_BY_INVOICE`; when allowed, its `BILLABLE_CONFIRMED` visits become `NON_BILLABLE`, `DRAFT` invoices referencing the event become `VOIDED`, and contract accumulators recompute. `VOIDED` events are excluded from every billing projection.

### 3.4. Subcontractor Coverage and Equipment-Failure Backup

An `OpsDispatcher` registers a subcontractor with its `legal_name`, dispatch `contact_email`, and two capability flags, `has_loader` and `has_brine_truck`, both defaulting to false. The record is born `PENDING` with `assignments_released_count`, `assignments_failed_count`, and `active_assignment_count` all at zero. A `PlatformAdmin` approves `PENDING` to `APPROVED`, may suspend an `APPROVED` subcontractor to `SUSPENDED`, and may re-approve a `SUSPENDED` one back to `APPROVED`. Suspension leaves already-`ACTIVE` coverage assignments untouched but blocks any new activation with `ERR_SUBCONTRACTOR_NOT_APPROVED`.

Coverage for a storm is arranged per contract. Creating a CoverageAssignment names `storm_event_id`, `contract_id`, and `subcontractor_id`, plus a half-open coverage window from `coverage_start` to `coverage_end` — the end exclusive, the end strictly later than the start — which must overlap the event's window. The subcontractor's capabilities must cover every loader-requiring site of the contract, failing as `ERR_CAPABILITY_MISMATCH`. At most one non-terminal coverage may exist for the same subcontractor, event, and contract triple, failing as `ERR_DUPLICATE_COVERAGE`. And no two `CREATED` or `ACTIVE` assignments of the same subcontractor may overlap in time under half-open semantics — back-to-back adjacency, where one window ends exactly as another begins, is legal — failing as `ERR_COVERAGE_OVERLAP`; this overlap check runs both at creation and again at activation.

Activation is self-service: the subcontractor itself moves `CREATED` to `ACTIVE`, which requires its `X-User-ID` to equal the assignment's `subcontractor_id` (failing as `ERR_FORBIDDEN_OWNERSHIP`), its own status to be `APPROVED`, and the overlap check above to pass. Activation adds one to `active_assignment_count`.

Release is the dispatcher's off-ramp and comes in two shapes with equal standing. From `CREATED`, releasing simply cancels the assignment to `CANCELLED` with no counters affected. From `ACTIVE`, releasing to `RELEASED` requires the storm event to be `CLOSED` or every visit assigned via this coverage to be in a terminal execution state, failing as `ERR_INVALID_STATE`; on success `active_assignment_count` drops by one, `assignments_released_count` rises by one, and `reliability_score` recomputes.

Failure is the interesting path. An equipment failure — reported by the subcontractor itself or by an `OpsDispatcher`, recording a `failure_reason` — moves an `ACTIVE` assignment to `FAILED` and fires a three-level cascade. First, every `SCHEDULED` visit assigned to this subcontractor under this event drops its `assigned_subcontractor_id` to null and moves to `AWAITING_BACKUP`, awaiting the reassign flow of §3.5. Second, `active_assignment_count` drops by one, `assignments_failed_count` rises by one, and `reliability_score` recomputes as one hundred times the released count divided by the sum of released and failed — with the denominator guarded so that zero counts as one — rounded down to a whole number between 0 and 100. Third, once the subcontractor's released plus failed assignments reach at least 3, a `reliability_score` below 70 automatically moves the subcontractor to `SUSPENDED`.

### 3.5. Service Visit Execution

Work happens in ServiceVisits. Scheduling one — an `OpsDispatcher` action — supplies `storm_event_id`, `contract_site_id`, `scheduled_start`, and `scheduled_end` (the end strictly later than the start), and may optionally pre-assign a subcontractor via `assigned_subcontractor_id`. The contract must be `ACTIVE`, failing as `ERR_CONTRACT_NOT_ACTIVE`; the storm event must be in `REPORTED`, `VERIFIED`, or `CHALLENGED`, failing as `ERR_INVALID_STATE`; and a named subcontractor must hold `ACTIVE` coverage for this event and contract, again failing as `ERR_INVALID_STATE`. Creation denormalizes `contract_id` and `site_id` from the contract-site link onto the visit, computes `sla_deadline_at` as the storm's `window_end` plus the link's `completion_target_minutes`, and starts the visit with `execution_status` `SCHEDULED` and `billing_status` `PENDING`. A buffer rule protects the same pavement from double-booking: for the same site — regardless of contract — a new visit conflicts with any existing non-`CANCELLED` visit unless the new `scheduled_start` is at least ninety minutes after the existing visit's `scheduled_end`, or the new `scheduled_end` is at least ninety minutes before the existing visit's `scheduled_start`; a gap of exactly ninety minutes is legal on either side, and a violation is rejected with `ERR_VISIT_GAP_CONFLICT`.

Within an event, a route plan orders the work: for a given contract, every visit in `SCHEDULED`, `IN_PROGRESS`, or `AWAITING_BACKUP` is ordered by its contract-site's `priority_sequence` ascending — unique per contract, so no tie is possible — and each entry is assigned a `route_order` counting upward from 1.

Starting a visit moves `SCHEDULED` to `IN_PROGRESS` and stamps `actual_start_at` from the logical clock. Crew ownership is enforced here and at completion: a `CrewLead` may start or complete only an in-house visit whose `assigned_subcontractor_id` is null, while a `Subcontractor` caller's id must equal the visit's `assigned_subcontractor_id` — violations fail as `ERR_FORBIDDEN_OWNERSHIP`.

Completing a visit moves `IN_PROGRESS` to `COMPLETED`. Like scheduling, completion requires the parent contract to be `ACTIVE`, failing as `ERR_CONTRACT_NOT_ACTIVE`. When the contract's `require_photo_verification` is true, at least one `AFTER` photo of the visit with `review_status` `ACCEPTED` must exist, failing as `ERR_PHOTO_REQUIRED`. Completion stamps `completed_at`, records the caller as `completed_by_user_id`, and freezes the `applied_trigger_depth_inches` and `applied_per_push_rate_cents` snapshots from the effective values at that moment — later amendments never reprice this visit. The SLA verdict is then rendered: `sla_miss` is true when `completed_at` is strictly later than `sla_deadline_at`, and completing exactly at the deadline counts as on time; a miss adds one to the contract's `season_sla_miss_count`. When the storm event is already `VERIFIED` or `CLOSED`, billing evaluates immediately at completion — the visit moves from `PENDING` to `BILLABLE_CONFIRMED` or `NON_BILLABLE` with the second- and third-level cascades of §3.3.

Three more outcomes round out execution. A dispatcher may cancel a `SCHEDULED` visit to `CANCELLED` outright. A dispatcher may also void a `COMPLETED` visit to `VOIDED`, but only while its billing has not reached `INVOICED`, `DISPUTED`, `SETTLED`, or `WRITTEN_OFF` — otherwise the invoice or dispute flow must resolve first and the attempt fails as `ERR_INVALID_STATE`; voiding forces billing to `NON_BILLABLE`, voids every `RECORDED` material row of the visit so `material_cost_cents` returns to zero, recomputes the contract's `season_billable_push_count`, `season_billable_minutes`, and `unbilled_billable_cents`, and — if the visit's `sla_miss` had been true — subtracts one from `season_sla_miss_count`. And when a covering assignment fails, the system itself moves the affected `SCHEDULED` visits to `AWAITING_BACKUP` as described in §3.4.

Reassignment rescues a waiting visit. Reassigning — an `OpsDispatcher` action that may name a `preferred_subcontractor_id` — moves `AWAITING_BACKUP` back to `SCHEDULED` with a selected backup. The eligible pool contains every subcontractor that is `APPROVED`, that has a loader when the site requires one, that holds no `CREATED` or `ACTIVE` coverage overlapping the event window under half-open semantics, and that has no `FAILED` coverage for this storm event — a failed subcontractor is never retried on the same event. The pool is ranked by fewest `CREATED`-or-`ACTIVE` assignments for this event, ties broken by earliest subcontractor `created_at`; the selector is deterministic and never ordered by id. A named `preferred_subcontractor_id` must satisfy the same eligibility, surfacing `ERR_CAPABILITY_MISMATCH`, `ERR_SUBCONTRACTOR_NOT_APPROVED`, or `ERR_COVERAGE_OVERLAP` as applicable. An empty pool fails the reassignment with `ERR_NO_BACKUP_AVAILABLE` and the visit stays `AWAITING_BACKUP`. On success the visit's `assigned_subcontractor_id` becomes the backup, `grace_extended` flips to true, `sla_deadline_at` is extended by two hours, and a fresh CoverageAssignment for the event, contract, and backup is created directly in `ACTIVE` status spanning the event window.

### 3.6. Material Logging and Photo Evidence

Crews log de-icing material as they spread it. Logging an application — by the `CrewLead` of an in-house visit or the assigned `Subcontractor` — names the `visit_id`, a `material_type` of `ROCK_SALT`, `ICE_MELT_BLEND`, or `LIQUID_BRINE`, and a `quantity_lbs` at two decimal places that must be strictly greater than zero, failing as `ERR_INVALID_QUANTITY`. The parent contract must be `ACTIVE`, failing as `ERR_CONTRACT_NOT_ACTIVE`. At log time the applicable contract rate — `salt_rate_per_lb_cents` for rock salt, `blend_rate_per_lb_cents` for ice-melt blend, or `brine_rate_per_lb_cents` for liquid brine — is frozen into `rate_per_lb_cents_snapshot`, and the acting user's id is recorded as `logged_by_user_id`. Each application's `line_cost_cents` is its `quantity_lbs` multiplied by that frozen snapshot, rounded half-up to a whole cent per line before any summation; the visit's `material_cost_cents` is then the sum of `line_cost_cents` over its `RECORDED` rows. The order is pinned — round per line, then sum — because summing first and rounding once yields a different, incorrect result. Logging or voiding a line also recomputes the lines of any `DRAFT` invoice that covers the visit.

A material row may be voided from `RECORDED` to `VOIDED` by the crew lead or a dispatcher, but only while the parent visit's billing has not reached `INVOICED`, `DISPUTED`, `SETTLED`, or `WRITTEN_OFF`, failing as `ERR_INVALID_STATE`; the visit's `material_cost_cents` recomputes with the voided line excluded.

Photographic evidence follows the visit. Uploading a photo names the `visit_id`, a `phase` of `BEFORE` or `AFTER`, and an `image_uri` object-storage reference; the parent contract must be `ACTIVE`, failing as `ERR_CONTRACT_NOT_ACTIVE`. `BEFORE` photos are accepted while the visit is `SCHEDULED` or `IN_PROGRESS`, while `AFTER` photos are accepted only while the visit is `IN_PROGRESS`. Each upload is born with `review_status` `UPLOADED`. Review is a dispatcher function: accepting moves `UPLOADED` to `ACCEPTED`, rejecting moves it to `REJECTED`, both record `reviewed_by_user_id`, and both outcomes are terminal. Once the parent visit is `COMPLETED`, an `AFTER` photo remains acceptable only while the logical clock is no later than six hours after `completed_at`, inclusive — beyond that the accept attempt fails as `ERR_PHOTO_WINDOW_EXPIRED`.

### 3.7. Visit Billing, Invoicing, and Payments

Every visit carries a billing lifecycle independent of its execution until the coupling rules fire. A visit's `billing_status` moves from `PENDING` to `BILLABLE_CONFIRMED` when execution is `COMPLETED` and the event's `verified_accumulation_inches` is at least the applicable trigger depth — the visit's own `applied_trigger_depth_inches` snapshot when frozen, otherwise the contract-site's `effective_trigger_depth_inches` — with the comparison inclusive, so accumulation exactly equal to the trigger is billable. When the trigger is not met, or execution ends anywhere other than `COMPLETED`, the visit falls to `NON_BILLABLE`. A challenge sends `BILLABLE_CONFIRMED` back to `PENDING`; a later re-verification whose new accumulation meets the trigger lifts a `NON_BILLABLE` visit back to `BILLABLE_CONFIRMED`, provided it is `COMPLETED`.

The charge itself depends on contract type. For `PER_PUSH`, the visit's `billable_amount_cents` is simply the frozen `applied_per_push_rate_cents`. For `HOURLY`, elapsed time from `actual_start_at` to `completed_at` is rounded up to whole six-minute increments to produce `billable_minutes`; tier allocation is chronological across the season, ordered by `actual_start_at` and then by `created_at` — never by completion order. Of the visit's minutes, the portion billed at tier 1 is the headroom remaining under `hourly_tier_threshold_minutes` after accounting for all chronologically earlier billable visits of the contract, never less than zero and never more than the visit's own minutes; the remainder bills at tier 2. Each tier's amount — minutes times rate divided by sixty — is rounded half-up per tier before the two are summed into the base. When the visit's `actual_start_at` hour in UTC is 22, 23, or 0 through 5, `night_premium_applied` is true and the summed base is multiplied by one plus `night_premium_pct`, with the final amount rounded half-up — the premium rounds last. For `SEASONAL`, in-season visits carry a `billable_amount_cents` of zero; their economics settle at true-up in §3.9.

The contract's season accumulators track this work: `season_billable_push_count` counts the contract's visits with billing in `BILLABLE_CONFIRMED`, `INVOICED`, `DISPUTED`, or `SETTLED`; `season_billable_minutes` sums `billable_minutes` over that same set and feeds hourly tiering; `unbilled_billable_cents` sums `billable_amount_cents` plus `material_cost_cents` over visits sitting in `BILLABLE_CONFIRMED`; `season_billed_cents` sums `total_cents` over the contract's invoices in `ISSUED`, `PARTIALLY_CREDITED`, `PARTIALLY_PAID`, or `PAID`; and `overage_active` — meaningful only for `SEASONAL` — flips true once `season_billable_push_count` exceeds `seasonal_push_cap`.

Two read models expose the money before it moves. The billing preview projects both an optimistic and a conservative season: the `provisional_billable_push_count` and `provisional_billable_cents` count `REPORTED` and `CHALLENGED` events at their `reported_accumulation_inches` and `VERIFIED` or `CLOSED` events at `verified_accumulation_inches`, while the `final_billable_push_count` and `final_billable_cents` count only `VERIFIED` and `CLOSED` events — mirroring exactly what invoicing may bill. `VOIDED` events are excluded from both. In either variant a push counts only when the applicable depth meets the effective trigger and the visit is `COMPLETED`, and the cents total sums each billable visit's per-type charge plus its `material_cost_cents`. The true-up preview is described in §3.9.

Invoices are generated per contract with a `kind` that must match the contract type: an `EVENT` invoice bills a single storm and is for `PER_PUSH` contracts; a `PERIOD` invoice bills a time window and is for `HOURLY` contracts; any other pairing fails as `ERR_CONTRACT_TYPE_FORBIDS`. An `EVENT` invoice requires `storm_event_id` and requires that event to be `VERIFIED` or `CLOSED`, failing as `ERR_EVENT_NOT_VERIFIED`. A `PERIOD` invoice requires `period_start` and `period_end`, and covers visits whose `completed_at` falls at or after `period_start` and strictly before `period_end` — a half-open window. Uniqueness is enforced per contract: one non-`VOIDED` `EVENT` invoice per storm event, and one non-`VOIDED` `PERIOD` invoice per `period_start`, failing as `ERR_DUPLICATE_INVOICE`. An invoice is born `DRAFT`; its `lines` contain, for each eligible visit in `BILLABLE_CONFIRMED` belonging to the contract, one `SERVICE` line carrying the visit's `billable_amount_cents` plus one `MATERIAL` line when the visit's `material_cost_cents` is greater than zero. `subtotal_cents` is the sum of the lines, `credit_cents` starts at zero, `total_cents` is the subtotal minus the credit, and `paid_cents` starts at zero. While `DRAFT`, the lines recompute live on every underlying visit billing change.

Issuing moves `DRAFT` to `ISSUED` and is the fiscal point of no return. The invoice must contain at least one line, failing as `ERR_INVOICE_EMPTY`. The contract must be `ACTIVE` — or, if `EXPIRED`, the logical clock must be no later than sixty days past `season_end`, inclusive — failing as `ERR_INVALID_STATE`. And the client's `credit_exposure_cents` plus the invoice's `total_cents` must be less than or equal to the client's `credit_limit_cents`, failing as `ERR_CLIENT_CREDIT_EXCEEDED`. On issue, the lines freeze so that later visit changes never mutate the invoice; every line visit moves from `BILLABLE_CONFIRMED` to `INVOICED`; `issued_at` and `issued_by_user_id` are recorded; the contract's `season_billed_cents` grows by `total_cents` and the client's `credit_exposure_cents` grows by the same amount; and the contract's `version` increments by one.

Payments are recorded against an issued invoice by carrying `amount_cents`, which must be greater than zero and no more than the remaining balance — `total_cents` minus `paid_cents` — failing as `ERR_OVERPAYMENT`. A partial payment moves `ISSUED` to `PARTIALLY_PAID`, and further partial payments keep the invoice in `PARTIALLY_PAID` while reducing the remainder. A payment exactly equal to the remaining balance settles the invoice to `PAID`, whether from `ISSUED`, `PARTIALLY_PAID`, or `PARTIALLY_CREDITED`. Every recorded payment raises `paid_cents` and lowers the client's `credit_exposure_cents` by the paid amount.

Voiding reverses an invoice. A `DRAFT` invoice may be voided freely — and is voided automatically when its storm event is voided. Voiding an `ISSUED`, `PARTIALLY_PAID`, or `PARTIALLY_CREDITED` invoice — three sibling branches with identical guards — requires `paid_cents` to be exactly zero, failing as `ERR_INVOICE_HAS_PAYMENTS`, and requires that no dispute of the invoice be in `OPEN` or `EVIDENCE_REVIEW`, failing as `ERR_INVALID_STATE`. The compensation is symmetric: the contract's `season_billed_cents` and the client's `credit_exposure_cents` each drop by `total_cents`, every line visit returns from `INVOICED` to `BILLABLE_CONFIRMED`, and the contract's `version` increments by one. For a `PARTIALLY_PAID` invoice the zero-payments guard is unreachable in practice — partial payment implies money received — but the guard is declared there so the fiscal rule, not an accident of state, owns the rejection.

### 3.8. Disputes and Slip-and-Fall Claims

When a client contests a billed line, a `ClientContact` opens a Dispute naming the `invoice_id`, the contested `visit_id`, and a `reason` of `TRIGGER_NOT_MET`, `INCOMPLETE_SERVICE`, `PHOTO_INSUFFICIENT`, `RATE_DISAGREEMENT`, or `MATERIAL_QUANTITY`. The visit must appear among the invoice's lines, failing as `ERR_DISPUTE_LINE_NOT_FOUND`, and the caller may dispute only its own client's invoices, failing as `ERR_FORBIDDEN_OWNERSHIP`. The dispute opens in `OPEN` with `opened_by_client_id` recorded, and the contested visit's billing moves from `INVOICED` to `DISPUTED`.

Evidence ping-pongs. The client submits evidence — an `evidence_note`, a list of `photo_ids` referencing ServicePhoto records, or both, with at least one of the two required, failing as `ERR_EVIDENCE_REQUIRED` — which appends to the dispute's `evidence_items` and moves it from `OPEN` to `EVIDENCE_REVIEW`. A dispatcher who finds the file thin may request more evidence with a `note`, returning the dispute from `EVIDENCE_REVIEW` to `OPEN`, and the cycle may repeat.

Resolution is dispatcher work with a hard segregation-of-duties gate: the resolver's `X-User-ID` must differ from the invoice's `issued_by_user_id` and from the visit's `completed_by_user_id`, failing as `ERR_DISPUTE_SEGREGATION`. Three outcomes exist, each fully specified. Resolving `UPHELD` moves the dispute to `RESOLVED_UPHELD`, applies a `resolution_credit_cents` of zero, and settles the visit's billing from `DISPUTED` to `SETTLED`. Resolving `ADJUSTED` carries a `credit_cents` that must be greater than zero and no more than the visit's combined line amount on this invoice, failing as `ERR_INVALID_REQUEST`; the invoice's `credit_cents` grows by that amount, recomputing `total_cents`, the contract's `season_billed_cents`, and the client's exposure, and moving the invoice to `PARTIALLY_CREDITED`; the visit settles to `SETTLED` and the dispute to `RESOLVED_ADJUSTED`. Resolving `REMOVED` credits the invoice by all of the visit's lines — service and material together — again landing the invoice in `PARTIALLY_CREDITED`, but the visit's billing moves to `WRITTEN_OFF`, one is subtracted from the contract's `season_billable_push_count`, and the remaining accumulators recompute; the dispute closes as `RESOLVED_REMOVED`. In every case `resolved_by_user_id` is recorded, and the three resolved states are terminal.

Slip-and-fall exposure is managed as its own workflow. A `ClientContact` files a SlipFallClaim against one of its own client's sites with the `site_id`, an `incident_at` timestamp, a `severity` of `INJURY_REPORTED`, `PROPERTY_DAMAGE`, or `NEAR_MISS`, and a narrative `description`; the claim is born `FILED`. A `ClaimsAdjuster` then reviews it, moving `FILED` to `DOCUMENTATION_REVIEW`. Review resolves coverage first: some contract in `ACTIVE`, `SUSPENDED`, or `EXPIRED` must cover the site with `season_start` at or before `incident_at` and `incident_at` at or before `season_end`, failing as `ERR_CLAIM_WINDOW_EXPIRED`. The covering contract is recorded as `documentation_contract_id`, and when a storm event's window contains the incident the event is linked as `storm_event_id`, left null otherwise. Review also computes two completeness scores over the linked event's visits at the claim site, from five indicators: an accepted `BEFORE` photo, an accepted `AFTER` photo, material logged, response within target — no `sla_miss` among those visits — and weather verified, meaning the event is `VERIFIED` or `CLOSED`. The `STANDARD` weights are 15 for the before photo, 25 for the after photo, 20 for material, 20 for timeliness, and 20 for weather; the `STRICT` weights are 30, 40, 10, 10, and 10 respectively, so photo evidence carries seventy of the hundred points and a claim without photos cannot pass. Each score is the sum of the weights of the satisfied indicators — the weights sum to one hundred, so no division is needed — and `score_standard` and `score_strict` are both stored. The selected `documentation_completeness_score` is the `STRICT` figure when severity is `INJURY_REPORTED` and the `STANDARD` figure otherwise. Documenting the claim — moving `DOCUMENTATION_REVIEW` to `DOCUMENTED` — requires that selected score to be at least 60, failing as `ERR_DOCUMENTATION_INCOMPLETE`.

Closure is shared between the two roles with distinct outcomes. A `ClaimsAdjuster` closes a claim in `DOCUMENTATION_REVIEW` or `DOCUMENTED` by passing an `outcome` of `CLOSED`. The owning `ClientContact` withdraws a claim in `FILED` or `DOCUMENTATION_REVIEW` by passing an `outcome` of `WITHDRAWN`, permitted only when the caller's client owns the claim's site, failing as `ERR_FORBIDDEN_OWNERSHIP`. For litigation support, a computed documentation bundle assembles the claim's `claim_id`, its `documentation_contract_id` and `storm_event_id`, the `matching_visit_ids` at the site under the linked event, the associated `photo_ids` and `material_application_ids`, the `weather_observation_ids` behind verification, and both `score_standard` and `score_strict`.

### 3.9. Seasonal True-Up and Settlement

When a `SEASONAL` contract reaches `EXPIRED`, its economics close through a SeasonalTrueUp. Creation names the `contract_id` and carries the OCC guard `expected_contract_version` per §2.7. A true-up against a non-`SEASONAL` contract fails as `ERR_CONTRACT_TYPE_FORBIDS`; against a contract not yet `EXPIRED` it fails as `ERR_INVALID_STATE`. At most one true-up per contract may be `DRAFT`: a successful creation moves the previously `DRAFT` true-up to `SUPERSEDED`, and creation increments the contract's `version` by one. A `DRAFT` true-up exits only by being superseded — there is no client-visible discard operation.

Creation computes the settlement components in one pinned order; the dependency chain looks circular but is not. First, the billable set is fixed as the season's visits with billing in `BILLABLE_CONFIRMED`, `INVOICED`, `DISPUTED`, or `SETTLED`, and `billable_push_count` is its size. Second, `overage_pushes` is the count minus `seasonal_push_cap`, floored at zero, and `overage_cents` is that many pushes times `seasonal_overage_rate_cents`. Third, `sla_miss_count` is taken from the contract's season counter. Fourth, `performance_credit_cents` is the smaller of the miss count times `sla_miss_penalty_cents` and one fifth of `seasonal_fee_cents` rounded down to a whole cent — the credit can never exceed twenty percent of the fee. Fifth, materials settle: `material_actual_cents` is the sum of `line_cost_cents` over all `RECORDED` applications of the contract's season visits, while `material_normative_cents` is the area-normative cap — for each `RECORDED` application, the site's `pavement_area_sqft` times the normative rate for its material (0.0023 pounds per square foot for `ROCK_SALT`, 0.0015 for `ICE_MELT_BLEND`, 0.0040 for `LIQUID_BRINE`) times the application's frozen rate snapshot, rounded half-up per application. The prepaid `material_allowance_cents` is the sum over the contract's sites of `salt_included_lbs` times the contract's `salt_rate_per_lb_cents`, rounded half-up per site. `material_settlement_cents` is then the smaller of actual and normative, reduced by the allowance, and never below zero — over-application bills only up to the normative cap, and light application bills only what was logged. Sixth and last, `balance_due_cents` is `overage_cents` plus `material_settlement_cents` minus `performance_credit_cents`. The created true-up is the FINAL variant: only visits under `VERIFIED` or `CLOSED` events count.

During the season, the true-up preview exposes the same machinery in its PROJECTED variant — optimistic, in that `REPORTED` and `CHALLENGED` events count at their reported accumulation — returning `projected_billable_push_count`, `projected_overage_pushes`, `projected_overage_cents`, `projected_material_actual_cents`, `projected_material_normative_cents`, `projected_material_allowance_cents`, `projected_material_settlement_cents`, `projected_sla_miss_count`, `projected_performance_credit_cents`, and `projected_balance_due_cents` alongside the `contract_id`.

Issuing a true-up moves `DRAFT` to `ISSUED`, freezes every computed component, and stamps `issued_at`. Settlement moves `ISSUED` to `SETTLED` and is exact: the `settled_amount_cents` presented must equal `balance_due_cents` to the cent, failing as `ERR_SETTLEMENT_MISMATCH`; success stamps `settled_at` and makes the parent contract eligible for the renewal flow of §3.2.

## 4. Endpoint Definitions

Operations that create a new resource — onboarding a client, creating a site or contract, spawning a renewal contract, linking a contract-site, creating an amendment, reporting a storm event, ingesting an observation, scheduling a visit, logging a material application, uploading a photo, generating an invoice, opening a dispute, filing a claim, registering a subcontractor, creating a coverage assignment, or creating a true-up — return `201 Created`. Operations that modify an existing resource, drive a state transition, or read data return `200 OK`; this includes the logical-clock capability and every lifecycle action. The complete request parameters, preconditions, and side effects of each operation are specified narratively in §2 and §3; this table is the addressing and authorization contract only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock to a supplied instant | PlatformAdmin |
| POST | `/clients` | Onboard a property-manager client | OpsDispatcher |
| GET | `/clients/{id}` | Get a client | PlatformAdmin, OpsDispatcher, ClientContact, ClaimsAdjuster |
| GET | `/clients` | List clients (paginated) | PlatformAdmin, OpsDispatcher |
| GET | `/clients/{id}/sites` | List sites of a client | PlatformAdmin, OpsDispatcher, ClientContact, ClaimsAdjuster |
| POST | `/sites` | Create a service site | OpsDispatcher, ClientContact |
| GET | `/sites/{id}` | Get a site | PlatformAdmin, OpsDispatcher, ClientContact, ClaimsAdjuster, Subcontractor |
| GET | `/sites/{id}/contract-sites` | List contract links of a site | PlatformAdmin, OpsDispatcher, ClientContact, ClaimsAdjuster |
| POST | `/contracts` | Create a contract in DRAFT | OpsDispatcher |
| GET | `/contracts/{id}` | Get a contract | PlatformAdmin, OpsDispatcher, ClientContact, ClaimsAdjuster |
| GET | `/contracts` | List/filter contracts | PlatformAdmin, OpsDispatcher, ClientContact |
| POST | `/contracts/{id}/activate` | Activate a contract (DRAFT to ACTIVE) | OpsDispatcher |
| POST | `/contracts/{id}/suspend` | Suspend a contract (ACTIVE to SUSPENDED) | OpsDispatcher |
| POST | `/contracts/{id}/resume` | Resume a contract (SUSPENDED to ACTIVE) | OpsDispatcher |
| POST | `/contracts/{id}/expire` | Expire a contract once past season end with no open work | OpsDispatcher |
| POST | `/contracts/{id}/renew` | Create a renewal contract in DRAFT copying terms | OpsDispatcher |
| GET | `/contracts/{id}/billing-preview` | Dual provisional/final billable projection | OpsDispatcher, ClientContact |
| GET | `/contracts/{id}/true-up-preview` | Projected seasonal true-up components | OpsDispatcher, ClientContact |
| POST | `/contract-sites` | Link a site into a contract with per-site overrides | OpsDispatcher |
| GET | `/contract-sites/{id}` | Get a contract-site link | PlatformAdmin, OpsDispatcher, ClientContact |
| GET | `/contracts/{id}/contract-sites` | List site links of a contract | PlatformAdmin, OpsDispatcher, ClientContact |
| POST | `/amendments` | Create a PENDING amendment (OCC on contract version) | OpsDispatcher |
| GET | `/contracts/{id}/amendments` | List amendments of a contract | PlatformAdmin, OpsDispatcher, ClientContact |
| POST | `/amendments/{id}/approve` | Approve an amendment and apply its changes | OpsDispatcher |
| POST | `/amendments/{id}/reject` | Reject an amendment | OpsDispatcher |
| POST | `/storm-events` | Report a storm event (REPORTED) | OpsDispatcher |
| GET | `/storm-events/{id}` | Get a storm event | PlatformAdmin, OpsDispatcher, ClientContact, ClaimsAdjuster, Subcontractor, CrewLead |
| GET | `/storm-events` | List/filter storm events | PlatformAdmin, OpsDispatcher, ClientContact, ClaimsAdjuster |
| POST | `/storm-events/{id}/verify` | Verify (or re-verify) an event; runs the billing cascade | OpsDispatcher |
| POST | `/storm-events/{id}/challenge` | Challenge a verified event's accumulation | ClientContact |
| POST | `/storm-events/{id}/void` | Void an event; locked once an issued invoice references it | PlatformAdmin |
| POST | `/storm-events/{id}/close-sweep` | Close a verified event: mark missed visits, expire contracts | OpsDispatcher |
| GET | `/storm-events/{id}/route-plan` | Computed route order for a contract under the event | OpsDispatcher, Subcontractor |
| POST | `/observations` | Append a weather observation (immutable feed) | PlatformAdmin |
| GET | `/storm-events/{id}/observations` | List observations of an event | PlatformAdmin, OpsDispatcher, ClientContact, ClaimsAdjuster |
| POST | `/visits` | Schedule a service visit | OpsDispatcher |
| GET | `/visits/{id}` | Get a visit | PlatformAdmin, OpsDispatcher, ClientContact, ClaimsAdjuster, Subcontractor, CrewLead |
| GET | `/visits` | List/filter visits | PlatformAdmin, OpsDispatcher, ClientContact, ClaimsAdjuster, Subcontractor |
| POST | `/visits/{id}/start` | Start a visit (SCHEDULED to IN_PROGRESS) | CrewLead, Subcontractor |
| POST | `/visits/{id}/complete` | Complete a visit; photo gate, SLA verdict, billing evaluation | CrewLead, Subcontractor |
| POST | `/visits/{id}/cancel` | Cancel a scheduled visit | OpsDispatcher |
| POST | `/visits/{id}/void` | Void a completed visit with billing/material compensation | OpsDispatcher |
| POST | `/visits/{id}/reassign` | Assign a backup subcontractor to a waiting visit | OpsDispatcher |
| POST | `/materials` | Log a material application on a visit | CrewLead, Subcontractor |
| GET | `/visits/{id}/materials` | List material applications of a visit | PlatformAdmin, OpsDispatcher, ClientContact, ClaimsAdjuster, CrewLead, Subcontractor |
| POST | `/materials/{id}/void` | Void a recorded material application | CrewLead, OpsDispatcher |
| POST | `/photos` | Upload a verification photo | CrewLead, Subcontractor |
| GET | `/visits/{id}/photos` | List photos of a visit | PlatformAdmin, OpsDispatcher, ClientContact, ClaimsAdjuster, CrewLead, Subcontractor |
| POST | `/photos/{id}/accept` | Accept an uploaded photo | OpsDispatcher |
| POST | `/photos/{id}/reject` | Reject an uploaded photo | OpsDispatcher |
| POST | `/invoices` | Generate a DRAFT invoice (EVENT or PERIOD) | OpsDispatcher |
| GET | `/invoices/{id}` | Get an invoice | PlatformAdmin, OpsDispatcher, ClientContact, ClaimsAdjuster |
| GET | `/invoices` | List/filter invoices | PlatformAdmin, OpsDispatcher, ClientContact |
| POST | `/invoices/{id}/issue` | Issue an invoice; freezes lines; credit gate | OpsDispatcher |
| POST | `/invoices/{id}/void` | Void an invoice with compensation | OpsDispatcher |
| POST | `/invoices/{id}/pay` | Record a payment against an invoice | OpsDispatcher |
| POST | `/disputes` | Open a dispute against an invoice line | ClientContact |
| GET | `/disputes/{id}` | Get a dispute | PlatformAdmin, OpsDispatcher, ClientContact |
| GET | `/disputes` | List/filter disputes | PlatformAdmin, OpsDispatcher, ClientContact |
| POST | `/disputes/{id}/submit-evidence` | Submit evidence (OPEN to EVIDENCE_REVIEW) | ClientContact |
| POST | `/disputes/{id}/request-evidence` | Request more evidence (EVIDENCE_REVIEW to OPEN) | OpsDispatcher |
| POST | `/disputes/{id}/resolve` | Resolve a dispute; segregation of duties enforced | OpsDispatcher |
| POST | `/slip-fall-claims` | File a slip-and-fall claim against a site | ClientContact |
| GET | `/slip-fall-claims/{id}` | Get a claim | PlatformAdmin, OpsDispatcher, ClientContact, ClaimsAdjuster |
| GET | `/slip-fall-claims` | List/filter claims | PlatformAdmin, OpsDispatcher, ClientContact, ClaimsAdjuster |
| GET | `/slip-fall-claims/{id}/documentation-bundle` | Computed documentation bundle for a claim | PlatformAdmin, OpsDispatcher, ClaimsAdjuster |
| POST | `/slip-fall-claims/{id}/review` | Review a claim; resolve coverage; compute scores | ClaimsAdjuster |
| POST | `/slip-fall-claims/{id}/document` | Mark a claim documented (score gate) | ClaimsAdjuster |
| POST | `/slip-fall-claims/{id}/close` | Close or withdraw a claim | ClaimsAdjuster, ClientContact |
| POST | `/subcontractors` | Register a subcontractor (PENDING) | OpsDispatcher |
| GET | `/subcontractors/{id}` | Get a subcontractor | PlatformAdmin, OpsDispatcher, Subcontractor, ClaimsAdjuster |
| GET | `/subcontractors` | List/filter subcontractors | PlatformAdmin, OpsDispatcher |
| POST | `/subcontractors/{id}/approve` | Approve (or re-approve) a subcontractor | PlatformAdmin |
| POST | `/subcontractors/{id}/suspend` | Suspend a subcontractor | PlatformAdmin |
| POST | `/coverage-assignments` | Create storm coverage for a contract by a subcontractor | OpsDispatcher |
| GET | `/coverage-assignments/{id}` | Get a coverage assignment | PlatformAdmin, OpsDispatcher, Subcontractor |
| GET | `/coverage-assignments` | List/filter coverage assignments | PlatformAdmin, OpsDispatcher, Subcontractor |
| POST | `/coverage-assignments/{id}/activate` | Activate coverage (self-service by subcontractor) | Subcontractor |
| POST | `/coverage-assignments/{id}/fail` | Report equipment failure; cascades to backup-seeking | Subcontractor, OpsDispatcher |
| POST | `/coverage-assignments/{id}/release` | Release or cancel coverage | OpsDispatcher |
| POST | `/true-ups` | Create a DRAFT seasonal true-up (OCC on contract version) | OpsDispatcher |
| GET | `/true-ups/{id}` | Get a true-up | PlatformAdmin, OpsDispatcher, ClientContact |
| GET | `/true-ups` | List/filter true-ups | PlatformAdmin, OpsDispatcher, ClientContact |
| POST | `/true-ups/{id}/issue` | Issue a true-up; freezes computed components | OpsDispatcher |
| POST | `/true-ups/{id}/settle` | Settle a true-up; amount must equal balance exactly | OpsDispatcher |

## 5. Error Code Catalogue

The table below is the complete catalog of error identifiers and their HTTP status codes. The conditions that trigger each error are specified in the narratives of §2 and §3 rather than repeated here.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED_ROLE` | 403 |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ALREADY_TERMINAL` | 409 |
| `ERR_STALE_CONTRACT_VERSION` | 412 |
| `ERR_DISPUTE_SEGREGATION` | 403 |
| `ERR_DOCUMENTATION_INCOMPLETE` | 422 |
| `ERR_INVALID_QUANTITY` | 422 |
| `ERR_CAPABILITY_MISMATCH` | 422 |
| `ERR_PRIORITY_SEQUENCE_CONFLICT` | 409 |
| `ERR_DUPLICATE_INVOICE` | 409 |
| `ERR_DUPLICATE_COVERAGE` | 409 |
| `ERR_CONTRACT_TYPE_FORBIDS` | 409 |
| `ERR_INVOICE_EMPTY` | 422 |
| `ERR_EVIDENCE_REQUIRED` | 422 |
| `ERR_CONTRACT_HAS_NO_SITES` | 422 |
| `ERR_DISPUTE_LINE_NOT_FOUND` | 422 |
| `ERR_SEASON_WINDOW_OVERLAP` | 409 |
| `ERR_COVERAGE_OVERLAP` | 409 |
| `ERR_VISIT_GAP_CONFLICT` | 409 |
| `ERR_PHOTO_WINDOW_EXPIRED` | 422 |
| `ERR_CHALLENGE_WINDOW_EXPIRED` | 422 |
| `ERR_AMENDMENT_WINDOW_INVALID` | 422 |
| `ERR_CLAIM_WINDOW_EXPIRED` | 422 |
| `ERR_OBSERVATION_OUT_OF_WINDOW` | 422 |
| `ERR_VERIFICATION_QUORUM` | 422 |
| `ERR_NO_NEW_EVIDENCE` | 409 |
| `ERR_EVENT_NOT_VERIFIED` | 409 |
| `ERR_SUBCONTRACTOR_NOT_APPROVED` | 409 |
| `ERR_CONTRACT_NOT_ACTIVE` | 409 |
| `ERR_RENEWAL_BLOCKED` | 409 |
| `ERR_EVENT_LOCKED_BY_INVOICE` | 409 |
| `ERR_NO_BACKUP_AVAILABLE` | 409 |
| `ERR_PHOTO_REQUIRED` | 422 |
| `ERR_CONTRACT_HAS_OPEN_WORK` | 409 |
| `ERR_CLIENT_CREDIT_EXCEEDED` | 422 |
| `ERR_OVERPAYMENT` | 422 |
| `ERR_INVOICE_HAS_PAYMENTS` | 409 |
| `ERR_SETTLEMENT_MISMATCH` | 422 |
