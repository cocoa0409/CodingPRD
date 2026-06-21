# Greek Recruitment API — Product Requirements Document

## 1. Introduction

College Greek recruitment — "Rush" in the vernacular of the sororities and fraternities that run it — is a tightly choreographed multi-party negotiation. A few hundred Potential New Members (PNMs) register on a campus's Panhellenic system, attend rounds of chapter-hosted parties, file mutual preference lists with the chapters they want to join, and on Bid Day discover whether a chapter has extended them an offer — a "bid" — to pledge. Behind the social ritual, the operational reality is unforgiving: chapters carry hard per-cycle quotas, alumna-family "legacy" status entitles certain PNMs to priority consideration, the campus risk-management office holds the authority to suspend a chapter mid-cycle over hazing or alcohol violations, and the dues a pledge owes are pinned to whatever the chapter charged the day the pledge accepted — not the day the chapter happened to revise its fee schedule.

This document specifies the REST API that drives that workflow end-to-end for a single Panhellenic/Interfraternity Council deployment. It models six interlocking entity families — chapters, PNMs, recruitment rounds, parties, party invitations, preferences, bid matches, dues-ledger entries, and risk incidents — and the validations and cascades that connect them. The system's defining responsibilities are four: enforcing chapter quotas against a derived pledge count that the mutual-selection matcher writes, gating party scheduling on a chapter's current risk posture so a suspended chapter cannot continue to host or accept bids, preserving a chronologically consistent dues ledger across both running per-entry balances and aggregate chapter-level balances, and providing the optimistic-concurrency guards that prevent two officers' stale views of a chapter from corrupting either the quota count or the dues balance. Where the social process is fluid, the API is strict.

The system is mounted at the URL prefix `/rush`. All paths in §4 are relative to that prefix.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every non-public request authenticates by carrying two HTTP headers: `X-User-ID`, the caller's identifier, and `X-User-Role`, the caller's role. A request with either header missing or malformed is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request that is authenticated but whose role is not authorized for the endpoint (per the §4 authorization column) is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes six roles, each spelled exactly as follows: `PanhellenicAdmin`, `RecruitmentChair`, `ChapterOfficer`, `RiskOfficer`, `PNM`, and `Anonymous`. The single endpoint that accepts `Anonymous` callers is PNM self-registration; everything else requires a real authenticated role.

Two of these roles are tied to a specific persisted entity, and the rest are operator/admin identities not tied to any row. When `X-User-Role` is `ChapterOfficer`, `X-User-ID` is the `id` of the acting `Chapter`; ownership checks on any resource that references a `Chapter` compare the resource's foreign-key field (for example, `Party.chapter_id` or `BidMatch.chapter_id`) to `X-User-ID`. When `X-User-Role` is `PNM`, `X-User-ID` is the `id` of the acting `PNM`; ownership checks on any resource that references a `PNM` (for example, `PartyInvitation.pnm_id` or `BidMatch.pnm_id`) compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `PanhellenicAdmin`, `RecruitmentChair`, `RiskOfficer`, or `Anonymous`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may log it but does not compare it to any entity's `id`.

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

Every list endpoint accepts two query-string parameters: `limit` and `offset`. The default `limit` is 10, the minimum is 1, and the maximum is 100; the default `offset` is 0. Lists are returned in `created_at` ascending order (with `created_at` ties broken by insertion order, never by `id`). The pagination block in `meta` reports `limit`, `offset`, `total_count` (the total number of rows matching the filter, ignoring the slice), and `has_more` (true when `offset + limit < total_count`).

### 2.4. Common Resource Properties and Resource Identity

Every persisted resource carries an `id` that is a server-minted UUID with no type prefix. Every resource also carries a `created_at` timestamp set at insertion. With one exception — `DuesLedgerEntry` — every resource additionally carries an `updated_at` timestamp refreshed on every mutation and a `version` integer initialized to 1 and incremented by exactly 1 on every mutation that changes the row. `DuesLedgerEntry` is an append-only ledger row; it carries only `id` and `created_at`, and has no `updated_at` and no `version`. Timestamps everywhere are emitted as ISO 8601 UTC strings with three fractional digits.

### 2.5. Optimistic Concurrency Control on Chapter

Two write paths that touch chapter quota are guarded by optimistic concurrency control, both gated on the parent `Chapter`'s `version`. The first guard sits on the manual / override bid-creation endpoint: the request body must carry `expected_chapter_version` set to whatever the client last observed as the chapter's `version`. If the chapter's current `version` does not equal that supplied value, the create is rejected with `ERR_STALE_VERSION` (HTTP 412). The motivating case is two strictly sequential creates both quoting the pre-bump version: another writer has already advanced the chapter's `version` by producing a bid that legitimately consumed the last quota slot, so the second writer's view of quota headroom is stale and would otherwise overrun the quota.

The second guard sits on the rescind operation for an already-accepted bid: the request body must again carry `expected_chapter_version`, and a mismatch with the chapter's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). Between the time the officer read the chapter and the time the rescind request lands, another writer may have legitimately accepted a different bid against the same chapter, bumping `Chapter.version` and altering `pledged_count`; rescinding off the stale view would corrupt the quota ledger, so the rescind is rejected. No other endpoint takes an `expected_chapter_version` field, and no other entity is the subject of an OCC guard.

