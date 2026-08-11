# County Fair Livestock Auction API — Product Requirements Document

## 1. Introduction

Every summer the county fair board runs its youth livestock program: exhibitors enter market animals, the board verifies ownership and possession deadlines, a weigh-master certifies official weights, the show office sorts entries into weight classes, judges place each class in the ring, and the week culminates in a premium auction where buyers bid on the animals and pile on add-on donations for the exhibitors. This document specifies the API that runs that program end to end — exhibitor entry with ownership and possession deadline verification, weigh-in, classification and class placement, show-ring scheduling and judge assignment, premium payment scheduling with state-fair qualification, buyer registration and auction ordering, add-on donation processing with buyer invoicing, animal disposition logistics for harvest and return, and health-inspection plus drug-free affidavit compliance. All resources are mounted under the `/v1` prefix; the only capability outside that prefix is the administrative logical-clock control described in §2.6.

Two commitments shape every rule that follows. First, the fair runs as a sequence of explicit postures — setup, entries, weigh-in, showing, auction, settlement, closure — and nearly every child operation is gated on the fair's current posture, so the board can freeze one phase before opening the next. Second, money and authority are kept under tight separation: the premium purse is a conserved quantity debited at placing time and scaled down pro-rata if oversubscribed, award approval and payment are split across different treasurers, disposition creation and approval are split across different operators, and a buyer's exposure is checked against a credit limit at the fall of the hammer. When corrections are needed — a reweigh, a voided placing, a disqualified animal — the API compensates every derived record immediately rather than leaving stale state behind.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID` identifying the acting user, and `X-User-Role` naming their operational capacity. A request missing either header, or carrying a role the system does not declare, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system declares exactly nine roles: `FairBoardAdmin`, `Exhibitor`, `WeighMaster`, `ShowClerk`, `Judge`, `Auctioneer`, `Buyer`, `HealthInspector`, and `Treasurer`. Authorization is evaluated after authentication: a caller whose role is not permitted for the endpoint, or who fails an entity-backed ownership check, is rejected with `ERR_FORBIDDEN` (HTTP 403).

Identity semantics differ by role, and the difference matters wherever ownership is checked. When `X-User-Role` is `Exhibitor`, `X-User-ID` is the `id` of the acting Exhibitor record; ownership checks on any resource that references an exhibitor compare the resource's `exhibitor_id` field to `X-User-ID`, so an exhibitor creates entries, signs affidavits, and requests dispositions only for their own animals. When `X-User-Role` is `Judge`, `X-User-ID` is the `id` of the acting Judge record, and submitting or voiding placings is permitted only on ring slots whose `judge_id` equals `X-User-ID`; a mismatch on those operations is rejected with `ERR_NOT_ASSIGNED_JUDGE` (HTTP 403) rather than the generic forbidden error. When `X-User-Role` is `Buyer`, `X-User-ID` is the `id` of the acting Buyer record, and add-on pledges may be created or voided only with `buyer_id` equal to `X-User-ID`. When `X-User-Role` is `FairBoardAdmin`, `WeighMaster`, `ShowClerk`, `Auctioneer`, `HealthInspector`, or `Treasurer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example as `created_by_user_id` on a disposition order, or as `approved_by_user_id` on a premium award or disposition — but never compares it to any entity `id`. Where segregation-of-duties rules apply, they compare these opaque `X-User-ID` values to each other. Every read endpoint is available to all nine roles.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of returned items: it defaults to 10 when omitted, and any value below 1 or above 100 is invalid. The `offset` parameter skips a number of items from the front of the result set and defaults to 0. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope. Unless stated otherwise, list endpoints sort by `created_at` in ascending order.

### 2.4. Resource Identity and Audit Fields

Every resource carries an `id` minted by the server as a bare UUID with no type prefix. The `id` is identity only: it is never used for ranking, tie-breaking, or selection anywhere in the system — where a deterministic fallback order is needed, `created_at` is the fallback. Alongside the `id`, resources carry `created_at` and `updated_at`, both ISO 8601 UTC timestamps rendered with exactly three fractional digits, and a `version` integer that increments by one on every mutation of the resource. Lifecycle-bearing entities expose their current state through a `status` field whose exact uppercase values are introduced per entity in §3; the fair is the exception in naming, exposing its lifecycle through `posture` instead. One entity is the exception: a `HealthInspection` is an immutable record carrying only `id` and `created_at` — both `updated_at` and `version` are absent from it. Any mutation described in §3 — including automatic ones driven by cascades — refreshes the owning entity's `updated_at` and advances its `version` by one.

### 2.5. Fair Posture: the Master Gate

A Fair progresses through a canonical posture sequence: `SETUP` → `ENTRIES_OPEN` → `ENTRIES_LOCKED` → `WEIGH_IN` → `SHOWING` → `AUCTION` → `SETTLEMENT` → `CLOSED`. The fair's current posture is exposed as its `posture` field, starting at `SETUP` when the fair is created. A `FairBoardAdmin` advances the posture by naming the desired next posture in `to_posture`; the advance is strictly one step — skipping a posture or naming an earlier one is rejected with `ERR_INVALID_STATE` (HTTP 409). The sole backward edge in the lifecycle is reopening entries, which moves `ENTRIES_LOCKED` → `ENTRIES_OPEN` and is permitted only while no weigh ticket in `ACTIVE` status exists for any entry of the fair; otherwise the reopen is rejected with `ERR_INVALID_STATE`. Every successful posture transition increments the Fair's `version` by one.

Posture is a gate, not merely a label. Entry creation is allowed only in `ENTRIES_OPEN`; entry verification is allowed in `ENTRIES_OPEN` or `ENTRIES_LOCKED`; weigh-in and classification require `WEIGH_IN`; starting a ring slot and submitting placings require `SHOWING`; auction-lot operations require `AUCTION`; and invoice issue, invoice payments, premium approval, and premium payment all require `SETTLEMENT`. An operation attempted under the wrong posture is rejected with `ERR_POSTURE_FORBIDS` (HTTP 409).

