# Rodeo Event Production API — Product Requirements Document

## 1. Introduction

A PRCA rodeo committee runs a production that is deceptively hard to keep consistent: a slate of competition events split between rough stock and timed disciplines, contestants entering through a central office against a hard entry deadline, a deterministic draw that slots entries into performances and pairs rough-stock riders with animals, judges recording scores and times that must survive verification and the occasional amendment, and a purse that must be divided fairly across go-rounds and the average — all while the box office sells seats and the attending veterinarian can pull an animal or a contestant mid-performance. When any one of these moving parts is reconciled by hand, money, draw sheets, and animal-welfare records drift apart, and the arguments surface at the worst possible moment: payout night.

This document specifies the Rodeo Event Production API, the committee's system of record for the full life of a rodeo — production setup, contestant entry and fee accounting, stock contractor agreements and animal welfare, the draw, result capture and verification, payout computation, settlement, and ticketing. It defines the six acting roles, the state machines governing every resource, the monetary calculations pinned to the cent, and the order in which the server evaluates every guard, so that two engineers reading only this document build the same system.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The API recognizes exactly six roles, spelled exactly as follows: `CommitteeAdmin` (the rodeo committee secretary/administrator who runs production, the draw, verification, and payouts), `EntryOffice` (the central entry office clerk who registers contestants and processes entries), `Contestant` (a PRCA contestant acting on their own entries), `Judge` (an assigned event judge who records and amends results), `Veterinarian` (the on-site veterinarian filing welfare reports), and `BoxOffice` (the arena box office selling and refunding tickets). A request with missing headers or an unrecognized role is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted for the endpoint or action is rejected with `ERR_FORBIDDEN` (HTTP 403); the same rejection applies when a `Contestant` attempts to act on an entry belonging to someone else.

The meaning of `X-User-ID` differs by role. When `X-User-Role` is `Contestant`, `X-User-ID` is the `id` of the acting Contestant, and ownership checks on any entry compare the entry's `contestant_id` field to `X-User-ID`. When `X-User-Role` is `Judge`, `X-User-ID` is the `id` of the acting Judge; a result the judge submits records that value as its `judge_id`, and assignment-based checks compare against it. When `X-User-Role` is `CommitteeAdmin`, `EntryOffice`, `Veterinarian`, or `BoxOffice`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity — the server does not compare it to any resource's `id`.

All read endpoints (every GET in §4) are available to any authenticated role. Write operations are restricted per the role column of §4 and the workflow rules of §3.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter says how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns its resources sorted by creation timestamp (`created_at`) in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

Each list endpoint also accepts resource-scoped filter parameters, all optional: events filter by `rodeo_id` or `rodeo_event_id`; performances by `rodeo_id` and `status`; contestants by `card_number` and `status`; stock contracts by `rodeo_id` and `status`; animals by `contract_id`, `event_code`, and `status`; judges by `card_number` and `certification`; judge assignments by `judge_id` and `performance_id`; entries by `contestant_id`, `rodeo_event_id`, `status`, and `vet_report_id`; draw assignments by `entry_id`, `rodeo_event_id`, `performance_id`, `animal_id`, and `status`; results by `draw_assignment_id`, `entry_id`, `rodeo_event_id`, `judge_id`, and `status`; payouts by `rodeo_event_id` and `status`; vet reports by `animal_id`, `contestant_id`, and `performance_id`; and ticket orders by `performance_id` and `status`.

### 2.4. The Logical Clock

Rodeo deadlines are evaluated against a server-maintained logical clock, never against wall-clock time. At startup the logical clock reads exactly `2026-08-01T00:00:00Z`, and the server never silently falls back to wall-clock time at any point afterward. A `CommitteeAdmin`-only test-driving capability advances the clock: the request carries a `to_iso8601` instant and the response reports the resulting `current_utc`. The entry deadline on each rodeo — `entries_close_at` — is compared against this logical clock whenever an entry is created or re-entered (§3.2).

### 2.5. Common Resource Properties

Every primary resource in the API — rodeos, events, performances, contestants, stock contracts, animals, judges, judge assignments, entries, draw assignments, results, payouts, and ticket orders — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set when the resource is created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on any mutation of the resource.
- `version` (integer): a system-managed integer that increments by one on every mutation, including mutations caused by cascade side effects rather than a direct client call on that resource.

Vet reports are the one exception. A vet report is immutable once filed: it carries `id` and `created_at` only, and both `updated_at` and `version` are absent from it.

Posture transitions increment the rodeo's `version`; a contestant status update increments the contestant's `version`; entry transitions increment the entry's `version`; executing a draw increments the event's `version`; a re-ride increments the assignment's `version`; and verify, amend, and void each increment the result's `version`.

### 2.6. Money, Cents, and the Per-Entry Rounding Rule

All monetary amounts in the API are integer cents. Fees, retentions, purse contributions, ticket prices, contractor rates, and payout amounts are never fractional.

The entry-fee split (§3.2) is computed and rounded per entry at charge time, using round-half-up to whole cents. Aggregates such as the purse or total retention are always sums of those per-entry rounded values; the server never rounds an aggregate fee sum. The difference is real money: two entries at 2,005 and 2,030 cents produce retentions of 241 and 244 cents (summing to 485) and contributions of 1,164 and 1,186 cents (summing to 2,350), whereas rounding the combined 4,035-cent fee would yield a retention of 484 and a combined contribution of 2,351. Only the per-entry figures are correct.

Payout allocations (§3.7) are likewise integer cents rounded half-up, with two residual rules pinned: within a pool, the last paid place receives whatever remains after the earlier places are rounded; and the average pool absorbs every cent not allocated to non-empty go-round pools.

### 2.7. Cross-Entity Consistency and Automatic Cascades

