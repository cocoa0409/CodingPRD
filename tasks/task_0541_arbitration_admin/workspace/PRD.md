# Arbitration Admin API — Product Requirements Document

## 1. Introduction

This document specifies a case-administration platform for a mediation-and-arbitration provider modeled on the operational conventions of bodies such as the AAA and JAMS. The system is the system of record for the full life of a dispute: intake and fee tiering when a matter is filed, assembly and vetting of a candidate pool of neutrals, party-driven striking and ranking, the appointment of a single arbitrator or a three-member panel (or a mediator), hearing scheduling and document exchange, the retainer-and-fee ledger that funds neutral compensation, and finally the issuance, finalization, appeal, and possible vacatur of an award.

The domain is unusually interconnected. A single administrative act — appointing a neutral, issuing an award, granting an appeal — ripples across several records at once, and the money owed to a neutral is tracked twice over (once as a forward-looking estimate and once as a realized total). Because the workflow is cyclic — a granted appeal vacates a standing award and returns the case to its hearing phase for re-arbitration — the platform must keep case status, award status, and the deposit ledger consistent through every loop. The requirements below define the entities, their state machines, the fee and compensation calculations, the validation and safety gates, and the exact API contract that binds them together.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply uniformly across every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The system recognizes exactly three roles: `CaseAdministrator`, `Party`, and `Neutral`. A request that omits either header, or that names a role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is authenticated but is not permitted to perform the requested operation — or whose identity does not own the targeted resource where ownership is required — is rejected with `ERR_UNAUTHORIZED`.

The three roles differ in how `X-User-ID` binds to persisted data:

- When `X-User-Role` is `CaseAdministrator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The administrator drives the case lifecycle and the panel roster; the server does not compare this identifier to any entity's `id`.
- When `X-User-Role` is `Party`, `X-User-ID` is the `id` of the acting `Party`. Ownership checks on any resource that references a `Party` compare that resource's party foreign key to `X-User-ID` — for example, withdrawing a ranking requires that the ranking's `party_id` equal `X-User-ID`, and an appeal records the filer's identifier in `filed_by_party_id`.
- When `X-User-Role` is `Neutral`, `X-User-ID` is the `id` of the acting `Neutral`. Ownership checks on any resource that references a `Neutral` compare that resource's neutral foreign key to `X-User-ID` — for example, submitting a disclosure requires that the target candidate's `neutral_id` equal `X-User-ID`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. A `limit` or `offset` outside its allowed bounds is rejected with `ERR_PAGINATION_INVALID`.

Unless a specific endpoint states otherwise, every list is sorted by the resource's creation timestamp (`created_at`) in ascending order. Each paginated response echoes `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

Every entity in this system is a top-level, independently addressable resource, and each one carries a common set of system-managed fields:

- `id` — a server-minted UUID, with no type prefix, unique across the resource's collection.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- `updated_at` — an ISO 8601 UTC timestamp, refreshed on every mutation of the resource.
- `version` — an integer that starts at its initial value and increments by one on every mutation. It underpins the optimistic-concurrency mechanism described in §2.6.

Whenever a derived or aggregate field on a resource is recomputed as a side effect of some action — for instance, a case's rolled-up deposit balance changing because a fee was posted — that recomputation is itself a mutation: the resource's `updated_at` is refreshed and its `version` increments.

### 2.5. Monetary Values, Compensation, and Precision

All monetary quantities in this system are stored and returned as integer cents; there are no fractional cents. Where a calculation multiplies a rate by a fractional quantity (such as billable hours) or applies a multiplier, the result is converted to an integer number of cents using **round half up** — a value whose fractional part is exactly one half rounds away from zero to the next whole cent.

The order in which rounding is applied is significant and is specified per calculation in §3; where a total is assembled from several charges, each charge is rounded to whole cents on its own before the charges are summed, and where a single amount carries more than one multiplier, the multipliers are applied first and the product is rounded once. Two distinct views of neutral compensation coexist on every case — a forward-looking estimate over scheduled work and a realized total over posted charges — and §3 defines each precisely.

### 2.6. Optimistic Concurrency Control on the Case

Two write operations that add records under a case are guarded by optimistic concurrency keyed on the case's `version`. In each case the request body must include a non-optional `expected_case_version` field carrying the `version` of the parent `Case` that the client last observed.

