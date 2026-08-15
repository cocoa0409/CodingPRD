# Housing Cooperative Board & Share Transfer API — Product Requirements Document

## 1. Introduction

A New York housing cooperative is a corporation that owns a residential building; residents do not own their apartments outright but hold shares in the corporation together with a proprietary lease on a specific unit. Every resale of a unit is therefore a share transfer that the board of directors must vet — financially, through a purchase application, and personally, through a board interview — before any shares change hands. Alongside transfers, the board carries an ongoing fiscal burden: levying monthly maintenance charges that cover the building's operating budget and its underlying permanent mortgage, pursuing shareholders who fall into arrears up to the termination of their proprietary lease, policing sublets and renovations, and renewing its own mandate through annual meetings and cumulative-voting elections.

This document specifies an API that models those operations for a managing agent's back office and the board's own workflow tooling. It covers the constitution of a cooperative and its share ledger, the annual budgeting and maintenance-charge cycle, payment posting and arrears escalation, the full purchase-application pipeline from draft to recorded transfer with flip tax, sublet and alteration approvals, board resolutions with majority voting, and meetings with quorum tracking and ballot tallying. Because co-op bookkeeping and governance decisions are strictly serialized in practice — a flip-tax computation is only meaningful against the share totals and policy in force at the instant of transfer — the API also exposes optimistic concurrency controls on the cooperative aggregate and a test-driving logical clock that governs every time-dependent transition in the domain.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming the role under which the operator acts. A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_CONTEXT_HEADER` (HTTP 400). A request whose `X-User-Role` is not among the roles permitted for the target endpoint (as enumerated in §4) is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

Five roles exist, spelled exactly as follows:

- `PlatformAdmin` — the system operator. Creates cooperatives, advances each cooperative's logical clock, and may read any resource. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- `BoardOfficer` — a board president, treasurer, or secretary. Schedules interviews, opens and withdraws resolutions, manages charge schedules and meetings, records transfers, escalates or withdraws arrears actions, and rules on sublets. When `X-User-Role` is `BoardOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- `BoardMember` — a board director. Sits on interview panels and casts votes on resolutions. When `X-User-Role` is `BoardMember`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it as `voter_user_id` on each `ResolutionVote` the member casts and as entries of `panel_member_user_ids` on each `Interview` the member conducts, but never compares it against an entity's `id`.
- `ManagingAgent` — the building's external managing agent. Certifies the completeness of purchase packages, posts and voids payments, and issues arrears notices; it cannot vote, schedule interviews, or sit on panels. When `X-User-Role` is `ManagingAgent`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- `Shareholder` — a co-op unit owner. Initiates purchase applications as seller, requests sublets and alterations, performs renovation lifecycle actions, and casts ballots. When `X-User-Role` is `Shareholder`, `X-User-ID` is the `id` of the acting `Shareholder`; ownership checks on any resource that references a `Shareholder` — for example `seller_shareholder_id` on a purchase application or `shareholder_id` on a sublet, alteration, or ballot — compare that foreign-key field to `X-User-ID`, and a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

Two segregation-of-duties rules run across these roles. First, the `ManagingAgent` operator who certifies a purchase package may not later sit on the interview panel for that same application. Second, the same natural person — identified by `X-User-ID` — may not simultaneously exercise `BoardOfficer` and `BoardMember` authority over the same resolution. Breaches of these segregations are rejected with `ERR_SEPARATION_OF_DUTIES` (HTTP 422).

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

List endpoints accept the query parameters `limit` and `offset`. The `limit` parameter defaults to 10, with a minimum of 1 and a maximum of 100; the `offset` parameter defaults to 0. Results are always ordered by `created_at` ascending. The `meta` object of a list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `total_count` reports the full size of the filtered result set and `has_more` indicates whether further pages exist beyond the returned window.

### 2.4. Resource Identity, Common Fields, and the Cooperative-Scoped URL Hierarchy