Although resources live in a flat collection rather than nested paths, mutations ripple across entity boundaries, and the server performs those ripples automatically — no client ever issues a separate request against the affected resource. A rodeo posture change can cancel or refund entries, release draw assignments, free drawn animals, disburse payouts, and settle contracts. Verifying a single result completes a draw assignment, advances an animal's welfare counter, and can bubble an entry to completion. Suspending a contestant, terminating a stock contract, or filing an injury report each sets off its own documented cascade in §3.

Two bookkeeping rules hold everywhere. First, every resource touched by a cascade has its `updated_at` refreshed and — where the resource carries one — its `version` incremented. Second, a stored payout reflects exactly the inputs present at computation time: any refund, verification, or amendment that lands afterward leaves the event's payout stale until it is recomputed (§3.7). Stale payouts are never patched in place behind the scenes.

For request validation, resources are addressed in a fixed order: identifiers in the URL path are resolved left to right, and only then are foreign keys in the request body checked. The first missing reference — path or body — produces the `ERR_NOT_FOUND` (HTTP 404) rejection.

### 2.8. Validation Order

When several checks could reject the same request, the server evaluates them in a fixed order and surfaces the earliest failure. The order is:

1. Authentication — headers present and role recognized (`ERR_UNAUTHENTICATED`).
2. Authorization and ownership — role permitted for the endpoint and action, a `Contestant` acting only on their own entries, a result's judge identity matching the caller (`ERR_FORBIDDEN`).
3. Path existence — every path identifier exists, checked left to right (`ERR_NOT_FOUND`).
4. Body foreign-key existence — referenced `contestant_id`, `rodeo_event_id`, `contract_id`, `judge_id`, `performance_id`, `draw_assignment_id`, `animal_id`, and `vet_report_id` values exist (`ERR_NOT_FOUND`).
5. Field shape — enum membership, numeric ranges, `ends_at` later than `starts_at`, legal vet-report subject/disposition pairing, barrier assignments held by gold-card judges (`ERR_VALIDATION`).
6. State-machine legality — the requested transition action is valid from the resource's current state, including the lockdown of terminal states (`ERR_INVALID_STATE`).
7. Rodeo posture gate — entries and re-entries require `ENTRIES_OPEN`; draws require `DRAW_LOCKED` or `IN_PROGRESS`; result recording requires `IN_PROGRESS`; payout finalization requires `COMPLETED` (`ERR_RODEO_NOT_OPEN`).
8. Entry window — the logical clock reads earlier than `entries_close_at` (`ERR_ENTRY_WINDOW_CLOSED`).
9. Contestant standing — the contestant is in `GOOD_STANDING` (`ERR_CONTESTANT_SUSPENDED`).
10. Animal eligibility for stock selection — the animal is `AVAILABLE`, under the welfare-out limit, and slated for the matching event (`ERR_ANIMAL_NOT_ELIGIBLE`).
11. Contract activity — the animal's stock contract is `ACTIVE` (`ERR_CONTRACT_NOT_ACTIVE`); and, for medical turn-outs, the vet-report linkage is satisfied (`ERR_MEDICAL_RELEASE_REQUIRED`).
12. Uniqueness — card numbers globally unique (`ERR_DUPLICATE_CARD`), animal tags unique within a contract (`ERR_DUPLICATE_TAG`).
13. Duplicate entry — no second non-terminal entry for the same contestant and event (`ERR_DUPLICATE_ENTRY`).
14. Scheduling and scoring conflicts — performance overlap (`ERR_PERFORMANCE_OVERLAP`), judge buffered conflict (`ERR_JUDGE_CONFLICT`), judge assigned to the result's performance (`ERR_JUDGE_NOT_ASSIGNED`), one live result per assignment (`ERR_DUPLICATE_RESULT`), discipline-correct score/time payload (`ERR_SCORE_OUT_OF_RANGE`).
15. Draw integrity — go-round number and ordering (`ERR_GO_ROUND_INVALID`), re-draw after verification (`ERR_RESULTS_EXIST`), enough eligible stock for an atomic draw (`ERR_INSUFFICIENT_STOCK`).
16. Production guards — performance cancellation blocked by live assignments (`ERR_PERF_HAS_ASSIGNMENTS`), rodeo completion blocked by unverified results (`ERR_RESULTS_PENDING`), settlement blocked by unfinalized payouts (`ERR_PAYOUT_NOT_FINAL`).
17. Fiscal checks — ticket capacity (`ERR_CAPACITY_EXCEEDED`).
18. Concurrency — the stale-version check on draw execution, always last (`ERR_STALE_VERSION`).

A concrete consequence: a draw request carrying both an out-of-range go-round number and a stale event version is rejected with `ERR_GO_ROUND_INVALID`, because draw integrity is evaluated before concurrency.

### 2.9. Optimistic Concurrency Control

Exactly one endpoint participates in optimistic concurrency control: executing the draw for a go-round of an event. That request must carry `expected_rodeo_event_version` holding the event's `version` as the client last observed it. If the event's current `version` has advanced past that value, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). The guard exists because a draw legitimately supersedes the previous draw of the same go-round, releasing its pending assignments and freeing its animals — a writer holding a stale version would otherwise silently wipe assignments created after its last read. No other endpoint accepts a version field: requests to any other resource proceed without an expected-version input.

## 3. Business Logic & Workflows

### 3.1. Building the Production: Rodeos, Events, and Performances

A new production begins when a `CommitteeAdmin` creates a rodeo with a `name`, a host `city`, and the `entries_close_at` deadline. The rodeo opens in `DRAFT` posture with `unclaimed_purse_cents` at zero. Over its life the `posture` field walks `DRAFT` → `ENTRIES_OPEN` → `DRAW_LOCKED` → `IN_PROGRESS` → `COMPLETED` → `SETTLED`, with `CANCELLED` reachable as an alternate ending; `SETTLED` and `CANCELLED` are terminal, and any transition attempted from a terminal state is rejected with `ERR_INVALID_STATE`.