- A request that adds a candidate to a case's candidate list must carry `expected_case_version` equal to the target case's current `version`. If another writer has advanced that `version` since the client last read it — because another candidate was added, a strike was posted that regenerated the list, or an appointment was made — the add is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the client to re-read before writing against a superseded view of the pool.
- A request that posts a neutral fee charge against a case must likewise carry `expected_case_version` equal to the case's current `version`. If the version has advanced since the client last read the deposit balance, the post is rejected with `ERR_STALE_VERSION` (HTTP 412), so the losing writer re-reads the current balance rather than double-spending against a stale figure.

The appointment operation also accepts `expected_case_version` and rejects a mismatch with the case's current `version` under `ERR_STALE_VERSION`. Endpoints not named here do not take a version field.

### 2.7. The Logical Clock and Temporal Windows

All time-sensitive rules — hearing notice periods, appeal windows, and exchange due dates — read a single server-held **logical clock** rather than wall-clock time. On startup the clock reads exactly `2026-05-01T00:00:00Z`, and until an administrator advances it explicitly it holds this value and never falls back to real time. An administrator advances the clock to a supplied instant through a dedicated test-driving capability; the request supplies the target instant as `to_iso8601`, and the response reports the new setting as `current_utc`.

Three temporal constants govern the workflow. Hearings must be scheduled with at least seven days of advance notice measured against the logical clock (the notice window is `HEARING_NOTICE_DAYS`, seven days). An appeal must be filed within thirty days of the moment its target award was issued (the appeal window is `APPEAL_WINDOW_DAYS`, thirty days). And two hearings that share the same appointed neutral must be separated by at least thirty minutes of clear time (the neutral buffer is `NEUTRAL_BUFFER_MINUTES`, thirty minutes). The precise gate wording for each appears with its workflow in §3.

### 2.8. Validation Order and Nested-Path Resolution

When several checks could reject the same request, they are evaluated in a fixed priority order so that a given bad request always fails with the same, most-fundamental error. The order is:

1. **Authentication** — headers present and the role known; otherwise `ERR_UNAUTHENTICATED` (401).
2. **Authorization** — the role is permitted for the operation, and an entity-backed role owns the target resource; otherwise `ERR_UNAUTHORIZED` (403).
3. **Existence** — every identifier in the path and every foreign-key reference in the body resolves to a real resource. Path and body identifiers are resolved left to right, and the first one that does not resolve produces `ERR_NOT_FOUND` (404) immediately, before any later identifier is examined.
4. **Structural validation** — required fields present, types correct, enums drawn from their declared sets, pagination within range, a hearing's `end_at` strictly after its `start_at`, a case's `panel_size` equal to 1 or 3, and a `MEDIATION` case restricted to a `panel_size` of 1; a violation yields `ERR_VALIDATION` (400). A hearing whose `end_at` is not strictly after its `start_at` specifically carries `ERR_HEARING_END_BEFORE_START` (400). An enum value that falls outside its declared set is reported as `ERR_INVALID_ENUM` (422).
5. **Concurrency** — the `expected_case_version` guard of §2.6; a mismatch yields `ERR_STALE_VERSION` (412).
6. **State** — the target resource is in a state that permits the requested transition or action; otherwise `ERR_INVALID_STATE` (409).
7. **Compliance safety gates** — roster, conflict, and neutral-type gates (see §3), reported as `ERR_NEUTRAL_NOT_ACTIVE`, `ERR_CANDIDATE_HAS_CONFLICT`, or `ERR_NEUTRAL_TYPE_MISMATCH` (all 409).
8. **Temporal gates** — the hearing-notice and appeal-window gates, reported as `ERR_HEARING_NOTICE_TOO_SHORT` or `ERR_APPEAL_WINDOW_CLOSED` (both 422).
9. **Structural business gates** — parties completeness, hearing overlap, neutral buffer, strike duplication and budget, eligible-candidate presence, single-standing-award, and case-membership of a party, reported as `ERR_PARTIES_INCOMPLETE`, `ERR_HEARING_OVERLAP`, `ERR_NEUTRAL_UNAVAILABLE`, `ERR_DUPLICATE_RANKING`, `ERR_STRIKE_BUDGET_EXCEEDED`, `ERR_NO_ELIGIBLE_CANDIDATE`, `ERR_AWARD_EXISTS`, or `ERR_NOT_CASE_PARTY` (all 409).
10. **Fiscal gate** — a posted fee charge must not exceed the case's current deposit balance; otherwise `ERR_INSUFFICIENT_DEPOSIT` (402).

An earlier check always takes precedence over a later one: an unauthenticated caller never learns that a resource is missing, and a stale-version conflict surfaces before any state or business objection.

### 2.9. Cascading Consistency Across Records

