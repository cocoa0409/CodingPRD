# Broadcast Affiliate Relations & Network Compensation API — Product Requirements Document

## 1. Introduction

Broadcast networks and the local stations that carry their programming live in a long, mutually dependent negotiation. A network needs each affiliate to clear a minimum amount of its national feed every sweep period, to honor syndicated-exclusivity windows inside its Designated Market Area (DMA), and to remit a contractually negotiated share of retransmission-consent revenue. Stations, in turn, need room to preempt network inventory for breaking news, local sports, emergencies and political coverage; to claim local commercial avails inside network programs; and to receive timely outage credits when a transmitter, fiber cut, satellite jam or power loss takes their signal dark.

This document specifies the Broadcast Affiliate Relations & Network Compensation API, the single system of record through which networks administer affiliation agreements, govern program clearances and preemption requests, compute reverse-compensation and retransmission revenue shares, allocate local avails, issue outage credits, audit regulatory compliance filings, and arbitrate syndication-exclusivity disputes. The system serves four audiences with sharply segregated duties: the platform operator that bootstraps networks and station groups, the network-side affiliate-relations desk that enforces the contract, the station-group owner that runs stations day to day, and an independent compliance auditor that verifies regulatory filings.

The model is sweep-period-driven. A logical clock — distinct from wall time — advances the network's `current_period_index`, rolls station outage counters, expires stale avail claims, and triggers time-sensitive transitions such as `ACTIVE → EXPIRING` on affiliation agreements and `CLAIMED → EXPIRED` on avail allocations. Most write actions are scoped under a nested path of network → station → child resource, and every mutation increments a per-entity `version` so clients can use optimistic concurrency when two desks could otherwise collide on the same agreement or station.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

All requests carry two HTTP headers that together identify the caller:

- `X-User-ID` — the caller's unique identifier
- `X-User-Role` — the caller's role, exactly one of `PlatformAdmin`, `NetworkAffiliateRelations`, `StationGroupOwner`, `ComplianceAuditor`

A request missing either header, or carrying a role not in the RBAC matrix, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not authorized for the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

The `X-User-ID` is interpreted differently by role:

- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server does not compare it to any entity's `id`.
- When `X-User-Role` is `NetworkAffiliateRelations`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server does not compare it to any entity's `id`.
- When `X-User-Role` is `StationGroupOwner`, `X-User-ID` is the `id` of the acting `StationGroup`; ownership checks on any resource that references a `StationGroup` compare the resource's foreign-key field to `X-User-ID`.
- When `X-User-Role` is `ComplianceAuditor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server does not compare it to any entity's `id`.

Segregation-of-duties is enforced for the renewal-offer workflow specifically: a `NetworkAffiliateRelations` operator and a `StationGroupOwner` operator alternate turns, and neither side may accept, reject, or counter its own most recent offer. Violations of that rule surface as `ERR_SOD_VIOLATION` (HTTP 403) — see §3.4.

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

List endpoints accept two optional query parameters: `limit` and `offset`. `limit` defaults to 10, must be at least 1, and may not exceed 100. `offset` defaults to 0 and must be non-negative. Lists are returned in `created_at` ascending order. The `meta` block of a list response includes the four pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true exactly when `offset + limit < total_count`.

### 2.4. Common Resource Properties and the Optimistic Currency of `version`

Every entity in this API exposes the following fields, regardless of entity type:

- `id` — a server-minted UUID, with no type prefix.
- `created_at` — ISO 8601 UTC timestamp with three fractional digits, populated at creation.
- `updated_at` — ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation.
- `version` — an integer starting at 1 on creation and incremented by exactly 1 on every mutation, including state transitions and side-effect-driven updates.

In addition to those four, most workflow entities carry a system-managed `status` field that holds the entity's current state-machine state (for example, an `AffiliationAgreement`'s `status` is one of `DRAFT`, `PENDING_ACTIVATION`, `ACTIVE`, `EXPIRING`, `RENEWAL_NEGOTIATION`, `LAPSED`, `TERMINATED`; a `ClearanceReport`'s `status` is one of `DRAFT`, `FILED`, `AUDITED`, `CLEARED`, `DISPUTED`; the §3 subsections enumerate each entity's `status` domain). Two entities use a different field name for the same idea: `Network.posture` and `Station.posture` are the network- and station-level state fields.

The `version` field is the linchpin of the optimistic-concurrency contract. Two write endpoints — renewal-offer creation and settlement commit — require the client to echo back the version of a parent resource it last observed; if the server's current version has advanced past the echoed value, the write is rejected (see §2.6). Endpoints not listed in a concurrency rule do not take any version field in their payload.

### 2.5. Nested Resource Resolution and Path Parameter Scoping

Nested URLs are validated left-to-right. A request for `/networks/{nid}/stations/{sid}/agreements/{aid}` first confirms the network `nid` exists, then confirms station `sid` exists and is scoped to that network, then confirms agreement `aid` exists and is scoped to that station. A failure at any tier returns `ERR_NOT_FOUND` (HTTP 404). Stations are always scoped to a network; affiliation agreements, clearance reports, preemption requests, avail allocations, retrans settlements, outage events, outage credits, and compliance reports are all scoped to a station; renewal offers are scoped to an agreement; territories and programs are scoped to a network; syndication-exclusivity claims are scoped to a territory. Flat reverse-reachability routes (e.g., `/stations/{id}`, `/agreements/{id}`) exist so clients can fetch a single resource by id without knowing its parent path, and the corresponding list endpoints accept foreign-key filters (e.g., `station_id`, `network_id`, `program_id`) to traverse relationships in reverse.

### 2.6. Optimistic Concurrency Control on High-Contention Writes

Two endpoints guard against stale-parent writes by requiring an explicit version echo:

- **Renewal-offer creation** — posting a new offer under an agreement requires the request body to carry `expected_agreement_version`, matching the current `version` of the parent `AffiliationAgreement`. A mismatch is rejected with `ERR_STALE_AGREEMENT_VERSION` (HTTP 412). This captures the case where another writer has just proposed an offer — which legitimately supersedes the prior round under the alternating-turns rule — and the current writer's view of the agreement is therefore stale.
- **Retrans-settlement commit** — committing a settlement requires the request body to carry `expected_station_version`, matching the current `version` of the parent `Station`. A mismatch is rejected with `ERR_STALE_STATION_VERSION` (HTTP 412). This captures the case where another writer has just confirmed an outage event — which mutates the station's outage counter and bumps its version — and the committer's settlement inputs are therefore stale.

No other endpoint takes a version field. A generic stale-version error code `ERR_STALE_VERSION_GENERIC` (HTTP 412) exists in the catalogue but is not currently produced by any endpoint.

### 2.7. Precision, Rounding, and Integer-Cent Accounting

All monetary amounts are represented as integer cents — `gross_retrans_cents`, `net_retrans_cents`, `network_share_cents`, `outage_credit_cents`, `aggregate_retrans_cents`, `claimed_revenue_cents`, `credit_cents`. No fractional cents are stored. Two rounding conventions are used and are not interchangeable:

- **Round-half-up** is applied when computing provisional settlement shares, outage-credit amounts, and clearance rates.
- **Ceiling** is applied when computing final settlement shares.

Ratios (`reverse_comp_pct`, `retrans_share_pct`, `reverse_comp_standard_pct`, `retrans_share_standard_pct`, `proposed_reverse_comp_pct`, `proposed_retrans_share_pct`) are decimal numbers in `[0, 1]`. Clearance rates are expressed to four decimal places. Pairwise rate sums on an agreement or renewal offer must total exactly 1.0 within a tolerance of 1e-9, otherwise the write is rejected with `ERR_RATE_SUM_MISMATCH` (HTTP 422).

### 2.8. Logical Clock and Sweep Periods

The server maintains a logical UTC clock, exposed on each `Network` as `current_utc`. At server startup the clock defaults to `2026-05-01T00:00:00Z`. A platform administrator may set the clock to an arbitrary ISO 8601 UTC timestamp via the test-driving endpoint, supplying the new value as `to_iso8601` in the request body; the new value must be non-decreasing relative to the current value. Setting the clock is the mechanism by which time-triggered transitions (an agreement entering `EXPIRING`, an agreement lapsing, an avail claim expiring) are fired.

Each network also carries a `current_period_index`, an integer that starts at 0 and is incremented by a platform administrator action. Advancing the period rolls every station's `monthly_outage_minutes_current_period` back to 0, expires any `CLAIMED` avail allocations whose `period_index` is earlier than the new period, and recomputes both `Network.posture` and every station's `posture`. Many validations reference "the current period" — that phrase always means `Network.current_period_index`.

### 2.9. Network and Station Posture Derivation

Two computed postures drive most of the system's cross-cutting gating.

**Station posture** is one of `CLEARANCE_OK`, `CLEARANCE_DEFICIENT`, or `DARK`. Precedence is `DARK > CLEARANCE_DEFICIENT > CLEARANCE_OK`. A station is `DARK` when its `monthly_outage_minutes_current_period` strictly exceeds 240 minutes. Otherwise it is `CLEARANCE_DEFICIENT` when its `clearance_rate_current_period` is non-null and below 0.85, or when there exists a syndication-exclusivity claim against it in `VALIDATED` status. Otherwise it is `CLEARANCE_OK`. The derivation is deterministic and reaches its fixed point in a single pass.

**Network posture** is one of `NORMAL`, `SWEEP_LOCKDOWN`, or `DISPUTE_FREEZE`. Precedence is `SWEEP_LOCKDOWN > DISPUTE_FREEZE > NORMAL`. A network enters `SWEEP_LOCKDOWN` when at least 3 compliance reports against stations of that network in the current period reach `FAILED` status; while locked down, all preemption approvals network-wide are blocked. A network enters `DISPUTE_FREEZE` when any renewal offer is in `PROPOSED` status on an agreement whose station belongs to a station group with `leverage_tier` equal to `MAJOR`. Otherwise the network is `NORMAL`. Advancing `current_period_index` always recomputes both postures; exiting `SWEEP_LOCKDOWN` happens automatically on period advance, and exiting `DISPUTE_FREEZE` happens automatically once no `PROPOSED` offer remains on any `MAJOR`-tier agreement.

### 2.10. Validation Ordering

Every request passes through a fixed sequence of checks. The order matters because earlier checks can mask later ones; the canonical order is:

1. **Authentication** — headers `X-User-ID` and `X-User-Role` present, role in the RBAC matrix (else `ERR_UNAUTHENTICATED`).
2. **Authorization** — the role is permitted for the endpoint (else `ERR_UNAUTHORIZED_ROLE`).
3. **Existence and scoping** — every path parameter resolves left-to-right (else `ERR_NOT_FOUND`).
4. **State admissibility** — the target resource is in a state that permits the requested transition per its state machine (else `ERR_INVALID_STATE`).
5. **Network lockdown** — when approving a preemption, the network must not be in `SWEEP_LOCKDOWN` (else `ERR_NETWORK_LOCKDOWN`).
6. **Segregation of duties** — renewal-offer accept/reject/withdraw obey the SoD rule (else `ERR_SOD_VIOLATION`).
7. **Rate-sum** — `reverse_comp_pct + retrans_share_pct` (or the `proposed_*` equivalents) totals 1.0 within 1e-9 (else `ERR_RATE_SUM_MISMATCH`).
8. **Time ranges** — every (start, end) pair in the payload has end strictly greater than start (else `ERR_INVALID_TIME_RANGE`).
9. **Avail pool capacity** — confirming a claim does not push confirmed local minutes past `avail_minutes_local_allocatable` (else `ERR_AVAIL_POOL_EXHAUSTED`).
10. **Window overlap** — exclusivity-claim alleged window overlaps the territory protection window under half-open semantics (else `ERR_NO_WINDOW_OVERLAP`).
11. **Territory exclusivity holder** — agreement activation checks the territory's holder is null or self (else `ERR_TERRITORY_EXCLUSIVITY_HELD`).
12. **Preemption quota** — cumulative approved preemption hours this period plus the new request does not exceed 10% of the agreement's clearance obligation (else `ERR_PREEMPTION_QUOTA_EXCEEDED`).
13. **Duplicate committed settlement** — only one settlement in `COMMITTED` per (station, period) pair (else `ERR_DUPLICATE_COMMITTED_SETTLEMENT`).
14. **Claimant holds exclusivity** — exclusivity-claim validation requires claimant to be the current holder (else `ERR_CLAIMANT_NOT_HOLDER`).
15. **OCC on agreement** — `expected_agreement_version` matches (else `ERR_STALE_AGREEMENT_VERSION`).
16. **OCC on station** — `expected_station_version` matches (else `ERR_STALE_STATION_VERSION`).
17. **Counter-round budget** — a countered preemption may be resubmitted only when `counter_round_count` is below 3 (else `ERR_COUNTER_ROUND_EXHAUSTED`).
18. **No future outages** — outage events may not end after the logical clock (else `ERR_FUTURE_OUTAGE`).
19. **Term length** — renewal offers must propose a term in {12, 24, 36, 48, 60} months (else `ERR_INVALID_TERM_LENGTH`).
20. **No future period reports** — clearance reports and compliance reports may not be filed against a `period_index` greater than the network's current period (else `ERR_FUTURE_PERIOD`).

Malformed payloads and missing required fields are rejected with `ERR_INVALID_REQUEST` (HTTP 400) before any of the above checks.

## 3. Business Logic & Workflows

### 3.1. Bootstrap: Networks, Station Groups, Stations, Territories, Programs

A new deployment begins with the platform administrator. The administrator creates a `Network` by supplying its `call_sign`, the IANA timezone of its primary satellite feed `primary_feed_tz`, and the network's standard revenue split: `reverse_comp_standard_pct` (the share of station net retrans revenue owed back to the network) and `retrans_share_standard_pct` (the network's share of retransmission consent revenue). The two standard percentages must sum to 1.0 within 1e-9. The network is born with `current_period_index` equal to 0, `current_utc` at the default clock, and `posture` equal to `NORMAL`.

Independently, the administrator creates each `StationGroup` with its `group_name` and a `leverage_tier` drawn from `SMALL`, `MID`, `LARGE`, or `MAJOR`. The leverage tier matters financially — it gates a group-volume discount in the reverse-compensation calculation (§3.6) — and politically, because any renewal offer proposed on an agreement owned by a `MAJOR` group drags the whole network into `DISPUTE_FREEZE`. The group also carries a computed `aggregate_retrans_cents`, a rolling four-period sum of net retrans revenue across all its stations, recomputed on every settlement commit and reconcile.

Registering a `Station` is a joint operation between the platform administrator and the network-side affiliate-relations desk: the request carries the station's `call_sign` (unique within the network), its Nielsen `dma_code`, and the `station_group_id` of the owning group. The station is created with `posture` equal to `CLEARANCE_OK`, `monthly_outage_minutes_current_period` equal to 0, and `clearance_rate_current_period` null until a first clearance report is filed.

Territories are the network-side artifact that pins exclusivity to geography. The affiliate-relations desk creates a `Territory` by naming the `dma_code` it covers (unique within the network) and the half-open protected broadcast window bounded by `protection_window_start_utc` and `protection_window_end_utc`; the end must be strictly after the start, otherwise the creation fails with `ERR_INVALID_TIME_RANGE`. The territory's `exclusivity_holder_station_id` starts null and is populated only when an affiliation agreement activates.

Programs are the unit of inventory. The affiliate-relations desk creates a `Program` with a `title`, the scheduled air window `scheduled_start_utc` to `scheduled_end_utc` (end strictly after start), the total commercial `avail_minutes_total` inside the window, the `avail_minutes_local_allocatable` that stations may sell locally (which must be at most `avail_minutes_total`), and a boolean `is_syndicated` flag marking the program as participating in syndicated-exclusivity protection.

### 3.2. Affiliation Agreements: From Draft to Active

Once a station exists, the affiliate-relations desk drafts an `AffiliationAgreement` against it. The creation payload carries the `term_start_utc` and `term_end_utc` (end strictly after start), the negotiated `reverse_comp_pct` and `retrans_share_pct` (which must sum to 1.0 within 1e-9 and which override the network's standard percentages for this agreement), and the `clearance_obligation_hours` the station must clear per sweep period. The agreement is born in `DRAFT`, with `renewal_round_count` equal to 0 and `version` equal to 1.

Submitting the agreement moves it from `DRAFT` to `PENDING_ACTIVATION`. The submit is permitted only when the station's posture is not `DARK` and when no other agreement on the same station is already in `ACTIVE` or `PENDING_ACTIVATION` — the system enforces one active agreement per station at a time. A successful submit bumps the agreement's `version` by 1.

Activation moves the agreement from `PENDING_ACTIVATION` to `ACTIVE`. Two preconditions must hold: the network's `current_utc` must be at or past the agreement's `term_start_utc`, and the territory covering the station's `dma_code` must have its `exclusivity_holder_station_id` either null or already equal to this station's id. If another station already holds exclusivity in the DMA, the activation is rejected with `ERR_TERRITORY_EXCLUSIVITY_HELD` (HTTP 409). On successful activation, the territory's `exclusivity_holder_station_id` is set to this station, and the agreement's `version` increments.

Once active, the agreement lives under time pressure. When `current_utc` reaches 90 days before `term_end_utc`, the agreement auto-transitions from `ACTIVE` to `EXPIRING`. When `current_utc` reaches 180 days before `term_end_utc`, the agreement becomes eligible to enter renewal negotiation — the first renewal offer posted against it moves it from `ACTIVE` to `RENEWAL_NEGOTIATION`.

Termination is an explicit act by the affiliate-relations desk. From `ACTIVE`, termination requires that no `RetransSettlement` for this agreement remain in `DRAFT`; the check is waived when terminating from `EXPIRING`. In both cases the side effects are the same in spirit: the territory's `exclusivity_holder_station_id` is cleared back to null, and the agreement's `version` increments. Terminating from `ACTIVE` additionally cascades to every avail allocation in `CLAIMED` or `CONFIRMED` on this station, flipping each to `REVOKED`. `TERMINATED` is a terminal state.

If the agreement enters `RENEWAL_NEGOTIATION` and the parties let `term_end_utc` pass without either side accepting an offer, the agreement auto-transitions to `LAPSED`. The territory's `exclusivity_holder_station_id` is cleared, the station's posture is recomputed (in case the now-lapsed station was the exclusive holder), and the agreement's `version` increments. `LAPSED` is the other terminal state.

### 3.3. Preemption Requests and the Ten-Percent Quota

When a station group needs to preempt a network program — for breaking news, a local sports overrun, an emergency, political coverage, or another reason — it files a `PreemptionRequest`. The creation payload carries the `program_id` being preempted, the `agreement_id` under which the preemption is requested, the requested window `requested_start_utc` to `requested_end_utc` (end strictly after start), and a `reason` drawn from `BREAKING_NEWS`, `LOCAL_SPORTS`, `EMERGENCY`, `POLITICAL`, or `OTHER`. The request is born in `SUBMITTED`, with `counter_round_count` equal to 0 and the `counter_start_utc` / `counter_end_utc` fields empty.

The affiliate-relations desk picks up the request by beginning review, moving it from `SUBMITTED` to `UNDER_REVIEW`. The referenced agreement must be in `ACTIVE` or `EXPIRING` at this point; a request filed against an agreement that has lapsed or terminated cannot enter review. From `UNDER_REVIEW`, three outcomes are possible.

**Approval** is the consequential one. Approval moves the request from `UNDER_REVIEW` to `APPROVED` and is gated by two checks evaluated in the order given in §2.10: first, the network must not be in `SWEEP_LOCKDOWN` (otherwise `ERR_NETWORK_LOCKDOWN`, HTTP 409); second, the cumulative approved preemption hours this period plus the new request's hours must not exceed ten percent of the agreement's `clearance_obligation_hours` — otherwise the approval is rejected with `ERR_PREEMPTION_QUOTA_EXCEEDED` (HTTP 422). On approval, any clearance report for the current period on this station that is in `FILED` or `AUDITED` is flagged for recompute of its clearance rate, the station's posture is recomputed, and the request's `version` increments.

**Denial** is a terminal move from `UNDER_REVIEW` to `DENIED`. **Counter** moves the request from `UNDER_REVIEW` to `COUNTERED`: the desk supplies a `counter_start_utc` and `counter_end_utc` in the payload, and the proposed counter window must overlap the originally requested window by strictly more than zero minutes — a fully disjoint counter is not a meaningful negotiation move. The counter populates the request's `counter_start_utc` and `counter_end_utc` fields and increments its `version`.

From `COUNTERED`, the station group has two moves. It may **resubmit**, which moves the request back from `COUNTERED` to `SUBMITTED`: the requested window is updated to the counter window (`requested_start_utc` becomes `counter_start_utc`, `requested_end_utc` becomes `counter_end_utc`), `counter_round_count` increments by 1, and `version` increments. Resubmission is capped — when `counter_round_count` has already reached 3, the resubmit is rejected with `ERR_COUNTER_ROUND_EXHAUSTED` (HTTP 409), preventing endless volleys. Alternatively, the station group may **withdraw** the request, moving it from `COUNTERED` to `WITHDRAWN`; a request in `SUBMITTED` may also be withdrawn directly. `APPROVED`, `DENIED`, and `WITHDRAWN` are the terminal states of a preemption request.

### 3.4. Renewal Negotiation: Alternating Turns Under Segregation of Duties

Renewal offers are the negotiation surface between the network and a station group. A `RenewalOffer` is always scoped to an existing `AffiliationAgreement` and is created with `proposed_by_role` (either `NETWORK_AFFILIATE_RELATIONS` or `STATION_GROUP_OWNER`), the offered `proposed_reverse_comp_pct` and `proposed_retrans_share_pct` (which must sum to 1.0 within 1e-9), and a `proposed_term_months` drawn from the closed set {12, 24, 36, 48, 60}. Terms outside this set are rejected with `ERR_INVALID_TERM_LENGTH` (HTTP 422).

The first offer posted against an `ACTIVE` or `EXPIRING` agreement moves the agreement into `RENEWAL_NEGOTIATION`, increments its `renewal_round_count`, increments its `version`, and recomputes the network's posture — which is where the `DISPUTE_FREEZE` rule fires if the station's group is `MAJOR`-tier. Each offer is created in `PROPOSED` with a `round_index` equal to 1 for the first offer on an agreement and incremented by 1 on each subsequent offer. Because offer creation is an OCC-guarded write (§2.6), the request body must also carry `expected_agreement_version`; a stale view is rejected with `ERR_STALE_AGREEMENT_VERSION` (HTTP 412).

The alternating-turns rule governs subsequent offers. While an offer is `PROPOSED`, the only way to post a new offer is for the new offer's `proposed_by_role` to differ from the existing offer's `proposed_by_role`. The new offer is created in `PROPOSED` with `round_index` one higher than the prior round, and the prior `PROPOSED` offer is implicitly flipped to `COUNTERED`. A `COUNTERED` offer never returns to `PROPOSED`; it awaits either acceptance (of a sibling) or supersession.

From `PROPOSED`, the three terminal moves are accept, reject, and withdraw — and each carries a segregation-of-duties rule enforced as `ERR_SOD_VIOLATION` (HTTP 403):

- **Accept** moves the offer from `PROPOSED` to `ACCEPTED` and is permitted only when the caller's role is not the offer's `proposed_by_role` — the proposer cannot accept their own offer. Acceptance cascades: the parent agreement's `reverse_comp_pct` is overwritten with the offer's `proposed_reverse_comp_pct`, `retrans_share_pct` with `proposed_retrans_share_pct`, and `term_end_utc` is extended by `proposed_term_months`; the agreement itself moves from `RENEWAL_NEGOTIATION` back to `ACTIVE`; every other offer on the same agreement in `PROPOSED` or `COUNTERED` flips to `SUPERSEDED`; the network's posture is recomputed; and the agreement's `version` increments.
- **Reject** moves the offer from `PROPOSED` to `REJECTED`, again requiring that the caller's role differ from `proposed_by_role`. The network's posture is recomputed (rejection may take the network out of `DISPUTE_FREEZE` if no other `MAJOR`-tier proposal remains).
- **Withdraw** moves the offer from `PROPOSED` to `WITHDRAWN` and is permitted only when the caller's role equals `proposed_by_role` — only the proposer may retract their own offer.

`ACCEPTED`, `REJECTED`, `WITHDRAWN`, and `SUPERSEDED` are all terminal states for a renewal offer. A `COUNTERED` offer becomes `SUPERSEDED` automatically when a subsequent offer on the same agreement is accepted.

### 3.5. Clearance Reporting and Station Posture

Sweep-period clearance is the station group's accountability mechanism. The group creates a `ClearanceReport` against a station with a `period_index`, the `cleared_hours` of network programming actually aired, and the `preempted_hours` taken for local content. The report is born in `DRAFT` with a computed `clearance_rate` of null.

Filing the report moves it from `DRAFT` to `FILED` and triggers the clearance-rate computation. The rate is the report's `cleared_hours` divided by the agreement's `clearance_obligation_hours`, rounded half-up to four decimal places — and the order of operations is pinned: divide first, then round. Pre-rounding the inputs yields different four-decimal results and is non-conformant. Filing is bounded in time: the report's `period_index` must not exceed the network's `current_period_index`, otherwise the file is rejected with `ERR_FUTURE_PERIOD` (HTTP 422). On a successful file, the station's `clearance_rate_current_period` is set to the freshly computed rate, the station's posture is recomputed (entering `CLEARANCE_DEFICIENT` when the rate falls below 0.85), and the report's `version` increments.

The affiliate-relations desk audits a filed report, moving it from `FILED` to `AUDITED`. From `AUDITED`, two resolutions are possible, gated on the rate:

- **Resolve cleared** moves the report to `CLEARED` and requires `clearance_rate` to be at least 0.85. Attempting resolve-cleared on a rate below 0.85 is rejected with `ERR_DEFICIENT_CLEARANCE` (HTTP 409). On success the station's posture is recomputed.
- **Resolve disputed** moves the report to `DISPUTED` and requires `clearance_rate` strictly below 0.85. The station's posture is set to `CLEARANCE_DEFICIENT` directly, and the network's posture is recomputed.

`CLEARED` and `DISPUTED` are the terminal states of a clearance report.

Station posture is recomputed not just on clearance events but on any mutation to a clearance report, outage event, or syndication-exclusivity claim affecting the station — the derivation in §2.9 is applied in precedence order, and a station that has gone `DARK` returns to `CLEARANCE_OK` only when the period advances and the outage counter resets.

### 3.6. Retrans Settlements: Provisional vs. Final Variant

The financial heart of the system is the `RetransSettlement`. Either the station group or the affiliate-relations desk may create one in `DRAFT`, supplying the `agreement_id` whose rates govern, the `period_index` being settled, and the `gross_retrans_cents` of retransmission consent revenue the station earned that period. Computed fields — `net_retrans_cents`, `network_share_cents`, `outage_credit_cents`, and `variant_used` — are populated at commit and reconcile time, not at creation.

**Commit** is the affiliate-relations desk's action, moving the settlement from `DRAFT` to `COMMITTED`. Three preconditions apply: the governing agreement must be in `ACTIVE` status; no other settlement on the same station in the same period may already be in `COMMITTED` (else `ERR_DUPLICATE_COMMITTED_SETTLEMENT`, HTTP 409); and the request must carry `expected_station_version` matching the station's current `version` (else `ERR_STALE_STATION_VERSION`, HTTP 412) — this is the OCC guard that prevents a committer from overwriting an outage-confirm they have not observed.

The commit applies the **PROVISIONAL** variant of the reverse-comp calculation. In words: the gross is reduced by the sum of every outage credit already linked to this settlement in `APPLIED` status, yielding the net. A tiered discount is then read off the station's group's `leverage_tier` and the group's trailing four-period `aggregate_retrans_cents` snapshot as of the **current** period — a `MAJOR` group with trailing aggregate at least 100,000,000 cents takes a 4 percent discount, a `LARGE` group with trailing aggregate at least 50,000,000 cents takes 2.5 percent, a `MID` group with trailing aggregate at least 20,000,000 cents takes 1 percent, and any other combination takes no discount. The base share is the net multiplied by the agreement's `reverse_comp_pct`, rounded half-up to integer cents; the provisional share is that base multiplied by one minus the discount, again rounded half-up to integer cents. The result is stored as `network_share_cents`, `variant_used` is set to `PROVISIONAL`, every linked outage credit flips from `PENDING` to `APPLIED` with its `settlement_id` populated, the station's `monthly_outage_minutes_current_period` is consumed into the credit math, the group's `aggregate_retrans_cents` is recomputed, and both the settlement's and the station's `version` increment.

**Reconcile** moves the settlement from `COMMITTED` to `RECONCILED` and is permitted only when the network's `current_period_index` has advanced past the settlement's `period_index`. Reconcile recomputes `network_share_cents` under the **FINAL** variant: the discount tier table is the same, but the trailing aggregate is the snapshot as of the **end of the prior period** — explicitly excluding any settlements from the current period — and the share is computed by ceiling instead of round-half-up: the final share is the ceiling of the net multiplied by the agreement's `reverse_comp_pct` multiplied by one minus the prior-period discount. `variant_used` flips to `FINAL`, the group's aggregate is recomputed, and the settlement's `version` increments.

A settlement in `DRAFT` may also be **voided**, moving it from `DRAFT` to `VOID` — a terminal state used to abandon a draft that should never be committed.

### 3.7. Outage Events and the Credit Waterfall

Stations report outages, and the network confirms them. Either side may create an `OutageEvent` against a station with the `period_index` in which the outage occurred, the `started_at_utc` and `ended_at_utc` (end strictly after start, and the end must not lie in the future relative to `current_utc` — future outages are rejected with `ERR_FUTURE_OUTAGE`, HTTP 422), and a `cause` drawn from `TRANSMITTER_FAILURE`, `FIBER_CUT`, `SATELLITE_JAM`, `POWER_LOSS`, or `PLANNED_MAINTENANCE`. The event is born in `REPORTED`, and its `duration_minutes` is computed as the whole-minute floor of the difference between `ended_at_utc` and `started_at_utc`.

Confirming the event moves it from `REPORTED` to `CONFIRMED` and is permitted only when `duration_minutes` is at least 1. Confirmation is the cascade point: an `OutageCredit` is created in `PENDING` with `credit_cents` computed per the outage-credit formula; the station's `monthly_outage_minutes_current_period` is incremented by `duration_minutes`; the station's posture is recomputed (and becomes `DARK` if the new total strictly exceeds 240 minutes); and both the event's and the station's `version` increment. Rejecting the event moves it from `REPORTED` to `REJECTED` with no side effects beyond the version bump.

The outage-credit formula is duration-tiered and cause-multiplied. The baseline rate is 500 cents per minute. The first 30 minutes of the outage are paid at one times the baseline; minutes 31 through 120 are paid at one-and-a-half times; minutes beyond 120 are paid at two times. That raw subtotal is then scaled by a cause multiplier: zero for `PLANNED_MAINTENANCE` (planned work earns no credit), one-and-a-half for `SATELLITE_JAM` (an aggravated cause), and one for every other cause. The final credit is the scaled amount rounded half-up to integer cents. Boundary examples: an outage of 0 minutes yields a credit of 0 cents; an outage of exactly 30 minutes yields 30 times 1.0 times 500, or 15,000 cents; an outage of exactly 31 minutes yields 30 times 500 plus 1 times 750, or 15,750 cents.

An outage credit in `PENDING` becomes `APPLIED` automatically when the settlement it will be attached to commits — the credit's `settlement_id` is populated at that moment. A credit in `PENDING` may also be explicitly **forfeited** by the affiliate-relations desk, but only when the underlying event's `cause` is `PLANNED_MAINTENANCE`; this is the cleanup path for credits that should never have been issued. `APPLIED` and `FORFEITED` are the terminal states of an outage credit.

### 3.8. Avail Allocations and the Waterfall

Inside every program's window are commercial avails that stations may sell locally. The station group claims a slice by creating an `AvailAllocation` against its station, supplying the `program_id`, the `period_index` in which the avail is exercised, the `local_minutes_claimed`, and the `claimed_revenue_cents` the station expects to earn. The allocation is born in `CLAIMED`.

Confirmation is where the waterfall runs. Confirming an allocation moves it from `CLAIMED` to `CONFIRMED` and is permitted only when the station's posture is not `DARK` and the sum of `local_minutes_claimed` across every already-`CONFIRMED` allocation for the same program, plus this claim, does not exceed the program's `avail_minutes_local_allocatable`. Exceeding that pool is rejected with `ERR_AVAIL_POOL_EXHAUSTED` (HTTP 409). Claims are processed in chronological order by `created_at`; if two claims share an identical `created_at`, the smaller claim wins, and any further tie is rejected outright — no random tiebreak is used. This is aggregate capacity semantics, not pairwise interval overlap; two claims against the same program can perfectly well coexist as long as their minutes fit under the cap.

A `CLAIMED` allocation may be revoked by the affiliate-relations desk, moving it to `REVOKED`. A `CLAIMED` allocation whose `period_index` falls behind the network's `current_period_index` auto-expires to `EXPIRED` at period-advance time. And as covered in §3.2, terminating an agreement from `ACTIVE` cascades every `CLAIMED` and `CONFIRMED` allocation on the station to `REVOKED`. `REVOKED` and `EXPIRED` are the terminal states of an avail allocation.

### 3.9. Compliance Reporting and the Sweep Lockdown

The fourth workflow is regulatory. Either the station group or the independent compliance auditor creates a `ComplianceReport` against a station with the `period_index` reported and a `report_kind` drawn from `FCC_302`, `CHILDRENS_TELEVISION`, `EEO`, or `POLITICAL_FILE`. The report is born in `OPEN` with `finding_count` equal to 0.

The station group submits the report, moving it from `OPEN` to `SUBMITTED`; the same `period_index`-not-in-future rule as clearance reports applies, enforced as `ERR_FUTURE_PERIOD` (HTTP 422). Audit moves the report from `SUBMITTED` to `AUDITED` — either the affiliate-relations desk or the compliance auditor may audit — and the audit payload carries the `finding_count` which is stored on the report.

Resolution splits on `finding_count`:

- **Resolve pass** moves the report from `AUDITED` to `PASSED` and requires `finding_count` equal to 0. The network's posture is recomputed.
- **Resolve fail** moves the report from `AUDITED` to `FAILED` and requires `finding_count` to be at least 1. The network's posture is recomputed, and if the count of `FAILED` reports against this network's stations in the current period has reached 3, the network enters `SWEEP_LOCKDOWN` — which, per §2.9 and §3.3, blocks all preemption approvals network-wide until the period advances.

`PASSED` and `FAILED` are the terminal states of a compliance report.

### 3.10. Syndication Exclusivity Claims

The last workflow arbitrates territorial exclusivity. When one station believes another is airing a syndicated program inside its protected window, the station group files a `SyndicationExclusivityClaim` against the relevant territory, supplying the `program_id` claimed against, the `claimant_station_id` asserting exclusivity, the `respondent_station_id` accused of the violation, and the alleged violation window `alleged_window_start_utc` to `alleged_window_end_utc` (end strictly after start). The claim is born in `FILED`.

The affiliate-relations desk validates the claim, moving it from `FILED` to `VALIDATED`. Three preconditions, all enforced:

- The claimant must be the current exclusivity holder — the territory's `exclusivity_holder_station_id` must equal the `claimant_station_id`. Otherwise the validation is rejected with `ERR_CLAIMANT_NOT_HOLDER` (HTTP 422).
- The alleged window must overlap the territory's protection window under half-open interval semantics: an overlap exists exactly when the alleged start is strictly before the protection end **and** the alleged end is strictly after the protection start. Adjacent windows — where the alleged end equals the protection start — do **not** overlap, because the intersection is zero-length. Failure to overlap is rejected with `ERR_NO_WINDOW_OVERLAP` (HTTP 422).
- The respondent must differ from the claimant — a station cannot file a violation claim against itself.

On validation, the respondent station's posture is recomputed and becomes `CLEARANCE_DEFICIENT` while the claim remains `VALIDATED`, and the claim's `version` increments.

The desk may instead **dismiss** a `FILED` claim, moving it to `DISMISSED`. A `VALIDATED` claim is closed by **settling** it, moving it to `SETTLED` — settlement recomputes the respondent's posture, potentially lifting the `CLEARANCE_DEFICIENT` flag. `VALIDATED`, `DISMISSED`, and `SETTLED` are the terminal states of a claim.

## 4. Endpoint Definitions

New resource creation returns HTTP 201. State transitions and other modifications of an existing resource return HTTP 200. List endpoints return HTTP 200 with a paginated envelope per §2.3. The following table summarizes the available routes; readers must refer back to §3 narratives for full request-body and side-effect semantics.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/networks` | Create a new Network | PlatformAdmin |
| GET | `/networks/{nid}` | Fetch a Network by id | PlatformAdmin, NetworkAffiliateRelations, StationGroupOwner, ComplianceAuditor |
| GET | `/networks` | List networks | PlatformAdmin, NetworkAffiliateRelations, StationGroupOwner, ComplianceAuditor |
| POST | `/networks/{nid}/advance-period` | Advance the network's `current_period_index` by 1, rolling station outage counters, expiring stale claims, recomputing postures | PlatformAdmin |
| POST | `/station-groups` | Create a station group | PlatformAdmin |
| GET | `/station-groups/{sgid}` | Fetch a station group | PlatformAdmin, NetworkAffiliateRelations, StationGroupOwner, ComplianceAuditor |
| POST | `/networks/{nid}/stations` | Register a station under a network and group | PlatformAdmin, NetworkAffiliateRelations |
| GET | `/networks/{nid}/stations/{sid}` | Fetch station | PlatformAdmin, NetworkAffiliateRelations, StationGroupOwner, ComplianceAuditor |
| GET | `/networks/{nid}/stations` | List stations for a network (filterable by `dma_code`, `posture`, `station_group_id`) | PlatformAdmin, NetworkAffiliateRelations, StationGroupOwner, ComplianceAuditor |
| POST | `/networks/{nid}/territories` | Create a DMA territory with protection window | NetworkAffiliateRelations |
| GET | `/networks/{nid}/territories/{tid}` | Fetch territory | PlatformAdmin, NetworkAffiliateRelations, StationGroupOwner, ComplianceAuditor |
| POST | `/networks/{nid}/programs` | Create a program inventory entry | NetworkAffiliateRelations |
| GET | `/networks/{nid}/programs/{pid}` | Fetch a program | PlatformAdmin, NetworkAffiliateRelations, StationGroupOwner, ComplianceAuditor |
| POST | `/networks/{nid}/stations/{sid}/agreements` | Create an AffiliationAgreement in `DRAFT` | NetworkAffiliateRelations |
| GET | `/networks/{nid}/stations/{sid}/agreements/{aid}` | Fetch agreement | PlatformAdmin, NetworkAffiliateRelations, StationGroupOwner, ComplianceAuditor |
| GET | `/networks/{nid}/stations/{sid}/agreements` | List agreements for a station | PlatformAdmin, NetworkAffiliateRelations, StationGroupOwner, ComplianceAuditor |
| POST | `/networks/{nid}/stations/{sid}/agreements/{aid}/submit` | Move agreement `DRAFT` → `PENDING_ACTIVATION` | NetworkAffiliateRelations |
| POST | `/networks/{nid}/stations/{sid}/agreements/{aid}/activate` | Move agreement `PENDING_ACTIVATION` → `ACTIVE`; sets territory exclusivity holder | NetworkAffiliateRelations |
| POST | `/networks/{nid}/stations/{sid}/agreements/{aid}/terminate` | Move agreement `ACTIVE` or `EXPIRING` → `TERMINATED`; revokes avail allocations | NetworkAffiliateRelations |
| POST | `/networks/{nid}/stations/{sid}/agreements/{aid}/renewal-offers` | Propose a renewal offer (creates offer in `PROPOSED`; flips prior `PROPOSED` offer to `COUNTERED`); OCC on the agreement | NetworkAffiliateRelations, StationGroupOwner |
| GET | `/networks/{nid}/stations/{sid}/agreements/{aid}/renewal-offers/{oid}` | Fetch a renewal offer | PlatformAdmin, NetworkAffiliateRelations, StationGroupOwner, ComplianceAuditor |
| GET | `/networks/{nid}/stations/{sid}/agreements/{aid}/renewal-offers` | List renewal offers for an agreement | PlatformAdmin, NetworkAffiliateRelations, StationGroupOwner, ComplianceAuditor |
| POST | `/networks/{nid}/stations/{sid}/agreements/{aid}/renewal-offers/{oid}/accept` | Accept offer (SoD: caller role differs from `proposed_by_role`); agreement returns to `ACTIVE` with new rates and extended term | NetworkAffiliateRelations, StationGroupOwner |
| POST | `/networks/{nid}/stations/{sid}/agreements/{aid}/renewal-offers/{oid}/reject` | Reject offer (SoD: caller role differs from `proposed_by_role`) | NetworkAffiliateRelations, StationGroupOwner |
| POST | `/networks/{nid}/stations/{sid}/agreements/{aid}/renewal-offers/{oid}/withdraw` | Withdraw offer (SoD: caller role equals `proposed_by_role`) | NetworkAffiliateRelations, StationGroupOwner |
| POST | `/networks/{nid}/stations/{sid}/clearance-reports` | Create a ClearanceReport in `DRAFT` | StationGroupOwner |
| GET | `/networks/{nid}/stations/{sid}/clearance-reports/{cid}` | Fetch clearance report | PlatformAdmin, NetworkAffiliateRelations, StationGroupOwner, ComplianceAuditor |
| GET | `/networks/{nid}/stations/{sid}/clearance-reports` | List clearance reports for a station | PlatformAdmin, NetworkAffiliateRelations, StationGroupOwner, ComplianceAuditor |
| POST | `/networks/{nid}/stations/{sid}/clearance-reports/{cid}/file` | Move report `DRAFT` → `FILED`; computes `clearance_rate` and updates station posture | StationGroupOwner |
| POST | `/networks/{nid}/stations/{sid}/clearance-reports/{cid}/audit` | Move report `FILED` → `AUDITED` | NetworkAffiliateRelations |
| POST | `/networks/{nid}/stations/{sid}/clearance-reports/{cid}/resolve-cleared` | Move report `AUDITED` → `CLEARED` (requires rate at least 0.85) | NetworkAffiliateRelations |
| POST | `/networks/{nid}/stations/{sid}/clearance-reports/{cid}/resolve-disputed` | Move report `AUDITED` → `DISPUTED` (requires rate below 0.85) | NetworkAffiliateRelations |
| POST | `/networks/{nid}/stations/{sid}/preemptions` | Create a PreemptionRequest in `SUBMITTED` | StationGroupOwner |
| GET | `/networks/{nid}/stations/{sid}/preemptions/{pid}` | Fetch preemption request | PlatformAdmin, NetworkAffiliateRelations, StationGroupOwner, ComplianceAuditor |
| GET | `/networks/{nid}/stations/{sid}/preemptions` | List preemption requests for a station | PlatformAdmin, NetworkAffiliateRelations, StationGroupOwner, ComplianceAuditor |
| POST | `/networks/{nid}/stations/{sid}/preemptions/{pid}/begin-review` | Move request `SUBMITTED` → `UNDER_REVIEW` | NetworkAffiliateRelations |
| POST | `/networks/{nid}/stations/{sid}/preemptions/{pid}/approve` | Move request `UNDER_REVIEW` → `APPROVED`; enforces 10% preemption quota; blocked under `SWEEP_LOCKDOWN` | NetworkAffiliateRelations |
| POST | `/networks/{nid}/stations/{sid}/preemptions/{pid}/deny` | Move request `UNDER_REVIEW` → `DENIED` | NetworkAffiliateRelations |
| POST | `/networks/{nid}/stations/{sid}/preemptions/{pid}/counter` | Move request `UNDER_REVIEW` → `COUNTERED` with counter window | NetworkAffiliateRelations |
| POST | `/networks/{nid}/stations/{sid}/preemptions/{pid}/resubmit` | Move request `COUNTERED` → `SUBMITTED` (requires `counter_round_count` below 3) | StationGroupOwner |
| POST | `/networks/{nid}/stations/{sid}/preemptions/{pid}/withdraw` | Move request `SUBMITTED` or `COUNTERED` → `WITHDRAWN` | StationGroupOwner |
| POST | `/networks/{nid}/stations/{sid}/avail-allocations` | Claim local avails inside a program | StationGroupOwner |
| GET | `/networks/{nid}/stations/{sid}/avail-allocations/{aid}` | Fetch avail allocation | PlatformAdmin, NetworkAffiliateRelations, StationGroupOwner, ComplianceAuditor |
| GET | `/networks/{nid}/stations/{sid}/avail-allocations` | List avail allocations for a station | PlatformAdmin, NetworkAffiliateRelations, StationGroupOwner, ComplianceAuditor |
| POST | `/networks/{nid}/stations/{sid}/avail-allocations/{aid}/confirm` | Move allocation `CLAIMED` → `CONFIRMED` (waterfall allocation, capacity check) | NetworkAffiliateRelations |
| POST | `/networks/{nid}/stations/{sid}/avail-allocations/{aid}/revoke` | Move allocation `CLAIMED` → `REVOKED` | NetworkAffiliateRelations |
| POST | `/networks/{nid}/stations/{sid}/retrans-settlements` | Create a DRAFT RetransSettlement | StationGroupOwner, NetworkAffiliateRelations |
| GET | `/networks/{nid}/stations/{sid}/retrans-settlements/{rid}` | Fetch settlement | PlatformAdmin, NetworkAffiliateRelations, StationGroupOwner, ComplianceAuditor |
| GET | `/networks/{nid}/stations/{sid}/retrans-settlements` | List settlements for a station | PlatformAdmin, NetworkAffiliateRelations, StationGroupOwner, ComplianceAuditor |
| POST | `/networks/{nid}/stations/{sid}/retrans-settlements/{rid}/commit` | Move settlement `DRAFT` → `COMMITTED` using PROVISIONAL variant; OCC on Station; applies pending outage credits | NetworkAffiliateRelations |
| POST | `/networks/{nid}/stations/{sid}/retrans-settlements/{rid}/reconcile` | Move settlement `COMMITTED` → `RECONCILED` using FINAL variant; `network_share_cents` recomputed | NetworkAffiliateRelations |
| POST | `/networks/{nid}/stations/{sid}/retrans-settlements/{rid}/void` | Move settlement `DRAFT` → `VOID` | NetworkAffiliateRelations |
| POST | `/networks/{nid}/stations/{sid}/outage-events` | Report an outage event | StationGroupOwner, NetworkAffiliateRelations |
| GET | `/networks/{nid}/stations/{sid}/outage-events/{oid}` | Fetch outage event | PlatformAdmin, NetworkAffiliateRelations, StationGroupOwner, ComplianceAuditor |
| GET | `/networks/{nid}/stations/{sid}/outage-events` | List outage events for a station | PlatformAdmin, NetworkAffiliateRelations, StationGroupOwner, ComplianceAuditor |
| POST | `/networks/{nid}/stations/{sid}/outage-events/{oid}/confirm` | Move event `REPORTED` → `CONFIRMED`; creates outage credit; mutates station outage counter | NetworkAffiliateRelations |
| POST | `/networks/{nid}/stations/{sid}/outage-events/{oid}/reject` | Move event `REPORTED` → `REJECTED` | NetworkAffiliateRelations |
| GET | `/networks/{nid}/stations/{sid}/outage-credits/{oid}` | Fetch outage credit | PlatformAdmin, NetworkAffiliateRelations, StationGroupOwner, ComplianceAuditor |
| GET | `/networks/{nid}/stations/{sid}/outage-credits` | List outage credits for a station | PlatformAdmin, NetworkAffiliateRelations, StationGroupOwner, ComplianceAuditor |
| POST | `/networks/{nid}/stations/{sid}/outage-credits/{oid}/forfeit` | Move credit `PENDING` → `FORFEITED` (only when cause is `PLANNED_MAINTENANCE`) | NetworkAffiliateRelations |
| POST | `/networks/{nid}/stations/{sid}/compliance-reports` | Create a compliance report | StationGroupOwner, ComplianceAuditor |
| GET | `/networks/{nid}/stations/{sid}/compliance-reports/{cid}` | Fetch compliance report | PlatformAdmin, NetworkAffiliateRelations, StationGroupOwner, ComplianceAuditor |
| GET | `/networks/{nid}/stations/{sid}/compliance-reports` | List compliance reports for a station | PlatformAdmin, NetworkAffiliateRelations, StationGroupOwner, ComplianceAuditor |
| POST | `/networks/{nid}/stations/{sid}/compliance-reports/{cid}/submit` | Move report `OPEN` → `SUBMITTED` | StationGroupOwner |
| POST | `/networks/{nid}/stations/{sid}/compliance-reports/{cid}/audit` | Move report `SUBMITTED` → `AUDITED`; records `finding_count` | NetworkAffiliateRelations, ComplianceAuditor |
| POST | `/networks/{nid}/stations/{sid}/compliance-reports/{cid}/resolve-pass` | Move report `AUDITED` → `PASSED` (requires `finding_count` equal to 0) | NetworkAffiliateRelations, ComplianceAuditor |
| POST | `/networks/{nid}/stations/{sid}/compliance-reports/{cid}/resolve-fail` | Move report `AUDITED` → `FAILED` (requires `finding_count` at least 1) | NetworkAffiliateRelations, ComplianceAuditor |
| POST | `/networks/{nid}/territories/{tid}/exclusivity-claims` | File a syndication exclusivity claim | StationGroupOwner |
| GET | `/networks/{nid}/territories/{tid}/exclusivity-claims/{cid}` | Fetch claim | PlatformAdmin, NetworkAffiliateRelations, StationGroupOwner, ComplianceAuditor |
| GET | `/networks/{nid}/territories/{tid}/exclusivity-claims` | List claims for a territory | PlatformAdmin, NetworkAffiliateRelations, StationGroupOwner, ComplianceAuditor |
| POST | `/networks/{nid}/territories/{tid}/exclusivity-claims/{cid}/validate` | Move claim `FILED` → `VALIDATED`; enforces half-open window overlap and holder check | NetworkAffiliateRelations |
| POST | `/networks/{nid}/territories/{tid}/exclusivity-claims/{cid}/dismiss` | Move claim `FILED` → `DISMISSED` | NetworkAffiliateRelations |
| POST | `/networks/{nid}/territories/{tid}/exclusivity-claims/{cid}/settle` | Move claim `VALIDATED` → `SETTLED` | NetworkAffiliateRelations |
| GET | `/stations/{id}` | Fetch a Station by id (flat form for segment derivation) | PlatformAdmin, NetworkAffiliateRelations, StationGroupOwner, ComplianceAuditor |
| GET | `/stations` | Filtered list of stations by foreign keys (`station_group_id`, `network_id`) | PlatformAdmin, NetworkAffiliateRelations, StationGroupOwner, ComplianceAuditor |
| GET | `/territories/{id}` | Fetch a Territory by id (flat form) | PlatformAdmin, NetworkAffiliateRelations, StationGroupOwner, ComplianceAuditor |
| GET | `/territories` | Filtered list of territories by foreign keys (`network_id`, `exclusivity_holder_station_id`) | PlatformAdmin, NetworkAffiliateRelations, StationGroupOwner, ComplianceAuditor |
| GET | `/agreements/{id}` | Fetch an AffiliationAgreement by id (flat form) | PlatformAdmin, NetworkAffiliateRelations, StationGroupOwner, ComplianceAuditor |
| GET | `/agreements` | Filtered list of agreements by foreign keys (`station_id`, `network_id`) | PlatformAdmin, NetworkAffiliateRelations, StationGroupOwner, ComplianceAuditor |
| GET | `/programs/{id}` | Fetch a Program by id (flat form) | PlatformAdmin, NetworkAffiliateRelations, StationGroupOwner, ComplianceAuditor |
| GET | `/programs` | Filtered list of programs by `network_id` | PlatformAdmin, NetworkAffiliateRelations, StationGroupOwner, ComplianceAuditor |
| GET | `/clearance-reports/{id}` | Fetch ClearanceReport by id (flat form) | PlatformAdmin, NetworkAffiliateRelations, StationGroupOwner, ComplianceAuditor |
| GET | `/clearance-reports` | Filtered list of clearance reports by `station_id` | PlatformAdmin, NetworkAffiliateRelations, StationGroupOwner, ComplianceAuditor |
| GET | `/preemptions/{id}` | Fetch PreemptionRequest by id (flat form) | PlatformAdmin, NetworkAffiliateRelations, StationGroupOwner, ComplianceAuditor |
| GET | `/preemptions` | Filtered list of preemptions by `station_id`, `program_id`, `agreement_id` | PlatformAdmin, NetworkAffiliateRelations, StationGroupOwner, ComplianceAuditor |
| GET | `/avail-allocations/{id}` | Fetch AvailAllocation by id (flat form) | PlatformAdmin, NetworkAffiliateRelations, StationGroupOwner, ComplianceAuditor |
| GET | `/avail-allocations` | Filtered list of avail allocations by `station_id`, `program_id` | PlatformAdmin, NetworkAffiliateRelations, StationGroupOwner, ComplianceAuditor |
| GET | `/retrans-settlements/{id}` | Fetch RetransSettlement by id (flat form) | PlatformAdmin, NetworkAffiliateRelations, StationGroupOwner, ComplianceAuditor |
| GET | `/retrans-settlements` | Filtered list of settlements by `station_id`, `agreement_id` | PlatformAdmin, NetworkAffiliateRelations, StationGroupOwner, ComplianceAuditor |
| GET | `/outage-events/{id}` | Fetch OutageEvent by id (flat form) | PlatformAdmin, NetworkAffiliateRelations, StationGroupOwner, ComplianceAuditor |
| GET | `/outage-events` | Filtered list of outage events by `station_id` | PlatformAdmin, NetworkAffiliateRelations, StationGroupOwner, ComplianceAuditor |
| GET | `/outage-credits/{id}` | Fetch OutageCredit by id (flat form) | PlatformAdmin, NetworkAffiliateRelations, StationGroupOwner, ComplianceAuditor |
| GET | `/outage-credits` | Filtered list of outage credits by `station_id`, `outage_event_id`, `settlement_id` | PlatformAdmin, NetworkAffiliateRelations, StationGroupOwner, ComplianceAuditor |
| GET | `/renewal-offers/{id}` | Fetch RenewalOffer by id (flat form) | PlatformAdmin, NetworkAffiliateRelations, StationGroupOwner, ComplianceAuditor |
| GET | `/renewal-offers` | Filtered list of renewal offers by `agreement_id` | PlatformAdmin, NetworkAffiliateRelations, StationGroupOwner, ComplianceAuditor |
| GET | `/compliance-reports/{id}` | Fetch ComplianceReport by id (flat form) | PlatformAdmin, NetworkAffiliateRelations, StationGroupOwner, ComplianceAuditor |
| GET | `/compliance-reports` | Filtered list of compliance reports by `station_id` | PlatformAdmin, NetworkAffiliateRelations, StationGroupOwner, ComplianceAuditor |
| GET | `/exclusivity-claims/{id}` | Fetch SyndicationExclusivityClaim by id (flat form) | PlatformAdmin, NetworkAffiliateRelations, StationGroupOwner, ComplianceAuditor |
| GET | `/exclusivity-claims` | Filtered list of exclusivity claims by `territory_id`, `program_id`, `claimant_station_id`, `respondent_station_id` | PlatformAdmin, NetworkAffiliateRelations, StationGroupOwner, ComplianceAuditor |
| POST | `/_clock/set_current_utc` | Set the server logical clock to an arbitrary non-decreasing ISO 8601 UTC timestamp (default at startup is `2026-05-01T00:00:00Z`); fires time-triggered transitions | PlatformAdmin |