Within the rodeo the committee adds one competition event per call, in a payload carrying `rodeo_id`, `event_code`, `go_rounds`, `entry_fee_cents`, `added_money_cents`, `per_performance_slots`, and `payout_places`. The `event_code` is one of `BAREBACK`, `SADDLE_BRONC`, `BULL_RIDING`, `TIE_DOWN_ROPING`, `STEER_WRESTLING`, `TEAM_ROPING`, or `BARREL_RACING`, and the server derives `discipline` from it: `ROUGH_STOCK` for the three riding events (`BAREBACK`, `SADDLE_BRONC`, `BULL_RIDING`) and `TIMED` for the remaining four. An event runs between one and three go-rounds inclusive (`go_rounds`), charges a gross entry fee of at least 1,000 cents (`entry_fee_cents`), may carry committee added money of zero or more cents (`added_money_cents`), slots at least one contestant per performance (`per_performance_slots`), and pays between one and four places inclusive per go-round and per average (`payout_places`). Its `drawn_rounds` list — the go-round numbers whose draw has been executed — starts empty. A value outside any of these shapes is rejected with `ERR_VALIDATION`.

Performances are scheduled with `rodeo_id`, a human `label` such as "Friday Night", an `arena` identifier, a `starts_at` and `ends_at`, and an `arena_capacity` of at least one seat. The end of a performance must be strictly later than its start, otherwise `ERR_VALIDATION`. A new performance is `SCHEDULED` with `sold_tickets` at zero; its other states are `COMPLETED` and `CANCELLED`, both terminal. Two performances of the same rodeo in the same arena may not overlap while `SCHEDULED`: each occupies a half-open interval that includes its `starts_at` instant and excludes its `ends_at` instant, so back-to-back performances — one ending exactly when the next begins — are permitted, while any true intersection is rejected with `ERR_PERFORMANCE_OVERLAP`.

With at least one event and at least one performance in place, a `CommitteeAdmin` opens entries by driving the rodeo's posture transition with an `action` of `OPEN_ENTRIES`, moving `DRAFT` → `ENTRIES_OPEN`; without both an event and a performance the attempt is rejected. The same transition capability carries every later posture change — `LOCK_DRAW`, `UNLOCK_DRAW`, `START_RODEO`, `COMPLETE_RODEO`, `SETTLE_RODEO`, and `CANCEL_RODEO` — and each successful posture transition increments the rodeo's `version`.

Cancelling the rodeo is permitted from `DRAFT`, `ENTRIES_OPEN`, or `DRAW_LOCKED`. The cascade is identical from all three: every entry not yet in a terminal state is cancelled with a full refund, every `PENDING` draw assignment is released, and every `DRAWN` animal returns to `AVAILABLE`.

### 3.2. Contestants, Entries, and the Fee Ledger

A `CommitteeAdmin` or an `EntryOffice` clerk registers a contestant with a `card_number` — the PRCA card, unique across all contestants, with duplicates rejected as `ERR_DUPLICATE_CARD` — and a `full_name`. Contestants begin in `GOOD_STANDING`; the only other standing is `SUSPENDED`.

Entering a contestant into an event is the central office's bread and butter, and a contestant may also enter themself. The payload carries `contestant_id` and `rodeo_event_id`; when the caller's role is `Contestant`, the `contestant_id` must equal their `X-User-ID`, otherwise `ERR_FORBIDDEN`. Four gates guard creation, evaluated in this order: the rodeo must be in `ENTRIES_OPEN` posture (`ERR_RODEO_NOT_OPEN`); the logical clock must read strictly earlier than the rodeo's `entries_close_at` — a clock at or past the deadline closes the window (`ERR_ENTRY_WINDOW_CLOSED`); the contestant must be in `GOOD_STANDING` (`ERR_CONTESTANT_SUSPENDED`); and the contestant must not already hold a non-terminal entry for the same event, where non-terminal means `ENTERED`, `WAITLISTED`, or `DRAWN` (`ERR_DUPLICATE_ENTRY`).

On acceptance, the entry's `entry_fee_cents` is copied from the event's fee at that moment, and the fee split is computed immediately: a flat 600-cent `sanction_fee_cents`, a `committee_retention_cents` equal to twelve percent of the fee rounded half-up to whole cents, and a `purse_contribution_cents` equal to the fee minus the retention minus the sanction. Rounding follows the per-entry rule of §2.6. These three fields always reflect the most recent charge, while two running totals — `fee_charges_cents` and `contribution_charges_cents` — accumulate the gross fee and the purse contribution across every charge the entry ever incurs, and `refunded_cents` and `refunded_contribution_cents` accumulate everything returned. The event's purse grows by each new contribution as it lands.

An entry begins `ENTERED`, and its possible states are `ENTERED`, `WAITLISTED`, `DRAWN`, `TURNED_OUT`, `DRAWN_OUT`, `CANCELLED`, and `COMPETED`, the last three being terminal. The draw (§3.5) moves an entry `ENTERED` → `DRAWN` when it slots the entry, or `ENTERED` → `WAITLISTED` when no performance slot is free.

Cancelling an entry (`CANCEL_ENTRY`, available to `EntryOffice` or the contestant themself from `ENTERED`) refunds the purse contribution and the committee retention but keeps the sanction fee: `refunded_cents` grows by the contribution plus the retention, `refunded_contribution_cents` grows by the contribution alone, and the event's purse is recomputed downward.

