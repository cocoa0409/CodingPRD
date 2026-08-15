# Artist Management Commission API — Product Requirements Document

## 1. Introduction

An artist management firm lives or dies on the accuracy of its commission accounting. Touring guarantees, recording royalties, publishing income, and endorsement fees arrive on different schedules, under different agreements, and at different commission rates — and every dollar must be split correctly between the firm and the artist, net of recouped advances and reimbursable expenses, then presented on a statement the artist can trust, dispute, and audit. This document specifies the Artist Management Commission API: the system of record for a management firm's roster, agreements, deal pipeline, career calendar, income ledger, and statement production.

The API serves six kinds of users — firm administrators, agents, business managers, publicists, the artists themselves, and external auditors — with strict segregation of duties between the people who report money and the people who verify it. It models the commercial realities of the business: commission rates that step down during post-term "sunset" windows, advances that recoup out of incoming cash, expenses that route through tiered approvals, opportunities that are scored, negotiated, and converted into calendar bookings, and statements that carry balances forward period over period. A single logical clock drives every time-based transition, so the lifecycle of agreements, options, offers, dispute windows, and team assignments is deterministic.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two mandatory headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their capacity. The six roles are `FirmAdmin`, `Agent`, `BusinessManager`, `Publicist`, `Artist`, and `Auditor`. A request missing either header, or carrying an empty value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`; a request whose role is not in the endpoint's declared role list is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

Identity resolution differs by role. When `X-User-Role` is `Agent`, `BusinessManager`, or `Publicist`, `X-User-ID` is the `id` of the acting `TeamMember`; the server resolves that record, requires its `member_role` to match the presented role, and treats its `artist_id` as the caller's scope — ownership checks on any artist-scoped resource compare the resource's artist chain against that `artist_id`, and a mismatch is rejected with `ERR_ARTIST_ACCESS_DENIED`. Team-backed callers must additionally be in `ACTIVE` status: a `SUSPENDED` or `ENDED` member may not act, and attempts are rejected with `ERR_TEAM_MEMBER_INACTIVE`. When `X-User-Role` is `Artist`, `X-User-ID` is the `id` of the acting `Artist`, and the artist may touch only resources whose `artist_id` equals that id. When `X-User-Role` is `FirmAdmin` or `Auditor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `decided_by_user_id` on an `ApprovalRequest`) but never compares it to an entity's `id`.

These scoping rules apply to every artist-scoped endpoint — everything except creating an artist, listing the artist collection, and advancing the logical clock. Read endpoints are available to all six roles, with entity-backed callers restricted to their own artist's records.

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