Several operations mutate more than one record at once, and every such cascade is part of the operation's contract, not an incidental effect. Appointing a neutral simultaneously promotes the winning candidate, stamps the case's appointed-neutral reference, and retires every other still-open candidate. Issuing an award both advances the award and bubbles the case forward, recomputing the case's final administrative fee and re-deriving its deposit balance. Granting an appeal vacates the standing award and returns the case to its hearing phase, again re-deriving the deposit balance now that the final administrative fee no longer stands. Withdrawing a ranking and reversing a fee charge are compensating actions: each unwinds the derived figures its original action produced, returning strike allowances or restoring the deposit balance to its pre-charge value. Each affected record is independently mutated — its `updated_at` refreshed and its `version` incremented — as part of the same operation. The specific cascades are spelled out with their workflows in §3.

## 3. Business Logic & Workflows

### 3.1. Filing a Case, Fee Tiering, and Parties

A `CaseAdministrator` opens a matter by filing a **Case**. Filing supplies the `case_type` — either `ARBITRATION` or `MEDIATION` — a `title` caption, the amount in controversy as `claim_amount_cents` (an integer of at least zero), and optionally the `panel_size` and `strikes_per_party`. The `panel_size` is the number of neutrals who will decide the matter and must be either 1 or 3, defaulting to 1; a `MEDIATION` case must have a `panel_size` of 1. The `strikes_per_party` is the strike allowance each party may spend against the candidate list, an integer of at least zero, defaulting to 2. A freshly filed case enters `FILED` status.

At filing the system derives two figures. First, the case's `fee_tier` is selected from the amount in controversy by threshold: a `claim_amount_cents` below 1,000,000 cents is `TIER_1`; from 1,000,000 up to but not including 7,500,000 cents it is `TIER_2`; from 7,500,000 up to but not including 50,000,000 cents it is `TIER_3`; and at 50,000,000 cents or above it is `TIER_4`. Each tier floor is inclusive of its lower bound. Second, the provisional `filing_fee_cents` is computed from that tier: a base administrative amount is looked up by tier — 75,000 cents for `TIER_1`, 175,000 cents for `TIER_2`, 400,000 cents for `TIER_3`, and 700,000 cents for `TIER_4` — then multiplied by a case-type multiplier of 1.0 for an `ARBITRATION` case or 0.5 for a `MEDIATION` case, and by a panel multiplier of 1.5 when `panel_size` is 3 or 1.0 otherwise. Both multipliers are applied to the base and the single product is rounded half up to whole cents. At filing the case's `final_admin_fee_cents` is 0 (it remains 0 until an award is issued), and its `deposit_balance_cents` is 0.

A `CaseAdministrator` adds a **Party** to a case by supplying the party's `case_id`, its `role` — either `CLAIMANT` or `RESPONDENT` — a `display_name`, and a `share_pct`, the whole-percent portion of neutral fees allocated to that party (an integer from 0 to 100; the parties on a case are expected to sum to 100). A new party begins with `strikes_used` of 0 and `strikes_remaining` equal to the case's `strikes_per_party`. As strikes are cast and withdrawn, `strikes_used` is maintained as the count of that party's strike rankings that remain active, and `strikes_remaining` is the case's `strikes_per_party` less `strikes_used`. Each party also carries an `allocated_fee_share_cents`, its portion of the case's posted fees, described in §3.8.

A case may move out of `FILED` in two ways, both driven by a `CaseAdministrator`. Opening candidate selection advances the case from `FILED` to `SELECTION`, but only if the case already has at least one party whose `role` is `CLAIMANT` and at least one whose `role` is `RESPONDENT`; otherwise the transition is rejected with `ERR_PARTIES_INCOMPLETE`. Alternatively the case may be abandoned from `FILED` to `WITHDRAWN` with no precondition. A case in `SELECTION` may also be withdrawn to `WITHDRAWN`; when it is, every candidate still open on the case — that is, every candidate in `PROPOSED`, `DISCLOSED`, `CLEARED`, or `OBJECTED` — is moved to `NOT_SELECTED`. `CLOSED` and `WITHDRAWN` are the terminal states of a case. Every case transition increments the case's `version`.

### 3.2. The Panel Roster and Neutral Compensation

A `CaseAdministrator` maintains the roster of neutrals independently of any case. Adding a **Neutral** supplies a `full_name`, a `neutral_type` of `ARBITRATOR`, `MEDIATOR`, or `BOTH`, and an `hourly_rate_cents` billing rate greater than zero. A new neutral joins with `roster_status` of `ACTIVE`; roster management can move a neutral among `ACTIVE`, `SUSPENDED`, and `RETIRED`.