Two posture transitions carry settlement guards. Advancing `AUCTION` → `SETTLEMENT` requires every auction lot of the fair to be in a terminal state — `SOLD` or `NO_SALE`. Advancing `SETTLEMENT` → `CLOSED` requires every invoice of the fair to be `PAID`, every premium award to be `PAID` or `FORFEITED`, and every disposition order to be `COMPLETED` or `REJECTED`. A guard failure is rejected with `ERR_INVALID_STATE`.

### 2.6. Logical Time

All temporal rules in the system — affidavit signing, withdrawal clearance, scheduled movement dates — evaluate against a server-side logical clock, never against wall-clock time. The clock's startup default, before it is ever set, is exactly 2026-05-01T00:00:00Z, and the clock never falls back to wall-clock time on its own. A `FairBoardAdmin`-only test-driving capability sets the clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`; the capability may move the clock forward or backward.

### 2.7. Request Evaluation Order

Validation on every endpoint is priority-ordered, and the first failure wins — an earlier failure masks later ones. Evaluated in order, the ladder is: authentication of the two headers (failure: `ERR_UNAUTHENTICATED`); role permission and entity-backed ownership, including the assigned-judge check (failures: `ERR_FORBIDDEN`, `ERR_NOT_ASSIGNED_JUDGE`); existence of every referenced resource, validated left-to-right along the path identifiers first and then the body foreign keys (failure: `ERR_NOT_FOUND`); state validity for the requested transition, including terminal-state lockdown, non-adjacent posture advance, settlement and closure guards, reoffer from a non-`PASSED` lot, double issue or double void, and lots opened out of order (failure: `ERR_INVALID_STATE`); the fair posture gate (failure: `ERR_POSTURE_FORBIDS`); business safety rules — the health hold on disposition completion, the suspended-exhibitor block on entry creation, the affidavit requirement on approvals, and segregation of duties; business temporal rules — the ownership and possession deadlines, ring time conflicts, judge spacing, withdrawal clearance, and disposition scheduling; business constraint rules — payload well-formedness (failure: `ERR_INVALID_REQUEST`, covering missing required fields, invalid enum values, non-positive `weight_lbs`, an `ends_at` not after `starts_at`, a `weight_max_lbs` not greater than `weight_min_lbs`, non-positive `capacity`, and bad ranks), tag and class uniqueness, class capacity, judge qualification, champion uniqueness, rank sequence, placing completeness, reoffer limits, disposition compatibility, and affidavit uniqueness; referential rules — placing-line class membership and the sold-lot requirement on pledges; and finally fiscal rules, where buyer credit exposure is checked before amount positivity, and amount positivity before overpayment. Because the ladder fixes evaluation order, a posture failure surfaces as `ERR_POSTURE_FORBIDS` even when a deadline is also missed, and a non-existent buyer surfaces as `ERR_NOT_FOUND` before any credit check runs.

### 2.8. Money, Weights and Rounding

Every monetary value in the system is an integer number of cents; no fractional cents are ever stored or returned. Three computations round half-up to whole cents: the per-line buyer premium on an invoice, the auction commission deducted from an exhibitor payout, and the large-class premium bonus. One computation rounds down: the settlement scale-down floors the scaled premium amount to whole cents. Weights — `weight_lbs` on a ticket, `official_weight_lbs` on an entry, and the `weight_min_lbs` / `weight_max_lbs` class bounds — are stored exactly as given (one decimal place is typical) and compared exactly, with no rounding.

### 2.9. Optimistic Concurrency Control

Two write operations are version-checked, and both take their version field as a non-optional input. Creating a weigh ticket (`POST /v1/weigh-tickets` — the write behind every new ticket, whether a first weigh-in or a reweigh) requires `expected_entry_version` carrying the caller's last observed `version` of the parent animal entry; recording a ticket advances the entry's `version`, so a client holding a stale value — for example one that read the entry before an earlier ticket was recorded — is rejected deterministically with `ERR_STALE_VERSION` (HTTP 412). Assigning a judge to a ring slot (`POST /v1/ring-slots/{slotId}/assign-judge`) requires `expected_ring_slot_version` carrying the caller's last observed `version` of the slot; assignment advances the slot's `version`, and a stale value is likewise rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint takes a version field; every other conflict in the system is expressed as a state precondition under §2.7.

### 2.10. Cascading Corrections and Derived Reconciliation

Several fields are never set directly by clients but are reconciled by the server as events occur: an entry's `official_weight_lbs` tracks its latest active weigh ticket; a class's `placed_count` tracks its placed entries; the fair's `available_premium_pool_cents` tracks outstanding award reservations against the purse; a draft invoice's totals track its swept lines; and an entry's `state_fair_qualified` flag tracks its placing. When a correction lands — a ticket superseded, a placing voided, an entry disqualified, a sale closed — the server fires the compensating cascade immediately: prior tickets are voided, awards are forfeited back to the pool, lots are closed, pending dispositions are rejected, class counts are decremented, and classes reopen. Each reconciliation independently mutates the owning entity, refreshing its `updated_at` and incrementing its `version`.

## 3. Business Logic & Workflows

### 3.1. Standing Up the Fair Edition and Its People

A `FairBoardAdmin` stands up a new fair edition by supplying its `name`, the two entry deadlines `ownership_deadline_at` and `possession_deadline_at`, the total purse `premium_budget_cents`, the sale economics — `commission_rate` as the fair's fraction of the hammer price (for example 0.05), `buyer_premium_rate` as the fraction charged to buyers on each hammer line (for example 0.03), and the flat per-lot `yardage_fee_cents` deducted from exhibitor payouts — the per-award `premium_cap_cents`, and the large-class configuration, where `large_class_min_entries` defaults to 8 and `large_class_bonus_rate` defaults to 0.10 when omitted. The premium schedule is supplied as `premium_schedule`, mapping each species to six values: `grand_champion_cents`, `reserve_champion_cents`, `rank_1_cents`, `rank_2_cents`, `rank_3_cents`, and `other_rank_cents`. Two further per-species maps govern what happens after the show: `state_qualify_rank` gives the maximum rank, inclusive, that qualifies an entry for the state fair, and `sale_rank_threshold` gives the maximum rank, inclusive, that makes an entry eligible for the auction; in both maps, any entry carrying a champion award qualifies regardless of rank. Finally, `species_sale_order` lists the species in the order they should sell within an award tier. A newly created fair starts in `posture` `SETUP` with `available_premium_pool_cents` equal to `premium_budget_cents` — the full purse is uncommitted.