A drawn contestant may turn out — `TURN_OUT` from `DRAWN`, carrying a `reason` of `VOLUNTARY` or `MEDICAL` — only while the rodeo is `DRAW_LOCKED` or `IN_PROGRESS` (`ERR_RODEO_NOT_OPEN` otherwise). A medical turn-out must name a `vet_report_id` referencing a vet report whose `disposition` is `INJURED_TURNOUT`; without that linkage the request fails with `ERR_MEDICAL_RELEASE_REQUIRED`. The two reasons diverge on money. A voluntary turn-out forfeits the entire fee to the purse — nothing is refunded. A medical turn-out refunds the purse contribution: `refunded_cents` and `refunded_contribution_cents` each grow by the contribution, and the purse shrinks accordingly. In both cases the entry's `PENDING` draw assignments are released, any drawn animals return from `DRAWN` to `AVAILABLE`, and `turn_out_reason` records the cause on the entry.

Re-entry reverses the waystation. Through the `RE_ENTER` action, a `TURNED_OUT` entry returns to `ENTERED` under the same three gates as initial creation — `ENTRIES_OPEN` posture (`ERR_RODEO_NOT_OPEN`), a logical clock earlier than `entries_close_at` (`ERR_ENTRY_WINDOW_CLOSED`), and a contestant in `GOOD_STANDING` (`ERR_CONTESTANT_SUSPENDED`). The split is recomputed from the event's current `entry_fee_cents`, the new fee adds onto `fee_charges_cents`, the new contribution onto `contribution_charges_cents`, both `turn_out_reason` and `vet_report_id` are cleared, and the purse grows by the new contribution. Because a voluntary turn-out forfeited the first fee, a contestant who turns out and re-enters legitimately contributes to the purse twice — this is intended behavior, not an accounting error.

`DRAW_OUT`, restricted to a `CommitteeAdmin` and valid from `DRAWN`, is the full-refund removal: `refunded_cents` grows by the entire fee including the sanction, `refunded_contribution_cents` grows by the contribution, pending assignments are released with their animals freed, and the purse is recomputed.

Suspension is the disciplinary lever. A `CommitteeAdmin` patches a contestant's `status` to `SUSPENDED`, and the cascade runs immediately: the contestant's `ENTERED` entries are cancelled with a full refund including the sanction; their `WAITLISTED` entries are cancelled on the same terms; and their `DRAWN` entries become `DRAWN_OUT` with the same full refund, their pending assignments released and their drawn animals returned to `AVAILABLE`. Event purses are recomputed as `refunded_contribution_cents` rises, and any stored payout for those events is stale until recomputed. Patching the contestant back to `GOOD_STANDING` restores eligibility for future entries but does not undo any prior cancellation or draw-out. Either patch increments the contestant's `version`.

One last entry motion is driven entirely by results: when every go-round assignment of a `DRAWN` entry reaches `COMPLETED`, the entry bubbles up to `COMPETED`; and if a verified result belonging to that entry is later amended, the entry reopens from `COMPETED` back to `DRAWN` (§3.4).

### 3.3. Stock Contracts, Animals, and Veterinary Care

A stock contractor agreement is created with `rodeo_id`, a `contractor_name`, and its two fee bases — `day_rate_cents` (the per-performance-day fee) and `per_out_fee_cents` (the fee per completed animal out), each zero or more. The contract begins `PROPOSED` and can be activated (`ACTIVATE`: `PROPOSED` → `ACTIVE`) only while the rodeo is `DRAFT` or `ENTRIES_OPEN`. Its settlement figures — `day_rate_total_cents`, `per_out_total_cents`, `settlement_cents`, and `settlement_basis` — remain at their zero and null defaults until the rodeo settles (§3.7); `settlement_basis` will then read `DAY_RATE` or `PER_OUT`. A contract's terminal states are `SETTLED` and `TERMINATED`.

Animals are registered under a contract via `contract_id`, with a `tag_number` unique within that contract (`ERR_DUPLICATE_TAG` on collision) and the `event_code` the animal is slated for, drawn from the same seven-value event enum as the events themselves. Each animal starts `AVAILABLE` with a `welfare_out_count` of zero. That counter is not merely informational: it always equals the number of verified, non-voided results naming the animal, and it gates both draw eligibility (§3.5) and retirement. An animal's states are `AVAILABLE`, `DRAWN`, `COMPETED`, `INJURED`, and `RETIRED`, the last being terminal.

The welfare threshold is three outs. Each verified result naming the animal moves it `DRAWN` → `COMPETED` and increments `welfare_out_count`; if the count has reached three — the boundary is inclusive, so exactly three retires — the animal immediately auto-retires (`COMPETED` → `RETIRED`), otherwise it auto-releases back to the pen (`COMPETED` → `AVAILABLE`). Amending a verified result compensates: the count decrements and the animal returns to `DRAWN`, even if it had already auto-retired.

Veterinary reports are filed by a `Veterinarian` and drive the injury protocol. The payload carries a `subject_type` of `ANIMAL` or `CONTESTANT`; an animal report requires `animal_id` and leaves the contestant reference null, while a contestant report requires `contestant_id` and leaves the animal reference null. An optional `performance_id` supplies context, `findings` holds the free-text veterinary observations, and `veterinarian_name` records the attending veterinarian. The `disposition` is `CLEARED`, `INJURED_TURNOUT`, or `RETIRED` — with one hard pairing rule: a `CONTESTANT` report may carry only `INJURED_TURNOUT`, and any other subject/disposition combination is rejected with `ERR_VALIDATION`. Recall from §2.5 that a filed report is immutable, addressed later by its `report_id`.