Compensation owed to the neutral appointed to a case is tracked two ways. The **estimated** compensation, held on the case as `estimated_neutral_fee_cents`, is a forward-looking projection over the case's scheduled hearings: it takes the appointed neutral's `hourly_rate_cents`, multiplies it by the total planned duration in hours of every hearing on the case whose status is `SCHEDULED` (hearings that are `HELD` or `CANCELLED` are excluded), and rounds the product half up to whole cents. It is recomputed whenever a hearing is scheduled and whenever a scheduled hearing is cancelled and thereby leaves the scheduled set. The **actual** compensation, held on the case as `actual_neutral_fee_cents`, is the realized total from posted fee charges and always equals the case's `posted_fee_cents`; §3.8 defines how each charge's amount is computed and summed. The two figures diverge whenever the hours actually logged differ from the planned hearing durations.

### 3.3. Candidate Selection: Disclosure and Conflict Clearance

Once a case is in `SELECTION`, the administrator populates its **Candidate** pool. Adding a candidate names the case in the path and supplies the roster `neutral_id` to propose; the new candidate enters `PROPOSED`. Because this write regenerates the pool, it is guarded by optimistic concurrency: the body must carry `expected_case_version` matching the case's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (see §2.6). Adding a candidate also increments the case's `version`. The candidate's `neutral_type` must be compatible with the case's `case_type`: an `ARBITRATION` case admits only a neutral whose `neutral_type` is `ARBITRATOR` or `BOTH`, and a `MEDIATION` case admits only `MEDIATOR` or `BOTH`; an incompatible pairing is rejected with `ERR_NEUTRAL_TYPE_MISMATCH`. A candidate also carries a `disclosure_text` and a `has_conflict` flag, both null/absent until the neutral discloses, and two derived signals — `aggregate_rank_score` and `is_struck` — described in §3.4.

A candidate proceeds through a vetting sequence. The proposed neutral submits a disclosure, moving the candidate from `PROPOSED` to `DISCLOSED`. This action is reserved to the `Neutral` who owns the candidacy — the acting `X-User-ID` must equal the candidate's `neutral_id` — and the disclosing neutral's `roster_status` must be `ACTIVE`, else the disclosure is rejected with `ERR_NEUTRAL_NOT_ACTIVE`. The disclosure carries the `disclosure_text` the neutral supplies and a `has_conflict` boolean (defaulting to false), and both are written onto the candidate.

From `DISCLOSED`, the administrator either clears the candidate or objects. Clearing moves the candidate from `DISCLOSED` to `CLEARED`, but only when its `has_conflict` is false; a candidate whose `has_conflict` is true cannot be cleared and the attempt is rejected with `ERR_CANDIDATE_HAS_CONFLICT`. Objecting moves the candidate from `DISCLOSED` to `OBJECTED` with no precondition. An objection is not necessarily final: from `OBJECTED` the administrator may cure the candidate back to `CLEARED` — again only when `has_conflict` is false, otherwise `ERR_CANDIDATE_HAS_CONFLICT` — or may instead move it from `OBJECTED` to `DISQUALIFIED`. `APPOINTED`, `DISQUALIFIED`, and `NOT_SELECTED` are the terminal states of a candidate. Beyond these administrator-driven moves, the system itself sweeps candidates to `NOT_SELECTED` as a cascade of appointment or case withdrawal (§3.5), taking a candidate to `NOT_SELECTED` from `PROPOSED`, `DISCLOSED`, `CLEARED`, or `OBJECTED`, and promoting the single winner from `CLEARED` to `APPOINTED`.

### 3.4. The Strike-and-Rank List

Parties shape the candidate pool by striking and ranking. A `Party` casts a **Ranking** by supplying the target `candidate_id`, the acting `party_id`, an `action` of `STRIKE` or `RANK`, and — when the action is `RANK` — a `rank_value` of preference points (an integer of at least 1; it is ignored when the action is `STRIKE`, where higher values indicate stronger preference). A new ranking is `ACTIVE`. Casting a ranking recomputes the target candidate's derived signals and the acting party's strike counters.

Several gates protect the ranking list. The acting party must belong to the same case as the targeted candidate; if the ranking's `party_id` is not a party of the candidate's case, the request is rejected with `ERR_NOT_CASE_PARTY`. A party may not hold two active rankings on the same candidate; a second active ranking on a candidate the party has already ranked or struck is rejected with `ERR_DUPLICATE_RANKING`. And a strike may not exceed the party's allowance: if casting a strike would push the party's `strikes_used` beyond the case's `strikes_per_party`, it is rejected with `ERR_STRIKE_BUDGET_EXCEEDED`.