Every resource in the API — the cooperative itself and all fifteen subordinate entity kinds — carries a common set of system-maintained properties. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` timestamps are ISO 8601 UTC values rendered with three fractional digits. The `version` is an integer that increments on every mutation of the resource. No entity in this API is exempt from these common fields.

The API is mounted under `/cooperatives` and most resources are addressed through a cooperative-scoped path hierarchy: `/cooperatives/{cid}` for the cooperative, then one segment per subordinate collection. The path parameter names are: `cid` (the cooperative), `uid` (a unit), `sid` (a shareholder or, on sublet and alteration routes, a sublet or alteration agreement), `eid` (a share-ledger entry), `csid` (a charge schedule), `mcid` (a maintenance charge), `pid` (a payment), `aid` (an arrears action or, on alteration routes, an alteration agreement), `paid` (a purchase application), `iid` (an interview), `rid` (a resolution), `mid` (a meeting), `bid` (a ballot), and `vid` (a resolution vote on the flat vote routes) — rendered in paths as the placeholders `{cid}`, `{uid}`, `{sid}`, `{eid}`, `{csid}`, `{mcid}`, `{pid}`, `{aid}`, `{paid}`, `{iid}`, `{rid}`, `{mid}`, `{bid}`, and `{vid}` respectively. Path parameters are validated left to right: each segment must identify an existing resource, and each child must belong to the scope established by its parent segments. Any failure along this chain is rejected with `ERR_NOT_FOUND` (HTTP 404).

Identifiers are globally unique across cooperatives. A unit, charge, application, or any other subordinate record can therefore be located by its `id` alone, which is what makes the flat read aliases of §2.10 unambiguous.

### 2.5. The Logical Clock and Scheduled System Behavior

Each cooperative carries a logical clock in the field `current_utc`. When a cooperative is created, `current_utc` initializes to 2026-08-01T00:00:00Z, and it thereafter advances only when a `PlatformAdmin` explicitly sets it through the clock-advance capability, passing the target instant as `to_iso8601`. The logical clock must never fall back to wall-clock time: every time-dependent rule in this document — charge issuance, grace expiry, interest accrual, sublet and alteration window boundaries, interview no-show detection, meeting auto-adjournment, and arrears escalation checks — is evaluated against `current_utc`, and advancing the clock is what fires those scheduled transitions. Each clock advancement also increments the cooperative's `version`.

Because so much behavior is clock-driven, readers should treat `current_utc` as the single source of temporal truth: a due date in the past relative to `current_utc` is overdue, an interview whose `scheduled_at` lies more than twenty-four hours in the past is a no-show, and a meeting still waiting for quorum twenty-four hours after its `scheduled_at` adjourns itself.

### 2.6. Monetary Representation, Precision, and Rounding

All money amounts are integers denominated in cents — field names ending in `_cents` — and all computed money amounts are rounded half-up to whole cents (zero decimal places). Rates and percentages are expressed in basis points, where 10,000 basis points equal one hundred percent: the default flip-tax percentage of 200 basis points is two percent, the arrears interest rate of 600 basis points is a six percent annual rate, and so on. Share counts, vote counts, and day counts are plain integers; the quorum threshold uses ceiling division so that any fractional share rounds up to the next whole share.

### 2.7. Share Conservation and the Cooperative Version Counter

Two invariants bind the cooperative aggregate to its parts. First, share conservation (invariant INV-SHARES): the cooperative's `total_shares` must always equal the sum of `shares_allocated` over all of its units, and the shares assigned to a unit through the share ledger must in turn reconcile exactly with that unit's allocation. Creating a unit adds its `shares_allocated` to the cooperative's `total_shares` and increments the cooperative's `version`. Second, the cooperative's `version` acts as an aggregate-wide mutation counter: beyond direct edits, it is incremented by unit creation, charge-schedule creation, the approval cascade of a charge schedule, certification of a purchase package, recording of a share transfer, and every clock advancement. Subordinate entities carry their own `version` and `updated_at`, which follow the common rule of §2.4 — every mutation of the entity itself increments its `version` and refreshes `updated_at`.

### 2.8. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control against the cooperative aggregate, and both take their guard value from the same field. Creating a charge schedule, and recording the transfer of an approved purchase application, each require the request body to carry `expected_cooperative_version`, a non-optional field holding the cooperative's `version` as the client last observed it. If the cooperative's current `version` no longer matches — because another writer has since created units, opened a schedule, changed policy, recorded a transfer, or advanced the clock — the request is rejected with `ERR_STALE_COOP_VERSION` (HTTP 412) and nothing is written. The rationale differs by operation: for schedule creation, the stale view would encode a fiscal basis (share totals and allocation) that no longer exists; for transfer recording, the client may have computed expectations about the flip tax from a policy that has since changed. Endpoints other than these two do not accept a version field.

### 2.9. Validation Order and Error Semantics

When several checks could fail on the same request, the server reports only the earliest failure, evaluating checks in this fixed priority order:

1. **Context headers** — presence and well-formedness of `X-User-ID` and `X-User-Role` on every endpoint; failure yields `ERR_MISSING_CONTEXT_HEADER` (HTTP 400).
2. **Role authorization** — the role named by `X-User-Role` is permitted for the endpoint; failure yields `ERR_UNAUTHORIZED_ROLE` (HTTP 403).
3. **Ownership** — on shareholder-self endpoints (submitting or withdrawing one's own purchase application, submitting requested information, submitting a sublet, submitting, starting, completing, or abandoning one's own alteration, casting a ballot), `X-User-ID` must equal the shareholder id the resource belongs to; failure yields `ERR_NOT_RESOURCE_OWNER` (HTTP 403).
4. **Existence** — path parameters identify existing resources in the correct cooperative scope, validated left to right; failure yields `ERR_NOT_FOUND` (HTTP 404).
5. **State-transition legality** — the target resource is in a state from which the requested transition exists; failure yields `ERR_INVALID_STATE` (HTTP 409), or `ERR_ALREADY_TERMINAL` (HTTP 409) when the resource already sits in a terminal state from which no transition is permitted at all.
6. **Alteration safety** — contractor insurance meets the minimum and wet-over-dry work carries its explicit acknowledgment; failure yields `ERR_ALTERATION_SAFETY_VIOLATION` (HTTP 422).
7. **Cross-entity referential integrity** — every referenced entity exists and is in a compatible state: the selling shareholder is in `GOOD_STANDING`, the schedule being approved is still `DRAFT`, panel members are not the certifying agent; failure yields `ERR_CROSS_ENTITY_VIOLATION` (HTTP 422).
8. **Temporal consistency** — date and window ordering holds, prohibited interval overlaps are absent (sublet windows, alteration work windows), and interview scheduling lands in the future; failure yields `ERR_TEMPORAL_CONFLICT` (HTTP 422).
9. **Domain constraints** — share conservation across the ledger, at most one ballot per shareholder per meeting, the financing cap, and the interview-panel minimum size; failure yields `ERR_BUSINESS_CONSTRAINT` (HTTP 422).
10. **Fiscal thresholds** — the buyer's debt-to-income and liquidity requirements, and the arrears level required before a termination notice may issue; failure yields `ERR_FISCAL_THRESHOLD_VIOLATION` (HTTP 422).
11. **Optimistic concurrency** — on the two guarded writes, `expected_cooperative_version` must match the cooperative's current `version`; failure yields `ERR_STALE_COOP_VERSION` (HTTP 412).

Independent of this business-rule ladder, structural request failures are reported as they are found: a request body missing a required field or failing a type check is rejected with `ERR_INVALID_REQUEST` (HTTP 400), and a value outside the declared set of an enum field is rejected with `ERR_INVALID_ENUM` (HTTP 400). Sublet-policy breaches carry their own dedicated code, `ERR_SUBLET_POLICY_VIOLATION` (HTTP 422), described in §3.7, and the share-ledger reconciliation carries `ERR_SHARES_MISMATCH` (HTTP 422), described in §3.1.

### 2.10. Cross-Cooperative Flat Read Aliases

Alongside the cooperative-scoped nested routes, the API exposes a flat, cross-cooperative read alias for every subordinate entity kind — a by-id read and a filtered list read — made unambiguous by the global uniqueness of identifiers (§2.4). The by-id aliases are `/cooperatives/units/{uid}`, `/cooperatives/shareholders/{sid}`, `/cooperatives/share-ledger-entries/{eid}`, `/cooperatives/charge-schedules/{csid}`, `/cooperatives/maintenance-charges/{mcid}`, `/cooperatives/payments/{pid}`, `/cooperatives/arrears-actions/{aid}`, `/cooperatives/purchase-applications/{paid}`, `/cooperatives/interviews/{iid}`, `/cooperatives/resolutions/{rid}`, `/cooperatives/resolution-votes/{vid}`, `/cooperatives/sublet-agreements/{sid}`, `/cooperatives/alteration-agreements/{aid}`, `/cooperatives/meetings/{mid}`, and `/cooperatives/ballots/{bid}`; each returns the single record with that id regardless of which cooperative owns it.

The flat list aliases return records across all cooperatives and are filterable by foreign keys and status fields. Units filter by `cooperative_id` and `unit_label`. Shareholders filter by `cooperative_id` and `standing`. Share-ledger entries filter by `cooperative_id`, `unit_id`, `shareholder_id`, and `entry_status`. Charge schedules filter by `cooperative_id`, `approving_resolution_id`, `fiscal_year`, and `schedule_status`. Maintenance charges filter by `cooperative_id`, `unit_id`, `schedule_id`, `charge_status`, and `billing_month`. Payments filter by `cooperative_id`, `shareholder_id`, `charge_id`, and `payment_status`. Arrears actions filter by `cooperative_id`, `shareholder_id`, `action_type`, and `action_status`. Purchase applications filter by `cooperative_id`, `unit_id`, `seller_shareholder_id`, `deciding_resolution_id`, and `application_status`. Interviews filter by `cooperative_id`, `application_id`, and `interview_status`. Resolutions filter by `cooperative_id`, `supersedes_resolution_id`, `resolution_kind`, `resolution_status`, and `subject_entity_id`. Resolution votes filter by `cooperative_id`, `resolution_id`, and `vote_choice`. Sublet agreements filter by `cooperative_id`, `unit_id`, `shareholder_id`, and `sublet_status`. Alteration agreements filter by `cooperative_id`, `unit_id`, `shareholder_id`, and `alteration_status`. Meetings filter by `cooperative_id`, `meeting_kind`, and `meeting_status`. Ballots filter by `cooperative_id`, `meeting_id`, `shareholder_id`, and `ballot_status`. All flat list aliases honor the pagination contract of §2.3. The nested list endpoints support the same entity-level filters minus `cooperative_id` (which the path already supplies): nested shareholders filter by `standing`; nested share-ledger entries by `unit_id`, `shareholder_id`, and `entry_status`; nested charge schedules by `fiscal_year` and `schedule_status`; nested maintenance charges by `unit_id`, `schedule_id`, `charge_status`, and `billing_month`; nested arrears actions by `shareholder_id`, `action_type`, and `action_status`; nested purchase applications by `unit_id`, `seller_shareholder_id`, and `application_status`; nested interviews by `application_id` and `interview_status`; nested resolutions by `resolution_kind`, `resolution_status`, and `subject_entity_id`; nested sublets by `unit_id`, `shareholder_id`, and `sublet_status`; nested alterations by `unit_id`, `shareholder_id`, and `alteration_status`; nested meetings by `meeting_kind` and `meeting_status`; and nested ballots by `ballot_status`.

## 3. Business Logic & Workflows

### 3.1. Establishing the Building: Units, Shareholders, and the Share Ledger

A `PlatformAdmin` brings a cooperative into existence by supplying its legal `name` and street `address`, together with the building's underlying permanent mortgage: `underlying_mortgage_principal_cents` for the outstanding principal and `underlying_mortgage_rate_bps` for the annual interest rate in basis points. The new cooperative starts with `total_shares` of zero and its logical clock at the startup instant described in §2.5. Policy knobs may be set at creation or left to their defaults: `flip_tax_policy` (either `GROSS_PERCENT` or `PER_SHARE`, defaulting to `GROSS_PERCENT`), `flip_tax_percent_bps` (default 200, i.e., two percent of the gross sale price), `flip_tax_per_share_cents` (default 50000, i.e., $500 per share), `sublet_policy_years_max` (default 2 consecutive years), `sublet_policy_gap_years` (default 1 year of owner occupancy between sublets), `arrears_late_fee_flat_cents` (default 5000, a $50 flat late fee), `arrears_interest_rate_bps` (default 600, a six percent annual rate), `arrears_grace_days` (default 10 days after the due date), `arrears_termination_threshold_cents` (default 1000000, i.e., $10,000 of arrears), and `annual_meeting_quorum_percent_bps` (default 5000, i.e., 50.00% of all shares).

With the cooperative in place, a `PlatformAdmin` or `BoardOfficer` creates its units one by one, each with a `unit_label` such as "3B" or "PH-A" and a strictly positive `shares_allocated`. Every unit creation adds its allocation into the cooperative's `total_shares` and bumps the cooperative's `version`, preserving the INV-SHARES invariant that `total_shares` always equals the sum of allocations. Each unit also carries a derived `occupancy_status` of `OWNER_OCCUPIED`, `SUBLET`, or `VACANT`, computed from the unit's most recent sublet and purchase activity — a unit with no active sublet reads `OWNER_OCCUPIED` — and a `last_sublet_end_date`, which stays null until the unit completes its first sublet and thereafter feeds the sublet-policy gap rule of §3.7.

Shareholders are registered by a `PlatformAdmin`, `BoardOfficer`, or `ManagingAgent` with a `full_name` and a contact `email`; the email must be unique within the cooperative, and a duplicate is rejected with `ERR_BUSINESS_CONSTRAINT`. A new shareholder begins with `standing` of `GOOD_STANDING` and an `arrears_balance_cents` of zero. The `standing` field is derived rather than set directly: it moves among `GOOD_STANDING`, `DELINQUENT`, and `TERMINATED` according to the arrears rules of §3.4, and `arrears_balance_cents` is itself a derived figure — the sum of `outstanding_cents` across every maintenance charge attached to units the shareholder owns, recomputed on every charge or payment write.

Ownership of shares is recorded in the share ledger. A `PlatformAdmin` or `BoardOfficer` creates a `ShareLedgerEntry` naming a `unit_id`, a `shareholder_id`, and the `shares_held` this entry assigns; the entry is born with `entry_status` of `ACTIVE` and an `effective_at` timestamp recording when it became active. After every insertion the server revalidates the conservation rule: the sum of `shares_held` over the unit's `ACTIVE` entries must equal that unit's `shares_allocated` exactly, or the write is rejected with `ERR_SHARES_MISMATCH` (HTTP 422). Entries leave the `ACTIVE` state only by becoming `SUPERSEDED` — when a purchase application reaches `TRANSFERRED` and replaces the seller's holdings with the buyer's (§3.6), or when a shareholder's proprietary lease is terminated (§3.4).

### 3.2. Board Resolutions and Voting Discipline

Nearly every consequential decision in the cooperative flows through a board resolution. A `BoardOfficer` opens a `Resolution` by naming its `resolution_kind` — one of `APPROVE_PURCHASE`, `REJECT_PURCHASE`, `APPROVE_SCHEDULE`, `APPROVE_REFINANCE`, `APPROVE_SUBLET`, `APPROVE_ALTERATION`, `ISSUE_ARREARS_ACTION`, or `SET_POLICY` — together with the `subject_entity_kind` (`PurchaseApplication`, `ChargeSchedule`, `SubletAgreement`, `AlterationAgreement`, `Shareholder`, or `Cooperative`), the `subject_entity_id` of the entity being decided, and a kind-specific `payload_json` object (for a refinance, the proposed `rate_bps_new`; for a policy change, the new policy field values). A `SET_POLICY` resolution that replaces an earlier policy carries the prior resolution's id in `supersedes_resolution_id`; for all other kinds that field stays null.

The seated board has five members, so a resolution opens with `votes_required` of three — a majority captured from the cooperative at creation time — and with `votes_for`, `votes_against`, and `votes_abstain` all at zero in `OPEN` status, stamped with `opened_at`. A `BoardMember` casts a vote by supplying a `vote_choice` of `FOR`, `AGAINST`, or `ABSTAIN`; the server records a `ResolutionVote` carrying the member's `voter_user_id`, the `resolution_id`, and a `cast_at` timestamp, and increments the matching counter on the resolution. A member who attempts to vote twice on the same resolution is rejected with `ERR_VOTER_ALREADY_CAST` (HTTP 409).

Resolution closure is automatic. The instant `votes_for` reaches `votes_required`, the resolution passes: `resolution_status` becomes `PASSED` and `closed_at` is set. Conversely, the resolution fails as soon as a majority becomes unreachable — when the count of `votes_against` plus `votes_abstain` exceeds the number of seats minus `votes_required`, so that even if every not-yet-voted member voted `FOR` the tally could not reach `votes_required` — at which point `resolution_status` becomes `FAILED` and `closed_at` is set. A `BoardOfficer` may also withdraw a resolution, but only while it is still `OPEN` and not a single vote has been cast; withdrawing after any vote exists is rejected with `ERR_RESOLUTION_ALREADY_VOTED` (HTTP 409), and withdrawal sets `closed_at` like any other closure. Once closed, a resolution is terminal — `PASSED`, `FAILED`, and `WITHDRAWN` admit no further transitions, and attempts are rejected with `ERR_ALREADY_TERMINAL`.

Passing a resolution fires the downstream effect its kind declares. `APPROVE_PURCHASE` moves the subject application to `APPROVED` (subject to the buyer-qualification preconditions of §3.6) and `REJECT_PURCHASE` moves it to `REJECTED`; both stamp the application's `deciding_resolution_id`. `APPROVE_SCHEDULE` approves the subject charge schedule and unleashes the charge-generation cascade of §3.3. `APPROVE_REFINANCE` rewrites the cooperative's `underlying_mortgage_rate_bps` and principal from `payload_json` and runs the refinance payment estimator: the projected new annual payment is the cooperative's outstanding underlying-mortgage principal multiplied by the proposed new rate, rounded half-up to whole cents — a deliberately simple interest-only approximation — and the delta versus the current annual payment, computed the same way from the existing `underlying_mortgage_principal_cents` and `underlying_mortgage_rate_bps`, is persisted in `payload_json` for audit. Refinancing is forward-looking: it does not re-budget the current fiscal year, and every `APPROVED` charge schedule stays exactly in place. `APPROVE_SUBLET` approves the subject sublet and prices its fee (§3.7); `APPROVE_ALTERATION` approves the subject alteration (§3.8); `ISSUE_ARREARS_ACTION` escalates the referenced arrears action (§3.4). `SET_POLICY` writes the cooperative's policy fields — the `flip_tax_`, `sublet_policy_`, and `arrears_` families — from `payload_json`, and when `supersedes_resolution_id` is present the referenced resolution's policy ceases to apply, its status treated as superseded even though the resolution ledger keeps it as history.

### 3.3. Budgeting, Charge Schedules, and the Monthly Maintenance Cycle

Each fiscal year the board adopts an operating budget through a `ChargeSchedule`. A `BoardOfficer` creates the schedule as a draft, supplying the `fiscal_year` (a calendar year such as 2027), the `annual_operating_budget_cents`, the `allocation_method` — `PRO_RATA_SHARES` or `EQUAL_SPLIT` — and the coverage window as `effective_from` (inclusive) and `effective_to` (exclusive). Because the budget's per-unit math depends on the share totals, creation is one of the two optimistic-concurrency-guarded writes of §2.8: the request must carry `expected_cooperative_version` matching the cooperative's current `version`, or it is rejected with `ERR_STALE_COOP_VERSION` (HTTP 412). A successfully created schedule starts in `DRAFT` status with `approving_resolution_id` still null, and its creation increments the cooperative's `version`.

Approval arrives only through the ballot box: when a resolution of kind `APPROVE_SCHEDULE` whose `subject_entity_id` names this schedule reaches `PASSED`, the schedule moves from `DRAFT` to `APPROVED`, records that resolution in `approving_resolution_id`, and increments the cooperative's `version`. Approval is also a replacement event. If any other schedule for the same cooperative is `APPROVED` over a window overlapping the new one's, the older schedule moves from `APPROVED` to `SUPERSEDED`; every maintenance charge already generated from the superseded schedule whose `billing_month` falls at or after the new schedule's effective month, and which still sits in `PENDING`, `ISSUED`, or `PARTIALLY_PAID`, is marked `WAIVED` with its `outstanding_cents` zeroed and the shareholder's `arrears_balance_cents` recomputed; and replacement charges are generated from the new schedule. Approval of the new schedule then triggers charge generation: one `MaintenanceCharge` per unit per billing month within the window, each stamped with its `schedule_id`, a `billing_month` in YYYY-MM (UTC) form, and a `due_date` — typically the first of the month — computed per the maintenance allocation formula.

The allocation formula runs once, at approval, and fixes each unit's `base_amount_cents` for every month of the schedule. All units participate regardless of occupancy. Under `PRO_RATA_SHARES`, a unit's monthly charge is found by first computing the unit's annual share of the budget — the annual budget multiplied by the unit's `shares_allocated` and divided by the cooperative's `total_shares` — and then dividing that annual share by twelve months; only the final monthly figure is rounded, half-up to whole cents. Under `EQUAL_SPLIT`, every unit pays the same monthly figure: the annual budget divided by the product of the unit count and twelve, rounded half-up to whole cents. Either variant can leave a rounding residual — twelve times the sum of the per-unit monthly charges may differ from the annual budget — so a reconciliation step runs once at approval: the residual, defined as the budget minus twelve times that sum, is divided by twelve, rounded half-up to whole cents, and added to the monthly charge of a single absorber unit. Under `PRO_RATA_SHARES` the absorber is the unit with the largest `shares_allocated`, ties broken by the earliest `created_at`; under `EQUAL_SPLIT` the absorber is the earliest-created unit. The residual is never re-applied at later billings.

A freshly generated charge sits in `PENDING`. When the logical clock reaches the start of the charge's `billing_month`, the charge is issued — `charge_status` becomes `ISSUED` and its `due_date` is set — and from there it participates in the payment and arrears machinery of §3.4. A charge's money fields decompose as `base_amount_cents` from the allocation formula, `late_fee_cents` and `interest_cents` from the arrears rules, and `paid_cents` accumulating posted payments; its `outstanding_cents` is always the base plus late fee plus interest minus payments, never less than zero.

### 3.4. Payments, Arrears, and Termination of the Proprietary Lease

Payments are the managing agent's bookkeeping entry point. A `ManagingAgent` posts a `Payment` against a specific charge, naming the paying `shareholder_id` and an `amount_cents`; the payment is created in `POSTED` status with a `posted_at` timestamp. The amount must be positive — a zero or negative amount is rejected with `ERR_INVALID_REQUEST` — and may not exceed the charge's `outstanding_cents`, on pain of `ERR_PAYMENT_EXCEEDS_OUTSTANDING` (HTTP 422). A payment smaller than the outstanding balance moves an `ISSUED` charge to `PARTIALLY_PAID`, adding the amount into `paid_cents` and recomputing `outstanding_cents` and the shareholder's `arrears_balance_cents`. A payment that exactly covers the outstanding balance moves the charge — whether `ISSUED`, `PARTIALLY_PAID`, or `PAST_DUE` — to `PAID`: `paid_cents` rises to the full base plus late fee plus interest, `outstanding_cents` becomes zero, the shareholder's arrears balance is recomputed, and any of that shareholder's arrears actions still in `ISSUED` status are cured (see below) if the balance has truly returned to zero. A posted payment can later be voided by a `ManagingAgent` while it is still `POSTED`, provided the associated charge is not `PAID` — or, if the charge is `PAID`, provided voiding would not drive the charge's `paid_cents` negative. Voiding flips the payment to `VOIDED`, subtracts its amount from the charge's `paid_cents`, recomputes `outstanding_cents` and the shareholder's arrears balance, and if a formerly `PAID` charge reopens a positive balance the charge falls back to `PARTIALLY_PAID` — or to `PAST_DUE` when the grace window has already elapsed.

Arrears begin at the grace boundary. When the logical clock passes a charge's `due_date` by more than the cooperative's `arrears_grace_days` and money is still owed, an `ISSUED` or `PARTIALLY_PAID` charge becomes `PAST_DUE`. The boundary is exact: at the instant precisely equal to `due_date` plus the grace days the charge is not yet past due; one second later it is. Entering `PAST_DUE` applies exactly one flat late fee — `late_fee_cents` is set to the cooperative's `arrears_late_fee_flat_cents`, a one-time charge that never recurs — and sets the interest meter running.

Interest accrues daily while a charge remains `PAST_DUE`. Each day's accrual is the outstanding principal — defined as `base_amount_cents` plus `late_fee_cents` minus `paid_cents`, so interest never compounds onto earlier interest — multiplied by the daily rate and rounded half-up to whole cents. The daily rate is one 365th of the cooperative's annual `arrears_interest_rate_bps`, and the day count is the number of complete 86,400-second days elapsed since the end of the grace window, never less than zero: a charge that crosses into `PAST_DUE` at the very first second after the grace boundary accrues one day of interest on that first tick. The charge's `interest_cents` is the running sum of these daily accruals since it entered `PAST_DUE`; subsequent payments reduce the principal basis for the days that follow. Every accrual recomputes `outstanding_cents` and the shareholder's `arrears_balance_cents`.

The shareholder's `standing` tracks arrears automatically. When any charge attached to a unit the shareholder owns becomes `PAST_DUE` and the shareholder's `arrears_balance_cents` is positive, `standing` moves from `GOOD_STANDING` to `DELINQUENT`. When the balance returns to zero — and no termination notice is outstanding — `standing` returns from `DELINQUENT` to `GOOD_STANDING`.

Formal collection runs through the arrears-action ladder. A `BoardOfficer` or `ManagingAgent` issues an `ArrearsAction` naming the `shareholder_id` and an `action_type` of `LATE_NOTICE`, `DEMAND_LETTER`, or `TERMINATION_NOTICE`; the action starts `ISSUED`, stamped with `issued_at`, carrying a `cure_amount_cents` snapshot of the shareholder's arrears balance at issuance, and with a `cure_deadline` computed from its type — thirty days out for a `LATE_NOTICE`, fifteen for a `DEMAND_LETTER`, and ten for a `TERMINATION_NOTICE`. Issuing a `TERMINATION_NOTICE` has a fiscal gate: the shareholder's `arrears_balance_cents` must be at least the cooperative's `arrears_termination_threshold_cents`, otherwise the issuance is rejected with `ERR_FISCAL_THRESHOLD_VIOLATION` (HTTP 422). If the shareholder pays the arrears to zero while the clock is still at or before the `cure_deadline`, the action is cured automatically — `action_status` becomes `CURED`. A `BoardOfficer` may instead withdraw an action that is still `ISSUED`, moving it to `WITHDRAWN`.

Escalation climbs the ladder. When the `cure_deadline` passes with the balance still positive, or when a `BoardOfficer` escalates manually, an `ISSUED` action becomes `ESCALATED` and spawns the next tier: a `LATE_NOTICE` gives rise to a freshly `ISSUED` `DEMAND_LETTER`, and a `DEMAND_LETTER` to a freshly `ISSUED` `TERMINATION_NOTICE`. Escalating a `TERMINATION_NOTICE` is the gravest step and carries an extra precondition — a `PASSED` resolution of kind `ISSUE_ARREARS_ACTION` naming the shareholder must exist — and its effect is to move the shareholder's `standing` to `TERMINATED`, the terminal state of the standing machine. Termination of the proprietary lease cascades widely: every `ShareLedgerEntry` the shareholder holds becomes `SUPERSEDED`; every sublet the shareholder owns in `APPROVED` or `ACTIVE` status becomes `TERMINATED_EARLY`; every alteration the shareholder owns in `APPROVED` or `IN_PROGRESS` status becomes `ABANDONED`; and every purchase application where the shareholder is the seller, in any non-terminal state, becomes `WITHDRAWN`.

### 3.5. Selling a Unit: Application, Certification, and the Board Interview

A sale begins when a `Shareholder` — the seller — drafts a `PurchaseApplication`, naming the `unit_id` being sold, their own id as `seller_shareholder_id`, and the prospective buyer's `buyer_full_name` and `buyer_email` (the buyer need not yet be a shareholder). The financial disclosures on the draft are the `gross_sale_price_cents` contract price, the `financing_percent_bps` share of the price the buyer intends to mortgage, the buyer's declared `debt_to_income_bps` ratio, and the buyer's declared `post_closing_liquidity_cents`. The draft sits in `DRAFT` with `submitted_at` still null, and may be withdrawn at any time.

Submitting the application is the seller's own act — the caller's `X-User-ID` must equal the `seller_shareholder_id`, else `ERR_NOT_RESOURCE_OWNER` — and is gated by four preconditions, checked under the ordering of §2.9: the seller must be in `GOOD_STANDING` (a delinquent seller is rejected with `ERR_CROSS_ENTITY_VIOLATION`); no other application for the same unit may be in flight in `SUBMITTED`, `UNDER_REVIEW`, `INFO_REQUESTED`, `INTERVIEW_SCHEDULED`, or `APPROVED` status; the buyer's financing may not exceed the house cap of 8000 basis points — eighty percent of the price — with breaches rejected as `ERR_BUSINESS_CONSTRAINT`; and the sale price must be positive. A valid submission moves the application from `DRAFT` to `SUBMITTED` and stamps `submitted_at`.

From there the managing agent takes over: certification of the package's completeness moves the application from `SUBMITTED` to `UNDER_REVIEW` and increments the cooperative's `version`. Board review is iterative. A `BoardOfficer` may bounce the package back by requesting more information — optionally annotating the request with `info_request_notes` — moving the application from `UNDER_REVIEW` to `INFO_REQUESTED`; the seller answers by submitting the requested material, optionally attaching `info_payload`, which returns the application to `UNDER_REVIEW`. This request-and-answer cycle between `UNDER_REVIEW` and `INFO_REQUESTED` may repeat any number of times.

When the package is ready, a `BoardOfficer` schedules the board interview, supplying a `scheduled_at` time that must lie strictly in the future relative to the cooperative's logical clock (a past or present time is rejected with `ERR_TEMPORAL_CONFLICT`) and a `panel_member_user_ids` array. The panel must contain at least two distinct `BoardMember` user ids — too few is rejected with `ERR_BUSINESS_CONSTRAINT` — and segregation of duties forbids any panel entry from equal­ing the `X-User-ID` of the managing agent who certified the package, a violation rejected with `ERR_SEPARATION_OF_DUTIES` (HTTP 422). Scheduling creates an `Interview` in `SCHEDULED` status with `interview_outcome` of `PENDING` — the outcome field's full domain is `PENDING`, `FAVORABLE`, `UNFAVORABLE`, and `WAIVED` — and moves the application from `UNDER_REVIEW` to `INTERVIEW_SCHEDULED`.

The interview itself is conducted and recorded by its panel: a `BoardMember` whose `X-User-ID` appears in `panel_member_user_ids` records the outcome — anyone else attempting it is rejected with `ERR_NOT_RESOURCE_OWNER` — once the logical clock has reached `scheduled_at`, passing an `interview_outcome` of `FAVORABLE` or `UNFAVORABLE`. Completion stamps `completed_at`, moves the interview from `SCHEDULED` to `COMPLETED`, and, when the outcome is `UNFAVORABLE`, sends the application back to `UNDER_REVIEW` for re-review. A `BoardOfficer` may instead cancel a scheduled interview, moving it to `CANCELLED` and likewise returning the application to `UNDER_REVIEW`. If twenty-four hours (86,400 seconds) pass after `scheduled_at` with no completion, the clock marks the interview `NO_SHOW` on its own and the application returns to `UNDER_REVIEW`.

The seller may withdraw the application from any non-terminal status — `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, `INFO_REQUESTED`, `INTERVIEW_SCHEDULED`, or `APPROVED` — moving it to `WITHDRAWN`; withdrawing while an interview is scheduled cancels that interview. Once an application has reached a terminal state (`REJECTED`, `WITHDRAWN`, or `TRANSFERRED`), further transitions are rejected with `ERR_ALREADY_TERMINAL`.