Filing `INJURED_TURNOUT` on an `AVAILABLE` or `COMPETED` animal simply moves it to `INJURED`. Filing it on a `DRAWN` animal runs a deeper cascade: every `PENDING` draw assignment naming the animal is released, the entries behind those assignments become `TURNED_OUT` with a `MEDICAL` reason — the purse contribution refunded and `vet_report_id` set to the new report — and the affected purses are recomputed, leaving any stored payout stale. A `CLEARED` disposition returns an `INJURED` animal to `AVAILABLE`; clearing is valid only from `INJURED`, and any other source state is rejected with `ERR_INVALID_STATE`. A `RETIRED` disposition retires the animal outright from `AVAILABLE`, `INJURED`, or `DRAWN`; from `DRAWN` the same entry-release cascade as an injury applies — pending assignments released, entries turned out medically with contribution refunds, purses recomputed.

Terminating a contract (`TERMINATE`, from `ACTIVE`) pulls the contractor's herd mid-production. Its `AVAILABLE` animals become `RETIRED`. For each of its `DRAWN` animals, the pending assignments are released, the affected entries become `DRAWN_OUT` with a full refund, and only then does the animal retire. Its `INJURED` animals retire as well. Purses of the affected events are recomputed against the refunded entries. A contract reaches `SETTLED` only as part of rodeo settlement, never by direct call.

### 3.4. Judges, Assignments, and Results

A judge is registered with a globally unique `card_number` (`ERR_DUPLICATE_CARD` on collision), a `full_name`, and a `certification` of `PRCA_CARD` or `PRCA_GOLD`. Assigning a judge to a performance takes `judge_id`, `performance_id`, and a `position` — `ARENA_1`, `ARENA_2`, `BARRIER`, or `TIMER`. The barrier position demands the gold card: a `BARRIER` assignment for a judge whose certification is not `PRCA_GOLD` is rejected with `ERR_VALIDATION`. Assignments also respect a buffered conflict rule: each assignment occupies a window running from 45 minutes before its performance's `starts_at` to 45 minutes after its `ends_at`, including the start of that window and excluding its end, and a new assignment whose buffered window intersects another buffered window of the same judge is rejected with `ERR_JUDGE_CONFLICT`. Assignments are addressable individually by `assignment_id` and listable by judge or performance.

Only a `Judge` records results, and only for outs in performances they are assigned to. The submission names a `draw_assignment_id`; the server stamps the result's `judge_id` from the caller's `X-User-ID`, so a caller whose role is not `Judge` never reaches the scoring logic (`ERR_FORBIDDEN`), and an acting judge who holds no assignment for the result's performance is rejected with `ERR_JUDGE_NOT_ASSIGNED`. Results may be recorded only while the rodeo is `IN_PROGRESS` (`ERR_RODEO_NOT_OPEN`).

The scoring payload is discipline-specific. A rough-stock out takes `judge_1_score` and `judge_2_score`, each an integer from 0 to 50 inclusive, and must not carry `raw_time_ms`. A timed out takes `raw_time_ms` of zero or more milliseconds and must not carry judge scores. Sending scores on a timed event, time on a rough-stock event, or a score outside its range is rejected with `ERR_SCORE_OUT_OF_RANGE`. Two optional inputs complete the payload: `penalty_ms`, zero or more, defaults to 0, and `disqualified_flag`, which defaults to false; `qualified_flag` tells the server the judges marked the ride or run qualified. An assignment may hold at most one live result — a second submission while a non-voided result exists for the same `draw_assignment_id` is rejected with `ERR_DUPLICATE_RESULT`. The stored result also carries `entry_id` and `rodeo_event_id`, denormalized from its assignment for querying.

From the inputs the server computes the outcome fields. For rough stock, `total_score` is the sum of the two judge scores — a value from 0 to 100. For timed events, `total_time_ms` is the raw time plus the penalty. The `outcome` derives from the flags in a fixed order: `DISQUALIFIED` whenever `disqualified_flag` is set; otherwise `QUALIFIED` when `qualified_flag` is set; otherwise `NO_SCORE` for rough stock or `NO_TIME` for timed events. A fresh result is `RECORDED`; its other states are `VERIFIED`, `AMENDED`, and `VOIDED`, the last being terminal.

Verification (`VERIFY`, a `CommitteeAdmin` action requiring the rodeo `IN_PROGRESS`) stamps `verified_at` on the result and fires the forward cascade. The assignment moves `PENDING` → `COMPLETED`. A rough-stock animal named by the assignment moves `DRAWN` → `COMPETED`, its welfare counter increments, and it immediately auto-releases or auto-retires per the three-out rule of §3.3. The entry then bubbles from `DRAWN` to `COMPETED` once all of its go-round assignments have completed. Any stored payout for the event is stale from the moment of verification until recomputed. Verifying an `AMENDED` result runs the identical cascade, and `verified_at` always reflects the latest verification.

Amendment is the judge's correction path and runs as compensation. From `VERIFIED`, the acting judge may amend the result addressed by `result_id` — but only while the rodeo is still `IN_PROGRESS`, because results freeze when the rodeo completes, and only if that judge holds an assignment for the result's performance (`ERR_JUDGE_NOT_ASSIGNED`). The request carries an `amendment_reason` plus any corrected scoring fields — `judge_1_score`, `judge_2_score`, `raw_time_ms`, `penalty_ms`, `qualified_flag`, `disqualified_flag` — which must satisfy the same discipline rules as an initial submission (`ERR_SCORE_OUT_OF_RANGE`). The amendment unwinds the verification: the assignment drops back `COMPLETED` → `PENDING`, the animal's welfare counter decrements and the animal returns to `DRAWN` from `COMPETED` or `RETIRED`, a completed entry reopens to `DRAWN`, and the corrected fields and reason are stored with the result now in `AMENDED`.

Voiding (`VOID`, a `CommitteeAdmin` action) sends a `RECORDED` or `AMENDED` result to `VOIDED`. The assignment stays `PENDING` in both cases, so a fresh result may be recorded for the out afterward. Every verify, amend, or void increments the result's `version`.