A candidate's `aggregate_rank_score` is the sum of the `rank_value` of every active `RANK` ranking targeting it (zero when there are none); a higher score means the candidate is more preferred. A candidate's `is_struck` is true whenever any active `STRIKE` ranking targets it. A party's `strikes_used` counts that party's active `STRIKE` rankings, and its `strikes_remaining` is the case's `strikes_per_party` less that count.

A `Party` may withdraw its own ranking, moving it from `ACTIVE` to `WITHDRAWN`; the acting `X-User-ID` must equal the ranking's `party_id`. `WITHDRAWN` is terminal for a ranking. Withdrawal is compensating: it recomputes the target candidate's `aggregate_rank_score` and `is_struck`, and recomputes the party's `strikes_used` and `strikes_remaining` — a withdrawn strike returns its allowance to the party.

### 3.5. Appointment of a Neutral

When vetting is complete, a `CaseAdministrator` appoints a neutral, moving the case from `SELECTION` to `APPOINTED`. Appointment is not a manual pick: the server runs a deterministic selector over the case's candidates. The eligible set is every candidate whose status is `CLEARED` and whose `is_struck` is false. If that set is empty, the appointment is rejected with `ERR_NO_ELIGIBLE_CANDIDATE`. Otherwise the winner is the eligible candidate with the highest `aggregate_rank_score`; ties are broken in favor of the earliest-created candidate (by `created_at` ascending), and because a wholly unranked pool ties at a score of zero, the earliest candidate wins by default. The candidate's `id` is never used as a tiebreaker. This appointment write also accepts `expected_case_version`; a mismatch against the case's current `version` is rejected with `ERR_STALE_VERSION`.

Appointment triggers a coordinated cascade. The winning candidate moves from `CLEARED` to `APPOINTED`. The case's `appointed_neutral_id` is set to that candidate's `neutral_id` — a plain reference to the appointed neutral, not an owned relationship. Every other candidate still open on the case — those in `PROPOSED`, `DISCLOSED`, `CLEARED`, or `OBJECTED` — is swept to `NOT_SELECTED`. And the case's `version` increments. From `APPOINTED`, the administrator advances the case to `HEARING`, a transition permitted only while the case's `appointed_neutral_id` is set (not null); this transition too increments the case's `version`.

### 3.6. Hearings and Scheduling Windows

Within a case, a `CaseAdministrator` schedules a **Hearing** by supplying its `hearing_type` — `PREHEARING`, `EVIDENTIARY`, or `MEDIATION_SESSION` — a `start_at` and `end_at` (ISO 8601 UTC instants defining a half-open interval `[start_at, end_at)`), and a `location` venue label. A new hearing is `SCHEDULED`, and the system records its `duration_hours` as the length of the interval in hours, which feeds the estimated-compensation projection of §3.2. Scheduling recomputes the case's `estimated_neutral_fee_cents`.

Three gates guard scheduling. The interval must be well formed: `end_at` must be strictly after `start_at`, otherwise `ERR_HEARING_END_BEFORE_START`. The hearing must give adequate notice: its `start_at` must be no earlier than the logical clock's current instant plus the seven-day notice window (`HEARING_NOTICE_DAYS`); a `start_at` earlier than that threshold is rejected with `ERR_HEARING_NOTICE_TOO_SHORT`. The hearing must not collide on the same case: if its half-open interval overlaps that of any other non-cancelled hearing on the same case, it is rejected with `ERR_HEARING_OVERLAP`. And it must respect the neutral's buffer: if the hearing falls within thirty minutes (`NEUTRAL_BUFFER_MINUTES`) of another hearing on any case that shares the same appointed neutral, it is rejected with `ERR_NEUTRAL_UNAVAILABLE`.

A `CaseAdministrator` marks a scheduled hearing `HELD` or `CANCELLED` (both terminal). Cancelling a hearing removes it from the scheduled set and therefore recomputes the case's `estimated_neutral_fee_cents`.

### 3.7. Document Exchanges

A `CaseAdministrator` sets a document-exchange deadline within a case by creating an **Exchange** with an `exchange_type` of `EXHIBITS`, `WITNESS_LIST`, or `BRIEFS` and a `due_at` submission deadline. A new exchange is `PENDING`, and its `submitted_at` is null until it is submitted.