### 3.6. The Purchase Decision, Recording the Transfer, and the Flip Tax

Board approval of a sale is itself a resolution. Approval requires a resolution of kind `APPROVE_PURCHASE` naming the application to reach `PASSED`, and even a passed resolution does not approve an unqualified buyer: the application's interview must be `COMPLETED` with a `FAVORABLE` outcome, and the buyer must clear both fiscal thresholds, each failure rejected with `ERR_FISCAL_THRESHOLD_VIOLATION` (HTTP 422). First, the declared `debt_to_income_bps` may not exceed 2800 basis points — twenty-eight percent. Second, the declared `post_closing_liquidity_cents` must cover twelve months of carrying costs: the unit's current monthly maintenance, taken as the `base_amount_cents` of the unit's charge for the billing month current at decision time (zero if none exists yet), plus the buyer's estimated monthly mortgage. The mortgage estimate assumes a seven percent annual rate: take the financed principal — the gross sale price multiplied by the financed fraction, `financing_percent_bps` out of ten thousand — apply the seven percent annual assumption, divide by twelve months, and round half-up to whole cents. Approval moves the application from `INTERVIEW_SCHEDULED` to `APPROVED` and stamps `deciding_resolution_id`; a passed `REJECT_PURCHASE` resolution instead moves the application from `UNDER_REVIEW` or `INTERVIEW_SCHEDULED` to `REJECTED`, likewise stamping `deciding_resolution_id`.