## 5. Error Code Catalogue

The following table enumerates every error code the API may return. Trigger conditions are described in §2 and §3 narratives and are intentionally not repeated here.

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_NETWORK_LOCKDOWN` | 409 |
| `ERR_SOD_VIOLATION` | 403 |
| `ERR_RATE_SUM_MISMATCH` | 422 |
| `ERR_INVALID_TIME_RANGE` | 422 |
| `ERR_AVAIL_POOL_EXHAUSTED` | 409 |
| `ERR_NO_WINDOW_OVERLAP` | 422 |
| `ERR_TERRITORY_EXCLUSIVITY_HELD` | 409 |
| `ERR_PREEMPTION_QUOTA_EXCEEDED` | 422 |
| `ERR_DUPLICATE_COMMITTED_SETTLEMENT` | 409 |
| `ERR_CLAIMANT_NOT_HOLDER` | 422 |
| `ERR_STALE_AGREEMENT_VERSION` | 412 |
| `ERR_STALE_STATION_VERSION` | 412 |
| `ERR_COUNTER_ROUND_EXHAUSTED` | 409 |
| `ERR_FUTURE_OUTAGE` | 422 |
| `ERR_INVALID_TERM_LENGTH` | 422 |
| `ERR_FUTURE_PERIOD` | 422 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_DEFICIENT_CLEARANCE` | 409 |
| `ERR_STALE_VERSION_GENERIC` | 412 |