With the fair configured, the board registers its people. An exhibitor is registered with `fair_id`, `full_name`, and `organization`, which must be one of `FFA`, `FOUR_H`, or `INDEPENDENT`; new exhibitors start `ACTIVE`. Suspending an exhibitor moves them to `SUSPENDED`: from that point, entry creation naming that exhibitor is rejected with `ERR_EXHIBITOR_SUSPENDED` (HTTP 409) no matter who files it, while their existing entries are unaffected. A buyer is registered at the sale desk with `fair_id`, `business_name`, and `credit_limit_cents`; the server assigns a `bidder_number` automatically — the letter B followed by a zero-padded three-digit sequence number, handed out per fair in `created_at` ascending order. A judge is registered with `fair_id`, `full_name`, and a non-empty `qualified_species` list drawn from the four market species.

### 3.2. Entry Intake and Deadline Verification

While the fair is in `ENTRIES_OPEN`, a `FairBoardAdmin` or an `Exhibitor` files an animal entry; an exhibitor may file only for themselves, meaning the payload's `exhibitor_id` must equal their `X-User-ID`. The entry carries `fair_id`, `exhibitor_id`, `species` (one of `MARKET_STEER`, `MARKET_SWINE`, `MARKET_LAMB`, `MARKET_GOAT`), the ear tag `tag_number`, and the two dates the board will verify: `ownership_acquired_at` and `possession_start_at`. The `tag_number` must be unique within the fair — a duplicate is rejected with `ERR_DUPLICATE_TAG` (HTTP 409). A fresh entry starts in `ENTERED` with `official_weight_lbs` null (it has never been weighed), `class_id` null (it has not been classified), `state_fair_qualified` false, and `disqualification_reason` null.

Verification is a `FairBoardAdmin` decision carrying `decision` — `APPROVE` or `REJECT` — plus an optional `note`. The fair must be in `ENTRIES_OPEN` or `ENTRIES_LOCKED`, otherwise the verification is rejected with `ERR_POSTURE_FORBIDS`. Approval then checks the two deadlines in order, both boundaries inclusive: `ownership_acquired_at` must be on or before the fair's `ownership_deadline_at`, else `ERR_OWNERSHIP_DEADLINE_MISSED` (HTTP 422); then `possession_start_at` must be on or before the fair's `possession_deadline_at`, else `ERR_POSSESSION_DEADLINE_MISSED` (HTTP 422). Because the deadline checks are temporal rules, they are evaluated only after the posture gate has passed, per §2.7. An approved entry moves `ENTERED` → `VERIFIED`; a rejected one moves `ENTERED` → `REJECTED`, which is terminal. Each decision increments the entry's `version` by one.

### 3.3. Weigh-In, Official Weight and Classification

Once the fair reaches `WEIGH_IN`, the `WeighMaster` records scale tickets. Each ticket names the `entry_id`, the scale reading `weight_lbs` (which must be greater than zero, else `ERR_INVALID_REQUEST`), the ticket timestamp `weighed_at`, and an optional `scale_identifier` naming the scale station. Because creating a ticket supersedes the entry's prior `ACTIVE` ticket and rewrites the official weight, the request must also carry `expected_entry_version` matching the entry's current `version`; a stale value is rejected with `ERR_STALE_VERSION` as described in §2.9. The first ticket for an entry moves it `VERIFIED` → `WEIGHED`. A ticket is accepted only while the entry is `VERIFIED`, `WEIGHED`, or `CLASSIFIED` — recording one against an entry in any other state is rejected with `ERR_INVALID_STATE`. Recording a fresh ticket for a `WEIGHED` entry supersedes its prior `ACTIVE` ticket, which is voided with `void_reason` `SUPERSEDED`, while the entry remains `WEIGHED` and the official weight is recomputed. Recording a fresh ticket for a `CLASSIFIED` entry is a reweigh: the prior `ACTIVE` ticket is voided with `void_reason` `SUPERSEDED`, the entry's `class_id` is cleared to null, the prior class's `placed_count` is decremented by one, the entry falls back `CLASSIFIED` → `WEIGHED`, and the official weight is recomputed. Every ticket creation increments the entry's `version` by one.

The official weight is resolved deterministically. Among the entry's weigh tickets in `ACTIVE` status — `VOIDED` tickets are excluded — the winner is the ticket with the greatest `created_at`; if two tickets share the same `created_at` millisecond, the larger `weighed_at` wins; if still tied, the larger `weight_lbs` wins. The `id` never participates in this tie-break. The winning ticket's `weight_lbs` becomes `official_weight_lbs`; when no `ACTIVE` ticket remains, `official_weight_lbs` becomes null. A `WeighMaster` may also void a ticket manually with an optional `reason`, but only while the entry is `WEIGHED` — voiding against a `CLASSIFIED`-or-later entry is rejected with `ERR_INVALID_STATE`, because such an entry is corrected by recording a new ticket instead. After a manual void the official weight is recomputed from the remaining `ACTIVE` tickets, and if none remain the entry falls back `WEIGHED` → `VERIFIED`.

Classification starts with the classes themselves. A `FairBoardAdmin` creates each `ShowClass` with `fair_id`, `species`, a human `class_code` label such as LAMB-LIGHT, a half-open weight bracket from `weight_min_lbs` (inclusive) to `weight_max_lbs` (exclusive, and strictly greater than the minimum), and a `capacity` greater than zero. Two classes of the same fair and species may not have overlapping brackets under half-open semantics — touching boundaries, where one class's maximum equals the next class's minimum, are allowed — and `class_code` must be unique within the fair and species; either violation is rejected with `ERR_CLASS_RANGE_OVERLAP` (HTTP 409). A new class starts `OPEN` with `placed_count` zero. Thereafter `placed_count` is a derived count of the entries whose `class_id` references the class and whose status is `CLASSIFIED`, `SHOWN`, `SOLD`, `NOT_SOLD`, or `CLEARED`.