Recording the completed closing is a `BoardOfficer` act and the second of the two optimistic-concurrency-guarded writes of §2.8: the request must carry `expected_cooperative_version` equal to the cooperative's current `version`, or the recording is rejected with `ERR_STALE_COOP_VERSION` (HTTP 412) and nothing changes — the guard exists because the flip-tax policy or share totals the client priced against may have been rewritten by a policy resolution since approval. A valid recording moves the application from `APPROVED` to `TRANSFERRED`, stamps `transferred_at`, computes and stores `flip_tax_cents`, and increments the cooperative's `version`.

The flip tax is computed exactly once, at the instant of recording, against the policy then in force — later policy changes never reopen recorded transfers. Under `GROSS_PERCENT`, the tax is the `gross_sale_price_cents` multiplied by the cooperative's `flip_tax_percent_bps` and divided by ten thousand, rounded half-up to whole cents. Under `PER_SHARE`, the tax is the unit's `shares_allocated` multiplied by the cooperative's `flip_tax_per_share_cents` — it depends only on the unit's allocation, never on the price or the buyer's financing. Either policy computes a zero tax when its configured rate is zero.

The recording also rewrites the share ledger: every `ACTIVE` ledger entry for the unit becomes `SUPERSEDED`, and a fresh `ACTIVE` entry is created assigning the buyer the unit's full `shares_allocated`. If no shareholder record exists with the application's `buyer_email`, one is created for the buyer; the seller's `standing` is then recomputed and ordinarily stands unchanged.