### 3.5. The Draw

Draws run only while the rodeo is `DRAW_LOCKED` or `IN_PROGRESS` (`ERR_RODEO_NOT_OPEN` otherwise). Locking the draw — `LOCK_DRAW`, moving `ENTRIES_OPEN` → `DRAW_LOCKED` — has no preconditions. Starting the rodeo — `START_RODEO`, moving `DRAW_LOCKED` → `IN_PROGRESS` — requires every event of the rodeo to have go-round 1 present in its `drawn_rounds`.

A `CommitteeAdmin` executes the draw for one go-round of the event addressed as `event_id`, supplying `go_round_number` together with `expected_rodeo_event_version`; per §2.9, a version that no longer matches the event's current `version` is rejected with `ERR_STALE_VERSION`. Two parameter rules guard the go-round itself, evaluated before the version check: `go_round_number` must lie between 1 and the event's `go_rounds` inclusive, and go-round G may be drawn only after go-round G−1 already appears in `drawn_rounds` — violations of either are rejected with `ERR_GO_ROUND_INVALID`. Separately, re-drawing a go-round that already has verified results is rejected with `ERR_RESULTS_EXIST`.

The draw takes the event's `ENTERED` entries, ordered by entry `created_at` ascending with ties broken by the contestant's `card_number` ascending, and slots them round-robin into the rodeo's `SCHEDULED` performances taken in `starts_at` ascending order, never exceeding `per_performance_slots` in any one performance. Each slotted entry receives a draw assignment in `PENDING` status carrying the `go_round_number`, the `performance_id`, the event denormalized as `rodeo_event_id` for queries, and a 1-based `draw_position` giving the run order within that performance for this event and go-round — and the entry itself moves `ENTERED` → `DRAWN`. A draw assignment's states are `PENDING`, `COMPLETED`, and `RELEASED`, the latter two terminal; an assignment reaches `RELEASED` whenever the slot it held is unwound — by turn-out, re-draw supersede, draw unlock, suspension, contract termination, or a vet injury or retirement — and its assigned animal returns `DRAWN` → `AVAILABLE`.

For a rough-stock event the draw also pairs each slotted entry with an animal, one-to-one in draw order. Eligible animals are `AVAILABLE`, carry a `welfare_out_count` below three, belong to a contract in `ACTIVE` status, and match the event's `event_code`; the pool is taken in `tag_number` ascending order. Each chosen animal moves `AVAILABLE` → `DRAWN` and its id is recorded on the assignment's `animal_id` (which stays null for `TIMED` events). If the eligible pool cannot cover every assigned entry, the entire draw is rejected with `ERR_INSUFFICIENT_STOCK` — draws are atomic and never partial. The same animal gates apply whenever stock is selected: an ineligible animal (`ERR_ANIMAL_NOT_ELIGIBLE`) or a contract that is not active (`ERR_CONTRACT_NOT_ACTIVE`) blocks the selection.

Entries for which no performance slot is free in the first go-round overflow to `WAITLISTED`. A successful draw reports `assigned_count`, `waitlisted_count`, and the `go_round_number`, records the go-round in `drawn_rounds`, and increments the event's `version`. When a later re-draw runs with freed capacity, a waitlisted entry may be slotted after all — its assignment is created and it moves `WAITLISTED` → `DRAWN`, with an animal drawn for rough stock exactly as above.

Executing a draw for a go-round that was already drawn — and still has no verified results — supersedes the earlier draw: that go-round's prior `PENDING` assignments are released, their animals freed back to `AVAILABLE`, and its waitlisted entries returned to `ENTERED`, all before the new draw is built. Unlocking the draw (`UNLOCK_DRAW`, moving `DRAW_LOCKED` → `ENTRIES_OPEN`) wipes the draw rodeo-wide: every `PENDING` assignment of the rodeo's events is released with the drawn animals returned to `AVAILABLE`, `WAITLISTED` entries and `DRAWN` entries alike revert to `ENTERED`, and `drawn_rounds` is cleared on every event of the rodeo — so a later lock and draw rebuilds everything from scratch.

A re-ride is the surgical exception to redrawing. A `CommitteeAdmin` may swap the animal on a `PENDING` rough-stock assignment by naming a new `animal_id`: the old animal returns `DRAWN` → `AVAILABLE`, the new animal moves `AVAILABLE` → `DRAWN`, and the assignment keeps its status and position. The usual stock gates apply — `ERR_ANIMAL_NOT_ELIGIBLE` for an ineligible pick and `ERR_CONTRACT_NOT_ACTIVE` when the new animal's contract is not active — and the assignment's `version` increments.

### 3.6. Ticketing and Performance Operations

The `BoxOffice` sells seats against a performance with a payload of `performance_id`, `section`, `quantity` (at least one), and `unit_price_cents` (zero or more). The order's `total_cents` is the quantity multiplied by the unit price, the order starts `PAID`, and the performance's `sold_tickets` rises immediately by the quantity. Capacity is enforced at sale time: the seats already sold — the sum of `quantity` over that performance's `PAID` orders — plus the requested quantity must not exceed `arena_capacity`. An order that brings the total exactly to capacity succeeds; one seat beyond capacity is rejected with `ERR_CAPACITY_EXCEEDED`.

Refunds unwind a sale. A `BoxOffice` refund of the order addressed by `order_id` moves it `PAID` → `REFUNDED` — the order's terminal state — and subtracts its quantity from the performance's `sold_tickets`. The same refund runs automatically when a performance is cancelled.