A `ShowClerk` classifies a `WEIGHED` entry during the `WEIGH_IN` posture. Without an explicit target, the selector considers every `OPEN` class of the entry's fair and species whose bracket contains the official weight — lower bound inclusive, upper bound exclusive — and whose `placed_count` is still below `capacity`; among the eligible classes it picks the one with the lowest `weight_min_lbs`, breaking ties by earliest `created_at` and never by `id`, and an empty eligible set is rejected with `ERR_NO_CLASS_FOR_WEIGHT` (HTTP 422). When the request names an explicit `class_id`, failures map specifically: a target that is not `OPEN` yields `ERR_CLASS_NOT_OPEN` (HTTP 409), a target already at capacity yields `ERR_CLASS_CAPACITY_FULL` (HTTP 409), and a weight outside the bracket or a species mismatch yields `ERR_NO_CLASS_FOR_WEIGHT` — in that order. A successful classification moves the entry `WEIGHED` → `CLASSIFIED`, sets its `class_id`, and increments the target class's `placed_count` by one.

### 3.4. Ring Scheduling, Judge Assignment and Placing Submission

Before the show, a `ShowClerk` schedules each class into the ring. A ring slot names `fair_id`, the `class_id` it covers — at most one slot per class within the fair — the physical `ring_name`, and a half-open interval from `starts_at` to `ends_at`, where `ends_at` must be strictly after `starts_at` (else `ERR_INVALID_REQUEST`). Two slots sharing the same `ring_name` may not overlap under half-open semantics; touching intervals, where one slot's end equals the other's start, are allowed. An overlap is rejected with `ERR_RING_TIME_CONFLICT` (HTTP 409). A new slot starts `SCHEDULED` with `judge_id` null.

Judge assignment, also by the `ShowClerk`, carries `judge_id` and the non-optional `expected_ring_slot_version`; because assignment overwrites the slot's `judge_id` and advances the slot's `version`, a stale expected version is rejected with `ERR_STALE_VERSION` per §2.9. Two business checks follow. The judge's `qualified_species` must include the species of the slot's class, otherwise `ERR_JUDGE_NOT_QUALIFIED` (HTTP 422). And the judge's booked intervals must keep at least a 15-minute gap between any two assignments — mere adjacency without that buffer is a conflict, rejected with `ERR_JUDGE_TIME_CONFLICT` (HTTP 409). Reassignment uses the same operation and the same checks.

When the fair is `SHOWING`, the clerk starts a slot, moving it `SCHEDULED` → `IN_PROGRESS`; starting requires a judge to be assigned (else `ERR_INVALID_STATE`) and the `SHOWING` posture (else `ERR_POSTURE_FORBIDS`). The assigned judge — and only that judge, with anyone else rejected as `ERR_NOT_ASSIGNED_JUDGE` — then submits the complete placing set for the slot's class in a single atomic request whose body carries a `placings` collection; every line names an `entry_id`, a `rank`, and an `award` of `NONE`, `GRAND_CHAMPION`, or `RESERVE_CHAMPION` (defaulting to `NONE` when omitted). Either every line is valid and the whole set is recorded, or nothing is. Within the submission the checks fire in a fixed order: payload well-formedness first; then champion uniqueness — at most one `GRAND_CHAMPION` and one `RESERVE_CHAMPION` per species per fair, else `ERR_CHAMPION_ALREADY_AWARDED` (HTTP 409); then rank contiguity — the ranks must be exactly the contiguous set 1 through N with no duplicates or gaps, else `ERR_RANK_SEQUENCE_INVALID` (HTTP 422); then completeness — the set must cover every entry whose `class_id` is the slot's class and whose status is `CLASSIFIED`, else `ERR_INCOMPLETE_PLACINGS` (HTTP 422); and finally per-line membership — each line's entry must belong to the slot's class and be `CLASSIFIED`, else `ERR_ENTRY_NOT_IN_CLASS` (HTTP 422).

Acceptance sets off a chain of effects. A `Placing` row is recorded per line in `RECORDED` status, carrying the denormalized `ring_slot_id` and `class_id` of the slot. Every placed entry moves `CLASSIFIED` → `SHOWN`. The class moves `OPEN` → `FINALIZED`, and the slot moves `IN_PROGRESS` → `COMPLETED`. A `PremiumAward` in `ACCRUED` status is created for each placing — one award per placing, recorded against the placing through `placing_id` and against the animal through `entry_id` — its `provisional_amount_cents` computed per §3.5, and the fair's `available_premium_pool_cents` is debited by that amount. Each entry's `state_fair_qualified` is recomputed: it is set when the placing's `award` is anything other than `NONE`, or when the `rank` is at or under the species threshold in the fair's `state_qualify_rank` — the boundary is inclusive, so a rank exactly equal to the threshold qualifies. The response returns the created `placing_ids` and `premium_award_ids`.

A placing can be voided afterwards by the slot's assigned judge or by a `FairBoardAdmin`, supplying a `reason`. Voiding moves the placing `RECORDED` → `VOIDED` with `void_reason` set, forfeits its premium award with the reservation released back to the pool, drops the entry back `SHOWN` → `CLASSIFIED`, recomputes `state_fair_qualified` to false, and reopens the class `FINALIZED` → `OPEN`.

### 3.5. Premium Awards and the Purse

The premium for a placing comes from the fair's `premium_schedule` for the entry's species. The base amount is `grand_champion_cents` for a `GRAND_CHAMPION` award, `reserve_champion_cents` for a `RESERVE_CHAMPION` award, `rank_1_cents`, `rank_2_cents`, or `rank_3_cents` for ranks one through three respectively, and `other_rank_cents` for any deeper rank. A large-class bonus applies when the class's `placed_count`, counted after the placing batch lands, is at least the fair's `large_class_min_entries`: the bonus is the base multiplied by `large_class_bonus_rate`, rounded half-up to whole cents, and is zero otherwise. The provisional award, `provisional_amount_cents`, is the base plus the bonus, capped at `premium_cap_cents` — the cap applies after the bonus, so the stored amount is the smaller of the two.