### 3.7. Subletting under the House Policy

A shareholder who wishes to sublet drafts a `SubletAgreement` naming the `unit_id`, their own id as `shareholder_id`, the `subtenant_name`, and the proposed occupancy window from `sublet_start_date` (inclusive) to `sublet_end_date` (exclusive). The draft rests in `DRAFT`.

Submitting the sublet is the owner's act and carries the house policy's full battery of checks. The caller's `X-User-ID` must equal the agreement's `shareholder_id`, and the shareholder must be in `GOOD_STANDING`. The unit must not already carry an active sublet — its `occupancy_status` must be something other than `SUBLET` — and no other sublet agreement for the same unit in `SUBMITTED`, `APPROVED`, or `ACTIVE` status may overlap the proposed window; an overlapping interval is rejected with `ERR_TEMPORAL_CONFLICT` (HTTP 422). The window itself must be well ordered, start before end, and the policy-specific breaches carry the dedicated code `ERR_SUBLET_POLICY_VIOLATION` (HTTP 422): the window's length may not exceed the cooperative's `sublet_policy_years_max` consecutive years, and when the unit's `last_sublet_end_date` is set, the new `sublet_start_date` must fall on or after the date exactly `sublet_policy_gap_years` years later, enforcing the mandatory owner-occupancy gap.