Two transitions close out a performance. Completing it (`COMPLETE_PERFORMANCE`: `SCHEDULED` → `COMPLETED`) requires the rodeo to be `IN_PROGRESS`. Cancelling it (`CANCEL_PERFORMANCE`: `SCHEDULED` → `CANCELLED`) is blocked while any draw assignment in `PENDING` or `COMPLETED` status references the performance (`ERR_PERF_HAS_ASSIGNMENTS`); when the cancel does succeed, every `PAID` ticket order for that performance is refunded and `sold_tickets` is recomputed.

### 3.7. Purse Accounting, Payouts, and Settlement

Once the last performance ends, the committee completes the rodeo (`COMPLETE_RODEO`: `IN_PROGRESS` → `COMPLETED`). Completion demands two things: every performance of the rodeo is `COMPLETED` or `CANCELLED`, and no result belonging to the rodeo's entries remains in `RECORDED` or `AMENDED` status — a straggler rejects the transition with `ERR_RESULTS_PENDING`.

Each event has exactly one payout record. Its purse — `purse_cents` — is the event's `added_money_cents` plus, summed over all of the event's entries regardless of their status, each entry's `contribution_charges_cents` minus its `refunded_contribution_cents`. Refunded money nets out of the purse precisely because refund bookkeeping has already run on the entries; that is also why a refund landing after a computation leaves the stored payout stale until recomputed.

A `CommitteeAdmin` computes or refreshes the payout by naming `rodeo_event_id` and a `variant` of `PROVISIONAL` or `FINAL`. The two variants differ only in which results feed the ranking: the provisional variant includes results in `RECORDED` or `VERIFIED` status, while the final variant ranks `VERIFIED` results only — so identical underlying data with a single unverified recorded result produces different place lines under the two variants. The variant used is recorded in `computed_variant`; every payout before finalization is in `PROVISIONAL` status, and computing with the provisional variant is what refreshes a payout during the rodeo.

Pool construction pins where every cent lands. Thirty percent of the purse is conceptually reserved for the average. Each go-round's pool is the purse multiplied by seventy percent and divided by the event's number of go-rounds, rounded half-up to whole cents; the pools are recorded in `go_round_pools` as one `go_round` / `pool_cents` pair per go-round. A go-round with zero qualified ranked contestants is empty, and its pool rolls into the average: `average_pool_cents` is the purse minus the sum of the non-empty go-round pools, so every residual cent lands in the average. If the average itself ends with zero eligible contestants, the entire purse rolls to the rodeo's `unclaimed_purse_cents` when the rodeo settles.

Places paid per pool equal the event's `payout_places`. For one place the pool pays 100 percent; for two places, 60 and 40 percent; for three, 50, 30, and 20 percent; for four, 40, 30, 20, and 10 percent. Every place before the last receives its percentage of the pool, rounded half-up to whole cents; the last place receives whatever remains of the pool after the earlier places are paid. Ranking uses only `QUALIFIED` results: rough stock ranks by `total_score` descending, timed events by `total_time_ms` ascending. Go-round scope ranks that go-round's results; the average scope ranks per-contestant aggregates. The payout's `place_lines` carries one row per paid place, each with `scope` (`GO_ROUND_n` for a go-round or `AVERAGE`), `place`, `contestant_id`, `amount_cents`, and `tied_count`.

Eligibility for the average is strict: a contestant must hold a qualified in-scope result in every go-round from 1 through the event's `go_rounds`. The aggregate is the sum of `total_score` across the go-rounds for rough stock, ranked descending, or the sum of `total_time_ms` across the go-rounds for timed events, ranked ascending. Ties in the aggregate are ties for placing and split exactly as go-round ties do.

Tie-splitting follows one rule everywhere. When m contestants tie at place k — covering m consecutive places — they split the combined amount of places k through k+m−1 equally: each tied contestant receives the combined sum divided by m, rounded half-up to whole cents, and the leftover cents (the combined sum minus m times that share) go to the tied contestant whose result was verified earliest by `verified_at`, with a tie on that instant broken by the result's `created_at` ascending — never by any resource identifier.

Finalizing the payout addressed by `payout_id` (`FINALIZE`) requires the rodeo to be `COMPLETED` (`ERR_RODEO_NOT_OPEN` otherwise); finalization recomputes the payout under the final variant — verified results only — and moves it `PROVISIONAL` → `FINAL`. Settlement (`SETTLE_RODEO`: `COMPLETED` → `SETTLED`) then requires every event of the rodeo to hold a payout in `FINAL` status, rejecting with `ERR_PAYOUT_NOT_FINAL` while any event's payout is missing or merely provisional. Settlement disburses: every final payout becomes `DISBURSED` (its terminal state), every `ACTIVE` stock contract moves to `SETTLED` with its settlement figures computed and stored, and each event whose average had zero eligible contestants adds its `average_pool_cents` to the rodeo's `unclaimed_purse_cents`.