List endpoints accept the query parameters `limit` and `offset`. `limit` specifies the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` specifies how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of list responses carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

All primary resources — Artist, Agreement, CommissionRateSchedule, IncomeEvent, Advance, Expense, ApprovalRequest, Opportunity, Engagement, Option, TeamMember, Statement, Dispute, and Audit — share four system-managed fields:

- `id` (string): a server-minted UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation.
- `version` (integer): starts at 1 and increments by one on every mutation of the resource.

`StatementLine` is the sole exception: statement lines carry only `id` and `created_at`; both `updated_at` and `version` are absent, because lines are append-only and never mutated after creation.

### 2.5. Money, Rates, and Rounding

All monetary amounts are integer cents carried in `..._cents` fields; the API never uses floating-point money. Commission rates and recoupment percentages are expressed in basis points, where 10000 basis points equal 100%. Commissions are computed per income event at verification time and rounded half up to whole cents at that moment; statements sum the pinned per-event values and never re-round or re-derive them. The pro-rata recoupment split uses floor for its share arithmetic, assigning the share remainder to the last eligible advance in order. Dates are compared as ISO calendar dates, and month arithmetic is calendrical — adding one month to 2027-01-31 yields 2027-02-28. Datetime comparisons for exercise windows and engagement windows are made at second precision, without fractional microseconds.

### 2.6. The Logical Clock

Every temporal rule in the system — sunset windows, offer expiries, option exercise windows, dispute windows, deemed acceptance, team assignment windows — reads a single logical clock, never wall-clock time. At startup the clock reads exactly 2026-08-01T00:00:00Z. A `FirmAdmin` advances it through the clock-driving capability by supplying `to_iso8601`, which must be at or after the current logical time; a regression is rejected with `ERR_INVALID_REQUEST`.

Advancing the clock runs a sweep that applies every time-driven transition due at the new instant. Active agreements whose term has ended move `ACTIVE → EXPIRED` and, within the same sweep, agreements in `EXPIRED`, `TERMINATED`, or `SUPERSEDED` move on to `SUNSET` or `CLOSED` depending on their sunset window; `SUNSET` agreements past their sunset end move to `CLOSED`. `OPEN` options past their exercise window move to `LAPSED`. Opportunities still in `RECEIVED`, `UNDER_EVALUATION`, or `NEGOTIATING` once the clock date passes their offer expiry move to `EXPIRED`, cancelling their pending approval requests. `ISSUED` statements whose dispute window has lapsed with no active dispute move to `ACKNOWLEDGED` (deemed acceptance). Team members whose `window_end_date` has passed move to `ENDED`. The sweep response reports per-category counts under the keys `agreements_expired`, `agreements_sunset`, `agreements_closed`, `options_lapsed`, `opportunities_expired`, `statements_acknowledged`, and `team_members_ended`.

### 2.7. Validation Order and Error Precedence

When a request violates several rules at once, the server reports the earliest failure in a fixed evaluation order:

1. Header presence — both `X-User-ID` and `X-User-Role` present and non-empty (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. Role membership — the presented role appears in the endpoint's declared role list (`ERR_FORBIDDEN_FOR_ROLE`).
3. Artist scoping — entity-backed callers resolve to a team member (or the artist) serving the target resource's artist (`ERR_ARTIST_ACCESS_DENIED`).
4. Team-member status — entity-backed team callers are `ACTIVE` (`ERR_TEAM_MEMBER_INACTIVE`).
5. Request-body shape — required fields present, types valid, enum values in range, amounts positive where required, window end later than start (`ERR_INVALID_REQUEST`).
6. Path existence — every path identifier resolves to an existing resource (`ERR_NOT_FOUND`).
7. Body references — body-supplied foreign keys such as `artist_id`, `agreement_id`, `statement_id`, `linked_engagement_id`, `parent_event_id`, `opportunity_id`, `source_opportunity_id`, and `engagement_id` resolve to existing resources (`ERR_INVALID_REFERENCE`).
8. State-machine preconditions — the target is in a state from which the requested transition exists (`ERR_INVALID_STATE`, including its specialized forms such as `ERR_EVENT_ALREADY_SETTLED` and `ERR_EXPENSE_NOT_REJECTED`).
9. Optimistic concurrency — the expected-version field matches the parent's current `version` (the stale-version rules of §2.8).
10. Segregation of duties — the approver or verifier is not the submitter or reporter (`ERR_SEGREGATION_OF_DUTIES`); this guards exactly three operations: approving an approval request, rejecting an approval request, and verifying an income event.
11. Temporal guards — option exercise windows, offer expiry, engagement window guards, dispute and audit windows, statement periods in the future (`ERR_OPTION_WINDOW_VIOLATION`, `ERR_OFFER_EXPIRED`, `ERR_ENGAGEMENT_WINDOW_PAST`, `ERR_ENGAGEMENT_NOT_ENDED`, `ERR_DISPUTE_WINDOW_CLOSED`, `ERR_AUDIT_WINDOW_CLOSED`, `ERR_STATEMENT_PERIOD_FUTURE`).
12. Cross-entity state gates — archived artists, missing covering agreements, non-commissionable agreement postures, missing rate schedules, unaccepted opportunities, missing artist approval, open prior statements, unresolved disputes, invalid adjustment parents (`ERR_ARTIST_ARCHIVED`, `ERR_NO_COVERING_AGREEMENT`, `ERR_AGREEMENT_NOT_ACTIVE`, `ERR_NO_RATE_SCHEDULE`, `ERR_OPPORTUNITY_NOT_ACCEPTED`, `ERR_ARTIST_APPROVAL_REQUIRED`, `ERR_PRIOR_STATEMENT_OPEN`, `ERR_DISPUTE_NOT_RESOLVED`, `ERR_ADJUSTMENT_PARENT_INVALID`).
13. Uniqueness and overlap — rate-schedule windows, buffered engagement windows, statement periods, one active dispute per statement, one non-closed audit per statement (`ERR_RATE_SCHEDULE_OVERLAP`, `ERR_ENGAGEMENT_OVERLAP`, `ERR_STATEMENT_PERIOD_OVERLAP`, `ERR_DISPUTE_ALREADY_ACTIVE`, `ERR_AUDIT_ALREADY_ACTIVE`).
14. Monetary limits last — approver authority caps and settlement amount ranges (`ERR_APPROVAL_AUTHORITY_EXCEEDED`, `ERR_AMOUNT_OUT_OF_RANGE`).

### 2.8. Optimistic Concurrency Control

Three write operations require the client to prove it has observed the current state of the record it acts against by carrying an expected-version field. A mismatch between the supplied value and the record's current `version` means the client's view is stale — for example, another writer has since activated a different agreement for the same artist, or countered the offer — and the request is rejected without side effects:

- Creating an agreement (`POST /agreements`) requires `expected_artist_version`, compared against the artist's current `version`; a mismatch is rejected with `ERR_STALE_ARTIST_VERSION` (HTTP 412).
- Editing an agreement (`PATCH /agreements/{id}`) requires `expected_agreement_version`, compared against the agreement's current `version`; a mismatch is rejected with `ERR_STALE_AGREEMENT_VERSION` (HTTP 412).
- Recording a counter-offer (`POST /opportunities/{id}/counter-offer`) requires `expected_opportunity_version`, compared against the opportunity's current `version`; a mismatch is rejected with `ERR_STALE_OPPORTUNITY_VERSION` (HTTP 412).

Endpoints not listed here do not take a version field.

### 2.9. Cascading Mutations and the Artist Aggregate Ledger

A single API call may mutate several records in ordered hops — settling one income event can touch the event, several advances, the artist, and a linked engagement. Every mutated record refreshes its `updated_at` and increments its `version`, including records the client did not name directly.

Four computed aggregates on the Artist form the firm's standing ledger for that artist, recomputed by the workflows of §3:

- `unrecouped_advance_balance_cents` — the sum of `outstanding_cents` over the artist's advances in `ACTIVE` status.
- `lifetime_gross_cents` — the sum of `gross_amount_cents` over the artist's income events that are not `VOIDED`.
- `lifetime_commission_cents` — the sum of `commission_amount_cents` over the artist's income events in `VERIFIED`, `SETTLED`, or `POSTED` status.
- `lifetime_disbursed_cents` — the sum of `disbursed_cents` over the artist's `FINALIZED` statements.

Whenever a workflow recomputes any of these aggregates, the Artist's `version` increments by one and `updated_at` refreshes — so an artist's version advances as a side effect of agreement activations, verifications, settlements, write-offs, amendments, and disbursements. That is exactly the movement the agreement-creation concurrency guard of §2.8 keys on.

## 3. Business Logic & Workflows

### 3.1. Building the Roster: Artists and Their Teams

A `FirmAdmin` onboards an artist by supplying `stage_name`, `legal_name`, and `primary_genre`; `home_currency` is optional and defaults to `USD`. The artist is born `ACTIVE` with `version` 1, and `current_agreement_id` stays null until an agreement activates. Administrators may later update `stage_name` or `home_currency`, or move the artist between operational states: an `ACTIVE` artist can be placed `ON_HIATUS` and later returned to `ACTIVE`, and an artist in either `ACTIVE` or `ON_HIATUS` can be moved to the terminal `ARCHIVED` state. A request to make a transition the current state does not support is rejected with `ERR_INVALID_STATE`; each successful transition increments the artist's `version`.

Archiving is a hard stop for new business: for an `ARCHIVED` artist, the system rejects new income events, expenses, opportunities, engagements, options, agreements, advances, and statement generation with `ERR_ARTIST_ARCHIVED`. Archiving also cascades downward — every team member of the artist in `ACTIVE` or `SUSPENDED` status is moved to `ENDED`. Two doors stay open: disputes and audits on statements that already exist remain openable, because audit rights survive archiving.

Each artist is served by a team. A `FirmAdmin` assigns a team member with `artist_id`, a `member_role` of `AGENT`, `BUSINESS_MANAGER`, or `PUBLICIST`, a `display_name`, and a `window_start_date`; `window_end_date` is optional, and null means the assignment is open-ended. A business manager's spending authority is bounded by `authority_expense_cap_cents`, which defaults to 100000 cents ($1,000) and is meaningful only for the `BUSINESS_MANAGER` member role. Members are born `ACTIVE`; an administrator may suspend an active member (`ACTIVE → SUSPENDED`), resume a suspended one (`SUSPENDED → ACTIVE`), or end an assignment from either state (`→ ENDED`), and the clock sweep ends assignments whose `window_end_date` has passed. Wrong-state transitions are rejected with `ERR_INVALID_STATE`. Team assignments can be listed and filtered by `artist_id`, `member_role`, and `status`.

### 3.2. Management Agreements, Rate Schedules, and the Sunset Window

A management agreement begins life in `DRAFT`. A `FirmAdmin` creates one by supplying `artist_id`, `term_start_date`, and `term_end_date` (the term is inclusive at both ends), plus two optional policy selectors: `touring_commission_base` (`GROSS` or `NET_OF_EXPENSES`, default `GROSS`) and `recoupment_policy` (`FIFO` or `PRO_RATA`, default `FIFO`). Creation carries the concurrency guard `expected_artist_version` (§2.8) and itself increments the artist's `version`. While an agreement remains `DRAFT`, an administrator may edit its term dates and both policy selectors; once `ACTIVE`, the only permitted edit is extending `term_end_date` to a later date, and edits attempted in any other state are rejected with `ERR_INVALID_STATE`. Every edit carries `expected_agreement_version` and increments the agreement's `version`. Agreements can be listed by `artist_id`, `prior_agreement_id`, and `status`, which exposes the self-referential supersede chain: `prior_agreement_id` points at the agreement this one replaced, or null for the artist's first.

Activation is the pivotal transition. Activating a `DRAFT` agreement requires the artist not to be `ARCHIVED` (`ERR_ARTIST_ARCHIVED`) and at least one rate schedule to exist for the agreement — an activation attempt with zero schedules fails with `ERR_NO_RATE_SCHEDULE`. If the artist already has an `ACTIVE` agreement, activation supersedes it: the old agreement moves to `SUPERSEDED`, its sunset window opens at that day's clock date, and the new agreement's `prior_agreement_id` records it. The artist's `current_agreement_id` is updated to the newly active agreement, and the artist's `version` increments.

An `ACTIVE` agreement ends in one of two ways. A `FirmAdmin` may terminate it early by supplying `termination_date`; the agreement moves to `TERMINATED`, `current_agreement_id` is cleared, and the artist's `version` increments. Alternatively, the clock sweep moves an agreement whose term has ended — clock date later than `term_end_date` — from `ACTIVE` to `EXPIRED`, again clearing `current_agreement_id`. Either way, a **sunset window** opens: `sunset_start_date` is the day after `termination_date` for a terminated agreement, the day after `term_end_date` for an expired one, or the supersede date for a superseded one; it stays null while the agreement is `DRAFT` or `ACTIVE`. `sunset_end_date` is `sunset_start_date` plus the largest `sunset_months` found among the agreement's rate schedules, minus one day; when that maximum is zero, `sunset_end_date` is null and there is no sunset window at all.

From `EXPIRED`, `TERMINATED`, or `SUPERSEDED`, the same sweep then moves the agreement to `SUNSET` when a sunset window exists and the clock date is on or before `sunset_end_date`, and to `CLOSED` when there is no window or the window has passed; a `SUNSET` agreement later moves to `CLOSED` once the clock date passes `sunset_end_date`. `SUNSET` is a commission posture, not a freeze: income recognized inside the sunset window remains verifiable at sunset rates. `DRAFT` and `CLOSED` are the two non-commissionable postures, and `CLOSED` is terminal.

Commission rates are effective-dated. A `FirmAdmin` or `BusinessManager` creates a rate schedule with `agreement_id`, an `income_type` of `TOURING`, `RECORDING`, `PUBLISHING`, or `ENDORSEMENT`, `in_term_rate_bps` and `sunset_rate_bps` (each between 0 and 10000, and the sunset rate may not exceed the in-term rate), `sunset_months` (zero or more), and `effective_from_date`; `effective_to_date` is optional, must be later than `effective_from_date` when set, and null means the window is open-ended. A schedule has no status field — its lifecycle is its half-open effective window: it covers a recognition date that is on or after `effective_from_date` and, when an end is set, strictly before `effective_to_date`. Windows for the same agreement and income type must not overlap: a new window conflicts with an existing one when the new start falls before the existing end (or the existing window is open-ended) and the existing start falls before the new end (or the new window is open-ended). Pure adjacency — one window's start equalling the other's end — is allowed. A conflict is rejected with `ERR_RATE_SCHEDULE_OVERLAP`. Closing a schedule pins its `effective_to_date` and re-validates the same overlap rule. Schedules can be listed by `agreement_id` and `income_type`.

### 3.3. The Opportunity Pipeline: Evaluation, Negotiation, and Artist Approval

An `Agent` registers an incoming offer with `artist_id`, `income_type`, `counterparty_name`, `proposed_value_cents` (greater than zero), `offer_expiry_date`, a proposed engagement window from `proposed_window_start` to `proposed_window_end` (the end must be later than the start), and a subjective `fit_score` between 0 and 100. The opportunity is born `RECEIVED`, with `current_value_cents` initialized to `proposed_value_cents` and `round_number` at 0.

Evaluation, performed by an `Agent` or `BusinessManager`, moves the opportunity from `RECEIVED` to `UNDER_EVALUATION`; evaluating an opportunity already under evaluation refreshes its numbers in place without changing state. Evaluation pins two outputs, `evaluation_score` and `recommendation`, from three components. The **financial component** compares the offer against the artist's trailing average gross for the same income type: the trailing window is the 365 days ending on the clock date, inclusive of both ends, taken over the artist's income events of that income type in `SETTLED` or `POSTED` status with `received_date` inside the window — verified-but-unsettled events do not count. When no such events exist the average is null and the financial component defaults to a neutral 50; otherwise the component is the smaller of 100 and 50 times `current_value_cents` divided by that average, with the average computed as the sum of `received_amount_cents` over the count, rounded half up, and the component's division also rounded half up. The **availability component** inspects the artist's engagements whose plain, unbuffered windows intersect the proposed window as closed intervals: 0 when any conflicting engagement is `CONFIRMED`, 50 when the only conflicts are `HOLD`, and 100 when the calendar is clear. The final score is 0.5 times the financial component plus 0.3 times `fit_score` plus 0.2 times the availability component, rounded half up to an integer at this final weighted step only. A score of at least 70 recommends `PURSUE`; a score of at least 40 recommends `CONSIDER`; anything lower recommends `PASS_SUGGESTED`.

Opening negotiation moves `UNDER_EVALUATION → NEGOTIATING` and requires the offer not to have lapsed — the clock date must be on or before `offer_expiry_date`, or the request fails with `ERR_OFFER_EXPIRED`. High-value deals need the artist's signature: `requires_artist_approval` is true exactly when `current_value_cents` exceeds 10000000 cents ($100,000). Entering negotiation at a value above that threshold raises a `PENDING` approval request requiring the `ARTIST` approver, unless one already pending or approved exists for the opportunity.

Counter-offers keep the negotiation cycling. Recording one requires the opportunity to be `NEGOTIATING`, a positive `new_value_cents` (`ERR_INVALID_REQUEST` otherwise), an unexpired offer, and the concurrency guard `expected_opportunity_version` (§2.8). The movement band is measured as the absolute difference between `new_value_cents` and `current_value_cents`, divided by `current_value_cents`: a change of at most ten percent keeps the opportunity in `NEGOTIATING`, while a larger change loops it back to `UNDER_EVALUATION` — and exactly ten percent stays in `NEGOTIATING`, because the band boundary is inclusive of ten percent on the stay side. Either branch writes `current_value_cents` to the new value, adds one to `round_number`, and increments the opportunity's `version`; a change that newly crosses the approval threshold raises the artist approval request. On the loop-back branch the score is deliberately not recomputed — a fresh evaluation must be requested to refresh `evaluation_score` and `recommendation`.

Acceptance, by an `Agent`, is allowed from `UNDER_EVALUATION` or `NEGOTIATING` and requires three things: a prior evaluation (`evaluation_score` must not be null — accepting unevaluated is rejected with `ERR_INVALID_STATE`), an unexpired offer (`ERR_OFFER_EXPIRED`), and, when `requires_artist_approval` is true, an existing `APPROVED` approval request from the artist (`ERR_ARTIST_APPROVAL_REQUIRED`). Approval requests targeting opportunities are consumed rather than state-driving: approving one does not itself move the opportunity — acceptance merely checks that an approved request exists — and rejecting one leaves the opportunity unchanged, so the agent may keep negotiating.

An accepted offer becomes real through conversion, which requires `proposed_window_end` still to be in the future (`ERR_ENGAGEMENT_WINDOW_PAST`), because the engagement is born `CONFIRMED` and the confirm-time temporal guard applies at creation. Conversion creates the engagement with the proposed window, a `travel_buffer_hours` of 24, `guarantee_cents` equal to the negotiated `current_value_cents`, `opportunity_id` pointing back at the opportunity, and `confirmed_at` stamped from the clock; the opportunity records the result in `converted_engagement_id` and moves to `CONVERTED`. The new engagement runs the buffered overlap check of §3.4 — a conflict fails the whole conversion with `ERR_ENGAGEMENT_OVERLAP` — and otherwise releases competing holds and withdraws their opportunities as described there. Conversion returns the newly created engagement.

Every exit from the pipeline cancels its paperwork. Declining (the agent's choice) or withdrawing (the counterparty pulls the offer, or the calendar cascade of §3.4 takes the slot away) is possible from `RECEIVED`, `UNDER_EVALUATION`, or `NEGOTIATING`, moving the opportunity to `DECLINED` or `WITHDRAWN` and cancelling any of its pending approval requests. The clock sweep expires opportunities still in one of those three states once the clock date passes `offer_expiry_date`, likewise cancelling pending requests. Opportunities can be listed by `artist_id`, `income_type`, `status`, and `converted_engagement_id`.

### 3.4. The Career Calendar: Engagements, Holds, and Contract Options

The calendar distinguishes tentative holds from firm bookings. An `Agent` places a hold by creating an engagement with `artist_id`, `income_type`, `counterparty_name`, `start_datetime`, `end_datetime` (later than the start), and `guarantee_cents` (zero or more); `travel_buffer_hours` is optional, defaults to 24, and may not be negative, and `opportunity_id` is optional, tying the hold to a pipeline entry. Engagements created this way are born in `HOLD`, and holds never block anything by themselves.

Confirmation is where the calendar enforces itself. Confirming requires the engagement to be in `HOLD` (`ERR_INVALID_STATE` otherwise), its `end_datetime` still in the future (`ERR_ENGAGEMENT_WINDOW_PAST`), and — when `opportunity_id` is set — the linked opportunity to be `ACCEPTED` or `CONVERTED` (`ERR_OPPORTUNITY_NOT_ACCEPTED`). The **buffered overlap rule** extends every engagement's window by its `travel_buffer_hours` on both sides, then rejects the confirmation with `ERR_ENGAGEMENT_OVERLAP` when another `CONFIRMED` engagement of the same artist has a buffered window that strictly intersects it — the candidate's buffered start falls before the existing one's buffered end, and the existing one's buffered start falls before the candidate's buffered end; windows that merely touch at the buffered edge do not conflict. On success, `confirmed_at` is stamped from the clock and the cascade runs the other way: every overlapping `HOLD` engagement of the same artist is `RELEASED`, and a released hold whose `opportunity_id` points at an opportunity still in `RECEIVED`, `UNDER_EVALUATION`, or `NEGOTIATING` drives that opportunity to `WITHDRAWN` (cancelling its pending approval requests).

After the engagement ends — the clock at or past `end_datetime`, with earlier attempts rejected as `ERR_ENGAGEMENT_NOT_ENDED` — an `Agent` or `BusinessManager` marks it `COMPLETED`. Settlement then follows the money: when an income event whose `linked_engagement_id` points at a `COMPLETED` engagement settles (§3.5), the engagement moves to its terminal `SETTLED` state. Cancellation is available from `HOLD` or `CONFIRMED` but is blocked with `ERR_ENGAGEMENT_HAS_INCOME` when a linked income event has already reached `VERIFIED`, `SETTLED`, or `POSTED`. `RELEASED` is reachable only through the confirmation, conversion, and exercise cascades, never directly. Engagements can be listed by `artist_id`, `opportunity_id`, and `status`.

Contract options give the artist a bounded right to future work. An `Agent` or `FirmAdmin` creates one on an `ACTIVE` agreement with `artist_id`, `agreement_id`, an `option_type` of `RECORDING_CYCLE`, `ENDORSEMENT_RENEWAL`, `TOUR_LEG`, or `MERCHANDISE`, the `income_type` of the eventual engagement, an exercise window from `exercise_window_start` to `exercise_window_end` (end later than start), the engagement window `engagement_start_datetime` to `engagement_end_datetime` (likewise later than its start), `exercise_value_cents` (greater than zero), and optionally `source_opportunity_id` recording the negotiation the option came from. Options are born `OPEN`.

Exercising an option, an `Agent`-only action, is allowed only while the clock instant is at or after `exercise_window_start` and at or before `exercise_window_end` — both bounds inclusive; violations are rejected with `ERR_OPTION_WINDOW_VIOLATION`. The referenced agreement must still be `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE`), and `engagement_end_datetime` must still be in the future (`ERR_ENGAGEMENT_WINDOW_PAST`), because the new engagement is born `CONFIRMED`. Exercise creates that engagement with the option's engagement window, a 24-hour travel buffer, `guarantee_cents` equal to `exercise_value_cents`, the option's `income_type`, and `confirmed_at` from the clock; `exercised_engagement_id` records the result. The same buffered overlap rule applies: a conflict fails the exercise wholesale with `ERR_ENGAGEMENT_OVERLAP`, and otherwise overlapping holds are released and their open opportunities withdrawn. An option can instead be given up — waived to `WAIVED` by the `Artist` or a `FirmAdmin` — and the clock sweep lapses `OPEN` options once the clock passes `exercise_window_end`, moving them to `LAPSED`. Options can be listed by `artist_id`, `agreement_id`, `source_opportunity_id`, `exercised_engagement_id`, and `status`.

### 3.5. Income Reporting, Verification, and Settlement

Income enters the ledger when an `Agent` or `BusinessManager` reports an income event with `artist_id`, `income_type`, `gross_amount_cents` (greater than zero), `recognition_date` — the date the income was earned, which drives rate selection — and `source_name`, the payer. Two optional fields shape linkage and corrections: `linked_engagement_id` marks the event as the payout of a booked engagement, and `kind`, defaulting to `ORIGINAL`, may be `ADJUSTMENT` for corrections, in which case `parent_event_id` must point at an event already in `SETTLED` or `POSTED` — a missing parent or a parent in any other state is rejected with `ERR_ADJUSTMENT_PARENT_INVALID`. The event is born `REPORTED`, and `reported_by_user_id` captures the caller for segregation of duties. At creation the server resolves and pins `agreement_id`: among the artist's agreements whose `term_start_date` is on or before the recognition date, the one with the greatest `term_start_date` wins, with ties broken by the earliest `created_at`. Resolution ignores agreement status entirely — an agreement whose sunset window has already passed for this income type still resolves, and the event simply verifies as exempt. When no agreement qualifies, creation fails with `ERR_NO_COVERING_AGREEMENT`.

Verification is the `BusinessManager`'s desk and is deliberately separated from reporting: the caller's identity must differ from `reported_by_user_id`, or the request is rejected with `ERR_SEGREGATION_OF_DUTIES`. Verification requires the event to be `REPORTED` (`ERR_INVALID_STATE` otherwise), the resolved agreement to be in a commissionable posture — `ACTIVE`, `SUPERSEDED`, `TERMINATED`, `EXPIRED`, or `SUNSET`, with `DRAFT` and `CLOSED` rejected as `ERR_AGREEMENT_NOT_ACTIVE` — and a rate schedule for the agreement and income type whose effective window covers the recognition date (`ERR_NO_RATE_SCHEDULE`).

Verification pins the rate. The agreement's effective end is its recorded `termination_date` whenever one is present — termination stamps `termination_date` and nothing ever clears it, so it still governs after the agreement has moved on from `TERMINATED` to `SUNSET` — and otherwise its `term_end_date`. The covering schedule is the unique one matching the agreement and income type whose half-open window contains `recognition_date`, and its id is pinned to `applied_schedule_id`. When the recognition date is on or before the effective end, `term_relation` is `IN_TERM` and `applied_rate_bps` is the schedule's `in_term_rate_bps`. Otherwise the sunset test runs: the sunset end for this income type is the effective end plus the schedule's `sunset_months` calendar months (calendrical arithmetic — a month added to January 31 lands on February 28), and the event is inside the window when its recognition date is on or before that sunset end. The deal itself counts as in-term when the event has no `linked_engagement_id`, or when the linked engagement's `confirmed_at` date-part is on or before the effective end. Only when both conditions hold does the event take `term_relation` `SUNSET` at the schedule's `sunset_rate_bps`; otherwise it is `POST_TERM_EXEMPT` with an `applied_rate_bps` of 0.

The commission itself is computed once, per event, and never re-derived. The base is `gross_amount_cents`, with one variant: when the agreement's `touring_commission_base` is `NET_OF_EXPENSES` and the event is a `TOURING` event linked to an engagement, the base is reduced by the sum of `amount_cents` over that engagement's expenses in `APPROVED` or `REIMBURSED` status — pending and rejected expenses are excluded — and the result is floored at zero. `commission_amount_cents` is the base times `applied_rate_bps`, divided by 10000, rounded half up to whole cents, and `artist_net_cents` is `gross_amount_cents` minus the commission. For a concrete reading: a gross of 200000 with 30000 of approved engagement expenses and a 1500-basis-point rate yields a commission of 30000 under `GROSS` but 25500 under `NET_OF_EXPENSES`. Verification also recomputes the artist's `lifetime_commission_cents` and increments the artist's `version`.

Settlement records the cash. Settling — again a `BusinessManager` action — is allowed from `VERIFIED` or `POSTED` and takes `received_date` and `received_amount_cents`; the received amount must be greater than zero, no greater than `gross_amount_cents`, and no less than `commission_amount_cents`, or the request fails with `ERR_AMOUNT_OUT_OF_RANGE`. Settlement writes both fields, runs the recoupment waterfall of §3.6, and records the event's `recouped_amount_cents` and `artist_payable_cents` — the latter being the cash share minus what was recouped. The cascade continues outward: any advance whose outstanding balance reaches zero flips to `RECOUPED`, the artist's aggregates are recomputed with a `version` increment, and when the event is linked to a `COMPLETED` engagement that engagement moves to `SETTLED`. Cash that arrives after an accrual posting does not reopen the issued statement: settling a `POSTED` event leaves its status at `POSTED` — the status latches — while the settlement fields and the recoupment run identically, and the recoup line flows onto the next generated statement because `recoup_statement_id` remains null until a statement sweeps it.

Voiding corrects mistakes, but only early ones. A `REPORTED` event can be voided, which recomputes `lifetime_gross_cents`; a `VERIFIED` event can be voided, which recomputes both lifetime aggregates and increments the artist's `version`. An event that has reached `SETTLED` or `POSTED` can never be voided — the attempt fails with `ERR_EVENT_ALREADY_SETTLED`, and corrections must instead be filed as an `ADJUSTMENT` child event. Income events can be listed by `artist_id`, `agreement_id`, `linked_engagement_id`, `parent_event_id`, `statement_id`, `recoup_statement_id`, `applied_schedule_id`, `status`, and `income_type`.

### 3.6. Advances and the Recoupment Waterfall

A `BusinessManager` or `FirmAdmin` issues a recoupable advance with `artist_id`, `principal_cents` (greater than zero), and `issued_date`, which serves as the waterfall's ordering key. Two optional fields shape recovery: `recoup_pct_bps`, the share of each settling event's cash applied to this advance, defaulting to 10000 (100 percent) and bounded between 1 and 10000; and `applies_to_income_types`, defaulting to empty — an empty list means the advance is cross-collateralized against all four income types, while a non-empty list restricts recoupment to the listed types. The advance is born `ACTIVE` with `recouped_cents` and `written_off_cents` at 0 and `outstanding_cents` equal to `principal_cents` minus those two counters; issuing recomputes the artist's `unrecouped_advance_balance_cents` and increments the artist's `version`.

The waterfall runs inside every income settlement. The **cash share** is `received_amount_cents` minus `commission_amount_cents`. Eligible advances are the artist's `ACTIVE` advances whose `applies_to_income_types` is empty or contains the event's income type, walked in order of `issued_date` ascending with ties broken by `created_at` ascending — never by id.

Under the `FIFO` policy the oldest advance eats first: each advance in order takes the smaller of its `outstanding_cents` and the remaining cash share times its `recoup_pct_bps` divided by 10000, rounded half up; the take reduces both the advance's outstanding and the remaining share, and the walk stops when nothing remains. With a cash share of 80000, advance A outstanding 50000 at 100% takes 50000, then advance B outstanding 60000 at 50% takes 15000, for a total recouped of 65000. Under the `PRO_RATA` policy, nothing is recouped when the eligible outstanding total is zero; otherwise each advance's raw share is the cash share times its `outstanding_cents` divided by the total outstanding, rounded down — except the last advance in order, which receives the remainder of the cash share after the earlier shares — and each advance then applies the smaller of its outstanding and its raw share times its `recoup_pct_bps` divided by 10000, rounded half up. With the same inputs, A's raw share is 36363 applied in full, while B's raw share is 43637 of which 21819 applies at 50%, for a total recouped of 58182.

In both policies an advance whose `outstanding_cents` reaches zero through the waterfall moves from `ACTIVE` to `RECOUPED`; the event's `recouped_amount_cents` is the total taken, and `artist_payable_cents` is the cash share minus it. A `FirmAdmin` may instead forgive an advance: writing off requires `ACTIVE` status with a positive outstanding balance — a wrong state or a zero balance fails with `ERR_INVALID_STATE` — and it moves the full `outstanding_cents` into `written_off_cents`, zeroes the outstanding (preserving the identity that principal equals recouped plus outstanding plus written-off), and moves the advance to `WRITTEN_OFF`, recomputing the artist's aggregate and incrementing the artist's `version`. Advances can be listed by `artist_id` and `status`.

### 3.7. Expense Reimbursement and Approval Routing

Any member of the artist's working team — `Agent`, `BusinessManager`, or `Publicist` — may file a reimbursable expense with `artist_id`, a `category` of `TRAVEL`, `PRODUCTION`, `MARKETING`, `LEGAL`, or `OTHER`, `amount_cents` (greater than zero), `incurred_date`, and a free-text `description`; an optional `engagement_id` ties production costs to a booking, which is what feeds the `NET_OF_EXPENSES` commission base of §3.5. The expense is born `PENDING_APPROVAL`, `submitted_by_user_id` captures the filer, and approval routing immediately raises one `PENDING` approval request per required approver.

Routing tiers key off the amount, with inclusive upper bounds: an amount up to and including 100000 cents ($1,000) needs only a `BUSINESS_MANAGER`; above that, up to and including 1000000 cents ($10,000), it needs the `BUSINESS_MANAGER` and the `ARTIST`; above that it needs all three of `BUSINESS_MANAGER`, `ARTIST`, and `FIRM_ADMIN`. Exactly 100000 cents therefore routes to the business manager alone, and exactly 1000000 adds the artist but not the firm administrator.

Each approval request records `artist_id` (copied from the target for scoping), a `target_type` of `EXPENSE` or `OPPORTUNITY`, a polymorphic `target_id` resolved through that type, the `required_approver`, the `requested_by_user_id` whose action raised it, and a `decided_by_user_id` that stays null while the request is `PENDING`. Deciding a request requires the caller's role to match the `required_approver` — a business-manager request needs a `BusinessManager` team member, an artist request needs the `Artist` themself acting on their own behalf, a firm-admin request needs a `FirmAdmin` — and mismatches fail with `ERR_FORBIDDEN_FOR_ROLE`. The decider must not be the raiser (`ERR_SEGREGATION_OF_DUTIES`), and a `BusinessManager` deciding an expense request may approve only amounts up to their own `authority_expense_cap_cents`; beyond the cap the approval fails with `ERR_APPROVAL_AUTHORITY_EXCEEDED`. Both decisions accept an optional `decision_note`. Approval stamps `decided_by_user_id`, and when the last pending request for an expense is approved the expense moves to `APPROVED`. Rejection moves the expense to `REJECTED`, copies the rejecting request's `decision_note` into the expense's `rejection_note`, and cancels the sibling pending requests.

A rejected expense is not dead: resubmission — open to the same three filing roles — requires the `REJECTED` state (anything else fails with `ERR_EXPENSE_NOT_REJECTED`) and may carry a new `amount_cents` and/or `description`; routing re-runs against the possibly new amount, and a fresh set of approval requests is created. Reimbursement itself happens on the statement: when a statement is issued, the artist's `APPROVED` expenses with `incurred_date` on or before the period end that have not been reimbursed before are swept on as `EXPENSE_REIMBURSEMENT` lines, and each swept expense moves to the terminal `REIMBURSED` state with `reimbursed_statement_id` recording the statement. Expenses can be listed by `artist_id`, `engagement_id`, `reimbursed_statement_id`, and `status`; approval requests by `artist_id`, `target_type`, `target_id`, `required_approver`, and `status`. Requests are cancelled wholesale when their target is withdrawn, declined, or expired, when a sibling request rejects, or when the underlying expense is resubmitted.

### 3.8. Statement Production: Generation, Issue, Amendment, and Disbursement

A `BusinessManager` generates a statement with `artist_id`, `period_start_date`, `period_end_date`, and a `basis` of `ACCRUAL` or `CASH`. The period is a closed interval: the end must be on or after the start (a malformed window fails with `ERR_INVALID_REQUEST`) and may not lie after the clock date (`ERR_STATEMENT_PERIOD_FUTURE`), and the artist must not be `ARCHIVED` (`ERR_ARTIST_ARCHIVED`). Two statements of the same artist may not cover the same day: under closed-interval arithmetic the new period collides with any existing non-`DISCARDED` statement when the new start is on or before the existing end and the existing start is on or before the new end — so a new period starting exactly on the previous period's end date IS an overlap, and the tightest legal successor starts the day after (`ERR_STATEMENT_PERIOD_OVERLAP`). The carry chain also demands closure: the immediately preceding statement — the latest non-`DISCARDED` one whose `period_end_date` falls before the new start — must not still be `DRAFT` (`ERR_PRIOR_STATEMENT_OPEN`).

Generation then builds the draft in a pinned evaluation order. First come the `INCOME` lines: events not yet posted (their `statement_id` is null) are swept in, keyed by basis — under `ACCRUAL`, events in `VERIFIED` or `SETTLED` whose `recognition_date` falls inside the period; under `CASH`, only `SETTLED` events whose `received_date` falls inside the period. Each income line's `amount_cents` is the event's `artist_net_cents`, and its `commission_cents` is the event's pinned `commission_amount_cents`; the statement's `rate_snapshot` records, per income line, the event's income type, `applied_schedule_id`, and `applied_rate_bps`, and amendments never re-derive those pinned lines. The basis choice changes what appears: an event recognized in one period but settled in the next appears on the earlier period's `ACCRUAL` statement but on the later period's `CASH` statement, so identical underlying data yields different `gross_total_cents`, `commission_total_cents`, and `net_payable_cents` between the two bases. Second, `EXPENSE_REIMBURSEMENT` lines sweep the artist's `APPROVED`, not-yet-reimbursed expenses with `incurred_date` on or before the period end, each stored as a positive amount. Third, `ADVANCE_RECOUPMENT` lines sweep settled events whose `recoup_statement_id` is still null, whose `recouped_amount_cents` is greater than zero, and whose `received_date` falls inside the period; the line amount is the recouped amount. Fourth, `ADJUSTMENT` lines draw on the artist's audits in `FINDINGS_ISSUED` or `CLOSED`: an audit's `findings_underpayment_cents` is added when it is positive and its `underpayment_applied` flag is still false (the sweep then sets the flag), and an audit's `audit_cost_cents` is subtracted when `cost_bearer` is `ARTIST`, the cost is positive, and `cost_applied` is still false (likewise then set). Fifth, `carry_in_cents` is the `carry_out_cents` of the prior statement in the chain — recorded on the new statement as `prior_statement_id`, the latest non-`DISCARDED` statement of the artist ending before this period starts — or zero for the artist's first statement.

Totals follow from the lines. `gross_total_cents`, `commission_total_cents`, and `income_net_total_cents` sum the gross, commission, and net components of the income lines (commissions were already rounded per event at verify; the statement never re-rounds or re-derives them). `expense_total_cents` sums the reimbursement lines, `recoup_total_cents` sums the recoupment lines, and `adjustment_total_cents` — initially zero on a first draft — sums the signed adjustment lines. The bottom line is `net_payable_cents`: income net total minus expense total minus recoup total plus adjustment total plus carry-in. A disbursement threshold of 50000 cents ($500) then splits the outcome: when `net_payable_cents` is at least the threshold, `disbursed_cents` equals the net payable and `carry_out_cents` is 0; when it is positive but below the threshold, nothing is disbursed and the whole amount carries forward; when it is zero or negative, nothing is disbursed and the full amount carries as the artist's debt to the firm. One invariant holds after every generation, amendment, and disbursement: `disbursed_cents` plus `carry_out_cents` always equals `net_payable_cents`. The statement is born `DRAFT` with `revision_number` 1.

Issuing is the point of commitment. A `BusinessManager` issues a `DRAFT` statement (`ERR_INVALID_STATE` otherwise); `issued_at` is stamped from the clock, `dispute_window_ends_at` opens thirty days later, and the totals freeze. The issue sweep then lands on the ledger: every swept income event moves to `POSTED` with `statement_id` recorded, every swept expense moves to `REIMBURSED` with `reimbursed_statement_id` recorded, and every swept recoup event gets `recoup_statement_id` set.

The artist then has thirty days. The artist may explicitly accept, moving `ISSUED → ACKNOWLEDGED`; alternatively the clock sweep deems acceptance, moving an `ISSUED` statement to `ACKNOWLEDGED` once the clock passes `dispute_window_ends_at` with no active dispute. Because deemed acceptance fires the moment the window lapses, an `ISSUED` statement always has an open dispute window — `ERR_DISPUTE_WINDOW_CLOSED` is therefore the terminal-state message for statements already `ACKNOWLEDGED` or `FINALIZED`. A `BusinessManager` disburses an `ACKNOWLEDGED` statement, moving it to the terminal `FINALIZED` state: the pinned `disbursed_cents` is paid out, the artist's `lifetime_disbursed_cents` increases by that amount, and the artist's `version` increments. A draft that should never have been generated can be discarded (`DRAFT → DISCARDED`) by a `BusinessManager`; discarded statements drop out of the overlap and carry-chain arithmetic entirely.

Amendment is the dispute-driven revision path. A `BusinessManager` amends a `DISPUTED` statement only when every dispute on it has reached `RESOLVED_UPHELD`, `RESOLVED_REJECTED`, or `WITHDRAWN` — any dispute still open, under review, or escalated blocks the amendment with `ERR_DISPUTE_NOT_RESOLVED`. For each upheld dispute the amendment appends an `ADJUSTMENT` line whose amount is the dispute's `awarded_amount_cents` and whose reference is the dispute; `revision_number` increments by one. Totals then re-run over the amended line set — the pinned `rate_snapshot` lines are untouched — so `adjustment_total_cents`, `net_payable_cents`, `disbursed_cents`, and `carry_out_cents` recompute, and the amended carry-out becomes the carry-in of the next generated statement. The artist's `version` increments, but the lifetime aggregates are not restated, because dispute awards are commission-free. Finally, `issued_at` and `dispute_window_ends_at` reset, opening a fresh thirty-day dispute window on the revised statement.

Statement lines are the audit trail. Each line carries `statement_id`, a `line_type` of `INCOME`, `EXPENSE_REIMBURSEMENT`, `ADVANCE_RECOUPMENT`, or `ADJUSTMENT`, and a polymorphic `ref_id` resolved through the line type — an income line points at its income event, a reimbursement line at its expense, a recoupment line at the settled income event, and an adjustment line at the dispute or audit that produced it. `amount_cents` is signed: income lines carry the event's net, reimbursement and recoupment lines are stored positive and subtracted by the totals calculation, and adjustment lines may be positive or negative. `commission_cents` carries the commission component on income lines and is 0 on all other types, and `note` holds a human-readable derivation. Lines are append-only; amendments only ever add adjustment lines. Statements can be listed by `artist_id`, `prior_statement_id`, `status`, and `basis`.

### 3.9. Disputes, Escalation, and Audit Rights

The artist contests a statement by opening a dispute with `artist_id`, `statement_id`, a `reason` of `COMMISSION_RATE`, `INCOME_MISSING`, `EXPENSE_UNAUTHORIZED`, `RECOUPMENT_ERROR`, `SUNSET_MISCLASSIFIED`, or `OTHER`, and `claimed_amount_cents` (greater than zero). The target statement must be `ISSUED`: a `DRAFT` or `DISCARDED` statement fails with `ERR_INVALID_STATE`, an `ACKNOWLEDGED` or `FINALIZED` statement means the dispute window has closed (`ERR_DISPUTE_WINDOW_CLOSED`), and a `DISPUTED` statement means another dispute is already active (`ERR_DISPUTE_ALREADY_ACTIVE`). Opening the dispute flips the statement from `ISSUED` to `DISPUTED`; the dispute itself is born `OPEN`.

Review and resolution belong to the firm. A `BusinessManager` starts review (`OPEN → UNDER_REVIEW`), and a `BusinessManager` or `FirmAdmin` resolves from `UNDER_REVIEW` by supplying an `outcome`: `RESOLVED_REJECTED` needs nothing more, while `RESOLVED_UPHELD` requires `awarded_amount_cents` to be present and greater than zero (`ERR_INVALID_REQUEST` otherwise); an optional `resolution_note` may accompany either outcome. An upheld award is commission-free and becomes an `ADJUSTMENT` line only when the statement is amended (§3.8) — it never restates the artist's lifetime aggregates. The artist may withdraw a dispute from `OPEN` or `UNDER_REVIEW`; when no other active dispute remains on the statement, the statement reverts from `DISPUTED` back to `ISSUED`. Disputes can be listed by `artist_id`, `statement_id`, and `status`.

Escalation is the artist's audit right in action. Escalating a dispute — from `OPEN` or `UNDER_REVIEW` — moves it to `ESCALATED` and creates an audit in `REQUESTED` scoped to the dispute's statement, with `source_dispute_id` recording the dispute it arose from. The artist may also demand an audit directly, without any dispute, by supplying `artist_id` and `scope_statement_id`; the scope statement must be `ISSUED`, `DISPUTED`, `ACKNOWLEDGED`, or `FINALIZED` (`ERR_INVALID_STATE` otherwise), its `issued_at` must lie within the trailing 365 days of the clock, inclusive (`ERR_AUDIT_WINDOW_CLOSED`), and no other audit on the same statement may be open — any audit not yet `CLOSED` blocks a new one with `ERR_AUDIT_ALREADY_ACTIVE`. Audit rights survive artist archiving.

The audit itself belongs to the `Auditor`. Beginning moves `REQUESTED → IN_PROGRESS`. Issuing findings moves `IN_PROGRESS → FINDINGS_ISSUED` and takes `findings_underpayment_cents` (zero or more) and `audit_cost_cents` (zero or more). Findings trigger the cost-allocation rule, evaluated in a pinned order: the base is the scope statement's pinned `net_payable_cents`, never recomputed; the ratio is treated as infinite when that base is zero or negative, otherwise it is the underpayment divided by the base; `cost_bearer` is `FIRM` when the ratio reaches five percent — compared as an exact rational, so the boundary reads: underpayment times 100 is at least base times 5 — or when the underpayment reaches 2500000 cents ($25,000), and `ARTIST` otherwise. Only an `ARTIST`-borne cost is recoverable, swept as a negative `ADJUSTMENT` line on a later statement generation (§3.8). The artist may object: reopening moves `FINDINGS_ISSUED → IN_PROGRESS` and adds one to `reopen_count`, which is capped at 2 — a third attempt fails with `ERR_AUDIT_REOPEN_LIMIT`. An `Auditor` or `FirmAdmin` closes the audit from `FINDINGS_ISSUED` to the terminal `CLOSED` state. Audits can be listed by `artist_id`, `scope_statement_id`, `source_dispute_id`, and `status`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource return `200 OK`. This includes the three creation-style actions whose primary effect is producing a new resource from an existing one: converting an opportunity, exercising an option, and escalating a dispute each return `201 Created` with the newly created resource. Request bodies, response payloads, and side effects are specified by the narratives of §2 and §3; the table below is the routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/artists` | Create an Artist (born `ACTIVE`, version 1) | FirmAdmin |
| GET | `/artists/{id}` | Get one Artist | FirmAdmin, Agent, BusinessManager, Publicist, Artist, Auditor |
| GET | `/artists` | List artists with optional filters and pagination | FirmAdmin, Agent, BusinessManager, Publicist, Artist, Auditor |
| PATCH | `/artists/{id}` | Update mutable fields or status (`ACTIVE`↔`ON_HIATUS`, →`ARCHIVED`) | FirmAdmin |
| POST | `/agreements` | Create a management Agreement in `DRAFT`; OCC via `expected_artist_version` | FirmAdmin |
| GET | `/agreements/{id}` | Get one Agreement | FirmAdmin, Agent, BusinessManager, Publicist, Artist, Auditor |
| GET | `/agreements` | List agreements (by artist, supersede chain, status) | FirmAdmin, Agent, BusinessManager, Publicist, Artist, Auditor |
| PATCH | `/agreements/{id}` | Edit an agreement; OCC via `expected_agreement_version` | FirmAdmin |
| POST | `/agreements/{id}/activate` | `DRAFT → ACTIVE`; supersedes the artist's current `ACTIVE` agreement | FirmAdmin |
| POST | `/agreements/{id}/terminate` | `ACTIVE → TERMINATED` early; opens the sunset window | FirmAdmin |
| POST | `/rate-schedules` | Create an effective-dated rate schedule (half-open window) | FirmAdmin, BusinessManager |
| GET | `/rate-schedules/{id}` | Get one CommissionRateSchedule | FirmAdmin, Agent, BusinessManager, Publicist, Artist, Auditor |
| GET | `/rate-schedules` | List rate schedules (by agreement, income type) | FirmAdmin, Agent, BusinessManager, Publicist, Artist, Auditor |
| POST | `/rate-schedules/{id}/close` | Pin `effective_to_date` on an open schedule; overlap re-validated | FirmAdmin, BusinessManager |
| POST | `/income-events` | Report an income event (`REPORTED`); server resolves the covering agreement | Agent, BusinessManager |
| GET | `/income-events/{id}` | Get one IncomeEvent | FirmAdmin, Agent, BusinessManager, Publicist, Artist, Auditor |
| GET | `/income-events` | List income events (by artist, agreement, links, status, type) | FirmAdmin, Agent, BusinessManager, Publicist, Artist, Auditor |
| POST | `/income-events/{id}/verify` | `REPORTED → VERIFIED`; pins schedule, `term_relation`, commission, net | BusinessManager |
| POST | `/income-events/{id}/settle` | `VERIFIED`/`POSTED → SETTLED`; runs the recoupment waterfall cascade | BusinessManager |
| POST | `/income-events/{id}/void` | `REPORTED`/`VERIFIED → VOIDED`; settled/posted events rejected | BusinessManager |
| POST | `/advances` | Issue a recoupable advance (`ACTIVE`) | BusinessManager, FirmAdmin |
| GET | `/advances/{id}` | Get one Advance | FirmAdmin, Agent, BusinessManager, Publicist, Artist, Auditor |
| GET | `/advances` | List advances (by artist, status) | FirmAdmin, Agent, BusinessManager, Publicist, Artist, Auditor |
| POST | `/advances/{id}/write-off` | `ACTIVE → WRITTEN_OFF`; forgives the outstanding balance | FirmAdmin |
| POST | `/expenses` | Submit a reimbursable expense; auto-creates routed approval requests | Agent, BusinessManager, Publicist |
| GET | `/expenses/{id}` | Get one Expense | FirmAdmin, Agent, BusinessManager, Publicist, Artist, Auditor |
| GET | `/expenses` | List expenses (by artist, engagement, statement, status) | FirmAdmin, Agent, BusinessManager, Publicist, Artist, Auditor |
| POST | `/expenses/{id}/resubmit` | `REJECTED → PENDING_APPROVAL` with optional edits; routing re-run | Agent, BusinessManager, Publicist |
| GET | `/approval-requests/{id}` | Get one ApprovalRequest | FirmAdmin, Agent, BusinessManager, Publicist, Artist, Auditor |
| GET | `/approval-requests` | List approval requests (by artist, target, approver, status) | FirmAdmin, Agent, BusinessManager, Publicist, Artist, Auditor |
| POST | `/approval-requests/{id}/approve` | Approve a `PENDING` request; role, SoD, and authority caps enforced | BusinessManager, Artist, FirmAdmin |
| POST | `/approval-requests/{id}/reject` | Reject a `PENDING` request; expense target rejected, siblings cancelled | BusinessManager, Artist, FirmAdmin |
| POST | `/opportunities` | Register an incoming offer (`RECEIVED`) | Agent |
| GET | `/opportunities/{id}` | Get one Opportunity | FirmAdmin, Agent, BusinessManager, Publicist, Artist, Auditor |
| GET | `/opportunities` | List opportunities (by artist, status, type, conversion) | FirmAdmin, Agent, BusinessManager, Publicist, Artist, Auditor |
| POST | `/opportunities/{id}/evaluate` | `RECEIVED → UNDER_EVALUATION` (or refresh in place); computes score | Agent, BusinessManager |
| POST | `/opportunities/{id}/negotiate` | `UNDER_EVALUATION → NEGOTIATING`; may raise artist approval request | Agent |
| POST | `/opportunities/{id}/counter-offer` | Record a counter-offer; OCC; 10% band governs stay vs loop-back | Agent |
| POST | `/opportunities/{id}/accept` | `UNDER_EVALUATION`/`NEGOTIATING → ACCEPTED`; approval gates enforced | Agent |
| POST | `/opportunities/{id}/decline` | `RECEIVED`/`UNDER_EVALUATION`/`NEGOTIATING → DECLINED` | Agent |
| POST | `/opportunities/{id}/withdraw` | Counterparty pulls the offer: → `WITHDRAWN` | Agent |
| POST | `/opportunities/{id}/convert` | `ACCEPTED → CONVERTED`; creates a `CONFIRMED` engagement | Agent |
| POST | `/engagements` | Create a calendar engagement in `HOLD` (tentative; no blocking) | Agent |
| GET | `/engagements/{id}` | Get one Engagement | FirmAdmin, Agent, BusinessManager, Publicist, Artist, Auditor |
| GET | `/engagements` | List engagements (by artist, opportunity, status) | FirmAdmin, Agent, BusinessManager, Publicist, Artist, Auditor |
| POST | `/engagements/{id}/confirm` | `HOLD → CONFIRMED`; buffered overlap check; releases overlapping holds | Agent |
| POST | `/engagements/{id}/complete` | `CONFIRMED → COMPLETED` once the engagement has ended | Agent, BusinessManager |
| POST | `/engagements/{id}/cancel` | `HOLD`/`CONFIRMED → CANCELLED`; blocked when verified income is linked | Agent |
| POST | `/options` | Create a contract option (`OPEN`) on an `ACTIVE` agreement | Agent, FirmAdmin |
| GET | `/options/{id}` | Get one Option | FirmAdmin, Agent, BusinessManager, Publicist, Artist, Auditor |
| GET | `/options` | List options (by artist, agreement, source, exercise, status) | FirmAdmin, Agent, BusinessManager, Publicist, Artist, Auditor |
| POST | `/options/{id}/exercise` | `OPEN → EXERCISED` inside the inclusive window; creates a `CONFIRMED` engagement | Agent |
| POST | `/options/{id}/waive` | `OPEN → WAIVED` (the artist gives up the right) | Artist, FirmAdmin |
| POST | `/team-members` | Assign an agent, business manager, or publicist to an artist (`ACTIVE`) | FirmAdmin |
| GET | `/team-members/{id}` | Get one TeamMember | FirmAdmin, Agent, BusinessManager, Publicist, Artist, Auditor |
| GET | `/team-members` | List team members (by artist, role, status) | FirmAdmin, Agent, BusinessManager, Publicist, Artist, Auditor |
| POST | `/team-members/{id}/suspend` | `ACTIVE → SUSPENDED` (member may not act while suspended) | FirmAdmin |
| POST | `/team-members/{id}/resume` | `SUSPENDED → ACTIVE` | FirmAdmin |
| POST | `/team-members/{id}/end` | `ACTIVE`/`SUSPENDED → ENDED` | FirmAdmin |
| POST | `/statements/generate` | Generate a `DRAFT` statement for a closed period; runs statement generation | BusinessManager |
| GET | `/statements/{id}` | Get one Statement | FirmAdmin, Agent, BusinessManager, Publicist, Artist, Auditor |
| GET | `/statements` | List statements (by artist, carry chain, status, basis) | FirmAdmin, Agent, BusinessManager, Publicist, Artist, Auditor |
| GET | `/statements/{id}/lines` | List the statement's lines (append-only) | FirmAdmin, Agent, BusinessManager, Publicist, Artist, Auditor |
| POST | `/statements/{id}/issue` | `DRAFT → ISSUED`; freezes totals; opens the 30-day dispute window | BusinessManager |
| POST | `/statements/{id}/acknowledge` | `ISSUED → ACKNOWLEDGED` (artist accepts the statement) | Artist |
| POST | `/statements/{id}/amend` | `DISPUTED → ISSUED` as revision+1 once all disputes resolved | BusinessManager |
| POST | `/statements/{id}/disburse` | `ACKNOWLEDGED → FINALIZED`; executes the pinned disbursed amount | BusinessManager |
| POST | `/statements/{id}/discard` | `DRAFT → DISCARDED` (withdraw a draft statement) | BusinessManager |
| POST | `/disputes` | Open a dispute against an `ISSUED` statement; statement → `DISPUTED` | Artist |
| GET | `/disputes/{id}` | Get one Dispute | FirmAdmin, Agent, BusinessManager, Publicist, Artist, Auditor |
| GET | `/disputes` | List disputes (by artist, statement, status) | FirmAdmin, Agent, BusinessManager, Publicist, Artist, Auditor |
| POST | `/disputes/{id}/start-review` | `OPEN → UNDER_REVIEW` | BusinessManager |
| POST | `/disputes/{id}/resolve` | `UNDER_REVIEW → RESOLVED_UPHELD` or `RESOLVED_REJECTED` | BusinessManager, FirmAdmin |
| POST | `/disputes/{id}/withdraw` | `OPEN`/`UNDER_REVIEW → WITHDRAWN`; statement may revert to `ISSUED` | Artist |
| POST | `/disputes/{id}/escalate` | `OPEN`/`UNDER_REVIEW → ESCALATED`; creates an Audit (`REQUESTED`) | Artist |
| POST | `/audits` | Artist demands an audit of a statement issued within the last 365 days | Artist |
| GET | `/audits/{id}` | Get one Audit | FirmAdmin, Agent, BusinessManager, Publicist, Artist, Auditor |
| GET | `/audits` | List audits (by artist, scope statement, source dispute, status) | FirmAdmin, Agent, BusinessManager, Publicist, Artist, Auditor |
| POST | `/audits/{id}/begin` | `REQUESTED → IN_PROGRESS` | Auditor |
| POST | `/audits/{id}/issue-findings` | `IN_PROGRESS → FINDINGS_ISSUED`; runs audit cost allocation | Auditor |
| POST | `/audits/{id}/reopen` | `FINDINGS_ISSUED → IN_PROGRESS` (artist objection); max 2 reopens | Artist |
| POST | `/audits/{id}/close` | `FINDINGS_ISSUED → CLOSED` | Auditor, FirmAdmin |
| POST | `/_clock/set_current_utc` | Advance the logical clock; applies every time-driven automatic transition | FirmAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_ARTIST_ACCESS_DENIED` | 403 Forbidden |
| `ERR_TEAM_MEMBER_INACTIVE` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REFERENCE` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_ARTIST_VERSION` | 412 Precondition Failed |
| `ERR_STALE_AGREEMENT_VERSION` | 412 Precondition Failed |
| `ERR_STALE_OPPORTUNITY_VERSION` | 412 Precondition Failed |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_ARTIST_ARCHIVED` | 409 Conflict |
| `ERR_NO_COVERING_AGREEMENT` | 409 Conflict |
| `ERR_AGREEMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_NO_RATE_SCHEDULE` | 422 Unprocessable Entity |
| `ERR_RATE_SCHEDULE_OVERLAP` | 409 Conflict |
| `ERR_EVENT_ALREADY_SETTLED` | 409 Conflict |
| `ERR_AMOUNT_OUT_OF_RANGE` | 422 Unprocessable Entity |
| `ERR_ADJUSTMENT_PARENT_INVALID` | 422 Unprocessable Entity |
| `ERR_APPROVAL_AUTHORITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_EXPENSE_NOT_REJECTED` | 409 Conflict |
| `ERR_ARTIST_APPROVAL_REQUIRED` | 409 Conflict |
| `ERR_OFFER_EXPIRED` | 409 Conflict |
| `ERR_OPPORTUNITY_NOT_ACCEPTED` | 409 Conflict |
| `ERR_ENGAGEMENT_OVERLAP` | 409 Conflict |
| `ERR_ENGAGEMENT_WINDOW_PAST` | 422 Unprocessable Entity |
| `ERR_ENGAGEMENT_NOT_ENDED` | 409 Conflict |
| `ERR_ENGAGEMENT_HAS_INCOME` | 409 Conflict |
| `ERR_OPTION_WINDOW_VIOLATION` | 409 Conflict |
| `ERR_STATEMENT_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_STATEMENT_PERIOD_FUTURE` | 422 Unprocessable Entity |
| `ERR_PRIOR_STATEMENT_OPEN` | 409 Conflict |
| `ERR_DISPUTE_WINDOW_CLOSED` | 409 Conflict |
| `ERR_DISPUTE_ALREADY_ACTIVE` | 409 Conflict |
| `ERR_DISPUTE_NOT_RESOLVED` | 409 Conflict |
| `ERR_AUDIT_WINDOW_CLOSED` | 409 Conflict |
| `ERR_AUDIT_ALREADY_ACTIVE` | 409 Conflict |
| `ERR_AUDIT_REOPEN_LIMIT` | 409 Conflict |