The purse is a conserved quantity. At every moment, `available_premium_pool_cents` equals `premium_budget_cents` minus the sum of `provisional_amount_cents` across all of the fair's awards in `ACCRUED`, `APPROVED`, or `PAID` status; `FORFEITED` awards are excluded because their reservation has returned to the pool. When placings outrun the purse, the pool may transiently go negative; the settlement sweep brings payouts back within budget.

That sweep is run by a `FairBoardAdmin` via run-settlement. For every award still `ACCRUED` or `APPROVED`, the server totals the outstanding reservations, computes a scale as the ratio of `premium_budget_cents` to that outstanding total capped at 1 (an outstanding total of zero scales at 1 vacuously), and sets each award's `final_amount_cents` to its `provisional_amount_cents` multiplied by the scale and rounded down to whole cents. The final amount therefore differs from the provisional amount whenever the purse is oversubscribed. The same sweep also computes the final exhibitor payouts described in §3.7, and increments the fair's `version` by one.

Awards are settled under segregation of duties. A `Treasurer` approves an `ACCRUED` award only while the fair is in `SETTLEMENT` (else `ERR_POSTURE_FORBIDS`) and only when the entry has an affidavit in `SIGNED` status (else `ERR_AFFIDAVIT_MISSING`, HTTP 409); approval records the caller in `approved_by_user_id` and moves the award `ACCRUED` → `APPROVED`. Payment moves `APPROVED` → `PAID` and must be executed by a different treasurer: the caller's `X-User-ID` must differ from `approved_by_user_id`, else the payment is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). The paying treasurer is recorded in `paid_by_user_id`, and the paid amount is `final_amount_cents` when it has been set, otherwise `provisional_amount_cents`. A `Treasurer` may also forfeit an award — from `ACCRUED` or from `APPROVED` alike — by supplying a `reason`; forfeiture moves the award to `FORFEITED` and releases `provisional_amount_cents` back into `available_premium_pool_cents`. Forfeiture also fires automatically when the underlying placing is voided and when the entry is disqualified.

### 3.6. The Premium Auction

With the fair in `AUCTION`, the `Auctioneer` generates the sale order for a `fair_id`. An entry is eligible for a lot when it is `SHOWN`, no lot already references it, its exhibitor is still `ACTIVE`, its health record is clean — no inspection of the entry has result `FAIL`, and the latest inspection by `created_at`, if any exists, is `PASS` — and it earned its way in: either its placing's `award` is not `NONE`, or its `rank` is at or under the species threshold in `sale_rank_threshold`, with the boundary inclusive. Eligible entries are ordered by award tier first — `GRAND_CHAMPION` before `RESERVE_CHAMPION` before `NONE` — then by their species' position in `species_sale_order`, then by `rank` ascending, then by the entry's `created_at` ascending; `id` never participates in the ordering. Lots receive `lot_number` values gapless from 1 in that order, and the response returns the created `lot_ids` and a `lot_count`. Each new lot starts `QUEUED` with `reoffer_count` zero and `buyer_id`, `hammer_price_cents`, and `invoice_id` all null.

Lots sell strictly in order. Opening a lot moves it `QUEUED` → `OPEN`, and requires every lot of the fair with a smaller `lot_number` to be past `QUEUED` already; opening out of order is rejected with `ERR_INVALID_STATE`.

Closing a lot as sold records the hammer. The payload names the winning `buyer_id`, which must reference an existing buyer (else `ERR_NOT_FOUND`), and `hammer_price_cents`. Before the hammer falls, the buyer's exposure is checked: the buyer's committed total is the sum of `hammer_price_cents` across their `SOLD` lots that are not on a `PAID` invoice, plus the sum of `amount_cents` across their pledges in `PLEDGED` or `INVOICED` status; the committed total plus the new `hammer_price_cents` must not exceed the buyer's `credit_limit_cents`. The boundary is inclusive — equality passes — and one cent over is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 422). Per the evaluation ladder, this credit check runs before the amount-positivity check, which requires `hammer_price_cents` to be greater than zero (else `ERR_INVALID_AMOUNT`, HTTP 422).

A successful hammer close fires a four-part cascade. The lot records `buyer_id` and `hammer_price_cents`, and its `provisional_payout_cents` is computed as the hammer price minus the commission — the hammer price multiplied by the fair's `commission_rate`, rounded half-up to whole cents — minus the flat `yardage_fee_cents`. The entry moves `SHOWN` → `SOLD`. The sale requires harvest: a new disposition order is auto-created for the entry with `disposition_type` `HARVEST` in `REQUESTED` status and `created_by_user_id` recorded as `SYSTEM`, and any of the entry's pending `RETURN` orders in `REQUESTED` or `APPROVED` status are rejected with `reject_reason` `SALE_REQUIRES_HARVEST`. Finally, the buyer's `DRAFT` invoice is upserted — created on the buyer's first hammer, reused thereafter — and the lot line is added, with the draft totals live-recomputed per §3.7.

Not every lot sells. When no bid is acceptable, the auctioneer passes the lot, moving `OPEN` → `PASSED`. A passed lot may be reoffered, moving `PASSED` → `OPEN` and incrementing `reoffer_count` by one, but only while `reoffer_count` is below 2 — a third reoffer is rejected with `ERR_REOFFER_LIMIT_REACHED` (HTTP 409). Declaring no-sale moves a `PASSED` lot to `NO_SALE` and drops the entry `SHOWN` → `NOT_SOLD`. Lots in `QUEUED` or `PASSED` are also closed to `NO_SALE` automatically when their entry is disqualified. The auction phase can end — advancing `AUCTION` → `SETTLEMENT` — only once every lot of the fair sits in `SOLD` or `NO_SALE`.

### 3.7. Add-On Pledges, Invoicing and Collections

