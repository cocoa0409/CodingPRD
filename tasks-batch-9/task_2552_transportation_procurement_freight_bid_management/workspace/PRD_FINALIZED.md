# Freight Bid Management API — Product Requirements Document

## 1. Introduction

A shipper's annual transportation procurement event is the single largest cost-setting exercise the logistics organisation runs, and it is almost always run on spreadsheets. Lane histories arrive from three different systems and disagree with each other; carrier insurance certificates are verified by email and re-verified from memory; bid rounds are compared by eye; and the routing guide that finally emerges is a workbook nobody can reproduce six months later when a carrier stops accepting tenders. This API replaces that workbook. It carries a transportation procurement event end to end — lane data preparation, carrier qualification, invitation, multi-round rate negotiation, weighted optimisation, award allocation into primary and backup routing positions, contract execution, rate loading, go-live cutover, tender monitoring, and the mid-contract mini-bid procedures that keep a twelve-month routing guide honest against a moving market.

Two properties drive nearly every design decision below. First, **the numbers must be reproducible**: every cost, score, percentage and allowance is derived by a named rule with a pinned rounding order, so that two parties reading the same event arrive at the same figure to the cent. Second, **volume and money are conserved quantities**: a lane's unallocated volume plus the volume held by its live commitments always equals its planned annual volume, and applying a mid-contract rate adjustment and then reverting it must return the contract's committed value to exactly the figure it held before. Rules that look like bookkeeping trivia — which statuses count toward a rollup, whether a discount tier reads the pre- or post-discount subtotal, whether a percentage is a ratio of sums or a mean of ratios — are therefore normative, not incidental.

The system is also deliberately adversarial about authority. Procurement analysts build events but never award them; compliance officers qualify carriers but never price lanes; the category manager who approved an award allocation is permanently barred from countersigning the resulting contract on the shipper's behalf; and a carrier representative can only ever act on rows belonging to its own carrier. Where two roles could collude by being the same human being, the system checks user identity rather than trusting the role label.

## 2. Global Specifications & System-Wide Principles

This section defines the contract-level rules that hold across every endpoint: authentication, envelope shape, pagination, timekeeping, rounding, concurrency guards, and the fixed order in which rules are evaluated.

### 2.1. User Roles and Access Control

Every request other than the logical-clock endpoint must present two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which it acts. The system recognises exactly five roles, spelled precisely as follows: `ProcurementAnalyst`, `ComplianceOfficer`, `CategoryManager`, `ContractAdmin`, and `CarrierRep`. If either header is absent, or if `X-User-Role` is not one of those five strings, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well formed but the acting role is not among the roles authorised for the endpoint being called, the rejection is `ERR_FORBIDDEN_ROLE` (HTTP 403). Section 4 lists the authorised roles for every endpoint.

Four of the five roles are **opaque operator identities**. When `X-User-Role` is `ProcurementAnalyst`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example, no analyst-owned field exists today, so it is simply carried on the request — but it never compares that value to any entity's `id`. The same holds for `ComplianceOfficer`, whose identifier is recorded as `decision_by_user_id` on the qualification review it decides; for `CategoryManager`, whose identifier is recorded as `approved_by_user_id` on each award allocation it approves; and for `ContractAdmin`, whose identifier is recorded as `shipper_signed_by_user_id` on the contract it countersigns. None of those four values is ever matched against an entity primary key.

`CarrierRep` is different: it is **entity-backed**. When `X-User-Role` is `CarrierRep`, `X-User-ID` is the `id` of the acting `Carrier`, and ownership checks on any resource that references a `Carrier` compare the resource's carrier foreign-key field to `X-User-ID`. Concretely, a `CarrierRep` may withdraw a lane bid only when the bid's `carrier_id` equals `X-User-ID`; may respond to an invitation only when the invitation's `carrier_id` equals `X-User-ID`; may apply the carrier signature only when the contract's `carrier_id` equals `X-User-ID`; may dispute a scorecard only when the scorecard's `carrier_id` equals `X-User-ID`; and may submit a mini-bid proposal or a lane bid only when the `carrier_id` in the request payload equals `X-User-ID`. A mismatch on any of those six operations produces `ERR_NOT_RESOURCE_OWNER` (HTTP 403). Note that `CategoryManager` and `ContractAdmin` are both opaque operator roles, so nothing prevents the same human operator identifier from presenting itself under both labels — which is exactly the compliance hole that the segregation-of-duties rule in §2.11 closes.

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

List endpoints accept two query parameters. `limit` bounds the number of items returned; when omitted it defaults to 10, its minimum accepted value is 1 and its maximum accepted value is 100. `offset` is the number of items to skip before the first returned item and defaults to 0.

Unless a specific collection declares a different ordering in §2.4, list endpoints return their rows sorted by `created_at` in ascending order.