Approval comes from a passed resolution of kind `APPROVE_SUBLET`, which moves the agreement from `SUBMITTED` to `APPROVED` and prices the monthly sublet fee: `monthly_sublet_fee_cents` is fifteen percent of the unit's current base maintenance — the `base_amount_cents` of the unit's charge for the billing month current at approval, or zero if no such charge exists yet — rounded half-up to whole cents. Rejection can arrive two ways with identical effect: the resolution failing, or a `BoardOfficer` rejecting outright, either of which moves a `SUBMITTED` or `APPROVED` agreement to `REJECTED`.

An approved sublet activates itself when the logical clock reaches `sublet_start_date` (and has not yet reached `sublet_end_date`), moving from `APPROVED` to `ACTIVE` and flipping the unit's `occupancy_status` to `SUBLET`. When the clock reaches `sublet_end_date`, the agreement completes — `COMPLETED` — the unit returns to `OWNER_OCCUPIED`, and the unit's `last_sublet_end_date` is set to the agreement's end date, starting the gap clock for any future sublet. A `BoardOfficer` may terminate an `APPROVED` or `ACTIVE` sublet early — as may the system when the owning shareholder's lease is terminated — moving it to `TERMINATED_EARLY`, restoring `OWNER_OCCUPIED`, and stamping the unit's `last_sublet_end_date` with the current logical time rather than the scheduled end.

### 3.8. Renovations under an Alteration Agreement

Renovation requests open as a draft `AlterationAgreement` created by the owning shareholder, describing the `scope_description` of the work, the licensed `contractor_name`, the contractor's liability coverage `contractor_insurance_cents`, the `contractor_bid_cents`, whether the work `involves_wet_over_dry` plumbing, and the permitted work window from `work_window_start` to `work_window_end`. The draft rests in `DRAFT`.

Submission is the owner's act — `X-User-ID` must equal the agreement's `shareholder_id` — and enforces the alteration safety rules. The shareholder must be in `GOOD_STANDING`. The contractor's coverage must be at least 100,000,000 cents (one million dollars); short coverage is rejected with `ERR_ALTERATION_SAFETY_VIOLATION` (HTTP 422). The window must be well ordered, and no other alteration for the same unit in `APPROVED` or `IN_PROGRESS` status may overlap it — overlaps are rejected with `ERR_TEMPORAL_CONFLICT`. A successful submission moves the agreement from `DRAFT` to `SUBMITTED` and computes the refundable `security_deposit_cents`: the greater of five percent of the contractor bid — rounded up to whole cents — and 500,000 cents (five thousand dollars).

Approval requires a passed resolution of kind `APPROVE_ALTERATION`, moving the agreement from `SUBMITTED` to `APPROVED`; a failed resolution moves it to `REJECTED`. Wet-over-dry plumbing work raises the bar: when `involves_wet_over_dry` is true, the approving resolution's `payload_json` must carry an explicit `wet_over_dry_ack` acknowledgment set to true, and without it the approval is rejected with `ERR_ALTERATION_SAFETY_VIOLATION` — board review is mandatory for wet-over-dry regardless of the bid size.

Once approved, the owner starts the work within its window — the logical clock must have reached `work_window_start` and not yet reached `work_window_end` — moving the agreement to `IN_PROGRESS`, and later marks it complete, moving it to `COMPLETED`; completion releases the security deposit back to the shareholder, a refund deliberately kept out of the arrears ledger. An agreement can be abandoned from `APPROVED` or `IN_PROGRESS` by the owner or a `BoardOfficer`, and is abandoned automatically when the owning shareholder's lease is terminated or when the work window closes with the job unfinished. Abandonment before any work began releases the deposit in full; abandonment after work has started holds the deposit for inspection as a business matter rather than recording any transfer.

### 3.9. Meetings, Quorum, and Board Elections

A `BoardOfficer` schedules a `Meeting` by naming its `meeting_kind` — `ANNUAL` or `SPECIAL` — and its `scheduled_at` start. A meeting's state has two orthogonal dimensions: the `preparation_state`, which begins at `PREPARING`, and the `quorum_state`, which begins at `QUORUM_PENDING`; the externally visible `meeting_status`, beginning at `SCHEDULED`, derives from the combination of the two. Sending notice to the shareholders moves `preparation_state` from `PREPARING` to `NOTICE_SENT`, and only then may the officer open the meeting — opening requires both that notice has been sent and that the logical clock has reached `scheduled_at` — moving `meeting_status` from `SCHEDULED` to `IN_SESSION`.

Shareholders participate by casting ballots: a ballot names the `shareholder_id` — ownership-checked against the caller, as on all shareholder-self actions — a `ballot_kind` of `IN_PERSON` or `PROXY`, and a `candidate_user_ids` array of board candidates. At cast time the server derives `shares_voted` from the shareholder's active ledger entries — the sum of shares the shareholder controls at that moment — stamps `cast_at`, and files the ballot in `SUBMITTED` status. A shareholder may re-vote: submitting a new ballot for the same meeting invalidates the shareholder's earlier `SUBMITTED` ballot, moving it to `INVALIDATED`, so at most one live ballot per shareholder per meeting exists. The error code `ERR_DUPLICATE_BALLOT` (HTTP 409) is reserved for hard-duplicate scenarios and is deprecated in favor of this re-vote-replaces semantics. Every ballot submission and every invalidation recomputes the meeting's `shares_represented` and `quorum_state` from scratch — never incrementally.

Quorum is measured in shares. The meeting's `shares_represented` is the sum of `shares_voted` over its ballots in `SUBMITTED` or `COUNTED` status, and the quorum threshold is the smallest whole number of shares that is at least the cooperative's `total_shares` multiplied by `annual_meeting_quorum_percent_bps` out of ten thousand — ceiling division, so any fraction rounds up. When `shares_represented` reaches the threshold the `quorum_state` becomes `QUORUM_MET`; equality counts — representation exactly at the threshold is met, not pending. While the meeting is `SCHEDULED` or `IN_SESSION` below the threshold, quorum remains `QUORUM_PENDING`; a meeting that adjourns without quorum lands in `QUORUM_FAILED`. Any action that requires an established quorum while quorum has not been reached is rejected with `ERR_MEETING_NO_QUORUM` (HTTP 422).

Closing the meeting is a `BoardOfficer` act that takes the number of `open_seats` up for election. If quorum stands at `QUORUM_MET`, the meeting moves from `IN_SESSION` to `COMPLETED`, every `SUBMITTED` ballot becomes `COUNTED`, and the election tally runs. Tallying follows a simplified cumulative rule: each candidate listed on a `COUNTED` ballot is credited with that ballot's full `shares_voted`, so a ballot naming two candidates contributes its whole share weight to each. Candidates are ranked by their total descending; ties break toward the candidate whose highest-share supporting ballot was cast earliest by `cast_at`, and a still-perfect tie breaks toward the lexicographically smaller candidate user id. The top candidates, numbering `open_seats`, take the seats. If quorum is not met, closing instead moves the meeting from `IN_SESSION` to `ADJOURNED_NO_QUORUM`: every `SUBMITTED` ballot becomes `INVALIDATED` and `preparation_state` becomes `ADJOURNED`. The same adjournment happens on its own when the logical clock runs more than twenty-four hours past `scheduled_at` with quorum still pending.

## 4. Endpoint Definitions