Either a `Party` or a `CaseAdministrator` submits an exchange. Submission always stamps `submitted_at` with the logical clock's current instant, but the target state depends on timeliness: if the clock is at or before the exchange's `due_at`, the exchange becomes `SUBMITTED`; if the clock is past `due_at`, the same action instead lands the exchange in `LATE`. Both `SUBMITTED` and `LATE` are terminal.

### 3.8. Deposits, Fee Charges, and the Deposit Ledger

Funding a case runs through a deposit ledger. A `CaseAdministrator` requests a retainer by creating a **Deposit** with a `case_id` and an `amount_cents` greater than zero; a new deposit is `REQUESTED` with a null `paid_at`. A `Party` pays a requested deposit, moving it from `REQUESTED` to `PAID`; payment stamps `paid_at` with the logical clock and recomputes the case's `paid_deposit_cents` and `deposit_balance_cents`. After a case has reached `CLOSED`, a `CaseAdministrator` may refund a paid deposit, moving it from `PAID` to `REFUNDED` (terminal); a refund attempted while the case is not `CLOSED` is rejected with `ERR_INVALID_STATE`, and it too recomputes the case's `paid_deposit_cents` and `deposit_balance_cents`.

Neutral compensation is drawn against the retainer through fee charges. A `CaseAdministrator` posts a **FeeCharge** against a case by supplying the `neutral_id` — which must equal the case's `appointed_neutral_id` — the logged `hours` (greater than zero), and `expected_case_version`. The charge's `amount_cents` is computed as the logged `hours` multiplied by the neutral's `hourly_rate_cents`, rounded half up to whole cents. A new charge is `POSTED`. Posting is guarded three ways: the `expected_case_version` OCC check of §2.6 (mismatch is `ERR_STALE_VERSION`), and a fiscal gate — the charge's `amount_cents` must not exceed the case's current `deposit_balance_cents`, otherwise the post is rejected with `ERR_INSUFFICIENT_DEPOSIT`. Posting recomputes the case's `posted_fee_cents`, `actual_neutral_fee_cents`, and `deposit_balance_cents`, recomputes each party's `allocated_fee_share_cents`, and increments the case's `version`. A `CaseAdministrator` may reverse a posted charge, moving it from `POSTED` to `REVERSED` (terminal); reversal is compensating and recomputes the case's `posted_fee_cents`, `actual_neutral_fee_cents`, and `deposit_balance_cents` — returning the balance to its pre-charge value — and recomputes each affected party's `allocated_fee_share_cents`.

The case's `posted_fee_cents` is the sum of `amount_cents` across the case's charges whose status is `POSTED` (reversed charges are excluded), and its `actual_neutral_fee_cents` equals that same total. The case's `paid_deposit_cents` is the sum of `amount_cents` across the case's deposits whose status is `PAID`. The case's `deposit_balance_cents` is the paid deposits less the posted fees less the administrative fee, where the administrative fee is the case's `final_admin_fee_cents` when the case is in `AWARD_ISSUED` or `CLOSED` and zero otherwise.

The parties' shares of the posted fees are allocated by a pinned two-step procedure so that every cent is accounted for. Let the total be the case's `posted_fee_cents` and consider the parties ordered by `created_at` ascending. First, each party's base share is the total multiplied by that party's `share_pct` divided by 100, rounded **down** to whole cents. Second, the leftover — the total less the sum of all the floored base shares — is distributed one cent at a time to the parties in that same `created_at`-ascending order, giving one extra cent to each of the first several parties until the leftover is exhausted. The result is each party's `allocated_fee_share_cents`. This order is authoritative: flooring per party first and only then distributing the remainder avoids the drift that a divide-then-round-each approach would introduce.

### 3.9. Awards, Appeals, and Vacatur

A `CaseAdministrator` drafts an **Award** for a case that is in `HEARING`, supplying an `award_type` of `MONETARY`, `SETTLEMENT`, or `DISMISSAL` and an `award_amount_cents` (at least zero, defaulting to 0; a `DISMISSAL` carries 0). A new award is `DRAFT` with a null `issued_at`. A case may hold only one standing award: drafting a new award while the case already has an award in any status other than `VACATED` is rejected with `ERR_AWARD_EXISTS`.