Contractor settlement always computes both fee bases and lets the larger win. Performance days are counted as the distinct UTC calendar dates among the rodeo's performances that stand in `SCHEDULED` or `COMPLETED` status at settle time, and `day_rate_total_cents` is the contract's `day_rate_cents` multiplied by that day count. In parallel, outs are counted as the `COMPLETED` draw assignments whose animal belongs to the contract, and `per_out_total_cents` is the contract's `per_out_fee_cents` multiplied by those outs. The `settlement_cents` paid is the larger of the two totals, and `settlement_basis` records which basis won: `DAY_RATE` whenever the day-rate total is at least the per-out total — a tie pays the day rate — otherwise `PER_OUT`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — posture and status transitions of every kind, the draw, payout computation and finalization, re-rides, contestant status updates, and the clock — return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/_clock/set_current_utc` | Set the logical clock | CommitteeAdmin |
| POST | `/api/rodeos` | Create a rodeo (posture DRAFT) | CommitteeAdmin |
| GET | `/api/rodeos/{rodeo_id}` | Get a rodeo | Any |
| POST | `/api/rodeos/{rodeo_id}/transition` | Drive a rodeo posture transition | CommitteeAdmin |
| POST | `/api/rodeo-events` | Add a competition event to a rodeo | CommitteeAdmin |
| GET | `/api/rodeo-events` | List events | Any |
| GET | `/api/rodeo-events/{event_id}` | Get an event | Any |
| POST | `/api/rodeo-events/{event_id}/draws` | Execute or supersede the draw for one go-round | CommitteeAdmin |
| POST | `/api/performances` | Schedule a performance | CommitteeAdmin |
| GET | `/api/performances` | List performances | Any |
| GET | `/api/performances/{performance_id}` | Get a performance | Any |
| POST | `/api/performances/{performance_id}/transition` | Complete or cancel a performance | CommitteeAdmin |
| POST | `/api/contestants` | Register a contestant | CommitteeAdmin, EntryOffice |
| GET | `/api/contestants` | List contestants | Any |
| GET | `/api/contestants/{contestant_id}` | Get a contestant | Any |
| PATCH | `/api/contestants/{contestant_id}` | Update contestant standing (suspension cascades) | CommitteeAdmin |
| POST | `/api/stock-contracts` | Create a stock contractor agreement | CommitteeAdmin |
| GET | `/api/stock-contracts` | List stock contracts | Any |
| GET | `/api/stock-contracts/{contract_id}` | Get a stock contract | Any |
| POST | `/api/stock-contracts/{contract_id}/transition` | Activate or terminate a contract | CommitteeAdmin |
| POST | `/api/stock-animals` | Register an animal under a contract | CommitteeAdmin |
| GET | `/api/stock-animals` | List animals | Any |
| GET | `/api/stock-animals/{animal_id}` | Get an animal | Any |
| POST | `/api/judges` | Register a judge | CommitteeAdmin |
| GET | `/api/judges` | List judges | Any |
| GET | `/api/judges/{judge_id}` | Get a judge | Any |
| POST | `/api/judge-assignments` | Assign a judge to a performance | CommitteeAdmin |
| GET | `/api/judge-assignments` | List judge assignments | Any |
| GET | `/api/judge-assignments/{assignment_id}` | Get a judge assignment | Any |
| POST | `/api/entries` | Enter a contestant into an event | EntryOffice, Contestant |
| GET | `/api/entries` | List entries | Any |
| GET | `/api/entries/{entry_id}` | Get an entry | Any |
| POST | `/api/entries/{entry_id}/transition` | Cancel, turn out, re-enter, or draw out an entry | CommitteeAdmin, EntryOffice, Contestant |
| GET | `/api/draw-assignments` | List draw assignments | Any |
| GET | `/api/draw-assignments/{draw_assignment_id}` | Get a draw assignment | Any |
| POST | `/api/draw-assignments/{draw_assignment_id}/reride` | Swap the animal on a pending rough-stock assignment | CommitteeAdmin |
| POST | `/api/run-results` | Record a score or time for an out | Judge |
| GET | `/api/run-results` | List results | Any |
| GET | `/api/run-results/{result_id}` | Get a result | Any |
| POST | `/api/run-results/{result_id}/transition` | Verify, amend, or void a result | CommitteeAdmin, Judge |
| POST | `/api/payouts/compute` | Compute or refresh an event's payout under a variant | CommitteeAdmin |
| GET | `/api/payouts` | List payouts | Any |
| GET | `/api/payouts/{payout_id}` | Get a payout | Any |
| POST | `/api/payouts/{payout_id}/transition` | Finalize a payout | CommitteeAdmin |
| POST | `/api/vet-reports` | File a veterinary report | Veterinarian |
| GET | `/api/vet-reports` | List vet reports | Any |
| GET | `/api/vet-reports/{report_id}` | Get a vet report | Any |
| POST | `/api/ticket-orders` | Sell tickets for a performance | BoxOffice |
| GET | `/api/ticket-orders` | List ticket orders | Any |
| GET | `/api/ticket-orders/{order_id}` | Get a ticket order | Any |
| POST | `/api/ticket-orders/{order_id}/transition` | Refund a paid order | BoxOffice |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_RODEO_NOT_OPEN` | 409 Conflict |
| `ERR_ENTRY_WINDOW_CLOSED` | 409 Conflict |
| `ERR_CONTESTANT_SUSPENDED` | 409 Conflict |
| `ERR_DUPLICATE_CARD` | 409 Conflict |
| `ERR_DUPLICATE_TAG` | 409 Conflict |
| `ERR_DUPLICATE_ENTRY` | 409 Conflict |
| `ERR_MEDICAL_RELEASE_REQUIRED` | 409 Conflict |
| `ERR_PERFORMANCE_OVERLAP` | 409 Conflict |
| `ERR_JUDGE_CONFLICT` | 409 Conflict |
| `ERR_JUDGE_NOT_ASSIGNED` | 409 Conflict |
| `ERR_DUPLICATE_RESULT` | 409 Conflict |
| `ERR_SCORE_OUT_OF_RANGE` | 400 Bad Request |
| `ERR_GO_ROUND_INVALID` | 422 Unprocessable Entity |
| `ERR_RESULTS_EXIST` | 409 Conflict |
| `ERR_INSUFFICIENT_STOCK` | 409 Conflict |
| `ERR_PERF_HAS_ASSIGNMENTS` | 409 Conflict |
| `ERR_RESULTS_PENDING` | 409 Conflict |
| `ERR_PAYOUT_NOT_FINAL` | 409 Conflict |
| `ERR_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_CONTRACT_NOT_ACTIVE` | 409 Conflict |
| `ERR_ANIMAL_NOT_ELIGIBLE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