All endpoints live under the `/cooperatives` mount. Creation of a new resource returns HTTP 201 with the created resource in `data`; reads, state transitions, and other modifications return HTTP 200 with the affected resource. List endpoints honor the pagination contract of §2.3 and the filter parameters enumerated in §2.10. Authorization is per the role column below and enforced per §2.1 and §2.9.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /cooperatives | Create a new housing cooperative | PlatformAdmin |
| GET | /cooperatives | List cooperatives | PlatformAdmin |
| GET | /cooperatives/{cid} | Get cooperative by id | PlatformAdmin, BoardOfficer, BoardMember, ManagingAgent, Shareholder |
| POST | /cooperatives/{cid}/_clock/set_current_utc | Advance the cooperative's logical clock (startup default 2026-08-01T00:00:00Z; never falls back to wall-clock) | PlatformAdmin |
| POST | /cooperatives/{cid}/units | Create a unit | PlatformAdmin, BoardOfficer |
| GET | /cooperatives/{cid}/units | List units | PlatformAdmin, BoardOfficer, BoardMember, ManagingAgent, Shareholder |
| GET | /cooperatives/{cid}/units/{uid} | Get unit by id | PlatformAdmin, BoardOfficer, BoardMember, ManagingAgent, Shareholder |
| POST | /cooperatives/{cid}/shareholders | Create a shareholder | PlatformAdmin, BoardOfficer, ManagingAgent |
| GET | /cooperatives/{cid}/shareholders | List shareholders | PlatformAdmin, BoardOfficer, BoardMember, ManagingAgent |
| GET | /cooperatives/{cid}/shareholders/{sid} | Get shareholder | PlatformAdmin, BoardOfficer, BoardMember, ManagingAgent, Shareholder |
| POST | /cooperatives/{cid}/share-ledger-entries | Assign shares: link shareholder to unit | PlatformAdmin, BoardOfficer |
| GET | /cooperatives/{cid}/share-ledger-entries | List share ledger entries (filterable) | PlatformAdmin, BoardOfficer, BoardMember, ManagingAgent, Shareholder |
| GET | /cooperatives/{cid}/share-ledger-entries/{eid} | Get one ledger entry | PlatformAdmin, BoardOfficer, BoardMember, ManagingAgent, Shareholder |
| POST | /cooperatives/{cid}/charge-schedules | Create a draft charge schedule (OCC-guarded) | BoardOfficer |
| GET | /cooperatives/{cid}/charge-schedules | List charge schedules | PlatformAdmin, BoardOfficer, BoardMember, ManagingAgent |
| GET | /cooperatives/{cid}/charge-schedules/{csid} | Get charge schedule | PlatformAdmin, BoardOfficer, BoardMember, ManagingAgent, Shareholder |
| GET | /cooperatives/{cid}/maintenance-charges | List charges | PlatformAdmin, BoardOfficer, BoardMember, ManagingAgent, Shareholder |
| GET | /cooperatives/{cid}/maintenance-charges/{mcid} | Get charge | PlatformAdmin, BoardOfficer, BoardMember, ManagingAgent, Shareholder |
| POST | /cooperatives/{cid}/maintenance-charges/{mcid}/payments | Post a payment against a charge | ManagingAgent |
| GET | /cooperatives/{cid}/payments/{pid} | Get payment | PlatformAdmin, BoardOfficer, BoardMember, ManagingAgent |
| POST | /cooperatives/{cid}/payments/{pid}/void | Void a posted payment | ManagingAgent |
| POST | /cooperatives/{cid}/arrears-actions | Issue an arrears action (LATE_NOTICE / DEMAND_LETTER / TERMINATION_NOTICE) | BoardOfficer, ManagingAgent |
| GET | /cooperatives/{cid}/arrears-actions | List arrears actions | PlatformAdmin, BoardOfficer, BoardMember, ManagingAgent |
| GET | /cooperatives/{cid}/arrears-actions/{aid} | Get arrears action | PlatformAdmin, BoardOfficer, BoardMember, ManagingAgent |
| POST | /cooperatives/{cid}/arrears-actions/{aid}/escalate | Manually escalate an arrears action | BoardOfficer |
| POST | /cooperatives/{cid}/arrears-actions/{aid}/withdraw | Withdraw an issued arrears action | BoardOfficer |
| POST | /cooperatives/{cid}/purchase-applications | Create a draft purchase application | Shareholder |
| GET | /cooperatives/{cid}/purchase-applications | List purchase applications | PlatformAdmin, BoardOfficer, BoardMember, ManagingAgent, Shareholder |
| GET | /cooperatives/{cid}/purchase-applications/{paid} | Get purchase application | PlatformAdmin, BoardOfficer, BoardMember, ManagingAgent, Shareholder |
| POST | /cooperatives/{cid}/purchase-applications/{paid}/submit | Submit application (seller only) | Shareholder |
| POST | /cooperatives/{cid}/purchase-applications/{paid}/certify | Managing Agent certifies package completeness | ManagingAgent |
| POST | /cooperatives/{cid}/purchase-applications/{paid}/request-info | Board requests additional info | BoardOfficer |
| POST | /cooperatives/{cid}/purchase-applications/{paid}/submit-info | Seller submits requested info | Shareholder |
| POST | /cooperatives/{cid}/purchase-applications/{paid}/schedule-interview | Board Officer schedules interview | BoardOfficer |
| POST | /cooperatives/{cid}/purchase-applications/{paid}/record-transfer | Record completed share transfer (OCC-guarded on Cooperative) | BoardOfficer |
| POST | /cooperatives/{cid}/purchase-applications/{paid}/withdraw | Seller withdraws application | Shareholder |
| GET | /cooperatives/{cid}/interviews | List interviews | PlatformAdmin, BoardOfficer, BoardMember, ManagingAgent |
| GET | /cooperatives/{cid}/interviews/{iid} | Get interview | PlatformAdmin, BoardOfficer, BoardMember, ManagingAgent |
| POST | /cooperatives/{cid}/interviews/{iid}/complete | Panel member records interview outcome | BoardMember |
| POST | /cooperatives/{cid}/interviews/{iid}/cancel | Cancel interview | BoardOfficer |
| POST | /cooperatives/{cid}/resolutions | Open a board resolution | BoardOfficer |
| GET | /cooperatives/{cid}/resolutions | List resolutions | PlatformAdmin, BoardOfficer, BoardMember, ManagingAgent |
| GET | /cooperatives/{cid}/resolutions/{rid} | Get resolution | PlatformAdmin, BoardOfficer, BoardMember, ManagingAgent |
| POST | /cooperatives/{cid}/resolutions/{rid}/vote | Board member casts a vote | BoardMember |
| POST | /cooperatives/{cid}/resolutions/{rid}/withdraw | Withdraw an open resolution (only before any vote cast) | BoardOfficer |
| GET | /cooperatives/{cid}/resolutions/{rid}/votes | List votes on a resolution | PlatformAdmin, BoardOfficer, BoardMember, ManagingAgent |
| POST | /cooperatives/{cid}/sublet-agreements | Create sublet draft | Shareholder |
| GET | /cooperatives/{cid}/sublet-agreements | List sublet agreements | PlatformAdmin, BoardOfficer, BoardMember, ManagingAgent, Shareholder |
| GET | /cooperatives/{cid}/sublet-agreements/{sid} | Get sublet | PlatformAdmin, BoardOfficer, BoardMember, ManagingAgent, Shareholder |
| POST | /cooperatives/{cid}/sublet-agreements/{sid}/submit | Submit sublet for board approval | Shareholder |
| POST | /cooperatives/{cid}/sublet-agreements/{sid}/reject | Board rejects sublet | BoardOfficer |
| POST | /cooperatives/{cid}/sublet-agreements/{sid}/terminate-early | Board terminates an approved/active sublet early | BoardOfficer |
| POST | /cooperatives/{cid}/alteration-agreements | Create alteration draft | Shareholder |
| GET | /cooperatives/{cid}/alteration-agreements | List alterations | PlatformAdmin, BoardOfficer, BoardMember, ManagingAgent, Shareholder |
| GET | /cooperatives/{cid}/alteration-agreements/{aid} | Get alteration | PlatformAdmin, BoardOfficer, BoardMember, ManagingAgent, Shareholder |
| POST | /cooperatives/{cid}/alteration-agreements/{aid}/submit | Submit alteration for board approval | Shareholder |
| POST | /cooperatives/{cid}/alteration-agreements/{aid}/start-work | Begin work within window | Shareholder |
| POST | /cooperatives/{cid}/alteration-agreements/{aid}/complete | Mark work complete | Shareholder |
| POST | /cooperatives/{cid}/alteration-agreements/{aid}/abandon | Abandon alteration | Shareholder, BoardOfficer |
| POST | /cooperatives/{cid}/meetings | Schedule a meeting | BoardOfficer |
| GET | /cooperatives/{cid}/meetings | List meetings | PlatformAdmin, BoardOfficer, BoardMember, ManagingAgent, Shareholder |
| GET | /cooperatives/{cid}/meetings/{mid} | Get meeting | PlatformAdmin, BoardOfficer, BoardMember, ManagingAgent, Shareholder |
| POST | /cooperatives/{cid}/meetings/{mid}/send-notice | Send meeting notice to shareholders | BoardOfficer |
| POST | /cooperatives/{cid}/meetings/{mid}/open | Open meeting (must have sent notice first) | BoardOfficer |
| POST | /cooperatives/{cid}/meetings/{mid}/close | Close meeting; tally election if applicable | BoardOfficer |
| POST | /cooperatives/{cid}/meetings/{mid}/ballots | Cast a ballot | Shareholder |
| GET | /cooperatives/{cid}/meetings/{mid}/ballots | List ballots for a meeting | PlatformAdmin, BoardOfficer, BoardMember, ManagingAgent |
| GET | /cooperatives/{cid}/meetings/{mid}/ballots/{bid} | Get ballot | PlatformAdmin, BoardOfficer, BoardMember, ManagingAgent |
| GET | /cooperatives/units | List Unit records across cooperatives, filterable by foreign keys (flat alias) | PlatformAdmin, BoardOfficer, BoardMember, ManagingAgent, Shareholder |
| GET | /cooperatives/units/{uid} | Get Unit by id (flat alias; ids are globally unique) | PlatformAdmin, BoardOfficer, BoardMember, ManagingAgent, Shareholder |
| GET | /cooperatives/shareholders | List Shareholder records across cooperatives, filterable by foreign keys (flat alias) | PlatformAdmin, BoardOfficer, BoardMember, ManagingAgent |
| GET | /cooperatives/shareholders/{sid} | Get Shareholder by id (flat alias; ids are globally unique) | PlatformAdmin, BoardOfficer, BoardMember, ManagingAgent, Shareholder |
| GET | /cooperatives/share-ledger-entries | List ShareLedgerEntry records across cooperatives, filterable by foreign keys (flat alias) | PlatformAdmin, BoardOfficer, BoardMember, ManagingAgent, Shareholder |
| GET | /cooperatives/share-ledger-entries/{eid} | Get ShareLedgerEntry by id (flat alias; ids are globally unique) | PlatformAdmin, BoardOfficer, BoardMember, ManagingAgent, Shareholder |
| GET | /cooperatives/charge-schedules | List ChargeSchedule records across cooperatives, filterable by foreign keys (flat alias) | PlatformAdmin, BoardOfficer, BoardMember, ManagingAgent |
| GET | /cooperatives/charge-schedules/{csid} | Get ChargeSchedule by id (flat alias; ids are globally unique) | PlatformAdmin, BoardOfficer, BoardMember, ManagingAgent, Shareholder |
| GET | /cooperatives/maintenance-charges | List MaintenanceCharge records across cooperatives, filterable by foreign keys (flat alias) | PlatformAdmin, BoardOfficer, BoardMember, ManagingAgent, Shareholder |
| GET | /cooperatives/maintenance-charges/{mcid} | Get MaintenanceCharge by id (flat alias; ids are globally unique) | PlatformAdmin, BoardOfficer, BoardMember, ManagingAgent, Shareholder |
| GET | /cooperatives/payments | List Payment records across cooperatives, filterable by foreign keys (flat alias) | PlatformAdmin, BoardOfficer, BoardMember, ManagingAgent |
| GET | /cooperatives/payments/{pid} | Get Payment by id (flat alias; ids are globally unique) | PlatformAdmin, BoardOfficer, BoardMember, ManagingAgent |
| GET | /cooperatives/arrears-actions | List ArrearsAction records across cooperatives, filterable by foreign keys (flat alias) | PlatformAdmin, BoardOfficer, BoardMember, ManagingAgent |
| GET | /cooperatives/arrears-actions/{aid} | Get ArrearsAction by id (flat alias; ids are globally unique) | PlatformAdmin, BoardOfficer, BoardMember, ManagingAgent |
| GET | /cooperatives/purchase-applications | List PurchaseApplication records across cooperatives, filterable by foreign keys (flat alias) | PlatformAdmin, BoardOfficer, BoardMember, ManagingAgent, Shareholder |
| GET | /cooperatives/purchase-applications/{paid} | Get PurchaseApplication by id (flat alias; ids are globally unique) | PlatformAdmin, BoardOfficer, BoardMember, ManagingAgent, Shareholder |
| GET | /cooperatives/interviews | List Interview records across cooperatives, filterable by foreign keys (flat alias) | PlatformAdmin, BoardOfficer, BoardMember, ManagingAgent |
| GET | /cooperatives/interviews/{iid} | Get Interview by id (flat alias; ids are globally unique) | PlatformAdmin, BoardOfficer, BoardMember, ManagingAgent |
| GET | /cooperatives/resolutions | List Resolution records across cooperatives, filterable by foreign keys (flat alias) | PlatformAdmin, BoardOfficer, BoardMember, ManagingAgent |
| GET | /cooperatives/resolutions/{rid} | Get Resolution by id (flat alias; ids are globally unique) | PlatformAdmin, BoardOfficer, BoardMember, ManagingAgent |
| GET | /cooperatives/resolution-votes | List ResolutionVote records across cooperatives, filterable by foreign keys (flat alias) | PlatformAdmin, BoardOfficer, BoardMember, ManagingAgent |
| GET | /cooperatives/resolution-votes/{vid} | Get ResolutionVote by id (flat alias; ids are globally unique) | PlatformAdmin, BoardOfficer, BoardMember, ManagingAgent |
| GET | /cooperatives/sublet-agreements | List SubletAgreement records across cooperatives, filterable by foreign keys (flat alias) | PlatformAdmin, BoardOfficer, BoardMember, ManagingAgent, Shareholder |
| GET | /cooperatives/sublet-agreements/{sid} | Get SubletAgreement by id (flat alias; ids are globally unique) | PlatformAdmin, BoardOfficer, BoardMember, ManagingAgent, Shareholder |
| GET | /cooperatives/alteration-agreements | List AlterationAgreement records across cooperatives, filterable by foreign keys (flat alias) | PlatformAdmin, BoardOfficer, BoardMember, ManagingAgent, Shareholder |
| GET | /cooperatives/alteration-agreements/{aid} | Get AlterationAgreement by id (flat alias; ids are globally unique) | PlatformAdmin, BoardOfficer, BoardMember, ManagingAgent, Shareholder |
| GET | /cooperatives/meetings | List Meeting records across cooperatives, filterable by foreign keys (flat alias) | PlatformAdmin, BoardOfficer, BoardMember, ManagingAgent, Shareholder |
| GET | /cooperatives/meetings/{mid} | Get Meeting by id (flat alias; ids are globally unique) | PlatformAdmin, BoardOfficer, BoardMember, ManagingAgent, Shareholder |
| GET | /cooperatives/ballots | List Ballot records across cooperatives, filterable by foreign keys (flat alias) | PlatformAdmin, BoardOfficer, BoardMember, ManagingAgent |
| GET | /cooperatives/ballots/{bid} | Get Ballot by id (flat alias; ids are globally unique) | PlatformAdmin, BoardOfficer, BoardMember, ManagingAgent |