### 2.6. Nested Resource Retrieval and Path Validation

The API exposes a number of nested reverse-lookup paths — invitations under a party, invitations under a PNM, parties under a chapter, parties under a round, preferences under a round, bid-matches under a round, dues-ledger entries under a chapter or a single bid, risk-incidents under a chapter or a party, the legacy roster under a chapter, and so on. Path parameters are validated left-to-right: the outermost id is resolved first and, if it does not exist, returns `ERR_RESOURCE_NOT_FOUND` (HTTP 404) before the inner id is even inspected. Foreign-key ids supplied in request bodies (any of `chapter_id`, `pnm_id`, `party_id`, `round_id`, `bid_match_id`, or the optional `legacy_chapter_id`) that do not resolve to an existing row are rejected with `ERR_REFERENCE_NOT_FOUND` (HTTP 422).

### 2.7. Validation Priority

When multiple validation conditions could apply to a single request, they are evaluated in a fixed order so that the response code identifies the first failure deterministically: authentication first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_UNAUTHORIZED`), then path-parameter existence (`ERR_RESOURCE_NOT_FOUND`), then body-foreign-key existence (`ERR_REFERENCE_NOT_FOUND`), then state-machine precondition (`ERR_INVALID_STATE`), then optimistic-concurrency match (`ERR_STALE_VERSION`), then the chapter-suspension safety gate (`ERR_CHAPTER_SUSPENDED`), then domain-temporal conflicts (`ERR_PARTY_TIME_CONFLICT` on invitation accept, `ERR_CHAPTER_DOUBLE_BOOK` on party create), then preference eligibility (`ERR_PREFERENCE_NOT_ELIGIBLE`), then preference-rank uniqueness (`ERR_PREFERENCE_RANK_TAKEN`), then round-phase gating (`ERR_ROUND_PHASE_MISMATCH`), then chapter quota fullness (`ERR_CHAPTER_QUOTA_FULL`), then duplicate-invitation uniqueness (`ERR_DUPLICATE_INVITATION`), then the PNM GPA floor on activation (`ERR_GPA_BELOW_MINIMUM`), and finally generic body shape (`ERR_INVALID_REQUEST`).

In particular: state-machine precondition checks dominate OCC checks (a request that targets a row in the wrong state never reaches the version comparison), OCC dominates the chapter-suspension safety gate, and the safety gate dominates every fiscal gate that follows it.

### 2.8. Risk-Management Posture and the Suspension Safety Gate

Every chapter carries a derived risk posture, `risk_status`, drawn from the enumeration `GOOD_STANDING`, `PROBATION`, and `SUSPENDED`. It is recomputed from the chapter's cumulative `risk_points`, which is itself the sum of `severity_points` taken across that chapter's `RiskIncident` rows whose `status` is `ACTIVE` — incidents whose `status` is `EXPIRED` or `DISMISSED` no longer count. The threshold rule is: if `risk_points` is at least 15, the chapter is `SUSPENDED`; otherwise, if `risk_points` is at least 6, the chapter is on `PROBATION`; otherwise it is in `GOOD_STANDING`. The boundary is inclusive on the lower bound — 6 points is `PROBATION` (not `GOOD_STANDING`), 5 points is `GOOD_STANDING`, 15 points is `SUSPENDED`, 14 points is `PROBATION`. Both `risk_points` and `risk_status` are recomputed every time a `RiskIncident` is created, dismissed, or expired, and the recomputation always bumps `Chapter.version` and refreshes `updated_at`.

A `SUSPENDED` chapter is barred from two operations: scheduling a new party and producing a new bid. Both rejections use `ERR_CHAPTER_SUSPENDED` (HTTP 409). A chapter on `PROBATION` may still schedule parties and produce bids; only `SUSPENDED` triggers the safety block. The same is true for the `ChapterOfficer` opening or completing a party — those operations also require `risk_status` to be `GOOD_STANDING` or `PROBATION`, never `SUSPENDED`, and reject with `ERR_INVALID_STATE` when the precondition fails because a chapter has slipped under suspension between scheduling and opening.

### 2.9. Precision and Monetary Representation

All monetary amounts are denominated in integer US-dollar cents and stored as integers; the system performs no rounding because no division operations are required by the dues ledger. Chapter dues per pledge (`dues_per_member_cents`), the per-bid dues snapshot (`dues_charged_cents`), the signed ledger entry value (`amount_cents`), and the running ledger total (`running_balance_cents`) are all integer cents. Severity-point arithmetic and quota counting are likewise integer operations, with no rounding.

### 2.10. Hierarchical Cascade and Derived-Field Reconciliation

The system stores both raw inputs (incidents, invitations, ledger entries) and derived counters that summarize them (`risk_points`, `risk_status`, `pledged_count`, `legacy_pledged_count`, `confirmed_count`, `running_balance_cents`). Whenever a base row that feeds a derived counter is created or transitioned, the derived counter is recomputed in the same logical operation, and the parent entity's `version` and `updated_at` are advanced. A `Chapter.version` increment is therefore not a Chapter-only event: it propagates from any of (i) a new `RiskIncident`, (ii) a `RiskIncident` dismissal, (iii) the cascading expiry of party-tied `RiskIncident` rows when a round advances out of party phase, (iv) the creation of a `BidMatch`, (v) the acceptance of a `BidMatch` (which bumps `pledged_count`), and (vi) the rescission of an accepted `BidMatch` (which decrements `pledged_count`). Similarly, a `Party.version` increment propagates from any RSVP that changes `confirmed_count`. Implementations must keep the derived counters reconciled with their inputs at every commit; a `pledged_count` that disagrees with the count of `ACCEPTED` `BidMatch` rows on that chapter in the current cycle is a bug.

## 3. Business Logic & Workflows

### 3.1. Cycle Setup: Chapters, PNMs, and Recruitment Rounds

The recruitment cycle is bracketed by three setup actions, all controlled by the `PanhellenicAdmin`. Creating a chapter records its display `name` — between 1 and 80 characters, unique system-wide and case-insensitive — its `greek_type` drawn from `SORORITY` or `FRATERNITY`, its per-cycle `quota_total` (at least 1), the dues it will charge each pledge (`dues_per_member_cents`, zero or positive), and the count of `legacy_priority_slots` carved out of `quota_total` for alumna-family PNMs. The legacy slots count *against* `quota_total`, not in addition to it, and the system enforces that `legacy_priority_slots` lies between 0 and `quota_total` inclusive. On creation, `risk_status` is `GOOD_STANDING`, `risk_points` is 0, `pledged_count` is 0, and `legacy_pledged_count` is 0. A subsequent admin update may change `dues_per_member_cents`, `quota_total`, or `legacy_priority_slots`, and bumps `Chapter.version`; crucially, that update has no retroactive effect on dues already snapshot onto past bids — see §3.6.

Potential New Members register themselves through the one public endpoint in the system. Self-registration takes a `full_name` (1 to 120 characters), a cumulative `gpa` expressed to two decimal places between 0.00 and 4.00 inclusive, and an optional `legacy_chapter_id` pointing at a chapter where the PNM's parent or sibling is an alumna. The PNM row is created in `REGISTERED` status with `matched_chapter_id` null; the `is_legacy` flag is set to true if and only if `legacy_chapter_id` is non-null, and is otherwise false. Activation by the `RecruitmentChair` advances `status` from `REGISTERED` to `ACTIVE`, but only if the PNM's `gpa` is at least 2.50 — a `gpa` strictly below 2.50 is rejected with `ERR_GPA_BELOW_MINIMUM` (HTTP 422), not the generic not-found code, because the row does exist. A PNM may also voluntarily withdraw at any time while in `ACTIVE` status, which transitions them to `WITHDRAWN` and cascades: every one of that PNM's outstanding `PartyInvitation` rows whose `rsvp_status` is currently `INVITED` or `ACCEPTED` is transitioned to `DECLINED`.

A `RecruitmentRound` is the cycle envelope. The `PanhellenicAdmin` opens one with a unique `cycle_label` of 1 to 40 characters (for example, "Fall 2026") and a target `bid_day_at` wall-clock timestamp that is informational only — round phase does not advance on a wall clock, it advances explicitly by command. A new round opens in `phase` `PARTY` and walks forward through `MUTUAL_SELECTION`, `BID_DAY`, and finally the terminal `CLOSED` state in strictly linear order. Advancement is the responsibility of the `RecruitmentChair`. The first phase advance — transitioning `phase` from `PARTY` to `MUTUAL_SELECTION` — has two preconditions: the current `phase` must be `PARTY`, and every `Party` row attached to the round (by `round_id`) must have `status` in `COMPLETED` or `CANCELLED`. Its cascading side effects are three: (a) any `ACTIVE` PNM who attended at least one party in this round (that is, has at least one `PartyInvitation` whose `rsvp_status` is `ATTENDED`) keeps `status` `ACTIVE` and is eligible to file preferences, but any `ACTIVE` PNM with zero `ATTENDED` invitations is transitioned to `WITHDRAWN` with reason `NO_PARTY_ATTENDANCE`; (b) every `ACTIVE` `RiskIncident` whose `party_id` belongs to a party on this round is transitioned to `EXPIRED`, with `Chapter.risk_points` and `Chapter.risk_status` recomputed for each affected chapter and the chapter's `version` advanced; and (c) the round's own `phase` field flips, with `RecruitmentRound.version` advanced. `RiskIncident` rows with a null `party_id` (non-party incidents such as bid-day conduct) do not expire automatically.

### 3.2. The Party Schedule

While the round is in `phase` `PARTY`, chapter officers schedule the parties their chapter will host. The officer supplies the owning `round_id`, the hosting `chapter_id`, the `scheduled_start_utc` start instant, a `duration_minutes` of at least 30 and at most 240, and a `capacity` of at least 1. The party is created in `status` `SCHEDULED`, with `confirmed_count` at 0 and `version` at 1. Two preconditions guard scheduling. The hosting chapter must not be `SUSPENDED`: if `risk_status` is `SUSPENDED`, the request is rejected with `ERR_CHAPTER_SUSPENDED`. And the round must currently be in `phase` `PARTY`: a creation attempt in any other phase yields `ERR_ROUND_PHASE_MISMATCH`. In addition, the system runs a same-chapter double-booking check: the half-open interval from `scheduled_start_utc` (inclusive) to `scheduled_start_utc` plus `duration_minutes` (exclusive) must not overlap any other party hosted by the same chapter. Adjacent parties — those whose intervals abut at exactly zero gap — are allowed; any positive overlap is rejected with `ERR_CHAPTER_DOUBLE_BOOK`.

A scheduled party becomes available for RSVPs when its `ChapterOfficer` transitions `status` from `SCHEDULED` to `OPEN`. The transition requires that the round is still in `phase` `PARTY` and the chapter's `risk_status` is still in `GOOD_STANDING` or `PROBATION` — a chapter that has been suspended in the interval between scheduling and opening fails the opening precondition with `ERR_INVALID_STATE`. Completing a party transitions `status` from `OPEN` to `COMPLETED` and cascades: every `PartyInvitation` on the party whose `rsvp_status` is `ACCEPTED` advances to `ATTENDED` (a terminal state), and every invitation whose `rsvp_status` is still `INVITED` advances to `NO_SHOW` (also terminal); PNMs themselves remain `ACTIVE`. Cancelling a party — which the officer may do from either `SCHEDULED` or `OPEN` — transitions `status` to `CANCELLED` and likewise cascades, but with a critical distinction from completion: every non-terminal invitation on the party advances to `DECLINED`, not `NO_SHOW`, because the chapter, not the PNM, is the cancelling party. The chapter's `version` and the party's `version` advance in each of these state changes, and so does `updated_at` on the party.

### 3.3. Party Invitations and the PNM Schedule

Invitations are issued individually by a `ChapterOfficer` from a specific party to a specific PNM. The request body carries the `party_id` and the `pnm_id`, and the row is created in `rsvp_status` `INVITED`. Two preconditions guard creation: the targeted PNM's `status` must be `ACTIVE` at the time the invitation is created, and the pair `(party_id, pnm_id)` must not already exist — a duplicate is rejected with `ERR_DUPLICATE_INVITATION`. From `INVITED`, the acting PNM may either accept or decline; the chapter cannot accept on the PNM's behalf.

Accepting an invitation has four preconditions, evaluated against the live party state. First, the invitation must still be in `rsvp_status` `INVITED` — re-accepting an already-`ACCEPTED` invitation is rejected with `ERR_INVALID_STATE`. Second, the party itself must be in `status` `OPEN`; an `OPEN` party is the only kind a PNM can RSVP into. Third, the party's `confirmed_count` must be strictly less than its `capacity`. And fourth — the most consequential check for the PNM — the system enforces a no-double-booking rule on the PNM's own schedule: the PNM must not have another `ACCEPTED` `PartyInvitation` whose party's half-open time interval, computed as `scheduled_start_utc` (inclusive) to `scheduled_start_utc` plus `duration_minutes` (exclusive), overlaps the new party's interval. Adjacency at exactly zero gap is allowed; any positive overlap is rejected with `ERR_PARTY_TIME_CONFLICT`. On a successful accept, the invitation transitions to `ACCEPTED`, the party's `confirmed_count` is incremented by 1, and the party's `version` advances. Declining an invitation — from either `INVITED` or `ACCEPTED` — transitions it to `DECLINED`; if it was previously `ACCEPTED`, the party's `confirmed_count` is also decremented by 1. Declining from `ACCEPTED` is allowed only while the underlying party is still `SCHEDULED` or `OPEN`.

### 3.4. Filing Preferences

Preference filing opens only while the round is in `phase` `MUTUAL_SELECTION`; a filing attempt in any other phase is rejected with `ERR_ROUND_PHASE_MISMATCH`. Each `Preference` row encodes one rank of one ranker's list, identified by a `side` drawn from `PNM_TO_CHAPTER` (a PNM ranking a chapter) or `CHAPTER_TO_PNM` (a chapter ranking a PNM). The body carries the `round_id`, the `side`, the `pnm_id`, the `chapter_id`, and the integer `rank` (1-based, with 1 the top choice and the constraint `rank` at least 1).

Each row is unique on the tuple `(round_id, side, ranker, rank)`. The ranker is the `pnm_id` when `side` is `PNM_TO_CHAPTER` and the `chapter_id` when `side` is `CHAPTER_TO_PNM`, so a single PNM cannot file two `rank` 1 picks against two different chapters in the same round, and a single chapter cannot rank two different PNMs as its `rank` 1. A duplicate-rank attempt is rejected with `ERR_PREFERENCE_RANK_TAKEN`. The role layer restricts authoring as well: a `PNM` may only file rows with `side` `PNM_TO_CHAPTER`, and a `ChapterOfficer` may only file rows with `side` `CHAPTER_TO_PNM`. Beyond authorship, the system runs an eligibility gate: filing on `side` `PNM_TO_CHAPTER` requires the PNM's `status` to be `ACTIVE` at filing time, and filing on `side` `CHAPTER_TO_PNM` requires that the target PNM's `status` is `ACTIVE` *and* that the PNM has at least one `PartyInvitation` whose `rsvp_status` is `ATTENDED` on a party hosted by this chapter in this round. A failure of either branch is rejected with `ERR_PREFERENCE_NOT_ELIGIBLE`.

### 3.5. Mutual Selection and Bid Production

The transition from `MUTUAL_SELECTION` to `BID_DAY` is the cycle's most concentrated piece of business logic. It is driven by the `RecruitmentChair` advancing the round and gated on two preconditions: the round's current `phase` is `MUTUAL_SELECTION`, and every chapter that has received at least one `PNM_TO_CHAPTER` preference targeting it has also filed at least one `CHAPTER_TO_PNM` preference of its own in this round (so the matcher has mutual data to consume). When the precondition holds, the round's `phase` advances to `BID_DAY`, `RecruitmentRound.version` advances, and the mutual-selection allocator runs — producing zero or more `BidMatch` rows, each initially in `status` `PROPOSED`, and, for each match produced, transitioning the targeted PNM from `ACTIVE` to `MATCHED` and setting `PNM.matched_chapter_id` to the chapter on the bid.

The allocator is a two-pass waterfall, not a global bipartite optimum. Its input set is fixed: all `Preference` rows on the round; all PNMs whose `status` is `ACTIVE`; and all chapters whose `risk_status` is `GOOD_STANDING` or `PROBATION`. Chapters whose `risk_status` is `SUSPENDED` are excluded — they do not bid in this cycle. PNMs without at least one mutual preference pair (a `PNM_TO_CHAPTER` rank by the PNM toward some chapter *and* a `CHAPTER_TO_PNM` rank by that chapter toward the PNM) are excluded from consideration with that chapter.

Within each pass, chapters are processed in `created_at` ascending order — the older chapter goes first, with ties broken by insertion order and never by `id`. The first pass — the legacy pass — walks chapters in that order; for each chapter whose `legacy_priority_slots` is still positive (after any matches already produced in this pass for this chapter) and which still has quota headroom, it builds a candidate list of PNMs whose `is_legacy` flag is true, whose `legacy_chapter_id` equals this chapter's `id`, who are not yet matched anywhere in this pass, and who are part of a mutual preference pair with this chapter. The candidate list is sorted primarily by the chapter's `CHAPTER_TO_PNM` rank for the PNM (lower `rank` is better; a missing chapter rank places the candidate at the back); secondarily by the PNM's `PNM_TO_CHAPTER` rank for the chapter (again, lower is better, with missing ranks at the back); and finally by the PNM's `created_at` ascending. From the head of that list, the allocator takes up to the lesser of (i) the chapter's remaining `legacy_priority_slots` and (ii) the chapter's remaining quota headroom (`quota_total` minus the chapter's pending pledged count after prior produced matches in this pass), producing a `BidMatch` for each. Every match produced in the legacy pass carries `priority_kind` `LEGACY` and is counted against *both* `Chapter.legacy_priority_slots` and `Chapter.quota_total` — legacy slots sit inside quota, not on top of it. A PNM matched in the legacy pass is removed from all other chapters' candidate lists immediately.

The second pass — the standard pass — repeats the walk in the same `created_at` ascending order over chapters, but with two changes. The candidate set drops the legacy filter (any unmatched `ACTIVE` PNM with a mutual preference pair toward this chapter is eligible), and the per-chapter take size is whatever remaining quota headroom the chapter has after the legacy pass (specifically, `quota_total` minus pending pledged count). Each match produced in this pass carries `priority_kind` `STANDARD` and is counted only against `Chapter.quota_total`. The sort key inside the candidate list is identical to the legacy pass — chapter rank first, PNM rank second, PNM `created_at` ascending as the final tie-break. The constant `MAX_BIDS_PER_PNM` is 1: as before, a PNM matched in either pass is removed from every chapter's candidate list for the remainder of the run, so no PNM emerges from the allocator with more than one `BidMatch`.

A `ChapterOfficer` may also bypass the allocator and produce a single bid manually. The manual create takes a `round_id`, a `chapter_id`, a `pnm_id`, and the `expected_chapter_version` value carrying the client's last observed `Chapter.version`. The manual path is gated identically to the allocator: the chapter must not be `SUSPENDED` (else `ERR_CHAPTER_SUSPENDED`), `Chapter.pledged_count` plus 1 must be at most `Chapter.quota_total` (else `ERR_CHAPTER_QUOTA_FULL`), the round must be in `phase` `BID_DAY` (else `ERR_ROUND_PHASE_MISMATCH`), and the supplied `expected_chapter_version` must match the chapter's current `version` (else `ERR_STALE_VERSION`). On a successful manual create, the `BidMatch` row is initialized with `status` `PROPOSED`, `dues_charged_cents` at 0, and `version` at 1; `priority_kind` is `LEGACY` if and only if the PNM's `legacy_chapter_id` equals the bidding `chapter_id` *and* the chapter's `legacy_pledged_count` is strictly less than its `legacy_priority_slots`, and `STANDARD` otherwise. The targeted PNM advances to `MATCHED`, with `matched_chapter_id` set to the bidding chapter and `PNM.version` advanced; `Chapter.version` advances as well to seal off any other officer's stale view.

### 3.6. Bid Acceptance, Decline, Rescind, and the Dues Ledger

A `MATCHED` PNM resolves the bid by either accepting it or declining it. Both actions are gated by the round being in `phase` `BID_DAY` and by the underlying `BidMatch.status` still being `PROPOSED`; an attempt against a `PROPOSED` bid in a chapter whose `risk_status` is `SUSPENDED` is also rejected — the safety gate dominates even on accept. The transition pair is `PROPOSED → ACCEPTED` (or `PROPOSED → DECLINED`) for the bid and `MATCHED → BID_ACCEPTED` (or `MATCHED → BID_DECLINED`) for the PNM. Accepting cascades through several fields. The chapter's *current* `dues_per_member_cents` is read at the instant the accept commits and snapshot onto the bid as `BidMatch.dues_charged_cents` — this is the fixed amount that bid will ever be billed for. A subsequent `PanhellenicAdmin` revision of `dues_per_member_cents` on the chapter does *not* alter the `dues_charged_cents` of any past `ACCEPTED` bid. A `DuesLedgerEntry` is appended with `entry_kind` `CHARGE`, `amount_cents` equal to the positive snapshot value, `chapter_id` set to the bidding chapter, and `bid_match_id` set to the accepting bid. The chapter's `pledged_count` is incremented; if the bid's `priority_kind` is `LEGACY`, the chapter's `legacy_pledged_count` is also incremented. The PNM moves to `BID_ACCEPTED` (terminal). All of `BidMatch.version`, `PNM.version`, and `Chapter.version` advance. Declining a bid instead sets `BidMatch.status` to `DECLINED`, sets `PNM.status` to `BID_DECLINED`, clears `PNM.matched_chapter_id` to null, and bumps both versions — no dues entry is posted on decline.

The chapter side has one compensating action available on the previously accepted bid: the `ChapterOfficer` may rescind an `ACCEPTED` bid while the round is still in `phase` `BID_DAY`, supplying `expected_chapter_version` to gate the operation under optimistic concurrency. On a successful rescind, the bid's `status` transitions to `DECLINED` (the rescission is modeled as a `DECLINED` bid distinguished from a PNM decline by the trailing refund entry on its `bid_match_id`); a compensating `DuesLedgerEntry` is appended with `entry_kind` `REFUND` and `amount_cents` equal to the *negation* of the bid's `dues_charged_cents`, so the chapter's CHARGE plus REFUND on that bid sums to exactly zero. The chapter's `pledged_count` is decremented (and `legacy_pledged_count` is decremented as well if `priority_kind` is `LEGACY`), freeing the slot. The PNM is pushed back to `ACTIVE` with `matched_chapter_id` cleared to null so the chapter has the opportunity to refill the slot before `BID_DAY` closes. `BidMatch.version`, `PNM.version`, and `Chapter.version` all advance.

The dues ledger is the system's accounting record. Each `DuesLedgerEntry` row is ordered by `created_at` ascending, with ties broken by insertion order (never by `id`), and carries a signed `amount_cents` (positive for a `CHARGE`, negative for a `REFUND`) and a precomputed `running_balance_cents`. Two evaluation modes pin the same chronological order but produce different shapes. The per-entry running balance, returned by the ledger listing, is computed by walking the chapter's entries in `created_at` ascending order, accumulating the sum of `amount_cents` into a running total, and stamping that running total onto each row's `running_balance_cents`; the final entry's running total is the ledger's final balance. The chapter-aggregate balance — equivalently, `dues_balance_cents` as reported on the chapter resource — is computed as the plain sum of `amount_cents` across all of that chapter's entries; by construction it equals the final per-entry running total. The two modes must always agree at the final row: any drift between the last `running_balance_cents` in the listing and the aggregate sum is a bug. The per-entry mode is sensitive to insertion order — a back-dated `REFUND` inserted between two earlier `CHARGE`s would change every subsequent row's `running_balance_cents` — while the aggregate mode is order-insensitive (commutative sum), which is precisely the property the implementation must preserve even across mid-cycle refunds. There is no rounding anywhere: cents are integers, ledger arithmetic is integer arithmetic.

### 3.7. Round Closure

When every `BidMatch` on the round has reached a terminal — that is, every bid is either `ACCEPTED` or `DECLINED` — the `RecruitmentChair` may advance the round from `BID_DAY` to `CLOSED`. The advance flips `phase` to `CLOSED` and refreshes `RecruitmentRound.version`. Two further cascades complete the cycle. Any PNM still in `MATCHED` `status` whose `BidMatch` somehow remained `PROPOSED` is transitioned to `WITHDRAWN` — a timed-out bid — and no further dues movement is implied because dues are posted only on individual accept and individual rescind, never on the close itself.

### 3.8. Risk Management

The `RiskOfficer` is the sole writer of `RiskIncident` rows. Filing an incident takes the `chapter_id` to charge, an optional `party_id` (null for non-party incidents such as bid-day conduct), a `severity_points` integer between 1 and 10 inclusive, and a free-text `reason` of 1 to 200 characters. The incident is created in `status` `ACTIVE`, the chapter's `risk_points` is recomputed as the sum of `severity_points` over the chapter's `ACTIVE` incidents, the chapter's `risk_status` is recomputed against the 6-point `PROBATION` and 15-point `SUSPENSION` thresholds described in §2.8, and `Chapter.version` advances.

An `ACTIVE` incident may be dismissed by the `RiskOfficer`, transitioning its `status` to `DISMISSED`. Dismissal is consequential precisely because of the cascade: the chapter's `risk_points` is recomputed (dropping this incident's severity contribution), and `risk_status` may transition all the way back to `GOOD_STANDING`, transitively re-opening party scheduling and bid production on that chapter. An incident may also be retired by the system as `EXPIRED` — but only as a side-effect of the round advancing from `phase` `PARTY` to `phase` `MUTUAL_SELECTION`, and only for incidents whose `party_id` ties them to a party on that round; non-party incidents (those with null `party_id`) persist across phase advance and continue to count toward `risk_points` until explicitly dismissed.

### 3.9. Test-Driving the Logical Clock

For deterministic temporal tests, the system exposes one admin-only capability to advance its logical clock to a supplied instant: the request body carries a `to_iso8601` ISO 8601 UTC timestamp, and the server's observed current UTC moves to that value. This capability does not advance any state machine, does not write any business row, and is the only endpoint that exists for test-driving purposes.

## 4. Endpoint Definitions

The endpoint table summarizes all available HTTP operations. Creation endpoints return HTTP 201 with the new resource in `data`; read endpoints, state-transition endpoints, and modification endpoints all return HTTP 200. Errors follow the standard error envelope and use the HTTP status codes catalogued in §5. The request body, the response body, and the side effects of each endpoint are described in §3; this table is a routing reference only.

| Method | Path | Description | Authorized Role(s) |
|--------|------|-------------|--------------------|
| POST   | `/rush/chapters` | Create a chapter (sorority or fraternity) | `PanhellenicAdmin` |
| GET    | `/rush/chapters/{id}` | Fetch a chapter | `PanhellenicAdmin`, `ChapterOfficer`, `RecruitmentChair`, `RiskOfficer`, `PNM` |
| GET    | `/rush/chapters` | List chapters; filterable by `greek_type` | `PanhellenicAdmin`, `ChapterOfficer`, `RecruitmentChair`, `RiskOfficer`, `PNM` |
| PUT    | `/rush/chapters/{id}` | Update mutable chapter fields (no retroactive effect on past dues snapshots) | `PanhellenicAdmin` |
| GET    | `/rush/chapters/{id}/parties` | List parties hosted by a chapter; filterable by `round_id`, `status` | `PanhellenicAdmin`, `ChapterOfficer`, `RecruitmentChair`, `RiskOfficer`, `PNM` |
| GET    | `/rush/chapters/{id}/risk-incidents` | List risk incidents charged to a chapter; filterable by `status` | `PanhellenicAdmin`, `RiskOfficer` |
| GET    | `/rush/chapters/{id}/dues-ledger` | Chronological dues ledger with per-entry running balance | `PanhellenicAdmin`, `ChapterOfficer` |
| GET    | `/rush/chapters/{id}/preferences` | List preferences referencing this chapter; filterable by `side`, `round_id` | `PanhellenicAdmin`, `RecruitmentChair`, `ChapterOfficer` |
| POST   | `/rush/pnms/register` | Public PNM self-registration | `Anonymous` |
| GET    | `/rush/pnms/{id}` | Fetch a PNM | `PanhellenicAdmin`, `RecruitmentChair`, `ChapterOfficer`, `PNM` |
| GET    | `/rush/pnms` | List PNMs; filterable by `status`, `legacy_chapter_id`, `matched_chapter_id` | `PanhellenicAdmin`, `RecruitmentChair`, `ChapterOfficer` |
| POST   | `/rush/pnms/{id}/activate` | Activate a registered PNM (gated by `gpa` floor) | `RecruitmentChair` |
| POST   | `/rush/pnms/{id}/withdraw` | PNM voluntary withdrawal (cascades to invitations) | `PNM` |
| GET    | `/rush/pnms/{id}/invitations` | List a PNM's invitations; filterable by `rsvp_status` | `PanhellenicAdmin`, `RecruitmentChair`, `ChapterOfficer`, `PNM` |
| GET    | `/rush/pnms/{id}/preferences` | List preferences referencing this PNM; filterable by `side`, `round_id` | `PanhellenicAdmin`, `RecruitmentChair`, `ChapterOfficer`, `PNM` |
| GET    | `/rush/pnms/{id}/bid-matches` | List bid matches targeting this PNM; filterable by `status` | `PanhellenicAdmin`, `RecruitmentChair`, `ChapterOfficer`, `PNM` |
| GET    | `/rush/pnms/legacy-of/{id}` | List PNMs whose `legacy_chapter_id` is this chapter | `PanhellenicAdmin`, `ChapterOfficer`, `RecruitmentChair` |
| POST   | `/rush/rounds` | Open a recruitment cycle in `PARTY` phase | `PanhellenicAdmin` |
| GET    | `/rush/rounds/{id}` | Fetch a round | `PanhellenicAdmin`, `ChapterOfficer`, `RecruitmentChair`, `RiskOfficer`, `PNM` |
| GET    | `/rush/rounds` | List rounds; filterable by `phase` | `PanhellenicAdmin`, `ChapterOfficer`, `RecruitmentChair`, `RiskOfficer` |
| POST   | `/rush/rounds/{id}/advance` | Advance the round phase (with cascades per §3) | `RecruitmentChair` |
| GET    | `/rush/rounds/{id}/parties` | List parties on a round; filterable by `chapter_id`, `status` | `PanhellenicAdmin`, `ChapterOfficer`, `RecruitmentChair`, `RiskOfficer`, `PNM` |
| GET    | `/rush/rounds/{id}/preferences` | List preferences on a round; filterable by `side`, `chapter_id`, `pnm_id` | `PanhellenicAdmin`, `RecruitmentChair` |
| GET    | `/rush/rounds/{id}/bid-matches` | List bid matches on a round; filterable by `chapter_id`, `pnm_id`, `status` | `PanhellenicAdmin`, `RecruitmentChair`, `ChapterOfficer` |
| POST   | `/rush/parties` | Schedule a party | `ChapterOfficer` |
| GET    | `/rush/parties/{id}` | Fetch a party | `PanhellenicAdmin`, `ChapterOfficer`, `RecruitmentChair`, `RiskOfficer`, `PNM` |
| POST   | `/rush/parties/{id}/open` | Open a scheduled party for RSVPs | `ChapterOfficer` |
| POST   | `/rush/parties/{id}/complete` | Complete an open party (ACCEPTED → ATTENDED, INVITED → NO_SHOW) | `ChapterOfficer` |
| POST   | `/rush/parties/{id}/cancel` | Cancel a scheduled or open party (cascades to invitations) | `ChapterOfficer` |
| GET    | `/rush/parties/{id}/invitations` | List invitations on a party; filterable by `rsvp_status` | `PanhellenicAdmin`, `ChapterOfficer`, `RecruitmentChair`, `PNM` |
| GET    | `/rush/parties/{id}/risk-incidents` | List risk incidents on a party; filterable by `status` | `PanhellenicAdmin`, `RiskOfficer` |
| POST   | `/rush/invitations` | Issue a party invitation | `ChapterOfficer` |
| GET    | `/rush/invitations/{id}` | Fetch an invitation | `PanhellenicAdmin`, `ChapterOfficer`, `RecruitmentChair`, `PNM` |
| POST   | `/rush/invitations/{id}/accept` | PNM accepts an invitation | `PNM` |
| POST   | `/rush/invitations/{id}/decline` | PNM declines an invitation (cancellable from `ACCEPTED`) | `PNM` |
| POST   | `/rush/preferences` | File one preference row | `PNM`, `ChapterOfficer` |
| GET    | `/rush/preferences/{id}` | Fetch a preference | `PanhellenicAdmin`, `RecruitmentChair`, `ChapterOfficer`, `PNM` |
| POST   | `/rush/bid-matches` | Manual override bid creation (OCC-gated) | `ChapterOfficer` |
| GET    | `/rush/bid-matches/{id}` | Fetch a bid match | `PanhellenicAdmin`, `RecruitmentChair`, `ChapterOfficer`, `PNM` |
| GET    | `/rush/bid-matches` | List bid matches; filterable by `chapter_id`, `pnm_id`, `round_id`, `status` | `PanhellenicAdmin`, `RecruitmentChair`, `ChapterOfficer`, `PNM` |
| GET    | `/rush/bid-matches/{id}/dues-ledger-entries` | List dues-ledger entries produced by this bid | `PanhellenicAdmin`, `ChapterOfficer` |
| POST   | `/rush/bid-matches/{id}/accept` | PNM accepts a bid (charges dues snapshot, pledges PNM) | `PNM` |
| POST   | `/rush/bid-matches/{id}/rescind` | Chapter rescinds an accepted bid (OCC-gated, posts refund) | `ChapterOfficer` |
| POST   | `/rush/bid-matches/{id}/decline` | PNM declines a proposed bid | `PNM` |
| POST   | `/rush/risk-incidents` | Record a risk incident | `RiskOfficer` |
| GET    | `/rush/risk-incidents/{id}` | Fetch a risk incident | `PanhellenicAdmin`, `RiskOfficer` |
| POST   | `/rush/risk-incidents/{id}/dismiss` | Dismiss an active risk incident (cascades) | `RiskOfficer` |
| POST   | `/rush/_clock/set_current_utc` | Test-driving: pin server's current UTC | `PanhellenicAdmin` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|----------|------------------|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_RESOURCE_NOT_FOUND` | 404 |
| `ERR_REFERENCE_NOT_FOUND` | 422 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_CHAPTER_SUSPENDED` | 409 |
| `ERR_PARTY_TIME_CONFLICT` | 409 |
| `ERR_CHAPTER_DOUBLE_BOOK` | 409 |
| `ERR_PREFERENCE_NOT_ELIGIBLE` | 409 |
| `ERR_PREFERENCE_RANK_TAKEN` | 409 |
| `ERR_ROUND_PHASE_MISMATCH` | 409 |
| `ERR_CHAPTER_QUOTA_FULL` | 409 |
| `ERR_DUPLICATE_INVITATION` | 409 |
| `ERR_GPA_BELOW_MINIMUM` | 422 |