After a lot sells, supporters can pile on donations. A `Buyer` pledging for themselves — `buyer_id` equal to their `X-User-ID` — or a `FairBoardAdmin` creates an add-on pledge naming `lot_id`, `buyer_id`, and `amount_cents`. The lot must be `SOLD` and not yet swept into an `ISSUED` invoice, otherwise the pledge is rejected with `ERR_LOT_NOT_SOLD` (HTTP 409); that lot-eligibility check runs before the amount check, which requires `amount_cents` greater than zero (else `ERR_INVALID_AMOUNT`). A new pledge starts `PLEDGED` with `invoice_id` null, and the buyer's draft invoice totals live-recompute to include it. While still `PLEDGED`, a pledge can be voided by the pledging buyer or an admin with an optional `reason`, moving it to `VOIDED` and removing it from the draft totals; once invoiced it can no longer be voided.

An invoice belongs to one buyer within one fair and tracks the buyer's whole account. While it is `DRAFT`, its totals are live-derived: `hammer_subtotal_cents` sums the hammer prices of the swept `SOLD` lots, `addon_subtotal_cents` sums the `amount_cents` of the swept pledges, `buyer_premium_cents` sums the per-line premiums, `total_due_cents` is the sum of those three subtotals, and `line_count` counts the swept lines of both kinds — each swept lot contributes a hammer line and each swept pledge an add-on line. The premium rounding order is pinned: for each hammer line, the line premium is the line's hammer price multiplied by the fair's `buyer_premium_rate`, rounded half-up to whole cents, and `buyer_premium_cents` is the sum of those rounded line values; add-on lines carry no buyer premium. The alternative order — rounding the premium on the summed hammer — can differ by cents and is not the contract.

Issuing is a `Treasurer` action under the `SETTLEMENT` posture (else `ERR_POSTURE_FORBIDS`) and requires at least one unswept line for the buyer (else `ERR_INVALID_STATE`). The issue sweeps the buyer's `SOLD` lots whose `invoice_id` is still null, together with their `PLEDGED` add-on pledges, into the invoice: swept pledges move `PLEDGED` → `INVOICED` with `invoice_id` set, swept lots get their `invoice_id` set, the invoice moves `DRAFT` → `ISSUED`, and every total freezes at its issued value.

Payments are posted by a `Treasurer` with `amount_cents`. The amount must be greater than zero (else `ERR_INVALID_AMOUNT`) and must not exceed the invoice's `balance_cents` (else `ERR_OVERPAYMENT`, HTTP 422); positivity is checked before the overpayment bound. A payment smaller than the balance moves `ISSUED` → `PARTIALLY_PAID`, and further partial payments keep the invoice in `PARTIALLY_PAID`; each payment recomputes `amount_paid_cents` as the sum of posted payments and `balance_cents` as `total_due_cents` minus that sum. A payment exactly equal to the balance — from `ISSUED` or from `PARTIALLY_PAID` — moves the invoice to `PAID`, drives `balance_cents` to zero, and cascades every swept pledge from `INVOICED` to `PAID`.

The exhibitor side of the sale settles at run-settlement. Each `SOLD` lot's `final_payout_cents` is the hammer price plus the sum of `amount_cents` across the lot's pledges in any status other than `VOIDED`, minus the same rounded commission, minus `yardage_fee_cents`. The final payout therefore differs from `provisional_payout_cents` whenever any non-void add-on pledge exists on the lot.

### 3.8. Health Compliance, Affidavits and Animal Disposition

A `HealthInspector` records an inspection for an `entry_id` with a `result` of `PASS`, `FAIL`, or `QUARANTINE` and optional `notes`. Inspection records are immutable once created. A `FAIL` result disqualifies the entry immediately through the cascade described below.

The drug-free affidavit is signed once per entry — a second affidavit for the same entry is rejected with `ERR_AFFIDAVIT_EXISTS` (HTTP 409). An `Exhibitor` signs only for their own entries; a `FairBoardAdmin` may sign for any. Signing records `signed_at` from the logical clock, denormalizes the entry's owner into the affidavit's `exhibitor_id`, accepts an optional `withdrawal_end_date` marking the end of a drug withdrawal period, and leaves the affidavit `SIGNED`. A `HealthInspector` may later revoke a `SIGNED` affidavit by supplying a `reason`, which is recorded as `revoked_reason`; revocation is blocked while the entry is `SOLD`, `CLEARED`, `REJECTED`, or `DISQUALIFIED` (else `ERR_INVALID_STATE`), and a successful revocation moves the affidavit to `REVOKED` and disqualifies the entry through the same cascade.

Movement off the grounds runs through disposition orders. An order is requested for an `entry_id` with a `disposition_type` of `HARVEST` or `RETURN`, an optional `destination`, and an optional `scheduled_date`; it starts `REQUESTED` with `created_by_user_id` set to the caller, or to `SYSTEM` when the sale cascade auto-creates it. An `Exhibitor` requests orders only for their own entries. Type compatibility is enforced at request time, again at approval, and again at completion against the entry's then-current status: `HARVEST` requires the entry to be `SOLD` or `NOT_SOLD`, and `RETURN` requires `SHOWN`, `NOT_SOLD`, or `DISQUALIFIED`; any mismatch is rejected with `ERR_DISPOSITION_NOT_ALLOWED` (HTTP 409). Approval is a `FairBoardAdmin` checker step on a `REQUESTED` order, and its checks fire in order: the entry must carry a `SIGNED` affidavit (else `ERR_AFFIDAVIT_MISSING`) — the same requirement that guards premium approval — then the approver must differ from `created_by_user_id` unless the creator is `SYSTEM` (else `ERR_SEGREGATION_OF_DUTIES`), then type compatibility. Approval records `approved_by_user_id`. Rejection supplies a `reason`, sets `reject_reason`, and moves the order `REQUESTED` → `REJECTED`.