Issuing an award moves it from `DRAFT` to `ISSUED`, permitted only while the case's status is `HEARING`, otherwise `ERR_INVALID_STATE`. Issuance stamps the award's `issued_at` with the logical clock (this anchors the appeal window) and bubbles the case forward from `HEARING` to `AWARD_ISSUED`. That bubble-up recomputes the case's `final_admin_fee_cents` from the awarded amount and re-derives its `deposit_balance_cents` — which now debits the administrative fee — and increments the case's `version`. The final administrative fee uses the same tier table and multipliers as the filing fee, but the tier is selected from the awarded `award_amount_cents` rather than the claimed amount: the tier is chosen by the same thresholds (below 1,000,000 cents is `TIER_1`; 1,000,000 up to but not including 7,500,000 is `TIER_2`; 7,500,000 up to but not including 50,000,000 is `TIER_3`; 50,000,000 or above is `TIER_4`, floors inclusive), the base for that tier (75,000, 175,000, 400,000, or 700,000 cents) is multiplied by the case-type multiplier (1.0 for `ARBITRATION`, 0.5 for `MEDIATION`) and the panel multiplier (1.5 when `panel_size` is 3, otherwise 1.0), and the product is rounded half up to whole cents. Because the tier is keyed on the award rather than the claim, `final_admin_fee_cents` diverges from `filing_fee_cents` whenever the award falls in a different tier than the claim.

Finalizing an award moves it from `ISSUED` to `FINAL` (terminal), permitted only when no appeal on that award is in `FILED` or `UNDER_REVIEW`, otherwise `ERR_INVALID_STATE`. Finalization bubbles the case from `AWARD_ISSUED` to `CLOSED`; the case-level guard mirrors the award guard — the case may close only when no appeal on its award is `FILED` or `UNDER_REVIEW`. Every case bubble-up increments the case's `version`.

A `Party` challenges an issued award by filing an **Appeal**, supplying the target `award_id` and a `ground` of `EVIDENT_PARTIALITY`, `EXCEEDED_POWERS`, or `PROCEDURAL`. The filing must fall within the appeal window: it is allowed only when the logical clock is within thirty days (`APPEAL_WINDOW_DAYS`) of the target award's `issued_at`, and a filing after that window is rejected with `ERR_APPEAL_WINDOW_CLOSED`. A new appeal is `FILED`; the system records the filer's identity in `filed_by_party_id` (the acting `X-User-ID`, a plain reference) and stamps `filed_at` with the logical clock.