## 5. Error Code Catalogue

Trigger conditions for each error live in the narrative of §2 and §3; this table is only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_CONTEXT_HEADER | 400 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_ENUM | 400 |
| ERR_UNAUTHORIZED_ROLE | 403 |
| ERR_NOT_RESOURCE_OWNER | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_ALREADY_TERMINAL | 409 |
| ERR_DUPLICATE_BALLOT | 409 |
| ERR_RESOLUTION_ALREADY_VOTED | 409 |
| ERR_VOTER_ALREADY_CAST | 409 |
| ERR_STALE_COOP_VERSION | 412 |
| ERR_ALTERATION_SAFETY_VIOLATION | 422 |
| ERR_CROSS_ENTITY_VIOLATION | 422 |
| ERR_TEMPORAL_CONFLICT | 422 |
| ERR_SUBLET_POLICY_VIOLATION | 422 |
| ERR_BUSINESS_CONSTRAINT | 422 |
| ERR_FISCAL_THRESHOLD_VIOLATION | 422 |
| ERR_SHARES_MISMATCH | 422 |
| ERR_MEETING_NO_QUORUM | 422 |
| ERR_PAYMENT_EXCEEDS_OUTSTANDING | 422 |
| ERR_SEPARATION_OF_DUTIES | 422 |