List responses carry `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope.

### 2.4. Collection Reads, Filters and Ordering

Because the entity graph here is flat — foreign keys travel in request bodies and query strings rather than in deep URL paths — the filtered list endpoints are the primary way to walk a relationship backwards. Each collection therefore declares its filter set explicitly, and every filter is optional:

- Carriers may be filtered by `status` and by `diversity_classification`, and are ordered by `created_at` ascending.
- Lanes may be filtered by `bid_event_id`, `incumbent_carrier_id`, `status` and `equipment_type`, and are ordered by `created_at` ascending.
- Invitations may be filtered by `bid_event_id`, `carrier_id` and `status`.
- Lane bids may be filtered by `bid_round_id`, `lane_id`, `carrier_id` and `status`, and are ordered by `rank_in_lane` ascending and then by `created_at` ascending.
- Award allocations may be filtered by `bid_event_id`, `optimization_run_id`, `lane_id`, `carrier_id`, `lane_bid_id`, `routing_position` and `status`.
- Contracts may be filtered by `bid_event_id`, `carrier_id`, `status` and `signature_status`.
- Rate records may be filtered by `contract_id`, `lane_id`, `carrier_id`, `award_allocation_id`, `superseded_by_rate_record_id` and `status`.
- Mini-bids may be filtered by `bid_event_id`, `lane_id`, `rate_record_id`, `applied_rate_record_id`, `proposed_by_carrier_id` and `status`.

Three carrier- or event-scoped collections have their own fixed ordering rather than a filter set. The qualification reviews of one carrier are returned in `created_at` ascending order. The scorecards of one carrier are returned ordered by `period_end` descending and then by `created_at` ascending. The bidding rounds of one event are returned ordered by `round_no` ascending, the optimization runs of one event by `created_at` ascending, and the tender log of one rate record by `tendered_at` ascending and then by `created_at` ascending.

### 2.5. The Logical Procurement Clock

Every instant the system writes or compares is read from a server-side **logical clock**, never from the host wall clock. That covers `created_at` and `updated_at`, every field whose name ends in `_at`, insurance-expiry comparisons, mini-bid window and cooldown arithmetic, rate effective-window checks, and scorecard period boundaries. Before the clock has ever been set it reads exactly `2026-08-01T00:00:00Z`; that fixed default sits at or before every seeded date, so an unset clock is a well-defined earliest instant rather than a drifting real time.

An administrative test-driving capability sets the clock to an absolute UTC instant supplied as `to_iso8601`. It returns HTTP 200, modifies no business row, and is available to all five roles. Uniquely among the endpoints in this specification, it does not require the user-context headers of §2.1.

### 2.6. Common Resource Properties

Thirteen of the fourteen resource types — carriers, qualification reviews, lanes, bid events, bid rounds, invitations, lane bids, optimization runs, award allocations, contracts, rate records, mini-bids and scorecards — carry the same four system-managed fields:

- **`id`** (string): a server-minted UUID, with no type prefix of any kind.
- **`created_at`** (string): an ISO 8601 UTC timestamp with three fractional digits, e.g. `2026-08-01T00:00:00.000Z`, recording when the row was first written.
- **`updated_at`** (string): an ISO 8601 UTC timestamp in the same format, refreshed on every mutation of the row — including mutations the row did not ask for, such as a rollup recomputed by a cascade in another aggregate.
- **`version`** (integer): a counter that increments by one on every mutation of the row, and which the concurrency guards of §2.8 compare against. The counter advances **at most once per request**: where several links of one request mutate the same row — a status change and, later in the same cascade, a rollup recomputation on that very row — each of them refreshes `updated_at`, but the row's `version` rises by exactly one for the request taken as a whole. A row that the request itself creates is written with `version` `1` and is likewise not advanced again by later links of that same request. This is why §3 can state, for an operation whose cascade touches one row more than once, that the row's `version` increases by one.

The `TenderEvent` resource is the exception. A tender outcome is an immutable append to a log, so a tender event carries only `id` and `created_at`. It has **no** `updated_at` field and **no** `version` field, and nothing in the system ever mutates one after it is appended.

### 2.7. Money, Rates and Rounding Discipline

All monetary amounts are decimal values carried to exactly 2 decimal places, and all rounding is **round half up**. Per-mile rates — `rate_per_mile`, `incumbent_rate_per_mile`, `fuel_index_per_mile`, `rate_floor_per_mile` and `proposed_rate_per_mile` — are carried to 4 decimal places. Percentage fields are carried to 2 decimal places, except `claims_ratio`, which is a fraction on a zero-to-one scale carried to 4 decimal places. The ratios internal to the optimisation objective are carried to 6 decimal places and the service credit inside bid ranking to 4 decimal places; the specific rounding points are stated with each rule in §3.

Two aspects of rounding are normative rather than stylistic, and getting either wrong produces a different and incorrect answer even though the inputs are identical. **Rounding order matters**: where a rule rounds two components separately and then adds them, the sum of the two already-rounded components is the answer, and rounding once at the end of the unrounded expression is wrong. **Comparisons read rounded values**: where a rule rounds a percentage and then compares it to a threshold, the comparison uses the rounded figure, not the full-precision one.

Configuration and rate inputs preserve the precision at which they were supplied. Integer quantities — load counts, fleet power units, transit days, mileage, round numbers and counters — are whole numbers and are never expressed with decimals.

### 2.8. Version Guards on Scenario and Amendment Writes

Two write operations in this system can silently destroy state that the calling client has never observed, and both are therefore guarded by an optimistic concurrency check against the `version` of a parent row.

The first is **optimization-run creation**. A `POST /freight-procurement/optimization-runs` request must carry `expected_bid_event_version` as a non-optional field of its payload, holding the `version` of the target `BidEvent` as the client last read it. Creating a run legitimately supersedes every earlier `COMPLETED` or `PUBLISHED` run of that event and releases the lane volume that the earlier run's approved allocations were holding, so a creation carrying an out-of-date view of the event would discard scenario state the client never saw. If `expected_bid_event_version` does not equal the bid event's current `version`, the request is rejected with `ERR_STALE_BID_EVENT_VERSION` (HTTP 412) and nothing is created.

The second is **mini-bid apply**. A `POST /freight-procurement/mini-bids/{id}/apply` request must carry `expected_contract_version` as a non-optional field of its payload, holding the `version` of the affected `Contract` as the client last read it. Applying a mini-bid amends the contract's committed value; if another mini-bid on a different lane of the same contract has already been applied, the contract's `version` has advanced past what the client read, and layering a second amendment onto a committed value the client never saw is exactly the outcome to prevent. A mismatch is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412).

No other endpoint in this specification accepts a version field, and no other endpoint performs a version check. Endpoints that are not one of the two named above must not require, and must not reject on, any `expected_*_version` input.

### 2.9. The Rule Evaluation Ladder

Checks are evaluated in a single fixed ascending order, and **the first violated check decides the response** — no later check is evaluated and no partial write is retained. The ladder is the same for every endpoint; a rung simply has nothing to say on an endpoint it does not apply to. Stating the ladder once here means that when §3 lists several checks guarding one operation, their relative precedence is already determined.

1. **Header integrity.** Both `X-User-ID` and `X-User-Role` are present and the role is one of the five declared names, otherwise `ERR_UNAUTHENTICATED` (401). This applies to every endpoint except the logical-clock endpoint.
2. **Role authorisation.** The acting role appears in the endpoint's authorised list, otherwise `ERR_FORBIDDEN_ROLE` (403). This applies to every endpoint.
3. **Path identifiers.** Every identifier appearing in the request path must resolve to an existing row, validated **left to right** — the parent segment before the child segment — so a request naming a non-existent parent fails on the parent even when the child identifier is also wrong. Each entity raises its own 404: a carrier raises `ERR_CARRIER_NOT_FOUND`, a qualification review `ERR_QUALIFICATION_REVIEW_NOT_FOUND`, a bid event `ERR_BID_EVENT_NOT_FOUND`, a lane `ERR_LANE_NOT_FOUND`, a bid round `ERR_BID_ROUND_NOT_FOUND`, an invitation `ERR_INVITATION_NOT_FOUND`, a lane bid `ERR_LANE_BID_NOT_FOUND`, an optimization run `ERR_OPTIMIZATION_RUN_NOT_FOUND`, an award allocation `ERR_AWARD_ALLOCATION_NOT_FOUND`, a contract `ERR_CONTRACT_NOT_FOUND`, a rate record `ERR_RATE_RECORD_NOT_FOUND`, a mini-bid `ERR_MINI_BID_NOT_FOUND` and a scorecard `ERR_SCORECARD_NOT_FOUND`. This applies to every endpoint carrying a path parameter.
4. **Body shape.** On every POST endpoint, each input field that has no declared default must be present; each supplied value must match its declared type; each enum value must be a declared member of its enumeration; integers standing for volumes or counts must be non-negative; money and rate values must be non-negative; and wherever an interval is supplied, its start must be strictly before its end — `effective_from` before `effective_to`, `period_start` before `period_end`, `window_open_at` before `window_close_at`, `contract_effective_from` before `contract_effective_to`. Any violation is `ERR_INVALID_REQUEST` (400).
5. **Body foreign keys.** Every foreign key supplied in the request **body** must resolve to an existing row, checked in the order the fields are declared for that endpoint, each raising that entity's own 404 from the list in rung 3. This applies to lane creation, invitation creation, lane-bid submission, optimization-run creation, rate-record staging, mini-bid creation and scorecard drafting.
6. **Resource ownership.** When the acting role is `CarrierRep`, `X-User-ID` must equal the carrier that owns the target, as enumerated in §2.1, otherwise `ERR_NOT_RESOURCE_OWNER` (403). This applies to lane-bid withdrawal, invitation response, carrier signature, scorecard dispute, mini-bid proposal and lane-bid submission.
7. **Segregation of duties.** The acting `X-User-ID` must not appear as `approved_by_user_id` on any award allocation matching the contract's pairing of event and carrier, otherwise `ERR_SEGREGATION_OF_DUTIES` (403). This applies only to the shipper signature; §2.11 states it in full.
8. **Version guard.** The supplied `expected_bid_event_version` or `expected_contract_version` equals the parent's current `version`, otherwise `ERR_STALE_BID_EVENT_VERSION` or `ERR_STALE_CONTRACT_VERSION` (412) as described in §2.8. This applies to optimization-run creation and mini-bid apply.
9. **State preconditions.** The target row and its governing parents are in states that permit the operation. The mapping is fixed: a lane still in `DRAFT` when the event's lanes are locked raises `ERR_LANE_NOT_VALIDATED`; inviting carriers or opening the first round before the lane scope is locked raises `ERR_LANES_NOT_LOCKED`; submitting or withdrawing a bid on a round that is not `OPEN` raises `ERR_ROUND_NOT_OPEN`; creating an optimization run while a round of the event is still `OPEN` raises `ERR_ROUND_STILL_OPEN`; publishing a routing guide while the event is not `OPTIMIZING` raises `ERR_EVENT_NOT_OPTIMIZING`; approving an allocation that is not `PROPOSED` raises `ERR_ALLOCATION_NOT_PROPOSED`; taking a rate record live while the contract's `signature_status` is not `FULLY_SIGNED` raises `ERR_CONTRACT_NOT_FULLY_SIGNED`; loading a record that is not `STAGED`, or taking live a record that is not `LOADED`, raises `ERR_RATE_RECORD_NOT_LOADED`; appending a tender to, or applying a mini-bid against, a record that is neither `LIVE` nor `AT_RISK` raises `ERR_RATE_RECORD_NOT_LIVE`; proposing on a mini-bid that is not `REQUESTED`, or applying or denying one that is not `OPEN`, raises `ERR_MINI_BID_NOT_OPEN`; reverting a mini-bid that is not `APPLIED` raises `ERR_MINI_BID_NOT_APPLIED`; deciding a qualification review that has not reached `SCREENED` raises `ERR_REVIEW_NOT_SCREENED`; publishing a scorecard that is already `PUBLISHED` or `DISPUTED` raises `ERR_SCORECARD_ALREADY_PUBLISHED`; disputing a scorecard still in `DRAFT` raises `ERR_SCORECARD_NOT_PUBLISHED`; and a carrier status change whose current-status-to-target-status pair is not one of the declared carrier transitions — including every attempt to leave the terminal `DISQUALIFIED` state — raises `ERR_CARRIER_NOT_QUALIFIED`. All of these carry HTTP 409.
10. **Carrier fitness.** The carrier being bound is fit, per §2.10, otherwise `ERR_CARRIER_SUSPENDED`, `ERR_CARRIER_INSURANCE_EXPIRED` or `ERR_CARRIER_NOT_QUALIFIED` (all 409).
11. **Lane data quality.** The lane carries no blocking data-quality flag when it is validated or when its event's lanes are locked, otherwise `ERR_LANE_DATA_QUALITY_BLOCKED` (409). This applies to lane validation and to event lane-locking.
12. **Bidding relationship.** The bidding carrier stands in the required relationship to the event: an invitation must exist for that pairing of event and carrier, otherwise `ERR_CARRIER_NOT_INVITED` (409), and that invitation's status must be `ACCEPTED`, otherwise `ERR_INVITATION_NOT_ACCEPTED` (409). This applies to lane-bid submission.
13. **Uniqueness.** `scac_code` is unique across all carriers (`ERR_DUPLICATE_SCAC`); `lane_code` is unique within its bid event (`ERR_DUPLICATE_LANE_CODE`); at most one non-`REVOKED` invitation may exist per pairing of event and carrier (`ERR_DUPLICATE_INVITATION`); at most one non-`WITHDRAWN` lane bid may exist per combination of round, lane and carrier (`ERR_DUPLICATE_LANE_BID`); and `load_reference` is unique within its rate record (`ERR_DUPLICATE_LOAD_REFERENCE`). All carry 409, and the rung applies to carrier registration, lane creation, invitation creation, lane-bid submission and tender append.
14. **Time-window integrity.** Rate intervals and mini-bid windows must not collide, raising `ERR_RATE_INTERVAL_OVERLAP`, `ERR_RATE_NOT_IN_EFFECTIVE_WINDOW`, `ERR_MINI_BID_WINDOW_CONFLICT` or `ERR_MINI_BID_COOLDOWN_ACTIVE` (all 409) as detailed in §3.8 and §3.9. This rung applies to rate-record loading, rate go-live, mini-bid creation and mini-bid apply.
15. **Structural constraints.** The bid's lane must belong to the round's event (`ERR_LANE_NOT_IN_EVENT_SCOPE`); `transit_days_offered` must not exceed the lane's `service_days_required` (`ERR_TRANSIT_DAYS_EXCEEDED`); an invitation requiring an NDA cannot be accepted without one (`ERR_NDA_NOT_SIGNED`); a new bidding round must not push the event past its permitted round count (`ERR_ROUND_LIMIT_EXCEEDED`); and a qualification review must not be sent back for remediation more times than the remediation ceiling allows (`ERR_REMEDIATION_LIMIT_EXCEEDED`). All carry 409, and the rung applies to lane-bid submission, invitation response, round creation and review decision.
16. **Rolling mini-bid quota.** A lane may not exceed its rolling mini-bid quota, otherwise `ERR_MINI_BID_QUOTA_EXCEEDED` (409). This applies to mini-bid creation.
17. **Per-rate money limits.** A submitted or proposed per-mile rate must be at or above the event's rate floor (`ERR_RATE_BELOW_FLOOR`); a returning bidder in a round carrying a reduction target must meet that target (`ERR_RATE_ABOVE_ROUND_TARGET`); and a mini-bid's adjustment must stay inside the adjustment cap (`ERR_ADJUSTMENT_EXCEEDS_CAP`). All carry HTTP 422, and the rung applies to lane-bid submission, mini-bid proposal and mini-bid apply.
18. **Portfolio money limits.** Evaluated across the whole award: no approved allocation's `allocated_pct` may exceed the event's maximum single-carrier share (`ERR_AWARD_SHARE_EXCEEDED`); the event's `diversity_pct` must reach its diversity minimum (`ERR_DIVERSITY_MINIMUM_NOT_MET`); a run's `coverage_pct` must reach its minimum capacity coverage before its guide may be published (`ERR_COVERAGE_BELOW_MINIMUM`); and a run whose status is `FAILED` may never be published (`ERR_NO_FEASIBLE_ALLOCATION`). All carry HTTP 422, and the rung applies to routing-guide publication and to the award commit.

Because rung 11 sits above rung 12, a lane whose data is blocked reports its data-quality failure rather than an invitation problem; because rung 9 sits above rung 10, a request against a wrongly-stated row reports the state conflict rather than a carrier-fitness conflict; and because rung 17 sits above rung 18, a single below-floor rate surfaces as a rate error rather than as a portfolio shortfall.

### 2.10. Carrier Standing as a Portfolio-Wide Gate

A carrier's `status` is the system's single expression of whether it may be bound to new commercial obligations, and it is re-checked at the moment of every such write rather than trusted from an earlier check. Six operations consult it: inviting a carrier to an event, submitting a lane bid, approving an award allocation, loading a rate record, taking a rate record live, and submitting a mini-bid proposal. In all six the checks are the same three, and they are distinguishable by their error identifiers. A carrier whose `status` is `SUSPENDED` or `DISQUALIFIED` is rejected with `ERR_CARRIER_SUSPENDED`. A carrier whose `insurance_expiry_date` is at or before the logical clock is rejected with `ERR_CARRIER_INSURANCE_EXPIRED` — note the strictness: the certificate must expire strictly after the current instant, so a certificate expiring exactly now is expired. A carrier that has not reached `QUALIFIED`, `CONDITIONALLY_QUALIFIED` or `WATCHLIST` standing where the operation requires standing is rejected with `ERR_CARRIER_NOT_QUALIFIED`.

That same third error identifier does double duty as the rejection for an illegal carrier status change, as rung 9 of §2.9 states.

### 2.11. Segregation of Duties Between Award and Signature

The operator who approved an award may never countersign the resulting contract on the shipper's side. Precisely: when a shipper signature is applied to a contract, the acting `X-User-ID` must not appear as `approved_by_user_id` on **any** award allocation whose pairing of `bid_event_id` and `carrier_id` matches that contract's own pairing. It does not matter that the approval was performed under the `CategoryManager` label and the signature under the `ContractAdmin` label; because both are opaque operator identities, the same person can hold both, and it is the identifier — not the role — that is compared. A violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), and the bar is permanent: no later state change lifts it.

The carrier-side signature carries no equivalent restriction; it is gated only by the ownership rule of §2.1.

### 2.12. Cascade Discipline, Rollups and Conserved Quantities

Several operations in this system mutate rows in more than one aggregate, and each such mutation is a real mutation: the affected row's `updated_at` is refreshed and its `version` incremented, even when the row was touched only because a rollup it owns had to be recomputed. Cascades are described in §3 as numbered links, and each link is caused by the link before it — a reader who implements link 1 but not link 4 has produced a system whose rollups drift permanently out of alignment.

Two quantities are conserved and are worth stating up front, because most of the cascade bookkeeping exists to protect them.

**Lane volume.** For every lane, the sum of `unallocated_volume_loads` and the `allocated_volume_loads` of that lane's award allocations whose status is `APPROVED`, `EXECUTED`, `ACTIVE` or `SUSPENDED_ROUTING` always equals the lane's `annual_volume_loads`. A `PROPOSED` allocation reserves nothing at all: the debit against `unallocated_volume_loads` is taken when the allocation is approved and credited back exactly when it is rejected or superseded. When a backup promotion changes the allocated volume of an allocation that already holds a debit, only the delta is applied, in the same request.

**Contract value.** A contract's `total_committed_value_usd` is derived only from rate records that are still part of its rate basis. Applying a mini-bid removes the superseded record from that basis and adds a replacement; reverting the mini-bid restores the original and removes the replacement. Consequently, after an apply followed by a revert, `total_committed_value_usd` equals the value snapshotted in `contract_value_before_usd` exactly, to the cent, and not merely to within a rounding step.

Finally, several rollups are defined as counts or sums over specific status sets rather than as running increments, and where the two readings could differ, the status set governs. `BidEvent.invited_carrier_count` counts invitations whose status is `SENT`, `ACCEPTED` or `DECLINED`, so a revoked invitation drops out of it. `BidEvent.accepted_invitation_count` counts invitations whose status is `ACCEPTED`. `BidEvent.lane_count` counts the lanes of the event. `BidRound.submitted_bid_count` counts lane bids on the round whose status is `SUBMITTED`, `SHORTLISTED`, `AWARDED_PRIMARY`, `AWARDED_BACKUP` or `NOT_AWARDED`, so withdrawal removes a bid from the count while award does not. `BidRound.lowest_rate_per_mile` is the minimum `rate_per_mile` across the round's bids whose status is `SUBMITTED`, and is null when the round holds none. `Carrier.active_primary_lane_count` counts that carrier's award allocations whose `routing_position` is `PRIMARY` and whose status is `EXECUTED` or `ACTIVE`. `Carrier.committed_volume_loads` sums `allocated_volume_loads` over that carrier's allocations whose status is `EXECUTED`, `ACTIVE` or `SUSPENDED_ROUTING`. `Contract.rate_record_count` counts the contract's rate records whose status is `STAGED`, `LOADED`, `LIVE` or `AT_RISK`. `RateRecord.tender_count` counts every tender event on the record regardless of outcome.

## 3. Business Logic & Workflows

### 3.1. Carrier Registration and the Qualification Fork

A carrier enters the system through registration by a procurement analyst. The registration payload carries the carrier's `legal_name`, between 1 and 120 characters; its `scac_code`, exactly four uppercase letters in the range A through Z, which must be unique across every carrier in the system — a repeat is rejected with `ERR_DUPLICATE_SCAC`; its `service_modes`, a non-empty set drawn from `DRY_VAN`, `REEFER` and `FLATBED`; its `fleet_power_units`, an integer of at least 1; its `auto_liability_limit_usd` and `cargo_limit_usd`, non-negative money amounts at 2 decimal places taken from the certificate of insurance; and its `insurance_expiry_date`, the certificate's expiry instant. Optionally the payload may state a `diversity_classification`, one of `NONE`, `MWBE`, `VETERAN_OWNED` or `SMALL_BUSINESS`; when omitted it is `NONE`.

A newly registered carrier is created with `status` set to `REGISTERED`, `status_reason` null, `capability_score` `0.00`, `published_scorecard_count` `0`, `active_primary_lane_count` `0`, `committed_volume_loads` `0` and `qualified_at` null. Its `composite_score` is computed immediately and its `composite_score_variant` is `PROVISIONAL_SCREENING`, because no performance history exists yet; the composite rule is stated in §3.2.

A carrier's `status` moves through `REGISTERED`, `SCREENING`, `QUALIFIED`, `CONDITIONALLY_QUALIFIED`, `WATCHLIST`, `SUSPENDED` and `DISQUALIFIED`. `REGISTERED` is where every carrier begins, and `DISQUALIFIED` is terminal: once a carrier reaches it, no transition out exists, and any attempt to move it elsewhere is rejected under rung 9 of §2.9 with `ERR_CARRIER_NOT_QUALIFIED`.

**Opening a review.** A compliance officer opens a qualification review against a `REGISTERED` carrier. The review payload states `required_modes`, a non-empty set drawn from the same three equipment modes, describing what the shipper needs this carrier to be able to haul; and it may optionally state `min_auto_liability_usd`, defaulting to `1000000.00`, and `min_cargo_usd`, defaulting to `100000.00`, the insurance thresholds the carrier will be measured against. A review may be opened only when the carrier's `status` is `REGISTERED` and no earlier review of that carrier is still in flight — that is, none of its reviews has status `SUBMITTED`, `SCREENED` or `REMEDIATION`; an attempt against a carrier who fails either condition is a state conflict and is rejected with HTTP 409. Opening the review moves the carrier from `REGISTERED` to `SCREENING` and creates the review with `status` `SUBMITTED`, `insurance_result` `PENDING`, `capability_result` `PENDING`, `remediation_count` `0`, and `insurance_verified_at`, `capability_screened_at`, `decision_outcome`, `decision_note` and `decision_by_user_id` all null.

The review then runs as a **fork with two independent arms that must both complete before the review may be decided**. The insurance arm and the capability arm may be executed in either order; each is performed by a compliance officer; and the review advances from `SUBMITTED` to `SCREENED` at the moment the second arm records a non-`PENDING` result. Neither arm alone advances the review.

**The insurance arm.** The compliance officer records what the certificate actually says: `verified_auto_liability_usd`, `verified_cargo_usd` and `verified_expiry_date`. The arm may only be run while the review's `insurance_result` is `PENDING`. The result is `PASS` when all three of the following hold — `verified_auto_liability_usd` is greater than or equal to the review's `min_auto_liability_usd`, `verified_cargo_usd` is greater than or equal to its `min_cargo_usd`, and `verified_expiry_date` is strictly after the current logical clock instant — and `FAIL` if any of the three does not hold. Either way, `insurance_verified_at` is set to the clock. **Only on a `PASS`** are the verified figures written back to the carrier, overwriting `auto_liability_limit_usd`, `cargo_limit_usd` and `insurance_expiry_date` with the verified values; on a `FAIL` the carrier's own insurance fields are left exactly as registered. If `capability_result` is already `PASS` or `FAIL` when this arm completes, the review advances from `SUBMITTED` to `SCREENED`.

**The capability arm.** This arm takes no payload; it derives everything from the carrier and the review. It computes the review's `capability_score` from four inputs, in this order:

- **Mode coverage.** Count how many of the review's `required_modes` also appear in the carrier's `service_modes`. Divide that count by the number of `required_modes`, multiply by `100.00`, and round to 2 decimal places. A carrier able to haul every required mode scores `100.00`; one able to haul two of three scores `66.67`.
- **Fleet adequacy.** Divide `fleet_power_units` by the fleet target of 200 power units, multiply by `100.00`, round to 2 decimal places, and then cap the result at `100.00`. A fleet of 240 units therefore scores `100.00`, not `120.00`.
- **Insurance headroom.** Divide `auto_liability_limit_usd` by `min_auto_liability_usd`, round to 4 decimal places, and cap at `1.0000`; do the same with `cargo_limit_usd` over `min_cargo_usd`. Multiply each capped ratio by `50.00`, add the two products, and round to 2 decimal places. A carrier at or above both thresholds scores `100.00`.
- **Weighted total.** Multiply the mode coverage by `0.40`, the fleet adequacy by `0.30` and the insurance headroom by `0.30`, add the three products, and round to 2 decimal places. That figure is the review's `capability_score`.

The arm may only be run while `capability_result` is `PENDING`. The result is `PASS` when the review's `required_modes` are all contained in the carrier's `service_modes` **and** the computed `capability_score` is greater than or equal to the capability pass floor of `70.00`; otherwise it is `FAIL`. `capability_screened_at` is set to the clock. The carrier's own `capability_score` is updated to the computed figure **whether the result is `PASS` or `FAIL`** — the screening measurement is recorded regardless of whether it clears the floor, because it feeds the composite score. If `insurance_result` is already `PASS` or `FAIL` when this arm completes, the review advances from `SUBMITTED` to `SCREENED`.

**Deciding the review.** Once the review is `SCREENED`, a compliance officer records a `decision_outcome`, optionally with a `decision_note`. A decision attempted while the review is still `SUBMITTED` or `REMEDIATION` is rejected with `ERR_REVIEW_NOT_SCREENED` (409). In every branch the review records `decision_outcome`, `decision_note` and `decision_by_user_id` set to the acting `X-User-ID`. The four outcomes are symmetric in structure and differ in their preconditions and consequences:

- **`APPROVE`** requires that `insurance_result` is `PASS` **and** `capability_result` is `PASS`. The review moves from `SCREENED` to `APPROVED`. The carrier moves from `SCREENING` to `QUALIFIED`, its `capability_score` is set from the review's `capability_score`, its `qualified_at` is set to the logical clock, and its `composite_score` and `composite_score_variant` are recomputed.
- **`APPROVE_CONDITIONAL`** requires that `insurance_result` is `PASS` **and** `capability_result` is `FAIL` — that is, the carrier is properly insured but does not clear the capability floor. The review moves from `SCREENED` to `CONDITIONALLY_APPROVED`. The carrier moves from `SCREENING` to `CONDITIONALLY_QUALIFIED`, and exactly as in the approval branch its `capability_score` is set from the review, its `qualified_at` is set to the clock, and its composite score and variant are recomputed.
- **`REMEDIATE`** requires that the review's `remediation_count` is strictly less than the remediation ceiling of 2; a third attempt to send the same review back is rejected with `ERR_REMEDIATION_LIMIT_EXCEEDED` (409). The review moves from `SCREENED` to `REMEDIATION`, `remediation_count` increases by one, and **both** arm results are reset to `PENDING`, reopening the fork. The carrier remains in `SCREENING`; nothing on the carrier is rewritten. Re-running either arm on a review in `REMEDIATION` returns it to `SUBMITTED`, from which the ordinary fork-and-join behaviour resumes: the second arm to complete moves it to `SCREENED` again.
- **`REJECT`** has no result precondition beyond the review being `SCREENED`. The review moves from `SCREENED` to `REJECTED`. The carrier moves from `SCREENING` straight to the terminal `DISQUALIFIED`, and its `status_reason` is set to the `decision_note` supplied with the decision.

`APPROVED`, `CONDITIONALLY_APPROVED` and `REJECTED` are all terminal review states; a decided review is never reopened.

**Administrative status changes.** A compliance officer may also move a carrier's `status` directly, supplying the target as `to_status` together with a mandatory `reason` that is written to `status_reason`. Only the following pairings are declared, and any other pairing of current status and `to_status` is rejected with `ERR_CARRIER_NOT_QUALIFIED` (409):

- **Suspension.** A carrier whose `status` is `REGISTERED`, `SCREENING`, `QUALIFIED`, `WATCHLIST` or `CONDITIONALLY_QUALIFIED` may be moved to `SUSPENDED`. Suspension is a commercial freeze rather than a termination: it blocks every new binding described in §2.10 while leaving existing rows intact.
- **Reinstatement.** A carrier whose `status` is `SUSPENDED` may be moved to `QUALIFIED`, but only when its `insurance_expiry_date` is strictly after the logical clock — a carrier cannot be reinstated on a lapsed certificate. Reinstatement sets `qualified_at` to the clock.
- **Disqualification.** A carrier may be moved to `DISQUALIFIED` from any status other than `DISQUALIFIED` itself. This is terminal, and it triggers a withdrawal cascade in two links. First, every invitation held by that carrier whose status is `SENT` or `ACCEPTED` moves to `REVOKED`. Second, because those invitations no longer stand, every lane bid belonging to that carrier whose status is `SUBMITTED` and whose round is still `OPEN` moves to `WITHDRAWN`, and each affected round's `submitted_bid_count` and `lowest_rate_per_mile` are recomputed over what remains.

Every accepted status change also recomputes the carrier's `composite_score` and `composite_score_variant`, because insurance headroom is one of the composite's inputs. The `WATCHLIST` status is never reached or left by administrative action; it is reached and left only by the scorecard cascade of §3.2.

### 3.2. Carrier Standing Over Time: Scorecards and Composite Re-Scoring

Qualification establishes whether a carrier may be used. Scorecards establish how well it has been performing, and they continuously feed back into the composite score that ranks its bids and, in one case, into its qualification standing itself.

**Drafting a period scorecard.** A category manager drafts a scorecard against a carrier for a measurement period. The payload carries `period_start` and `period_end`, with `period_end` strictly after `period_start`; `on_time_pct`, a percentage between `0.00` and `100.00` at 2 decimal places, supplied from the shipper's delivery records; and `claims_ratio`, a fraction between `0.0000` and `1.0000` at 4 decimal places, expressing claims as a proportion of shipments. The scorecard is created with `status` `DRAFT`, `published_at` null and `disputed_reason` null, and its `composite_score` is computed on the spot from four steps:

- **Select the period's tenders.** Take every tender event recorded against a rate record belonging to this carrier whose `tendered_at` falls inside the **half-open** window from `period_start` inclusive to `period_end` exclusive. A tender stamped exactly at `period_start` is in the period; a tender stamped exactly at `period_end` belongs to the next period, not this one. The selection deliberately ignores the current status of the rate record the tender sits on, so tenders on records that have since been superseded or rolled back still count toward the period in which they occurred. The count of those tenders is `period_tender_count`.
- **Derive tender acceptance.** When `period_tender_count` is zero, `tender_acceptance_pct` is `100.00` — a carrier that was never tendered in the period is not penalised for it. Otherwise divide the number of those tenders whose `outcome` is `ACCEPTED` by `period_tender_count`, multiply by `100.00`, and round to 2 decimal places.
- **Derive the claims subscore.** Multiply `claims_ratio` by 1000, subtract that product from `100.00`, round to 2 decimal places, and then floor the result at `0.00` so it never goes negative. A `claims_ratio` of `0.0150` therefore yields `85.00`; a ratio of `0.1200` yields `0.00` rather than a negative number.
- **Weight the three components.** Multiply `on_time_pct` by `0.45`, `tender_acceptance_pct` by `0.35` and the claims subscore by `0.20`, add the three products, and round to 2 decimal places. That figure is the scorecard's `composite_score`.

Drafting a scorecard does not touch the carrier in any way. A `DRAFT` scorecard is invisible to the carrier's own composite score.

**Publishing a scorecard.** A category manager publishes a `DRAFT` scorecard; the scorecard moves from `DRAFT` to `PUBLISHED` and `published_at` is set to the logical clock. Publication requires that the scorecard's `period_end` is at or before the current clock instant — an unfinished period cannot be published. A scorecard that is already `PUBLISHED`, or that has since been `DISPUTED`, cannot be published again and is rejected with `ERR_SCORECARD_ALREADY_PUBLISHED` (409). Publication re-evaluates the period score from current data before recording it, so a tender appended after the draft was written is included.

Publication then drives a three-link cascade into the carrier:

1. The carrier's `published_scorecard_count` is recomputed as the number of that carrier's scorecards that participate in the composite lookback — that is, the count of its `PUBLISHED` and `DISPUTED` scorecards, capped at three, since only the three most recent participate.
2. The carrier's `composite_score` and `composite_score_variant` are recomputed by the composite rule below. The first publication is what flips the variant: because the final-variant threshold is one scorecard, a carrier goes from `PROVISIONAL_SCREENING` to `FINAL_PERFORMANCE` as soon as its first scorecard is published.
3. Because link 2 may have moved the composite across the watchlist floor of `75.00`, the carrier's standing is re-evaluated. A carrier whose `status` is `QUALIFIED` and whose new `composite_score` is strictly below `75.00` moves to `WATCHLIST`, with `status_reason` set to `SCORECARD_BELOW_FLOOR`. Conversely, a carrier whose `status` is `WATCHLIST` and whose new `composite_score` is at or above `75.00` moves back to `QUALIFIED`, with `status_reason` cleared to null. Carriers in any other status — `CONDITIONALLY_QUALIFIED`, `SUSPENDED`, `DISQUALIFIED`, `REGISTERED` or `SCREENING` — are left where they are by this link. Because `WATCHLIST` is one of the statuses eligible to bid and to hold an allocation, a watchlisted carrier keeps trading; the flag is a signal, not a suspension.

**Disputing a scorecard.** A carrier representative may dispute a scorecard belonging to its own carrier, supplying a `disputed_reason`. The scorecard must be `PUBLISHED`; a scorecard still in `DRAFT` cannot be disputed and the attempt is rejected with `ERR_SCORECARD_NOT_PUBLISHED` (409). The scorecard moves from `PUBLISHED` to `DISPUTED`, which is terminal. Disputing changes no score: the carrier's `composite_score` is deliberately **not** recomputed, and a `DISPUTED` scorecard remains inside the composite lookback exactly as it was. A dispute records the carrier's objection for human follow-up; it does not let a carrier improve its own ranking by objecting to a bad period.

**The composite score.** A carrier's `composite_score` is recomputed on every qualification decision, on every scorecard publication and on every administrative status change. It is produced as follows:

- **Assemble the lookback.** Take that carrier's scorecards whose `status` is `PUBLISHED` or `DISPUTED`, order them by `period_end` descending and then by `created_at` ascending, and keep at most the first three. `published_scorecard_count` is the size of that kept list.
- **Choose the variant.** When the kept list holds at least one scorecard, `composite_score_variant` is `FINAL_PERFORMANCE`; when it is empty, the variant is `PROVISIONAL_SCREENING`.
- **Derive the performance component.** Under `PROVISIONAL_SCREENING` the performance component is the fixed provisional baseline of `90.00`, since there is no evidence either way. Under `FINAL_PERFORMANCE` the recency weights `0.50`, `0.30` and `0.20` are taken in order and truncated to the number of scorecards actually kept; each kept scorecard's `composite_score` is multiplied by its positional weight; the products are summed; that sum is divided by **the sum of the weights actually used**, not by 1.00; and the quotient is rounded to 2 decimal places. With three scorecards the divisor is `1.00`; with two it is `0.80`; with one it is `0.50`, which makes a single-scorecard carrier's performance component equal to that scorecard's own score. This rounding happens **before** weighting into the composite.
- **Derive the insurance component.** If the carrier's `insurance_expiry_date` is at or after the logical clock advanced by 90 days of headroom, the insurance component is `100.00`; otherwise it is `60.00`. There is no intermediate value: a certificate with 91 days left scores full marks and one with 89 days left scores the thin figure.
- **Combine.** Multiply the performance component by `0.70`, the carrier's `capability_score` by `0.20` and the insurance component by `0.10`, add the three products, and round to 2 decimal places. That is the carrier's `composite_score`.

### 3.3. Preparing the Lane Package and Freezing the Baseline

**Creating the event.** A procurement analyst opens a bid event, which is the container for everything that follows. Its payload carries a `name` of 1 to 120 characters; a `cost_basis` of either `FORECAST` or `HISTORICAL`, which decides how every bid in the event is evaluated; a `rate_floor_per_mile`, strictly greater than zero at 4 decimal places, below which no rate will be accepted; four weights — `cost_weight`, `service_weight`, `capacity_weight` and `diversity_weight` — each between `0.00` and `1.00` at 2 decimal places, which **must sum to exactly `1.00`**, a payload that does not being rejected with `ERR_INVALID_REQUEST` (400); and `contract_effective_from` and `contract_effective_to`, with the end strictly after the start, which are the dates the resulting contracts will carry. Optionally it may state `fuel_index_per_mile`, a non-negative per-mile fuel adder defaulting to `0.4500`; `accessorial_inflation_factor`, between `1.00` and `2.00` and defaulting to `1.15`; `rounds_allowed`, an integer between 1 and 4 defaulting to 2; `diversity_min_pct`, defaulting to `10.00`; `max_award_share_pct`, defaulting to `60.00`; and `max_carriers_per_lane`, an integer between 1 and 3 defaulting to 3.

The event is created with `status` `DRAFT`, `current_round_no` `0`, `lane_count` `0`, `invited_carrier_count` `0`, `accepted_invitation_count` `0`, `total_scope_volume_loads` `0`, `coverage_pct` `0.00`, `diversity_pct` `0.00`, and `baseline_cost_usd`, `award_cost_usd`, `savings_pct` and `awarded_at` all null. Its `status` will travel forward through `DRAFT`, `LANES_LOCKED`, `INVITING`, `ROUND_OPEN`, `ROUND_CLOSED`, `OPTIMIZING`, `AWARDING`, `AWARDED` and finally the terminal `LIVE`, with one deliberate backward edge: an event in `ROUND_CLOSED` may re-enter `ROUND_OPEN` when another negotiation round is opened, and an event in `OPTIMIZING` or `AWARDING` may return to `OPTIMIZING` when a fresh optimisation is run. That cycle is what makes multi-round negotiation and scenario re-running possible.

**Adding lanes.** While the event is still `DRAFT`, the analyst adds lanes to it. Each lane carries a `lane_code` of 1 to 32 characters, unique within its bid event — a repeat inside the same event is rejected with `ERR_DUPLICATE_LANE_CODE`, while the same code in a different event is perfectly legal; `origin_zip3` and `dest_zip3`, each exactly three digits; an `equipment_type` of `DRY_VAN`, `REEFER` or `FLATBED`; `mileage`, an integer of at least 1; `annual_volume_loads`, an integer of at least 1, the planned volume being procured; `service_days_required`, an integer of at least 1, the maximum transit the shipper will accept; and `accessorial_history_usd_per_load`, a non-negative money amount at 2 decimal places. Optionally it may carry `trailing_12m_actual_loads`, a non-negative integer of what actually shipped, which defaults to null; `seasonality_peak_index`, between `1.00` and `2.00` at 2 decimal places, defaulting to `1.00`; `incumbent_carrier_id`, defaulting to null; and `incumbent_rate_per_mile`, strictly positive at 4 decimal places, defaulting to null.

A new lane is created with `status` `DRAFT`, `unallocated_volume_loads` equal to its `annual_volume_loads`, `awarded_coverage_pct` `0.00`, and `baseline_cost_usd` and `validated_at` null. Its `data_quality_flags` are computed immediately, and the event's `lane_count` is increased by one. Lane statuses are `DRAFT`, `VALIDATED`, `LOCKED`, `AWARDED` and `UNDER_REBID`; none of them is terminal, because a lane that goes into mid-contract rebid can be returned to `AWARDED`.

**Data quality flags.** A lane's `data_quality_flags` are recomputed from scratch on every evaluation — the list is replaced wholesale, never appended to, so a flag whose underlying condition has been corrected disappears. Each condition is tested independently and the flags that fire are emitted in exactly this declared order, with no sorting and no de-duplication:

1. `MILEAGE_IMPLAUSIBLE` fires when `mileage` is below the plausible minimum of 25 miles or above the plausible maximum of 3200 miles.
2. `MISSING_TRAILING_VOLUME` fires when `trailing_12m_actual_loads` is null, or when it is present but equal to zero.
3. `VOLUME_VARIANCE_HIGH` fires when `trailing_12m_actual_loads` is greater than zero and the planned volume diverges too far from it: take the absolute difference between `annual_volume_loads` and `trailing_12m_actual_loads`, multiply by `100.00`, divide by `annual_volume_loads`, round to 2 decimal places, and fire the flag when that percentage is strictly greater than the tolerance of `25.00`. A variance of exactly `25.00` does not fire.
4. `SEASONALITY_EXTREME` fires when `seasonality_peak_index` is greater than or equal to `1.50`.
5. `NO_INCUMBENT_BASELINE` fires when either `incumbent_carrier_id` or `incumbent_rate_per_mile` is null; one without the other is not a usable baseline.
6. `ACCESSORIAL_OUTLIER` fires only when an incumbent rate exists. Multiply `mileage` by `incumbent_rate_per_mile` and round to 2 decimal places to obtain a linehaul reference; multiply that reference by the outlier ratio of `0.10`, round to 2 decimal places, and fire the flag when `accessorial_history_usd_per_load` is strictly greater than that product. When `incumbent_rate_per_mile` is null no reference exists and this flag cannot fire, regardless of how large the accessorial history is.

Two of the six are **blocking**: `MILEAGE_IMPLAUSIBLE` and `MISSING_TRAILING_VOLUME`. The other four — `VOLUME_VARIANCE_HIGH`, `SEASONALITY_EXTREME`, `NO_INCUMBENT_BASELINE` and `ACCESSORIAL_OUTLIER` — are advisory: they are recorded and they can affect downstream arithmetic, but they never stop a lane from progressing.

**Validating a lane.** The analyst validates a lane while both the lane's `status` is `DRAFT` and its event's `status` is `DRAFT`. Validation recomputes the flags from scratch first; if the resulting list contains either blocking flag, the request is rejected with `ERR_LANE_DATA_QUALITY_BLOCKED` (409) and the lane stays in `DRAFT`. Otherwise `unallocated_volume_loads` is reset to `annual_volume_loads`, `baseline_cost_usd` is computed, `validated_at` is set to the logical clock, and the lane moves from `DRAFT` to `VALIDATED`.

**The lane baseline.** A lane's `baseline_cost_usd` is what the shipper is paying today, and it is computed in three rounding steps taken in order, none of which may be collapsed into the others. First, multiply `mileage` by `incumbent_rate_per_mile` and round to 2 decimal places to obtain the baseline linehaul per load. Second, add `accessorial_history_usd_per_load` to that already-rounded figure and round the sum to 2 decimal places to obtain the baseline cost per load. Third, multiply that already-rounded per-load figure by `annual_volume_loads` and round to 2 decimal places. When `incumbent_rate_per_mile` is null the baseline is `0.00` outright. The baseline is a historical figure and is **never** touched by `accessorial_inflation_factor`; only forward-looking bid evaluation inflates accessorials.

**Locking the lane scope.** When the lane package is ready, the analyst locks it. Locking requires the event to be in `DRAFT` and to hold at least one lane; every lane of the event must be `VALIDATED`, and a lane still in `DRAFT` causes rejection with `ERR_LANE_NOT_VALIDATED` (409); and no lane may carry a blocking data-quality flag, a re-check that raises `ERR_LANE_DATA_QUALITY_BLOCKED` (409) if data has degraded since validation. The lock then does three things: every `VALIDATED` lane of the event moves to `LOCKED`; each locked lane's `baseline_cost_usd` is recomputed so the frozen scope carries current figures; and the event's `total_scope_volume_loads` and `baseline_cost_usd` are rolled up. The event moves from `DRAFT` to `LANES_LOCKED` and its `version` increases by one. From this point the lane scope is fixed: lanes are neither added nor re-validated for the rest of the event.

**Event-level scope, savings and coverage rollups.** Five figures on the event are derived together, and every one of them reads a specific status set:

- `total_scope_volume_loads` is the sum of `annual_volume_loads` over the event's lanes whose `status` is `VALIDATED`, `LOCKED`, `AWARDED` or `UNDER_REBID`. Lanes still in `DRAFT` are outside the scope.
- `baseline_cost_usd` is the sum of `baseline_cost_usd` over those same lanes, **excluding any lane whose `data_quality_flags` contain `NO_INCUMBENT_BASELINE`**, rounded to 2 decimal places. A lane with no incumbent contributes nothing to the baseline, so it can never manufacture apparent savings.
- `award_cost_usd` is `0.00` when the event has no contracts at all; otherwise it is the sum of `total_committed_value_usd` over the event's contracts whose `status` is `DRAFT`, `EXECUTED` or `AMENDED`, rounded to 2 decimal places.
- `savings_pct` is `0.00` whenever `baseline_cost_usd` is `0.00` or `award_cost_usd` is `0.00`; otherwise subtract `award_cost_usd` from `baseline_cost_usd`, multiply the difference by `100.00`, divide by `baseline_cost_usd`, and round to 2 decimal places. This figure **may legitimately be negative** when the award costs more than the incumbent baseline — a real and reportable outcome in a tight market, not an error to be clamped at zero.
- `coverage_pct` is `0.00` when `total_scope_volume_loads` is zero; otherwise it is the sum of `allocated_volume_loads` over the event's award allocations whose `status` is `APPROVED`, `EXECUTED`, `ACTIVE` or `SUSPENDED_ROUTING`, multiplied by `100.00`, divided by `total_scope_volume_loads`, rounded to 2 decimal places. `diversity_pct` is `0.00` when that allocated sum is zero; otherwise it is the portion of that same allocated sum belonging to carriers whose `diversity_classification` is anything other than `NONE`, multiplied by `100.00`, divided by the total allocated sum, and rounded to 2 decimal places. Both percentages are volume-weighted, not headcount-weighted: one diverse carrier holding half the volume yields `50.00`, not a fraction based on how many carriers were used.

### 3.4. Inviting Carriers and Opening Negotiation Rounds

**Issuing an invitation.** With the lane scope locked, the procurement analyst invites carriers. The payload names the `carrier_id` and may state `nda_required`, which defaults to `true`. Inviting before the scope is locked is rejected with `ERR_LANES_NOT_LOCKED` (409). The carrier must be fit in the sense of §2.10 — not suspended or disqualified, insurance not expired, and standing at `QUALIFIED`, `CONDITIONALLY_QUALIFIED` or `WATCHLIST`. At most one invitation that is not `REVOKED` may exist for a given pairing of event and carrier; a duplicate is rejected with `ERR_DUPLICATE_INVITATION` (409), while re-inviting a carrier whose earlier invitation was revoked is permitted.

The invitation is created with `status` `SENT`, `nda_signed` `false`, `snapshot_stale` `false`, and `responded_at`, `decline_reason` and `revoked_reason` null. Two snapshot fields are frozen at issue time: `qualification_snapshot_score` records the carrier's `composite_score` as it stood when the invitation went out, and `qualification_snapshot_carrier_version` records the carrier's `version` at that same instant. The event's `invited_carrier_count` is recomputed, and on the first invitation the event moves from `LANES_LOCKED` to `INVITING`.

**Responding.** A carrier representative responds on its own invitation, which must be `SENT`. The payload carries `accept`, a boolean, and may carry `nda_signed` and `decline_reason`.

On an acceptance, three conditions must hold: the carrier's `status` must be `QUALIFIED` or `CONDITIONALLY_QUALIFIED`; its `insurance_expiry_date` must be strictly after the logical clock; and if the invitation's `nda_required` is `true`, the payload's `nda_signed` must be `true`, otherwise the acceptance is rejected with `ERR_NDA_NOT_SIGNED` (409). The invitation moves from `SENT` to `ACCEPTED`, `nda_signed` takes the payload value, `responded_at` is set to the clock, and the event's `accepted_invitation_count` is increased by one. At the same moment `snapshot_stale` is evaluated: it is set to `true` when the carrier's current `version` differs from `qualification_snapshot_carrier_version`, meaning the carrier's qualification data has moved since the invitation was issued and the frozen `qualification_snapshot_score` no longer describes it. The flag is informational — it does not block anything — but it tells the analyst that this carrier's screening figures deserve a second look before award.

On a decline, no carrier-fitness conditions apply. The invitation moves from `SENT` to `DECLINED`, `decline_reason` takes the payload value, and `responded_at` is set to the clock. A decline does not touch `accepted_invitation_count`, but it does leave the invitation inside `invited_carrier_count`.

**Revoking.** The analyst may revoke an invitation whose `status` is `SENT` or `ACCEPTED`, supplying a mandatory `revoked_reason`. The invitation moves to the terminal `REVOKED` and drops out of `invited_carrier_count`. When the revocation is from `ACCEPTED`, the event's `accepted_invitation_count` is additionally decreased by one. In both cases the withdrawal cascade fires: every lane bid belonging to that carrier whose `status` is `SUBMITTED` and whose round is still `OPEN` moves to `WITHDRAWN`, and each affected round's `submitted_bid_count` and `lowest_rate_per_mile` are recomputed. This is the same cascade a disqualification triggers, which is why revoking an invitation and disqualifying a carrier leave the rounds in an identical, self-consistent state.

**Opening a round.** The analyst opens a bidding round on the event. The payload carries `incumbent_visibility`, one of `HIDDEN`, `RANK_ONLY` or `FULL`; `closes_at`, the submission deadline; and optionally `target_reduction_pct`, between `0.00` and `50.00` at 2 decimal places, defaulting to `0.00`.

Round 1 may be opened from `INVITING` and requires that `accepted_invitation_count` is at least 1 — there is no point opening a round nobody can bid into — and that `current_round_no` is strictly less than the event's `rounds_allowed`. Subsequent rounds are opened from `ROUND_CLOSED` under the same round-count condition. An attempt to open a round when `current_round_no` has already reached `rounds_allowed` is rejected with `ERR_ROUND_LIMIT_EXCEEDED` (409), and an attempt to open the first round before the scope is locked is rejected with `ERR_LANES_NOT_LOCKED` (409).

The round is created with `round_no` set to the event's `current_round_no` plus one, `status` `OPEN`, `opens_at` set to the logical clock, `closed_at` null, `submitted_bid_count` `0` and `lowest_rate_per_mile` null. The event's `current_round_no` increases by one, the event moves to `ROUND_OPEN`, and its `version` increases by one.

`incumbent_visibility` governs how much of the incumbent position is disclosed to bidders during the round: `HIDDEN` discloses nothing, `RANK_ONLY` discloses a bidder's standing without the underlying rates, and `FULL` discloses the incumbent rate itself. `target_reduction_pct` is the reduction the shipper is asking returning bidders to deliver against their own previous round. In round 1 it is purely informational, because there is no previous round to measure against; from round 2 onward it becomes an enforced constraint, described in §3.5.

**Closing a round.** The analyst closes a round whose `status` is `OPEN` while the event is in `ROUND_OPEN`. The round moves to the terminal `CLOSED` and `closed_at` is set to the logical clock. Closing re-evaluates every bid: each lane bid on the round whose `status` is `SUBMITTED` has its evaluated cost and its cost-rank score recomputed and its `rank_in_lane` rewritten, so the ranking that the optimiser will read reflects final, post-withdrawal reality rather than the ordering that happened to exist when each bid arrived. The event moves from `ROUND_OPEN` to `ROUND_CLOSED` and its `version` increases by one. Rounds carry only the two statuses `OPEN` and `CLOSED`, and closure is one-way.

### 3.5. Rate Submission, Evaluation and Ranking

**Submitting a rate.** A carrier representative submits one lane bid per lane it wants, into an `OPEN` round. The payload carries `lane_id`; `carrier_id`, which must equal the acting `X-User-ID` or the request is rejected with `ERR_NOT_RESOURCE_OWNER`; `rate_per_mile`, strictly greater than zero at 4 decimal places; `fuel_surcharge_included`, a boolean stating whether the quoted rate is all-in or excludes fuel; `committed_volume_loads`, an integer of at least 1 stating the maximum annual volume the carrier will commit to on this lane; and `transit_days_offered`, an integer of at least 1.

A submission passes through a sequence of gates, in the order fixed by §2.9. The round must be `OPEN`, and because `closes_at` is the submission deadline, a bid arriving at or after that instant is treated as arriving on a round that is no longer open and is rejected with `ERR_ROUND_NOT_OPEN` (409). The carrier must be fit in the sense of §2.10. An invitation must exist for this pairing of event and carrier, otherwise `ERR_CARRIER_NOT_INVITED` (409), and that invitation's `status` must be `ACCEPTED`, otherwise `ERR_INVITATION_NOT_ACCEPTED` (409) — a carrier that was invited but has not yet accepted, or that declined, cannot bid. At most one bid that is not `WITHDRAWN` may exist for a given combination of round, lane and carrier; a second is rejected with `ERR_DUPLICATE_LANE_BID` (409), while re-bidding after a withdrawal within the same open round is permitted. The named lane must belong to the same bid event as the round, otherwise `ERR_LANE_NOT_IN_EVENT_SCOPE` (409). `transit_days_offered` must be less than or equal to the lane's `service_days_required`, otherwise `ERR_TRANSIT_DAYS_EXCEEDED` (409) — offering exactly the required number of days is acceptable. Finally the two money gates: `rate_per_mile` must be greater than or equal to the event's `rate_floor_per_mile`, otherwise `ERR_RATE_BELOW_FLOOR` (422); and from round 2 onward, when the round carries a `target_reduction_pct` above `0.00`, a carrier that also bid on this lane in the immediately preceding round must quote at or below its own previous `rate_per_mile` reduced by that percentage, otherwise `ERR_RATE_ABOVE_ROUND_TARGET` (422). A carrier bidding this lane for the first time in this round has no previous rate to be measured against and so cannot violate the target.

The accepted bid is created with `status` `SUBMITTED` and `withdrawn_at` null. Its `is_incumbent` is frozen at submission from whether the bidding `carrier_id` equals the lane's `incumbent_carrier_id` at that moment. Its evaluated cost figures and its cost-rank score are computed at once, `rank_in_lane` is written, and the `rank_in_lane` of every other bid on the same lane in the same round is recomputed so the lane's ordering stays consistent. The round's `submitted_bid_count` and `lowest_rate_per_mile` are then recomputed.

**Evaluating a bid's cost.** Every bid is converted into a comparable annual cost by a rule with two variants, selected by the event's `cost_basis`. The bid records which variant was applied in its own `evaluated_basis` field, so a bid always carries the evidence of how it was scored. The step order below is normative; the rounding points are part of the answer.

- **Step 1 — the effective rate.** When `fuel_surcharge_included` is `true`, the effective per-mile rate is the quoted `rate_per_mile` unchanged. When it is `false`, add the event's `fuel_index_per_mile` to `rate_per_mile` and round the sum to 4 decimal places. This is written to `effective_rate_per_mile`.
- **Step 2 — the linehaul per load.** Multiply the lane's `mileage` by `effective_rate_per_mile` and round to 2 decimal places, giving `linehaul_per_load_usd`.
- **Step 3 — the accessorial per load.** Under the `FORECAST` variant, multiply the lane's `accessorial_history_usd_per_load` by the event's `accessorial_inflation_factor` and round to 2 decimal places. Under the `HISTORICAL` variant, take `accessorial_history_usd_per_load` unchanged, with no inflation applied at all. Either way the result is `accessorial_per_load_usd`. This is the only step where the two variants differ in their treatment of accessorials, and it is the reason the same bid scores differently in a forecast event and a historical one.
- **Step 4 — the cost per load.** Add `linehaul_per_load_usd` and `accessorial_per_load_usd`. Both are already rounded to 2 decimal places, and `cost_per_load_usd` is the sum of those two already-rounded figures. Computing the unrounded linehaul plus the unrounded accessorial and rounding once at the end is **wrong** and can differ by a cent, which propagates into every downstream total.
- **Step 5 — the volume basis.** Under the `FORECAST` variant, multiply the lane's `annual_volume_loads` by the forecast growth factor of `1.20` and round to a whole number of loads. Under the `HISTORICAL` variant, the volume basis is the lane's `trailing_12m_actual_loads` as recorded. Then take `awardable_volume_loads` as the smaller of the carrier's `committed_volume_loads` and that volume basis: a carrier is only ever evaluated on volume it has actually committed to carry, and never on more volume than the lane basis supports.
- **Step 6 — the evaluated total.** Multiply `cost_per_load_usd` by `awardable_volume_loads` and round to 2 decimal places, giving `evaluated_total_cost_usd`.

**Ranking bids within a lane.** Cost alone would ignore that some carriers perform better than others, so the evaluated total is discounted by a small service credit derived from the bidding carrier's `composite_score`:

- **The service credit.** Subtract the service credit base of `80.00` from the carrier's `composite_score`, divide by the service credit divisor of 200, and round to 4 decimal places. Floor the result at `0.0000` so a carrier scoring below `80.00` receives no credit rather than a penalty, and cap it at the maximum credit of `0.0500` so no carrier can earn more than a five percent advantage however strong its record. This value is the bid's `service_credit_pct`.
- **The rank score.** Subtract `service_credit_pct` from 1, multiply `evaluated_total_cost_usd` by that factor, and round to 2 decimal places. That is the bid's `cost_rank_score`, a service-adjusted cost where lower is better.
- **The ordering.** Within one lane and one round, order the bids whose `status` is `SUBMITTED` or `SHORTLISTED` by `cost_rank_score` ascending; break ties by `transit_days_offered` ascending, so the faster carrier wins an equal-cost tie; break remaining ties by `is_incumbent` descending, so an incumbent beats a challenger at equal cost and equal transit; and break any remaining tie by `created_at` ascending, so the earlier submission wins. `rank_in_lane` is assigned from that ordering starting at 1, where 1 is the best bid. The bid's own `id` is **never** an input to the ordering, at any tier: a system that falls back to identifier order produces rankings that are stable but arbitrary, and two implementations would disagree.

**Withdrawing a bid.** A carrier representative may withdraw its own bid while the bid's `status` is `SUBMITTED` and the round is still `OPEN`. The bid moves to the terminal `WITHDRAWN` and `withdrawn_at` is set to the logical clock. The round's `submitted_bid_count` is recomputed, its `lowest_rate_per_mile` is recomputed over the bids that remain `SUBMITTED` — becoming null if none remain — and the surviving bids on that lane are renumbered so `rank_in_lane` again runs contiguously from 1 with no gap where the withdrawn bid sat.

A bid's `status` travels through `SUBMITTED`, `WITHDRAWN`, `SHORTLISTED`, `AWARDED_PRIMARY`, `AWARDED_BACKUP` and `NOT_AWARDED`. `SUBMITTED` is the only non-terminal state; every other is an end point, reached either by the bidder's own withdrawal or by the award machinery of §3.6 and §3.7.

### 3.6. Optimisation Scenarios, the Allocation Waterfall and the Routing Guide

**Running a scenario.** Once no round of the event remains open, the procurement analyst runs an optimisation scenario. The payload names the `bid_event_id`; carries `expected_bid_event_version` as described in §2.8; carries a `scenario_label` of 1 to 64 characters so competing scenarios can be told apart by a human; and may optionally override three constraints for this scenario only — `max_carriers_per_lane` between 1 and 3, `diversity_min_pct`, and `min_capacity_coverage_pct`, which defaults to `90.00`. When `max_carriers_per_lane` or `diversity_min_pct` is not supplied on the run, the event's own configured value applies.

A run may be created while the event's `status` is `ROUND_CLOSED`, `OPTIMIZING` or `AWARDING` — the last two being what makes re-running a scenario after seeing its result possible. No round of the event may still be `OPEN`; if one is, the request is rejected with `ERR_ROUND_STILL_OPEN` (409). The version guard is applied as described in §2.8, with a mismatch rejected as `ERR_STALE_BID_EVENT_VERSION` (412).

Creating a run first **supersedes the scenario history**, in three linked steps followed by a rollup refresh. Every earlier run of the same event whose `status` is `COMPLETED` or `PUBLISHED` moves to `SUPERSEDED`. Every award allocation belonging to those superseded runs whose `status` is `PROPOSED` or `APPROVED` moves to `SUPERSEDED`. And for each of those that was `APPROVED` — and only those, since a `PROPOSED` allocation was never holding volume — its `allocated_volume_loads` is credited back to its lane's `unallocated_volume_loads` and that lane's `awarded_coverage_pct` is recomputed from the credited figure, restoring the conservation identity of §2.12 exactly. Then, when the supersession moved at least one allocation, the event's `coverage_pct` and `diversity_pct` are recomputed by the rule of §3.3: the superseded allocations have dropped out of the status set those two rollups read, and an event whose rollups are not refreshed here would go on reporting coverage and diversity that no surviving allocation holds. The new run is then created, the allocation waterfall and the objective score are evaluated, the event moves to `OPTIMIZING`, and the event's `version` increases by one. A run's `status` is `COMPLETED` on creation, or `FAILED` when no lane yielded a feasible primary; from `COMPLETED` it may move to `PUBLISHED`, and from either `COMPLETED` or `PUBLISHED` it may be moved to the terminal `SUPERSEDED` by a later run. `FAILED` is also terminal.

**The allocation waterfall.** The waterfall is the heart of the award. It runs lane by lane, taking the event's in-scope lanes in `created_at` ascending order so that its output is deterministic, and for each lane it fills routing positions from the best bid downward.

For one lane, the candidate set is the lane's bids **from the event's most recent `CLOSED` round only** — earlier rounds are superseded by the negotiation and are not mixed in — whose `status` is `SUBMITTED` or `SHORTLISTED`, and which satisfy every one of five eligibility conditions: the bidding carrier's invitation to this event is `ACCEPTED`; the carrier's `status` is `QUALIFIED`, `CONDITIONALLY_QUALIFIED` or `WATCHLIST`; the carrier's `insurance_expiry_date` is strictly after the logical clock; the bid's `transit_days_offered` is less than or equal to the lane's `service_days_required`; and the bid's `rate_per_mile` is greater than or equal to the event's `rate_floor_per_mile`. Candidates are ordered by the same four-tier ordering used for `rank_in_lane`: `cost_rank_score` ascending, then `transit_days_offered` ascending, then `is_incumbent` descending, then `created_at` ascending.

The lane then has a remaining volume, initialised to its `annual_volume_loads`, and a single-carrier share cap computed by multiplying `annual_volume_loads` by the event's `max_award_share_pct`, dividing by `100.00`, and taking the **floor** — the largest whole number of loads not exceeding that product, never a rounded-up figure. Three routing positions are available in strict order: `PRIMARY`, then `BACKUP_1`, then `BACKUP_2`, capped at the smaller of the run's effective `max_carriers_per_lane` and the structural maximum of 3 positions.

Walking the ordered candidates, the waterfall stops as soon as every available position is filled or the remaining volume reaches zero. For each candidate it computes a grant as the smallest of three quantities: the lane's remaining volume, the bid's `committed_volume_loads`, and the share cap. **A grant of zero consumes no position**: the candidate is skipped and the next one is considered for the same seat, so a fully-consumed lane never burns a backup slot on a carrier receiving nothing. A positive grant produces a pick carrying the next `routing_position` in sequence, `allocated_volume_loads` equal to the grant, `allocated_pct` equal to the grant multiplied by `100.00`, divided by `annual_volume_loads` and rounded to 2 decimal places, and `allocated_cost_usd` equal to the bid's `cost_per_load_usd` multiplied by the grant and rounded to 2 decimal places. The remaining volume is then reduced by the grant and the next position becomes current.

The waterfall itself writes nothing to the lane: it never sets `unallocated_volume_loads` and never sets `awarded_coverage_pct`. Those move only when an allocation is approved, rejected, superseded or promoted, which is what keeps the conservation identity of §2.12 true at every instant rather than only after a full recomputation.

**Scoring the scenario.** The run's headline figures are derived from the picks the waterfall produced across the event's lanes whose `status` is `LOCKED`, `AWARDED` or `UNDER_REBID`:

- `total_cost_usd` is the sum of the picks' `allocated_cost_usd`, rounded to 2 decimal places.
- `coverage_pct` is the sum of the picks' `allocated_volume_loads`, multiplied by `100.00`, divided by the sum of the in-scope lanes' `annual_volume_loads`, rounded to 2 decimal places.
- `diversity_pct` is `0.00` when nothing was allocated; otherwise it is the allocated volume belonging to carriers whose `diversity_classification` is not `NONE`, multiplied by `100.00`, divided by the total allocated volume, rounded to 2 decimal places.
- The **cost ratio** compares the award against the baseline over only those in-scope lanes whose `baseline_cost_usd` is strictly greater than `0.00`. Sum the `allocated_cost_usd` of the picks that fall on those lanes, sum the `baseline_cost_usd` of those lanes, divide the first sum by the second, and round to 6 decimal places. When that baseline sum is `0.00` the cost ratio is `1.000000`. This is a **ratio of sums, never a mean of per-lane ratios**: averaging each lane's own cost-to-baseline ratio gives every lane equal weight regardless of size and yields a materially different, incorrect number.
- The **service ratio** is `0.000000` when nothing was allocated; otherwise, for each pick multiply its `allocated_volume_loads` by its carrier's `composite_score` divided by `100.00`, sum those products, divide by the total `allocated_volume_loads`, and round to 6 decimal places. It is likewise volume-weighted, not a plain average of carrier scores.
- `objective_score` combines the four with the event's weights. Take the cost ratio subtracted from `1.000000`, so that lower award cost scores higher, and multiply by `cost_weight`. Multiply the service ratio by `service_weight`. Divide `coverage_pct` by `100.00`, round to 6 decimal places, and multiply by `capacity_weight`. Divide `diversity_pct` by `100.00`, round to 6 decimal places, and multiply by `diversity_weight`. Add the four products, multiply the total by `100.00`, and round to 2 decimal places.
- `infeasible_lane_ids` lists the `id` of every in-scope lane that produced no `PRIMARY` pick at all, ordered by the lane's `created_at` ascending. A lane appears here when its candidate set was empty after eligibility filtering, or when every candidate's grant computed to zero.
- `proposed_primary_count` is the number of picks whose `routing_position` is `PRIMARY`, and `proposed_backup_count` is the number whose `routing_position` is anything else.

When `infeasible_lane_ids` covers every in-scope lane, the run is created with `status` `FAILED`, `coverage_pct` `0.00`, `total_cost_usd` `0.00` and `objective_score` `0.00`. A failed run records the diagnosis without pretending a routing guide exists.

**Publishing the routing guide.** The analyst publishes a run whose `status` is `COMPLETED`, while the event's `status` is `OPTIMIZING`; publishing against an event in any other state is rejected with `ERR_EVENT_NOT_OPTIMIZING` (409). Two portfolio gates apply. The run's `coverage_pct` must be greater than or equal to its own `min_capacity_coverage_pct`, otherwise `ERR_COVERAGE_BELOW_MINIMUM` (422) — a scenario that leaves too much volume uncovered is not a routing guide. And a run whose `status` is `FAILED` can never be published, the attempt being rejected with `ERR_NO_FEASIBLE_ALLOCATION` (422).

Publication materialises the picks. An `AwardAllocation` row is created for each pick with `status` `PROPOSED`, carrying its `routing_position`, `allocated_volume_loads`, `allocated_pct` and `allocated_cost_usd`, its `promoted_from_position` null, and `approved_by_user_id`, `approved_at` and `rejection_reason` all null. Each lane bid that was selected moves from `SUBMITTED` to `SHORTLISTED`. Each lane bid that was **not** selected, on a lane that did produce a guide, moves from `SUBMITTED` to the terminal `NOT_AWARDED`; bids on lanes that produced nothing are left `SUBMITTED`, since those lanes may be addressed by a further scenario. The run moves from `COMPLETED` to `PUBLISHED`, `published_at` is set to the logical clock, the event moves from `OPTIMIZING` to `AWARDING`, and the event's `version` increases by one.

### 3.7. Allocation Governance and the Award Commit

A published routing guide is a proposal. Turning it into commitments is a category manager's job, taken one allocation at a time, and only when every allocation has been dispositioned may the event be awarded.

An allocation's `status` travels through `PROPOSED`, `APPROVED`, `REJECTED`, `SUPERSEDED`, `EXECUTED`, `ACTIVE` and `SUSPENDED_ROUTING`. `PROPOSED` and `APPROVED` are the reviewable states; `REJECTED` and `SUPERSEDED` are terminal dead ends; `EXECUTED` is the committed state produced by the award; `ACTIVE` is reached when the corresponding rate goes live; and `SUSPENDED_ROUTING` is the reversible state a live allocation enters when its lane goes into mid-contract rebid.

**Approving an allocation.** The category manager approves an allocation whose `status` is `PROPOSED`; an attempt against any other status is rejected with `ERR_ALLOCATION_NOT_PROPOSED` (409). The event must be in `AWARDING`. The carrier must be fit: its `status` must be `QUALIFIED` or `CONDITIONALLY_QUALIFIED`, and its `insurance_expiry_date` must be strictly after the logical clock — a carrier that was eligible when the scenario ran but has since been suspended, watchlisted into an ineligible position or allowed its certificate to lapse cannot be approved without re-running the scenario.

Approval is where volume is actually reserved, and it is the first of the three-link consistency chain:

1. The allocation moves from `PROPOSED` to `APPROVED`, `approved_by_user_id` is set to the acting `X-User-ID` — the value the segregation-of-duties rule of §2.11 will later compare against — and `approved_at` is set to the logical clock.
2. The lane's `unallocated_volume_loads` is reduced by the allocation's `allocated_volume_loads`, and the lane's `awarded_coverage_pct` is recomputed as `annual_volume_loads` minus `unallocated_volume_loads`, multiplied by `100.00`, divided by `annual_volume_loads`, and rounded to 2 decimal places.
3. The event's `coverage_pct` and `diversity_pct` are recomputed over the allocation status set given in §3.3.

**Rejecting an allocation.** The category manager rejects an allocation whose `status` is `PROPOSED` or `APPROVED`, while the event is in `AWARDING`, supplying a mandatory `rejection_reason`. Rejection is a compensating operation and it fires four links:

1. The allocation moves to the terminal `REJECTED` and records `rejection_reason`.
2. The lane bid the allocation referenced moves from `SHORTLISTED` back to `NOT_AWARDED`, since that carrier is no longer being routed on that lane.
3. If — and only if — the allocation was `APPROVED` rather than `PROPOSED`, its `allocated_volume_loads` is credited back to the lane's `unallocated_volume_loads`. The credit is the exact figure that was debited, so the conservation identity of §2.12 is restored without recomputation drift. A `PROPOSED` allocation reserved nothing, so rejecting it moves no volume at all.
4. If the rejected allocation's `routing_position` was `PRIMARY`, the lane's backups are promoted to close the gap. The allocation on that lane whose `routing_position` is `BACKUP_1` and whose `status` is `PROPOSED` or `APPROVED` is promoted to `PRIMARY`, with `promoted_from_position` set to `BACKUP_1` so the routing guide's history remains legible. If a `BACKUP_2` allocation also exists, it is promoted to `BACKUP_1` with `promoted_from_position` set to `BACKUP_2`. Volumes across the surviving positions are then re-derived by the same waterfall arithmetic of §3.6, with the share cap and remaining-volume walk applied over the new position order. Where a promoted allocation already held a volume debit because it was `APPROVED`, only the **difference** between its new and old `allocated_volume_loads` is applied to the lane's `unallocated_volume_loads`, in the same request — never a full re-debit on top of the existing one. Rejecting a backup promotes nothing, because no gap opens above it.

Finally the event's `coverage_pct` and `diversity_pct` are recomputed, since both the removal and the promotions moved allocated volume.

**Committing the award.** With every allocation of the published run dispositioned, the category manager commits the award. Four preconditions apply. The event's `status` must be `AWARDING`. No allocation belonging to the event's `PUBLISHED` run may still be `PROPOSED` — an undecided line item blocks the whole award. The event's `coverage_pct` must be greater than or equal to the `PUBLISHED` run's `min_capacity_coverage_pct`, otherwise `ERR_COVERAGE_BELOW_MINIMUM` (422). The event's `diversity_pct` must be greater than or equal to its `diversity_min_pct`, otherwise `ERR_DIVERSITY_MINIMUM_NOT_MET` (422). And no approved allocation's `allocated_pct` may exceed the event's `max_award_share_pct`, otherwise `ERR_AWARD_SHARE_EXCEEDED` (422) — a guard against a share cap having been undermined by a promotion.

The commit is the widest cascade in the system, and its five links must all land:

1. The event moves from `AWARDING` to `AWARDED`, `awarded_at` is set to the logical clock, and its `award_cost_usd` and `savings_pct` are recomputed per §3.3.
2. Every allocation of the `PUBLISHED` run whose `status` is `APPROVED` moves to `EXECUTED`, and each one's referenced lane bid moves from `SHORTLISTED` to `AWARDED_PRIMARY` when the allocation's `routing_position` is `PRIMARY`, or to `AWARDED_BACKUP` when it is `BACKUP_1` or `BACKUP_2`.
3. Every lane holding an executed allocation moves from `LOCKED` to `AWARDED`, and its `awarded_coverage_pct` is recomputed.
4. One contract is created for each distinct pairing of `bid_event_id` and `carrier_id` appearing among those executed allocations — one contract per carrier per event, however many lanes that carrier won. Each contract is created with `status` `DRAFT`, `signature_status` `PENDING_BOTH`, `rate_load_status` `NOT_STAGED`, `amendment_count` `0`, `rate_record_count` `0`, its `effective_from` and `effective_to` copied from the event's `contract_effective_from` and `contract_effective_to`, its four signature fields — `carrier_signed_by_user_id`, `carrier_signed_at`, `shipper_signed_by_user_id`, `shipper_signed_at` — null, and its committed value evaluated by the rule in §3.8.
5. Each carrier that now holds a contract has its `committed_volume_loads` and `active_primary_lane_count` recomputed from its executed allocations, per the status sets in §2.12.

The event's `version` increases by one. Because `award_cost_usd` in link 1 is derived from the contracts created in link 4, an implementation that skips link 4 leaves the event reporting `0.00` award cost and `0.00` savings against a fully awarded portfolio.

### 3.8. Contract Execution, Rate Loading and Go-Live

A contract carries **three independent status dimensions**, and understanding their independence is essential. `status` is the commercial lifecycle — `DRAFT`, `EXECUTED`, `AMENDED`. `signature_status` is the execution progress — `PENDING_BOTH`, `PENDING_SHIPPER`, `PENDING_CARRIER`, `FULLY_SIGNED`. `rate_load_status` is the operational readiness of the rates behind it — `NOT_STAGED`, `STAGED`, `LOADED`, `LIVE`. Signature progress and rate-loading progress advance **independently of one another**: rates may be staged and loaded while signatures are still outstanding, and signatures may complete while no rate has been staged. The two dimensions couple at exactly one point — a rate record may only be taken live when the contract's `signature_status` is `FULLY_SIGNED` — and nowhere else.

**Signing.** Each side signs once, and whichever side signs second completes execution. A carrier representative signs on behalf of its own carrier: from `PENDING_BOTH` the `signature_status` becomes `PENDING_SHIPPER`, and from `PENDING_CARRIER` it becomes `FULLY_SIGNED` and the contract's `status` moves from `DRAFT` to `EXECUTED`. The signature records `carrier_signed_by_user_id` and `carrier_signed_at`. A contract administrator countersigns on the shipper's behalf: from `PENDING_BOTH` the `signature_status` becomes `PENDING_CARRIER`, and from `PENDING_SHIPPER` it becomes `FULLY_SIGNED` and `status` moves from `DRAFT` to `EXECUTED`. That signature records `shipper_signed_by_user_id` and `shipper_signed_at`, and it is the one operation in the system subject to the segregation-of-duties rule of §2.11. In both cases the contract's `version` increases by one.

**Staging a rate.** A contract administrator stages a rate record against an executed or draft contract. The payload names the `lane_id`, the `carrier_id`, the `award_allocation_id` the rate implements, and a `routing_position` that must match that allocation's own `routing_position`; and it carries `rate_per_mile`, strictly positive at 4 decimal places; `fuel_surcharge_included`; `effective_from` and `effective_to`, with the end strictly after the start; and `committed_volume_loads`, an integer of at least 1.

The record is created with `status` `STAGED`; `acceptance_pct` `100.00` and `rejection_pct` `0.00`, the neutral starting position of a lane that has never been tendered; `tender_count` `0`; `superseded_by_rate_record_id` null; and `loaded_at` and `live_at` null. Its `committed_value_usd` is computed. The contract's `rate_record_count` is recomputed, its `rate_load_status` moves from `NOT_STAGED` to `STAGED`, its committed value is re-evaluated, and its `version` increases by one.

A rate record's `status` travels through `STAGED`, `LOADED`, `LIVE`, `AT_RISK`, `SUPERSEDED` and `ROLLED_BACK`. Only `ROLLED_BACK` is terminal. Both `AT_RISK` and `SUPERSEDED` are reversible: a record can recover from `AT_RISK` back to `LIVE`, and a record that was superseded by a mini-bid can be restored to `LIVE` when that mini-bid is reverted.

**The contract's committed value.** A contract's committed value is recomputed whenever its rate basis changes, and the tier boundaries are exact:

- **Per-record value.** For each rate record in the basis, derive its effective per-mile rate exactly as bid evaluation does — the quoted `rate_per_mile` when `fuel_surcharge_included` is `true`, otherwise `rate_per_mile` plus the event's `fuel_index_per_mile` rounded to 4 decimal places. Multiply the lane's `mileage` by that effective rate and round to 2 decimal places; multiply that already-rounded figure by the record's `committed_volume_loads` and round to 2 decimal places. That is the record's `committed_value_usd`.
- **The basis.** Only rate records whose `status` is `STAGED`, `LOADED`, `LIVE` or `AT_RISK` are in the basis. Records whose `status` is `SUPERSEDED` or `ROLLED_BACK` are **excluded**, which is precisely how a mini-bid apply removes the old rate's value and a revert removes the replacement's. The contract's `base_committed_value_usd` is the sum of the in-basis records' `committed_value_usd`, rounded to 2 decimal places.
- **The volume discount.** The contract's `volume_discount_pct` is selected from `base_committed_value_usd`: below `500000` it is `0.000`; from `500000` up to but not including `1500000` it is `0.015`; at `1500000` and above it is `0.025`. Multiply the base by `volume_discount_pct` and round to 2 decimal places to obtain `volume_discount_usd`. Subtract that from the base and round to 2 decimal places to obtain the post-discount subtotal.
- **The accessorial allowance.** The contract's `accessorial_allowance_pct` is selected from the **post-discount subtotal**, not from the base: below `400000` it is `0.000`; from `400000` up to but not including `1200000` it is `0.010`; at `1200000` and above it is `0.020`. Reading the base figure instead of the subtotal is a distinct and wrong answer for any contract whose discount pushes it across a tier boundary. Multiply the subtotal by `accessorial_allowance_pct` and round to 2 decimal places to obtain `accessorial_allowance_usd`.
- **The total.** Add `accessorial_allowance_usd` to the post-discount subtotal and round to 2 decimal places. That is `total_committed_value_usd`.

**Loading a rate.** A contract administrator loads a rate record whose `status` is `STAGED`; against any other status the attempt is rejected with `ERR_RATE_RECORD_NOT_LOADED` (409). The carrier's `status` must not be `SUSPENDED` or `DISQUALIFIED`, otherwise `ERR_CARRIER_SUSPENDED` (409). And the record's effective interval must not collide with an existing one: no other rate record sharing the same `lane_id`, `carrier_id` and `routing_position`, and whose `status` is `LOADED`, `LIVE` or `AT_RISK`, may have an overlapping interval, otherwise `ERR_RATE_INTERVAL_OVERLAP` (409). Intervals are **half-open**, running from `effective_from` inclusive to `effective_to` exclusive, so two records where one's `effective_to` is exactly the other's `effective_from` are adjacent and do **not** overlap — that is how a mid-contract rate change is expressed as a clean handover rather than a collision. On success the record moves from `STAGED` to `LOADED`, `loaded_at` is set to the logical clock, and on the contract's first loaded record the contract's `rate_load_status` moves from `STAGED` to `LOADED`.

**Going live.** A contract administrator takes a `LOADED` record live; against any other status the attempt is rejected with `ERR_RATE_RECORD_NOT_LOADED` (409). Three further conditions apply. The contract's `signature_status` must be `FULLY_SIGNED`, otherwise `ERR_CONTRACT_NOT_FULLY_SIGNED` (409) — this is the single coupling point between the two contract dimensions. The current logical clock instant must fall inside the record's own half-open effective interval, at or after `effective_from` and strictly before `effective_to`, otherwise `ERR_RATE_NOT_IN_EFFECTIVE_WINDOW` (409); a rate cannot go live before it begins or after it has expired. And the carrier must be fit in the sense of §2.10.

Go-live is a four-link cutover cascade:

1. The record moves from `LOADED` to `LIVE` and `live_at` is set to the logical clock.
2. The award allocation the record implements moves from `EXECUTED` to `ACTIVE`, and the carrier's `active_primary_lane_count` is recomputed.
3. The contract's `rate_load_status` moves from `LOADED` to `LIVE`.
4. On the **first** rate record of the whole event to go live, the event moves from `AWARDED` to the terminal `LIVE` and its `coverage_pct` is recomputed over the allocations now `ACTIVE`. Subsequent go-lives in the same event leave the event where it is, since `LIVE` is terminal.

### 3.9. Live Tendering, Mini-Bids and Mid-Contract Adjustment

A routing guide only works if the primary carrier accepts the loads it was awarded. The tender log is how the system finds out, and the mini-bid is how it responds.

**Appending a tender outcome.** A procurement analyst or contract administrator appends a tender outcome against a rate record whose `status` is `LIVE` or `AT_RISK`; against any other status the attempt is rejected with `ERR_RATE_RECORD_NOT_LIVE` (409). The payload carries an `outcome` of `ACCEPTED`, `REJECTED` or `TIMEOUT`; a `load_reference` of 1 to 32 characters, unique within that rate record — a repeat is rejected with `ERR_DUPLICATE_LOAD_REFERENCE` (409), while the same reference under a different record is legal; and optionally a `reject_reason`.

The tender event records `tendered_at` from the logical clock and freezes `position_used` from the rate record's `routing_position` as it stands at append time, so the log preserves which routing seat was actually offered the load even if the guide is later rearranged. As stated in §2.6, a tender event carries only `id` and `created_at` — no `updated_at` and no `version` — because it is an immutable log entry.

**The acceptance metrics.** Every append re-derives three figures on the rate record, plus a risk determination:

- `tender_count` is the number of tender events on the record, counting every outcome.
- `rejection_count` is the number of those whose `outcome` is `REJECTED` or `TIMEOUT`. A tender the carrier let time out counts against it exactly as an explicit refusal does.
- `rejection_pct` is `0.00` when `tender_count` is zero; otherwise multiply `rejection_count` by `100.00`, divide by `tender_count`, and round to 2 decimal places. `acceptance_pct` is `100.00` minus `rejection_pct`, rounded to 2 decimal places, so the two always sum to exactly `100.00`.
- The record is **at risk** when two conditions hold **independently and together**: `tender_count` is greater than or equal to the minimum sample of 5, and `rejection_pct` is greater than or equal to the at-risk threshold of `20.00`. Both gates matter. A record with 4 tenders of which all 4 were rejected has a `rejection_pct` of `100.00` but has not met the sample gate, so it is **not** at risk — a small sample is not evidence. A record with 5 tenders of which exactly 1 was rejected has a `rejection_pct` of exactly `20.00`, meets both gates, and **is** at risk.

When the determination turns positive and the record's `status` is `LIVE`, the three-link risk cascade fires:

1. The rate record moves from `LIVE` to `AT_RISK`.
2. The award allocation the record implements, if it is `ACTIVE` and its `routing_position` is `PRIMARY`, moves to `SUSPENDED_ROUTING`; and the lane moves from `AWARDED` to `UNDER_REBID`. The lane is now formally open for re-pricing without the original award being destroyed.
3. A mini-bid is created automatically, with `origin` `SYSTEM`, `status` `REQUESTED`, `trigger_reason` `TENDER_REJECTION_RATE`, its `window_open_at` set to the current logical clock instant and its `window_close_at` set to that instant advanced by the system mini-bid window of 10 days. The system opens the negotiation window itself rather than waiting for a human to notice the rejection pattern.

When the determination turns negative again — the record's `status` is `AT_RISK`, `tender_count` is still at or above the sample of 5, and `rejection_pct` has fallen below `20.00` because later loads were accepted — the cascade unwinds symmetrically: the record moves from `AT_RISK` back to `LIVE`, the suspended allocation moves from `SUSPENDED_ROUTING` back to `ACTIVE`, and the lane moves from `UNDER_REBID` back to `AWARDED` provided no other at-risk record remains on that lane.

**Requesting a mini-bid.** A category manager may also open a mini-bid by hand. The payload names the `bid_event_id`, the `lane_id` and the `rate_record_id` being targeted; carries a `trigger_reason` of `TENDER_REJECTION_RATE`, `MARKET_INDEX` or `CAPACITY_FAILURE`, recording why the window is being opened; and carries `window_open_at` and `window_close_at`, with the close strictly after the open. The mini-bid is created with `status` `REQUESTED` and `origin` `MANUAL`, distinguishing it from the automatically generated ones, and with `proposed_rate_per_mile`, `proposed_by_carrier_id`, `adjustment_pct`, `applied_rate_record_id`, `applied_at`, `contract_value_before_usd`, `contract_value_after_usd`, `denial_reason`, `revert_reason` and `reverted_at` all null.

Three time-and-quota gates guard creation, and they are distinct rejections:

- **Window conflict.** The requested window must not intersect the window of any other mini-bid on the same lane whose `status` is `REQUESTED`, `OPEN` or `APPLIED`. The comparison treats each window as a **closed** interval from `window_open_at` through `window_close_at` inclusive, so windows that merely touch at an endpoint do conflict. A violation is rejected with `ERR_MINI_BID_WINDOW_CONFLICT` (409). Mini-bids that were `DENIED` or `REVERTED` are ignored by this check.
- **Cooldown.** `window_open_at` must be at least the cooldown of 7 days after the `applied_at` of the lane's most recently applied mini-bid. A lane whose rate was adjusted three days ago cannot immediately be reopened; the attempt is rejected with `ERR_MINI_BID_COOLDOWN_ACTIVE` (409). A lane that has never had a mini-bid applied has no cooldown.
- **Rolling quota.** A lane may hold at most 2 mini-bids whose `status` is `OPEN` or `APPLIED` and whose `window_open_at` falls within the trailing quota window of 90 days measured back from the requested `window_open_at`. A third is rejected with `ERR_MINI_BID_QUOTA_EXCEEDED` (409). The quota counts windows that actually reached negotiation or adjustment; mini-bids still `REQUESTED`, or that ended `DENIED` or `REVERTED`, do not consume quota.

A mini-bid's `status` travels through `REQUESTED`, `OPEN`, `APPLIED`, `DENIED` and `REVERTED`. `DENIED` and `REVERTED` are terminal.

**Proposing a rate.** A carrier representative proposes a replacement rate on a mini-bid whose `status` is `REQUESTED`; against any other status the attempt is rejected with `ERR_MINI_BID_NOT_OPEN` (409). The payload names the `carrier_id`, which must equal the acting `X-User-ID`, and carries `proposed_rate_per_mile`. The current logical clock instant must fall inside the mini-bid's window, treated as a **closed** interval — at or after `window_open_at` and at or before `window_close_at`. The proposing carrier must actually hold an award allocation on the mini-bid's lane whose `status` is `EXECUTED`, `ACTIVE` or `SUSPENDED_ROUTING`; a carrier not routed on the lane has nothing to re-price. And the carrier must be fit in the sense of §2.10.

The proposed adjustment is then measured:

- Take the `rate_per_mile` of the targeted rate record **as it is currently stored**. On a lane whose rate has already been adjusted once, this is the adjusted rate, not the rate originally awarded in the bid event. Measuring against the original awarded rate would let a carrier walk a lane upward in repeated small steps that each look compliant.
- Subtract that current rate from `proposed_rate_per_mile`, multiply the difference by `100.00`, divide by the current rate, and round to 2 decimal places. That is `adjustment_pct`, which is positive for an increase and negative for a decrease.
- The absolute value of `adjustment_pct` must not exceed the adjustment cap of `12.00`, otherwise the proposal is rejected with `ERR_ADJUSTMENT_EXCEEDS_CAP` (422). The cap is symmetric: a `-14.00` reduction is refused just as a `+14.00` increase is.
- `proposed_rate_per_mile` must be greater than or equal to the event's `rate_floor_per_mile`, otherwise `ERR_RATE_BELOW_FLOOR` (422).

On success the mini-bid records `proposed_rate_per_mile`, `proposed_by_carrier_id` and `adjustment_pct`, and moves from `REQUESTED` to `OPEN`.

**Applying a mini-bid.** A contract administrator applies a mini-bid whose `status` is `OPEN`; against any other status the attempt is rejected with `ERR_MINI_BID_NOT_OPEN` (409). The payload carries `expected_contract_version` as described in §2.8, and `effective_from` and `effective_to` for the replacement rate, with the end strictly after the start. The targeted rate record's `status` must be `LIVE` or `AT_RISK`, otherwise `ERR_RATE_RECORD_NOT_LIVE` (409). Both the adjustment cap and the rate floor are **re-checked at apply time** against the currently stored rate, because the record may have moved since the proposal was made. And the replacement interval must not overlap any other rate record sharing the same `lane_id`, `carrier_id` and `routing_position` whose `status` is `LOADED`, `LIVE` or `AT_RISK`, under the same half-open interval semantics of §3.8, otherwise `ERR_RATE_INTERVAL_OVERLAP` (409). Note that the record being superseded leaves the basis in the same operation, so it does not conflict with its own replacement.

The apply is a three-link money cascade. The contract's `total_committed_value_usd` is snapshotted into `contract_value_before_usd` immediately before the links run, and into `contract_value_after_usd` immediately after they complete:

1. A replacement rate record is minted directly in `LIVE` — it does not pass through `STAGED` or `LOADED` — carrying `rate_per_mile` set to the mini-bid's `proposed_rate_per_mile`, the `effective_from` and `effective_to` supplied in the payload, and `lane_id`, `carrier_id`, `routing_position`, `award_allocation_id`, `contract_id`, `fuel_surcharge_included` and `committed_volume_loads` copied from the record it replaces. The targeted record moves from `LIVE` or `AT_RISK` to `SUPERSEDED`, and its `superseded_by_rate_record_id` is set to the new record's `id`. The mini-bid records `applied_rate_record_id` as the new record's `id` and `applied_at` from the logical clock.
2. The contract's `status` moves from `EXECUTED` to `AMENDED`, its `amendment_count` increases by one, its committed value is re-evaluated over the new basis — which now excludes the superseded record and includes the replacement — and its `version` increases by one.
3. The event's `award_cost_usd` and `savings_pct` are recomputed, since the portfolio's committed value has changed.

When the lane was in `UNDER_REBID` because of the risk cascade, applying the mini-bid also resolves it: the suspended allocation moves from `SUSPENDED_ROUTING` back to `ACTIVE`, the lane moves from `UNDER_REBID` back to `AWARDED`, and the lane's `awarded_coverage_pct` is recomputed. The mini-bid itself moves from `OPEN` to `APPLIED`.

**Denying a mini-bid.** A category manager may close a mini-bid without adjusting anything, from either `REQUESTED` or `OPEN`, supplying a mandatory `denial_reason`. The mini-bid moves to the terminal `DENIED`. No rate record is created or changed, no contract value moves, and no lane or allocation status changes — a denied mini-bid leaves a lane that went into `UNDER_REBID` exactly where it was, to be resolved by tender recovery or by a later window.

**Reverting an applied mini-bid.** A contract administrator may unwind an applied adjustment, supplying a mandatory `revert_reason`. The mini-bid's `status` must be `APPLIED`, otherwise `ERR_MINI_BID_NOT_APPLIED` (409), and the replacement record identified by `applied_rate_record_id` must still be `LIVE` — a replacement that has itself been superseded or rolled back cannot be unwound through this path.

The revert is the exact compensating inverse of the apply, in three matching links:

1. The replacement rate record moves from `LIVE` to the terminal `ROLLED_BACK`. The record it had superseded moves from `SUPERSEDED` back to `LIVE`, and its `superseded_by_rate_record_id` is cleared to null.
2. The contract's `amendment_count` decreases by one, its committed value is re-evaluated over the restored basis, and its `version` increases by one. When `amendment_count` returns to `0`, the contract's `status` moves from `AMENDED` back to `EXECUTED`; while any other amendment remains outstanding it stays `AMENDED`.
3. The event's `award_cost_usd` and `savings_pct` are recomputed.

The mini-bid records `revert_reason` and sets `reverted_at` from the logical clock, then moves from `APPLIED` to the terminal `REVERTED`. Because link 1 restores the original record to the basis and removes the replacement from it, and because the committed-value rule is a pure function of the basis, the contract's `total_committed_value_usd` after a revert equals the `contract_value_before_usd` snapshotted at apply time **exactly** — the round-trip leaves no residue.

## 4. Endpoint Definitions

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/_clock/set_current_utc` | Sets the logical clock to an absolute UTC instant for deterministic time-dependent behaviour. | ProcurementAnalyst, ComplianceOfficer, CategoryManager, ContractAdmin, CarrierRep |
| POST | `/freight-procurement/carriers` | Registers a carrier with its SCAC, service modes, fleet size, insurance limits and diversity classification. | ProcurementAnalyst |
| GET | `/freight-procurement/carriers/{id}` | Retrieves a single carrier with its standing, scores and commitment rollups. | ProcurementAnalyst, ComplianceOfficer, CategoryManager, ContractAdmin, CarrierRep |
| GET | `/freight-procurement/carriers` | Lists carriers, optionally filtered by status and diversity classification. | ProcurementAnalyst, ComplianceOfficer, CategoryManager, ContractAdmin |
| POST | `/freight-procurement/carriers/{id}/status-change` | Suspends, reinstates or disqualifies a carrier with a mandatory reason. | ComplianceOfficer |
| POST | `/freight-procurement/carriers/{id}/qualification-reviews` | Opens a qualification review against a registered carrier with required modes and insurance thresholds. | ComplianceOfficer |
| GET | `/freight-procurement/carriers/{id}/qualification-reviews` | Lists the qualification reviews of one carrier. | ComplianceOfficer, ProcurementAnalyst |
| POST | `/freight-procurement/qualification-reviews/{id}/insurance-verification` | Records verified insurance limits and expiry, resolving the insurance arm of the review. | ComplianceOfficer |
| POST | `/freight-procurement/qualification-reviews/{id}/capability-screening` | Scores mode coverage, fleet adequacy and insurance headroom, resolving the capability arm of the review. | ComplianceOfficer |
| POST | `/freight-procurement/qualification-reviews/{id}/decision` | Approves, conditionally approves, remediates or rejects a screened qualification review. | ComplianceOfficer |
| POST | `/freight-procurement/carriers/{id}/scorecards` | Drafts a period performance scorecard for a carrier from on-time and claims data. | CategoryManager |
| GET | `/freight-procurement/carriers/{id}/scorecards` | Lists the scorecards of one carrier, most recent period first. | CategoryManager, ProcurementAnalyst, CarrierRep |
| POST | `/freight-procurement/scorecards/{id}/publish` | Publishes a draft scorecard and re-scores the carrier's composite standing. | CategoryManager |
| POST | `/freight-procurement/scorecards/{id}/dispute` | Records a carrier's dispute against a published scorecard. | CarrierRep |
| POST | `/freight-procurement/bid-events` | Creates a bid event with its cost basis, fuel and accessorial settings, objective weights and award constraints. | ProcurementAnalyst |
| GET | `/freight-procurement/bid-events/{id}` | Retrieves a single bid event with its scope, coverage, diversity and savings figures. | ProcurementAnalyst, ComplianceOfficer, CategoryManager, ContractAdmin |
| POST | `/freight-procurement/bid-events/{id}/lanes` | Adds a lane to a draft bid event with its geography, volumes, seasonality and incumbent baseline. | ProcurementAnalyst |
| POST | `/freight-procurement/bid-events/{id}/lock-lanes` | Locks the lane scope of a bid event and freezes its baseline cost and scope volume. | ProcurementAnalyst |
| POST | `/freight-procurement/bid-events/{id}/invitations` | Invites a qualified carrier to bid on the event, freezing its qualification snapshot. | ProcurementAnalyst |
| POST | `/freight-procurement/bid-events/{id}/bid-rounds` | Opens the next negotiation round with its incumbent visibility, deadline and reduction target. | ProcurementAnalyst |
| GET | `/freight-procurement/bid-events/{id}/bid-rounds` | Lists the negotiation rounds of one bid event in round order. | ProcurementAnalyst, CategoryManager, CarrierRep |
| GET | `/freight-procurement/bid-events/{id}/optimization-runs` | Lists the optimisation scenarios run against one bid event. | ProcurementAnalyst, CategoryManager |
| POST | `/freight-procurement/bid-events/{id}/award` | Commits the award, executing allocations and creating one contract per awarded carrier. | CategoryManager |
| GET | `/freight-procurement/lanes/{id}` | Retrieves a single lane with its data-quality flags, baseline and allocation coverage. | ProcurementAnalyst, CategoryManager, ContractAdmin, CarrierRep |
| GET | `/freight-procurement/lanes` | Lists lanes, optionally filtered by event, incumbent carrier, status and equipment type. | ProcurementAnalyst, CategoryManager, ContractAdmin, CarrierRep |
| POST | `/freight-procurement/lanes/{id}/validate` | Validates a draft lane, recomputing its data-quality flags and baseline cost. | ProcurementAnalyst |
| GET | `/freight-procurement/invitations/{id}` | Retrieves a single invitation with its response state and qualification snapshot. | ProcurementAnalyst, CategoryManager, CarrierRep |
| GET | `/freight-procurement/invitations` | Lists invitations, optionally filtered by event, carrier and status. | ProcurementAnalyst, CategoryManager, CarrierRep |
| POST | `/freight-procurement/invitations/{id}/response` | Accepts or declines an invitation, recording NDA execution or the decline reason. | CarrierRep |
| POST | `/freight-procurement/invitations/{id}/revoke` | Revokes an invitation and withdraws that carrier's open-round bids. | ProcurementAnalyst |
| GET | `/freight-procurement/bid-rounds/{id}` | Retrieves a single negotiation round with its submission counters. | ProcurementAnalyst, CategoryManager, CarrierRep |
| POST | `/freight-procurement/bid-rounds/{id}/lane-bids` | Submits a carrier's rate, commitment and transit offer for one lane in an open round. | CarrierRep |
| GET | `/freight-procurement/lane-bids/{id}` | Retrieves a single lane bid with its evaluated cost, rank score and rank. | ProcurementAnalyst, CategoryManager, CarrierRep |
| GET | `/freight-procurement/lane-bids` | Lists lane bids in rank order, optionally filtered by round, lane, carrier and status. | ProcurementAnalyst, CategoryManager, CarrierRep |
| POST | `/freight-procurement/lane-bids/{id}/withdraw` | Withdraws a carrier's own submitted bid while its round is still open. | CarrierRep |
| POST | `/freight-procurement/bid-rounds/{id}/close` | Closes an open round and re-evaluates and re-ranks every submitted bid on it. | ProcurementAnalyst |
| POST | `/freight-procurement/optimization-runs` | Runs an optimisation scenario over the closed round, superseding earlier scenarios. | ProcurementAnalyst |
| GET | `/freight-procurement/optimization-runs/{id}` | Retrieves a single optimisation run with its objective, coverage, diversity and infeasible lanes. | ProcurementAnalyst, CategoryManager |
| POST | `/freight-procurement/optimization-runs/{id}/routing-guide` | Publishes a completed scenario as proposed primary and backup allocations. | ProcurementAnalyst |
| GET | `/freight-procurement/award-allocations/{id}` | Retrieves a single award allocation with its routing position and allocated volume. | ProcurementAnalyst, CategoryManager, ContractAdmin, CarrierRep |
| GET | `/freight-procurement/award-allocations` | Lists award allocations, optionally filtered by event, run, lane, carrier, bid, position and status. | ProcurementAnalyst, CategoryManager, ContractAdmin, CarrierRep |
| POST | `/freight-procurement/award-allocations/{id}/approve` | Approves a proposed allocation and reserves its volume against the lane. | CategoryManager |
| POST | `/freight-procurement/award-allocations/{id}/reject` | Rejects an allocation, releasing its volume and promoting the lane's backups. | CategoryManager |
| GET | `/freight-procurement/contracts/{id}` | Retrieves a single contract with its signature progress, rate-load progress and committed value. | ProcurementAnalyst, CategoryManager, ContractAdmin, CarrierRep |
| GET | `/freight-procurement/contracts` | Lists contracts, optionally filtered by event, carrier, status and signature status. | ProcurementAnalyst, CategoryManager, ContractAdmin, CarrierRep |
| POST | `/freight-procurement/contracts/{id}/carrier-signature` | Applies the carrier's signature to its own contract. | CarrierRep |
| POST | `/freight-procurement/contracts/{id}/shipper-signature` | Applies the shipper's countersignature, subject to segregation of duties from award approval. | ContractAdmin |
| POST | `/freight-procurement/contracts/{id}/rate-records` | Stages a rate record against a contract for one lane, position and effective interval. | ContractAdmin |
| GET | `/freight-procurement/rate-records/{id}` | Retrieves a single rate record with its effective interval and tender acceptance metrics. | ProcurementAnalyst, CategoryManager, ContractAdmin, CarrierRep |
| GET | `/freight-procurement/rate-records` | Lists rate records, optionally filtered by contract, lane, carrier, allocation, supersession and status. | ProcurementAnalyst, CategoryManager, ContractAdmin, CarrierRep |
| POST | `/freight-procurement/rate-records/{id}/load` | Loads a staged rate record after checking its effective interval against existing rates. | ContractAdmin |
| POST | `/freight-procurement/rate-records/{id}/go-live` | Takes a loaded rate live on a fully signed contract and activates its allocation. | ContractAdmin |
| POST | `/freight-procurement/rate-records/{id}/tender-events` | Appends a tender outcome to a live rate record and re-derives its acceptance metrics. | ProcurementAnalyst, ContractAdmin |
| GET | `/freight-procurement/rate-records/{id}/tender-events` | Lists the tender log of one rate record in tender order. | ProcurementAnalyst, CategoryManager, ContractAdmin, CarrierRep |
| POST | `/freight-procurement/mini-bids` | Requests a mid-contract mini-bid window on a lane, subject to conflict, cooldown and quota limits. | CategoryManager |
| GET | `/freight-procurement/mini-bids/{id}` | Retrieves a single mini-bid with its window, proposal, adjustment and value snapshots. | ProcurementAnalyst, CategoryManager, ContractAdmin, CarrierRep |
| GET | `/freight-procurement/mini-bids` | Lists mini-bids, optionally filtered by event, lane, targeted rate, applied rate, proposer and status. | ProcurementAnalyst, CategoryManager, ContractAdmin, CarrierRep |
| POST | `/freight-procurement/mini-bids/{id}/proposal` | Submits a carrier's replacement rate inside an open mini-bid window. | CarrierRep |
| POST | `/freight-procurement/mini-bids/{id}/apply` | Applies the proposed rate, superseding the old rate record and amending the contract. | ContractAdmin |
| POST | `/freight-procurement/mini-bids/{id}/deny` | Denies a requested or open mini-bid with a mandatory reason and changes no rates. | CategoryManager |
| POST | `/freight-procurement/mini-bids/{id}/revert` | Reverts an applied mini-bid, restoring the superseded rate and the prior contract value. | ContractAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_CARRIER_NOT_FOUND` | 404 |
| `ERR_QUALIFICATION_REVIEW_NOT_FOUND` | 404 |
| `ERR_BID_EVENT_NOT_FOUND` | 404 |
| `ERR_LANE_NOT_FOUND` | 404 |
| `ERR_BID_ROUND_NOT_FOUND` | 404 |
| `ERR_INVITATION_NOT_FOUND` | 404 |
| `ERR_LANE_BID_NOT_FOUND` | 404 |
| `ERR_OPTIMIZATION_RUN_NOT_FOUND` | 404 |
| `ERR_AWARD_ALLOCATION_NOT_FOUND` | 404 |
| `ERR_CONTRACT_NOT_FOUND` | 404 |
| `ERR_RATE_RECORD_NOT_FOUND` | 404 |
| `ERR_MINI_BID_NOT_FOUND` | 404 |
| `ERR_SCORECARD_NOT_FOUND` | 404 |
| `ERR_STALE_BID_EVENT_VERSION` | 412 |
| `ERR_STALE_CONTRACT_VERSION` | 412 |
| `ERR_LANE_NOT_VALIDATED` | 409 |
| `ERR_LANES_NOT_LOCKED` | 409 |
| `ERR_ROUND_NOT_OPEN` | 409 |
| `ERR_ROUND_STILL_OPEN` | 409 |
| `ERR_EVENT_NOT_OPTIMIZING` | 409 |
| `ERR_ALLOCATION_NOT_PROPOSED` | 409 |
| `ERR_CONTRACT_NOT_FULLY_SIGNED` | 409 |
| `ERR_RATE_RECORD_NOT_LOADED` | 409 |
| `ERR_RATE_RECORD_NOT_LIVE` | 409 |
| `ERR_MINI_BID_NOT_OPEN` | 409 |
| `ERR_MINI_BID_NOT_APPLIED` | 409 |
| `ERR_REVIEW_NOT_SCREENED` | 409 |
| `ERR_SCORECARD_ALREADY_PUBLISHED` | 409 |
| `ERR_SCORECARD_NOT_PUBLISHED` | 409 |
| `ERR_CARRIER_SUSPENDED` | 409 |
| `ERR_CARRIER_INSURANCE_EXPIRED` | 409 |
| `ERR_CARRIER_NOT_QUALIFIED` | 409 |
| `ERR_LANE_DATA_QUALITY_BLOCKED` | 409 |
| `ERR_CARRIER_NOT_INVITED` | 409 |
| `ERR_INVITATION_NOT_ACCEPTED` | 409 |
| `ERR_DUPLICATE_SCAC` | 409 |
| `ERR_DUPLICATE_LANE_CODE` | 409 |
| `ERR_DUPLICATE_INVITATION` | 409 |
| `ERR_DUPLICATE_LANE_BID` | 409 |
| `ERR_DUPLICATE_LOAD_REFERENCE` | 409 |
| `ERR_RATE_INTERVAL_OVERLAP` | 409 |
| `ERR_RATE_NOT_IN_EFFECTIVE_WINDOW` | 409 |
| `ERR_MINI_BID_WINDOW_CONFLICT` | 409 |
| `ERR_MINI_BID_COOLDOWN_ACTIVE` | 409 |
| `ERR_LANE_NOT_IN_EVENT_SCOPE` | 409 |
| `ERR_TRANSIT_DAYS_EXCEEDED` | 409 |
| `ERR_NDA_NOT_SIGNED` | 409 |
| `ERR_ROUND_LIMIT_EXCEEDED` | 409 |
| `ERR_REMEDIATION_LIMIT_EXCEEDED` | 409 |
| `ERR_MINI_BID_QUOTA_EXCEEDED` | 409 |
| `ERR_RATE_BELOW_FLOOR` | 422 |
| `ERR_RATE_ABOVE_ROUND_TARGET` | 422 |
| `ERR_ADJUSTMENT_EXCEEDS_CAP` | 422 |
| `ERR_AWARD_SHARE_EXCEEDED` | 422 |
| `ERR_DIVERSITY_MINIMUM_NOT_MET` | 422 |
| `ERR_COVERAGE_BELOW_MINIMUM` | 422 |
| `ERR_NO_FEASIBLE_ALLOCATION` | 422 |