Completing an `APPROVED` order is the last mile, and four gates stand in front of it, evaluated in order. The latest health inspection for the entry, by `created_at`, must exist and be `PASS` — no inspection at all, or a latest of `QUARANTINE` or `FAIL`, is rejected with `ERR_HEALTH_HOLD` (HTTP 409). For `HARVEST` only, the affidavit's `withdrawal_end_date` must be null or the current logical time must be at or past it — a logical time strictly earlier is rejected with `ERR_WITHDRAWAL_NOT_CLEARED` (HTTP 409). The `scheduled_date` must be null or the current logical time must be at or past it, else `ERR_DISPOSITION_TOO_EARLY` (HTTP 409). And the disposition type must still be compatible with the entry's current status, else `ERR_DISPOSITION_NOT_ALLOWED`. Completion moves the order to `COMPLETED`, and when the entry is `SOLD` or `NOT_SOLD` the entry itself moves to `CLEARED`.

Disqualification is the system's heaviest correction. A `FairBoardAdmin` disqualifies an entry manually with a `reason` recorded as `disqualification_reason`; the same transition fires automatically on a `FAIL` inspection and on affidavit revocation. It is permitted from `VERIFIED`, `WEIGHED`, `CLASSIFIED`, `SHOWN`, or `NOT_SOLD`; `SOLD` and `CLEARED` entries cannot be disqualified because the sale is final, and attempts there are rejected with `ERR_INVALID_STATE`. The cascade compensates everything the entry touched: the entry becomes `DISQUALIFIED`; its `RECORDED` placings become `VOIDED`; its `ACCRUED` or `APPROVED` awards become `FORFEITED` with `provisional_amount_cents` released back to the pool; its `QUEUED` or `PASSED` lots become `NO_SALE`; its `REQUESTED` or `APPROVED` disposition orders become `REJECTED` with `reject_reason` set; `state_fair_qualified` is cleared to false; and if the entry was `CLASSIFIED` or `SHOWN`, its `class_id` is cleared, the class's `placed_count` is decremented by one, and a `FINALIZED` class reopens to `OPEN`.