A `CaseAdministrator` advances an appeal from `FILED` to `UNDER_REVIEW`, and from `UNDER_REVIEW` to either `GRANTED` or `DENIED` (both terminal). Granting an appeal triggers the vacatur cascade: the linked award (identified by the appeal's `award_id`) moves from `ISSUED` to `VACATED`, and that in turn bubbles the case from `AWARD_ISSUED` back to `HEARING` for re-arbitration. Returning to `HEARING` re-derives the case's `deposit_balance_cents` — the final administrative fee is no longer debited once the award is vacated — and increments the case's `version`. After a vacatur, the administrator may re-draft the vacated award from `VACATED` back to `DRAFT` (permitted while the case is in `HEARING`) so that a fresh award can be issued, closing the cycle.

## 4. Endpoint Definitions

Operations that create a new standalone resource or add a new record to a collection return `201 Created`. Operations that modify an existing resource — including transitions and other state-changing actions — return `200 OK`. Reads return `200 OK`. A generic transition endpoint (those whose path ends in `transition`) selects its target state through a `to_status` field in the request body, whose accepted values are the destination states described for that entity in §3. Readers must consult the §3 narratives to reconstruct each endpoint's request body, computed effects, and cascades; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/cases` | File a new case; computes fee tier and provisional filing fee | CaseAdministrator |
| GET | `/cases` | List cases (paginated; optional status filter) | CaseAdministrator, Party, Neutral |
| GET | `/cases/{id}` | Get a case | CaseAdministrator, Party, Neutral |
| POST | `/cases/{id}/transition` | Administrator-driven case status change (SELECTION, WITHDRAWN, HEARING) | CaseAdministrator |
| POST | `/cases/{id}/appoint` | Auto-select and appoint the top-ranked eligible candidate | CaseAdministrator |
| POST | `/parties` | Add a party to a case | CaseAdministrator |
| GET | `/cases/{id}/parties` | List parties of a case | CaseAdministrator, Party, Neutral |
| POST | `/neutrals` | Add a neutral to the panel roster | CaseAdministrator |
| GET | `/neutrals` | List roster (paginated; optional roster_status filter) | CaseAdministrator, Party, Neutral |
| GET | `/neutrals/{id}` | Get a neutral | CaseAdministrator, Party, Neutral |
| POST | `/neutrals/{id}/transition` | Change a neutral's roster_status | CaseAdministrator |
| POST | `/cases/{id}/candidates` | Add a neutral to the case's candidate list (OCC-guarded) | CaseAdministrator |
| GET | `/cases/{id}/candidates` | List candidates of a case | CaseAdministrator, Party, Neutral |
| GET | `/neutrals/{id}/candidates` | List candidacies of a neutral | CaseAdministrator, Party, Neutral |
| POST | `/candidates/{id}/disclose` | Neutral submits disclosure | Neutral |
| POST | `/candidates/{id}/transition` | Administrator clears / objects / disqualifies a candidate | CaseAdministrator |
| POST | `/rankings` | Party strikes or ranks a candidate | Party |
| GET | `/rankings` | List rankings (paginated; optional candidate_id / party_id filters) | CaseAdministrator, Party, Neutral |
| GET | `/rankings/{id}` | Get a ranking | CaseAdministrator, Party, Neutral |
| POST | `/rankings/{id}/withdraw` | Party withdraws its strike/rank | Party |
| POST | `/cases/{id}/hearings` | Schedule a hearing (notice / overlap / buffer checks) | CaseAdministrator |
| GET | `/cases/{id}/hearings` | List hearings of a case | CaseAdministrator, Party, Neutral |
| POST | `/hearings/{id}/transition` | Mark a hearing HELD or CANCELLED | CaseAdministrator |
| POST | `/cases/{id}/exchanges` | Create a document-exchange deadline | CaseAdministrator |
| GET | `/cases/{id}/exchanges` | List exchanges of a case | CaseAdministrator, Party, Neutral |
| POST | `/exchanges/{id}/submit` | Submit an exchange (SUBMITTED or LATE by clock vs due_at) | Party, CaseAdministrator |
| POST | `/deposits` | Request a retainer deposit for a case | CaseAdministrator |
| GET | `/deposits` | List deposits (paginated; optional case_id filter) | CaseAdministrator, Party, Neutral |
| GET | `/deposits/{id}` | Get a deposit | CaseAdministrator, Party, Neutral |
| POST | `/deposits/{id}/pay` | Pay a requested deposit | Party |
| POST | `/deposits/{id}/refund` | Refund a paid deposit (only after case CLOSED) | CaseAdministrator |
| POST | `/cases/{id}/fee-charges` | Post a neutral fee charge (OCC-guarded; fiscal gate) | CaseAdministrator |
| GET | `/fee-charges` | List fee charges (paginated; optional case_id / neutral_id filters) | CaseAdministrator, Party, Neutral |
| GET | `/fee-charges/{id}` | Get a fee charge | CaseAdministrator, Party, Neutral |
| POST | `/fee-charges/{id}/reverse` | Reverse a posted fee charge | CaseAdministrator |
| POST | `/cases/{id}/awards` | Draft an award/settlement for a case in HEARING | CaseAdministrator |
| GET | `/cases/{id}/awards` | List awards of a case | CaseAdministrator, Party, Neutral |
| POST | `/awards/{id}/transition` | Issue / finalize / re-draft an award | CaseAdministrator |
| POST | `/appeals` | File an appeal/vacatur petition against an issued award | Party |
| GET | `/appeals` | List appeals (paginated; optional award_id filter) | CaseAdministrator, Party, Neutral |
| GET | `/appeals/{id}` | Get an appeal | CaseAdministrator, Party, Neutral |
| POST | `/appeals/{id}/transition` | Advance an appeal (UNDER_REVIEW / GRANTED / DENIED) | CaseAdministrator |
| POST | `/_clock/set_current_utc` | Set the server logical clock | CaseAdministrator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_ENUM` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PARTIES_INCOMPLETE` | 409 |
| `ERR_NEUTRAL_NOT_ACTIVE` | 409 |
| `ERR_NEUTRAL_TYPE_MISMATCH` | 409 |
| `ERR_CANDIDATE_HAS_CONFLICT` | 409 |
| `ERR_NO_ELIGIBLE_CANDIDATE` | 422 |
| `ERR_STRIKE_BUDGET_EXCEEDED` | 409 |
| `ERR_DUPLICATE_RANKING` | 409 |
| `ERR_NOT_CASE_PARTY` | 409 |
| `ERR_INSUFFICIENT_DEPOSIT` | 402 |
| `ERR_HEARING_END_BEFORE_START` | 400 |
| `ERR_HEARING_NOTICE_TOO_SHORT` | 422 |
| `ERR_HEARING_OVERLAP` | 409 |
| `ERR_NEUTRAL_UNAVAILABLE` | 409 |
| `ERR_AWARD_EXISTS` | 409 |
| `ERR_APPEAL_WINDOW_CLOSED` | 422 |
| `ERR_PAGINATION_INVALID` | 400 |