Closing the fair is the final board action. The move `SETTLEMENT` → `CLOSED` succeeds only when every invoice of the fair is `PAID`, every premium award is `PAID` or `FORFEITED`, and every disposition order is `COMPLETED` or `REJECTED`; any straggler rejects the close with `ERR_INVALID_STATE`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — state transitions, assignments, sweeps, payments — return `200 OK`. All list and get endpoints return `200 OK`. The request and response shapes for each operation are defined by the workflows in §3; this table is the routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/v1/fairs` | Create a fair edition with deadlines, purse, fee and schedule config | FairBoardAdmin |
| GET | `/v1/fairs/{fairId}` | Get a fair, including posture and available premium pool | All roles |
| POST | `/v1/fairs/{fairId}/advance-posture` | Advance the fair posture exactly one step in canonical order | FairBoardAdmin |
| POST | `/v1/fairs/{fairId}/reopen-entries` | Move ENTRIES_LOCKED back to ENTRIES_OPEN before any active weigh ticket exists | FairBoardAdmin |
| POST | `/v1/fairs/{fairId}/run-settlement` | Settlement sweep: final premium amounts and final exhibitor payouts | FairBoardAdmin |
| POST | `/_clock/set_current_utc` | Set the server-side logical clock | FairBoardAdmin |
| POST | `/v1/exhibitors` | Register an exhibitor | FairBoardAdmin |
| GET | `/v1/exhibitors/{exhibitorId}` | Get an exhibitor | All roles |
| GET | `/v1/exhibitors` | List exhibitors, optionally filtered | All roles |
| POST | `/v1/exhibitors/{exhibitorId}/suspend` | Suspend an exhibitor, blocking new entries | FairBoardAdmin |
| POST | `/v1/entries` | Create an animal entry; exhibitors file only for themselves | FairBoardAdmin, Exhibitor |
| GET | `/v1/entries/{entryId}` | Get an entry | All roles |
| GET | `/v1/entries` | List entries, optionally filtered | All roles |
| POST | `/v1/entries/{entryId}/verify` | Verify ownership and possession deadlines; approve or reject | FairBoardAdmin |
| POST | `/v1/entries/{entryId}/disqualify` | Manually disqualify an entry with the full compensation cascade | FairBoardAdmin |
| POST | `/v1/weigh-tickets` | Record a weigh-in; supersedes the entry's prior active ticket | WeighMaster |
| GET | `/v1/weigh-tickets/{ticketId}` | Get a weigh ticket | All roles |
| GET | `/v1/weigh-tickets` | List weigh tickets, optionally filtered by entry | All roles |
| POST | `/v1/weigh-tickets/{ticketId}/void` | Void an active ticket while the entry is WEIGHED | WeighMaster |
| POST | `/v1/classes` | Create a show class with a half-open weight bracket | FairBoardAdmin |
| GET | `/v1/classes/{classId}` | Get a class | All roles |
| GET | `/v1/classes` | List classes, optionally filtered | All roles |
| POST | `/v1/entries/{entryId}/classify` | Place a WEIGHED entry into a class, by selector or explicit target | ShowClerk |
| POST | `/v1/judges` | Register a judge with species qualifications | FairBoardAdmin |
| GET | `/v1/judges/{judgeId}` | Get a judge | All roles |
| GET | `/v1/judges` | List judges, optionally filtered by fair | All roles |
| POST | `/v1/ring-slots` | Schedule a class into a ring time slot | ShowClerk |
| GET | `/v1/ring-slots/{slotId}` | Get a ring slot | All roles |
| GET | `/v1/ring-slots` | List ring slots, optionally filtered | All roles |
| POST | `/v1/ring-slots/{slotId}/assign-judge` | Assign or reassign the slot judge with qualification and spacing checks | ShowClerk |
| POST | `/v1/ring-slots/{slotId}/start` | Start a scheduled slot that has a judge assigned | ShowClerk |
| POST | `/v1/ring-slots/{slotId}/placings` | Judge submits the slot's complete placing set, atomically | Judge |
| GET | `/v1/placings/{placingId}` | Get a placing | All roles |
| GET | `/v1/placings` | List placings, optionally filtered | All roles |
| POST | `/v1/placings/{placingId}/void` | Void a recorded placing, compensating award, pool, class and entry | Judge, FairBoardAdmin |
| GET | `/v1/premium-awards/{awardId}` | Get a premium award | All roles |
| GET | `/v1/premium-awards` | List premium awards, optionally filtered | All roles |
| POST | `/v1/premium-awards/{awardId}/approve` | Approve an accrued award under SETTLEMENT with a signed affidavit | Treasurer |
| POST | `/v1/premium-awards/{awardId}/pay` | Pay an approved award; payer must differ from approver | Treasurer |
| POST | `/v1/premium-awards/{awardId}/forfeit` | Forfeit an accrued or approved award back to the pool | Treasurer |
| POST | `/v1/buyers` | Register a buyer; bidder number auto-assigned per fair | FairBoardAdmin |
| GET | `/v1/buyers/{buyerId}` | Get a buyer | All roles |
| GET | `/v1/buyers` | List buyers, optionally filtered by fair | All roles |
| POST | `/v1/auction-lots/generate` | Build the sale order: one queued lot per eligible SHOWN entry | Auctioneer |
| GET | `/v1/auction-lots/{lotId}` | Get an auction lot | All roles |
| GET | `/v1/auction-lots` | List auction lots, optionally filtered | All roles |
| POST | `/v1/auction-lots/{lotId}/open` | Open a lot for bidding in strict lot-number order | Auctioneer |
| POST | `/v1/auction-lots/{lotId}/close-sold` | Record the hammer: buyer and price, with the close-sold cascade | Auctioneer |
| POST | `/v1/auction-lots/{lotId}/close-passed` | Pass an open lot when no bid is acceptable | Auctioneer |
| POST | `/v1/auction-lots/{lotId}/reoffer` | Reopen a passed lot, at most twice | Auctioneer |
| POST | `/v1/auction-lots/{lotId}/no-sale` | Declare a passed lot no-sale; the entry becomes NOT_SOLD | Auctioneer |
| POST | `/v1/add-ons` | Pledge an add-on donation on a sold, not-yet-invoiced lot | Buyer, FairBoardAdmin |
| GET | `/v1/add-ons/{addonId}` | Get an add-on pledge | All roles |
| GET | `/v1/add-ons` | List add-on pledges, optionally filtered | All roles |
| POST | `/v1/add-ons/{addonId}/void` | Void a pledged add-on before invoicing | Buyer, FairBoardAdmin |
| GET | `/v1/invoices/{invoiceId}` | Get an invoice; draft totals are live, issued totals frozen | All roles |
| GET | `/v1/invoices` | List invoices, optionally filtered | All roles |
| POST | `/v1/invoices/{invoiceId}/issue` | Issue a draft invoice: sweep lines, freeze totals, invoice add-ons | Treasurer |
| POST | `/v1/invoices/{invoiceId}/payments` | Post a payment against an issued invoice | Treasurer |
| POST | `/v1/dispositions` | Request a harvest or return disposition for an entry | FairBoardAdmin, Exhibitor |
| GET | `/v1/dispositions/{orderId}` | Get a disposition order | All roles |
| GET | `/v1/dispositions` | List disposition orders, optionally filtered | All roles |
| POST | `/v1/dispositions/{orderId}/approve` | Approve a requested order; approver differs from creator, affidavit required | FairBoardAdmin |
| POST | `/v1/dispositions/{orderId}/reject` | Reject a requested order with a reason | FairBoardAdmin |
| POST | `/v1/dispositions/{orderId}/complete` | Complete an approved order after health, withdrawal and schedule gates | FairBoardAdmin |
| POST | `/v1/health-inspections` | Record a health inspection; FAIL auto-disqualifies the entry | HealthInspector |
| GET | `/v1/health-inspections/{inspectionId}` | Get a health inspection | All roles |
| GET | `/v1/health-inspections` | List health inspections, optionally filtered by entry | All roles |
| POST | `/v1/affidavits` | Sign the drug-free affidavit for an entry, one per entry | Exhibitor, FairBoardAdmin |
| GET | `/v1/affidavits/{affidavitId}` | Get an affidavit | All roles |
| GET | `/v1/affidavits` | List affidavits, optionally filtered | All roles |
| POST | `/v1/affidavits/{affidavitId}/revoke` | Revoke a signed affidavit, triggering the disqualification cascade | HealthInspector |

## 5. Error Code Catalogue

Trigger conditions for each error live in the §2 and §3 narratives; this table is the identifier-to-status reference only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_ASSIGNED_JUDGE` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_POSTURE_FORBIDS` | 409 |
| `ERR_DUPLICATE_TAG` | 409 |
| `ERR_EXHIBITOR_SUSPENDED` | 409 |
| `ERR_CLASS_RANGE_OVERLAP` | 409 |
| `ERR_CLASS_NOT_OPEN` | 409 |
| `ERR_CLASS_CAPACITY_FULL` | 409 |
| `ERR_RING_TIME_CONFLICT` | 409 |
| `ERR_JUDGE_TIME_CONFLICT` | 409 |
| `ERR_CHAMPION_ALREADY_AWARDED` | 409 |
| `ERR_REOFFER_LIMIT_REACHED` | 409 |
| `ERR_DISPOSITION_NOT_ALLOWED` | 409 |
| `ERR_AFFIDAVIT_EXISTS` | 409 |
| `ERR_AFFIDAVIT_MISSING` | 409 |
| `ERR_HEALTH_HOLD` | 409 |
| `ERR_WITHDRAWAL_NOT_CLEARED` | 409 |
| `ERR_DISPOSITION_TOO_EARLY` | 409 |
| `ERR_LOT_NOT_SOLD` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_OWNERSHIP_DEADLINE_MISSED` | 422 |
| `ERR_POSSESSION_DEADLINE_MISSED` | 422 |
| `ERR_NO_CLASS_FOR_WEIGHT` | 422 |
| `ERR_JUDGE_NOT_QUALIFIED` | 422 |
| `ERR_ENTRY_NOT_IN_CLASS` | 422 |
| `ERR_RANK_SEQUENCE_INVALID` | 422 |
| `ERR_INCOMPLETE_PLACINGS` | 422 |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 422 |
| `ERR_INVALID_AMOUNT` | 422 |
| `ERR_OVERPAYMENT` | 422 |
